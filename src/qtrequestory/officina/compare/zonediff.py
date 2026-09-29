"""The zone-by-zone comparison (phase 2.5, spec §3.2, D4; task A3).

The body and the title flow across pages (``sides``); every other zone
(:data:`COMPARED`) is compared PAGE BY PAGE, zone by zone, on the zoned
documents of both sides:

* a page present on both sides is compared with the same page. A page only
  one side has (another page count — itself the pipeline's ``pagine``
  difference) whose zone reads exactly like a compared page's zone on its
  side repeats that page's differences (they gain a page); any other zone
  text there is compared with nothing (a ``mancante`` / ``in_piu``);
* the zone's text on that page is ``zonesides``' (zone, page) text: the
  same normalisation as the body, the target's fill-in slots, and the noise
  rules (presets and the user's) applied exactly as to the body (ruling
  F13); the word diff (``worddiff.changes``, with the slots) runs on it and
  each change is cut at far gaps (``spread``);
* class: a TEXT change is ``zona`` (it counts in every profile); a change of
  style or spacing keeps its class (``stile``, ``spaziatura``); what a slot
  swallows is ``variabile`` and what a rule covers ``rumore``, as in the
  body; in a zone set aside (``aside``: by default page number and
  watermark, D4) every other change is ``arredo`` (no verdict, does not
  count; ruling F3);
* the SAME difference on several pages (same zone, operation, class, texts
  and context) is ONE difference with ``detail`` "uguale su N pagine",
  holding the words of every page (``left_text`` / ``right_text`` and the
  spans are the first page's); a zone slot is ONE difference over its pages
  whatever value fills it on each (``detail`` "su N pagine" when the values
  differ): one "non è una variabile" decides it on every page (re-review A3 I1);
* a text missing from a zone on one page and added to the same zone on
  another page (a footnote reflowed) is ONE ``spostato`` (``composizione``);
* in a shoulder, a ``q`` followed by more text reads as the box ``❏`` (a
  Wingdings glyph without a Unicode mapping); a page number's context has
  its digits masked, so «1 di 2 → 1 di 3» on every page is one difference;
* ``tipo`` (``tipi``): ``zona`` when the zone has text on one side only on
  that page, else the kind of the change.

The anchor is taken in the zone's own text BEFORE noise (switching a rule
does not move it): ``context`` = the zone name and up to ``CONTEXT_KEYS``
target keys around the change (one for an insertion), ``target_text`` = the
target keys — no page, so a difference keeps its anchor when it moves to
another page or its page count changes. A slot's difference has the slot's
anchor (``slots.slot_anchor``: "non è una variabile" works in a zone too).

Deterministic and pure; stdlib only, no Qt, no pypdfium2.
"""
from __future__ import annotations

import dataclasses
import re
from collections.abc import Collection
from dataclasses import dataclass, field

from qtrequestory.officina.compare import moves
from qtrequestory.officina.compare.anchor_keys import CONTEXT_KEYS
from qtrequestory.officina.compare.classify import classify
from qtrequestory.officina.compare.display import empty_at
from qtrequestory.officina.compare.model import NO_VERDICT, Anchor, Diff, Word
from qtrequestory.officina.compare.slots import slot_anchor
from qtrequestory.officina.compare.spread import split
from qtrequestory.officina.compare.tipi import tipo_of
from qtrequestory.officina.compare.variables import NO_SITE, Site, site
from qtrequestory.officina.compare.worddiff import changes, char_spans
from qtrequestory.officina.compare.zonesides import COMPARED, ZoneText

__all__ = ["COMPARED", "PAGES_DETAIL", "VALUES_DETAIL", "zone_diffs"]

#: The detail of a difference found identical on several pages…
PAGES_DETAIL = "uguale su {n} pagine"
#: …and of a zone slot filled on several pages with values that differ.
VALUES_DETAIL = "su {n} pagine"
#: Zones whose text is one line along the margin or a mark: never cut at gaps.
_UNCUT = frozenset({"spalla_sx", "spalla_dx", "filigrana", "numero_pagina"})
#: Words of display context on each side.
_WIDTH = 5
_DIGITS = re.compile(r"\d+")
_EMPTY = ZoneText([], [], {}, [], [])
Texts = dict[tuple[str, int], ZoneText]


@dataclass
class _Found:
    """One zone difference on one page (before grouping)."""

    op: str
    klass: str
    zone: str
    left: tuple[Word, ...]
    right: tuple[Word, ...]
    left_keys: tuple[str, ...]
    right_keys: tuple[str, ...]
    anchor: Anchor
    before: str
    after: str
    alone: bool
    at: tuple[int, float, float, float, float] | None = None
    i1: int = 0
    i2: int = 0
    j1: int = 0
    j2: int = 0
    pages: list[int] = field(default_factory=list)
    varies: bool = False       # grouped pages whose generated values differ (a slot)
    site: Site = NO_SITE       # the words around it (``variables.site``), on its first page


def zone_diffs(left: Texts, right: Texts, pages: tuple[int, int],
               aside: Collection[str]) -> list[tuple[int, Diff, Site]]:
    """The zone differences of two documents' (zone, page) texts
    (``zonesides.chunks``) as ``(page, diff, site)`` (``site``: the words
    around it, for the variables' second pass), in page order then
    :data:`COMPARED` order; ids are 0 (the pipeline numbers them). ``pages``
    = each side's page count; ``page`` is the target page (the generated one
    for a text only there)."""
    found: list[_Found] = []
    na, nb = pages
    for zone in COMPARED:
        seen: tuple[dict, dict] = ({}, {})   # per side: zone keys of a compared page → its differences
        for k in range(min(na, nb)):
            mine, theirs = left.get((zone, k), _EMPTY), right.get((zone, k), _EMPTY)
            items = _compare(zone, mine, theirs, aside)
            found += items
            seen[0].setdefault(tuple(mine.keys), items)
            seen[1].setdefault(tuple(theirs.keys), items)
        for k in range(nb, na):
            found += _extra(zone, left.get((zone, k), _EMPTY), seen[0], 0, aside)
        for k in range(na, nb):
            found += _extra(zone, right.get((zone, k), _EMPTY), seen[1], 1, aside)
    found = _moved(_grouped(found), aside)
    out: list[tuple[int, Diff, Site]] = []
    for item in found:
        out.append((_first_page(item), _diff(item), item.site))
    order = {zone: k for k, zone in enumerate(COMPARED)}
    out.sort(key=lambda pd: (pd[0], order.get(pd[1].zone, 0)))
    return out


def _extra(zone: str, text: ZoneText, seen: dict, side: int, aside: Collection[str]) -> list[_Found]:
    """The zone of a page only one side has (another page count). The same
    text as a compared page of that side repeats that page's differences on
    this page too (they become "uguale su N pagine"); any other text is
    compared with nothing."""
    if not text.keys:
        return []
    known = seen.get(tuple(text.keys))
    if known is None:
        return _compare(zone, text, _EMPTY, aside) if side == 0 else _compare(zone, _EMPTY, text, aside)
    out: list[_Found] = []
    for item in known:
        start, end = (item.i1, item.i2) if side == 0 else (item.j1, item.j2)
        mine = tuple(w for group in text.members[start:end] for w in group)
        if mine:
            out.append(dataclasses.replace(item, left=mine, right=()) if side == 0
                       else dataclasses.replace(item, left=(), right=mine))
    return out


def _compare(zone: str, left: ZoneText, right: ZoneText, aside: Collection[str]) -> list[_Found]:
    """The differences of one zone on one page pair."""
    lk, lm, rk, rm = left.keys, left.members, right.keys, right.members
    if not lk and not rk:
        return []
    alone = not lk or not rk
    out: list[_Found] = []
    for change in changes(lk, lm, rk, rm, left.slot_at):
        parts = [change] if zone in _UNCUT else split(change, lk, lm, rk, rm)
        for c in parts:
            klass = "rumore" if c.noise else classify(c.op, lk[c.i1:c.i2], rk[c.j1:c.j2],
                                                       slot=c.slot is not None, style=c.style)
            if zone in aside and klass not in NO_VERDICT:
                klass = "arredo"
            elif klass == "testo":
                klass = "zona"
            words_l = c.slot.words if c.slot else tuple(w for group in lm[c.i1:c.i2] for w in group)
            words_r = tuple(w for group in rm[c.j1:c.j2] for w in group)
            anchor, left_keys = _anchor(zone, left, c, klass)
            before = " ".join(w.text for group in lm[:c.i1] for w in group).split()[-_WIDTH:]
            after = " ".join(w.text for group in lm[c.i2:] for w in group).split()[:_WIDTH]
            at = None
            if bool(words_l) != bool(words_r):
                at = empty_at(rm, c.j1) if words_l else empty_at(lm, c.i1)
            out.append(_Found(c.op, klass, zone, words_l, words_r, left_keys, tuple(rk[c.j1:c.j2]),
                              anchor, " ".join(before), " ".join(after), alone, at, c.i1, c.i2, c.j1, c.j2,
                              site=site(lm, rm, c.i1, c.i2, c.j1, c.j2)))
    return out


def _anchor(zone: str, text: ZoneText, c, klass: str) -> tuple[Anchor, tuple[str, ...]]:
    """The anchor of a change (module doc) and the target keys it covers,
    both on the text before noise."""
    old = text.before
    if c.slot is not None:
        return slot_anchor(old, c.slot), tuple(old[r[0]] for r in text.ranges[c.i1:c.i2])
    start = text.ranges[c.i1][0] if c.i1 < len(text.ranges) else len(old)
    end = text.ranges[c.i2 - 1][1] if c.i2 > c.i1 else start
    width = 1 if end == start else CONTEXT_KEYS
    context = " ".join([*old[max(0, start - width):start], *old[end:end + width]])
    if zone == "numero_pagina":
        context = _DIGITS.sub("#", context)   # «1 di» and «2 di»: the same change on every page
    keys = tuple(old[start:end])
    return Anchor(c.op, klass, f"{zone}: {context}".rstrip(), " ".join(keys)), keys  # type: ignore[arg-type]


def _grouped(found: list[_Found]) -> list[_Found]:
    """Identical differences on several pages as one (module doc)."""
    groups: dict[tuple, _Found] = {}
    for item in found:
        # a slot is one decision for its zone: grouped over the pages whatever value fills it
        values = () if item.klass == "variabile" else item.right_keys
        key = (item.zone, item.op, item.klass, item.left_keys, values, item.anchor)
        page = _first_page(item)
        known = groups.get(key)
        if known is None:
            item.pages = [page]
            groups[key] = item
        elif page not in known.pages:
            known.pages.append(page)
            known.varies = known.varies or item.right_keys != known.right_keys
            known.left += item.left
            known.right += item.right
    return list(groups.values())


def _moved(found: list[_Found], aside: Collection[str]) -> list[_Found]:
    """A zone text missing on one page and added on another: one move
    (``arredo`` in a zone set aside)."""
    deleted = [f for f in found if f.op == "mancante"]
    inserted = [f for f in found if f.op == "in_piu"]
    matched = moves.text_moves([list(f.left_keys) for f in deleted], [list(f.right_keys) for f in inserted])
    gone: set[int] = set()
    out: list[_Found] = []
    for d, k in matched:
        a, b = deleted[d], inserted[k]
        if a.zone != b.zone or {w.page for w in a.left} == {w.page for w in b.right}:
            continue
        gone.update((id(a), id(b)))
        klass = "arredo" if a.zone in aside else "composizione"
        anchor = dataclasses.replace(a.anchor, op="spostato", klass=klass)
        out.append(dataclasses.replace(a, op="spostato", klass=klass, right=b.right,
                                       right_keys=b.right_keys, alone=False, anchor=anchor))
    return [f for f in found if id(f) not in gone] + out


def _first_page(item: _Found) -> int:
    words = item.left or item.right
    return min(w.page for w in words) if words else 0


def _diff(item: _Found) -> Diff:
    first = _first_page(item)
    left_one = tuple(w for w in item.left if w.page == min((x.page for x in item.left), default=first))
    right_one = tuple(w for w in item.right if w.page == min((x.page for x in item.right), default=first))
    left_text = " ".join(w.text for w in left_one)
    right_text = " ".join(w.text for w in right_one)
    spans: tuple = ((), ())
    if item.op == "cambiato" and item.klass not in ("stile", "rumore", "variabile"):
        spans = char_spans(left_text, right_text)
    detail = ""
    if len(item.pages) > 1:
        detail = (VALUES_DETAIL if item.varies else PAGES_DETAIL).format(n=len(item.pages))
    diff = Diff(0, item.op, item.klass, item.left, item.right, left_text, right_text,  # type: ignore[arg-type]
                spans[0], spans[1], item.anchor, detail, item.before, item.after,
                zone=item.zone,  # type: ignore[arg-type]
                empty_at=item.at if bool(item.left) != bool(item.right) else None)
    return dataclasses.replace(diff, tipo=tipo_of(diff, zone_alone=item.alone))
