"""The arithmetic behind the Sincronizzazione progress strip. No Qt in here.

The strip has to answer four questions while a sync runs — which file, how far
into it, how far into the whole run, and how long is left — and only the first
two come straight out of an event. The other two need state that survives
across events (bytes already finished, the announced total) and a rate measured
over time.

That is why this is a plain object with an injectable clock instead of code in
the widget: the ETA arithmetic is the part most likely to be wrong, and here it
can be tested by feeding events and turning a fake clock by hand, with no
``QApplication`` and no scripted download to race against.

**Why a sliding window and not an average since the start.** A mirror that
downloads 200 MB in ten seconds and then stalls on a dead connection would keep
claiming 20 MB/s for minutes if the rate were cumulative. Sampling only the
last :data:`RATE_WINDOW_S` seconds makes the number follow reality, and makes a
stall show up as "no ETA" rather than as an optimistic one.
"""
from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from qtrequestory.ui.contracts import (
    Event,
    EnvStarted,
    FileDone,
    FileFailed,
    FileProgress,
    FileSkipped,
    FileStarted,
    IndexFileScanned,
    IndexFinished,
    IndexStarted,
    RemoteIndexRead,
    SyncStarted,
)

__all__ = [
    "PHASE_IDLE", "PHASE_DOWNLOAD", "PHASE_INDEX",
    "RATE_WINDOW_S", "ProgressModel", "ProgressSnapshot",
]

#: Nothing running: the strip is hidden.
PHASE_IDLE = "idle"
#: Downloading daily files: file bar, totals, rate and ETA.
PHASE_DOWNLOAD = "download"
#: Scanning the mirror into the index: same strip, counts only.
PHASE_INDEX = "index"

#: Seconds of history the rate is averaged over (DESIGN-ui: "rate over a 3 s
#: sliding window").
RATE_WINDOW_S = 3.0


@dataclass(frozen=True)
class ProgressSnapshot:
    """Everything the strip shows, taken in one consistent read.

    A snapshot rather than a bag of getters so the widget cannot paint a file
    name from one moment next to a byte count from the next.
    """

    phase: str
    env: str | None
    name: str | None
    #: 1-based position of the current file, 0 before the first one.
    file_index: int
    #: Files the remote index announced (or files to scan, while indexing).
    n_files: int
    file_done: int
    file_size: int
    bytes_done: int
    bytes_total: int
    #: Bytes per second over the sliding window; None until two samples exist.
    rate_bps: float | None
    #: Seconds left, or None when it cannot be honestly computed.
    eta_s: float | None

    @property
    def file_percent(self) -> int:
        """0..100 for the per-file bar; 0 when no file is in flight."""
        if self.file_size <= 0:
            return 0
        return max(0, min(100, round(100 * self.file_done / self.file_size)))


class ProgressModel:
    """Folds the sync events into the numbers :class:`ProgressSnapshot` holds.

    ``handle`` accepts *every* event and ignores the ones it has no use for, so
    the page can forward its whole stream without a filter of its own.
    """

    def __init__(self, window_s: float = RATE_WINDOW_S,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._window = window_s
        self._clock = clock
        self.reset()

    def reset(self) -> None:
        """Back to "nothing is running" — also what a new ``SyncStarted`` does."""
        self._phase = PHASE_IDLE
        self._env: str | None = None
        self._name: str | None = None
        self._file_index = 0
        self._n_files = 0
        self._file_done = 0
        self._file_size = 0
        self._completed = 0
        self._total = 0
        self._samples: deque[tuple[float, int]] = deque()

    # -- events ------------------------------------------------------------

    def handle(self, ev: Event) -> None:
        if isinstance(ev, SyncStarted):
            self.reset()
            self._phase = PHASE_DOWNLOAD
        elif isinstance(ev, EnvStarted):
            self._env, self._name = ev.env, None
        elif isinstance(ev, RemoteIndexRead):
            # Totals are cumulative: the strip counts the whole run, not one env.
            self._env = ev.env
            self._total += ev.bytes_to_download
            self._n_files += ev.n_daily
        elif isinstance(ev, FileSkipped):
            self._file_index += 1
        elif isinstance(ev, FileStarted):
            self._env, self._name = ev.env, ev.name
            self._file_index += 1
            self._file_done, self._file_size = 0, ev.size
            self._sample()
        elif isinstance(ev, FileProgress):
            self._file_done, self._file_size = ev.done, ev.size
            self._sample()
        elif isinstance(ev, FileDone):
            self._completed += ev.size
            self._file_done, self._file_size = 0, 0
            self._sample()
        elif isinstance(ev, FileFailed):
            # Nothing landed on disk, so the partial bytes leave the total too.
            self._file_done, self._file_size = 0, 0
        elif isinstance(ev, IndexStarted):
            self._phase = PHASE_INDEX
            self._name = None
            self._file_index, self._n_files = 0, ev.n_files_to_scan
            self._file_done, self._file_size = 0, 0
        elif isinstance(ev, IndexFileScanned):
            self._file_index, self._n_files = ev.i, ev.n
            self._name = ev.path.name
        elif isinstance(ev, IndexFinished):
            self._phase = PHASE_IDLE

    # -- reading -----------------------------------------------------------

    def snapshot(self) -> ProgressSnapshot:
        rate = self._rate() if self._phase == PHASE_DOWNLOAD else None
        return ProgressSnapshot(
            phase=self._phase,
            env=self._env,
            name=self._name,
            file_index=self._file_index,
            n_files=self._n_files,
            file_done=self._file_done,
            file_size=self._file_size,
            bytes_done=self.bytes_done,
            bytes_total=self._total,
            rate_bps=rate,
            eta_s=self._eta(rate),
        )

    @property
    def bytes_done(self) -> int:
        """Finished files plus what has landed of the current one."""
        return self._completed + self._file_done

    # -- internals ---------------------------------------------------------

    def _sample(self) -> None:
        now = self._clock()
        self._samples.append((now, self.bytes_done))
        # Keep the first sample that is still inside the window, and the one
        # just before it, so the span is at least as long as the window.
        cutoff = now - self._window
        while len(self._samples) > 2 and self._samples[1][0] < cutoff:
            self._samples.popleft()

    def _rate(self) -> float | None:
        if len(self._samples) < 2:
            return None
        (t0, b0), (t1, b1) = self._samples[0], self._samples[-1]
        elapsed = t1 - t0
        if elapsed <= 0:
            return None
        return (b1 - b0) / elapsed

    def _eta(self, rate: float | None) -> float | None:
        """Seconds left, or None when the answer would be a guess.

        A missing, zero or negative rate (a stall, a single sample, the index
        phase) has no ETA at all: DESIGN-ui asks for the ETA to be *hidden*
        rather than for a number nobody should trust.
        """
        if rate is None or rate <= 0:
            return None
        remaining = self._total - self.bytes_done
        return remaining / rate if remaining > 0 else 0.0
