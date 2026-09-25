"""Scene pieces of the Officina viewer: page slots, highlight boxes, colours.

A :class:`PageSlot` is one page of the column: a placeholder (``surface2``)
with a label, and the rendered image once there is one.


A difference is drawn as one box per run of words on a line (not one box per
word), filled with the kind's soft token (``ok_bg``/``bad_bg``/``warn_bg``) and
outlined with its strong one (``ok``/``bad``/``warn``). The fill is painted in
*multiply* mode, so the page's black text stays black under it; a dark theme's
soft tokens are dark, so there the fill is also made translucent, or the page
would turn nearly black. Everything is re-derived from ``theme.tokens()`` when
the theme changes (the viewer calls :func:`style_highlight` again).
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsTextItem,
)

from qtrequestory.ui import theme

if TYPE_CHECKING:
    from qtrequestory.officina.compare.extract_pdf import Word

__all__ = ["HighlightItem", "HighlightsMixin", "PageSlot", "kind_colours", "line_boxes", "style_highlight", "union"]

#: Kind -> (soft token, strong token). "moved" is phase 2 (spec §7: blue).
_KIND_TOKENS = {
    "added": ("ok_bg", "ok"),
    "removed": ("bad_bg", "bad"),
    "changed": ("warn_bg", "warn"),
    "moved": ("selection", "accent"),
}
#: Padding around a word box, in points.
PAD = 1.0
#: Translucency of a dark soft token over the (always white) page.
_DARK_FILL_ALPHA = 110


def kind_colours(kind: str) -> tuple[QColor, QColor]:
    """(fill, border) of a difference ``kind`` in the current theme."""
    tokens = theme.tokens()
    soft, strong = _KIND_TOKENS.get(kind, ("neutral_bg", "muted"))
    fill = QColor(getattr(tokens, soft))
    if fill.lightnessF() < 0.5:
        fill.setAlpha(_DARK_FILL_ALPHA)
    return fill, QColor(getattr(tokens, strong))


class HighlightItem(QGraphicsRectItem):
    """One highlight box; ``diff_id`` is the ``Difference.id`` it belongs to."""

    def __init__(self, rect: QRectF, diff_id: int, kind: str) -> None:
        super().__init__(rect)
        self.diff_id = diff_id
        self.kind = kind
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)  # the view handles clicks
        self.setZValue(2)
        style_highlight(self)

    def paint(self, painter: QPainter, option, widget=None) -> None:  # noqa: D102
        painter.save()
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Multiply)
        painter.fillRect(self.rect(), self.brush())
        painter.restore()
        painter.setPen(self.pen())
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(self.rect())


def style_highlight(item: HighlightItem) -> None:
    fill, border = kind_colours(item.kind)
    item.setBrush(QBrush(fill))
    pen = QPen(border, 1.0)
    pen.setCosmetic(True)
    item.setPen(pen)


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
    """DocView's overlay half: difference boxes, focus ring, their colours.

    Needs from the view: ``scene()``, ``_pages`` (PageSlot list), ``_page_at``,
    ``_visible_scene_rect``, ``centerOn`` and ``_schedule``.
    """

    def _init_highlights(self) -> None:
        self._diffs: dict[int, list[HighlightItem]] = {}
        self._focused: int | None = None
        self._ring = QGraphicsRectItem()
        self._ring.setZValue(3)
        self._ring.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self._ring.setVisible(False)
        self.scene().addItem(self._ring)

    def set_highlights(self, items: list[tuple[int, str, list[Word]]]) -> None:
        """Replace the overlays: ``(difference id, kind, words)`` each."""
        self._clear_highlights()
        for diff_id, kind, words in items:
            boxes = []
            for page, rect in line_boxes(words):
                if 0 <= page < len(self._pages):
                    origin = self._pages[page].rect.topLeft()
                    item = HighlightItem(rect.translated(origin), diff_id, kind)
                    self.scene().addItem(item)
                    boxes.append(item)
            if boxes:
                self._diffs.setdefault(diff_id, []).extend(boxes)

    def highlight_items(self, diff_id: int) -> list[HighlightItem]:
        return list(self._diffs.get(diff_id, ()))

    def difference_rect(self, diff_id: int) -> QRectF:
        """Scene rect of a difference: its boxes on the first page it touches."""
        items = self._diffs.get(diff_id, [])
        if not items:
            return QRectF()
        first = self._page_at(items[0].rect().center().y())
        return union([i.rect() for i in items if self._page_at(i.rect().center().y()) == first])

    def focus_difference(self, diff_id: int) -> None:
        """Scroll ``diff_id`` into the middle of the view and ring it."""
        rect = self.difference_rect(diff_id)
        if rect.isNull():
            self._focused = None
            self._ring.setVisible(False)
            return
        self._focused = diff_id
        self._ring.setRect(rect.adjusted(-RING_PAD, -RING_PAD, RING_PAD, RING_PAD))
        self._ring.setVisible(True)
        if not self._visible_scene_rect().contains(self._ring.rect()):
            self.centerOn(rect.center())
        self._schedule()

    def focused_difference(self) -> int | None:
        return self._focused

    def focus_ring(self) -> QGraphicsRectItem:
        return self._ring

    def _clear_highlights(self) -> None:
        for items in self._diffs.values():
            for item in items:
                self.scene().removeItem(item)
        self._diffs = {}
        self._focused = None
        self._ring.setVisible(False)

    def _recolour_highlights(self, tokens: theme.Tokens) -> None:
        for items in self._diffs.values():
            for item in items:
                style_highlight(item)
        ring = QPen(QColor(tokens.accent), 2.0)
        ring.setCosmetic(True)
        self._ring.setPen(ring)
        self._ring.setBrush(Qt.BrushStyle.NoBrush)
