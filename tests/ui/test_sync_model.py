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


def test_whole_kb_keeps_kilobytes_all_the_way_up_for_the_results_table():
    """The Ricerca table wants one unit for every row, so a 1,4 MB body and a
    312 KB one can be compared by eye; every other caller wants the readable
    unit. One function, one flag, so the same body cannot read "1.434 KB" in
    the table and "1,4 MB" in the status bar of the same click."""
    assert fmt.format_size(4096, whole_kb=True) == "4 KB"
    assert fmt.format_size(0, whole_kb=True) == "0 KB"
    assert fmt.format_size(300, whole_kb=True) == "1 KB", "a small body is 1 KB, never 0 KB"
    assert fmt.format_size(2 * MB, whole_kb=True) == "2.048 KB", "Italian thousands separator"
    assert fmt.format_size(int(1.4 * MB), whole_kb=True) == "1.434 KB"
    assert fmt.format_size(int(1.4 * MB)) == "1,4 MB", "the same body, in the readable unit"


def test_the_registro_and_the_cards_share_one_size_formatter():
    """sync.log (written by the core) and the page (written by the UI) used to
    say "4.0 MB" and "4 MB" for the same file: one function now does both."""
    from qtrequestory.core.events import format_size as core_format_size

    for value in (0, 512, 2560, 41 * MB, int(80.4 * MB), int(1.5 * GB)):
        assert fmt.format_size(value) == core_format_size(value)
    assert fmt.message(FileDone("coll", "a.txt", int(80.4 * MB), Path("x"))) == (
        f"coll: scaricato a.txt ({fmt.format_size(int(80.4 * MB))})"
    )


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
    assert line == "coll: scaricato 20260918.txt (4 MB)"
    assert fmt.message(RemoteIndexRead("coll", 4, 1, 2, int(4.5 * MB))) == (
        "coll: elenco del server letto: 4 file giornalieri, 1 vuoti, 2 sciolti, 4,5 MB da scaricare"
    )
    assert fmt.message(EnvUnreachable("coll", "timeout")) == (
        "coll: endpoint non raggiungibile, riprovo al prossimo giro (timeout)"
    )
    assert fmt.message(EnvSkipped("coll", "fresh")) == (
        "coll: già sincronizzato dopo l'ultima compattazione, niente da fare"
    )
    assert fmt.message(LogMessage(logging.INFO, "ciao")) == "ciao"
    assert fmt.message(EnvFinished("coll", EnvResult("coll", "ok", downloaded=1, present=2))) == (
        "coll: 1 scaricati, 2 già presenti, 0 vuoti saltati, 0 errori (completato)"
    )
    assert fmt.message(FileFailed("coll", "a.txt", "troncato")) == "coll: ERRORE su a.txt: troncato"


def test_the_registro_has_no_english_status_words_and_a_decimal_comma():
    unreachable = EnvResult("svil", "unreachable", error="timeout")
    assert fmt.message(EnvFinished("svil", unreachable)).endswith("(non raggiungibile)")
    errors = EnvResult("coll", "errors", failed=2)
    assert fmt.message(EnvFinished("coll", errors)).endswith("(con errori)")
    assert fmt.message(IndexFinished(2, 0, 0.12)) == "indice: 2 file indicizzati, 0 rimossi in 0,1 s"


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
    assert line == "[2026-09-22 09:03:00] coll: scaricato a.txt (0 B)"
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

def test_the_task_status_line_says_active_schedule_next_and_last():
    from qtrequestory.ui.contracts import ScheduleSettings, TaskStatus

    task = TaskStatus(registered=True, command=Path("q.exe"), args="--sync", exe_matches=True,
                      state="Pronto", next_run="domani 09:00", last_run="oggi 11:24", last_result=0)
    line = fmt.format_task_status(task, ScheduleSettings())
    assert "Ogni giorno alle 09:00" in line  # the schedule, in words
    assert "domani 09:00" in line and "oggi 11:24" in line and "0" in line


def test_an_unregistered_task_says_only_that():
    from qtrequestory.ui.contracts import NOT_REGISTERED, ScheduleSettings

    assert fmt.format_task_status(NOT_REGISTERED, ScheduleSettings()) == strings.SYNC_AUTO_OFF_HINT


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
    assert strip.label == "20260716.txt (80,4 MB)", "the card already names the env"
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
    assert build_strip(model).label == strings.SYNC_PROGRESS_ENV


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


# ------------------------------------------------------------------ badges ---
#
# One function decides what an environment "is" right now; the card's badge
# and the app-bar chip both read it, so they cannot disagree.

from datetime import date, datetime  # noqa: E402

from qtrequestory.ui.contracts import CoverageDays, EnvStatus  # noqa: E402
from qtrequestory.ui.pages import sync_badge as sb  # noqa: E402


def _status(**kw) -> EnvStatus:
    base = dict(env="coll", last_success=datetime(2026, 9, 22, 11, 23), fresh=False,
                n_local_files=3, local_bytes=MB, latest_day=None, index_pending=0)
    return EnvStatus(**{**base, **kw})


@pytest.mark.parametrize(
    ("kw", "kind", "tone", "text"),
    [
        (dict(status=_status(fresh=True)), sb.FRESH, "ok", "aggiornato"),
        (dict(status=_status()), sb.STALE, "warn", strings.SYNC_BADGE_STALE),
        (dict(status=_status(last_success=None, n_local_files=0)), sb.NEVER, "neutral",
         "mai sincronizzato"),
        (dict(status=None), sb.NEVER, "neutral", "mai sincronizzato"),
        (dict(status=_status(fresh=True), running=True), sb.RUNNING, "neutral", "in corso"),
        (dict(status=_status(fresh=True), queued=True), sb.QUEUED, "neutral", "in attesa"),
        (dict(status=_status(fresh=True), missing=3), sb.MISSING, "warn", "3 giorni mancanti"),
        (dict(status=_status(fresh=True), missing=1), sb.MISSING, "warn", "1 giorno mancante"),
        (dict(status=_status(fresh=True), reachable=False), sb.UNREACHABLE, "warn",
         "non raggiungibile"),
        (dict(status=_status(fresh=True), failed=2), sb.ERRORS, "warn", "errori"),
    ],
)
def test_every_badge_has_one_readable_text_and_one_tone(kw, kind, tone, text):
    badge = sb.badge_for(**kw)
    assert (badge.kind, badge.tone, badge.text) == (kind, tone, text)


def test_what_is_happening_beats_what_happened():
    assert sb.badge_for(_status(), running=True, reachable=False, failed=2).kind == sb.RUNNING
    assert sb.badge_for(_status(), queued=True, reachable=False).kind == sb.QUEUED
    assert sb.badge_for(_status(), reachable=False, failed=2, missing=1).kind == sb.UNREACHABLE
    assert sb.badge_for(_status(), failed=2, missing=1).kind == sb.ERRORS
    assert sb.badge_for(_status(fresh=True), missing=1).kind == sb.MISSING, (
        "a lost day matters more than a fresh mirror")


def test_no_badge_is_ever_red():
    """An unreachable endpoint is the normal state outside the VPN."""
    for kw in (dict(reachable=False), dict(failed=5), dict(missing=9), {}):
        assert sb.badge_for(_status(), **kw).tone in ("ok", "warn", "neutral")


# --------------------------------------------------------- coverage strip ---

from qtrequestory.ui.pages import coverage_strip as cs  # noqa: E402

TODAY = date(2026, 9, 23)  # a Wednesday


def test_coverage_days_are_present_missing_weekend_today_or_before_the_archive():
    cov = CoverageDays(present=frozenset({date(2026, 9, 21), date(2026, 9, 19)}),
                       missing=(date(2026, 9, 22),), first_local=date(2026, 9, 18))
    kinds = cs.day_kinds(cov, TODAY, days=30)
    assert len(kinds) == 30
    assert kinds[-1] == (TODAY, cs.TODAY)
    assert dict(kinds)[date(2026, 9, 22)] == cs.MISSING
    assert dict(kinds)[date(2026, 9, 21)] == cs.PRESENT
    assert dict(kinds)[date(2026, 9, 20)] == cs.WEEKEND
    assert dict(kinds)[date(2026, 9, 19)] == cs.PRESENT, "a weekend file that exists is present"
    assert dict(kinds)[date(2026, 9, 17)] == cs.BEFORE, "nothing to miss before the archive began"
    assert kinds[0][0] == date(2026, 8, 25)


def test_each_square_explains_itself():
    assert cs.tooltip(date(2026, 9, 22), cs.MISSING) == "22/09/2026: mancante"
    assert cs.tooltip(date(2026, 9, 21), cs.PRESENT) == "21/09/2026: presente"
    assert cs.tooltip(date(2026, 9, 20), cs.WEEKEND) == "20/09/2026: weekend"
    assert cs.tooltip(TODAY, cs.TODAY) == "23/09/2026: oggi (arriva domani)"


# ------------------------------------------------------ missing-days banner ---

def test_the_missing_days_banner_names_the_env_the_dates_and_the_server_limit():
    text = fmt.missing_days_text({"svil": (date(2026, 9, 17),), "coll": ()})
    assert "svil" in text and "17/09/2026" in text and "coll" not in text
    assert "circa un giorno" in text
    many = fmt.missing_days_text({"svil": tuple(date(2026, 9, d) for d in (1, 2, 3, 4, 7, 8, 9))})
    assert "01/09/2026" in many and "7" in many
    assert fmt.missing_days_text({"svil": ()}) == ""


# ------------------------------------------------------------ run outcome ---

def test_completata_only_when_every_environment_is_fine():
    ok = fmt.run_outcome(0, {"coll": ("ok", 0), "svil": ("fresh", 0)})
    assert (ok.text, ok.tone) == ("Sincronizzazione completata", "ok")
    partial = fmt.run_outcome(0, {"coll": ("ok", 0), "svil": ("unreachable", 0)})
    assert (partial.text, partial.tone) == ("Completata · svil non raggiungibile", "warn")
    errors = fmt.run_outcome(1, {"coll": ("errors", 2), "svil": ("ok", 0)})
    assert errors.text == "Completata · coll con 2 errori" and errors.tone == "warn"
    assert fmt.run_outcome(3, {}).text == strings.SYNC_CANCELLED
    assert fmt.run_outcome(2, {"coll": ("unreachable", 0)}).text == strings.SYNC_DONE_UNREACHABLE


def test_the_log_header_says_when_and_how_the_last_run_ended():
    assert fmt.log_header(None, None) == "Registro dell'ultima esecuzione"
    assert fmt.log_header("11:24", "completata") == (
        "Registro dell'ultima esecuzione · 11:24 · completata")


def test_the_log_header_time_comes_from_the_last_sync_log_line():
    assert fmt.last_log_time(["[2026-09-22 09:03:00] coll: scaricato a.txt (1 MB)"],
                             now=datetime(2026, 9, 22, 12, 0)) == "oggi 09:03"
    assert fmt.last_log_time(["garbage"], now=datetime(2026, 9, 22, 12, 0)) is None
    assert fmt.last_log_time([], now=datetime(2026, 9, 22, 12, 0)) is None


# ----------------------------------------------------- automatic sync line ---

def test_the_auto_sync_line_is_schedule_next_and_last_without_the_title():
    from qtrequestory.ui.contracts import ScheduleSettings, TaskStatus

    task = TaskStatus(registered=True, command=Path("q.exe"), args="--sync", exe_matches=True,
                      state="Pronto", next_run="24/09/2026 09:00", last_run=None, last_result=None)
    line = fmt.format_task_status(task, ScheduleSettings())
    assert line.startswith("Ogni giorno alle 09:00")
    assert "24/09/2026 09:00" in line
    assert fmt.auto_title(task) == "Sincronizzazione automatica attiva"
    from qtrequestory.ui.contracts import NOT_REGISTERED
    assert fmt.auto_title(NOT_REGISTERED) == "Sincronizzazione automatica non attiva"
    assert fmt.auto_title(None) == "Sincronizzazione automatica"


def test_a_run_the_core_skipped_for_a_held_lock_is_not_completata():
    skipped = fmt.run_outcome(0, {}, skipped=True)
    assert (skipped.text, skipped.tone) == (strings.SYNC_LOCK_HELD, "neutral")
    assert skipped.log == strings.SYNC_LOG_SKIPPED
