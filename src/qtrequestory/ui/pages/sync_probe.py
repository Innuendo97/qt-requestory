"""The reachability probe of the Sincronizzazione page.

"Non raggiungibile" used to appear only after a run had failed to reach an
environment, and vanished at the next restart — so it was never a state the
page could simply *be* in, off the VPN. The page now asks when it is shown:
one short GET per enabled environment (``SyncApi.check_reachable``) in a
worker, at most once every :attr:`ReachabilityProbe.INTERVAL_S` seconds, so
flipping between tabs does not hammer the servers.
"""
from __future__ import annotations

import time
from collections.abc import Callable, Sequence

from PySide6.QtCore import QObject, Signal

from qtrequestory.ui.contracts import CancelToken, CoreServices, Environment
from qtrequestory.ui.workers import Job, JobRunner

__all__ = ["REACHABILITY_JOB", "ReachabilityProbe", "probe_reachability"]

#: The runner name of the probe (not exclusive: a newer probe supersedes).
REACHABILITY_JOB = "sync-reachability"


def probe_reachability(check: Callable[[Environment], bool], envs: Sequence[Environment],
                       cancel: CancelToken) -> dict[str, bool]:
    """``{env: reachable}``, one short GET each; runs on a worker thread."""
    results: dict[str, bool] = {}
    for env in envs:
        if cancel.is_set():
            break
        results[env.name] = check(env)
    return results


class ReachabilityProbe(QObject):
    """Throttled ``check_reachable`` of every enabled environment."""

    #: ``{env: reachable}`` once a probe answers.
    answered = Signal(object)

    #: A probe runs at most this often (seconds).
    INTERVAL_S = 300.0

    def __init__(self, services: CoreServices, runner: JobRunner,
                 clock: Callable[[], float] = time.monotonic,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._services = services
        self._runner = runner
        self._clock = clock
        self._last: float | None = None
        self.job: Job | None = None

    def reset(self) -> None:
        """Forget the throttle (the environments changed)."""
        self._last = None

    def check(self) -> None:
        """Probe now, unless one ran recently or a sync is running (it will know)."""
        now = self._clock()
        if self._last is not None and now - self._last < self.INTERVAL_S:
            return
        if self._runner.is_running("sync"):
            return
        envs = self._services.config.load().enabled_environments()
        if not envs:
            return
        job = self._runner.submit(REACHABILITY_JOB, probe_reachability,
                                  self._services.sync.check_reachable, list(envs))
        if job is None:  # the application is closing
            return
        self._last = now
        self.job = job
        job.signals.result.connect(self.answered.emit)
