"""Deleting an initiative's folder for good (phase 2.5, D6) — stdlib only.

The UI never deletes at once: the initiative disappears from the list, the
bar offers "Annulla" for 5 s, and only then :func:`delete_initiative_folder`
runs (``OfficinaApi.delete_initiative``). It is the one place of the Officina
that removes a whole tree, so it refuses anything it cannot prove is an
initiative folder directly inside the configured Officina folder — a wrong
path here would be unrecoverable:

* the Officina folder is set and absolute, and exists;
* ``folder`` is ONE plain, non-reserved name directly under it (never the
  folder itself, never deeper, never a path with ``..``) — checked on the paths
  as given AND once resolved, so a link pointing elsewhere is refused;
* ``folder`` is a real directory, not a symlink or a junction;
* it holds an ``iniziativa.json`` file.

Anything else is :class:`RefusedDeletion` (a ``ValueError``) and nothing is
touched.

**All or nothing, as far as Windows allows.** The folder is first RENAMED to
a hidden sibling (``.eliminazione-<name>-<random>``, same volume): on Windows
a folder with a file open inside cannot be renamed, so a PDF open in Acrobat
or a shell window inside it makes the rename fail with ``PermissionError``
and the initiative stays whole. Only the renamed copy is then removed:
every entry but ``iniziativa.json`` (matched ignoring case) first (read-only files are made writable;
a link inside is removed, never followed), ``iniziativa.json`` LAST, then the
empty folder. Should that still fail half-way, the copy is renamed back: it
still holds ``iniziativa.json``, so the initiative reappears in the list with
what is left and can be deleted again once the file is free (should even the
rename back fail, the hidden copy is listed as an initiative, for the same
reason). The time taken is logged (a worker thread is on the backlog).
"""
from __future__ import annotations

import logging
import os
import shutil
import stat
import time
import uuid
from pathlib import Path

from qtrequestory.officina.model_versions import is_safe_component

__all__ = ["INITIATIVE_FILE", "RefusedDeletion", "check_initiative_folder", "delete_initiative_folder"]

log = logging.getLogger(__name__)

INITIATIVE_FILE = "iniziativa.json"
#: Windows device names: never a folder of ours.
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{d}" for d in range(10)} | {f"LPT{d}" for d in range(10)}
TOMBSTONE_PREFIX = ".eliminazione-"


class RefusedDeletion(ValueError):
    """``folder`` is not provably an initiative folder inside the Officina
    folder: nothing was deleted."""


def _is_link(path: Path) -> bool:
    isjunction = getattr(os.path, "isjunction", None)  # 3.12+
    return path.is_symlink() or bool(isjunction and isjunction(path))


def check_initiative_folder(root: Path | None, folder: Path) -> Path:
    """The resolved ``folder`` when it may be deleted; :class:`RefusedDeletion` otherwise."""
    if root is None or not str(root).strip() or not Path(root).is_absolute():
        raise RefusedDeletion("cartella dell'Officina non impostata")
    root, folder = Path(root), Path(folder)
    if not folder.is_absolute() or any(part in (".", "..") for part in folder.parts):
        raise RefusedDeletion(f"percorso non valido: {folder}")
    name = folder.name
    if not is_safe_component(name) or name.split(".", 1)[0].strip().upper() in _RESERVED:
        raise RefusedDeletion(f"nome di cartella non valido: {name!r}")
    if os.path.normcase(os.path.normpath(folder.parent)) != os.path.normcase(os.path.normpath(root)):
        raise RefusedDeletion(f"{folder} non è direttamente nella cartella dell'Officina")
    if not root.is_dir():
        raise RefusedDeletion(f"la cartella dell'Officina non esiste: {root}")
    if _is_link(folder):
        raise RefusedDeletion(f"{folder} è un collegamento, non una cartella di iniziativa")
    if not folder.is_dir():
        if not folder.exists():
            raise FileNotFoundError(f"iniziativa non trovata: {folder}")
        raise RefusedDeletion(f"{folder} non è una cartella")
    real_root, real = root.resolve(strict=True), folder.resolve(strict=True)
    if real.parent != real_root or real == real_root:
        raise RefusedDeletion(f"{folder} non è dentro la cartella dell'Officina")
    meta = folder / INITIATIVE_FILE
    if _is_link(meta) or not meta.is_file():
        raise RefusedDeletion(f"{folder} non contiene {INITIATIVE_FILE}: non è un'iniziativa")
    return real


def _writable_and_retry(func, path, exc) -> None:  # noqa: ANN001 - shutil's onexc signature
    """``shutil.rmtree`` ``onexc``: an entry already gone is removed; a
    read-only file (Windows attribute) is made writable, once."""
    if isinstance(exc, FileNotFoundError):
        return
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _remove_entry(path: Path) -> None:
    """Remove one child of the renamed folder (a tree, a file or a link)."""
    if _is_link(path):
        (os.rmdir if path.is_dir() else os.unlink)(path)  # the link, never its target
    elif path.is_dir():
        shutil.rmtree(path, onexc=_writable_and_retry)
    else:
        try:
            path.unlink()
        except PermissionError:
            os.chmod(path, stat.S_IWRITE)
            path.unlink()


def _is_meta(path: Path) -> bool:
    """``iniziativa.json`` however it is spelt (NTFS ignores case)."""
    return os.path.normcase(path.name) == os.path.normcase(INITIATIVE_FILE)


def _remove_child(path: Path) -> None:
    """:func:`_remove_entry`, where an entry already gone counts as removed."""
    try:
        _remove_entry(path)
    except FileNotFoundError:
        pass


def delete_initiative_folder(root: Path | None, folder: Path) -> None:
    """Delete ``folder`` (an initiative directly under ``root``) permanently.

    ``RefusedDeletion`` when it is not provably one (nothing touched);
    ``FileNotFoundError`` when it is already gone; ``PermissionError`` /
    ``OSError`` when a file inside is in use or protected (the initiative
    stays, whole when the first step — the rename — was refused)."""
    real = check_initiative_folder(root, folder)
    tomb = real.with_name(f"{TOMBSTONE_PREFIX}{real.name}-{uuid.uuid4().hex[:8]}")
    started = time.monotonic()
    real.rename(tomb)  # PermissionError while anything inside is open: nothing lost
    try:
        children = sorted(tomb.iterdir())
        for child in [c for c in children if not _is_meta(c)]:
            _remove_child(child)
        for meta in [c for c in children if _is_meta(c)]:  # last: until here it is still an initiative
            _remove_child(meta)
        tomb.rmdir()
    except OSError as exc:
        log.warning("eliminazione di %s non completata: la cartella torna al suo posto", real.name)
        try:
            tomb.rename(real)
        except OSError:
            log.exception("impossibile ripristinare %s (resta come %s)", real.name, tomb.name)
        if isinstance(exc, FileNotFoundError):  # upstream that reads "already gone": never while it is back
            raise OSError(f"eliminazione non completata: {exc.strerror or exc}") from exc  # no errno: 2 = FileNotFoundError
        raise
    log.info("iniziativa eliminata: %s in %.2f s", real.name, time.monotonic() - started)
