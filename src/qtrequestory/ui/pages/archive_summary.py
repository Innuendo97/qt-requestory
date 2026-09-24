"""Impostazioni › Archivio, row "Log": what the archive folder holds.

"N log in archivio · M da importare · K da assegnare · J ignorati
[Dettagli…] [Importa log da una cartella…]". The numbers come from the shared
:class:`~qtrequestory.ui.import_state.ArchiveWatch` (the saved configuration,
not the form being edited); both buttons open the import dialog through
``MainWindow.open_import``, the first on the archive folder itself, the second
on a folder the user picks. While the saved log folder is not usable the row
says why and both buttons are off: nothing is imported into an invalid archive.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QPushButton, QWidget

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import CONFLICT, IGNORED, IMPORTABLE, NEEDS_ENV, CoreServices
from qtrequestory.ui.import_state import ArchiveWatch
from qtrequestory.ui.workers import JobRunner

__all__ = ["ArchiveSummary", "summary_text"]


def summary_text(watch: ArchiveWatch) -> str:
    if watch.problem is not None:
        return strings.ARCHIVE_SUMMARY_UNAVAILABLE.format(problem=watch.problem)
    if watch.snapshot is None:
        return strings.ARCHIVE_SUMMARY_LOADING
    counts = watch.snapshot.report.counts()
    text = strings.ARCHIVE_SUMMARY.format(
        archived=_count(watch.snapshot.archived), todo=_count(counts[IMPORTABLE]),
        assign=_count(counts[NEEDS_ENV]), ignored=_count(counts[IGNORED]))
    if counts[CONFLICT]:
        text += strings.ARCHIVE_SUMMARY_CONFLICTS.format(n=_count(counts[CONFLICT]))
    return text


class ArchiveSummary(QWidget):
    """The summary line and its two buttons."""

    def __init__(self, services: CoreServices, runner: JobRunner, window: object | None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._window = window
        self.label = QLabel()
        theme.set_role(self.label, "muted")
        self.label.setWordWrap(True)
        self.details_button = QPushButton(strings.ARCHIVE_BTN_DETAILS)
        self.details_button.clicked.connect(lambda: self._open([None]))
        self.import_button = QPushButton(strings.ARCHIVE_BTN_IMPORT_FOLDER)
        self.import_button.clicked.connect(self.import_folder)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.label, 1)
        layout.addWidget(self.details_button)
        layout.addWidget(self.import_button)
        self.watch = ArchiveWatch.shared(services, runner)
        self.watch.changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        self.label.setText(summary_text(self.watch))
        usable = self.watch.problem is None
        self.details_button.setEnabled(usable and self.watch.snapshot is not None)
        self.import_button.setEnabled(usable)

    def import_folder(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, strings.ARCHIVE_IMPORT_CAPTION, "")
        if chosen:
            self._open([Path(chosen)])

    def _open(self, sources: list[Path | None]) -> None:
        opener = getattr(self._window, "open_import", None)
        if callable(opener):
            opener(sources)


def _count(n: int) -> str:
    """Thousands with the Italian dot: 3.412."""
    return f"{n:,}".replace(",", ".")
