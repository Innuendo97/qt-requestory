"""SyncEngine against the synthetic stub server (two envs, real UrllibHttpClient).

Nothing here is real: hostnames are the loopback stub, file bodies are byte
patterns. Every test drives the engine end to end and inspects the mirror on
disk, the recorded HTTP requests, the emitted events and the sync state.
"""
from __future__ import annotations

import dataclasses
import logging
from datetime import date, datetime
from pathlib import Path

import pytest

from qtrequestory.core import sync as syncmod
from qtrequestory.core.config import Config, Environment, SyncSettings, UnknownEnvironment, default_config
from qtrequestory.core.events import (
    CancelToken,
    CollectingSink,
    EnvFinished,
    EnvSkipped,
    EnvStarted,
    EnvUnreachable,
    Event,
    FileDone,
    FileFailed,
    FileProgress,
    FileSkipped,
    FileStarted,
    LogMessage,
    RemoteIndexRead,
    SyncFinished,
    SyncStarted,
)
from qtrequestory.core.http import UrllibHttpClient
from qtrequestory.core.state import SyncState
from qtrequestory.core.sync import EnvResult, SyncEngine, SyncReport

from .conftest import FakeClock, StubServer, autoindex_html

CHUNK = 1024
RETRIES = 1


def _payload(n: int) -> bytes:
    return bytes(range(256)) * (n // 256) + bytes(range(n % 256))


def _config(tmp_path: Path, stub_server: StubServer) -> Config:
    return dataclasses.replace(
        default_config(),
        mirror_root=tmp_path / "mirror",
        environments=[
            Environment("svil", stub_server.url + "/svil/"),
            Environment("coll", stub_server.url + "/coll/"),
        ],
        sync=SyncSettings(index_timeout_s=5, download_timeout_s=5, chunk_size=CHUNK, retries=RETRIES),
    )


def _serve_env(stub_server: StubServer, env: str, files: dict[str, bytes], loose: int = 0) -> None:
    """Publish an autoindex page plus one route per daily file under ``/<env>/``."""
    entries = [(name, "21-Sep-2026 18:30", len(body)) for name, body in files.items()]
    stub_server.add(f"/{env}/", autoindex_html(entries, loose=loose))
    for name, body in files.items():
        stub_server.add(f"/{env}/{name}", body)


@pytest.fixture
def cfg(tmp_path: Path, stub_server: StubServer) -> Config:
    return _config(tmp_path, stub_server)


@pytest.fixture
def state(cfg: Config) -> SyncState:
    return SyncState(cfg.state_path)


def _engine(cfg: Config, state: SyncState, sink, clock: FakeClock, cancel: CancelToken | None = None) -> SyncEngine:
    return SyncEngine(cfg, UrllibHttpClient(), state, sink, cancel=cancel, clock=clock)


def _local(cfg: Config, env: str, name: str) -> Path:
    return cfg.mirror_root / env / name[:4] / name[4:6] / name


def _requests_to(stub_server: StubServer, path: str) -> list[tuple[str, str]]:
    return [r for r in stub_server.requests if r[1] == path]


def _no_part_files(root: Path) -> bool:
    return not list(root.rglob("*.part")) if root.exists() else True


def _result(events: CollectingSink, env: str) -> EnvResult:
    return next(e.result for e in events.of(EnvFinished) if e.env == env)


# ------------------------------------------------------- 1. file decisions ---

def test_downloads_missing_files_newest_first_and_skips_empty_and_present(cfg, state, events, fake_clock, stub_server):
    bodies = {
        "20260921.txt": _payload(5_000),   # missing -> download
        "20260920.txt": b"",               # weekend -> empty
        "20260919.txt": _payload(3_000),   # present with same size -> skip
        "20260918.txt": _payload(4_000),   # present with wrong size -> re-download
        "20260917.txt": _payload(2_500),   # missing -> download
    }
    _serve_env(stub_server, "svil", bodies, loose=2)
    present = _local(cfg, "svil", "20260919.txt")
    present.parent.mkdir(parents=True)
    present.write_bytes(bodies["20260919.txt"])
    stale = _local(cfg, "svil", "20260918.txt")
    stale.write_bytes(b"old and short")

    report = _engine(cfg, state, events, fake_clock).run(["svil"])

    assert [e.name for e in events.of(FileDone)] == ["20260921.txt", "20260918.txt", "20260917.txt"]
    for name in ("20260921.txt", "20260918.txt", "20260917.txt"):
        assert _local(cfg, "svil", name).read_bytes() == bodies[name]
    assert present.read_bytes() == bodies["20260919.txt"]
    assert _no_part_files(cfg.mirror_root)
    assert {(e.name, e.reason) for e in events.of(FileSkipped)} == {("20260920.txt", "empty"), ("20260919.txt", "present")}
    assert ("GET", "/svil/20260919.txt") not in stub_server.requests
    assert ("GET", "/svil/20260920.txt") not in stub_server.requests

    idx = events.of(RemoteIndexRead)
    assert len(idx) == 1
    assert idx[0] == RemoteIndexRead("svil", n_daily=5, n_empty=1, n_loose=2,
                                     bytes_to_download=5_000 + 4_000 + 2_500, ts=idx[0].ts)
    assert events.events.index(idx[0]) < events.events.index(events.of(FileStarted)[0])

    result = _result(events, "svil")
    assert result == EnvResult("svil", "ok", downloaded=3, present=1, empty=1, failed=0, bytes=11_500, error=None)
    assert report.results == (result,)
    assert report.exit_code == 0


def test_run_defaults_to_enabled_envs_and_rejects_unknown_names(cfg, state, events, fake_clock, stub_server):
    _serve_env(stub_server, "svil", {"20260921.txt": _payload(100)})
    _serve_env(stub_server, "coll", {"20260921.txt": _payload(200)})
    cfg.environments[1] = dataclasses.replace(cfg.environments[1], enabled=False)

    report = _engine(cfg, state, events, fake_clock).run()

    assert [r.env for r in report.results] == ["svil"]
    assert events.of(SyncStarted)[0].envs == ("svil",)
    with pytest.raises(UnknownEnvironment) as exc_info:
        _engine(cfg, state, events, fake_clock).run(["prod"])
    assert str(exc_info.value) == "ambiente sconosciuto: 'prod' (configurati: coll, svil)"


# ------------------------------------------------------------- 1b. shrunk ---

def test_a_smaller_remote_never_overwrites_the_local_day(cfg, state, events, fake_clock, stub_server):
    """local 5000 bytes, server 1200 -> the local file must survive untouched,
    the smaller remote copy is stashed in a sidecar, and the day still counts
    as mirrored (the LARGER, local copy is what's kept)."""
    _serve_env(stub_server, "svil", {"20260921.txt": _payload(1_200)})
    local = _local(cfg, "svil", "20260921.txt")
    local.parent.mkdir(parents=True)
    local.write_bytes(_payload(5_000))

    report = _engine(cfg, state, events, fake_clock).run(["svil"])

    assert local.read_bytes() == _payload(5_000)
    sidecar = local.with_name("20260921.txt.remote-1200")
    assert sidecar.exists()
    assert sidecar.read_bytes() == _payload(1_200)
    assert _no_part_files(cfg.mirror_root)

    assert {(e.name, e.reason) for e in events.of(FileSkipped)} == {("20260921.txt", "shrunk")}
    warnings = [e for e in events.of(LogMessage) if e.level == logging.WARNING]
    assert len(warnings) == 1
    assert warnings[0].text == (
        "svil: 20260921.txt sul server è più piccolo della copia locale "
        "(5000 contro 1200): tenuta la copia locale, quella remota salvata come "
        "20260921.txt.remote-1200"
    )
    assert not events.of(FileStarted) and not events.of(FileDone) and not events.of(FileFailed)

    result = _result(events, "svil")
    assert result.status == "ok"
    assert report.exit_code == 0
    st = SyncState(cfg.state_path).load().get("svil")
    assert st.newest_day == date(2026, 9, 21)


def test_a_smaller_remote_is_not_redownloaded_once_the_sidecar_matches(cfg, state, events, fake_clock, stub_server):
    _serve_env(stub_server, "svil", {"20260921.txt": _payload(1_200)})
    local = _local(cfg, "svil", "20260921.txt")
    local.parent.mkdir(parents=True)
    local.write_bytes(_payload(5_000))
    sidecar = local.with_name("20260921.txt.remote-1200")
    sidecar.write_bytes(_payload(1_200))

    _engine(cfg, state, events, fake_clock).run(["svil"])

    assert ("GET", "/svil/20260921.txt") not in stub_server.requests
    assert sidecar.read_bytes() == _payload(1_200)
    assert {(e.name, e.reason) for e in events.of(FileSkipped)} == {("20260921.txt", "shrunk")}
    # F5: the WARNING is emitted once, when the sidecar is created, not on every run.
    assert not [e for e in events.of(LogMessage) if e.level >= logging.WARNING]


def test_a_smaller_remote_whose_sidecar_fails_to_save_says_so_not_that_it_saved(
    cfg, state, events, fake_clock, stub_server,
):
    """The sidecar fetch is best-effort: when it fails, the local day must
    still stay untouched and be reported "shrunk", but the warning must NOT
    claim "quella remota salvata come ..." for a sidecar that never landed on
    disk — that would contradict a second, honest failure warning (the bug
    this test guards against)."""
    _serve_env(stub_server, "svil", {"20260921.txt": _payload(1_200)})
    stub_server.routes["/svil/20260921.txt"].status = 500
    local = _local(cfg, "svil", "20260921.txt")
    local.parent.mkdir(parents=True)
    local.write_bytes(_payload(5_000))

    report = _engine(cfg, state, events, fake_clock).run(["svil"])

    assert local.read_bytes() == _payload(5_000)
    sidecar = local.with_name("20260921.txt.remote-1200")
    assert not sidecar.exists()
    assert _no_part_files(cfg.mirror_root)
    assert len(_requests_to(stub_server, "/svil/20260921.txt")) == 1

    assert {(e.name, e.reason) for e in events.of(FileSkipped)} == {("20260921.txt", "shrunk")}
    warnings = [e for e in events.of(LogMessage) if e.level == logging.WARNING]
    assert len(warnings) == 1
    text = warnings[0].text
    assert "salvata come" not in text
    assert "impossibile salvare la copia remota" in text
    assert text.startswith(
        "svil: 20260921.txt sul server è più piccolo della copia locale "
        "(5000 contro 1200): tenuta la copia locale, "
    )

    result = _result(events, "svil")
    assert result.status == "ok"
    assert report.exit_code == 0
    st = SyncState(cfg.state_path).load().get("svil")
    assert st.newest_day == date(2026, 9, 21)


# --------------------------------------------------------------- 2. state ---

def test_state_marked_with_clock_after_success(cfg, state, events, fake_clock, stub_server):
    _serve_env(stub_server, "coll", {"20260921.txt": _payload(2_000), "20260920.txt": b""})

    report = _engine(cfg, state, events, fake_clock).run(["coll"])

    assert report.exit_code == 0
    st = SyncState(cfg.state_path).load().get("coll")
    assert st.last_success == fake_clock.now
    assert st.last_remote_daily == 2
    assert st.last_downloaded == 1
    assert st.newest_day == date(2026, 9, 21)
    assert SyncState(cfg.state_path).load().get("svil").last_success is None


def test_last_success_is_the_listing_time_not_a_later_one_and_confirms_the_newest_day(
    cfg, state, events, stub_server,
):
    """C1: the listing is read at 18:29 (only 20260921 on the server), and the
    run only finishes at 18:31 (downloads take "wall clock" time). The stored
    ``last_success`` must be the listing time, not the later one, and
    ``newest_day`` must be the newest day the listing actually showed. The
    next morning, before the 22nd was ever seen in a listing, the env must
    NOT be considered fresh even though ``last_success`` is after that day's
    compaction moment — this is exactly the bug: a day the server never
    listed for us was still treated as if it had been checked.
    """
    _serve_env(stub_server, "coll", {"20260921.txt": _payload(1_000)})
    clock = FakeClock(datetime(2026, 9, 22, 18, 29))

    def advancing_sink(ev) -> None:
        events(ev)
        if isinstance(ev, RemoteIndexRead):
            clock.advance(minutes=2)  # downloads happen after the listing was read

    report = _engine(cfg, state, advancing_sink, clock).run(["coll"])

    assert report.exit_code == 0
    st = SyncState(cfg.state_path).load().get("coll")
    assert st.last_success == datetime(2026, 9, 22, 18, 29)  # listing time, not 18:31
    assert st.newest_day == date(2026, 9, 21)

    reloaded = SyncState(cfg.state_path).load()
    assert not reloaded.is_fresh("coll", datetime(2026, 9, 23, 9, 0), cfg.compaction_time)


# ---------------------------------------------------- 2b. state save fails ---

def test_a_state_save_failure_does_not_stop_the_next_env(cfg, state, events, fake_clock, stub_server, monkeypatch):
    """WinError 5 on ``sync-state.json`` (AV, read-only attribute, a reader with
    it open) must not raise out of ``engine.run``: the files are already safe
    on disk, only the bookkeeping failed, and the *next* env must still run."""
    _serve_env(stub_server, "svil", {"20260921.txt": _payload(500)})
    _serve_env(stub_server, "coll", {"20260921.txt": _payload(700)})

    def _boom(self) -> None:
        raise PermissionError("sync-state.json is locked")

    monkeypatch.setattr(SyncState, "_save", _boom)

    report = _engine(cfg, state, events, fake_clock).run(["svil", "coll"])

    finished = events.of(EnvFinished)
    assert [e.env for e in finished] == ["svil", "coll"]
    assert all(e.result.status == "ok" for e in finished)
    warnings = [e for e in events.of(LogMessage) if e.level == logging.WARNING]
    assert any("sync-state.json" in w.text for w in warnings)
    assert report.exit_code == 0
    assert _local(cfg, "svil", "20260921.txt").exists()
    assert _local(cfg, "coll", "20260921.txt").exists()


# --------------------------------------------------------------- 3. fresh ---

def test_fresh_env_makes_no_requests_unless_forced(cfg, state, events, fake_clock, stub_server):
    _serve_env(stub_server, "svil", {"20260921.txt": _payload(1_000)})
    # synced yesterday after the 18:30 compaction, and that compacted day was mirrored;
    # the clock says 09:30 today
    state.mark_success("svil", datetime(2026, 9, 21, 19, 0), newest_day=date(2026, 9, 21))

    report = _engine(cfg, state, events, fake_clock).run(["svil"])

    assert stub_server.requests == []
    assert events.of(EnvSkipped) and events.of(EnvSkipped)[0] == EnvSkipped("svil", "fresh", ts=events.of(EnvSkipped)[0].ts)
    assert report.results[0].status == "fresh"
    assert report.exit_code == 0

    report = _engine(cfg, state, events, fake_clock).run(["svil"], force=True)

    assert ("GET", "/svil/") in stub_server.requests
    assert report.results[0].status == "ok"
    assert report.results[0].downloaded == 1


# --------------------------------------------------------- 4. unreachable ---

def test_unreachable_env_does_not_stop_the_next_one(cfg, state, events, fake_clock, stub_server):
    # no /svil/ route -> 404 on the index; coll is fine. Order: unreachable first.
    _serve_env(stub_server, "coll", {"20260921.txt": _payload(1_500)})

    report = _engine(cfg, state, events, fake_clock).run(["svil", "coll"])

    assert report.exit_code == 0
    assert [r.status for r in report.results] == ["unreachable", "ok"]
    assert events.of(EnvUnreachable)[0].env == "svil"
    assert report.results[0].error
    assert not (cfg.mirror_root / "svil").exists()
    assert _local(cfg, "coll", "20260921.txt").exists()
    assert SyncState(cfg.state_path).load().get("svil").last_success is None
    assert SyncState(cfg.state_path).load().get("coll").last_success == fake_clock.now


def test_all_unreachable_is_exit_2(cfg, state, events, fake_clock, stub_server):
    report = _engine(cfg, state, events, fake_clock).run(["svil", "coll"])

    assert [r.status for r in report.results] == ["unreachable", "unreachable"]
    assert report.exit_code == 2
    assert not cfg.state_path.exists()


# ----------------------------------------------------------- 5. truncated ---

def test_truncated_download_is_retried_then_fails_file_but_not_the_rest(cfg, state, events, fake_clock, stub_server):
    _serve_env(stub_server, "coll", {"20260921.txt": _payload(10_000), "20260920.txt": _payload(3_000)})
    stub_server.routes["/coll/20260921.txt"].truncate_after = 4_000

    report = _engine(cfg, state, events, fake_clock).run(["coll"])

    assert len(_requests_to(stub_server, "/coll/20260921.txt")) == RETRIES + 1
    failed = events.of(FileFailed)
    assert len(failed) == 1
    assert failed[0].name == "20260921.txt"
    assert failed[0].error == "troncato: 4000 di 10000 byte"
    assert not _local(cfg, "coll", "20260921.txt").exists()
    assert _no_part_files(cfg.mirror_root)
    assert _local(cfg, "coll", "20260920.txt").read_bytes() == _payload(3_000)
    result = _result(events, "coll")
    assert result.status == "errors"
    assert result.failed == 1 and result.downloaded == 1
    assert report.exit_code == 1
    # The listing is remembered (U1.3), the run is not a success.
    assert all(s.last_success is None for s in (SyncState(cfg.state_path).load().get(e) for e in ("svil", "coll")))


def test_truncated_once_then_complete_succeeds_on_retry(cfg, state, events, fake_clock, stub_server):
    _serve_env(stub_server, "coll", {"20260921.txt": _payload(10_000)})
    stub_server.routes["/coll/20260921.txt"].truncate_after = 4_000
    stub_server.routes["/coll/20260921.txt"].truncate_once = True

    report = _engine(cfg, state, events, fake_clock).run(["coll"])

    assert len(_requests_to(stub_server, "/coll/20260921.txt")) == 2
    assert not events.of(FileFailed)
    assert [e.name for e in events.of(FileDone)] == ["20260921.txt"]
    assert _local(cfg, "coll", "20260921.txt").read_bytes() == _payload(10_000)
    assert _no_part_files(cfg.mirror_root)
    warnings = [e for e in events.of(LogMessage) if e.level == logging.WARNING]
    assert len(warnings) == 1 and "troncato" in warnings[0].text
    assert report.exit_code == 0
    assert SyncState(cfg.state_path).load().get("coll").last_success == fake_clock.now


def test_oversized_download_is_reported_as_unexpected_size(cfg, state, events, fake_clock, stub_server):
    _serve_env(stub_server, "coll", {"20260921.txt": _payload(2_000)})
    # the index promised 2000 bytes but the server now sends more
    stub_server.routes["/coll/20260921.txt"].body = _payload(2_500)

    _engine(cfg, state, events, fake_clock).run(["coll"])

    assert events.of(FileFailed)[0].error == "dimensione inattesa: 2500 di 2000 byte"
    assert not _local(cfg, "coll", "20260921.txt").exists()
    assert _no_part_files(cfg.mirror_root)


# --------------------------------------------------------- 5b. rename fails ---

def test_an_os_replace_failure_keeps_the_old_file_and_reports(cfg, state, events, fake_clock, stub_server, monkeypatch):
    """The GUI indexer / a preview pane holding the destination open makes
    ``replace_with_retry`` fail for good: the transfer must not clobber
    anything, the old (stale) local file stays exactly as it was, no ``.part``
    is left behind, and the file counts as a failure — the missing BACKLOG test."""
    _serve_env(stub_server, "coll", {"20260921.txt": _payload(1_000)})
    old = _local(cfg, "coll", "20260921.txt")
    old.parent.mkdir(parents=True)
    old.write_bytes(b"old-and-stale")  # wrong size -> planned as "download"

    def _always_locked(src, dst):
        raise PermissionError("locked by AV")

    monkeypatch.setattr(syncmod, "replace_with_retry", _always_locked)

    report = _engine(cfg, state, events, fake_clock).run(["coll"])

    assert old.read_bytes() == b"old-and-stale"
    failed = events.of(FileFailed)
    assert len(failed) == 1
    assert failed[0].name == "20260921.txt"
    assert _no_part_files(cfg.mirror_root)
    result = _result(events, "coll")
    assert result.status == "errors"
    assert report.exit_code == 1
    # The listing is remembered (U1.3), the run is not a success.
    assert all(s.last_success is None for s in (SyncState(cfg.state_path).load().get(e) for e in ("svil", "coll")))


# ----------------------------------------------------- 4b. not an index ---

def test_page_without_daily_files_is_unreachable_not_fresh(cfg, state, events, fake_clock, stub_server):
    stub_server.add("/svil/", "<html>captive portal</html>")

    report = _engine(cfg, state, events, fake_clock).run(["svil"])

    assert report.results[0].status == "unreachable"
    assert report.exit_code == 2
    warnings = [e for e in events.of(LogMessage) if e.level == logging.WARNING]
    assert warnings and warnings[0].text == (
        "svil: l'index non contiene file giornalieri, probabile pagina di login/proxy — stato non aggiornato"
    )
    assert not cfg.state_path.exists()
    assert not events.of(RemoteIndexRead)


# --------------------------------------------------- 4c. abbreviated sizes ---

def test_abbreviated_autoindex_sizes_fail_the_env_without_downloading(cfg, state, events, fake_clock, stub_server):
    """``autoindex_exact_size off`` on the server: sizes show as "98K" instead
    of exact bytes. Every plan/download decision compares against that size,
    so this must stop the env with status "errors" and download nothing,
    rather than silently misreading "98K" as 98 bytes."""
    stub_server.add("/svil/", autoindex_html([("20260921.txt", "21-Sep-2026 18:30", "98K")]))

    report = _engine(cfg, state, events, fake_clock).run(["svil"])

    result = _result(events, "svil")
    assert result.status == "errors"
    assert (result.downloaded, result.present, result.empty, result.failed) == (0, 0, 0, 0)
    assert report.exit_code == 1
    errors = [e for e in events.of(LogMessage) if e.level == logging.ERROR]
    assert errors and errors[0].text == f"svil: {syncmod.ABBREVIATED_SIZES_TEXT}"
    assert not cfg.state_path.exists()
    assert not events.of(RemoteIndexRead)
    assert not (cfg.mirror_root / "svil").exists()


def test_abbreviated_sizes_in_one_env_do_not_stop_the_other(cfg, state, events, fake_clock, stub_server):
    stub_server.add("/svil/", autoindex_html([("20260921.txt", "21-Sep-2026 18:30", "98K")]))
    _serve_env(stub_server, "coll", {"20260921.txt": _payload(1_500)})

    report = _engine(cfg, state, events, fake_clock).run(["svil", "coll"])

    assert [r.status for r in report.results] == ["errors", "ok"]
    assert report.exit_code == 1
    assert _local(cfg, "coll", "20260921.txt").exists()


# -------------------------------------------------------------- 6. retry ---

def test_server_error_is_retried_then_failed(cfg, state, events, fake_clock, stub_server):
    _serve_env(stub_server, "svil", {"20260921.txt": _payload(1_000), "20260920.txt": _payload(500)})
    stub_server.routes["/svil/20260921.txt"].status = 500

    report = _engine(cfg, state, events, fake_clock).run(["svil"])

    assert len(_requests_to(stub_server, "/svil/20260921.txt")) == RETRIES + 1
    assert len(_requests_to(stub_server, "/svil/20260920.txt")) == 1
    assert [e.name for e in events.of(FileFailed)] == ["20260921.txt"]
    assert "500" in events.of(FileFailed)[0].error
    warnings = [e for e in events.of(LogMessage) if e.level == logging.WARNING]
    assert len(warnings) == RETRIES
    assert _no_part_files(cfg.mirror_root)
    assert report.exit_code == 1


def test_retries_zero_means_a_single_attempt(cfg, state, events, fake_clock, stub_server):
    cfg.sync.retries = 0
    _serve_env(stub_server, "svil", {"20260921.txt": _payload(1_000)})
    stub_server.routes["/svil/20260921.txt"].status = 500

    _engine(cfg, state, events, fake_clock).run(["svil"])

    assert len(_requests_to(stub_server, "/svil/20260921.txt")) == 1
    assert len(events.of(FileFailed)) == 1


# ------------------------------------------------------------ 7. dry run ---

def test_dry_run_downloads_nothing_and_counts_candidates(cfg, state, events, fake_clock, stub_server):
    _serve_env(stub_server, "coll", {"20260921.txt": _payload(2_000), "20260920.txt": b"", "20260919.txt": _payload(1_000)})
    present = _local(cfg, "coll", "20260919.txt")
    present.parent.mkdir(parents=True)
    present.write_bytes(_payload(1_000))

    report = _engine(cfg, state, events, fake_clock).run(["coll"], dry_run=True)

    assert stub_server.requests == [("GET", "/coll/")]
    assert not _local(cfg, "coll", "20260921.txt").exists()
    assert not cfg.state_path.exists()
    assert events.of(SyncStarted)[0].dry_run is True
    assert events.of(RemoteIndexRead)[0].bytes_to_download == 2_000
    assert not events.of(FileStarted) and not events.of(FileDone)
    # Minor P1: a dry run must still say what it would have downloaded, since
    # LoggingSink drops FileSkipped (sync.log only gets the "anteprima"
    # summary lines) — this is the CLI's only source for the file listing.
    assert {(e.name, e.reason, e.size) for e in events.of(FileSkipped)} == {
        ("20260921.txt", "dry-run", 2_000),
        ("20260920.txt", "empty", 0),
        ("20260919.txt", "present", 0),
    }
    result = _result(events, "coll")
    assert result == EnvResult("coll", "ok", downloaded=1, present=1, empty=1, failed=0, bytes=2_000, error=None)
    assert report.exit_code == 0


# ------------------------------------------------------------- 8. cancel ---

def test_cancel_during_download_removes_part_and_stops(cfg, state, events, fake_clock, stub_server):
    _serve_env(stub_server, "svil", {"20260921.txt": _payload(50_000), "20260920.txt": _payload(1_000)})
    _serve_env(stub_server, "coll", {"20260921.txt": _payload(1_000)})
    cancel = CancelToken()

    def cancelling_sink(ev: Event) -> None:
        events(ev)
        if isinstance(ev, FileProgress):
            cancel.cancel()

    report = _engine(cfg, state, cancelling_sink, fake_clock, cancel=cancel).run(["svil", "coll"])

    assert report.exit_code == 3
    assert [r.status for r in report.results] == ["cancelled", "cancelled"]
    assert _no_part_files(cfg.mirror_root)
    assert not _local(cfg, "svil", "20260921.txt").exists()
    assert not _local(cfg, "svil", "20260920.txt").exists()
    assert ("GET", "/svil/20260920.txt") not in stub_server.requests
    assert not [r for r in stub_server.requests if r[1].startswith("/coll/")]
    assert not events.of(FileDone)
    # The listing is remembered (U1.3), the run is not a success.
    assert all(s.last_success is None for s in (SyncState(cfg.state_path).load().get(e) for e in ("svil", "coll")))
    # every env announced in SyncStarted is started and finished, even after the cancel
    assert [e.env for e in events.of(EnvStarted)] == ["svil", "coll"]
    assert [e.env for e in events.of(EnvFinished)] == ["svil", "coll"]
    assert isinstance(events.events[-1], SyncFinished)


def test_cancel_requested_before_an_env_starts_touches_no_network(cfg, state, events, fake_clock, stub_server):
    _serve_env(stub_server, "svil", {"20260921.txt": _payload(1_000)})
    cancel = CancelToken()
    cancel.cancel()

    report = _engine(cfg, state, events, fake_clock, cancel=cancel).run(["svil"])

    assert stub_server.requests == []
    assert report.exit_code == 3
    assert report.results[0].status == "cancelled"


# ---------------------------------------------------- 9. event sequence ---

def test_happy_run_event_sequence(cfg, state, events, fake_clock, stub_server):
    _serve_env(stub_server, "svil", {"20260921.txt": _payload(CHUNK * 5 + 10)})

    report = _engine(cfg, state, events, fake_clock).run(["svil"])

    kinds = [type(e) for e in events.events]
    progress = events.of(FileProgress)
    assert progress
    assert kinds[:4] == [SyncStarted, EnvStarted, RemoteIndexRead, FileStarted]
    assert kinds[4:4 + len(progress)] == [FileProgress] * len(progress)
    assert kinds[4 + len(progress):] == [FileDone, EnvFinished, SyncFinished]
    dones = [p.done for p in progress]
    assert dones == sorted(dones)
    assert dones[-1] == CHUNK * 5 + 10
    assert all(p.size == CHUNK * 5 + 10 for p in progress)
    assert events.of(SyncFinished)[0].report is report
    assert events.of(SyncStarted)[0].envs == ("svil",)


def test_file_progress_is_throttled_but_final_always_emitted(cfg, state, events, fake_clock, stub_server, monkeypatch):
    n_chunks = 40
    _serve_env(stub_server, "svil", {"20260921.txt": _payload(CHUNK * n_chunks)})
    ticks = iter(i * 0.01 for i in range(10_000))   # 10 ms per call: ~1 emit every 10 chunks
    monkeypatch.setattr(syncmod, "_monotonic", lambda: next(ticks))

    _engine(cfg, state, events, fake_clock).run(["svil"])

    progress = events.of(FileProgress)
    assert 2 <= len(progress) < n_chunks
    assert progress[-1].done == CHUNK * n_chunks


# ------------------------------------------------------- 10. exit codes ---

def _r(env: str, status: str) -> EnvResult:
    return EnvResult(env, status, 0, 0, 0, 0, 0, None)  # type: ignore[arg-type]


@pytest.mark.parametrize("statuses, code", [
    ([], 0),
    (["ok"], 0),
    (["fresh"], 0),
    (["ok", "fresh"], 0),
    (["ok", "unreachable"], 0),
    (["fresh", "unreachable"], 0),
    (["unreachable"], 2),
    (["unreachable", "unreachable"], 2),
    (["errors"], 1),
    (["errors", "ok"], 1),
    (["errors", "unreachable"], 1),
    (["cancelled"], 3),
    (["cancelled", "errors"], 3),
    (["cancelled", "unreachable"], 3),
    (["ok", "cancelled"], 3),
])
def test_exit_code_table(statuses, code):
    t = datetime(2026, 9, 22, 9, 30)
    report = SyncReport(tuple(_r(f"e{i}", s) for i, s in enumerate(statuses)), t, t)
    assert report.exit_code == code


def test_results_are_frozen():
    r = _r("svil", "ok")
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.status = "errors"  # type: ignore[misc]


def test_summary_line_mentions_every_env_and_exit_code():
    t0 = datetime(2026, 9, 22, 9, 30, 0)
    t1 = datetime(2026, 9, 22, 9, 30, 12)
    report = SyncReport((
        EnvResult("svil", "ok", 2, 3, 1, 0, 4_000_000, None),
        EnvResult("coll", "unreachable", 0, 0, 0, 0, 0, "boom"),
    ), t0, t1)
    line = report.summary_line()
    assert "\n" not in line
    assert "svil" in line and "coll" in line
    assert "2 scaricati" in line
    assert "codice di uscita 0" in line
    assert "exit" not in line, "the registro is Italian"
    assert "svil completato" in line
    assert "12" in line  # seconds


# ------------------------------------------- 9. empty days and freshness ---
#
# The server keeps every daily file until a manual purge, and publishes a day
# without traffic as a 0-byte file. Once that day is compacted the 0-byte file
# IS the day ("no traffic"), so it is mirrored as a 0-byte local file and it
# confirms freshness like any other day (F1/F3). Before its compaction (today)
# the same 0-byte file only means "not compacted yet" and is left alone.

def test_a_compacted_0_byte_day_is_mirrored_as_an_empty_file_and_confirms_it(
    cfg, state, events, fake_clock, stub_server,
):
    _serve_env(stub_server, "svil", {"20260921.txt": b"", "20260920.txt": _payload(1_000)})

    report = _engine(cfg, state, events, fake_clock).run(["svil"])

    local = _local(cfg, "svil", "20260921.txt")
    assert local.is_file() and local.stat().st_size == 0
    assert ("GET", "/svil/20260921.txt") not in stub_server.requests
    assert report.results[0] == EnvResult("svil", "ok", downloaded=1, present=0, empty=1, failed=0,
                                          bytes=1_000, error=None)
    st = SyncState(cfg.state_path).load()
    assert st.get("svil").newest_day == date(2026, 9, 21)
    assert st.is_fresh("svil", fake_clock.now, cfg.compaction_time)

    before = len(stub_server.requests)
    report = _engine(cfg, st, events, fake_clock).run(["svil"])
    assert report.results[0].status == "fresh"
    assert len(stub_server.requests) == before


def test_todays_0_byte_file_before_compaction_is_not_written(cfg, state, events, fake_clock, stub_server):
    # fake_clock: 2026-09-22 09:30, before today's 18:30 compaction
    _serve_env(stub_server, "svil", {"20260922.txt": b"", "20260921.txt": _payload(700)})

    _engine(cfg, state, events, fake_clock).run(["svil"])

    assert not _local(cfg, "svil", "20260922.txt").exists()
    assert SyncState(cfg.state_path).load().get("svil").newest_day == date(2026, 9, 21)


def test_a_0_byte_day_listed_the_same_evening_is_left_for_the_next_day(cfg, state, events, stub_server):
    """Review fix 1: a late compaction can leave D.txt at 0 bytes after
    compaction_time on D. Writing it then (and confirming D) would make the
    env fresh and skip the whole of D+1, when the real D arrives."""
    _serve_env(stub_server, "svil", {"20260922.txt": b"", "20260921.txt": _payload(700)})
    clock = FakeClock(datetime(2026, 9, 22, 18, 31))

    _engine(cfg, state, events, clock).run(["svil"])

    assert not _local(cfg, "svil", "20260922.txt").exists()
    st = SyncState(cfg.state_path).load()
    assert st.get("svil").newest_day == date(2026, 9, 21)
    assert not st.is_fresh("svil", clock.now, cfg.compaction_time)


def test_a_0_byte_day_is_written_when_listed_on_a_later_day(cfg, state, events, stub_server):
    _serve_env(stub_server, "svil", {"20260922.txt": b"", "20260921.txt": _payload(700)})
    clock = FakeClock(datetime(2026, 9, 23, 0, 5))

    _engine(cfg, state, events, clock).run(["svil"])

    assert _local(cfg, "svil", "20260922.txt").stat().st_size == 0
    assert SyncState(cfg.state_path).load().get("svil").newest_day == date(2026, 9, 22)


def test_a_0_byte_listing_never_overwrites_a_local_file(cfg, state, events, fake_clock, stub_server):
    _serve_env(stub_server, "svil", {"20260921.txt": b"", "20260920.txt": b""})
    full = _local(cfg, "svil", "20260921.txt")
    full.parent.mkdir(parents=True)
    full.write_bytes(_payload(900))
    empty = _local(cfg, "svil", "20260920.txt")
    empty.write_bytes(b"")
    mtime = empty.stat().st_mtime_ns

    report = _engine(cfg, state, events, fake_clock).run(["svil"])

    assert full.read_bytes() == _payload(900)
    assert empty.stat().st_mtime_ns == mtime
    assert report.results[0].status == "ok"
    assert SyncState(cfg.state_path).load().get("svil").newest_day == date(2026, 9, 21)


def test_a_dry_run_writes_no_empty_day(cfg, state, events, fake_clock, stub_server):
    _serve_env(stub_server, "svil", {"20260921.txt": b""})

    _engine(cfg, state, events, fake_clock).run(["svil"], dry_run=True)

    assert not _local(cfg, "svil", "20260921.txt").exists()


def test_a_day_listed_non_empty_later_replaces_the_0_byte_local_file(cfg, state, events, fake_clock, stub_server):
    empty = _local(cfg, "svil", "20260921.txt")
    empty.parent.mkdir(parents=True)
    empty.write_bytes(b"")
    _serve_env(stub_server, "svil", {"20260921.txt": _payload(1_300)})

    report = _engine(cfg, state, events, fake_clock).run(["svil"])

    assert report.results[0].downloaded == 1
    assert empty.read_bytes() == _payload(1_300)


def test_a_listing_of_only_empty_days_confirms_the_compacted_day(cfg, state, events, fake_clock, stub_server):
    _serve_env(stub_server, "svil", {"20260921.txt": b"", "20260920.txt": b""})

    _engine(cfg, state, events, fake_clock).run(["svil"])

    st = SyncState(cfg.state_path).load()
    assert st.get("svil").newest_day == date(2026, 9, 21)
    assert st.is_fresh("svil", fake_clock.now, cfg.compaction_time)


def test_a_quiet_weekend_is_fresh_without_waiting_for_monday(cfg, state, events, stub_server):
    """F3: Saturday and Sunday are 0-byte; once Sunday is compacted the env is
    fresh, so it is not listed again every hour until Monday's traffic."""
    _serve_env(stub_server, "svil", {"20260920.txt": b"", "20260919.txt": _payload(800)})
    clock = FakeClock(datetime(2026, 9, 21, 9, 0))  # compacted day: 2026-09-20 (empty)
    _engine(cfg, state, events, clock).run(["svil"])
    assert SyncState(cfg.state_path).load().is_fresh("svil", clock.now, cfg.compaction_time)

    _serve_env(stub_server, "svil", {"20260921.txt": _payload(900), "20260920.txt": b"",
                                     "20260919.txt": _payload(800)})
    clock.now = datetime(2026, 9, 21, 19, 0)  # after Monday's compaction
    report = _engine(cfg, SyncState(cfg.state_path).load(), events, clock).run(["svil"])

    assert report.results[0].downloaded == 1
    reloaded = SyncState(cfg.state_path).load()
    assert reloaded.get("svil").newest_day == date(2026, 9, 21)
    assert reloaded.is_fresh("svil", clock.now, cfg.compaction_time)


def test_an_empty_day_that_cannot_be_written_is_a_warning_and_confirms_nothing(
    cfg, state, events, fake_clock, stub_server, monkeypatch,
):
    _serve_env(stub_server, "svil", {"20260921.txt": b""})

    def _deny(*_a, **_kw):
        raise PermissionError("denied")

    monkeypatch.setattr(syncmod, "_create_empty", _deny)

    report = _engine(cfg, state, events, fake_clock).run(["svil"])

    assert report.results[0].status == "ok"
    warnings = [e.text for e in events.of(LogMessage) if e.level == logging.WARNING]
    assert any("20260921.txt" in w for w in warnings)
    assert SyncState(cfg.state_path).load().get("svil").newest_day is None


# ----------------------------------------------------- 9b. listing memory ---

def test_the_listing_is_remembered_in_the_state(cfg, state, events, fake_clock, stub_server):
    _serve_env(stub_server, "svil", {"20260921.txt": _payload(10), "20260920.txt": b"",
                                     "20260918.txt": _payload(20)})

    _engine(cfg, state, events, fake_clock).run(["svil"])

    st = SyncState(cfg.state_path).load().get("svil")
    assert st.oldest_listed == date(2026, 9, 18)
    assert st.listed_nonempty == (date(2026, 9, 18), date(2026, 9, 21))
    assert st.seen_nonempty == (date(2026, 9, 18), date(2026, 9, 21))


def test_the_listing_is_remembered_even_when_a_download_fails(cfg, state, events, fake_clock, stub_server):
    """A failed day is exactly what must show up as "da scaricare"."""
    _serve_env(stub_server, "svil", {"20260921.txt": _payload(10)})
    stub_server.routes["/svil/20260921.txt"].status = 500

    report = _engine(cfg, state, events, fake_clock).run(["svil"])

    assert report.results[0].status == "errors"
    st = SyncState(cfg.state_path).load().get("svil")
    assert st.last_success is None
    assert st.listed_nonempty == (date(2026, 9, 21),)


def test_a_dry_run_remembers_nothing(cfg, state, events, fake_clock, stub_server):
    _serve_env(stub_server, "svil", {"20260921.txt": _payload(10)})

    _engine(cfg, state, events, fake_clock).run(["svil"], dry_run=True)

    assert not cfg.state_path.exists()


# ------------------------------------------------ 9c. CRLF-converted copy ---

LF_BODY = b'### 00000000-0000-4000-8000-000000000001_MOD_TEST_A_0123456789abcdef.json\n{"a": 1}\n' * 40


def test_a_local_copy_with_crlf_line_endings_is_present_not_shrunk(cfg, state, events, fake_clock, stub_server):
    """F5: an imported day whose line endings were converted is the same day."""
    _serve_env(stub_server, "svil", {"20260921.txt": LF_BODY})
    local = _local(cfg, "svil", "20260921.txt")
    local.parent.mkdir(parents=True)
    crlf = LF_BODY.replace(b"\n", b"\r\n")
    local.write_bytes(crlf)

    report = _engine(cfg, state, events, fake_clock).run(["svil"])

    assert local.read_bytes() == crlf
    assert list(local.parent.iterdir()) == [local], "no sidecar"
    assert ("GET", "/svil/20260921.txt") not in stub_server.requests
    assert {(e.name, e.reason) for e in events.of(FileSkipped)} == {("20260921.txt", "present")}
    logs = events.of(LogMessage)
    assert [e.level for e in logs] == [logging.INFO]
    assert "20260921.txt" in logs[0].text
    assert report.results[0].present == 1
    assert SyncState(cfg.state_path).load().get("svil").newest_day == date(2026, 9, 21)


def test_crlf_plus_extra_bytes_is_shrunk_never_present(cfg, state, events, fake_clock, stub_server):
    """Review fix 3: the CRLF count must explain the WHOLE difference."""
    _serve_env(stub_server, "svil", {"20260921.txt": LF_BODY})
    local = _local(cfg, "svil", "20260921.txt")
    local.parent.mkdir(parents=True)
    local.write_bytes(LF_BODY.replace(b"\n", b"\r\n") + b"extra")

    _engine(cfg, state, events, fake_clock).run(["svil"])

    assert {(e.name, e.reason) for e in events.of(FileSkipped)} == {("20260921.txt", "shrunk")}
    assert local.with_name(f"20260921.txt.remote-{len(LF_BODY)}").exists()
    assert not [e for e in events.of(LogMessage) if e.level == logging.INFO]


def test_crlf_that_does_not_account_for_the_difference_is_still_shrunk(cfg, state, events, fake_clock, stub_server):
    _serve_env(stub_server, "svil", {"20260921.txt": LF_BODY[:-100]})
    local = _local(cfg, "svil", "20260921.txt")
    local.parent.mkdir(parents=True)
    local.write_bytes(LF_BODY.replace(b"\n", b"\r\n"))

    _engine(cfg, state, events, fake_clock).run(["svil"])

    assert {(e.name, e.reason) for e in events.of(FileSkipped)} == {("20260921.txt", "shrunk")}
    assert local.with_name(f"20260921.txt.remote-{len(LF_BODY) - 100}").exists()


@pytest.mark.parametrize("chunk", [1, 2, 3, 7, 1 << 20])
def test_count_crlf_is_right_across_chunk_boundaries(tmp_path, chunk):
    path = tmp_path / "f.txt"
    path.write_bytes(b"a\r\nb\r\r\n\n\r\nc\r")
    assert syncmod.count_crlf(path, chunk_size=chunk) == 3


# ------------------------------------------------ 10. shrunk, file gone ---

def test_a_shrunk_day_removed_during_the_run_is_a_file_failure_not_a_crash(cfg, state, events, fake_clock, stub_server):
    """Final review #6: the local file vanishes between plan and handling
    (a user, an AV quarantine): one FileFailed, status "errors", and the
    rest of the listing is still processed."""
    _serve_env(stub_server, "svil", {"20260921.txt": _payload(1_200), "20260920.txt": _payload(700)})
    local = _local(cfg, "svil", "20260921.txt")
    local.parent.mkdir(parents=True)
    local.write_bytes(_payload(5_000))

    def deleting_sink(ev) -> None:
        events(ev)
        if isinstance(ev, RemoteIndexRead):
            local.unlink()

    report = _engine(cfg, state, deleting_sink, fake_clock).run(["svil"])

    failed = events.of(FileFailed)
    assert [e.name for e in failed] == ["20260921.txt"]
    assert [e.name for e in events.of(FileDone)] == ["20260920.txt"]
    result = _result(events, "svil")
    assert result.status == "errors"
    assert (result.failed, result.downloaded) == (1, 1)
    assert report.exit_code == 1
    # The listing is remembered (U1.3), the run is not a success.
    assert all(s.last_success is None for s in (SyncState(cfg.state_path).load().get(e) for e in ("svil", "coll")))


# --------------------------------------------------- 11. dry-run wording ---

def test_a_dry_run_summary_says_anteprima():
    t = datetime(2026, 9, 22, 9, 30)
    real = SyncReport((EnvResult("svil", "ok", 1, 0, 0, 0, 10, None),), t, t)
    preview = SyncReport((EnvResult("svil", "ok", 1, 0, 0, 0, 10, None),), t, t, dry_run=True)
    assert "anteprima" not in real.summary_line()
    assert preview.summary_line().startswith("anteprima della sincronizzazione terminata")


def test_the_engine_report_carries_dry_run(cfg, state, events, fake_clock, stub_server):
    _serve_env(stub_server, "svil", {"20260921.txt": _payload(100)})
    assert _engine(cfg, state, events, fake_clock).run(["svil"], dry_run=True).dry_run is True
