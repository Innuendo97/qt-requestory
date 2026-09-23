"""Open the SQLite index with the connection settings every caller needs.

WAL + ``synchronous=NORMAL`` lets the UI search while the builder writes;
``busy_timeout`` covers the brief lock the builder takes per file;
``foreign_keys=ON`` is what makes ``ON DELETE CASCADE`` in the DDL do anything
(SQLite ignores it otherwise).

The index is a rebuildable cache, so a corrupt ``index.sqlite`` is never worth
an error the user cannot get out of (``--index --rebuild`` opens it the same
way): it is set aside as ``index.sqlite.broken-YYYYMMDD-HHMMSS`` and a fresh
one takes its place, which the next update refills.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from qtrequestory.core.index.schema import migrate

log = logging.getLogger(__name__)

MEMORY = ":memory:"
BUSY_TIMEOUT_MS = 5000
#: Set-aside corrupt copies kept next to the index (the oldest go first).
KEEP_BROKEN = 3
#: One short retry when switching to WAL finds the file locked (another
#: process opening or repairing the same index at that very moment).
WAL_RETRY_DELAY_S = 0.2

#: ``sqlite3.DatabaseError`` messages that mean "the file itself is damaged" —
#: not "busy", "locked" or "readonly", which a retry or the user can fix.
_CORRUPT_MARKERS = ("not a database", "malformed")


def open_index(path: Path | str) -> sqlite3.Connection:
    """Open (creating if needed) the index at ``path`` and migrate it to the current schema.

    ``":memory:"`` is accepted for tests. A damaged file is replaced by a fresh
    index whichever statement first notices the damage (see module docstring).
    """
    if str(path) == MEMORY:
        return _connect(MEMORY)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        return _connect(path)
    except sqlite3.DatabaseError as e:
        if not _is_corrupt(e):
            raise
        corrupt = e
    # The GUI and the hourly --sync can find the same corrupt file at once. If
    # the other one has repaired it meanwhile, what is at `path` now is ITS
    # fresh index: use it, never set it aside.
    try:
        return _connect(path)
    except sqlite3.DatabaseError as e:
        if not _is_corrupt(e):
            raise
    try:
        broken = _set_aside(path)
    except OSError:  # e.g. Windows: the other process holds the file open
        raise corrupt from None
    log.warning("indice corrotto (%s): spostato in %s, verrà ricostruito", corrupt, broken.name)
    return _connect(path)


def _connect(target: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(target))
    try:
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        _enable_wal(conn)
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        migrate(conn)
        # The PRAGMAs above may only read the file header: make SQLite parse the
        # schema and read the root page of both tables now (NOT INDEXED: left
        # alone, the planner would scan a smaller index instead), so damage
        # there surfaces here and not at the first search. Cheap: one row each.
        conn.execute(
            "SELECT (SELECT 1 FROM files NOT INDEXED LIMIT 1), (SELECT 1 FROM entries NOT INDEXED LIMIT 1)"
        ).fetchone()
    except BaseException:
        conn.close()  # Windows: the file cannot be renamed while a handle is open
        raise
    return conn


def _enable_wal(conn: sqlite3.Connection) -> None:
    """Switch to WAL, retrying once if the file is locked. The journal-mode
    change does not always go through the busy handler; a locked error is
    never corruption, so after the retry it simply propagates."""
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError as e:
        if "locked" not in str(e).lower():
            raise
        time.sleep(WAL_RETRY_DELAY_S)
        conn.execute("PRAGMA journal_mode=WAL")


def _is_corrupt(e: sqlite3.DatabaseError) -> bool:
    message = str(e).lower()
    return any(marker in message for marker in _CORRUPT_MARKERS)


def _set_aside(path: Path) -> Path:
    """Rename ``path`` to ``<name>.broken-<stamp>``, drop its WAL/SHM, prune old copies."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = path.with_name(f"{path.name}.broken-{stamp}")
    n = 1
    while target.exists():  # two repairs within the same second
        target = path.with_name(f"{path.name}.broken-{stamp}-{n}")
        n += 1
    path.replace(target)
    for suffix in ("-wal", "-shm"):
        path.with_name(path.name + suffix).unlink(missing_ok=True)
    broken = sorted(path.parent.glob(f"{path.name}.broken-*"))
    for old in broken[:-KEEP_BROKEN]:
        old.unlink(missing_ok=True)
    return target
