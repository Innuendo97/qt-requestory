"""Two steps of the Genera setup pane: "Dove" and the headers.

Widgets only: the page connects them to the presenter and renders into them.

* :class:`WhereStep` — "Genera su" (the generator) and "Chiamate dai log di"
  (the logs the payloads come from) side by side, labels above; when the logs
  are not the generator's own a note says so in place ("I payload vengono dai
  log di coll e vanno al generatore svil.") with [Usa i log di svil]; then
  "Salva in" (the folder, + [Sfoglia…]).
* :class:`HeadersStep` — one line that stays out of the way, "▸ Header  7
  inviati", until the table differs from Impostazioni: then a warn pill
  ("1 modificato") and [Ripristina] sit on that same line, so an edit that also
  changes Ricerca's "Genera documento" is visible and undone in one click
  without opening anything. Opened, the full table of what is sent
  (``genera_headers``) with [Aggiungi] [Rimuovi] and a hint.
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
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import strings, theme
from qtrequestory.ui.pages.genera_headers import GeneraHeaderTable
from qtrequestory.ui.pages.settings_widgets import PathField, button, muted

__all__ = ["COMBO_WIDTH", "HeadersStep", "WhereStep", "field_label", "fill_combo"]

#: The narrowest the two environment combos get.
COMBO_WIDTH = 120


def field_label(text: str, buddy: QWidget | None = None) -> QLabel:
    """A small label above its field."""
    label = QLabel(text)
    theme.set_role(label, "fieldLabel")
    if buddy is not None:
        label.setBuddy(buddy)
    return label


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


def _link(text: str, slot: Callable[[], None]) -> QPushButton:
    link = button(text, slot)
    theme.set_role(link, "link")
    link.setCursor(Qt.CursorShape.PointingHandCursor)
    return link


class WhereStep(QWidget):
    """"Dove": generator, logs (with the note), folder."""

    def __init__(self, browse: Callable[[], None], follow: Callable[[], None],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        heading = QLabel(strings.GENERA_WHERE)
        theme.set_role(heading, "section")
        self.generator_combo = QComboBox()
        self.generator_combo.setToolTip(strings.GENERA_GENERATOR_TIP)
        self.generator_combo.setMinimumWidth(COMBO_WIDTH)
        self.source_combo = QComboBox()
        self.source_combo.setToolTip(strings.GENERA_SOURCE_TIP)
        self.source_combo.setMinimumWidth(COMBO_WIDTH)
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(theme.SPACE[3])
        grid.setVerticalSpacing(theme.SPACE[0])
        grid.addWidget(field_label(strings.GENERA_GENERATOR, self.generator_combo), 0, 0)
        grid.addWidget(field_label(strings.GENERA_SOURCE, self.source_combo), 0, 1)
        grid.addWidget(self.generator_combo, 1, 0)
        grid.addWidget(self.source_combo, 1, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        self.source_note = QFrame()
        self.source_note.setProperty("banner", "progress")
        self.source_note_text = QLabel()
        self.source_note_text.setWordWrap(True)
        self.follow_button = _link("", follow)
        note = QVBoxLayout(self.source_note)
        note.setContentsMargins(theme.SPACE[2], theme.SPACE[1], theme.SPACE[2], theme.SPACE[1])
        note.setSpacing(0)
        note.addWidget(self.source_note_text)
        note.addWidget(self.follow_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.source_note.setVisible(False)

        self.destination = PathField(strings.GENERA_DESTINATION_NONE)
        self.destination.setToolTip(strings.GENERA_DESTINATION_HINT)
        self.browse_destination = self.destination.add(button(strings.BTN_BROWSE, browse))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE[1])
        layout.addWidget(heading)
        layout.addSpacing(theme.SPACE[0])
        layout.addLayout(grid)
        layout.addWidget(self.source_note)
        layout.addSpacing(theme.SPACE[1])
        layout.addWidget(field_label(strings.GENERA_DESTINATION, self.browse_destination))
        layout.addWidget(self.destination)

    def show_source_note(self, text: str, follow_env: str) -> None:
        """The note under the combos (``text`` "" hides it); ``follow_env``
        names the generator whose logs one click goes back to ("" = none)."""
        self.source_note_text.setText(text)
        self.follow_button.setText(strings.GENERA_SOURCE_FOLLOW.format(env=follow_env))
        self.follow_button.setVisible(bool(follow_env))
        self.source_note.setVisible(bool(text))


class HeadersStep(QWidget):
    """The headers: one line until opened (module docstring)."""

    def __init__(self, reset: Callable[[], None], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.toggle = QToolButton()
        self.toggle.setText(strings.GENERA_HEADERS)
        self.toggle.setToolTip(strings.GENERA_HEADERS_TIP)
        self.toggle.setCheckable(True)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        theme.set_role(self.toggle, "stepToggle")
        self.sent = muted()
        self.modified_pill = QLabel()
        self.modified_pill.setProperty("pill", "warn")
        self.modified_pill.setToolTip(strings.GENERA_HEADERS_MODIFIED_TIP)
        theme.repolish(self.modified_pill)
        self.reset_button = _link(strings.GENERA_HEADERS_RESET, reset)
        self.reset_button.setToolTip(strings.GENERA_HEADERS_RESET_TIP)
        line = QHBoxLayout()
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(theme.SPACE[2])
        line.addWidget(self.toggle)
        line.addWidget(self.sent)
        line.addWidget(self.modified_pill)
        line.addStretch(1)
        line.addWidget(self.reset_button)

        self.table = GeneraHeaderTable()
        self.add_button = button(strings.BTN_ADD, self.table.add_and_edit)
        self.remove_button = button(strings.BTN_REMOVE, self.table.remove_selected)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(theme.SPACE[1])
        buttons.addWidget(self.add_button)
        buttons.addWidget(self.remove_button)
        buttons.addStretch(1)
        self.panel = QWidget()
        panel = QVBoxLayout(self.panel)
        panel.setContentsMargins(0, theme.SPACE[1], 0, 0)
        panel.setSpacing(theme.SPACE[1] + theme.SPACE[0])
        panel.addWidget(self.table)
        panel.addLayout(buttons)
        panel.addWidget(muted(strings.GENERA_HEADERS_HINT, wrap=True))
        self.panel.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(line)
        layout.addWidget(self.panel)
        self.panel.setVisible(False)  # closed at start (it has a parent by now)
        self.toggle.toggled.connect(self._toggled)
        self.show_state("", "")

    def show_state(self, sent: str, modified: str) -> None:
        """"7 inviati" and, when the table differs from Impostazioni, the pill
        and [Ripristina] — on the collapsed line itself."""
        self.sent.setText(sent)
        self.modified_pill.setText(modified)
        self.modified_pill.setVisible(bool(modified))
        self.reset_button.setVisible(bool(modified))

    def _toggled(self, open_: bool) -> None:
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if open_ else Qt.ArrowType.RightArrow)
        self.panel.setVisible(open_)
