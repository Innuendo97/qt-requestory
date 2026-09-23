"""The 30-day coverage calendar of an environment card, and its legend.

The local mirror is the ONLY archive — the server keeps about one day — so a
weekday missing from it is lost for good. A row of squares, one per day, makes
that invariant visible at a glance: green = the log is here, red = a weekday
that is missing, grey = weekend, dashed = today (its log arrives tomorrow).
Days before the archive began are drawn as an empty outline: there was nothing
to miss yet.

The classification (:func:`day_kinds`) is plain Python over the core's
``CoverageDays``; the widgets only paint it, with colours from
``theme.tokens()`` (existing tokens: ``ok``, ``bad``, ``neutral_bg``, ``muted``
and ``border``), and repaint on a theme switch.
"""
from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QEvent, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QToolTip, QWidget

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import CoverageDays

__all__ = [
    "BEFORE", "MISSING", "PRESENT", "TODAY", "WEEKEND",
    "CoverageLegend", "CoverageStrip", "day_kinds", "tooltip",
]

PRESENT = "present"
MISSING = "missing"
WEEKEND = "weekend"
TODAY = "today"
BEFORE = "before"

DAYS = 30
SQUARE_H = 12
GAP = 2
RADIUS = 2.0
SWATCH = 9
#: Opacity of the ``muted`` edge that keeps a weekend square visible.
WEEKEND_EDGE_ALPHA = 0.45

_WHAT = {
    PRESENT: strings.SYNC_COVERAGE_PRESENT,
    MISSING: strings.SYNC_COVERAGE_MISSING,
    WEEKEND: strings.SYNC_COVERAGE_WEEKEND,
    TODAY: strings.SYNC_COVERAGE_TODAY,
    BEFORE: strings.SYNC_COVERAGE_BEFORE,
}


def day_kinds(cov: CoverageDays | None, today: date, days: int = DAYS) -> list[tuple[date, str]]:
    """``[(day, kind), ...]`` oldest first, ``days`` long, ending with today.

    A file that exists is ``present`` even on a weekend. A weekday counts as
    ``missing`` only when the core says so (it ignores the days before the
    archive began); any other absent weekday is ``before``.
    """
    present = cov.present if cov is not None else frozenset()
    missing = set(cov.missing) if cov is not None else set()
    out = []
    for offset in range(days - 1, -1, -1):
        day = today - timedelta(days=offset)
        if day == today:
            kind = TODAY
        elif day in present:
            kind = PRESENT
        elif day.weekday() >= 5:
            kind = WEEKEND
        elif day in missing:
            kind = MISSING
        else:
            kind = BEFORE
        out.append((day, kind))
    return out


def tooltip(day: date, kind: str) -> str:
    """"22/09/2026: mancante"."""
    return strings.SYNC_COVERAGE_TIP.format(day=day.strftime("%d/%m/%Y"), what=_WHAT[kind])


def _paint_square(painter: QPainter, rect: QRectF, kind: str) -> None:
    """One square in the theme's colours; shared by the strip and the legend."""
    t = theme.tokens()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    if kind in (PRESENT, MISSING):
        painter.setBrush(QColor(t.ok if kind == PRESENT else t.bad))
    elif kind == WEEKEND:  # neutral_bg alone vanishes on a light card: add an edge
        painter.setBrush(QColor(t.neutral_bg))
        edge = QColor(t.muted)
        edge.setAlphaF(WEEKEND_EDGE_ALPHA)
        painter.setPen(QPen(edge, 1.0))
        rect = rect.adjusted(0.5, 0.5, -0.5, -0.5)
    else:
        pen = QPen(QColor(t.muted if kind == TODAY else t.border))
        pen.setWidthF(1.0)
        if kind == TODAY:
            pen.setStyle(Qt.PenStyle.DashLine)
            pen.setDashPattern([2.0, 2.0])
        painter.setPen(pen)
        rect = rect.adjusted(0.5, 0.5, -0.5, -0.5)
    painter.drawRoundedRect(rect, RADIUS, RADIUS)


class CoverageStrip(QWidget):
    """``days`` squares, oldest on the left, today on the right."""

    def __init__(self, days: int = DAYS, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._days = days
        self._kinds: list[tuple[date, str]] = day_kinds(None, date.today(), days)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        theme.signals.changed.connect(self.update)

    def set_coverage(self, cov: CoverageDays | None, today: date | None = None) -> None:
        self._kinds = day_kinds(cov, today if today is not None else date.today(), self._days)
        self.update()

    def kinds(self) -> list[tuple[date, str]]:
        return list(self._kinds)

    def square_rect(self, index: int) -> QRectF:
        n = len(self._kinds)
        width = (self.width() - GAP * (n - 1)) / n if n else 0
        return QRectF(index * (width + GAP), 0, width, SQUARE_H)

    def index_at(self, x: float) -> int | None:
        for i in range(len(self._kinds)):
            rect = self.square_rect(i)
            if rect.left() <= x < rect.right() + GAP:
                return i
        return None

    def tooltip_at(self, index: int) -> str:
        day, kind = self._kinds[index]
        return tooltip(day, kind)

    # -- Qt ----------------------------------------------------------------

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        return QSize(self._days * 8 + GAP * (self._days - 1), SQUARE_H)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        return QSize(self._days * 4 + GAP * (self._days - 1), SQUARE_H)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for i, (_day, kind) in enumerate(self._kinds):
            _paint_square(painter, self.square_rect(i), kind)
        painter.end()

    def event(self, event) -> bool:  # noqa: D102 - per-square tooltips
        if event.type() == QEvent.Type.ToolTip:
            index = self.index_at(event.pos().x())  # a QHelpEvent
            if index is None:
                QToolTip.hideText()
            else:
                QToolTip.showText(event.globalPos(), self.tooltip_at(index), self)
            return True
        return super().event(event)


class _Swatch(QWidget):
    def __init__(self, kind: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._kind = kind
        self.setFixedSize(SWATCH, SWATCH)
        theme.signals.changed.connect(self.update)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        _paint_square(painter, QRectF(0, 0, SWATCH, SWATCH), self._kind)
        painter.end()


class CoverageLegend(QWidget):
    """"■ log presente  ■ giorno feriale mancante  ■ weekend  ⬚ oggi (arriva domani)"."""

    ITEMS = (
        (PRESENT, strings.SYNC_LEGEND_PRESENT),
        (MISSING, strings.SYNC_LEGEND_MISSING),
        (WEEKEND, strings.SYNC_LEGEND_WEEKEND),
        (TODAY, strings.SYNC_LEGEND_TODAY),
        (BEFORE, strings.SYNC_LEGEND_BEFORE),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SPACE[1])
        self.labels: list[QLabel] = []
        self._before: list[QWidget] = []
        for kind, text in self.ITEMS:
            swatch = _Swatch(kind)
            row.addWidget(swatch, 0, Qt.AlignmentFlag.AlignVCenter)
            label = QLabel(text)
            theme.set_role(label, "muted")
            self.labels.append(label)
            row.addWidget(label)
            row.addSpacing(theme.SPACE[1])
            if kind == BEFORE:
                self._before = [swatch, label]
        row.addStretch(1)
        self.set_before_visible(False)

    def set_before_visible(self, visible: bool) -> None:
        """The outline square is explained only when some card draws one."""
        for widget in self._before:
            widget.setVisible(visible)
