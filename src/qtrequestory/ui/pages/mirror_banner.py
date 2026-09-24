"""The "cartella dei log non valida" banner shared by Ricerca and Sincronizzazione.

An empty or relative ``mirror_root`` is what the CLI refuses with exit 2
(``config.mirror_root_errors``): the scheduled task then fails every hour,
and the window must neither sync nor index into its own working directory.
The banner says so on the two pages that would otherwise look merely empty,
and its button leads to the one place that fixes it, Impostazioni › Archivio.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import CoreServices

__all__ = ["MirrorRootBanner", "open_settings_section"]

#: ``SettingsPage.show_section`` key of the section holding the log folder.
ARCHIVE_SECTION = "archive"


def open_settings_section(window: object | None, key: str) -> None:
    """Impostazioni, on section ``key``; a window without pages is ignored."""
    show_page = getattr(window, "show_page", None)
    if not callable(show_page):
        return
    show_page("settings")
    page = getattr(window, "page", None)
    show_section = getattr(page("settings") if callable(page) else None, "show_section", None)
    if callable(show_section):
        show_section(key)


class MirrorRootBanner(QFrame):
    """Warn banner + [Apri Impostazioni › Archivio]; hidden while the folder is valid."""

    def __init__(self, services: CoreServices, window: object | None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._services = services
        self._window = window
        self.setProperty("banner", "warn")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.button = QPushButton(strings.MIRROR_ROOT_BUTTON)
        self.button.clicked.connect(lambda: open_settings_section(self._window, ARCHIVE_SECTION))
        layout = QHBoxLayout(self)
        layout.setContentsMargins(theme.SPACE[2], theme.SPACE[0], theme.SPACE[1], theme.SPACE[0])
        layout.addWidget(self.label, 1)
        layout.addWidget(self.button)
        self.setVisible(False)

    def problems(self) -> list[str]:
        """The current configuration's log-folder problems (a pure check, no I/O)."""
        return self._services.config.mirror_root_errors(self._services.config.load())

    def refresh(self) -> list[str]:
        """Re-read the configuration, show or hide; returns the problems."""
        problems = self.problems()
        if problems:
            self.label.setText(strings.MIRROR_ROOT_BANNER.format(problem=problems[0]))
        self.setVisible(bool(problems))
        return problems
