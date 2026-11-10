"""Two cards of the Genera form: "Dove" and the headers.

Widgets only: the page connects them to the presenter and renders into them.

* :class:`WhereCard` — "Genera su" (the generator), "Chiamate da" (the logs
  the payloads come from) and "Salva in" (the folder, + [Sfoglia…]).
* :class:`HeadersCard` — one line, "Header · 7 inviati · 1 modificato", that
  opens the full table of what is sent (closed at start) with
  [Aggiungi] [Rimuovi] [Ripristina] and a hint.
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import strings, theme
from qtrequestory.ui.pages.genera_headers import GeneraHeaderTable
from qtrequestory.ui.pages.settings_widgets import PathField, button, muted

__all__ = ["COMBO_WIDTH", "HeadersCard", "WhereCard", "card_layout", "fill_combo"]

#: The narrowest the two environment combos get.
COMBO_WIDTH = 150


def card_layout(card: QFrame, title: str) -> QVBoxLayout:
    """The card look and its column, with ``title`` as heading when given."""
    theme.set_role(card, "card")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(theme.SPACE[3], theme.SPACE[2], theme.SPACE[3], theme.SPACE[3])
    layout.setSpacing(theme.SPACE[2])
    if title:
        heading = QLabel(title)
        theme.set_role(heading, "section")
        layout.addWidget(heading)
    return layout


def fill_combo(combo: QComboBox, items: list[str], current: str) -> None:
    """``items`` with ``current`` selected, without echoing the change back."""
    combo.blockSignals(True)
    try:
        if [combo.itemText(i) for i in range(combo.count())] != items:
            combo.clear()
            combo.addItems(items)
        index = combo.findText(current)
        if index >= 0 and combo.currentIndex() != index:
            combo.setCurrentIndex(index)
    finally:
        combo.blockSignals(False)


class WhereCard(QFrame):
    """"Dove": generator, logs, folder."""

    def __init__(self, browse: Callable[[], None], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = card_layout(self, strings.GENERA_WHERE)
        self.generator_combo = QComboBox()
        self.generator_combo.setToolTip(strings.GENERA_GENERATOR_TIP)
        self.generator_combo.setMinimumWidth(COMBO_WIDTH)
        self.source_combo = QComboBox()
        self.source_combo.setToolTip(strings.GENERA_SOURCE_TIP)
        self.source_combo.setMinimumWidth(COMBO_WIDTH)
        self.destination = PathField(strings.GENERA_DESTINATION_NONE)
        self.browse_destination = self.destination.add(button(strings.BTN_BROWSE, browse))
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(theme.SPACE[3])
        grid.setVerticalSpacing(theme.SPACE[2])
        labels = [muted(text) for text in (strings.GENERA_GENERATOR, strings.GENERA_SOURCE,
                                            strings.GENERA_DESTINATION)]
        grid.addWidget(labels[0], 0, 0)
        grid.addWidget(self.generator_combo, 0, 1)
        grid.addWidget(labels[1], 0, 2)
        grid.addWidget(self.source_combo, 0, 3)
        grid.setColumnStretch(4, 1)
        grid.addWidget(labels[2], 1, 0)
        grid.addWidget(self.destination, 1, 1, 1, 4)
        grid.addWidget(muted(strings.GENERA_DESTINATION_HINT, wrap=True), 2, 1, 1, 4)
        layout.addLayout(grid)


class HeadersCard(QFrame):
    """The headers, collapsed to one line until opened."""

    def __init__(self, reset: Callable[[], None], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = card_layout(self, "")
        layout.setContentsMargins(theme.SPACE[3], theme.SPACE[1], theme.SPACE[3], theme.SPACE[1])
        self.toggle = QToolButton()
        self.toggle.setCheckable(True)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.toggle.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        theme.set_role(self.toggle, "syncDisclosure")
        self.table = GeneraHeaderTable()
        self.add_button = button(strings.BTN_ADD, self.table.add_row)
        self.remove_button = button(strings.BTN_REMOVE, self.table.remove_selected)
        self.reset_button = button(strings.GENERA_HEADERS_RESET, reset)
        self.reset_button.setToolTip(strings.GENERA_HEADERS_RESET_TIP)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(theme.SPACE[1])
        for widget in (self.add_button, self.remove_button, self.reset_button):
            buttons.addWidget(widget)
        buttons.addStretch(1)
        self.panel = QWidget()
        panel = QVBoxLayout(self.panel)
        panel.setContentsMargins(0, 0, 0, 0)
        panel.setSpacing(theme.SPACE[1])
        panel.addWidget(self.table)
        panel.addLayout(buttons)
        panel.addWidget(muted(strings.GENERA_HEADERS_HINT, wrap=True))
        layout.addWidget(self.toggle)
        layout.addWidget(self.panel)
        self.panel.setVisible(False)  # closed at start (it has a parent by now)
        self.toggle.toggled.connect(self._toggled)

    def _toggled(self, open_: bool) -> None:
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if open_ else Qt.ArrowType.RightArrow)
        self.panel.setVisible(open_)
