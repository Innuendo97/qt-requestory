"""Blocks from positioned words (spec §4.2 step 6): the units alignment pairs.

PDF words (extract_pdf, reading order) are grouped per page:

* **lines** — words whose bottoms (baselines) lie within half a line height
  of each other, left to right;
* **columns** — a vertical corridor at least :data:`CORRIDOR_CHARS` median
  character widths wide, free of words on at least :data:`COLUMN_MIN_LINES`
  consecutive lines (and with words on both sides), splits those lines into
  columns; each column is read top to bottom, left column first. A single
  wide gap (``Luogo e data        Firma``) is not a column;
* **paragraphs** — inside one column, a new block starts when the pitch from
  the previous line exceeds :data:`PARAGRAPH_GAP` times the reference pitch,
  when the indent changes (a first-line indent opens a paragraph, a hanging
  indent does not), or when the font size changes;
* **form rows** — a line holding a slot leader (a run of ≥4 ``.``/``_``/``…``)
  or a checkbox (``☐``/``☒`` after normalisation) is a block of its own, kind
  ``riga_modulo``, so the rows of a form stay separate units.

Content is judged on normalised keys (``normalise.units``), the same the diff
uses. HTML blocks do not come from here: the HTML extractor makes them.

Deterministic and pure; stdlib only, no Qt, no pypdfium2.
"""
from __future__ import annotations

import re
import statistics
from collections.abc import Sequence

from qtrequestory.officina.compare.model import Block, Word
from qtrequestory.officina.compare.normalise import CHECK_OFF, CHECK_ON, units

__all__ = ["COLUMN_MIN_LINES", "CORRIDOR_CHARS", "PARAGRAPH_GAP", "content_keys", "is_form_row", "make_blocks"]

#: A column corridor is at least this many median character widths wide…
CORRIDOR_CHARS = 3.0
#: …and empty on at least this many consecutive lines.
COLUMN_MIN_LINES = 3
#: A pitch above this multiple of the reference pitch starts a paragraph.
PARAGRAPH_GAP = 1.5
#: An indent change wider than this many character widths starts a paragraph.
_INDENT_CHARS = 2.0
#: A relative font size change above this starts a paragraph.
_SIZE_CHANGE = 0.15
#: The reference pitch never exceeds this multiple of the median line height
#: (so a document made only of one-line paragraphs still splits).
_PITCH_PER_HEIGHT = 1.25

_LEADER = re.compile(r"[._]{4,}")

_Line = list[Word]
_Interval = tuple[float, float]


def is_form_row(words: Sequence[Word]) -> bool:
    """Whether a line holds a slot leader or a checkbox (normalised keys)."""
    keys, _ = units(words)
    return any(_LEADER.search(k) or CHECK_OFF in k or CHECK_ON in k for k in keys)


def content_keys(words: Sequence[Word]) -> list[str]:
    """The keys alignment compares a block on: ``normalise.units`` keys with
    slot leaders removed. A leader glued to its label ("Località..........")
    leaves the label; a key that is only a leader disappears — so an empty
    form row and the same row filled in share their labels."""
    out: list[str] = []
    for key in units(words)[0]:
        out += [part for part in _LEADER.split(key) if part]
    return out


def make_blocks(words: Sequence[Word]) -> list[Block]:
    """The blocks of a PDF's words, in reading order, ids 0..n-1."""
    if not words:
        return []
    pages: dict[int, list[Word]] = {}
    for word in words:
        pages.setdefault(word.page, []).append(word)
    char = _median([(w.x1 - w.x0) / len(w.text) for w in words if w.text and w.x1 > w.x0])
    streams: list[tuple[int, list[_Line]]] = []   # (page, lines of one column)
    for page in sorted(pages):
        streams += [(page, s) for s in _streams(_lines(pages[page]), char)]
    heights = [_bottom(line) - _top(line) for _, s in streams for line in s]
    pitches = [_bottom(b) - _bottom(a) for _, s in streams for a, b in zip(s, s[1:])]
    reference = _median(pitches)
    height = _median(heights)
    if height > 0 and (reference <= 0 or reference > _PITCH_PER_HEIGHT * height):
        reference = _PITCH_PER_HEIGHT * height
    blocks: list[Block] = []
    for page, stream in streams:
        for kind, group in _paragraphs(stream, reference, char):
            blocks.append(Block(len(blocks), tuple(w for line in group for w in line), page, kind))
    return blocks


# ------------------------------------------------------------------ lines ---

def _lines(words: list[Word]) -> list[_Line]:
    """Words of one page grouped on their bottom (± half a height), top to bottom."""
    lines: list[_Line] = []
    anchor = 0.0
    for word in sorted(words, key=lambda w: (w.y1, w.x0)):
        tolerance = 0.5 * max(word.y1 - word.y0, (lines[-1][0].y1 - lines[-1][0].y0) if lines else 0.0)
        if lines and word.y1 - anchor <= tolerance:
            lines[-1].append(word)
            continue
        lines.append([word])
        anchor = word.y1
    return [sorted(line, key=lambda w: (w.x0, w.x1)) for line in lines]


def _top(line: _Line) -> float:
    return min(w.y0 for w in line)


def _bottom(line: _Line) -> float:
    return max(w.y1 for w in line)


# ---------------------------------------------------------------- columns ---

def _streams(lines: list[_Line], char: float) -> list[list[_Line]]:
    """The page's lines cut into column streams, in reading order."""
    if not lines or char <= 0:
        return [lines] if lines else []
    left = min(w.x0 for line in lines for w in line)
    right = max(w.x1 for line in lines for w in line)
    width = CORRIDOR_CHARS * char
    free = [_free(line, left, right, width) for line in lines]
    streams: list[list[_Line]] = []
    single: list[_Line] = []
    i = 0
    while i < len(lines):
        corridors = [g for g in free[i] if left < g[0] and g[1] < right]  # interior on the first line
        j = i + 1
        while j < len(lines) and corridors:
            narrowed = _intersect(corridors, free[j], width)
            if not narrowed:
                break
            corridors, j = narrowed, j + 1
        corridors = [g for g in corridors if _both_sides(lines[i:j], g)]
        if j - i >= COLUMN_MIN_LINES and corridors:
            if single:
                streams.append(single)
                single = []
            streams += _split(lines[i:j], corridors)
            i = j
        else:
            single.append(lines[i])
            i += 1
    if single:
        streams.append(single)
    return streams


def _free(line: _Line, left: float, right: float, width: float) -> list[_Interval]:
    """Horizontal intervals of the page's text width that the line leaves empty."""
    out: list[_Interval] = []
    cursor = left
    for word in line:
        if word.x0 - cursor >= width:
            out.append((cursor, word.x0))
        cursor = max(cursor, word.x1)
    if right - cursor >= width:
        out.append((cursor, right))
    return out


def _intersect(a: list[_Interval], b: list[_Interval], width: float) -> list[_Interval]:
    out = []
    for a0, a1 in a:
        for b0, b1 in b:
            lo, hi = max(a0, b0), min(a1, b1)
            if hi - lo >= width:
                out.append((lo, hi))
    return out


def _both_sides(lines: list[_Line], corridor: _Interval) -> bool:
    words = [w for line in lines for w in line]
    return any(w.x1 <= corridor[0] for w in words) and any(w.x0 >= corridor[1] for w in words)


def _split(lines: list[_Line], corridors: list[_Interval]) -> list[list[_Line]]:
    """One stream per column (left to right); empty fragments are skipped."""
    cuts = [(g0 + g1) / 2 for g0, g1 in corridors]
    columns: list[list[_Line]] = [[] for _ in range(len(cuts) + 1)]
    for line in lines:
        parts: list[_Line] = [[] for _ in columns]
        for word in line:
            parts[sum(1 for c in cuts if (word.x0 + word.x1) / 2 > c)].append(word)
        for column, part in zip(columns, parts, strict=True):
            if part:
                column.append(part)
    return [c for c in columns if c]


# ------------------------------------------------------------- paragraphs ---

def _paragraphs(stream: list[_Line], reference: float, char: float) -> list[tuple[str, list[_Line]]]:
    out: list[tuple[str, list[_Line]]] = []
    current: list[_Line] = []
    for line in stream:
        if is_form_row(line):
            if current:
                out.append(("paragrafo", current))
                current = []
            out.append(("riga_modulo", [line]))
            continue
        if current and _breaks(current, line, reference, char):
            out.append(("paragrafo", current))
            current = []
        current.append(line)
    if current:
        out.append(("paragrafo", current))
    return out


def _breaks(paragraph: list[_Line], line: _Line, reference: float, char: float) -> bool:
    previous = paragraph[-1]
    if reference > 0 and _bottom(line) - _bottom(previous) > PARAGRAPH_GAP * reference:
        return True
    # The first line may be indented (first-line indent) or outdented
    # (hanging indent) against the second; from the second line on, a change
    # of left edge starts a new paragraph.
    if len(paragraph) >= 2 and abs(line[0].x0 - previous[0].x0) > _INDENT_CHARS * char:
        return True
    before, after = _size(previous), _size(line)
    return bool(before and after and abs(after - before) > _SIZE_CHANGE * max(before, after))


def _size(line: _Line) -> float:
    return _median([w.size for w in line if w.size > 0])


def _median(values: list[float]) -> float:
    return float(statistics.median(values)) if values else 0.0
