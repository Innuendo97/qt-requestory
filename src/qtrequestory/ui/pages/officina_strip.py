"""The verdict strip of the case view's progress bar (spec §7.1).

One segment per judged difference that has a verdict (variables and noise
have none), in document order, drawn like the ``coverage_strip`` squares with
theme tokens (the chrome follows the theme, R13); a click emits the
difference's id, a tooltip names its verdict, page and text. Split from
``officina_progress`` (size).
"""
from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QEvent, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import Judged
from qtrequestory.ui.pages.officina_verdict_style import LOOKS, state_of

__all__ = ["SEGMENT_LOOKS", "VerdictStrip", "document_order", "paint_segment"]

#: Height of the red band on top of a "non risolta" segment.
BAND_H = 3.0

SEGMENT_H = 12
GAP = 2
RADIUS = 2.0
#: Below this segment width the gaps go: a long document stays one readable bar.
MIN_GAPPED_W = 4.0
STRIP_MAX_W = 480
SNIPPET = 60


def _position(j: Judged) -> tuple[float, float, float]:
    words = j.diff.left or j.diff.right
    if not words:
        return (float("inf"), 0.0, 0.0)  # no words (a link, an attribute): at the end
    w = words[0]
    return (float(w.page), w.y0, w.x0)


def document_order(judged: Sequence[Judged]) -> list[Judged]:
    """The judged differences with a verdict, by page then top then left
    (target words first, the generated ones for an added text)."""
    ranked = [(_position(j), i, j) for i, j in enumerate(judged) if j.verdict is not None]
    return [j for _pos, _i, j in sorted(ranked, key=lambda r: (r[0], r[1]))]


class VerdictStrip(QWidget):
    """One segment per judged difference, in document order; click = go there."""

    diff_selected = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items: list[Judged] = []
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMaximumWidth(STRIP_MAX_W)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(strings.AVANZAMENTO_STRIP_TIP)
        theme.signals.changed.connect(self.update)

    def set_judged(self, judged: Sequence[Judged]) -> None:
        self._items = document_order(judged)
        self.update()

    def segments(self) -> list[tuple[int, str]]:
        """``[(diff id, look state), ...]`` left to right."""
        return [(j.diff.id, state_of(j)) for j in self._items]

    def _gap(self) -> float:
        n = len(self._items)
        width = (self.width() - GAP * (n - 1)) / n if n else 0
        return GAP if width >= MIN_GAPPED_W else 0.0

    def segment_rect(self, index: int) -> QRectF:
        n = len(self._items)
        gap = self._gap()
        width = (self.width() - gap * (n - 1)) / n if n else 0
        return QRectF(index * (width + gap), 0, width, SEGMENT_H)

    def index_at(self, x: float) -> int | None:
        gap = self._gap()
        for i in range(len(self._items)):
            rect = self.segment_rect(i)
            if rect.left() <= x < rect.right() + gap:
                return i
        return None

    def tooltip_at(self, index: int) -> str:
        j = self._items[index]
        label = LOOKS[state_of(j)].label
        text = " ".join((j.diff.left_text or j.diff.right_text or j.diff.detail).split())
        if len(text) > SNIPPET:
            text = text[:SNIPPET - 1] + "…"
        words = j.diff.left or j.diff.right
        if not words:
            return strings.AVANZAMENTO_SEGMENT_TIP_NO_PAGE.format(label=label, text=text)
        return strings.AVANZAMENTO_SEGMENT_TIP.format(label=label, page=words[0].page + 1, text=text)

    # -- Qt ----------------------------------------------------------------

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        return QSize(STRIP_MAX_W, SEGMENT_H)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        return QSize(40, SEGMENT_H)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for i, j in enumerate(self._items):
            paint_segment(painter, self.segment_rect(i), state_of(j))
        painter.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.button() == Qt.MouseButton.LeftButton:
            index = self.index_at(event.position().x())
            if index is not None:
                self.diff_selected.emit(self._items[index].diff.id)
                return
        super().mousePressEvent(event)

    def event(self, event) -> bool:  # noqa: D102 - per-segment tooltips
        if event.type() == QEvent.Type.ToolTip:
            index = self.index_at(event.pos().x())  # a QHelpEvent
            if index is None:
                QToolTip.showText(event.globalPos(), strings.AVANZAMENTO_STRIP_TIP, self)
            else:
                QToolTip.showText(event.globalPos(), self.tooltip_at(index), self)
            return True
        return super().event(event)


#: state -> (fill token, edge token, dashed edge): the strong colours of the
#: coverage strip; "non risolta" is a da-fare square with a red band on top.
SEGMENT_LOOKS: dict[str, tuple[str | None, str | None, bool]] = {
    "regressione": ("bad", None, False),
    "non_risolta": ("warn", None, False),  # plus a red band on top, below
    "da_fare": ("warn", None, False),
    "in_corso": ("progress", None, False),
    "da_verificare": (None, "ok", True),
    "fatta": ("ok", None, False),
    "tollerata": ("neutral_bg", "muted", False),  # hatched below
}


def paint_segment(painter: QPainter, rect: QRectF, state: str, *, band_left: bool = False) -> None:
    """One segment of ``state`` in ``rect`` (also the minimap's: there the
    "non risolta" band runs down the left edge, ``band_left``)."""
    t = theme.tokens()
    fill, edge, dashed = SEGMENT_LOOKS.get(state, ("neutral_bg", "muted", False))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(getattr(t, fill)) if fill else Qt.BrushStyle.NoBrush)
    if edge:
        pen = QPen(QColor(getattr(t, edge)), 1.0)
        if dashed:
            pen.setStyle(Qt.PenStyle.DashLine)
            pen.setDashPattern([2.0, 2.0])
        painter.setPen(pen)
        rect = rect.adjusted(0.5, 0.5, -0.5, -0.5)
    painter.drawRoundedRect(rect, RADIUS, RADIUS)
    if state == "non_risolta":
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(t.bad))
        band = (QRectF(rect.left(), rect.top(), BAND_H, rect.height()) if band_left
                else QRectF(rect.left(), rect.top(), rect.width(), BAND_H))
        painter.drawRoundedRect(band, 1.0, 1.0)
    if state == "tollerata":
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(t.muted), Qt.BrushStyle.BDiagPattern))
        painter.drawRoundedRect(rect, RADIUS, RADIUS)
