"""Fix round 1: "only verified originals, never anything in the archive".

* the archive reached through another path (a junction) is still the archive;
* recycling re-checks every original against its canonical copy right before
  the shell call, and accepts only records the import produced.
The shell delete is always mocked.
"""
from __future__ import annotations

import os
import subprocess
from datetime import date
from pathlib import Path

import pytest

from qtrequestory.core import importer
from qtrequestory.core.archive import AMBIGUOUS, DUPLICATE, IGNORED, IMPORTABLE, FoundLog, discover
from qtrequestory.core.daily import local_path
from qtrequestory.core.importer import VerifiedOriginal, run_import, send_to_recycle_bin
from qtrequestory.core.archive_names import day_from_parts
from tests.test_archive import LOG, LOG2, put

TODAY = date(2026, 9, 24)
D = date(2026, 9, 22)


def scan(root: Path, canon: Path):
    return discover(root, ("coll", "svil"), {}, canonical_root=canon, today=TODAY)


@pytest.fixture
def shell(monkeypatch) -> list[str]:
    calls: list[str] = []

    def fake(path: str):
        calls.append(path)
        os.remove(path)
        return 0, False

    monkeypatch.setattr(importer, "_shell_delete", fake)
    monkeypatch.setattr(importer, "_drive_type", lambda p: importer.DRIVE_FIXED)
    monkeypatch.setattr(importer.sys, "platform", "win32")
    return calls


def _junction(link: Path, target: Path) -> None:
    if os.name != "nt":
        pytest.skip("junctions are a Windows thing")
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)


# ------------------------------------------------------ the archive by alias ---

def test_a_mirror_scanned_through_a_junction_is_still_the_archive(tmp_path, shell):
    canon = tmp_path / "mirror"
    real = put(canon, "coll/2026/09/20260922.txt", LOG)
    alias = tmp_path / "alias"
    _junction(alias, canon)
    report = scan(alias, canon)
    assert report.items == ()                                  # canonical: silent
    # and even a hand-made report cannot get it verified or recycled
    item = FoundLog("coll/2026/09/20260922.txt", alias / "coll/2026/09/20260922.txt", len(LOG),
                    real.stat().st_mtime_ns, "coll", D, DUPLICATE, "", local_path(canon, "coll", D))
    forged = type(report)(alias, canon, (item,))
    result = run_import(forged, canon)
    assert result.verified == [] and result.skipped == 0 and result.errors == []
    record = VerifiedOriginal(item.path, item.size, item.mtime_ns, item.dest)
    failures = send_to_recycle_bin([record], canonical_root=canon)
    assert [p for p, _ in failures] == [item.path]
    assert shell == [] and real.read_bytes() == LOG


def test_an_importable_that_is_the_canonical_file_itself_is_skipped(tmp_path):
    canon = tmp_path / "mirror"
    real = put(canon, "coll/2026/09/20260922.txt", LOG)
    alias = tmp_path / "alias"
    _junction(alias, canon)
    item = FoundLog("x", alias / "coll/2026/09/20260922.txt", len(LOG), real.stat().st_mtime_ns,
                    "coll", D, IMPORTABLE, "", local_path(canon, "coll", D))
    result = run_import(type(scan(tmp_path / "none", canon))(alias, canon, (item,)), canon)
    assert (result.copied, result.skipped, result.verified, result.errors) == (0, 0, [], [])
    assert real.read_bytes() == LOG


def test_recycle_refuses_the_canonical_file_under_any_spelling(tmp_path, shell):
    canon = tmp_path / "mirror"
    real = put(canon, "coll/2026/09/20260922.txt", LOG)
    alias = tmp_path / "alias"
    _junction(alias, canon)
    elsewhere = tmp_path / "old"
    elsewhere.mkdir()
    record = VerifiedOriginal(alias / "coll/2026/09/20260922.txt", len(LOG), real.stat().st_mtime_ns,
                              local_path(canon, "coll", D))
    assert send_to_recycle_bin([record], canonical_root=canon)[0][0] == record.path
    assert shell == []


# ------------------------------------------------ recycle re-checks everything ---

def _imported(tmp_path) -> tuple[Path, VerifiedOriginal]:
    canon = tmp_path / "mirror"
    put(tmp_path / "old", "coll/20260922.txt", LOG)
    result = run_import(scan(tmp_path / "old", canon), canon)
    assert result.copied == 1 and len(result.verified) == 1
    rec = result.verified[0]
    assert isinstance(rec, VerifiedOriginal)
    assert rec.dest == local_path(canon, "coll", D) and rec.size == len(LOG)
    assert result.verified_paths == [rec.path]
    return canon, rec


def test_a_verified_original_is_recycled(tmp_path, shell):
    canon, rec = _imported(tmp_path)
    assert send_to_recycle_bin([rec], canonical_root=canon) == []
    assert shell == [str(rec.path)]


def test_an_original_changed_after_verification_is_not_recycled(tmp_path, shell):
    canon, rec = _imported(tmp_path)
    with open(rec.path, "ab") as f:
        f.write(b"probe\n")
    failures = send_to_recycle_bin([rec], canonical_root=canon)
    assert [p for p, _ in failures] == [rec.path] and shell == []


def test_an_original_rewritten_with_the_same_size_and_mtime_is_not_recycled(tmp_path, shell):
    canon, rec = _imported(tmp_path)
    data = bytearray(rec.path.read_bytes())
    data[10] ^= 1
    rec.path.write_bytes(bytes(data))
    os.utime(rec.path, ns=(rec.mtime_ns, rec.mtime_ns))
    assert [p for p, _ in send_to_recycle_bin([rec], canonical_root=canon)] == [rec.path]
    assert shell == []


def test_a_canonical_copy_gone_or_changed_blocks_the_recycle(tmp_path, shell):
    canon, rec = _imported(tmp_path)
    rec.dest.write_bytes(b"### other.json\n{}\n")
    assert [p for p, _ in send_to_recycle_bin([rec], canonical_root=canon)] == [rec.path]
    rec.dest.unlink()
    assert [p for p, _ in send_to_recycle_bin([rec], canonical_root=canon)] == [rec.path]
    assert shell == [] and rec.path.exists()


def test_a_canonical_copy_that_grew_still_holds_the_original(tmp_path, shell):
    canon, rec = _imported(tmp_path)
    rec.dest.write_bytes(LOG2)
    assert send_to_recycle_bin([rec], canonical_root=canon) == []


def test_recycle_accepts_only_verified_records(tmp_path, shell):
    canon = tmp_path / "mirror"
    loose = put(tmp_path / "old", "coll/20260922.txt", LOG)
    failures = send_to_recycle_bin([loose], canonical_root=canon)  # type: ignore[list-item]
    assert [p for p, _ in failures] == [loose] and shell == [] and loose.exists()


def test_a_source_changed_during_the_copy_is_not_renamed(tmp_path, monkeypatch):
    canon = tmp_path / "mirror"
    src = put(tmp_path / "old", "coll/20260922.txt", LOG)
    report = scan(tmp_path / "old", canon)
    real_copy = importer._copy_to_part

    def copy_then_touch(s, part, cancel):
        out = real_copy(s, part, cancel)
        with open(src, "ab") as f:
            f.write(b"late\n")
        return out

    monkeypatch.setattr(importer, "_copy_to_part", copy_then_touch)
    result = run_import(report, canon)
    assert result.copied == 0 and result.verified == [] and len(result.errors) == 1
    assert not local_path(canon, "coll", D).exists()
    assert not list(canon.rglob("*.part"))


# ------------------------------------------------------------------ minors ---

@pytest.mark.parametrize("name", ["123456789.txt", "log_2026092.txt", "1695370000123.txt", "20190101.txt"])
def test_a_long_digit_run_that_is_not_a_date_is_ambiguous(name):
    assert day_from_parts([name, "20260922"], today=TODAY) == (None, AMBIGUOUS)


def test_short_numbers_in_the_name_still_fall_back_to_the_folder():
    assert day_from_parts(["access (2).txt", "20260922"], today=TODAY) == (D, None)
    assert day_from_parts(["22.txt", "09", "2026"], today=TODAY) == (D, None)


@pytest.mark.parametrize("rel", ["20260922/coll.txt", "coll/20260922.log", "coll/2026/09/22.txt"])
def test_a_0_byte_file_is_an_empty_day_only_with_the_date_in_a_txt_name(tmp_path, rel):
    put(tmp_path / "old", rel, b"")
    item = scan(tmp_path / "old", tmp_path / "mirror").items[0]
    assert item.status == IGNORED and "vuoto" in item.reason


@pytest.mark.parametrize("rel", ["coll/20260922.txt", "coll/20260922"])
def test_a_0_byte_file_named_after_its_day_is_an_empty_day(tmp_path, rel):
    put(tmp_path / "old", rel, b"")
    assert scan(tmp_path / "old", tmp_path / "mirror").items[0].status == IMPORTABLE
