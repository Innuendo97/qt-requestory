"""Impostazioni → Officina: folder, timeout, Postman-Token, generators, the
default generator and the header profile (spec §5, §9).

Three cards, like the other sections, and the page's own Save flow: every
edit emits :attr:`OfficinaSection.changed` (the page's ``on_edited``), and
:meth:`OfficinaSection.values` is the ``OfficinaSettings`` the form means.

Every rule is the core's — ``generator_problems`` (PROD in any spelling,
https only, unique names), ``default_generator_problem``,
``postman_token_problem``, ``header_problems``, ``officina_root_errors`` — so
Impostazioni can never accept what ``config.validate`` or the generator would
refuse. The section only decides *where* each message goes: inline, next to
the offending row or field. While any is there, :meth:`problems` is not empty
and the page keeps [Salva] disabled.

The default generator follows its *row*: renaming it keeps it the default;
disabling or deleting it clears the default, says so under the combo, and
blocks Save until another enabled generator is chosen (or the disabled row is
ticked again, which restores it).

The folder is picked with the shared PathField. OneDrive and network folders
are allowed with a warning (the payloads hold real customer data). Changing
the folder while the Officina is generating or delivering is refused at Save
(:meth:`save_refusals`): those jobs write into the folder they started with.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import (
    OFFICINA_TIMEOUT_RANGE,
    Config,
    OfficinaSettings,
    default_generator_problem,
    generator_problems,
    header_problems,
    officina_root_errors,
    postman_token_problem,
)
from qtrequestory.ui.pages import officina_dialogs
from qtrequestory.ui.pages.settings_officina_tables import GeneratorTable, HeaderTable
from qtrequestory.ui.pages.settings_widgets import PathField, button, form_card, form_label, muted, row

__all__ = ["OfficinaSection"]

Browse = Callable[[PathField, str], None]


def _message(tone: str) -> QLabel:
    """An inline message under a field, hidden while it has no text."""
    label = QLabel()
    label.setWordWrap(True)
    label.setProperty("dot", tone)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    label.hide()
    return label


def _say(label: QLabel, text: str) -> None:
    label.setText(text)
    label.setVisible(bool(text))


def _column(*widgets: QWidget) -> QWidget:
    holder = QWidget()
    layout = QVBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(theme.SPACE[1])
    for widget in widgets:
        layout.addWidget(widget)
    return holder


class OfficinaSection(QWidget):
    """The Officina section of the Impostazioni page."""

    changed = Signal()

    def __init__(self, browse: Browse, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._loading = False
        #: The default named by the configuration when no row carries it
        #: (kept so that a form nobody touched saves it back unchanged).
        self._orphan = ""
        #: The default row's name at the last edit, and why it was lost.
        self._default_name = ""
        self._lost = ""
        self._problems: list[str] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE[2])
        layout.addWidget(self._general_card(browse))
        layout.addWidget(self._generators_card())
        layout.addWidget(self._headers_card())
        layout.addStretch(1)

    # -- construction ------------------------------------------------------

    def _general_card(self, browse: Browse) -> QFrame:
        card, form = form_card(strings.SETTINGS_OFFICINA_GENERAL)
        self.folder = PathField(strings.SETTINGS_OFFICINA_FOLDER_NONE)
        self.browse_folder_button = self.folder.add(button(
            strings.BTN_BROWSE,
            lambda: browse(self.folder, strings.SETTINGS_OFFICINA_FOLDER_CAPTION)))
        self.folder_warning = _message("warn")
        self.folder_problem = _message("bad")
        form.addRow(form_label(strings.SETTINGS_OFFICINA_FOLDER_LABEL),
                    _column(self.folder, self.folder_warning, self.folder_problem))

        self.timeout = QSpinBox()
        self.timeout.setRange(*OFFICINA_TIMEOUT_RANGE)
        self.timeout_label = form_label(strings.SETTINGS_OFFICINA_TIMEOUT_LABEL)
        form.addRow(self.timeout_label, row(self.timeout, stretch_at_end=True))

        self.token = QLineEdit()
        self.token.setFont(theme.mono_font())
        self.token_problem = _message("bad")
        self.token_hint = muted(strings.SETTINGS_OFFICINA_TOKEN_HINT, wrap=True)
        form.addRow(form_label(strings.SETTINGS_OFFICINA_TOKEN_LABEL),
                    _column(self.token, self.token_problem, self.token_hint))

        self.folder.changed.connect(self._on_folder)
        self.timeout.valueChanged.connect(self._edited)
        self.token.textChanged.connect(self._edited)
        return card

    def _generators_card(self) -> QFrame:
        card, form = form_card(strings.SETTINGS_OFFICINA_GENERATORS)
        self.generators = GeneratorTable()
        form.addRow(self.generators)
        self.add_generator_button = button(strings.BTN_ADD, self.generators.add_row)
        self.remove_generator_button = button(strings.BTN_REMOVE, self.generators.remove_selected)
        form.addRow(row(self.add_generator_button, self.remove_generator_button,
                        stretch_at_end=True))
        form.addRow(muted(strings.SETTINGS_OFFICINA_GENERATORS_HINT, wrap=True))
        self.default_combo = QComboBox()
        self.default_combo.setPlaceholderText(strings.SETTINGS_OFFICINA_DEFAULT_NONE)
        self.default_combo.setMinimumWidth(160)
        self.default_problem = _message("bad")
        form.addRow(form_label(strings.SETTINGS_OFFICINA_DEFAULT_LABEL),
                    _column(row(self.default_combo, stretch_at_end=True), self.default_problem))
        self.generators.changed.connect(self._on_generators)
        self.default_combo.currentIndexChanged.connect(self._on_default_chosen)
        return card

    def _headers_card(self) -> QFrame:
        card, form = form_card(strings.SETTINGS_OFFICINA_HEADERS)
        self.headers = HeaderTable()
        form.addRow(self.headers)
        self.add_header_button = button(strings.BTN_ADD, self.headers.add_row)
        self.remove_header_button = button(strings.BTN_REMOVE, self.headers.remove_selected)
        form.addRow(row(self.add_header_button, self.remove_header_button, stretch_at_end=True))
        form.addRow(muted(strings.SETTINGS_OFFICINA_HEADERS_HINT, wrap=True))
        self.headers.changed.connect(self._edited)
        return card

    # -- the form as data --------------------------------------------------

    def load(self, o: OfficinaSettings) -> None:
        """Show ``o`` (a load, not an edit: ``changed`` is not emitted)."""
        self._loading = True
        try:
            self.folder.setText(str(o.root) if o.root is not None else "")
            self.generators.set_generators(o.generators, o.default_generator)
            flagged = self.generators.default_row()
            self._orphan = "" if flagged is not None else o.default_generator
            self._default_name = o.default_generator if flagged is not None else ""
            self._lost = ""
            self.token.setText(o.postman_token)
            self.headers.set_rows(o.header_profile)
            self.timeout.setValue(o.timeout_s)
            _say(self.folder_problem, "")
        finally:
            self._loading = False
        self._refresh()

    def values(self) -> OfficinaSettings:
        text = self.folder.text().strip()
        return OfficinaSettings(
            root=Path(text) if text else None,
            generators=self.generators.generators(),
            default_generator=self._current_default(),
            postman_token=self.token.text(),
            header_profile=dict(self.headers.rows()),
            timeout_s=self.timeout.value(),
        )

    def problems(self) -> list[str]:
        """Every inline problem now on screen; Save is blocked while any is."""
        return list(self._problems)

    def save_refusals(self, candidate: Config, loaded_root: Path | None,
                      writing: bool) -> list[str]:
        """What stops a save of ``candidate`` beyond ``config.validate``: a new
        folder while the Officina writes into the old one (``writing``: see
        ``SettingsActions.officina_writing``), or a row problem. The folder's
        own message (busy, or inside the logs) goes under it."""
        busy = candidate.officina.root != loaded_root and writing
        roots = officina_root_errors(candidate)
        _say(self.folder_problem,
             strings.SETTINGS_OFFICINA_BUSY if busy else (roots[0] if roots else ""))
        refusals = [strings.SETTINGS_OFFICINA_BUSY] if busy else []
        if self._problems:
            refusals.append(strings.SETTINGS_OFFICINA_FIX_ROWS)
        return refusals

    # -- reactions ---------------------------------------------------------

    def _edited(self, *_args: object) -> None:
        if self._loading:
            return
        self._refresh()
        self.changed.emit()

    def _on_folder(self, _text: str) -> None:
        _say(self.folder_problem, "")  # a save-time message about the old choice
        self._edited()

    def _on_generators(self) -> None:
        table = self.generators
        flagged = table.default_row()
        if flagged is None and self._default_name:
            self._lost = strings.SETTINGS_OFFICINA_DEFAULT_REMOVED.format(name=self._default_name)
            self._orphan = ""
        elif flagged is not None and not table.is_enabled(flagged):
            table.set_default_row(None)
            table.set_disabled_default_row(flagged)  # ticked again, it is the default again
            self._lost = strings.SETTINGS_OFFICINA_DEFAULT_DISABLED.format(
                name=table.text(flagged, table.COL_NAME).strip())
            self._orphan = ""
        elif flagged is None and table.disabled_default_row() is not None and                 table.is_enabled(table.disabled_default_row()):
            table.set_default_row(table.disabled_default_row())
            table.set_disabled_default_row(None)
            self._lost = ""
        elif flagged is None and self._orphan:
            # The configured default had no row: the one now named so takes it.
            match = next((r for r, g in table.entries() if g.enabled and g.name == self._orphan),
                         None)
            if match is not None:
                table.set_default_row(match)
                self._orphan = ""
        self._edited()

    def _on_default_chosen(self, index: int) -> None:
        if self._loading or index < 0:
            return
        name = self.default_combo.itemText(index)
        match = next((r for r, g in self.generators.entries() if g.enabled and g.name == name),
                     None)
        if match is None or match == self.generators.default_row():
            return
        self.generators.set_default_row(match)
        self.generators.set_disabled_default_row(None)
        self._lost = self._orphan = ""
        self._edited()

    # -- what the form shows -------------------------------------------------

    def _flagged_name(self) -> str:
        """The name of the row marked as the default ("" when none is)."""
        flagged = self.generators.default_row()
        if flagged is None:
            return ""
        return self.generators.text(flagged, self.generators.COL_NAME).strip()

    def _current_default(self) -> str:
        return self._flagged_name() if self.generators.default_row() is not None else self._orphan

    def _refresh(self) -> None:
        """Recompute every inline message from the core's rules."""
        found: list[str] = []
        gens = self.generators.entries()
        per_row = generator_problems([g for _row, g in gens])
        self.generators.show_problems({r: p for (r, _g), p in zip(gens, per_row)})
        found += [p for problems in per_row for p in problems]

        self._default_name = self._flagged_name()
        self._fill_combo()
        values = self.values()
        default = ((self._lost if values.generators else "")
                   or default_generator_problem(values) or "")
        _say(self.default_problem, default)
        found += [default] if default else []

        token = postman_token_problem(self.token.text()) or ""
        _say(self.token_problem, token)
        found += [token] if token else []

        heads = self.headers.entries()
        per_head = header_problems([pair for _row, pair in heads])
        self.headers.show_problems({r: p for (r, _pair), p in zip(heads, per_head)})
        found += [p for problems in per_head for p in problems]

        self._problems = found
        _say(self.folder_warning, self._folder_warning(values.root))

    def _fill_combo(self) -> None:
        names = [g.name for _row, g in self.generators.entries() if g.enabled and g.name]
        current = self._flagged_name()
        with QSignalBlocker(self.default_combo):
            self.default_combo.clear()
            self.default_combo.addItems(names)
            self.default_combo.setCurrentIndex(names.index(current) if current in names else -1)

    @staticmethod
    def _folder_warning(root: Path | None) -> str:
        if root is None:
            return ""
        if officina_dialogs.in_onedrive(root):
            return strings.SETTINGS_OFFICINA_ONEDRIVE
        if officina_dialogs.on_network(root):
            return strings.SETTINGS_OFFICINA_NETWORK
        return ""

