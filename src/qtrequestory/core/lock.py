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
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from pathlib import Path

try:  # Windows
    import msvcrt
except ImportError:  # pragma: no cover - non-Windows fallback
    msvcrt = None  # type: ignore[assignment]
    import fcntl

log = logging.getLogger(__name__)

_LOCK_OFFSET = 1 << 20      # 1 MiB: far beyond any holder info we will ever write
_BLOCK_POLL_S = 0.2


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
