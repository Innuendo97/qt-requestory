"""Keep the SQLite index in step with the mirrored daily files.

The index is a cache: ``plan`` diffs the mirror on disk against the ``files``
table by ``(size, mtime_ns)`` and ``update`` rescans only what changed. Each
file is written in ONE transaction (delete old rows -> insert file -> insert
entries -> insert documents) so a crash or a cancel between files never
leaves a half-indexed day: ``read_body`` can trust every row it finds.
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from qtrequestory.core.daily import LocalDailyFile, list_local_daily_files, local_path, relative_path
from qtrequestory.core.events import CancelToken, EventSink, IndexFileScanned, IndexFinished, IndexStarted
from qtrequestory.core.index.scanner import ScannedEntry, scan_daily_file

# ANALYZE costs a full index read; it only pays off after a sizeable batch.
ANALYZE_THRESHOLD = 10

_INSERT_FILE = (
    "INSERT INTO files (env, day, rel_path, size, mtime_ns, n_entries, n_orphans, scanned_at) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
)
_INSERT_ENTRY = (
    "INSERT INTO entries (file_id, env, day, seq, name, fdi, template_key, call_id, well_formed, "
    "header_offset, body_offset, body_len, request_date, ndocs, dossier_id, dossier_number, json_ok) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)
_INSERT_DOCUMENT = "INSERT INTO entry_documents (entry_id, pos, template_key) VALUES (?, ?, ?)"


@dataclass
class IndexPlan:
    to_scan: list[LocalDailyFile] = field(default_factory=list)  # newest first
    to_remove: list[int] = field(default_factory=list)  # files.id whose file vanished


@dataclass(frozen=True)
class IndexStats:
    scanned: int
    removed: int
    seconds: float


def _entry_row(file_id: int, env: str, day: str, e: ScannedEntry) -> tuple:
    n = e.name
    return (
        file_id, env, day, e.seq, n.raw,
        n.fdi or None,  # a degenerate "_KEY_id" name parses to fdi == "": store NULL, not ""
        n.template_key, n.call_id, int(n.well_formed),
        e.header_offset, e.body_offset, e.body_len,
        e.request_date, e.ndocs, e.dossier_id, e.dossier_number, int(e.json_ok),
    )


class IndexBuilder:
    def __init__(
        self,
        conn: sqlite3.Connection,
        root: Path,
        sink: EventSink,
        cancel: CancelToken | None = None,
        *,
        parse_json: bool = True,
    ) -> None:
        self._conn = conn
        self._root = Path(root)
        self._sink = sink
        self._cancel = cancel
        self._parse_json = parse_json

    # ------------------------------------------------------------- plan ---

    def plan(self, envs: list[str]) -> IndexPlan:
        """Diff disk vs index for ``envs``: new/changed files to scan (newest
        first), ids of indexed files that no longer exist to remove."""
        plan = IndexPlan()
        for env in envs:
            indexed = {
                row["day"]: row
                for row in self._conn.execute("SELECT id, day, size, mtime_ns FROM files WHERE env=?", (env,))
            }
            for f in list_local_daily_files(self._root, env):
                row = indexed.pop(f.day.isoformat(), None)
                if row is None or (row["size"], row["mtime_ns"]) != (f.size, f.mtime_ns):
                    plan.to_scan.append(f)
            plan.to_remove.extend(row["id"] for row in indexed.values())
        plan.to_scan.sort(key=lambda f: f.day, reverse=True)
        return plan

    # ----------------------------------------------------------- update ---

    def update(self, envs: list[str], *, full_rebuild: bool = False) -> IndexStats:
        """Bring the index up to date for ``envs``.

        ``cancel`` is honoured between files (and inside the scanner, before
        anything is written), so a ``Cancelled`` always propagates with the
        last file fully committed and nothing half-written.
        """
        t0 = time.perf_counter()
        self._check_cancel()  # before the (irreversible) full-rebuild wipe
        if full_rebuild:
            with self._conn:
                self._conn.executemany("DELETE FROM files WHERE env=?", [(env,) for env in envs])

        plan = self.plan(envs)
        n = len(plan.to_scan)
        self._sink(IndexStarted(n))
        for i, f in enumerate(plan.to_scan, start=1):  # i is 1-based: "i/n" reads naturally in the UI
            self._check_cancel()
            n_entries = self._index_file(f)
            self._sink(IndexFileScanned(f.path, n_entries, i, n))

        if plan.to_remove:
            with self._conn:
                self._conn.executemany("DELETE FROM files WHERE id=?", [(fid,) for fid in plan.to_remove])
        if n > ANALYZE_THRESHOLD:
            self._conn.execute("ANALYZE")
            self._conn.commit()

        stats = IndexStats(scanned=n, removed=len(plan.to_remove), seconds=time.perf_counter() - t0)
        self._sink(IndexFinished(stats.scanned, stats.removed, stats.seconds))
        return stats

    def rescan_file(self, env: str, day: date) -> int:
        """Re-index one day unconditionally (self-heal after ``IndexStale``);
        returns the number of entries found.

        A vanished file is one of the documented ``IndexStale`` triggers, so
        it is handled here too: its rows are dropped and 0 is returned.
        """
        path = local_path(self._root, env, day)
        try:
            st = path.stat()
        except FileNotFoundError:
            with self._conn:
                self._conn.execute("DELETE FROM files WHERE env=? AND day=?", (env, day.isoformat()))
            return 0
        return self._index_file(LocalDailyFile(env, day, path, st.st_size, st.st_mtime_ns))

    # ---------------------------------------------------------- internal ---

    def _check_cancel(self) -> None:
        if self._cancel is not None:
            self._cancel.check()

    def _index_file(self, f: LocalDailyFile) -> int:
        """Scan ``f`` and replace its rows in one transaction."""
        entries, stats = scan_daily_file(f.path, parse_json=self._parse_json, cancel=self._cancel)
        day = f.day.isoformat()
        conn = self._conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("DELETE FROM files WHERE env=? AND day=?", (f.env, day))  # cascades to entries/documents
            cur = conn.execute(_INSERT_FILE, (
                f.env, day, relative_path(f.env, f.day), f.size, f.mtime_ns,
                stats.n_entries, stats.n_orphans,
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ))
            file_id = cur.lastrowid
            conn.executemany(_INSERT_ENTRY, [_entry_row(file_id, f.env, day, e) for e in entries])
            # executemany yields no ids: map seq -> id back from the table.
            id_by_seq = {
                row["seq"]: row["id"]
                for row in conn.execute("SELECT id, seq FROM entries WHERE file_id=?", (file_id,))
            }
            conn.executemany(_INSERT_DOCUMENT, [
                (id_by_seq[e.seq], pos, key)
                for e in entries
                for pos, key in enumerate(e.doc_keys)
            ])
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        return stats.n_entries
