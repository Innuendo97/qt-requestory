"""Display context of a difference (ruling R33).

``Diff.context_before`` / ``Diff.context_after`` frame a change in the
difference list: up to :data:`WIDTH` TARGET words right before and right
after it, in their original glyphs, single-spaced. They are display text
only, never part of an anchor.

The words come from the change's own block when it has any there; a change
that starts (ends) its block — a whole missing section, a changed first
word — takes them from the block before (after) it instead, so the list
still says where the change sits. For an insertion the two sides are the
target words around the insertion point.

Pure; stdlib only, no Qt, no pypdfium2.
"""
from __future__ import annotations

from collections.abc import Sequence

from qtrequestory.officina.compare.model import Word

__all__ = ["WIDTH", "context"]

#: Words of context on each side.
WIDTH = 5


def context(members: Sequence[tuple[Word, ...]], block: Sequence[int], i1: int, i2: int) -> tuple[str, str]:
    """``(before, after)`` for the target keys ``[i1, i2)`` (``i1 == i2``: an
    insertion before key ``i1``) of a side whose keys hold the words
    ``members`` and belong to the blocks ``block``."""
    n = len(members)
    before = _words(members, block, range(i1 - 1, -1, -1), reverse=True) if i1 > 0 else []
    after = _words(members, block, range(i2, n), reverse=False) if i2 < n else []
    return " ".join(w.text for w in before), " ".join(w.text for w in after)


def _words(members: Sequence[tuple[Word, ...]], block: Sequence[int], keys: range, *,
           reverse: bool) -> list[Word]:
    """Up to :data:`WIDTH` words of the keys walked in ``keys`` order (away
    from the change), all of the block of the first key walked: the change's
    own block, or the neighbour's when the change starts (ends) its block."""
    out: list[Word] = []
    own = block[keys[0]]
    for k in keys:
        if block[k] != own:
            break
        for word in (members[k][::-1] if reverse else members[k]):
            out.append(word)
            if len(out) == WIDTH:
                return out[::-1] if reverse else out
    return out[::-1] if reverse else out
