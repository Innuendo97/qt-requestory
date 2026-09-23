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


# ------------------------------------------------------------- peek_holder ---
#
# The Sincronizzazione page polls "is somebody syncing?" every couple of
# seconds. Answering that by *taking* the lock (the old way) could make a
# scheduled run find it busy and skip an hour, so the probe is read-only: every
# test below uses a temp lock file, never the real mirror's.

WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND


def test_peek_holder_reads_the_holder_line_of_a_live_holder(lock_path):
    from qtrequestory.core.lock import peek_holder

    child, child_pid = _spawn_holder(lock_path)
    try:
        info = peek_holder(lock_path)
        assert info is not None and info.split()[0] == child_pid
        assert ProcessLock(lock_path).acquire() is False, "peeking never takes the lock"
    finally:
        _kill_holder(child, child_pid)
        child.stdout.close()
        child.stdin.close()


def test_peek_holder_is_none_when_nobody_holds_the_lock(lock_path):
    from qtrequestory.core.lock import peek_holder

    assert peek_holder(lock_path) is None, "no file at all"
    lock = ProcessLock(lock_path)
    lock.acquire()
    lock.release()  # release empties the holder line
    assert peek_holder(lock_path) is None


def test_a_stale_holder_line_left_by_a_dead_process_is_nobody(lock_path):
    """A crash leaves the text behind; the PID in it decides, not the text."""
    import subprocess
    import sys

    from qtrequestory.core.lock import peek_holder

    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait(timeout=10)
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text(f"{dead.pid} 2026-09-23T09:00:00\n", encoding="utf-8")
    assert peek_holder(lock_path) is None


def test_a_reused_pid_does_not_pass_for_the_holder(lock_path):
    """Our own PID is alive, but this process started long after the holder
    line was written: Windows recycled the number, the holder is gone."""
    from qtrequestory.core.lock import peek_holder

    lock_path.parent.mkdir(parents=True)
    lock_path.write_text(f"{os.getpid()} 2001-01-01T09:00:00\n", encoding="utf-8")
    assert peek_holder(lock_path) is None
    lock_path.write_text(f"{os.getpid()} 2999-01-01T09:00:00\n", encoding="utf-8")
    assert peek_holder(lock_path) is not None, "a holder that started before the line is alive"


@pytest.mark.parametrize("content", ["", "not-a-pid 2026-09-23T09:00:00\n", "\n\n", "-5 x\n"])
def test_a_garbled_holder_file_is_nobody(lock_path, content):
    from qtrequestory.core.lock import peek_holder

    lock_path.parent.mkdir(parents=True)
    lock_path.write_text(content, encoding="utf-8")
    assert peek_holder(lock_path) is None


def test_peek_holder_never_opens_the_file_for_writing(lock_path, monkeypatch):
    from qtrequestory.core import lock as lock_mod

    lock_path.parent.mkdir(parents=True)
    lock_path.write_text(f"{os.getpid()} 2999-01-01T09:00:00\n", encoding="utf-8")
    real_open = os.open
    seen: list[int] = []

    def spy(path, flags, *args, **kwargs):
        seen.append(flags)
        assert flags & WRITE_FLAGS == 0, f"opened for writing: {flags:#x}"
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(lock_mod.os, "open", spy)
    monkeypatch.setattr(lock_mod, "_try_lock", lambda fd: pytest.fail("peek took the lock"))
    assert lock_mod.peek_holder(lock_path) is not None
    assert seen, "the file is opened through os.open"


# The holder is always one of *our* processes. A PID that belongs to a process
# we may not inspect (a SYSTEM service) and a line written before this boot is
# a leftover of a shutdown mid-sync whose number a boot-time service reused.

def test_an_inaccessible_process_with_a_pre_boot_line_is_nobody(lock_path, monkeypatch):
    from datetime import datetime

    from qtrequestory.core import lock as lock_mod

    boot = datetime(2026, 9, 23, 8, 0, 0)
    monkeypatch.setattr(lock_mod, "_boot_time", lambda: boot)
    monkeypatch.setattr(lock_mod, "_process_state", lambda pid: (lock_mod.DENIED, None))
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text("4 2026-09-22T18:00:00\n", encoding="utf-8")
    assert lock_mod.peek_holder(lock_path) is None, "written before this boot: stale"
    lock_path.write_text("4 2026-09-23T09:00:00\n", encoding="utf-8")
    assert lock_mod.peek_holder(lock_path) is not None, "after boot we cannot tell: be safe"


def test_any_pre_boot_holder_line_is_nobody_even_for_a_live_pid(lock_path, monkeypatch):
    from datetime import datetime

    from qtrequestory.core import lock as lock_mod

    monkeypatch.setattr(lock_mod, "_boot_time", lambda: datetime(2026, 9, 23, 8, 0, 0))
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text(f"{os.getpid()} 2026-09-22T18:00:00\n", encoding="utf-8")
    assert lock_mod.peek_holder(lock_path) is None


def test_the_boot_time_is_in_the_past():
    from datetime import datetime

    from qtrequestory.core import lock as lock_mod

    assert lock_mod._boot_time() < datetime.now()
