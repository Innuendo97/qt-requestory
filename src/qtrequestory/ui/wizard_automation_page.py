"""Page 3 of the first-run wizard: the scheduled task and the old one."""
from __future__ import annotations

import logging

from PySide6.QtWidgets import QCheckBox

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import CoreServices
from qtrequestory.ui.pages.schedule_text import schedule_sentence
from qtrequestory.ui.wizard_step import WizardStepPage, muted
from qtrequestory.ui.workers import Job, JobRunner

__all__ = ["TASK_STATUS_JOB", "AutomationPage"]

log = logging.getLogger(__name__)

#: Page 3 asks whether the scheduled task exists (a ``schtasks`` subprocess).
TASK_STATUS_JOB = "wizard-task-status"


class AutomationPage(WizardStepPage):
    """The scheduled task, the legacy one, and what happens right after [Fine].

    On a first run the automation checkbox starts ticked (the recommended
    setup). On a *rerun* ("Riesegui configurazione iniziale") it starts from
    what is really there — ``scheduler.status().registered`` — so the wizard
    does not quietly re-enable a task the user had turned off, and unticking a
    task that *is* registered means removing it (see :meth:`unregister_requested`).
    That answer is a ``schtasks`` call, so it runs in a worker (``runner``) and
    the checkbox waits disabled, saying so, until it arrives; asked once per
    wizard.

    The old ``NginxLogSync`` task is only ever removed on request: when it is
    detected an **unticked** checkbox offers it, because the two tasks coexist
    safely and the old one is the user's proven fallback.
    """

    def __init__(self, services: CoreServices, runner: JobRunner | None = None,
                 parent=None) -> None:
        super().__init__(3, strings.WIZARD_P3_TITLE, strings.WIZARD_P3_SUBTITLE, parent)
        self._services = services
        self._runner = runner
        self._task_job: Job | None = None
        #: ``registered`` from the scheduler on a rerun; None = not (yet) known.
        self._registered: bool | None = None
        self._legacy = False

        self.autosync_check = QCheckBox(strings.WIZARD_P3_AUTOSYNC)
        self.autosync_check.setChecked(True)
        self.autosync_note = muted()
        self.autosync_checking = muted(strings.WIZARD_P3_AUTOSYNC_CHECKING)
        self.autosync_checking.setVisible(False)
        self.refresh_schedule_note()
        self.legacy_check = QCheckBox(strings.WIZARD_P3_LEGACY_REMOVE)
        self.legacy_check.setChecked(False)
        self.legacy_note = muted(strings.WIZARD_P3_LEGACY_NOTE)
        self.legacy_check.setVisible(False)
        self.legacy_note.setVisible(False)
        self.start_sync_check = QCheckBox(strings.WIZARD_P3_START_SYNC)
        self.start_sync_check.setChecked(True)
        self.start_sync_note = muted(strings.WIZARD_P3_FIRST_SYNC_NOTE)

        self.body.addWidget(self.autosync_check)
        self.body.addWidget(self.autosync_checking)
        self.body.addWidget(self.autosync_note)
        self.body.addSpacing(theme.SPACE[2])
        self.body.addWidget(self.legacy_check)
        self.body.addWidget(self.legacy_note)
        self.body.addSpacing(theme.SPACE[2])
        self.body.addWidget(self.start_sync_check)
        self.body.addWidget(self.start_sync_note)
        self.body.addStretch(1)

    def initializePage(self) -> None:
        self._ask_task_status()
        self._legacy = self._services.scheduler.detect_legacy_task()
        self.legacy_check.setVisible(self._legacy)
        self.legacy_note.setVisible(self._legacy)
        self.refresh_schedule_note()

    def refresh_schedule_note(self) -> None:
        """Say which schedule the checkbox would actually register.

        ``wizard.py`` registers whatever ``config.json`` holds, and Impostazioni
        can have changed it long ago — "Riesegui configurazione iniziale" must
        not offer a 09:00 task to someone who moved the start to 07:30. Same
        sentence as Impostazioni and the Sincronizzazione page.
        """
        self.autosync_note.setText(
            strings.WIZARD_P3_AUTOSYNC_NOTE.format(
                schedule=schedule_sentence(self._services.config.load().schedule)
            )
        )

    # -- the answers --------------------------------------------------------

    def autosync_enabled(self) -> bool:
        """False while the task is still being checked: [Fine] pressed before
        the answer must not register a task the user may have turned off."""
        return self.autosync_check.isChecked() and not self._checking()

    def unregister_requested(self) -> bool:
        """A rerun found our task registered and the user unticked the box.

        Only a *known* registered task: before the answer (or on a first run)
        nothing says there is anything to remove.
        """
        return (self._registered is True and not self._checking()
                and not self.autosync_check.isChecked())

    def remove_legacy_requested(self) -> bool:
        """The old task exists and the user explicitly asked to remove it."""
        return self._legacy and self.legacy_check.isChecked()

    def start_sync_requested(self) -> bool:
        return self.start_sync_check.isChecked()

    def has_legacy_task(self) -> bool:
        """What ``detect_legacy_task`` answered when the page was shown."""
        return self._legacy

    def cancel_jobs(self) -> None:
        if self._task_job is not None:
            self._task_job.cancel()

    # -- internals ----------------------------------------------------------

    def _checking(self) -> bool:
        return self.autosync_checking.isVisibleTo(self)

    def _ask_task_status(self) -> None:
        """Rerun only, once: pre-check the box from the scheduled task."""
        if (self._task_job is not None or self._runner is None
                or self._services.config.is_first_run()):
            return
        job = self._runner.submit(TASK_STATUS_JOB, self._services.scheduler.status)
        if job is None:  # the application is closing: keep the default
            return
        self._task_job = job
        self._set_checking(True)
        # Bound methods, not lambdas: Qt drops the connection if the wizard is
        # closed before schtasks answers.
        job.signals.result.connect(self._on_task_status)
        job.signals.finished.connect(self._on_task_checked)

    def _on_task_status(self, task) -> None:
        self._registered = bool(task.registered)
        self.autosync_check.setChecked(self._registered)

    def _on_task_checked(self) -> None:
        self._set_checking(False)

    def _set_checking(self, checking: bool) -> None:
        self.autosync_check.setEnabled(not checking)
        self.autosync_checking.setVisible(checking)
