"""``--archivio`` and ``--import``: the archive importer from the command line.

* ``--archivio [PERCORSO]`` lists what ``core/archive.py`` finds under the
  folder (default: the mirror itself) and why; read-only. Exit 1 when a file
  still needs an environment or two copies of a day conflict.
* ``--import PERCORSO [--env-for CARTELLA=AMBIENTE ...] [--delete-originals]``
  copies and verifies (``core/importer.py``), then indexes the environments
  that received files. ``--env-for`` assigns a folder for this run only
  (``ignora`` skips it); the originals go to the Recycle Bin only with
  ``--delete-originals``, and only the verified ones outside the mirror.

Kept apart from ``cli.py`` for size; like it, it never imports Qt.
"""
from __future__ import annotations

import dataclasses
from collections.abc import Callable, Sequence
from pathlib import Path

from qtrequestory.core import facade
from qtrequestory.core.archive import CONFLICT, DUPLICATE, IGNORED, IMPORTABLE, NEEDS_ENV, ArchiveReport
from qtrequestory.core.config import IGNORE_FOLDER, Config
from qtrequestory.core.events import CancelToken, EventSink, format_size
from qtrequestory.core.fsutil import real_is_within
from qtrequestory.core.jobs import EXIT_CANCELLED, EXIT_ERRORS, JobReport, run_index_job

EXIT_CONFIG_ERROR = 2
IGNORE_WORDS = frozenset({"ignora", IGNORE_FOLDER})

LABELS = {
    IMPORTABLE: "da importare",
    DUPLICATE: "già presenti",
    NEEDS_ENV: "da assegnare",
    CONFLICT: "conflitti",
    IGNORED: "ignorati",
}

RunJob = Callable[[Callable[[EventSink, CancelToken], JobReport]], int]


def parse_env_for(raw: str) -> tuple[str, str] | None:
    """``"cartella=ambiente"`` -> the pair; ``None`` when malformed."""
    folder, sep, env = raw.partition("=")
    folder, env = folder.strip(), env.strip()
    if not sep or not folder or not env:
        return None
    return folder, env


def print_report(report: ArchiveReport) -> None:
    print(f"cartella analizzata: {report.root}")
    for f in report.items:
        where = " ".join(x for x in (f.env or "?", f.day.isoformat() if f.day else "?") if x)
        print(f"  [{LABELS[f.status]}] {f.rel_path}  ({where}, {format_size(f.size)}) — {f.reason}")
    counts = report.counts()
    print(f"trovati: {len(report.items)} · " + " · ".join(f"{LABELS[s]}: {counts[s]}" for s in LABELS))
    if report.needs_env_dirs():
        print("cartelle senza ambiente (usa --env-for CARTELLA=AMBIENTE con --import): "
              + ", ".join(d or "." for d in report.needs_env_dirs()))


def folder_error(path: str) -> str | None:
    """Why ``path`` is not a folder to scan, or ``None``."""
    if not path.strip():
        return "cartella non indicata"
    if not Path(path).is_dir():
        return f"la cartella '{path}' non esiste o non è una cartella"
    return None


def run_archivio(config: Config, path: str) -> int:
    """``path == ""``: the mirror itself (``--archivio`` with no value)."""
    if path:
        problem = folder_error(path)
        if problem:
            print(f"Errore: {problem}")
            return EXIT_CONFIG_ERROR
    report = facade.ArchiveService(lambda: config).report(Path(path).resolve() if path else None)
    print_report(report)
    counts = report.counts()
    return EXIT_ERRORS if counts[NEEDS_ENV] or counts[CONFLICT] else 0


def _folder_envs(config: Config, pairs: Sequence[tuple[str, str]]) -> dict[str, str] | str:
    """``config.folder_envs`` plus this run's assignments, or an error message."""
    by_lower = {e.name.lower(): e.name for e in config.environments}
    merged = dict(config.folder_envs)
    for folder, env in pairs:
        if env.lower() in IGNORE_WORDS:
            merged[folder] = IGNORE_FOLDER
        elif env.lower() in by_lower:
            merged[folder] = by_lower[env.lower()]
        else:
            known = ", ".join(sorted(by_lower.values())) or "nessuno"
            return f"--env-for {folder}={env}: ambiente sconosciuto (configurati: {known}; oppure 'ignora')"
    return merged


def run_import(config: Config, path: str, env_for: Sequence[tuple[str, str]], *,
               delete_originals: bool, run_job: RunJob, cancel: CancelToken) -> int:
    """``cancel`` is the Ctrl+C token (``cli._sigint_cancels``)."""
    problem = folder_error(path)
    if problem:
        print(f"Errore: {problem}")
        return EXIT_CONFIG_ERROR
    folder_envs = _folder_envs(config, env_for)
    if isinstance(folder_envs, str):
        print(f"Errore: {folder_envs}")
        return EXIT_CONFIG_ERROR
    run_config = dataclasses.replace(config, folder_envs=folder_envs)  # this run only, never saved
    service = facade.ArchiveService(lambda: run_config)
    report = service.report(Path(path).resolve())
    print_report(report)
    try:
        result = service.import_(report, cancel=cancel)
    except facade.ArchiveBusy as e:
        print(f"Errore: {e}")
        return EXIT_ERRORS
    print(f"copiati: {result.copied} · già presenti: {result.skipped} · "
          f"conflitti: {result.conflicts} · errori: {len(result.errors)}")
    for p, why in result.errors:
        print(f"  errore: {p}: {why}")

    code = 0
    if result.envs:
        code = run_job(lambda sink, token: run_index_job(
            run_config, envs=sorted(result.envs), full_rebuild=False, sink=sink, cancel=token))

    if result.cancelled:
        print("importazione annullata: nessun originale è stato cancellato")
        return EXIT_CANCELLED
    originals = [v for v in result.verified if not real_is_within(v.path, config.mirror_root)]
    if delete_originals and originals:
        failures = service.recycle(originals)
        print(f"Cestino: {len(originals) - len(failures)} file")
        for p, why in failures:
            print(f"  non cancellato: {p}: {why}")
        if failures:
            code = code or EXIT_ERRORS
    elif originals:
        print(f"{len(originals)} originali verificati: aggiungi --delete-originals "
              "per spostarli nel Cestino")

    if result.errors or result.conflicts or report.counts()[NEEDS_ENV]:
        return code or EXIT_ERRORS
    return code
