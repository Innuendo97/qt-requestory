"""Every core call the Ricerca page makes, off the GUI thread, plus the debounce.

A plain object with signals (DESIGN-ui §Testability): it holds the last result
set and knows nothing about widgets, so the page stays a renderer.

The search itself runs on the :class:`~qtrequestory.ui.workers.JobRunner`
under the name ``"search"``, which supersedes: a slow first query is silenced
the moment a second one starts, so the page needs no request ids of its own.
While one runs the presenter says so through :attr:`SearchPresenter.busy` —
the page turns that into "Cerca…" on the button, not into a status-bar line
that would outlive the results.
"""
from __future__ import annotations

import logging
from datetime import date

from PySide6.QtCore import QObject, QTimer, Signal

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import Coverage, CoverageDays, CoreServices, SearchHit, SearchQuery
from qtrequestory.ui.workers import JobRunner

log = logging.getLogger(__name__)

__all__ = ["SELECTION_DEBOUNCE_MS", "SearchPresenter"]

#: A selection settles before the preview is asked for a body (DESIGN-ui).
SELECTION_DEBOUNCE_MS = 150


class SearchPresenter(QObject):
    results_ready = Signal(list)
    selection_changed = Signal(object)  # SearchHit or None
    status = Signal(str)
    busy = Signal(bool)
    template_keys_ready = Signal(list)
    index_pending = Signal(int)

    def __init__(self, services: CoreServices, runner: JobRunner,
                 parent: QObject | None = None,
                 debounce_ms: int = SELECTION_DEBOUNCE_MS) -> None:
        super().__init__(parent)
        self._services = services
        self._runner = runner
        self._hits: list[SearchHit] = []
        self._selected: SearchHit | None = None
        # A restartable single-shot timer, not a chain of QTimer.singleShot:
        # dragging the cursor down the table must produce ONE preview request,
        # not one per row passed over.
        self.selection_timer = QTimer(self)
        self.selection_timer.setSingleShot(True)
        self.selection_timer.setInterval(debounce_ms)
        self.selection_timer.timeout.connect(self._emit_selection)

    # -- synchronous, cheap ------------------------------------------------

    def environments(self) -> list[str]:
        return [env.name for env in self._services.config.load().enabled_environments()]

    def default_window_days(self) -> int:
        return self._services.config.load().default_window_days

    def coverage(self, env: str) -> Coverage | None:
        """One indexed aggregate over ``files``; cheap enough for the GUI thread."""
        try:
            return self._services.index.coverage(env)
        except Exception:  # noqa: BLE001 - a missing index must not break the page
            log.exception("periodo coperto di %s non disponibile", env)
            return None

    def mirror_problem(self) -> str | None:
        """Why the log folder is unusable, or None. With one, the page shows
        the banner (``MirrorRootBanner``) and nothing is asked of the index:
        the facade would only refuse it (``ValueError``) from a worker."""
        problems = self._services.config.mirror_root_errors(self._services.config.load())
        return problems[0] if problems else None

    def coverage_days(self, env: str, today: date | None = None) -> CoverageDays | None:
        """The mirror listing's holes (a directory listing: cheap too)."""
        if self.mirror_problem() is not None:
            return None
        try:
            return self._services.index.coverage_days(env, today=today)
        except Exception:  # noqa: BLE001 - a broken mirror must not break the page
            log.exception("copertura giornaliera di %s non disponibile", env)
            return None

    def hits(self) -> list[SearchHit]:
        return list(self._hits)

    # -- jobs --------------------------------------------------------------

    def search(self, query: SearchQuery) -> None:
        problem = self.mirror_problem()
        if problem is not None:
            self.status.emit(strings.SEARCH_FAILED.format(error=strings.lower_first(problem)))
            return
        job = self._runner.submit("search", self._services.index.search, query)
        if job is None:  # shutting down
            return
        self.busy.emit(True)
        job.signals.result.connect(self._on_hits)
        job.signals.error.connect(self._on_error)

    def reload_template_keys(self, env: str) -> None:
        if self.mirror_problem() is not None:
            self.template_keys_ready.emit([])
            return
        job = self._runner.submit("search_keys", self._services.index.list_template_keys, env)
        if job is not None:
            job.signals.result.connect(lambda keys: self.template_keys_ready.emit(list(keys)))

    def refresh_index_state(self, env: str) -> None:
        """How many local files the index has not scanned yet (stale banner)."""
        if self.mirror_problem() is not None:
            self.index_pending.emit(0)
            return
        job = self._runner.submit("search_plan", self._services.index.plan, [env])
        if job is not None:
            job.signals.result.connect(lambda plan: self.index_pending.emit(len(plan.to_scan)))

    # -- selection ---------------------------------------------------------

    def select(self, hit: SearchHit | None) -> None:
        self._selected = hit
        self.selection_timer.start()

    def flush_selection(self) -> None:
        """Deliver a pending selection now (a row action must not wait 150 ms)."""
        if self.selection_timer.isActive():
            self.selection_timer.stop()
            self._emit_selection()

    def _emit_selection(self) -> None:
        self.selection_changed.emit(self._selected)

    def _on_hits(self, hits: list[SearchHit]) -> None:
        self._hits = list(hits)
        self.busy.emit(False)
        self.results_ready.emit(self._hits)

    def _on_error(self, _kind: str, message: str) -> None:
        self.busy.emit(False)
        self.status.emit(strings.SEARCH_FAILED.format(error=message))
