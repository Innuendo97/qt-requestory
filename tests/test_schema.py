"""core/index/schema.py + db.py: DDL, PRAGMAs and the drop-and-rebuild migration."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from qtrequestory.core.index.db import open_index
from qtrequestory.core.index.schema import SCHEMA_VERSION, migrate, schema_version

EXPECTED_TABLES = {"files", "entries", "entry_documents"}
EXPECTED_INDEXES = {"ix_entries_env_day", "ix_entries_fdi", "ix_entries_key", "ix_entry_documents_key"}


def _names(conn: sqlite3.Connection, kind: str) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = ?", (kind,)).fetchall()
    return {r["name"] for r in rows if not r["name"].startswith("sqlite_")}


def test_fresh_open_creates_schema_with_wal(tmp_path: Path):
    path = tmp_path / "nested" / "dir" / "index.sqlite"
    conn = open_index(path)
    try:
        assert path.exists()  # parent dirs created
        assert _names(conn, "table") == EXPECTED_TABLES
        assert _names(conn, "index") == EXPECTED_INDEXES
        assert schema_version(conn) == SCHEMA_VERSION == 1
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        assert conn.row_factory is sqlite3.Row
    finally:
        conn.close()


def test_open_index_in_memory_works():
    conn = open_index(":memory:")
    try:
        assert _names(conn, "table") == EXPECTED_TABLES
        assert schema_version(conn) == 1
    finally:
        conn.close()


def test_migrate_drops_and_recreates_when_version_differs(tmp_path: Path):
    path = tmp_path / "index.sqlite"
    raw = sqlite3.connect(path)
    raw.execute("CREATE TABLE entries (x TEXT)")
    raw.executemany("INSERT INTO entries VALUES (?)", [("a",), ("b",)])
    raw.commit()
    assert raw.execute("PRAGMA user_version").fetchone()[0] == 0
    raw.close()

    conn = open_index(path)
    try:
        assert schema_version(conn) == 1
        assert conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 0
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(entries)")}
        assert {"file_id", "seq", "name", "fdi", "template_key", "body_offset", "json_ok"} <= cols
        assert "x" not in cols
        assert _names(conn, "table") == EXPECTED_TABLES
    finally:
        conn.close()


def test_migrate_is_noop_when_version_matches(tmp_path: Path):
    path = tmp_path / "index.sqlite"
    conn = open_index(path)
    try:
        conn.execute(
            "INSERT INTO files (env, day, rel_path, size, mtime_ns, n_entries, scanned_at) "
            "VALUES ('coll', '20260918', 'coll/2026/09/20260918.txt', 1, 1, 0, 'now')"
        )
        conn.commit()
        migrate(conn)
        assert conn.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 1
    finally:
        conn.close()


def test_foreign_keys_cascade_from_files_to_entries():
    conn = open_index(":memory:")
    try:
        conn.execute(
            "INSERT INTO files (id, env, day, rel_path, size, mtime_ns, n_entries, scanned_at) "
            "VALUES (1, 'coll', '20260918', 'coll/2026/09/20260918.txt', 1, 1, 1, 'now')"
        )
        conn.execute(
            "INSERT INTO entries (id, file_id, env, day, seq, name, template_key, well_formed, "
            "header_offset, body_offset, body_len) VALUES (7, 1, 'coll', '20260918', 0, 'n', 'K', 1, 0, 10, 5)"
        )
        conn.execute("INSERT INTO entry_documents (entry_id, pos, template_key) VALUES (7, 0, 'K')")
        conn.execute("DELETE FROM files WHERE id = 1")
        assert conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM entry_documents").fetchone()[0] == 0
    finally:
        conn.close()
