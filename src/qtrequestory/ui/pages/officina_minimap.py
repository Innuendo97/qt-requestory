"""The minimap beside each document's scroll bar (spec §7.1, approved draft
"caso-fase2")::

    ┌──────────────────────────┬─┬─┐
    │ page 1                   │▮│▲│   ▮ a segment per difference, at its
    │                          │ │ │     relative height in the document,
    │ page 2                   │▮│█│     coloured by verdict
    │                          │▯│ │   ▯ the part of the document on screen
    └──────────────────────────┴─┴─┘

One segment for every difference the viewer draws on that side, at the
vertical position of its words in the whole document (its top and bottom over
the scene height), in the verdict strip's colours (``officina_strip``: the
chrome follows the theme, R13): regressione red, da fare amber, non risolta
amber with a red band down its left edge, in corso blue, da verificare a
green **dashed** outline, fatta green — shown only where the viewer shows it
(target side, "Mostra fatte"), tollerata hatched grey. Variables and noise
have no verdict and no segment (as in the strip). A faint band marks what is
on screen.

A click on a segment (or within a few pixels of one) emits
:attr:`MiniMap.diff_chosen` (the view goes to that difference); elsewhere
:attr:`MiniMap.position_chosen` with the fraction of the document (the view
centres that point). :func:`document_segments` is the pure half.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QToolTip, QWidget

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import Judged
from qtrequestory.ui.pages.officina_overlays import line_boxes
from qtrequestory.ui.pages.officina_strip import paint_segment
from qtrequestory.ui.pages.officina_verdict_style import LOOKS, WORST_ORDER, state_of

__all__ = ["MINIMAP_W", "MiniMap", "Segment", "document_segments"]

#: Width of the minimap, in logical pixels (between the page and the scroll bar).
MINIMAP_W = 12
#: A segment is at least this tall, so one line in a 60-page document shows.
MIN_SEG_H = 5.0
#: A click this close (pixels) to a segment picks it.
HIT_SLACK = 3.0
#: Horizontal inset of the segments inside the minimap.
INSET = 2.0
#: States without a segment: variables and noise (no verdict). The AS-IS view's neutral
#: "nessuno" keeps its grey segment: it still says where a difference is.
_NO_SEGMENT = frozenset({"variabile", "rumore"})
#: Paint order: the mildest first, so the worst state is on top where they overlap.
_PAINT_RANK = {state: i for i, state in enumerate(reversed((*WORST_ORDER, "nessuno", "tollerata")))}


@dataclass(frozen=True)
class Segment:
    """One difference on the minimap: ``top`` / ``bottom`` are 0..1 of the document height."""

    diff_id: int
    state: str
    top: float
    bottom: float
    page: int  # 0-based, of its first words


def document_segments(items: Sequence[tuple[Judged, str]], *, show_done: bool,
                      page_tops: Sequence[float], height: float) -> list[Segment]:
    """The segments of ``items`` — ``(judged, side)`` as ``DocView.set_highlights``
    takes them — for a document whose pages start at scene ``page_tops`` and
    whose scene is ``height`` points tall; in document order."""
    out: list[Segment] = []
    if height <= 0:
        return out
    for judged, side in items:
        state = state_of(judged)
        if state in _NO_SEGMENT or (state == "fatta" and (side != "left" or not show_done)):
            continue
        words = judged.diff.left if side == "left" else judged.diff.right
        spans = [(page_tops[page] + rect.top(), page_tops[page] + rect.bottom(), page)
                 for page, rect in line_boxes(words) if 0 <= page < len(page_tops)]
        if not spans:
            continue
        top = min(s[0] for s in spans)
        bottom = max(s[1] for s in spans)
        first = min(spans)[2]
        out.append(Segment(judged.diff.id, state, max(0.0, top / height),
                           min(1.0, bottom / height), first))
    return sorted(out, key=lambda s: (s.top, s.diff_id))


class MiniMap(QWidget):
    """The strip of segments beside one ``DocView`` (a child of the view)."""

    diff_chosen = Signal(int)        # Diff.id
    position_chosen = Signal(float)  # 0..1 of the document height

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._segments: list[Segment] = []
        self._band = (0.0, 0.0)
        self.setFixedWidth(MINIMAP_W)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        theme.signals.changed.connect(self.update)

    # -- content -------------------------------------------------------------

    def set_segments(self, segments: Sequence[Segment]) -> None:
        self._segments = list(segments)
        self.update()

    def segments(self) -> list[Segment]:
        return list(self._segments)

    def set_band(self, top: float, bottom: float) -> None:
        """The part of the document on screen (0..1)."""
        band = (max(0.0, min(1.0, top)), max(0.0, min(1.0, bottom)))
        if band != self._band:
            self._band = band
            self.update()

    def band(self) -> tuple[float, float]:
        return self._band

    def segment_rect(self, segment: Segment) -> QRectF:
        h = float(self.height())
        tall = max(MIN_SEG_H, (segment.bottom - segment.top) * h)
        top = min(max(0.0, segment.top * h), max(0.0, h - tall))
        return QRectF(INSET, top, self.width() - 2 * INSET, tall)

    def segment_at(self, y: float) -> Segment | None:
        """The segment under ``y`` (the nearest within :data:`HIT_SLACK`), if any."""
        best: tuple[float, int, Segment] | None = None
        for segment in self._segments:
            rect = self.segment_rect(segment)
            distance = 0.0 if rect.top() <= y <= rect.bottom() else min(
                abs(y - rect.top()), abs(y - rect.bottom()))
            if distance <= HIT_SLACK:
                key = (distance, -_PAINT_RANK.get(segment.state, 0), segment)
                if best is None or key[:2] < best[:2]:
                    best = key
        return best[2] if best is not None else None

    def tooltip_at(self, y: float) -> str:
        segment = self.segment_at(y)
        if segment is None:
            return strings.MINIMAPPA_TIP
        return strings.MINIMAPPA_SEGMENT_TIP.format(label=LOOKS[segment.state].label,
                                                    page=segment.page + 1)

    # -- Qt ------------------------------------------------------------------

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        return QSize(MINIMAP_W, 100)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt naming
        t = theme.tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(t.surface2))
        top, bottom = self._band
        if bottom > top:
            shade = QColor(t.muted)
            shade.setAlphaF(0.18)
            painter.fillRect(QRectF(0, top * self.height(), self.width(),
                                    (bottom - top) * self.height()), shade)
        for segment in sorted(self._segments, key=lambda s: _PAINT_RANK.get(s.state, 0)):
            paint_segment(painter, self.segment_rect(segment), segment.state, band_left=True)
        painter.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.button() != Qt.MouseButton.LeftButton or self.height() <= 0:
            super().mousePressEvent(event)
            return
        y = event.position().y()
        segment = self.segment_at(y)
        if segment is not None:
            self.diff_chosen.emit(segment.diff_id)
        else:
            self.position_chosen.emit(max(0.0, min(1.0, y / self.height())))
        event.accept()

    def event(self, event) -> bool:  # noqa: D102 - per-segment tooltips
        if event.type() == QEvent.Type.ToolTip:
            QToolTip.showText(event.globalPos(), self.tooltip_at(event.pos().y()), self)
            return True
        return super().event(event)
