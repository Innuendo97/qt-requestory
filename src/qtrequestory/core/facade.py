"""The six service objects the UI talks to — the ONLY adapter layer.

The core is a set of modules with functions (``search(conn, root, q)``,
``scheduler.status(exe, runner=...)``, ...). The UI wants objects with short,
already-bound methods (``index.search(q)``) and a couple of computed views the
core does not store anywhere (``env_status``: last sync + local files + index
backlog). Putting that glue here, in the core (standard library only, no Qt),
keeps the UI free of adapter code: ``ui/contracts.py`` declares the Protocols
and these classes satisfy them structurally.

What the adapters actually do beyond binding arguments:

* ``IndexService.read_body`` swallows ``IndexStale``: a re-downloaded daily file
  shifts every byte offset, so the day is rescanned and the read retried once.
  The UI never has to know that failure mode exists.
* ``SchedulerService.status`` normalises the placeholder strings ``schtasks``
  prints in its CSV (``""``, ``N/A``, ``N/D``, ``N/V``) to ``None``, so the UI
  can simply test for ``None`` instead of guessing the locale.
* ``SyncService.lock_holder`` is a read-only probe (``lock.peek_holder``): the
  info file alone is not a liveness signal (a crashed holder may leave text
  behind), so the PID written in it is checked, and the lock itself is never
  taken — a probe that took it could make a scheduled run skip an hour.
* ``ArchiveService.import_`` holds the sync lock while it copies: a sync
  writing the same day's ``.part`` at the same time would race it.
* Every service reads the configuration through a callable, so saving new
  settings in Impostazioni is picked up without rebuilding anything.

SQLite connections are opened per operation: the UI calls search and preview
from worker threads and ``sqlite3`` objects must not be shared across threads.
Opening a WAL database costs well under a millisecond.
"""
from __future__ import annotations

import dataclasses
import sqlite3
from collections.abc import Callable, Iterable, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterator

from qtrequestory.core import config as config_mod
from qtrequestory.core import archive, daily, extract, opener, scheduler
from qtrequestory.core.archive import ArchiveReport
from qtrequestory.core.autoindex import parse_autoindex
from qtrequestory.core.config import Config, Environment
from qtrequestory.core.events import CancelToken, EventSink
from qtrequestory.core.http import HttpClient, HttpUnreachable, UrllibHttpClient
from qtrequestory.core.index.builder import IndexBuilder, IndexPlan
from qtrequestory.core.index.db import open_index
from qtrequestory.core.index.search import (
    Coverage,
    IndexStale,
    SearchHit,
    SearchQuery,
    coverage as core_coverage,
    list_template_keys as core_list_template_keys,
    output_name_for,
    output_name_with_id,
    read_body as core_read_body,
    search as core_search,
)
from qtrequestory.core.importer import (
    CancelLike, ImportResult, Progress, VerifiedOriginal, run_import, send_to_recycle_bin,
)
from qtrequestory.core.jobs import JobReport, run_index_job, run_sync_job
from qtrequestory.core.lock import ProcessLock, peek_holder
from qtrequestory.core.paths import AppPaths, app_paths, executable_dir
from qtrequestory.core.scheduler import CommandRunner, SchedulerError, TaskStatus
from qtrequestory.core.state import SyncState

#: How a configuration is obtained. ``ConfigService.current`` is the real one.
ConfigSource = Callable[[], Config]

#: Placeholders ``schtasks`` prints for "no value" in its localised CSV.
NO_VALUE_STRINGS = frozenset({"", "n/a", "n/d", "n/v", "-"})

REACHABLE_TIMEOUT_S = 5.0


# ---------------------------------------------------------------- env status ---

@dataclass(frozen=True)
class EnvStatus:
    """Everything the Sincronizzazione card shows for one environment.

    Computed on demand from the sync state, the local mirror and the index —
    nothing here is persisted, so it is always in step with the disk. It says
    nothing about reachability: that costs a network round trip and is asked
    for separately with ``SyncService.check_reachable``.
    """

    env: str
    last_success: datetime | None
    fresh: bool
    n_local_files: int
    local_bytes: int
    latest_day: date | None
    index_pending: int
    last_remote_daily: int = 0
    last_downloaded: int = 0

    @property
    def never_synced(self) -> bool:
        return self.last_success is None

    @property
    def index_up_to_date(self) -> bool:
        return self.index_pending == 0


# ------------------------------------------------------------ config service ---

class ConfigService:
    """Loads, validates and saves ``config.json``; the single source of truth
    the other services read the current configuration from."""

    def __init__(
        self,
        paths: AppPaths,
        *,
        exe_dir: Path | None = None,
        editor_candidates: Iterable[Path | None] | None = None,
    ) -> None:
        self._paths = paths
        self._exe_dir = exe_dir if exe_dir is not None else executable_dir()
        self._editor_candidates = editor_candidates
        self._current: Config | None = None

    # -- Protocol surface ---------------------------------------------------

    def is_first_run(self) -> bool:
        return config_mod.is_first_run(self._paths.config_file)

    def load(self) -> Config:
        self._current = config_mod.load_config(self._paths.config_file)
        return self._current

    def save(self, cfg: Config) -> None:
        config_mod.save_config(cfg, self._paths.config_file)
        self._current = cfg

    def validate(self, cfg: Config) -> list[str]:
        return config_mod.validate(cfg)

    def mirror_root_errors(self, cfg: Config) -> list[str]:
        return config_mod.mirror_root_errors(cfg)

    def detect_editor(self) -> Path | None:
        return config_mod.detect_editor(self._editor_candidates)

    def import_environments_file(self, path: Path) -> list[Environment]:
        return config_mod.import_environments_file(Path(path))

    def find_sidecar_environments(self) -> Path | None:
        return config_mod.find_sidecar_environments(self._exe_dir)

    def config_path(self) -> Path:
        return self._paths.config_file

    # -- used by the other services ----------------------------------------

    def current(self) -> Config:
        """The configuration in effect, loading it on first use."""
        return self._current if self._current is not None else self.load()


# -------------------------------------------------------------- sync service ---

class SyncService:
    """Sync status, reachability and the sync job itself, bound to the config."""

    def __init__(
        self,
        config_source: ConfigSource,
        *,
        paths: AppPaths | None = None,
        http_factory: Callable[[], HttpClient] = UrllibHttpClient,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._config_source = config_source
        self._paths = paths if paths is not None else app_paths()
        self._http_factory = http_factory
        self._clock = clock

    def env_status(self, env_name: str) -> EnvStatus:
        cfg = self._config_source()
        st = SyncState(cfg.state_path).load().get(env_name)
        local = daily.list_local_daily_files(cfg.mirror_root, env_name)  # newest first
        return EnvStatus(
            env=env_name,
            last_success=st.last_success,
            fresh=self.is_fresh(env_name),
            n_local_files=len(local),
            local_bytes=sum(f.size for f in local),
            latest_day=local[0].day if local else None,
            index_pending=self._index_pending(cfg, env_name),
            last_remote_daily=st.last_remote_daily,
            last_downloaded=st.last_downloaded,
        )

    def check_reachable(self, env: Environment, timeout: float = REACHABLE_TIMEOUT_S) -> bool:
        """GET the autoindex with a short timeout: True only if it answers with
        something that looks like the listing.

        The **environment being probed is passed in**, never a name looked up in
        the saved configuration. "Verifica raggiungibilità" is offered exactly
        where nothing has been saved yet: in the first-run wizard, before
        [Fine] writes ``config.json``, and in Impostazioni on a row just typed
        or corrected before [Salva]. Resolving a name against the stored
        configuration there found an empty ``environments`` list and reported
        every row unreachable — the check was useless in the only two places
        that offer it.

        A captive portal or a proxy error page answers 200 with HTML that holds
        no log file at all; the sync engine treats that as unreachable, and the
        UI's "Verifica raggiungibilità" must agree with it.

        ``ValueError`` is caught too: an ``environments.json`` imported from a
        colleague may hold a URL with no scheme, and urllib raises that instead
        of a network error. This method promises never to raise; the malformed
        URL is reported where it belongs, by ``config.validate``.
        """
        try:
            html = self._http_factory().get_text(env.url, timeout=timeout)
        except (HttpUnreachable, ValueError):
            return False
        index = parse_autoindex(html)
        return bool(index.daily) or index.loose_count > 0

    def run(
        self,
        envs: Sequence[str] | None = None,
        *,
        force: bool = False,
        dry_run: bool = False,
        sink: EventSink,
        cancel: CancelToken,
    ) -> JobReport:
        return run_sync_job(
            self._config_source(),
            envs=list(envs) if envs is not None else None,
            force=force,
            dry_run=dry_run,
            sink=sink,
            cancel=cancel,
            http=self._http_factory(),
        )

    def lock_holder(self) -> str | None:
        """Who is syncing right now, or None when nobody is.

        Read-only (:func:`~qtrequestory.core.lock.peek_holder`): the holder
        line is read without opening the file for writing, and liveness comes
        from the PID in it, because a crashed holder can leave the text behind.
        It never takes the lock: the Sincronizzazione page polls this every
        couple of seconds, and a probe holding the lock even briefly could
        make a scheduled run log "già in corso" and skip until the next hour.

        An unusable mirror path (not configured yet, removable drive gone)
        answers "nobody" rather than raising inside a timer callback.
        """
        try:
            return peek_holder(self._config_source().lock_path)
        except (OSError, ValueError):
            return None

    def sync_log_path(self) -> Path:
        return self._paths.sync_log

    def tail_sync_log(self, n: int) -> list[str]:
        return _tail(self._paths.sync_log, n)

    def is_fresh(self, env_name: str) -> bool:
        cfg = self._config_source()
        state = SyncState(cfg.state_path).load()
        return state.is_fresh(env_name, self._clock(), cfg.compaction_time)

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _index_pending(cfg: Config, env_name: str) -> int:
        """How many local files of ``env_name`` the index has yet to scan.

        A missing or unreadable index is not an error here: it simply means
        "everything is pending" once files exist. The missing case is checked
        first so that merely refreshing the page never creates a database.
        """
        if not cfg.index_path.exists():
            return len(daily.list_local_daily_files(cfg.mirror_root, env_name))
        try:
            with closing(open_index(cfg.index_path)) as conn:
                return len(IndexBuilder(conn, cfg.mirror_root, _drop).plan([env_name]).to_scan)
        except (sqlite3.Error, OSError):
            return len(daily.list_local_daily_files(cfg.mirror_root, env_name))


# --------------------------------------------------------- scheduler service ---

class SchedulerService:
    """Task Scheduler operations for the current executable."""

    def __init__(
        self,
        *,
        runner: CommandRunner = scheduler.run_schtasks,
        exe_provider: Callable[[], Path | None] = scheduler.current_exe_for_task,
        config_source: ConfigSource = config_mod.default_config,
    ) -> None:
        self._runner = runner
        self._exe_provider = exe_provider
        #: Read at every ``register``, never cached: Impostazioni can change the
        #: schedule and immediately re-register through this same object.
        #: The default is the standalone one (no config file in sight), and it
        #: is exactly what ``config.json`` would say if it had no schedule block.
        self._config_source = config_source

    def status(self) -> TaskStatus:
        """``scheduler.status`` with the schtasks placeholders normalised to None.

        ``command`` goes through the same filter as the text fields: a task
        whose XML holds "N/D" must not reach the UI as ``Path("N/D")``, which
        would be shown as a real command and compared against the exe.
        """
        st = scheduler.status(self.exe_path(), runner=self._runner)
        command = _clean_path(st.command)
        return dataclasses.replace(
            st,
            command=command,
            args=_clean_text(st.args),
            exe_matches=st.exe_matches and command is not None,
            state=_clean_text(st.state),
            next_run=_clean_text(st.next_run),
            last_run=_clean_text(st.last_run),
        )

    def register(self) -> None:
        exe = self.exe_path()
        if exe is None:
            raise SchedulerError(
                "la sincronizzazione automatica richiede l'eseguibile installato: "
                "avviato dai sorgenti non c'è nulla da pianificare"
            )
        spec = scheduler.spec_from_config(self._config_source().schedule, exe)
        scheduler.register(spec, runner=self._runner)

    def unregister(self) -> None:
        scheduler.unregister(runner=self._runner)

    def run_now(self) -> None:
        scheduler.run_now(runner=self._runner)

    def detect_legacy_task(self) -> bool:
        return scheduler.detect_legacy_task(runner=self._runner)

    def remove_legacy_task(self) -> None:
        scheduler.remove_legacy_task(runner=self._runner)

    def exe_path(self) -> Path | None:
        return self._exe_provider()

    def unstable_location_reason(self) -> str | None:
        exe = self.exe_path()
        return scheduler.is_unstable_location(exe) if exe is not None else None


# ------------------------------------------------------------- index service ---

class IndexService:
    """Index maintenance and queries, bound to the configured mirror."""

    def __init__(self, config_source: ConfigSource) -> None:
        self._config_source = config_source

    def plan(self, envs: Sequence[str]) -> IndexPlan:
        cfg = self._config_source()
        with self._connect() as conn:
            return IndexBuilder(conn, cfg.mirror_root, _drop).plan(list(envs))

    def update(
        self,
        envs: Sequence[str] | None = None,
        *,
        full_rebuild: bool = False,
        sink: EventSink,
        cancel: CancelToken,
    ) -> JobReport:
        return run_index_job(
            self._config_source(),
            envs=list(envs) if envs is not None else None,
            full_rebuild=full_rebuild,
            sink=sink,
            cancel=cancel,
        )

    def coverage(self, env: str) -> Coverage | None:
        with self._connect() as conn:
            return core_coverage(conn, env)

    def coverage_days(self, env: str, days: int = 30, today: date | None = None) -> daily.CoverageDays:
        """Each day of the window classified (``daily.classify_days``) from
        the on-disk daily files and the listing memory of the sync state (no
        index/DB involved), so it is right even before an index update."""
        cfg = self._config_source()
        sizes = {f.day: f.size for f in daily.list_local_daily_files(cfg.mirror_root, env)}
        # load() may write sync-state.json once, when only a legacy .last-sync.json exists.
        st = SyncState(cfg.state_path).load().get(env)
        return daily.classify_days(sizes, st.listed_nonempty, st.seen_nonempty, days,
                                   today if today is not None else date.today())

    def count_local_files(self, root: Path | None = None) -> int:
        """``root`` defaults to the configured mirror; the wizard passes the
        folder the user just picked, which is not in the config yet."""
        return daily.count_local_files(Path(root) if root is not None else self._config_source().mirror_root)

    def list_template_keys(self, env: str, prefix: str = "") -> list[str]:
        with self._connect() as conn:
            return core_list_template_keys(conn, env, prefix)

    def search(self, query: SearchQuery) -> list[SearchHit]:
        cfg = self._config_source()
        with self._connect() as conn:
            return core_search(conn, cfg.mirror_root, query)

    def read_body(self, hit: SearchHit) -> bytes:
        """The body bytes of ``hit``, rescanning that day once if the index is stale.

        The daily file may have been re-downloaded since it was indexed, which
        moves every offset. Rather than leaking ``IndexStale`` into the UI, the
        day is re-indexed and the read retried against the fresh offsets. If it
        still fails the exception propagates: the entry really is gone.
        """
        try:
            return core_read_body(hit)
        except IndexStale as stale:
            fresh = self._rescan_and_find(stale.env, stale.day, hit)
            if fresh is None:
                raise
            return core_read_body(fresh)

    def db_path(self) -> Path:
        return self._config_source().index_path

    # -- internals ---------------------------------------------------------

    def _rescan_and_find(self, env: str, day: date, hit: SearchHit) -> SearchHit | None:
        """Re-index ``(env, day)`` and return the same entry with fresh offsets.

        The same name can occur twice in one day (a replayed call): the entry
        is matched on ``(name, seq)``, and on the name alone only when that
        leaves no doubt — handing back the other copy's body would be a
        silently wrong answer.
        """
        cfg = self._config_source()
        with self._connect() as conn:
            if IndexBuilder(conn, cfg.mirror_root, _drop).rescan_file(env, day) == 0:
                return None
            query = SearchQuery(env, template_key=hit.template_key, day_from=day, day_to=day)
            same_name = [c for c in core_search(conn, cfg.mirror_root, query) if c.name == hit.name]
        for candidate in same_name:
            if candidate.seq == hit.seq:
                return candidate
        return same_name[0] if len(same_name) == 1 else None

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """One connection per operation: the UI queries from worker threads and
        a ``sqlite3.Connection`` belongs to the thread that created it."""
        conn = open_index(self._config_source().index_path)
        try:
            yield conn
        finally:
            conn.close()


# ----------------------------------------------------------- extract service ---

class ExtractService:
    """Pretty-print, write and open the extracted request bodies."""

    def __init__(
        self,
        config_source: ConfigSource,
        *,
        popen: opener.PopenFn | None = None,
        startfile: opener.StartFileFn | None = None,
        editor_candidates: Iterable[Path] | None = None,
    ) -> None:
        self._config_source = config_source
        self._popen = popen
        self._startfile = startfile
        self._editor_candidates = editor_candidates

    def pretty_json(self, raw: bytes) -> str:
        return extract.pretty_json(raw)

    def output_name(self, hit: SearchHit) -> str:
        return output_name_for(hit)

    def write_temp_file(self, hit: SearchHit, text: str) -> Path:
        cfg = self._config_source()
        return extract.write_temp_file(
            cfg.resolved_output_dir,
            output_name_for(hit),
            text,
            retention_hours=cfg.output_retention_hours,
            alt_name=output_name_with_id(hit),
            protected=cfg.mirror_root,
        )

    def save_as(self, path: Path, text: str) -> None:
        extract.save_as(Path(path), text)

    def open_in_editor(self, paths: Sequence[Path]) -> str:
        cfg = self._config_source()
        editor = opener.find_editor(cfg.editor_path, self._editor_candidates)
        return opener.open_in_editor(list(paths), editor, popen=self._popen, startfile=self._startfile)

    def open_folder(self, path: Path) -> None:
        opener.open_folder(Path(path), startfile=self._startfile)

    def output_dir(self) -> Path:
        return self._config_source().resolved_output_dir


# ----------------------------------------------------------- archive service ---

class ArchiveBusy(RuntimeError):
    """A sync (UI or scheduled task) holds the lock: import after it ends."""


class ArchiveService:
    """Logs outside the canonical layout: find them, import them, recycle the
    verified originals. See ``core/archive.py`` and ``core/importer.py``."""

    def __init__(self, config_source: ConfigSource) -> None:
        self._config_source = config_source

    def _usable_config(self) -> Config:
        cfg = self._config_source()
        problems = config_mod.mirror_root_errors(cfg)
        if problems:
            raise ValueError(problems[0])
        return cfg

    def report(self, path: Path | None = None, *,
               canonical_root: Path | None = None) -> ArchiveReport:
        """Classify every file under ``path`` (default: the mirror itself).
        ``canonical_root`` (default: the mirror) is the tree whose canonical
        files are skipped: the wizard passes the folder about to become the
        mirror. Read-only. ``ValueError`` while the mirror folder is not usable."""
        cfg = self._usable_config()
        root = Path(path) if path is not None else cfg.mirror_root
        canonical = Path(canonical_root) if canonical_root is not None else cfg.mirror_root
        return archive.discover(root, [e.name for e in cfg.environments], cfg.folder_envs,
                                canonical_root=canonical)

    def import_(
        self,
        report: ArchiveReport,
        *,
        cancel: CancelLike | None = None,
        progress: Progress | None = None,
    ) -> ImportResult:
        """Copy + verify the importable files; ``ArchiveBusy`` while a sync runs.
        The index is NOT updated here: the caller runs an index update of
        ``result.envs`` afterwards."""
        cfg = self._usable_config()
        lock = ProcessLock(cfg.lock_path)
        if not lock.acquire():
            holder = peek_holder(cfg.lock_path)
            raise ArchiveBusy("sincronizzazione in corso" + (f" ({holder})" if holder else "")
                              + ": importa al termine")
        try:
            return run_import(report, cfg.mirror_root, cancel=cancel, progress=progress)
        finally:
            lock.release()

    def recycle(self, originals: Sequence[VerifiedOriginal]) -> list[tuple[Path, str]]:
        """Send ``ImportResult.verified`` records to the Recycle Bin, each
        re-checked against its canonical copy first; returns the refused or
        failed ones. Nothing inside the mirror folder is ever touched."""
        cfg = self._usable_config()
        return send_to_recycle_bin(list(originals), canonical_root=cfg.mirror_root)


# ------------------------------------------------------------------ helpers ---

def _drop(event: object) -> None:
    """Sink for the internal read-only operations (plan/rescan): the UI shows
    progress for the jobs it started, not for a status refresh."""


def _clean_text(value: str | None) -> str | None:
    """``None`` for schtasks' placeholders (``""``, ``N/A``, ``N/D``, ...)."""
    if value is None:
        return None
    text = value.strip()
    return None if text.lower() in NO_VALUE_STRINGS else text


def _clean_path(value: Path | None) -> Path | None:
    """None for a path that is only a schtasks placeholder.

    Compared as POSIX text: ``Path("N/D")`` prints as ``N\\D`` on Windows,
    which would slip past the placeholder list.
    """
    text = _clean_text(value.as_posix()) if value is not None else None
    return Path(text) if text else None


def _tail(path: Path, n: int) -> list[str]:
    """Last ``n`` lines of a log file; a missing or unreadable file gives ``[]``.

    Read whole: ``sync.log`` rotates at 1 MB, so this is cheap and much simpler
    than seeking backwards.
    """
    if n <= 0:
        return []
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return text.splitlines()[-n:]
