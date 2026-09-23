"""core/jobs.py: lock -> sync -> index, as one job, against the stub server."""
from __future__ import annotations

import dataclasses
import logging
from pathlib import Path

import pytest

from qtrequestory.core.config import Config, Environment, SyncSettings, default_config
from qtrequestory.core.events import (
    CancelToken,
    CollectingSink,
    EnvFinished,
    FileDone,
    IndexFinished,
    IndexStarted,
    LogMessage,
    SyncFinished,
    SyncStarted,
)
from qtrequestory.core.index.db import open_index
from qtrequestory.core.index.search import SearchQuery, search
from qtrequestory.core.jobs import JobReport, run_index_job, run_sync_job
from qtrequestory.core.lock import ProcessLock
from qtrequestory.core.state import SyncState

from .conftest import FDI_A, FDI_B, KEY_CTE, KEY_SINT, StubServer, autoindex_html, entry_name, make_daily_file, synthetic_body

DAY = "20260918"


def _daily(*entries: tuple[str, bytes]) -> bytes:
    return b"".join(b"### " + name.encode() + b".json\r\n" + body + b"\r\n" for name, body in entries)


@pytest.fixture
def cfg(tmp_path: Path, stub_server: StubServer) -> Config:
    return dataclasses.replace(
        default_config(),
        mirror_root=tmp_path / "mirror",
        environments=[
            Environment("svil", stub_server.url + "/svil/"),
            Environment("coll", stub_server.url + "/coll/"),
        ],
        sync=SyncSettings(index_timeout_s=5, download_timeout_s=5, chunk_size=1024, retries=0),
    )


def _serve(stub_server: StubServer, env: str, files: dict[str, bytes]) -> None:
    stub_server.add(f"/{env}/", autoindex_html([(n, "18-Sep-2026 18:30", len(b)) for n, b in files.items()]))
    for name, body in files.items():
        stub_server.add(f"/{env}/{name}", body)


def _search_names(cfg: Config, env: str, fdi: str) -> list[str]:
    conn = open_index(cfg.index_path)
    try:
        return [h.name for h in search(conn, cfg.mirror_root, SearchQuery(env, fdi_prefix=fdi))]
    finally:
        conn.close()


# ----------------------------------------------------------------- sync ---

def test_sync_job_downloads_and_indexes(cfg: Config, stub_server: StubServer):
    _serve(stub_server, "svil", {f"{DAY}.txt": _daily((entry_name(FDI_A, KEY_SINT), synthetic_body(FDI_A, KEY_SINT)))})
    _serve(stub_server, "coll", {f"{DAY}.txt": _daily((entry_name(FDI_B, KEY_CTE), synthetic_body(FDI_B, KEY_CTE)))})
    sink = CollectingSink()

    report = run_sync_job(cfg, sink=sink, cancel=CancelToken())

    assert isinstance(report, JobReport)
    assert report.exit_code == 0
    assert report.sync is not None and report.sync.exit_code == 0
    assert report.indexed_files == 2
    assert {e.env for e in sink.of(FileDone)} == {"svil", "coll"}
    assert (cfg.mirror_root / "svil" / "2026" / "09" / f"{DAY}.txt").is_file()
    # the search index knows the freshly downloaded entries
    assert _search_names(cfg, "svil", FDI_A) == [entry_name(FDI_A, KEY_SINT)]
    assert _search_names(cfg, "coll", FDI_B) == [entry_name(FDI_B, KEY_CTE)]
    # event order: sync first, index after, one summary line in between for sync.log
    kinds = [type(e) for e in sink.events]
    assert kinds.index(SyncFinished) < kinds.index(IndexStarted) < kinds.index(IndexFinished)
    summary = [e for e in sink.of(LogMessage) if "sincronizzazione terminata" in e.text]
    assert len(summary) == 1 and summary[0].level == logging.INFO
    # state written, lock released
    assert SyncState(cfg.state_path).load().get("svil").last_success is not None
    assert ProcessLock(cfg.lock_path).acquire() is True


def test_sync_job_restricts_to_requested_envs(cfg: Config, stub_server: StubServer):
    _serve(stub_server, "svil", {f"{DAY}.txt": _daily((entry_name(FDI_A, KEY_SINT), synthetic_body(FDI_A, KEY_SINT)))})
    sink = CollectingSink()
    report = run_sync_job(cfg, envs=["svil"], sink=sink, cancel=CancelToken())
    assert report.exit_code == 0
    assert sink.of(SyncStarted)[0].envs == ("svil",)
    assert [r.env for r in report.sync.results] == ["svil"]
    assert all("/coll/" not in path for _, path in stub_server.requests)
    assert report.indexed_files == 1


def test_sync_job_lock_held_is_a_quiet_no_op(cfg: Config, stub_server: StubServer):
    _serve(stub_server, "svil", {f"{DAY}.txt": b"### x_K_0000000000000000.json\r\n{}\r\n"})
    other = ProcessLock(cfg.lock_path)
    assert other.acquire()
    try:
        sink = CollectingSink()
        report = run_sync_job(cfg, sink=sink, cancel=CancelToken())
    finally:
        other.release()

    assert report == JobReport(sync=None, indexed_files=0, exit_code=0)
    assert stub_server.requests == []
    assert len(sink.events) == 1
    msg = sink.events[0]
    assert isinstance(msg, LogMessage)
    assert msg.text.startswith("sincronizzazione già in corso (")
    assert not cfg.index_path.exists()


def test_sync_job_dry_run_touches_nothing(cfg: Config, stub_server: StubServer):
    _serve(stub_server, "svil", {f"{DAY}.txt": _daily((entry_name(FDI_A, KEY_SINT), synthetic_body(FDI_A, KEY_SINT)))})
    _serve(stub_server, "coll", {f"{DAY}.txt": _daily((entry_name(FDI_B, KEY_CTE), synthetic_body(FDI_B, KEY_CTE)))})
    sink = CollectingSink()
    report = run_sync_job(cfg, dry_run=True, sink=sink, cancel=CancelToken())
    assert report.exit_code == 0
    assert report.indexed_files == 0
    assert report.sync.results[0].downloaded == 1  # counted, not fetched
    assert not (cfg.mirror_root / "svil").exists()
    assert not cfg.index_path.exists()
    assert not cfg.state_path.exists()
    assert sink.of(IndexStarted) == []


def test_sync_job_cancel_reports_exit_3_and_skips_indexing(cfg: Config, stub_server: StubServer):
    _serve(stub_server, "svil", {f"{DAY}.txt": _daily((entry_name(FDI_A, KEY_SINT), synthetic_body(FDI_A, KEY_SINT)))})
    _serve(stub_server, "coll", {f"{DAY}.txt": _daily((entry_name(FDI_B, KEY_CTE), synthetic_body(FDI_B, KEY_CTE)))})
    cancel = CancelToken()
    sink = CollectingSink()

    def cancelling_sink(ev):
        sink(ev)
        if isinstance(ev, FileDone):  # cancel after the first file lands
            cancel.cancel()

    report = run_sync_job(cfg, sink=cancelling_sink, cancel=cancel)
    assert report.exit_code == 3
    assert report.sync is not None and report.sync.exit_code == 3
    assert report.indexed_files == 0
    assert [e.result.status for e in sink.of(EnvFinished)] == ["ok", "cancelled"]
    assert sink.of(IndexStarted) == []
    assert ProcessLock(cfg.lock_path).acquire() is True  # released in finally


def test_sync_job_unreachable_env_still_indexes_local_files(cfg: Config, stub_server: StubServer, tmp_path):
    # nothing served: both envs unreachable (404) -> exit 2, but a pre-existing local file gets indexed
    from datetime import date
    make_daily_file(cfg.mirror_root, "coll", date(2026, 9, 15), [(entry_name(FDI_A, KEY_CTE), synthetic_body(FDI_A, KEY_CTE))])
    sink = CollectingSink()
    report = run_sync_job(cfg, sink=sink, cancel=CancelToken())
    assert report.exit_code == 2
    assert report.indexed_files == 1
    assert _search_names(cfg, "coll", FDI_A) == [entry_name(FDI_A, KEY_CTE)]


def test_sync_job_indexes_a_disabled_env_too(cfg: Config, stub_server: StubServer):
    """M23: ``envs=None`` only SYNCS enabled environments (``core.sync``'s
    ``enabled_environments()``), but ``_index_envs`` deliberately indexes every
    configured one regardless — a disabled env may still hold history worth
    searching (see ``core/jobs.py``). A disabled "coll" with a pre-existing
    local file (from before it was disabled) must therefore end up indexed by
    a plain ``--sync``, even though the sync itself never touches it.
    """
    cfg = dataclasses.replace(
        cfg, environments=[dataclasses.replace(e, enabled=(e.name != "coll")) for e in cfg.environments]
    )
    from datetime import date
    make_daily_file(cfg.mirror_root, "coll", date(2026, 9, 15), [(entry_name(FDI_B, KEY_CTE), synthetic_body(FDI_B, KEY_CTE))])
    _serve(stub_server, "svil", {f"{DAY}.txt": _daily((entry_name(FDI_A, KEY_SINT), synthetic_body(FDI_A, KEY_SINT)))})
    sink = CollectingSink()

    report = run_sync_job(cfg, sink=sink, cancel=CancelToken())

    assert report.exit_code == 0
    assert [r.env for r in report.sync.results] == ["svil"]  # coll was never synced
    assert all("/coll/" not in path for _, path in stub_server.requests)
    assert report.indexed_files == 2  # the fresh svil download AND the pre-existing coll file
    assert _search_names(cfg, "coll", FDI_B) == [entry_name(FDI_B, KEY_CTE)]
    assert _search_names(cfg, "svil", FDI_A) == [entry_name(FDI_A, KEY_SINT)]


def test_sync_job_index_failure_is_logged_not_fatal(cfg: Config, stub_server: StubServer, monkeypatch):
    _serve(stub_server, "svil", {f"{DAY}.txt": _daily((entry_name(FDI_A, KEY_SINT), synthetic_body(FDI_A, KEY_SINT)))})
    cfg = dataclasses.replace(cfg, environments=cfg.environments[:1])

    def boom(path):
        raise OSError("disk full")

    monkeypatch.setattr("qtrequestory.core.jobs.open_index", boom)
    sink = CollectingSink()
    report = run_sync_job(cfg, sink=sink, cancel=CancelToken())
    assert report.exit_code == 0  # sync exit code, untouched
    assert report.indexed_files == 0
    errors = [e for e in sink.of(LogMessage) if e.level == logging.ERROR]
    assert errors and "disk full" in errors[0].text


# ---------------------------------------------------------------- index ---

def test_index_job_indexes_local_mirror(cfg: Config, mirror):
    cfg = dataclasses.replace(cfg, mirror_root=mirror.root)
    sink = CollectingSink()
    report = run_index_job(cfg, sink=sink, cancel=CancelToken())
    assert report == JobReport(sync=None, indexed_files=4, exit_code=0)
    assert sink.of(IndexStarted)[0].n_files_to_scan == 4
    assert len(_search_names(cfg, "coll", FDI_A)) == 4

    # second run: nothing changed
    assert run_index_job(cfg, sink=CollectingSink(), cancel=CancelToken()).indexed_files == 0
    # full rebuild rescans everything
    assert run_index_job(cfg, full_rebuild=True, sink=CollectingSink(), cancel=CancelToken()).indexed_files == 4
    # explicit env subset
    assert run_index_job(cfg, envs=["svil"], full_rebuild=True, sink=CollectingSink(), cancel=CancelToken()).indexed_files == 1


def test_index_job_cancelled_before_start(cfg: Config, mirror):
    cfg = dataclasses.replace(cfg, mirror_root=mirror.root)
    cancel = CancelToken()
    cancel.cancel()
    report = run_index_job(cfg, sink=CollectingSink(), cancel=cancel)
    assert report == JobReport(sync=None, indexed_files=0, exit_code=3)


def test_index_job_failure_exit_1(cfg: Config, monkeypatch):
    def boom(path):
        raise OSError("disk full")

    monkeypatch.setattr("qtrequestory.core.jobs.open_index", boom)
    sink = CollectingSink()
    report = run_index_job(cfg, sink=sink, cancel=CancelToken())
    assert report.exit_code == 1
    assert any("disk full" in e.text for e in sink.of(LogMessage))


def test_index_job_rejects_an_unknown_environment(cfg: Config):
    """Final review #4: ``--index -e <typo>`` used to exit 0 having done nothing."""
    from qtrequestory.core.config import UnknownEnvironment

    with pytest.raises(UnknownEnvironment):
        run_index_job(cfg, envs=["nope"], sink=CollectingSink(), cancel=CancelToken())


def test_sync_job_dry_run_is_logged_as_anteprima(cfg: Config, stub_server: StubServer):
    """Final review #3: the window's "Anteprima" writes sync.log through the
    same LoggingSink; its lines must not read like a real sync."""
    from qtrequestory.core.events import LoggingSink

    _serve(stub_server, "svil", {f"{DAY}.txt": _daily((entry_name(FDI_A, KEY_SINT), synthetic_body(FDI_A, KEY_SINT)))})

    def logged_run(**kw) -> list[str]:
        lines: list[str] = []

        class _Capture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                lines.append(record.getMessage())

        logger = logging.getLogger("test.dry_run_log")
        handler = _Capture()
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
        try:
            run_sync_job(cfg, envs=["svil"], sink=LoggingSink(logger), cancel=CancelToken(), **kw)
        finally:
            logger.removeHandler(handler)
        return lines

    preview = logged_run(dry_run=True)
    assert any(line.startswith("svil: anteprima") for line in preview), preview
    assert any(line.startswith("anteprima della sincronizzazione terminata") for line in preview), preview

    real = logged_run()
    assert real and all("anteprima" not in line for line in real), real
