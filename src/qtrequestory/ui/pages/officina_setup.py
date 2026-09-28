"""The Officina setup form, and the card that carries it in the Officina tab.

Release 1.3.2 (user decision U3): the folder and the document generator are
asked where they are missing, not in a far-away Impostazioni section.

* :class:`SetupForm` — the folder (typed or picked) and the generators
  (a :class:`~qtrequestory.ui.pages.settings_officina_tables.GeneratorTable`
  and the default generator). Used by the first-run wizard's "Officina" step
  (``ui/wizard_officina_page``) and by :class:`SetupCard`. Every rule is the
  core's, as in Impostazioni: ``generator_problems`` (https only, no PROD in
  any spelling, unique names), ``default_generator_problem`` and
  ``officina_root_errors`` (never inside the log mirror or the output
  folder); a OneDrive or network folder is allowed with a warning.
* :class:`SetupCard` — the form with [Salva] and "Altre impostazioni…". The
  Officina tab shows it instead of the initiatives while no folder is chosen,
  and over them while no generator is active. [Salva] writes through
  ``services.config.save`` (the API Impostazioni uses) and emits ``saved``;
  the tab then refreshes without a restart.

What the form proposes: the configured generators; else the ``generators`` of
the environments.json next to the exe (``config.sidecar_generators``); else
one empty row to fill. Nothing is written before the user confirms.
"""
from __future__ import annotations

import dataclasses
from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import (
    Config,
    CoreServices,
    GeneratorEndpoint,
    OfficinaSettings,
    default_generator_problem,
    generator_problems,
    officina_root_errors,
)
from qtrequestory.ui.pages import officina_dialogs
from qtrequestory.ui.pages.settings_officina_tables import GeneratorTable

__all__ = ["SetupCard", "SetupForm"]

#: The generator table shows its rows: at least one, at most this many
#: (then it scrolls), so a single generator leaves no empty band.
TABLE_MAX_ROWS = 4


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


def _muted(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    theme.set_role(label, "muted")
    return label


def _column(*widgets: QWidget) -> QWidget:
    holder = QWidget()
    layout = QVBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(theme.SPACE[0])
    for widget in widgets:
        layout.addWidget(widget)
    return holder


def _row(*widgets: QWidget) -> QWidget:
    holder = QWidget()
    layout = QHBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(theme.SPACE[1])
    for widget in widgets:
        layout.addWidget(widget)
    layout.addStretch(1)
    return holder


class SetupForm(QWidget):
    """Folder + generators + default; ``base`` gives the configuration the
    answers go on top of (the wizard's pages, or the saved one)."""

    changed = Signal()

    def __init__(self, base: Callable[[], Config], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._base = base
        self._loading = False
        #: The default the configuration named: chosen again whenever offered.
        self._preferred = ""

        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText(strings.OFFICINA_SETUP_FOLDER_PLACEHOLDER)
        self.browse_button = QPushButton(strings.BTN_BROWSE)
        self.browse_button.clicked.connect(self.browse)
        self.folder_advice = _muted(strings.OFFICINA_SETUP_FOLDER_ADVICE)
        self.folder_warning = _message("warn")
        self.folder_problem = _message("bad")
        folder_line = QHBoxLayout()
        folder_line.setSpacing(theme.SPACE[1])
        folder_line.addWidget(self.folder_edit, 1)
        folder_line.addWidget(self.browse_button)
        folder = QWidget()
        folder.setLayout(folder_line)
        folder_line.setContentsMargins(0, 0, 0, 0)

        self.generators = GeneratorTable()
        self.generators.setMinimumHeight(0)
        model = self.generators.model()
        model.rowsInserted.connect(self._fit_table)
        model.rowsRemoved.connect(self._fit_table)
        self.add_button = QPushButton(strings.BTN_ADD)
        self.add_button.clicked.connect(lambda: self.generators.add_row())
        self.remove_button = QPushButton(strings.BTN_REMOVE)
        self.remove_button.clicked.connect(self.generators.remove_selected)
        self.source_hint = _muted()
        self.default_combo = QComboBox()
        self.default_combo.setMinimumWidth(160)
        self.default_problem = _message("bad")
        #: "Aggiungi almeno un generatore attivo", a save that failed.
        self.problem = _message("bad")

        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(theme.SPACE[3])
        form.setVerticalSpacing(theme.SPACE[2])
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.addRow(_muted(strings.OFFICINA_SETUP_FOLDER_LABEL),
                    _column(folder, self.folder_advice, self.folder_warning, self.folder_problem))
        form.addRow(_muted(strings.OFFICINA_SETUP_GENERATORS_LABEL),
                    _column(self.generators, _row(self.add_button, self.remove_button),
                            self.source_hint))
        form.addRow(_muted(strings.OFFICINA_SETUP_DEFAULT_LABEL),
                    _column(_row(self.default_combo), self.default_problem, self.problem))

        self.folder_edit.textChanged.connect(self._edited)
        self.generators.changed.connect(self._edited)
        self.default_combo.currentIndexChanged.connect(self._edited)

    # -- the form as data --------------------------------------------------

    def load(self, officina: OfficinaSettings, suggested: Sequence[GeneratorEndpoint]) -> None:
        """Show ``officina``; its generators, else ``suggested`` (the
        sidecar's), else one empty row. A load, not an edit."""
        self._loading = True
        try:
            self.folder_edit.setText(str(officina.root) if officina.root is not None else "")
            self._preferred = officina.default_generator
            if officina.generators:
                shown, hint = list(officina.generators), strings.OFFICINA_SETUP_CONFIGURED
            elif suggested:
                shown, hint = list(suggested), strings.OFFICINA_SETUP_FROM_SIDECAR
            else:
                shown, hint = [], strings.OFFICINA_SETUP_EMPTY_HINT
            self.generators.set_generators(shown, officina.default_generator)
            if not shown:
                with QSignalBlocker(self.generators):
                    self.generators.add_row()
            self.source_hint.setText(hint)
            for label in (self.folder_problem, self.default_problem, self.problem):
                _say(label, "")
        finally:
            self._loading = False
        self._refresh()

    def root(self) -> Path | None:
        text = self.folder_edit.text().strip()
        return Path(text) if text else None

    def officina(self, base: OfficinaSettings) -> OfficinaSettings:
        """``base`` with this form's folder, generators and default."""
        generators = self.generators.generators()
        default = self.default_combo.currentText() or (
            "" if any(g.enabled for g in generators) else base.default_generator)
        return dataclasses.replace(base, root=self.root(), generators=generators,
                                   default_generator=default)

    def candidate(self) -> Config:
        """The configuration [Salva] / [Fine] would write."""
        base = self._base()
        return dataclasses.replace(base, officina=self.officina(base.officina))

    def check(self, *, require_folder: bool, require_generator: bool) -> list[str]:
        """Every problem, each shown where it belongs; empty means savable."""
        found = self._refresh()
        if require_folder and self.root() is None:
            _say(self.folder_problem, strings.OFFICINA_SETUP_NEED_FOLDER)
            found.append(strings.OFFICINA_SETUP_NEED_FOLDER)
        need = require_generator and not any(g.enabled for g in self.generators.generators())
        _say(self.problem, strings.OFFICINA_SETUP_NEED_GENERATOR if need else "")
        if need:
            found.append(strings.OFFICINA_SETUP_NEED_GENERATOR)
        return found

    def show_problem(self, text: str) -> None:
        """A problem found outside the rules (a folder not creatable, a save that failed)."""
        _say(self.problem, text)

    def browse(self) -> None:
        folder = officina_dialogs.ask_folder(self, strings.OFFICINA_ROOT_TITLE, self.root())
        if folder is not None:
            self.folder_edit.setText(str(folder))

    # -- reactions ---------------------------------------------------------

    def _edited(self, *_args: object) -> None:
        if self._loading:
            return
        _say(self.problem, "")
        self._refresh()
        self.changed.emit()

    def _refresh(self) -> list[str]:
        """Recompute the inline messages from the core's rules; the problems."""
        found: list[str] = []
        entries = self.generators.entries()
        per_row = generator_problems([g for _row, g in entries])
        self.generators.show_problems({r: p for (r, _g), p in zip(entries, per_row)})
        found += [p for problems in per_row for p in problems]

        self._fill_combo()
        candidate = self.candidate()
        default = default_generator_problem(candidate.officina) or ""
        _say(self.default_problem, default)
        found += [default] if default else []

        root = self.root()
        roots = officina_root_errors(candidate) if root is not None else []
        _say(self.folder_problem, roots[0] if roots else "")
        found += roots[:1]
        _say(self.folder_warning, _folder_warning(root))
        self._fit_table()  # the problems may have made rows taller
        return found

    def _fit_table(self, *_args: object) -> None:
        """Height = header + the first rows (1 to TABLE_MAX_ROWS) + frame."""
        table = self.generators
        rows = min(max(table.rowCount(), 1), TABLE_MAX_ROWS)
        heights = [table.rowHeight(r) if r < table.rowCount()
                   else table.verticalHeader().defaultSectionSize() for r in range(rows)]
        header = table.horizontalHeader().sizeHint().height()
        table.setFixedHeight(header + sum(heights) + 2 * table.frameWidth())

    def _fill_combo(self) -> None:
        names = [g.name for g in self.generators.generators() if g.enabled and g.name]
        current = self.default_combo.currentText()
        chosen = next((n for n in (current, self._preferred) if n in names),
                      names[0] if names else "")
        with QSignalBlocker(self.default_combo):
            self.default_combo.clear()
            self.default_combo.addItems(names)
            self.default_combo.setCurrentIndex(names.index(chosen) if chosen else -1)


def _folder_warning(root: Path | None) -> str:
    if root is None:
        return ""
    if officina_dialogs.in_onedrive(root):
        return strings.SETTINGS_OFFICINA_ONEDRIVE
    if officina_dialogs.on_network(root):
        return strings.SETTINGS_OFFICINA_NETWORK
    return ""


class SetupCard(QFrame):
    """"Configura l'Officina": the form, [Salva] and "Altre impostazioni…".

    ``require_generator``: the card over the initiatives exists because no
    generator is active, so its [Salva] needs one; the card that stands in
    for the initiatives needs the folder, and takes a generator if given.
    ``writing`` says whether the Officina is generating or delivering: the
    folder must not change under those jobs (as Impostazioni refuses it).
    """

    saved = Signal(object)          # the Config written
    settings_requested = Signal()   # "Altre impostazioni…"

    def __init__(self, services: CoreServices, *, require_generator: bool,
                 writing: Callable[[], bool] = lambda: False,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._services = services
        self._require_generator = require_generator
        self._writing = writing
        theme.set_role(self, "card")
        self.title = QLabel(strings.OFFICINA_SETUP_TITLE)
        theme.set_role(self.title, "section")
        self.text = _muted(strings.OFFICINA_SETUP_TEXT_GENERATOR if require_generator
                           else strings.OFFICINA_SETUP_TEXT)
        self.form = SetupForm(services.config.load)
        self.save_button = QPushButton(strings.BTN_SAVE)
        theme.set_role(self.save_button, "primary")
        self.save_button.clicked.connect(self.save)
        self.more_label = QLabel(f'<a href="settings">{strings.OFFICINA_SETUP_MORE}</a>')
        self.more_label.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse
                                                | Qt.TextInteractionFlag.LinksAccessibleByKeyboard)
        self.more_label.linkActivated.connect(lambda _href: self.settings_requested.emit())

        buttons = QHBoxLayout()
        buttons.addWidget(self.save_button)
        buttons.addSpacing(theme.SPACE[3])
        buttons.addWidget(self.more_label)
        buttons.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SPACE[3], theme.SPACE[2], theme.SPACE[3], theme.SPACE[3])
        layout.setSpacing(theme.SPACE[2])
        layout.addWidget(self.title)
        layout.addWidget(self.text)
        layout.addWidget(self.form)
        layout.addLayout(buttons)

    def load(self) -> None:
        """Fill the form from the saved configuration (and the sidecar)."""
        self.form.load(self._services.config.load().officina,
                       self._services.config.sidecar_generators())

    def save(self) -> bool:
        """Check, create the folder, save; ``saved`` on success."""
        form = self.form
        if form.check(require_folder=True, require_generator=self._require_generator):
            return False
        candidate = form.candidate()
        root = candidate.officina.root
        if root != self._services.config.load().officina.root and self._writing():
            form.show_problem(strings.SETTINGS_OFFICINA_BUSY)
            return False
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            form.show_problem(strings.OFFICINA_ROOT_FAILED.format(path=root, reason=exc))
            return False
        try:
            self._services.config.save(candidate)
        except (OSError, ValueError) as exc:
            form.show_problem(strings.OFFICINA_ROOT_SAVE_FAILED.format(reason=exc))
            return False
        self.saved.emit(candidate)
        return True
