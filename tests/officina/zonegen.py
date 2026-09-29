"""Test helper: synthetic extracted documents for the zone stage.

Builds :class:`DocText` values directly (words with boxes, sizes, angles and
page graphics) the way ``compare.extract_pdf`` lays them out — each page's
horizontal words first, then its rotated ones — without writing a PDF.
Synthetic text only (public repository). Coordinates: points, origin at the
top-left of an A4 page (595 x 842).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from qtrequestory.officina.compare.extract_pdf import DocText
from qtrequestory.officina.compare.graphics import PageGraphics, PathShape
from qtrequestory.officina.compare.model import Word

W, H = 595.0, 842.0
BLACK = (0, 0, 0, 255)
GREY = (179, 179, 179, 255)


@dataclass
class Page:
    """One page being built; every method returns ``self`` (chaining)."""

    flat: list[Word] = field(default_factory=list)
    turned: list[tuple[Word, int]] = field(default_factory=list)
    paths: list[PathShape] = field(default_factory=list)
    images: list[tuple[float, float, float, float]] = field(default_factory=list)
    pale: set[int] = field(default_factory=set)  # id() of the words drawn in a light colour

    def text(self, x: float, y: float, text: str, size: float = 8.0, *, bold: bool = False,
             light: bool = False) -> Page:
        """A line of horizontal words whose box top is ``y`` (``light``: drawn pale)."""
        for token in text.split():
            width = 0.5 * size * len(token)
            self.flat.append(Word(token, -1, x, y, x + width, y + 1.15 * size, size, bold))
            if light:
                self.pale.add(id(self.flat[-1]))
            x += width + 0.3 * size
        return self

    def body(self, y0: float, y1: float, *, x: float = 60.0, step: float = 12.0, words: int = 10) -> Page:
        """Ordinary body lines (8 pt) from ``y0`` down to ``y1``."""
        y, n = y0, 0
        while y <= y1:
            self.text(x, y, " ".join(f"corpo{n}p{k}" for k in range(words)))
            y += step
            n += 1
        return self

    def turned_text(self, x: float, y: float, text: str, angle: int = 270, size: float = 6.0, *,
                    light: bool = False) -> Page:
        """Words at ``angle`` (270 reads bottom-up from ``y``, 90 top-down;
        any other angle: a diagonal, boxes as a watermark's)."""
        for token in text.split():
            length = 0.5 * size * len(token)
            if angle == 270:
                box = (x, y - length, x + 1.15 * size, y)
                y -= length + 0.3 * size
            elif angle == 90:
                box = (x, y, x + 1.15 * size, y + length)
                y += length + 0.3 * size
            else:
                box = (x, y, x + 0.7 * length, y + 0.7 * length)
                x, y = x + 0.75 * length, y - 0.75 * length
            self.turned.append((Word(token, -1, *box, size), angle))
            if light:
                self.pale.add(id(self.turned[-1][0]))
        return self

    def divider(self, y: float, x0: float = 28.0, x1: float = 568.0) -> Page:
        self.paths.append(PathShape((x0, y - 3, x1, y + 3), 2.83, None, BLACK, 2))
        return self

    def logo(self, x0: float, y0: float, x1: float, y1: float, letters: int = 1) -> Page:
        """A logo drawn as ``letters`` black glyph-like paths side by side."""
        step = (x1 - x0) / letters
        for k in range(letters):
            self.paths.append(PathShape((x0 + k * step, y0, x0 + (k + 1) * step - 1, y1), 0.0, BLACK, None, 40 + k))
        return self

    def image(self, x0: float, y0: float, x1: float, y1: float) -> Page:
        self.images.append((x0, y0, x1, y1))
        return self

    def watermark_path(self, x0: float, y0: float, x1: float = 0, y1: float = 0) -> Page:
        """A light-grey glyph-like path (the "DEV" mark of a test generator)."""
        self.paths.append(PathShape((x0, y0, x1 or x0 + 79, y1 or y0 + 57), 0.0, GREY, None, 83))
        return self

    def rect(self, x0: float, y0: float, x1: float, y1: float, fill=(229, 229, 229, 255)) -> Page:
        self.paths.append(PathShape((x0, y0, x1, y1), 0.0, fill, None, 5))
        return self


def build(*pages: Page, invisible: list[Word] = ()) -> DocText:
    """The pages as an extracted document."""
    words: list[Word] = []
    rotated: dict[int, int] = {}
    light: set[int] = set()
    for number, page in enumerate(pages):
        ordered = sorted(page.flat, key=lambda w: (w.y0, w.x0))
        for word in ordered:
            if id(word) in page.pale:
                light.add(len(words))
            words.append(_on(word, number))
        for word, angle in page.turned:
            rotated[len(words)] = angle
            if id(word) in page.pale:
                light.add(len(words))
            words.append(_on(word, number))
    return DocText(words, [(W, H)] * len(pages), bool(words), rotated, list(invisible),
                   [PageGraphics(tuple(p.paths), tuple(p.images)) for p in pages], light)


#: Body words carry their line and page as LETTERS: the zone rules compare
#: lines with numbers masked, and real body lines do not repeat page to page.
_LETTERS = str.maketrans("0123456789", "abcdefghij")


def _on(word: Word, page: int) -> Word:
    text = word.text
    if text.startswith("corpo"):
        text = "corpo" + text[5:].translate(_LETTERS) + "abcdefghij"[page % 10]
    return Word(text, page, word.x0, word.y0, word.x1, word.y1, word.size, word.bold)


def zones_of(doc: DocText, text: str) -> list[str]:
    """The zone of every word of ``doc`` in ``text`` (in document order)."""
    wanted = text.split()
    return [w.zone for w in doc.words if w.text in wanted]


def zone_text(doc: DocText, zone: str, page: int | None = None) -> str:
    return " ".join(w.text for w in doc.words if w.zone == zone and (page is None or w.page == page))
