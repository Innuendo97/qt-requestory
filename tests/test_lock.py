"""ProcessLock: mutual exclusion, context manager, holder info."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from qtrequestory.core.lock import LockHeld, ProcessLock


@pytest.fixture
def lock_path(tmp_path: Path) -> Path:
    return tmp_path / "mirror" / ".qtrequestory" / "sync.lock"  # parent must be created


def test_second_lock_in_same_process_fails_until_released(lock_path):
    """Two handles on the same file: msvcrt/fcntl locks are per handle, so this
    is a real exclusion test even inside one process."""
    first, second = ProcessLock(lock_path), ProcessLock(lock_path)
    assert first.acquire() is True
    assert second.acquire() is False
    assert second.acquire() is False  # stays busy, no side effects
    first.release()
    assert second.acquire() is True
    second.release()


def test_acquire_is_idempotent_for_the_holder(lock_path):
    lock = ProcessLock(lock_path)
    assert lock.acquire() is True
    assert lock.acquire() is True
    lock.release()
    lock.release()  # releasing twice is harmless
    assert ProcessLock(lock_path).acquire() is True


def test_context_manager_raises_lock_held_when_busy(lock_path):
    holder = ProcessLock(lock_path)
    assert holder.acquire()
    try:
        with pytest.raises(LockHeld) as info:
            with ProcessLock(lock_path):
                pass
        assert str(os.getpid()) in str(info.value)
    finally:
        holder.release()
    with ProcessLock(lock_path):
        assert ProcessLock(lock_path).acquire() is False
    assert ProcessLock(lock_path).acquire() is True


def test_holder_info_reports_pid_and_timestamp(lock_path):
    assert ProcessLock(lock_path).holder_info() is None  # no file yet
    lock = ProcessLock(lock_path)
    lock.acquire()
    try:
        info = ProcessLock(lock_path).holder_info()  # readable through another handle
        assert info is not None
        assert str(os.getpid()) in info
        assert "T" in info  # ISO timestamp
    finally:
        lock.release()
    assert ProcessLock(lock_path).holder_info() is None  # cleared on release


def test_blocking_acquire_waits_for_release(lock_path):
    import threading
    import time

    holder = ProcessLock(lock_path)
    assert holder.acquire()
    threading.Timer(0.3, holder.release).start()
    t0 = time.monotonic()
    waiter = ProcessLock(lock_path)
    assert waiter.acquire(blocking=True) is True
    assert 0.2 <= time.monotonic() - t0 < 5
    waiter.release()


# ---------------------------------------------------------- cross-process ---

CHILD_HOLDS_LOCK = """
import os, sys
from pathlib import Path
from qtrequestory.core.lock import ProcessLock
lock = ProcessLock(Path(sys.argv[1]))
assert lock.acquire()
print("held", os.getpid(), flush=True)   # our own pid: sys.executable may be a venv launcher
sys.stdin.read()          # released when the parent closes our stdin
lock.release()
print("released", flush=True)
"""


def _spawn_holder(lock_path: Path) -> tuple[object, str]:
    """Start a child that holds the lock; return ``(popen, child_pid)``."""
    import subprocess
    import sys

    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    child = subprocess.Popen(
        [sys.executable, "-c", CHILD_HOLDS_LOCK, str(lock_path)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env,
    )
    word, pid = child.stdout.readline().split()
    assert word == "held"
    return child, pid


def _kill_holder(child, child_pid: str) -> None:
    """Terminate the interpreter that holds the lock (not just a venv launcher)."""
    import signal

    try:
        os.kill(int(child_pid), signal.SIGTERM)
    except OSError:
        pass
    child.kill()
    child.wait(timeout=10)


def test_lock_is_exclusive_across_processes(lock_path):
    """The real contract: a scheduled task and the UI must not sync together."""
    child, child_pid = _spawn_holder(lock_path)
    try:
        mine = ProcessLock(lock_path)
        assert mine.acquire() is False
        info = mine.holder_info()
        assert info is not None and child_pid in info
        with pytest.raises(LockHeld):
            with ProcessLock(lock_path):
                pass
        child.stdin.close()
        assert child.stdout.readline().strip() == "released"
        child.wait(timeout=10)
        assert mine.acquire() is True
        mine.release()
    finally:
        if child.poll() is None:
            _kill_holder(child, child_pid)
        child.stdout.close()


def test_lock_is_released_when_holder_dies(lock_path):
    """Byte-range locks belong to the OS handle: killing the holder frees it."""
    child, child_pid = _spawn_holder(lock_path)
    try:
        assert ProcessLock(lock_path).acquire() is False
        _kill_holder(child, child_pid)
        survivor = ProcessLock(lock_path)
        assert survivor.acquire() is True
        survivor.release()
    finally:
        child.stdout.close()
        child.stdin.close()
