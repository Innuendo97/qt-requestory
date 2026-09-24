"""Page 1 of the wizard, the import offer: "li importerò alla fine".

Under the log-folder field: when the chosen folder already holds logs
OUTSIDE ``<env>/YYYY/MM/YYYYMMDD.txt`` a checkbox (on by default) says they
will be imported at the end; "Hai già dei log altrove? [Scegli cartella…]"
queues one more folder. [Fine] hands :meth:`ImportOffer.sources` to the
caller through ``WizardResult.import_sources``; ``MainWindow`` then opens the
import dialog on them (``None`` stands for the log folder itself).

The count is an estimate on purpose: the environments are only asked on the
next page, so a log whose environment is unknown still counts. The dialog
rescans with the saved configuration before anything is copied. The folder
about to become the archive is passed as ``canonical_root``, so the logs
already in place there are not counted as "to import".
"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import ArchiveApi, CoreServices
from qtrequestory.ui.import_state import WIZARD_ARCHIVE_JOB, stray_count
from qtrequestory.ui.workers import Job, JobRunner

__all__ = ["ImportOffer", "count_strays"]

log = logging.getLogger(__name__)


def count_strays(archive: ArchiveApi, folder: Path, extra: Path | None) -> tuple[int, int | None]:
    """Worker thread: the logs to import in ``folder`` and in ``extra``."""
    mine = stray_count(archive.report(folder, canonical_root=folder))
    other = (stray_count(archive.report(extra, canonical_root=folder))
             if extra is not None else None)
    return mine, other


class ImportOffer(QWidget):
    """The checkbox, the "altrove" picker and its line."""

    def __init__(self, services: CoreServices, runner: JobRunner | None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._services = services
        self._runner = runner
        self._folder: Path | None = None
        self.extra: Path | None = None
        self.found = 0
        self.extra_found: int | None = None
        self.job: Job | None = None

        self.checkbox = QCheckBox()
        self.checkbox.setChecked(True)
        self.checkbox.hide()
        self.elsewhere_label = QLabel(strings.WIZARD_IMPORT_ELSEWHERE)
        self.pick_button = QPushButton(strings.WIZARD_IMPORT_PICK)
        self.pick_button.clicked.connect(self.browse)
        self.extra_label = QLabel()
        theme.set_role(self.extra_label, "muted")
        self.extra_label.setWordWrap(True)
        self.remove_button = QPushButton(strings.WIZARD_IMPORT_EXTRA_REMOVE)
        self.remove_button.clicked.connect(lambda: self.set_extra(None))
        pick_row = QHBoxLayout()
        pick_row.addWidget(self.elsewhere_label)
        pick_row.addWidget(self.pick_button)
        pick_row.addStretch(1)
        extra_row = QHBoxLayout()
        extra_row.addWidget(self.extra_label, 1)
        extra_row.addWidget(self.remove_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE[1])
        layout.addWidget(self.checkbox)
        layout.addLayout(pick_row)
        layout.addLayout(extra_row)
        self._show_extra()

    # -- inputs -------------------------------------------------------------

    def set_folder(self, folder: Path | None) -> None:
        self._folder = folder
        self._count()

    def set_extra(self, folder: Path | None) -> None:
        self.extra = folder
        self.extra_found = None
        self._count()

    def browse(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, strings.WIZARD_IMPORT_PICK_CAPTION, "")
        if chosen:
            self.set_extra(Path(chosen))

    def cancel_jobs(self) -> None:
        if self.job is not None:
            self.job.cancel()

    # -- the answer ---------------------------------------------------------

    def sources(self) -> tuple[Path | None, ...]:
        """What to import after [Fine]; ``None`` is the log folder itself."""
        chosen: list[Path | None] = []
        if self.found and self.checkbox.isChecked():
            chosen.append(None)
        if self.extra is not None and self.extra_found != 0:
            chosen.append(self.extra)  # also while still counting: the dialog rescans
        return tuple(chosen)

    # -- internals ----------------------------------------------------------

    def _count(self) -> None:
        self.job = None
        if self._folder is not None and self._runner is not None:
            self.job = self._runner.submit(WIZARD_ARCHIVE_JOB, count_strays,
                                           self._services.archive, self._folder, self.extra)
        if self.job is None:
            self._show_counts(0, None)
            return
        self.job.signals.result.connect(self._on_counts)
        self.job.signals.error.connect(self._count_failed)

    def _on_counts(self, counts: tuple[int, int | None]) -> None:
        self._show_counts(*counts)

    def _count_failed(self, kind: str, message: str) -> None:
        log.debug("conteggio dei log da importare non riuscito: %s: %s", kind, message)
        self._show_counts(0, None)

    def _show_counts(self, found: int, extra_found: int | None) -> None:
        self.found = found
        self.extra_found = extra_found
        self.checkbox.setText(strings.WIZARD_IMPORT_FOUND_ONE if found == 1
                              else strings.WIZARD_IMPORT_FOUND.format(n=found))
        self.checkbox.setVisible(found > 0)
        self._show_extra()

    def _show_extra(self) -> None:
        visible = self.extra is not None
        if visible and self.extra_found is not None:
            template = (strings.WIZARD_IMPORT_EXTRA if self.extra_found
                        else strings.WIZARD_IMPORT_EXTRA_NONE)
            self.extra_label.setText(template.format(path=self.extra, n=self.extra_found))
        elif visible:
            self.extra_label.setText(str(self.extra))
        self.extra_label.setVisible(visible)
        self.remove_button.setVisible(visible)
