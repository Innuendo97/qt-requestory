"""The Officina's background work: the generation queue and the worker calls.

**Generation.** Every AS-IS or TO-BE goes through one :class:`GenerationQueue`
owned by the page, whether it is a single F5 in the workbench or "Rigenera
TO-BE selezionati" on the board. Each case is one ``JobRunner`` job on one of
the three lanes of :data:`~qtrequestory.ui.workers.OFFICINA_GENERATE_JOBS`, so
at most three cases are on the wire at once (spec §5 "Batch"). The queue — not
``JobRunner.is_running`` — decides when a lane is free again: a lane is busy
until its ``finished`` has been *delivered*, because submitting on a lane whose
result is still queued would supersede that job and silence its result.

A failed case never stops the others: ``OfficinaApi.generate`` returns a failed
``SendResult`` instead of raising (Review Focus 5), and the queue simply moves
on. "Annulla" drops the cases still waiting and sets the cancel token of the
running ones; ``generate`` checks it right before sending, so a call already
on the wire runs to its end (its document is still saved).

**Documents and comparisons.** :func:`load_case_docs` is a plain function
for ``JobRunner.submit``: the PDF the viewer shows (an
HTML is printed by Edge first — slow, hence the worker), its page sizes, and
the text comparison with the TARGET and, for a TO-BE, the three-way
comparison of phase 2 (``compare_case``; ``None`` when the core cannot judge
yet). ``CompareError`` becomes a readable message, never a traceback. The
board runs no comparison: its pill is read from ``case.review.summary``
(``riepilogo``, saved by ``compare_case``; ``officina_board_pill``). PDFium
is only reached from here, inside the worker, through
``qtrequestory.officina.pdf`` — importing this module loads nothing heavy.
The workers that write a case's ``caso.json`` take the case's lock
(``officina_judge``).
"""
from __future__ import annotations

from collections import deque
from collections.abc import Sequence
import dataclasses
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any, Literal

from PySide6.QtCore import QObject, Signal

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import (
    Case,
    CaseComparison,
    CompareError,
    Comparison,
    CoreServices,
    Initiative,
    SendResult,
    Version,
    mask_text,
)
from qtrequestory.ui.pages.officina_judge import generate_locked, judge
from qtrequestory.ui.workers import (
    OFFICINA_COMPARE_JOB,
    OFFICINA_GENERATE_JOBS,
    Job,
    JobRunner,
)

__all__ = [
    "COMPARE_JOB", "GENERATE_JOBS", "CaseDocs", "GenerationQueue", "SideDoc", "load_case_docs",
]

GENERATE_JOBS = OFFICINA_GENERATE_JOBS
COMPARE_JOB = OFFICINA_COMPARE_JOB

Kind = Literal["asis", "tobe"]


@dataclass
class _Request:
    ini: Initiative
    case: Case
    kind: Kind
    note: str | None

    def matches(self, initiative: str, case_id: str) -> bool:
        return self.ini.id == initiative and self.case.id == case_id


class GenerationQueue(QObject):
    """At most ``len(lanes)`` generations at once; the rest wait their turn."""

    #: ``initiative id, case_id`` — the case is waiting, has started or is over
    #: (an initiative is known by its folder, ``Initiative.id``, never its name).
    state_changed = Signal(str, str)
    #: ``initiative id, case_id, kind, Version | None, SendResult, cancelled`` — one
    #: case is over; ``cancelled`` when "Annulla" stopped it before it was sent.
    case_finished = Signal(str, str, str, object, object, bool)
    #: ``done, total`` of the current batch (a batch ends when the queue empties).
    progress = Signal(int, int)
    #: ``ok, failed`` — the queue is empty again (cases cancelled before
    #: sending count as neither).
    batch_finished = Signal(int, int)

    def __init__(self, services: CoreServices, runner: JobRunner,
                 lanes: Sequence[str] = GENERATE_JOBS, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._services = services
        self._runner = runner
        self._lanes = tuple(lanes)
        self._pending: deque[_Request] = deque()
        self._running: dict[str, tuple[_Request, Job]] = {}  # lane -> what runs there
        self._cancelled: set[int] = set()  # ids of the running jobs "Annulla" stopped
        self._done = self._ok = self._total = self._stopped = 0

    # -- public API --------------------------------------------------------

    def enqueue(self, ini: Initiative, cases: Sequence[Case], kind: Kind,
                note: str | None = None) -> list[Case]:
        """Queue ``cases``; returns the ones SKIPPED because they are already
        waiting or running (a case is never queued twice)."""
        skipped: list[Case] = []
        accepted = 0
        for case in cases:
            if self.state(ini.id, case.id) is not None:
                skipped.append(case)
                continue
            self._pending.append(_Request(ini, case, kind, note))
            self._total += 1
            accepted += 1
            self.state_changed.emit(ini.id, case.id)
        if accepted:
            self.progress.emit(self._done, self._total)
            self._pump()
        return skipped

    def cancel(self) -> None:
        """Drop the waiting cases, and stop the running ones before they send."""
        dropped = list(self._pending)
        self._pending.clear()
        self._total -= len(dropped)
        for request in dropped:
            self.state_changed.emit(request.ini.id, request.case.id)
        for _request, job in self._running.values():
            job.cancel()
            self._cancelled.add(job.id)
        if not self._running:
            self._finish_batch()
        else:
            self.progress.emit(self._done, self._total)

    def state(self, initiative: str, case_id: str) -> Literal["queued", "running"] | None:
        """Where case ``case_id`` of initiative ``initiative`` (its id) is in
        the queue, if anywhere (a case id is unique only inside its initiative)."""
        if any(r.matches(initiative, case_id) for r, _job in self._running.values()):
            return "running"
        if any(r.matches(initiative, case_id) for r in self._pending):
            return "queued"
        return None

    def is_busy(self) -> bool:
        return bool(self._pending or self._running)

    def initiatives(self) -> set[str]:
        """The ids of the initiatives with a case waiting or running (whose batch this is)."""
        return ({r.ini.id for r in self._pending}
                | {r.ini.id for r, _job in self._running.values()})

    def counts(self) -> tuple[int, int]:
        """``(done, total)`` of the batch under way."""
        return self._done, self._total

    # -- internals ---------------------------------------------------------

    def _pump(self) -> None:
        for lane in self._lanes:
            if not self._pending:
                return
            if lane in self._running or self._runner.is_running(lane):
                continue  # ours until its `finished` is delivered; or not ours at all
            request = self._pending.popleft()
            job = self._runner.submit(lane, generate_locked, self._services, request.ini,
                                      request.case, request.kind,
                                      replace_asis_note=request.note)
            if job is None:  # the application is closing: nothing more will run
                self._pending.clear()
                self._total = self._done
                return
            self._running[lane] = (request, job)
            outcome: dict[str, Any] = {}
            job.signals.result.connect(partial(_store, outcome, "value"))
            job.signals.error.connect(partial(_store_error, outcome))
            job.signals.finished.connect(partial(self._on_finished, lane, job, outcome))
            self.state_changed.emit(request.ini.id, request.case.id)

    def _on_finished(self, lane: str, job: Job, outcome: dict[str, Any]) -> None:
        entry = self._running.get(lane)
        if entry is None or entry[1] is not job:
            return
        request, _job = self._running.pop(lane)
        version, result = outcome.get("value") or (None, _failed(outcome.get("error", "")))
        cancelled = (job.id in self._cancelled and version is None and result.status is None
                     and not result.duration_ms)  # refused before sending, not failed on the wire
        self._cancelled.discard(job.id)
        self._done += 1
        if version is not None:
            self._ok += 1
        if cancelled:
            self._stopped += 1
        self.case_finished.emit(request.ini.id, request.case.id, request.kind, version,
                                result, cancelled)
        self.state_changed.emit(request.ini.id, request.case.id)
        self.progress.emit(self._done, self._total)
        self._pump()
        if not self._running and not self._pending:
            self._finish_batch()

    def _finish_batch(self) -> None:
        ok, failed = self._ok, self._done - self._ok - self._stopped
        self._done = self._ok = self._total = self._stopped = 0
        self.batch_finished.emit(ok, failed)


def _store(outcome: dict[str, Any], key: str, value: object) -> None:
    outcome[key] = value


def _store_error(outcome: dict[str, Any], _kind: str, message: str) -> None:
    outcome["error"] = message


def _failed(detail: str) -> SendResult:
    """What an unexpected exception in ``generate`` looks like to the page:
    an Italian sentence, with the exception's own text (maybe English, maybe
    holding a link) masked after it."""
    reason = strings.OFFICINA_GENERATION_INTERRUPTED
    if detail.strip():
        reason = f"{reason}: {mask_text(detail.strip())}"
    return SendResult(ok=False, status=None, doc_type=None, content=b"", duration_ms=0,
                      reason=reason, headers_sent={})


# ------------------------------------------------------------ worker calls ---

@dataclass(frozen=True)
class SideDoc:
    """One side of the workbench: the PDF to render and its page sizes, or why not."""

    version: Version | None
    path: Path | None = None
    sizes: list[tuple[float, float]] = field(default_factory=list)
    error: str = ""
    #: An HTML whose Edge print is not available, judged through its DOM anyway (R45).
    no_print: bool = False


@dataclass(frozen=True)
class CaseDocs:
    """What the workbench shows for one (case, version) pair."""

    case_id: str
    left: SideDoc
    right: SideDoc
    comparison: Comparison | None
    compare_error: str = ""
    #: Phase 2: the judged comparison of a TO-BE (None: the AS-IS, or no verdict available).
    judged: CaseComparison | None = None
    #: The case's effective profile (case → initiative → Tollerante): what the
    #: comparison without verdicts shows (``Comparison.counting``).
    profile: str = "tollerante"


def _side(services: CoreServices, case: Case, version: Version | None) -> SideDoc:
    if version is None:
        return SideDoc(None)
    try:
        path = services.officina.render_path(case, version)
        from qtrequestory.officina import pdf  # PDFium: in the worker only

        return SideDoc(version, path, pdf.page_sizes(path))
    except (CompareError, OSError, ValueError) as exc:  # PdfReadError is a ValueError
        return SideDoc(version, error=str(exc))


def load_case_docs(services: CoreServices, case: Case, version: Version | None,
                   ini: Initiative | None = None) -> CaseDocs:
    """The TARGET, ``version`` (AS-IS or a TO-BE) and, with ``ini`` and a
    TO-BE, its judged comparison (``compare_case``); the comparison without
    verdicts (``compare``) only when there is no judged one (the AS-IS, a
    case being generated, a failed judge): the same engine, run once."""
    left = _side(services, case, case.target())
    right = _side(services, case, version)
    comparison, error, judged = None, "", None
    both = left.version is not None and right.version is not None
    # R45: an HTML side without its Edge print is still judged through the DOM
    printless = [s for s in (left, right) if s.error and s.version is not None and s.version.doc_type == "html"]
    if both and not [s for s in (left, right) if s.error and s not in printless]:
        if ini is not None and version is not None and version.kind == "tobe":
            judged = judge(services, ini, case, version)
        if judged is not None and printless:
            left, right = (dataclasses.replace(s, no_print=True, error=strings.OFFICINA_PRINT_MISSING.format(
                reason=s.error)) if s in printless else s for s in (left, right))
        elif printless:
            error = printless[0].error
        elif judged is None:
            try:
                comparison = services.officina.compare(left.version, right.version)
            except (CompareError, OSError, ValueError) as exc:
                error = str(exc)
    elif left.error or right.error:
        error = left.error or right.error
    profile = case.review.profile or (ini.profile if ini is not None else None) or "tollerante"
    return CaseDocs(case.id, left, right, comparison, error, judged, profile)
