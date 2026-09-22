"""The Qt-free half of the Sincronizzazione page: progress math and wording.

Nothing here builds (or needs) a ``QApplication``: ``progress_model`` is plain
arithmetic over the core events and ``sync_format`` turns one event into one
line of text. Both are imported and driven directly, with an injected clock, so
the rate/ETA numbers are asserted exactly instead of being raced against a
scripted download.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import (
    EnvFinished,
    EnvResult,
    EnvStarted,
    EnvSkipped,
    EnvUnreachable,
    FileDone,
    FileFailed,
    FileProgress,
    FileSkipped,
    FileStarted,
    IndexFileScanned,
    IndexFinished,
    IndexStarted,
    LogMessage,
    RemoteIndexRead,
    SyncStarted,
)
from qtrequestory.ui.pages import progress_model as pm
from qtrequestory.ui.pages import sync_format as fmt

MB = 1_048_576
GB = 1024 * MB


class FakeClock:
    """A monotonic clock the test advances by hand."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def model(clock: FakeClock) -> pm.ProgressModel:
    return pm.ProgressModel(clock=clock)


# ----------------------------------------------------------- progress model ---

def test_a_fresh_model_is_idle_and_knows_nothing(model):
    snap = model.snapshot()
    assert snap.phase == pm.PHASE_IDLE
    assert snap.env is None and snap.name is None
    assert (snap.file_index, snap.n_files) == (0, 0)
    assert (snap.bytes_done, snap.bytes_total) == (0, 0)
    assert snap.rate_bps is None and snap.eta_s is None


def test_totals_come_from_remote_index_read_across_every_environment(model):
    model.handle(SyncStarted(("coll", "svil"), False))
    model.handle(RemoteIndexRead("coll", n_daily=4, n_empty=1, n_loose=2,
                                 bytes_to_download=8 * MB))
    model.handle(RemoteIndexRead("svil", n_daily=44, n_empty=0, n_loose=0,
                                 bytes_to_download=200 * MB))
    snap = model.snapshot()
    assert snap.bytes_total == 8 * MB + 200 * MB
    assert snap.n_files == 48


def test_the_file_counter_advances_on_every_started_or_skipped_file(model):
    model.handle(SyncStarted(("coll",), False))
    model.handle(RemoteIndexRead("coll", n_daily=3, n_empty=0, n_loose=0, bytes_to_download=3 * MB))
    model.handle(FileSkipped("coll", "20260916.txt", "present"))
    model.handle(FileStarted("coll", "20260917.txt", 1 * MB))
    assert model.snapshot().file_index == 2
    model.handle(FileDone("coll", "20260917.txt", 1 * MB, Path("x")))
    model.handle(FileStarted("coll", "20260918.txt", 2 * MB))
    snap = model.snapshot()
    assert (snap.file_index, snap.n_files) == (3, 3)
    assert snap.name == "20260918.txt" and snap.env == "coll"


def test_bytes_done_adds_the_current_file_to_the_finished_ones(model):
    model.handle(SyncStarted(("coll",), False))
    model.handle(RemoteIndexRead("coll", n_daily=2, n_empty=0, n_loose=0, bytes_to_download=10 * MB))
    model.handle(FileStarted("coll", "a.txt", 4 * MB))
    model.handle(FileDone("coll", "a.txt", 4 * MB, Path("a")))
    model.handle(FileStarted("coll", "b.txt", 6 * MB))
    model.handle(FileProgress("coll", "b.txt", 3 * MB, 6 * MB))
    snap = model.snapshot()
    assert snap.bytes_done == 7 * MB
    assert (snap.file_done, snap.file_size) == (3 * MB, 6 * MB)
    assert snap.file_percent == 50


def test_rate_and_eta_are_computed_over_the_sliding_window(model, clock):
    model.handle(SyncStarted(("coll",), False))
    model.handle(RemoteIndexRead("coll", n_daily=1, n_empty=0, n_loose=0, bytes_to_download=10 * MB))
    model.handle(FileStarted("coll", "a.txt", 10 * MB))
    clock.advance(1.0)
    model.handle(FileProgress("coll", "a.txt", 2 * MB, 10 * MB))
    snap = model.snapshot()
    assert snap.rate_bps == pytest.approx(2 * MB)
    assert snap.eta_s == pytest.approx(4.0)  # 8 MB left at 2 MB/s


def test_a_single_sample_leaves_the_rate_unknown_so_no_eta_is_shown(model):
    model.handle(SyncStarted(("coll",), False))
    model.handle(RemoteIndexRead("coll", n_daily=1, n_empty=0, n_loose=0, bytes_to_download=10 * MB))
    model.handle(FileStarted("coll", "a.txt", 10 * MB))
    snap = model.snapshot()
    assert snap.rate_bps is None and snap.eta_s is None


def test_samples_older_than_the_window_stop_counting(model, clock):
    """A stalled minute must not keep a long-gone burst in the average."""
    model.handle(SyncStarted(("coll",), False))
    model.handle(RemoteIndexRead("coll", n_daily=1, n_empty=0, n_loose=0, bytes_to_download=100 * MB))
    model.handle(FileStarted("coll", "a.txt", 100 * MB))
    clock.advance(0.5)
    model.handle(FileProgress("coll", "a.txt", 50 * MB, 100 * MB))  # very fast burst
    for _ in range(4):
        clock.advance(1.0)
        model.handle(FileProgress("coll", "a.txt", 50 * MB, 100 * MB))  # stalled
    snap = model.snapshot()
    assert snap.rate_bps == pytest.approx(0.0, abs=1.0)
    assert snap.eta_s is None, "a stalled transfer has no honest ETA"


def test_the_index_phase_takes_over_the_same_strip(model):
    model.handle(SyncStarted(("coll",), False))
    model.handle(RemoteIndexRead("coll", n_daily=1, n_empty=0, n_loose=0, bytes_to_download=1 * MB))
    model.handle(FileStarted("coll", "a.txt", 1 * MB))
    model.handle(FileDone("coll", "a.txt", 1 * MB, Path("a")))
    model.handle(IndexStarted(2))
    assert model.snapshot().phase == pm.PHASE_INDEX
    model.handle(IndexFileScanned(Path("mirror/20260918.txt"), 7, 1, 2))
    snap = model.snapshot()
    assert (snap.file_index, snap.n_files) == (1, 2)
    assert snap.name == "20260918.txt"
    assert snap.eta_s is None, "the index phase has no byte totals to predict from"
    model.handle(IndexFinished(2, 0, 0.05))
    assert model.snapshot().phase == pm.PHASE_IDLE


def test_a_failed_file_clears_the_per_file_bar_without_losing_the_run_total(model):
    model.handle(SyncStarted(("coll",), False))
    model.handle(RemoteIndexRead("coll", n_daily=2, n_empty=0, n_loose=0, bytes_to_download=8 * MB))
    model.handle(FileStarted("coll", "a.txt", 4 * MB))
    model.handle(FileDone("coll", "a.txt", 4 * MB, Path("a")))
    model.handle(FileStarted("coll", "b.txt", 4 * MB))
    model.handle(FileProgress("coll", "b.txt", 1 * MB, 4 * MB))
    model.handle(FileFailed("coll", "b.txt", "troncato"))
    snap = model.snapshot()
    assert snap.bytes_done == 4 * MB
    assert snap.file_percent == 0


def test_a_new_run_starts_from_zero(model):
    model.handle(SyncStarted(("coll",), False))
    model.handle(RemoteIndexRead("coll", n_daily=4, n_empty=0, n_loose=0, bytes_to_download=8 * MB))
    model.handle(SyncStarted(("coll",), False))
    snap = model.snapshot()
    assert (snap.bytes_total, snap.n_files) == (0, 0)


# ------------------------------------------------------------------ sizes ---

@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, "0 B"),
        (512, "512 B"),
        (2048, "2 KB"),
        (2560, "2,5 KB"),
        (41 * MB, "41 MB"),
        (int(80.4 * MB), "80,4 MB"),
        (212 * MB, "212 MB"),
        (int(1.5 * GB), "1,5 GB"),
    ],
)
def test_sizes_are_italian_with_a_decimal_comma(value: int, expected: str):
    assert fmt.format_size(value) == expected


def test_a_rate_is_a_size_per_second():
    assert fmt.format_rate(8.2 * MB) == "8,2 MB/s"


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(3, "circa 5 s rimanenti"), (42, "circa 40 s rimanenti"),
     (120, "circa 2 min rimanenti"), (7200, "circa 2 h rimanenti")],
)
def test_an_eta_is_rounded_and_never_pretends_to_be_precise(seconds: float, expected: str):
    assert fmt.format_eta(seconds) == expected


def test_no_eta_at_all_rather_than_a_wrong_one():
    assert fmt.format_eta(None) == ""


# -------------------------------------------------------------- last sync ---

def test_last_sync_reads_as_today_yesterday_or_a_date():
    from datetime import datetime

    now = datetime(2026, 9, 22, 12, 0)
    assert fmt.format_when(datetime(2026, 9, 22, 11, 23), now=now) == "oggi 11:23"
    assert fmt.format_when(datetime(2026, 9, 21, 15, 48), now=now) == "ieri 15:48"
    assert fmt.format_when(datetime(2026, 9, 3, 8, 5), now=now) == "03/09/2026 08:05"
    assert fmt.format_when(None, now=now) == strings.SYNC_WHEN_NEVER


# ----------------------------------------------------- event -> log line ---

def test_a_rendered_event_reuses_the_core_wording_verbatim():
    line = fmt.message(FileDone("coll", "20260918.txt", 4 * MB, Path("x")))
    assert line == "coll: scaricato 20260918.txt (4.0 MB)"
    assert fmt.message(RemoteIndexRead("coll", 4, 1, 2, 4 * MB)) == (
        "coll: index letto: 4 file giornalieri, 1 vuoti, 2 sciolti, 4.0 MB da scaricare"
    )
    assert fmt.message(EnvUnreachable("coll", "timeout")) == (
        "coll: endpoint non raggiungibile, riprovo al prossimo giro (timeout)"
    )
    assert fmt.message(EnvSkipped("coll", "fresh")) == (
        "coll: già sincronizzato dopo l'ultima compattazione, niente da fare"
    )
    assert fmt.message(LogMessage(logging.INFO, "ciao")) == "ciao"
    assert fmt.message(EnvFinished("coll", EnvResult("coll", "ok", downloaded=1, present=2))) == (
        "coll: 1 scaricati, 2 già presenti, 0 vuoti saltati, 0 errori (ok)"
    )
    assert fmt.message(FileFailed("coll", "a.txt", "troncato")) == "coll: ERRORE su a.txt: troncato"


def test_the_chatty_events_produce_no_line_at_all():
    assert fmt.message(FileStarted("coll", "a.txt", 1)) is None
    assert fmt.message(FileProgress("coll", "a.txt", 1, 2)) is None
    assert fmt.message(SyncStarted(("coll",), False)) is None
    assert fmt.message(FileSkipped("coll", "a.txt", "present")) is None
    assert fmt.message(IndexStarted(0)) is None, "nothing to index is not worth a line"


def test_a_log_line_carries_the_same_timestamp_prefix_as_sync_log():
    from datetime import datetime

    ts = datetime(2026, 9, 22, 9, 3, 0).timestamp()
    line = fmt.log_line(FileDone("coll", "a.txt", 0, Path("x"), ts=ts))
    assert line == "[2026-09-22 09:03:00] coll: scaricato a.txt (0.0 MB)"
    assert fmt.log_line(FileStarted("coll", "a.txt", 1)) is None


def test_rendering_one_event_never_leaks_into_the_next():
    """The formatter reuses one LoggingSink; a stale line must not survive."""
    assert fmt.message(LogMessage(logging.INFO, "prima")) == "prima"
    assert fmt.message(FileStarted("coll", "a.txt", 1)) is None
    assert fmt.message(LogMessage(logging.INFO, "dopo")) == "dopo"


def test_the_formatter_does_not_write_into_the_application_log(caplog):
    with caplog.at_level(logging.DEBUG):
        fmt.message(FileFailed("coll", "a.txt", "troncato"))
    assert caplog.records == [], "the registro must not duplicate every line into app.log"


# ------------------------------------------------------------ task status ---

def test_the_task_status_line_says_active_next_and_last():
    from qtrequestory.ui.contracts import TaskStatus

    task = TaskStatus(registered=True, command=Path("q.exe"), args="--sync", exe_matches=True,
                      state="Pronto", next_run="domani 09:00", last_run="oggi 11:24", last_result=0)
    line = fmt.format_task_status(task)
    assert strings.SYNC_AUTO_ON in line
    assert "domani 09:00" in line and "oggi 11:24" in line and "0" in line


def test_an_unregistered_task_says_only_that():
    from qtrequestory.core.scheduler import NOT_REGISTERED

    assert fmt.format_task_status(NOT_REGISTERED) == strings.SYNC_AUTO_OFF


# ------------------------------------------------------------- strip texts ---

def build_strip(model: pm.ProgressModel) -> fmt.StripTexts:
    return fmt.strip_texts(model.snapshot())


def test_the_strip_reads_file_totals_rate_and_eta_together(model, clock):
    model.handle(SyncStarted(("coll",), False))
    model.handle(RemoteIndexRead("coll", n_daily=48, n_empty=0, n_loose=0,
                                 bytes_to_download=int(1.4 * GB)))
    model.handle(FileStarted("coll", "20260716.txt", int(80.4 * MB)))
    clock.advance(1.0)
    model.handle(FileProgress("coll", "20260716.txt", int(8.2 * MB), int(80.4 * MB)))

    strip = build_strip(model)
    assert strip.label == "coll · 20260716.txt (80,4 MB)"
    assert strip.totals.startswith("file 1 di 48 · ")
    assert strip.totals.endswith("/1,4 GB")
    assert strip.rate.startswith("8,2 MB/s · circa ")
    assert strip.percent == 10


def test_the_strip_hides_the_rate_until_it_is_known(model):
    model.handle(SyncStarted(("coll",), False))
    model.handle(RemoteIndexRead("coll", n_daily=1, n_empty=0, n_loose=0, bytes_to_download=MB))
    model.handle(FileStarted("coll", "a.txt", MB))
    assert build_strip(model).rate == ""


def test_the_strip_says_nothing_about_the_file_before_there_is_one(model):
    model.handle(SyncStarted(("coll", "svil"), False))
    assert build_strip(model).label == "", "an empty label keeps 'Avvio…' on screen"
    model.handle(EnvStarted("coll"))
    assert build_strip(model).label == "coll · lettura index…"


def test_the_index_phase_counts_files_and_shows_no_rate(model):
    model.handle(SyncStarted(("coll",), False))
    model.handle(IndexStarted(2))
    strip = build_strip(model)
    assert strip.label == strings.SYNC_PROGRESS_INDEXING and strip.totals == "file 0 di 2"
    model.handle(IndexFileScanned(Path("mirror/20260918.txt"), 7, 1, 2))
    strip = build_strip(model)
    assert strip.label == "Indicizzazione · 20260918.txt"
    assert strip.totals == "file 1 di 2"
    assert strip.rate == "" and strip.percent == 0
