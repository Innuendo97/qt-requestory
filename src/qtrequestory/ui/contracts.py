"""The boundary the UI is written against: five Protocols plus the core dataclasses.

Every widget, presenter and worker in ``qtrequestory.ui`` takes its core
functionality from a ``CoreServices`` bundle and never imports a core module
directly. Two implementations satisfy these Protocols:

* the real services in ``qtrequestory.core.facade`` (``CoreServices.real()``);
* the in-memory ones in ``tests/fakes/fake_core.py`` (scripted events, synthetic
  hits, settable task status), which is what the UI tests run against.

Rules that keep that swap free of surprises:

* **No Qt here.** The fakes and plain unit tests import this module without a
  ``QApplication``; only typing and core dataclasses are allowed.
* **No new dataclasses.** Everything returned is the core's own type, re-exported
  below so the UI has a single import surface. ``EnvStatus`` is a core dataclass
  too (``core.facade``), not a UI invention.
* **No adapter code in the UI.** If the core's shape does not fit what a page
  needs, the adapter goes into ``core/facade.py`` — never into a widget.

Progress is reported through ``EventSink``: core functions call it from the
worker thread with the event dataclasses of ``core.events``; ``ui/workers.py``
turns those into queued Qt signals. Cancellation is a ``CancelToken``.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from qtrequestory import __version__
from qtrequestory.core.config import (
    Config,
    ConfigError,
    Environment,
    IndexSettings,
    ScheduleSettings,
    SyncSettings,
    parse_hhmm,
)
from qtrequestory.core.daily import EntryName, LocalDailyFile, parse_entry_name
from qtrequestory.core.events import (
    CancelToken,
    Cancelled,
    EnvFinished,
    EnvSkipped,
    EnvStarted,
    EnvUnreachable,
    Event,
    EventSink,
    FileDone,
    FileFailed,
    FileProgress,
    FileSkipped,
    FileStarted,
    IndexFileScanned,
    IndexFinished,
    IndexStarted,
    LogMessage,
    RemoteIndexRead,
    SyncFinished,
    SyncStarted,
)
from qtrequestory.core.facade import EnvStatus
from qtrequestory.core.index.builder import IndexPlan, IndexStats
from qtrequestory.core.index.search import Coverage, IndexStale, SearchHit, SearchQuery
from qtrequestory.core.jobs import JobReport
from qtrequestory.core.paths import AppPaths
from qtrequestory.core.scheduler import NOT_REGISTERED, SchedulerError, TaskSpec, TaskStatus
from qtrequestory.core.sync import EnvResult, SyncReport

__all__ = [
    # protocols + bundle
    "ConfigApi", "SyncApi", "SchedulerApi", "IndexApi", "ExtractApi", "CoreServices",
    # re-exported core types
    "AppPaths", "CancelToken", "Cancelled", "Config", "ConfigError", "Coverage", "EntryName",
    "Environment", "EnvResult", "EnvStatus", "Event", "EventSink", "IndexPlan", "IndexSettings",
    "IndexStale", "IndexStats", "JobReport", "LocalDailyFile", "NOT_REGISTERED", "ScheduleSettings",
    "SchedulerError", "SearchHit", "SearchQuery", "SyncReport", "SyncSettings", "TaskSpec",
    "TaskStatus",
    # the two core helpers the UI is allowed to call directly (pure parsing)
    "parse_entry_name", "parse_hhmm",
    # events (the sink payloads the UI renders)
    "SyncStarted", "EnvStarted", "EnvSkipped", "EnvUnreachable", "RemoteIndexRead", "FileSkipped",
    "FileStarted", "FileProgress", "FileDone", "FileFailed", "EnvFinished", "SyncFinished",
    "IndexStarted", "IndexFileScanned", "IndexFinished", "LogMessage",
]


# ------------------------------------------------------------------- config ---

@runtime_checkable
class ConfigApi(Protocol):
    """``config.json``: first-run detection, load/save, validation, sidecars."""

    def is_first_run(self) -> bool:
        """True when no configuration exists yet (the wizard must run)."""
        ...

    def load(self) -> Config:
        """Current configuration; the defaults when no file exists yet.

        Reading never creates the file: ``is_first_run`` must stay True until
        something explicitly ``save``s, or a cancelled wizard would never be
        offered again.
        """
        ...

    def save(self, cfg: Config) -> None:
        """Persist ``cfg`` atomically; later ``load()`` calls return it."""
        ...

    def validate(self, cfg: Config) -> list[str]:
        """Italian error messages for Impostazioni; empty list means valid."""
        ...

    def detect_editor(self) -> Path | None:
        """Notepad++ if it can be found, else None."""
        ...

    def import_environments_file(self, path: Path) -> list[Environment]:
        """Parse an ``environments.json``; ``ValueError`` when malformed."""
        ...

    def find_sidecar_environments(self) -> Path | None:
        """``environments.json`` next to the executable, if present."""
        ...

    def config_path(self) -> Path:
        ...


# --------------------------------------------------------------------- sync ---

@runtime_checkable
class SyncApi(Protocol):
    """Mirror status and the sync job."""

    def env_status(self, env_name: str) -> EnvStatus:
        """Card data for one environment (last sync, local files, index backlog).

        Cheap: state file + directory listing + an index plan, no network.
        """
        ...

    def check_reachable(self, env_name: str, timeout: float = 5.0) -> bool:
        """One short HTTP GET of the autoindex. Never raises; blocking, so call
        it from a worker."""
        ...

    def run(
        self,
        envs: Sequence[str] | None = None,
        *,
        force: bool = False,
        dry_run: bool = False,
        sink: EventSink,
        cancel: CancelToken,
    ) -> JobReport:
        """Download, then index. ``envs=None`` means every enabled environment.

        Emits the sync events (``SyncStarted`` ... ``SyncFinished``) and then the
        index ones to ``sink``. Refuses nothing: when another process holds the
        lock it logs one ``LogMessage`` and returns ``exit_code == 0`` with
        ``sync is None``. ``JobReport.exit_code``: 0 ok, 1 file errors,
        2 nothing reachable, 3 cancelled.
        """
        ...

    def lock_holder(self) -> str | None:
        """Description of the process currently syncing, or None when free."""
        ...

    def sync_log_path(self) -> Path:
        ...

    def tail_sync_log(self, n: int) -> list[str]:
        """Last ``n`` lines of ``sync.log`` (empty when it does not exist yet)."""
        ...

    def is_fresh(self, env_name: str) -> bool:
        """True when this env was already synced after the last compaction."""
        ...


# ---------------------------------------------------------------- scheduler ---

@runtime_checkable
class SchedulerApi(Protocol):
    """The Windows scheduled task that keeps the mirror complete."""

    def status(self) -> TaskStatus:
        """Snapshot of the task. ``state``/``next_run``/``last_run`` are the
        localised strings schtasks prints, or None when it reports no value."""
        ...

    def register(self) -> None:
        """Create/overwrite the task. ``SchedulerError`` on failure (including
        "running from source": there is no exe to schedule)."""
        ...

    def unregister(self) -> None:
        ...

    def run_now(self) -> None:
        ...

    def detect_legacy_task(self) -> bool:
        """True when the old PowerShell task is still registered."""
        ...

    def remove_legacy_task(self) -> None:
        ...

    def exe_path(self) -> Path | None:
        """The executable the task would point at; None when run from source."""
        ...

    def unstable_location_reason(self) -> str | None:
        """Why scheduling this exe is a bad idea (%TEMP%, Downloads, OneDrive,
        UNC), in Italian, or None."""
        ...


# -------------------------------------------------------------------- index ---

@runtime_checkable
class IndexApi(Protocol):
    """Index maintenance plus the queries the Ricerca page runs."""

    def plan(self, envs: Sequence[str]) -> IndexPlan:
        """What an update would scan/remove — used to show "N file da indicizzare"."""
        ...

    def update(
        self,
        envs: Sequence[str] | None = None,
        *,
        full_rebuild: bool = False,
        sink: EventSink,
        cancel: CancelToken,
    ) -> JobReport:
        """(Re)index the local mirror, emitting the index events to ``sink``."""
        ...

    def coverage(self, env: str) -> Coverage | None:
        """First/last indexed day and the counts, or None when nothing is indexed."""
        ...

    def count_local_files(self, root: Path | None = None) -> int:
        """Daily files present under ``root`` (default: the configured mirror
        root), across every env folder.

        The wizard passes the folder the user just browsed to, before any
        configuration has been saved: "Trovati N file di log già presenti".
        """
        ...

    def list_template_keys(self, env: str, prefix: str = "") -> list[str]:
        """Keys for the picker, most recently seen first."""
        ...

    def search(self, query: SearchQuery) -> list[SearchHit]:
        """Most recent first. ``ValueError`` without an FDI prefix or a key."""
        ...

    def read_body(self, hit: SearchHit) -> bytes:
        """The raw body bytes of ``hit``.

        A stale index is healed transparently (rescan + retry), so the UI does
        not handle ``IndexStale``; only a body that really vanished raises.
        """
        ...

    def db_path(self) -> Path:
        ...


# ------------------------------------------------------------------ extract ---

@runtime_checkable
class ExtractApi(Protocol):
    """Turn a hit into a file the user can open, save or copy."""

    def pretty_json(self, raw: bytes) -> str:
        """4-space pretty JSON starting with ``{\\n    "documents": [``; an
        unparseable body is wrapped instead of raising."""
        ...

    def output_name(self, hit: SearchHit) -> str:
        """``<YYYYMMDD>_<fdi|nofdi>_<TEMPLATE_KEY>.json``."""
        ...

    def write_temp_file(self, hit: SearchHit, text: str) -> Path:
        """Write ``text`` into the output dir (after housekeeping) and return it."""
        ...

    def save_as(self, path: Path, text: str) -> None:
        """UTF-8 without BOM, LF."""
        ...

    def open_in_editor(self, paths: Sequence[Path]) -> str:
        """Open the files in Notepad++ (one window) or the default handler;
        returns ``"editor"`` or ``"default"`` for the status bar."""
        ...

    def open_folder(self, path: Path) -> None:
        ...

    def output_dir(self) -> Path:
        ...


# ----------------------------------------------------------- service bundle ---

@dataclass(frozen=True)
class CoreServices:
    """Everything the UI needs from the core, in one object to pass around.

    ``MainWindow`` receives one of these and hands it to the pages; tests pass
    the fake bundle instead. Nothing else is injected.
    """

    config: ConfigApi
    sync: SyncApi
    scheduler: SchedulerApi
    index: IndexApi
    extract: ExtractApi
    paths: AppPaths
    app_version: str = __version__

    @classmethod
    def real(cls, paths: AppPaths | None = None) -> CoreServices:
        """The real core, wired up — the integration task's one-liner.

        Every service reads the configuration through ``ConfigService.current``,
        so a save in Impostazioni is visible everywhere without rebuilding.
        """
        from qtrequestory.core import facade
        from qtrequestory.core.paths import app_paths

        resolved = paths if paths is not None else app_paths().ensure()
        config = facade.ConfigService(resolved)
        return cls(
            config=config,
            sync=facade.SyncService(config.current, paths=resolved),
            scheduler=facade.SchedulerService(config_source=config.current),
            index=facade.IndexService(config.current),
            extract=facade.ExtractService(config.current),
            paths=resolved,
        )

    # -- misc accessors the Info page shows ---------------------------------

    def version(self) -> str:
        return self.app_version

    def app_log_path(self) -> Path:
        return self.paths.app_log

    def sync_log_path(self) -> Path:
        return self.sync.sync_log_path()

    def index_db_path(self) -> Path:
        return self.index.db_path()
