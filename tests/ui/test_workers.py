"""The background-job layer: threads in, Qt signals on the GUI thread out.

Every assertion here is about a rule five page tasks rely on, so they are
written against observable behaviour (which signal fires, on which thread, with
what payload) and never against internals.
"""
from __future__ import annotations

import logging
import threading
import time


# The events come through the UI's own seam, exactly as a page would import them.
from qtrequestory.ui.contracts import Cancelled, FileDone, FileProgress, LogMessage
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


def test_a_second_schtasks_call_is_refused_rather_than_superseding_the_first(qtbot, runner):
    """``schtasks`` ignores the cancel token, so a superseded call still runs:
    the two would land in either order and the task could end up in the state
    of the *first* one. Both pages that drive it use ``SCHEDULER_JOB``."""
    from qtrequestory.ui.workers import SCHEDULER_JOB

    assert SCHEDULER_JOB in JobRunner.EXCLUSIVE
    gate = threading.Event()
    refused: list[str] = []
    runner.busy.connect(refused.append)

    job = runner.submit(SCHEDULER_JOB, lambda: gate.wait(3.0))

    assert runner.submit(SCHEDULER_JOB, lambda: None) is None
    assert refused == [SCHEDULER_JOB]

    gate.set()
    with qtbot.waitSignal(job.signals.finished, timeout=3000):
        pass
    assert runner.submit(SCHEDULER_JOB, lambda: None) is not None


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


def test_a_result_already_emitted_is_dropped_when_the_job_is_superseded(qtbot, runner):
    """The guarantee is "silent", not "usually silent".

    A worker can finish while the GUI thread is busy elsewhere: its signal is
    then sitting in the queue when the next submit supersedes the job. Checking
    liveness on the worker thread would let that stale result through, so the
    check has to happen at delivery time.
    """
    started = threading.Event()
    release = threading.Event()
    results: list[str] = []

    def first():
        started.set()
        release.wait(3.0)
        return "primo"

    job1 = runner.submit("search", first)
    job1.signals.result.connect(results.append)
    qtbot.waitUntil(started.is_set, timeout=3000)

    # From here on the GUI thread never spins the event loop: the worker emits
    # into the queue and nothing is delivered.
    release.set()
    deadline = time.monotonic() + 3.0
    while not job1.finished and time.monotonic() < deadline:
        time.sleep(0.005)
    assert job1.finished, "the worker must have emitted before the loop runs again"

    job2 = runner.submit("search", lambda: "secondo")  # supersedes the queued result
    job2.signals.result.connect(results.append)
    with qtbot.waitSignal(job2.signals.finished, timeout=3000):
        pass
    qtbot.wait(100)

    assert results == ["secondo"]


def test_superseded_jobs_are_cancelled_so_they_stop_early(qtbot, runner):
    job1 = runner.submit("preview", lambda *, cancel: None)
    # no event loop turn in between: the first worker has not even started
    runner.submit("preview", lambda *, cancel: None)
    assert job1.token.is_set() is True


def test_a_shut_down_runner_refuses_new_work(qapp):
    """Nothing may be queued while the pool is being torn down."""
    runner = JobRunner()
    runner.shutdown(1000)
    assert runner.submit("search", lambda: "tardi") is None


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


def test_shutdown_leaves_no_job_claiming_to_still_be_running(qapp):
    """A job whose deferred start never came must not look like a live one.

    ``submit`` starts the worker on the next turn of the event loop. When the
    application quits before that turn — ``run_gui`` returning from ``exec``,
    or a first sync started right before the window closes — the job would stay
    "running" forever, and ``MainWindow.closeEvent`` would ask the user whether
    to interrupt a sync that can no longer happen.
    """
    runner = JobRunner()
    job = runner.submit("sync", lambda: None)  # no event loop turn before shutdown
    assert runner.shutdown(2000) is True
    assert not runner.is_running("sync")
    assert not job.is_running()


def test_shutdown_does_not_claim_a_job_finished_when_the_pool_did_not_drain(qapp, monkeypatch):
    """A timed-out ``waitForDone`` means a worker IS still running.

    Marking the jobs finished anyway made ``is_running`` lie about a thread
    still inside the core, which is the one case a caller must be able to trust.
    """
    runner = JobRunner()
    job = runner.submit("sync", lambda: None)
    monkeypatch.setattr(runner._pool, "waitForDone", lambda _ms: False)

    assert runner.shutdown(10) is False
    assert job.is_running()
    assert runner.is_running("sync")


# ------------------------------------------------------------- pool sizing ---

def test_the_pool_has_a_thread_per_name_plus_room_for_superseded_jobs():
    """Four threads for nine names meant a search could WAIT for a sync.

    One job per name is *live*, but a superseded job keeps its thread until
    the core function reaches a cancel check point (``read_body`` has none),
    so the pool holds a few threads more than there are names. Anything
    smaller means a 20-minute download plus a couple of superseded searches
    can hold every thread while the user presses [Cerca].
    """
    from qtrequestory.ui.workers import JOB_NAMES, SUPERSEDED_HEADROOM

    runner = JobRunner()
    try:
        assert SUPERSEDED_HEADROOM == 4
        assert runner.max_thread_count() == len(JOB_NAMES) + 4
        assert len(JOB_NAMES) >= 9
    finally:
        runner.shutdown()


# ------------------------------------------------------------ job_finished ---

def test_job_finished_reports_the_name_and_success(qtbot, runner):
    seen: list[tuple[str, bool]] = []
    runner.job_finished.connect(lambda name, ok: seen.append((name, ok)))

    job = runner.submit("index", lambda: 42)
    with qtbot.waitSignal(job.signals.finished, timeout=3000):
        pass
    qtbot.waitUntil(lambda: bool(seen), timeout=3000)
    assert seen == [("index", True)]


def test_job_finished_reports_a_failure_and_a_cancellation_as_not_ok(qtbot, runner):
    seen: list[tuple[str, bool]] = []
    runner.job_finished.connect(lambda name, ok: seen.append((name, ok)))

    def boom():
        raise RuntimeError("no")

    def cancelled():
        raise Cancelled()

    for name, fn in (("sync", boom), ("index", cancelled)):
        job = runner.submit(name, fn)
        with qtbot.waitSignal(job.signals.finished, timeout=3000):
            pass
    qtbot.waitUntil(lambda: len(seen) == 2, timeout=3000)
    assert seen == [("sync", False), ("index", False)]


def test_a_superseded_job_never_reports_job_finished(qtbot, runner):
    seen: list[tuple[str, bool]] = []
    runner.job_finished.connect(lambda name, ok: seen.append((name, ok)))
    gate = threading.Event()
    runner.submit("search", lambda: gate.wait(5.0))
    second = runner.submit("search", lambda: "b")
    with qtbot.waitSignal(second.signals.finished, timeout=3000):
        pass
    gate.set()
    qtbot.wait(100)
    assert seen == [("search", True)]


def test_every_name_a_page_submits_is_declared():
    """``JOB_NAMES`` is only honest if it is the whole list; a name missing
    from it is a job that may queue behind a sync, and a status-bar message
    with an internal identifier in it."""
    from qtrequestory.ui.main_window import JOB_LABELS
    from qtrequestory.ui.pages.about_page import LOG_JOB
    from qtrequestory.ui.pages.preview_pane import PREVIEW_JOB
    from qtrequestory.ui.pages.settings_page import CHECK_JOB, INDEX_JOB
    from qtrequestory.ui.pages.sync_auto_card import TASK_STATUS_JOB
    from qtrequestory.ui.pages.sync_page import REACHABILITY_JOB as SYNC_REACHABILITY_JOB
    from qtrequestory.ui.wizard_pages import REACHABILITY_JOB
    from qtrequestory.ui.pages.officina_jobs import COMPARE_JOB, GENERATE_JOBS, SUMMARY_JOB
    from qtrequestory.ui.workers import JOB_NAMES, SCHEDULER_JOB

    declared = set(JOB_NAMES)
    assert {*GENERATE_JOBS, COMPARE_JOB, SUMMARY_JOB} <= declared
    assert GENERATE_JOBS[0] == "officina-generate" and COMPARE_JOB == "officina-compare"
    assert set(GENERATE_JOBS) <= JobRunner.EXCLUSIVE, "a generation is never superseded"
    assert {LOG_JOB, PREVIEW_JOB, CHECK_JOB, INDEX_JOB, REACHABILITY_JOB,
            SCHEDULER_JOB, TASK_STATUS_JOB, SYNC_REACHABILITY_JOB} <= declared
    assert {"sync", "search", "search_keys", "search_plan"} <= declared
    assert set(JOB_LABELS) == declared, "every job name gets a label the user can read"


# ------------------------------------------------- which thread runs what ---

def _tid(box):
    """Module level, and not a lambda: PySide only keeps a connected callable
    alive while something references it."""
    def record(*_args):
        box.append(threading.get_ident())
    return record


def test_the_sink_connection_is_queued_to_the_gui_thread(qtbot):
    """Where each hop of an event runs. Measured, because it is not obvious.

    ``JobRunner`` connects ``sink.event`` to ``partial(_relay_event, delivery)``
    — a callable with no receiver ``QObject``. Qt then uses the SENDER as the
    connection's context, and ``QtEventSink`` was created on the GUI thread, so
    an emission from a worker is QUEUED, not run in place. Everything after the
    emit therefore already runs on the GUI thread.

    Worth a test rather than a comment: connect the same signal to a bound
    method of a worker-affine object, or hand Qt a context object, and the
    thread changes underneath every page without a single test noticing.
    """
    sink = QtEventSink(min_interval=0.0)
    threads: list[int] = []
    handler = _tid(threads)
    sink.event.connect(handler)
    gui = threading.get_ident()
    done = threading.Event()

    def emit_from_a_worker():
        sink(LogMessage(ts=0.0, level=logging.INFO, text="dal worker"))
        done.set()

    worker = threading.Thread(target=emit_from_a_worker)
    worker.start()
    assert done.wait(5)
    worker.join(5)

    assert threads == [], "nothing runs on the worker: the connection is queued"
    qtbot.waitUntil(lambda: bool(threads), timeout=5000)
    assert threads == [gui]


def test_a_job_delivers_progress_and_result_on_the_gui_thread(qtbot):
    """The rule pages depend on: a slot may touch widgets."""
    runner = JobRunner()
    gui = threading.get_ident()
    threads: list[int] = []

    def work(*, sink, cancel):
        sink(LogMessage(ts=0.0, level=logging.INFO, text="in corso"))
        return threading.get_ident()

    try:
        job = runner.submit("search", work)
        job.signals.progress.connect(lambda _ev: threads.append(threading.get_ident()))
        with qtbot.waitSignal(job.signals.result, timeout=5000) as blocker:
            pass
        assert blocker.args[0] != gui, "the core call itself ran on a pool thread"
        qtbot.waitUntil(lambda: bool(threads), timeout=5000)
        assert set(threads) == {gui}
    finally:
        runner.shutdown()
