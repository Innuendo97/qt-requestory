"""In-memory core for the UI tests: everything ``ui/contracts.py`` declares.

The six UI tasks are written against these fakes without ever seeing the real
core, so a fake must behave like the real thing in every way a UI test can
observe: the same return types (core dataclasses, never look-alikes), the same
event sequence and ordering, the same cancellation behaviour and the same
exceptions (``ValueError`` from an unbounded search, ``IndexStale`` for a body
that vanished).

Everything is synthetic — the data comes from ``tests/conftest.py`` helpers.
No Qt, no network, no SQLite, no subprocess: building a fake core costs a
directory and a list of dataclasses.

Knobs the tests use (all plain attributes/setters, no magic):

* ``FakeSyncApi.set_unreachable(env)`` / ``set_failing(env, n)`` / ``set_fresh(env)``
  / ``set_ok(env)`` — the four outcomes a Sincronizzazione card can show
* ``FakeSyncApi.set_lock_holder(text)``, ``FakeSyncApi.set_env_status(env, ...)``
* ``FakeSyncApi.step_delay`` — seconds between scripted events (default tiny)
* ``FakeSchedulerApi.set_status(...)`` / ``set_legacy(flag)``
* ``FakeIndexApi.set_missing(hit)`` — ``read_body`` of that hit raises ``IndexStale``
* ``FakeIndexApi.set_pending(n)`` — n files waiting to be indexed
* ``FakeIndexApi.set_local_days(env, days, empty=())`` / ``set_server_days(env,
  listed=(), seen=())`` — what ``coverage_days`` classifies (local files, and
  the listing memory of the sync state)
* ``FakeArchiveApi.set_report(report)`` / ``set_busy(flag)``; ``recycled`` lists
  what "went to the Recycle Bin" (only files under the fake root are removed)
"""
from __future__ import annotations

import copy
import dataclasses
import logging
import time
from collections.abc import Callable, Iterable, Sequence
from datetime import date, datetime
from pathlib import Path

from qtrequestory.core import archive as archive_mod
from qtrequestory.core import extract as extract_mod
from qtrequestory.core import importer as importer_mod
from qtrequestory.core.archive import ArchiveReport
from qtrequestory.core.fsutil import is_within
from qtrequestory.core.config import (
    Config,
    Environment,
    UnknownEnvironment,
    default_config,
    mirror_root_errors as core_mirror_root_errors,
    validate as core_validate,
)
from qtrequestory.core.events import (
    CancelToken,
    EnvFinished,
    EnvSkipped,
    EnvStarted,
    EnvUnreachable,
    EventSink,
    FileDone,
    FileFailed,
    FileProgress,
    FileStarted,
    IndexFileScanned,
    IndexFinished,
    IndexStarted,
    LogMessage,
    RemoteIndexRead,
    SyncFinished,
    SyncStarted,
)
from qtrequestory.core.daily import CoverageDays, LocalDailyFile
from qtrequestory.core.daily import classify_days as core_classify_days
from qtrequestory.core.facade import ArchiveBusy, EnvStatus
from qtrequestory.core.index.builder import IndexPlan
from qtrequestory.core.index.search import (
    Coverage,
    IndexStale,
    SearchHit,
    SearchQuery,
    output_name_for,
    output_name_with_id,
)
from qtrequestory.core.jobs import JobReport
from qtrequestory.core.paths import AppPaths
from qtrequestory.core.scheduler import NOT_REGISTERED, SchedulerError, TaskStatus
from qtrequestory.core.sync import EnvResult, SyncReport
from qtrequestory.ui.contracts import CoreServices

from tests.conftest import FDI_A, FDI_B, FDI_C, KEY_CTE, KEY_EMAIL, KEY_SINT, synthetic_body

ENVS = ("coll", "svil")
DAYS = (date(2026, 9, 18), date(2026, 9, 16), date(2026, 9, 15))
#: 12 hits over 3 days x 3 FDIs, the shape the Ricerca page renders.
HIT_SPECS: tuple[tuple[date, str, str, str, int | None, str | None], ...] = (
    (DAYS[0], FDI_A, KEY_SINT, "1a2b3c0200000031", 3, "2026-09-18T10:38:28.776Z"),
    (DAYS[0], FDI_A, KEY_EMAIL, "1a2b3c0200000032", 5, "2026-09-18T10:38:31.100Z"),
    (DAYS[0], FDI_A, KEY_CTE, "1a2b3c0200000033", 2, None),
    (DAYS[0], FDI_B, KEY_SINT, "1a2b3c0100000040", 2, "2026-09-18T12:10:43.279Z"),
    (DAYS[0], FDI_B, KEY_CTE, "1a2b3c0100000041", 2, "2026-09-18T12:11:02.010Z"),
    (DAYS[1], FDI_A, KEY_SINT, "1a2b3c0200000021", 2, "2026-09-16T08:15:00.000Z"),
    (DAYS[1], FDI_C, KEY_SINT, "10b6016c00000022", 4, "2026-09-16T09:20:10.500Z"),
    (DAYS[1], FDI_C, KEY_EMAIL, "10b6016c00000023", 2, "2026-09-16T09:20:12.000Z"),
    (DAYS[2], FDI_A, KEY_CTE, "1a2b3c0200000011", 2, "2026-09-15T07:05:00.000Z"),
    (DAYS[2], FDI_B, KEY_EMAIL, "1a2b3c0100000012", 2, "2026-09-15T08:00:00.000Z"),
    (DAYS[2], FDI_C, KEY_CTE, "10b6016c00000013", 6, "2026-09-15T09:00:00.000Z"),
    (DAYS[2], FDI_C, KEY_SINT, "10b6016c00000014", 2, None),
)

#: Scripted download the fake sync "performs" per environment.
SCRIPT_FILE_NAME = "20260918.txt"
SCRIPT_FILE_SIZE = 4 * 1_048_576
SCRIPT_PROGRESS_STEPS = 4
#: Daily files the scripted remote index holds besides the downloaded one: two
#: already in the mirror and one empty. ``RemoteIndexRead`` announces them and
#: every ``EnvResult`` produced after it reports the very same numbers.
SCRIPT_PRESENT = 2
SCRIPT_EMPTY = 1
#: What the autoindex lists: the downloaded file plus the present and empty
#: ones (the engine's ``len(index.daily)``, which counts the empty entries).
SCRIPT_N_DAILY = 1 + SCRIPT_PRESENT + SCRIPT_EMPTY
#: Files the index phase "scans" after a successful scripted sync.
SCRIPT_INDEXED_FILES = 2
#: Small by default so a UI test that drives the whole sequence stays fast, but
#: non-zero so the worker really yields and the UI shows intermediate progress.
DEFAULT_STEP_DELAY_S = 0.002


def _body(spec) -> bytes:
    day, fdi, key, call_id, ndocs, request_date = spec
    return synthetic_body(fdi, key, request_date=request_date, ndocs=ndocs or 2)


def _hit(entry_id: int, spec, root: Path) -> SearchHit:
    day, fdi, key, call_id, ndocs, request_date = spec
    body = _body(spec)
    rel = f"{ENVS[0]}/{day:%Y}/{day:%m}/{day:%Y%m%d}.txt"
    name = f"{fdi}_{key}_{call_id}"
    return SearchHit(
        entry_id=entry_id,
        env=ENVS[0],
        day=day,
        rel_path=rel,
        seq=entry_id,
        name=name,
        fdi=fdi,
        template_key=key,
        call_id=call_id,
        well_formed=True,
        request_date=request_date,
        ndocs=ndocs,
        dossier_number="DA00000001",
        header_offset=entry_id * 1024,
        header_len=64,
        body_offset=entry_id * 1024 + 64,
        body_len=len(body),
        json_ok=True,
        file_path=root / rel,
    )


# ------------------------------------------------------------------- config ---

class FakeConfigApi:
    """Mutable in-memory configuration; save/load never touch the disk."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self.config = dataclasses.replace(
            default_config(),
            mirror_root=root / "mirror",
            environments=[Environment(name, f"https://example.invalid/{name}/") for name in ENVS],
            output_dir=root / "out",
        )
        self.first_run = False
        self.editor: Path | None = None
        self.sidecar: Path | None = None
        self.sidecar_environments: list[Environment] = [
            Environment(name, f"https://example.invalid/{name}/") for name in ENVS
        ]
        self.saved: list[Config] = []
        self.import_error: str | None = None

    def set_import_error(self, message: str | None) -> None:
        """Make every ``import_environments_file`` raise ``ValueError(message)``
        (the wizard's malformed-file path) until ``None`` clears it again."""
        self.import_error = message

    def is_first_run(self) -> bool:
        return self.first_run

    def load(self) -> Config:
        """A fresh copy, never the stored instance.

        The real ``load()`` re-parses ``config.json`` on every call, so two
        calls never return the same object and a caller that mutates what it
        got back cannot corrupt what the next ``load()`` returns. Handing out
        ``self.config`` itself used to let exactly that happen.
        """
        return copy.deepcopy(self.config)

    def save(self, cfg: Config) -> None:
        self.config = cfg
        self.saved.append(cfg)

    def validate(self, cfg: Config) -> list[str]:
        return core_validate(cfg)

    def mirror_root_errors(self, cfg: Config) -> list[str]:
        return core_mirror_root_errors(cfg)

    def detect_editor(self) -> Path | None:
        return self.editor

    def import_environments_file(self, path: Path) -> list[Environment]:
        if self.import_error is not None:
            raise ValueError(self.import_error)
        return list(self.sidecar_environments)

    def find_sidecar_environments(self) -> Path | None:
        return self.sidecar

    def config_path(self) -> Path:
        return self._root / "config.json"


# --------------------------------------------------------------------- sync ---

class FakeSyncApi:
    """Scripted sync: a fixed event sequence per env, honouring the cancel token."""

    def __init__(self, root: Path, paths: AppPaths, config_source: Callable[[], Config]) -> None:
        self._root = root
        self._paths = paths
        #: Same contract as ``core.facade.SyncService``: ``run(envs=None)``
        #: targets ``config.enabled_environments()`` and an explicit name not
        #: in ``config.environments`` is ``UnknownEnvironment`` (see ``run``).
        self._config_source = config_source
        self.step_delay = DEFAULT_STEP_DELAY_S
        #: env -> "ok" | "unreachable" | "errors" | "fresh" (default "ok")
        self._outcomes: dict[str, str] = {}
        self._n_failures: dict[str, int] = {}
        self.holder: str | None = None
        self.runs: list[dict] = []
        self.log_lines = [f"[2026-09-22 09:0{i}:00] coll: scaricato 2026091{i}.txt (12,5 MB)" for i in range(4)]
        #: "coll" looks like a mirror synced before, "svil" like a never-synced
        #: one. Neither starts *fresh*: the default outcome is "ok" (a scripted
        #: download), and ``is_fresh`` must agree with what a non-forced ``run``
        #: does — an env whose card says "Aggiornato" and that then downloads
        #: anyway is a fake no UI test can be written against. ``set_fresh`` is
        #: the knob for the skipped case, and it sets both.
        self._statuses: dict[str, EnvStatus] = {
            name: EnvStatus(
                env=name,
                last_success=datetime(2026, 9, 22, 9, 23) if name == "coll" else None,
                fresh=False,
                n_local_files=39 if name == "coll" else 0,
                local_bytes=41 * 1_048_576 if name == "coll" else 0,
                latest_day=DAYS[0] if name == "coll" else None,
                index_pending=0 if name == "coll" else 0,
                last_remote_daily=39 if name == "coll" else 0,
                last_downloaded=2 if name == "coll" else 0,
            )
            for name in ENVS
        }

    # -- knobs -------------------------------------------------------------

    def set_unreachable(self, env_name: str) -> None:
        """``check_reachable`` says no and a run ends in ``EnvUnreachable``."""
        self._set_outcome(env_name, "unreachable")

    def set_failing(self, env_name: str, n: int = 1) -> None:
        """A run emits ``n`` ``FileFailed`` and ends with status ``errors``."""
        self._set_outcome(env_name, "errors")
        self._n_failures[env_name] = n

    def set_fresh(self, env_name: str) -> None:
        """Already synced after the last compaction: a run without ``force``
        emits ``EnvSkipped(env, "fresh")`` and nothing else, exactly like the
        engine (with ``force`` — what "Sincronizza ora" uses — it downloads)."""
        self._set_outcome(env_name, "fresh")

    def set_ok(self, env_name: str) -> None:
        """Back to the default scripted download."""
        self._set_outcome(env_name, "ok")
        self._n_failures.pop(env_name, None)

    def set_reachable(self, env_name: str) -> None:
        """Alias of ``set_ok`` kept for readability at the call site."""
        self.set_ok(env_name)

    def _set_outcome(self, env_name: str, outcome: str) -> None:
        """Keep the card and the run in step: only a "fresh" env shows the
        "Aggiornato" pill."""
        self._outcomes[env_name] = outcome
        self.set_env_status(env_name, fresh=outcome == "fresh")

    def set_lock_holder(self, text: str | None) -> None:
        self.holder = text

    def set_env_status(self, env_name: str, **kw) -> EnvStatus:
        """Patch one card's status, creating it for an env the fake does not
        know: the wizard can import an ``environments.json`` with any names at
        all, and a knob that raised ``KeyError`` there would make those names
        untestable even though ``env_status`` answers for them."""
        self._statuses[env_name] = dataclasses.replace(self._status(env_name), **kw)
        return self._statuses[env_name]

    @staticmethod
    def _default_status(env_name: str) -> EnvStatus:
        """A never-synced, never-fresh env: what an unknown name looks like."""
        return EnvStatus(
            env=env_name,
            last_success=None,
            fresh=False,
            n_local_files=0,
            local_bytes=0,
            latest_day=None,
            index_pending=0,
        )

    def _status(self, env_name: str) -> EnvStatus:
        status = self._statuses.get(env_name)
        return status if status is not None else self._default_status(env_name)

    # -- contract ----------------------------------------------------------

    def env_status(self, env_name: str) -> EnvStatus:
        return self._status(env_name)

    def check_reachable(self, env: Environment, timeout: float = 5.0) -> bool:
        """Faithful about the case that matters: an environment nobody knows.

        The real service probes ``env.url``, so an environment that exists only
        in a half-filled wizard table — pointing at a host that is not there —
        answers False. This fake used to answer True for any name it had not
        been told about, which is exactly how a first-run wizard that reported
        every environment unreachable got through the whole suite. An unknown
        name is therefore unreachable here too, until a knob says otherwise
        (``set_ok`` / ``set_reachable`` work for any name).

        Intentional, harmless remaining divergence: the outcome is keyed on
        ``env.name`` and ``env.url`` is never even read, so editing a row's URL
        in Impostazioni/the wizard without also calling a knob does not change
        what this answers. Actually probing a URL would mean giving this
        "no network, ever" fake an HTTP client, for a check whose only job is
        letting a UI test script "this row is reachable/not" — not worth it.
        """
        outcome = self._outcomes.get(env.name, "ok" if env.name in ENVS else "unreachable")
        return outcome != "unreachable"

    def run(
        self,
        envs: Sequence[str] | None = None,
        *,
        force: bool = False,
        dry_run: bool = False,
        sink: EventSink,
        cancel: CancelToken,
    ) -> JobReport:
        """Emit the same event sequence the real job does, then a ``JobReport``.

        Mirrors ``core.jobs.run_sync_job`` step by step: a held lock is one
        ``LogMessage`` and nothing else; otherwise the sync events, the summary
        line, and then — unless cancelled or dry run — the index phase, which
        the UI shows in the same progress strip. Like the real one it never
        raises on cancel: the affected env finishes with status ``cancelled``
        and the report carries exit code 3.

        ``envs=None`` targets ``config.enabled_environments()``, exactly like
        ``SyncEngine.run`` — a disabled env is never synced by an unqualified
        run. An explicit name not in ``config.environments`` is
        ``UnknownEnvironment``, raised before anything starts (no event, no
        entry in ``self.runs``), same as ``Config.require_env`` used to build
        ``SyncEngine.run``'s targets.
        """
        cfg = self._config_source()
        if envs is None:
            names = tuple(e.name for e in cfg.environments if e.enabled)
        else:
            names = tuple(envs)
            known = {e.name for e in cfg.environments}
            for name in names:
                if name not in known:
                    raise UnknownEnvironment(name, known)
        self.runs.append({"envs": names, "force": force, "dry_run": dry_run})
        if self.holder is not None:
            sink(LogMessage(logging.INFO, f"sincronizzazione già in corso ({self.holder})"))
            return JobReport(sync=None, indexed_files=0, exit_code=0)
        started = datetime.now()
        sink(SyncStarted(names, dry_run))
        results = tuple(
            self._run_env(name, force=force, dry_run=dry_run, sink=sink, cancel=cancel) for name in names
        )
        report = SyncReport(results, started, datetime.now(), dry_run=dry_run)
        sink(SyncFinished(report))
        sink(LogMessage(logging.INFO, report.summary_line()))
        if not dry_run:
            # The real ``env_status`` is derived from the state file and the
            # mirror listing a successful run just wrote to disk, so a card
            # refreshed after "Sincronizza ora" (``sync_page.refresh_cards``)
            # sees the new numbers. A dry run touches neither, so it must not
            # touch this snapshot either — even though its scripted result
            # also carries status "ok".
            for result in results:
                self._apply_result(result)
        indexed = 0
        if not dry_run and not cancel.is_set():
            indexed = self._index_phase(sink)
        return JobReport(sync=report, indexed_files=indexed, exit_code=report.exit_code)

    def _apply_result(self, result: EnvResult) -> None:
        if result.status != "ok":
            return
        current = self._status(result.env)
        self._statuses[result.env] = dataclasses.replace(
            current,
            last_success=datetime.now(),
            fresh=False,
            n_local_files=current.n_local_files + result.downloaded,
            local_bytes=current.local_bytes + result.bytes,
            latest_day=DAYS[0],
            index_pending=0,
            last_remote_daily=SCRIPT_N_DAILY,
            last_downloaded=result.downloaded,
        )

    def _index_phase(self, sink: EventSink) -> int:
        """The index events the real job emits right after a successful sync."""
        n = SCRIPT_INDEXED_FILES
        sink(IndexStarted(n))
        for i in range(1, n + 1):
            self._pause()
            sink(IndexFileScanned(self._root / "mirror" / SCRIPT_FILE_NAME, 7, i, n))
        sink(IndexFinished(n, 0, 0.05))
        return n

    def lock_holder(self) -> str | None:
        """Read-only, like the real probe: asking never changes the answer."""
        return self.holder

    def sync_log_path(self) -> Path:
        return self._paths.sync_log

    def tail_sync_log(self, n: int) -> list[str]:
        return self.log_lines[-n:] if n > 0 else []

    def is_fresh(self, env_name: str) -> bool:
        return self.env_status(env_name).fresh

    # -- internals ---------------------------------------------------------

    def _run_env(self, name: str, *, force: bool, dry_run: bool, sink: EventSink,
                 cancel: CancelToken) -> EnvResult:
        sink(EnvStarted(name))
        result = self._script(name, force=force, dry_run=dry_run, sink=sink, cancel=cancel)
        sink(EnvFinished(name, result))
        return result

    def _script(self, name: str, *, force: bool, dry_run: bool, sink: EventSink,
                cancel: CancelToken) -> EnvResult:
        """One environment, event for event as ``SyncEngine.sync_env`` emits them."""
        outcome = self._outcomes.get(name, "ok")
        if cancel.is_set():
            return EnvResult(name, "cancelled", error="annullato prima dell'avvio")
        if outcome == "fresh" and not force:
            sink(EnvSkipped(name, "fresh"))
            return EnvResult(name, "fresh")
        if outcome == "unreachable":
            error = "endpoint non raggiungibile"
            sink(EnvUnreachable(name, error))
            return EnvResult(name, "unreachable", error=error)
        size = SCRIPT_FILE_SIZE
        sink(RemoteIndexRead(name, n_daily=SCRIPT_N_DAILY, n_empty=SCRIPT_EMPTY, n_loose=2,
                             bytes_to_download=size))
        # The engine tallies the files already present and the empty ones plan
        # by plan, before its `if dry_run` branch: a dry run walks every plan,
        # so it reports the numbers RemoteIndexRead has just announced. A
        # cancel is an early exit from that same loop, so it reports only what
        # it walked — here nothing, since the scripted index is newest-first
        # with the download ahead of the present/empty entries.
        if dry_run:
            # The engine skips the transfer entirely under dry_run: no
            # FileStarted, no FileProgress, so no progress bar in the UI. It
            # still counts what it would have downloaded, and what it skipped.
            return EnvResult(name, "ok", downloaded=1, present=SCRIPT_PRESENT, empty=SCRIPT_EMPTY, bytes=size)
        if outcome == "errors":
            return self._fail_files(name, size, sink, cancel)
        sink(FileStarted(name, SCRIPT_FILE_NAME, size))
        for step in range(1, SCRIPT_PROGRESS_STEPS + 1):
            self._pause()
            if cancel.is_set():
                return EnvResult(name, "cancelled", error=f"annullato durante {SCRIPT_FILE_NAME}")
            sink(FileProgress(name, SCRIPT_FILE_NAME, size * step // SCRIPT_PROGRESS_STEPS, size))
        sink(FileDone(name, SCRIPT_FILE_NAME, size, self._root / "mirror" / name / SCRIPT_FILE_NAME))
        return EnvResult(name, "ok", downloaded=1, present=SCRIPT_PRESENT, empty=SCRIPT_EMPTY, bytes=size)

    def _fail_files(self, name: str, size: int, sink: EventSink, cancel: CancelToken) -> EnvResult:
        """``FileStarted`` then ``FileFailed`` per file, like a truncated transfer.

        The token is checked before every file and again while one is in
        flight, exactly where the engine checks it, so a run cancelled while
        files are failing ends ``cancelled`` (exit 3) and not ``errors``
        (exit 1). Only what the loop actually walked travels with the cancelled
        result: the failures so far, and no present/empty (those plans come
        after the downloads in the scripted index, so the cancel never reaches
        them).
        """
        n = self._n_failures.get(name, 1)
        for i in range(n):
            file_name = f"2026091{i}.txt"
            if cancel.is_set():
                return EnvResult(name, "cancelled", failed=i, error=f"annullato prima di {file_name}")
            sink(FileStarted(name, file_name, size))
            self._pause()
            if cancel.is_set():
                return EnvResult(name, "cancelled", failed=i, error=f"annullato durante {file_name}")
            sink(FileFailed(name, file_name, "troncato: 512 di 4194304 byte"))
        return EnvResult(name, "errors", present=SCRIPT_PRESENT, empty=SCRIPT_EMPTY, failed=n)

    def _pause(self) -> None:
        if self.step_delay:
            time.sleep(self.step_delay)


# -------------------------------------------------------------- scheduler ---

class FakeSchedulerApi:
    """Task status the tests set directly; register/unregister flip it."""

    def __init__(self, exe: Path | None = None) -> None:
        self.task = NOT_REGISTERED
        self.legacy = False
        self.exe = exe
        self.run_now_calls = 0
        self.register_calls = 0
        self.unregister_calls = 0
        self.unstable_reason: str | None = None

    # -- knobs -------------------------------------------------------------

    def set_status(self, **kw) -> TaskStatus:
        self.task = dataclasses.replace(self.task, **kw)
        return self.task

    def set_legacy(self, flag: bool) -> None:
        self.legacy = flag

    # -- contract ----------------------------------------------------------

    def status(self) -> TaskStatus:
        return self.task

    def register(self) -> None:
        """``SchedulerError`` with no exe — ``facade.SchedulerService.register``
        refuses before calling ``schtasks`` at all: "running from source" has
        no executable to point the task at."""
        if self.exe is None:
            raise SchedulerError(
                "la sincronizzazione automatica richiede l'eseguibile installato: "
                "avviato dai sorgenti non c'è nulla da pianificare"
            )
        self.register_calls += 1
        self.task = TaskStatus(
            registered=True,
            command=self.exe,
            args="--sync",
            exe_matches=self.exe is not None,
            state="Pronto",
            next_run=None,
            last_run=None,
            last_result=None,
        )

    def unregister(self) -> None:
        self.unregister_calls += 1
        self.task = NOT_REGISTERED

    def run_now(self) -> None:
        self.run_now_calls += 1

    def detect_legacy_task(self) -> bool:
        return self.legacy

    def remove_legacy_task(self) -> None:
        self.legacy = False

    def exe_path(self) -> Path | None:
        return self.exe

    def unstable_location_reason(self) -> str | None:
        return self.unstable_reason


# -------------------------------------------------------------------- index ---

class FakeIndexApi:
    """12 synthetic hits, filtered the way the SQL query filters them."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self.hits: list[SearchHit] = [_hit(i + 1, spec, root / "mirror") for i, spec in enumerate(HIT_SPECS)]
        self.bodies: dict[int, bytes] = {h.entry_id: _body(spec) for h, spec in zip(self.hits, HIT_SPECS)}
        self.missing: set[int] = set()
        self.updates: list[dict] = []
        self.pending: list[LocalDailyFile] = []
        self.local_file_counts: dict[Path, int] = {}
        #: env -> local mirror days, for coverage_days. Defaults to the hit
        #: days of that env (the synthetic hits stand in for what is on disk
        #: unless a test overrides it with ``set_local_days``).
        self._local_days: dict[str, dict[date, int]] | None = None
        #: env -> (listed_nonempty, seen_nonempty), the sync state's listing
        #: memory; unset -> nothing listed yet (like a fresh state file).
        self._server_days: dict[str, tuple[frozenset[date], frozenset[date]]] = {}

    # -- knobs -------------------------------------------------------------

    def set_local_days(self, env: str, days: set[date], empty: Iterable[date] = ()) -> None:
        """Override what ``coverage_days(env, ...)`` sees as the local mirror
        listing for ``env``: ``days`` are non-empty files, ``empty`` 0-byte
        ones — used to line the fake up with a real mirror on disk (e.g. the
        ``mirror`` fixture) for a fake-vs-real comparison."""
        if self._local_days is None:
            self._local_days = {}
        sizes = {d: 0 for d in empty}
        sizes.update({d: 1 for d in days})
        self._local_days[env] = sizes

    def set_server_days(self, env: str, listed: Iterable[date] = (), seen: Iterable[date] = ()) -> None:
        """The sync state's listing memory for ``env``: the non-empty days of
        the last listing (``listed``) and every non-empty day ever listed
        (``seen``; ``listed`` is added to it, as the real state does)."""
        listed = frozenset(listed)
        self._server_days[env] = (listed, frozenset(seen) | listed)

    def set_missing(self, hit: SearchHit) -> None:
        """``read_body`` of ``hit`` raises ``IndexStale``.

        There is no "stale" knob: the real facade rescans and retries, so a
        stale index is invisible to the UI and a fake that surfaced it would
        make the UI handle a case that cannot happen.
        """
        self.missing.add(hit.entry_id)

    def set_pending(self, n: int) -> None:
        """Pretend ``n`` local files are waiting to be indexed."""
        self.pending = [
            LocalDailyFile(ENVS[0], DAYS[i % len(DAYS)], self._root / "mirror" / f"pending{i}.txt", 1024, i)
            for i in range(n)
        ]

    # -- contract ----------------------------------------------------------

    def plan(self, envs: Sequence[str]) -> IndexPlan:
        """Only the pending files of ``envs`` — the real ``IndexBuilder.plan``
        scopes its query to the requested environments the same way."""
        names = set(envs)
        return IndexPlan(to_scan=[f for f in self.pending if f.env in names], to_remove=[])

    def update(
        self,
        envs: Sequence[str] | None = None,
        *,
        full_rebuild: bool = False,
        sink: EventSink,
        cancel: CancelToken,
    ) -> JobReport:
        self.updates.append({"envs": None if envs is None else list(envs), "full_rebuild": full_rebuild})
        paths = ([f.path for f in self.pending] if not full_rebuild
                 else sorted({h.file_path for h in self.hits}))
        n = len(paths)
        sink(IndexStarted(n))
        for i, path in enumerate(paths, start=1):
            if cancel.is_set():
                return JobReport(sync=None, indexed_files=i - 1, exit_code=3)
            sink(IndexFileScanned(Path(path), 3, i, n))
        sink(IndexFinished(n, 0, 0.01))
        self.pending = []
        return JobReport(sync=None, indexed_files=n, exit_code=0)

    def coverage(self, env: str) -> Coverage | None:
        days = sorted({h.day for h in self.hits if h.env == env})
        if not days:
            return None
        return Coverage(days[0], days[-1], len(days), sum(1 for h in self.hits if h.env == env))

    def coverage_days(self, env: str, days: int = 30, today: date | None = None) -> CoverageDays:
        if self._local_days is not None and env in self._local_days:
            sizes = self._local_days[env]
        else:
            sizes = {h.day: 1 for h in self.hits if h.env == env}
        listed, seen = self._server_days.get(env, (frozenset(), frozenset()))
        return core_classify_days(sizes, listed, seen, days, today if today is not None else date.today())

    def set_local_file_count(self, root: Path, n: int) -> None:
        """What ``count_local_files(root)`` answers for that folder (wizard)."""
        self.local_file_counts[Path(root)] = n

    def count_local_files(self, root: Path | None = None) -> int:
        """The configured mirror by default; a browsed folder answers from the
        map set with ``set_local_file_count`` (unknown folder -> 0, like an
        empty directory)."""
        if root is None:
            return len({(h.env, h.day) for h in self.hits})
        return self.local_file_counts.get(Path(root), 0)

    def list_template_keys(self, env: str, prefix: str = "") -> list[str]:
        """Same three-way order as the real SQL: ``ORDER BY MAX(day) DESC,
        COUNT(*) DESC, template_key`` — most recently seen, then most
        frequent, then alphabetical. Sorting on day alone (the previous
        version) left same-day ties in whatever order ``self.hits`` happened
        to hold them, which is not what a real index would ever produce."""
        prefix = prefix.strip().lower()
        max_day: dict[str, date] = {}
        count: dict[str, int] = {}
        for h in self.hits:
            if h.env != env or not h.template_key.lower().startswith(prefix):
                continue
            if h.template_key not in max_day or h.day > max_day[h.template_key]:
                max_day[h.template_key] = h.day
            count[h.template_key] = count.get(h.template_key, 0) + 1
        return sorted(max_day, key=lambda k: (-max_day[k].toordinal(), -count[k], k))

    def search(self, query: SearchQuery) -> list[SearchHit]:
        """Same contract as the real query: FDI prefix or key required (blank
        counts as absent), most recent first, day window inclusive, ``limit``
        applied last."""
        fdi = (query.fdi_prefix or "").strip().lower()
        key = (query.template_key or "").strip()
        if not fdi and not key:
            raise ValueError("search needs an FDI prefix or a template key")
        found = [h for h in self.hits if h.env == query.env]
        if fdi:
            found = [h for h in found if (h.fdi or "").startswith(fdi)]
        if key:
            found = [h for h in found if _key_matches(h.template_key, key, query.key_mode)]
        if query.day_from is not None:
            found = [h for h in found if h.day >= query.day_from]
        if query.day_to is not None:
            found = [h for h in found if h.day <= query.day_to]
        found.sort(key=lambda h: (h.day.toordinal(), h.request_date is not None, h.request_date or "", h.seq),
                   reverse=True)
        return found[: query.limit]

    def read_body(self, hit: SearchHit) -> bytes:
        if hit.entry_id in self.missing:
            raise IndexStale(hit.env, hit.day)
        return self.bodies[hit.entry_id]

    def db_path(self) -> Path:
        return self._root / "mirror" / ".qtrequestory" / "index.sqlite"


def _key_matches(value: str, key: str, mode: str) -> bool:
    value, key = value.lower(), key.lower()
    if mode == "exact":
        return value == key
    if mode == "prefix":
        return value.startswith(key)
    if mode == "contains":
        return key in value
    raise ValueError(f"unknown key_mode {mode!r}")


# ------------------------------------------------------------------ extract ---

class FakeExtractApi:
    """Real formatting (the output contract matters), real files under a tmp dir,
    but launching an editor or Explorer is only recorded."""

    def __init__(self, out_dir: Path, config_source: Callable[[], Config] | None = None) -> None:
        self._out_dir = out_dir
        #: Real ``ExtractService.write_temp_file`` reads ``output_retention_hours``
        #: from the current configuration; without a source, the same default
        #: (24h) ``core.extract.write_temp_file`` itself uses applies.
        self._config_source = config_source
        self.opened: list[list[Path]] = []
        self.folders: list[Path] = []
        self.editor: Path | None = None

    def pretty_json(self, raw: bytes) -> str:
        return extract_mod.pretty_json(raw)

    def output_name(self, hit: SearchHit) -> str:
        return output_name_for(hit)

    def write_temp_file(self, hit: SearchHit, text: str) -> Path:
        kw = {}
        if self._config_source is not None:
            kw["retention_hours"] = self._config_source().output_retention_hours
            kw["protected"] = self._config_source().mirror_root
        return extract_mod.write_temp_file(
            self._out_dir, output_name_for(hit), text, alt_name=output_name_with_id(hit), **kw
        )

    def save_as(self, path: Path, text: str) -> None:
        extract_mod.save_as(Path(path), text)

    def open_in_editor(self, paths: Sequence[Path]) -> str:
        self.opened.append(list(paths))
        return "editor" if self.editor is not None else "default"

    def open_folder(self, path: Path) -> None:
        self.folders.append(Path(path))

    def output_dir(self) -> Path:
        return self._out_dir


# ------------------------------------------------------------------ archive ---

class FakeArchiveApi:
    """The real discovery and copy on the fake's tmp tree (both are pure file
    work, so faking them would only let the fake drift); the Recycle Bin is
    simulated: a file under the fake root is removed and recorded, nothing
    else is ever deleted."""

    def __init__(self, root: Path, config_source: Callable[[], Config]) -> None:
        self._root = Path(root)
        self._config_source = config_source
        self.scripted: ArchiveReport | None = None
        self.busy = False
        self.recycled: list[Path] = []
        self.imports: list[ArchiveReport] = []
        #: The ``path`` of every ``report()`` call (None = the mirror).
        self.reports: list[Path | None] = []

    def set_report(self, report: ArchiveReport | None) -> None:
        """Every ``report()`` returns this until ``None`` clears it."""
        self.scripted = report

    def set_busy(self, flag: bool) -> None:
        """``import_`` raises ``ArchiveBusy`` (a sync holds the lock)."""
        self.busy = flag

    def _cfg(self) -> Config:
        cfg = self._config_source()
        problems = core_mirror_root_errors(cfg)
        if problems:
            raise ValueError(problems[0])
        return cfg

    def report(self, path: Path | None = None, *,
               canonical_root: Path | None = None) -> ArchiveReport:
        cfg = self._cfg()
        self.reports.append(path)
        if self.scripted is not None:
            return self.scripted
        root = Path(path) if path is not None else cfg.mirror_root
        canonical = Path(canonical_root) if canonical_root is not None else cfg.mirror_root
        return archive_mod.discover(root, [e.name for e in cfg.environments], cfg.folder_envs,
                                    canonical_root=canonical)

    def import_(self, report: ArchiveReport, *, cancel=None, progress=None) -> importer_mod.ImportResult:
        cfg = self._cfg()
        if self.busy:
            raise ArchiveBusy("sincronizzazione in corso: importa al termine")
        self.imports.append(report)
        return importer_mod.run_import(report, cfg.mirror_root, cancel=cancel, progress=progress)

    def recycle(self, originals: Sequence[importer_mod.VerifiedOriginal]) -> list[tuple[Path, str]]:
        """The real re-checks (``importer.check_original``), minus the shell:
        a file under the fake root is unlinked and recorded."""
        cfg = self._cfg()
        failures: list[tuple[Path, str]] = []
        for rec in originals:
            if not isinstance(rec, importer_mod.VerifiedOriginal):
                failures.append((Path(rec), "non verificato da un'importazione: non viene cancellato"))
                continue
            why = importer_mod.check_original(rec, cfg.mirror_root)
            if why is None and not is_within(rec.path, self._root):
                why = "fuori dalla cartella del fake"
            if why is not None:
                failures.append((rec.path, why))
            else:
                rec.path.unlink()
                self.recycled.append(rec.path)
        return failures


# ------------------------------------------------------------------- bundle ---

def build_fake_core(root: Path) -> CoreServices:
    """A complete in-memory ``CoreServices`` rooted at ``root`` (a tmp dir)."""
    root = Path(root)
    paths = AppPaths(root / "apphome").ensure()
    config = FakeConfigApi(root)
    return CoreServices(
        config=config,
        sync=FakeSyncApi(root, paths, lambda: config.config),
        # A non-None exe: the common case for every UI test is "running from
        # an installed exe", where ``register()`` succeeds — the "no exe at
        # all" case (``SchedulerError``, see ``register``) is exercised with
        # an explicit ``FakeSchedulerApi(exe=None)`` where it matters.
        scheduler=FakeSchedulerApi(exe=root / "qtRequestory.exe"),
        index=FakeIndexApi(root),
        extract=FakeExtractApi(root / "out", lambda: config.config),
        archive=FakeArchiveApi(root, lambda: config.config),
        paths=paths,
    )
