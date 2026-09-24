"""Copy the logs an :class:`~qtrequestory.core.archive.ArchiveReport` found into
the canonical tree, verify every copy, and — only when the user says so — send
the verified originals to the Windows Recycle Bin.

The archive is precious, so the rules are narrow:

* A copy goes to ``<dest>.part``, is flushed and fsynced, read back and
  checked against the source (size + sha256), and only then renamed onto
  ``dest`` with ``fsutil.replace_with_retry``.
* An existing canonical file is replaced ONLY when it is a strict prefix of
  the source — re-checked at copy time, not trusted from the scan, and once
  more right before the rename. Anything else is left exactly as it is.
* ``verified`` lists the sources whose whole content is, right now, in the
  archive: every copy that passed the check, plus the ``duplicate_same``
  files re-checked against the canonical file at import time (a copy that
  depended on a twin whose import failed is therefore NOT verified).
* :func:`send_to_recycle_bin` refuses every path inside the canonical tree,
  folders, missing files and drives without a Recycle Bin (network,
  removable), where ``FOF_ALLOWUNDO`` would silently delete for good.

The caller holds the sync lock while importing (see ``facade.ArchiveService``
and ``cli``): the sync writes the same ``.part`` names.
"""
from __future__ import annotations

import ctypes
import hashlib
import logging
import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from qtrequestory.core.archive import CONFLICT, DUPLICATE, IMPORTABLE, ArchiveReport, FoundLog, compare_files
from qtrequestory.core.daily import local_path
from qtrequestory.core.fsutil import is_within, remove_quietly, replace_with_retry

log = logging.getLogger(__name__)

CHUNK = 1024 * 1024

Progress = Callable[[int, int, str], None]


class CancelLike(Protocol):
    """``threading.Event`` or ``events.CancelToken``: anything with ``is_set``."""

    def is_set(self) -> bool: ...


@dataclass
class ImportResult:
    copied: int = 0
    skipped: int = 0       # already in the archive ("già presenti")
    conflicts: int = 0
    errors: list[tuple[Path, str]] = field(default_factory=list)
    verified: list[Path] = field(default_factory=list)
    envs: set[str] = field(default_factory=set)  # envs that received a copy: index them
    cancelled: bool = False


class _Cancelled(Exception):
    pass


# -------------------------------------------------------------------- copy ---

def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def _write_chunk(f, data: bytes) -> None:
    f.write(data)


def _copy_to_part(src: Path, part: Path, cancel: CancelLike | None) -> tuple[int, str]:
    """Stream ``src`` into ``part`` (fsynced); return the size and sha256 read."""
    part.parent.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256()
    size = 0
    with open(src, "rb") as fin, open(part, "wb") as fout:
        while chunk := fin.read(CHUNK):
            _write_chunk(fout, chunk)
            h.update(chunk)
            size += len(chunk)
            if cancel is not None and cancel.is_set():
                raise _Cancelled
        fout.flush()
        os.fsync(fout.fileno())
    return size, h.hexdigest()


def _dest_allows(src: Path, dest: Path) -> str:
    """What the canonical file says NOW: ``copy`` (missing, or a strict prefix
    of ``src``), ``have`` (it already holds all of ``src``) or ``conflict``."""
    if not os.path.lexists(dest):
        return "copy"
    if not dest.is_file():
        return "conflict"
    verdict = compare_files(src, dest)
    if verdict == "b_prefix":
        return "copy"
    return "have" if verdict in ("same", "a_prefix") else "conflict"


def _import_one(item: FoundLog, dest: Path, cancel: CancelLike | None, result: ImportResult) -> None:
    src = item.path
    st = src.stat()
    if st.st_size != item.size or st.st_mtime_ns != item.mtime_ns:
        result.errors.append((src, "il file è cambiato dopo l'analisi: ripeti la ricerca"))
        return
    state = _dest_allows(src, dest)
    if state == "have":
        result.skipped += 1
        result.verified.append(src)
        return
    if state == "conflict":
        result.conflicts += 1
        return
    part = dest.with_name(dest.name + ".part")
    try:
        size, digest = _copy_to_part(src, part, cancel)
        if size != item.size or part.stat().st_size != size or _hash_file(part) != digest:
            result.errors.append((src, "verifica della copia fallita"))
            return
        # Once more, right before the rename: nothing may be overwritten.
        state = _dest_allows(src, dest)
        if state != "copy":
            if state == "have":
                result.skipped += 1
                result.verified.append(src)
            else:
                result.conflicts += 1
            return
        replace_with_retry(part, dest)
    finally:
        remove_quietly(part)  # gone after the rename; a leftover after any failure
    result.copied += 1
    result.verified.append(src)
    result.envs.add(item.env)  # type: ignore[arg-type]
    log.info("importato %s -> %s", src, dest)


def _check_duplicate(item: FoundLog, dest: Path, result: ImportResult) -> None:
    if os.path.lexists(dest) and dest.is_file() and compare_files(item.path, dest) in ("same", "a_prefix"):
        result.skipped += 1
        result.verified.append(item.path)
    else:
        result.errors.append((item.path, "la copia in archivio non contiene questo file"))


def run_import(
    report: ArchiveReport,
    canonical_root: Path,
    *,
    cancel: CancelLike | None = None,
    progress: Progress | None = None,
) -> ImportResult:
    """Copy every ``importable`` item, then re-verify every ``duplicate_same``."""
    canonical_root = Path(canonical_root)
    result = ImportResult(conflicts=len(report.of(CONFLICT)))
    work = report.of(IMPORTABLE) + report.of(DUPLICATE)
    total = len(work)
    for i, item in enumerate(work):
        if progress is not None:
            progress(i, total, item.rel_path)
        if cancel is not None and cancel.is_set():
            result.cancelled = True
            break
        dest = local_path(canonical_root, item.env, item.day)  # type: ignore[arg-type]
        try:
            if item.status == IMPORTABLE:
                _import_one(item, dest, cancel, result)
            else:
                _check_duplicate(item, dest, result)
        except _Cancelled:
            result.cancelled = True
            break
        except OSError as e:
            log.warning("importazione di %s non riuscita: %s", item.path, e)
            result.errors.append((item.path, str(e.strerror or e)))
    else:
        if progress is not None:
            progress(total, total, "")
    return result


# ------------------------------------------------------------- recycle bin ---

FO_DELETE = 0x0003
FOF_SILENT = 0x0004
FOF_NOCONFIRMATION = 0x0010
FOF_ALLOWUNDO = 0x0040
FOF_NOERRORUI = 0x0400
RECYCLE_FLAGS = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI
DRIVE_FIXED = 3


class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("wFunc", ctypes.c_uint),
        ("pFrom", ctypes.c_wchar_p),
        ("pTo", ctypes.c_wchar_p),
        ("fFlags", ctypes.c_ushort),
        ("fAnyOperationsAborted", ctypes.c_int),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", ctypes.c_wchar_p),
    ]


def _shell_delete(path: str) -> tuple[int, bool]:  # pragma: no cover - real shell, mocked in tests
    """SHFileOperationW(FO_DELETE, ALLOWUNDO...) on ONE file: (return code, aborted)."""
    op = _SHFILEOPSTRUCTW()
    op.wFunc = FO_DELETE
    op.pFrom = path + "\0"  # ctypes adds the second terminator
    op.fFlags = RECYCLE_FLAGS
    rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    return rc, bool(op.fAnyOperationsAborted)


def _drive_type(path: Path) -> int:  # pragma: no cover - real API, mocked in tests
    anchor = path.anchor or os.path.splitdrive(str(path))[0] + "\\"
    return ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(anchor))


def send_to_recycle_bin(paths: Sequence[Path], *, canonical_root: Path) -> list[tuple[Path, str]]:
    """Recycle each path; return the ones that were not recycled, with why.

    Never touches a path inside ``canonical_root`` (the whole archive), a
    folder, a symlink, a missing file, or a file on a drive that has no
    Recycle Bin. Windows only: elsewhere every path fails.
    """
    failures: list[tuple[Path, str]] = []
    for raw in paths:
        path = Path(raw)
        why = _refusal(path, Path(canonical_root))
        if why is None:
            try:
                rc, aborted = _shell_delete(str(path))
            except OSError as e:
                rc, aborted = -1, False
                why = f"errore di sistema: {e}"
            if why is None and (rc != 0 or aborted or os.path.lexists(path)):
                why = f"non spostato nel Cestino (codice {rc:#x})"
        if why is not None:
            failures.append((path, why))
        else:
            log.info("spostato nel Cestino: %s", path)
    return failures


def _refusal(path: Path, canonical_root: Path) -> str | None:
    if not path.is_absolute():
        return "percorso non assoluto"
    if is_within(path, canonical_root):
        return "si trova nell'archivio: non viene mai cancellato"
    if sys.platform != "win32":
        return "il Cestino è disponibile solo su Windows"
    if path.is_symlink() or not path.is_file():
        return "non è un file"
    if _drive_type(path) != DRIVE_FIXED:
        return "unità senza Cestino (di rete o rimovibile): cancellalo a mano se vuoi"
    return None
