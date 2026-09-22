"""The Impostazioni page: the whole configuration as one form.

The widgets, the dialogs and the background jobs live here; the rules live in
``settings_presenter.py`` (:class:`SettingsPresenter` — what the form means as
a ``Config``, whether it is dirty, whether it validates, and the one call that
writes it). This page decides nothing on its own.

Nothing is written until [Salva]: this page is the only writer of
``config.json`` in the application, so an accidental keystroke must not reach
the disk, and a save that would produce an invalid configuration lists its
errors inline instead. ``config_changed`` is re-emitted by the page because
that is where ``MainWindow`` looks for it, and the window broadcasts it to
every *other* page, so this one never hears its own save.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtCore import QTime, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import CoreServices, ScheduleSettings, parse_hhmm
from qtrequestory.ui.env_table import EnvTable
from qtrequestory.ui.pages.schedule_text import schedule_sentence
from qtrequestory.ui.pages.settings_presenter import (
    FormValues,
    SettingsPresenter,
    check_reachable,
    form_of,
    normalised,
)
from qtrequestory.ui.workers import SCHEDULER_JOB, Job, JobRunner

#: The three "Periodo predefinito" buttons (DESIGN-ui §Impostazioni page).
WINDOW_CHOICES = (7, 30, 90)
#: Exclusive job name: an index run refuses a second one while it works.
INDEX_JOB = "index"
CHECK_JOB = "check-envs"
#: What ``QTimeEdit`` shows and what ``ScheduleSettings.start_time`` stores.
TIME_FORMAT = "HH:mm"
#: Shown when the stored start time cannot be parsed at all (hand-edited file).
DEFAULT_START = parse_hhmm(ScheduleSettings().start_time)


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
        #: The re-registration a save may start; kept so a test — and one day a
        #: busy indicator — can tell whether schtasks was actually driven.
        self.scheduler_job: Job | None = None
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
        layout.addWidget(QLabel(strings.SETTINGS_SCHEDULE_LABEL))
        layout.addLayout(self._schedule_row())
        layout.addWidget(self.schedule_logon)
        self.schedule_hint = QLabel(strings.SETTINGS_SCHEDULE_LOGON_HINT)
        self.schedule_hint.setWordWrap(True)
        layout.addWidget(self.schedule_hint)
        self.schedule_summary = QLabel()
        self.schedule_summary.setWordWrap(True)
        layout.addWidget(self.schedule_summary)

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

    def _schedule_row(self) -> QHBoxLayout:
        """Ora di avvio · Riprova ogni N ore · per N ore, plus the logon box.

        The widgets, not the validation, are what stops an impossible schedule:
        the ranges here are the ones ``config.validate`` enforces, so the form
        can never even offer a value the core would refuse.
        """
        self.schedule_start = QTimeEdit()
        self.schedule_start.setDisplayFormat(TIME_FORMAT)
        self.schedule_start.timeChanged.connect(self._on_edited)

        self.schedule_every = _hours_spin(1, 12)
        self.schedule_for = _hours_spin(0, 23, special=strings.SETTINGS_SCHEDULE_NO_REPEAT)
        for spin in (self.schedule_every, self.schedule_for):
            spin.valueChanged.connect(self._on_edited)

        self.schedule_logon = QCheckBox(strings.SETTINGS_SCHEDULE_LOGON)
        self.schedule_logon.toggled.connect(self._on_edited)

        return _row(
            QLabel(strings.SETTINGS_SCHEDULE_START), self.schedule_start,
            QLabel(strings.SETTINGS_SCHEDULE_EVERY), self.schedule_every,
            QLabel(strings.SETTINGS_SCHEDULE_FOR), self.schedule_for,
            stretch_at_end=True,
        )

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
        """The three path fields go through ``normalised`` so that re-picking
        the folder that is already configured is not an edit (Qt's dialogs hand
        back forward slashes, ``str(Path(...))`` hands back Windows ones)."""
        return FormValues(
            mirror_root=normalised(self.mirror_edit.text()),
            environments=self.env_table.environments(),
            editor_path=normalised(self.editor_edit.text()),
            window_days=self._window_days,
            output_dir=normalised(self.output_edit.text()),
            schedule=self.schedule_values(),
        )

    def schedule_values(self) -> ScheduleSettings:
        """The four automatic-synchronisation widgets as the core's own block."""
        return ScheduleSettings(
            start_time=self.schedule_start.time().toString(TIME_FORMAT),
            repeat_every_h=self.schedule_every.value(),
            repeat_for_h=self.schedule_for.value(),
            run_at_logon=self.schedule_logon.isChecked(),
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
        self.set_schedule(form.schedule)
        self.set_window_days(form.window_days)
        self.config_path_label.setText(
            strings.SETTINGS_CONFIG_PATH.format(path=self._services.config.config_path())
        )
        self._show_errors([])
        self._on_edited()

    def set_schedule(self, schedule: ScheduleSettings) -> None:
        """Load the four fields; an unparsable stored time shows the default.

        The time goes through ``parse_hhmm`` — the core's own parser — and NOT
        through ``QTime.fromString``, which is stricter: it rejects ``"7:30"``
        while ``config.validate`` accepts it and the task registers 07:30. The
        form would then show 09:00, disagree with the Sincronizzazione line, be
        dirty without a single edit, and rewrite the user's hour on the next
        save. One parser, one answer.
        """
        start = parse_hhmm(schedule.start_time) or DEFAULT_START
        self.schedule_start.setTime(QTime(start.hour, start.minute))
        self.schedule_every.setValue(schedule.repeat_every_h)
        self.schedule_for.setValue(schedule.repeat_for_h)
        self.schedule_logon.setChecked(schedule.run_at_logon)

    def _on_edited(self) -> None:
        self.schedule_summary.setText(
            strings.SETTINGS_SCHEDULE_SUMMARY.format(
                schedule=schedule_sentence(self.schedule_values())
            )
        )
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
        self._update_scheduled_task()
        if moved:
            self._offer_reindex()

    def _update_scheduled_task(self) -> None:
        """Re-register an existing task so it runs on the schedule just saved.

        Saving a schedule that never reaches Task Scheduler is the one failure
        the user could not see: the form would show 07:30 while the task kept
        09:00. A task that is not registered is left alone — ticking the box on
        the Sincronizzazione page is what creates it, and it will read the
        saved values when it does.

        ``schtasks`` is a subprocess call, so it goes through the runner, and a
        failure is a status line: a modal over a save that *did* succeed would
        say the wrong thing.
        """
        if not self._services.scheduler.status().registered:
            return
        job = self._runner.submit(SCHEDULER_JOB, self._services.scheduler.register)
        if job is None:  # closing, or the Sincronizzazione page is driving schtasks
            return
        self.scheduler_job = job
        job.signals.error.connect(
            lambda _kind, message: self._status(
                strings.SETTINGS_SCHEDULE_UPDATE_FAILED.format(message=message)
            )
        )

    def _show_errors(self, errors: Sequence[str]) -> None:
        if not errors:
            self.errors_label.clear()
            self.errors_label.hide()
            return
        self.errors_label.setText(
            "\n".join(
                [strings.SETTINGS_ERRORS_TITLE,
                 *(strings.SETTINGS_ERROR_BULLET + e for e in errors)]
            )
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
        job = self._runner.submit(CHECK_JOB, check_reachable, self._services.sync, tuple(envs))
        if job is None:  # the application is closing: no job, so no "in corso…"
            return
        self.check_label.setText(strings.SETTINGS_CHECK_RUNNING)
        job.signals.result.connect(self._on_checked)
        # Without this the label would sit on "Verifica in corso…" for ever if
        # a probe raised something `check_reachable` does not swallow.
        job.signals.error.connect(
            lambda _kind, message: self.check_label.setText(
                strings.SETTINGS_CHECK_FAILED.format(message=message)
            )
        )

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


def _hours_spin(minimum: int, maximum: int, *, special: str | None = None) -> QSpinBox:
    """A whole-hours box whose suffix follows the number ("1 ora", "2 ore").

    ``special`` is shown instead of the minimum value, which is how the retry
    window says "nessuna ripetizione" rather than a bare 0.
    """
    spin = QSpinBox()
    spin.setRange(minimum, maximum)
    if special is not None:
        spin.setSpecialValueText(special)

    def follow(value: int) -> None:
        spin.setSuffix(strings.SETTINGS_SCHEDULE_HOUR_ONE if value == 1
                       else strings.SETTINGS_SCHEDULE_HOURS)

    spin.valueChanged.connect(follow)
    follow(spin.value())
    return spin


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
