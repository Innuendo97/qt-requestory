"""Keeps two Officina document views in step (scroll on both axes, and zoom).

Vertical scroll is followed by *relative page position* — page index plus the
fraction of that page at the top of the view — so two documents whose pages
differ in length (TARGET vs TO-BE) still show the same page side by side.
Horizontal scroll (zoomed in) is followed by the fraction of the column's
width at the middle of the view: the two views may be of different widths,
so copying the scroll bar value would frame different parts (spec §4.3).

Focusing a difference rings it in both views, each at its own place; a side
where it has no words (a «mancante» has none on the version) is brought to
the corresponding place — the word next to the engine's insertion point
(``Diff.empty_at``) when there is one, else the same point of the same page
as on the other side — at the same height on screen as the other side's
anchor box, instead of staying where it was (§4.5).
Imported by ``officina_viewer`` and re-exported from there.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QPointF

if TYPE_CHECKING:
    from qtrequestory.ui.pages.officina_viewer import DocView

__all__ = ["SyncController", "centre_x_fraction", "set_centre_x_fraction"]


def centre_x_fraction(view: DocView) -> float:
    """Where the middle of ``view`` is across its scene (0 left, 1 right)."""
    rect = view.sceneRect()
    if rect.width() <= 0:
        return 0.5
    return (view.mapToScene(view.viewport().rect().center()).x() - rect.left()) / rect.width()


def set_centre_x_fraction(view: DocView, fraction: float) -> None:
    """Scroll ``view`` sideways so ``fraction`` of its scene is in the middle."""
    rect = view.sceneRect()
    target = rect.left() + fraction * rect.width()
    now = view.mapToScene(view.viewport().rect().center()).x()
    bar = view.horizontalScrollBar()
    bar.setValue(bar.value() + round((target - now) * view.transform().m11()))


def align_to(view: DocView, page: int, point: QPointF, screen: QPointF) -> None:
    """Scroll ``view`` so ``point`` (in the coordinates of page ``page``) sits
    at viewport position ``screen``; past its last page: its last page."""
    if view.page_count() == 0:
        return
    page = max(0, min(page, view.page_count() - 1))
    scene = view.page_rect(page).topLeft() + point
    now = view.mapToScene(screen.toPoint())
    scale = view.transform().m11()
    for bar, delta in ((view.horizontalScrollBar(), scene.x() - now.x()),
                       (view.verticalScrollBar(), scene.y() - now.y())):
        bar.setValue(bar.value() + round(delta * scale))


class SyncController(QObject):
    """Keeps ``left`` and ``right`` in step: relative page position, the
    horizontal centre and zoom.

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
                     (left.horizontalScrollBar().valueChanged, self._left_scrolled),
                     (left.zoom_changed, self._left_zoomed),
                     (left.destroyed, self._left_destroyed)],
            "right": [(right.verticalScrollBar().valueChanged, self._right_scrolled),
                      (right.horizontalScrollBar().valueChanged, self._right_scrolled),
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

    def focus_difference(self, diff_id: int, *, reveal: bool = False, scroll: bool = True) -> None:
        """Focus ``diff_id`` in both views, each at its own place; ``reveal``
        centres it in both even when it is already on screen; without
        ``scroll`` only the rings move (an action from the page: the view
        stays where the user is looking). A side where it has no words goes
        to the place matching the other side's anchor box."""
        if not self.is_attached():
            return
        self._busy = True
        try:
            drawn = {name: view.focus_difference(diff_id, reveal=reveal, scroll=scroll)
                     for name, view in (("left", self._left), ("right", self._right))}
            if scroll and drawn["left"] != drawn["right"]:
                source, target = ((self._left, self._right) if drawn["left"]
                                  else (self._right, self._left))
                self._match(source, target, diff_id)
        finally:
            self._busy = False

    @staticmethod
    def _match(source: DocView, target: DocView, diff_id: int) -> None:
        box = source.difference_rect(diff_id)
        screen = QPointF(source.mapFromScene(box.center()))
        at = target.insertion_rect(diff_id)
        if not at.isNull():  # the engine knows where it would sit there
            page = target.page_at(at.center().y())
            align_to(target, page, at.center() - target.page_rect(page).topLeft(), screen)
            return
        page = source.page_at(box.center().y())
        align_to(target, page, box.center() - source.page_rect(page).topLeft(), screen)

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
            set_centre_x_fraction(target, centre_x_fraction(source))
        finally:
            self._busy = False
