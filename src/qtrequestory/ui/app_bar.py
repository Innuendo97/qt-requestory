"""The top app bar: brand, page tabs, sync-status chip, icon buttons.

Navigation option A of the redesign::

    [icon] qtRequestory   Ricerca  Sincronizzazione      (● coll oggi 11:24 · ● svil mai)  ⚙  ⓘ

The bar knows nothing about pages: the window adds a tab or an icon button per
``PAGES`` entry, listens to :attr:`AppBar.page_requested` and calls
:meth:`AppBar.set_current` when the page changes for any other reason (a
shortcut, a page asking for another). Every colour comes from the theme's QSS
(``QWidget#appBar``, ``QPushButton[tab="true"]``, ``QPushButton#statusChip``,
``QLabel[dot=…]``); the glyphs are re-tinted on ``theme.signals.changed``.
"""
from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from qtrequestory.ui import icons, strings, theme

__all__ = ["AppBar", "StatusChip", "TONES"]

#: Height of the bar (the mockup's 46 px).
BAR_HEIGHT = 46
BRAND_ICON_PX = 22
TAB_ICON_PX = 16
ICON_BUTTON_PX = 18
#: The dot colours the theme knows; anything else is drawn neutral.
TONES = ("ok", "warn", "bad", "neutral")
DOT = "●"


class StatusChip(QPushButton):
    """"● coll oggi 11:24 · ● svil ieri 18:40": one toned dot + text per environment.

    A button, so it is focusable and clickable; the dots and texts are child
    labels laid out inside it (a ``QPushButton`` cannot colour part of its own
    text) and let the clicks through to the button.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("statusChip")
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)  # a click must not steal the focus
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(strings.STATUS_SYNC_SUMMARY_TOOLTIP)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(10, 0, 10, 0)
        self._layout.setSpacing(5)
        self._dots: list[QLabel] = []
        self._summary = ""
        self.hide()

    def set_envs(self, items: Sequence[tuple]) -> None:
        """``(env, tone, text)`` or ``(env, tone, text, note)`` per environment;
        an empty list hides the chip. A note goes into the chip's tooltip as
        "env: note" (the labels let the mouse through, so they cannot carry
        one themselves).

        ``env`` may be empty: :meth:`MainWindow.set_sync_summary` passes one
        plain line that way.
        """
        while self._layout.count():
            widget = self._layout.takeAt(0).widget()
            if widget is not None:
                widget.hide()  # deleteLater waits for the event loop; do not paint meanwhile
                widget.deleteLater()
        self._dots = []
        parts: list[str] = []
        notes: list[str] = []
        for index, (env, tone, text, *note) in enumerate(items):
            if index:
                self._add_label(strings.CHIP_SEPARATOR.strip(), role="muted")
            dot = self._add_label(DOT)
            dot.setProperty("dot", tone if tone in TONES else "neutral")
            theme.repolish(dot)
            self._dots.append(dot)
            line = f"{env} {text}".strip()
            self._add_label(line)
            parts.append(line)
            if note and note[0]:
                notes.append(f"{env}: {note[0]}" if env else note[0])
        self.setToolTip("\n".join([strings.STATUS_SYNC_SUMMARY_TOOLTIP, *notes]))
        self._summary = strings.CHIP_SEPARATOR.join(parts)
        self.setAccessibleName(self._summary)
        self.setVisible(bool(parts))
        self.updateGeometry()

    def summary(self) -> str:
        """The chip as plain text ("coll oggi 11:24 · svil ieri 18:40")."""
        return self._summary

    def dots(self) -> list[QLabel]:
        return list(self._dots)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        """The children's size: ``QPushButton`` only measures its own text."""
        hint = self._layout.sizeHint()
        return QSize(hint.width(), max(hint.height(), 24))

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        return self.sizeHint()

    def _add_label(self, text: str, role: str | None = None) -> QLabel:
        label = QLabel(text, self)
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        if role:
            theme.set_role(label, role)
        self._layout.addWidget(label)
        label.show()  # a child created under an already visible parent starts hidden
        return label


class AppBar(QWidget):
    """Brand + tabs on the left, status chip and icon buttons on the right."""

    page_requested = Signal(str)

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
        self.status_chip.clicked.connect(lambda: self.page_requested.emit("sync"))
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
        """Check the entry of ``key`` and uncheck every other one."""
        for name, button in (*self.tabs.items(), *self.icon_buttons.items()):
            button.setChecked(name == key)

    # -- internals ---------------------------------------------------------

    def _register(self, button: QPushButton, icon_name: str, key: str) -> None:
        # Reachable with Tab, but a click leaves the focus where the user was typing.
        button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self._icon_names[button] = icon_name
        button.setIcon(icons.icon(icon_name))
        # clicked, not toggled: a click on the current tab would uncheck it,
        # and the window's set_current puts the check back.
        button.clicked.connect(lambda _checked=False, k=key: self.page_requested.emit(k))

    def _retint(self) -> None:
        """The theme switched: the glyphs were tinted for the old one."""
        for button, name in self._icon_names.items():
            button.setIcon(icons.icon(name))
