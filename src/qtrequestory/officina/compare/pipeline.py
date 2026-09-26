"""The staged comparison (spec §4): every stage, composed.

:func:`compare_docs` compares a TARGET (``left``) with one generated version
(``right``): a PDF's :class:`DocText` (blocked by ``blocks.make_blocks``) or
a :class:`Block` list (HTML, from ``extract_html``, used as it is). In order:

1. **blocks** and **align** — then the generated blocks are read in their
   own order, except a block of a STRONG pair (content ratio ≥ 0.85) that is
   out of order: it is read at its partner's place and reported as a move
   (rulings R20, R26). Weakly paired and unpaired blocks stay where they are;
2. **normalise** — comparison units over each side's whole block sequence;
3. **slots** — on the target units (``slots.find_slots``, with the case's
   ``disabled_slots``); the anchors of ``variabile`` differences are the
   slots' own (``slots.slot_anchor``, ruling R2 amended);
4. **noise** — the enabled valid ``rules`` on both sides (``noise.apply``,
   with the line ends); a rule that cannot be used is named in ``note``.
   The user's own rules never run here (ruling R46): the service matches
   them in the noise guard's child on the exact keys and line ends of this
   stage (``sides.Prepared.noise_sides``) and passes the spans found as
   ``custom_hits``, applied after ``rules``. Stages 1–3 are
   ``sides.prepare``, 4–8 :func:`finish`; :func:`compare_docs` is both;
5. **worddiff** — one ``SequenceMatcher`` over the whole unit sequences,
   fixed on the aligned blocks with identical keys, then by character inside
   each ``cambiato`` (``worddiff.changes``, ``worddiff.char_spans``). Only a
   stretch longer than ``worddiff.PATIENCE_MIN`` keys with no word occurring
   once on each side (a long form of identical rows) is cut at the starts of
   its aligned block pairs — pair by pair there, to stay in the time budget;
6. **moves** — aligned blocks out of order, and a ``mancante`` and an
   ``in_piu`` with the same text, become ONE ``spostato`` each (a weak pair
   never moves);
7. **sections** — blocks the alignment left unpaired are hard boundaries
   of the word diff (ruling R27), so a missing block is never swallowed by a
   neighbouring change; a ``mancante`` (``in_piu``) that covers whole target
   (generated) blocks holding at least two lines between them becomes ONE
   ``sezione_assente`` (``sezione_in_piu``) with ``detail="N righe"``; an HTML
   block counts as one line. Different page counts (PDF only) give one
   ``pagine`` difference, first in the list;
8. **classify** — ``classify.classify``.

Anchors are taken on the TARGET's slotted keys BEFORE noise (so switching a
noise rule on does not move them): ``context`` = the :data:`CONTEXT_KEYS`
target keys before and after the difference (for an insertion, the ONE key
before and the ONE after it), ``target_text`` = the target keys of the
difference (a slot as its leader). ``context_before`` / ``context_after`` are
the display words around the change (``display.context``, R33). Every anchor
then goes through ``anchors.disambiguate`` in target order, and the differences are numbered
1..n in that order. Spans are given for ``cambiato`` only (the characters that
changed); a missing, extra or moved text is changed as a whole.

HTML (two ``Block`` lists) also gets the ``link`` differences of the critical
attributes (``linkdiff.link_changes``, URLs normalised with ``link_drop``: the
tracking rule when that noise preset is on): one ``cambiato`` of class
``link`` per attribute, ``left_text`` / ``right_text`` = the two values,
``detail`` = ``"href: a → b"``, anchored like a change of its target block
with ``target_text`` = ``"href: <target value>"``; the words are the blocks'.

Deterministic and pure; stdlib only, no Qt, no pypdfium2.
"""
from __future__ import annotations

import dataclasses
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass

from qtrequestory.officina.compare import display, moves, urls
from qtrequestory.officina.compare.anchor_keys import CONTEXT_KEYS, TargetKeys
from qtrequestory.officina.compare.anchors import disambiguate
from qtrequestory.officina.compare.classify import classify, is_noise
from qtrequestory.officina.compare.extract_pdf import DocText
from qtrequestory.officina.compare.linkdiff import link_changes
from qtrequestory.officina.compare.model import Anchor, Block, Comparison, Diff, Op, Word
from qtrequestory.officina.compare.noise import Found, compile_rules
from qtrequestory.officina.compare.normalise import line_end
from qtrequestory.officina.compare.sides import Pair, Prepared, noise_stage, prepare
from qtrequestory.officina.compare.sides import Side as _Side
from qtrequestory.officina.compare.slots import Slot, slot_anchor
from qtrequestory.officina.compare.worddiff import Change, changes, char_spans
from qtrequestory.officina.model_review import NoiseRule

__all__ = ["CONTEXT_KEYS", "CustomHits", "compare_docs", "finish"]


@dataclass
class _Raw:
    """A difference before anchoring: key ranges on the final sides."""

    op: Op
    i1: int
    i2: int
    j1: int
    j2: int
    left: tuple[Word, ...]
    right: tuple[Word, ...]
    slot: Slot | None = None
    noise: bool = False
    style: bool = False
    detail: str = ""
    link: tuple[str, str, str] | None = None     # (name, target value, generated value)


#: A user's rule matched in the noise guard's child (R46): its name, then its
#: ``(start, end)`` spans on the target's and on the generated side's noise
#: text (``sides.Prepared.noise_sides``, ``noise.spans``).
CustomHits = tuple[str, Sequence[tuple[int, int]], Sequence[tuple[int, int]]]


def compare_docs(left: DocText | Sequence[Block], right: DocText | Sequence[Block], *,
                 rules: Sequence[NoiseRule] = (), custom_hits: Sequence[CustomHits] = (),
                 disabled_slots: Collection[Anchor] = (), left_label: str = "target", right_label: str = "TO-BE",
                 link_drop: Callable[[str], bool] = urls.keep_all) -> Comparison:
    """The comparison of ``left`` (the target) with ``right`` (see module doc)."""
    return finish(prepare(left, right, disabled_slots=disabled_slots, left_label=left_label,
                          right_label=right_label),
                  rules=rules, custom_hits=custom_hits, link_drop=link_drop)


def finish(prepared: Prepared, *, rules: Sequence[NoiseRule] = (), custom_hits: Sequence[CustomHits] = (),
           link_drop: Callable[[str], bool] = urls.keep_all) -> Comparison:
    """Stages 4–8 on ``prepared`` (``sides.prepare``). ``rules`` are compiled
    and matched here: only the built-in presets (tested) go there. The user's
    rules come as ``custom_hits``, applied after ``rules`` in their order,
    matched elsewhere on :meth:`~sides.Prepared.noise_sides` (R46)."""
    p = prepared
    left, right = p.left, p.right
    left_blocks, right_blocks, left_pages, right_pages = p.left_blocks, p.right_blocks, p.left_pages, p.right_pages
    usable, errors = compile_rules(rules)
    notes = [f"regola «{name}» ignorata: {message}" for name, message in errors.items()]
    if not p.has_text:
        notes = [_label(label) for label, has in ((p.left_label, p.left_has), (p.right_label, p.right_has))
                 if not has] + notes
        return Comparison((), p.left_has, p.right_has, left_pages, right_pages, "; ".join(notes), 0, ())

    pairs, slots = p.pairs, p.slots
    l_rules = [*usable, *((name, Found(found)) for name, found, _ in custom_hits)]
    r_rules = [*usable, *((name, Found(found)) for name, _, found in custom_hits)]
    l_final, l_hits, l_ranges = noise_stage(p.left_side, l_rules)
    r_final, r_hits, _ = noise_stage(p.right_side, r_rules)
    old_to_new = {old: new for new, (start, end) in enumerate(l_ranges) for old in range(start, end)}
    slot_at = {old_to_new[s.index]: s for s in slots}

    fixed, cuts = _sync(pairs, l_final, r_final)
    bounds = (_unmatched(l_final, [i for i, j in pairs if j is None and i is not None]),
              _unmatched(r_final, [j for i, j in pairs if i is None and j is not None]))
    found = changes(l_final.keys, l_final.members, r_final.keys, r_final.members, slot_at, fixed=fixed,
                    cuts=cuts, breaks=(l_final.breaks, r_final.breaks), bounds=bounds,
                    line_starts=r_final.breaks if not isinstance(right, DocText) else ())
    raws = _moves(found, p.moved, left_blocks, right_blocks, l_final, r_final)
    raws = [_section(raw, l_final, r_final) for raw in raws]
    if not isinstance(left, DocText) and not isinstance(right, DocText):
        raws += [_Raw("cambiato", c.i1, c.i2, c.j1, c.j2, c.left, c.right, detail=f"{c.name}: {c.old} → {c.new}",
                      link=(c.name, c.old, c.new))
                 for c in link_changes(pairs, left_blocks, right_blocks, l_final.span, r_final.span, link_drop)]
    raws.sort(key=lambda r: (r.i1, r.j1, r.i2, r.j2))
    if isinstance(left, DocText) and isinstance(right, DocText) and left_pages != right_pages:
        raws.insert(0, _Raw("pagine", 0, 0, 0, 0, (), (), detail=f"{_pages(left_pages)} contro {right_pages}"))

    context = TargetKeys(p.left_side.keys, slots, l_ranges)
    built = [_diff(raw, l_final, r_final, context, left_pages, right_pages) for raw in raws]
    anchors = disambiguate([d.anchor for d in built])
    diffs = tuple(_renumber(d, n, anchor) for n, (d, anchor) in enumerate(zip(built, anchors, strict=True), 1))
    names = [*(name for name, _ in usable), *(name for name, _, _ in custom_hits)]
    hits = tuple((name, sum(1 for h in (*l_hits, *r_hits) if h[2] == name)) for name in names)
    return Comparison(diffs, True, True, left_pages, right_pages, "; ".join(notes), len(slots), hits)


# ------------------------------------------------------------- stages ---

def _sync(pairs: Sequence[Pair], lf: _Side, rf: _Side) -> tuple[list[tuple[int, int, int, int]],
                                                                list[tuple[int, int]]]:
    """``fixed`` (aligned blocks with identical keys) and ``cuts`` (starts of
    aligned pairs) for the word diff, both increasing on both sides: a pair
    read out of order (a weak pair) gives neither."""
    fixed: list[tuple[int, int, int, int]] = []
    cuts: list[tuple[int, int]] = []
    last_i = last_j = -1
    for i, j in pairs:
        a = lf.span(i) if i is not None else None
        b = rf.span(j) if j is not None else None
        if not (a and b) or a[0] <= last_i or b[0] <= last_j:
            continue
        cuts.append((a[0], b[0]))
        if lf.keys[a[0]:a[1]] == rf.keys[b[0]:b[1]]:
            fixed.append((a[0], a[1], b[0], b[1]))
            last_i, last_j = a[1] - 1, b[1] - 1
        else:
            last_i, last_j = a[0], b[0]
    return fixed, cuts


def _unmatched(side: _Side, blocks: list[int]) -> list[tuple[int, int]]:
    """Key ranges of the unmatched blocks, adjacent ones merged, sorted, that
    could become a section (≥ 2 lines together, R24): the hard boundaries of
    ruling R27. A shorter one (a heading, a name, a date line) is no boundary,
    so a line whose text is replaced stays ONE ``cambiato``."""
    ranges = sorted(span for span in (side.span(b) for b in blocks) if span)
    out: list[tuple[int, int]] = []
    for start, end in ranges:
        if out and out[-1][1] == start:
            out[-1] = (out[-1][0], end)
        else:
            out.append((start, end))
    return [(start, end) for start, end in out if _lines(side, start, end) >= 2]


def _label(label: str) -> str:
    article = "l'" if label[:1].upper() in "AEIOU" else "il "
    return f"{article}{label} non ha testo estraibile"


def _moves(found: list[Change], moved: list[tuple[list[int], list[int]]], left_blocks: list[Block],
           right_blocks: list[Block], lf: _Side, rf: _Side) -> list[_Raw]:
    """The changes as raw differences, with the moves made ``spostato``: the
    moved runs of ``moves.reading_order``, and equal texts deleted and inserted."""
    raws = [_Raw(c.op, c.i1, c.i2, c.j1, c.j2, c.slot.words if c.slot else _flat(lf.members[c.i1:c.i2]),
                 _flat(rf.members[c.j1:c.j2]), c.slot, c.noise, c.style) for c in found]
    for target, generated in moved:
        a = [lf.span(i) for i in target if lf.span(i)]
        b = [rf.span(j) for j in generated if rf.span(j)]
        if not a or not b:
            continue
        raws.append(_Raw("spostato", a[0][0], a[-1][1], b[0][0], b[-1][1],
                         tuple(w for i in target for w in left_blocks[i].words),
                         tuple(w for j in generated for w in right_blocks[j].words)))
    deleted = [r for r in raws if r.op == "mancante" and not _covered(lf.keys[r.i1:r.i2])]
    inserted = [r for r in raws if r.op == "in_piu" and not _covered(rf.keys[r.j1:r.j2])]
    matched = moves.text_moves([lf.keys[r.i1:r.i2] for r in deleted], [rf.keys[r.j1:r.j2] for r in inserted])
    gone: set[int] = set()
    for d, k in matched:
        a, b = deleted[d], inserted[k]
        gone.update((id(a), id(b)))
        raws.append(_Raw("spostato", a.i1, a.i2, b.j1, b.j2, a.left, b.right))
    return [r for r in raws if id(r) not in gone]


def _section(raw: _Raw, lf: _Side, rf: _Side) -> _Raw:
    """A ``mancante`` / ``in_piu`` covering whole blocks with ≥ 2 lines → a section."""
    if raw.op == "mancante" and not _covered(lf.keys[raw.i1:raw.i2]):
        side, start, end, op = lf, raw.i1, raw.i2, "sezione_assente"
    elif raw.op == "in_piu" and not _covered(rf.keys[raw.j1:raw.j2]):
        side, start, end, op = rf, raw.j1, raw.j2, "sezione_in_piu"
    else:
        return raw
    covered = [b for b in dict.fromkeys(side.block[start:end]) if start <= side.spans[b][0] and side.spans[b][1] <= end]
    if sum(_lines(side, *side.spans[b]) for b in covered) < 2:
        return raw
    raw.op = op  # type: ignore[assignment]
    raw.detail = f"{_lines(side, start, end)} righe"
    return raw


def _covered(keys: Sequence[str]) -> bool:
    """Whether a text on one side only is all noise-covered (then it is ``rumore``)."""
    return is_noise(keys, ())


def _lines(side: _Side, start: int, end: int) -> int:
    """Lines of the keys ``[start, end)``: a block break or a line end starts one."""
    count = 0
    previous: Word | None = None
    for k in range(start, end):
        group = side.members[k]
        if k == start or k in side.breaks:
            count += 1
            previous = None
        for word in group:
            if previous is not None and line_end(previous, word):
                count += 1
            previous = word
    return count


def _flat(groups: Sequence[tuple[Word, ...]]) -> tuple[Word, ...]:
    return tuple(w for group in groups for w in group)


# ------------------------------------------------------------ anchors ---

def _diff(raw: _Raw, lf: _Side, rf: _Side, context: TargetKeys, left_pages: int, right_pages: int) -> Diff:
    left_keys, right_keys = lf.keys[raw.i1:raw.i2], rf.keys[raw.j1:raw.j2]
    if raw.op == "pagine":
        anchor = Anchor("pagine", "composizione", "", str(left_pages))
        return Diff(0, "pagine", "composizione", (), (), _pages(left_pages), _pages(right_pages),
                    (), (), anchor, raw.detail)
    before, after = display.context(lf.members, lf.block, raw.i1, raw.i2)
    if raw.link is not None:
        name, old, new = raw.link
        anchor = dataclasses.replace(context.anchor("cambiato", "link", raw.i1, raw.i2), target_text=f"{name}: {old}")
        spans = char_spans(old, new)
        return Diff(0, "cambiato", "link", raw.left, raw.right, old, new, spans[0], spans[1], anchor, raw.detail,
                    before, after)
    klass = "rumore" if raw.noise else classify(raw.op, left_keys, right_keys, slot=raw.slot is not None,
                                                style=raw.style)
    left_text = " ".join(w.text for w in raw.left)
    right_text = " ".join(w.text for w in raw.right)
    spans: tuple = ((), ())
    if raw.op == "cambiato" and klass not in ("stile", "rumore", "variabile"):
        spans = char_spans(left_text, right_text)
    if raw.slot is not None:
        anchor = slot_anchor(context.keys, raw.slot)
    else:
        anchor = context.anchor(raw.op, klass, raw.i1, raw.i2)
    return Diff(0, raw.op, klass, raw.left, raw.right, left_text, right_text, spans[0], spans[1], anchor, raw.detail,
                before, after)


def _pages(n: int) -> str:
    return "1 pagina" if n == 1 else f"{n} pagine"


def _renumber(diff: Diff, number: int, anchor: Anchor) -> Diff:
    return dataclasses.replace(diff, id=number, anchor=anchor)
