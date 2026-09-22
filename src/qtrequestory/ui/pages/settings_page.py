"""The Impostazioni page: the whole configuration as one form.

Two objects, on purpose. :class:`SettingsPresenter` owns the *rules* — what the
form means as a ``Config``, whether it differs from what is on disk, whether it
validates, and the one place that writes it — and :class:`SettingsPage` owns
the widgets, the dialogs and the background jobs. The rules are then testable
without a single click, and the page never decides anything.

Nothing is written until [Salva]: this page is the only writer of
``config.json`` in the application, so an accidental keystroke must not reach
the disk, and a save that would produce an invalid configuration lists its
errors inline instead. ``config_changed`` is re-emitted by the page because
that is where ``MainWindow`` looks for it, and the window broadcasts it to
every *other* page, so this one never hears its own save.
"""
from __future__ import annotations

import dataclasses
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import Config, CoreServices, Environment
from qtrequestory.ui.env_table import EnvTable
from qtrequestory.ui.workers import JobRunner

#: The three "Periodo predefinito" buttons (DESIGN-ui §Impostazioni page).
WINDOW_CHOICES = (7, 30, 90)
#: Exclusive job name: an index run refuses a second one while it works.
INDEX_JOB = "index"
CHECK_JOB = "check-envs"


@dataclass(frozen=True)
class FormValues:
    """What the widgets currently say, as plain data.

    Dirty tracking compares two of these rather than two ``Config`` objects:
    the form holds *text*, and ``Path("")`` and ``Path(".")`` are the same
    configuration but a very different thing to show the user.
    """

    mirror_root: str
    environments: list[Environment] = field(default_factory=list)
    editor_path: str = ""
    window_days: int = 30
    output_dir: str = ""


def form_of(cfg: Config) -> FormValues:
    """The form a configuration loads into."""
    return FormValues(
        mirror_root=str(cfg.mirror_root),
        environments=list(cfg.environments),
        editor_path=str(cfg.editor_path) if cfg.editor_path is not None else "",
        window_days=cfg.default_window_days,
        output_dir=str(cfg.output_dir) if cfg.output_dir is not None else "",
    )


def _optional_path(text: str) -> Path | None:
    """An empty field means "use the default", not ``Path("")``."""
    text = text.strip()
    return Path(text) if text else None


def check_reachable(sync, envs: Sequence[str], cancel) -> list[tuple[str, bool]]:
    """One blocking probe per environment; runs in a worker, stops on cancel."""
    results: list[tuple[str, bool]] = []
    for name in envs:
        if cancel.is_set():
            break
        results.append((name, sync.check_reachable(name)))
    return results


class SettingsPresenter(QObject):
    """Form in, configuration out — and the only ``config.save`` call."""

    config_changed = Signal(object)

    def __init__(self, services: CoreServices, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._services = services
        self.loaded: Config = services.config.load()

    def load(self) -> Config:
        self.loaded = self._services.config.load()
        return self.loaded

    def to_config(self, form: FormValues) -> Config:
        """The loaded configuration with the edited fields replaced.

        A copy, never a mutation: the fields this page does not show
        (``compaction_time``, ``sync``, ``index``, ``log_level``) must survive
        a save untouched.
        """
        return dataclasses.replace(
            self.loaded,
            mirror_root=Path(form.mirror_root.strip()),
            environments=list(form.environments),
            editor_path=_optional_path(form.editor_path),
            default_window_days=form.window_days,
            output_dir=_optional_path(form.output_dir),
        )

    def is_dirty(self, form: FormValues) -> bool:
        return form != form_of(self.loaded)

    def mirror_moved(self, form: FormValues) -> bool:
        """Asked *before* saving: afterwards the old root is gone."""
        return Path(form.mirror_root.strip()) != self.loaded.mirror_root

    def errors(self, form: FormValues) -> list[str]:
        """Italian messages from ``config.validate``, plus the one rule the core
        cannot check: a configuration without a mirror root is meaningless to a
        user even though ``Path("")`` validates."""
        found = list(self._services.config.validate(self.to_config(form)))
        if not form.mirror_root.strip():
            found.insert(0, strings.SETTINGS_ERROR_NO_MIRROR)
        return found

    def save(self, form: FormValues) -> list[str]:
        """Persist ``form``; the returned errors mean nothing was written."""
        found = self.errors(form)
        if found:
            return found
        cfg = self.to_config(form)
        self._services.config.save(cfg)
        self.loaded = cfg
        self.config_changed.emit(cfg)
        return []


class SettingsPage(QWidget):
    """The form, its dialogs and the two jobs it can start."""

    config_changed = Signal(object)

    def __init__(
        self,
        services: CoreServices,
        runner: JobRunner,
        window: object | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._services = services
        self._runner = runner
        self._window = window
        self._presenter = SettingsPresenter(services, self)
        self._presenter.config_changed.connect(self.config_changed.emit)
        self._window_days = WINDOW_CHOICES[1]
        self._build()
        self.reload()

    # -- construction ------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        self.browse_mirror_button = _button(
            strings.BTN_BROWSE, lambda: self._browse_folder(
                self.mirror_edit, strings.SETTINGS_MIRROR_CAPTION)
        )
        self.open_mirror_button = _button(strings.BTN_OPEN, self._open_mirror)
        self.mirror_edit = self._path_field(
            layout, strings.SETTINGS_MIRROR_LABEL,
            self.browse_mirror_button, self.open_mirror_button,
        )

        layout.addWidget(QLabel(strings.SETTINGS_ENVS_LABEL))
        self.env_table = EnvTable()
        self.env_table.changed.connect(self._on_edited)
        layout.addWidget(self.env_table, 1)
        self.add_button = _button(strings.BTN_ADD, self.env_table.add_row)
        self.remove_button = _button(strings.BTN_REMOVE, self.env_table.remove_selected)
        self.check_button = _button(strings.SETTINGS_BTN_CHECK, self._check_environments)
        self.import_button = _button(strings.BTN_IMPORT_FILE, self._import_environments)
        layout.addLayout(
            _row(self.add_button, self.remove_button, self.check_button, self.import_button,
                 stretch_at_end=True)
        )
        self.check_label = QLabel(strings.SETTINGS_CHECK_HINT)
        self.check_label.setWordWrap(True)
        layout.addWidget(self.check_label)

        self.browse_editor_button = _button(strings.BTN_BROWSE, self._browse_editor)
        self.detect_button = _button(strings.SETTINGS_BTN_DETECT, self._detect_editor)
        self.editor_edit = self._path_field(
            layout, strings.SETTINGS_EDITOR_LABEL,
            self.browse_editor_button, self.detect_button,
        )

        layout.addWidget(QLabel(strings.SETTINGS_WINDOW_LABEL))
        layout.addLayout(self._window_row())

        self.browse_output_button = _button(
            strings.BTN_BROWSE, lambda: self._browse_folder(
                self.output_edit, strings.SETTINGS_OUTPUT_CAPTION)
        )
        self.output_edit = self._path_field(
            layout, strings.SETTINGS_OUTPUT_LABEL, self.browse_output_button
        )
        self.output_edit.setPlaceholderText(strings.SETTINGS_OUTPUT_HINT)

        layout.addWidget(_separator())
        layout.addWidget(QLabel(strings.SETTINGS_ADVANCED_LABEL))
        self.rebuild_button = _button(strings.SETTINGS_BTN_REBUILD, self._rebuild_index)
        self.wizard_button = _button(strings.SETTINGS_BTN_RERUN_WIZARD, self._rerun_wizard)
        layout.addLayout(_row(self.rebuild_button, self.wizard_button, stretch_at_end=True))
        self.config_path_label = QLabel()
        self.config_path_label.setWordWrap(True)
        self.open_config_button = _button(strings.BTN_OPEN_FOLDER, self._open_config_folder)
        layout.addLayout(_row(self.config_path_label, self.open_config_button))

        self.errors_label = QLabel()
        self.errors_label.setWordWrap(True)
        self.errors_label.hide()
        layout.addWidget(self.errors_label)

        self.cancel_button = _button(strings.BTN_CANCEL, self.reload)
        self.save_button = _button(strings.BTN_SAVE, self.save)
        self.save_button.setEnabled(False)
        layout.addLayout(_row(self.cancel_button, self.save_button, stretch_at_start=True))

    def _path_field(self, layout: QVBoxLayout, label: str, *buttons: QPushButton) -> QLineEdit:
        """A labelled path field with its buttons, already wired to dirty tracking."""
        edit = QLineEdit()
        edit.textChanged.connect(self._on_edited)
        layout.addWidget(QLabel(label))
        layout.addLayout(_row(edit, *buttons))
        return edit

    def _window_row(self) -> QHBoxLayout:
        self.window_buttons: dict[int, QPushButton] = {}
        group = QButtonGroup(self)
        group.setExclusive(True)
        for days in WINDOW_CHOICES:
            button = QPushButton(strings.SETTINGS_WINDOW_DAYS.format(days=days))
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, d=days: self.set_window_days(d))
            group.addButton(button)
            self.window_buttons[days] = button
        return _row(*self.window_buttons.values(), stretch_at_end=True)

    # -- form state --------------------------------------------------------

    def form_values(self) -> FormValues:
        return FormValues(
            mirror_root=self.mirror_edit.text().strip(),
            environments=self.env_table.environments(),
            editor_path=self.editor_edit.text().strip(),
            window_days=self._window_days,
            output_dir=self.output_edit.text().strip(),
        )

    def is_dirty(self) -> bool:
        return self._presenter.is_dirty(self.form_values())

    def window_days(self) -> int:
        return self._window_days

    def set_window_days(self, days: int) -> None:
        """Also used by the buttons; an unlisted value simply checks nothing."""
        self._window_days = days
        for value, button in self.window_buttons.items():
            button.setChecked(value == days)
        self._on_edited()

    def reload(self) -> None:
        """[Annulla], and what follows every successful save."""
        cfg = self._presenter.load()
        form = form_of(cfg)
        self.mirror_edit.setText(form.mirror_root)
        self.env_table.set_environments(form.environments)
        self.editor_edit.setText(form.editor_path)
        self.output_edit.setText(form.output_dir)
        self.set_window_days(form.window_days)
        self.config_path_label.setText(
            strings.SETTINGS_CONFIG_PATH.format(path=self._services.config.config_path())
        )
        self._show_errors([])
        self._on_edited()

    def _on_edited(self) -> None:
        self.save_button.setEnabled(self.is_dirty())

    # -- saving ------------------------------------------------------------

    def save(self) -> None:
        form = self.form_values()
        moved = self._presenter.mirror_moved(form)
        errors = self._presenter.save(form)
        self._show_errors(errors)
        if errors:
            return
        self.reload()  # the saved configuration, normalised, is the new baseline
        self._status(strings.SETTINGS_SAVED)
        if moved:
            self._offer_reindex()

    def _show_errors(self, errors: Sequence[str]) -> None:
        if not errors:
            self.errors_label.clear()
            self.errors_label.hide()
            return
        self.errors_label.setText(
            "\n".join([strings.SETTINGS_ERRORS_TITLE, *(f"• {e}" for e in errors)])
        )
        self.errors_label.show()

    def _offer_reindex(self) -> None:
        answer = QMessageBox.question(
            self, strings.SETTINGS_REINDEX_TITLE, strings.SETTINGS_REINDEX_QUESTION
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._start_index(full_rebuild=False)

    # -- jobs --------------------------------------------------------------

    def _rebuild_index(self) -> None:
        answer = QMessageBox.question(
            self, strings.SETTINGS_REBUILD_TITLE, strings.SETTINGS_REBUILD_QUESTION
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._start_index(full_rebuild=True)

    def _start_index(self, *, full_rebuild: bool) -> None:
        envs = [e.name for e in self._presenter.loaded.enabled_environments()]
        job = self._runner.submit(
            INDEX_JOB, self._services.index.update, envs, full_rebuild=full_rebuild
        )
        if job is None:  # already running, or the application is closing
            return
        job.signals.result.connect(self._on_index_done)
        job.signals.error.connect(
            lambda _kind, message: self._status(
                strings.SETTINGS_INDEX_FAILED.format(message=message)
            )
        )
        self._status(strings.SETTINGS_INDEX_STARTED)

    def _on_index_done(self, report: object) -> None:
        self._status(
            strings.SETTINGS_INDEX_DONE.format(n=getattr(report, "indexed_files", 0))
        )

    def _check_environments(self) -> None:
        envs = [e.name for e in self.env_table.environments()]
        if not envs:
            self.check_label.setText(strings.SETTINGS_CHECK_NONE)
            return
        self.check_label.setText(strings.SETTINGS_CHECK_RUNNING)
        job = self._runner.submit(CHECK_JOB, check_reachable, self._services.sync, tuple(envs))
        if job is not None:
            job.signals.result.connect(self._on_checked)

    def _on_checked(self, results: object) -> None:
        parts = [
            (strings.SETTINGS_CHECK_REACHABLE if ok else strings.SETTINGS_CHECK_UNREACHABLE)
            .format(name=name)
            for name, ok in results or ()
        ]
        self.check_label.setText(
            strings.SETTINGS_CHECK_SEPARATOR.join(parts) or strings.SETTINGS_CHECK_NONE
        )

    # -- dialogs and folders -----------------------------------------------

    def _browse_folder(self, edit: QLineEdit, caption: str) -> None:
        chosen = QFileDialog.getExistingDirectory(self, caption, edit.text())
        if chosen:  # empty means the user cancelled: leave the field alone
            edit.setText(chosen)

    def _browse_editor(self) -> None:
        chosen, _filter = QFileDialog.getOpenFileName(
            self, strings.SETTINGS_EDITOR_CAPTION, self.editor_edit.text(),
            strings.SETTINGS_EDITOR_FILTER,
        )
        if chosen:
            self.editor_edit.setText(chosen)

    def _detect_editor(self) -> None:
        found = self._services.config.detect_editor()
        if found is None:
            self._status(strings.SETTINGS_EDITOR_NOT_FOUND)
            return
        self.editor_edit.setText(str(found))
        self._status(strings.SETTINGS_EDITOR_FOUND.format(path=found))

    def _import_environments(self) -> None:
        chosen, _filter = QFileDialog.getOpenFileName(
            self, strings.ENV_IMPORT_CAPTION, "", strings.ENV_IMPORT_FILTER
        )
        if not chosen:
            return
        try:
            self.env_table.import_from_file(
                Path(chosen), self._services.config.import_environments_file
            )
        except ValueError as exc:
            QMessageBox.warning(
                self, strings.ENV_IMPORT_ERROR_TITLE,
                strings.ENV_IMPORT_ERROR.format(error=exc),
            )

    def _open_mirror(self) -> None:
        text = self.mirror_edit.text().strip()
        if text:
            self._services.extract.open_folder(Path(text))

    def _open_config_folder(self) -> None:
        self._services.extract.open_folder(self._services.config.config_path().parent)

    def _rerun_wizard(self) -> None:
        hook = getattr(self._window, "rerun_wizard", None)
        if not callable(hook):
            return
        hook()
        # The wizard writes the configuration itself; reload only when it did,
        # so a cancelled wizard does not throw away what is in the form.
        if self._services.config.load() != self._presenter.loaded:
            self.reload()

    def _status(self, text: str) -> None:
        setter = getattr(self._window, "set_status", None)
        if callable(setter):
            setter(text)


# -- small layout helpers ----------------------------------------------------

def _button(text: str, slot: Callable[[], object]) -> QPushButton:
    """``clicked`` carries a ``checked`` flag no slot here wants."""
    button = QPushButton(text)
    button.clicked.connect(lambda _checked=False: slot())
    return button


def _row(*widgets: QWidget, stretch_at_end: bool = False,
         stretch_at_start: bool = False) -> QHBoxLayout:
    row = QHBoxLayout()
    if stretch_at_start:
        row.addStretch(1)
    for widget in widgets:
        row.addWidget(widget)
    if stretch_at_end:
        row.addStretch(1)
    return row


def _separator() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Sunken)
    return line
