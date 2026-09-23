"""fsutil: os.replace retried past transient PermissionError; best-effort unlink."""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

from qtrequestory.core import fsutil


def test_replace_with_retry_survives_transient_permission_errors(monkeypatch):
    calls: list[tuple[Path, Path]] = []

    def flaky_replace(src, dst):
        calls.append((src, dst))
        if len(calls) < 3:
            raise PermissionError("in use")

    monkeypatch.setattr(fsutil.os, "replace", flaky_replace)
    sleeps: list[float] = []

    fsutil.replace_with_retry(Path("a"), Path("b"), sleep=sleeps.append)

    assert len(calls) == 3
    assert sleeps == [0.2, 0.2]  # only between attempts, none after the final try


def test_replace_with_retry_reraises_the_last_error_after_exhausting_attempts(monkeypatch):
    def always_fails(src, dst):
        raise PermissionError("still locked")

    monkeypatch.setattr(fsutil.os, "replace", always_fails)

    with pytest.raises(PermissionError, match="still locked"):
        fsutil.replace_with_retry(Path("a"), Path("b"), attempts=3, sleep=lambda _: None)


def test_replace_with_retry_does_not_retry_other_os_errors(monkeypatch):
    calls: list[int] = []

    def missing_dir(src, dst):
        calls.append(1)
        raise FileNotFoundError("no such directory")

    monkeypatch.setattr(fsutil.os, "replace", missing_dir)

    with pytest.raises(FileNotFoundError):
        fsutil.replace_with_retry(Path("a"), Path("b"), sleep=lambda _: None)
    assert len(calls) == 1


def test_remove_quietly_ignores_a_missing_file(tmp_path: Path):
    fsutil.remove_quietly(tmp_path / "does-not-exist")  # must not raise


def test_remove_quietly_removes_an_existing_file(tmp_path: Path):
    f = tmp_path / "leftover.part"
    f.write_text("x", encoding="utf-8")
    fsutil.remove_quietly(f)
    assert not f.exists()


def test_remove_quietly_swallows_other_os_errors_and_logs(monkeypatch, tmp_path: Path, caplog):
    f = tmp_path / "held.part"
    f.write_text("x", encoding="utf-8")

    def locked(self):
        raise PermissionError("locked by AV")

    monkeypatch.setattr(Path, "unlink", locked)
    with caplog.at_level(logging.WARNING):
        fsutil.remove_quietly(f)  # must not raise
    assert any(r.levelno == logging.WARNING for r in caplog.records)
