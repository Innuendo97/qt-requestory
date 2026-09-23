"""The right half of the Ricerca page: the preview pane, or a placeholder.

The pane is built by the page (``preview_factory``) and installed here; with no
pane (the degraded mode, ``preview_factory=None``) the slot shows a
placeholder in the UI font and the page disables the body actions.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from qtrequestory.ui import strings, theme

__all__ = ["PreviewSlot"]


class PreviewSlot(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.pane: QWidget | None = None
        self.placeholder = QLabel(strings.SEARCH_PREVIEW_PLACEHOLDER)
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setWordWrap(True)
        theme.set_role(self.placeholder, "muted")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.addWidget(self.placeholder)

    def install(self, widget: QWidget | None) -> None:
        """Put ``widget`` in the slot (replacing any pane); None = the placeholder."""
        if self.pane is not None:
            self._layout.removeWidget(self.pane)
            self.pane.setParent(None)
        self.pane = widget
        self.placeholder.setVisible(widget is None)
        if widget is not None:
            self._layout.addWidget(widget)
            widget.setVisible(True)
