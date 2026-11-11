""""Cosa generare": the three sources of the Genera tab.

Two widgets, because the setup pane pins one and scrolls the other:

* :attr:`GeneraSource.modes` — the heading and the segments **Template key ·
  Elenco · FDI**, pinned at the top of the setup pane (they never scroll away);
* :class:`GeneraSource` itself — only the current source (the others are
  hidden, not stacked: a stacked widget would be as tall as its tallest page),
  taking the height the pane has left:

  * **Template key** — a monospace field, any separator; under it how many and
    where they go ("2 template key · cartella _senza_pacchetto");
  * **Elenco** — the file (elided path + [Sfoglia…]) and, before one is loaded,
    what it must look like; then a filter with [Tutti] [Nessuno] (on the
    packages SHOWN), the packages (``genera_packages``: tall rows, ticked with
    a click anywhere) and the running total "3 package scelti su 40 · 57
    template key" (+ the rows dropped);
  * **FDI** — a monospace field, whole FDIs, one per line.

The widgets only forward edits to the presenter and re-render from it
(:meth:`GeneraSource.render`); the text fields are the source of their own
text, so a render never moves the cursor.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import Elenco
from qtrequestory.ui.pages import officina_dialogs as ask
from qtrequestory.ui.pages.genera_packages import PackageList
from qtrequestory.ui.pages.genera_presenter import MODES, GeneraPresenter
from qtrequestory.ui.pages.settings_widgets import PathField, button, muted

__all__ = ["GeneraSource"]

#: Four lines of keys or FDIs at least; the field grows with the pane.
FIELD_HEIGHT = 92
#: The package list never gets shorter than about seven rows.
LIST_MIN_HEIGHT = 216

_LABELS = {"keys": strings.GENERA_MODE_KEYS, "elenco": strings.GENERA_MODE_ELENCO,
           "fdi": strings.GENERA_MODE_FDI}


class _Field(QPlainTextEdit):
    """A field that ASKS for four lines and takes whatever height is free.
    The setup pane's scroll area sizes its content by height-for-width (the
    wrapped notes), i.e. by preferred heights: QPlainTextEdit's own ~190 px
    preference pushed the steps under it out of view on a 768 px screen."""

    def sizeHint(self):  # noqa: N802 - Qt naming
        hint = super().sizeHint()
        hint.setHeight(FIELD_HEIGHT)
        return hint


def _field(placeholder: str) -> QPlainTextEdit:
    edit = _Field()
    edit.setFont(theme.mono_font())
    edit.setPlaceholderText(placeholder)
    edit.setTabChangesFocus(True)  # Tab walks the form, it does not type a tab
    edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
    edit.setMinimumHeight(FIELD_HEIGHT)
    return edit


def _column(*widgets: QWidget, spacing: int = theme.SPACE[1], stretch: QWidget | None = None) -> QWidget:
    holder = QWidget()
    layout = QVBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(spacing)
    for widget in widgets:
        layout.addWidget(widget, 1 if widget is stretch else 0)
    return holder


class GeneraSource(QWidget):
    """The current source's panel; :attr:`modes` is its pinned head (module docstring)."""

    def __init__(self, presenter: GeneraPresenter, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._presenter = presenter
        self._shown_elenco: Elenco | None = None
        self.modes = self._modes()

        self.keys_edit = _field(strings.GENERA_KEYS_PLACEHOLDER)
        self.keys_note = muted()
        self.keys_panel = _column(self.keys_edit, self.keys_note, stretch=self.keys_edit)
        self.fdi_edit = _field(strings.GENERA_FDI_PLACEHOLDER)
        self.fdi_note = muted()
        self.fdi_panel = _column(self.fdi_edit, self.fdi_note, stretch=self.fdi_edit)
        self.elenco_panel = self._elenco_panel()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        for panel in (self.keys_panel, self.elenco_panel, self.fdi_panel):
            layout.addWidget(panel, 1)

        self.keys_edit.textChanged.connect(
            lambda: self._presenter.set_keys_text(self.keys_edit.toPlainText()))
        self.fdi_edit.textChanged.connect(
            lambda: self._presenter.set_fdi_text(self.fdi_edit.toPlainText()))
        self.filter_edit.textChanged.connect(self.package_list.apply_filter)
        self.package_list.toggled.connect(self._presenter.set_package_checked)

    def _modes(self) -> QWidget:
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
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE[1] + theme.SPACE[0])
        layout.addWidget(heading)
        layout.addLayout(segments)
        return holder

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
        tools_row = QWidget()
        tools = QHBoxLayout(tools_row)
        tools.setContentsMargins(0, 0, 0, 0)
        tools.setSpacing(theme.SPACE[1])
        tools.addWidget(self.filter_edit, 1)
        tools.addWidget(self.all_button)
        tools.addWidget(self.none_button)
        self.package_list = PackageList()
        self.package_list.setMinimumHeight(LIST_MIN_HEIGHT)
        self.elenco_summary = QLabel()  # the running total: plain text, not muted
        self.elenco_skipped = muted()
        self.package_panel = _column(tools_row, self.package_list, self.elenco_summary, self.elenco_skipped,
                                     spacing=theme.SPACE[1] + theme.SPACE[0], stretch=self.package_list)
        panel = _column(self.elenco_path, self.elenco_error, self.elenco_hint, self.package_panel,
                        spacing=theme.SPACE[2], stretch=self.package_panel)
        panel.layout().addStretch(0)
        return panel

    # -- user actions ---------------------------------------------------------------

    def browse_elenco(self) -> None:
        current = self._presenter.elenco_path
        start = current.parent if current is not None else None
        chosen = ask.ask_open_file(self, strings.GENERA_ELENCO_PICK, strings.GENERA_ELENCO_FILTERS, start)
        if chosen is not None:
            self._presenter.load_elenco(Path(chosen))

    def _tick_shown(self, on: bool) -> None:
        self._presenter.set_packages_checked(self.package_list.shown(), on)

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
            note.setVisible(bool(text))  # an empty line would leave a gap
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
            self._shown_elenco = p.elenco
            self.package_list.fill(p.elenco.packages() if p.elenco is not None else [])
            self.package_list.apply_filter(self.filter_edit.text())
        self.package_list.set_checked(p.checked_packages)
        self.elenco_summary.setText(p.elenco_summary())
        skipped = p.elenco_skipped_note()
        self.elenco_skipped.setText(skipped)
        self.elenco_skipped.setVisible(bool(skipped))

    def package_texts(self) -> list[str]:
        """Every package row as read aloud (tests, accessibility)."""
        return self.package_list.texts()

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
