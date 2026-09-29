"""The top app bar: brand, page tabs, sync-status chip, icon buttons.

Navigation option A of the redesign::

    [icon] qtRequestory   Ricerca  Officina      (⟳• svil oggi 09:00 · coll 2 da scaricare)  ⚙  ⓘ

Since Officina 2.5 (D5) the Sincronizzazione page has no tab: the sync chip
(:mod:`~.sync_chip`) carries its state and asks for its dropdown panel
(:attr:`AppBar.sync_requested`); the chip reads as "current" while the full
page is on screen.

The bar knows nothing about pages: the window adds a tab or an icon button per
``PAGES`` entry, listens to :attr:`AppBar.page_requested` and calls
:meth:`AppBar.set_current` when the page changes for any other reason (a
shortcut, a page asking for another). Every colour comes from the theme's QSS
(``QWidget#appBar``, ``QPushButton[tab="true"]``, ``QPushButton#statusChip``,
``QLabel[dot=…]``). Palette B: the bar is the icon's blue gradient in both
modes, so its text and glyphs are ``on_header`` (white), the active tab is
underlined in the icon's amber; the glyphs are re-tinted on
``theme.signals.changed``.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from qtrequestory.ui import icons, strings, theme
from qtrequestory.ui.sync_chip import StatusChip

__all__ = ["AppBar", "StatusChip", "SYNC_PAGE_KEY", "TONES"]

#: Height of the bar (the mockup's 46 px).
BAR_HEIGHT = 46
BRAND_ICON_PX = 22
TAB_ICON_PX = 16
ICON_BUTTON_PX = 18
#: Padding (12 + 12), icon-text gap and a little slack of a tab, around icon and label.
TAB_CHROME_PX = 34
#: The dot colours the theme knows; anything else is drawn neutral.
TONES = ("ok", "warn", "bad", "neutral")
#: The page the chip stands for (hidden from the tabs, reached from the panel).
SYNC_PAGE_KEY = "sync"


class AppBar(QWidget):
    """Brand + tabs on the left, status chip and icon buttons on the right."""

    page_requested = Signal(str)
    #: The sync chip was pressed: open (or close) its dropdown panel.
    sync_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("appBar")
        # A plain QWidget ignores the background of its QSS rule without this.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(BAR_HEIGHT)
        self.tabs: dict[str, QPushButton] = {}
        self.icon_buttons: dict[str, QPushButton] = {}
        self._icon_names: dict[QPushButton, str] = {}

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 10, 0)
        layout.setSpacing(4)
        self.brand_icon = QLabel()
        self.brand_icon.setPixmap(icons.app_icon().pixmap(BRAND_ICON_PX, BRAND_ICON_PX))
        self.brand_label = QLabel(strings.APP_NAME)
        self.brand_label.setObjectName("appBarBrand")
        layout.addWidget(self.brand_icon)
        layout.addSpacing(4)
        layout.addWidget(self.brand_label)
        layout.addSpacing(18)
        self._tabs_layout = QHBoxLayout()
        self._tabs_layout.setSpacing(4)
        layout.addLayout(self._tabs_layout)
        layout.addStretch(1)
        self.status_chip = StatusChip()
        self.status_chip.clicked.connect(self.sync_requested)
        layout.addWidget(self.status_chip)
        layout.addSpacing(8)
        self._icons_layout = QHBoxLayout()
        self._icons_layout.setSpacing(2)
        layout.addLayout(self._icons_layout)

        theme.signals.changed.connect(self._retint)

    def add_tab(self, key: str, label: str, icon_name: str, tooltip: str = "") -> QPushButton:
        button = QPushButton(label)
        button.setProperty("tab", True)
        button.setCheckable(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        button.setIconSize(QSize(TAB_ICON_PX, TAB_ICON_PX))
        if tooltip:
            button.setToolTip(tooltip)
        button.setMinimumWidth(theme.bold_min_width(button, label, TAB_ICON_PX + TAB_CHROME_PX))
        self._register(button, icon_name, key)
        self.tabs[key] = button
        self._tabs_layout.addWidget(button)
        return button

    def add_icon_button(self, key: str, icon_name: str, tooltip: str) -> QPushButton:
        button = QPushButton()
        theme.set_role(button, "icon")
        button.setCheckable(True)
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setIconSize(QSize(ICON_BUTTON_PX, ICON_BUTTON_PX))
        self._register(button, icon_name, key)
        self.icon_buttons[key] = button
        self._icons_layout.addWidget(button)
        return button

    def focus_chain(self) -> list[QWidget]:
        """The keyboard order: tabs, then the chip, then the icon buttons."""
        return [*self.tabs.values(), self.status_chip, *self.icon_buttons.values()]

    def set_current(self, key: str) -> None:
        """Check the entry of ``key`` and uncheck every other one; the chip
        reads as current while its full page is on screen."""
        for name, button in (*self.tabs.items(), *self.icon_buttons.items()):
            button.setChecked(name == key)
        if self.status_chip.property("current") != (key == SYNC_PAGE_KEY):
            self.status_chip.setProperty("current", key == SYNC_PAGE_KEY)
            theme.repolish(self.status_chip)

    # -- internals ---------------------------------------------------------

    def _register(self, button: QPushButton, icon_name: str, key: str) -> None:
        # Reachable with Tab, but a click leaves the focus where the user was typing.
        button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self._icon_names[button] = icon_name
        button.setIcon(_header_icon(icon_name))
        # clicked, not toggled: a click on the current tab would uncheck it,
        # and the window's set_current puts the check back.
        button.clicked.connect(lambda _checked=False, k=key: self.page_requested.emit(k))

    def _retint(self) -> None:
        """The theme switched: the glyphs were tinted for the old one."""
        for button, name in self._icon_names.items():
            button.setIcon(_header_icon(name))


def _header_icon(name: str) -> QIcon:
    """``name`` tinted for the blue header (``on_header``, white in both modes)."""
    return icons.icon(name, theme.tokens().on_header)
