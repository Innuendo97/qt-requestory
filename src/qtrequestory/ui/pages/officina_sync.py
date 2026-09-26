"""Keeps two Officina document views in step (scroll and zoom).

Scroll is followed by *relative page position* — page index plus the fraction
of that page at the top of the view — so two documents whose pages differ in
length (TARGET vs TO-BE) still show the same page side by side. Imported by
``officina_viewer`` and re-exported from there.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject

if TYPE_CHECKING:
    from qtrequestory.ui.pages.officina_viewer import DocView

__all__ = ["SyncController"]


class SyncController(QObject):
    """Keeps ``left`` and ``right`` in step: relative page position and zoom.

    ``set_enabled(False)`` lets each view scroll on its own; re-enabling
    brings the right view back to the left one's zoom and place. A view
    scrolled past the other's last page puts the other at its end.

    Every connection has this controller as its receiver, so Qt drops them
    with it; when either view is destroyed the controller lets go of the
    other one too (:meth:`is_attached` turns False) and does nothing more.
    """

    def __init__(self, left: DocView, right: DocView, parent: QObject | None = None) -> None:
        super().__init__(parent if parent is not None else left)
        self._left: DocView | None = left
        self._right: DocView | None = right
        self._enabled = True
        self._busy = False
        #: Per view, its (signal, slot) connections to this controller.
        self._links = {
            "left": [(left.verticalScrollBar().valueChanged, self._left_scrolled),
                     (left.zoom_changed, self._left_zoomed),
                     (left.destroyed, self._left_destroyed)],
            "right": [(right.verticalScrollBar().valueChanged, self._right_scrolled),
                      (right.zoom_changed, self._right_zoomed),
                      (right.destroyed, self._right_destroyed)],
        }
        for links in self._links.values():
            for signal, slot in links:
                signal.connect(slot)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        if self._enabled:
            self._left_zoomed()

    def is_enabled(self) -> bool:
        return self._enabled

    def is_attached(self) -> bool:
        """Both views still exist and are kept in step (when enabled)."""
        return self._left is not None and self._right is not None

    def focus_difference(self, diff_id: int, *, reveal: bool = False) -> None:
        """Focus ``diff_id`` in both views, each at its own place; ``reveal``
        centres it in both even when it is already on screen."""
        if not self.is_attached():
            return
        self._busy = True
        try:
            self._left.focus_difference(diff_id, reveal=reveal)
            self._right.focus_difference(diff_id, reveal=reveal)
        finally:
            self._busy = False

    # -- slots (receiver: self) ------------------------------------------------

    def _left_scrolled(self, _value: int = 0) -> None:
        self._follow(self._left, self._right, zoom=False)

    def _right_scrolled(self, _value: int = 0) -> None:
        self._follow(self._right, self._left, zoom=False)

    def _left_zoomed(self) -> None:
        self._follow(self._left, self._right, zoom=True)

    def _right_zoomed(self) -> None:
        self._follow(self._right, self._left, zoom=True)

    def _left_destroyed(self, *_args) -> None:
        self._detach(survivor="right")

    def _right_destroyed(self, *_args) -> None:
        self._detach(survivor="left")

    def _detach(self, survivor: str) -> None:
        """One view is being destroyed: let go of both, disconnect the other."""
        links = self._links.get(survivor, [])
        self._links = {}
        self._left = self._right = None
        for signal, slot in links:
            signal.disconnect(slot)

    def _follow(self, source: DocView | None, target: DocView | None, *, zoom: bool) -> None:
        if not self._enabled or self._busy or source is None or target is None:
            return
        self._busy = True
        try:
            if zoom:
                mode = source.zoom_mode()
                target.set_zoom(mode if mode is not None else source.zoom())
            target.scroll_to_position(*source.relative_position())
        finally:
            self._busy = False
