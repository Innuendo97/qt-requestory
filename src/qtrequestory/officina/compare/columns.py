"""Columns of a PDF page (spec §3.6; used by ``blocks``).

A page's lines (``blocks`` groups the words) are cut into column streams:

* **page-wide corridors** (phase 2.5, research ``fase25-zone-variabili``
  §B.5): an interval of the page's text width that at most :data:`CROSSING`
  of the lines run across, at least :data:`CORRIDOR_CHARS` median character
  widths wide, found from the coverage of the lines (a histogram of where
  text is). It is a column gutter when words lie on both sides of it on at
  least :data:`COLUMN_SHARE` of the lines clear of it (and
  :data:`COLUMN_MIN_LINES`), the line parts right of it start at one x (a
  column edge: the x0 histogram), and the column left of it is text (most of
  its lines run up to the gutter, as justified text does — not the ragged
  cells of a form or a table). Its edges hold on :data:`_HOLD` of the lines,
  so a justified line poking into the gutter narrows nothing and stays in
  its column. A line running across a whole corridor is read on its own; the
  lines between two such lines are split into columns, left first;
* otherwise the **local rule** of phase 2: a corridor free of words on at
  least :data:`COLUMN_MIN_LINES` consecutive lines (with words on both
  sides) splits those lines. A single wide gap (``Luogo e data        Firma``)
  is not a column.

Deterministic and pure; stdlib only, no Qt, no pypdfium2.
"""
from __future__ import annotations

import itertools
from collections.abc import Sequence

from qtrequestory.officina.compare.model import Word

__all__ = ["COLUMN_MIN_LINES", "COLUMN_SHARE", "CORRIDOR_CHARS", "CROSSING", "both_sides", "column_streams", "crosses",
           "page_corridors"]

Line = list[Word]
Interval = tuple[float, float]

#: A column corridor is at least this many median character widths wide…
CORRIDOR_CHARS = 3.0
#: …and empty on at least this many consecutive lines.
COLUMN_MIN_LINES = 3
#: A page-wide corridor is crossed by at most this share of the page's lines.
CROSSING = 0.2
#: …and each side of it holds words on at least this share of the lines clear
#: of it (a text column, not the cells of a table).
COLUMN_SHARE = 0.3
#: A text column's lines end within this share of its width from the gutter.
_FILL = 0.15
#: Where in a corridor the right column begins (share of its width).
_RIGHT_EDGE = 0.75
#: A corridor's edges hold on this share of the lines clear of it.
_HOLD = 0.9
#: The line parts right of a column edge start within this many points.
_EDGE = 2.5
#: At most this many page-wide corridors (three columns).
_MAX_CORRIDORS = 2

def column_streams(lines: list[Line], char: float, given: Sequence[Interval] | None = None) -> list[list[Line]]:
    """The page's lines cut into column streams, in reading order: along
    the page-wide corridors (``given``, else measured), else by the local rule."""
    if not lines or char <= 0:
        return [lines] if lines else []
    corridors = list(given) if given is not None else page_corridors(lines, char)
    if corridors:
        return _banded(lines, corridors, CORRIDOR_CHARS * char)
    left = min(w.x0 for line in lines for w in line)
    right = max(w.x1 for line in lines for w in line)
    width = CORRIDOR_CHARS * char
    free = [_free(line, left, right, width) for line in lines]
    streams: list[list[Line]] = []
    single: list[Line] = []
    i = 0
    while i < len(lines):
        corridors = [g for g in free[i] if left < g[0] and g[1] < right]  # interior on the first line
        j = i + 1
        while j < len(lines) and corridors:
            narrowed = _intersect(corridors, free[j], width)
            if not narrowed:
                break
            corridors, j = narrowed, j + 1
        corridors = [g for g in corridors if both_sides(lines[i:j], g)]
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


def page_corridors(lines: list[Line], char: float) -> list[Interval]:
    """The page-wide column corridors of ``lines`` (module doc), left to right."""
    if len(lines) < 2 * COLUMN_MIN_LINES or char <= 0:
        return []
    width = CORRIDOR_CHARS * char
    left = min(w.x0 for line in lines for w in line)
    right = max(w.x1 for line in lines for w in line)
    runs = [_runs(line, width) for line in lines]
    size = int(right - left) + 1
    steps = [0] * (size + 1)          # a difference array: +1 where a run starts, -1 past its end
    for line_runs in runs:
        for x0, x1 in line_runs:
            steps[max(0, int(x0 - left))] += 1
            steps[min(size, int(x1 - left) + 1)] -= 1
    cover = list(itertools.accumulate(steps[:size]))
    limit = CROSSING * len(lines)
    found: list[Interval] = []
    for b in sorted(_candidates(cover, limit), key=lambda b: (cover[b], abs(b - size / 2))):
        if len(found) == _MAX_CORRIDORS:
            break
        x = left + b + 0.5
        if any(g0 - width <= x <= g1 + width for g0, g1 in found):
            continue
        corridor = _corridor_at(runs, x, left, right)
        if corridor is None or corridor[1] - corridor[0] < width or not left < corridor[0] < corridor[1] < right:
            continue
        if any(corridor[0] < g1 and corridor[1] > g0 for g0, g1 in found):
            continue
        clear = [line for line, line_runs in zip(lines, runs, strict=True) if not _run_across(line_runs, x)]
        least = max(COLUMN_MIN_LINES, int(COLUMN_SHARE * len(clear)))
        if both_sides(clear, corridor, least) and _edge(clear, corridor) and _filled(clear, corridor, left):
            found.append(corridor)
    return sorted(found)


def _candidates(cover: list[int], limit: float) -> list[int]:
    """One bin per maximal run of bins crossed by at most ``limit`` lines,
    away from the text's edges: the run's least crossed bin (the middle one
    on a tie)."""
    out: list[int] = []
    b, size = 0, len(cover)
    while b < size:
        if cover[b] > limit:
            b += 1
            continue
        start = b
        while b < size and cover[b] <= limit:
            b += 1
        if start > 0 and b < size:
            low = min(cover[start:b])
            ties = [k for k in range(start, b) if cover[k] == low]
            out.append(ties[len(ties) // 2])
    return out


def _runs(line: Line, width: float) -> list[Interval]:
    """The line's words merged across gaps narrower than ``width``."""
    out: list[list[float]] = []
    for word in line:
        if out and word.x0 - out[-1][1] < width:
            out[-1][1] = max(out[-1][1], word.x1)
        else:
            out.append([word.x0, word.x1])
    return [(a, b) for a, b in out]


def _run_across(runs: list[Interval], x: float) -> bool:
    return any(x0 <= x <= x1 for x0, x1 in runs)


def _corridor_at(runs: list[list[Interval]], x: float, left: float, right: float) -> Interval | None:
    """The corridor around ``x`` that the lines NOT crossing ``x`` leave
    free: from where their left parts end to where their right parts start,
    on the most lines (:data:`_HOLD` of them) — a justified line poking into
    the gutter narrows no column (it stays in its column: :func:`_crosses`)."""
    ends: list[float] = []
    starts: list[float] = []
    for line_runs in runs:
        if _run_across(line_runs, x):
            continue
        before = [x1 for _, x1 in line_runs if x1 < x]
        after = [x0 for x0, _ in line_runs if x0 > x]
        if before:
            ends.append(max(before))
        if after:
            starts.append(min(after))
    lo = sorted(ends)[int(_HOLD * (len(ends) - 1))] if ends else left
    hi = sorted(starts)[int((1 - _HOLD) * (len(starts) - 1))] if starts else right
    return (lo, hi) if hi > lo else None


def _edge(lines: list[Line], corridor: Interval) -> bool:
    """Whether the line parts right of ``corridor`` start at one x (± :data:`_EDGE`)
    on at least :data:`COLUMN_MIN_LINES` lines: a column's left edge."""
    starts = sorted(x for x in (next((w.x0 for w in line if w.x0 >= corridor[1]), -1.0) for line in lines) if x >= 0)
    best, j = 0, 0
    for i, x in enumerate(starts):
        while starts[j] < x - 2 * _EDGE:
            j += 1
        best = max(best, i - j + 1)
    return best >= COLUMN_MIN_LINES


def _filled(lines: list[Line], corridor: Interval, left: float) -> bool:
    """Whether the column left of ``corridor`` is text: most of its line
    parts run up to the gutter (within :data:`_FILL` of the column's width),
    as in a justified column — not the ragged cells of a form or a table."""
    ends = [max((w.x1 for w in line if w.x1 <= corridor[0]), default=None) for line in lines]
    ends = [x for x in ends if x is not None]
    reach = corridor[0] - _FILL * (corridor[0] - left)
    return bool(ends) and sum(1 for x in ends if x >= reach) >= 0.5 * len(ends)


def crosses(line: Line, corridors: Sequence[Interval], width: float) -> bool:
    """Whether the line runs across a whole corridor (a line only poking
    into it belongs to its column)."""
    return any(x0 <= g0 and x1 >= g1 for x0, x1 in _runs(line, width) for g0, g1 in corridors)


def _banded(lines: list[Line], corridors: list[Interval], width: float) -> list[list[Line]]:
    """Lines crossing a corridor read on their own; the bands between them
    split into columns (:func:`_band`)."""
    streams: list[list[Line]] = []
    band: list[Line] = []
    across: list[Line] = []
    for line in lines:
        if crosses(line, corridors, width):
            if band:
                streams += _band(band, corridors)
                band = []
            across.append(line)
            continue
        if across:
            streams.append(across)
            across = []
        band.append(line)
    if across:
        streams.append(across)
    if band:
        streams += _band(band, corridors)
    return streams


def _band(lines: list[Line], corridors: list[Interval]) -> list[list[Line]]:
    """One band in columns. Its first lines with nothing right of the first
    corridor, above the right column's start, are read on their own first
    (text above the columns that stops short of the gutter): the order is
    the same either way, only the paragraph ends differ."""
    edge = corridors[0][1]
    first = next((k for k, line in enumerate(lines) if any(w.x0 >= edge for w in line)), len(lines))
    head, rest = lines[:first], lines[first:]
    return ([head] if head else []) + (_split(rest, corridors) if rest else [])


def _free(line: Line, left: float, right: float, width: float) -> list[Interval]:
    """Horizontal intervals of the page's text width that the line leaves empty."""
    out: list[Interval] = []
    cursor = left
    for word in line:
        if word.x0 - cursor >= width:
            out.append((cursor, word.x0))
        cursor = max(cursor, word.x1)
    if right - cursor >= width:
        out.append((cursor, right))
    return out


def _intersect(a: list[Interval], b: list[Interval], width: float) -> list[Interval]:
    out = []
    for a0, a1 in a:
        for b0, b1 in b:
            lo, hi = max(a0, b0), min(a1, b1)
            if hi - lo >= width:
                out.append((lo, hi))
    return out


def both_sides(lines: list[Line], corridor: Interval, least: int = 1) -> bool:
    """Whether at least ``least`` lines have words left of ``corridor`` and as many right of it."""
    lefts = sum(1 for line in lines if any(w.x1 <= corridor[0] for w in line))
    rights = sum(1 for line in lines if any(w.x0 >= corridor[1] for w in line))
    return lefts >= least and rights >= least


def _split(lines: list[Line], corridors: list[Interval]) -> list[list[Line]]:
    """One stream per column (left to right); empty fragments are skipped.
    A word belongs to the column right of a corridor when it STARTS in the
    corridor's last quarter or beyond: a word poking into the gutter from
    the left stays in its column."""
    cuts = [g0 + _RIGHT_EDGE * (g1 - g0) for g0, g1 in corridors]
    columns: list[list[Line]] = [[] for _ in range(len(cuts) + 1)]
    for line in lines:
        parts: list[Line] = [[] for _ in columns]
        for word in line:
            parts[sum(1 for c in cuts if word.x0 >= c)].append(word)
        for column, part in zip(columns, parts, strict=True):
            if part:
                column.append(part)
    return [c for c in columns if c]
