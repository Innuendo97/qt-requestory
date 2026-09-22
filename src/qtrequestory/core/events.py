"""Progress events, event sinks and cancellation shared by every core job.

Core functions are synchronous and report progress by calling an ``EventSink``
with frozen event dataclasses. The CLI uses ``LoggingSink``; the UI wraps a Qt
signal. Cancellation is cooperative: jobs call ``cancel.check()`` at safe points.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:  # avoid import cycles; sync.py defines these
    from qtrequestory.core.sync import EnvResult, SyncReport


class Cancelled(Exception):
    """Raised by ``CancelToken.check()`` once cancellation was requested."""


class CancelToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    def is_set(self) -> bool:
        return self._event.is_set()

    def check(self) -> None:
        if self._event.is_set():
            raise Cancelled()


def _now() -> float:
    return time.time()


@dataclass(frozen=True)
class Event:
    ts: float = field(default_factory=_now, kw_only=True)


# --------------------------------------------------------------------- sync ---

@dataclass(frozen=True)
class SyncStarted(Event):
    envs: tuple[str, ...]
    dry_run: bool


@dataclass(frozen=True)
class EnvStarted(Event):
    env: str


@dataclass(frozen=True)
class EnvSkipped(Event):
    env: str
    reason: Literal["fresh"]


@dataclass(frozen=True)
class EnvUnreachable(Event):
    env: str
    error: str


@dataclass(frozen=True)
class RemoteIndexRead(Event):
    """Emitted before any download so the caller can show totals / ETA."""
    env: str
    n_daily: int
    n_empty: int
    n_loose: int
    bytes_to_download: int


@dataclass(frozen=True)
class FileSkipped(Event):
    env: str
    name: str
    reason: Literal["present", "empty"]


@dataclass(frozen=True)
class FileStarted(Event):
    env: str
    name: str
    size: int


@dataclass(frozen=True)
class FileProgress(Event):
    env: str
    name: str
    done: int
    size: int


@dataclass(frozen=True)
class FileDone(Event):
    env: str
    name: str
    size: int
    path: Path


@dataclass(frozen=True)
class FileFailed(Event):
    env: str
    name: str
    error: str


@dataclass(frozen=True)
class EnvFinished(Event):
    env: str
    result: EnvResult


@dataclass(frozen=True)
class SyncFinished(Event):
    report: SyncReport


# -------------------------------------------------------------------- index ---

@dataclass(frozen=True)
class IndexStarted(Event):
    n_files_to_scan: int


@dataclass(frozen=True)
class IndexFileScanned(Event):
    path: Path
    n_entries: int
    i: int
    n: int


@dataclass(frozen=True)
class IndexFinished(Event):
    scanned: int
    removed: int
    seconds: float


# ------------------------------------------------------------------ generic ---

@dataclass(frozen=True)
class LogMessage(Event):
    level: int
    text: str


EventSink = Callable[[Event], None]


def null_sink(_: Event) -> None:
    """Sink that drops everything (tests, quiet callers)."""


class CollectingSink:
    """Sink that keeps every event in a list (tests)."""

    def __init__(self) -> None:
        self.events: list[Event] = []

    def __call__(self, ev: Event) -> None:
        self.events.append(ev)

    def of(self, kind: type[Event]) -> list[Event]:
        return [e for e in self.events if isinstance(e, kind)]


class LoggingSink:
    """Sink for headless runs: formats events as log lines (same wording as the
    original PowerShell script, so ``sync.log`` stays familiar)."""

    def __init__(self, logger: logging.Logger) -> None:
        self._log = logger

    def __call__(self, ev: Event) -> None:
        log = self._log
        if isinstance(ev, LogMessage):
            log.log(ev.level, ev.text)
        elif isinstance(ev, EnvSkipped):
            log.info("%s: già sincronizzato dopo l'ultima compattazione, niente da fare", ev.env)
        elif isinstance(ev, EnvUnreachable):
            log.info("%s: endpoint non raggiungibile, riprovo al prossimo giro (%s)", ev.env, ev.error)
        elif isinstance(ev, RemoteIndexRead):
            log.info(
                "%s: index letto: %d file giornalieri, %d vuoti, %d sciolti, %.1f MB da scaricare",
                ev.env, ev.n_daily, ev.n_empty, ev.n_loose, ev.bytes_to_download / 1_048_576,
            )
        elif isinstance(ev, FileDone):
            log.info("%s: scaricato %s (%.1f MB)", ev.env, ev.name, ev.size / 1_048_576)
        elif isinstance(ev, FileFailed):
            log.error("%s: ERRORE su %s: %s", ev.env, ev.name, ev.error)
        elif isinstance(ev, EnvFinished):
            r = ev.result
            log.info(
                "%s: %d scaricati, %d già presenti, %d vuoti saltati, %d errori (%s)",
                r.env, r.downloaded, r.present, r.empty, r.failed, r.status,
            )
        elif isinstance(ev, IndexStarted):
            if ev.n_files_to_scan:
                log.info("indice: %d file da indicizzare", ev.n_files_to_scan)
        elif isinstance(ev, IndexFinished):
            if ev.scanned or ev.removed:
                log.info("indice: %d file indicizzati, %d rimossi in %.1f s", ev.scanned, ev.removed, ev.seconds)
        # FileStarted/FileProgress/FileSkipped/SyncStarted/SyncFinished: too chatty for a log file
