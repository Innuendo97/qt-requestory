"""The overlay half of the Officina viewer (a mixin of ``DocView``, split
from ``officina_overlays`` for size): the verdict boxes and changed
characters of the differences on screen, and the focus ring.

Spec §4 (phase 2.5): the ring outlines each box, never their union; one ring
item per view, repainted whole; the view scrolls to the *anchor box* only;
invisible and off-page words get no highlight.
"""
from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from typing import TYPE_CHECKING

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsPathItem

from qtrequestory.ui import theme
from qtrequestory.ui.pages.officina_overlays import (
    CharMark,
    HighlightItem,
    line_boxes,
    paper,
    shown_words,
    span_boxes,
    style_highlight,
)
from qtrequestory.ui.pages.officina_verdict_style import look_for, state_of

if TYPE_CHECKING:
    from qtrequestory.ui.contracts import Judged

__all__ = ["RING_PAD", "HighlightsMixin"]

#: States whose changed characters are not pinpointed (nothing to fix there).
_NO_CHAR_MARKS = frozenset({"fatta", "tollerata", "rumore", "variabile", "arredo"})

#: Padding of the focus ring around each box of a difference, in points.
RING_PAD = 3.0


class HighlightsMixin:
    """DocView's overlay half: verdict boxes, changed characters, focus ring.

    The ring outlines **each box** of the focused difference (one per run on
    a line, spec §4.1), never their union: a section that jumps columns would
    otherwise ring half a page. It is ONE path item per view, and the view
    repaints its whole viewport (``FullViewportUpdate``), so a ring that moves
    leaves nothing behind (§4.4). The *anchor box* — the box last clicked, else
    the first one — is what the view scrolls to and the mini-bar sits under.

    Needs from the view: ``scene()``, ``viewport()``, ``_pages`` (PageSlot
    list), ``_visible_scene_rect``, ``centerOn``, ``_schedule`` and
    ``_refresh_minimap`` (called whenever what is drawn changes).
    """

    def _init_highlights(self) -> None:
        self._diffs: dict[int, list[HighlightItem]] = {}
        self._marks: dict[int, list[CharMark]] = {}
        #: Diff.id → scene rect of ``Diff.empty_at`` on this side (it has no words here).
        self._insertions: dict[int, QRectF] = {}
        self._items: list[tuple[Judged, str]] = []
        self._show_done = False
        self._focused: int | None = None
        #: (Diff.id, scene rect) of the box last clicked: the anchor while it is drawn.
        self._clicked: tuple[int, QRectF] | None = None
        self._ring = QGraphicsPathItem()
        self._ring.setZValue(3)
        self._ring.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self._ring.setVisible(False)
        self.scene().addItem(self._ring)

    def set_highlights(self, items: list[tuple[Judged, str]]) -> None:
        """Replace the overlays: ``(judged, side)`` each; ``side`` is "left"
        (the target: ``diff.left`` words) or "right" (the version: ``diff.right``).
        Invisible and off-page words are left out (:func:`shown_words`)."""
        sizes = [(p.rect.width(), p.rect.height()) for p in self._pages]
        self._items = [(_shown(judged, side, sizes), side) for judged, side in items]
        self._layout_highlights()
        self._focused = None
        self._hide_ring()

    def set_show_done(self, show: bool) -> None:
        """Draw the "fatta" differences too (target side only): "Mostra fatte"."""
        if show == self._show_done:
            return
        self._show_done = show
        self._layout_highlights()
        if self._focused is not None:
            self._ring_around(self._focused)

    def show_done(self) -> bool:
        return self._show_done

    def _layout_highlights(self) -> None:
        self._clear_items()
        for judged, side in self._items:
            self._note_insertion(judged, side)
            state = state_of(judged)
            if state == "fatta" and (side != "left" or not self._show_done):
                continue
            diff = judged.diff
            words, text, spans = ((diff.left, diff.left_text, diff.left_spans) if side == "left"
                                  else (diff.right, diff.right_text, diff.right_spans))
            look = look_for(judged)
            for page, rect in line_boxes(words):
                self._place(self._diffs, page, HighlightItem, rect, diff.id, look)
            if state not in _NO_CHAR_MARKS:
                for page, rect in span_boxes(words, text, spans):
                    self._place(self._marks, page, CharMark, rect, diff.id)
        self._refresh_minimap()

    def _place(self, into: dict, page: int, kind, rect: QRectF, diff_id: int, *args) -> None:
        if 0 <= page < len(self._pages):
            item = kind(rect.translated(self._pages[page].rect.topLeft()), diff_id, *args)
            self.scene().addItem(item)
            into.setdefault(diff_id, []).append(item)

    def _note_insertion(self, judged: Judged, side: str) -> None:
        """Where a one-sided difference sits on this side, which has no words
        of it: the engine's insertion point (``Diff.empty_at``)."""
        diff = judged.diff
        at = diff.empty_at
        if at is None or (diff.left if side == "left" else diff.right):
            return
        page, x0, y0, x1, y1 = at
        if 0 <= page < len(self._pages):
            rect = QRectF(x0, y0, max(x1 - x0, 0.0), max(y1 - y0, 0.0))
            self._insertions[diff.id] = rect.translated(self._pages[page].rect.topLeft())

    def insertion_rect(self, diff_id: int) -> QRectF:
        """Scene rect of the word next to where ``diff_id`` would sit on this
        side (spec §4.5, ``Diff.empty_at``); null when unknown or when the
        difference has words here."""
        return QRectF(self._insertions.get(diff_id, QRectF()))

    def highlight_items(self, diff_id: int) -> list[HighlightItem]:
        return list(self._diffs.get(diff_id, ()))

    def char_marks(self, diff_id: int) -> list[CharMark]:
        return list(self._marks.get(diff_id, ()))

    def difference_boxes(self, diff_id: int) -> list[QRectF]:
        """Scene rects of the difference's boxes, in document order."""
        return [item.rect() for item in self._diffs.get(diff_id, ())]

    def difference_rect(self, diff_id: int) -> QRectF:
        """Scene rect of the difference's anchor box: the box last clicked
        when it is one of its boxes, else its first box (null: none drawn)."""
        boxes = self.difference_boxes(diff_id)
        if not boxes:
            return QRectF()
        clicked = self._clicked
        if clicked is not None and clicked[0] == diff_id and clicked[1] in boxes:
            return QRectF(clicked[1])
        return boxes[0]

    def remember_click(self, item: HighlightItem) -> None:
        """The box under a click becomes its difference's anchor box."""
        self._clicked = (item.diff_id, QRectF(item.rect()))

    def focus_difference(self, diff_id: int, *, reveal: bool = False, scroll: bool = True) -> bool:
        """Ring ``diff_id``; with ``scroll``, centre its anchor box when that
        box is not wholly on screen — always with ``reveal`` (Enter in the
        list). False when the difference has nothing drawn in this view."""
        if not self._ring_around(diff_id):
            return False
        anchor = self.difference_rect(diff_id).adjusted(-RING_PAD, -RING_PAD, RING_PAD, RING_PAD)
        if scroll and (reveal or not self._visible_scene_rect().contains(anchor)):
            self.centerOn(anchor.center())
        self._schedule()
        return True

    def _ring_around(self, diff_id: int) -> bool:
        boxes = self.difference_boxes(diff_id)
        if not boxes:
            self._focused = None
            self._hide_ring()
            return False
        self._focused = diff_id
        path = QPainterPath()
        for box in boxes:
            path.addRect(box.adjusted(-RING_PAD, -RING_PAD, RING_PAD, RING_PAD))
        self._ring.setPath(path)
        self._ring.setVisible(True)
        self.viewport().update()
        return True

    def _hide_ring(self) -> None:
        if self._ring.isVisible():
            self._ring.setVisible(False)
            self.viewport().update()

    def focused_difference(self) -> int | None:
        return self._focused

    def focus_ring(self) -> QGraphicsPathItem:
        return self._ring

    def _clear_items(self) -> None:
        for group in (self._diffs, self._marks):
            for items in group.values():
                for item in items:
                    self.scene().removeItem(item)
        self._diffs, self._marks, self._insertions = {}, {}, {}

    def _clear_highlights(self) -> None:
        self._items = []
        self._clear_items()
        self._focused = None
        self._clicked = None
        self._hide_ring()
        self._refresh_minimap()

    def _recolour_highlights(self, _tokens: theme.Tokens) -> None:
        """Re-style after a theme switch (on-page colours are PAPER values, R13)."""
        for items in self._diffs.values():
            for item in items:
                style_highlight(item)
        for marks in self._marks.values():
            for mark in marks:
                mark.recolour()
        ring = QPen(paper("accent"), 2.0)
        ring.setCosmetic(True)
        self._ring.setPen(ring)
        self._ring.setBrush(Qt.BrushStyle.NoBrush)


def _shown(judged: Judged, side: str, sizes: Sequence[tuple[float, float]]) -> Judged:
    """``judged`` keeping only the words of ``side`` that can be seen."""
    words = judged.diff.left if side == "left" else judged.diff.right
    kept = shown_words(words, sizes)
    if len(kept) == len(words):
        return judged
    return dataclasses.replace(judged, diff=dataclasses.replace(judged.diff, **{side: kept}))
