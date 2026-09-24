""""Trovati N log fuori dalla struttura dell'archivio · [Importa]".

Shown on Ricerca and Sincronizzazione while the mirror folder itself holds
logs the index cannot see: files to import, or waiting for an environment
(misplaced, renamed, a colleague's folder copied in). The count comes from
the shared :class:`~qtrequestory.ui.import_state.ArchiveWatch`, which rescans
after every sync, index or import, so the page needs no hook of its own:
one line builds the banner, one puts it in the layout.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import CoreServices
from qtrequestory.ui.import_state import ArchiveWatch, stray_count
from qtrequestory.ui.workers import JobRunner

__all__ = ["ImportBanner"]


class ImportBanner(QFrame):
    """Warn banner + [Importa]; hidden while the mirror holds no stray log."""

    def __init__(self, services: CoreServices, runner: JobRunner, window: object | None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._window = window
        self.setProperty("banner", "warn")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setToolTip(strings.IMPORT_BANNER_TOOLTIP)
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.button = QPushButton(strings.IMPORT_BANNER_BUTTON)
        self.button.clicked.connect(self.open_import)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(theme.SPACE[2], theme.SPACE[0], theme.SPACE[1], theme.SPACE[0])
        layout.addWidget(self.label, 1)
        layout.addWidget(self.button)
        self.setVisible(False)
        self.watch = ArchiveWatch.shared(services, runner)
        self.watch.changed.connect(self.refresh)
        self.refresh()

    def count(self) -> int:
        return stray_count(self.watch.report)

    def refresh(self) -> None:
        n = self.count()
        if n:
            self.label.setText(strings.IMPORT_BANNER_ONE if n == 1
                               else strings.IMPORT_BANNER.format(n=n))
        self.setVisible(n > 0)

    def open_import(self) -> None:
        opener = getattr(self._window, "open_import", None)
        if callable(opener):
            opener([None])
