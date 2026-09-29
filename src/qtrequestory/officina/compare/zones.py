"""Document zones (spec §3.2, D4): which part of the page every word is in.

Zones: ``header``, ``titolo``, ``footer``, ``spalla_sx``, ``spalla_dx``,
``numero_pagina``, ``filigrana`` and ``corpo`` (the rest). They are decided
on BOTH sides of a comparison together: target and generated come from the
same layout, so a zone found with confidence on one side (a divider, a logo,
a footer line) guides the other.

Per page, in this order (thresholds measured on the real corpus, research
``fase25-zone-variabili`` §A.1):

1. rotated words: at 90/270 degrees left of the horizontal text →
   ``spalla_sx``, right of it → ``spalla_dx`` (the position decides, not
   the angle). Watermark CANDIDATES: rotated words larger than 3× the body
   size, diagonal ones at least 2× (a chart's slanted labels stay body),
   huge horizontal words mid-page. A cluster of them is ``filigrana`` when
   light (off a dark background), or diagonal and repeated on another page
   (``zones_watermark``) — and not when the other side holds
   DIFFERENT large text in the same slot (``disagree``: a changed price);
2. graphics (``zones_page.page_art``): dividers, logos/images at the edges,
   light-grey glyph-like paths (the watermark, which holds no words);
3. the header/footer limits: the header divider (top 8 %, or up to 15 % when
   it repeats on another page) and the logos above it; the footer divider
   (bottom 12 %, or 15 % repeated) and the logos below it. A page without its
   own limit takes the other side's (same page, else that side's usual one);
4. lines above the header limit → ``header``, below the footer limit →
   ``footer``; without a limit, a short big line at the top or a line
   repeated on at least half the pages (a form row with a fill-in leader:
   on most pages; A3); a first block of small print set apart at the
   top (a company line under the divider, D4) → ``header``; a last block set
   apart at the bottom → ``footer`` when it is small print, or when the
   other side's footer text starts at the same height on that page; a body
   line reading like a header/footer line of the other side (Jaccard ≥ 0.7),
   in the same band → that zone (``zones_page`` holds the line-block rules);
5. page numbers («1 di 3», «Pag. 2», «2/3», a number alone in sequence) at
   the end of a line in the header, the footer or the extreme bands →
   ``numero_pagina``;
6. page 1, upper half: from the first line ≥ 1.3× the body size (else
   ≥ 1.2×), with the large lines tightly around it (not an address block
   set apart above it), or the lines reading like the other side's title →
   ``titolo``.

Words keep their ORDER (only ``zone`` changes), so ``DocText.rotated``
(keyed by index, review A1 M2) stays valid. Invisible words are left alone.
Each side also gets one :class:`~compare.model.ZoneBox` per page and zone
(not ``corpo``) for the viewer's margin rails.

Note for A3 (review A2 M2/M3): footer words COUNT but leave the flow. A body
tail matched to the other side's footer, and small-print footnotes set apart
at the bottom, become ``footer``: a reflow there shows per page.

Deterministic and pure; stdlib only, no Qt, no pypdfium2.
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field, replace

from qtrequestory.officina.compare.extract_pdf import DocText
from qtrequestory.officina.compare.graphics import Box, PageGraphics
from qtrequestory.officina.compare.model import ZONES, ZoneBox
from qtrequestory.officina.compare.zones_page import (
    ALIKE_TITLE, Alike, BAND_WIDE, FOOT_STRICT, HEAD_STRICT, SMALL, TEXT_HEADER_BAND, Line, PageArt, bottom_block,
    make_lines, matches, page_art, page_number_marks, size_of, small_header, title_by_size, tokens,
    union, usual,
)
from qtrequestory.officina.compare.zones_watermark import disagree, watermark_marks

__all__ = ["ZonedDoc", "zone_document", "zone_pair"]

#: Size ratios to the body size: big header line, watermark, diagonal watermark.
_BIG_HEADER = 1.5
_WATERMARK = 3.0
_DIAGONAL = 2.0
#: Bands (share of the page height).
_SHORT_HEADER_BAND = 0.07
_FOOT_REPEAT_BAND = 0.88
_GUIDE_FOOT_BAND = 0.70
_GUIDE_HEAD_BAND = 0.20
#: Two lines/dividers "repeat" across pages within this many points.
_SAME_Y = 4.0
#: A fill-in leader (a form row).
_LEADER = re.compile(r"[._…]{4,}")
#: A repeated line repeats on at least this share of the pages (two pages of
#: a long document can share a line by chance; furniture is on most pages)…
_HALF = 0.5
#: …a form row on at least this share.
_MOST = 0.6


@dataclass(frozen=True)
class ZonedDoc:
    """One side after the zone stage: ``doc`` with every word's ``zone`` set
    (same words, same order, same ``rotated``), the zone boxes per page, and
    the body size the rules measured against (points)."""

    doc: DocText
    boxes: tuple[ZoneBox, ...]
    body_size: float


def zone_pair(left: DocText, right: DocText) -> tuple[ZonedDoc, ZonedDoc]:
    """The zones of both sides of a comparison, decided together."""
    a, b = _Side(left), _Side(right)
    disagree(a.marks, b.marks)
    a.build()
    b.build()
    limits = (a.own_limits(), b.own_limits())
    a.adopt(*limits[1])
    b.adopt(*limits[0])
    a.classify()
    b.classify()
    heads, feet = (a.texts("header"), b.texts("header")), (a.texts("footer"), b.texts("footer"))
    tops = (a.footer_tops(), b.footer_tops())
    a.guide(heads[1], feet[1], tops[1])
    b.guide(heads[0], feet[0], tops[0])
    a.numbers()
    b.numbers()
    titles = (a.title(()), b.title(()))
    if not titles[0]:
        a.title(titles[1])
    if not titles[1]:
        b.title(titles[0])
    return a.result(), b.result()


def zone_document(doc: DocText) -> ZonedDoc:
    """The zones of one document alone (no other side to guide it)."""
    return zone_pair(doc, DocText([], [], False))[0]


@dataclass
class _Page:
    number: int
    width: float
    height: float
    art: PageArt
    lines: list[Line] = field(default_factory=list)
    top: float | None = None       # header limit (y): a line centred above it is header
    bottom: float | None = None    # footer limit (y): a line centred below it is footer
    head_rule: Box | None = None
    foot_rule: Box | None = None


class _Side:
    """The zone state of one document."""

    def __init__(self, doc: DocText) -> None:
        self.doc = doc
        words = doc.words
        self.zone = ["corpo"] * len(words)
        flat = [size_of(w) for i, w in enumerate(words) if not doc.rotated.get(i)]
        self.body = statistics.median(flat) if flat else 8.0
        self.pages: list[_Page] = []
        by_page: dict[int, list[int]] = {}
        for i, word in enumerate(words):
            by_page.setdefault(word.page, []).append(i)
        self._flat: list[list[int]] = []
        self._index: dict[tuple[str, ...], list[tuple[int, float]]] | None = None
        candidates: dict[int, list[int]] = {}
        for number, (width, height) in enumerate(doc.page_sizes):
            graphics = doc.graphics[number] if number < len(doc.graphics) else PageGraphics()
            page = _Page(number, width, height, page_art(graphics, width, height))
            flat_here, candidates[number] = self._margins(page, by_page.get(number, []))
            self._flat.append(flat_here)
            self.pages.append(page)
        self.marks = watermark_marks(words, candidates, doc.light, doc.rotated, doc.graphics, doc.page_sizes)

    def build(self) -> None:
        """After the watermarks were checked against the other side
        (``zones_watermark.disagree``): zone them, make the lines, pick the limits."""
        for mark in self.marks:
            if mark.accepted:
                for i in mark.members:
                    self.zone[i] = "filigrana"
        for page, flat_here in zip(self.pages, self._flat, strict=True):
            page.lines = make_lines(self.doc.words, [i for i in flat_here if self.zone[i] == "corpo"])
        self._rules()

    # ------------------------------------------------------ step 1 ---
    def _margins(self, page: _Page, indices: list[int]) -> tuple[list[int], list[int]]:
        """Zone the shoulders of ``page``; its horizontal words and its
        watermark candidates (decided by ``zones_watermark``)."""
        words, rotated = self.doc.words, self.doc.rotated
        flat = [i for i in indices if not rotated.get(i)]
        xs = sorted(words[i].x0 for i in flat)
        ends = sorted(words[i].x1 for i in flat)
        left = xs[len(xs) // 50] if xs else 0.15 * page.width
        right = ends[-1 - len(ends) // 50] if ends else 0.85 * page.width
        big = max(_WATERMARK * self.body, 28.0)
        candidates: list[int] = []
        for i in indices:
            word, angle = words[i], rotated.get(i, 0)
            if not angle:
                centre = (word.y0 + word.y1) / 2
                if size_of(word) > big and BAND_WIDE * page.height < centre < (1 - BAND_WIDE) * page.height:
                    candidates.append(i)
                continue
            if angle in (90, 270) and word.x1 <= left + 2:
                self.zone[i] = "spalla_sx"
            elif angle in (90, 270) and word.x0 >= right - 2:
                self.zone[i] = "spalla_dx"
            elif size_of(word) > _WATERMARK * self.body or (
                    angle not in (90, 180, 270) and size_of(word) >= _DIAGONAL * self.body):
                candidates.append(i)
        return flat, candidates

    # ------------------------------------------------------ steps 2-3 ---
    def _rules(self) -> None:
        """Pick each page's header and footer dividers and set its limits."""
        for page in self.pages:
            h = page.height
            head = [b for b in page.art.dividers if _cy(b) < BAND_WIDE * h]
            foot = [b for b in page.art.dividers if _cy(b) > (1 - BAND_WIDE) * h]
            head = [b for b in head if _cy(b) < HEAD_STRICT * h or self._repeats(page, b)]
            foot = [b for b in foot if _cy(b) > (1 - FOOT_STRICT) * h or self._repeats(page, b)]
            # the repeated one first, then the one nearest the page edge
            page.head_rule = min(head, key=lambda b: (not self._repeats(page, b), _cy(b)), default=None)
            page.foot_rule = min(foot, key=lambda b: (not self._repeats(page, b), -_cy(b)), default=None)
            tops = ([_cy(page.head_rule)] if page.head_rule else []) + [b[3] + 2 for b in page.art.head]
            bottoms = ([_cy(page.foot_rule)] if page.foot_rule else []) + [b[1] - 2 for b in page.art.foot]
            page.top = max(tops) if tops else None
            page.bottom = min(bottoms) if bottoms else None

    def _repeats(self, page: _Page, rule: Box) -> bool:
        return any(abs(_cy(b) - _cy(rule)) <= _SAME_Y for other in self.pages if other is not page
                   for b in other.art.dividers)

    def own_limits(self) -> tuple[list[tuple[float | None, float | None]], tuple[float | None, float | None]]:
        """Each page's own limits as shares of its height, and the usual ones."""
        per = [(None if p.top is None else p.top / p.height, None if p.bottom is None else p.bottom / p.height)
               for p in self.pages]
        return per, (usual([t for t, _ in per]), usual([b for _, b in per]))

    def adopt(self, other: list[tuple[float | None, float | None]],
              usual: tuple[float | None, float | None]) -> None:
        """Fill the limits a page lacks with the other side's (same page, else its usual)."""
        for page in self.pages:
            top, bottom = other[page.number] if page.number < len(other) else usual
            if page.top is None and top is not None:
                page.top = top * page.height
            if page.bottom is None and bottom is not None:
                page.bottom = bottom * page.height

    # ------------------------------------------------------ step 4 ---
    def classify(self) -> None:
        for page in self.pages:
            h, lines = page.height, page.lines
            for line in lines:
                if page.top is not None and line.cy <= page.top:
                    line.zone = "header"
                elif page.bottom is not None and line.cy >= page.bottom:
                    line.zone = "footer"
            if page.top is None:
                last = -1
                for k, line in enumerate(lines):
                    if line.cy > TEXT_HEADER_BAND * h:
                        break
                    short_big = (line.cy < _SHORT_HEADER_BAND * h and len(line.members) <= 3
                                 and line.size >= _BIG_HEADER * self.body)
                    if short_big or self._repeated(page, line):
                        last = k
                for line in lines[:last + 1]:
                    line.zone = "header"
            first = next((k for k, line in enumerate(lines)
                          if line.cy > _FOOT_REPEAT_BAND * h and self._repeated(page, line)), None)
            if first is not None:
                for line in lines[first:]:
                    line.zone = "footer" if line.zone == "corpo" else line.zone
            for line in small_header(_body(page), h, self.body):
                line.zone = "header"
            block = bottom_block(_body(page), h, page.bottom, self.body)
            if block and all(line.size < SMALL * self.body for line in block):
                for line in block:
                    line.zone = "footer"

    def _repeated(self, page: _Page, line: Line) -> bool:
        """Whether ``line`` repeats at the same height on other pages: on at
        least :data:`_HALF` of them (page furniture is on most pages; in a
        long document two pages can share a body line by chance, and that
        line would cut the running text: review A3 I2). A form row (a
        fill-in leader, «Firma ......») repeats only when it does on
        :data:`_MOST` of the pages: otherwise its filled copy on the other
        side differs and it stays in the body."""
        key = tokens(line.text)
        same = self._pages_with(key, line.cy)
        if not key or len(same - {page.number}) == 0 or len(same) < _HALF * len(self.pages):
            return False
        if _LEADER.search(line.text) and len(same) < max(2, _MOST * len(self.pages)):
            return False
        return True

    def _pages_with(self, key: tuple[str, ...], cy: float) -> set[int]:
        """The pages holding a line reading ``key`` at the height ``cy``."""
        if self._index is None:   # the lines' texts are set once, in build(): indexed on first use
            self._index = {}
            for other in self.pages:
                for o in other.lines:
                    self._index.setdefault(tokens(o.text), []).append((other.number, o.cy))
        return {number for number, y in self._index.get(key, ()) if abs(y - cy) <= _SAME_Y}

    def footer_tops(self) -> list[float | None]:
        """Per page, where this side's footer TEXT starts (share of the height)."""
        return [min((line.cy / p.height for line in p.lines if line.zone == "footer"), default=None)
                for p in self.pages]

    def texts(self, zone: str) -> list[tuple[str, ...]]:
        """The word sets of this side's ``zone`` lines worth matching (≥ 3 words)."""
        return list(dict.fromkeys(key for page in self.pages for line in page.lines
                                  if line.zone == zone and len(key := tokens(line.text)) >= 3))

    def guide(self, heads: list[tuple[str, ...]], feet: list[tuple[str, ...]], tops: list[float | None]) -> None:
        """Body lines reading like the other side's header/footer lines, in
        the same band; the bottom block where the other side's footer text
        starts on the same page (its print may be as large as the body)."""
        head_index, foot_index = Alike(heads), Alike(feet)
        for page in self.pages:
            top = tops[page.number] if page.number < len(tops) else None
            block = bottom_block(_body(page), page.height, page.bottom, self.body)
            if block and top is not None and block[0].cy >= top * page.height - self.body:
                for line in block:
                    line.zone = "footer"
            body = _body(page)
            low = [line for line in body if line.cy > _GUIDE_FOOT_BAND * page.height and matches(line, foot_index)]
            if low:
                for line in body:
                    if line.cy >= low[0].cy:
                        line.zone = "footer"
            high = [line for line in body if line.cy < _GUIDE_HEAD_BAND * page.height and matches(line, head_index)]
            if high:
                for line in body:
                    if line.cy <= high[-1].cy:
                        line.zone = "header"

    # ------------------------------------------------------ steps 5-6 ---
    def numbers(self) -> None:
        """Page numbers (``zones_page.page_number_marks``)."""
        pages = [(page.number, page.height, page.lines) for page in self.pages]
        for line, first in page_number_marks(pages, self.doc.words, self.body):
            for i in line.members[first:]:
                self.zone[i] = "numero_pagina"

    def title(self, other: list[tuple[str, ...]]) -> list[tuple[str, ...]]:
        """Zone page 1's title; ``other`` = the other side's title lines to
        recognise it by (used when this side found none by size)."""
        if not self.pages:
            return []
        page = self.pages[0]
        body = [line for line in page.lines if line.zone == "corpo" and line.cy < 0.5 * page.height][:12]
        picked: list[Line] = []
        if other:
            for line in body[:6]:
                if not matches(line, other, ALIKE_TITLE):
                    break
                picked.append(line)
        else:
            picked = title_by_size(body, self.body)
        for line in picked:
            line.zone = "titolo"
        return [tokens(line.text) for line in picked]

    # ------------------------------------------------------ result ---
    def result(self) -> ZonedDoc:
        for page in self.pages:
            for line in page.lines:
                for i in line.members:
                    if self.zone[i] == "corpo":
                        self.zone[i] = line.zone
        words = [w if w.zone == z else replace(w, zone=z) for w, z in zip(self.doc.words, self.zone, strict=True)]
        doc = replace(self.doc, words=words)
        return ZonedDoc(doc, self._boxes(), self.body)

    def _boxes(self) -> tuple[ZoneBox, ...]:
        boxes: dict[tuple[int, str], list[Box]] = {}
        for word, zone in zip(self.doc.words, self.zone, strict=True):
            if zone != "corpo":
                boxes.setdefault((word.page, zone), []).append((word.x0, word.y0, word.x1, word.y1))
        for page in self.pages:
            art = page.art
            for zone, extra in (("header", [*art.head, *([page.head_rule] if page.head_rule else [])]),
                                ("footer", [*art.foot, *([page.foot_rule] if page.foot_rule else [])]),
                                ("filigrana", art.watermark)):
                if extra:
                    boxes.setdefault((page.number, zone), []).extend(extra)
        order = {zone: k for k, zone in enumerate(ZONES)}
        out = []
        for (number, zone), members in sorted(boxes.items(), key=lambda item: (item[0][0], order[item[0][1]])):
            out.append(ZoneBox(number, zone, *union(members)))
        return tuple(out)


def _body(page: _Page) -> list[Line]:
    return [line for line in page.lines if line.zone == "corpo"]


def _cy(box: Box) -> float:
    return (box[1] + box[3]) / 2
