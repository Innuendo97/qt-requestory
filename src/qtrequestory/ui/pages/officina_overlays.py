"""Scene pieces of the Officina viewer: page slots, highlight boxes, colours.

A :class:`PageSlot` is one page of the column: a placeholder (``surface2``)
with a label, and the rendered image once there is one.

A judged difference is drawn **by its verdict** (spec §7.1; the looks are in
``officina_verdict_style``): one box per run of words on a line (not one box
per word), filled with the look's soft token and outlined with its edge —
solid, or dashed for "da verificare" (2 px), tolerated and noise; a variable
and a "fatta" are a line under the words instead of a box. The changed
characters (``Diff.left_spans`` / ``right_spans``) are yellow
(``mark_yellow``) sub-rects of the word boxes, proportional to the character
offsets, with a 2 px underline in the page's ink colour so they stay visible
on a ``warn_bg`` fill (ruling R14). Fills are painted in *multiply* mode, so
the page's black text stays black under them.

The page is white paper in both themes, so everything drawn ON it takes the
LIGHT token values (:data:`PAPER`, ruling R13) — still tokens, never hex; the
chrome around it (placeholder, background, list, pills) follows the theme.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING

from PySide6.QtCore import QLineF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsTextItem,
)

from qtrequestory.ui import theme
from qtrequestory.ui.pages.officina_verdict_style import Look, look_for, state_of

if TYPE_CHECKING:
    from qtrequestory.ui.contracts import Judged, Word

__all__ = ["CharMark", "HighlightItem", "HighlightsMixin", "PageSlot", "line_boxes", "look_colours",
           "span_boxes", "style_highlight", "union"]

#: Padding around a word box, in points.
PAD = 1.0
#: The token values of everything drawn on the page (white paper in both themes, R13).
PAPER = theme.LIGHT
#: Width of the ink underline under the changed characters, in pixels (R14).
CHAR_UNDERLINE = 2.0
#: States whose changed characters are not pinpointed (nothing to fix there).
_NO_CHAR_MARKS = frozenset({"fatta", "tollerata", "rumore", "variabile"})


def _paper(token: str) -> QColor:
    return QColor(getattr(PAPER, token))


def look_colours(look: Look) -> tuple[QColor | None, QColor]:
    """(fill or None, edge) of ``look`` on the page (:data:`PAPER` values)."""
    return (_paper(look.fill) if look.fill else None), _paper(look.edge)


def _multiply_fill(painter: QPainter, rect: QRectF, brush: QBrush) -> None:
    painter.save()
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Multiply)
    painter.fillRect(rect, brush)
    painter.restore()


class HighlightItem(QGraphicsRectItem):
    """One highlight box; ``diff_id`` is the ``Diff.id`` it belongs to."""

    def __init__(self, rect: QRectF, diff_id: int, look: Look) -> None:
        super().__init__(rect)
        self.diff_id = diff_id
        self.look = look
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)  # the view handles clicks
        self.setZValue(2)
        style_highlight(self)

    def paint(self, painter: QPainter, option, widget=None) -> None:  # noqa: D102
        rect = self.rect()
        if self.brush().style() != Qt.BrushStyle.NoBrush:
            _multiply_fill(painter, rect, self.brush())
        painter.setPen(self.pen())
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if self.look.underline:
            painter.drawLine(QLineF(rect.bottomLeft(), rect.bottomRight()))
        else:
            painter.drawRect(rect)


def style_highlight(item: HighlightItem) -> None:
    fill, edge = look_colours(item.look)
    item.setBrush(QBrush(fill) if fill is not None else QBrush(Qt.BrushStyle.NoBrush))
    pen = QPen(edge, item.look.width)
    pen.setStyle(Qt.PenStyle.DashLine if item.look.dash else Qt.PenStyle.SolidLine)
    pen.setCosmetic(True)
    item.setPen(pen)


class CharMark(QGraphicsRectItem):
    """Changed characters of a word: a ``mark_yellow`` sub-rect (multiply) with
    a 2 px underline in the page's ink colour (``text`` of :data:`PAPER`)."""

    def __init__(self, rect: QRectF, diff_id: int) -> None:
        super().__init__(rect)
        self.diff_id = diff_id
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setZValue(2.5)
        self.recolour()

    def recolour(self) -> None:
        self.setBrush(QBrush(_paper("mark_yellow")))
        pen = QPen(_paper("text"), CHAR_UNDERLINE)
        pen.setCosmetic(True)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        self.setPen(pen)

    def paint(self, painter: QPainter, option, widget=None) -> None:  # noqa: D102
        rect = self.rect()
        _multiply_fill(painter, rect, self.brush())
        painter.setPen(self.pen())
        painter.drawLine(QLineF(rect.bottomLeft(), rect.bottomRight()))


def line_boxes(words: Iterable[Word]) -> list[tuple[int, QRectF]]:
    """``(page, rect)`` boxes covering ``words``: one per run on a line.

    Consecutive words merge when they are on the same page, overlap vertically
    by at least half the smaller height and sit close together horizontally
    (gap under 1.5 × the line height). Rects are in page points, padded.
    """
    boxes: list[tuple[int, QRectF]] = []
    for word in words:
        rect = QRectF(word.x0, word.y0, word.x1 - word.x0, word.y1 - word.y0)
        if boxes and _joins(boxes[-1], word.page, rect):
            page, last = boxes[-1]
            boxes[-1] = (page, last.united(rect))
        else:
            boxes.append((word.page, rect))
    return [(page, rect.adjusted(-PAD, -PAD, PAD, PAD)) for page, rect in boxes]


def _joins(box: tuple[int, QRectF], page: int, rect: QRectF) -> bool:
    last_page, last = box
    if last_page != page:
        return False
    overlap = min(last.bottom(), rect.bottom()) - max(last.top(), rect.top())
    height = min(last.height(), rect.height())
    if height <= 0 or overlap < height / 2:
        return False
    gap = max(rect.left() - last.right(), last.left() - rect.right())
    return gap < 1.5 * max(last.height(), rect.height())


def span_boxes(words: Sequence[Word], text: str,
               spans: Sequence[tuple[int, int]]) -> list[tuple[int, QRectF]]:
    """``(page, rect)`` of the changed characters.

    ``spans`` are char ranges of ``text`` (the words' text, space-joined).
    Each word is found in ``text`` in order; a span's part inside it becomes a
    sub-rect of the word box, proportional to the character offsets. A word
    that is not found (the text was normalised differently) gets no rect — a
    guessed position would mark the wrong letters. When the spans cover every
    placed word entirely there is nothing to pinpoint: ``[]``.
    """
    boxes: list[tuple[int, QRectF]] = []
    whole, cursor = True, 0
    for word in words:
        start = text.find(word.text, cursor) if word.text else -1
        if start < 0:
            continue
        end = cursor = start + len(word.text)
        covered = 0
        width = word.x1 - word.x0
        for s, e in spans:
            lo, hi = max(s, start), min(e, end)
            if lo < hi:
                covered += hi - lo
                x0 = word.x0 + width * (lo - start) / (end - start)
                x1 = word.x0 + width * (hi - start) / (end - start)
                boxes.append((word.page, QRectF(x0, word.y0, x1 - x0, word.y1 - word.y0)))
        whole = whole and covered >= end - start
    return [] if whole else boxes


def union(rects: Sequence[QRectF]) -> QRectF:
    out = QRectF()
    for rect in rects:
        out = rect if out.isNull() else out.united(rect)
    return out


class PageSlot:
    """One page in the scene: placeholder + label, then its image (z 0 / 1)."""

    __slots__ = ("_scene", "rect", "placeholder", "label", "pixmap", "bucket", "error", "retried")

    def __init__(self, scene: QGraphicsScene, rect: QRectF, label: str) -> None:
        self._scene = scene
        self.rect = rect
        self.placeholder = scene.addRect(rect)
        self.placeholder.setZValue(0)
        self.label = QGraphicsTextItem(label)
        self.label.setTextWidth(max(40.0, rect.width() - 48))
        self.label.setPos(rect.left() + 24, rect.top() + 24)
        self.label.setZValue(0.5)
        scene.addItem(self.label)
        self.pixmap: QGraphicsPixmapItem | None = None
        #: The scale bucket of the image shown (None: no image).
        self.bucket: float | None = None
        #: Why the page could not be rendered (None: no failure).
        self.error: str | None = None
        #: A first failure was already retried (the second one is shown).
        self.retried = False

    def set_image(self, image: QImage, scale_bucket: float) -> None:
        if self.pixmap is None:
            self.pixmap = QGraphicsPixmapItem()
            self.pixmap.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
            self.pixmap.setZValue(1)
            self.pixmap.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self._scene.addItem(self.pixmap)
        self.pixmap.setPixmap(QPixmap.fromImage(image))
        self.pixmap.setScale(self.rect.width() / image.width())  # pixels back to points
        self.pixmap.setPos(self.rect.topLeft())
        self.bucket = scale_bucket

    def drop_image(self) -> None:
        if self.pixmap is not None:
            self._scene.removeItem(self.pixmap)
        self.pixmap, self.bucket = None, None

    def set_label(self, text: str) -> None:
        self.label.setPlainText(text)

    def recolour(self, tokens: theme.Tokens, edge: QPen) -> None:
        self.placeholder.setBrush(QBrush(QColor(tokens.surface2)))
        self.placeholder.setPen(edge)
        self.label.setDefaultTextColor(QColor(tokens.bad if self.error else tokens.muted))

    def remove(self) -> None:
        self.drop_image()
        self._scene.removeItem(self.placeholder)
        self._scene.removeItem(self.label)


#: Padding of the focus ring around a difference, in points.
RING_PAD = 3.0


class HighlightsMixin:
    """DocView's overlay half: verdict boxes, changed characters, focus ring.

    Needs from the view: ``scene()``, ``_pages`` (PageSlot list), ``_page_at``,
    ``_visible_scene_rect``, ``centerOn``, ``_schedule`` and ``_refresh_minimap``
    (called whenever what is drawn changes).
    """

    def _init_highlights(self) -> None:
        self._diffs: dict[int, list[HighlightItem]] = {}
        self._marks: dict[int, list[CharMark]] = {}
        self._items: list[tuple[Judged, str]] = []
        self._show_done = False
        self._focused: int | None = None
        self._ring = QGraphicsRectItem()
        self._ring.setZValue(3)
        self._ring.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self._ring.setVisible(False)
        self.scene().addItem(self._ring)

    def set_highlights(self, items: list[tuple[Judged, str]]) -> None:
        """Replace the overlays: ``(judged, side)`` each; ``side`` is "left"
        (the target: ``diff.left`` words) or "right" (the version: ``diff.right``)."""
        self._items = list(items)
        self._layout_highlights()
        self._focused = None
        self._ring.setVisible(False)

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

    def highlight_items(self, diff_id: int) -> list[HighlightItem]:
        return list(self._diffs.get(diff_id, ()))

    def char_marks(self, diff_id: int) -> list[CharMark]:
        return list(self._marks.get(diff_id, ()))

    def difference_rect(self, diff_id: int) -> QRectF:
        """Scene rect of a difference: its boxes on the first page it touches."""
        items = self._diffs.get(diff_id, [])
        if not items:
            return QRectF()
        first = self._page_at(items[0].rect().center().y())
        return union([i.rect() for i in items if self._page_at(i.rect().center().y()) == first])

    def focus_difference(self, diff_id: int, *, reveal: bool = False) -> None:
        """Ring ``diff_id`` and scroll it into the middle of the view when it
        is not wholly on screen — always with ``reveal`` (Enter in the list)."""
        if not self._ring_around(diff_id):
            return
        if reveal or not self._visible_scene_rect().contains(self._ring.rect()):
            self.centerOn(self._ring.rect().center())
        self._schedule()

    def _ring_around(self, diff_id: int) -> bool:
        rect = self.difference_rect(diff_id)
        if rect.isNull():
            self._focused = None
            self._ring.setVisible(False)
            return False
        self._focused = diff_id
        self._ring.setRect(rect.adjusted(-RING_PAD, -RING_PAD, RING_PAD, RING_PAD))
        self._ring.setVisible(True)
        return True

    def focused_difference(self) -> int | None:
        return self._focused

    def focus_ring(self) -> QGraphicsRectItem:
        return self._ring

    def _clear_items(self) -> None:
        for group in (self._diffs, self._marks):
            for items in group.values():
                for item in items:
                    self.scene().removeItem(item)
        self._diffs, self._marks = {}, {}

    def _clear_highlights(self) -> None:
        self._items = []
        self._clear_items()
        self._focused = None
        self._ring.setVisible(False)
        self._refresh_minimap()

    def _recolour_highlights(self, _tokens: theme.Tokens) -> None:
        """Re-style after a theme switch (on-page colours are PAPER values, R13)."""
        for items in self._diffs.values():
            for item in items:
                style_highlight(item)
        for marks in self._marks.values():
            for mark in marks:
                mark.recolour()
        ring = QPen(_paper("accent"), 2.0)
        ring.setCosmetic(True)
        self._ring.setPen(ring)
        self._ring.setBrush(Qt.BrushStyle.NoBrush)
