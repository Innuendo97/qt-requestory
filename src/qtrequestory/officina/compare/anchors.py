"""Anchor occurrences (ruling R19).

An anchor is taken from the target's text around a difference, so a form
with ten identical rows gives ten identical anchors: a tolerance, a mark or
"non è una variabile" on one row would apply to every row. :func:`disambiguate`
numbers the repeats in target order: the first keeps its anchor, the n-th
(n ≥ 2) gets ``" #n"`` appended to its ``context``.

The numbering depends on the whole target sequence, so callers pass ALL the
anchors of one kind of thing in target order (every slot, including those
switched off; every difference), never a filtered subset.

Every anchor produced is unique (ruling R35): a number that would give an
anchor already in the list (a context that really ends in ``#2``) is
skipped, and the next free one is used. A list that is already unique comes
back unchanged.

Stdlib only; no Qt, no pypdfium2.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from qtrequestory.officina.compare.model import Anchor

__all__ = ["disambiguate"]


def disambiguate(anchors: Sequence[Anchor]) -> list[Anchor]:
    """``anchors`` with the 2nd, 3rd… copy of an anchor made distinct (same order)."""
    originals = set(anchors)
    used: set[Anchor] = set()
    seen: dict[Anchor, int] = {}
    out: list[Anchor] = []
    for anchor in anchors:
        if anchor not in used:
            used.add(anchor)
            out.append(anchor)
            seen.setdefault(anchor, 1)
            continue
        n = seen[anchor]
        while True:  # the next number whose anchor nobody has (nor will have: originals)
            n += 1
            context = f"{anchor.context} #{n}" if anchor.context else f"#{n}"
            candidate = replace(anchor, context=context)
            if candidate not in used and candidate not in originals:
                break
        seen[anchor] = n
        used.add(candidate)
        out.append(candidate)
    return out
