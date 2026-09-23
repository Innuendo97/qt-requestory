"""The period control of the Ricerca bar: ``[7 gg|30 gg|90 gg|📅]``.

Three presets and a calendar button in one segmented row. The custom range
lives in a small popup (two dates and [Applica]) instead of two date editors
in the bar: those editors were what pushed the page's minimum width to 1450
px, and they were on screen all the time for a choice made once in a while.

The calendar button is checked while a custom range is active, and its
tooltip then says which one ("Dal 01/09/2026 al 18/09/2026"). Clicking it does
NOT switch to "custom" by itself: the popup opens on the window currently
selected, and only [Applica] changes the period — closing the popup leaves
the preset the user had.
"""
from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QDateEdit,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import strings, theme
from qtrequestory.ui.pages.search_icons import ThemedIcons

__all__ = ["CUSTOM_ID", "PRESETS", "PeriodPopup", "PeriodSelector"]

#: The three preset windows, in the order the buttons appear.
PRESETS: tuple[tuple[int, str], ...] = (
    (7, strings.SEARCH_PERIOD_7),
    (30, strings.SEARCH_PERIOD_30),
    (90, strings.SEARCH_PERIOD_90),
)
#: ``QButtonGroup`` id of the calendar button (the presets use their day count).
CUSTOM_ID = -2


def _qdate(day: date) -> QDate:
    return QDate(day.year, day.month, day.day)


class PeriodPopup(QFrame):
    """Two dates and [Applica], as a popup under the calendar button."""

    applied = Signal(object, object)  # date, date

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        theme.set_role(self, "card")
        self.date_from = QDateEdit()
        self.date_to = QDateEdit()
        for edit in (self.date_from, self.date_to):
            edit.setCalendarPopup(True)
            edit.setDisplayFormat(strings.SEARCH_DATE_FORMAT)
        self.apply_button = QPushButton(strings.SEARCH_PERIOD_APPLY)
        theme.set_role(self.apply_button, "primary")
        self.apply_button.clicked.connect(self._apply)
        form = QFormLayout()
        form.addRow(QLabel(strings.SEARCH_DATE_FROM_LABEL), self.date_from)
        form.addRow(QLabel(strings.SEARCH_DATE_TO_LABEL), self.date_to)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addLayout(form)
        layout.addWidget(self.apply_button, 0, Qt.AlignmentFlag.AlignRight)

    def open_under(self, anchor: QWidget, day_from: date, day_to: date) -> None:
        self.date_from.setDate(_qdate(day_from))
        self.date_to.setDate(_qdate(day_to))
        self.adjustSize()
        self.move(anchor.mapToGlobal(anchor.rect().bottomRight()) - self.rect().topRight())
        self.show()
        self.date_from.setFocus()

    def _apply(self) -> None:
        first, last = self.date_from.date().toPython(), self.date_to.date().toPython()
        if first > last:
            first, last = last, first
        self.hide()
        self.applied.emit(first, last)


class PeriodSelector(QWidget):
    """The segmented presets + calendar; all state, no search logic."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.group = QButtonGroup(self)
        self.calendar_button = QPushButton()
        self.popup = PeriodPopup(self)
        self._custom: tuple[date, date] | None = None
        #: The preset the popup opens on while no custom range is active.
        self._last_preset = PRESETS[1][0]
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        for days, label in PRESETS:
            button = QPushButton(label)
            button.setCheckable(True)
            self.group.addButton(button, days)
            layout.addWidget(button)
        self.calendar_button.setCheckable(True)
        ThemedIcons(self).set(self.calendar_button, "calendar")
        self.group.addButton(self.calendar_button, CUSTOM_ID)
        layout.addWidget(self.calendar_button)
        theme.set_segmented(self.group.buttons())
        self.group.idClicked.connect(self._on_clicked)
        self.popup.applied.connect(self.set_custom_range)
        self.set_preset(self._last_preset)

    # -- state -----------------------------------------------------------------

    def set_preset(self, days: int) -> None:
        """Check one of 7/30/90; any other window becomes a custom range."""
        button = self.group.button(days)
        if button is None or days == CUSTOM_ID:
            today = date.today()
            self.set_custom_range(today - timedelta(days=max(days, 1) - 1), today)
            return
        button.setChecked(True)
        self._last_preset = days
        self._custom = None
        self._update_tooltip()
        self.changed.emit()

    def preset_days(self) -> int | None:
        """The checked preset, or None when the range is custom."""
        return None if self._custom is not None else self._last_preset

    def set_custom_range(self, day_from: date, day_to: date) -> None:
        self._custom = (day_from, day_to)
        self.calendar_button.setChecked(True)
        self._update_tooltip()
        self.changed.emit()

    def is_custom(self) -> bool:
        return self._custom is not None

    def day_range(self) -> tuple[date, date]:
        """The window to search, inclusive on both ends.

        A preset of N days ends today and counts today in, so "7 gg" really is
        seven daily files and not eight.
        """
        if self._custom is not None:
            return self._custom
        today = date.today()
        return today - timedelta(days=self._last_preset - 1), today

    def window_days(self) -> int:
        day_from, day_to = self.day_range()
        return (day_to - day_from).days + 1

    def open_popup(self) -> None:
        self.popup.open_under(self.calendar_button, *self.day_range())

    # -- reactions -------------------------------------------------------------

    def _on_clicked(self, button_id: int) -> None:
        if button_id != CUSTOM_ID:
            self.set_preset(button_id)
            return
        # The calendar only OPENS the popup: until [Applica] the period is
        # still what it was, so the check goes back where it belongs.
        if self._custom is None:
            self.group.button(self._last_preset).setChecked(True)
        self.open_popup()

    def _update_tooltip(self) -> None:
        if self._custom is None:
            self.calendar_button.setToolTip(strings.SEARCH_PERIOD_CUSTOM_TOOLTIP)
            return
        first, last = self._custom
        self.calendar_button.setToolTip(strings.SEARCH_PERIOD_CUSTOM_ACTIVE_TOOLTIP.format(
            first=f"{first:%d/%m/%Y}", last=f"{last:%d/%m/%Y}"))
