"""The three pages of the first-run wizard, one class each.

They live apart from :mod:`qtrequestory.ui.wizard` for the usual reason a form
splits from its dialog: the wizard owns the *flow* (order, buttons, what Fine
does) and each page owns one question and its validation. A page never saves
anything and never talks to the scheduler — it only answers what the user chose,
through the small accessors at the end of each class, which is what makes the
finish step in ``wizard.py`` short enough to read in one screen.

Every page holds the ``CoreServices`` bundle rather than a core module, and
asks its questions in ``initializePage`` rather than in ``__init__``: the
services are queried when the page is *shown*, so a test (and the [Indietro]
button) can change the answer and see the page follow.
"""
from __future__ import annotations

import dataclasses
import logging
import tempfile
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWizardPage,
)

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import Config, CoreServices, Environment
from qtrequestory.ui.env_table import EnvTable
from qtrequestory.ui.workers import Job, JobRunner

__all__ = ["AutomationPage", "EnvironmentsPage", "LogFolderPage"]

log = logging.getLogger(__name__)

#: Name of the reachability job in the shared runner. Not ``sync``/``index``
#: (those are exclusive), so a second click simply supersedes the first check.
REACHABILITY_JOB = "wizard-reachability"


def _muted(text: str = "") -> QLabel:
    """A wrapping, non-shouting label — hints, notices and inline errors."""
    label = QLabel(text)
    label.setWordWrap(True)
    return label


# --------------------------------------------------- 1. cartella dei log ---

class LogFolderPage(QWizardPage):
    """Where the mirror goes. Valid means: we can actually write there."""

    def __init__(self, services: CoreServices, parent=None) -> None:
        super().__init__(parent)
        self._services = services
        self.setTitle(strings.WIZARD_P1_TITLE)
        self.setSubTitle(strings.WIZARD_P1_SUBTITLE)

        self.path_edit = QLineEdit()
        self.browse_button = QPushButton(strings.BTN_BROWSE)
        self.browse_button.clicked.connect(self.browse)
        self.info_label = _muted()
        self.error_label = _muted()

        row = QHBoxLayout()
        row.addWidget(QLabel(strings.WIZARD_P1_LABEL))
        row.addWidget(self.path_edit, 1)
        row.addWidget(self.browse_button)
        layout = QVBoxLayout(self)
        layout.addLayout(row)
        layout.addWidget(self.info_label)
        layout.addWidget(self.error_label)
        layout.addStretch(1)

        self.path_edit.textChanged.connect(self._on_text_changed)
        # Counting the files under a folder walks it, so it happens when the
        # user stops typing (or picks a folder), never on every keystroke.
        self.path_edit.editingFinished.connect(self._refresh_info)

    def initializePage(self) -> None:
        if not self.path_edit.text():
            self.set_path(self._services.config.load().mirror_root)

    # -- what the wizard asks ----------------------------------------------

    def isComplete(self) -> bool:
        """[Avanti] stays disabled while the field is empty; the real check
        happens in :meth:`validatePage`, which can show *why* it failed."""
        return bool(self.path_edit.text().strip())

    def validatePage(self) -> bool:
        folder = self.folder()
        if folder is None:
            self.error_label.setText(strings.WIZARD_P1_ERROR_EMPTY)
            return False
        if not _is_writable(folder):
            self.error_label.setText(strings.WIZARD_P1_ERROR_NOT_WRITABLE.format(path=folder))
            return False
        self.error_label.setText("")
        self._refresh_info()
        return True

    # -- the answer ---------------------------------------------------------

    def folder(self) -> Path | None:
        text = self.path_edit.text().strip()
        # Kept exactly as typed or picked: the folder shown in the field is the
        # one written into config.json, with no silent resolution behind it.
        return Path(text) if text else None

    def set_path(self, path: Path | str) -> None:
        self.path_edit.setText(str(path))
        self._refresh_info()

    def browse(self) -> None:
        current = self.path_edit.text().strip()
        chosen = QFileDialog.getExistingDirectory(
            self, strings.WIZARD_P1_BROWSE_CAPTION, current
        )
        if chosen:
            self.set_path(Path(chosen))

    # -- internals ----------------------------------------------------------

    def _on_text_changed(self, _text: str) -> None:
        self.error_label.setText("")
        self.completeChanged.emit()

    def _refresh_info(self) -> None:
        """Refresh the WIZARD_P1_EXISTING_FILES line.

        The folder may already hold a mirror somebody copied over by hand: those
        files must be indexed, not downloaded again, and saying so here is what
        stops the user from picking an empty folder "to be safe".
        """
        folder = self.folder()
        n = 0
        if folder is not None:
            try:
                n = self._services.index.count_local_files(folder)
            except OSError as exc:  # an unreadable folder is not worth a dialog
                log.debug("conteggio dei file locali non riuscito per %s: %s", folder, exc)
        self.info_label.setText(strings.WIZARD_P1_EXISTING_FILES.format(n=n) if n else "")


def _is_writable(folder: Path) -> bool:
    """Create the folder and a throwaway file in it.

    Only a real write tells the truth on Windows: a path can be listable and
    still refuse new files (a read-only share, a redirected Documents folder),
    and ``os.access`` does not know that.
    """
    try:
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=folder, prefix=".qtrequestory-", suffix=".tmp"):
            pass
    except OSError as exc:
        log.info("cartella dei log non utilizzabile (%s): %s", folder, exc)
        return False
    return True


# ------------------------------------------------------------ 2. ambienti ---

class EnvironmentsPage(QWizardPage):
    """The [abilitato | nome | URL] table, filled from the sidecar when there
    is one. Zero environments is allowed — the user can add them later — so the
    page warns instead of blocking."""

    def __init__(self, services: CoreServices, runner: JobRunner, parent=None) -> None:
        super().__init__(parent)
        self._services = services
        self._runner = runner
        self._prefilled = False
        self.setTitle(strings.WIZARD_P2_TITLE)
        self.setSubTitle(strings.WIZARD_P2_SUBTITLE)

        self.table = EnvTable()
        self.hint_label = _muted(strings.WIZARD_P2_HINT)
        self.error_label = _muted()
        self.reachability_label = _muted()

        self.add_button = QPushButton(strings.BTN_ADD)
        self.add_button.clicked.connect(self.add_environment)
        self.remove_button = QPushButton(strings.BTN_REMOVE)
        self.remove_button.clicked.connect(self.remove_selected)
        self.import_button = QPushButton(strings.BTN_IMPORT_FILE)
        self.import_button.clicked.connect(self.import_environments)

        buttons = QHBoxLayout()
        for button in (self.add_button, self.remove_button, self.import_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        self.check_button = QPushButton(strings.WIZARD_P2_BTN_CHECK)
        self.check_button.clicked.connect(self.check_reachability)
        buttons.addWidget(self.check_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.hint_label)
        layout.addWidget(self.table, 1)
        layout.addLayout(buttons)
        layout.addWidget(self.reachability_label)
        layout.addWidget(_muted(strings.WIZARD_P2_CHECK_NOTE))
        layout.addWidget(self.error_label)

    def initializePage(self) -> None:
        """Pre-fill from the ``environments.json`` next to the executable.

        A sidecar that cannot be parsed is *not* an error the user must deal
        with here: the page falls back to the hint, exactly as if there were no
        file, and the details go to the log.

        It happens once: [Indietro] then [Avanti] must not undo the edits the
        user made in between — including emptying the table on purpose.
        """
        if self._prefilled:
            return
        self._prefilled = True
        sidecar = self._services.config.find_sidecar_environments()
        if sidecar is None:
            return
        try:
            self.table.set_environments(self._services.config.import_environments_file(sidecar))
        except ValueError as exc:
            log.warning("environments.json accanto all'eseguibile non leggibile: %s", exc)
            return
        self.hint_label.setText(strings.WIZARD_P2_SIDECAR_LOADED.format(path=sidecar))

    # -- what the wizard asks ----------------------------------------------

    def validatePage(self) -> bool:
        """``config.validate`` on the configuration this page would produce.

        Validating a whole ``Config`` rather than the rows by hand is what keeps
        the wizard and Impostazioni from drifting apart: there is one set of
        rules and it lives in the core.
        """
        errors = self._services.config.validate(self._candidate_config())
        if errors:
            self.error_label.setText("\n".join(errors))
            return False
        self.error_label.setText(
            "" if any(e.enabled for e in self.environments()) else strings.WIZARD_P2_NO_ENVIRONMENTS
        )
        return True

    # -- the answer ---------------------------------------------------------

    def environments(self) -> list[Environment]:
        return self.table.environments()

    # -- buttons ------------------------------------------------------------

    def add_environment(self) -> None:
        self.table.add_row()

    def remove_selected(self) -> None:
        self.table.remove_selected()

    def import_environments(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, strings.ENV_IMPORT_CAPTION, "", strings.ENV_IMPORT_FILTER
        )
        if not path:
            return
        try:
            self.table.import_from_file(Path(path), self._services.config.import_environments_file)
        except ValueError as exc:
            QMessageBox.warning(
                self,
                strings.ENV_IMPORT_ERROR_TITLE,
                strings.ENV_IMPORT_ERROR.format(error=exc),
            )
            return
        self.hint_label.setText(strings.WIZARD_P2_SIDECAR_LOADED.format(path=path))

    def check_reachability(self) -> Job | None:
        """One short HTTP GET per environment, in the shared runner.

        The names are read here, on the GUI thread, and only they travel to the
        worker: the table is a widget and a worker never touches one.
        """
        names = [e.name for e in self.environments() if e.name]
        if not names:
            self.reachability_label.setText(strings.WIZARD_P2_CHECK_EMPTY)
            return None
        job = self._runner.submit(
            REACHABILITY_JOB, _probe_reachability, self._services.sync.check_reachable, names
        )
        if job is None:  # the application is shutting down
            return None
        self.reachability_label.setText(strings.WIZARD_P2_CHECK_RUNNING)
        job.signals.result.connect(self._show_reachability)
        return job

    # -- internals ----------------------------------------------------------

    def _show_reachability(self, outcome: dict) -> None:
        self.reachability_label.setText(
            strings.WIZARD_P2_CHECK_SEPARATOR.join(
                strings.WIZARD_P2_CHECK_RESULT.format(
                    env=name,
                    state=(strings.WIZARD_P2_REACHABLE if reachable
                           else strings.WIZARD_P2_UNREACHABLE),
                )
                for name, reachable in outcome.items()
            )
        )

    def _candidate_config(self) -> Config:
        return dataclasses.replace(
            self._services.config.load(), environments=self.environments()
        )


def _probe_reachability(check, names: list[str], *, cancel) -> dict[str, bool]:
    """Runs on a pool thread: plain data in, plain data out, no widgets.

    ``cancel`` is injected by the worker and checked between environments. Each
    probe is a blocking GET with a several-second timeout, so without this a
    wizard closed mid-check would keep the pool busy for one timeout *per*
    environment and outlive ``JobRunner.shutdown``'s wait.
    """
    outcome: dict[str, bool] = {}
    for name in names:
        if cancel.is_set():
            break
        outcome[name] = check(name)
    return outcome


# --------------------------------------------------------- 3. automazione ---

class AutomationPage(QWizardPage):
    """The scheduled task, the editor, and what happens right after [Fine]."""

    def __init__(self, services: CoreServices, parent=None) -> None:
        super().__init__(parent)
        self._services = services
        self._legacy = False
        self.setTitle(strings.WIZARD_P3_TITLE)
        self.setSubTitle(strings.WIZARD_P3_SUBTITLE)

        self.autosync_check = QCheckBox(strings.WIZARD_P3_AUTOSYNC)
        self.autosync_check.setChecked(True)
        self.legacy_label = _muted()
        self.editor_edit = QLineEdit()
        self.editor_hint = _muted()
        self.start_sync_check = QCheckBox(strings.WIZARD_P3_START_SYNC)
        self.start_sync_check.setChecked(True)
        self.browse_button = QPushButton(strings.BTN_BROWSE)
        self.browse_button.clicked.connect(self.browse_editor)

        editor_row = QHBoxLayout()
        editor_row.addWidget(QLabel(strings.WIZARD_P3_EDITOR_LABEL))
        editor_row.addWidget(self.editor_edit, 1)
        editor_row.addWidget(self.browse_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.autosync_check)
        layout.addWidget(_muted(strings.WIZARD_P3_AUTOSYNC_NOTE))
        layout.addWidget(self.legacy_label)
        layout.addSpacing(12)
        layout.addLayout(editor_row)
        layout.addWidget(self.editor_hint)
        layout.addSpacing(12)
        layout.addWidget(self.start_sync_check)
        layout.addStretch(1)

    def initializePage(self) -> None:
        self._legacy = self._services.scheduler.detect_legacy_task()
        self.legacy_label.setText(strings.WIZARD_P3_LEGACY_TASK if self._legacy else "")
        if not self.editor_edit.text():
            detected = self._services.config.detect_editor()
            self.editor_edit.setText(str(detected) if detected is not None else "")
        self.editor_hint.setText(
            "" if self.editor_edit.text() else strings.WIZARD_P3_EDITOR_NOT_FOUND
        )

    # -- the answers --------------------------------------------------------

    def autosync_enabled(self) -> bool:
        return self.autosync_check.isChecked()

    def start_sync_requested(self) -> bool:
        return self.start_sync_check.isChecked()

    def editor_path(self) -> Path | None:
        text = self.editor_edit.text().strip()
        return Path(text) if text else None

    def has_legacy_task(self) -> bool:
        """What ``detect_legacy_task`` answered when the page was shown."""
        return self._legacy

    # -- buttons ------------------------------------------------------------

    def browse_editor(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self,
            strings.WIZARD_P3_EDITOR_CAPTION,
            self.editor_edit.text().strip(),
            strings.WIZARD_P3_EDITOR_FILTER,
        )
        if path:
            self.editor_edit.setText(str(Path(path)))
            self.editor_hint.setText("")
