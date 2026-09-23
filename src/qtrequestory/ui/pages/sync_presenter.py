"""What the Sincronizzazione page knows between two events.

The page itself keeps almost no state: the arithmetic lives in
:class:`~.progress_model.ProgressModel`, the wording in :mod:`~.sync_format`,
the verdict of one environment in :func:`~.sync_badge.badge_for`, and this
presenter holds what is left — which environment the run is on, which ones
wait for their turn, what each one ended up doing, whether it answered the
last reachability probe, and its 30-day coverage.

It is a plain ``QObject`` with two signals so the summary and the chip state
can be asserted without a widget in sight. Both the cards and the app-bar chip
read :meth:`SyncPresenter.badge`, which is why the dot and the badge can no
longer disagree.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping

from PySide6.QtCore import QObject, Signal

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import CoreServices, CoverageDays, EnvFinished, EnvStarted, Event
from qtrequestory.ui.pages import progress_model as pm
from qtrequestory.ui.pages import sync_badge as sb
from qtrequestory.ui.pages import sync_format as fmt

__all__ = ["SyncPresenter"]

log = logging.getLogger(__name__)

#: Days of history in the coverage calendar.
COVERAGE_DAYS = 30


class SyncPresenter(QObject):
    """Per-environment run state, reachability and coverage; see the module doc."""

    summary_changed = Signal(str)
    #: ``[(env, tone, text), ...]`` for the app-bar chip; see :meth:`state`.
    state_changed = Signal(list)

    def __init__(self, services: CoreServices, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._services = services
        self.progress = pm.ProgressModel()
        #: env -> ``EnvResult.status`` of the last finished run.
        self.outcomes: dict[str, str] = {}
        #: env -> how many files failed in that run.
        self.failures: dict[str, int] = {}
        #: The environment the run in flight is working on right now.
        self.running: str | None = None
        #: Environments of the run in flight still waiting for their turn.
        self.queued: set[str] = set()
        #: Environments of the last run, in order, for the final message.
        self.targets: list[str] = []
        #: env -> did it answer the last probe or run? Absent = nobody asked.
        self.reachable: dict[str, bool] = {}
        #: env -> the local archive's last 30 days.
        self.coverage: dict[str, CoverageDays | None] = {}

    # -- the run -----------------------------------------------------------

    def begin_run(self, targets: Iterable[str]) -> None:
        """Every target is "in attesa" until its ``EnvStarted``; old verdicts go."""
        self.targets = list(targets)
        self.queued = set(self.targets)
        self.running = None
        for env in self.targets:
            self.outcomes.pop(env, None)
            self.failures.pop(env, None)
        self.progress.reset()

    def handle(self, ev: Event) -> None:
        self.progress.handle(ev)
        if isinstance(ev, EnvStarted):
            self.running = ev.env
            self.queued.discard(ev.env)
        elif isinstance(ev, EnvFinished):
            status = ev.result.status
            self.outcomes[ev.env] = status
            self.failures[ev.env] = ev.result.failed
            if status != "cancelled":
                self.reachable[ev.env] = status != "unreachable"
            if self.running == ev.env:
                self.running = None
            self.queued.discard(ev.env)

    def end_run(self) -> None:
        self.running = None
        self.queued.clear()

    def is_busy(self, env: str) -> bool:
        return env == self.running or env in self.queued

    def run_results(self) -> dict[str, tuple[str, int]]:
        """``{env: (status, failed)}`` of the last run's targets that finished."""
        return {env: (self.outcomes[env], self.failures.get(env, 0))
                for env in self.targets if env in self.outcomes}

    # -- what is known without a run ---------------------------------------

    def set_reachability(self, results: Mapping[str, bool]) -> None:
        """A probe answered; an environment a run is working on is left alone."""
        for env, ok in results.items():
            if not self.is_busy(env):
                self.reachable[env] = ok

    def refresh_coverage(self) -> None:
        """Re-read every enabled environment's 30 days (a directory listing)."""
        self.coverage = {}
        for env in self.environments():
            try:
                self.coverage[env] = self._services.index.coverage_days(env, days=COVERAGE_DAYS)
            except (OSError, ValueError) as exc:  # an unusable mirror: no calendar
                log.debug("coverage_days(%s) non disponibile: %s", env, exc)
                self.coverage[env] = None

    def missing(self) -> dict[str, tuple]:
        return {env: (cov.missing if cov is not None else ())
                for env, cov in self.coverage.items()}

    # -- verdicts ----------------------------------------------------------

    def environments(self) -> list[str]:
        return [e.name for e in self._services.config.load().enabled_environments()]

    def badge(self, env: str) -> sb.Badge:
        cov = self.coverage.get(env)
        failed = self.failures.get(env, 0) if self.outcomes.get(env) == "errors" else 0
        return sb.badge_for(
            self._services.sync.env_status(env),
            running=env == self.running,
            queued=env in self.queued,
            reachable=self.reachable.get(env),
            failed=failed,
            missing=len(cov.missing) if cov is not None else 0,
        )

    def summary(self) -> str:
        """"svil: oggi 11:23 · coll: non raggiungibile" for the status bar."""
        parts = []
        for name in self.environments():
            if self.reachable.get(name) is False:
                when = strings.SYNC_WHEN_UNREACHABLE
            else:
                when = fmt.format_when(self._services.sync.env_status(name).last_success)
            parts.append(strings.SYNC_SUMMARY_ENTRY.format(env=name, when=when))
        return strings.SYNC_SUMMARY_SEP.join(parts)

    def state(self) -> list[tuple[str, str, str]]:
        """``(env, tone, text)`` per enabled environment, for the status chip.

        The tone is the badge's tone — the same function decides both — and
        the text is what fits in a chip: "in corso", "in attesa",
        "non raggiungibile", or when the mirror was last filled.
        """
        items = []
        for name in self.environments():
            badge = self.badge(name)
            if badge.kind == sb.RUNNING:
                text = strings.SYNC_CHIP_RUNNING
            elif badge.kind == sb.QUEUED:
                text = strings.SYNC_CHIP_QUEUED
            elif badge.kind == sb.UNREACHABLE:
                text = strings.SYNC_WHEN_UNREACHABLE
            else:
                text = fmt.format_when(self._services.sync.env_status(name).last_success)
            items.append((name, badge.tone, text))
        return items

    def emit_state(self) -> None:
        self.state_changed.emit(self.state())

    def emit_summary(self) -> str:
        """Emit both the plain summary and the per-environment state."""
        text = self.summary()
        self.summary_changed.emit(text)
        self.emit_state()
        return text
