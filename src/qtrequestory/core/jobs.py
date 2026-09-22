"""The two headless jobs the CLI, the scheduled task and the UI all run.

``run_sync_job`` is "mirror then index" under the process lock: the scheduled
task and the UI may target the same mirror, and only one of them may write
it at a time. A busy lock is not an error — the other side is doing the work —
so the job says so once and exits 0. The index phase is best effort: a broken
index never hides a successful download (the exit code stays the sync's), it
is only reported.

``run_index_job`` re-indexes the local mirror alone (no network, no lock:
SQLite serialises the writers itself, one transaction per file).
"""
from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass

from qtrequestory.core.config import Config
from qtrequestory.core.events import Cancelled, CancelToken, EventSink, LogMessage
from qtrequestory.core.http import HttpClient, UrllibHttpClient
from qtrequestory.core.index.builder import IndexBuilder
from qtrequestory.core.index.db import open_index
from qtrequestory.core.lock import ProcessLock
from qtrequestory.core.state import SyncState
from qtrequestory.core.sync import SyncEngine, SyncReport

EXIT_OK = 0
EXIT_ERRORS = 1
EXIT_CANCELLED = 3


@dataclass(frozen=True)
class JobReport:
    sync: SyncReport | None
    indexed_files: int
    exit_code: int


def _index_envs(config: Config, envs: Iterable[str] | None) -> list[str]:
    """Every configured environment, enabled or not: the index describes local
    files, and a disabled env may still hold history worth searching."""
    return [e.name for e in config.environments] if envs is None else list(envs)


def _update_index(config: Config, envs: list[str], *, full_rebuild: bool, sink: EventSink, cancel: CancelToken) -> int:
    """Run ``IndexBuilder.update``; returns the number of files scanned.

    ``Cancelled`` propagates (the caller decides the exit code); any other
    failure is reported through the sink and counted as 0 files.
    """
    try:
        conn = open_index(config.index_path)
    except (sqlite3.Error, OSError) as e:
        sink(LogMessage(logging.ERROR, f"indice: impossibile aprire {config.index_path}: {e}"))
        raise
    try:
        builder = IndexBuilder(conn, config.mirror_root, sink, cancel, parse_json=config.index.parse_json)
        return builder.update(envs, full_rebuild=full_rebuild).scanned
    except (sqlite3.Error, OSError) as e:
        sink(LogMessage(logging.ERROR, f"indice: aggiornamento fallito: {e}"))
        raise
    finally:
        conn.close()


def run_sync_job(
    config: Config,
    *,
    envs: Iterable[str] | None = None,
    force: bool = False,
    dry_run: bool = False,
    sink: EventSink,
    cancel: CancelToken,
    http: HttpClient | None = None,
) -> JobReport:
    """Lock -> ``SyncEngine.run`` -> ``IndexBuilder.update`` -> report.

    ``exit_code`` is the sync's (0 ok, 1 file errors, 2 nothing reachable,
    3 cancelled); a cancel that lands during the index phase is 3 as well.
    ``envs=None`` syncs every enabled environment.
    """
    lock = ProcessLock(config.lock_path)
    if not lock.acquire():
        holder = lock.holder_info() or "processo sconosciuto"
        sink(LogMessage(logging.INFO, f"sincronizzazione già in corso ({holder})"))
        return JobReport(sync=None, indexed_files=0, exit_code=EXIT_OK)
    try:
        env_names = list(envs) if envs is not None else None
        state = SyncState(config.state_path).load()
        engine = SyncEngine(config, http or UrllibHttpClient(), state, sink, cancel)
        report = engine.run(env_names, force=force, dry_run=dry_run)
        sink(LogMessage(logging.INFO, report.summary_line()))
        exit_code = report.exit_code
        indexed = 0
        if not dry_run and not cancel.is_set():
            try:
                indexed = _update_index(config, _index_envs(config, env_names), full_rebuild=False, sink=sink, cancel=cancel)
            except Cancelled:
                exit_code = EXIT_CANCELLED
            except (sqlite3.Error, OSError):
                pass  # already reported; the sync outcome is what counts
        return JobReport(sync=report, indexed_files=indexed, exit_code=exit_code)
    finally:
        lock.release()


def run_index_job(
    config: Config,
    *,
    envs: Iterable[str] | None = None,
    full_rebuild: bool = False,
    sink: EventSink,
    cancel: CancelToken,
) -> JobReport:
    """Index the local mirror: 0 ok, 1 index failure, 3 cancelled."""
    try:
        indexed = _update_index(config, _index_envs(config, envs), full_rebuild=full_rebuild, sink=sink, cancel=cancel)
    except Cancelled:
        return JobReport(sync=None, indexed_files=0, exit_code=EXIT_CANCELLED)
    except (sqlite3.Error, OSError):
        return JobReport(sync=None, indexed_files=0, exit_code=EXIT_ERRORS)
    return JobReport(sync=None, indexed_files=indexed, exit_code=EXIT_OK)
