"""What the application does on its own once the window is on screen.

DESIGN-ui "Startup order": after ``MainWindow.show()``, bring the index up to
date with the mirror, then run an opportunistic sync. Both in workers, never
before the window is visible (``run_gui`` schedules this with a zero-delay
timer), and one after the other: the sync job indexes what it downloads, and
two jobs writing the same index at once would only fight over it.

* **Index first.** ``index.plan`` decides whether there is anything to do; an
  empty plan costs one query and no ``update``. The job runs under the same
  name as Impostazioni' [Ricostruisci indice], so the two exclude each other.
* **Then a NON-forced sync.** The core skips every environment already synced
  after the last compaction, so on a normal morning this downloads nothing.
  It is started through the Sincronizzazione page (progress, registro,
  ``sync.log``), without switching to it.
* **Never over the scheduled task.** When another process holds the sync lock
  the sync is skipped silently; the page already says who holds it.
* **Never into the CWD.** An empty or relative ``mirror_root`` (the CLI's
  exit 2) starts nothing at all; Ricerca and Sincronizzazione show a banner
  that leads to Impostazioni › Archivio.

``run_gui`` skips all of this when the first-run wizard asked for a sync: that
run indexes too, and a second one would only be refused.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Sequence

from PySide6.QtCore import QObject

from qtrequestory.ui.contracts import CancelToken, CoreServices, EventSink, IndexApi, JobReport
from qtrequestory.ui.workers import JobRunner

__all__ = ["INDEX_JOB", "StartupTasks"]

log = logging.getLogger(__name__)

#: Same name as ``settings_page.INDEX_JOB``: one index job at a time.
INDEX_JOB = "index"


class StartupTasks(QObject):
    """Index-if-needed, then a non-forced sync. Built and run once by the window."""

    def __init__(self, services: CoreServices, runner: JobRunner,
                 start_sync: Callable[[], None], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._services = services
        self._runner = runner
        self._start_sync = start_sync

    def run(self) -> None:
        cfg = self._services.config.load()
        problems = self._services.config.mirror_root_errors(cfg)
        if problems:
            log.warning("avvio: niente indice né sincronizzazione (%s)", "; ".join(problems))
            return
        envs = [env.name for env in cfg.enabled_environments()]
        if not envs:
            log.info("avvio: nessun ambiente abilitato, niente da indicizzare o sincronizzare")
            return
        job = self._runner.submit(INDEX_JOB, _index_if_pending, self._services.index, envs)
        if job is None:  # an index job is already running, or the app is closing
            return
        job.signals.finished.connect(self._sync)

    def _sync(self) -> None:
        holder = self._services.sync.lock_holder()
        if holder is not None:
            log.info("avvio: sincronizzazione saltata, il lock è di %s", holder)
            return
        self._start_sync()


def _index_if_pending(index: IndexApi, envs: Sequence[str], *, sink: EventSink,
                      cancel: CancelToken) -> JobReport | None:
    """Worker thread: ``update`` only when ``plan`` found something to do."""
    plan = index.plan(envs)
    if not plan.to_scan and not plan.to_remove:
        return None
    return index.update(envs, sink=sink, cancel=cancel)
