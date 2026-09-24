"""Scan one daily file into ``ScannedEntry`` records with exact byte offsets.

The daily format is ``### <name>.json`` header lines strictly alternating with
one-line JSON bodies (CRLF or LF). The index stores *byte* offsets so that
``read_body`` can ``seek`` straight to a body without re-parsing 60 MB files;
that only works if the file is read in binary mode and the position is taken
with ``f.tell()`` before every ``readline()`` (text mode would translate
newlines and ``for line in f`` disables ``tell``).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from qtrequestory.core.daily import EntryName, parse_entry_name
from qtrequestory.core.events import CancelToken

HEADER_RE = re.compile(rb"^### (?P<name>.+?)\.json[ \t]*\r?\n?$")
# Fallback when json.loads fails: the first "requestDate" is always the dossier one.
REQDATE_RE = re.compile(rb'"requestDate":"([^"]*)"')

CANCEL_EVERY = 50
BOM = b"\xef\xbb\xbf"
#: What counts as a blank line (F6): skipped, neither a body nor an orphan.
#: ``read_body`` accepts exactly these bytes between a header and its body.
BLANKS = b" \t\r\n"


@dataclass(frozen=True)
class ScannedEntry:
    seq: int
    name: EntryName
    header_offset: int
    header_len: int  # raw bytes of the header line, terminator excluded (trailing blanks included)
    body_offset: int
    body_len: int  # bytes of the body line, terminator excluded
    request_date: str | None
    ndocs: int | None
    dossier_id: str | None
    dossier_number: str | None
    doc_keys: tuple[str, ...]
    json_ok: bool


@dataclass
class ScanStats:
    n_entries: int = 0
    n_orphans: int = 0


@dataclass(frozen=True)
class _BodyInfo:
    request_date: str | None = None
    ndocs: int | None = None
    dossier_id: str | None = None
    dossier_number: str | None = None
    doc_keys: tuple[str, ...] = ()
    json_ok: bool = False


def _opt_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _regex_body_info(body: bytes) -> _BodyInfo:
    m = REQDATE_RE.search(body)
    request_date = m.group(1).decode("utf-8", "replace") if m else None
    return _BodyInfo(request_date=request_date)


def _json_body_info(body: bytes) -> _BodyInfo:
    """Full extraction; any decode problem (or a non-object body) degrades to the regex path."""
    try:
        d = json.loads(body)
    except ValueError:  # JSONDecodeError and UnicodeDecodeError
        return _regex_body_info(body)
    if not isinstance(d, dict):
        return _regex_body_info(body)

    documents = d.get("documents") or []
    if not isinstance(documents, list):
        documents = []
    doc_keys: list[str] = []
    for doc in documents:
        template = doc.get("template") if isinstance(doc, dict) else None
        key = template.get("templateKey") if isinstance(template, dict) else None
        if isinstance(key, str):
            doc_keys.append(key)

    dossier = d.get("dossier") or {}
    if not isinstance(dossier, dict):
        dossier = {}
    return _BodyInfo(
        request_date=_opt_str(dossier.get("requestDate")),
        ndocs=len(documents),
        dossier_id=_opt_str(dossier.get("id")),
        dossier_number=_opt_str(dossier.get("number")),
        doc_keys=tuple(doc_keys),
        json_ok=True,
    )


def scan_daily_file(
    path: Path | str,
    *,
    parse_json: bool = True,
    cancel: CancelToken | None = None,
) -> tuple[list[ScannedEntry], ScanStats]:
    """Return every (header, body) pair in ``path`` plus orphan counts.

    A UTF-8 BOM at offset 0 is skipped (the first header then starts at 3)
    and blank lines (only spaces, tabs, CR, LF) are ignored everywhere, so a
    blank line between a header and its body does not separate them.

    Orphan rules: a header immediately followed by another header is an orphan
    header; a non-header line with no pending header is an orphan body. Neither
    produces an entry, both bump ``n_orphans``. With ``parse_json=False`` only
    ``request_date`` is extracted (regex), which is ~6x faster.
    """
    extract = _json_body_info if parse_json else _regex_body_info
    entries: list[ScannedEntry] = []
    stats = ScanStats()
    pending: tuple[bytes, int, int] | None = None  # (name, header_offset, header_len)

    if cancel is not None:
        cancel.check()
    with Path(path).open("rb") as f:
        while True:
            pos = f.tell()
            line = f.readline()
            if not line:
                break
            if pos == 0 and line.startswith(BOM):
                # F6: an editor's BOM. The header starts after it, and the
                # stored offsets say so: read_body seeks to 3, byte-exact.
                pos, line = len(BOM), line[len(BOM):]
            if not line.strip(BLANKS):
                continue  # F6: a blank line is neither a body nor an orphan
            m = HEADER_RE.match(line)
            if m:
                if pending is not None:
                    stats.n_orphans += 1
                pending = (m.group("name"), pos, len(line.rstrip(b"\r\n")))
                continue
            if pending is None:
                stats.n_orphans += 1
                continue
            raw_name, header_offset, header_len = pending
            pending = None
            body = line.rstrip(b"\r\n")
            info = extract(body)
            entries.append(ScannedEntry(
                seq=len(entries),
                # surrogateescape, not "replace": read_body re-encodes the name
                # and must get the header's exact bytes back.
                name=parse_entry_name(raw_name.decode("utf-8", "surrogateescape")),
                header_offset=header_offset,
                header_len=header_len,
                body_offset=pos,
                body_len=len(body),
                request_date=info.request_date,
                ndocs=info.ndocs,
                dossier_id=info.dossier_id,
                dossier_number=info.dossier_number,
                doc_keys=info.doc_keys,
                json_ok=info.json_ok,
            ))
            if cancel is not None and len(entries) % CANCEL_EVERY == 0:
                cancel.check()
    if pending is not None:  # header at EOF with no body
        stats.n_orphans += 1
    stats.n_entries = len(entries)
    return entries, stats
