"""core/index/builder.py: plan/update/rescan against the synthetic mirror."""
from __future__ import annotations

import os
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from qtrequestory.core.daily import count_local_files, relative_path
from qtrequestory.core.events import CancelToken, Cancelled, CollectingSink, IndexFileScanned, IndexFinished, IndexStarted
from qtrequestory.core.index.builder import IndexBuilder, IndexPlan, IndexStats
from qtrequestory.core.index.db import open_index
from tests.conftest import FDI_A, KEY_SINT, entry_name, make_daily_file, synthetic_body

ENVS = ["coll", "svil"]
NEWEST = ("coll", date(2026, 9, 18))
LF_DAY = ("coll", date(2026, 9, 15))
TOTAL_ENTRIES = 7 + 2 + 1 + 1


@pytest.fixture
def conn() -> sqlite3.Connection:
    c = open_index(":memory:")
    yield c
    c.close()


def _count(conn: sqlite3.Connection, table: str, where: str = "1", *params) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", params).fetchone()[0]


def _builder(conn, mirror, events, cancel=None) -> IndexBuilder:
    return IndexBuilder(conn, mirror.root, events, cancel)


# ------------------------------------------------------------- fresh build ---

def test_fresh_update_indexes_everything(conn, mirror, events: CollectingSink):
    stats = _builder(conn, mirror, events).update(ENVS)

    assert isinstance(stats, IndexStats)
    assert (stats.scanned, stats.removed) == (4, 0)
    assert stats.seconds >= 0
    assert _count(conn, "files") == 4
    assert _count(conn, "entries") == TOTAL_ENTRIES

    # files row content
    env, day = LF_DAY
    row = conn.execute("SELECT * FROM files WHERE env=? AND day=?", (env, day.isoformat())).fetchone()
    assert row["rel_path"] == relative_path(env, day)
    assert row["size"] == mirror.files[LF_DAY].stat().st_size
    assert row["mtime_ns"] == mirror.files[LF_DAY].stat().st_mtime_ns
    assert (row["n_entries"], row["n_orphans"]) == (2, 2)
    assert "T" in row["scanned_at"]  # ISO timestamp

    # ndocs, the only thing the index keeps about documents[] (3, 2, 5, 2, 2, 2 on
    # the newest day; the non-JSON body has none)
    file_id = conn.execute("SELECT id FROM files WHERE env=? AND day=?", ("coll", "2026-09-18")).fetchone()[0]
    ndocs = [r[0] for r in conn.execute(
        "SELECT ndocs FROM entries WHERE file_id=? ORDER BY seq", (file_id,))]
    assert ndocs == [3, 2, 5, 2, 2, 2, None]

    # entry columns: lowercase fdi, key, call_id, well_formed, json_ok, dossier fields
    e = conn.execute("SELECT * FROM entries WHERE file_id=? AND seq=0", (file_id,)).fetchone()
    assert e["fdi"] == FDI_A
    assert e["template_key"] == KEY_SINT
    assert e["call_id"] == "1a2b3c0200000033"
    assert (e["well_formed"], e["json_ok"]) == (1, 1)
    assert e["ndocs"] == 3
    assert e["request_date"] == "2026-09-18T10:38:28.776Z"
    assert e["dossier_id"] == "dossier-" + FDI_A[:8]
    assert e["dossier_number"] == "DA00000001"
    assert e["body_len"] > 0 and e["body_offset"] > e["header_offset"]
    # correlationId_vuoto -> NULL fdi; non-JSON body -> json_ok 0
    assert conn.execute("SELECT fdi FROM entries WHERE file_id=? AND seq=4", (file_id,)).fetchone()[0] is None
    assert conn.execute("SELECT json_ok, ndocs FROM entries WHERE file_id=? AND seq=6", (file_id,)).fetchone()[:] == (0, None)

    # events
    assert [ev.n_files_to_scan for ev in events.of(IndexStarted)] == [4]
    scanned = events.of(IndexFileScanned)
    assert len(scanned) == 4
    assert [(ev.i, ev.n) for ev in scanned] == [(1, 4), (2, 4), (3, 4), (4, 4)]
    assert sum(ev.n_entries for ev in scanned) == TOTAL_ENTRIES
    assert all(isinstance(ev.path, Path) for ev in scanned)
    finished = events.of(IndexFinished)
    assert len(finished) == 1 and finished[0].scanned == 4 and finished[0].removed == 0


def test_update_scans_newest_first(conn, mirror, events: CollectingSink):
    _builder(conn, mirror, events).update(ENVS)
    days = [ev.path.name for ev in events.of(IndexFileScanned)]
    assert days == ["20260918.txt", "20260916.txt", "20260915.txt", "20260803.txt"]


def test_degenerate_name_with_empty_fdi_stores_null(conn, mirror, events):
    """``_KEY_id`` parses to ``fdi == ""``; the index must store NULL, not an empty string."""
    make_daily_file(mirror.root, "svil", date(2026, 9, 17), [
        ("_MOD_X_1a2b3c0200000001", synthetic_body(FDI_A, "MOD_X")),
    ])
    _builder(conn, mirror, events).update(["svil"])
    rows = conn.execute("SELECT fdi, template_key FROM entries WHERE env='svil' AND day='2026-09-17'").fetchall()
    assert [tuple(r) for r in rows] == [(None, "MOD_X")]


# ---------------------------------------------------------- incremental ---

def test_second_update_is_a_no_op(conn, mirror, events: CollectingSink):
    b = _builder(conn, mirror, events)
    b.update(ENVS)
    events.events.clear()

    plan = b.plan(ENVS)
    assert isinstance(plan, IndexPlan)
    assert plan.to_scan == [] and plan.to_remove == []

    stats = b.update(ENVS)
    assert (stats.scanned, stats.removed) == (0, 0)
    assert [type(ev) for ev in events.events] == [IndexStarted, IndexFinished]
    assert events.of(IndexStarted)[0].n_files_to_scan == 0
    assert _count(conn, "files") == 4 and _count(conn, "entries") == TOTAL_ENTRIES


def test_changed_size_rescans_only_that_file(conn, mirror, events: CollectingSink):
    b = _builder(conn, mirror, events)
    b.update(ENVS)
    env, day = LF_DAY
    old_ids = {r[0] for r in conn.execute("SELECT id FROM entries WHERE env=? AND day=?", (env, day.isoformat()))}

    path = mirror.files[LF_DAY]
    with path.open("ab") as f:
        f.write(b"### " + entry_name(FDI_A, KEY_SINT, "1a2b3c0200000099").encode() + b".json\n")
        f.write(synthetic_body(FDI_A, KEY_SINT) + b"\n")

    plan = b.plan(ENVS)
    assert [(f.env, f.day) for f in plan.to_scan] == [LF_DAY]
    stats = b.update(ENVS)
    assert (stats.scanned, stats.removed) == (1, 0)
    assert _count(conn, "files") == 4
    assert _count(conn, "entries", "env=? AND day=?", env, day.isoformat()) == 3
    new_ids = {r[0] for r in conn.execute("SELECT id FROM entries WHERE env=? AND day=?", (env, day.isoformat()))}
    assert not (old_ids & new_ids)  # old rows gone, not updated in place
    assert _count(conn, "entries") == TOTAL_ENTRIES + 1


def test_touched_mtime_rescans(conn, mirror, events: CollectingSink):
    b = _builder(conn, mirror, events)
    b.update(ENVS)
    path = mirror.files[NEWEST]
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))

    plan = b.plan(ENVS)
    assert [(f.env, f.day) for f in plan.to_scan] == [NEWEST]
    stats = b.update(ENVS)
    assert stats.scanned == 1
    assert _count(conn, "entries") == TOTAL_ENTRIES
    row = conn.execute("SELECT mtime_ns FROM files WHERE env=? AND day=?", ("coll", "2026-09-18")).fetchone()
    assert row[0] == path.stat().st_mtime_ns


def test_deleted_file_rows_are_removed(conn, mirror, events: CollectingSink):
    b = _builder(conn, mirror, events)
    b.update(ENVS)
    env, day = LF_DAY
    file_id = conn.execute("SELECT id FROM files WHERE env=? AND day=?", (env, day.isoformat())).fetchone()[0]
    mirror.files[LF_DAY].unlink()

    plan = b.plan(ENVS)
    assert plan.to_scan == [] and plan.to_remove == [file_id]
    stats = b.update(ENVS)
    assert (stats.scanned, stats.removed) == (0, 1)
    assert _count(conn, "files") == 3
    assert _count(conn, "entries", "file_id=?", file_id) == 0
    assert _count(conn, "entries") == TOTAL_ENTRIES - 2
    assert events.of(IndexFinished)[-1].removed == 1


# ------------------------------------------------------------------ cancel ---

def test_cancel_after_first_file_leaves_consistent_index(conn, mirror):
    cancel = CancelToken()
    seen: list[IndexFileScanned] = []

    def sink(ev):
        if isinstance(ev, IndexFileScanned):
            seen.append(ev)
            cancel.cancel()

    b = IndexBuilder(conn, mirror.root, sink, cancel)
    with pytest.raises(Cancelled):
        b.update(ENVS)

    assert len(seen) == 1
    assert _count(conn, "files") == 1
    assert conn.in_transaction is False
    file_id = conn.execute("SELECT id, n_entries FROM files").fetchone()
    assert _count(conn, "entries") == file_id["n_entries"] == 7  # newest coll day was first
    assert _count(conn, "entries", "file_id<>?", file_id["id"]) == 0


def test_cancel_before_start_writes_nothing(conn, mirror, events):
    cancel = CancelToken()
    cancel.cancel()
    with pytest.raises(Cancelled):
        IndexBuilder(conn, mirror.root, events, cancel).update(ENVS)
    assert _count(conn, "files") == 0


def test_cancel_before_start_does_not_wipe_on_full_rebuild(conn, mirror, events):
    _builder(conn, mirror, events).update(ENVS)
    cancel = CancelToken()
    cancel.cancel()
    with pytest.raises(Cancelled):
        IndexBuilder(conn, mirror.root, events, cancel).update(ENVS, full_rebuild=True)
    assert _count(conn, "files") == 4 and _count(conn, "entries") == TOTAL_ENTRIES


# ------------------------------------------------------- full rebuild etc ---

def test_full_rebuild_rescans_everything(conn, mirror, events: CollectingSink):
    b = _builder(conn, mirror, events)
    b.update(ENVS)
    events.events.clear()

    stats = b.update(ENVS, full_rebuild=True)
    assert (stats.scanned, stats.removed) == (4, 0)
    assert events.of(IndexStarted)[0].n_files_to_scan == 4
    assert len(events.of(IndexFileScanned)) == 4
    assert _count(conn, "files") == 4 and _count(conn, "entries") == TOTAL_ENTRIES


def test_full_rebuild_only_touches_requested_envs(conn, mirror, events: CollectingSink):
    b = _builder(conn, mirror, events)
    b.update(ENVS)
    svil_id = conn.execute("SELECT id FROM files WHERE env='svil'").fetchone()[0]
    stats = b.update(["coll"], full_rebuild=True)
    assert stats.scanned == 3
    assert conn.execute("SELECT id FROM files WHERE env='svil'").fetchone()[0] == svil_id


def test_rescan_file_and_count_local_files(conn, mirror, events: CollectingSink):
    b = _builder(conn, mirror, events)
    b.update(ENVS)
    assert b.rescan_file("coll", date(2026, 9, 18)) == 7
    assert b.rescan_file("coll", date(2026, 9, 15)) == 2
    assert _count(conn, "files") == 4 and _count(conn, "entries") == TOTAL_ENTRIES
    # rescan_file on a day that was never indexed simply indexes it
    conn.execute("DELETE FROM files WHERE env='svil'")
    conn.commit()
    assert b.rescan_file("svil", date(2026, 9, 16)) == 1
    assert _count(conn, "files") == 4

    (mirror.root / ".qtrequestory").mkdir()
    (mirror.root / ".qtrequestory" / "index.sqlite").write_bytes(b"")
    assert count_local_files(mirror.root) == 4
    assert count_local_files(mirror.root / "does-not-exist") == 0


def test_parse_json_false_skips_documents(conn, mirror, events: CollectingSink):
    IndexBuilder(conn, mirror.root, events, parse_json=False).update(ENVS)
    assert _count(conn, "entries") == TOTAL_ENTRIES
    assert _count(conn, "entries", "ndocs IS NOT NULL") == 0
    # request_date still extracted by regex
    n = conn.execute("SELECT COUNT(*) FROM entries WHERE request_date IS NOT NULL").fetchone()[0]
    assert n == TOTAL_ENTRIES - 2  # the request_date=None body and the non-JSON body lack it


def _has_stats(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='sqlite_stat1'").fetchone()[0] == 1


def test_analyze_runs_only_after_more_than_ten_files(conn, mirror, events):
    b = _builder(conn, mirror, events)
    b.update(ENVS)  # 4 files: no ANALYZE
    assert not _has_stats(conn)
    for d in range(1, 12):
        make_daily_file(mirror.root, "prod", date(2026, 7, d), [
            (entry_name(FDI_A, KEY_SINT, f"10b6016b000000{d:02x}"), synthetic_body(FDI_A, KEY_SINT)),
        ])
    assert b.update(["prod"]).scanned == 11
    assert _has_stats(conn)
    assert conn.in_transaction is False


# ------------------------------------------------------ corrupt index repair ---

def _index_service(mirror, tmp_path: Path):
    import dataclasses

    from qtrequestory.core import facade
    from qtrequestory.core.config import Environment, default_config

    cfg = dataclasses.replace(
        default_config(),
        mirror_root=mirror.root,
        environments=[Environment("svil", "https://example.invalid/svil/"),
                      Environment("coll", "https://example.invalid/coll/")],
        output_dir=tmp_path / "out",
    )
    return facade.IndexService(lambda: cfg), cfg


def _broken(index_path: Path) -> list[Path]:
    return sorted(index_path.parent.glob(index_path.name + ".broken-*"))


def test_a_corrupt_index_is_set_aside_and_rebuilt(mirror, tmp_path: Path, caplog):
    """7 KB of garbage as index.sqlite: "file is not a database" used to be
    permanent, --index --rebuild included (same open_index)."""
    from qtrequestory.core.events import CancelToken

    svc, cfg = _index_service(mirror, tmp_path)
    cfg.index_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.index_path.write_bytes(os.urandom(7 * 1024))
    cfg.index_path.with_name("index.sqlite-wal").write_bytes(b"junk")
    cfg.index_path.with_name("index.sqlite-shm").write_bytes(b"junk")

    report = svc.update(["coll", "svil"], sink=CollectingSink(), cancel=CancelToken())
    assert (report.indexed_files, report.exit_code) == (4, 0)
    broken = _broken(cfg.index_path)
    assert len(broken) == 1
    assert broken[0].stat().st_size == 7 * 1024
    assert "index.sqlite.broken-" in caplog.text
    assert svc.plan(["coll", "svil"]).to_scan == []


@pytest.mark.parametrize("damage", ["schema", "table"])
def test_damage_found_by_any_statement_of_open_index_is_repaired(tmp_path: Path, damage: str):
    """Valid file header, garbage further in. ``schema``: sqlite_master (page 1)
    is hit by the first PRAGMA. ``table``: only the root page of ``entries`` is
    hit — connect(), every PRAGMA and the version check succeed, and the damage
    would first surface at a search unless open_index looks for it."""
    path = tmp_path / "index.sqlite"
    conn = open_index(path)
    conn.execute("PRAGMA journal_mode=DELETE")  # everything in the main file
    page_size = conn.execute("PRAGMA page_size").fetchone()[0]
    root = conn.execute("SELECT rootpage FROM sqlite_master WHERE name='entries'").fetchone()[0]
    conn.close()
    raw = bytearray(path.read_bytes())
    start, end = (100, page_size) if damage == "schema" else ((root - 1) * page_size, root * page_size)
    raw[start:end] = b"\xa5" * (end - start)
    path.write_bytes(bytes(raw))

    conn = open_index(path)
    try:
        assert _count(conn, "entries") == 0
    finally:
        conn.close()
    assert len(_broken(path)) == 1


def test_at_most_three_broken_copies_are_kept(tmp_path: Path):
    path = tmp_path / "index.sqlite"
    for stamp in ("20260101-000000", "20260102-000000", "20260103-000000"):
        path.with_name(f"index.sqlite.broken-{stamp}").write_bytes(b"old")
    path.write_bytes(os.urandom(7 * 1024))
    open_index(path).close()
    broken = _broken(path)
    assert len(broken) == 3
    assert path.with_name("index.sqlite.broken-20260101-000000") not in broken
    assert any(p.stat().st_size == 7 * 1024 for p in broken)


def test_a_locked_index_is_not_mistaken_for_a_corrupt_one(tmp_path: Path, monkeypatch):
    from qtrequestory.core.index import db

    path = tmp_path / "index.sqlite"
    open_index(path).close()

    def locked(conn):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(db, "migrate", locked)
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        open_index(path)
    assert _broken(path) == []
    assert path.exists()


def test_a_file_repaired_meanwhile_by_another_process_is_used_not_set_aside(tmp_path: Path, monkeypatch):
    """GUI and hourly --sync find the same corrupt file: by the time the second
    one retries, the first has put a fresh index at ``path``. That index must be
    used, not renamed away (on Windows the rename even raised PermissionError)."""
    from qtrequestory.core.index import db

    path = tmp_path / "index.sqlite"
    open_index(path).close()  # the other process's fresh index
    real = db._connect
    calls: list[Path] = []

    def corrupt_first(target):
        calls.append(target)
        if len(calls) == 1:  # what we saw before the other process repaired it
            raise sqlite3.DatabaseError("file is not a database")
        return real(target)

    monkeypatch.setattr(db, "_connect", corrupt_first)
    conn = open_index(path)
    try:
        assert _count(conn, "files") == 0
    finally:
        conn.close()
    assert len(calls) == 2
    assert _broken(path) == []


def test_a_failed_set_aside_reraises_the_corruption_not_the_os_error(tmp_path: Path, monkeypatch):
    path = tmp_path / "index.sqlite"
    path.write_bytes(os.urandom(7 * 1024))

    def held_open(self, target):
        raise PermissionError(32, "The process cannot access the file")

    monkeypatch.setattr(Path, "replace", held_open)
    with pytest.raises(sqlite3.DatabaseError, match="not a database"):
        open_index(path)
    assert _broken(path) == []
    assert path.stat().st_size == 7 * 1024


class _LockedWal:
    """Proxy connection whose first ``n`` journal-mode switches find the file locked."""

    def __init__(self, conn: sqlite3.Connection, n: int) -> None:
        self._conn, self.left, self.attempts = conn, n, 0

    def execute(self, sql: str, *args):
        if "journal_mode" in sql:
            self.attempts += 1
            if self.left:
                self.left -= 1
                raise sqlite3.OperationalError("database is locked")
        return self._conn.execute(sql, *args)


def test_wal_switch_retries_once_when_locked(tmp_path: Path, monkeypatch):
    from qtrequestory.core.index import db

    monkeypatch.setattr(db, "WAL_RETRY_DELAY_S", 0)
    raw = sqlite3.connect(tmp_path / "index.sqlite")
    once = _LockedWal(raw, 1)
    db._enable_wal(once)
    assert once.attempts == 2
    assert raw.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    twice = _LockedWal(raw, 2)
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        db._enable_wal(twice)
    assert twice.attempts == 2
    raw.close()


def test_a_locked_wal_switch_is_never_treated_as_corruption(tmp_path: Path, monkeypatch):
    from qtrequestory.core.index import db

    path = tmp_path / "index.sqlite"
    open_index(path).close()

    def locked(conn):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(db, "_enable_wal", locked)
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        open_index(path)
    assert _broken(path) == []
    assert path.exists()
