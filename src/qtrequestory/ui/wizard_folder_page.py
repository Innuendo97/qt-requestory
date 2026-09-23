"""Page 1 of the first-run wizard: where the mirror goes, and the editor.

The editor (Notepad++) is asked here rather than on Automazione: both are
"where things live on this PC", and neither has anything to do with the
scheduled task.
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QGridLayout, QLabel, QLineEdit, QPushButton

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import CoreServices
from qtrequestory.ui.wizard_step import WizardStepPage, error_line, muted
from qtrequestory.ui.workers import Job, JobRunner

__all__ = ["COUNT_JOB", "LogFolderPage"]

log = logging.getLogger(__name__)

#: ``count_local_files`` walks the whole folder: a worker, superseded per folder.
COUNT_JOB = "wizard-count-files"


class LogFolderPage(WizardStepPage):
    """Where the mirror goes (valid means: we can actually write there), plus
    the optional Notepad++ path."""

    def __init__(self, services: CoreServices, runner: JobRunner | None = None,
                 parent=None) -> None:
        super().__init__(1, strings.WIZARD_P1_TITLE, strings.WIZARD_P1_SUBTITLE, parent)
        self._services = services
        self._runner = runner
        self._count_job: Job | None = None
        self._counting = False

        self.intro_label = QLabel(f"{strings.WIZARD_P1_INTRO}\n{strings.WIZARD_P1_ADVICE}")
        self.intro_label.setWordWrap(True)
        self.path_edit = QLineEdit()
        self.browse_button = QPushButton(strings.BTN_BROWSE)
        self.browse_button.clicked.connect(self.browse)
        self.info_label = muted()
        self.error_label = error_line()
        self.error_label.setVisible(False)
        self.editor_edit = QLineEdit()
        self.editor_browse_button = QPushButton(strings.BTN_BROWSE)
        self.editor_browse_button.clicked.connect(self.browse_editor)
        self.editor_hint = muted()

        grid = QGridLayout()
        grid.setHorizontalSpacing(theme.SPACE[1])
        grid.setVerticalSpacing(theme.SPACE[0])
        grid.addWidget(QLabel(strings.WIZARD_P1_LABEL), 0, 0)
        grid.addWidget(self.path_edit, 0, 1)
        grid.addWidget(self.browse_button, 0, 2)
        grid.addWidget(self.info_label, 1, 1, 1, 2)
        grid.addWidget(self.error_label, 2, 1, 1, 2)
        grid.setRowMinimumHeight(3, theme.SPACE[2])
        grid.addWidget(QLabel(strings.WIZARD_P1_EDITOR_LABEL), 4, 0)
        grid.addWidget(self.editor_edit, 4, 1)
        grid.addWidget(self.editor_browse_button, 4, 2)
        grid.addWidget(self.editor_hint, 5, 1, 1, 2)
        grid.setColumnStretch(1, 1)

        self.body.addWidget(self.intro_label)
        self.body.addSpacing(theme.SPACE[2])
        self.body.addLayout(grid)
        self.body.addStretch(1)

        self.path_edit.textChanged.connect(self._on_text_changed)
        # Counting the files under a folder walks it, so it happens when the
        # user stops typing (or picks a folder), never on every keystroke.
        self.path_edit.editingFinished.connect(self._refresh_info)

    def initializePage(self) -> None:
        if not self.path_edit.text():
            self.set_path(self._services.config.load().mirror_root)
        if not self.editor_edit.text():
            # A rerun keeps the editor already configured; detection is for
            # the first run (or when none was ever set).
            current = self._services.config.load().editor_path
            detected = current if current is not None else self._services.config.detect_editor()
            self.editor_edit.setText(str(detected) if detected is not None else "")
        self.editor_hint.setText(
            "" if self.editor_edit.text() else strings.WIZARD_P1_EDITOR_NOT_FOUND
        )

    # -- what the wizard asks ----------------------------------------------

    def isComplete(self) -> bool:
        """[Avanti] stays disabled while the field is empty; the real check
        happens in :meth:`validatePage`, which can show *why* it failed."""
        return bool(self.path_edit.text().strip())

    def validatePage(self) -> bool:
        folder = self.folder()
        if folder is None:
            self._set_error(strings.WIZARD_P1_ERROR_EMPTY)
            return False
        if not _is_writable(folder):
            self._set_error(strings.WIZARD_P1_ERROR_NOT_WRITABLE.format(path=folder))
            return False
        self._set_error("")
        return True

    # -- the answers ---------------------------------------------------------

    def folder(self) -> Path | None:
        text = self.path_edit.text().strip()
        # Kept exactly as typed or picked: the folder shown in the field is the
        # one written into config.json, with no silent resolution behind it.
        return Path(text) if text else None

    def editor_path(self) -> Path | None:
        text = self.editor_edit.text().strip()
        return Path(text) if text else None

    def set_path(self, path: Path | str) -> None:
        self.path_edit.setText(str(path))
        self._refresh_info()

    # -- the file count ------------------------------------------------------

    def counting(self) -> bool:
        """True while ``count_local_files`` runs for the folder in the field."""
        return self._counting

    def count_job(self) -> Job | None:
        return self._count_job

    def cancel_jobs(self) -> None:
        """The wizard is closing: stop walking the folder."""
        if self._count_job is not None:
            self._count_job.cancel()

    # -- buttons ------------------------------------------------------------

    def browse(self) -> None:
        current = self.path_edit.text().strip()
        chosen = QFileDialog.getExistingDirectory(
            self, strings.WIZARD_P1_BROWSE_CAPTION, current
        )
        if chosen:
            self.set_path(Path(chosen))

    def browse_editor(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self,
            strings.WIZARD_P1_EDITOR_CAPTION,
            self.editor_edit.text().strip(),
            strings.WIZARD_P1_EDITOR_FILTER,
        )
        if path:
            self.editor_edit.setText(str(Path(path)))
            self.editor_hint.setText("")

    # -- internals ----------------------------------------------------------

    def _set_error(self, text: str) -> None:
        """An empty error line takes no room in the form."""
        self.error_label.setText(text)
        self.error_label.setVisible(bool(text))

    def _on_text_changed(self, _text: str) -> None:
        self._set_error("")
        self.completeChanged.emit()

    def _refresh_info(self) -> None:
        """Refresh the WIZARD_P1_EXISTING_FILES line, counting in a worker.

        The folder may already hold a mirror somebody copied over by hand: those
        files must be indexed, not downloaded again, and saying so here is what
        stops the user from picking an empty folder "to be safe". A new count
        supersedes the previous one, so only the folder in the field answers.
        """
        folder = self.folder()
        job = None
        if folder is not None and self._runner is not None:
            job = self._runner.submit(COUNT_JOB, self._services.index.count_local_files, folder)
        self._count_job = job
        self._counting = job is not None
        if job is None:  # nothing to count, or the application is closing
            self.info_label.setText("")
            return
        self.info_label.setText(strings.WIZARD_P1_COUNTING)
        # Bound methods: the connection dies with the page if it closes first.
        # A superseded count is silent, so whatever arrives is for this folder.
        job.signals.result.connect(self._show_count)
        job.signals.error.connect(self._count_failed)
        job.signals.finished.connect(self._count_finished)

    def _show_count(self, n: int) -> None:
        self.info_label.setText(strings.WIZARD_P1_EXISTING_FILES.format(n=n) if n else "")

    def _count_failed(self, kind: str, message: str) -> None:
        # An unreadable folder is not worth a dialog; validatePage says the rest.
        log.debug("conteggio dei file locali non riuscito: %s: %s", kind, message)
        self.info_label.setText("")

    def _count_finished(self) -> None:
        self._counting = False
        if self.info_label.text() == strings.WIZARD_P1_COUNTING:  # cancelled
            self.info_label.setText("")


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
