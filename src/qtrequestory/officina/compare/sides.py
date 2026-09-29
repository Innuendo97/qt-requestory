"""The two sides of a comparison up to the noise stage (``pipeline``, spec §4).

:func:`prepare` runs the stages before noise — blocks, alignment and reading
order, normalisation, slots — and keeps what the rest of the pipeline needs
in a :class:`Prepared`. :meth:`Prepared.noise_sides` gives the EXACT keys and
line ends the noise stage matches on each side (:func:`noise_stage` builds
its line ends with the same :func:`line_ends`): the service hands them to the
noise guard's child, which matches the user's rules on them, so no user
regex ever runs in the application (ruling R46).

Phase 2.5 (spec §3.2, §3.6): two PDFs first go through the zone stage
(``zones.zone_pair``, both sides together), and only the words of the body
and the title (:data:`FLOW_ZONES`) become blocks: header, footer, shoulders,
page numbers and watermarks leave the flow, so a text reflowed across a
page break costs nothing again. The zoned documents are kept
(:attr:`Prepared.left` / :attr:`Prepared.right`: same words, same order,
``rotated`` and ``light`` still valid) for the zone-by-zone comparison
(``zonediff``), with each side's zone boxes. The column corridors of each
page are measured on the whole page on the side with more lines and
borrowed by the other side when they hold there too (``blocks.page_columns``).

Deterministic and pure; stdlib only, no Qt, no pypdfium2.
"""
from __future__ import annotations

import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from qtrequestory.officina.compare import moves
from qtrequestory.officina.compare.align import align
from qtrequestory.officina.compare.blocks import Layout, fits, layout, make_blocks, page_columns
from qtrequestory.officina.compare.extract_pdf import DocText
from qtrequestory.officina.compare.model import Anchor, Block, Word, ZoneBox
from qtrequestory.officina.compare.noise import apply
from qtrequestory.officina.compare.normalise import line_end, units
from qtrequestory.officina.compare.placeholders import rewrite
from qtrequestory.officina.compare.slots import Slot, find_slots
from qtrequestory.officina.compare.zones import zone_pair

if TYPE_CHECKING:
    from qtrequestory.officina.compare.zonesides import ZoneSide

__all__ = ["FLOW_ZONES", "Prepared", "Side", "line_ends", "noise_stage", "prepare"]

#: The zones whose words flow across pages as the body (spec §3.2).
FLOW_ZONES = frozenset({"corpo", "titolo"})

Pair = tuple[int | None, int | None]


@dataclass
class Side:
    """One side's units after every stage: ``block`` = the block index of
    each key (the index in that side's block list)."""

    keys: list[str]
    members: list[tuple[Word, ...]]
    block: list[int]

    def __post_init__(self) -> None:
        self.spans: dict[int, tuple[int, int]] = {}
        for k, b in enumerate(self.block):
            start, _ = self.spans.get(b, (k, k))
            self.spans[b] = (start, k + 1)
        self.breaks = {k for k in range(1, len(self.block)) if self.block[k] != self.block[k - 1]}

    def span(self, b: int) -> tuple[int, int] | None:
        """Key range ``[start, end)`` of block ``b``; None when it has no key."""
        return self.spans.get(b)


@dataclass
class Prepared:
    """Both sides before noise. Without text on a side (``has_text`` False)
    only the first group of fields is set. Two PDFs are the ZONED documents
    (``zones``), their blocks made of the flow words only, with each side's
    zone boxes (``left_zones`` / ``right_zones``, empty for HTML)."""

    left: DocText | Sequence[Block]
    right: DocText | Sequence[Block]
    left_blocks: list[Block]
    right_blocks: list[Block]
    left_pages: int
    right_pages: int
    left_has: bool
    right_has: bool
    left_label: str
    right_label: str
    left_zones: tuple[ZoneBox, ...] = ()
    right_zones: tuple[ZoneBox, ...] = ()
    left_zone: ZoneSide | None = None       # the zone text (``zonesides``), None without zones
    right_zone: ZoneSide | None = None
    pairs: list[Pair] = field(default_factory=list)
    moved: list[tuple[list[int], list[int]]] = field(default_factory=list)
    left_side: Side = field(default_factory=lambda: Side([], [], []))    # the target's slotted keys
    right_side: Side = field(default_factory=lambda: Side([], [], []))   # the generated keys in reading order
    slots: list[Slot] = field(default_factory=list)

    @property
    def has_text(self) -> bool:
        return self.left_has and self.right_has

    def noise_sides(self) -> tuple[tuple[list[str], list[int]], tuple[list[str], list[int]]]:
        """``((keys, line ends), (keys, line ends))`` of the target and the
        generated side, exactly as the noise stage matches them (empty
        without text): the body's keys, then — after a line end — the zone
        text's (ruling F13; ``zonesides.split_spans`` splits the spans back)."""
        return (_with_zones(self.left_side, self.left_zone), _with_zones(self.right_side, self.right_zone))


def prepare(left: DocText | Sequence[Block], right: DocText | Sequence[Block], *,
            disabled_slots: Collection[Anchor] = (), left_label: str = "target",
            right_label: str = "TO-BE", zones: bool = True) -> Prepared:
    """Stages 1–3 of the pipeline (see ``pipeline``'s module doc), after
    the zones for two PDFs (module doc). ``zones=False``: no zone stage, the
    whole text flows as the body (the body stages alone)."""
    boxes: tuple[tuple[ZoneBox, ...], tuple[ZoneBox, ...]] = ((), ())
    guides: tuple[dict | None, dict | None] = (None, None)
    lays: tuple[Layout | None, Layout | None] = (None, None)
    if zones and isinstance(left, DocText) and isinstance(right, DocText):
        zoned = zone_pair(left, right)
        left, right = zoned[0].doc, zoned[1].doc
        boxes = (zoned[0].boxes, zoned[1].boxes)
        lays = (layout(_flow(left)), layout(_flow(right)))
        guides = _borrowed(lays[0], lays[1])
    left_blocks, left_pages, left_has = _blocks(left, guides[0], lays[0])
    right_blocks, right_pages, right_has = _blocks(right, guides[1], lays[1])
    prepared = Prepared(left, right, left_blocks, right_blocks, left_pages, right_pages, left_has, right_has,
                        left_label, right_label, *boxes)
    if not prepared.has_text:
        return prepared
    if zones and isinstance(left, DocText) and isinstance(right, DocText):
        from qtrequestory.officina.compare.zonesides import zone_side  # zonesides builds on this module
        prepared.left_zone = zone_side(left, target=True, disabled=disabled_slots)  # type: ignore[arg-type]
        prepared.right_zone = zone_side(right, target=False)  # type: ignore[arg-type]
    prepared.pairs = align(list(left_blocks), list(right_blocks))
    order, prepared.moved = moves.reading_order(prepared.pairs, left_blocks, right_blocks)
    keys, members, block = _units(left_blocks, range(len(left_blocks)))
    keys = rewrite(keys)   # the target's {{…}}: a value as a leader (a slot), a conditional text without braces
    # HTML words may have no boxes: block boundaries are line ends for the slots too (final review I1)
    slotted, s_members, prepared.slots = find_slots(
        keys, members, disabled_slots, _block_ends(block) if not isinstance(left, DocText) else ())
    prepared.left_side = Side(slotted, s_members, _blocks_of(s_members, keys, members, block))
    prepared.right_side = Side(*_units(right_blocks, order))
    return prepared


def _with_zones(body: Side, zone: ZoneSide | None) -> tuple[list[str], list[int]]:
    ends = line_ends(body)
    if zone is None or not zone.side.keys:
        return list(body.keys), ends
    n = len(body.keys)
    joint = [n - 1] if n else []
    return [*body.keys, *zone.side.keys], [*ends, *joint, *(e + n for e in line_ends(zone.side))]


def line_ends(side: Side) -> list[int]:
    """Indices of the keys a line ends after: a block boundary, or a line
    end between the words' boxes."""
    keys, members, block = side.keys, side.members, side.block
    return [k for k in range(len(keys) - 1)
            if block[k] != block[k + 1]
            or (members[k] and members[k + 1] and line_end(members[k][-1], members[k + 1][0]))]


def noise_stage(side: Side, rules: Sequence[tuple[str, re.Pattern]]) -> tuple[
        Side, list[tuple[int, int, str]], list[tuple[int, int]]]:
    """The side after the noise ``rules`` (compiled presets, and
    ``noise.Found`` for a user's rule), the hits, and for each final key the
    range ``[start, end)`` of keys it stands for before noise."""
    keys = side.keys
    n_keys, n_members, hits = apply(keys, side.members, rules, set(line_ends(side)))
    ranges: list[tuple[int, int]] = []
    index = 0
    for first, last in _merged(hits):
        ranges += [(k, k + 1) for k in range(index, first)]
        ranges.append((first, last + 1))
        index = last + 1
    ranges += [(k, k + 1) for k in range(index, len(keys))]
    return Side(n_keys, n_members, [side.block[start] for start, _ in ranges]), hits, ranges


# ------------------------------------------------------------ helpers ---

def _blocks(doc: DocText | Sequence[Block], columns: dict | None = None,
            lines: Layout | None = None) -> tuple[list[Block], int, bool]:
    """(blocks, pages, has text) of one side: a PDF's blocks hold its flow
    words only, but a PDF with zone text alone still has text."""
    if isinstance(doc, DocText):
        blocks = make_blocks(_flow(doc), columns, lines=lines) if doc.has_text else []
        return blocks, len(doc.page_sizes), doc.has_text and bool(doc.words)
    blocks = list(doc)
    pages = max(b.page for b in blocks) + 1 if blocks else 0
    return blocks, pages, any(b.words for b in blocks)


def _flow(doc: DocText) -> list[Word]:
    return [w for w in doc.words if w.zone in FLOW_ZONES]


def _borrowed(left: Layout, right: Layout) -> tuple[dict, dict]:
    """Per page, the column corridors each side reads its body with: those
    of the side with more lines on that page (the other side's when it
    found none), when they hold on the other side too (``blocks.fits``),
    else each side's own (measured once, here)."""
    mine, theirs = page_columns(left), page_columns(right)
    out: tuple[dict, dict] = ({p: c for p, (c, _) in mine.items()}, {p: c for p, (c, _) in theirs.items()})
    for page in set(mine) & set(theirs):
        (a, na), (b, nb) = mine[page], theirs[page]
        # the side with more lines first; the other when it found none
        options = [(a, right), (b, left)] if na >= nb else [(b, left), (a, right)]
        for corridors, other in options:
            if corridors:
                if fits(other, page, corridors):
                    out[0][page] = corridors
                    out[1][page] = corridors
                break
    return out


def _units(blocks: Sequence[Block], order: Sequence[int]) -> tuple[list[str], list[tuple[Word, ...]], list[int]]:
    """Units over the blocks taken in ``order``, and each unit's block."""
    words: list[Word] = []
    owner: dict[int, int] = {}
    for b in order:
        for word in blocks[b].words:
            owner[id(word)] = b
            words.append(word)
    keys, members = units(words)
    return keys, members, [owner[id(group[0])] for group in members]


def _blocks_of(s_members: list[tuple[Word, ...]], keys: list[str], members: list[tuple[Word, ...]],
               block: list[int]) -> list[int]:
    """The block of each slotted key: its first word's; a probable slot (no
    word) the key's before it."""
    owner = {id(w): b for group, b in zip(members, block, strict=True) for w in group}
    out: list[int] = []
    for group in s_members:
        out.append(owner[id(group[0])] if group else (out[-1] if out else (block[0] if block else 0)))
    return out


def _block_ends(block: Sequence[int]) -> list[int]:
    """Indices of the keys a block ends after."""
    return [k for k in range(len(block) - 1) if block[k] != block[k + 1]]


def _merged(hits: list[tuple[int, int, str]]) -> list[tuple[int, int]]:
    """The key ranges ``noise.apply`` merged (hits sorted, sharing keys → one)."""
    groups: list[list[int]] = []
    for first, last, _ in sorted(hits):
        if groups and first <= groups[-1][1]:
            groups[-1][1] = max(groups[-1][1], last)
        else:
            groups.append([first, last])
    return [(first, last) for first, last in groups]
