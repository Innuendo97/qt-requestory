"""Per-page primitives of the zone stage (``compare.zones``, spec §3.2).

Lines of horizontal words, the page's graphics sorted into dividers, logos
and watermark paths, the page-number patterns and the text normalisation the
zone rules compare lines with. The thresholds are the ones measured on the
real corpus (research ``fase25-zone-variabili`` §A.1-A.2): positions are
shares of the page height, sizes multiples of the document's body size.

Deterministic and pure; stdlib only, no Qt, no pypdfium2.
"""
from __future__ import annotations

import re
import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from qtrequestory.officina.compare.graphics import Box, PageGraphics, PathShape
from qtrequestory.officina.compare.model import Word

__all__ = [
    "ALIKE", "ALIKE_TITLE", "BAND_WIDE", "FOOT_STRICT", "GLYPH_SEGMENTS", "HEAD_STRICT", "SMALL", "TEXT_HEADER_BAND",
    "Alike",
    "Line", "PageArt", "Tail", "bottom_block", "is_divider", "make_lines", "matches", "page_art", "page_number_tail",
    "first_word", "page_number_marks", "size_of", "small_header", "title_by_size", "tokens", "union", "usual",
]

#: A path with more segments than this is drawn like a glyph (a logo,
#: outlined text, a watermark); a divider has 1-5.
GLYPH_SEGMENTS = 20
#: A divider: at most this many segments, at most this tall (points; the
#: measured ones are 2.83 thick, ≤ 7 tall with the stroke) and at least this
#: share of the page wide.
DIVIDER_SEGMENTS = 6
DIVIDER_HEIGHT = 7.0
DIVIDER_WIDTH = 0.6
#: The header divider lies in the top 8 % of the page, the footer one in the
#: bottom 12 %; up to 15 % when the same divider repeats on another page.
HEAD_STRICT = 0.08
FOOT_STRICT = 0.12
BAND_WIDE = 0.15
#: A logo or image of the header starts in the top 6 % and ends in the top
#: 15 %; one of the footer starts in the bottom 15 % and ends in the bottom 6 %.
_ART_EDGE = 0.06
#: A watermark path: glyph-like, filled light grey (min channel in this
#: range), at least this large (points) on its longer side.
_LIGHT = (150, 250)
_WATERMARK_SIDE = 30.0
#: Words of a line: their bottoms within this share of the font size.
_LINE_TOLERANCE = 0.45
#: Line sizes against the body size: a title line (a strong one), small print.
TITLE = 1.2
TITLE_STRONG = 1.3
SMALL = 0.95
#: A text header lies in the top 12 %; a bottom block below 85 %.
TEXT_HEADER_BAND = 0.12
SMALL_FOOT_BAND = 0.85
#: A block of lines: consecutive lines at most this many sizes apart; set
#: apart from the body by more than this (less right above the footer limit).
PITCH = 1.6
APART = 2.2
NEAR_APART = 1.5
#: Lines read alike when their word sets overlap this much (Jaccard): a
#: header/footer line changed by a brand scores ≥ 0.8; a form line that only
#: QUOTES the company («PER RICEVUTA DA PARTE DI <company> …») ≈ 0.6. A title
#: whose placeholder was filled («OFFERTA [xx]» → «OFFERTA Luce Facile») 0.5.
ALIKE = 0.7
ALIKE_TITLE = 0.5

Rgba = tuple[int, int, int, int]


def size_of(word: Word) -> float:
    """A word's font size; from its box height when the extractor gave none."""
    return word.size if word.size > 0 else max(word.y1 - word.y0, 0.0) / 1.15


def union(boxes: Iterable[Box]) -> Box | None:
    """The smallest box holding ``boxes``; None for none."""
    boxes = list(boxes)
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


@dataclass
class Line:
    """Horizontal words on one baseline: ``members`` are indices into the
    document's words, left to right; ``size`` the median font size."""

    members: list[int]
    box: Box
    size: float
    text: str
    zone: str = "corpo"

    @property
    def cy(self) -> float:
        return (self.box[1] + self.box[3]) / 2


def make_lines(words: Sequence[Word], indices: Iterable[int]) -> list[Line]:
    """The words ``indices`` of one page grouped into lines (by the bottom of
    their boxes), top to bottom."""
    order = sorted(indices, key=lambda i: (words[i].y1, words[i].x0, i))
    groups: list[list[int]] = []
    for i in order:
        word = words[i]
        if groups and abs(word.y1 - words[groups[-1][0]].y1) <= _LINE_TOLERANCE * max(size_of(word), 4.0):
            groups[-1].append(i)
        else:
            groups.append([i])
    lines = []
    for group in groups:
        group.sort(key=lambda i: (words[i].x0, i))
        members = [words[i] for i in group]
        box = union((w.x0, w.y0, w.x1, w.y1) for w in members)
        size = statistics.median(size_of(w) for w in members)
        lines.append(Line(group, box, size, " ".join(w.text for w in members)))
    lines.sort(key=lambda line: (line.cy, line.box[0]))
    return lines


def tokens(text: str) -> tuple[str, ...]:
    """The words of a text for comparing lines: casefolded, every number
    turned into ``#`` (page numbers, dates and codes change from page to page)."""
    return tuple(re.sub(r"\d+", "#", t) for t in re.findall(r"\w+", text.casefold()))


def is_divider(path: PathShape, width: float) -> bool:
    """A long thin horizontal path (a rule across the page)."""
    x0, y0, x1, y1 = path.box
    return path.segments <= DIVIDER_SEGMENTS and y1 - y0 <= DIVIDER_HEIGHT and x1 - x0 >= DIVIDER_WIDTH * width


def _paints(path: PathShape) -> bool:
    """Whether a path leaves ink on a white page (not a clip, not white on white)."""
    if path.stroke is not None and path.stroke[3] > 0 and min(path.stroke[:3]) < 250:
        return True
    return path.fill is not None and path.fill[3] > 0 and min(path.fill[:3]) < 250


def _light(colour: Rgba | None) -> bool:
    return colour is not None and colour[3] > 0 and _LIGHT[0] <= min(colour[:3]) < _LIGHT[1]


@dataclass
class PageArt:
    """The graphics of one page by role (boxes in word space): divider
    candidates, watermark paths, logos/images at the top and at the bottom."""

    dividers: list[Box] = field(default_factory=list)
    watermark: list[Box] = field(default_factory=list)
    head: list[Box] = field(default_factory=list)
    foot: list[Box] = field(default_factory=list)


def page_art(graphics: PageGraphics, width: float, height: float) -> PageArt:
    """Sort a page's paths and images: dividers (any height: the side picks
    the header and footer ones, :data:`HEAD_STRICT`…), watermark paths
    (glyph-like, light grey, large, outside the top 8 % and the bottom 12 %),
    and logos/images compact enough (narrower than half the page) at the
    top or the bottom edge."""
    art = PageArt()
    shapes: list[Box] = []
    for path in graphics.paths:
        if is_divider(path, width):
            if _paints(path):
                art.dividers.append(path.box)
            continue
        x0, y0, x1, y1 = path.box
        centre = (y0 + y1) / 2
        if (path.segments > GLYPH_SEGMENTS and _light(path.fill) and max(x1 - x0, y1 - y0) >= _WATERMARK_SIDE
                and HEAD_STRICT * height < centre < (1 - FOOT_STRICT) * height):
            art.watermark.append(path.box)
        elif _paints(path):
            shapes.append(path.box)
    shapes.extend(graphics.images)
    for box in shapes:
        x0, y0, x1, y1 = box
        if x1 - x0 >= 0.5 * width:
            continue  # a band or a background, not a logo
        if y0 < _ART_EDGE * height and y1 < BAND_WIDE * height:
            art.head.append(box)
        elif y0 > (1 - BAND_WIDE) * height and y1 > (1 - _ART_EDGE) * height:
            art.foot.append(box)
    return art


# ---------------------------------------------------------- line blocks ---
# ``body``: one page's body lines, top to bottom; ``size``: the body size.

def small_header(body: list[Line], height: float, size: float) -> list[Line]:
    """The first block of small lines at the top, set apart from the body
    below (a company line under the header divider, D4); [] when none."""
    for k, line in enumerate(body[:-1]):
        if line.cy >= TEXT_HEADER_BAND * height or line.size >= SMALL * size:
            return []
        gap = body[k + 1].cy - line.cy
        if gap > APART * line.size:
            return body[:k + 1]
        if gap > PITCH * line.size:
            return []
    return []


def bottom_block(body: list[Line], height: float, bottom: float | None, size: float) -> list[Line]:
    """The last block of body lines at the bottom (below 85 %, one line
    pitch apart), set apart from the body above (a gap of 2.2 lines; 1.5
    when it ends right above the footer limit ``bottom``); [] when none."""
    k = len(body) - 1
    if k < 1 or body[k].cy <= SMALL_FOOT_BAND * height:
        return []
    while k >= 1 and body[k - 1].cy > SMALL_FOOT_BAND * height and body[k].cy - body[k - 1].cy <= PITCH * body[k].size:
        k -= 1
    if k == 0:
        return []
    near = bottom is not None and bottom - body[-1].cy <= 2.5 * size
    gap = body[k].cy - body[k - 1].cy
    return body[k:] if gap > (NEAR_APART if near else APART) * body[k].size else []


def title_by_size(body: list[Line], size: float) -> list[Line]:
    """From the first line ≥ 1.3× the body ``size`` (else ≥ 1.2×), up and
    down through the large lines tightly around it (an «ALLEGATO n» line
    above; not an address block or a section heading set apart)."""
    large = [line.size >= TITLE * size for line in body]
    start = next((k for k, line in enumerate(body) if line.size >= TITLE_STRONG * size),
                 next((k for k, ok in enumerate(large) if ok), None))
    if start is None:
        return []
    end = start
    while end + 1 < len(body) and large[end + 1] and end + 1 - start < 6 and _tight(body[end], body[end + 1]):
        end += 1
    while start > 0 and large[start - 1] and _tight(body[start - 1], body[start]):
        start -= 1
    return body[start:end + 1]


def _tight(upper: Line, lower: Line) -> bool:
    """Whether two lines follow each other without a gap (2.2× the smaller size)."""
    return lower.cy - upper.cy <= APART * min(upper.size, lower.size)


class Alike:
    """Word sets indexed by word, to ask many times which one a line reads
    like (:func:`matches`) without intersecting every set each time."""

    def __init__(self, others: Iterable[Iterable[str]]) -> None:
        self.sets = [frozenset(o) for o in dict.fromkeys(tuple(o) for o in others)]
        self.by_word: dict[str, list[int]] = {}
        for k, words in enumerate(self.sets):
            for word in words:
                self.by_word.setdefault(word, []).append(k)

    def best(self, key: set[str]) -> float:
        """The highest Jaccard similarity of ``key`` with one of the sets."""
        shared: dict[int, int] = {}
        for word in key:
            for k in self.by_word.get(word, ()):
                shared[k] = shared.get(k, 0) + 1
        return max((n / (len(key) + len(self.sets[k]) - n) for k, n in shared.items()), default=0.0)


def matches(line: Line, others: Alike | Sequence[Iterable[str]], alike: float = ALIKE) -> bool:
    """Whether ``line`` (≥ 3 words) reads like one of ``others`` (word sets,
    or an :class:`Alike` index of them to call it often)."""
    key = set(tokens(line.text))
    if len(key) < 3:
        return False
    index = others if isinstance(others, Alike) else Alike(others)
    return index.best(key) >= alike


# ---------------------------------------------------------- page numbers ---

def first_word(line: Line, words: Sequence[Word], start: int) -> int | None:
    """The index (in ``line.members``) of the word starting at character
    ``start`` of ``line.text``; None when ``start`` falls inside a word."""
    offset = 0
    for k, i in enumerate(line.members):
        if offset == start:
            return k
        if offset > start:
            return None
        offset += len(words[i].text) + 1
    return None


def usual(values: list[float | None]) -> float | None:
    """The value most pages agree on (within 1 %), None when they do not."""
    known = sorted(v for v in values if v is not None)
    if not known:
        return None
    middle = known[len(known) // 2]
    return middle if all(abs(v - middle) <= 0.01 for v in known) else None



#: «1 di 3», «Pag. 2 di 5», «Pagina 2/3», «3 of 4» at the END of a line.
_TAIL = re.compile(r"(?P<pag>\bpag(?:ina|\.)?\s*)?\b(?P<n>\d{1,3})\s*(?P<sep>di|/|of)\s*(?P<m>\d{1,3})\s*$",
                   re.IGNORECASE)
#: A line that is only a number: «3», «Pag. 3», «Pagina 3», «- 3 -».
_ALONE = re.compile(r"^(?:(?:pag(?:ina|\.)?\s*)?(\d{1,3})|-\s*(\d{1,3})\s*-)$", re.IGNORECASE)


@dataclass(frozen=True)
class Tail:
    """A page number found at the end of a line: ``start`` its first
    character in the line's text, ``number`` / ``total`` (``total`` 0 for a
    number alone). ``bare``: an «n/m» without «Pag.», which must be the
    whole line (review A2 C1: «Ed. 04/26», «Rev. 1/2»)."""

    start: int
    number: int
    total: int
    bare: bool = False


def page_number_tail(text: str) -> Tail | None:
    """The page number ending ``text``, if any («n di m» needs 1 ≤ n ≤ m)."""
    stripped = text.strip()
    alone = _ALONE.match(stripped)
    if alone:
        return Tail(text.index(stripped), int(alone.group(1) or alone.group(2)), 0)
    found = _TAIL.search(stripped)
    if found:
        number, total = int(found.group("n")), int(found.group("m"))
        if 1 <= number <= total:
            bare = found.group("sep") == "/" and not found.group("pag")
            return Tail(text.index(stripped) + found.start(), number, total, bare)
    return None


#: Page numbers sit in the header, the footer or the extreme 8 % of the page;
#: a tail is set apart from the text before it by 2× the body size.
_NUMBER_BAND = 0.08
_NUMBER_GAP = 2.0


def page_number_marks(pages: Sequence[tuple[int, float, list[Line]]], words: Sequence[Word],
                      body: float) -> list[tuple[Line, int]]:
    """The page numbers of a document, as ``(line, first member)``: the
    line's words from ``first`` on (``pages``: number, height and lines).

    Review A2 C1: ``numero_pagina`` is not counted by default, so a false
    one hides a difference. A candidate is a whole line («1 di 3», «Pag. 2»,
    «2/3», «3») in the header, the footer or the extreme bands, or a «n di m»
    / «Pag. n/m» tail of a header or footer line set apart by a gap of 2× the
    body size. Accepted only when the pages agree: n − page index and m the
    same on ≥ 2 pages; a one-page document needs a whole-line «n di m» (not a
    bare «n/m»: «04/26», M6)."""
    found: list[tuple[int, Line, int, int, int, bool]] = []  # page, line, first, n, m, alone ok
    for number, height, lines in pages:
        for line in lines:
            edge = line.cy < _NUMBER_BAND * height or line.cy > (1 - _NUMBER_BAND) * height
            banded = line.zone in ("header", "footer")
            tail = page_number_tail(line.text) if banded or edge else None
            if tail is None:
                continue
            first = first_word(line, words, tail.start)
            whole = first == 0
            if not whole:
                apart = (first is not None and words[line.members[first]].x0
                         - words[line.members[first - 1]].x1 >= _NUMBER_GAP * body)
                if not banded or not tail.total or tail.bare or not apart:
                    continue
            found.append((number, line, first, tail.number, tail.total, whole and not tail.bare))
    groups: dict[tuple[int, int], set[int]] = {}
    for number, _, _, n, m, _ in found:
        groups.setdefault((n - number, m), set()).add(number)
    alone = len(pages) == 1
    return [(line, first) for number, line, first, n, m, alone_ok in found
            if len(groups[(n - number, m)]) >= 2 or (alone and alone_ok and m and n <= m)]
