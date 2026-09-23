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
    reason: Literal["present", "empty", "shrunk", "dry-run"]
    #: Only set for ``"dry-run"`` (what the transfer would have been); the
    #: other reasons leave it at 0, nothing downstream reads it for them.
    size: int = 0


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


_KB = 1024
_MB = 1024 * _KB
_GB = 1024 * _MB


def _decimal(value: float) -> str:
    """One decimal, Italian comma, and no pointless ",0" ("41", "1,5")."""
    text = f"{value:.1f}".replace(".", ",")
    return text[:-2] if text.endswith(",0") else text


def format_size(n_bytes: float) -> str:
    """"512 B" / "2,5 KB" / "80,4 MB" / "1,5 GB": THE size wording of the app.

    It lives here, in the core, because ``sync.log`` is written by
    :class:`LoggingSink` and the Sincronizzazione page shows those very lines
    next to its own numbers: the UI's ``sync_format.format_size`` delegates to
    this function, so "4.0 MB" in the registro and "4 MB" on a card cannot
    happen again.
    """
    n = max(0.0, float(n_bytes))
    if n < _KB:
        return f"{int(n)} B"
    if n < _MB:
        return f"{_decimal(n / _KB)} KB"
    if n < _GB:
        return f"{_decimal(n / _MB)} MB"
    return f"{_decimal(n / _GB)} GB"


#: ``EnvResult.status`` in the words of ``sync.log`` (shared with
#: ``SyncReport.summary_line``): the registro is read by people, in Italian.
STATUS_LABELS: dict[str, str] = {
    "ok": "completato",
    "fresh": "già sincronizzato",
    "unreachable": "non raggiungibile",
    "errors": "con errori",
    "cancelled": "annullato",
}


def format_seconds(seconds: float) -> str:
    """"0,1 s" / "12 s": one decimal, Italian comma, no pointless ",0"."""
    return f"{_decimal(max(0.0, seconds))} s"


class LoggingSink:
    """Sink for headless runs: formats events as log lines (same wording as the
    original PowerShell script, so ``sync.log`` stays familiar)."""

    def __init__(self, logger: logging.Logger) -> None:
        self._log = logger
        # Set by each SyncStarted: a preview's per-env line must not read
        # like a real sync in sync.log (the window's "Anteprima" writes here).
        self._dry_run = False

    def __call__(self, ev: Event) -> None:
        log = self._log
        if isinstance(ev, SyncStarted):
            self._dry_run = ev.dry_run
        elif isinstance(ev, LogMessage):
            log.log(ev.level, ev.text)
        elif isinstance(ev, EnvSkipped):
            log.info("%s: già sincronizzato dopo l'ultima compattazione, niente da fare", ev.env)
        elif isinstance(ev, EnvUnreachable):
            log.info("%s: endpoint non raggiungibile, riprovo al prossimo giro (%s)", ev.env, ev.error)
        elif isinstance(ev, RemoteIndexRead):
            log.info(
                "%s: elenco del server letto: %d file giornalieri, %d vuoti, %d sciolti, %s da scaricare",
                ev.env, ev.n_daily, ev.n_empty, ev.n_loose, format_size(ev.bytes_to_download),
            )
        elif isinstance(ev, FileDone):
            log.info("%s: scaricato %s (%s)", ev.env, ev.name, format_size(ev.size))
        elif isinstance(ev, FileFailed):
            log.error("%s: ERRORE su %s: %s", ev.env, ev.name, ev.error)
        elif isinstance(ev, EnvFinished):
            r = ev.result
            fmt = ("%s: anteprima, %d da scaricare, %d già presenti, %d vuoti saltati, %d errori (%s)"
                   if self._dry_run else
                   "%s: %d scaricati, %d già presenti, %d vuoti saltati, %d errori (%s)")
            log.info(fmt, r.env, r.downloaded, r.present, r.empty, r.failed,
                     STATUS_LABELS.get(r.status, r.status))
        elif isinstance(ev, IndexStarted):
            if ev.n_files_to_scan:
                log.info("indice: %d file da indicizzare", ev.n_files_to_scan)
        elif isinstance(ev, IndexFinished):
            if ev.scanned or ev.removed:
                log.info("indice: %d file indicizzati, %d rimossi in %s",
                         ev.scanned, ev.removed, format_seconds(ev.seconds))
        # FileStarted/FileProgress/FileSkipped/SyncFinished: too chatty for a log file
