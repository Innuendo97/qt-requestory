"""The preview pane's Dettagli tab: everything the log knows about one call.

A form — Ambiente, Giorno, Ora, File di log, Dimensione, N. documenti, FDI,
Template key, Nome chiamata — with the actions that used to hide in the
results' right-click menu next to the values they act on: [Copia] and [Cerca
solo questo …] beside the FDI and the key, [Apri cartella] beside the log file.

The widget only *asks*: it emits what the user clicked and the pane forwards
it to the Ricerca page, which owns copying (with its confirmation) and
searching.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import SearchHit
from qtrequestory.ui.pages import sync_format
from qtrequestory.ui.pages.search_icons import ThemedIcons
from qtrequestory.ui.results_model import format_day, format_time

__all__ = ["PreviewDetails"]


class PreviewDetails(QWidget):
    """Read-only facts about the selected call, with a few actions."""

    #: (text to copy, confirmation message)
    copy_requested = Signal(str, str)
    #: (fdi or None, template key or None): run that search instead
    search_requested = Signal(object, object)
    #: the folder of the call's daily log file
    log_folder_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._hit: SearchHit | None = None
        self.values: dict[str, QLabel] = {}
        self._icons = ThemedIcons(self)
        card = QFrame()
        theme.set_role(card, "card")
        self.form = QFormLayout(card)
        self.form.setContentsMargins(16, 12, 16, 12)
        self.form.setHorizontalSpacing(16)
        self.form.setVerticalSpacing(8)
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        mono = theme.mono_font()
        for key, label in (
            ("env", strings.PREVIEW_DETAIL_ENV), ("day", strings.PREVIEW_DETAIL_DAY),
            ("time", strings.PREVIEW_DETAIL_TIME), ("log", strings.PREVIEW_DETAIL_LOG),
            ("size", strings.PREVIEW_DETAIL_SIZE), ("ndocs", strings.PREVIEW_DETAIL_NDOCS),
            ("fdi", strings.PREVIEW_DETAIL_FDI), ("key", strings.PREVIEW_DETAIL_KEY),
            ("name", strings.PREVIEW_DETAIL_NAME),
        ):
            value = QLabel()
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            # Paths and entry names have no spaces to wrap at: the value must
            # not widen the pane (and push the splitter); the tooltip has it all.
            value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            value.setMinimumWidth(1)  # a size of 0 would mean "use the hint"
            if key in ("log", "fdi", "key", "name"):
                value.setFont(mono)
            self.values[key] = value
            caption = QLabel(label)
            theme.set_role(caption, "muted")
            self.form.addRow(caption, self._row(key, value))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(card)
        layout.addStretch(1)
        self.set_hit(None)

    def _row(self, key: str, value: QLabel) -> QWidget:
        """The value, plus the buttons that act on it."""
        buttons: list[QPushButton] = []
        if key == "log":
            buttons.append(self._button(strings.BTN_OPEN_FOLDER, self.log_folder_requested.emit))
            self.open_log_button = buttons[-1]
        elif key == "fdi":
            self.copy_fdi_button = self._copy_button(strings.SEARCH_MENU_COPY_FDI, self._copy_fdi)
            self.only_fdi_button = self._button(strings.SEARCH_MENU_ONLY_FDI, self._only_fdi)
            buttons += [self.copy_fdi_button, self.only_fdi_button]
        elif key == "key":
            self.copy_key_button = self._copy_button(strings.SEARCH_MENU_COPY_KEY, self._copy_key)
            self.only_key_button = self._button(strings.SEARCH_MENU_ONLY_KEY, self._only_key)
            buttons += [self.copy_key_button, self.only_key_button]
        if not buttons:
            return value
        row = QWidget()
        box = QVBoxLayout(row)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        box.addWidget(value)
        line = QHBoxLayout()
        line.setSpacing(6)
        for button in buttons:
            line.addWidget(button)
        line.addStretch(1)
        box.addLayout(line)
        return row

    @staticmethod
    def _button(text: str, slot) -> QPushButton:
        button = QPushButton(text)
        button.setAutoDefault(False)
        button.clicked.connect(lambda _checked=False: slot())
        return button

    def _copy_button(self, tooltip: str, slot) -> QPushButton:
        """[Copia] as an icon: the rows must stay narrow enough for the pane."""
        button = self._button("", slot)
        theme.set_role(button, "icon")
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        self._icons.set(button, "copy")
        return button

    # -- content ---------------------------------------------------------------

    def set_hit(self, hit: SearchHit | None) -> None:
        self._hit = hit
        missing = strings.SEARCH_VALUE_MISSING
        if hit is None:
            for key in self.values:
                self._set(key, missing)
        else:
            self._set("env", hit.env)
            self._set("day", format_day(hit.day))
            self._set("time", format_time(hit.request_date))
            self._set("log", str(hit.file_path))
            self._set("size", sync_format.format_size(hit.body_len))
            self._set("ndocs", strings.SEARCH_VALUE_UNKNOWN if hit.ndocs is None
                      else str(hit.ndocs))
            self._set("fdi", hit.fdi or missing)
            self._set("key", hit.template_key)
            self._set("name", hit.name)
        has_fdi = hit is not None and bool(hit.fdi)
        for button in (self.copy_fdi_button, self.only_fdi_button):
            button.setEnabled(has_fdi)
        for button in (self.copy_key_button, self.only_key_button, self.open_log_button):
            button.setEnabled(hit is not None)

    def _set(self, key: str, text: str) -> None:
        self.values[key].setText(text)
        self.values[key].setToolTip(text)

    def value(self, key: str) -> str:
        return self.values[key].text()

    # -- actions -----------------------------------------------------------

    def _copy_fdi(self) -> None:
        if self._hit is not None and self._hit.fdi:
            self.copy_requested.emit(self._hit.fdi, strings.SEARCH_STATUS_COPIED_FDI)

    def _copy_key(self) -> None:
        if self._hit is not None:
            self.copy_requested.emit(self._hit.template_key, strings.SEARCH_STATUS_COPIED_KEY)

    def _only_fdi(self) -> None:
        if self._hit is not None and self._hit.fdi:
            self.search_requested.emit(self._hit.fdi, None)

    def _only_key(self) -> None:
        if self._hit is not None:
            self.search_requested.emit(None, self._hit.template_key)
