"""Index schema: DDL, version and the (deliberately blunt) migration policy.

The index is a pure cache over the mirrored daily files — every row can be
rebuilt from disk in minutes. So instead of incremental migrations, any
``PRAGMA user_version`` mismatch drops every known table and recreates them;
the next ``IndexBuilder.update`` refills them. Bump ``SCHEMA_VERSION`` on any
DDL change, and leave a dropped table's name in ``TABLES`` so that an older
database still loses it.

Version 2 removed ``entry_documents`` (one row per document per entry, plus its
index). It was written on every build and selected by nothing: pure write cost
on the one operation the user waits for. Should a "search by attachment key"
mode ever be wanted, the data is still on the ``ScannedEntry.doc_keys`` the
scanner produces — re-add the table deliberately, with the query that reads it.
"""
from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 2

#: Drop order: children first. ``entry_documents`` stays in the list although
#: version 2 no longer creates it — that is how an index.sqlite written by
#: version 1 gets rid of it.
TABLES = ("entry_documents", "entries", "files")

DDL = """
CREATE TABLE files (id INTEGER PRIMARY KEY, env TEXT NOT NULL, day TEXT NOT NULL, rel_path TEXT NOT NULL,
  size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL, n_entries INTEGER NOT NULL,
  n_orphans INTEGER NOT NULL DEFAULT 0, scanned_at TEXT NOT NULL, UNIQUE (env, day));
CREATE TABLE entries (id INTEGER PRIMARY KEY, file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  env TEXT NOT NULL, day TEXT NOT NULL, seq INTEGER NOT NULL, name TEXT NOT NULL,
  fdi TEXT, template_key TEXT NOT NULL COLLATE NOCASE, call_id TEXT, well_formed INTEGER NOT NULL,
  header_offset INTEGER NOT NULL, body_offset INTEGER NOT NULL, body_len INTEGER NOT NULL,
  request_date TEXT, ndocs INTEGER, dossier_id TEXT, dossier_number TEXT, json_ok INTEGER NOT NULL DEFAULT 1);
CREATE INDEX ix_entries_env_day ON entries(env, day);
CREATE INDEX ix_entries_fdi ON entries(env, fdi);
CREATE INDEX ix_entries_key ON entries(env, template_key);
"""


def schema_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def migrate(conn: sqlite3.Connection) -> None:
    """Bring ``conn`` to ``SCHEMA_VERSION``: no-op if current, else drop + recreate.

    A fresh database has ``user_version == 0`` and takes the same path, so this
    is also the "create" step.
    """
    if schema_version(conn) == SCHEMA_VERSION:
        return
    script = "".join(f"DROP TABLE IF EXISTS {t};\n" for t in TABLES) + DDL
    # PRAGMA values cannot be bound as parameters; SCHEMA_VERSION is a trusted int.
    script += f"PRAGMA user_version = {int(SCHEMA_VERSION)};\n"
    conn.executescript(script)
