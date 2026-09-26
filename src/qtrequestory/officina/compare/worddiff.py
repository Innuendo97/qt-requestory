"""Word and character diff (spec §4.2 step 8): the ``worddiff`` stage.

It takes over from phase 1's ``textdiff.compare_text`` (removed in the
integration task, ruling R3: every comparison goes through the pipeline). The inputs are the unit
keys and members of both sides as the earlier stages leave them: the target
with its slots (:data:`~qtrequestory.officina.compare.slots.SLOT` keys) and
both sides with their noise placeholders, the generated side already put in
TARGET order by the alignment (ruling R20). So the diff runs over the WHOLE
sequence, page-agnostic, like phase 1: text reflowed onto another page, or
blocks cut differently on the two sides, costs nothing.

:func:`opcodes` is ``difflib.SequenceMatcher`` on the keys, run only between
``fixed`` ranges known to be equal (the aligned blocks with identical keys),
and inside a long gap between them only between *patience anchors* (equal
runs around keys that occur once on each side, in order): the same diff
where it matters, and a cost that stays near-linear on a long document with
changes everywhere (the plain matcher grows much faster).

:func:`changes` turns the opcodes into :class:`Change` records:

* a non-equal opcode cut at hard boundaries (``bounds.split``) has each
  two-sided part re-diffed (:func:`refine`), so a part keeps only the words
  that changed;
* a non-equal opcode is split around the slots in it: a slot swallows what
  :func:`~qtrequestory.officina.compare.slots.absorb` allows (a ``variabile``
  change); what is left before, between and after becomes ``cambiato``
  (both sides), ``mancante`` (target only) or ``in_piu`` (generated only). A
  slot that swallows nothing stays inside the surrounding change;
* an equal run holding a noise placeholder whose original texts differ is a
  ``rumore`` change (``noise=True``), one per unit; identical texts are no
  change at all;
* an equal run whose words differ in size (more than :data:`SIZE_TOLERANCE`
  points) or weight is a ``stile`` change (``style=True``), consecutive units
  grouped, never across a block break (one per restyled paragraph run).

:func:`char_spans` is the second ``SequenceMatcher``, on the characters of a
``cambiato``'s two texts.

Deterministic and pure; stdlib only (difflib), no Qt, no pypdfium2.
"""
from __future__ import annotations

import difflib
from collections import Counter
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from qtrequestory.officina.compare.bounds import split
from qtrequestory.officina.compare.model import Word
from qtrequestory.officina.compare.moves import increasing
from qtrequestory.officina.compare.noise import NOISE
from qtrequestory.officina.compare.slots import Slot, absorb

__all__ = ["CHAR_LIMIT", "PATIENCE_MIN", "PATIENCE_RUN", "REFINE_MAX", "SIZE_TOLERANCE", "Change", "changes",
           "char_spans", "opcodes", "refine"]

#: Font sizes closer than this (points) are the same size.
SIZE_TOLERANCE = 0.5
#: Texts longer than this (characters, either side) are not diffed by
#: character: the whole text is the span (a quadratic matcher on a wall of
#: text would cost more than it shows).
CHAR_LIMIT = 2000
#: A gap between fixed ranges longer than this (keys) is cut at patience anchors…
PATIENCE_MIN = 1000
#: …that are equal runs at least this long (a lone equal word is no anchor).
PATIENCE_RUN = 3
#: A split part longer than this (keys, either side) is not re-diffed (:func:`refine`).
REFINE_MAX = 400

Opcode = tuple[str, int, int, int, int]
ChangeOp = Literal["mancante", "in_piu", "cambiato"]
Members = Sequence[tuple[Word, ...]]


@dataclass(frozen=True)
class Change:
    """A difference in key indices: target keys ``[i1, i2)`` against
    generated keys ``[j1, j2)`` (an empty range = nothing on that side).
    ``slot`` is set for what a slot swallowed (``variabile``), ``noise`` for
    equal placeholders over different texts, ``style`` for equal keys in
    another size or weight."""

    op: ChangeOp
    i1: int
    i2: int
    j1: int
    j2: int
    slot: Slot | None = None
    noise: bool = False
    style: bool = False


def opcodes(a: Sequence[str], b: Sequence[str], fixed: Sequence[tuple[int, int, int, int]] = (),
            cuts: Sequence[tuple[int, int]] = ()) -> list[Opcode]:
    """``SequenceMatcher`` opcodes of ``a`` against ``b`` over the whole
    sequences, with ``fixed`` ranges ``(i1, i2, j1, j2)`` — equal, increasing
    on both sides, not overlapping — taken as equal and the matcher run only
    between them. Adjacent equal opcodes are merged.

    A gap between fixed ranges longer than :data:`PATIENCE_MIN` keys on
    either side is first cut at *patience anchors* (:func:`_patience`): the
    matcher's cost grows faster than linearly with the gap and with the
    number of changes in it, so a long document with changes everywhere would
    blow the time budget otherwise. A piece still that long (no word occurs
    once: a form of identical rows) is cut at the ``cuts`` inside it —
    ``(i, j)`` points where both sides start a new unit of their own (the
    pipeline gives the starts of the aligned block pairs), increasing on both
    sides."""
    out: list[Opcode] = []
    i = j = 0
    for i1, i2, j1, j2 in _with_patience(a, b, fixed, cuts):
        if i1 > i or j1 > j:
            matcher = difflib.SequenceMatcher(None, a[i:i1], b[j:j1], autojunk=False)
            for tag, a1, a2, b1, b2 in matcher.get_opcodes():
                _push(out, (tag, a1 + i, a2 + i, b1 + j, b2 + j))
        if i2 > i1:
            _push(out, ("equal", i1, i2, j1, j2))
        i, j = i2, j2
    return out


def _with_patience(a: Sequence[str], b: Sequence[str], fixed: Sequence[tuple[int, int, int, int]],
                   cuts: Sequence[tuple[int, int]]) -> list[tuple[int, int, int, int]]:
    """The increasing ``fixed`` ranges, with patience anchors added inside the
    long gaps (and cuts, as empty ranges, inside the pieces still long), and
    a final empty range at both ends."""
    out: list[tuple[int, int, int, int]] = []
    i = j = 0
    for i1, i2, j1, j2 in (*fixed, (len(a), len(a), len(b), len(b))):
        if i1 < i or j1 < j:
            continue  # not increasing: ignore (the matcher still sees it)
        if _long(i, i1, j, j1):
            ci, cj = i, j
            for run in (*_patience(a, b, i, i1, j, j1), (i1, i1, j1, j1)):
                if _long(ci, run[0], cj, run[2]):
                    out += [(x, x, y, y) for x, y in cuts if ci < x < run[0] and cj < y < run[2]]
                out.append(run)
                ci, cj = run[1], run[3]
            out.pop()                           # the closing empty range: replaced by the fixed one
        out.append((i1, i2, j1, j2))
        i, j = i2, j2
    return out


def _long(i: int, i1: int, j: int, j1: int) -> bool:
    return i1 - i > PATIENCE_MIN or j1 - j > PATIENCE_MIN


def _patience(a: Sequence[str], b: Sequence[str], i0: int, i1: int, j0: int, j1: int) -> list[tuple[int, int, int, int]]:
    """Equal runs of at least :data:`PATIENCE_RUN` keys around the keys that
    occur exactly once in ``a[i0:i1]`` and once in ``b[j0:j1]``, kept in
    order on both sides (a longest increasing subsequence), not overlapping."""
    count_a = Counter(a[i0:i1])
    count_b = Counter(b[j0:j1])
    at_b = {b[j]: j for j in range(j0, j1) if count_b[b[j]] == 1}
    pairs = [(i, at_b[a[i]]) for i in range(i0, i1) if count_a[a[i]] == 1 and a[i] in at_b]
    keep = increasing([j for _, j in pairs])
    runs: list[tuple[int, int, int, int]] = []
    low_i, low_j = i0, j0
    for k, (i, j) in enumerate(pairs):
        if k not in keep or i < low_i or j < low_j:
            continue
        start_i, start_j = i, j
        while start_i > low_i and start_j > low_j and a[start_i - 1] == b[start_j - 1]:
            start_i, start_j = start_i - 1, start_j - 1
        end_i, end_j = i + 1, j + 1
        while end_i < i1 and end_j < j1 and a[end_i] == b[end_j]:
            end_i, end_j = end_i + 1, end_j + 1
        if end_i - start_i >= PATIENCE_RUN:
            runs.append((start_i, end_i, start_j, end_j))
            low_i, low_j = end_i, end_j
    return runs


def _push(out: list[Opcode], code: Opcode) -> None:
    if out and code[0] == "equal" and out[-1][0] == "equal":
        tag, i1, _, j1, _ = out[-1]
        out[-1] = (tag, i1, code[2], j1, code[4])
    else:
        out.append(code)


def changes(left_keys: Sequence[str], left_members: Members, right_keys: Sequence[str], right_members: Members,
            slots: Mapping[int, Slot], *, fixed: Sequence[tuple[int, int, int, int]] = (),
            cuts: Sequence[tuple[int, int]] = (),
            breaks: tuple[Collection[int], Collection[int]] = ((), ()),
            bounds: tuple[Sequence[tuple[int, int]], Sequence[tuple[int, int]]] = ((), ()),
            line_starts: Collection[int] = ()) -> list[Change]:
    """The changes between the two sides, in target order (see module doc).

    ``fixed`` and ``cuts`` as in :func:`opcodes`; ``slots`` maps a target
    key index holding :data:`SLOT` to its slot; ``breaks`` = for each side,
    the key indices that start a new block (a ``stile`` change never spans
    one); ``bounds`` = for each side, sorted key ranges ``[start, end)`` that
    are hard boundaries (ruling R27): a non-equal opcode covering one whole
    is split so the range is a change of its own (``bounds.split``);
    ``line_starts`` = generated key indices that start a line whatever the
    words' boxes say (``slots.absorb``: HTML block starts)."""
    out: list[Change] = []
    for tag, i1, i2, j1, j2 in opcodes(left_keys, right_keys, fixed, cuts):
        if tag == "equal":
            out += _equal(left_keys, left_members, right_members, i1, i2, j1, j2, breaks)
            continue
        parts = split(left_keys, right_keys, i1, i2, j1, j2, bounds)
        if len(parts) > 1:  # the parts of a split region can hold words equal on both sides
            parts = [r for part in parts for r in refine(left_keys, right_keys, *part, slots)]
        for a1, a2, b1, b2 in parts:
            out += _region(left_keys, right_keys, right_members, slots, a1, a2, b1, b2, line_starts)
    return out


def refine(a: Sequence[str], b: Sequence[str], i1: int, i2: int, j1: int, j2: int,
           slots: Mapping[int, object]) -> list[tuple[int, int, int, int]]:
    """A two-sided part of a split region, re-diffed so it keeps only the keys
    that really differ: ``bounds.split`` pairs whole pieces, so a part like
    ``H i l m n`` against ``Y i l m n`` would highlight five words for one.
    The non-equal sub-ranges, in order. A one-sided part, one holding a slot
    (its absorption works on the whole part), or one longer than
    :data:`REFINE_MAX` keys on either side is returned as it is."""
    if i2 <= i1 or j2 <= j1 or any(k in slots for k in range(i1, i2)) \
            or i2 - i1 > REFINE_MAX or j2 - j1 > REFINE_MAX:
        return [(i1, i2, j1, j2)]
    matcher = difflib.SequenceMatcher(None, list(a[i1:i2]), list(b[j1:j2]), autojunk=False)
    return [(i1 + x1, i1 + x2, j1 + y1, j1 + y2)
            for tag, x1, x2, y1, y2 in matcher.get_opcodes() if tag != "equal"]


def char_spans(left: str, right: str) -> tuple[tuple[tuple[int, int], ...], tuple[tuple[int, int], ...]]:
    """The changed character ranges inside ``left`` and inside ``right``
    (empty ranges dropped); each whole text when either is over :data:`CHAR_LIMIT`."""
    if len(left) > CHAR_LIMIT or len(right) > CHAR_LIMIT:
        return (((0, len(left)),) if left else ()), (((0, len(right)),) if right else ())
    a: list[tuple[int, int]] = []
    b: list[tuple[int, int]] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, left, right, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        if i2 > i1:
            a.append((i1, i2))
        if j2 > j1:
            b.append((j1, j2))
    return tuple(a), tuple(b)


# ------------------------------------------------------------ regions ---

def _region(left_keys: Sequence[str], right_keys: Sequence[str], right_members: Members,
            slots: Mapping[int, Slot], i1: int, i2: int, j1: int, j2: int,
            line_starts: Collection[int] = ()) -> list[Change]:
    """A non-equal opcode, split around the slots that swallow something."""
    out: list[Change] = []
    start, j = i1, j1          # the pending (unsplit) part begins at target key ``start``, generated key ``j``
    for s in range(i1, i2):
        slot = slots.get(s)
        if slot is None:
            continue
        if j >= j2:
            break              # nothing left on the generated side to swallow
        at = _slot_start(left_keys[start:s], right_keys, j, j2)
        next_key = left_keys[s + 1] if s + 1 < len(left_keys) else None
        n = min(absorb(slot, right_keys, at, next_key, right_members, line_starts), j2 - at)  # type: ignore[arg-type]
        if n <= 0:
            continue           # swallows nothing: the slot stays in the pending part
        out += _plain(start, s, j, at, slots)
        out.append(Change("cambiato", s, s + 1, at, at + n, slot=slot))
        start, j = s + 1, at + n
    out += _plain(start, i2, j, j2, slots)
    return out


def _slot_start(pending: Sequence[str], right_keys: Sequence[str], j: int, j2: int) -> int:
    """Where, in the generated keys ``[j, j2)``, the text a slot swallows
    begins, given the target keys ``pending`` before the slot: right after
    the last generated key matching one of them, else after as many keys as
    ``pending`` has (a word-for-word replacement)."""
    if not pending:
        return j
    blocks = difflib.SequenceMatcher(None, list(pending), list(right_keys[j:j2]), autojunk=False).get_matching_blocks()
    real = [m for m in blocks if m.size]
    if real:
        return j + real[-1].b + real[-1].size
    return min(j + len(pending), j2)


def _plain(i1: int, i2: int, j1: int, j2: int, slots: Mapping[int, Slot]) -> list[Change]:
    if all(k in slots and slots[k].kind == "probabile" for k in range(i1, i2)):
        i2 = i1                # only probable slots: they stand for no target word
    if i2 > i1 and j2 > j1:
        return [Change("cambiato", i1, i2, j1, j2)]
    if i2 > i1:
        return [Change("mancante", i1, i2, j1, j1)]
    if j2 > j1:
        return [Change("in_piu", i1, i1, j1, j2)]
    return []


# -------------------------------------------------------- equal runs ---

def _equal(left_keys: Sequence[str], left_members: Members, right_members: Members,
           i1: int, i2: int, j1: int, j2: int, breaks: tuple[Collection[int], Collection[int]]) -> list[Change]:
    out: list[Change] = []
    run: list[int] = []        # offsets of a pending stile run
    left_breaks, right_breaks = breaks
    for k in range(i2 - i1):
        i, j = i1 + k, j1 + k
        a, b = left_members[i], right_members[j]
        if NOISE in left_keys[i]:
            if _texts(a) != _texts(b):
                out.append(Change("cambiato", i, i + 1, j, j + 1, noise=True))
            restyled = False
        else:
            restyled = _restyled(a, b)
        if run and (not restyled or i in left_breaks or j in right_breaks):
            out.append(Change("cambiato", i1 + run[0], i1 + run[-1] + 1, j1 + run[0], j1 + run[-1] + 1, style=True))
            run = []
        if restyled:
            run.append(k)
    if run:
        out.append(Change("cambiato", i1 + run[0], i1 + run[-1] + 1, j1 + run[0], j1 + run[-1] + 1, style=True))
    return sorted(out, key=lambda c: (c.i1, c.j1))


def _texts(words: tuple[Word, ...]) -> str:
    return " ".join(w.text for w in words)


def _restyled(a: tuple[Word, ...], b: tuple[Word, ...]) -> bool:
    """Whether two equal units differ in size or weight: word by word when
    they hold as many words, else largest size and any bold. An unknown size
    (0.0) is never a difference; weight is compared only where sizes are known."""
    if not a or not b:
        return False
    pairs = list(zip(a, b)) if len(a) == len(b) else [(_summary(a), _summary(b))]
    for x, y in pairs:
        if x.size <= 0 or y.size <= 0:
            continue
        if abs(x.size - y.size) > SIZE_TOLERANCE or x.bold != y.bold:
            return True
    return False


def _summary(words: tuple[Word, ...]) -> Word:
    first = words[0]
    return Word(first.text, first.page, first.x0, first.y0, first.x1, first.y1,
                max(w.size for w in words), any(w.bold for w in words))


