"""The Ricerca filter bar: ambiente, FDI, template key, periodo, [Cerca].

A dumb widget: it holds the filters, says when the user asked for a search
(:attr:`SearchForm.search_requested`) and when the environment changed
(:attr:`SearchForm.env_changed`). It never talks to the core — the page owns
that — which is what lets it be driven from a test with three setters.

Two behaviours are worth explaining:

* **Enter anywhere means Cerca.** Every field is watched by one event filter
  rather than each one connecting its own ``returnPressed``: the date editors
  and the period buttons have no such signal, and "Enter runs the search" must
  hold in the whole bar, not only in the two text fields. The same filter turns
  Esc into "clear the field I am in" (DESIGN-ui §Keyboard).
* **Smart paste.** :class:`EntryLineEdit` overrides ``insertFromMimeData``
  because the FDI field carries a ``[0-9a-fA-F-]*`` validator: an entry name
  pasted into it would be *rejected*, silently, before anything could look at
  it. The override inspects the text first and fills both fields when it is one.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta

from PySide6.QtCore import QDate, QEvent, QObject, Qt, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QRegularExpressionValidator
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QCompleter,
    QDateEdit,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import strings
from qtrequestory.ui.pages.search_paste import parse_pasted_entry

__all__ = ["PRESETS", "EntryLineEdit", "SearchForm"]

#: The three preset windows, in the order the buttons appear.
PRESETS: tuple[tuple[int, str], ...] = (
    (7, strings.SEARCH_PERIOD_7),
    (30, strings.SEARCH_PERIOD_30),
    (90, strings.SEARCH_PERIOD_90),
)
#: ``QButtonGroup`` id of "Personalizzato" (the presets use their day count).
CUSTOM_ID = -2
#: Below this many characters an FDI is treated as a prefix in the empty state.
FULL_FDI_LEN = 8


class EntryLineEdit(QLineEdit):
    """FDI field that recognises a pasted entry name.

    On a paste whose text is an entry name the field takes the FDI and emits
    :attr:`entry_pasted` with ``(fdi, template_key)`` so the form can fill the
    key too; anything else is pasted normally — and then filtered by the
    ``[0-9a-fA-F-]*`` validator, which is exactly why this hook has to exist:
    an entry name pasted into a validated field is rejected character by
    character and nothing is left to look at.

    Implemented on ``keyPressEvent`` rather than on ``insertFromMimeData``
    because ``QLineEdit`` has no such virtual (that is ``QTextEdit``'s API) and
    its ``paste()`` slot is not virtual either: the key event is the only hook
    a subclass really gets.
    """

    entry_pasted = Signal(object, str)  # fdi may be None

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.matches(QKeySequence.StandardKey.Paste) and self.smart_paste():
            event.accept()
            return
        super().keyPressEvent(event)

    def smart_paste(self, text: str | None = None) -> bool:
        """Consume ``text`` (default: the clipboard) as an entry name.

        Returns False when it is not one, which means "paste it normally".
        """
        if text is None:
            clipboard = QGuiApplication.clipboard()
            text = clipboard.text() if clipboard is not None else ""
        parsed = parse_pasted_entry(text) if text else None
        if parsed is None:
            return False
        fdi, key = parsed
        self.setText(fdi or "")
        self.entry_pasted.emit(fdi, key)
        return True


class SearchForm(QWidget):
    """The filter bar. All state, no behaviour beyond keeping itself coherent."""

    search_requested = Signal()
    env_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.env_combo = QComboBox()
        self.fdi_edit = EntryLineEdit()
        self.key_combo = QComboBox()
        self.date_from = QDateEdit()
        self.date_to = QDateEdit()
        self.period_group = QButtonGroup(self)
        self.search_button = QPushButton(strings.SEARCH_BTN)
        self._build()
        self._connect()
        self.set_preset(PRESETS[1][0])
        self._update_search_enabled()

    # -- construction ------------------------------------------------------

    def _build(self) -> None:
        self.env_combo.setToolTip(strings.SEARCH_ENV_LABEL)
        self.fdi_edit.setPlaceholderText(strings.SEARCH_FDI_PLACEHOLDER)
        self.fdi_edit.setToolTip(strings.SEARCH_FDI_TOOLTIP)
        self.fdi_edit.setClearButtonEnabled(True)
        self.fdi_edit.setValidator(QRegularExpressionValidator("[0-9a-fA-F-]*", self))
        self.key_combo.setEditable(True)
        self.key_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.key_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.key_combo.lineEdit().setPlaceholderText(strings.SEARCH_KEY_PLACEHOLDER)
        self.key_combo.setToolTip(strings.SEARCH_KEY_TOOLTIP)
        self._install_completer()
        for edit in (self.date_from, self.date_to):
            edit.setCalendarPopup(True)
            edit.setDisplayFormat(strings.SEARCH_DATE_FORMAT)
            edit.setDate(QDate.currentDate())
        self.search_button.setDefault(True)
        self.search_button.setAutoDefault(True)

        top = QHBoxLayout()
        top.addWidget(QLabel(strings.SEARCH_ENV_LABEL))
        top.addWidget(self.env_combo)
        top.addSpacing(12)
        top.addWidget(QLabel(strings.SEARCH_FDI_LABEL))
        top.addWidget(self.fdi_edit, 2)
        top.addSpacing(12)
        top.addWidget(QLabel(strings.SEARCH_KEY_LABEL))
        top.addWidget(self.key_combo, 3)

        bottom = QHBoxLayout()
        bottom.addWidget(QLabel(strings.SEARCH_PERIOD_LABEL))
        for days, label in PRESETS:
            bottom.addWidget(self._preset_button(label, days))
        bottom.addWidget(self._preset_button(strings.SEARCH_PERIOD_CUSTOM, CUSTOM_ID))
        bottom.addSpacing(12)
        self._from_label = QLabel(strings.SEARCH_DATE_FROM_LABEL)
        self._to_label = QLabel(strings.SEARCH_DATE_TO_LABEL)
        bottom.addWidget(self._from_label)
        bottom.addWidget(self.date_from)
        bottom.addWidget(self._to_label)
        bottom.addWidget(self.date_to)
        bottom.addStretch(1)
        bottom.addWidget(self.search_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(top)
        layout.addLayout(bottom)

        for widget in (self.env_combo, self.fdi_edit, self.key_combo,
                       self.key_combo.lineEdit(), self.date_from, self.date_to):
            widget.installEventFilter(self)

    def _preset_button(self, label: str, button_id: int) -> QPushButton:
        button = QPushButton(label)
        button.setCheckable(True)
        self.period_group.addButton(button, button_id)
        return button

    def _install_completer(self) -> None:
        """A completer over the combo's own item model, rebuilt with the items.

        ``MatchContains`` is the whole point: nobody remembers whether a key
        starts with ``MOD_TEST_`` or ``CTR_``, but everybody remembers
        ``TRANSFER``.
        """
        completer = QCompleter(self.key_combo.model(), self)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.key_combo.setCompleter(completer)

    def _connect(self) -> None:
        self.env_combo.currentTextChanged.connect(self._on_env_changed)
        self.fdi_edit.textChanged.connect(lambda _text: self._update_search_enabled())
        self.fdi_edit.entry_pasted.connect(self._on_entry_pasted)
        self.key_combo.currentTextChanged.connect(lambda _text: self._update_search_enabled())
        self.period_group.idClicked.connect(self._on_preset_clicked)
        self.search_button.clicked.connect(self.search_requested)

    # -- environment -------------------------------------------------------

    def set_environments(self, names: Sequence[str], current: str | None = None) -> None:
        """Fill the combo; silent, because loading is not the user choosing."""
        self.env_combo.blockSignals(True)
        self.env_combo.clear()
        self.env_combo.addItems(list(names))
        if current and current in names:
            self.env_combo.setCurrentText(current)
        self.env_combo.blockSignals(False)

    def environments(self) -> list[str]:
        return [self.env_combo.itemText(i) for i in range(self.env_combo.count())]

    def current_env(self) -> str:
        return self.env_combo.currentText()

    def set_env(self, name: str) -> None:
        self.env_combo.setCurrentText(name)

    # -- filters -----------------------------------------------------------

    def fdi(self) -> str:
        return self.fdi_edit.text().strip()

    def set_fdi(self, text: str) -> None:
        self.fdi_edit.setText(text)

    def template_key(self) -> str:
        return self.key_combo.currentText().strip()

    def set_template_key(self, text: str) -> None:
        self.key_combo.setCurrentText(text)

    def set_template_keys(self, keys: Sequence[str]) -> None:
        """Repopulate the picker, keeping whatever the user has typed."""
        typed = self.key_combo.currentText()
        self.key_combo.blockSignals(True)
        self.key_combo.clear()
        self.key_combo.addItems(list(keys))
        self.key_combo.setCurrentText(typed)
        self.key_combo.blockSignals(False)
        self._install_completer()  # clear() dropped the old completion model

    def template_keys(self) -> list[str]:
        return [self.key_combo.itemText(i) for i in range(self.key_combo.count())]

    def can_search(self) -> bool:
        """The core refuses an unbounded query: one of the two filters is a must."""
        return bool(self.fdi() or self.template_key())

    # -- period ------------------------------------------------------------

    def set_preset(self, days: int) -> None:
        """Check one of 7/30/90 and hide the date editors."""
        button = self.period_group.button(days)
        if button is None:  # a configured window that is not one of the presets
            today = date.today()
            self.set_custom_range(today - timedelta(days=max(days, 1) - 1), today)
            return
        button.setChecked(True)
        self._show_dates(False)

    def preset_days(self) -> int | None:
        """The checked preset, or None when the range is custom."""
        checked = self.period_group.checkedId()
        return checked if checked in {days for days, _ in PRESETS} else None

    def set_custom_range(self, day_from: date, day_to: date) -> None:
        custom = self.period_group.button(CUSTOM_ID)
        custom.setChecked(True)
        self.date_from.setDate(QDate(day_from.year, day_from.month, day_from.day))
        self.date_to.setDate(QDate(day_to.year, day_to.month, day_to.day))
        self._show_dates(True)

    def day_range(self) -> tuple[date, date]:
        """The window to search, inclusive on both ends.

        A preset of N days ends today and counts today in, so "7 gg" really is
        seven daily files and not eight.
        """
        days = self.preset_days()
        if days is None:
            return self.date_from.date().toPython(), self.date_to.date().toPython()
        today = date.today()
        return today - timedelta(days=days - 1), today

    def window_days(self) -> int:
        day_from, day_to = self.day_range()
        return (day_to - day_from).days + 1

    # -- focus helpers the page's shortcuts use ----------------------------

    def focus_fdi(self) -> None:
        self.fdi_edit.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.fdi_edit.selectAll()

    def focus_key(self) -> None:
        self.key_combo.lineEdit().setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.key_combo.lineEdit().selectAll()

    # -- reactions ---------------------------------------------------------

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt naming
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.search_requested.emit()
                return True
            if key == Qt.Key.Key_Escape and self._clear(obj):
                return True
        return super().eventFilter(obj, event)

    def _clear(self, obj: QObject) -> bool:
        """Esc empties the focused *filter*; elsewhere it keeps its meaning."""
        if obj is self.fdi_edit:
            self.fdi_edit.clear()
            return True
        if obj is self.key_combo.lineEdit():
            self.key_combo.setCurrentText("")
            return True
        return False

    def _on_env_changed(self, name: str) -> None:
        if name:
            self.env_changed.emit(name)

    def _on_entry_pasted(self, fdi: object, key: str) -> None:
        self.set_template_key(key)

    def _on_preset_clicked(self, button_id: int) -> None:
        self._show_dates(button_id == CUSTOM_ID)

    def _show_dates(self, visible: bool) -> None:
        for widget in (self._from_label, self.date_from, self._to_label, self.date_to):
            widget.setVisible(visible)

    def _update_search_enabled(self) -> None:
        enabled = self.can_search()
        self.search_button.setEnabled(enabled)
        self.search_button.setToolTip(
            strings.SEARCH_BTN_TOOLTIP if enabled else strings.SEARCH_BTN_DISABLED_TOOLTIP
        )
