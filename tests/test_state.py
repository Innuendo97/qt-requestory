"""SyncState: tolerant load, atomic save, freshness rule, legacy import."""
from __future__ import annotations

import json
import logging
from datetime import datetime, time
from pathlib import Path

import pytest

from qtrequestory.core.state import EnvSyncState, SyncState

COMPACTION = time(18, 30)


@pytest.fixture
def state_path(tmp_path: Path) -> Path:
    # <mirror_root>/.qtrequestory/sync-state.json, as in the design doc
    return tmp_path / "mirror" / ".qtrequestory" / "sync-state.json"


# ------------------------------------------------------------------- load ---

def test_missing_file_is_empty(state_path):
    st = SyncState(state_path)
    st.load()
    assert st.get("coll") == EnvSyncState()
    assert st.get("coll").last_success is None
    assert not state_path.exists()  # loading never creates anything


def test_corrupt_file_is_empty_with_warning(state_path, caplog):
    state_path.parent.mkdir(parents=True)
    state_path.write_text("{not json", encoding="utf-8")
    st = SyncState(state_path)
    with caplog.at_level(logging.WARNING):
        st.load()
    assert st.get("coll") == EnvSyncState()
    assert any(r.levelno == logging.WARNING and "sync-state.json" in r.getMessage() for r in caplog.records)


def test_wrong_shape_is_tolerated(state_path, caplog):
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps({"envs": {"coll": {"last_success": "not-a-date", "last_downloaded": "x"}}}),
                          encoding="utf-8")
    st = SyncState(state_path)
    with caplog.at_level(logging.WARNING):
        st.load()
    assert st.get("coll") == EnvSyncState()
    assert any(r.levelno == logging.WARNING for r in caplog.records)


# -------------------------------------------------------- save / roundtrip ---

def test_mark_success_roundtrip_is_iso_and_atomic(state_path):
    st = SyncState(state_path)
    st.load()
    when = datetime(2026, 9, 21, 18, 45, 12)
    st.mark_success("coll", when, last_remote_daily=7, last_downloaded=2)
    st.mark_success("svil", datetime(2026, 9, 20, 10, 0))

    raw = state_path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")  # UTF-8 without BOM
    data = json.loads(raw)
    assert data["envs"]["coll"]["last_success"] == "2026-09-21T18:45:12"
    assert data["envs"]["coll"]["last_remote_daily"] == 7
    assert data["envs"]["coll"]["last_downloaded"] == 2
    assert [p.name for p in state_path.parent.iterdir()] == ["sync-state.json"]  # no .tmp left behind

    again = SyncState(state_path)
    again.load()
    assert again.get("coll") == EnvSyncState(when, 7, 2)
    assert again.get("svil") == EnvSyncState(datetime(2026, 9, 20, 10, 0), 0, 0)
    assert again.get("prod") == EnvSyncState()


def test_mark_success_without_explicit_load_does_not_clobber_other_envs(state_path):
    st = SyncState(state_path)
    st.load()
    st.mark_success("coll", datetime(2026, 9, 21, 18, 45))

    other = SyncState(state_path)  # a consumer that forgets load()
    other.mark_success("svil", datetime(2026, 9, 21, 19, 0))

    check = SyncState(state_path)
    check.load()
    assert check.get("coll").last_success == datetime(2026, 9, 21, 18, 45)
    assert check.get("svil").last_success == datetime(2026, 9, 21, 19, 0)


# --------------------------------------------------------------- is_fresh ---

@pytest.mark.parametrize(
    "last_success, now, expected",
    [
        (datetime(2026, 9, 21, 19, 0), datetime(2026, 9, 22, 9, 30), True),    # after yesterday's compaction
        (datetime(2026, 9, 21, 17, 0), datetime(2026, 9, 22, 9, 30), False),   # before yesterday's compaction
        (datetime(2026, 9, 22, 17, 0), datetime(2026, 9, 22, 19, 0), False),   # today's compaction already passed
        (datetime(2026, 9, 22, 18, 45), datetime(2026, 9, 22, 19, 0), True),   # synced after today's compaction
        (datetime(2026, 9, 22, 18, 30), datetime(2026, 9, 22, 18, 30), True),  # boundary: >= is fresh
        (None, datetime(2026, 9, 22, 9, 30), False),
    ],
)
def test_is_fresh_matrix(state_path, last_success, now, expected):
    st = SyncState(state_path)
    st.load()
    if last_success is not None:
        st.mark_success("coll", last_success)
    assert st.is_fresh("coll", now, COMPACTION) is expected


# ---------------------------------------------------------- legacy import ---

def test_legacy_last_sync_json_is_imported_once(state_path, caplog):
    root = state_path.parent.parent
    root.mkdir(parents=True)
    legacy = root / ".last-sync.json"
    legacy_bytes = b"\xef\xbb\xbf" + json.dumps({"svil": "2026-09-21", "coll": "2026-09-20"}).encode("utf-8")
    legacy.write_bytes(legacy_bytes)

    st = SyncState(state_path)
    with caplog.at_level(logging.INFO):
        st.load()

    assert st.get("coll").last_success == datetime(2026, 9, 20, 12, 0)
    assert st.get("svil").last_success == datetime(2026, 9, 21, 12, 0)
    assert st.get("coll").last_downloaded == 0
    assert state_path.exists(), "the new state file is written right after the import"
    assert legacy.read_bytes() == legacy_bytes, "legacy file must be left untouched"

    # second load reads the new file, no re-import: mutate the legacy file and check it is ignored
    legacy.write_bytes(b"\xef\xbb\xbf" + json.dumps({"coll": "2000-01-01"}).encode("utf-8"))
    again = SyncState(state_path)
    again.load()
    assert again.get("coll").last_success == datetime(2026, 9, 20, 12, 0)


def test_legacy_import_is_not_fresh_relative_to_compaction(state_path):
    root = state_path.parent.parent
    root.mkdir(parents=True)
    (root / ".last-sync.json").write_text(json.dumps({"coll": "2026-09-21"}), encoding="utf-8-sig")
    st = SyncState(state_path)
    st.load()
    # noon on the 21st is before the 21st's 18:30 compaction: the first run after the migration re-syncs
    assert st.is_fresh("coll", datetime(2026, 9, 22, 9, 30), COMPACTION) is False


def test_legacy_import_skips_garbage_entries(state_path, caplog):
    root = state_path.parent.parent
    root.mkdir(parents=True)
    (root / ".last-sync.json").write_text(json.dumps({"coll": "2026-09-21", "svil": "yesterday", "x": 5}),
                                          encoding="utf-8-sig")
    st = SyncState(state_path)
    with caplog.at_level(logging.WARNING):
        st.load()
    assert st.get("coll").last_success == datetime(2026, 9, 21, 12, 0)
    assert st.get("svil") == EnvSyncState()


def test_corrupt_legacy_file_is_ignored(state_path, caplog):
    root = state_path.parent.parent
    root.mkdir(parents=True)
    (root / ".last-sync.json").write_text("garbage", encoding="utf-8")
    st = SyncState(state_path)
    with caplog.at_level(logging.WARNING):
        st.load()
    assert st.get("coll") == EnvSyncState()
    assert any(r.levelno == logging.WARNING for r in caplog.records)
