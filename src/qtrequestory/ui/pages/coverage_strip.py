"""The 30-day coverage calendar of an environment card, and its legend.

The server keeps its daily files until somebody purges it by hand, and it
publishes a day without traffic as a 0-byte file. So a day that is not in the
local archive is one of three things, and the calendar tells them apart:

* green, ``present``: the log is here;
* amber, ``pending``: still on the server, the next sync downloads it;
* red, ``lost``: the server listed it once and purged it before it was
  downloaded, so it cannot be recovered;
* grey, ``empty``: a 0-byte day, nobody called (weekends, holidays, svil);
* dashed grey, ``unknown``: no file and no listing ever mentioned it (before
  the listing memory began): nothing can be said;
* ``weekend``: a weekend nothing is known about, ``today`` (dashed outline,
  its log arrives tomorrow), ``before`` (empty outline: the archive had not
  started yet).

The classification (:func:`day_kinds`) is plain Python over the core's
``CoverageDays``; the widgets only paint it, with colours from
``theme.tokens()``, and repaint on a theme switch. The legend lists only the
kinds some card actually draws.
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta

from PySide6.QtCore import QEvent, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QToolTip, QWidget

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import CoverageDays

__all__ = [
    "BEFORE", "EMPTY", "LOST", "PENDING", "PRESENT", "TODAY", "UNKNOWN", "WEEKEND",
    "CoverageLegend", "CoverageStrip", "day_kinds", "tooltip",
]

PRESENT = "present"
EMPTY = "empty"
PENDING = "pending"
LOST = "lost"
UNKNOWN = "unknown"
WEEKEND = "weekend"
TODAY = "today"
BEFORE = "before"

DAYS = 30
SQUARE_H = 12
GAP = 2
RADIUS = 2.0
SWATCH = 9
#: Opacity of the ``muted`` edge that keeps a light square visible on a card.
EDGE_ALPHA = 0.45
#: Opacity of the ``muted`` fill of an ``empty`` day: a real grey, darker
#: than the weekend's ``neutral_bg``.
EMPTY_ALPHA = 0.4

_WHAT = {
    PRESENT: strings.SYNC_COVERAGE_PRESENT,
    EMPTY: strings.SYNC_COVERAGE_EMPTY,
    PENDING: strings.SYNC_COVERAGE_PENDING,
    LOST: strings.SYNC_COVERAGE_LOST,
    UNKNOWN: strings.SYNC_COVERAGE_UNKNOWN,
    WEEKEND: strings.SYNC_COVERAGE_WEEKEND,
    TODAY: strings.SYNC_COVERAGE_TODAY,
    BEFORE: strings.SYNC_COVERAGE_BEFORE,
}


def day_kinds(cov: CoverageDays | None, today: date, days: int = DAYS) -> list[tuple[date, str]]:
    """``[(day, kind), ...]`` oldest first, ``days`` long, ending with today.

    The core decides: a local file with calls is ``present`` (weekend or
    not), and its ``pending``/``lost``/``empty``/``unknown`` sets are drawn
    as such, weekends included. What is left is a weekend nothing is known
    about (``weekend``) or a weekday before the archive began (``before``).
    """
    if cov is None:
        cov = CoverageDays(present=frozenset())
    by_kind = ((PRESENT, cov.present), (PENDING, set(cov.pending)), (LOST, set(cov.lost)),
               (EMPTY, cov.empty), (UNKNOWN, set(cov.unknown)))
    out = []
    for offset in range(days - 1, -1, -1):
        day = today - timedelta(days=offset)
        if day == today:
            kind = TODAY
        else:
            kind = next((k for k, members in by_kind if day in members),
                        WEEKEND if day.weekday() >= 5 else BEFORE)
        out.append((day, kind))
    return out


def tooltip(day: date, kind: str) -> str:
    """"22/09/2026: sul server: da scaricare"."""
    return strings.SYNC_COVERAGE_TIP.format(day=day.strftime("%d/%m/%Y"), what=_WHAT[kind])


def _pen(colour: QColor, *, dashed: bool = False) -> QPen:
    pen = QPen(colour, 1.0)
    if dashed:
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setDashPattern([2.0, 2.0])
    return pen


def _paint_square(painter: QPainter, rect: QRectF, kind: str) -> None:
    """One square in the theme's colours; shared by the strip and the legend."""
    t = theme.tokens()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    edge = QColor(t.muted)
    edge.setAlphaF(EDGE_ALPHA)
    inner = rect.adjusted(0.5, 0.5, -0.5, -0.5)
    if kind in (PRESENT, PENDING, LOST):
        painter.setBrush(QColor({PRESENT: t.ok, PENDING: t.warn, LOST: t.bad}[kind]))
    elif kind == EMPTY:
        fill = QColor(t.muted)
        fill.setAlphaF(EMPTY_ALPHA)
        painter.setBrush(fill)
    elif kind in (WEEKEND, UNKNOWN):  # neutral_bg alone vanishes on a light card
        painter.setBrush(QColor(t.neutral_bg))
        painter.setPen(_pen(QColor(t.muted) if kind == UNKNOWN else edge,
                            dashed=kind == UNKNOWN))
        rect = inner
    else:  # TODAY, BEFORE: an outline only
        painter.setPen(_pen(QColor(t.muted if kind == TODAY else t.border),
                            dashed=kind == TODAY))
        rect = inner
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
    """"■ log presente  ■ nessuna chiamata  ■ da scaricare  …", only what is drawn."""

    ITEMS = (
        (PRESENT, strings.SYNC_LEGEND_PRESENT),
        (EMPTY, strings.SYNC_LEGEND_EMPTY),
        (PENDING, strings.SYNC_LEGEND_PENDING),
        (LOST, strings.SYNC_LEGEND_LOST),
        (UNKNOWN, strings.SYNC_LEGEND_UNKNOWN),
        (WEEKEND, strings.SYNC_LEGEND_WEEKEND),
        (TODAY, strings.SYNC_LEGEND_TODAY),
        (BEFORE, strings.SYNC_LEGEND_BEFORE),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SPACE[2])
        self.labels: list[QLabel] = []
        #: kind -> its swatch-and-label box: hiding the box leaves no gap.
        self._items: dict[str, QWidget] = {}
        for kind, text in self.ITEMS:
            item = QWidget()
            box = QHBoxLayout(item)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(theme.SPACE[1])
            box.addWidget(_Swatch(kind), 0, Qt.AlignmentFlag.AlignVCenter)
            label = QLabel(text)
            theme.set_role(label, "muted")
            self.labels.append(label)
            box.addWidget(label)
            row.addWidget(item)
            self._items[kind] = item
        row.addStretch(1)
        self.set_kinds({PRESENT, TODAY})

    def set_kinds(self, kinds: Iterable[str]) -> None:
        """Explain only the squares some card draws right now."""
        shown = set(kinds)
        for kind, item in self._items.items():
            item.setVisible(kind in shown)

    def shown(self) -> list[str]:
        """The texts of the items not hidden, in legend order."""
        return [label.text() for label, item in zip(self.labels, self._items.values())
                if not item.isHidden()]
