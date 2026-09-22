"""The background-job layer: threads in, Qt signals on the GUI thread out.

Every assertion here is about a rule five page tasks rely on, so they are
written against observable behaviour (which signal fires, on which thread, with
what payload) and never against internals.
"""
from __future__ import annotations

import logging
import threading


from qtrequestory.core.events import Cancelled, FileDone, FileProgress, LogMessage
from qtrequestory.ui.workers import CancelToken, JobRunner, QtEventSink, Worker, WorkerSignals

MAIN_THREAD = threading.get_ident()

# The ``runner`` fixture (a JobRunner stopped after the test) lives in conftest.

# ------------------------------------------------------------------ worker ---

def test_worker_runs_the_fn_and_delivers_the_result_on_the_gui_thread(qtbot, runner):
    seen: list[tuple[object, int]] = []

    def work(a, b):
        return (a + b, threading.get_ident())

    job = runner.submit("calc", work, 2, 3)
    job.signals.result.connect(lambda value: seen.append((value, threading.get_ident())))
    with qtbot.waitSignal(job.signals.finished, timeout=3000):
        pass

    (payload, slot_thread) = seen[0]
    total, worker_thread = payload
    assert total == 5
    assert worker_thread != MAIN_THREAD, "the fn must not run on the GUI thread"
    assert slot_thread == MAIN_THREAD, "the result must be delivered on the GUI thread"


def test_worker_only_injects_sink_and_cancel_when_the_fn_accepts_them(qtbot, runner):
    """`index.search(q)` takes neither; `sync.run(...)` takes both."""
    got: dict[str, object] = {}

    def plain(value):
        return value

    def full(value, *, sink, cancel):
        got["sink"] = sink
        got["cancel"] = cancel
        sink(LogMessage(logging.INFO, "ciao"))
        return value

    job = runner.submit("plain", plain, "x")
    with qtbot.waitSignal(job.signals.result, timeout=3000) as blocker:
        pass
    assert blocker.args == ["x"]

    job2 = runner.submit("full", full, "y")
    with qtbot.waitSignal(job2.signals.result, timeout=3000):
        pass
    assert got["sink"] is job2.sink
    assert got["cancel"] is job2.token


def test_an_exception_becomes_the_error_signal(qtbot, runner):
    def boom():
        raise ValueError("rotto")

    job = runner.submit("boom", boom)
    with qtbot.waitSignal(job.signals.error, timeout=3000) as blocker:
        pass
    assert blocker.args == ["ValueError", "rotto"]


def test_cancel_stops_a_long_fn_and_emits_cancelled(qtbot, runner):
    started = threading.Event()

    def long_job(*, cancel: CancelToken):
        started.set()
        while True:
            cancel.check()

    job = runner.submit("long", long_job)
    qtbot.waitUntil(started.is_set, timeout=3000)  # the loop must spin for it to start
    with qtbot.waitSignals([job.signals.cancelled, job.signals.finished], timeout=3000):
        job.cancel()
    assert runner.is_running("long") is False


def test_events_from_the_fn_arrive_as_progress_on_the_gui_thread(qtbot, runner):
    seen: list[tuple[object, int]] = []

    def work(*, sink):
        sink(FileDone("coll", "20260918.txt", 10, __import__("pathlib").Path("x")))
        return None

    job = runner.submit("ev", work)
    job.signals.progress.connect(lambda ev: seen.append((ev, threading.get_ident())))
    with qtbot.waitSignal(job.signals.finished, timeout=3000):
        pass
    qtbot.waitUntil(lambda: bool(seen), timeout=3000)

    event, thread = seen[0]
    assert isinstance(event, FileDone) and event.name == "20260918.txt"
    assert thread == MAIN_THREAD


def test_log_messages_are_also_offered_as_plain_text(qtbot, runner):
    lines: list[str] = []

    def work(*, sink):
        sink(LogMessage(logging.INFO, "sincronizzazione già in corso"))

    job = runner.submit("log", work)
    job.signals.log.connect(lines.append)
    with qtbot.waitSignal(job.signals.finished, timeout=3000):
        pass
    qtbot.waitUntil(lambda: bool(lines), timeout=3000)
    assert lines == ["sincronizzazione già in corso"]


# ------------------------------------------------------------- job policies ---

def test_a_second_sync_submit_is_refused_while_the_first_runs(qtbot, runner):
    gate = threading.Event()
    refused: list[str] = []
    runner.busy.connect(refused.append)

    job = runner.submit("sync", lambda: gate.wait(3.0))
    assert runner.is_running("sync") is True, "a queued job already counts as running"

    assert runner.submit("sync", lambda: None) is None
    assert refused == ["sync"]

    gate.set()
    with qtbot.waitSignal(job.signals.finished, timeout=3000):
        pass
    assert runner.is_running("sync") is False
    assert runner.submit("sync", lambda: None) is not None


def test_a_second_search_supersedes_the_first_and_its_result_is_dropped(qtbot, runner):
    gate = threading.Event()
    running = threading.Event()
    first_done = threading.Event()
    results: list[str] = []

    def first():
        running.set()
        gate.wait(3.0)
        first_done.set()
        return "primo"

    job1 = runner.submit("search", first)
    job1.signals.result.connect(results.append)
    qtbot.waitUntil(running.is_set, timeout=3000)  # in flight before the second one
    job2 = runner.submit("search", lambda: "secondo")
    job2.signals.result.connect(results.append)

    assert job2.id > job1.id
    assert job1.superseded is True

    with qtbot.waitSignal(job2.signals.result, timeout=3000):
        pass
    gate.set()
    qtbot.waitUntil(first_done.is_set, timeout=3000)
    qtbot.wait(150)

    assert results == ["secondo"], "a superseded job must stay silent"


def test_superseded_jobs_are_cancelled_so_they_stop_early(qtbot, runner):
    job1 = runner.submit("preview", lambda *, cancel: None)
    # no event loop turn in between: the first worker has not even started
    runner.submit("preview", lambda *, cancel: None)
    assert job1.token.is_set() is True


# ----------------------------------------------------------------- the sink ---

def test_qt_event_sink_emits_every_event_it_is_called_with(qtbot):
    sink = QtEventSink()
    seen: list[object] = []
    sink.event.connect(seen.append)

    sink(LogMessage(logging.INFO, "a"))
    sink(FileDone("coll", "f", 1, __import__("pathlib").Path("p")))

    assert len(seen) == 2


def test_rapid_file_progress_is_coalesced_but_other_events_are_not(qtbot):
    sink = QtEventSink(min_interval=10.0)  # nothing else may pass for 10 s
    seen: list[object] = []
    sink.event.connect(seen.append)

    for done in range(10):
        sink(FileProgress("coll", "20260918.txt", done, 10))
    for i in range(3):
        sink(LogMessage(logging.INFO, f"riga {i}"))

    progress = [e for e in seen if isinstance(e, FileProgress)]
    assert len(progress) == 1, "only the first FileProgress of the window is forwarded"
    assert len([e for e in seen if isinstance(e, LogMessage)]) == 3


def test_progress_coalescing_lets_a_later_event_through(qtbot):
    sink = QtEventSink(min_interval=0.0)
    seen: list[object] = []
    sink.event.connect(seen.append)

    for done in range(3):
        sink(FileProgress("coll", "f", done, 3))

    assert len(seen) == 3


# --------------------------------------------------------- building blocks ---

def test_worker_signals_expose_the_documented_names():
    signals = WorkerSignals()
    for name in ("started", "progress", "log", "result", "error", "finished", "cancelled"):
        assert hasattr(signals, name), name


def test_worker_can_be_used_without_the_runner(qtbot):
    """`Worker` is a plain QRunnable: pages may run one directly if they must."""
    signals = WorkerSignals()
    seen: list[object] = []
    signals.result.connect(seen.append)
    worker = Worker(signals, CancelToken(), QtEventSink(), lambda: "ok")
    worker.run()  # synchronously, on this thread
    qtbot.waitUntil(lambda: bool(seen), timeout=2000)
    assert seen == ["ok"]


def test_cancelled_inside_a_direct_worker_emits_cancelled(qtbot):
    signals = WorkerSignals()
    seen: list[str] = []
    signals.cancelled.connect(lambda: seen.append("cancelled"))
    token = CancelToken()
    token.cancel()

    def work(*, cancel):
        cancel.check()
        raise AssertionError("unreachable")

    Worker(signals, token, QtEventSink(), work).run()
    qtbot.waitUntil(lambda: bool(seen), timeout=2000)
    assert seen == ["cancelled"]
    assert Cancelled is not None  # the core exception is the one we catch
