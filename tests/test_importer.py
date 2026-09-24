"""core/importer.py: copy + verify into the canonical tree, never lose anything,
and send only verified originals to the Recycle Bin (always mocked here)."""
from __future__ import annotations

import os
import threading
from datetime import date
from pathlib import Path

import pytest

from qtrequestory.core import importer
from qtrequestory.core.archive import CONFLICT, DUPLICATE, IMPORTABLE, discover
from qtrequestory.core.daily import local_path
from qtrequestory.core.importer import ImportResult, VerifiedOriginal, run_import, send_to_recycle_bin
from tests.test_archive import LOG, LOG2, OTHER, put

TODAY = date(2026, 9, 24)
D = date(2026, 9, 22)


def scan(root: Path, canon: Path):
    return discover(root, ("coll", "svil"), {}, canonical_root=canon, today=TODAY)


@pytest.fixture
def src(tmp_path: Path) -> Path:
    return tmp_path / "old"


@pytest.fixture
def canon(tmp_path: Path) -> Path:
    return tmp_path / "mirror"


# -------------------------------------------------------------------- copy ---

def test_copies_verifies_and_reports(src, canon):
    a = put(src, "coll/20260922.txt", LOG)
    b = put(src, "svil/2026-09-21.txt", b"")
    dup = put(src, "x/coll/20260922.txt", LOG)
    put(src, "misti/20260920.txt")                         # needs_env: untouched
    steps: list[tuple[int, int, str]] = []
    result = run_import(scan(src, canon), canon, progress=lambda *a: steps.append(a))
    assert isinstance(result, ImportResult)
    assert local_path(canon, "coll", D).read_bytes() == LOG
    assert local_path(canon, "svil", date(2026, 9, 21)).read_bytes() == b""
    assert (result.copied, result.skipped, result.conflicts, result.errors) == (2, 1, 0, [])
    assert sorted(result.verified_paths) == sorted([a, b, dup])
    assert result.envs == {"coll", "svil"}
    assert not result.cancelled
    assert steps[-1] == (3, 3, "") and [s[1] for s in steps] == [3] * 4
    assert a.read_bytes() == LOG  # originals are never touched by the import
    assert not list(canon.rglob("*.part"))


def test_a_duplicate_is_verified_without_copying(src, canon):
    put(canon, "coll/2026/09/20260922.txt", LOG2)
    orig = put(src, "coll/20260922.txt", LOG)
    before = local_path(canon, "coll", D).stat().st_mtime_ns
    result = run_import(scan(src, canon), canon)
    assert (result.copied, result.skipped) == (0, 1)
    assert result.verified_paths == [orig]
    assert local_path(canon, "coll", D).stat().st_mtime_ns == before


def test_strict_prefix_replaces_the_archive_copy(src, canon):
    put(canon, "coll/2026/09/20260922.txt", LOG)
    orig = put(src, "coll/20260922.txt", LOG2)
    result = run_import(scan(src, canon), canon)
    assert result.copied == 1 and result.verified_paths == [orig]
    assert local_path(canon, "coll", D).read_bytes() == LOG2


def test_conflicts_are_counted_and_never_copied(src, canon):
    put(canon, "coll/2026/09/20260922.txt", OTHER)
    put(src, "coll/20260922.txt", LOG2)
    result = run_import(scan(src, canon), canon)
    assert (result.copied, result.conflicts, result.verified_paths) == (0, 1, [])
    assert local_path(canon, "coll", D).read_bytes() == OTHER


@pytest.mark.parametrize("now", [OTHER, LOG2 + b"more"])
def test_the_archive_changed_after_the_scan_is_rechecked(src, canon, now):
    """Never overwrite: what the archive holds at COPY time decides. A copy
    that appeared meanwhile and is not a strict prefix blocks the replace."""
    orig = put(src, "coll/20260922.txt", LOG2)
    report = scan(src, canon)
    assert report.items[0].status == IMPORTABLE
    put(canon, "coll/2026/09/20260922.txt", now)
    result = run_import(report, canon)
    assert local_path(canon, "coll", D).read_bytes() == now
    assert result.copied == 0
    if now == OTHER:
        assert result.conflicts == 1 and result.verified_paths == []
    else:  # the archive became a superset: nothing to do, the original is safe
        assert result.skipped == 1 and result.verified_paths == [orig]


def test_a_source_changed_after_the_scan_is_an_error(src, canon):
    orig = put(src, "coll/20260922.txt", LOG)
    report = scan(src, canon)
    orig.write_bytes(LOG2)
    result = run_import(report, canon)
    assert result.copied == 0 and result.verified_paths == []
    assert [p for p, _ in result.errors] == [orig]
    assert not local_path(canon, "coll", D).exists()


def test_a_failed_verification_leaves_nothing_behind(src, canon, monkeypatch):
    put(src, "coll/20260922.txt", LOG)
    real = importer._hash_file
    monkeypatch.setattr(importer, "_hash_file", lambda p: "0" * 64 if p.name.endswith(".part") else real(p))
    result = run_import(scan(src, canon), canon)
    assert result.copied == 0 and len(result.errors) == 1 and result.verified_paths == []
    assert not local_path(canon, "coll", D).exists()
    assert not list(canon.rglob("*.part"))


def test_shadowed_copy_is_verified_only_if_its_larger_twin_made_it(src, canon, monkeypatch):
    small = put(src, "a/coll/20260922.txt", LOG)
    put(src, "b/coll/20260922.txt", LOG2)
    report = scan(src, canon)
    assert {f.status for f in report.items} == {IMPORTABLE, DUPLICATE}

    def boom(*a, **k):
        raise OSError("disco pieno")

    monkeypatch.setattr(importer, "_copy_to_part", boom)
    result = run_import(report, canon)
    assert result.verified_paths == []
    assert {p for p, _ in result.errors} == {small, src / "b/coll/20260922.txt"}


def test_cancel_stops_between_files(src, canon):
    put(src, "coll/20260921.txt", LOG)
    put(src, "coll/20260922.txt", LOG)
    cancel = threading.Event()
    result = run_import(scan(src, canon), canon, cancel=cancel,
                        progress=lambda done, total, rel: cancel.set() if done == 1 else None)
    assert result.cancelled and result.copied == 1


def test_cancel_mid_copy_removes_the_part(src, canon, monkeypatch):
    put(src, "coll/20260922.txt", LOG * 50)
    monkeypatch.setattr(importer, "CHUNK", 64)
    cancel = threading.Event()
    real_write = importer._write_chunk

    def write(f, data):
        real_write(f, data)
        cancel.set()

    monkeypatch.setattr(importer, "_write_chunk", write)
    result = run_import(scan(src, canon), canon, cancel=cancel)
    assert result.cancelled and result.copied == 0
    assert not list(canon.rglob("*")) or not [p for p in canon.rglob("*") if p.is_file()]


def test_a_crlf_copy_of_a_missing_day_is_imported_byte_exact(src, canon):
    from tests.test_archive import log_bytes
    from tests.conftest import FDI_A
    data = log_bytes(FDI_A, crlf=True)
    put(src, "coll/20260922.txt", data)
    assert run_import(scan(src, canon), canon).copied == 1
    assert local_path(canon, "coll", D).read_bytes() == data


# ------------------------------------------------------------ recycle bin ---

class _Shell:
    def __init__(self, rc: int = 0, aborted: bool = False) -> None:
        self.calls: list[str] = []
        self.rc, self.aborted = rc, aborted

    def __call__(self, path: str) -> tuple[int, bool]:
        self.calls.append(path)
        if self.rc == 0 and not self.aborted:
            os.remove(path)  # what the Recycle Bin looks like from here
        return self.rc, self.aborted


def rec(path: Path, canon: Path) -> VerifiedOriginal:
    """A verified original of ``path`` whose canonical copy really exists."""
    dest = put(canon, "coll/2026/09/20260922.txt", path.read_bytes())
    st = path.stat()
    return VerifiedOriginal(path, st.st_size, st.st_mtime_ns, dest)


@pytest.fixture
def shell(monkeypatch) -> _Shell:
    s = _Shell()
    monkeypatch.setattr(importer, "_shell_delete", s)
    monkeypatch.setattr(importer, "_drive_type", lambda p: importer.DRIVE_FIXED)
    monkeypatch.setattr(importer.sys, "platform", "win32")
    return s


def test_recycle_sends_only_the_given_files(src, canon, shell):
    a = put(src, "coll/20260922.txt")
    keep = put(src, "coll/20260921.txt")
    assert send_to_recycle_bin([rec(a, canon)], canonical_root=canon) == []
    assert shell.calls == [str(a)]
    assert not a.exists() and keep.exists()


def test_recycle_refuses_anything_inside_the_canonical_tree(canon, shell):
    inside = put(canon, "coll/2026/09/20260922.txt")
    misplaced = put(canon, "coll/2026/9/20260921.txt")
    failures = send_to_recycle_bin(
        [VerifiedOriginal(p, p.stat().st_size, p.stat().st_mtime_ns, inside) for p in (inside, misplaced)],
        canonical_root=canon)
    assert [p for p, _ in failures] == [inside, misplaced]
    assert all("archivio" in why for _, why in failures)
    assert shell.calls == [] and inside.exists() and misplaced.exists()


def test_recycle_refuses_folders_missing_and_relative_paths(src, canon, shell):
    put(src, "coll/20260922.txt")
    dest = put(canon, "coll/2026/09/20260922.txt")
    failures = send_to_recycle_bin([VerifiedOriginal(p, 1, 1, dest) for p in (src / "coll", src / "nope.txt", Path("rel.txt"))],
                                   canonical_root=canon)
    assert len(failures) == 3 and shell.calls == []
    assert (src / "coll").is_dir()


@pytest.mark.parametrize("drive", [2, 4, 0])  # removable, network, unknown
def test_recycle_refuses_drives_without_a_recycle_bin(src, canon, shell, monkeypatch, drive):
    """There SHFileOperation with FOF_ALLOWUNDO deletes for good."""
    a = put(src, "coll/20260922.txt")
    monkeypatch.setattr(importer, "_drive_type", lambda p: drive)
    failures = send_to_recycle_bin([rec(a, canon)], canonical_root=canon)
    assert [p for p, _ in failures] == [a] and "Cestino" in failures[0][1]
    assert shell.calls == [] and a.exists()


def test_recycle_reports_shell_failures(src, canon, shell):
    a = put(src, "coll/20260922.txt")
    shell.rc = 0x78
    assert [p for p, _ in send_to_recycle_bin([rec(a, canon)], canonical_root=canon)] == [a]
    shell.rc, shell.aborted = 0, True
    assert [p for p, _ in send_to_recycle_bin([rec(a, canon)], canonical_root=canon)] == [a]


def test_recycle_is_windows_only(src, canon, shell, monkeypatch):
    a = put(src, "coll/20260922.txt")
    monkeypatch.setattr(importer.sys, "platform", "linux")
    assert [p for p, _ in send_to_recycle_bin([rec(a, canon)], canonical_root=canon)] == [a]
    assert shell.calls == [] and a.exists()


def test_the_shell_call_uses_the_recycle_flags(monkeypatch):
    """The flags are the contract: ALLOWUNDO is what makes it the Recycle Bin."""
    assert importer.FO_DELETE == 3
    assert importer.RECYCLE_FLAGS == 0x40 | 0x10 | 0x4 | 0x400
