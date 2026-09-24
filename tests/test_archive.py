"""core/archive.py: finding logs in any folder layout and classifying them.

Every tree here is synthetic (uuid-shaped FDIs from conftest, MOD_TEST keys).
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest

from qtrequestory.core import archive
from qtrequestory.core.archive import (
    CONFLICT,
    DUPLICATE,
    IGNORED,
    IMPORTABLE,
    NEEDS_ENV,
    ArchiveReport,
    FoundLog,
    compare_files,
    discover,
)
from qtrequestory.core.config import IGNORE_FOLDER
from qtrequestory.core.daily import local_path
from tests.conftest import FDI_A, FDI_B, KEY_CTE, entry_name, synthetic_body

TODAY = date(2026, 9, 24)
D = date(2026, 9, 22)
ENVS = ("svil", "coll")


def log_bytes(*fdis: str, crlf: bool = False) -> bytes:
    nl = b"\r\n" if crlf else b"\n"
    out = b""
    for i, fdi in enumerate(fdis):
        out += b"### " + entry_name(fdi, "MOD_TEST_A", f"1a2b3c02000000{i:02d}").encode() + b".json" + nl
        out += synthetic_body(fdi, "MOD_TEST_A") + nl
    return out


LOG = log_bytes(FDI_A)
LOG2 = log_bytes(FDI_A, FDI_B)          # LOG is a strict prefix of LOG2
OTHER = log_bytes(FDI_B)                # same size as LOG, different bytes


def put(root: Path, rel: str, data: bytes = LOG) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def scan(root: Path, envs=ENVS, folder_envs=None, canonical: Path | None = None) -> ArchiveReport:
    return discover(root, envs, folder_envs or {}, canonical_root=canonical, today=TODAY)


def one(report: ArchiveReport, rel: str) -> FoundLog:
    found = [f for f in report.items if f.rel_path == rel]
    assert len(found) == 1, [f.rel_path for f in report.items]
    return found[0]


@pytest.fixture
def src(tmp_path: Path) -> Path:
    return tmp_path / "old"


@pytest.fixture
def canon(tmp_path: Path) -> Path:
    return tmp_path / "mirror"


# ---------------------------------------------------------------- layouts ---

@pytest.mark.parametrize("rel, env", [
    ("20260922.txt", None),                    # flat, env unknown with 2 envs
    ("coll/20260922.txt", "coll"),
    ("2026/09/svil/20260922.txt", "svil"),
    ("svil_20260922.txt", "svil"),
    ("coll/2026-09-22.log", "coll"),
    ("coll/22-09-2026.txt", "coll"),
    ("coll/22092026.txt", "coll"),
    ("coll/2026/09/22.txt", "coll"),
    ("coll/2026/9/20260922.txt", "coll"),      # a misplaced mirror layout
    ("estratto (1)/logs/svil/20260922.txt", "svil"),  # zip extracted in nested folders
    ("coll/20260922", "coll"),                 # no extension at all
])
def test_every_layout_is_recognised(src, canon, rel, env):
    put(src, rel)
    item = one(scan(src, canonical=canon), rel)
    assert item.day == D
    assert item.env == env
    assert item.size == len(LOG) and item.path == src / rel
    if env is None:
        assert item.status == NEEDS_ENV and item.dest is None
    else:
        assert item.status == IMPORTABLE
        assert item.dest == local_path(canon, env, D)


def test_rel_path_and_rel_dir_use_forward_slashes(src):
    put(src, "a/b/coll/20260922.txt")
    item = one(scan(src), "a/b/coll/20260922.txt")
    assert item.rel_dir == "a/b/coll"
    assert item.mtime_ns == (src / "a/b/coll/20260922.txt").stat().st_mtime_ns


def test_a_single_configured_env_is_assigned_automatically(src, canon):
    put(src, "20260922.txt")
    item = one(scan(src, envs=("prod",), canonical=canon), "20260922.txt")
    assert (item.env, item.status) == ("prod", IMPORTABLE)


def test_configured_names_whatever_they_are(src, canon):
    put(src, "Collaudo/20260922.txt")
    put(src, "PROD-vecchi/20260921.txt")
    report = scan(src, envs=("prod", "collaudo"), canonical=canon)
    assert one(report, "Collaudo/20260922.txt").env == "collaudo"
    assert one(report, "PROD-vecchi/20260921.txt").env == "prod"


def test_a_tie_needs_the_user(src):
    put(src, "svil e coll/20260922.txt")
    assert one(scan(src), "svil e coll/20260922.txt").status == NEEDS_ENV


def test_no_configured_env_means_nothing_is_importable(src):
    put(src, "coll/20260922.txt")
    assert one(scan(src, envs=()), "coll/20260922.txt").status == NEEDS_ENV


# ------------------------------------------------------------ folder_envs ---

def test_folder_envs_beats_the_tokens_and_the_deepest_wins(src, canon):
    put(src, "misti/coll/20260922.txt")
    put(src, "misti/altro/20260921.txt")
    report = scan(src, folder_envs={"misti": "svil", "misti/coll": "SVIL"}, canonical=canon)
    assert one(report, "misti/coll/20260922.txt").env == "svil"
    assert one(report, "misti/altro/20260921.txt").env == "svil"


def test_folder_envs_ignore(src):
    put(src, "scarti/coll/20260922.txt")
    item = one(scan(src, folder_envs={"scarti": IGNORE_FOLDER}), "scarti/coll/20260922.txt")
    assert item.status == IGNORED and item.dest is None


def test_folder_envs_for_the_root_and_absolute_keys(src, canon):
    put(src, "20260922.txt")
    put(src, "sub/20260921.txt")
    assert one(scan(src, folder_envs={"": "coll"}, canonical=canon), "20260922.txt").env == "coll"
    report = scan(src, folder_envs={str(src / "sub"): "svil"}, canonical=canon)
    assert one(report, "sub/20260921.txt").env == "svil"


def test_folder_envs_naming_an_unconfigured_env_is_not_trusted(src):
    put(src, "x/20260922.txt")
    assert one(scan(src, folder_envs={"x": "prod"}), "x/20260922.txt").status == NEEDS_ENV


def test_the_scanned_root_name_is_the_last_hint(tmp_path, canon):
    root = tmp_path / "log svil"
    put(root, "20260922.txt")
    assert one(scan(root, canonical=canon), "20260922.txt").env == "svil"


# ----------------------------------------------------------- ignored files ---

@pytest.mark.parametrize("rel, data, reason", [
    ("coll/20260922.zip", b"PK\x03\x04", "archivio compresso: estrailo nella cartella"),
    ("coll/20260922.txt.gz", b"\x1f\x8b", "archivio compresso: estrailo nella cartella"),
    ("coll/20260922.7z", b"7z", "archivio compresso: estrailo nella cartella"),
    ("coll/note-20260922.md", b"### Titolo\n\nappunti\n", "non è un log di chiamate"),
    ("coll/20260922.txt", b"   \n\t\n", "non è un log di chiamate"),
    ("coll/20260922.txt", b"\x00\x01binary", "non è un log di chiamate"),
    ("coll/notes.txt", LOG, "nessuna data nel nome"),
    ("coll/20260921_20260922.txt", LOG, "data ambigua"),
    ("coll/20190101.txt", LOG, "data ambigua"),           # a long digit run, not a date
])
def test_ignored_with_a_reason(src, rel, data, reason):
    put(src, rel, data)
    item = one(scan(src), rel)
    assert (item.status, item.reason) == (IGNORED, reason)


def test_a_zip_is_never_opened(src, monkeypatch):
    put(src, "coll/20260922.zip", b"PK")
    opened: list[str] = []
    real_open = archive._read_head

    def spy(path):
        opened.append(str(path))
        return real_open(path)

    monkeypatch.setattr(archive, "_read_head", spy)
    scan(src)
    assert opened == []


def test_a_bom_and_leading_blank_lines_are_still_a_log(src, canon):
    put(src, "coll/20260922.txt", b"\xef\xbb\xbf\r\n\r\n" + LOG)
    assert one(scan(src, canonical=canon), "coll/20260922.txt").status == IMPORTABLE


def test_a_0_byte_file_with_day_and_env_is_an_empty_day(src, canon):
    put(src, "coll/20260922.txt", b"")
    item = one(scan(src, canonical=canon), "coll/20260922.txt")
    assert item.status == IMPORTABLE and item.size == 0


def test_skipped_silently_app_files_hidden_and_system_dirs(src, canon):
    put(src, "coll/20260922.txt.part")
    put(src, "coll/20260922.txt.remote-1200")
    put(src, ".git/20260922.txt")
    put(src, "$RECYCLE.BIN/coll/20260922.txt")
    put(src, "System Volume Information/20260922.txt")
    assert scan(src, canonical=canon).items == ()


@pytest.mark.skipif(os.name != "nt", reason="junctions are a Windows thing")
def test_junctions_are_not_followed(src, tmp_path):
    import subprocess
    target = tmp_path / "elsewhere"
    put(target, "coll/20260922.txt")
    src.mkdir()
    subprocess.run(["cmd", "/c", "mklink", "/J", str(src / "link"), str(target)],
                   check=True, capture_output=True)
    assert scan(src).items == ()


def test_symlinks_are_not_followed(src, tmp_path):
    target = tmp_path / "elsewhere"
    put(target, "coll/20260922.txt")
    src.mkdir()
    try:
        os.symlink(target, src / "link", target_is_directory=True)
        os.symlink(target / "coll" / "20260922.txt", src / "coll-20260921.txt")
    except OSError:
        pytest.skip("no symlink privilege")
    assert scan(src).items == ()


def test_files_already_at_their_canonical_path_are_silent(canon):
    put(canon, "coll/2026/09/20260922.txt")
    put(canon, ".qtrequestory/20260922.txt")
    put(canon, "coll/2026/9/20260921.txt")        # misplaced: reported
    report = scan(canon, canonical=canon)
    assert [f.rel_path for f in report.items] == ["coll/2026/9/20260921.txt"]
    assert report.items[0].status == IMPORTABLE


# ------------------------------------------------- against the canonical file ---

def test_identical_to_the_archive_is_a_duplicate(src, canon):
    put(canon, "coll/2026/09/20260922.txt", LOG)
    put(src, "coll/20260922.txt", LOG)
    item = one(scan(src, canonical=canon), "coll/20260922.txt")
    assert item.status == DUPLICATE and item.dest == local_path(canon, "coll", D)


def test_bigger_with_the_archive_as_prefix_is_importable(src, canon):
    put(canon, "coll/2026/09/20260922.txt", LOG)
    put(src, "coll/20260922.txt", LOG2)
    item = one(scan(src, canonical=canon), "coll/20260922.txt")
    assert (item.status, item.reason) == (IMPORTABLE, "più completo della copia in archivio")


def test_an_empty_archive_day_is_a_prefix_of_anything(src, canon):
    put(canon, "coll/2026/09/20260922.txt", b"")
    put(src, "coll/20260922.txt", LOG)
    assert one(scan(src, canonical=canon), "coll/20260922.txt").status == IMPORTABLE


def test_a_prefix_of_the_archive_is_a_duplicate(src, canon):
    put(canon, "coll/2026/09/20260922.txt", LOG2)
    put(src, "coll/20260922.txt", LOG)
    item = one(scan(src, canonical=canon), "coll/20260922.txt")
    assert (item.status, item.reason) == (DUPLICATE, "l'archivio ha già una copia più completa")


@pytest.mark.parametrize("archived, imported", [(LOG, OTHER), (LOG2, OTHER), (OTHER, LOG2)])
def test_divergent_copies_are_a_conflict(src, canon, archived, imported):
    put(canon, "coll/2026/09/20260922.txt", archived)
    put(src, "coll/20260922.txt", imported)
    item = one(scan(src, canonical=canon), "coll/20260922.txt")
    assert (item.status, item.reason) == (CONFLICT, "copie diverse dello stesso giorno")


def test_crlf_converted_copy_is_a_conflict_unless_the_archive_lacks_the_day(src, canon):
    """Documented rule: equal modulo CRLF is NOT equal bytes. Replacing either
    copy with the other would change bodies the index points at byte-exactly,
    so the user decides; only a day the archive lacks is imported as is."""
    put(canon, "coll/2026/09/20260922.txt", log_bytes(FDI_A))
    put(src, "coll/20260922.txt", log_bytes(FDI_A, crlf=True))
    put(src, "coll/20260921.txt", log_bytes(FDI_A, crlf=True))
    report = scan(src, canonical=canon)
    assert one(report, "coll/20260922.txt").status == CONFLICT
    assert one(report, "coll/20260921.txt").status == IMPORTABLE


# ------------------------------------------------ two imports of one day ---

def test_two_copies_keep_the_larger_when_the_smaller_is_its_prefix(src, canon):
    put(src, "a/coll/20260922.txt", LOG)
    put(src, "b/coll/20260922.txt", LOG2)
    report = scan(src, canonical=canon)
    assert one(report, "b/coll/20260922.txt").status == IMPORTABLE
    small = one(report, "a/coll/20260922.txt")
    assert small.status == DUPLICATE and small.dest == local_path(canon, "coll", D)


def test_two_identical_copies(src, canon):
    put(src, "a/coll/20260922.txt", LOG)
    put(src, "b/coll/20260922.txt", LOG)
    report = scan(src, canonical=canon)
    assert sorted(f.status for f in report.items) == [DUPLICATE, IMPORTABLE]


def test_two_divergent_copies_are_both_conflicts(src, canon):
    put(src, "a/coll/20260922.txt", LOG)
    put(src, "b/coll/20260922.txt", OTHER)
    put(src, "c/coll/20260922.txt", LOG2)        # LOG is its prefix, OTHER is not
    report = scan(src, canonical=canon)
    assert {f.status for f in report.items} == {CONFLICT}


def test_group_and_archive_the_larger_is_a_duplicate_so_are_its_prefixes(src, canon):
    put(canon, "coll/2026/09/20260922.txt", LOG2)
    put(src, "a/coll/20260922.txt", LOG)
    put(src, "b/coll/20260922.txt", LOG2)
    assert {f.status for f in scan(src, canonical=canon).items} == {DUPLICATE}


def test_group_whose_larger_conflicts_with_the_archive_is_all_conflict(src, canon):
    put(canon, "coll/2026/09/20260922.txt", OTHER)
    put(src, "a/coll/20260922.txt", LOG)
    put(src, "b/coll/20260922.txt", LOG2)
    assert {f.status for f in scan(src, canonical=canon).items} == {CONFLICT}


def test_different_envs_of_the_same_day_are_separate(src, canon):
    put(src, "coll/20260922.txt", LOG)
    put(src, "svil/20260922.txt", OTHER)
    assert {f.status for f in scan(src, canonical=canon).items} == {IMPORTABLE}


# ------------------------------------------------------------------ report ---

def test_report_counts_and_groups(src, canon):
    put(src, "coll/20260922.txt")
    put(src, "misti/20260921.txt")
    put(src, "misti/20260920.txt")
    put(src, "coll/x.zip", b"PK")
    report = scan(src, canonical=canon)
    assert report.root == src
    assert report.counts() == {IMPORTABLE: 1, DUPLICATE: 0, NEEDS_ENV: 2, CONFLICT: 0, IGNORED: 1}
    assert [f.rel_path for f in report.of(NEEDS_ENV)] == ["misti/20260920.txt", "misti/20260921.txt"]
    assert report.needs_env_dirs() == ["misti"]
    assert [f.rel_path for f in report.items] == sorted(f.rel_path for f in report.items)


def test_a_missing_root_is_an_empty_report(tmp_path):
    assert scan(tmp_path / "nope").items == ()


# ------------------------------------------------------------ compare_files ---

@pytest.mark.parametrize("a, b, expected", [
    (LOG, LOG, "same"), (LOG, LOG2, "a_prefix"), (LOG2, LOG, "b_prefix"),
    (LOG, OTHER, "diverge"), (b"", LOG, "a_prefix"), (b"", b"", "same"),
])
def test_compare_files(tmp_path, a, b, expected, monkeypatch):
    monkeypatch.setattr(archive, "CHUNK", 7)  # several chunks, a partial last one
    pa, pb = put(tmp_path, "a", a), put(tmp_path, "b", b)
    assert compare_files(pa, pb) == expected
