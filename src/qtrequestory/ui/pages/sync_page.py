"""The Sincronizzazione page: auto-sync card, env cards, coverage, registro.

The page answers two questions before anything else — *is the automatic sync
on?* and *is any day with calls missing* (still on the server, or already
purged)? — then shows one card per environment and,
collapsed at the bottom, the registro. It keeps almost no state of its own:

* :class:`~.sync_auto_card.AutoSyncCard` owns the scheduled task (read in a
  worker, cached, errors in a banner) and the command buttons;
* :class:`~.sync_presenter.SyncPresenter` owns the per-environment run state,
  reachability and coverage, and computes the one badge that both a card and
  the app-bar chip show;
* :class:`~.env_card.EnvCard` paints one environment, including its own
  progress while the run is on it (the others say "in attesa");
* :mod:`~.sync_format` owns every sentence.

Nothing blocking runs here: the sync, ``schtasks`` and the reachability probe
go through the runner. ``env_status``, ``coverage_days`` and ``lock_holder``
are the documented cheap calls (a state file, a directory listing, a
read-only peek at the lock file) and are called inline; the lock is polled
only while the page is visible. A run started here also writes ``sync.log``
(:mod:`~.sync_job`), exactly like the scheduled ``--sync``.
"""
from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from datetime import datetime

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import (
    Config,
    CoreServices,
    EnvFinished,
    EnvStarted,
    Event,
    FileFailed,
    JobReport,
)
from qtrequestory.ui.pages import progress_model as pm
from qtrequestory.ui.pages import sync_format as fmt
from qtrequestory.ui.pages.coverage_strip import CoverageLegend
from qtrequestory.ui.pages.env_card import CARD_MIN_WIDTH, EnvCard
from qtrequestory.ui.pages.sync_cards import EnvCardsGrid
from qtrequestory.ui.pages.import_banner import ImportBanner
from qtrequestory.ui.pages.mirror_banner import MirrorRootBanner
from qtrequestory.ui.pages.sync_banners import CoverageBanners
from qtrequestory.ui.pages.sync_auto_card import AutoSyncCard
from qtrequestory.ui.pages.sync_job import run_logged
from qtrequestory.ui.pages.sync_log_panel import SyncLogPanel
from qtrequestory.ui.pages.sync_presenter import SyncPresenter
from qtrequestory.ui.pages.sync_probe import REACHABILITY_JOB, ReachabilityProbe
from qtrequestory.ui.workers import Job, JobRunner

__all__ = ["REACHABILITY_JOB", "SyncPage", "SyncPresenter"]

#: Lines of ``sync.log`` the registro opens with.
LOG_TAIL_LINES = 50


class SyncPage(QWidget):
    """App-bar tab ``"sync"``. Built by ``main_window.PAGES``."""

    summary_changed = Signal(str)
    state_changed = Signal(list)

    #: How often the lock file is peeked at while the page is visible.
    LOCK_POLL_MS = 2000
    #: The reachability probe runs on show at most this often.
    REACHABILITY_INTERVAL_S = ReachabilityProbe.INTERVAL_S
    #: Below this width the cards stack in one column.
    TWO_COLUMNS_MIN_WIDTH = 2 * CARD_MIN_WIDTH + 3 * theme.SPACE[3]

    def __init__(self, services: CoreServices, runner: JobRunner,
                 window: object | None = None, parent: QWidget | None = None, *,
                 clock: Callable[[], float] = time.monotonic) -> None:
        super().__init__(parent)
        self._services = services
        self._runner = runner
        self._window = window
        self.presenter = SyncPresenter(services, self)
        self.sync_job: Job | None = None
        self.probe = ReachabilityProbe(services, runner, clock, self)
        self._last_status: str | None = None
        self._outcome: fmt.RunOutcome | None = None
        self._dry_run = False

        self._build()
        self.presenter.summary_changed.connect(self.summary_changed)
        self.presenter.state_changed.connect(self.state_changed)
        self.auto_card.sync_requested.connect(
            lambda envs, dry_run: self.start_sync(envs, dry_run=dry_run))
        self.auto_card.cancel_requested.connect(self.cancel)
        self.probe.answered.connect(self._on_reachability)
        self.rebuild_cards()
        self.mirror_banner.refresh()
        self.auto_card.rebuild_menu(self.presenter.environments())
        self.auto_card.refresh_scheduler()
        tail = services.sync.tail_sync_log(LOG_TAIL_LINES)
        self.log_panel.set_lines(tail)
        self.log_panel.set_header(fmt.last_log_time(tail), None)

        self.lock_timer = QTimer(self)
        self.lock_timer.setInterval(self.LOCK_POLL_MS)
        self.lock_timer.timeout.connect(self.refresh_lock)
        self.refresh_lock()
        # No summary here: nobody is connected yet. The shell calls
        # emit_initial_state() once its hooks are wired.

    def emit_initial_state(self) -> None:
        """The shell's startup call: publish the state computed so far."""
        self.presenter.emit_summary()

    # -- construction ------------------------------------------------------

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)
        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(theme.SPACE[3], theme.SPACE[3], theme.SPACE[3], theme.SPACE[3])
        layout.setSpacing(theme.SPACE[2])

        title = QLabel(strings.SYNC_TITLE)
        theme.set_role(title, "pageTitle")
        self.mirror_banner = MirrorRootBanner(self._services, self._window)
        self.import_banner = ImportBanner(self._services, self._runner, self._window)
        self.auto_card = AutoSyncCard(self._services, self._runner, self._window)
        self.lock_label = QLabel(strings.SYNC_LOCK_HELD)
        theme.set_role(self.lock_label, "muted")
        self.lock_label.hide()

        self.banners = CoverageBanners()
        self.banners.hide()
        self.banners.sync_requested.connect(lambda envs: self.start_sync(envs))

        self.cards_grid = EnvCardsGrid()
        self.legend = CoverageLegend()
        self.run_label = QLabel()
        self.run_label.setWordWrap(True)
        self.run_label.hide()
        self.log_panel = SyncLogPanel()

        for widget in (title, self.mirror_banner, self.import_banner, self.auto_card,
                       self.lock_label, self.banners):
            layout.addWidget(widget)
        layout.addLayout(self.cards_grid)
        layout.addWidget(self.legend)
        layout.addWidget(self.run_label)
        layout.addWidget(self.log_panel)
        layout.addStretch(1)
        # The commands live on the auto card; short names for the page's callers.
        self.sync_button = self.auto_card.sync_button
        self.sync_menu = self.auto_card.sync_menu
        self.cancel_button = self.auto_card.cancel_button

    # -- cards -------------------------------------------------------------

    def rebuild_cards(self) -> None:
        """One card per *enabled* environment."""
        self.cards_grid.rebuild(self._services.config.load().enabled_environments(), self)
        self.refresh_cards()

    def columns(self) -> int:
        return self.cards_grid.columns()

    def refresh_cards(self) -> None:
        """Rows, calendar, badge and the pending/lost banners, from the disk."""
        self.presenter.refresh_coverage()
        for card in self.cards():
            card.set_status(self._services.sync.env_status(card.env_name),
                            self.presenter.coverage.get(card.env_name))
        self._refresh_badges()
        self.legend.set_kinds({kind for card in self.cards() for _day, kind in card.strip.kinds()})
        self.banners.set_days(self.presenter.pending(), self.presenter.lost())

    def _refresh_badges(self) -> None:
        for card in self.cards():
            card.set_badge(self.presenter.badge(card.env_name))

    def cards(self) -> list[EnvCard]:
        return self.cards_grid.cards()

    def card(self, env_name: str) -> EnvCard | None:
        return self.cards_grid.card(env_name)

    def on_config_changed(self, cfg: Config | None = None) -> None:
        """Impostazioni saved: the environments — or the schedule — may have changed."""
        self.rebuild_cards()
        self.mirror_banner.refresh()
        self.auto_card.rebuild_menu(self.presenter.environments())
        self.presenter.emit_summary()
        self.auto_card.refresh_scheduler()  # the line describes the saved schedule
        self.probe.reset()
        if self.isVisible():
            self.probe.check()

    def on_data_changed(self) -> None:
        """A sync or an index finished somewhere: re-read the disk."""
        if not self._runner.is_running("sync"):
            self.refresh_cards()
            self.presenter.emit_summary()

    def refresh_sync_state(self) -> None:
        """The window's slow refresh: a scheduled ``--sync`` may have run.

        Only the cheap reads (state file; the cards' directory listing when
        on screen) — no lock peek, no ``schtasks``. A run of ours keeps its
        own live state.
        """
        if self._runner.is_running("sync"):
            return
        if self.isVisible():
            self.refresh_cards()
        self.presenter.emit_summary()

    # -- running a sync ----------------------------------------------------

    def start_sync(self, envs: Sequence[str] | None = None, *, dry_run: bool = False,
                   force: bool = True) -> None:
        """"Sincronizza ora" — ``force=True``; the startup sync passes False.

        ``envs=None`` means every enabled environment, which is what the core
        does with it too; the list below is only which cards say "in attesa".

        The lock peek does NOT gate this: a stale holder line must never lock
        the user out. The core takes the real lock and, when the scheduled
        task holds it, runs nothing and reports ``sync=None`` (see
        :meth:`_on_result`).

        An invalid log folder (empty or relative ``mirror_root``) DOES gate
        it, like the CLI: the page says why and submits nothing.
        """
        problems = self.mirror_banner.refresh()
        if problems:
            text = strings.SYNC_REFUSED_MIRROR_ROOT.format(problem=problems[0])
            self._set_run_label(text, "warn")
            self._show_status(text)
            return
        job = self._runner.submit("sync", run_logged, self._services.sync.run, envs,
                                  force=force, dry_run=dry_run)
        if job is None:  # the runner refuses a second sync; it says so itself
            return
        self.sync_job = job
        job.signals.progress.connect(self.handle_event)
        job.signals.result.connect(self._on_result)
        job.signals.error.connect(self._on_error)
        job.signals.finished.connect(self._on_finished)
        self._outcome, self._dry_run, self._last_status = None, dry_run, None
        known = self.presenter.environments()
        self.presenter.begin_run([e for e in known if envs is None or e in envs])
        self.log_panel.clear()
        self.log_panel.set_header(None, strings.SYNC_LOG_RUNNING)
        self._set_run_label(strings.SYNC_PROGRESS_STARTING, "neutral")
        self.auto_card.set_running(True)
        self.refresh_lock()
        self._refresh_badges()
        self.presenter.emit_state()

    def cancel(self) -> None:
        """Ask the core to stop; the page says so until ``finished`` arrives."""
        if self.sync_job is None or not self.sync_job.is_running():
            return
        self.sync_job.cancel()
        self.cancel_button.setEnabled(False)
        self.run_label.setText(strings.SYNC_PROGRESS_CANCELLING)
        running = self.card(self.presenter.running or "")
        if running is not None:
            running.set_progress_text(strings.SYNC_PROGRESS_CANCELLING)

    def handle_event(self, ev: Event) -> None:
        """One core event: the cards, the chip, the registro and the status bar."""
        self.presenter.handle(ev)
        if isinstance(ev, (EnvStarted, EnvFinished)):
            card = self.card(ev.env)
            if card is not None and isinstance(ev, EnvFinished):
                card.set_progress(None)
            self._refresh_badges()
            self.presenter.emit_state()
        if isinstance(ev, FileFailed) or (isinstance(ev, EnvFinished) and ev.result.failed):
            self.log_panel.expand()
        line = fmt.log_line(ev)
        if line is not None:
            self.log_panel.append(line)
        if not self._cancelling():
            self._render_progress()
            self._show_progress_status()

    def progress_counts(self) -> tuple[int, int] | None:
        """``(done, total)`` files of the run in flight, for the quit question."""
        snap = self.presenter.progress.snapshot()
        if snap.n_files <= 0:
            return None
        return snap.file_index, snap.n_files

    def _render_progress(self) -> None:
        """The running env's card, or the page line while indexing."""
        snap = self.presenter.progress.snapshot()
        texts = fmt.strip_texts(snap)
        if snap.phase == pm.PHASE_INDEX:
            self.run_label.setText(strings.SYNC_SUMMARY_SEP.join(
                t for t in (texts.label, texts.totals) if t))
            return
        card = self.card(self.presenter.running or "")
        if card is not None:
            card.set_progress(texts)
        line = fmt.status_text(snap)
        if line:
            self.run_label.setText(line)

    def _cancelling(self) -> bool:
        return self.sync_job is not None and self.sync_job.token.is_set()

    # -- job lifecycle -----------------------------------------------------

    def _on_result(self, report: JobReport) -> None:
        self._outcome = fmt.run_outcome(report.exit_code, self.presenter.run_results(),
                                        dry_run=self._dry_run, skipped=report.sync is None)

    def _on_error(self, _kind: str, error: str) -> None:
        self._outcome = fmt.RunOutcome(strings.SYNC_ERROR.format(error=error), "warn",
                                       strings.SYNC_LOG_FAILED)

    def _on_finished(self) -> None:
        self.presenter.end_run()
        for card in self.cards():
            card.set_progress(None)
        self.auto_card.set_running(False)
        self.refresh_lock()
        self.refresh_cards()
        self.presenter.emit_summary()
        outcome = self._outcome
        if outcome is None:
            self.run_label.hide()
            self.log_panel.set_header(fmt.format_when(datetime.now()), None)
            return
        self._set_run_label(outcome.text, outcome.tone)
        self.log_panel.set_header(fmt.format_when(datetime.now()), outcome.log)
        if outcome.expand_log:
            self.log_panel.expand()
        self._show_status(outcome.text)
        toast = getattr(self._window, "show_toast", None)
        if callable(toast):
            toast(outcome.text, outcome.tone)

    def _set_run_label(self, text: str, tone: str) -> None:
        self.run_label.setText(text)
        self.run_label.setProperty("syncTone", tone)
        theme.repolish(self.run_label)
        self.run_label.show()

    # -- reachability: "non raggiungibile" as a resting state ---------------

    @property
    def reach_job(self) -> Job | None:
        return self.probe.job

    def _on_reachability(self, results: dict[str, bool]) -> None:
        self.presenter.set_reachability(results)
        self._refresh_badges()
        self.presenter.emit_summary()

    # -- lock held by the scheduled run ------------------------------------

    def refresh_lock(self) -> None:
        """Polled every :data:`LOCK_POLL_MS` while visible; also around every run.

        The lock is ours while *we* are the ones syncing, so the warning only
        appears when somebody else — the scheduled task — holds it.
        """
        ours = self._runner.is_running("sync")
        held = not ours and self._services.sync.lock_holder() is not None
        self.lock_label.setVisible(held)
        self.auto_card.set_sync_enabled(not held and not ours)
        self.banners.set_sync_enabled(not held and not ours)

    # -- Qt ----------------------------------------------------------------

    def showEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().showEvent(event)
        self.refresh_lock()
        self.lock_timer.start()
        self.probe.check()

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self.lock_timer.stop()  # nothing to watch on a page nobody sees
        super().hideEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self.cards_grid.set_columns(2 if self.width() >= self.TWO_COLUMNS_MIN_WIDTH else 1)

    # -- talking to the window ---------------------------------------------

    # ``state_changed`` is *not* pushed into the window from here: the shell
    # connects that signal to ``set_sync_state`` itself.

    def _show_status(self, text: str) -> None:
        setter = getattr(self._window, "set_status", None)
        if text and callable(setter):
            setter(text)

    def _show_progress_status(self) -> None:
        """"Sincronizzazione coll 3/48…" in the status bar, on every change."""
        text = fmt.status_text(self.presenter.progress.snapshot())
        if text is None or text == self._last_status:
            return
        self._last_status = text
        setter = getattr(self._window, "set_status", None)
        if callable(setter):
            setter(text, 0)
