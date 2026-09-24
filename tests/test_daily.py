"""core/daily.py: day/file-name helpers, local listing and entry-name parsing."""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

from qtrequestory.core.daily import (
    CALL_ID_RE,
    DAILY_NAME_RE,
    UUID_RE,
    CoverageDays,
    EntryName,
    LocalDailyFile,
    coverage_days,
    day_from_name,
    file_name,
    list_local_daily_files,
    local_path,
    missing_weekdays,
    parse_entry_name,
    relative_path,
)
from tests.conftest import FDI_A, FDI_C, KEY_CTE, KEY_NUMERIC

CALL_ID = "1a2b3c0200000031"


# ------------------------------------------------------------ day / names ---

def test_day_from_name_valid():
    assert day_from_name("20260921.txt") == date(2026, 9, 21)


@pytest.mark.parametrize("name", [
    "2026092.txt",          # 7 digits
    "20261340.txt",         # month 13
    "x20260921.txt",        # junk prefix
    "20260921.txt.part",    # partial download
    "20260921.TXT",         # regex is case sensitive by design
    "",
])
def test_day_from_name_invalid(name):
    assert day_from_name(name) is None


def test_daily_name_re_and_file_name_round_trip():
    assert re.match(DAILY_NAME_RE, "20260921.txt").group("day") == "20260921"
    assert file_name(date(2026, 9, 21)) == "20260921.txt"
    assert day_from_name(file_name(date(2026, 1, 5))) == date(2026, 1, 5)


def test_local_and_relative_path_layout(tmp_path: Path):
    day = date(2026, 9, 21)
    assert local_path(tmp_path, "coll", day) == tmp_path / "coll" / "2026" / "09" / "20260921.txt"
    assert relative_path("coll", day) == "coll/2026/09/20260921.txt"
    assert relative_path("svil", date(2026, 1, 5)) == "svil/2026/01/20260105.txt"


# ----------------------------------------------------------- local listing ---

def test_list_local_daily_files_newest_first_ignoring_part(mirror):
    files = list_local_daily_files(mirror.root, "coll")
    assert [f.day for f in files] == [date(2026, 9, 18), date(2026, 9, 15), date(2026, 8, 3)]
    for f in files:
        assert isinstance(f, LocalDailyFile)
        assert f.env == "coll"
        assert f.path == mirror.files[("coll", f.day)]
        assert f.path == local_path(mirror.root, "coll", f.day)
        assert f.size == f.path.stat().st_size > 0
        assert f.mtime_ns == f.path.stat().st_mtime_ns > 0
    assert all(not f.path.name.endswith(".part") for f in files)


def test_list_local_daily_files_ignores_junk_names(mirror):
    junk_dir = mirror.root / "coll" / "2026" / "09"
    (junk_dir / "notes.txt").write_text("x")
    (junk_dir / "20261340.txt").write_text("x")              # invalid date
    (junk_dir / "x20260919.txt").write_text("x")
    (mirror.root / "coll" / "20260920.txt").write_text("x")  # wrong depth
    files = list_local_daily_files(mirror.root, "coll")
    assert [f.day for f in files] == [date(2026, 9, 18), date(2026, 9, 15), date(2026, 8, 3)]


def test_the_shrunk_sidecar_is_not_indexed(mirror):
    """A ``<day>.txt.remote-<size>`` sidecar (the smaller remote copy stashed
    next to a mirrored day, see sync.py's "shrunk" handling) must never be
    picked up as if it were a daily file: neither by the bare regex nor by
    the directory listing the indexer walks."""
    sidecar = mirror.root / "coll" / "2026" / "09" / "20260918.txt.remote-1200"
    sidecar.write_bytes(b"remote copy")

    assert day_from_name(sidecar.name) is None
    files = list_local_daily_files(mirror.root, "coll")
    assert [f.day for f in files] == [date(2026, 9, 18), date(2026, 9, 15), date(2026, 8, 3)]
    assert sidecar.name not in [f.path.name for f in files]


def test_list_local_daily_files_keeps_only_the_canonical_path(mirror):
    """F4: a file is the mirror's only at ``<env>/YYYY/MM/YYYYMMDD.txt``. An
    unpadded month or a day filed under the wrong month is the archive
    importer's business, never the index's: the builder keeps one file per
    day and would flip between the two copies forever."""
    base = mirror.root / "coll" / "2026"
    (base / "8").mkdir()
    (base / "8" / "20260803.txt").write_text("x")          # unpadded month, same day
    (base / "09" / "20260801.txt").write_text("x")         # August day filed under 09
    (base / "10").mkdir()
    (base / "10" / "20260921.txt").write_text("x")         # a September day under 10
    files = list_local_daily_files(mirror.root, "coll")
    assert [f.day for f in files] == [date(2026, 9, 18), date(2026, 9, 15), date(2026, 8, 3)]
    assert all(f.path == local_path(mirror.root, "coll", f.day) for f in files)


def test_list_local_daily_files_unknown_env_or_root(mirror, tmp_path: Path):
    assert list_local_daily_files(mirror.root, "nope") == []
    assert list_local_daily_files(tmp_path / "missing-root", "coll") == []


def test_local_daily_file_is_frozen(mirror):
    f = list_local_daily_files(mirror.root, "svil")[0]
    with pytest.raises(AttributeError):
        f.size = 0  # type: ignore[misc]


# ------------------------------------------------------------------ gaps ---

def test_missing_weekdays_ignores_weekends():
    # Mon 2026-09-14 .. Sun 2026-09-20; only Tue and Thu are present.
    present = {date(2026, 9, 15), date(2026, 9, 17)}
    result = missing_weekdays(present, date(2026, 9, 14), date(2026, 9, 20))
    assert result == [date(2026, 9, 14), date(2026, 9, 16), date(2026, 9, 18)]


def test_missing_weekdays_empty_when_everything_present():
    present = {date(2026, 9, 14), date(2026, 9, 15), date(2026, 9, 16), date(2026, 9, 17), date(2026, 9, 18)}
    assert missing_weekdays(present, date(2026, 9, 14), date(2026, 9, 18)) == []


def test_missing_weekdays_start_after_end_is_empty():
    assert missing_weekdays(set(), date(2026, 9, 18), date(2026, 9, 14)) == []


def test_coverage_days_window_excludes_today():
    """The window is [today - days + 1, today - 1]: today is never in it,
    because today's calls only land on the server tomorrow."""
    today = date(2026, 9, 22)  # Tuesday, itself a weekday, but never in the window
    present = {date(2026, 9, 10)}  # first_local far before the window
    result = coverage_days(present, days=3, today=today)
    assert result.missing == (date(2026, 9, 21),)  # the Monday just before today
    assert today not in result.missing


def test_coverage_days_nothing_local_flags_nothing():
    """An empty mirror has no basis to say when the archive "should have"
    started, so no day is ever reported missing."""
    result = coverage_days(set(), days=30, today=date(2026, 9, 22))
    assert result.first_local is None
    assert result.missing == ()
    assert result.present == frozenset()


def test_coverage_days_does_not_flag_days_before_the_archive_began():
    """The mirror started on 2026-09-16 (a Wednesday). A weekday well before
    that, inside the requested 30-day window, must not be reported as a gap —
    there was no archive yet to have mirrored it."""
    present = {date(2026, 9, 16), date(2026, 9, 17), date(2026, 9, 18)}
    today = date(2026, 9, 22)  # Tuesday; window is [2026-08-24, 2026-09-21]
    result = coverage_days(present, days=30, today=today)
    assert result.first_local == date(2026, 9, 16)
    assert result.present == frozenset(present)
    # 2026-09-21 (Monday) is the one weekday in [first_local, today-1] with no
    # local file.
    assert result.missing == (date(2026, 9, 21),)
    # A weekday before the archive began (well within the 30-day window) is
    # NOT reported, even though it has no local file either.
    before_archive = date(2026, 8, 25)  # Tuesday
    assert before_archive.weekday() < 5
    assert before_archive not in result.missing


def test_coverage_days_is_frozen():
    result = coverage_days(set(), days=1, today=date(2026, 9, 22))
    with pytest.raises(AttributeError):
        result.first_local = date(2026, 9, 1)  # type: ignore[misc]
    assert isinstance(result, CoverageDays)


# -------------------------------------------------------- entry name parse ---

UPPER_FDI = FDI_A.upper()


@pytest.mark.parametrize("raw, expected", [
    # canonical UUID_KEY_ID
    (f"{FDI_A}_{KEY_CTE}_{CALL_ID}", (FDI_A, KEY_CTE, CALL_ID, True)),
    # correlationId_vuoto_KEY_ID: no FDI at all
    ("correlationId_vuoto_MOD_TEST_R_1a2b3c0300000000", (None, "MOD_TEST_R", "1a2b3c0300000000", False)),
    # UUID-t15_KEY_ID: test suffix keeps the fdi token but it is not canonical
    (f"{FDI_C}-t15_{KEY_CTE}_1a2b3c0200000099", (f"{FDI_C}-t15", KEY_CTE, "1a2b3c0200000099", False)),
    (f"{FDI_C}-test-12_{KEY_CTE}_1a2b3c0200000098", (f"{FDI_C}-test-12", KEY_CTE, "1a2b3c0200000098", False)),
    # numeric key prefix stays part of the key
    (f"{FDI_A}_{KEY_NUMERIC}_{CALL_ID}", (FDI_A, KEY_NUMERIC, CALL_ID, True)),
    (f"{FDI_A}_3_1_REQUEST_X_{CALL_ID}", (FDI_A, "3_1_REQUEST_X", CALL_ID, True)),
    # uppercase UUID is lowercased and still canonical
    (f"{UPPER_FDI}_{KEY_CTE}_{CALL_ID}", (FDI_A, KEY_CTE, CALL_ID, True)),
    # missing id
    (f"{FDI_A}_{KEY_CTE}", (FDI_A, KEY_CTE, None, False)),
    # id too short / not lowercase hex is not an id: stays inside the key
    (f"{FDI_A}_{KEY_CTE}_10b6016b", (FDI_A, f"{KEY_CTE}_10b6016b", None, False)),
    (f"{FDI_A}_{KEY_CTE}_10B6016B00000031", (FDI_A, f"{KEY_CTE}_10B6016B00000031", None, False)),
    # no underscore at all
    ("garbage", (None, "garbage", None, False)),
    (FDI_A, (None, FDI_A, None, False)),
    # correlationId_vuoto without id
    ("correlationId_vuoto_MOD_TEST_R", (None, "MOD_TEST_R", None, False)),
])
def test_parse_entry_name(raw, expected):
    fdi, key, call_id, well_formed = expected
    got = parse_entry_name(raw)
    assert got == EntryName(raw=raw, fdi=fdi, template_key=key, call_id=call_id, well_formed=well_formed)


def test_parse_entry_name_is_frozen():
    e = parse_entry_name(f"{FDI_A}_{KEY_CTE}_{CALL_ID}")
    with pytest.raises(AttributeError):
        e.fdi = None  # type: ignore[misc]


def test_exported_regexes():
    assert re.match(UUID_RE, FDI_A)
    assert not re.match(UUID_RE, FDI_A.upper())          # applied after lowercasing
    assert not re.match(UUID_RE, FDI_A + "-t15")
    assert re.search(CALL_ID_RE, f"x_{CALL_ID}").group(1) == CALL_ID
    assert re.search(CALL_ID_RE, f"x_{CALL_ID}.json") is None
