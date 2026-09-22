"""The first-run wizard: three questions, one configuration, one result.

``run_gui`` shows this before the main window when ``config.is_first_run()``,
and Impostazioni re-runs it on demand. It is the only place in the application
that writes a configuration where none existed, so the whole finish step lives
in one method (:meth:`FirstRunWizard.finish`) that reads exactly the three
pages of ``wizard_pages`` and does exactly what DESIGN-ui §"First-run wizard"
lists, in that order:

1. build the ``Config`` from the pages and ``config.save`` it — first, so a
   failure of anything below still leaves the user configured;
2. if automation was asked for, register the scheduled task, and only once ours
   is registered remove the legacy ``NginxLogSync`` one it replaces;
3. hand the caller a :class:`WizardResult` saying what to do next.

Neither step 2 nor step 3 can stop the wizard from closing: a scheduled task
that could not be registered is reported and forgotten (the Sincronizzazione
page can register it later), and the configuration is already on disk.
"""
from __future__ import annotations

import dataclasses
import logging

from PySide6.QtWidgets import QDialog, QMessageBox, QWidget, QWizard

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import Config, CoreServices
from qtrequestory.ui.wizard_pages import AutomationPage, EnvironmentsPage, LogFolderPage
from qtrequestory.ui.workers import JobRunner

__all__ = ["FirstRunWizard", "WizardResult", "run_first_run_wizard"]

log = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class WizardResult:
    """What the caller needs to know once the wizard closed with [Fine].

    ``autosync`` is the *effective* state, not the checkbox: when registering
    the scheduled task failed it is ``False``, because the shell uses it to say
    whether automation is on, and saying yes about a task that does not exist
    would be a lie the user only discovers the next morning.
    """

    config: Config
    start_sync: bool
    autosync: bool


class FirstRunWizard(QWizard):
    """The three pages, the Italian buttons, and what [Fine] does."""

    def __init__(self, services: CoreServices, runner: JobRunner,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._services = services
        self._result: WizardResult | None = None

        self.setWindowTitle(strings.WIZARD_TITLE)
        # ModernStyle rather than the platform default: AeroStyle needs DWM
        # composition, which is absent under a remote session and offscreen.
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)

        self.folder_page = LogFolderPage(services)
        self.environments_page = EnvironmentsPage(services, runner)
        self.automation_page = AutomationPage(services)
        for page in (self.folder_page, self.environments_page, self.automation_page):
            self.addPage(page)

        # Qt's own button texts follow the Qt translation, which a portable
        # build does not ship; the UI is Italian, so they are set here.
        for role, text in (
            (QWizard.WizardButton.NextButton, strings.WIZARD_BTN_NEXT),
            (QWizard.WizardButton.BackButton, strings.WIZARD_BTN_BACK),
            (QWizard.WizardButton.FinishButton, strings.WIZARD_BTN_FINISH),
            (QWizard.WizardButton.CancelButton, strings.BTN_CANCEL),
        ):
            self.setButtonText(role, text)

    # -- result -------------------------------------------------------------

    def wizard_result(self) -> WizardResult | None:
        """The result of the last [Fine]; ``None`` while the user is still in
        the wizard or after [Annulla]."""
        return self._result

    def accept(self) -> None:
        """[Fine]: do the work first, close afterwards.

        Qt calls this only after ``validatePage`` accepted the last page, so
        everything :meth:`finish` reads has already been validated.
        """
        self._result = self.finish()
        super().accept()

    def finish(self) -> WizardResult:
        """Save the configuration and set the automation up. See the module docstring."""
        base = self._services.config.load()
        folder = self.folder_page.folder()
        cfg = dataclasses.replace(
            base,
            # The page cannot be left empty, but ``mirror_root`` is not
            # optional: a None here would be written into config.json.
            mirror_root=folder if folder is not None else base.mirror_root,
            environments=self.environments_page.environments(),
            editor_path=self.automation_page.editor_path(),
        )
        self._services.config.save(cfg)
        autosync = self.automation_page.autosync_enabled() and self._enable_automation()
        return WizardResult(
            config=cfg,
            start_sync=self.automation_page.start_sync_requested(),
            autosync=autosync,
        )

    # -- internals ----------------------------------------------------------

    def _enable_automation(self) -> bool:
        """Register the task; ``False`` (and one dialog) when it did not work.

        Broad ``except``: this runs while the wizard is closing, and a scheduler
        that misbehaves in a way ``SchedulerError`` does not cover must not take
        the freshly saved configuration down with it.
        """
        try:
            self._services.scheduler.register()
        except Exception as exc:  # noqa: BLE001 - reported, never fatal
            log.warning("registrazione dell'attività pianificata non riuscita: %s", exc)
            QMessageBox.information(
                self,
                strings.WIZARD_SCHEDULER_FAILED_TITLE,
                strings.WIZARD_SCHEDULER_FAILED.format(error=exc),
            )
            return False
        if self.automation_page.has_legacy_task():
            try:
                self._services.scheduler.remove_legacy_task()
            except Exception as exc:  # noqa: BLE001 - ours is registered; this is tidying
                log.warning("rimozione del vecchio task NginxLogSync non riuscita: %s", exc)
        return True


def run_first_run_wizard(services: CoreServices, runner: JobRunner,
                         parent: QWidget | None = None) -> WizardResult | None:
    """Show the wizard modally; ``None`` when the user cancelled.

    This is the entry point ``ui/app.py`` imports lazily — its name and
    signature are the contract, not the class above.
    """
    wizard = FirstRunWizard(services, runner, parent)
    try:
        if wizard.exec() != int(QDialog.DialogCode.Accepted):
            log.info("configurazione iniziale annullata dall'utente")
            return None
        return wizard.wizard_result()
    finally:
        # No parent in the usual case, so nothing else would ever free it.
        wizard.deleteLater()
