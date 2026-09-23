"""The Impostazioni page: a section list on the left, one section on the right.

The seven sections are built by ``settings_sections.py`` (layout only); the
rules live in ``settings_presenter.py`` (:class:`SettingsPresenter` — what the
form means as a ``Config``, whether it is dirty, whether it validates, and the
one call that writes it). This page holds the behaviour: dirty tracking, the
dialogs and the background jobs.

Nothing is written until [Salva], which only exists — in the dark "Modifiche
non salvate" bar — while there is something to save: this page is the only
writer of ``config.json`` in the application, so an accidental keystroke must
not reach the disk, and a save that would produce an invalid configuration
lists its errors instead. Leaving the page with unsaved edits asks first
(:meth:`SettingsPage.can_leave`, consulted by ``MainWindow.show_page``).

Two things are deliberately *outside* that flow: the theme (Aspetto), applied
and remembered the moment it is picked, and the jobs ([Ricostruisci indice],
[Verifica]).

``config_changed`` is re-emitted by the page because that is where
``MainWindow`` looks for it, and the window broadcasts it to every *other*
page, so this one never hears its own save.
"""
from __future__ import annotations

from PySide6.QtCore import QTime, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import CoreServices, ScheduleSettings, parse_hhmm
from qtrequestory.ui.pages.schedule_text import schedule_sentence
from qtrequestory.ui.pages.settings_actions import CHECK_JOB, INDEX_JOB, SettingsActions, ask_leave
from qtrequestory.ui.pages.settings_presenter import (
    FormValues,
    PrefValues,
    SettingsPresenter,
    form_of,
    load_prefs,
    normalised,
    save_prefs,
)
from qtrequestory.ui.pages.settings_sections import BUILDERS, TIME_FORMAT, WINDOW_CHOICES
from qtrequestory.ui.pages.settings_widgets import button
from qtrequestory.ui.theme import Mode
from qtrequestory.ui.workers import SCHEDULER_JOB, Job, JobRunner

__all__ = ["CHECK_JOB", "INDEX_JOB", "SECTION_KEYS", "SettingsPage", "ask_leave"]

#: The keys ``show_section`` accepts, in list order (wave-D contract).
SECTION_KEYS = tuple(key for key, _label, _builder in BUILDERS)
#: Shown when the stored start time cannot be parsed at all (hand-edited file).
DEFAULT_START = parse_hhmm(ScheduleSettings().start_time)
#: Width of the section list (the mockup's 180 px, plus the list's padding).
NAV_WIDTH = 200


class SettingsPage(SettingsActions, QWidget):
    """Section list + stacked sections + the unsaved-changes bar."""

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
        self._key_mode = "exact"
        self._prefs = PrefValues()
        #: The re-registration a save may start; kept so a test — and one day a
        #: busy indicator — can tell whether schtasks was actually driven.
        self.scheduler_job: Job | None = None
        self._build()
        self.reload()

    # -- construction ------------------------------------------------------

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)  # as Sincronizzazione
        outer.setSpacing(theme.SPACE[2])
        self.title_label = QLabel(strings.SETTINGS_TITLE)
        theme.set_role(self.title_label, "pageTitle")
        outer.addWidget(self.title_label)

        self.nav = QListWidget()
        self.nav.setObjectName("settingsNav")
        self.nav.setFixedWidth(NAV_WIDTH)
        self.sections = QStackedWidget()
        self.section_widgets: dict[str, QWidget] = {}
        for key, label, build in BUILDERS:
            self.nav.addItem(label)
            section = build(self)
            self.section_widgets[key] = section
            self.sections.addWidget(section)
        self.nav.currentRowChanged.connect(self._on_section_row)

        # A tall section (Ambienti) does not fit a 1366x768 laptop, where the
        # page gets about 420 px: the sections scroll, the save bar does not.
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidget(self.sections)
        body = QHBoxLayout()
        body.setSpacing(theme.SPACE[3])
        body.addWidget(self.nav)
        body.addWidget(self.scroll, 1)
        outer.addLayout(body, 1)

        # Pinned under the sections: the errors are about the save the user is
        # attempting, so they sit next to its button.
        self.errors_label = QLabel()
        self.errors_label.setWordWrap(True)
        self.errors_label.hide()
        outer.addWidget(self.errors_label)
        outer.addWidget(self._save_bar())
        self.nav.setCurrentRow(0)

    def _save_bar(self) -> QFrame:
        self.save_bar = QFrame()
        self.save_bar.setObjectName("settingsSaveBar")
        self.save_bar_label = QLabel(strings.SETTINGS_UNSAVED)
        self.cancel_button = button(strings.BTN_CANCEL, self.reload)
        self.save_button = button(strings.BTN_SAVE, self.save)
        theme.set_role(self.save_button, "primary")
        layout = QHBoxLayout(self.save_bar)
        layout.setContentsMargins(theme.SPACE[2], theme.SPACE[1], theme.SPACE[1], theme.SPACE[1])
        layout.addWidget(self.save_bar_label)
        layout.addStretch(1)
        layout.addWidget(self.cancel_button)
        layout.addWidget(self.save_button)
        self.save_bar.hide()
        return self.save_bar

    # -- sections ----------------------------------------------------------

    def show_section(self, key: str) -> None:
        """Select a section by key ("appearance" … "advanced"); unknown keys are ignored."""
        if key in SECTION_KEYS:
            self.nav.setCurrentRow(SECTION_KEYS.index(key))

    def current_section(self) -> str:
        return SECTION_KEYS[self.sections.currentIndex()]

    def _on_section_row(self, index: int) -> None:
        if index < 0:
            return
        self.sections.setCurrentIndex(index)
        # A QStackedWidget is as tall as its tallest page; with the others
        # ignored, the scroll area follows the section on screen.
        for position in range(self.sections.count()):
            policy = (QSizePolicy.Policy.Preferred if position == index
                      else QSizePolicy.Policy.Ignored)
            self.sections.widget(position).setSizePolicy(policy, policy)
        self.sections.adjustSize()
        self.scroll.verticalScrollBar().setValue(0)

    # -- Aspetto: the theme, outside the Save flow -------------------------

    def set_theme(self, mode: Mode) -> None:
        """Remember ``mode`` and repaint the whole application with it, now."""
        mode = Mode(mode)
        self._show_theme(mode)
        theme.save_mode(mode)
        app = QApplication.instance()
        if app is not None:
            theme.apply(app, mode)

    def _show_theme(self, mode: Mode) -> None:
        for value, segment in self.theme_buttons.items():
            segment.setChecked(value is mode)

    # -- form state --------------------------------------------------------

    def form_values(self) -> FormValues:
        """The path fields go through ``normalised`` so that re-picking the
        folder that is already configured is not an edit (Qt's dialogs hand
        back forward slashes, ``str(Path(...))`` hands back Windows ones)."""
        return FormValues(
            mirror_root=normalised(self.mirror_path.text()),
            environments=self.env_table.environments(),
            editor_path=normalised(self.editor_path.text()),
            window_days=self._window_days,
            output_dir=normalised(self.output_path.text()),
            schedule=self.schedule_values(),
        )

    def pref_values(self) -> PrefValues:
        return PrefValues(group_by_fdi=self.group_by_fdi.isChecked(), key_mode=self._key_mode)

    def schedule_values(self) -> ScheduleSettings:
        """The four automatic-synchronisation widgets as the core's own block."""
        return ScheduleSettings(
            start_time=self.schedule_start.time().toString(TIME_FORMAT),
            repeat_every_h=self.schedule_every.value(),
            repeat_for_h=self.schedule_for.value(),
            run_at_logon=self.schedule_logon.isChecked(),
        )

    def is_dirty(self) -> bool:
        return self._presenter.is_dirty(self.form_values()) or self.pref_values() != self._prefs

    def window_days(self) -> int:
        return self._window_days

    def set_window_days(self, days: int) -> None:
        """Also used by the buttons; an unlisted value simply checks nothing."""
        self._window_days = days
        for value, segment in self.window_buttons.items():
            segment.setChecked(value == days)
        self.on_edited()

    def key_mode(self) -> str:
        return self._key_mode

    def set_key_mode(self, mode: str) -> None:
        self._key_mode = mode
        for value, segment in self.key_mode_buttons.items():
            segment.setChecked(value == mode)
        self.on_edited()

    def reload(self) -> None:
        """[Annulla], and what follows every successful save."""
        form = form_of(self._presenter.load())
        self._prefs = load_prefs()
        self.mirror_path.setText(form.mirror_root)
        self.env_table.set_environments(form.environments)
        self.editor_path.setText(form.editor_path)
        self.output_path.setText(form.output_dir)
        self.set_schedule(form.schedule)
        self.set_window_days(form.window_days)
        self.group_by_fdi.setChecked(self._prefs.group_by_fdi)
        self.set_key_mode(self._prefs.key_mode)
        self._show_theme(theme.saved_mode())
        self.config_path_label.set_full_text(str(self._services.config.config_path()))
        self._show_errors([])
        self._refresh_index_state()
        self.on_edited()

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

    def on_edited(self, *_args: object) -> None:
        """Any widget changed: refresh the summary and the save bar."""
        self.schedule_summary.setText(
            strings.SETTINGS_SCHEDULE_SUMMARY.format(
                schedule=schedule_sentence(self.schedule_values())
            )
        )
        self.output_default_button.setVisible(bool(self.output_path.text()))
        dirty = self.is_dirty()
        self.save_bar.setVisible(dirty)
        self.save_button.setEnabled(dirty)

    def on_data_changed(self) -> None:
        """A sync or an index job finished (``MainWindow`` hook)."""
        self._refresh_index_state()

    def _refresh_index_state(self) -> None:
        coverages = [self._services.index.coverage(env.name)
                     for env in self._presenter.loaded.enabled_environments()]
        coverages = [c for c in coverages if c is not None]
        if not coverages:
            self.index_label.setText(strings.SETTINGS_INDEX_EMPTY)
            return
        self.index_label.setText(strings.SETTINGS_INDEX_STATE.format(
            files=_count(sum(c.n_files for c in coverages)),
            entries=_count(sum(c.n_entries for c in coverages)),
            last=max(c.last_day for c in coverages).strftime("%d/%m/%Y"),
        ))

    # -- leaving -----------------------------------------------------------

    def can_leave(self) -> bool:
        """``MainWindow`` asks before switching away: Salva / Scarta / Annulla."""
        if not self.is_dirty():
            return True
        answer = ask_leave(self)
        if answer == "save":
            return self.save()
        if answer == "discard":
            self.reload()
            return True
        return False

    # -- saving ------------------------------------------------------------

    def save(self) -> bool:
        """Write what changed; False (and the errors shown) when nothing could be."""
        if not self.is_dirty():
            return True
        form = self.form_values()
        config_dirty = self._presenter.is_dirty(form)
        moved = config_dirty and self._presenter.mirror_moved(form)
        if config_dirty:
            errors = self._presenter.save(form)
            self._show_errors(errors)
            if errors:
                return False
        if self.pref_values() != self._prefs:
            save_prefs(self.pref_values())
        self.reload()  # the saved configuration, normalised, is the new baseline
        self._notify(strings.SETTINGS_SAVED)
        if config_dirty:
            self.update_scheduled_task()
        if moved:
            self._offer_reindex()
        return True

    def update_scheduled_task(self) -> None:
        """Re-register an existing task so it runs on the schedule just saved.

        Saving a schedule that never reaches Task Scheduler is the one failure
        the user could not see: the form would show 07:30 while the task kept
        09:00. A task that is not registered is left alone — ticking the box on
        the Sincronizzazione page is what creates it, and it will read the
        saved values when it does.

        ``schtasks`` is a subprocess call, so it goes through the runner. A
        failure — or a refusal because the Sincronizzazione page is driving
        schtasks right now — is a persistent banner with [Riprova] in the
        Sincronizzazione automatica section: a modal over a save that *did*
        succeed would say the wrong thing, and a status line goes away.
        """
        self.schedule_banner.hide()
        if not self._services.scheduler.status().registered:
            return
        job = self._runner.submit(SCHEDULER_JOB, self._services.scheduler.register)
        if job is None:
            if self._runner.is_running(SCHEDULER_JOB):
                self._on_schedule_failed("", strings.SETTINGS_SCHEDULE_BUSY)
            return  # otherwise the application is closing
        self.scheduler_job = job
        job.signals.error.connect(self._on_schedule_failed)

    def _on_schedule_failed(self, _kind: str, message: str) -> None:
        self.schedule_banner_label.setText(
            strings.SETTINGS_SCHEDULE_UPDATE_FAILED.format(message=message))
        self.schedule_banner.show()

    def _show_errors(self, errors: list[str]) -> None:
        if not errors:
            self.errors_label.clear()
            self.errors_label.hide()
            return
        self.errors_label.setText(
            "\n".join([strings.SETTINGS_ERRORS_TITLE,
                       *(strings.SETTINGS_ERROR_BULLET + e for e in errors)])
        )
        self.errors_label.show()


def _count(n: int) -> str:
    """Thousands with the Italian dot: 3.412."""
    return f"{n:,}".replace(",", ".")
