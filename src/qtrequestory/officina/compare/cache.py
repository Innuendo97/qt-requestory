"""The extraction cache on disk (spec §4.3).

One file per extracted document, keyed by the SHA-256 of the file:
``<case>\\cache\\extract-<sha>.json``. It holds the words (with boxes, size
and bold), the page sizes and ``has_text``, and (format 2, phase 2.5) the
angles of the rotated words, the invisible words, each page's graphics and
(format 3) the words drawn in a light colour —
everything an extraction gives — plus the :data:`FORMAT` it was written in.

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
from collections.abc import Collection, Sequence
from pathlib import Path

from qtrequestory.officina.compare.extract_pdf import DocText, Word
from qtrequestory.officina.compare.graphics import PageGraphics, PathShape
from qtrequestory.officina.model_io import write_bytes_atomic

__all__ = ["FORMAT", "load", "path_for", "store"]

log = logging.getLogger(__name__)

#: Bump whenever what is stored (or how a word is extracted) changes: every
#: older file then reads as a miss and is regenerated. 2: phase 2.5 (ink
#: test, rotated words, invisible channel, page graphics); 3: the words
#: drawn in a light colour (review A2 I1).
FORMAT = 3
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
    rotated, invisible, graphics = raw.get("rotated"), raw.get("invisible"), raw.get("graphics")
    if not isinstance(rotated, list) or not isinstance(invisible, list) or not isinstance(graphics, list):
        return None
    page_sizes = [_size(item) for item in sizes]
    parsed = [_word(item) for item in words]
    hidden = [_word(item) for item in invisible]
    pages = [_graphics(item) for item in graphics]
    angles = _angles(rotated, len(parsed))
    light = _indices(raw.get("light"), len(parsed))
    if None in page_sizes or None in parsed or None in hidden or None in pages or angles is None or light is None:
        return None
    if pages and len(pages) != len(page_sizes):
        return None
    return DocText(parsed, page_sizes, has_text, angles, hidden, pages, light)


def store(folder: Path, sha: str, words: Sequence[Word], page_sizes: Sequence[tuple[float, float]],
          has_text: bool, *, rotated: dict[int, int] | None = None, invisible: Sequence[Word] = (),
          graphics: Sequence[PageGraphics] = (), light: Collection[int] = ()) -> bool:
    """Write the extraction of ``sha`` into case ``folder`` (atomic; creates
    ``cache\\`` as needed, replaces any previous file). False when it could
    not be written (logged at debug level; the cache is only a shortcut).
    ``ValueError`` for an invalid ``sha`` (a caller bug, not a disk state).
    ``graphics`` is empty (none recorded) or has one entry per page."""
    path = path_for(folder, sha)
    if graphics and len(graphics) != len(page_sizes):
        raise ValueError("graphics: one entry per page expected")
    raw = {
        "format": FORMAT,
        "sha": sha,
        "has_text": bool(has_text),
        "page_sizes": [[float(w), float(h)] for w, h in page_sizes],
        "words": [_word_raw(w) for w in words],
        "rotated": [[int(i), int(a)] for i, a in sorted((rotated or {}).items())],
        "invisible": [_word_raw(w) for w in invisible],
        "light": sorted(int(i) for i in light),
        "graphics": [{"paths": [[*map(float, p.box), float(p.stroke_width), _rgba_raw(p.fill),
                                 _rgba_raw(p.stroke), int(p.segments)] for p in g.paths],
                      "images": [[*map(float, box)] for box in g.images]} for g in graphics],
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


def _word_raw(w: Word) -> list:
    return [w.text, w.page, w.x0, w.y0, w.x1, w.y1, w.size, w.bold]


def _rgba_raw(colour: tuple[int, int, int, int] | None) -> list[int] | None:
    return None if colour is None else [int(c) for c in colour]


def _angles(items: list, count: int) -> dict[int, int] | None:
    """``[[word index, angle], ...]`` -> the map; None for anything else."""
    out: dict[int, int] = {}
    for item in items:
        if (not isinstance(item, list) or len(item) != 2 or type(item[0]) is not int or type(item[1]) is not int
                or not 0 <= item[0] < count or not 0 < item[1] < 360 or item[0] in out):
            return None
        out[item[0]] = item[1]
    return out


def _indices(items: object, count: int) -> set[int] | None:
    """``[word index, ...]`` -> the set; None for anything else."""
    if not isinstance(items, list):
        return None
    if not all(type(i) is int and 0 <= i < count for i in items) or len(set(items)) != len(items):
        return None
    return set(items)


def _box(item: object) -> tuple[float, float, float, float] | None:
    if not isinstance(item, list) or len(item) != 4:
        return None
    values = [_number(n) for n in item]
    return None if None in values else tuple(values)


def _rgba(item: object) -> tuple[int, int, int, int] | None | bool:
    """An RGBA colour, None for "none" — or False when malformed."""
    if item is None:
        return None
    if (not isinstance(item, list) or len(item) != 4
            or not all(type(c) is int and 0 <= c <= 255 for c in item)):
        return False
    return tuple(item)


def _graphics(item: object) -> PageGraphics | None:
    if not isinstance(item, dict) or not isinstance(item.get("paths"), list) or not isinstance(item.get("images"), list):
        return None
    paths = []
    for raw in item["paths"]:
        if not isinstance(raw, list) or len(raw) != 8:
            return None
        box, width = _box(raw[:4]), _number(raw[4])
        fill, stroke, segments = _rgba(raw[5]), _rgba(raw[6]), raw[7]
        if box is None or width is None or fill is False or stroke is False or type(segments) is not int:
            return None
        paths.append(PathShape(box, width, fill, stroke, segments))
    images = [_box(raw) for raw in item["images"]]
    if None in images:
        return None
    return PageGraphics(tuple(paths), tuple(images))
