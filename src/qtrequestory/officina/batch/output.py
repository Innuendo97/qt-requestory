"""What a Genera run leaves on disk (spec "Nomi su disco", "Esiti").

Layout, under ``<destinazione>``::

    <generatore>_<AAAAMMGG-HHMMSS>\\
        <cartella>\\<TK>.<ext>        cartella = package name, FDI or NO_PACKAGE
        <cartella>.zip               optional, one per non-empty folder
        esito.csv                    one row per call

**Names.** Every folder and file name is user data (package names, FDIs,
template keys) and becomes exactly one Windows-safe component through
``delivery.safe_component``. Two names that clean up to the same component
in the same folder (``A:B`` and ``A?B``, or ``MOD_A`` and ``mod_a`` on a
case-insensitive disk) never overwrite each other: the later one gets
``_2``, ``_3``… A run RESERVES the names in call order before the first call
goes out (:meth:`Writer.reserve`, then :meth:`Writer.write_reserved`), so
the same request always gives the same names whatever order the answers
come in. A reservation is a stem (``MOD_X``, ``MOD_X_2``) valid for both
``.pdf`` and ``.html``: the type is known only from the answer. A row that
then fails keeps its stem (no renumbering), so a ``_2`` may stand without
its base name. A folder named like the run's own ``esito.csv`` is written as
``_esito.csv``; a zip whose name is taken by a folder gets ``_2``.

**Writes.** Every file goes to a hidden ``.<name>.<random>.part`` in its final
folder and is then moved onto its name, so a document, a zip or the esito is
either whole or absent; the ``.part`` is removed on every path, failures
included.

Stdlib only, Qt-free.
"""
from __future__ import annotations

import csv
import io
import logging
import os
import shutil
import threading
import uuid
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

from qtrequestory.core.fsutil import remove_quietly, replace_with_retry
from qtrequestory.officina.batch.elenco import NO_PACKAGE
from qtrequestory.officina.batch.model import Outcome, Status
from qtrequestory.officina.delivery import MAX_COMPONENT, _write_zip, safe_component
from qtrequestory.officina.links import mask_text, mask_text_for_log

log = logging.getLogger(__name__)

ESITO_NAME = "esito.csv"
#: Most ``<run>_n`` folders tried when two runs start in the same second.
_RUN_DIR_ATTEMPTS = 100
ESITO_COLUMNS = ("template_key", "cartella", "fdi", "esito", "tipo", "file", "durata_ms",
                 "stato_http", "motivo")
#: The Italian word of each status in ``esito.csv`` (and in the UI).
ESITO_LABELS: dict[Status, str] = {
    "ok": "ok",
    "html_skipped": "saltato: HTML",
    "no_call": "nessuna chiamata nei log",
    "failed": "non riuscito",
    "cancelled": "annullato",
}
#: Most ``_n`` suffixes tried for one name (a run has at most a few hundred calls).
MAX_SUFFIX = 10_000
_JOIN = " | "
#: The types a document is saved as; a reserved stem leaves room for the longest.
_DOC_EXTS = ("pdf", "html")
_LONGEST_EXT = max(_DOC_EXTS, key=len)

#: Where one call's document goes: ``(folder, stem)`` per distinct folder.
Slot = tuple[tuple[Path, str], ...]


def run_dir_name(generator: str, now: datetime) -> str:
    """``"<generator>_<AAAAMMGG-HHMMSS>"`` as one safe path component."""
    return safe_component(f"{generator.strip()}_{now:%Y%m%d-%H%M%S}", "genera")


def make_run_dir(destination: Path, name: str) -> Path:
    """``destination/name`` created fresh (``name_2``… when a run of the same
    second exists: a run never writes into another run's folder).
    ``ValueError`` (Italian, masked) when it cannot be created — a drive
    gone, a file in the way, a path too long: the caller then sends no call
    at all, rather than throwing every document away."""
    problem = "troppe generazioni nello stesso secondo"
    for n in range(1, _RUN_DIR_ATTEMPTS + 1):
        candidate = Path(destination) / (name if n == 1 else f"{name}_{n}")
        try:
            candidate.mkdir(parents=True)
            return candidate
        except FileExistsError:
            if os.path.lexists(candidate):
                continue  # a run of the same second (or a file of that name): the next one
            problem = "nel percorso c'è un file al posto di una cartella"
            break
        except OSError as exc:
            problem = exc.strerror or type(exc).__name__
            break
    reason = mask_text(f"impossibile creare la cartella della generazione in {destination}: {problem}")
    log.warning("Genera: %s", mask_text_for_log(reason))
    raise ValueError(reason)


class Writer:
    """Writes the documents of one run under ``run_dir`` (created on first use)."""

    def __init__(self, run_dir: Path) -> None:
        self._run_dir = Path(run_dir)
        self._lock = threading.Lock()
        self._folders: dict[str, str] = {}      # folded folder -> its first spelling on disk
        self._taken: dict[str, set[str]] = {}   # folded folder -> folded file names given out

    def reserve(self, folders: Sequence[str], key: str) -> Slot:
        """The names ``key``'s document will get in every one of ``folders``
        (``NO_PACKAGE`` when there are none), taken now: a later reservation
        of a name that cleans up the same gets ``_2``. Folders that clean up
        to the same component are one. Nothing is written yet."""
        base = safe_component(key, "_")
        planned: list[tuple[Path, str]] = []
        with self._lock:
            seen: set[str] = set()
            for folder in folders or (NO_PACKAGE,):
                component = _folder_component(folder)
                folded = component.casefold()
                if folded in seen:
                    continue
                seen.add(folded)
                component = self._folders.setdefault(folded, component)
                taken = self._taken.setdefault(folded, set())
                directory = self._run_dir / component

                def busy(name: str, taken=taken, directory=directory) -> bool:
                    stem = _stem(name)
                    return stem.casefold() in taken or any(
                        os.path.lexists(directory / f"{stem}.{ext}") for ext in _DOC_EXTS)

                stem = _stem(_free_name(base, _LONGEST_EXT, busy))
                taken.add(stem.casefold())
                planned.append((directory, stem))
        return tuple(planned)

    def write_reserved(self, slot: Slot, ext: str, content: bytes) -> tuple[Path, ...]:
        """``content`` as ``<stem>.<ext>`` in every folder of ``slot``; the
        paths written, in order. Raises ``OSError`` when a file cannot be
        written: the files this call already wrote are removed again, so a
        failed row leaves nothing behind (its names stay reserved)."""
        ext = safe_component(ext.strip().lstrip("."), "bin")
        planned = [directory / f"{stem[:MAX_COMPONENT - len(ext) - 1]}.{ext}" for directory, stem in slot]
        written: list[Path] = []
        try:
            for path in planned:
                path.parent.mkdir(parents=True, exist_ok=True)
                if not written:
                    _atomic_write(path, lambda tmp: _write_bytes(tmp, content))
                else:
                    first = written[0]
                    _atomic_write(path, lambda tmp: shutil.copyfile(first, tmp))
                written.append(path)
        except BaseException:
            for path in written:
                remove_quietly(path)
            raise
        return tuple(written)

    def write(self, folders: Sequence[str], key: str, ext: str, content: bytes) -> tuple[Path, ...]:
        """:meth:`reserve` then :meth:`write_reserved` in one go; on failure the
        names are released again (a retry in the same run gets them)."""
        slot = self.reserve(folders, key)
        try:
            return self.write_reserved(slot, ext, content)
        except BaseException:
            self._release(slot)
            raise

    def _release(self, slot: Slot) -> None:
        with self._lock:
            for directory, stem in slot:
                self._taken.get(directory.name.casefold(), set()).discard(stem.casefold())


def _folder_component(folder: str) -> str:
    """The folder's one safe component; never the run's own ``esito.csv``."""
    component = safe_component(folder, "_")
    if component.casefold() == ESITO_NAME:
        component = safe_component(f"_{component}")
    return component


def _stem(name: str) -> str:
    """``name`` without the ``.<longest ext>`` :func:`_free_name` put on it."""
    return name[: -len(_LONGEST_EXT) - 1]


def _free_name(base: str, ext: str, taken: Callable[[str], bool]) -> str:
    """``<base>.<ext>``, else ``<base>_2.<ext>``, ``<base>_3.<ext>``…: the
    first one not ``taken``. The root is cut BEFORE the suffix goes on, so
    the suffix survives the length limit of a component."""
    for n in range(1, MAX_SUFFIX + 1):
        suffix = "" if n == 1 else f"_{n}"
        root = base[:MAX_COMPONENT - len(ext) - 1 - len(suffix)].rstrip(" .") or "_"
        name = safe_component(f"{root}{suffix}.{ext}")
        if not taken(name):
            return name
    raise OSError(f"nessun nome libero per {base}.{ext}")


def write_esito(run_dir: Path, outcomes: Sequence[Outcome]) -> Path:
    """``run_dir/esito.csv``: ``;``-separated, UTF-8 with BOM (Excel opens it
    as is), one row per outcome in the given order. Reasons are masked again
    here: no signed link reaches the file whatever the caller passed."""
    run_dir = Path(run_dir)
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(ESITO_COLUMNS)
    for o in outcomes:
        writer.writerow([
            o.key,
            _JOIN.join(o.folders),
            o.fdi or "",
            ESITO_LABELS.get(o.status, o.status),
            o.doc_type or "",
            _JOIN.join(_relative(p, run_dir) for p in o.files),
            str(int(o.duration_ms)),
            "" if o.http_status is None else str(o.http_status),
            mask_text(o.reason or ""),
        ])
    data = buffer.getvalue().encode("utf-8-sig")
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / ESITO_NAME
    _atomic_write(path, lambda tmp: _write_bytes(tmp, data))
    return path


def zip_folders(run_dir: Path) -> tuple[Path, ...]:
    """``<cartella>.zip`` next to every non-empty folder of ``run_dir`` (the
    folder stays). Entries are ``<cartella>/<file>``, so unzipping gives the
    folder back. Raises ``OSError`` (or ``ValueError``) on the first failure,
    after removing the zips it already made: either every folder has its zip
    or none has."""
    run_dir = Path(run_dir)
    made: list[Path] = []
    try:
        folders = sorted((p for p in run_dir.iterdir() if p.is_dir() and not p.is_symlink()),
                         key=lambda p: p.name.casefold())
        for folder in folders:
            members = [p for p in folder.iterdir()
                       if p.is_file() and not (p.name.startswith(".") and p.name.endswith(".part"))]
            if not members:
                continue
            # a folder may itself be called "<other>.zip": never write over it
            taken = {p.name.casefold() for p in made}
            name = _free_name(folder.name, "zip",
                              lambda n: n.casefold() in taken or os.path.lexists(run_dir / n))
            archive = run_dir / name
            _atomic_write(archive, lambda tmp, m=members: _write_zip(run_dir, m, tmp))
            made.append(archive)
    except BaseException:
        for archive in made:
            remove_quietly(archive)
        raise
    return tuple(made)


# ------------------------------------------------------------------ helpers ---

def _write_bytes(path: Path, content: bytes) -> None:
    with open(path, "xb") as f:
        f.write(content)


def _atomic_write(final: Path, fill: Callable[[Path], object]) -> None:
    """``fill(tmp)`` into a hidden ``.part`` next to ``final``, then move it
    onto ``final``. The ``.part`` never survives, whatever happens."""
    tmp = final.with_name(f".{final.name}.{uuid.uuid4().hex[:12]}.part")
    try:
        fill(tmp)
        replace_with_retry(tmp, final)
    finally:
        remove_quietly(tmp)


def _relative(path: Path, run_dir: Path) -> str:
    try:
        return os.fspath(Path(path).relative_to(run_dir))
    except ValueError:
        return Path(path).name
