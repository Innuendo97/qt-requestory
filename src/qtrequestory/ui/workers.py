"""Background jobs: core calls on a thread pool, results as Qt signals.

The core is synchronous and blocking (HTTP downloads, SQLite scans, subprocess
calls). Running any of it on the GUI thread freezes the window, so every page
goes through the one :class:`JobRunner` the shell creates and hands to the page
factories.

The three rules that make this safe, and that every page can rely on:

* **Widgets are never touched from a worker.** A job communicates only through
  the signals of its :class:`WorkerSignals`; those are emitted from the worker
  thread and Qt delivers them queued on the GUI thread, because both the signal
  owner and the connected widgets live there.
* **One live job per name.** ``submit("sync", ...)`` while a sync runs is
  *refused* (returns ``None`` and emits :attr:`JobRunner.busy`) — see
  :attr:`JobRunner.EXCLUSIVE`. Every other name *supersedes*: the previous job
  with that name is marked superseded, cancelled, and goes silent, so a slow
  first search can never overwrite the results of the second one. "Silent" is
  guaranteed, not best effort: the check happens on the GUI thread at delivery
  time (:class:`_Delivery`), so a page never needs its own request ids.
* **Cancellation is cooperative.** The job owns a :class:`CancelToken` from the
  core; ``job.cancel()`` sets it and the core function raises ``Cancelled`` at
  its next check point, which becomes the ``cancelled`` signal. Functions that
  handle cancellation themselves (``sync.run`` returns a report with exit code
  3) simply deliver their result as usual.

Progress arrives as the core's own event dataclasses through a
:class:`QtEventSink`, which also coalesces the very chatty ``FileProgress``
events to ~10/s so a 2 GB download cannot flood the event queue.
"""
from __future__ import annotations

import inspect
import itertools
import logging
import time
from collections.abc import Callable, Mapping, Sequence
from functools import partial
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal

from qtrequestory.ui.contracts import CancelToken, Cancelled, Event, FileProgress, LogMessage

__all__ = ["CancelToken", "Job", "JobRunner", "QtEventSink", "Worker", "WorkerSignals"]

log = logging.getLogger(__name__)

#: Minimum seconds between two forwarded ``FileProgress`` events of one job.
PROGRESS_INTERVAL_S = 0.1

_next_id = itertools.count(1).__next__


class WorkerSignals(QObject):
    """The signals of a single job. Connect to these, never to the worker.

    ``progress`` carries the core ``Event`` dataclasses (``FileStarted``,
    ``RemoteIndexRead``, ``IndexFinished``, ...); ``log`` is the text of the
    ``LogMessage`` events, offered separately because most pages just append it
    to a log view. Exactly one of ``result`` / ``error`` / ``cancelled`` fires,
    always followed by ``finished``.
    """

    started = Signal()
    progress = Signal(object)
    log = Signal(str)
    result = Signal(object)
    error = Signal(str, str)  # exception class name, message
    finished = Signal()
    cancelled = Signal()


class QtEventSink(QObject):
    """A core ``EventSink`` (a callable) that re-emits events as a Qt signal.

    Created on the GUI thread and called from the worker thread: because the
    object lives in the GUI thread, Qt queues every connected slot there, which
    is what makes it legal for a slot to touch widgets.

    ``FileProgress`` is throttled to one event per ``min_interval`` seconds —
    the core emits one per downloaded chunk, which is thousands per file. No
    information is lost: ``FileDone`` always follows, and the progress bar only
    needs a recent sample. Every other event type passes through untouched,
    because losing an ``EnvFinished`` would corrupt what the page shows.
    """

    event = Signal(object)

    def __init__(self, min_interval: float = PROGRESS_INTERVAL_S,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._min_interval = min_interval
        self._last_progress = 0.0

    def __call__(self, ev: Event) -> None:
        if isinstance(ev, FileProgress):
            now = time.monotonic()
            if now - self._last_progress < self._min_interval:
                return
            self._last_progress = now
        self.event.emit(ev)


class _Delivery(QObject):
    """Carries a job's signals to the GUI thread and drops superseded ones.

    Why this exists rather than a flag the worker reads: ``superseded`` is set
    on the GUI thread (inside ``submit``) while the worker is running, so a
    check made on the *worker* thread can pass a microsecond before the job is
    superseded and the page would still receive the stale result. Here the check
    happens where the signal is *delivered* — on the GUI thread, after the queue
    — which makes "a superseded job is silent" a guarantee.

    It also puts every signal of a job on one queue, so ``progress`` and
    ``result`` reach the page in the order the worker produced them.
    """

    _forward = Signal(str, object)

    def __init__(self, job: Job) -> None:
        super().__init__()
        self._job = job
        self._forward.connect(self._on_forward)  # queued: emitted from the worker

    def is_live(self) -> bool:
        return self._job.is_live()

    def send(self, name: str, *args: Any) -> None:
        """Called from the worker thread; ``name`` is a ``WorkerSignals`` member."""
        self._forward.emit(name, args)

    def _on_forward(self, name: str, args: tuple) -> None:
        if self._job.is_live():
            getattr(self._job.signals, name).emit(*args)


class Worker(QRunnable):
    """Runs one callable on a pool thread and reports through ``signals``.

    ``sink=`` and ``cancel=`` are injected only when the callable declares them
    (``index.search(q)`` takes neither, ``sync.run(...)`` takes both), so the
    same worker serves every core API without adapters.

    With a ``delivery`` (what :class:`JobRunner` always passes) the signals go
    through it and a superseded job is silenced; without one — a page running a
    ``Worker`` by hand — they are emitted straight away.
    """

    def __init__(
        self,
        signals: WorkerSignals,
        cancel: CancelToken,
        sink: QtEventSink,
        fn: Callable[..., Any],
        args: Sequence[Any] = (),
        kwargs: Mapping[str, Any] | None = None,
        delivery: _Delivery | None = None,
    ) -> None:
        super().__init__()
        self._signals = signals
        self._cancel = cancel
        self._sink = sink
        self._fn = fn
        self._args = tuple(args)
        self._kwargs = dict(kwargs or {})
        self._delivery = delivery
        self._done: Callable[[], None] | None = None

    def set_done_callback(self, done: Callable[[], None]) -> None:
        """Called on the worker thread just before ``finished`` is emitted."""
        self._done = done

    def run(self) -> None:  # noqa: D102 - QRunnable entry point
        if self._delivery is not None and not self._delivery.is_live():
            return  # superseded before it even started: do not run the call
        self._emit("started")
        try:
            value = self._fn(*self._args, **self._call_kwargs())
            self._emit("result", value)
        except Cancelled:
            self._emit("cancelled")
        except Exception as exc:  # noqa: BLE001 - any core failure becomes a message
            log.exception("job %s failed", getattr(self._fn, "__name__", self._fn))
            self._emit("error", type(exc).__name__, str(exc))
        finally:
            if self._done is not None:
                self._done()
            self._emit("finished")

    # -- internals ---------------------------------------------------------

    def _call_kwargs(self) -> dict[str, Any]:
        kwargs = dict(self._kwargs)
        if _accepts(self._fn, "sink"):
            kwargs.setdefault("sink", self._sink)
        if _accepts(self._fn, "cancel"):
            kwargs.setdefault("cancel", self._cancel)
        return kwargs

    def _emit(self, name: str, *args: Any) -> None:
        if self._delivery is not None:
            self._delivery.send(name, *args)
        else:
            getattr(self._signals, name).emit(*args)


def _accepts(fn: Callable[..., Any], name: str) -> bool:
    """True when ``fn`` declares a ``name`` parameter (or takes ``**kwargs``)."""
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):  # builtins, C callables
        return False
    if name in params:
        return True
    return any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


class Job:
    """Handle on one submitted call: its signals, its sink and its cancel token.

    Pages keep a job to connect its signals and to cancel it; the runner keeps
    it to answer ``is_running`` and to supersede it.
    """

    __slots__ = ("id", "name", "signals", "sink", "token", "superseded", "finished",
                 "_delivery")

    def __init__(self, job_id: int, name: str, signals: WorkerSignals, sink: QtEventSink,
                 token: CancelToken) -> None:
        self.id = job_id
        self.name = name
        self.signals = signals
        self.sink = sink
        self.token = token
        self.superseded = False
        self.finished = False
        #: Set by the runner; kept here so the relay lives as long as the job.
        self._delivery: _Delivery | None = None

    def cancel(self) -> None:
        """Ask the core function to stop at its next check point."""
        self.token.cancel()

    def is_live(self) -> bool:
        """False once the job was superseded: it must stay completely silent."""
        return not self.superseded

    def is_running(self) -> bool:
        return not self.finished and not self.superseded

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Job {self.name}#{self.id} running={self.is_running()}>"


class JobRunner(QObject):
    """The one thread pool of the application, shared by every page.

    Four threads, one per name that can be live at the same time: ``sync`` and
    ``index`` (both exclusive) plus ``search`` and ``preview``. A fifth name
    would simply queue behind them — which is fine, but the four that the UI
    actually overlaps must never wait for each other. The runner is created by
    ``run_gui`` and passed to every page factory.
    """

    #: A submit with one of these names is refused while one is still running,
    #: because a second one would fight over the same lock/database. Everything
    #: else supersedes instead.
    EXCLUSIVE = frozenset({"sync", "index"})

    #: Emitted with the job name when an exclusive submit was refused.
    busy = Signal(str)

    def __init__(self, parent: QObject | None = None, *, max_threads: int = 4,
                 progress_interval: float = PROGRESS_INTERVAL_S) -> None:
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(max_threads)
        self._progress_interval = progress_interval
        self._jobs: dict[str, Job] = {}
        self._closing = False

    def submit(self, name: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Job | None:
        """Run ``fn(*args, **kwargs)`` on a pool thread; ``None`` when refused.

        ``sink=`` and ``cancel=`` are added by the worker when ``fn`` accepts
        them, so callers pass only the real arguments. ``None`` is also what a
        page gets while the application is shutting down — a job that would
        never run must not look like one that will.
        """
        if self._closing:
            log.debug("job %s refused: chiusura in corso", name)
            return None
        previous = self._jobs.get(name)
        if name in self.EXCLUSIVE and previous is not None and previous.is_running():
            log.debug("job %s refused: already running", name)
            self.busy.emit(name)
            return None
        if previous is not None:
            previous.superseded = True
            previous.cancel()  # a superseded job should stop as soon as it can

        # No parent: the sink and the signals must be freed with the job they
        # belong to, otherwise every search would leave two QObjects behind on
        # the runner for the lifetime of the application.
        sink = QtEventSink(self._progress_interval)
        signals = WorkerSignals()
        job = Job(_next_id(), name, signals, sink, CancelToken())
        delivery = _Delivery(job)
        job._delivery = delivery
        sink.event.connect(partial(_relay_event, delivery))
        self._jobs[name] = job

        worker = Worker(signals, job.token, sink, fn, args, kwargs, delivery=delivery)
        worker.set_done_callback(partial(_mark_finished, job))
        # Start on the next turn of the event loop, never inside submit(): the
        # caller gets the job back and connects its signals first, so a fast job
        # cannot emit `result` before anybody listens.
        QTimer.singleShot(0, partial(self._start, worker))
        return job

    def _start(self, worker: Worker) -> None:
        """Deferred pool start; skipped when the application is quitting."""
        if not self._closing:
            self._pool.start(worker)

    def job(self, name: str) -> Job | None:
        """The last job submitted under ``name`` (running or not)."""
        return self._jobs.get(name)

    def is_running(self, name: str) -> bool:
        job = self._jobs.get(name)
        return job is not None and job.is_running()

    def cancel(self, name: str) -> None:
        job = self._jobs.get(name)
        if job is not None:
            job.cancel()

    def cancel_all(self) -> None:
        for job in self._jobs.values():
            job.cancel()

    def shutdown(self, timeout_ms: int = 5000) -> bool:
        """Cancel everything and wait for the pool: called when the app quits.

        One way: the runner accepts no more work afterwards.

        Without this, Qt tears the pool down while a worker still touches
        Python objects, which on Windows shows up as a crash on exit.
        """
        self._closing = True
        self.cancel_all()
        return self._pool.waitForDone(timeout_ms)


def _relay_event(delivery: _Delivery, ev: Event) -> None:
    """Core event (worker thread) -> ``progress``, and ``log`` for a message."""
    delivery.send("progress", ev)
    if isinstance(ev, LogMessage):
        delivery.send("log", ev.text)


def _mark_finished(job: Job) -> None:
    """Runs on the worker thread, before ``finished`` reaches the GUI thread,
    so ``is_running`` is already False when a page handles that signal."""
    job.finished = True
