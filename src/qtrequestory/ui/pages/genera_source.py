""""Cosa generare": the three sources of the Genera tab, one card.

Segments **Template key · Elenco · FDI**, and under them only the current
source (the others are hidden, not stacked: a stacked widget would be as tall
as the tallest source, the list):

* **Template key** — a monospace field, any separator; under it how many and
  where they go ("2 template key · cartella _senza_pacchetto").
* **Elenco** — the file (elided path + [Sfoglia…]) and, before one is loaded,
  what the file must look like; then a filter, the packages with a tick and
  their key count, [Tutti] [Nessuno] (on the packages SHOWN), and
  "3 package scelti su 40 · 57 template key" (+ the rows dropped).
* **FDI** — a monospace field, whole FDIs, one per line.

The card only forwards edits to the presenter and re-renders from it
(:meth:`GeneraSource.render`); the text fields are the source of their own
text, so a render never moves the cursor.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import Elenco
from qtrequestory.ui.pages import officina_dialogs as ask
from qtrequestory.ui.pages.genera_presenter import MODES, GeneraPresenter
from qtrequestory.ui.pages.settings_widgets import PathField, button, muted

__all__ = ["GeneraSource"]

#: Four lines of keys or FDIs; more scroll.
FIELD_HEIGHT = 92
#: The package list: about six rows, then it scrolls.
LIST_HEIGHT = 156

_LABELS = {"keys": strings.GENERA_MODE_KEYS, "elenco": strings.GENERA_MODE_ELENCO,
           "fdi": strings.GENERA_MODE_FDI}


def _field(placeholder: str) -> QPlainTextEdit:
    edit = QPlainTextEdit()
    edit.setFont(theme.mono_font())
    edit.setPlaceholderText(placeholder)
    edit.setTabChangesFocus(True)  # Tab walks the form, it does not type a tab
    edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
    edit.setFixedHeight(FIELD_HEIGHT)
    return edit


def _column(*widgets: QWidget, spacing: int = theme.SPACE[1]) -> QWidget:
    holder = QWidget()
    layout = QVBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(spacing)
    for widget in widgets:
        layout.addWidget(widget)
    return holder


class GeneraSource(QFrame):
    """The "Cosa generare" card (module docstring)."""

    def __init__(self, presenter: GeneraPresenter, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._presenter = presenter
        self._shown_elenco: Elenco | None = None
        theme.set_role(self, "card")

        heading = QLabel(strings.GENERA_WHAT)
        theme.set_role(heading, "section")
        self.mode_buttons: dict[str, QPushButton] = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        segments = QHBoxLayout()
        segments.setSpacing(0)
        for mode in MODES:
            seg = QPushButton(_LABELS[mode])
            seg.setCheckable(True)
            self._group.addButton(seg)
            segments.addWidget(seg)
            self.mode_buttons[mode] = seg
            seg.clicked.connect(lambda _c=False, m=mode: self._presenter.set_mode(m))
        segments.addStretch(1)
        theme.set_segmented(list(self.mode_buttons.values()))

        self.keys_edit = _field(strings.GENERA_KEYS_PLACEHOLDER)
        self.keys_note = muted()
        self.keys_panel = _column(self.keys_edit, self.keys_note)
        self.fdi_edit = _field(strings.GENERA_FDI_PLACEHOLDER)
        self.fdi_note = muted()
        self.fdi_panel = _column(self.fdi_edit, self.fdi_note)
        self.elenco_panel = self._elenco_panel()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SPACE[3], theme.SPACE[2], theme.SPACE[3], theme.SPACE[3])
        layout.setSpacing(theme.SPACE[2])
        layout.addWidget(heading)
        layout.addLayout(segments)
        for panel in (self.keys_panel, self.elenco_panel, self.fdi_panel):
            layout.addWidget(panel)

        self.keys_edit.textChanged.connect(
            lambda: self._presenter.set_keys_text(self.keys_edit.toPlainText()))
        self.fdi_edit.textChanged.connect(
            lambda: self._presenter.set_fdi_text(self.fdi_edit.toPlainText()))
        self.filter_edit.textChanged.connect(lambda _t: self._apply_filter())
        self.package_list.itemChanged.connect(self._on_item_changed)

    def _elenco_panel(self) -> QWidget:
        self.elenco_path = PathField(strings.GENERA_ELENCO_NONE)
        self.browse_elenco_button = self.elenco_path.add(button(strings.BTN_BROWSE, self.browse_elenco))
        self.elenco_error = QLabel()
        self.elenco_error.setWordWrap(True)
        self.elenco_error.setProperty("dot", "warn")
        theme.repolish(self.elenco_error)
        hint_title = QLabel(strings.GENERA_ELENCO_EMPTY_TITLE)
        theme.set_role(hint_title, "section")
        self.elenco_hint = _column(hint_title, muted(strings.GENERA_ELENCO_EMPTY_HINT, wrap=True))

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText(strings.GENERA_ELENCO_FILTER)
        self.filter_edit.setClearButtonEnabled(True)
        self.all_button = button(strings.GENERA_ELENCO_ALL, lambda: self._tick_shown(True))
        self.all_button.setToolTip(strings.GENERA_ELENCO_ALL_TIP)
        self.none_button = button(strings.GENERA_ELENCO_NO_PACKAGES, lambda: self._tick_shown(False))
        self.none_button.setToolTip(strings.GENERA_ELENCO_NONE_TIP)
        tools = QHBoxLayout()
        tools.setContentsMargins(0, 0, 0, 0)
        tools.setSpacing(theme.SPACE[1])
        tools.addWidget(self.filter_edit, 1)
        tools.addWidget(self.all_button)
        tools.addWidget(self.none_button)
        self.package_list = QListWidget()
        self.package_list.setFixedHeight(LIST_HEIGHT)
        self.package_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.package_list.setUniformItemSizes(True)
        self.elenco_summary = muted()
        self.elenco_skipped = muted()
        tools_row = QWidget()
        tools_row.setLayout(tools)
        self.package_panel = _column(tools_row, self.package_list, self.elenco_summary, self.elenco_skipped)
        return _column(self.elenco_path, self.elenco_error, self.elenco_hint, self.package_panel,
                       spacing=theme.SPACE[2])

    # -- user actions ---------------------------------------------------------------

    def browse_elenco(self) -> None:
        current = self._presenter.elenco_path
        start = current.parent if current is not None else None
        chosen = ask.ask_open_file(self, strings.GENERA_ELENCO_PICK, strings.GENERA_ELENCO_FILTERS, start)
        if chosen is not None:
            self._presenter.load_elenco(Path(chosen))

    def _tick_shown(self, on: bool) -> None:
        shown = [self.package_list.item(i).data(Qt.ItemDataRole.UserRole)
                 for i in range(self.package_list.count()) if not self.package_list.item(i).isHidden()]
        self._presenter.set_packages_checked(shown, on)

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        self._presenter.set_package_checked(item.data(Qt.ItemDataRole.UserRole),
                                            item.checkState() == Qt.CheckState.Checked)

    def _apply_filter(self) -> None:
        wanted = self.filter_edit.text().strip().casefold()
        for i in range(self.package_list.count()):
            item = self.package_list.item(i)
            name = str(item.data(Qt.ItemDataRole.UserRole))
            item.setHidden(bool(wanted) and wanted not in name.casefold())

    # -- rendering ----------------------------------------------------------------------

    def render(self) -> None:
        p = self._presenter
        for mode, seg in self.mode_buttons.items():
            if seg.isChecked() != (mode == p.mode):
                seg.setChecked(mode == p.mode)
        self.keys_panel.setVisible(p.mode == "keys")
        self.elenco_panel.setVisible(p.mode == "elenco")
        self.fdi_panel.setVisible(p.mode == "fdi")
        _set_text(self.keys_edit, p.keys_text)
        _set_text(self.fdi_edit, p.fdi_text)
        for note, text in ((self.keys_note, p.keys_note()), (self.fdi_note, p.fdi_note())):
            note.setText(text)
            note.setVisible(bool(text))  # an empty line would leave a gap in the card
        self._render_elenco()

    def _render_elenco(self) -> None:
        p = self._presenter
        self.elenco_path.setText(str(p.elenco_path) if p.elenco_path is not None else "")
        self.elenco_error.setText(p.elenco_error)
        self.elenco_error.setVisible(bool(p.elenco_error))
        loaded = p.elenco is not None
        self.elenco_hint.setVisible(not loaded)
        self.package_panel.setVisible(loaded)
        if p.elenco is not self._shown_elenco:
            self._fill_packages(p.elenco)
        checked = p.checked_packages
        with QSignalBlocker(self.package_list):
            for i in range(self.package_list.count()):
                item = self.package_list.item(i)
                state = (Qt.CheckState.Checked if item.data(Qt.ItemDataRole.UserRole) in checked
                         else Qt.CheckState.Unchecked)
                if item.checkState() != state:
                    item.setCheckState(state)
        self.elenco_summary.setText(p.elenco_summary())
        skipped = p.elenco_skipped_note()
        self.elenco_skipped.setText(skipped)
        self.elenco_skipped.setVisible(bool(skipped))

    def _fill_packages(self, elenco: Elenco | None) -> None:
        self._shown_elenco = elenco
        with QSignalBlocker(self.package_list):
            self.package_list.clear()
            for package, n in (elenco.packages() if elenco is not None else []):
                item = QListWidgetItem(strings.GENERA_ELENCO_ROW.format(package=package, n=n))
                item.setData(Qt.ItemDataRole.UserRole, package)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Unchecked)
                self.package_list.addItem(item)
        self._apply_filter()

    def package_texts(self) -> list[str]:
        """Every package row as shown (tests, accessibility)."""
        return [self.package_list.item(i).text() for i in range(self.package_list.count())]

    def first_field(self) -> QWidget:
        """Where typing goes for the current source."""
        mode = self._presenter.mode
        if mode == "fdi":
            return self.fdi_edit
        if mode == "elenco":
            return self.browse_elenco_button if self._presenter.elenco is None else self.filter_edit
        return self.keys_edit


def _set_text(edit: QPlainTextEdit, text: str) -> None:
    if edit.toPlainText() != text:
        with QSignalBlocker(edit):
            edit.setPlainText(text)
