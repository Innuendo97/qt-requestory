"""Blocks from positioned words (spec §4.2 step 6): the units alignment pairs.

PDF words (extract_pdf, reading order) are grouped per page:

* **lines** — words whose bottoms (baselines) lie within half a line height
  of their nearest neighbour's in the line, left to right (a glyph drawn a
  little higher, from a fallback font, stays on its line even when the
  other column's baselines fall in between);
* **title** — the words the zone stage marked ``titolo`` are read first on
  their page, as their own lines: a title with a hole in it never joins a
  column below it (phase 2.5);
* **columns** — ``compare.columns``: page-wide corridors measured on the
  whole page first (phase 2.5, spec §3.6), else the local rule of phase 2;
  each column read top to bottom, left column first. The corridors can be
  given (``columns``: the structure borrowed from the other side of a
  comparison, :func:`page_columns`, :func:`fits`);
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

import bisect
import re
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from qtrequestory.officina.compare.columns import (
    COLUMN_MIN_LINES, CORRIDOR_CHARS, CROSSING, Interval, Line, both_sides, column_streams, crosses, page_corridors,
)
from qtrequestory.officina.compare.model import Block, Word
from qtrequestory.officina.compare.normalise import CHECK_OFF, CHECK_ON, units

__all__ = ["COLUMN_MIN_LINES", "CORRIDOR_CHARS", "CROSSING", "PARAGRAPH_GAP", "Columns", "Layout", "content_keys",
           "fits", "is_form_row", "layout", "make_blocks", "page_columns"]

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

_Line = Line
_Interval = Interval
#: Per page: the page-wide corridors and the number of lines they were measured on.
Columns = dict[int, tuple[list[_Interval], int]]


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


@dataclass(frozen=True)
class Layout:
    """One side's words as lines, measured once: per page, the title's lines
    and the other lines (each top to bottom), and the median character width."""

    pages: dict[int, tuple[list[_Line], list[_Line]]]
    char: float


def layout(words: Sequence[Word]) -> Layout:
    """The lines of ``words``, per page (:class:`Layout`)."""
    pages: dict[int, tuple[list[_Line], list[_Line]]] = {}
    for page, members in sorted(_by_page(words).items()):
        title = [w for w in members if w.zone == "titolo"]
        rest = [w for w in members if w.zone != "titolo"]
        pages[page] = (_lines(title) if title else [], _lines(rest) if rest else [])
    return Layout(pages, _char(words))


def make_blocks(words: Sequence[Word], columns: Mapping[int, Sequence[_Interval]] | None = None, *,
                lines: Layout | None = None) -> list[Block]:
    """The blocks of a PDF's words, in reading order, ids 0..n-1.
    ``columns`` gives the page-wide corridors of some pages (borrowed from
    the other side: :func:`page_columns`); the other pages measure their own.
    ``lines``: the :func:`layout` of ``words`` when the caller already has it."""
    if not words:
        return []
    lay = lines if lines is not None else layout(words)
    streams: list[tuple[int, list[_Line]]] = []   # (page, lines of one column)
    for page, (title, rest) in lay.pages.items():
        if title:
            streams.append((page, title))
        given = columns.get(page) if columns is not None else None
        streams += [(page, s) for s in column_streams(rest, lay.char, given)]
    heights = [_bottom(line) - _top(line) for _, s in streams for line in s]
    pitches = [_bottom(b) - _bottom(a) for _, s in streams for a, b in zip(s, s[1:])]
    reference = _median(pitches)
    height = _median(heights)
    if height > 0 and (reference <= 0 or reference > _PITCH_PER_HEIGHT * height):
        reference = _PITCH_PER_HEIGHT * height
    blocks: list[Block] = []
    for page, stream in streams:
        for kind, group in _paragraphs(stream, reference, lay.char):
            blocks.append(Block(len(blocks), tuple(w for line in group for w in line), page, kind))
    return blocks


def page_columns(lay: Layout) -> Columns:
    """Per page, the page-wide corridors of a side's :func:`layout` (not the
    title) and the number of lines measured: what a comparison borrows from
    the side with more lines (spec §3.6)."""
    return {page: (page_corridors(rest, lay.char), len(rest)) for page, (_, rest) in lay.pages.items()}


def fits(lay: Layout, page: int, corridors: Sequence[_Interval]) -> bool:
    """Whether borrowed ``corridors`` hold on the ``page`` of a side's
    :func:`layout`: few lines cross them and there are words on both sides."""
    lines = lay.pages.get(page, ([], []))[1]
    if not lines or not corridors:
        return False
    width = CORRIDOR_CHARS * lay.char
    crossing = sum(1 for line in lines if crosses(line, corridors, width))
    return crossing <= CROSSING * len(lines) and all(both_sides(lines, g) for g in corridors)


def _by_page(words: Sequence[Word]) -> dict[int, list[Word]]:
    pages: dict[int, list[Word]] = {}
    for word in words:
        pages.setdefault(word.page, []).append(word)
    return pages


def _char(words: Sequence[Word]) -> float:
    return _median([(w.x1 - w.x0) / len(w.text) for w in words if w.text and w.x1 > w.x0])


# ------------------------------------------------------------------ lines ---

def _lines(words: list[Word]) -> list[_Line]:
    """Words of one page grouped on their bottom, top to bottom: a word
    joins the current line when its bottom is within half a height of the
    bottom of its NEAREST word in that line (horizontally) — the lines of
    two columns with other baselines never pull a word off its own line."""
    lines: list[_Line] = []
    xs: list[float] = []            # the current line's x0, sorted; ``placed`` its words in that order
    placed: list[Word] = []
    for word in sorted(words, key=lambda w: (w.y1, w.x0)):
        if lines:
            k = bisect.bisect_left(xs, word.x0)
            near = placed[k - 1] if k else placed[0]
            if 0 < k < len(placed) and placed[k].x0 - word.x1 < word.x0 - near.x1:
                near = placed[k]      # the word to the right is nearer than the one to the left
            if word.y1 - near.y1 <= 0.5 * max(word.y1 - word.y0, near.y1 - near.y0):
                lines[-1].append(word)
                xs.insert(k, word.x0)
                placed.insert(k, word)
                continue
        lines.append([word])
        xs, placed = [word.x0], [word]
    return [sorted(line, key=lambda w: (w.x0, w.x1)) for line in lines]


def _top(line: _Line) -> float:
    return min(w.y0 for w in line)


def _bottom(line: _Line) -> float:
    return max(w.y1 for w in line)


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
