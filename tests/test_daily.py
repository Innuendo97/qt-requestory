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
    EntryName,
    LocalDailyFile,
    day_from_name,
    file_name,
    list_local_daily_files,
    local_path,
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


def test_list_local_daily_files_unknown_env_or_root(mirror, tmp_path: Path):
    assert list_local_daily_files(mirror.root, "nope") == []
    assert list_local_daily_files(tmp_path / "missing-root", "coll") == []


def test_local_daily_file_is_frozen(mirror):
    f = list_local_daily_files(mirror.root, "svil")[0]
    with pytest.raises(AttributeError):
        f.size = 0  # type: ignore[misc]


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
