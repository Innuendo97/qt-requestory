"""Open the SQLite index with the connection settings every caller needs.

WAL + ``synchronous=NORMAL`` lets the UI search while the builder writes;
``busy_timeout`` covers the brief lock the builder takes per file;
``foreign_keys=ON`` is what makes ``ON DELETE CASCADE`` in the DDL do anything
(SQLite ignores it otherwise).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from qtrequestory.core.index.schema import migrate

MEMORY = ":memory:"
BUSY_TIMEOUT_MS = 5000


def open_index(path: Path | str) -> sqlite3.Connection:
    """Open (creating if needed) the index at ``path`` and migrate it to the current schema.

    ``":memory:"`` is accepted for tests.
    """
    if str(path) != MEMORY:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    migrate(conn)
    return conn
