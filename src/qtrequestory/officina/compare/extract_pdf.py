"""Words with their boxes from a PDF's text layer.

Characters come from PDFium through ``qtrequestory.officina.pdf`` (the only
module allowed to import pypdfium2, loaded lazily inside :func:`extract` so that
importing this module stays light). They are grouped into words on whitespace
and on horizontal gaps, then put in reading order: top to bottom, left to right
on each page.

Coordinates are PDF points with the origin at the TOP-left of the page (PDFium's
bottom-left origin is flipped), which is what the viewer draws highlights in.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

#: A page is "image only" when it holds an image and fewer words than this.
MIN_WORDS = 5
#: A horizontal gap wider than this share of the glyph height splits a word.
GAP_RATIO = 0.25


@dataclass(frozen=True)
class Word:
    text: str
    page: int
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(frozen=True)
class DocText:
    words: list[Word]
    page_sizes: list[tuple[float, float]]
    has_text: bool


def extract(path: Path) -> DocText:
    """The words of the PDF at ``path`` in reading order.

    Boxes are in points of the page as displayed (CropBox and /Rotate applied),
    origin top-left. Characters are grouped into words and lines in the text's
    own direction, so a rotated page still reads word by word. Characters whose
    centre lies outside the displayed page are dropped: they are not visible
    (cropped away, or drawn past the page edge and clipped).

    ``has_text`` is ``False`` when there is nothing to compare: no word at all,
    or a "scanned" document — every page has fewer than :data:`MIN_WORDS`
    words and at least one page carries an image.

    Raises ``qtrequestory.officina.pdf.PdfReadError`` (a ``ValueError`` with an
    Italian message) when the file is not a readable PDF, and
    ``FileNotFoundError`` when it does not exist.
    """
    from qtrequestory.officina import pdf  # lazy: loads pypdfium2

    words: list[Word] = []
    sizes: list[tuple[float, float]] = []
    counts: list[tuple[int, int]] = []  # (words, images) per page
    for number, page in enumerate(pdf.read_chars(Path(path))):
        sizes.append((page.width, page.height))
        visible = [c for c in page.chars if c[2] is None or _on_page(c[2], page.width, page.height)]
        page_words = [_Pending.word(p, number) for p in _reading_order(_group(visible))]
        counts.append((len(page_words), page.image_count))
        words.extend(page_words)
    scanned = all(n < MIN_WORDS for n, _ in counts) and any(images for _, images in counts)
    return DocText(words, sizes, bool(words) and not scanned)


Box = tuple[float, float, float, float]


@dataclass
class _Pending:
    """A word being built: text, box in text space (grouping), box on display."""
    text: str
    tbox: Box
    dbox: Box

    @staticmethod
    def word(p: _Pending, page: int) -> Word:
        return Word(p.text, page, *p.dbox)


def _on_page(box: Box, width: float, height: float) -> bool:
    """Whether a box's centre lies on the displayed page (else it is invisible)."""
    x0, y0, x1, y1 = box
    return 0 <= (x0 + x1) / 2 <= width and 0 <= (y0 + y1) / 2 <= height


def _union(a: Box, b: Box) -> Box:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _group(chars) -> list[_Pending]:
    words: list[_Pending] = []
    current: _Pending | None = None
    for ch, tbox, dbox in chars:
        if tbox is None:
            current = None
            continue
        if current is not None and not _breaks(current.tbox, tbox):
            current.text += ch
            current.tbox = _union(current.tbox, tbox)
            current.dbox = _union(current.dbox, dbox)
            continue
        current = _Pending(ch, tbox, dbox)
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
