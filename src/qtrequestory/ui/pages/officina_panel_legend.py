"""The legend behind «?» of the side panel (phase 2.5, D15): a popover that
shows every verdict look as it is drawn on the page (a sample box or line
in the look's paper colours, beside the list's pill), the type icons with
their whole names, the zone rails' colours and the keys. Esc or a click
outside closes it.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QVBoxLayout, QWidget

from qtrequestory.ui import strings, theme
from qtrequestory.ui.pages.officina_overlays import look_colours, paper
from qtrequestory.ui.pages.officina_progress import glyph_html
from qtrequestory.ui.pages.officina_types import MAIN_ZONES, TYPE_ORDER, TYPES, ZONE_TOKENS, zone_name
from qtrequestory.ui.pages.officina_verdict_style import LOOKS, Look
from qtrequestory.ui.pages.officina_widgets import pill

__all__ = ["LegendPopover", "LookSample", "legend_states"]

#: The states the legend shows, in the list's order of importance.
_STATES = ("regressione", "non_risolta", "da_fare", "in_corso", "da_verificare", "fatta", "tollerata",
           "variabile", "rumore", "arredo")


def legend_states() -> tuple[str, ...]:
    return _STATES


class LookSample(QWidget):
    """A few grey "words" on white paper with the look drawn over them."""

    def __init__(self, look: Look | None = None, *, rail: str | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.look, self.rail = look, rail
        self.setFixedSize(46, 16)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), paper("surface"))
        painter.setPen(QPen(paper("border"), 1.0))
        painter.drawRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5))
        if self.rail is not None:
            painter.fillRect(QRectF(3, 2, 3, 12), paper(self.rail))
            painter.fillRect(QRectF(10, 6, 30, 4), paper("neutral_bg"))
            return
        word = QRectF(9, 4, 28, 8)
        painter.fillRect(word, paper("neutral_bg"))
        fill, edge = look_colours(self.look)
        pen = QPen(edge, self.look.width)
        if self.look.dotted:  # rumore, arredo: finer than dashed (D1, palette B)
            pen.setStyle(Qt.PenStyle.DotLine)
        elif self.look.dash:
            pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        if self.look.underline:
            painter.drawLine(word.bottomLeft() + QPointF(0, 2), word.bottomRight() + QPointF(0, 2))
            return
        if fill is not None:
            painter.fillRect(word.adjusted(-2, -2, 2, 2), fill)
            painter.fillRect(word, paper("neutral_bg").darker(105))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(word.adjusted(-2, -2, 2, 2))


def _title(text: str) -> QLabel:
    label = QLabel(text)
    theme.set_role(label, "section")
    return label


class LegendPopover(QFrame):
    """The popover (a ``Qt.Popup``: closes on Esc and on a click outside)."""

    def __init__(self, keys_html: str, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("panelLegend")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setAccessibleName(strings.PANNELLO_LEGEND_NAME)
        box = QVBoxLayout(self)
        box.setContentsMargins(theme.SPACE[2], theme.SPACE[2], theme.SPACE[2], theme.SPACE[2])
        box.setSpacing(theme.SPACE[1])
        box.addWidget(_title(strings.PANNELLO_LEGEND_VERDICTS))
        grid = QGridLayout()
        grid.setHorizontalSpacing(theme.SPACE[1])
        grid.setVerticalSpacing(2)
        for row, state in enumerate(_STATES):
            look = LOOKS[state]
            label = pill("", look.pill)
            label.setTextFormat(Qt.TextFormat.RichText)
            label.setText(glyph_html(f"{look.icon} {look.label}"))
            grid.addWidget(LookSample(look), row // 2, (row % 2) * 2)
            grid.addWidget(label, row // 2, (row % 2) * 2 + 1, Qt.AlignmentFlag.AlignLeft)
        box.addLayout(grid)
        box.addWidget(_title(strings.PANNELLO_LEGEND_TYPES))
        types = QGridLayout()
        types.setHorizontalSpacing(theme.SPACE[1])
        types.setVerticalSpacing(2)
        for row, tipo in enumerate(TYPE_ORDER):
            info = TYPES[tipo]
            icon = QLabel(glyph_html(info.icon))
            icon.setTextFormat(Qt.TextFormat.RichText)
            icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icon.setFixedWidth(26)
            theme.set_role(icon, "typeBadge")
            text = QLabel(info.tip)
            text.setWordWrap(True)
            types.addWidget(icon, row, 0)
            types.addWidget(text, row, 1)
        box.addLayout(types)
        box.addWidget(_title(strings.PANNELLO_LEGEND_ZONES))
        zones = QGridLayout()
        zones.setHorizontalSpacing(theme.SPACE[1])
        for index, zone in enumerate((*MAIN_ZONES, "numero_pagina")):
            zones.addWidget(LookSample(rail=ZONE_TOKENS[zone]), index // 2, (index % 2) * 2)
            name = zone_name(zone) if zone != "numero_pagina" else strings.PANNELLO_GROUP_ARREDO
            zones.addWidget(QLabel(name), index // 2, (index % 2) * 2 + 1)
        box.addLayout(zones)
        box.addWidget(_title(strings.PANNELLO_LEGEND_KEYS))
        keys = QLabel(keys_html)
        keys.setWordWrap(True)
        keys.setTextFormat(Qt.TextFormat.RichText)
        theme.set_role(keys, "diffLegend")
        self.keys = keys
        box.addWidget(keys)
        self.setFixedWidth(430)

    def open_at(self, anchor: QWidget) -> None:
        """Above ``anchor`` (the «?» button), inside the screen."""
        self.adjustSize()
        corner = anchor.mapToGlobal(QPoint(anchor.width(), 0))
        pos = QPoint(corner.x() - self.width(), corner.y() - self.height() - 4)
        screen = anchor.screen().availableGeometry() if anchor.screen() else None
        if screen is not None:
            pos.setX(max(screen.left(), min(pos.x(), screen.right() - self.width())))
            pos.setY(max(screen.top(), pos.y()))
        self.move(pos)
        self.show()
        self.setFocus(Qt.FocusReason.PopupFocusReason)

