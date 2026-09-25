"""The boundary the UI is written against: seven Protocols plus the core dataclasses.

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
  too (``core.facade``), not a UI invention. The Officina types come from
  ``qtrequestory.officina`` (model, generator, compare, service) the same way.
* **Officina stays lazy.** Importing this module imports only the light,
  stdlib-only Officina modules (never pypdfium2), and ``CoreServices.officina``
  builds the real service on first use, not in ``CoreServices.real()``.
* **No adapter code in the UI.** If the core's shape does not fit what a page
  needs, the adapter goes into ``core/facade.py`` — never into a widget.

Progress is reported through ``EventSink``: core functions call it from the
worker thread with the event dataclasses of ``core.events``; ``ui/workers.py``
turns those into queued Qt signals. Cancellation is a ``CancelToken``.
"""
from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

from qtrequestory import __version__
from qtrequestory.core.archive import (
    CONFLICT,
    DUPLICATE,
    IGNORED,
    IMPORTABLE,
    NEEDS_ENV,
    ArchiveReport,
    FoundLog,
)
from qtrequestory.core.config import (
    IGNORE_FOLDER,
    GeneratorEndpoint,
    OfficinaSettings,
    REPEAT_EVERY_RANGE,
    REPEAT_FOR_RANGE,
    Config,
    ConfigError,
    Environment,
    IndexSettings,
    ScheduleSettings,
    SyncSettings,
    OFFICINA_TIMEOUT_RANGE,
    default_generator_problem,
    generator_problems,
    header_problems,
    officina_root_errors,
    parse_hhmm,
    postman_token_problem,
    sanitised_schedule,
)
from qtrequestory.core.daily import CoverageDays, EntryName, LocalDailyFile, parse_entry_name
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
from qtrequestory.core.facade import ArchiveBusy, EnvStatus
from qtrequestory.core.fsutil import real_is_within
from qtrequestory.core.state import Freshness
from qtrequestory.core.index.builder import IndexPlan, IndexStats
from qtrequestory.core.importer import ImportResult, VerifiedOriginal
from qtrequestory.core.index.search import Coverage, IndexStale, SearchHit, SearchQuery, pick_best
from qtrequestory.core.jobs import JobReport
from qtrequestory.core.paths import AppPaths
from qtrequestory.core.scheduler import NOT_REGISTERED, SchedulerError, TaskSpec, TaskStatus
from qtrequestory.core.sync import EnvResult, SyncReport
from qtrequestory.officina.compare.extract_pdf import DocText, Word
from qtrequestory.officina.compare.textdiff import Difference, TextComparison
from qtrequestory.officina.delivery import (
    DeliveryItem,
    DeliveryPlan,
    DeliveryReport,
    MissingSlot,
    delivery_folder,
    safe_component,
    zip_destination,
)
from qtrequestory.officina.generator import SendResult
from qtrequestory.officina.model import AsisAlreadyExistsError, Case, Initiative, Version
from qtrequestory.officina.links import mask_text
from qtrequestory.officina.service import CompareError

__all__ = [
    # protocols + bundle
    "ConfigApi", "SyncApi", "SchedulerApi", "IndexApi", "ExtractApi", "ArchiveApi", "OfficinaApi",
    "CoreServices",
    # Officina (qtrequestory.officina: model, generator, compare, service)
    "Initiative", "Case", "Version", "SendResult", "TextComparison", "Difference", "Word", "DocText",
    "CompareError", "AsisAlreadyExistsError", "OfficinaSettings", "GeneratorEndpoint",
    "mask_text", "DeliveryItem", "DeliveryPlan", "DeliveryReport", "MissingSlot",
    # archive import (core/archive.py, core/importer.py)
    "ArchiveBusy", "ArchiveReport", "FoundLog", "ImportResult", "VerifiedOriginal", "IGNORE_FOLDER",
    "IMPORTABLE", "DUPLICATE", "NEEDS_ENV", "CONFLICT", "IGNORED",
    # re-exported core types
    "AppPaths", "CancelToken", "Cancelled", "Config", "ConfigError", "Coverage", "CoverageDays", "EntryName",
    "Environment", "EnvResult", "EnvStatus", "Event", "EventSink", "Freshness", "IndexPlan", "IndexSettings",
    "IndexStale", "IndexStats", "JobReport", "LocalDailyFile", "NOT_REGISTERED", "ScheduleSettings",
    "SchedulerError", "SearchHit", "SearchQuery", "SyncReport", "SyncSettings", "TaskSpec",
    "TaskStatus",
    # the core helpers the UI is allowed to call directly (pure functions, no I/O)
    "parse_entry_name", "parse_hhmm", "sanitised_schedule",
    # the limits config.validate enforces on a schedule (the Impostazioni spin boxes)
    "REPEAT_EVERY_RANGE", "REPEAT_FOR_RANGE",
    # the Officina rules config.validate applies, per row (the Impostazioni tables)
    "generator_problems", "default_generator_problem", "header_problems", "postman_token_problem",
    "officina_root_errors",
    "OFFICINA_TIMEOUT_RANGE",
    "pick_best",
    # "inside the archive" as the Recycle Bin guard decides it (junctions resolved)
    "real_is_within",
    # the delivery's names (pure: the dialog's preview uses them)
    "safe_component", "delivery_folder", "zip_destination",
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

    def mirror_root_errors(self, cfg: Config) -> list[str]:
        """Only the ``mirror_root`` problems (empty or relative folder).

        The same gate the CLI applies before ``--sync``/``--index``/``--find``
        (exit 2): while this is not empty the window starts no sync and no
        index job, which would otherwise write into the process's CWD.
        """
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

    def check_reachable(self, env: Environment, timeout: float = 5.0) -> bool:
        """One short HTTP GET of the autoindex. Never raises; blocking, so call
        it from a worker.

        Takes the whole ``Environment``, not its name: both callers — the
        first-run wizard and Impostazioni — probe rows that are still being
        edited and have never been saved, so there is no configuration to
        resolve a name against. Pass the row under the user's cursor.
        """
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
        """Description of the process currently syncing, or None when free.

        Read-only and cheap (one small file read plus a PID check): it never
        takes the lock, so the page may poll it on a timer while visible.
        """
        ...

    def sync_log_path(self) -> Path:
        ...

    def tail_sync_log(self, n: int) -> list[str]:
        """Last ``n`` lines of ``sync.log`` (empty when it does not exist yet)."""
        ...

    def is_fresh(self, env_name: str) -> bool:
        """True when this env was already synced after the last compaction."""
        ...

    def freshness(self, env_name: str) -> Freshness:
        """How the mirror reads: ``"fresh"`` (``is_fresh``), ``"empty_today"``
        (not fresh only because today had no calls: shown as up to date) or
        ``"stale"``. Display only; ``is_fresh`` decides what a run skips."""
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

    def coverage_days(self, env: str, days: int = 30, today: date | None = None) -> CoverageDays:
        """Every day of the ``days`` days before ``today`` (default: today's
        date) classified: present / empty locally, pending (still on the
        server), lost (purged before being downloaded) or unknown. Today
        itself is excluded — its file is complete only after the evening
        compaction. ``CoverageDays.missing`` is pending + lost. Read from the
        local mirror and the sync state, not the index, so it is right even
        before indexing runs.
        """
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


# ------------------------------------------------------------------ archive ---

@runtime_checkable
class ArchiveApi(Protocol):
    """Logs outside ``<mirror>/<env>/YYYY/MM/YYYYMMDD.txt``: find, import, recycle."""

    def report(self, path: Path | None = None, *,
               canonical_root: Path | None = None) -> ArchiveReport:
        """Classify every file under ``path`` (None: the mirror folder itself)
        as importable / duplicate_same / needs_env / conflict / ignored, using
        the configured env names and ``Config.folder_envs``. ``canonical_root``
        (None: the mirror) is the tree whose canonical files are skipped; the
        wizard passes the folder about to become the mirror. Read-only; reads
        every candidate, so call it from a worker. ``ValueError`` while the
        mirror folder is not usable (``mirror_root_errors``)."""
        ...

    def import_(self, report: ArchiveReport, *, cancel=None, progress=None) -> ImportResult:
        """Copy + verify the importable files into the mirror. ``cancel`` has
        ``is_set()`` (a ``CancelToken``); ``progress(done, total, rel_path)``
        runs on the worker thread. ``ArchiveBusy`` while a sync holds the lock.
        Does not index: run ``index.update(result.envs)`` afterwards."""
        ...

    def recycle(self, originals: Sequence[VerifiedOriginal]) -> list[tuple[Path, str]]:
        """Send ``ImportResult.verified`` records (nothing else is accepted)
        to the Recycle Bin, each re-checked right before: unchanged since the
        verification and still contained in its canonical copy. Returns the
        refused or failed ones with an Italian reason. Never touches anything
        inside the mirror folder, under any spelling."""
        ...


# ----------------------------------------------------------------- officina ---

@runtime_checkable
class OfficinaApi(Protocol):
    """The Officina tab: initiatives and cases on disk, generation against the
    Inspire Scaler, text comparison. The blocking methods (``generate``,
    ``compare``, ``case_from_hit``) run in a worker.

    Everything is read from and written to the Officina folder
    (``Config.officina.root``). While it is not set, ``workspace_root()`` is
    None, ``initiatives()`` is empty and every write raises ``ValueError``.
    """

    def workspace_root(self) -> Path | None:
        """The Officina folder, or None while it is not chosen (or not absolute)."""
        ...

    def initiatives(self) -> list[Initiative]:
        """Every initiative under the root, with its cases (read from disk)."""
        ...

    def create_initiative(self, name: str) -> Initiative:
        """``FileExistsError`` for a name already used; ``ValueError`` for a
        blank name or no root."""
        ...

    def load(self, initiative_id: str) -> Initiative:
        """Re-read one initiative from disk, by its id: its FOLDER's name
        (``Initiative.id``), never its display name — a folder copied in
        Explorer keeps the original's name. ``FileNotFoundError`` if it is
        gone. An unreadable ``iniziativa.json`` loads with ``load_error`` set."""
        ...

    def case_from_hit(self, ini: Initiative, hit: SearchHit, variant: str = "") -> Case:
        """A new case from a Ricerca hit: the payload is the hit's body (read
        through ``IndexApi.read_body``), key and FDI come from the hit, the env
        is the default generator. ``ValueError`` when the body is not a JSON
        object, and ``ValueError("la chiamata non è più nel log locale:
        ripetere la ricerca")`` when the daily file was rewritten or deleted
        since the search (no case is created); ``FileExistsError`` for a
        key+variant already in the initiative."""
        ...

    def case_from_file(self, ini: Initiative, path: Path, key: str, variant: str = "") -> Case:
        """A new case from a JSON file (UTF-8, BOM allowed), without a source
        FDI. ``ValueError`` for a blank key or a file that is not a JSON object."""
        ...

    def save_case(self, case: Case) -> None:
        """Merge into ``caso.json``. ``ValueError`` (nothing written) for a
        case with ``load_error``, or whose file is unreadable now."""
        ...

    def payload(self, case: Case) -> dict:
        """The case's payload as edited; ``{}`` when missing or unreadable."""
        ...

    def save_payload(self, case: Case, payload: dict) -> None:
        """The first save keeps the original as ``payload.original.json``."""
        ...

    def set_target(self, case: Case, src: Path) -> Version:
        """Copy ``src`` in as the TARGET, under its original name."""
        ...

    def generate(
        self,
        ini: Initiative,
        case: Case,
        kind: Literal["asis", "tobe"],
        *,
        replace_asis_note: str | None = None,
        cancel=None,
    ) -> tuple[Version | None, SendResult]:
        """Send the case to its generator and store the answer as the AS-IS or
        the next TO-BE.

        Never raises for a refused or failed run: it returns ``(None, result)``
        with ``result.ok`` False and an Italian ``reason``, and writes nothing.
        Refused before sending: an env that is not an enabled generator, an
        existing AS-IS without ``replace_asis_note``, a header problem, a
        still-valid upload link, an empty payload, ``cancel`` already set.
        After sending, an answer of the wrong type for the case (e.g. HTML for
        a PDF case: a gateway error page) is a failed run too.
        """
        ...

    def compare(self, left: Version, right: Version) -> TextComparison:
        """Word diff of ``left`` (the reference, usually the TARGET) against
        ``right``. HTML is printed to PDF by Edge first, under the case's
        ``cache`` folder. Cached by content hash.

        ``CompareError`` (Italian message) when it cannot be made: a file gone,
        an unreadable PDF, Edge missing or failing. A side without text is a
        result, not an error: the ``note`` says so and there are no differences.
        """
        ...

    def render_path(self, case: Case, version: Version) -> Path:
        """The PDF the viewer renders for ``version``: the version file itself
        for a PDF; for an HTML, its Edge print in the case's ``cache`` folder
        (converted now if needed — the same file ``compare`` uses, so call it
        from a worker). ``CompareError`` when the file is gone or the
        conversion fails."""
        ...

    # -- delivery to the testers (spec §8) ---------------------------------

    def delivery_plan(self, ini: Initiative, case_ids: Sequence[str]) -> DeliveryPlan:
        """The files a delivery of ``case_ids`` writes (``dest_rel`` relative
        to ``<destination>/<Iniziativa>``) and the slots it skips. Reads only
        the Officina folder (quick enough for the GUI thread)."""
        ...

    def delivery_conflicts(self, ini: Initiative, items: Sequence[DeliveryItem], destination: Path,
                           *, make_zip: bool) -> list[Path]:
        """The files already at the destination (to ask about them first).
        Touches the destination, which may be a synced folder: call it from a worker."""
        ...

    def deliver(self, ini: Initiative, items: Sequence[DeliveryItem], destination: Path, *,
                on_conflict: Callable[[Path], Literal["replace", "keep_both", "skip"]],
                make_zip: bool, cancel: CancelToken | None = None) -> DeliveryReport:
        """Copy ``items`` (and, with ``make_zip``, zip exactly this delivery:
        the files written plus the existing ones kept with "Salta" — nothing
        else in the folder, never through a symbolic link) and remember
        ``destination`` as the initiative's last one. Never overwrites a file
        without ``on_conflict``; a file that fails is in ``report.failed`` and
        the others are still delivered; one written under another name is in
        ``report.renamed``. ``ValueError`` for a relative destination."""
        ...

    def last_delivery_destination(self, ini: Initiative) -> Path | None:
        """Where the initiative was last delivered, or None."""
        ...


# ----------------------------------------------------------- service bundle ---

_OFFICINA_LOCK = threading.Lock()


@dataclass(frozen=True)
class CoreServices:
    """Everything the UI needs from the core, in one object to pass around.

    ``MainWindow`` receives one of these and hands it to the pages; tests pass
    the fake bundle instead. Nothing else is injected.

    ``officina`` is a property: ``officina_factory`` builds the service on
    first access (once, thread-safe), so starting the app or the CLI never
    pays for the Officina. ``dataclasses.replace(services, ...)`` does not copy
    that cache: the new bundle builds its own service on its first access.
    """

    config: ConfigApi
    sync: SyncApi
    scheduler: SchedulerApi
    index: IndexApi
    extract: ExtractApi
    archive: ArchiveApi
    paths: AppPaths
    app_version: str = __version__
    officina_factory: Callable[[], OfficinaApi] | None = field(default=None, repr=False, compare=False)

    @property
    def officina(self) -> OfficinaApi:
        """The Officina service, built on first access."""
        built = self.__dict__.get("_officina")
        if built is not None:
            return built
        with _OFFICINA_LOCK:
            built = self.__dict__.get("_officina")
            if built is None:
                if self.officina_factory is None:
                    raise RuntimeError("Officina non disponibile: nessun servizio configurato")
                built = self.officina_factory()
                object.__setattr__(self, "_officina", built)  # frozen: cached outside the fields
        return built

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
        index = facade.IndexService(config.current)

        def officina() -> OfficinaApi:
            from qtrequestory.officina.service import OfficinaService

            return OfficinaService(config.current, index=index)

        return cls(
            config=config,
            sync=facade.SyncService(config.current, paths=resolved),
            scheduler=facade.SchedulerService(config_source=config.current),
            index=index,
            extract=facade.ExtractService(config.current),
            archive=facade.ArchiveService(config.current),
            paths=resolved,
            officina_factory=officina,
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
