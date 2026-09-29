"""The chrome of the side panel of the case view (phase 2.5, spec §5, D15,
draft "f25-caso-v2", screens 1 and 2)::

    open (292 px)                              collapsed (40 px)
    [Da guardare 4] [ Verif. 0 ] [ Fatte 0 ]      ❮
    [   Toll. 0   ] [  Var. 1  ] [ Tutte 6 ]      4     Da guardare
    (Aa) Parole 2 (▭) Zone 2 (+8 altri)          Aa    Tipi
    ▾ Aa Parole · 2                              ▭     Zone
    ○ … da Acme ~~Pay~~**Services** …  corpo · pag. 1     ?  Legenda
    Header ✓ · Titolo ✓ · Spalla sx 1 · …
    ❯  ☐ Mostra fatte                       ?

The pieces live here, the behaviour in ``officina_diffs.DiffPanel``: the
verdict tabs (short words in equal columns, 3 × 2 — fewer columns rather
than a cut label), the collapse button (in the footer, out of the tab grid),
the footer (zones summary, tools, «?»), the
:class:`PanelRail` and whether the panel is collapsed — remembered for the
session (:data:`SESSION`), never saved to disk.
"""
from __future__ import annotations

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetItem,
)

from qtrequestory.ui import strings, theme
from qtrequestory.ui.pages.officina_rows import TABS
from qtrequestory.ui.pages.officina_progress import GLYPH_FONT
from qtrequestory.ui.pages.officina_type_chips import FlowLayout

__all__ = ["OPEN_WIDTH", "RAIL_WIDTH", "SESSION", "TAB_TEXT", "PanelFooter", "PanelRail", "build_tabs", "tool"]

#: The panel's width, open and collapsed (draft f25-caso-v2).
OPEN_WIDTH = 292
RAIL_WIDTH = 40
#: Remembered for the session (every case view of this run), never on disk.
SESSION = {"collapsed": False}

#: tab -> (short text, tooltip); the whole names are ``ELENCO_TAB_*`` (the accessible names).
TAB_TEXT = {
    "guardare": (strings.PANNELLO_TAB_GUARDARE, strings.ELENCO_TAB_GUARDARE_TIP),
    "verificare": (strings.PANNELLO_TAB_VERIFICARE, strings.ELENCO_TAB_VERIFICARE_TIP),
    "fatte": (strings.PANNELLO_TAB_FATTE, strings.ELENCO_TAB_FATTE_TIP),
    "tollerate": (strings.PANNELLO_TAB_TOLLERATE, strings.ELENCO_TAB_TOLLERATE_TIP),
    "variabili": (strings.PANNELLO_TAB_VARIABILI, strings.ELENCO_TAB_VARIABILI_TIP),
    "tutte": (strings.PANNELLO_TAB_TUTTE, strings.ELENCO_TAB_TUTTE_TIP),
}


#: The verdict tabs: a grid of compact pills, 3 equal columns × 2 rows (U3 fix round 1).
TAB_COLUMNS = 3


class TabGridLayout(FlowLayout):
    """Equal columns: :data:`TAB_COLUMNS` when the widest pill fits a
    column (always, at the panel's width and font), else fewer — a label is
    never cut, and the second row never reads as an overflow."""

    def _place(self, rect: QRect, *, move: bool) -> int:
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        items = [i for i in self._items if not (isinstance(i, QWidgetItem) and i.widget().isHidden())]
        if not items:
            return 0
        widest = max(i.sizeHint().width() for i in items)
        tall = max(i.sizeHint().height() for i in items)
        gap = self._gap
        columns = next((c for c in range(TAB_COLUMNS, 0, -1) if c * widest + (c - 1) * gap <= area.width()), 1)
        cell = max(widest, (area.width() - (columns - 1) * gap) // columns)
        for index, item in enumerate(items):
            row, column = divmod(index, columns)
            if move:
                item.setGeometry(QRect(area.x() + column * (cell + gap), area.y() + row * (tall + gap), cell, tall))
        rows = -(-len(items) // columns)
        return rows * tall + (rows - 1) * gap + margins.top() + margins.bottom()


class TabGrid(QWidget):
    """The tabs' holder: as tall as its rows at its width (height for width)."""

    def __init__(self) -> None:
        super().__init__()
        policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - Qt naming
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - Qt naming
        return self.layout().heightForWidth(width)


def build_tabs(owner: QWidget) -> tuple[QWidget, dict[str, QToolButton], QButtonGroup]:
    """The verdict tabs in equal columns (checkable, exclusive)."""
    holder = TabGrid()
    grid = TabGridLayout(holder, spacing=3)
    group = QButtonGroup(owner)
    group.setExclusive(True)
    buttons: dict[str, QToolButton] = {}
    for tab in TABS:
        button = QToolButton()
        button.setCheckable(True)
        button.setProperty("diffTab", "true")
        button.setToolTip(TAB_TEXT[tab][1])
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)  # fills its column
        group.addButton(button)
        grid.addWidget(button)
        buttons[tab] = button
    return holder, buttons, group


def tool(text: str, name: str, tip: str = "", *, glyph: bool = False) -> QToolButton:
    """A small flat button of the panel: its accessible name is ``name``;
    ``glyph``: the text is a symbol, drawn in the symbol font a size up (M4)."""
    button = QToolButton()
    button.setText(text)
    if glyph:
        font = QFont(button.font())
        font.setFamily(GLYPH_FONT)
        font.setPointSizeF(font.pointSizeF() * 1.25)
        button.setFont(font)
    button.setAccessibleName(name)
    button.setToolTip(tip or name)
    button.setAutoRaise(True)
    theme.set_role(button, "panelTool")
    return button


class PanelFooter(QFrame):
    """The zones summary, then a row with the tools (e.g. "Mostra fatte") and «?»."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("panelFooter")
        self.zones = QLabel()
        self.zones.setWordWrap(True)
        self.zones.setToolTip(strings.PANNELLO_ZONES_TIP)
        theme.set_role(self.zones, "panelZones")
        self.legend_button = tool(strings.PANNELLO_LEGEND, strings.PANNELLO_LEGEND_NAME,
                                   strings.PANNELLO_LEGEND_TIP)
        self.tools = QHBoxLayout()
        self.tools.setContentsMargins(0, 0, 0, 0)
        self.tools.setSpacing(theme.SPACE[0])
        self.tools.addStretch(1)
        self.tools.addWidget(self.legend_button)
        box = QVBoxLayout(self)
        box.setContentsMargins(theme.SPACE[1], 3, theme.SPACE[1], 3)
        box.setSpacing(2)
        box.addWidget(self.zones)
        box.addLayout(self.tools)

    def add_tool(self, widget: QWidget, *, first: bool = False) -> None:
        """A tool left of the stretch (``first``: before the others)."""
        self.tools.insertWidget(0 if first else self.tools.count() - 2, widget)


class PanelRail(QFrame):
    """The collapsed panel: open it, or open it at the tab / chips / zones,
    or show the legend. ``chosen`` carries "open" | "guardare" | "types" |
    "zones" | "legend"."""

    chosen = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("panelRail")
        self.setFixedWidth(RAIL_WIDTH)
        self.buttons = {
            "open": tool(strings.PANNELLO_EXPAND, strings.PANNELLO_EXPAND_NAME, glyph=True),
            "guardare": tool("0", strings.PANNELLO_RAIL_GUARDARE.format(n=0)),
            "types": tool(strings.PANNELLO_RAIL_TYPES, strings.PANNELLO_RAIL_TYPES_NAME),
            "zones": tool(strings.PANNELLO_RAIL_ZONES, strings.PANNELLO_RAIL_ZONES_NAME, glyph=True),
            "legend": tool(strings.PANNELLO_LEGEND, strings.PANNELLO_LEGEND_NAME, strings.PANNELLO_LEGEND_TIP),
        }
        box = QVBoxLayout(self)
        box.setContentsMargins(0, theme.SPACE[1], 0, theme.SPACE[1])
        box.setSpacing(theme.SPACE[1])
        for key, button in self.buttons.items():
            theme.set_role(button, "panelRailButton")
            button.setFixedSize(28, 28)
            button.clicked.connect(lambda _c=False, k=key: self.chosen.emit(k))
            box.addWidget(button, 0, Qt.AlignmentFlag.AlignHCenter)
        box.addStretch(1)

    def set_state(self, guardare: int, types_tip: str, zones_tip: str) -> None:
        counter = self.buttons["guardare"]
        counter.setText(str(guardare))
        counter.setAccessibleName(strings.PANNELLO_RAIL_GUARDARE.format(n=guardare))
        counter.setToolTip(strings.PANNELLO_RAIL_GUARDARE.format(n=guardare))
        types = self.buttons["types"]
        types.setToolTip("\n".join(t for t in (strings.PANNELLO_RAIL_TYPES_NAME, types_tip) if t))
        zones = self.buttons["zones"]
        zones.setToolTip("\n".join(t for t in (strings.PANNELLO_RAIL_ZONES_NAME, zones_tip) if t))
