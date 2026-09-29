"""Where a target leaves room for a value (phase 2.5, spec §3.3; task A4):
the geometry behind the position proofs of ``variables``.

Built once per comparison for each side (:meth:`Geometry.of`): the words
of each body block (a paragraph of one column: ``blocks``) and of each zone
of each page grouped into LINES, each group's extent being its column, and
the table CELLS the page's thin paths draw. Rotated words (the shoulders)
have no lines: a shoulder is one line along the margin.

The tests, all on the TARGET's geometry (the generated side is laid out
differently: only its value's width is used):

* :meth:`Geometry.gap` — the empty space between two words of one line of
  one block (not a gutter), and :meth:`Geometry.space` — the typical
  inter-word space of that line (``proofs.hole_room`` decides whether the
  gap stands out enough to be a **buco**);
* :meth:`Geometry.room_after` — the free width after a word to its column's
  right edge (a label at the end of its line);
* :meth:`Geometry.void_below` — a heading followed by an empty band of more
  than two line heights before the next word (a **sezione**);
* :meth:`Geometry.cell` — the table cell around a point, from the page's
  thin horizontal and vertical paths (or rectangles).

Pure; stdlib only, no Qt, no pypdfium2.
"""
from __future__ import annotations

import math

from bisect import bisect_left
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from qtrequestory.officina.compare.graphics import Box, PageGraphics
from qtrequestory.officina.compare.model import Word

__all__ = ["CHARS", "Geometry", "RATIO", "char_width", "group_of", "on_one_line", "width_of"]

#: A hole is at least this share of the value's width…
RATIO = 0.35
#: …and at least this many characters (a character = half the text height).
CHARS = 2.5
#: A path this thin (points) is a table rule.
_RULE = 2.5
#: Rules shorter than this (points) are not table rules (a dash, a bullet).
_MIN_RULE = 5.0
#: Lines this far (in line heights) above and below widen a column's edges.
_NEAR = 3.0
_FLOW = frozenset({"corpo", "titolo"})


def group_of(word: Word) -> str:
    """The zone group of a word: the body and the title flow together."""
    return "flow" if word.zone in _FLOW else word.zone


def width_of(words: Sequence[Word]) -> float:
    """The width a value takes on its first line."""
    if not words:
        return 0.0
    first = words[0]
    same = [w for w in words if w.page == first.page and _overlap(first, w)]
    return max(w.x1 for w in same) - min(w.x0 for w in same)


def char_width(*words: Word | None) -> float:
    """The width of a character next to ``words``: half their text height."""
    heights = [w.y1 - w.y0 for w in words if w is not None and w.y1 > w.y0]
    return 0.5 * (max(heights) if heights else 8.0)


def on_one_line(a: Word, b: Word) -> bool:
    """Whether two words of one document sit on the same line of the same page."""
    return a.page == b.page and _overlap(a, b)


def _overlap(a: Word, b: Word) -> bool:
    """Whether two words sit on the same line (their vertical centres within half a height)."""
    height = max(a.y1 - a.y0, b.y1 - b.y0, 1.0)
    return abs((a.y0 + a.y1) - (b.y0 + b.y1)) / 2 < 0.5 * height


@dataclass
class _Line:
    words: list[Word]

    @property
    def x0(self) -> float:
        return self.words[0].x0

    @property
    def x1(self) -> float:
        return self.words[-1].x1

    @property
    def top(self) -> float:
        return min(w.y0 for w in self.words)

    @property
    def bottom(self) -> float:
        return max(w.y1 for w in self.words)


class Geometry:
    """The lines and cells of one document (module doc)."""

    def __init__(self, groups: Iterable[Sequence[Word]], graphics: Sequence[PageGraphics]) -> None:
        self._lines: dict[tuple[int, str], list[_Line]] = {}
        self._line_of: dict[Word, _Line] = {}
        self._column_of: dict[int, tuple[float, float]] = {}
        for group in groups:
            by_page: dict[int, list[Word]] = {}
            for word in group:
                by_page.setdefault(word.page, []).append(word)
            for page, found in by_page.items():
                lines = _lines(found)
                edges = (min(line.x0 for line in lines), max(line.x1 for line in lines))
                for line in lines:
                    self._column_of[id(line)] = edges
                    self._lines.setdefault((page, group_of(line.words[0])), []).append(line)
                    for word in line.words:
                        self._line_of[word] = line
        self._graphics = graphics
        self._rules: dict[int, tuple[list, list]] = {}

    @staticmethod
    def of(blocks: Iterable[Sequence[Word]], zone_words: Iterable[Word], graphics: Sequence[PageGraphics],
           rotated: Iterable[Word] = ()) -> Geometry:
        """The geometry of a document: its body blocks (each one column's
        paragraph), and its zone words grouped by zone and page; ``rotated``
        words are left out."""
        turned = set(rotated)
        zones: dict[tuple[str, int], list[Word]] = {}
        for word in zone_words:
            if word not in turned and group_of(word) != "flow":
                zones.setdefault((word.zone, word.page), []).append(word)
        return Geometry([*blocks, *zones.values()], graphics)

    def knows(self, word: Word | None) -> bool:
        """Whether ``word`` is one of this document's horizontal words."""
        return word is not None and word in self._line_of

    def same_line(self, a: Word | None, b: Word | None) -> bool:
        return a is not None and b is not None and a.page == b.page and _overlap(a, b)

    def words_of(self, word: Word) -> list[Word]:
        """The words on ``word``'s line."""
        line = self._line_of.get(word)
        return list(line.words) if line else []

    def gap(self, a: Word, b: Word) -> float:
        """The empty space between ``a`` and ``b`` on one line of one block
        (a paragraph, or one zone of one page): 0 when they are not on one
        such line, another word lies between them, or the space is a column
        gutter (:meth:`gutter`)."""
        if not (self.knows(a) and self.knows(b)) or b.x0 <= a.x1:
            return 0.0
        line = self._line_of[a]
        if line is not self._line_of[b]:
            return 0.0               # two blocks side by side (columns), not a hole in one line
        if any(w.x0 >= a.x1 - 0.1 and w.x1 <= b.x0 + 0.1 and w != a and w != b for w in line.words):
            return 0.0
        return 0.0 if self.gutter(a, a.x1, b.x0) else b.x0 - a.x1

    def space(self, a: Word, b: Word | None = None) -> float:
        """The typical space between two words on ``a``'s line: the median of
        its other inter-word spaces, the one after ``a`` left out (the UPPER
        median when their number is even — the larger reference, so a hole
        is harder to prove); a justified line stretches them all alike. A
        line with no other space gives nothing to compare with: infinite (no
        hole there — a lone gap may be justification; review A4 fix 2, Minor 1)."""
        line = self._line_of.get(a)
        if line is None:
            return 0.0
        spaces = sorted(max(0.0, y.x0 - x.x1) for x, y in zip(line.words, line.words[1:]) if x != a)
        return spaces[len(spaces) // 2] if spaces else math.inf

    def gutter(self, a: Word, x0: float, x1: float) -> bool:
        """Whether the band ``[x0, x1]`` on ``a``'s line is a column gutter:
        at least two nearby lines have text on both sides of it and none
        runs through it (a hole in running text has text through it above
        or below, a gutter never)."""
        line = self._line_of[a]
        height = max(line.bottom - line.top, 1.0)
        split = 0
        for other in self._lines[(a.page, group_of(a))]:
            if other is line or abs(other.top - line.top) > _NEAR * 2 * height:
                continue
            if any(w.x0 < x1 - 2 and w.x1 > x0 + 2 for w in other.words):
                return False
            if other.x0 < x0 and other.x1 > x1:
                split += 1
        return split >= 2

    def ends_line(self, a: Word) -> bool:
        line = self._line_of.get(a)
        return line is not None and line.words[-1] == a

    def room_after(self, a: Word) -> float:
        """The free width after ``a`` (the last word of its line) to its column's right edge."""
        return max(0.0, self._column(a)[1] - a.x1) if self.ends_line(a) else 0.0

    def void_below(self, a: Word, b: Word) -> bool:
        """``a`` ends a heading line (bold, larger than ``b``, or in capitals) and
        the target leaves more than two line heights empty below it before ``b``,
        in the same column."""
        line_a, line_b = self._line_of.get(a), self._line_of.get(b)
        if line_a is None or line_b is None or a.page != b.page or line_a is line_b:
            return False
        height = max(line_a.bottom - line_a.top, 1.0)
        if line_b.top - line_a.bottom <= 2 * 1.2 * height:
            return False
        letters = "".join(c for w in line_a.words for c in w.text if c.isalpha())
        heading = a.bold or (a.size and b.size and a.size > b.size + 0.5) or (letters.isupper() and len(letters) > 2)
        if not heading or line_b.x0 > line_a.x1 or line_b.x1 < line_a.x0:
            return False
        lines = self._lines[(a.page, group_of(a))]
        if any(line_a.bottom < line.top < line_b.top and line.x0 < line_a.x1 + 20 and line.x1 > line_a.x0
               for line in lines if line is not line_a and line is not line_b):
            return False
        return not self._drawn(a.page, (min(line_a.x0, line_b.x0), line_a.bottom + 1,
                                        max(line_a.x1, line_b.x1), line_b.top - 1))

    def _drawn(self, page: int, box: Box) -> bool:
        """Whether a path wider than a rule, or an image, lies in ``box`` (a
        table or a picture fills that band: it is not empty)."""
        graphics = self._graphics[page] if 0 <= page < len(self._graphics) else PageGraphics()
        shapes = [p.box for p in graphics.paths if p.box[2] - p.box[0] > _RULE and p.box[3] - p.box[1] > _RULE]
        return any(s[0] < box[2] and s[2] > box[0] and s[1] < box[3] and s[3] > box[1]
                   for s in (*shapes, *graphics.images))

    def cell(self, page: int, x: float, y: float) -> Box | None:
        """The table cell around ``(x, y)`` on ``page``: the nearest rules
        on its four sides that cross its row / column; None outside a table."""
        horizontal, vertical = self._page_rules(page)
        left = right = top = bottom = None
        for x0, y0, y1 in vertical:
            if y0 - 1 <= y <= y1 + 1:
                if x0 <= x and (left is None or x0 > left):
                    left = x0
                if x0 > x and (right is None or x0 < right):
                    right = x0
        for y0, x0, x1 in horizontal:
            if x0 - 1 <= x <= x1 + 1:
                if y0 <= y and (top is None or y0 > top):
                    top = y0
                if y0 > y and (bottom is None or y0 < bottom):
                    bottom = y0
        if None in (left, right, top, bottom):
            return None
        return (left, top, right, bottom)  # type: ignore[return-value]

    def inside(self, box: Box, page: int, group: str) -> list[Word]:
        """This document's horizontal words of ``group`` whose centre is in ``box``."""
        x0, y0, x1, y1 = box
        out = []
        for line in self._lines.get((page, group), ()):
            if line.bottom < y0 or line.top > y1:
                continue
            out += [w for w in line.words if x0 <= (w.x0 + w.x1) / 2 <= x1 and y0 <= (w.y0 + w.y1) / 2 <= y1]
        return out

    # ------------------------------------------------------------ helpers ---

    def _column(self, word: Word) -> tuple[float, float]:
        """The left and right edges of ``word``'s column: the extent of its
        block's lines (a paragraph of one column, or one zone of one page),
        widened by the lines of the same page and group a few line heights
        above and below that overlap ``word``'s line (a one-line block: a label)."""
        line = self._line_of[word]
        left, right = self._column_of[id(line)]
        height = max(line.bottom - line.top, 1.0)
        for other in self._lines[(word.page, group_of(word))]:
            if abs(other.top - line.top) <= _NEAR * height and other.x0 < line.x1 and other.x1 > line.x0:
                left, right = min(left, other.x0), max(right, other.x1)
        return left, right

    def _page_rules(self, page: int) -> tuple[list, list]:
        if page not in self._rules:
            horizontal: list[tuple[float, float, float]] = []
            vertical: list[tuple[float, float, float]] = []
            paths = self._graphics[page].paths if 0 <= page < len(self._graphics) else ()
            for path in paths:
                x0, y0, x1, y1 = path.box
                w, h = x1 - x0, y1 - y0
                if h <= _RULE and w >= _MIN_RULE:
                    horizontal.append(((y0 + y1) / 2, x0, x1))
                elif w <= _RULE and h >= _MIN_RULE:
                    vertical.append(((x0 + x1) / 2, y0, y1))
                elif 4 <= path.segments <= 5 and w >= _MIN_RULE and h >= _MIN_RULE and path.stroke is not None:
                    horizontal += [(y0, x0, x1), (y1, x0, x1)]
                    vertical += [(x0, y0, y1), (x1, y0, y1)]
            self._rules[page] = (horizontal, vertical)
        return self._rules[page]


def _lines(words: list[Word]) -> list[_Line]:
    """One block's words grouped into lines (vertical centres close), each sorted by x."""
    ordered = sorted(words, key=lambda w: ((w.y0 + w.y1) / 2, w.x0))
    lines: list[list[Word]] = []
    centres: list[float] = []
    for word in ordered:
        centre = (word.y0 + word.y1) / 2
        k = bisect_left(centres, centre - 0.5 * max(word.y1 - word.y0, 1.0))
        placed = False
        for n in range(k, len(lines)):
            if _overlap(lines[n][0], word):
                lines[n].append(word)
                placed = True
                break
        if not placed:
            lines.append([word])
            centres.append(centre)
    return [_Line(sorted(line, key=lambda w: w.x0)) for line in lines]
