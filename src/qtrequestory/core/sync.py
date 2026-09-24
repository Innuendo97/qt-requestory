"""Mirror the daily nginx logs of every environment (port of the legacy script).

Per environment: skip when the state says we already synced after the last
server-side compaction; read the autoindex; download, newest first, every
non-empty daily file that is missing locally or has a different size. A file
is streamed to ``<name>.part`` and renamed only once its size matches the
index, so an interrupted run never leaves a half file that looks complete.
A compacted 0-byte day (a day without traffic) is mirrored as a 0-byte local
file, never over an existing one. Nothing local is ever deleted or shrunk:
the server keeps its daily files until a manual purge deletes them, so the
mirror is the archive.

Environments are independent: an unreachable one (no VPN, wrong host) is
reported and the next one is still synced. Progress goes to the ``EventSink``
so the CLI logs it and the UI shows it without the engine knowing either.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from qtrequestory.core.autoindex import AutoindexFormatError, RemoteDailyFile, parse_autoindex
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
    STATUS_LABELS,
    SyncFinished,
    SyncStarted,
)
from qtrequestory.core.fsutil import remove_quietly, replace_with_retry
from qtrequestory.core.http import HttpClient, HttpDownloadError, HttpUnreachable
from qtrequestory.core.state import SyncState

log = logging.getLogger(__name__)

EnvStatus = Literal["ok", "fresh", "unreachable", "errors", "cancelled"]

#: Minimum interval between two ``FileProgress`` events of the same file.
PROGRESS_INTERVAL_S = 0.1
_monotonic = time.monotonic  # module attribute so tests can drive the throttle

NOT_AN_INDEX_TEXT = "l'index non contiene file giornalieri, probabile pagina di login/proxy — stato non aggiornato"
ABBREVIATED_SIZES_TEXT = (
    "l'index del server mostra dimensioni abbreviate (autoindex_exact_size off): impossibile verificare i download"
)

_STATUS_LABELS = STATUS_LABELS  # one wording for sync.log, see core.events


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
    #: A preview (``--dry-run`` / the window's "Anteprima"): nothing was
    #: downloaded and no state written, so ``sync.log`` must say so.
    dry_run: bool = False

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
        what = "anteprima della sincronizzazione" if self.dry_run else "sincronizzazione"
        return (f"{what} terminata in {seconds:.0f} s "
                f"(codice di uscita {self.exit_code}): " + "; ".join(parts))


def _describe(r: EnvResult) -> str:
    # "shrunk" days (server copy smaller than local, see SyncEngine._handle_shrunk)
    # are counted in none of these four fields — they are neither downloaded,
    # present-and-skipped, empty, nor failed — so the numbers below never add
    # up to n_daily when a shrunk day was seen. That is intentional, not a bug
    # to "fix" by adding them to one of these buckets.
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
    action: Literal["download", "present", "crlf", "empty", "shrunk"]


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

        Unknown names raise ``UnknownEnvironment`` before anything starts.
        Every env gets a result, also after a cancel (then ``cancelled``
        without I/O).
        """
        targets = (self._config.enabled_environments() if envs is None
                   else [self._config.require_env(n) for n in envs])
        started = self._clock()
        self._sink(SyncStarted(tuple(e.name for e in targets), dry_run))
        # After a cancel the remaining envs still go through sync_env: it
        # short-circuits to "cancelled" without touching the network, so every
        # env announced in SyncStarted gets its EnvStarted/EnvFinished pair.
        results = tuple(self.sync_env(env, force=force, dry_run=dry_run) for env in targets)
        report = SyncReport(results, started, self._clock(), dry_run=dry_run)
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
        # Read the clock right before the listing, not after the downloads: a
        # slow run must not claim freshness for a moment later than what the
        # listing actually reflected (see mark_success below).
        listing_at = self._clock()
        try:
            html = self._http.get_text(env.url, timeout=self._config.sync.index_timeout_s)
        except HttpUnreachable as e:
            self._sink(EnvUnreachable(env.name, str(e)))
            return tally.result("unreachable", str(e))
        try:
            index = parse_autoindex(html)
        except AutoindexFormatError:
            # Every download decision below compares the remote size against
            # what is on disk; an abbreviated size would be misread as a tiny
            # number and could look like a shrunk or already-present file, so
            # this env must stop here — nothing downloaded — rather than
            # silently corrupt the mirror.
            text = f"{env.name}: {ABBREVIATED_SIZES_TEXT}"
            self._sink(LogMessage(logging.ERROR, text))
            return tally.result("errors", text)
        if not index.daily:
            # A captive portal / login page / proxy error answers 200 with HTML
            # that has no daily file at all. Marking the env fresh on that
            # would silently skip real syncs until the next compaction.
            text = f"{env.name}: {NOT_AN_INDEX_TEXT}"
            self._sink(LogMessage(logging.WARNING, text))
            return tally.result("unreachable", text)
        if not dry_run:
            self._record_listing(env, listing_at, index.daily)
        plans = [self._plan(env, remote) for remote in index.daily]  # already newest first
        to_download = [p for p in plans if p.action == "download"]
        self._sink(RemoteIndexRead(
            env.name,
            n_daily=len(index.daily),
            n_empty=sum(1 for p in plans if p.action == "empty"),
            n_loose=index.loose_count,
            bytes_to_download=sum(p.remote.size for p in to_download),
        ))
        # Days confirmed mirrored locally among what THIS listing showed —
        # present, shrunk, a successful download, or a COMPACTED 0-byte day
        # whose 0-byte local file now exists. The basis for
        # EnvSyncState.newest_day, so is_fresh can require the compacted day
        # to actually be here, not just "we ran recently". A 0-byte day not
        # compacted yet (today, before compaction_time) never counts: the
        # server lists one before it has compacted too (final review #2).
        mirrored: set[date] = set()
        for plan in plans:
            if plan.action == "empty":
                self._sink(FileSkipped(env.name, plan.remote.name, "empty"))
                tally.empty += 1
                if not dry_run and self._mirror_empty_day(env, plan, listing_at):
                    mirrored.add(plan.remote.day)
                continue
            if plan.action in ("present", "crlf"):
                self._sink(FileSkipped(env.name, plan.remote.name, "present"))
                if plan.action == "crlf":
                    self._sink(LogMessage(
                        logging.INFO,
                        f"{env.name}: {plan.remote.name} locale ha i fine riga Windows (CRLF): "
                        f"a parte quelli ha la dimensione del server ({plan.remote.size} byte), "
                        f"tenuta la copia locale",
                    ))
                tally.present += 1
                mirrored.add(plan.remote.day)
                continue
            if self._cancel.is_set():
                return tally.result("cancelled", f"annullato prima di {plan.remote.name}")
            if plan.action == "shrunk":
                # The local copy is the LARGER one, so it IS the mirrored day —
                # never overwrite it, just stash the remote bytes for inspection.
                if not dry_run:
                    try:
                        error = self._handle_shrunk(env, plan)
                    except Cancelled:
                        return tally.result("cancelled", f"annullato durante {plan.remote.name}")
                    if error is not None:
                        tally.failed += 1
                        continue
                mirrored.add(plan.remote.day)
                continue
            if dry_run:
                self._sink(FileSkipped(env.name, plan.remote.name, "dry-run", plan.remote.size))
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
                mirrored.add(plan.remote.day)
            else:
                tally.failed += 1
        if tally.failed:
            return tally.result("errors")
        if not dry_run:
            try:
                self._state.mark_success(env.name, listing_at, last_remote_daily=len(index.daily),
                                         last_downloaded=tally.downloaded, newest_day=max(mirrored, default=None))
            except OSError as e:
                # The downloads already succeeded and are safely on disk; only
                # the bookkeeping write failed (AV, a reader with the file
                # open, a read-only attribute). Losing it costs at most one
                # redundant sync next time - it must not fail this env, let
                # alone stop the ones after it.
                self._sink(LogMessage(logging.WARNING,
                                      f"{env.name}: stato non salvato ({e}); i file sono al sicuro"))
        return tally.result("ok")

    def _plan(self, env: Environment, remote: RemoteDailyFile) -> _Plan:
        dest = local_path(self._config.mirror_root, env.name, remote.day)
        if remote.size == 0:
            return _Plan(remote, dest, "empty")
        try:
            local_size = dest.stat().st_size
        except OSError:
            local_size = None
        if local_size is None:
            return _Plan(remote, dest, "download")
        if local_size == remote.size:
            return _Plan(remote, dest, "present")
        if local_size > remote.size:
            # A copy imported with converted line endings (LF -> CRLF) is the
            # same day, only longer by one byte per line (F5).
            try:
                crlf = count_crlf(dest)
            except OSError:
                crlf = 0
            if crlf and local_size - crlf == remote.size:
                return _Plan(remote, dest, "crlf")
            # A server-side compaction/truncation must never shrink what we
            # already have — the local copy is the archive of record.
            return _Plan(remote, dest, "shrunk")
        return _Plan(remote, dest, "download")

    # ----------------------------------------------------------- listing ---

    def _record_listing(self, env: Environment, listing_at: datetime,
                        daily: Iterable[RemoteDailyFile]) -> None:
        """Remember the listing in the state, whatever the run's outcome: a
        day that fails to download is exactly what the coverage view must
        show as still on the server. Best effort, like ``mark_success``."""
        daily = list(daily)
        try:
            self._state.record_listing(
                env.name, listing_at,
                oldest_listed=min((r.day for r in daily), default=None),
                listed_nonempty=[r.day for r in daily if r.size > 0],
            )
        except OSError as e:
            self._sink(LogMessage(logging.WARNING,
                                  f"{env.name}: elenco del server non salvato nello stato ({e})"))

    # ------------------------------------------------------------- empty ---

    def _mirror_empty_day(self, env: Environment, plan: _Plan, listing_at: datetime) -> bool:
        """Mirror a listed 0-byte day as a 0-byte local file (F1).

        Only once the day is compacted (``listing_at`` at or after that day
        at ``compaction_time``): before that, the 0-byte file only means "not
        compacted yet". Never overwrites: any existing local file (0 bytes or
        not) is kept and confirms the day. Returns whether the day is now
        mirrored; a creation failure is a warning, not a file failure (there
        was nothing to download), and confirms nothing.
        """
        if listing_at < datetime.combine(plan.remote.day, self._config.compaction_time):
            return False
        if plan.dest.exists():
            return True
        try:
            _create_empty(plan.dest)
        except FileExistsError:
            return True
        except OSError as e:
            self._sink(LogMessage(logging.WARNING,
                                  f"{env.name}: impossibile creare il giorno vuoto {plan.remote.name}: {e}"))
            return False
        return True

    # --------------------------------------------------------------- shrunk ---

    def _handle_shrunk(self, env: Environment, plan: _Plan) -> str | None:
        """The remote day is smaller than the one we already mirror: ``dest``
        is never touched. The remote bytes are stashed in a sidecar next to
        it, named so the indexer's ``DAILY_NAME_RE`` never matches it, purely
        so a human can compare the two later.

        Returns ``None`` when the local day is still there (whatever happened
        to the sidecar), or the error text after a ``FileFailed`` when the
        local file can no longer be read — removed or locked between the plan
        and now. That is one file's failure, never the whole run's.

        The sidecar write is best-effort (the local day is already safe on
        disk either way), so the single warning emitted below reflects
        whether it actually succeeded — never claiming "salvata come" when no
        sidecar landed on disk. When the sidecar is already there from an
        earlier run nothing is logged: the warning came with its creation.
        """
        remote, dest = plan.remote, plan.dest
        try:
            local_size = dest.stat().st_size
        except OSError as e:
            return self._fail(env, remote, f"copia locale non più leggibile: {e}")
        sidecar = dest.with_name(f"{dest.name}.remote-{remote.size}")
        self._sink(FileSkipped(env.name, remote.name, "shrunk"))
        if _size_or_none(sidecar) == remote.size:
            # Already reported when the sidecar was created: warning again on
            # every run would bury the log (F5).
            return None
        error = self._download_shrunk_sidecar(env, remote, sidecar)
        outcome = (f"quella remota salvata come {sidecar.name}" if error is None
                   else f"impossibile salvare la copia remota ({error})")
        self._sink(LogMessage(
            logging.WARNING,
            f"{env.name}: {remote.name} sul server è più piccolo della copia locale "
            f"({local_size} contro {remote.size}): tenuta la copia locale, {outcome}",
        ))
        return None

    def _download_shrunk_sidecar(self, env: Environment, remote: RemoteDailyFile, sidecar: Path) -> str | None:
        """Fetch the smaller remote file into ``sidecar`` via a ``.part`` next
        to it (never ``dest``). Returns the error text on failure, ``None`` on
        success — the caller decides how to word the single warning it emits,
        rather than this method logging its own (which would contradict it).
        """
        url = env.url + remote.name
        part = sidecar.with_name(sidecar.name + ".part")
        try:
            written = self._http.download(
                url, part,
                timeout=self._config.sync.download_timeout_s,
                chunk_size=self._config.sync.chunk_size,
                on_progress=lambda _done, _total: None,
                cancel=self._cancel,
            )
            if written != remote.size:
                raise _SizeMismatch(written, remote.size)
            replace_with_retry(part, sidecar)
            return None
        except (HttpDownloadError, _SizeMismatch, OSError) as e:
            return str(e)
        finally:
            remove_quietly(part)

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
                replace_with_retry(part, dest)
            except OSError as e:
                return self._fail(env, remote, f"impossibile rinominare {part.name}: {e}")
            self._sink(FileDone(env.name, remote.name, remote.size, dest))
            return None
        finally:
            remove_quietly(part)

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
                remove_quietly(part)
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


def count_crlf(path: Path, chunk_size: int = 1 << 20) -> int:
    """Number of ``b"\\r\\n"`` pairs in ``path``, streamed (a pair split across
    two chunks counts once)."""
    count = 0
    prev_cr = False
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            count += chunk.count(b"\r\n")
            if prev_cr and chunk[:1] == b"\n":
                count += 1
            prev_cr = chunk[-1:] == b"\r"
    return count


def _create_empty(dest: Path) -> None:
    """Create ``dest`` as a 0-byte file; ``FileExistsError`` if anything is
    already there (exclusive create: never truncates an existing day)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "xb"):
        pass


def _size_or_none(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None
