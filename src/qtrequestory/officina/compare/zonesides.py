"""The zone text of a document as a side of the comparison (phase 2.5,
ruling F13: noise rules and slots apply to zone text exactly as to the body).

:func:`zone_side` gathers every zone compared page by page (:data:`COMPARED`)
into ONE key sequence per document: one *chunk* per (zone, page) with text,
in :data:`COMPARED` order then page order, each chunk a block of the
:class:`~sides.Side` (so a chunk ends a line: no rule matches across two
chunks). The target's chunks go through ``slots.find_slots`` like the body
(a fill-in leader in a footer swallows the generated value; "non è una
variabile" switches it off by anchor). A zone slot's anchor carries the zone's
name (``"footer: <context>"``): it never equals a body slot's with the same
words around it (re-review A3 I1).

The noise stage then runs on this side like on the body (``sides.noise_stage``,
presets and the user's spans). The user's rules are matched in the noise
guard's child (R46) on ``Prepared.noise_sides``: the body's keys, then —
after a line end — this side's keys, so a span found there maps back here by
subtracting :func:`offset` (matching is line by line: a span never crosses
from the body into the zones). :func:`chunks` cuts the side after noise back
into (zone, page) texts for ``zonediff``.

Deterministic and pure; stdlib only, no Qt, no pypdfium2.
"""
from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass, replace

from qtrequestory.officina.compare.extract_pdf import DocText
from qtrequestory.officina.compare.model import Anchor, Word
from qtrequestory.officina.compare.normalise import CHECK_OFF, units
from qtrequestory.officina.compare.sides import Side
from qtrequestory.officina.compare.slots import Slot, find_slots

__all__ = ["COMPARED", "ZoneSide", "ZoneText", "chunks", "offset", "split_spans", "zone_keys", "zone_side"]

#: The zones compared page by page, in the order their differences are listed on a page.
COMPARED = ("header", "spalla_sx", "spalla_dx", "footer", "numero_pagina", "filigrana")

Span = tuple[int, int]


@dataclass(frozen=True)
class ZoneSide:
    """One document's zone text: ``side`` (block = chunk number; the target's
    keys slotted), ``names`` the (zone, page) of each chunk, ``slots`` the
    target's slots (indices into ``side.keys``)."""

    side: Side
    names: tuple[tuple[str, int], ...]
    slots: tuple[Slot, ...] = ()


@dataclass(frozen=True)
class ZoneText:
    """One (zone, page) text after noise, for ``zonediff``: its keys and
    words, the slots by key index, and for each key the range of the keys
    before noise it stands for in ``before`` (the anchors are taken there, so
    switching a rule does not move them)."""

    keys: list[str]
    members: list[tuple[Word, ...]]
    slot_at: dict[int, Slot]
    before: list[str]
    ranges: list[tuple[int, int]]


def zone_keys(zone: str, words: Sequence[Word]) -> tuple[list[str], list[tuple[Word, ...]]]:
    """``normalise.units`` of a zone's words; in a shoulder (one line along
    the margin) a ``q`` followed by more text is the Wingdings box ``❏``
    without a Unicode mapping, as at the start of a line of the body."""
    keys, members = units(words)
    if zone in ("spalla_sx", "spalla_dx"):
        keys = [CHECK_OFF if key == "q" and k + 1 < len(keys) else key for k, key in enumerate(keys)]
    return keys, members


def zone_side(doc: DocText, *, target: bool, disabled: Collection[Anchor] = ()) -> ZoneSide:
    """The zone text of a zoned document (module doc)."""
    by: dict[tuple[str, int], list[Word]] = {}
    for word in doc.words:
        if word.zone in COMPARED:
            by.setdefault((word.zone, word.page), []).append(word)
    keys: list[str] = []
    members: list[tuple[Word, ...]] = []
    block: list[int] = []
    names: list[tuple[str, int]] = []
    slots: list[Slot] = []
    for zone in COMPARED:
        for page in sorted(p for z, p in by if z == zone):
            k, m = zone_keys(zone, by[(zone, page)])
            found: list[Slot] = []
            if target:
                k, m, found = find_slots(k, m, _unzoned(zone, disabled))
                found = [replace(s, anchor=_zoned(zone, s.anchor)) for s in found]
            if not k:
                continue
            slots += [replace(s, index=s.index + len(keys)) for s in found]
            block += [len(names)] * len(k)
            names.append((zone, page))
            keys += k
            members += m
    return ZoneSide(Side(keys, members, block), tuple(names), tuple(slots))


def _zoned(zone: str, anchor: Anchor | None) -> Anchor | None:
    """A zone slot's anchor: its context prefixed by the zone's name, so it
    never equals a body slot's (or another zone's) with the same words around."""
    return None if anchor is None else replace(anchor, context=f"{zone}: {anchor.context}".rstrip())


def _unzoned(zone: str, disabled: Collection[Anchor]) -> set[Anchor]:
    """The switched-off anchors of ``zone``'s slots, as ``find_slots`` numbers them (prefix removed)."""
    head = f"{zone}:"
    return {replace(a, context=a.context[len(head):].lstrip()) for a in disabled if a.context.startswith(head)}


def offset(body: Side) -> int:
    """Where the zone text starts in ``Prepared.noise_sides``' joined text:
    after the body's text and one line end (0 without a body)."""
    # ``noise`` joins keys with ONE character (a space or a line end) between two
    return sum(len(key) for key in body.keys) + len(body.keys) if body.keys else 0


def split_spans(body: Side, found: Sequence[Span]) -> tuple[list[Span], list[Span]]:
    """A user's rule's spans on ``noise_sides`` split into the body's and
    the zones' (shifted to the zone text's own joined text)."""
    if not body.keys:
        return [], list(found)
    start = offset(body)
    return [(s, e) for s, e in found if e < start], [(s - start, e - start) for s, e in found if s >= start]


def chunks(zoned: ZoneSide, final: Side, ranges: list[tuple[int, int]]) -> dict[tuple[str, int], ZoneText]:
    """The (zone, page) texts of ``final`` (``zoned.side`` after the noise
    stage; ``ranges`` = for each final key its range of keys before noise)."""
    before = zoned.side
    slot_at_old = {s.index: s for s in zoned.slots}
    out: dict[tuple[str, int], ZoneText] = {}
    for number, name in enumerate(zoned.names):
        span, old = final.span(number), before.span(number)
        if span is None or old is None:
            continue
        a, b = span
        o = old[0]
        local = [(start - o, end - o) for start, end in ranges[a:b]]
        slot_at = {k: slot_at_old[start + o] for k, (start, end) in enumerate(local)
                   if end - start == 1 and start + o in slot_at_old}
        out[name] = ZoneText(final.keys[a:b], final.members[a:b], slot_at, before.keys[old[0]:old[1]], local)
    return out
