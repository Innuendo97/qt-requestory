"""Running a Genera batch (spec "Esecuzione", "Esiti").

:func:`run_batch`, in order:

1. Refuse up front — ``ValueError`` with an Italian reason, before any folder
   is created or any call sent — a generator that is not enabled or not
   usable (``service._enabled_generator``: never PROD), a destination that
   is not an absolute path, a header table that cannot be built.
2. Resolve the targets into calls (``resolve``). An index that cannot be
   searched is refused like step 1 (``ValueError``, nothing created).
   Cancelled while resolving: nothing is created (no folder, no
   ``esito.csv``: nothing was sent), every target is reported ``cancelled``
   and the report carries the folder the run WOULD have had.
3. Create ``<destination>/<generator>_<AAAAMMGG-HHMMSS>`` (``_2``… when a run
   of the same second exists: a run never writes into another run's folder).
   A folder that cannot be created (a drive gone, a file in the way, a path
   too long) is refused like step 1: ``ValueError``, nothing sent. Then the
   file names are reserved in call order (``Writer.reserve``: the same
   request always gives the same names) and ``BatchStarted``.
4. Run the calls on :data:`WORKERS` threads. Each row ends as exactly one
   :class:`~qtrequestory.officina.batch.model.Outcome`; nothing a row does
   (an HTTP error, an unreadable payload, a full disk, a bug) escapes it or
   stops the others. Just before sending, each row checks the generator in
   the CURRENT settings (``settings`` is a source, read again): disabled or
   removed in Impostazioni meanwhile → ``failed`` with that reason, nothing
   sent. A cancelled run lets the calls already on the wire finish and be
   saved; the rows not yet sent become ``cancelled``.
5. ``esito.csv`` always, then the zips when asked and not cancelled. A
   failure there is logged and never loses the report.

:func:`count_calls` is steps 1-2 alone: how many calls a request would send.

Events are emitted from the calling thread only, as rows complete
(``BatchItemDone.done`` counts in completion order); ``BatchReport.outcomes``
keeps the order of the calls.

**Privacy.** Payloads, headers and answers never reach a log, an event, a
reason or ``esito.csv``: reasons are Italian, written here or taken from
``SendResult.reason`` (already masked), and pass through ``mask_text``;
an unexpected exception is reported by its type only.

Stdlib + core only, Qt-free.
"""
from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

from qtrequestory.core.config import OfficinaSettings
from qtrequestory.core.events import Cancelled, CancelToken
from qtrequestory.officina.batch.elenco import NO_PACKAGE
from qtrequestory.officina.batch.headers import build_headers
from qtrequestory.officina.batch.memory import HtmlMemory
from qtrequestory.officina.batch.model import (
    BatchItemDone,
    BatchReport,
    BatchRequest,
    BatchStarted,
    Call,
    Outcome,
    Status,
    Target,
)
from qtrequestory.officina.batch.output import (
    Slot,
    Writer,
    make_run_dir,
    run_dir_name,
    write_esito,
    zip_folders,
)
from qtrequestory.officina.batch.resolve import resolve
from qtrequestory.officina.generator import HeaderError, send
from qtrequestory.officina.links import mask_text, mask_text_for_log

log = logging.getLogger(__name__)

WORKERS = 3

REASON_CANCELLED = "annullato prima dell'invio"
REASON_HTML_KNOWN = "HTML già noto: non richiesto"
REASON_HTML_NOT_WANTED = "HTML non richiesto"
REASON_BAD_PAYLOAD = "payload non leggibile"
_TRIAL_UUID = "00000000-0000-4000-8000-000000000000"


def reason_no_call(source_env: str) -> str:
    return f"nessuna chiamata nei log di {source_env}"


def reason_generator_gone(generator: str) -> str:
    """A row whose generator was disabled, removed or broken in Impostazioni mid-run."""
    return (f"il generatore '{generator}' è stato disattivato o modificato in Impostazioni "
            "durante la generazione: chiamata non inviata")


def run_batch(
    request: BatchRequest,
    *,
    index: Any,
    settings: Callable[[], OfficinaSettings],
    memory: HtmlMemory,
    clock: Callable[[], datetime],
    new_uuid: Callable[[], str],
    opener: Callable[..., Any] | None = None,
    sink: Callable[[Any], None] | None = None,
    cancel: CancelToken | None = None,
) -> BatchReport:
    """Run ``request`` (see the module docstring). ``settings`` gives the
    CURRENT Officina settings (read up front and again before each send);
    ``index`` has ``search(SearchQuery)`` and ``read_body(hit)``; ``opener``
    is passed to ``generator.send``. Raises ``ValueError`` only for the
    up-front problems of steps 1-3, before any call is sent; never
    ``Cancelled``."""
    endpoint = _check(request, settings())
    emit = _guarded(sink)

    calls, unresolved = _resolve(request, index, cancel)
    name = run_dir_name(endpoint.name, _local(clock()))
    if unresolved is not None:  # cancelled while looking the calls up: nothing to create
        never_run = [_outcome(c, "cancelled", REASON_CANCELLED) for c in calls]
        never_run += [o for t in unresolved for o in _target_cancelled(t)]
        return _finish(request, Path(request.destination) / name, never_run,
                       cancelled=True, written=False)
    run_dir = make_run_dir(Path(request.destination), name)  # ValueError: nothing sent

    writer = Writer(run_dir)
    # in call order, before anything is sent: the names never depend on who answers first
    slots = [writer.reserve(c.folders, c.key) if c.hit is not None else () for c in calls]
    total = len(calls)
    emit(BatchStarted(total))
    lane = _Lane(request, settings, memory, writer, index,
                 clock=_serialised(clock), new_uuid=_serialised(new_uuid),
                 opener=opener, cancel=cancel)
    outcomes: list[Outcome | None] = [None] * total
    with ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="genera") as pool:
        futures = {pool.submit(lane.run, call, slot): i
                   for i, (call, slot) in enumerate(zip(calls, slots))}
        done = 0  # touched by this thread only
        for future in as_completed(futures):
            i = futures[future]
            try:
                outcome = future.result()
            except Exception as exc:  # noqa: BLE001 - lane.run already catches; belt and braces
                outcome = _outcome(calls[i], "failed", _unexpected(exc))
            outcomes[i] = outcome
            done += 1
            emit(BatchItemDone(outcome, done, total))
    cancelled = cancel is not None and cancel.is_set()
    return _finish(request, run_dir, [o for o in outcomes if o is not None], cancelled=cancelled)


def count_calls(
    request: BatchRequest,
    *,
    index: Any,
    settings: OfficinaSettings,
    memory: HtmlMemory,
    cancel: CancelToken | None = None,
) -> int:
    """How many calls ``run_batch(request)`` would send now: the targets
    looked up, minus the calls not found and the keys known to answer HTML
    (when HTML is not wanted). Reads only: no folder, nothing sent. The
    refusals of steps 1-2 (``ValueError``); ``Cancelled`` between two lookups."""
    _check(request, settings)
    calls, unresolved = _resolve(request, index, cancel)
    if unresolved is not None:
        raise Cancelled()
    return sum(1 for c in calls if _may_write(c, request, memory))


# ----------------------------------------------------------------- one row ---

class _Lane:
    """The work of one row; shared by the worker threads (read-only state,
    plus the thread-safe ``memory`` and ``writer``)."""

    def __init__(self, request: BatchRequest, settings: Callable[[], OfficinaSettings],
                 memory: HtmlMemory, writer: Writer, index: Any, *,
                 clock: Callable[[], datetime], new_uuid: Callable[[], str],
                 opener: Callable[..., Any] | None, cancel: CancelToken | None) -> None:
        self._request, self._settings = request, settings
        self._memory, self._writer, self._index = memory, writer, index
        self._clock, self._new_uuid = clock, new_uuid
        self._opener, self._cancel = opener, cancel
        self._index_lock = threading.Lock()  # IndexService may rescan a stale day: one at a time

    def run(self, call: Call, slot: Slot = ()) -> Outcome:
        try:
            outcome = self._run(call, slot)
        except Exception as exc:  # noqa: BLE001 - a row never escapes its thread
            outcome = _outcome(call, "failed", _unexpected(exc))
        if outcome.status == "failed":
            log.warning("Genera: %s non riuscito (HTTP %s, %d ms): %s", call.key or call.fdi,
                        outcome.http_status, outcome.duration_ms, mask_text_for_log(outcome.reason))
        else:
            log.info("Genera: %s %s (%s, %d ms)", call.key or call.fdi, outcome.status,
                     outcome.doc_type, outcome.duration_ms)
        return outcome

    def _cancelled(self) -> bool:
        return self._cancel is not None and self._cancel.is_set()

    def _run(self, call: Call, slot: Slot) -> Outcome:
        request = self._request
        if self._cancelled():
            return _outcome(call, "cancelled", REASON_CANCELLED)
        if call.hit is None:
            return _outcome(call, "no_call", reason_no_call(request.source_env))
        if not request.save_html and self._memory.is_html(call.key):
            return _outcome(call, "html_skipped", REASON_HTML_KNOWN, doc_type="html")
        payload = self._payload(call)
        if payload is None:
            return _outcome(call, "failed", REASON_BAD_PAYLOAD)
        # the settings of NOW: a generator disabled in Impostazioni during the run gets nothing more
        settings = self._settings()
        endpoint, problem = _endpoint(settings, request.generator)
        if problem:
            return _outcome(call, "failed", reason_generator_gone(request.generator))
        now = _local(self._clock())
        try:
            headers = build_headers(request.header_rows, key=call.key,
                                    now_ms=int(now.timestamp() * 1000), new_uuid=self._new_uuid,
                                    postman_token=settings.postman_token)
        except HeaderError as exc:
            return _outcome(call, "failed", str(exc))
        if self._cancelled():
            return _outcome(call, "cancelled", REASON_CANCELLED)

        result = send(endpoint.url, payload, headers, timeout_s=settings.timeout_s,
                      opener=self._opener)
        del payload, headers
        sent = dict(doc_type=result.doc_type, duration_ms=result.duration_ms,
                    http_status=result.status)
        if not result.ok or result.doc_type is None:
            return _outcome(call, "failed", result.reason, **sent)  # never result.content
        self._memory.record(call.key, result.doc_type)
        if result.doc_type == "html" and not request.save_html:
            return _outcome(call, "html_skipped", REASON_HTML_NOT_WANTED, **sent)
        try:
            files = self._writer.write_reserved(slot, result.doc_type, result.content)
        except OSError as exc:
            return _outcome(call, "failed", f"scrittura non riuscita: {exc}", **sent)
        return _outcome(call, "ok", "", files=files, **sent)

    def _payload(self, call: Call) -> dict | None:
        """The body of the call as a JSON object, or None (never raises)."""
        try:
            with self._index_lock:
                raw = self._index.read_body(call.hit)
            data = json.loads(bytes(raw).decode("utf-8-sig"))
        except Exception:  # noqa: BLE001 - stale index, file gone, not UTF-8, not JSON...
            return None
        return data if isinstance(data, dict) else None


# ----------------------------------------------------------------- helpers ---

def _endpoint(settings: OfficinaSettings, name: str) -> tuple[Any, str]:
    """``(endpoint, "")`` or ``(None, Italian reason)`` (``service._enabled_generator``)."""
    # Imported here: the service module imports this one (through its batch mixin).
    from qtrequestory.officina.service import _enabled_generator

    return _enabled_generator(settings, name)


def _may_write(call: Call, request: BatchRequest, memory: HtmlMemory) -> bool:
    """True for a call that will be sent (found, and not a key known to answer HTML)."""
    return call.hit is not None and (request.save_html or not memory.is_html(call.key))


def _check(request: BatchRequest, settings: OfficinaSettings) -> Any:
    """The endpoint of ``request.generator``, or ``ValueError`` (step 1)."""
    endpoint, problem = _endpoint(settings, request.generator)
    if problem:
        raise ValueError(problem)
    if not Path(request.destination).is_absolute():
        raise ValueError("la cartella di destinazione deve essere un percorso assoluto")
    # The real headers are built per call (key, time, uuid); a trial build
    # catches a malformed table before anything is sent. HeaderError is a ValueError.
    build_headers(request.header_rows, key="MOD_PROVA", now_ms=0,
                  new_uuid=lambda: _TRIAL_UUID, postman_token=settings.postman_token)
    return endpoint


def _resolve(request: BatchRequest, index: Any,
             cancel: CancelToken | None) -> tuple[list[Call], list[Target] | None]:
    """The calls, and ``None`` — or, when cancelled midway, the calls found
    so far and the targets not looked up. An index that cannot be searched
    is an up-front problem like those of step 1: ``ValueError``, nothing
    created, nothing sent."""
    calls: list[Call] = []
    targets = list(request.targets)
    for i, target in enumerate(targets):
        try:
            calls.extend(resolve([target], index=index, source_env=request.source_env,
                                 cancel=cancel))
        except Cancelled:
            return calls, targets[i:]
        except ValueError:
            raise  # e.g. the mirror folder is not usable: its reason is already Italian
        except Exception as exc:  # noqa: BLE001 - sqlite, a file gone...
            raise ValueError(f"ricerca delle chiamate non riuscita: {type(exc).__name__}") from None
    return calls, None


def _finish(request: BatchRequest, run_dir: Path, outcomes: list[Outcome], *,
            cancelled: bool, written: bool = True) -> BatchReport:
    """The report; ``esito.csv`` and the zips only when the run folder was
    made (``written``): a run stopped before any call writes nothing."""
    if written:
        try:
            write_esito(run_dir, outcomes)
        except Exception as exc:  # noqa: BLE001 - the report is what matters
            log.warning("Genera: esito.csv non scritto: %s", mask_text_for_log(_describe(exc)))
    zips: tuple[Path, ...] = ()
    if written and request.make_zip and not cancelled:
        try:
            zips = zip_folders(run_dir)
        except Exception as exc:  # noqa: BLE001
            log.warning("Genera: zip non creati: %s", mask_text_for_log(_describe(exc)))
    counts: dict[str, int] = {}
    for o in outcomes:
        counts[o.status] = counts.get(o.status, 0) + 1
    log.info("Genera: %d chiamate%s: %s", len(outcomes), " (interrotto)" if cancelled else "",
             ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "nessuna")
    return BatchReport(run_dir=run_dir, outcomes=tuple(outcomes), zips=zips, cancelled=cancelled)


def _outcome(call: Call, status: Status, reason: str = "", *, doc_type=None,
             files: tuple[Path, ...] = (), duration_ms: int = 0,
             http_status: int | None = None) -> Outcome:
    return Outcome(key=call.key, folders=call.folders, fdi=call.fdi, status=status,
                   doc_type=doc_type, files=tuple(files), duration_ms=int(duration_ms or 0),
                   http_status=http_status, reason=mask_text(reason))


def _target_cancelled(target: Target) -> list[Outcome]:
    """The outcomes of a target never looked up (cancelled during resolution):
    one for a key or a whole FDI, one per key of a narrowed FDI."""
    value = target.value.strip()
    if target.kind == "fdi":
        keys = [k.strip() for k in target.keys if k.strip()] or [""]
        calls = [Call(key=k, folders=(value,), fdi=value, hit=None) for k in keys]
    else:
        calls = [Call(key=value, folders=target.folders or (NO_PACKAGE,), fdi=None, hit=None)]
    return [_outcome(c, "cancelled", REASON_CANCELLED) for c in calls]


def _unexpected(exc: BaseException) -> str:
    # The type only: a message could quote a payload or an answer.
    return f"errore inatteso: {type(exc).__name__}"


def _describe(exc: BaseException) -> str:
    return str(exc) if isinstance(exc, OSError) else type(exc).__name__


def _local(now: datetime) -> datetime:
    """``now`` as an aware local time (a naive one is taken as local)."""
    return now.astimezone()


def _serialised(fn: Callable[[], Any]) -> Callable[[], Any]:
    """``fn`` callable from several threads (a test's ``next(generator)`` is not)."""
    lock = threading.Lock()

    def call() -> Any:
        with lock:
            return fn()
    return call


def _guarded(sink: Callable[[Any], None] | None) -> Callable[[Any], None]:
    """``sink`` that never breaks the run (a closed window, a bug in a consumer)."""
    def emit(event: Any) -> None:
        if sink is None:
            return
        try:
            sink(event)
        except Exception as exc:  # noqa: BLE001
            log.warning("Genera: evento non consegnato: %s", type(exc).__name__)
    return emit
