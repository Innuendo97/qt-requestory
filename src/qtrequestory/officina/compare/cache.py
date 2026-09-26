"""The extraction cache on disk (spec §4.3).

One file per extracted document, keyed by the SHA-256 of the file:
``<case>\\cache\\extract-<sha>.json``. It holds the words (with boxes, size
and bold), the page sizes and ``has_text`` — everything an extraction gives —
plus the :data:`FORMAT` it was written in.

A cache is only ever a shortcut: a missing file, another format version, a
different sha inside, or anything that is not exactly the expected shape (a
corrupt or hand-edited file) is a miss (``None``), never an error. The caller
then extracts again and :func:`store` silently writes over it. Writes are
atomic (unique temporary file + replace), so a crash or a second writer never
leaves half a file behind, and best-effort: a cache that cannot be written
(read-only folder, a folder in the file's place) is logged at debug level —
path and error only, never the content — and the comparison goes on.

Stdlib only; no Qt, no pypdfium2.
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from pathlib import Path

from qtrequestory.officina.compare.extract_pdf import DocText, Word
from qtrequestory.officina.model_io import write_bytes_atomic

__all__ = ["FORMAT", "load", "path_for", "store"]

log = logging.getLogger(__name__)

#: Bump whenever what is stored (or how a word is extracted) changes: every
#: older file then reads as a miss and is regenerated.
FORMAT = 1
_SHA = re.compile(r"^[0-9a-f]{8,128}$")


def path_for(folder: Path, sha: str) -> Path:
    """The cache file of the document with hash ``sha`` in case ``folder``.
    ``ValueError`` for a sha that is not lowercase hex (never a path)."""
    if not isinstance(sha, str) or not _SHA.match(sha):
        raise ValueError(f"hash non valido per la cache: {sha!r}")
    return Path(folder) / "cache" / f"extract-{sha}.json"


def load(folder: Path, sha: str) -> DocText | None:
    """The extraction stored for ``sha`` in case ``folder``; None on a miss
    (no file, another format, unreadable or malformed content — deep nesting
    included). Never raises for the content; never creates anything."""
    try:
        return _parse(json.loads(path_for(folder, sha).read_bytes().decode("utf-8")), sha)
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        return None


def _parse(raw: object, sha: str) -> DocText | None:
    if not isinstance(raw, dict) or raw.get("format") != FORMAT or raw.get("sha") != sha:
        return None
    has_text, sizes, words = raw.get("has_text"), raw.get("page_sizes"), raw.get("words")
    if type(has_text) is not bool or not isinstance(sizes, list) or not isinstance(words, list):
        return None
    page_sizes = [_size(item) for item in sizes]
    parsed = [_word(item) for item in words]
    if None in page_sizes or None in parsed:
        return None
    return DocText(parsed, page_sizes, has_text)


def store(folder: Path, sha: str, words: Sequence[Word], page_sizes: Sequence[tuple[float, float]],
          has_text: bool) -> bool:
    """Write the extraction of ``sha`` into case ``folder`` (atomic; creates
    ``cache\\`` as needed, replaces any previous file). False when it could
    not be written (logged at debug level; the cache is only a shortcut).
    ``ValueError`` for an invalid ``sha`` (a caller bug, not a disk state)."""
    path = path_for(folder, sha)
    raw = {
        "format": FORMAT,
        "sha": sha,
        "has_text": bool(has_text),
        "page_sizes": [[float(w), float(h)] for w, h in page_sizes],
        "words": [[w.text, w.page, w.x0, w.y0, w.x1, w.y1, w.size, w.bold] for w in words],
    }
    data = json.dumps(raw, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    try:
        write_bytes_atomic(path, data)
    except OSError as exc:
        log.debug("cache di estrazione non scritta (%s): %s", type(exc).__name__, path)
        return False
    return True


def _number(value: object) -> float | None:
    return float(value) if type(value) in (int, float) else None


def _size(item: object) -> tuple[float, float] | None:
    if not isinstance(item, list) or len(item) != 2:
        return None
    width, height = _number(item[0]), _number(item[1])
    return None if width is None or height is None else (width, height)


def _word(item: object) -> Word | None:
    if not isinstance(item, list) or len(item) != 8:
        return None
    text, page, *numbers, bold = item
    values = [_number(n) for n in numbers]
    if not isinstance(text, str) or type(page) is not int or type(bold) is not bool or None in values:
        return None
    return Word(text, page, *values, bold)
