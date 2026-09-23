"""Cross-process mutual exclusion for the sync job (``<mirror>/.qtrequestory/sync.lock``).

The scheduled task and the UI may both try to sync the same mirror; only one
must run at a time. The lock is an OS byte-range lock (``msvcrt.locking`` on
Windows, ``fcntl.flock`` elsewhere), so it is released automatically when the
holder dies — a crashed task never leaves a stale lock behind. That is why a
"pid file" alone was not enough.

The holder writes its pid and start time into the file so that the other side
can say "sincronizzazione in corso dal task pianificato (pid N, dalle ...)".
The lock is taken on a byte *beyond* the end of the file: Windows refuses any
read overlapping a locked region, and locking a byte no reader ever touches
keeps ``holder_info()`` readable from other processes while the lock is held.

:func:`peek_holder` answers "who is syncing?" *without* touching the lock: the
Sincronizzazione page asks every couple of seconds, and a probe that took the
lock even for an instant could make a scheduled run find it busy and skip an
hour. It reads the holder line read-only and decides liveness from the PID in
it — the text alone is not a liveness signal, since a crash leaves it behind.
"""
from __future__ import annotations

import ctypes
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

try:  # Windows
    import msvcrt
except ImportError:  # pragma: no cover - non-Windows fallback
    msvcrt = None  # type: ignore[assignment]
    import fcntl

log = logging.getLogger(__name__)

_LOCK_OFFSET = 1 << 20      # 1 MiB: far beyond any holder info we will ever write
_BLOCK_POLL_S = 0.2
_PEEK_MAX_BYTES = 4096      # the holder line is ~30 bytes; never read a stray huge file
#: The holder line's timestamp has whole seconds and is written after the
#: process started; this much slack absorbs the truncation and clock jitter.
_START_SLACK = timedelta(seconds=2)


class LockHeld(Exception):
    """Raised by the context manager when the lock is busy."""


class ProcessLock:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._fd: int | None = None

    # ------------------------------------------------------------- acquire ---

    def acquire(self, blocking: bool = False) -> bool:
        """Take the lock; return False when another holder has it (non-blocking).

        Calling ``acquire`` while already holding the lock is a no-op returning True.
        """
        if self._fd is not None:
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            while not _try_lock(fd):
                if not blocking:
                    os.close(fd)
                    return False
                time.sleep(_BLOCK_POLL_S)
        except BaseException:
            os.close(fd)
            raise
        self._fd = fd
        self._write_holder_info()
        return True

    def release(self) -> None:
        if self._fd is None:
            return
        fd, self._fd = self._fd, None
        try:
            os.ftruncate(fd, 0)  # clear holder info: nobody holds it any more
        except OSError:  # pragma: no cover - best effort
            pass
        try:
            _unlock(fd)
        finally:
            os.close(fd)

    def holder_info(self) -> str | None:
        """``"<pid> <ISO timestamp>"`` written by the current holder, or None."""
        try:
            text = self.path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return text or None

    # ------------------------------------------------------ context manager ---

    def __enter__(self) -> ProcessLock:
        if not self.acquire():
            info = self.holder_info()
            raise LockHeld(f"lock già acquisito ({info})" if info else "lock già acquisito")
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()

    # ------------------------------------------------------------ internals ---

    def _write_holder_info(self) -> None:
        assert self._fd is not None
        try:
            line = f"{os.getpid()} {datetime.now().isoformat(timespec='seconds')}\n"
            os.ftruncate(self._fd, 0)
            os.lseek(self._fd, 0, os.SEEK_SET)
            os.write(self._fd, line.encode("utf-8"))
        except OSError as e:  # best effort: the lock itself is what matters
            log.debug("could not write holder info to %s: %s", self.path, e)


# ---------------------------------------------------------- read-only probe ---

def peek_holder(path: Path) -> str | None:
    """The holder line (``"<pid> <ISO timestamp>"``) of a *live* holder, or None.

    Never acquires the lock and never opens the file for writing: it is opened
    ``O_RDONLY``, and reading the first bytes does not overlap the locked byte
    far beyond the end of the file. A missing, empty or garbled file, a PID
    that is no longer running, or a PID whose process started after the line
    was written (Windows recycled the number), and a line written before the
    machine last booted all mean "nobody".
    """
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    except OSError:
        return None
    try:
        raw = os.read(fd, _PEEK_MAX_BYTES)
    except OSError:
        return None
    finally:
        os.close(fd)
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        return None
    fields = text.split()
    try:
        pid = int(fields[0])
    except ValueError:
        return None
    if pid <= 0:
        return None
    written = _parse_stamp(fields[1]) if len(fields) > 1 else None
    return text if _pid_alive(pid, written) else None


def _parse_stamp(token: str) -> datetime | None:
    try:
        return datetime.fromisoformat(token)
    except ValueError:
        return None


ALIVE = "alive"
GONE = "gone"
#: The process exists but belongs to someone we may not inspect (a service).
DENIED = "denied"


def _pid_alive(pid: int, written: datetime | None) -> bool:
    """Is the holder that wrote ``written`` still running as ``pid``?

    A line written before this boot is stale whatever the PID says now: the
    holder died with the machine (a shutdown in the middle of an hourly sync)
    and the number may belong to a boot-time service. After boot, a process
    we may not inspect counts as alive — the safe answer, it only greys the
    button — and one that started after the line was written is a recycled
    PID.
    """
    if written is not None and written < _boot_time() - _START_SLACK:
        return False
    state, started = _process_state(pid)
    if state == GONE:
        return False
    if state == DENIED or started is None or written is None:
        return True
    return started <= written + _START_SLACK


_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_ERROR_ACCESS_DENIED = 5
_STILL_ACTIVE = 259
#: FILETIME counts 100 ns ticks since 1601-01-01 (UTC).
_FILETIME_EPOCH_OFFSET_S = 11_644_473_600
_kernel32_dll = None


def _kernel32():
    """``kernel32`` with the prototypes used here, loaded once per process."""
    global _kernel32_dll
    if _kernel32_dll is None:
        from ctypes import wintypes

        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.OpenProcess.restype = wintypes.HANDLE
        k.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        k.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        k.GetProcessTimes.argtypes = (wintypes.HANDLE, *(ctypes.POINTER(wintypes.FILETIME),) * 4)
        k.CloseHandle.argtypes = (wintypes.HANDLE,)
        k.GetTickCount64.restype = ctypes.c_ulonglong
        _kernel32_dll = k
    return _kernel32_dll


def _boot_time() -> datetime:
    """When this machine last started (local time, like the holder line)."""
    if sys.platform == "win32":
        uptime_ms = _kernel32().GetTickCount64()
    else:  # pragma: no cover - non-Windows
        try:
            with open("/proc/uptime", encoding="ascii") as handle:
                uptime_ms = float(handle.read().split()[0]) * 1000
        except (OSError, ValueError, IndexError):
            return datetime.min
    return datetime.now() - timedelta(milliseconds=uptime_ms)


def _process_state(pid: int) -> tuple[str, datetime | None]:
    """``(ALIVE, start time or None)``, ``(DENIED, None)`` or ``(GONE, None)``."""
    if sys.platform != "win32":  # pragma: no cover - non-Windows
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return GONE, None
        except OSError:
            return DENIED, None
        return ALIVE, None
    from ctypes import wintypes

    kernel32 = _kernel32()
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        denied = ctypes.get_last_error() == _ERROR_ACCESS_DENIED
        return (DENIED if denied else GONE), None
    try:
        code = wintypes.DWORD()
        if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)) and code.value != _STILL_ACTIVE:
            return GONE, None  # exited, but somebody still holds a handle to it
        created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
        if not kernel32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                        ctypes.byref(kernel), ctypes.byref(user)):
            return ALIVE, None
        ticks = (created.dwHighDateTime << 32) | created.dwLowDateTime
        return ALIVE, datetime.fromtimestamp(ticks / 10_000_000 - _FILETIME_EPOCH_OFFSET_S)
    finally:
        kernel32.CloseHandle(handle)


def _try_lock(fd: int) -> bool:
    if msvcrt is not None:
        os.lseek(fd, _LOCK_OFFSET, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    try:  # pragma: no cover - non-Windows
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock(fd: int) -> None:
    if msvcrt is not None:
        os.lseek(fd, _LOCK_OFFSET, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:  # pragma: no cover - non-Windows
        fcntl.flock(fd, fcntl.LOCK_UN)
