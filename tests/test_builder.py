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

    # entry_documents: principal + attachments per body (ndocs 3, 2, 5, 2, 2, 2 on the newest day; the
    # non-JSON body has none)
    file_id = conn.execute("SELECT id FROM files WHERE env=? AND day=?", ("coll", "2026-09-18")).fetchone()[0]
    n_docs = conn.execute(
        "SELECT COUNT(*) FROM entry_documents d JOIN entries e ON e.id = d.entry_id WHERE e.file_id=?", (file_id,)
    ).fetchone()[0]
    assert n_docs == 3 + 2 + 5 + 2 + 2 + 2
    principal = conn.execute(
        "SELECT d.template_key FROM entry_documents d JOIN entries e ON e.id = d.entry_id "
        "WHERE e.file_id=? AND e.seq=0 ORDER BY d.pos", (file_id,)
    ).fetchall()
    assert [r[0] for r in principal] == [KEY_SINT, "ATTACH_1", "ATTACH_2"]

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
    # no dangling entry_documents
    assert _count(conn, "entry_documents", "entry_id NOT IN (SELECT id FROM entries)") == 0


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
    assert _count(conn, "entry_documents", "entry_id NOT IN (SELECT id FROM entries)") == 0


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
    assert _count(conn, "entry_documents", "entry_id NOT IN (SELECT id FROM entries)") == 0


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
    assert _count(conn, "entry_documents") == 0
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
