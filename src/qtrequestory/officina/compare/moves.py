"""Moves (spec §4.2 step 9): text that is there on both sides, elsewhere.

Where moves come from:

* :func:`reading_order` — the order the word diff reads the generated
  blocks in (rulings R20, R26): a STRONG aligned pair (content ratio ≥
  :data:`RATIO`, :func:`similar`) out of order is a move, read at its
  partner's place; every other generated block stays in its own position;
* :func:`out_of_order` — among the pairs it is given (the strong ones),
  those whose generated block is out of the relative order of its
  neighbours. The moved block is read at its partner's place, so the word
  diff sees the moved text as equal; this is where the move is found.
  The pairs kept in order are a longest increasing subsequence of the
  generated indices (in target order); the others are moved, and a run of
  them consecutive on both sides is ONE move;
* :func:`text_moves` — a target-only run and a generated-only run of the word
  diff (``mancante`` / ``in_piu``) with the same normalised text: at least
  :data:`MIN_WORDS` keys each and a key ``SequenceMatcher`` ratio of at least
  :data:`RATIO`. Each run is used once, the target runs in order taking the
  first generated run that qualifies.

Deterministic and pure; stdlib only, no Qt, no pypdfium2.
"""
from __future__ import annotations

import bisect
from collections.abc import Sequence
from difflib import SequenceMatcher

from qtrequestory.officina.compare.blocks import content_keys
from qtrequestory.officina.compare.model import Block

__all__ = ["MIN_WORDS", "RATIO", "increasing", "out_of_order", "reading_order", "similar", "text_moves"]

#: A text move needs at least this many keys on each side…
MIN_WORDS = 3
#: …and at least this similarity.
RATIO = 0.85

Pair = tuple[int | None, int | None]


def out_of_order(pairs: Sequence[Pair]) -> list[tuple[list[int], list[int]]]:
    """The moved runs among the aligned pairs, as (target blocks, generated
    blocks), in target order. ``pairs`` as ``align.align`` returns them."""
    matched = [(i, j) for i, j in pairs if i is not None and j is not None]
    keep = increasing([j for _, j in matched])
    runs: list[tuple[list[int], list[int]]] = []
    for k, (i, j) in enumerate(matched):
        if k in keep:
            continue
        if runs and runs[-1][0][-1] + 1 == i and runs[-1][1][-1] + 1 == j:
            runs[-1][0].append(i)
            runs[-1][1].append(j)
        else:
            runs.append(([i], [j]))
    return runs


def increasing(values: Sequence[int]) -> set[int]:
    """Positions of one longest strictly increasing subsequence of
    ``values`` (patience sorting with back links: deterministic)."""
    tails: list[int] = []        # value at the end of the best run of each length
    tail_at: list[int] = []      # its position
    back: list[int] = [-1] * len(values)
    for k, value in enumerate(values):
        n = bisect.bisect_left(tails, value)
        if n == len(tails):
            tails.append(value)
            tail_at.append(k)
        else:
            tails[n] = value
            tail_at[n] = k
        back[k] = tail_at[n - 1] if n else -1
    out: set[int] = set()
    k = tail_at[-1] if tail_at else -1
    while k >= 0:
        out.add(k)
        k = back[k]
    return out


def text_moves(deleted: Sequence[Sequence[str]], inserted: Sequence[Sequence[str]]) -> list[tuple[int, int]]:
    """``(index in deleted, index in inserted)`` for every pair of runs that
    is one moved text (see module doc), in the order of ``deleted``."""
    used: set[int] = set()
    out: list[tuple[int, int]] = []
    candidates = [k for k, keys in enumerate(inserted) if len(keys) >= MIN_WORDS]
    for d, keys in enumerate(deleted):
        if len(keys) < MIN_WORDS:
            continue
        for k in candidates:
            if k in used:
                continue
            other = inserted[k]
            if 2 * min(len(keys), len(other)) / (len(keys) + len(other)) < RATIO:
                continue       # the ratio cannot reach RATIO with lengths this far apart
            matcher = SequenceMatcher(None, list(keys), list(other), autojunk=False)
            if matcher.real_quick_ratio() >= RATIO and matcher.quick_ratio() >= RATIO and matcher.ratio() >= RATIO:
                used.add(k)
                out.append((d, k))
                break
    return out


def reading_order(pairs: Sequence[Pair], left_blocks: list[Block], right_blocks: list[Block]) -> tuple[
        list[int], list[tuple[list[int], list[int]]]]:
    """The generated blocks in the order the word diff reads them, and the
    moved runs (ruling R26).

    Only a STRONG pair (content ratio ≥ :data:`RATIO`) can be a move: the
    strong pairs out of order (:func:`out_of_order` on them alone) are the
    moves, and their generated blocks are read at their partner's place —
    right after the generated block of the nearest earlier in-order pair.
    Every other generated block (in order, weakly paired, unpaired) stays in
    its own reading position."""
    strong = [(i, j) for i, j in pairs
              if i is not None and j is not None and similar(left_blocks[i], right_blocks[j])]
    runs = out_of_order(strong)
    moved = {j for _, generated in runs for j in generated}
    matched = [(i, j) for i, j in pairs if i is not None and j is not None and j not in moved]
    keep = increasing([j for _, j in matched])
    anchors = [matched[k] for k in sorted(keep)]          # in order on both sides
    anchor_rows = [i for i, _ in anchors]
    after: dict[int | None, list[int]] = {}
    for target, generated in runs:
        k = bisect.bisect_left(anchor_rows, target[0])
        after.setdefault(anchors[k - 1][1] if k else None, []).extend(generated)
    order = list(after.get(None, ()))
    for j in range(len(right_blocks)):
        if j not in moved:
            order += [j, *after.get(j, ())]
    return order, runs


def similar(a: Block, b: Block) -> bool:
    """Whether two paired blocks say the same thing (a move can be trusted)."""
    x, y = content_keys(a.words), content_keys(b.words)
    if x == y:
        return True
    matcher = SequenceMatcher(None, x, y, autojunk=False)
    return (matcher.real_quick_ratio() >= RATIO and matcher.quick_ratio() >= RATIO
            and matcher.ratio() >= RATIO)
