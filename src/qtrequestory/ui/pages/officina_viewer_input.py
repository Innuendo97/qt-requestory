"""The document viewer's mouse and keyboard (a mixin of ``DocView``, split
from ``officina_viewer`` for size).

A click — not a drag: the view pans with the hand — on a highlight emits
``difference_clicked``, elsewhere ``blank_clicked``; a double click on one
``difference_double_clicked`` (its release is not a click); a right click on
one ``difference_menu`` with the global point, elsewhere the default menu;
F / T / V with no modifier ``key_action`` (``officina_rows.REVIEW_KEYS``). The
signals are declared on ``DocView``; the case view turns them into review
actions (``officina_actions_bar``).
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication

from qtrequestory.ui.pages.officina_overlays import HighlightItem
from qtrequestory.ui.pages.officina_rows import REVIEW_KEYS

__all__ = ["ViewerInputMixin"]


class ViewerInputMixin:
    """Needs from the view: ``_press`` (set in ``__init__``), ``items`` and
    the signals ``difference_clicked``, ``difference_double_clicked``,
    ``difference_menu``, ``blank_clicked``, ``key_action``."""

    def mousePressEvent(self, event) -> None:  # noqa: D102, N802
        left = event.button() == Qt.MouseButton.LeftButton
        self._press = event.position().toPoint() if left else None
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: D102, N802 - a click, not a drag
        pos = event.position().toPoint()
        press, self._press = self._press, None
        if (event.button() == Qt.MouseButton.LeftButton and press is not None
                and (pos - press).manhattanLength() < QApplication.startDragDistance()):
            hit = self.highlight_at(pos)
            if hit is None:
                self.blank_clicked.emit()
            else:
                self.difference_clicked.emit(hit)
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: D102, N802
        super().mouseDoubleClickEvent(event)
        self._press = None  # its release is not a click
        if event.button() == Qt.MouseButton.LeftButton:
            hit = self.highlight_at(event.position().toPoint())
            if hit is not None:
                self.difference_double_clicked.emit(hit)

    def contextMenuEvent(self, event) -> None:  # noqa: D102, N802
        hit = self.highlight_at(event.pos())
        if hit is None:
            super().contextMenuEvent(event)
            return
        event.accept()
        self.difference_menu.emit(hit, event.globalPos())

    def keyPressEvent(self, event) -> None:  # noqa: D102, N802
        mods = event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
        if mods == Qt.KeyboardModifier.NoModifier and event.key() in REVIEW_KEYS:
            self.key_action.emit(REVIEW_KEYS[event.key()])
            event.accept()
            return
        super().keyPressEvent(event)

    def highlight_at(self, pos: QPoint) -> int | None:
        """The difference drawn at viewport point ``pos``, if any."""
        for item in self.items(pos):
            if isinstance(item, HighlightItem):
                return item.diff_id
        return None
