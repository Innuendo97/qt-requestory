"""The ``link`` differences of an HTML comparison (spec §6).

The critical attributes of the aligned blocks (``extract_html.attr_changes``:
``href``, ``src``, ``alt``, URLs normalised with the tracking rule ``drop``)
that differ become one :class:`LinkChange` each, placed at their TARGET
block's keys so they sort, anchor and number with the text differences.

A block the alignment left unpaired is compared with "no attributes" only
when it has no words (an image cell, a bare link): a paragraph that is
missing as a whole is already a text difference, its links with it.

Pure; stdlib only, no Qt, no pypdfium2.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from qtrequestory.officina.compare.extract_html import attr_changes
from qtrequestory.officina.compare.model import Block, Word

__all__ = ["LinkChange", "link_changes"]

Span = Callable[[int], "tuple[int, int] | None"]


@dataclass(frozen=True)
class LinkChange:
    """One attribute that differs: target keys ``[i1, i2)`` (the block's, or
    an insertion point), generated keys ``[j1, j2)``, the two blocks' words
    (for the viewer) and ``name``, ``old`` (target) and ``new`` values."""

    i1: int
    i2: int
    j1: int
    j2: int
    left: tuple[Word, ...]
    right: tuple[Word, ...]
    name: str
    old: str
    new: str


def link_changes(pairs: Sequence[tuple[int | None, int | None]], left: Sequence[Block], right: Sequence[Block],
                 left_span: Span, right_span: Span, drop: Callable[[str], bool]) -> list[LinkChange]:
    """The link changes of the aligned ``pairs`` (target order); ``*_span``
    give a block's key range on its side (None for a block without keys)."""
    out: list[LinkChange] = []
    i_at = j_at = 0   # where a block without keys sits: after the last keys seen
    for li, ri in pairs:
        a = left_span(li) if li is not None else None
        b = right_span(ri) if ri is not None else None
        i1, i2 = a if a else (i_at, i_at)
        j1, j2 = b if b else (j_at, j_at)
        i_at, j_at = i2, j2
        if (ri is None and left[li].words) or (li is None and right[ri].words):  # type: ignore[index]
            continue
        for _, _, name, old, new in attr_changes(left, right, [(li, ri)], drop):
            out.append(LinkChange(i1, i2, j1, j2, left[li].words if li is not None else (),
                                  right[ri].words if ri is not None else (), name, old, new))
    return out
