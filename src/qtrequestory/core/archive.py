"""Find nginx daily logs in any folder layout and decide what importing them means.

Colleagues keep months of old logs wherever they happened to save them. They
are never indexed in place: ``core/importer.py`` COPIES them into the
canonical tree ``<mirror_root>/<env>/YYYY/MM/YYYYMMDD.txt``. This module only
looks — it never writes — and produces an :class:`ArchiveReport` with one
:class:`FoundLog` per candidate file and a verdict:

* ``importable``: copy it (a new day, or the archive's copy is a strict
  prefix of it and gets replaced);
* ``duplicate_same``: its content is already in the archive (identical, or a
  prefix of the archive's copy or of another imported file that is copied);
* ``needs_env``: day known, environment not — the UI asks once per folder
  (``Config.folder_envs``);
* ``conflict``: two different versions of one env+day; nothing is copied;
* ``ignored``: not a call log, no/ambiguous date, compressed, ignored folder.

The rule for "different versions" is strict on purpose: the index reads
bodies by byte offset, so a copy equal only modulo CRLF line endings is a
conflict unless the archive does not have that day at all.

Walked with ``os.scandir`` and an explicit stack; never follows symlinks or
junctions, never enters dot-folders, ``$RECYCLE.BIN`` or ``System Volume
Information``; the app's own ``.part`` / ``.remote-<n>`` files and every file
already at its canonical path under ``canonical_root`` are skipped silently.
"""
from __future__ import annotations

import logging
import os
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Literal

from qtrequestory.core.archive_names import day_from_parts, env_from_parts
from qtrequestory.core.config import IGNORE_FOLDER
from qtrequestory.core.daily import day_from_name, local_path
from qtrequestory.core.fsutil import is_within
from qtrequestory.core.index.scanner import BLANKS, BOM, HEADER_RE

log = logging.getLogger(__name__)

IMPORTABLE = "importable"
DUPLICATE = "duplicate_same"
NEEDS_ENV = "needs_env"
CONFLICT = "conflict"
IGNORED = "ignored"
STATUSES = (IMPORTABLE, DUPLICATE, NEEDS_ENV, CONFLICT, IGNORED)
Status = Literal["importable", "duplicate_same", "needs_env", "conflict", "ignored"]

R_NEW = "giorno mancante in archivio"
R_EMPTY = "giorno senza chiamate"
R_MORE_COMPLETE = "più completo della copia in archivio"
R_SAME = "già in archivio"
R_ARCHIVE_BIGGER = "l'archivio ha già una copia più completa"
R_CONFLICT = "copie diverse dello stesso giorno"
R_NEEDS_ENV = "ambiente non riconoscibile dal percorso"
R_COMPRESSED = "archivio compresso: estrailo nella cartella"
R_NOT_A_LOG = "non è un log di chiamate"
R_IGNORED_FOLDER = "cartella da ignorare"
R_UNREADABLE = "illeggibile"

COMPRESSED_SUFFIXES = frozenset({".zip", ".gz", ".7z", ".rar", ".tgz"})
SKIPPED_DIRS = frozenset({"$recycle.bin", "system volume information"})
_APP_FILE = re.compile(r"(\.part|\.remote-\d+)$", re.IGNORECASE)
SNIFF_BYTES = 64 * 1024
CHUNK = 1024 * 1024

Comparison = Literal["same", "a_prefix", "b_prefix", "diverge"]


@dataclass(frozen=True)
class FoundLog:
    rel_path: str           # relative to the scanned root, forward slashes
    path: Path              # absolute
    size: int
    mtime_ns: int
    env: str | None
    day: date | None
    status: Status
    reason: str             # Italian, short
    dest: Path | None       # canonical destination, when env and day are known

    @property
    def rel_dir(self) -> str:
        """The folder, relative to the scanned root ("" for the root itself)."""
        head, _, _ = self.rel_path.rpartition("/")
        return head


@dataclass(frozen=True)
class ArchiveReport:
    root: Path
    canonical_root: Path | None
    items: tuple[FoundLog, ...]

    def of(self, status: str) -> list[FoundLog]:
        return [f for f in self.items if f.status == status]

    def counts(self) -> dict[str, int]:
        return {s: len(self.of(s)) for s in STATUSES}

    def needs_env_dirs(self) -> list[str]:
        """The folders the UI asks an environment for, sorted."""
        return sorted({f.rel_dir for f in self.of(NEEDS_ENV)})


# ------------------------------------------------------------------ compare ---

def compare_files(a: Path, b: Path) -> Comparison:
    """Byte comparison, streamed: ``a_prefix`` means ``a`` is a STRICT prefix
    of ``b`` (an empty file is a prefix of anything non-empty)."""
    size_a, size_b = os.path.getsize(a), os.path.getsize(b)
    left = min(size_a, size_b)
    with open(a, "rb") as fa, open(b, "rb") as fb:
        while left > 0:
            n = min(CHUNK, left)
            ca, cb = fa.read(n), fb.read(n)
            if ca != cb or len(ca) != n:
                return "diverge"
            left -= n
    if size_a == size_b:
        return "same"
    return "a_prefix" if size_a < size_b else "b_prefix"


# -------------------------------------------------------------------- sniff ---

def _read_head(path: Path) -> bytes:
    with open(path, "rb") as f:
        return f.read(SNIFF_BYTES)


def looks_like_log(head: bytes) -> bool:
    """The first non-blank line (after a BOM) is a ``### <name>.json`` header."""
    if head.startswith(BOM):
        head = head[len(BOM):]
    lines = head.split(b"\n")
    for i, line in enumerate(lines):
        if not line.strip(BLANKS):
            continue
        return HEADER_RE.match(line + (b"\n" if i < len(lines) - 1 else b"")) is not None
    return False


# ------------------------------------------------------------------- walk ---

def _walk(root: Path) -> list[tuple[Path, list[str], os.stat_result]]:
    """Every regular file under ``root``: (path, rel parts, stat)."""
    out: list[tuple[Path, list[str], os.stat_result]] = []
    stack: list[tuple[Path, list[str]]] = [(root, [])]
    while stack:
        folder, rel = stack.pop()
        try:
            with os.scandir(folder) as it:
                entries = list(it)
        except OSError as e:
            log.warning("archivio: impossibile leggere la cartella %s: %s", folder, e)
            continue
        for entry in entries:
            try:
                if entry.is_symlink() or entry.is_junction():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    name = entry.name
                    if name.startswith(".") or name.casefold() in SKIPPED_DIRS:
                        continue
                    stack.append((Path(entry.path), rel + [name]))
                elif entry.is_file(follow_symlinks=False):
                    out.append((Path(entry.path), rel + [entry.name], entry.stat(follow_symlinks=False)))
            except OSError as e:
                log.warning("archivio: impossibile leggere %s: %s", entry.path, e)
    return out


def _is_canonical(path: Path, canonical_root: Path | None) -> bool:
    """``path`` is ``<canonical_root>/<env>/YYYY/MM/YYYYMMDD.txt``."""
    if canonical_root is None or not is_within(path, canonical_root):
        return False
    rel = os.path.relpath(os.path.abspath(path), os.path.abspath(canonical_root))
    parts = Path(rel).parts
    if len(parts) != 4:
        return False
    day = day_from_name(parts[3])
    return day is not None and parts[1] == f"{day:%Y}" and parts[2] == f"{day:%m}"


# ------------------------------------------------------------ folder_envs ---

def _norm_key(key: str) -> str:
    key = key.replace("\\", "/").strip("/")
    return "" if key == "." else key.casefold()


def _folder_choice(root: Path, rel_dirs: list[str], folder_envs: Mapping[str, str],
                   env_names: Sequence[str]) -> str | None:
    """The deepest folder the user assigned: a configured env name, IGNORE_FOLDER
    or ``None``. Keys are folders relative to the scanned root, or absolute."""
    if not folder_envs:
        return None
    by_lower = {e.lower(): e for e in env_names}
    rel_keys: dict[str, str] = {}
    abs_keys: dict[str, str] = {}
    for key, value in folder_envs.items():
        if os.path.isabs(key):
            abs_keys[os.path.normcase(os.path.abspath(key))] = value
        else:
            rel_keys[_norm_key(key)] = value
    for rel_dir in rel_dirs:  # deepest first
        candidates = [rel_keys.get(rel_dir.casefold()),
                      abs_keys.get(os.path.normcase(os.path.abspath(root / rel_dir)))]
        for value in candidates:
            if value is None:
                continue
            if value == IGNORE_FOLDER:
                return IGNORE_FOLDER
            if value.lower() in by_lower:
                return by_lower[value.lower()]
            # an env that is no longer configured: not trusted, look further up
    return None


def _ancestors(rel_parts: list[str]) -> list[str]:
    """``["a","b","f.txt"]`` -> ``["a/b", "a", ""]``."""
    dirs = rel_parts[:-1]
    return ["/".join(dirs[:i]) for i in range(len(dirs), -1, -1)]


# ---------------------------------------------------------------- discover ---

def discover(
    root: Path,
    env_names: Sequence[str],
    folder_envs: Mapping[str, str],
    *,
    canonical_root: Path | None = None,
    today: date | None = None,
) -> ArchiveReport:
    """Walk ``root`` and classify every file (read-only)."""
    root = Path(root)
    canonical = Path(canonical_root) if canonical_root is not None else None
    today = today if today is not None else date.today()
    found: list[FoundLog] = []
    for path, rel_parts, st in _walk(root) if root.is_dir() else []:
        if _APP_FILE.search(path.name) or _is_canonical(path, canonical):
            continue
        base = FoundLog("/".join(rel_parts), path, st.st_size, st.st_mtime_ns,
                        None, None, IGNORED, "", None)
        found.append(_classify(base, root, rel_parts, env_names, folder_envs, canonical, today))
    found = _resolve_groups(found, canonical)
    found.sort(key=lambda f: f.rel_path)
    return ArchiveReport(root, canonical, tuple(found))


def _classify(item: FoundLog, root: Path, rel_parts: list[str], env_names: Sequence[str],
              folder_envs: Mapping[str, str], canonical: Path | None, today: date) -> FoundLog:
    if item.path.suffix.lower() in COMPRESSED_SUFFIXES:
        return replace(item, reason=R_COMPRESSED)
    choice = _folder_choice(root, _ancestors(rel_parts), folder_envs, env_names)
    if choice == IGNORE_FOLDER:
        return replace(item, reason=R_IGNORED_FOLDER)
    if item.size > 0:
        try:
            if not looks_like_log(_read_head(item.path)):
                return replace(item, reason=R_NOT_A_LOG)
        except OSError as e:
            return replace(item, reason=f"{R_UNREADABLE}: {e.strerror or e}")
    parts = list(reversed(rel_parts)) + ([root.name] if root.name else [])
    day, why = day_from_parts(parts, today=today)
    if day is None:
        return replace(item, reason=why or "")
    env = choice or env_from_parts(parts, env_names)
    if env is None and len(env_names) == 1:
        env = env_names[0]
    if env is None:
        return replace(item, day=day, status=NEEDS_ENV, reason=R_NEEDS_ENV)
    dest = local_path(canonical, env, day) if canonical is not None else None
    # Provisional: the verdict comes from _resolve_groups.
    return replace(item, env=env, day=day, status=IMPORTABLE, reason=R_NEW, dest=dest)


def _resolve_groups(items: list[FoundLog], canonical: Path | None) -> list[FoundLog]:
    groups: dict[tuple[str, date], list[FoundLog]] = defaultdict(list)
    out: list[FoundLog] = []
    for item in items:
        if item.status == IMPORTABLE:
            groups[(item.env, item.day)].append(item)  # type: ignore[index]
        else:
            out.append(item)
    for members in groups.values():
        out.extend(_resolve_group(members))
    return out


def _resolve_group(members: list[FoundLog]) -> list[FoundLog]:
    """One env+day: the largest copy is the candidate, the others must be
    prefixes of it; then the candidate is compared with the archive."""
    members = sorted(members, key=lambda f: (-f.size, f.rel_path))
    lead, rest = members[0], members[1:]
    try:
        for other in rest:
            if compare_files(other.path, lead.path) not in ("same", "a_prefix"):
                return [replace(m, status=CONFLICT, reason=R_CONFLICT) for m in members]
        status, reason = _against_archive(lead)
    except OSError as e:
        return [replace(m, status=IGNORED, reason=f"{R_UNREADABLE}: {e.strerror or e}") for m in members]
    if status == CONFLICT:
        return [replace(m, status=CONFLICT, reason=R_CONFLICT) for m in members]
    shadow_reason = R_SAME if status == DUPLICATE else f"contenuto già in {lead.rel_path}"
    return [replace(lead, status=status, reason=reason)] + [
        replace(m, status=DUPLICATE, reason=shadow_reason) for m in rest
    ]


def _against_archive(item: FoundLog) -> tuple[Status, str]:
    dest = item.dest
    if dest is None or not os.path.lexists(dest):
        return IMPORTABLE, (R_EMPTY if item.size == 0 else R_NEW)
    if not dest.is_file():
        return CONFLICT, R_CONFLICT
    verdict = compare_files(item.path, dest)
    if verdict == "same":
        return DUPLICATE, R_SAME
    if verdict == "a_prefix":
        return DUPLICATE, R_ARCHIVE_BIGGER
    if verdict == "b_prefix":
        return IMPORTABLE, R_MORE_COMPLETE
    return CONFLICT, R_CONFLICT
