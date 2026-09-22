"""The Sincronizzazione page: cards, progress strip, registro, auto-sync.

One long-running job, four things that watch it. The page keeps almost no
state of its own: the arithmetic lives in :class:`~.progress_model.ProgressModel`,
the wording in :mod:`~.sync_format`, the per-environment verdicts in the cards,
and :class:`SyncPresenter` holds what is left — which run is in flight, what
each environment ended up doing, and the one-line summary the window shows in
its status bar.

Three things are deliberately *not* here:

* **No request ids.** ``JobRunner`` refuses a second ``"sync"`` while one runs
  and silences superseded jobs on the GUI thread, so a stale event cannot reach
  a live strip (``ui/workers.py``).
* **No blocking calls.** ``sync.run`` and the scheduler's ``register`` /
  ``unregister`` are subprocess-and-network work and go through the runner.
  ``env_status`` and ``lock_holder`` are the documented cheap ones (a state
  file and a directory listing) and are called inline.
* **No wording.** Every literal the user reads comes from ``strings.sync``,
  except the registro lines, which come from the core's own ``LoggingSink`` via
  :func:`~.sync_format.log_line` so the panel and ``sync.log`` cannot drift.
"""
from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QObject, QSignalBlocker, Qt, QTimer, Signal
from PySide6.QtGui import QFontDatabase, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import (
    Config,
    CoreServices,
    EnvFinished,
    EnvStarted,
    Event,
    JobReport,
)
from qtrequestory.ui.pages import progress_model as pm
from qtrequestory.ui.pages import sync_format as fmt
from qtrequestory.ui.pages.env_card import EnvCard
from qtrequestory.ui.workers import Job, JobRunner

__all__ = ["SyncPage", "SyncPresenter"]

#: Lines of ``sync.log`` the registro opens with.
LOG_TAIL_LINES = 50
#: Blocks the registro keeps (DESIGN-ui: "max 2000 righe").
LOG_MAX_BLOCKS = 2000


class SyncPresenter(QObject):
    """What the page knows between two events: outcomes and the summary.

    A plain object with one signal so the summary can be asserted — and one
    day recomputed — without a widget in sight.
    """

    summary_changed = Signal(str)

    def __init__(self, services: CoreServices, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._services = services
        self.progress = pm.ProgressModel()
        #: env -> ``EnvResult.status`` of the last finished run.
        self.outcomes: dict[str, str] = {}
        #: env -> how many files failed in that run (the amber pill needs it).
        self.failures: dict[str, int] = {}

    def handle(self, ev: Event) -> None:
        self.progress.handle(ev)
        if isinstance(ev, EnvFinished):
            self.outcomes[ev.env] = ev.result.status
            self.failures[ev.env] = ev.result.failed

    def environments(self) -> list[str]:
        return [e.name for e in self._services.config.load().enabled_environments()]

    def summary(self) -> str:
        """"svil: oggi 11:23 · coll: non raggiungibile" for the status bar.

        An environment the last run could not reach says so: "ieri 15:48" on
        its own would suggest the mirror is merely a little old, when in fact
        nothing got through this time.
        """
        parts = []
        for name in self.environments():
            if self.outcomes.get(name) == "unreachable":
                when = strings.SYNC_WHEN_UNREACHABLE
            else:
                when = fmt.format_when(self._services.sync.env_status(name).last_success)
            parts.append(strings.SYNC_SUMMARY_ENTRY.format(env=name, when=when))
        return strings.SYNC_SUMMARY_SEP.join(parts)

    def emit_summary(self) -> str:
        text = self.summary()
        self.summary_changed.emit(text)
        return text


class SyncPage(QWidget):
    """Rail entry ``"sync"``. Built by ``main_window.PAGES``."""

    summary_changed = Signal(str)

    #: How often the lock file is checked while the page is alive (DESIGN-ui).
    LOCK_POLL_MS = 2000

    def __init__(self, services: CoreServices, runner: JobRunner,
                 window: object | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._services = services
        self._runner = runner
        self._window = window
        self._cards: list[EnvCard] = []
        self.presenter = SyncPresenter(services, self)
        self.sync_job: Job | None = None
        self.scheduler_job: Job | None = None

        self._build()
        self.presenter.summary_changed.connect(self.summary_changed)
        self.rebuild_cards()
        self._rebuild_menu()
        self.refresh_scheduler()
        self.log_view.setPlainText("\n".join(services.sync.tail_sync_log(LOG_TAIL_LINES)))

        self.lock_timer = QTimer(self)
        self.lock_timer.setInterval(self.LOCK_POLL_MS)
        self.lock_timer.timeout.connect(self.refresh_lock)
        self.lock_timer.start()
        self.refresh_lock()
        self.presenter.emit_summary()
        # One connection for the whole page instead of one per card; Qt drops
        # it when the page is destroyed, so a rebuilt cards row leaks nothing.
        QGuiApplication.styleHints().colorSchemeChanged.connect(self.retune)

    # -- construction ------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addLayout(self._build_header())
        self.cards_row = QHBoxLayout()
        self.cards_row.setSpacing(12)
        layout.addLayout(self.cards_row)
        self.lock_label = QLabel(strings.SYNC_LOCK_HELD)
        self.lock_label.hide()
        layout.addWidget(self.lock_label)
        layout.addWidget(self._build_strip())
        layout.addWidget(QLabel(strings.SYNC_LOG_TITLE))
        layout.addWidget(self._build_log(), 1)
        layout.addWidget(self._build_auto())

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        title = QLabel(strings.SYNC_TITLE)
        title_font = title.font()
        title_font.setPointSize(title_font.pointSize() + 3)
        title_font.setBold(True)
        title.setFont(title_font)

        self.sync_menu = QMenu(self)  # filled by _rebuild_menu (it follows the config)
        self.sync_button = QToolButton()
        self.sync_button.setText(strings.SYNC_BTN_NOW)
        self.sync_button.setToolTip(strings.SYNC_BTN_NOW_TOOLTIP)
        self.sync_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.sync_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.sync_button.setMenu(self.sync_menu)
        self.sync_button.clicked.connect(lambda: self.start_sync())

        self.cancel_button = QPushButton(strings.BTN_CANCEL)
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel)

        row.addWidget(title)
        row.addStretch(1)
        row.addWidget(self.sync_button)
        row.addWidget(self.cancel_button)
        return row

    def _build_strip(self) -> QWidget:
        box = QFrame()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        top = QHBoxLayout()
        self.progress_label = QLabel()
        self.totals_label = QLabel()
        self.totals_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(self.progress_label, 1)
        top.addWidget(self.totals_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setTextVisible(False)
        self.rate_label = QLabel()
        self.outcome_label = QLabel()
        layout.addLayout(top)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.rate_label)
        layout.addWidget(self.outcome_label)
        self._show_strip(False)
        return box

    def _build_log(self) -> QPlainTextEdit:
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(LOG_MAX_BLOCKS)
        self.log_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.log_view.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.log_view.setMinimumHeight(120)
        return self.log_view

    def _build_auto(self) -> QWidget:
        box = QFrame()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.auto_check = QCheckBox(strings.SYNC_AUTO_TITLE)
        self.auto_check.toggled.connect(self._on_auto_toggled)
        self.auto_status = QLabel()
        self.auto_status.setWordWrap(True)
        warning = QHBoxLayout()
        self.exe_warning = QLabel()
        self.exe_warning.setWordWrap(True)
        self.exe_button = QPushButton(strings.SYNC_AUTO_EXE_UPDATE)
        self.exe_button.clicked.connect(lambda: self._run_scheduler(True))
        warning.addWidget(self.exe_warning, 1)
        warning.addWidget(self.exe_button)
        layout.addWidget(self.auto_check)
        layout.addWidget(self.auto_status)
        layout.addLayout(warning)
        return box

    # -- cards -------------------------------------------------------------

    def rebuild_cards(self) -> None:
        """One card per *enabled* environment, filled from ``sync.env_status``."""
        while self.cards_row.count():
            item = self.cards_row.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._cards = []
        for env in self._services.config.load().enabled_environments():
            card = EnvCard(env.name, env.url, self)
            self._cards.append(card)
            self.cards_row.addWidget(card)
        self.cards_row.addStretch(1)
        self.refresh_cards()

    def refresh_cards(self) -> None:
        for card in self._cards:
            card.set_status(self._services.sync.env_status(card.env_name))
            outcome = self.presenter.outcomes.get(card.env_name)
            if outcome is not None:
                card.set_outcome(outcome, self.presenter.failures.get(card.env_name, 0))

    def cards(self) -> list[EnvCard]:
        return list(self._cards)

    def card(self, env_name: str) -> EnvCard | None:
        return next((c for c in self._cards if c.env_name == env_name), None)

    def on_config_changed(self, cfg: Config | None = None) -> None:
        """Impostazioni saved: the environments — or the schedule — may have changed.

        The broadcast payload is only a notification: every service reads the
        configuration back through ``ConfigService.current``, so reloading is
        what keeps the cards, the menu and the core agreeing on one list.
        """
        self.rebuild_cards()
        self._rebuild_menu()
        self.presenter.emit_summary()
        self.refresh_scheduler()  # the status line describes the saved schedule

    def retune(self) -> None:
        """Light/dark switched: the pills were coloured for the old palette."""
        for card in self._cards:
            card.retune()

    # -- running a sync ----------------------------------------------------

    def start_sync(self, envs: Sequence[str] | None = None, *, dry_run: bool = False) -> None:
        """"Sincronizza ora" — always ``force=True`` (DESIGN-ui).

        ``envs=None`` means every enabled environment, which is what the core
        does with it too; the page does not expand the list itself so the two
        cannot disagree about what "enabled" means.
        """
        if self._services.sync.lock_holder() is not None and not self._runner.is_running("sync"):
            self.refresh_lock()  # the scheduled task got there first
            self._show_status(strings.SYNC_LOCK_HELD)
            return
        job = self._runner.submit("sync", self._services.sync.run, envs,
                                  force=True, dry_run=dry_run)
        if job is None:  # the runner refuses a second sync; it says so itself
            return
        self.sync_job = job
        job.signals.progress.connect(self.handle_event)
        job.signals.result.connect(self._on_result)
        job.signals.error.connect(self._on_error)
        job.signals.finished.connect(self._on_finished)
        self.presenter.progress.reset()
        self.outcome_label.clear()
        self._set_running(True)
        self.progress_label.setText(strings.SYNC_PROGRESS_STARTING)
        for card in self._cards:
            if envs is None or card.env_name in envs:
                card.set_running(True)

    def cancel(self) -> None:
        """Ask the core to stop; the strip says so until ``finished`` arrives."""
        if self.sync_job is None or not self.sync_job.is_running():
            return
        self.sync_job.cancel()
        self.cancel_button.setEnabled(False)
        self.progress_label.setText(strings.SYNC_PROGRESS_CANCELLING)
        self.totals_label.clear()
        self.rate_label.clear()

    def handle_event(self, ev: Event) -> None:
        """One core event: the strip, the registro and the cards."""
        self.presenter.handle(ev)
        if isinstance(ev, EnvStarted):
            card = self.card(ev.env)
            if card is not None:
                card.set_running(True)
        elif isinstance(ev, EnvFinished):
            card = self.card(ev.env)
            if card is not None:
                card.set_running(False)
                card.set_outcome(ev.result.status, ev.result.failed)
        line = fmt.log_line(ev)
        if line is not None:
            self.log_view.appendPlainText(line)
        if not self._cancelling():
            self._render_strip()

    # -- strip -------------------------------------------------------------

    def _render_strip(self) -> None:
        """Repaint from one snapshot; an empty label keeps what is on screen."""
        texts = fmt.strip_texts(self.presenter.progress.snapshot())
        if texts.label:
            self.progress_label.setText(texts.label)
        self.totals_label.setText(texts.totals)
        self.rate_label.setText(texts.rate)
        self.progress_bar.setValue(texts.percent)

    def _show_strip(self, visible: bool) -> None:
        for widget in (self.progress_label, self.totals_label, self.progress_bar,
                       self.rate_label):
            widget.setVisible(visible)
        if not visible:
            self.progress_bar.setValue(0)

    def _cancelling(self) -> bool:
        return self.sync_job is not None and self.sync_job.token.is_set()

    # -- job lifecycle -----------------------------------------------------

    def _set_running(self, running: bool) -> None:
        self.cancel_button.setEnabled(running)
        self._show_strip(running)
        self.refresh_lock()

    def _on_result(self, report: JobReport) -> None:
        """``sync.run`` handles cancellation itself and reports exit code 3."""
        self.outcome_label.setText({
            0: strings.SYNC_DONE,
            1: strings.SYNC_DONE_ERRORS,
            2: strings.SYNC_DONE_UNREACHABLE,
            3: strings.SYNC_CANCELLED,
        }.get(report.exit_code, strings.SYNC_DONE))

    def _on_error(self, _kind: str, error: str) -> None:
        self.outcome_label.setText(strings.SYNC_ERROR.format(error=error))

    def _on_finished(self) -> None:
        for card in self._cards:
            card.set_running(False)
        self._set_running(False)
        self.refresh_cards()
        self.presenter.emit_summary()
        self._show_status(self.outcome_label.text())

    # -- lock held by the scheduled run ------------------------------------

    def refresh_lock(self) -> None:
        """Polled every :data:`LOCK_POLL_MS`; also called around every run.

        The lock is ours while *we* are the ones syncing, so the warning only
        appears when somebody else — the scheduled task — holds it.
        """
        ours = self._runner.is_running("sync")
        held = self._services.sync.lock_holder() is not None and not ours
        self.lock_label.setVisible(held)
        self.sync_button.setEnabled(not held and not ours)

    # -- automatic synchronisation -----------------------------------------

    def refresh_scheduler(self) -> None:
        """Re-read the task and repaint the checkbox, the line and the warning."""
        task = self._services.scheduler.status()
        self._set_scheduler_busy(False)
        with QSignalBlocker(self.auto_check):  # a repaint is not a user decision
            self.auto_check.setChecked(task.registered)
        self.auto_status.setText(
            fmt.format_task_status(task, self._services.config.load().schedule)
        )
        mismatch = task.registered and not task.exe_matches
        self.exe_warning.setText(
            strings.SYNC_AUTO_EXE_MISMATCH.format(path=task.command) if mismatch else "")
        self.exe_warning.setVisible(mismatch)
        self.exe_button.setVisible(mismatch)

    def _on_auto_toggled(self, checked: bool) -> None:
        reason = self._services.scheduler.unstable_location_reason() if checked else None
        if reason is not None and not self.confirm_unstable(reason):
            with QSignalBlocker(self.auto_check):
                self.auto_check.setChecked(False)
            return
        self._run_scheduler(checked)

    def _run_scheduler(self, register: bool) -> None:
        """``schtasks`` is a subprocess call: never on the GUI thread."""
        scheduler = self._services.scheduler
        job = self._runner.submit("scheduler",
                                  scheduler.register if register else scheduler.unregister)
        if job is None:
            return
        self.scheduler_job = job
        self._set_scheduler_busy(True)
        job.signals.error.connect(
            lambda _kind, error: self._show_status(strings.SYNC_AUTO_FAILED.format(error=error)))
        job.signals.finished.connect(self.refresh_scheduler)

    def _set_scheduler_busy(self, busy: bool) -> None:
        """``schtasks`` takes no cancel token, so two calls in flight could land
        in either order: the controls stay locked until the current one is back."""
        self.auto_check.setEnabled(not busy)
        self.exe_button.setEnabled(not busy)

    def confirm_unstable(self, reason: str) -> bool:
        """Show the "posizione poco stabile" question; True = register anyway."""
        box = self.build_unstable_dialog(reason)
        try:
            return box.exec() == QMessageBox.StandardButton.Yes
        finally:
            box.deleteLater()

    def build_unstable_dialog(self, reason: str) -> QMessageBox:
        """The dialog without showing it, so its wording can be tested."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(strings.SYNC_AUTO_UNSTABLE_TITLE)
        box.setText(strings.SYNC_AUTO_UNSTABLE_TEXT.format(reason=reason))
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        box.button(QMessageBox.StandardButton.Yes).setText(strings.SYNC_AUTO_UNSTABLE_OK)
        box.button(QMessageBox.StandardButton.No).setText(strings.BTN_CANCEL)
        return box

    # -- talking to the window ---------------------------------------------

    # ``summary_changed`` is *not* pushed into the window from here: the shell
    # connects that signal to ``set_sync_summary`` itself (main_window
    # §"Optional hooks"), and doing both would set the same text twice.

    def _show_status(self, text: str) -> None:
        setter = getattr(self._window, "set_status", None)
        if text and callable(setter):
            setter(text)

    # -- internals ---------------------------------------------------------

    def _rebuild_menu(self) -> None:
        self.sync_menu.clear()
        self.sync_menu.addAction(strings.SYNC_MENU_ALL).triggered.connect(
            lambda: self.start_sync())
        self.sync_menu.addSeparator()
        for name in self.presenter.environments():
            action = self.sync_menu.addAction(strings.SYNC_MENU_ONLY.format(env=name))
            action.triggered.connect(lambda _checked=False, env=name: self.start_sync([env]))
        self.sync_menu.addSeparator()
        self.sync_menu.addAction(strings.SYNC_MENU_DRY_RUN).triggered.connect(
            lambda: self.start_sync(dry_run=True))
