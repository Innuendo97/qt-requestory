"""SyncState: tolerant load, atomic save, freshness rule, legacy import."""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, time
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
    st.mark_success("coll", when, last_remote_daily=7, last_downloaded=2, newest_day=date(2026, 9, 21))
    st.mark_success("svil", datetime(2026, 9, 20, 10, 0))

    raw = state_path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")  # UTF-8 without BOM
    data = json.loads(raw)
    assert data["envs"]["coll"]["last_success"] == "2026-09-21T18:45:12"
    assert data["envs"]["coll"]["last_remote_daily"] == 7
    assert data["envs"]["coll"]["last_downloaded"] == 2
    assert data["envs"]["coll"]["newest_day"] == "2026-09-21"
    assert data["envs"]["svil"]["newest_day"] is None
    assert [p.name for p in state_path.parent.iterdir()] == ["sync-state.json"]  # no .tmp left behind

    again = SyncState(state_path)
    again.load()
    assert again.get("coll") == EnvSyncState(when, 7, 2, date(2026, 9, 21))
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
    "last_success, now, newest_day, expected",
    [
        # after yesterday's compaction, and the compacted day is mirrored
        (datetime(2026, 9, 21, 19, 0), datetime(2026, 9, 22, 9, 30), date(2026, 9, 21), True),
        # before yesterday's compaction: fails rule 1 regardless of newest_day
        (datetime(2026, 9, 21, 17, 0), datetime(2026, 9, 22, 9, 30), None, False),
        # today's compaction already passed, synced before it: fails rule 1
        (datetime(2026, 9, 22, 17, 0), datetime(2026, 9, 22, 19, 0), None, False),
        # synced after today's compaction, and the compacted day is mirrored
        (datetime(2026, 9, 22, 18, 45), datetime(2026, 9, 22, 19, 0), date(2026, 9, 22), True),
        # boundary: last_success == compaction moment is fresh
        (datetime(2026, 9, 22, 18, 30), datetime(2026, 9, 22, 18, 30), date(2026, 9, 22), True),
        (None, datetime(2026, 9, 22, 9, 30), None, False),
        # synced after compaction but the compacted day itself was never mirrored (C1)
        (datetime(2026, 9, 21, 19, 0), datetime(2026, 9, 22, 9, 30), date(2026, 9, 20), False),
    ],
)
def test_is_fresh_matrix(state_path, last_success, now, newest_day, expected):
    st = SyncState(state_path)
    st.load()
    if last_success is not None:
        st.mark_success("coll", last_success, newest_day=newest_day)
    assert st.is_fresh("coll", now, COMPACTION) is expected


def _state(tmp_path, **kw):
    s = SyncState(tmp_path / "sync-state.json").load()
    s.mark_success("coll", **kw)
    return SyncState(tmp_path / "sync-state.json").load()  # round-trip through disk


def test_not_fresh_when_the_compacted_day_was_not_mirrored(tmp_path):
    # listing read 22/09 18:29 (only 21/09 on the server), run ended after compaction
    s = _state(tmp_path, when=datetime(2026, 9, 22, 18, 29), newest_day=date(2026, 9, 21))
    assert not s.is_fresh("coll", datetime(2026, 9, 23, 9, 0), COMPACTION)


def test_fresh_when_the_compacted_day_is_mirrored(tmp_path):
    s = _state(tmp_path, when=datetime(2026, 9, 22, 18, 45), newest_day=date(2026, 9, 22))
    assert s.is_fresh("coll", datetime(2026, 9, 23, 9, 0), COMPACTION)


def test_a_timestamp_in_the_future_is_never_fresh(tmp_path, caplog):
    s = _state(tmp_path, when=datetime(2027, 3, 1, 12, 0), newest_day=date(2027, 3, 1))
    assert not s.is_fresh("coll", datetime(2026, 9, 23, 9, 0), COMPACTION)
    assert "futuro" in caplog.text


def test_a_state_written_before_newest_day_existed_is_not_fresh(tmp_path):
    (tmp_path / "sync-state.json").write_text(
        '{"envs": {"coll": {"last_success": "2026-09-22T19:00:00", '
        '"last_remote_daily": 1, "last_downloaded": 1}}}', encoding="utf-8")
    s = SyncState(tmp_path / "sync-state.json").load()
    assert not s.is_fresh("coll", datetime(2026, 9, 23, 9, 0), COMPACTION)


def test_newest_day_none_is_never_fresh(state_path):
    # mark_success with no newest_day at all (e.g. an unreachable/errors path never calls it,
    # but a defensive caller might) must not be treated as fresh.
    st = SyncState(state_path)
    st.load()
    st.mark_success("coll", datetime(2026, 9, 22, 18, 45))
    assert not st.is_fresh("coll", datetime(2026, 9, 23, 9, 0), COMPACTION)


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


def test_legacy_import_on_read_only_mirror_does_not_raise(state_path, monkeypatch, caplog):
    """A read-only mirror (or AV holding the new file) must not turn a legacy
    import into a crash: the imported values are still usable this run, and
    the write is simply retried on the next successful save."""
    root = state_path.parent.parent
    root.mkdir(parents=True)
    legacy = root / ".last-sync.json"
    legacy.write_bytes(b"\xef\xbb\xbf" + json.dumps({"coll": "2026-09-21"}).encode("utf-8"))

    def _boom(self) -> None:
        raise PermissionError("mirror is read-only")

    monkeypatch.setattr(SyncState, "_save", _boom)
    st = SyncState(state_path)
    with caplog.at_level(logging.WARNING):
        result = st.load()

    assert result is st
    assert st.get("coll").last_success == datetime(2026, 9, 21, 12, 0)
    assert any(r.levelno == logging.WARNING for r in caplog.records)
    assert not state_path.exists()
