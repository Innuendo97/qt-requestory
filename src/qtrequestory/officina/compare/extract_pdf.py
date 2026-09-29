"""Words with their boxes from a PDF's text layer.

Characters come from PDFium through ``qtrequestory.officina.pdf`` (the only
module allowed to import pypdfium2, loaded lazily inside :func:`extract` so that
importing this module stays light). They are grouped into words on whitespace
and on horizontal gaps, then put in reading order: top to bottom, left to right
on each page.

Each word carries its font size (points, as displayed) and whether it is bold,
sampled once per word (see ``pdf.PageChars.fonts``).

Phase 2.5 (spec §3.1):

* text a reader cannot see (white on white, a hidden layer, render mode 3)
  is kept apart in :attr:`DocText.invisible` — never compared;
* rotated text (margins at 90/270 degrees) is grouped by glyph ORIGIN and read
  along its own direction; each page's rotated words follow its horizontal
  ones, and :meth:`DocText.angle` gives a word's angle;
* :attr:`DocText.graphics` holds each page's paths and images for the zones.

Coordinates are PDF points with the origin at the TOP-left of the page (PDFium's
bottom-left origin is flipped), which is what the viewer draws highlights in.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

# ``Word`` lives in the comparison contract (phase 2 added ``size``/``bold``);
# re-exported here so ``extract_pdf.Word`` keeps working. The graphics types
# live in the pure ``compare.graphics`` and are re-exported too.
from qtrequestory.officina.compare.graphics import PageGraphics, PathShape
from qtrequestory.officina.compare.model import Word

__all__ = ["DocText", "GAP_RATIO", "LIGHT", "MIN_WORDS", "SCAN_COVER", "PageGraphics", "PathShape", "Word", "extract"]

#: A page is "image only" when it holds an image and fewer words than this.
MIN_WORDS = 5
#: A horizontal gap wider than this share of the glyph height splits a word.
GAP_RATIO = 0.25
#: A page is a scan when one image covers at least this share of it and it
#: has fewer than :data:`MIN_WORDS` visible words: its invisible text (the OCR
#: layer) is then kept as its words (ruling F10).
SCAN_COVER = 0.8
#: A word is drawn in a LIGHT colour when every channel of its fill is at
#: least this (pale grey to white), or its fill is less than half opaque.
LIGHT = 150

Box = tuple[float, float, float, float]


@dataclass(frozen=True)
class DocText:
    """An extracted document.

    ``rotated`` maps the index (in ``words``) of every word NOT written
    horizontally to its angle in whole degrees, clockwise as PDFium reports it
    (270: reads bottom-up, as in a left margin; 90: top-down); a word absent
    from it is horizontal (0). It is keyed by POSITION in ``words``: a stage
    that filters, reorders or slices the words into a new ``DocText`` must
    remap it (or first carry the angle onto the words, e.g. as their zone),
    else the angles silently move to other words (review A1, M2).
    ``invisible`` are the words nobody can see, in reading order, never
    compared — except on a scanned page, whose invisible OCR layer is its only
    reading (ruling F10, :data:`SCAN_COVER`). ``graphics`` has one entry per
    page (empty for a document built without it, e.g. by an HTML extractor).
    ``light`` holds the indices (in ``words``, like ``rotated``: remap it
    when filtering) of the visible words drawn in a light colour
    (:data:`LIGHT`; sampled on each word's first glyph) — a watermark's
    colour, or white on a coloured band (review A2 I1)."""

    words: list[Word]
    page_sizes: list[tuple[float, float]]
    has_text: bool
    rotated: dict[int, int] = field(default_factory=dict)
    invisible: list[Word] = field(default_factory=list)
    graphics: list[PageGraphics] = field(default_factory=list)
    light: set[int] = field(default_factory=set)

    def angle(self, index: int) -> int:
        """The angle of ``words[index]`` (0 = horizontal); IndexError off the list."""
        if not 0 <= index < len(self.words):
            raise IndexError(index)
        return self.rotated.get(index, 0)


def extract(path: Path) -> DocText:
    """The words of the PDF at ``path`` in reading order.

    Boxes are in points of the page as displayed (CropBox and /Rotate applied),
    origin top-left. Characters are grouped into words and lines in the text's
    own direction, so a rotated page still reads word by word, and so does
    rotated text on an upright page. Characters whose centre lies outside the
    displayed page are dropped: they are not visible (cropped away, or drawn
    past the page edge and clipped). Invisible characters (``pdf`` marks them
    after its ink test) become :attr:`DocText.invisible` words.

    ``has_text`` is ``False`` when there is nothing to compare: no word at all,
    or a "scanned" document — every page has fewer than :data:`MIN_WORDS`
    words and at least one page carries an image.

    Raises ``qtrequestory.officina.pdf.PdfReadError`` (a ``ValueError`` with an
    Italian message) when the file is not a readable PDF, and
    ``FileNotFoundError`` when it does not exist.
    """
    from qtrequestory.officina import pdf  # lazy: loads pypdfium2

    words: list[Word] = []
    rotated: dict[int, int] = {}
    light: set[int] = set()
    invisible: list[Word] = []
    sizes: list[tuple[float, float]] = []
    graphics: list[PageGraphics] = []
    counts: list[tuple[int, int]] = []  # (words, images) per page
    for number, page in enumerate(pdf.read_chars(Path(path))):
        sizes.append((page.width, page.height))
        graphics.append(page.graphics)
        visible_count = 0
        streams = _streams(page)
        if _scan(page) and _visible_words(streams) < MIN_WORDS:
            streams = _streams(page, ocr=True)
        for (hidden, angle), chars in sorted(streams.items()):
            pending = _reading_order(_group(chars))
            page_words = [p.word(number) for p in pending]
            if hidden:
                invisible.extend(page_words)
                continue
            if angle:
                rotated.update((len(words) + i, angle) for i in range(len(page_words)))
            light.update(len(words) + i for i, p in enumerate(pending) if _light(p.fill))
            words.extend(page_words)
            visible_count += len(page_words)
        counts.append((visible_count, page.image_count))
    scanned = all(n < MIN_WORDS for n, _ in counts) and any(images for _, images in counts)
    return DocText(words, sizes, bool(words) and not scanned, rotated, invisible, graphics, light)


#: The font of a word when the text layer gave no sample.
_NO_FONT = (0.0, False)
_SEPARATOR = (" ", None, None, None, None)


@dataclass
class _Pending:
    """A word being built: text, box in text space (grouping), box on display,
    and its font ``(size, bold)`` — sampled ONCE per word, on its first
    character (or the last sample before it, for a word split off a run by a
    gap: same run of glyphs, same font)."""
    text: str
    tbox: Box
    dbox: Box
    font: tuple[float, bool]
    fill: tuple[int, int, int, int] | None = None

    def word(self, page: int) -> Word:
        return Word(self.text, page, *self.dbox, *self.font)


def _light(fill: tuple[int, int, int, int] | None) -> bool:
    return fill is not None and (fill[3] < 128 or min(fill[:3]) >= LIGHT)


def _scan(page) -> bool:
    """Whether one image covers :data:`SCAN_COVER` of the page (a scan)."""
    area = page.width * page.height
    for x0, y0, x1, y1 in page.graphics.images:
        w = min(x1, page.width) - max(x0, 0.0)
        h = min(y1, page.height) - max(y0, 0.0)
        if area > 0 and w > 0 and h > 0 and w * h >= SCAN_COVER * area:
            return True
    return False


def _visible_words(streams: dict[tuple[bool, int], list]) -> int:
    return sum(len(_group(chars)) for (hidden, _), chars in streams.items() if not hidden)


def _streams(page, *, ocr: bool = False) -> dict[tuple[bool, int], list]:
    """The page's characters split by (invisible, angle), each stream in
    PDFium's order as ``(char, text box, display box, font sample, fill sample)``. A
    separator (whitespace, a generated break) ends the current word of EVERY
    stream; a switch between streams does not: whether a glyph continues a
    word stays a matter of geometry, so a visible word whose glyphs PDFium
    interleaved with a hidden one drawn on top stays whole. Off-page characters
    are dropped; a rotated character's text box is turned into its reading
    frame. ``ocr``: invisible characters are read as visible (a scan's OCR layer)."""
    n = len(page.chars)
    fonts = page.fonts or [None] * n
    fills = page.fills or [None] * n
    angles = page.angles or [0] * n
    origins = page.origins or [None] * n
    hidden = page.invisible or [False] * n
    if not len(fonts) == len(fills) == len(angles) == len(origins) == len(hidden) == n:
        raise ValueError("PageChars: parallel lists of different lengths")
    streams: dict[tuple[bool, int], list] = {}
    for (ch, tbox, dbox), sample, fill, angle, origin, dark in zip(page.chars, fonts, fills, angles, origins, hidden):
        if tbox is None or dbox is None:
            for stream in streams.values():
                if stream[-1] is not _SEPARATOR:
                    stream.append(_SEPARATOR)
            continue
        if not _on_page(dbox, page.width, page.height):
            continue  # dropped, as if it were not there (no separator)
        if angle:
            tbox = _reading_frame(tbox, origin, angle, sample)
        streams.setdefault((bool(dark) and not ocr, angle), []).append((ch, tbox, dbox, sample, fill))
    return streams


def _reading_frame(tbox: Box, origin: tuple[float, float] | None, angle: int,
                   sample: tuple[float, bool] | None) -> Box:
    """A rotated glyph's box turned so that its text reads left to right.

    ``tbox`` (the tight box) and ``origin`` are in text space (x right, y
    down); ``angle`` is clockwise. Along the text the box spans the glyph; across
    it the box is set from the ORIGIN (baseline) and the font size, the same
    for every glyph of a line — a dash or a comma, whose tight box sits off
    the line, then stays in it."""
    rad = math.radians(angle)
    cos, sin = math.cos(rad), math.sin(rad)
    x0, y0, x1, y1 = tbox
    along = [x * cos + y * sin for x in (x0, x1) for y in (y0, y1)]
    across = [y * cos - x * sin for x in (x0, x1) for y in (y0, y1)]
    size = sample[0] if sample and sample[0] > 0 else max(across) - min(across)
    if origin is None:
        return (min(along), min(across), max(along), max(across))
    base = origin[1] * cos - origin[0] * sin
    return (min(along), base - 0.8 * size, max(along), base + 0.2 * size)


def _on_page(box: Box, width: float, height: float) -> bool:
    """Whether a box's centre lies on the displayed page (else it is invisible)."""
    x0, y0, x1, y1 = box
    return 0 <= (x0 + x1) / 2 <= width and 0 <= (y0 + y1) / 2 <= height


def _union(a: Box, b: Box) -> Box:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _group(chars) -> list[_Pending]:
    words: list[_Pending] = []
    current: _Pending | None = None
    font: tuple[float, bool] = _NO_FONT
    colour: tuple[int, int, int, int] | None = None
    for ch, tbox, dbox, sample, fill in chars:
        if sample is not None:
            font = sample
        if fill is not None:
            colour = fill
        if tbox is None:
            current = None
            continue
        if current is not None and not _breaks(current.tbox, tbox):
            current.text += ch
            current.tbox = _union(current.tbox, tbox)
            current.dbox = _union(current.dbox, dbox)
            continue
        current = _Pending(ch, tbox, dbox, font, colour)
        words.append(current)
    return words


def _breaks(box: Box, char: Box) -> bool:
    """Whether a character (text space) does not continue the word ``box``."""
    x0, y0, x1, y1 = char
    height = max(box[3] - box[1], y1 - y0, 1e-6)
    centre = (y0 + y1) / 2
    if not box[1] <= centre <= box[3]:
        return True  # another line
    if x0 < box[2] - height:
        return True  # jumped back to the left
    return x0 - box[2] > GAP_RATIO * height


def _reading_order(words: list[_Pending]) -> list[_Pending]:
    """Cluster words into lines (by vertical centre in text space), top to
    bottom, then left to right."""
    lines: list[tuple[float, float, list[_Pending]]] = []  # (top, bottom, words)
    for word in sorted(words, key=lambda w: ((w.tbox[1] + w.tbox[3]) / 2, w.tbox[0])):
        centre = (word.tbox[1] + word.tbox[3]) / 2
        if lines and lines[-1][0] <= centre <= lines[-1][1]:
            lines[-1][2].append(word)
            continue
        lines.append((word.tbox[1], word.tbox[3], [word]))
    return [w for _, _, members in lines for w in sorted(members, key=lambda w: w.tbox[0])]
