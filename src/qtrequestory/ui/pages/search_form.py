"""The Ricerca filter bar, one full-width row.

``[Ambiente ▾] [omnibox ……………] [esatta|contiene] [7 gg|30 gg|90 gg|📅] [Cerca]``

A dumb widget: it holds the filters, says when the user asked for a search
(:attr:`SearchForm.search_requested`) and when the environment changed
(:attr:`SearchForm.env_changed`). It never talks to the core — the page owns
that — which is what lets it be driven from a test with a few setters.

The key mode ("esatta" by default, the user's decision) is the one filter the
form persists itself (``search/key_mode``), because it is a habit rather than
part of one search. Enter anywhere in the bar means [Cerca]: the omnibox says
so through ``submitted``, the environment combo through an event filter.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QPushButton,
    QWidget,
)

from qtrequestory.ui import actions, prefs, strings, theme
from qtrequestory.ui.pages.search_icons import ThemedIcons
from qtrequestory.ui.pages.search_omnibox import SearchOmnibox
from qtrequestory.ui.pages.search_period import CUSTOM_ID, PRESETS, PeriodSelector

__all__ = ["CUSTOM_ID", "KEY_MODES", "PRESETS", "SearchForm"]

#: ``SearchQuery.key_mode`` values, in the order of the segmented buttons.
KEY_MODES: tuple[tuple[str, str], ...] = (
    ("exact", strings.SEARCH_KEY_MODE_EXACT),
    ("contains", strings.SEARCH_KEY_MODE_CONTAINS),
)


class SearchForm(QFrame):
    """The filter bar. All state, no behaviour beyond keeping itself coherent."""

    search_requested = Signal()
    env_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        theme.set_role(self, "card")
        self.env_combo = QComboBox()
        self.omnibox = SearchOmnibox()
        self.key_mode_group = QButtonGroup(self)
        self.period = PeriodSelector()
        self.search_button = QPushButton(strings.SEARCH_BTN)
        self._busy = False
        self._build()
        self._connect()
        self.set_key_mode(str(actions.user_settings().value(
            prefs.KEY_MODE_KEY, prefs.KEY_MODE_DEFAULT)), persist=False)
        self._update_search_enabled()

    # -- construction ------------------------------------------------------

    def _build(self) -> None:
        self.env_combo.setToolTip(strings.SEARCH_ENV_LABEL)
        self.env_combo.setAccessibleName(strings.SEARCH_ENV_LABEL)
        self.env_combo.installEventFilter(self)
        ThemedIcons(self).set(self.search_button, "search", "on_accent")
        self.search_button.setDefault(True)
        theme.set_role(self.search_button, "primary")

        modes = QHBoxLayout()
        modes.setSpacing(0)
        for index, (_mode, label) in enumerate(KEY_MODES):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setToolTip(strings.SEARCH_KEY_MODE_TOOLTIP)
            self.key_mode_group.addButton(button, index)
            modes.addWidget(button)
        theme.set_segmented(self.key_mode_group.buttons())

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 8, 8, 8)
        row.setSpacing(8)
        row.addWidget(self.env_combo)
        row.addWidget(self.omnibox, 1)
        row.addLayout(modes)
        row.addWidget(self.period)
        row.addWidget(self.search_button)

    def _connect(self) -> None:
        self.env_combo.currentTextChanged.connect(self._on_env_changed)
        self.omnibox.changed.connect(self._update_search_enabled)
        self.omnibox.submitted.connect(self.search_requested)
        self.key_mode_group.idClicked.connect(
            lambda index: self.set_key_mode(KEY_MODES[index][0]))
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
        return self.omnibox.fdi()

    def set_fdi(self, text: str) -> None:
        self.omnibox.set_fdi(text)

    def template_key(self) -> str:
        return self.omnibox.template_key()

    def set_template_key(self, text: str) -> None:
        self.omnibox.set_template_key(text)

    def set_template_keys(self, keys: Sequence[str]) -> None:
        self.omnibox.set_template_keys(keys)

    def template_keys(self) -> list[str]:
        return self.omnibox.template_keys()

    def key_mode(self) -> str:
        return KEY_MODES[max(self.key_mode_group.checkedId(), 0)][0]

    def set_key_mode(self, mode: str, *, persist: bool = True) -> None:
        """Check "esatta" or "contiene"; anything unknown reads as "esatta"."""
        index = next((i for i, (m, _l) in enumerate(KEY_MODES) if m == mode), 0)
        self.key_mode_group.button(index).setChecked(True)
        if persist:
            actions.user_settings().setValue(prefs.KEY_MODE_KEY, KEY_MODES[index][0])

    def can_search(self) -> bool:
        """The core refuses an unbounded query: one of the two filters is a must."""
        return bool(self.fdi() or self.template_key())

    # -- period ------------------------------------------------------------

    @property
    def period_group(self) -> QButtonGroup:
        return self.period.group

    def set_preset(self, days: int) -> None:
        self.period.set_preset(days)

    def preset_days(self) -> int | None:
        return self.period.preset_days()

    def set_custom_range(self, day_from: date, day_to: date) -> None:
        self.period.set_custom_range(day_from, day_to)

    def day_range(self) -> tuple[date, date]:
        return self.period.day_range()

    def window_days(self) -> int:
        return self.period.window_days()

    # -- busy --------------------------------------------------------------

    def set_busy(self, busy: bool) -> None:
        """"Cerca…" and disabled while a search runs; the status bar stays quiet."""
        self._busy = busy
        self.search_button.setText(strings.SEARCH_BTN_BUSY if busy else strings.SEARCH_BTN)
        self._update_search_enabled()

    def is_busy(self) -> bool:
        return self._busy

    # -- focus helpers the page's shortcuts use ----------------------------

    def focus_fdi(self) -> None:
        self.omnibox.focus_fdi()

    def focus_key(self) -> None:
        self.omnibox.focus_key()

    # -- reactions ---------------------------------------------------------

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt naming
        if (obj is self.env_combo and event.type() == QEvent.Type.KeyPress
                and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)):
            self.search_requested.emit()
            return True
        return super().eventFilter(obj, event)

    def _on_env_changed(self, name: str) -> None:
        if name:
            self.env_changed.emit(name)

    def _update_search_enabled(self) -> None:
        enabled = self.can_search() and not self._busy
        self.search_button.setEnabled(enabled)
        self.search_button.setToolTip(
            strings.SEARCH_BTN_TOOLTIP if self.can_search() else strings.SEARCH_BTN_DISABLED_TOOLTIP
        )
