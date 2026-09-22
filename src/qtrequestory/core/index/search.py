"""Query the index and read request bodies straight from the mirrored files.

Search only ever touches SQLite; ``read_body`` then seeks to the stored byte
offsets. Because the daily file may have been re-downloaded since it was
indexed, ``read_body`` first re-reads the header line at ``header_offset``
and refuses (``IndexStale``) if it is not the entry it expects — the caller
then re-indexes that day with ``IndexBuilder.rescan_file`` and retries.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

from qtrequestory.core.extract import output_name

KeyMode = Literal["exact", "prefix", "contains"]

_LIKE_ESCAPE = "\\"


@dataclass(frozen=True)
class SearchQuery:
    env: str
    fdi_prefix: str | None = None
    template_key: str | None = None
    key_mode: KeyMode = "exact"
    day_from: date | None = None
    day_to: date | None = None
    limit: int = 1000


@dataclass(frozen=True)
class SearchHit:
    entry_id: int
    env: str
    day: date
    rel_path: str
    seq: int
    name: str
    fdi: str | None
    template_key: str
    call_id: str | None
    well_formed: bool
    request_date: str | None
    ndocs: int | None
    dossier_number: str | None
    header_offset: int
    body_offset: int
    body_len: int
    json_ok: bool
    file_path: Path  # absolute: root / rel_path


class IndexStale(Exception):
    """The file behind a hit no longer matches the index; rescan ``(env, day)``."""

    def __init__(self, env: str, day: date) -> None:
        super().__init__(f"index stale for {env} {day.isoformat()}")
        self.env = env
        self.day = day


@dataclass(frozen=True)
class Coverage:
    first_day: date
    last_day: date
    n_files: int
    n_entries: int


# ------------------------------------------------------------------ helpers ---

def _clean(value: str | None) -> str | None:
    """Treat blank input from a text field as "not given"."""
    if value is None:
        return None
    value = value.strip()
    return value or None


def _fdi_range(prefix: str) -> tuple[str, str]:
    """Bounds for ``fdi >= lo AND fdi < hi``: a range scan uses ``ix_entries_fdi``,
    whereas ``LIKE`` would not."""
    lo = prefix.lower()
    hi = lo[:-1] + chr(ord(lo[-1]) + 1)
    return lo, hi


def _like_escape(text: str) -> str:
    return (
        text.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2)
        .replace("%", _LIKE_ESCAPE + "%")
        .replace("_", _LIKE_ESCAPE + "_")
    )


def _key_clause(key: str, mode: KeyMode, column: str = "template_key") -> tuple[str, list[object]]:
    if mode == "exact":
        return f"{column} = ?", [key]  # NOCASE collation on the column
    if mode == "prefix":
        pattern = _like_escape(key) + "%"
    elif mode == "contains":
        pattern = "%" + _like_escape(key) + "%"
    else:
        raise ValueError(f"unknown key_mode {mode!r}")
    return f"{column} LIKE ? ESCAPE '{_LIKE_ESCAPE}'", [pattern]


def _hit(row: sqlite3.Row, root: Path) -> SearchHit:
    return SearchHit(
        entry_id=row["id"],
        env=row["env"],
        day=date.fromisoformat(row["day"]),
        rel_path=row["rel_path"],
        seq=row["seq"],
        name=row["name"],
        fdi=row["fdi"],
        template_key=row["template_key"],
        call_id=row["call_id"],
        well_formed=bool(row["well_formed"]),
        request_date=row["request_date"],
        ndocs=row["ndocs"],
        dossier_number=row["dossier_number"],
        header_offset=row["header_offset"],
        body_offset=row["body_offset"],
        body_len=row["body_len"],
        json_ok=bool(row["json_ok"]),
        file_path=root / row["rel_path"],
    )


# ------------------------------------------------------------------- search ---

def search(conn: sqlite3.Connection, root: Path, q: SearchQuery) -> list[SearchHit]:
    """Run ``q``; at least one of ``fdi_prefix`` / ``template_key`` is required
    (an unbounded query would return the whole index)."""
    fdi_prefix = _clean(q.fdi_prefix)
    template_key = _clean(q.template_key)
    if fdi_prefix is None and template_key is None:
        raise ValueError("search needs an FDI prefix or a template key")

    where = ["e.env = ?"]
    params: list[object] = [q.env]
    if fdi_prefix is not None:
        lo, hi = _fdi_range(fdi_prefix)
        where.append("e.fdi >= ? AND e.fdi < ?")
        params += [lo, hi]
    if template_key is not None:
        clause, extra = _key_clause(template_key, q.key_mode, "e.template_key")
        where.append(clause)
        params += extra
    if q.day_from is not None:
        where.append("e.day >= ?")
        params.append(q.day_from.isoformat())
    if q.day_to is not None:
        where.append("e.day <= ?")
        params.append(q.day_to.isoformat())
    params.append(q.limit)

    sql = (
        "SELECT e.id, e.env, e.day, f.rel_path, e.seq, e.name, e.fdi, e.template_key, e.call_id, "
        "e.well_formed, e.request_date, e.ndocs, e.dossier_number, e.header_offset, e.body_offset, "
        "e.body_len, e.json_ok "
        "FROM entries e JOIN files f ON f.id = e.file_id "
        f"WHERE {' AND '.join(where)} "
        "ORDER BY e.day DESC, (e.request_date IS NULL), e.request_date DESC, e.seq DESC LIMIT ?"
    )
    root = Path(root)
    return [_hit(row, root) for row in conn.execute(sql, params)]


# ---------------------------------------------------------------- read_body ---

def read_body(hit: SearchHit) -> bytes:
    """Return the exact body bytes of ``hit`` (terminator excluded).

    Raises ``IndexStale`` if the file is gone or the header line at
    ``header_offset`` is not ``### <name>.json`` (file changed since indexing).
    """
    expected = b"### " + hit.name.encode("utf-8") + b".json"
    try:
        with hit.file_path.open("rb") as f:
            f.seek(hit.header_offset)
            header = f.readline().rstrip(b"\r\n")
            if header != expected:
                raise IndexStale(hit.env, hit.day)
            f.seek(hit.body_offset)
            body = f.read(hit.body_len)
    except FileNotFoundError:
        raise IndexStale(hit.env, hit.day) from None
    if len(body) != hit.body_len:  # truncated file
        raise IndexStale(hit.env, hit.day)
    return body


def output_name_for(hit: SearchHit) -> str:
    """``<YYYYMMDD>_<fdi|nofdi>_<TEMPLATE_KEY>.json``."""
    return output_name(hit.day, hit.fdi, hit.template_key)


def output_name_with_id(hit: SearchHit) -> str:
    """Same, with ``_<call_id>`` appended (collision fallback)."""
    return output_name(hit.day, hit.fdi, hit.template_key, hit.call_id)


# ---------------------------------------------------------- coverage/pickers ---

def coverage(conn: sqlite3.Connection, env: str) -> Coverage | None:
    row = conn.execute(
        "SELECT MIN(day), MAX(day), COUNT(*), COALESCE(SUM(n_entries), 0) FROM files WHERE env=?", (env,)
    ).fetchone()
    if not row[2]:
        return None
    return Coverage(date.fromisoformat(row[0]), date.fromisoformat(row[1]), row[2], row[3])


def list_template_keys(conn: sqlite3.Connection, env: str, prefix: str = "", limit: int = 500) -> list[str]:
    """Distinct principal template keys of ``env``, most recently seen first,
    then most frequent, then alphabetical — the order a picker wants."""
    where = ["env = ?"]
    params: list[object] = [env]
    if prefix:
        clause, extra = _key_clause(prefix, "prefix")
        where.append(clause)
        params += extra
    params.append(limit)
    rows = conn.execute(
        "SELECT template_key FROM entries "
        f"WHERE {' AND '.join(where)} "
        "GROUP BY template_key ORDER BY MAX(day) DESC, COUNT(*) DESC, template_key LIMIT ?",
        params,
    )
    return [row[0] for row in rows]


def list_fdi_prefix(conn: sqlite3.Connection, env: str, prefix: str, limit: int = 20) -> list[str]:
    """Distinct FDIs of ``env`` starting with ``prefix`` (case-insensitive), sorted."""
    where = ["env = ?", "fdi IS NOT NULL"]
    params: list[object] = [env]
    if prefix:
        lo, hi = _fdi_range(prefix)
        where.append("fdi >= ? AND fdi < ?")
        params += [lo, hi]
    params.append(limit)
    rows = conn.execute(
        f"SELECT DISTINCT fdi FROM entries WHERE {' AND '.join(where)} ORDER BY fdi LIMIT ?", params
    )
    return [row[0] for row in rows]
