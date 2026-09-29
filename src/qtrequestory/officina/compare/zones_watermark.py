"""Text watermarks for the zone stage (``compare.zones``, spec §3.2, D4).

``filigrana`` is not counted by default, so a false watermark HIDES content
(review A2 I1, R1). Large words are only candidates; a cluster of them is a
watermark when light (off a dark background) or diagonal and repeated on
another page, and never when the other side holds different large text in
the same slot.

Deterministic and pure; stdlib only, no Qt, no pypdfium2.
"""
from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass

from qtrequestory.officina.compare.graphics import PageGraphics
from qtrequestory.officina.compare.model import Word
from qtrequestory.officina.compare.zones_page import size_of, union

__all__ = ["Mark", "disagree", "watermark_marks"]

#: Two watermark clusters repeat when their sizes differ by at most this share
#: and their centres by at most this share of the page's width / height.
_SAME_SIZE = 0.10
_SAME_PLACE = 0.10
#: A word printed on a filled shape darker than this (min channel) or on an
#: image is on a background: its light colour is white on a band, not a watermark.
_DARK_BACKGROUND = 200


@dataclass
class Mark:
    """A cluster of watermark candidates on one page: its words, text
    (casefolded), median size, centre and page size; ``accepted`` when it
    is a watermark (``watermark_marks``, then ``disagree`` across the sides)."""

    page: int
    members: list[int]
    text: str
    size: float
    box: tuple[float, float, float, float]
    page_size: tuple[float, float]
    accepted: bool = False

    @property
    def centre(self) -> tuple[float, float]:
        return (self.box[0] + self.box[2]) / 2, (self.box[1] + self.box[3]) / 2

    def meets(self, other: Mark) -> bool:
        """Same slot: similar size (±10 %) and place (±10 % of the page)."""
        (cx, cy), (ox, oy) = self.centre, other.centre
        width, height = self.page_size
        return (abs(other.size - self.size) <= _SAME_SIZE * max(self.size, other.size)
                and abs(ox - cx) <= _SAME_PLACE * width and abs(oy - cy) <= _SAME_PLACE * height)

    def shares_slot(self, other: Mark) -> bool:
        """Same slot for texts that DIFFER (review A2 re-review 2): the boxes
        overlap, or they start at the same top-left corner (±10 % of the
        page). A changed text changes length, so its centre and size move:
        neither is compared."""
        a, b = self.box, other.box
        if a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]:
            return True
        width, height = self.page_size
        return abs(a[0] - b[0]) <= _SAME_PLACE * width and abs(a[1] - b[1]) <= _SAME_PLACE * height


def watermark_marks(words: Sequence[Word], candidates: dict[int, list[int]], light: set[int],
                    rotated: dict[int, int], graphics: Sequence[PageGraphics],
                    sizes: Sequence[tuple[float, float]]) -> list[Mark]:
    """The ``candidates`` (word indices per page: huge, or large and
    diagonal) in clusters, each ``accepted`` as a watermark or not (review
    A2 I1/R1: ``filigrana`` is not counted by default, so a false one hides
    content). Accepted: all its words ``light`` and none on a dark
    background; or DIAGONAL text whose cluster repeats (same text, size and
    place) on another page. A large horizontal or vertical text that is not
    light stays body (a heading, a price): a visible false difference is
    the safe direction. See also :func:`disagree`."""
    marks = []
    for page, indices in sorted(candidates.items()):
        for members in _clusters(words, indices):
            marks.append(Mark(page, members, " ".join(words[i].text.casefold() for i in members),
                              _median_size(words, members), _box(words, members),
                              sizes[page] if page < len(sizes) else (1.0, 1.0)))
    for mark in marks:
        page_graphics = graphics[mark.page] if mark.page < len(graphics) else PageGraphics()
        pale = all(i in light and not _on_background(words[i], page_graphics) for i in mark.members)
        diagonal = all(rotated.get(i, 0) not in (0, 90, 180, 270) for i in mark.members)
        repeated = any(other.page != mark.page and other.text == mark.text and mark.meets(other)
                       for other in marks)
        mark.accepted = pale or (diagonal and repeated)
    return marks


def disagree(left: list[Mark], right: list[Mark]) -> None:
    """Across the two sides: a watermark whose slot on the other side (same
    page, overlapping box or same top-left corner) holds DIFFERENT large text is content — a
    price, a heading that changed —, so both go back to the body (review A2
    R1). A watermark identical on both sides, or present on one side only,
    stays a watermark."""
    demote = []
    for this, other_side in ((left, right), (right, left)):
        for mark in this:
            if not mark.accepted:
                continue
            for other in other_side:
                if other.page == mark.page and other.text != mark.text and mark.shares_slot(other):
                    demote += [mark, other]
    for mark in demote:
        mark.accepted = False


def _clusters(words: Sequence[Word], indices: list[int]) -> list[list[int]]:
    """``indices`` grouped by proximity (boxes within one font size)."""
    groups: list[list[int]] = []
    for i in sorted(indices, key=lambda i: (words[i].y0, words[i].x0, i)):
        w = words[i]
        for group in groups:
            if any(_near(w, words[j]) for j in group):
                group.append(i)
                break
        else:
            groups.append([i])
    return groups


def _near(a: Word, b: Word) -> bool:
    reach = max(size_of(a), size_of(b))
    return a.x0 - reach <= b.x1 and b.x0 - reach <= a.x1 and a.y0 - reach <= b.y1 and b.y0 - reach <= a.y1


def _median_size(words: Sequence[Word], members: list[int]) -> float:
    return statistics.median(size_of(words[i]) for i in members)


def _box(words: Sequence[Word], members: list[int]) -> tuple[float, float, float, float]:
    return union((words[i].x0, words[i].y0, words[i].x1, words[i].y1) for i in members)


def _on_background(word: Word, graphics: PageGraphics) -> bool:
    cx, cy = (word.x0 + word.x1) / 2, (word.y0 + word.y1) / 2
    for path in graphics.paths:
        x0, y0, x1, y1 = path.box
        fill = path.fill
        if (fill is not None and fill[3] > 0 and min(fill[:3]) < _DARK_BACKGROUND
                and x0 <= cx <= x1 and y0 <= cy <= y1):
            return True
    return any(x0 <= cx <= x1 and y0 <= cy <= y1 for x0, y0, x1, y1 in graphics.images)
