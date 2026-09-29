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
The view's half that places them and rings the focused difference is
``officina_highlights``.
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
from qtrequestory.ui.pages.officina_verdict_style import Look

if TYPE_CHECKING:
    from qtrequestory.ui.contracts import Word

__all__ = ["CharMark", "HighlightItem", "PageSlot", "line_boxes", "look_colours", "paper",
           "shown_words", "span_boxes", "style_highlight"]

#: Padding around a word box, in points.
PAD = 1.0
#: The token values of everything drawn on the page (white paper in both themes, R13).
PAPER = theme.LIGHT
#: Width of the ink underline under the changed characters, in pixels (R14).
CHAR_UNDERLINE = 2.0


def paper(token: str) -> QColor:
    return QColor(getattr(PAPER, token))


def look_colours(look: Look) -> tuple[QColor | None, QColor]:
    """(fill or None, edge) of ``look`` on the page (:data:`PAPER` values)."""
    return (paper(look.fill) if look.fill else None), paper(look.edge)


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
    pen.setStyle(Qt.PenStyle.DotLine if item.look.dotted
                 else Qt.PenStyle.DashLine if item.look.dash else Qt.PenStyle.SolidLine)
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
        self.setBrush(QBrush(paper("mark_yellow")))
        pen = QPen(paper("text"), CHAR_UNDERLINE)
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


def shown_words(words: Iterable[Word], sizes: Sequence[tuple[float, float]]) -> tuple[Word, ...]:
    """``words`` without the ones nobody can see (spec §4.6): flagged
    ``invisible`` or ``off_page`` by the extraction (read defensively: an
    extractor may not set them) or whose box lies wholly outside its page
    (``sizes``: width and height in points; a word of an unknown page stays)."""
    out = []
    for w in words:
        if getattr(w, "invisible", False) or getattr(w, "off_page", False):
            continue
        if 0 <= w.page < len(sizes):
            width, height = sizes[w.page]
            if w.x1 <= 0 or w.y1 <= 0 or w.x0 >= width or w.y0 >= height:
                continue
        out.append(w)
    return tuple(out)


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
