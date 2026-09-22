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

* ``FakeSyncApi.set_unreachable(env)`` / ``set_reachable(env)``
* ``FakeSyncApi.set_lock_holder(text)``, ``FakeSyncApi.set_env_status(env, ...)``
* ``FakeSyncApi.step_delay`` — seconds between scripted events (default tiny)
* ``FakeSchedulerApi.set_status(...)`` / ``set_legacy(flag)``
* ``FakeIndexApi.set_missing(hit)`` — ``read_body`` of that hit raises ``IndexStale``
* ``FakeIndexApi.set_pending(n)`` — n files waiting to be indexed
"""
from __future__ import annotations

import dataclasses
import logging
import time
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path

from qtrequestory.core import extract as extract_mod
from qtrequestory.core.config import Config, Environment, default_config, validate as core_validate
from qtrequestory.core.events import (
    CancelToken,
    EnvFinished,
    EnvStarted,
    EnvUnreachable,
    EventSink,
    FileDone,
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
from qtrequestory.core.daily import LocalDailyFile
from qtrequestory.core.facade import EnvStatus
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
from qtrequestory.core.scheduler import NOT_REGISTERED, TaskStatus
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

    def is_first_run(self) -> bool:
        return self.first_run

    def load(self) -> Config:
        return self.config

    def save(self, cfg: Config) -> None:
        self.config = cfg
        self.saved.append(cfg)

    def validate(self, cfg: Config) -> list[str]:
        return core_validate(cfg)

    def detect_editor(self) -> Path | None:
        return self.editor

    def import_environments_file(self, path: Path) -> list[Environment]:
        return list(self.sidecar_environments)

    def find_sidecar_environments(self) -> Path | None:
        return self.sidecar

    def config_path(self) -> Path:
        return self._root / "config.json"


# --------------------------------------------------------------------- sync ---

class FakeSyncApi:
    """Scripted sync: a fixed event sequence per env, honouring the cancel token."""

    def __init__(self, root: Path, paths: AppPaths) -> None:
        self._root = root
        self._paths = paths
        self.step_delay = DEFAULT_STEP_DELAY_S
        self.unreachable: set[str] = set()
        self.holder: str | None = None
        self.runs: list[dict] = []
        self.log_lines = [f"[2026-09-22 09:0{i}:00] coll: scaricato 2026091{i}.txt (12,5 MB)" for i in range(4)]
        self._statuses: dict[str, EnvStatus] = {
            name: EnvStatus(
                env=name,
                last_success=datetime(2026, 9, 22, 9, 23) if name == "coll" else None,
                fresh=name == "coll",
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
        self.unreachable.add(env_name)

    def set_reachable(self, env_name: str) -> None:
        self.unreachable.discard(env_name)

    def set_lock_holder(self, text: str | None) -> None:
        self.holder = text

    def set_env_status(self, env_name: str, **kw) -> EnvStatus:
        self._statuses[env_name] = dataclasses.replace(self._statuses[env_name], **kw)
        return self._statuses[env_name]

    # -- contract ----------------------------------------------------------

    def env_status(self, env_name: str) -> EnvStatus:
        return self._statuses.get(
            env_name,
            EnvStatus(env=env_name, last_success=None, fresh=False, n_local_files=0,
                      local_bytes=0, latest_day=None, index_pending=0),
        )

    def check_reachable(self, env_name: str, timeout: float = 5.0) -> bool:
        return env_name not in self.unreachable

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
        """
        names = tuple(envs) if envs is not None else tuple(ENVS)
        self.runs.append({"envs": names, "force": force, "dry_run": dry_run})
        if self.holder is not None:
            sink(LogMessage(logging.INFO, f"sincronizzazione già in corso ({self.holder})"))
            return JobReport(sync=None, indexed_files=0, exit_code=0)
        started = datetime.now()
        sink(SyncStarted(names, dry_run))
        results = tuple(self._run_env(name, dry_run=dry_run, sink=sink, cancel=cancel) for name in names)
        report = SyncReport(results, started, datetime.now())
        sink(SyncFinished(report))
        sink(LogMessage(logging.INFO, report.summary_line()))
        indexed = 0
        if not dry_run and not cancel.is_set():
            indexed = self._index_phase(sink)
        return JobReport(sync=report, indexed_files=indexed, exit_code=report.exit_code)

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
        return self.holder

    def sync_log_path(self) -> Path:
        return self._paths.sync_log

    def tail_sync_log(self, n: int) -> list[str]:
        return self.log_lines[-n:] if n > 0 else []

    def is_fresh(self, env_name: str) -> bool:
        return self.env_status(env_name).fresh

    # -- internals ---------------------------------------------------------

    def _run_env(self, name: str, *, dry_run: bool, sink: EventSink, cancel: CancelToken) -> EnvResult:
        sink(EnvStarted(name))
        result = self._script(name, dry_run=dry_run, sink=sink, cancel=cancel)
        sink(EnvFinished(name, result))
        return result

    def _script(self, name: str, *, dry_run: bool, sink: EventSink, cancel: CancelToken) -> EnvResult:
        if cancel.is_set():
            return EnvResult(name, "cancelled", error="annullato prima dell'avvio")
        if name in self.unreachable:
            error = "endpoint non raggiungibile"
            sink(EnvUnreachable(name, error))
            return EnvResult(name, "unreachable", error=error)
        size = SCRIPT_FILE_SIZE
        sink(RemoteIndexRead(name, n_daily=3, n_empty=1, n_loose=2, bytes_to_download=size))
        sink(FileStarted(name, SCRIPT_FILE_NAME, size))
        for step in range(1, SCRIPT_PROGRESS_STEPS + 1):
            self._pause()
            if cancel.is_set():
                return EnvResult(name, "cancelled", error=f"annullato durante {SCRIPT_FILE_NAME}")
            sink(FileProgress(name, SCRIPT_FILE_NAME, size * step // SCRIPT_PROGRESS_STEPS, size))
        if dry_run:
            return EnvResult(name, "ok", downloaded=1, bytes=size)
        sink(FileDone(name, SCRIPT_FILE_NAME, size, self._root / "mirror" / name / SCRIPT_FILE_NAME))
        return EnvResult(name, "ok", downloaded=1, present=2, empty=1, bytes=size)

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

    # -- knobs -------------------------------------------------------------

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
        return IndexPlan(to_scan=list(self.pending), to_remove=[])

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

    def count_local_files(self, root: Path | None = None) -> int:
        """``root`` is ignored: the fake mirror is the same wherever it is asked about."""
        return len({(h.env, h.day) for h in self.hits})

    def list_template_keys(self, env: str, prefix: str = "") -> list[str]:
        keys = [h.template_key for h in sorted(self.hits, key=lambda h: h.day, reverse=True) if h.env == env]
        out: list[str] = []
        for key in keys:
            if key not in out and key.lower().startswith(prefix.strip().lower()):
                out.append(key)
        return out

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

    def __init__(self, out_dir: Path) -> None:
        self._out_dir = out_dir
        self.opened: list[list[Path]] = []
        self.folders: list[Path] = []
        self.editor: Path | None = None

    def pretty_json(self, raw: bytes) -> str:
        return extract_mod.pretty_json(raw)

    def output_name(self, hit: SearchHit) -> str:
        return output_name_for(hit)

    def write_temp_file(self, hit: SearchHit, text: str) -> Path:
        return extract_mod.write_temp_file(
            self._out_dir, output_name_for(hit), text, alt_name=output_name_with_id(hit)
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


# ------------------------------------------------------------------- bundle ---

def build_fake_core(root: Path) -> CoreServices:
    """A complete in-memory ``CoreServices`` rooted at ``root`` (a tmp dir)."""
    root = Path(root)
    paths = AppPaths(root / "apphome").ensure()
    return CoreServices(
        config=FakeConfigApi(root),
        sync=FakeSyncApi(root, paths),
        scheduler=FakeSchedulerApi(),
        index=FakeIndexApi(root),
        extract=FakeExtractApi(root / "out"),
        paths=paths,
    )
