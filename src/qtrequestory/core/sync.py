"""Mirror the daily nginx logs of every environment (port of the legacy script).

Per environment: skip when the state says we already synced after the last
server-side compaction; read the autoindex; download, newest first, every
non-empty daily file that is missing locally or has a different size. A file
is streamed to ``<name>.part`` and renamed only once its size matches the
index, so an interrupted run never leaves a half file that looks complete.
Nothing local is ever deleted: the server keeps ~1 day of history, the mirror
is the archive.

Environments are independent: an unreachable one (no VPN, wrong host) is
reported and the next one is still synced. Progress goes to the ``EventSink``
so the CLI logs it and the UI shows it without the engine knowing either.
"""
from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from qtrequestory.core.autoindex import RemoteDailyFile, parse_autoindex
from qtrequestory.core.config import Config, Environment
from qtrequestory.core.daily import local_path
from qtrequestory.core.events import (
    Cancelled,
    CancelToken,
    EnvFinished,
    EnvSkipped,
    EnvStarted,
    EnvUnreachable,
    EventSink,
    FileDone,
    FileFailed,
    FileProgress,
    FileSkipped,
    FileStarted,
    LogMessage,
    RemoteIndexRead,
    SyncFinished,
    SyncStarted,
)
from qtrequestory.core.http import HttpClient, HttpDownloadError, HttpUnreachable
from qtrequestory.core.state import SyncState

log = logging.getLogger(__name__)

EnvStatus = Literal["ok", "fresh", "unreachable", "errors", "cancelled"]

#: Minimum interval between two ``FileProgress`` events of the same file.
PROGRESS_INTERVAL_S = 0.1
_monotonic = time.monotonic  # module attribute so tests can drive the throttle

NOT_AN_INDEX_TEXT = "l'index non contiene file giornalieri, probabile pagina di login/proxy — stato non aggiornato"

_STATUS_LABELS: dict[str, str] = {
    "ok": "ok",
    "fresh": "già sincronizzato",
    "unreachable": "non raggiungibile",
    "errors": "con errori",
    "cancelled": "annullato",
}


# ---------------------------------------------------------------- results ---

@dataclass(frozen=True)
class EnvResult:
    env: str
    status: EnvStatus
    downloaded: int = 0
    present: int = 0
    empty: int = 0
    failed: int = 0
    bytes: int = 0
    error: str | None = None


@dataclass(frozen=True)
class SyncReport:
    results: tuple[EnvResult, ...]
    started: datetime
    finished: datetime

    @property
    def exit_code(self) -> int:
        """0 ok / nothing to do, 1 file errors, 2 nothing reachable, 3 cancelled.

        Cancellation wins over everything (the run is incomplete whatever else
        happened); file errors win over "nothing reachable" because they need
        a look, while an unreachable endpoint is expected without VPN and only
        matters when *no* environment could be read.
        """
        statuses = {r.status for r in self.results}
        if "cancelled" in statuses:
            return 3
        if "errors" in statuses:
            return 1
        if self.results and not statuses & {"ok", "fresh"}:
            return 2
        return 0

    def summary_line(self) -> str:
        """One Italian line for ``sync.log``: per-env outcome plus exit code."""
        seconds = (self.finished - self.started).total_seconds()
        parts = [_describe(r) for r in self.results] or ["nessun ambiente"]
        return f"sincronizzazione terminata in {seconds:.0f} s (exit {self.exit_code}): " + "; ".join(parts)


def _describe(r: EnvResult) -> str:
    text = f"{r.env} {_STATUS_LABELS[r.status]}"
    if r.status in ("ok", "errors", "cancelled"):
        text += f" ({r.downloaded} scaricati, {r.present} già presenti, {r.empty} vuoti, {r.failed} errori)"
    return text


# ------------------------------------------------------------------ engine ---

@dataclass
class _Tally:
    """Mutable counters of one env run; frozen into an ``EnvResult`` at the end."""
    env: str
    downloaded: int = 0
    present: int = 0
    empty: int = 0
    failed: int = 0
    bytes: int = 0

    def result(self, status: EnvStatus, error: str | None = None) -> EnvResult:
        return EnvResult(self.env, status, self.downloaded, self.present, self.empty,
                         self.failed, self.bytes, error)


class _SizeMismatch(Exception):
    """The transfer completed but its size differs from the autoindex entry."""

    def __init__(self, written: int, expected: int) -> None:
        kind = "troncato" if written < expected else "dimensione inattesa"
        super().__init__(f"{kind}: {written} di {expected} byte")


@dataclass(frozen=True)
class _Plan:
    """What to do with one remote daily file, decided before any download so
    that ``RemoteIndexRead`` can announce the total bytes up front."""
    remote: RemoteDailyFile
    dest: Path
    action: Literal["download", "present", "empty"]


class SyncEngine:
    def __init__(
        self,
        config: Config,
        http: HttpClient,
        state: SyncState,
        sink: EventSink,
        cancel: CancelToken | None = None,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._config = config
        self._http = http
        self._state = state
        self._sink = sink
        self._cancel = cancel if cancel is not None else CancelToken()
        self._clock = clock

    # ------------------------------------------------------------------ run ---

    def run(self, envs: Iterable[str] | None = None, *, force: bool = False, dry_run: bool = False) -> SyncReport:
        """Sync ``envs`` (default: every enabled environment) one after the other.

        Unknown names raise ``KeyError`` before anything starts. Every env
        gets a result, also after a cancel (then ``cancelled`` without I/O).
        """
        targets = self._config.enabled_environments() if envs is None else [self._config.env(n) for n in envs]
        started = self._clock()
        self._sink(SyncStarted(tuple(e.name for e in targets), dry_run))
        # After a cancel the remaining envs still go through sync_env: it
        # short-circuits to "cancelled" without touching the network, so every
        # env announced in SyncStarted gets its EnvStarted/EnvFinished pair.
        results = tuple(self.sync_env(env, force=force, dry_run=dry_run) for env in targets)
        report = SyncReport(results, started, self._clock())
        self._sink(SyncFinished(report))
        return report

    def sync_env(self, env: Environment, *, force: bool = False, dry_run: bool = False) -> EnvResult:
        self._sink(EnvStarted(env.name))
        result = self._sync_env(env, force=force, dry_run=dry_run)
        self._sink(EnvFinished(env.name, result))
        return result

    def _sync_env(self, env: Environment, *, force: bool, dry_run: bool) -> EnvResult:
        tally = _Tally(env.name)
        if self._cancel.is_set():
            return tally.result("cancelled", "annullato prima dell'avvio")
        if not force and self._state.is_fresh(env.name, self._clock(), self._config.compaction_time):
            self._sink(EnvSkipped(env.name, "fresh"))
            return tally.result("fresh")
        try:
            html = self._http.get_text(env.url, timeout=self._config.sync.index_timeout_s)
        except HttpUnreachable as e:
            self._sink(EnvUnreachable(env.name, str(e)))
            return tally.result("unreachable", str(e))
        index = parse_autoindex(html)
        if not index.daily:
            # A captive portal / login page / proxy error answers 200 with HTML
            # that has no daily file at all. Marking the env fresh on that
            # would silently skip real syncs until the next compaction.
            text = f"{env.name}: {NOT_AN_INDEX_TEXT}"
            self._sink(LogMessage(logging.WARNING, text))
            return tally.result("unreachable", text)
        plans = [self._plan(env, remote) for remote in index.daily]  # already newest first
        to_download = [p for p in plans if p.action == "download"]
        self._sink(RemoteIndexRead(
            env.name,
            n_daily=len(index.daily),
            n_empty=sum(1 for p in plans if p.action == "empty"),
            n_loose=index.loose_count,
            bytes_to_download=sum(p.remote.size for p in to_download),
        ))
        for plan in plans:
            if plan.action == "empty":
                self._sink(FileSkipped(env.name, plan.remote.name, "empty"))
                tally.empty += 1
                continue
            if plan.action == "present":
                self._sink(FileSkipped(env.name, plan.remote.name, "present"))
                tally.present += 1
                continue
            if self._cancel.is_set():
                return tally.result("cancelled", f"annullato prima di {plan.remote.name}")
            if dry_run:
                tally.downloaded += 1
                tally.bytes += plan.remote.size
                continue
            try:
                error = self._download_file(env, plan.remote, plan.dest)
            except Cancelled:
                return tally.result("cancelled", f"annullato durante {plan.remote.name}")
            if error is None:
                tally.downloaded += 1
                tally.bytes += plan.remote.size
            else:
                tally.failed += 1
        if tally.failed:
            return tally.result("errors")
        if not dry_run:
            self._state.mark_success(env.name, self._clock(), last_remote_daily=len(index.daily),
                                     last_downloaded=tally.downloaded)
        return tally.result("ok")

    def _plan(self, env: Environment, remote: RemoteDailyFile) -> _Plan:
        dest = local_path(self._config.mirror_root, env.name, remote.day)
        if remote.size == 0:
            return _Plan(remote, dest, "empty")
        try:
            local_size = dest.stat().st_size
        except OSError:
            local_size = None
        return _Plan(remote, dest, "present" if local_size == remote.size else "download")

    # ------------------------------------------------------------- download ---

    def _download_file(self, env: Environment, remote: RemoteDailyFile, dest: Path) -> str | None:
        """Fetch one file into place; return the error text or ``None`` on success.

        Emits ``FileStarted``, throttled ``FileProgress``, then ``FileDone`` or
        ``FileFailed``. A failed attempt (network error or a transfer whose
        size differs from the index) is retried ``config.sync.retries`` times.
        A ``Cancelled`` propagates. Whatever happens the ``.part`` is gone
        when this returns or raises.
        """
        url = env.url + remote.name
        part = dest.with_name(dest.name + ".part")
        self._sink(FileStarted(env.name, remote.name, remote.size))
        try:
            try:
                self._transfer_with_retries(env, remote, url, part)
            except (HttpDownloadError, _SizeMismatch) as e:
                return self._fail(env, remote, str(e))
            try:
                os.replace(part, dest)
            except OSError as e:
                return self._fail(env, remote, f"impossibile rinominare {part.name}: {e}")
            self._sink(FileDone(env.name, remote.name, remote.size, dest))
            return None
        finally:
            _remove_quietly(part)

    def _transfer_with_retries(self, env: Environment, remote: RemoteDailyFile, url: str, part: Path) -> None:
        """Leave a complete ``part`` in place or raise the last attempt's error.

        An attempt fails on ``HttpDownloadError`` or when the byte count does
        not match the index (short read: the server closed early; longer: the
        file changed under us). Each retry is announced as a warning so the
        log explains why one file shows several GETs.
        """
        retries = self._config.sync.retries
        attempt = 0
        while True:
            try:
                written = self._transfer(env, remote, url, part)
                if written != remote.size:
                    raise _SizeMismatch(written, remote.size)
                return
            except (HttpDownloadError, _SizeMismatch) as e:
                _remove_quietly(part)
                attempt += 1
                if attempt > retries:
                    raise
                self._sink(LogMessage(logging.WARNING,
                                      f"{env.name}: {remote.name}: {e} - nuovo tentativo {attempt}/{retries}"))

    def _transfer(self, env: Environment, remote: RemoteDailyFile, url: str, part: Path) -> int:
        """Stream ``url`` to ``part`` emitting at most ~10 ``FileProgress``/s
        plus, always, the final one (so the UI bar reaches 100%)."""
        last_emit = float("-inf")

        def on_progress(done: int, _total: int | None) -> None:
            nonlocal last_emit
            now = _monotonic()
            if done >= remote.size or now - last_emit >= PROGRESS_INTERVAL_S:
                last_emit = now
                self._sink(FileProgress(env.name, remote.name, done, remote.size))

        # http.download creates part.parent; an unwritable mirror surfaces as
        # HttpDownloadError and stays a per-file failure.
        return self._http.download(
            url, part,
            timeout=self._config.sync.download_timeout_s,
            chunk_size=self._config.sync.chunk_size,
            on_progress=on_progress,
            cancel=self._cancel,
        )

    def _fail(self, env: Environment, remote: RemoteDailyFile, error: str) -> str:
        self._sink(FileFailed(env.name, remote.name, error))
        return error


def _remove_quietly(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError as e:  # pragma: no cover - best effort (e.g. antivirus holding the file)
        log.warning("impossibile rimuovere il file parziale %s: %s", path, e)
