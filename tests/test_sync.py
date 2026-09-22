"""SyncEngine against the synthetic stub server (two envs, real UrllibHttpClient).

Nothing here is real: hostnames are the loopback stub, file bodies are byte
patterns. Every test drives the engine end to end and inspects the mirror on
disk, the recorded HTTP requests, the emitted events and the sync state.
"""
from __future__ import annotations

import dataclasses
import logging
from datetime import datetime
from pathlib import Path

import pytest

from qtrequestory.core import sync as syncmod
from qtrequestory.core.config import Config, Environment, SyncSettings, default_config
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
    with pytest.raises(KeyError):
        _engine(cfg, state, events, fake_clock).run(["prod"])


# --------------------------------------------------------------- 2. state ---

def test_state_marked_with_clock_after_success(cfg, state, events, fake_clock, stub_server):
    _serve_env(stub_server, "coll", {"20260921.txt": _payload(2_000), "20260920.txt": b""})

    report = _engine(cfg, state, events, fake_clock).run(["coll"])

    assert report.exit_code == 0
    st = SyncState(cfg.state_path).load().get("coll")
    assert st.last_success == fake_clock.now
    assert st.last_remote_daily == 2
    assert st.last_downloaded == 1
    assert SyncState(cfg.state_path).load().get("svil").last_success is None


# --------------------------------------------------------------- 3. fresh ---

def test_fresh_env_makes_no_requests_unless_forced(cfg, state, events, fake_clock, stub_server):
    _serve_env(stub_server, "svil", {"20260921.txt": _payload(1_000)})
    # synced yesterday after the 18:30 compaction; the clock says 09:30 today
    state.mark_success("svil", datetime(2026, 9, 21, 19, 0))

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

def test_truncated_download_fails_file_but_not_the_rest(cfg, state, events, fake_clock, stub_server):
    _serve_env(stub_server, "coll", {"20260921.txt": _payload(10_000), "20260920.txt": _payload(3_000)})
    stub_server.routes["/coll/20260921.txt"].truncate_after = 4_000

    report = _engine(cfg, state, events, fake_clock).run(["coll"])

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
    assert not cfg.state_path.exists()


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
    assert [r.status for r in report.results] == ["cancelled"]
    assert _no_part_files(cfg.mirror_root)
    assert not _local(cfg, "svil", "20260921.txt").exists()
    assert not _local(cfg, "svil", "20260920.txt").exists()
    assert ("GET", "/svil/20260920.txt") not in stub_server.requests
    assert ("GET", "/coll/") not in stub_server.requests
    assert not events.of(FileDone)
    assert not cfg.state_path.exists()
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
    assert "exit 0" in line
    assert "12" in line  # seconds
