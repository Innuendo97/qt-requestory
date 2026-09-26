"""The target keys a difference's :class:`Anchor` is taken on (spec §4.1).

Split out of ``pipeline`` (which documents the rule): ``context`` = the
:data:`CONTEXT_KEYS` target keys before and after the difference (for an
insertion, the ONE key before and the ONE after), ``target_text`` = the
target keys of the difference (a slot as its leader). Keys without a letter
or digit (a lone leader, punctuation) are never context.

Pure; stdlib only, no Qt, no pypdfium2.
"""
from __future__ import annotations

import bisect

from qtrequestory.officina.compare.model import Anchor, Op
from qtrequestory.officina.compare.slots import _LEADER, SLOT, Slot

__all__ = ["CONTEXT_KEYS", "TargetKeys"]

#: Target keys of context on each side of a difference in its anchor.
CONTEXT_KEYS = 3


class TargetKeys:
    """The target keys anchors are taken on: slotted, before noise (see
    ``pipeline``'s module doc). ``ranges`` maps each final key (after noise)
    to the range of slotted keys it stands for."""

    def __init__(self, keys: list[str], slots: list[Slot], ranges: list[tuple[int, int]]) -> None:
        self.keys = keys
        self.ranges = ranges
        leaders = {s.index: s.leader for s in slots}
        self.display = [leaders.get(k, "") if key == SLOT else key for k, key in enumerate(keys)]
        self.plain = [k for k, key in enumerate(keys) if key != SLOT and any(c.isalnum() for c in _LEADER.sub("", key))]

    def old(self, i1: int, i2: int) -> tuple[int, int]:
        """The final key range ``[i1, i2)`` as a range of slotted keys."""
        start = self.ranges[i1][0] if i1 < len(self.ranges) else len(self.keys)
        end = self.ranges[i2 - 1][1] if i2 > i1 else start
        return start, end

    def anchor(self, op: Op, klass, i1: int, i2: int) -> Anchor:
        start, end = self.old(i1, i2)
        width = 1 if i2 == i1 else CONTEXT_KEYS
        k = bisect.bisect_left(self.plain, start)
        before = [_LEADER.sub("", self.keys[x]) for x in self.plain[max(0, k - width):k]]
        k = bisect.bisect_left(self.plain, end)
        after = [_LEADER.sub("", self.keys[x]) for x in self.plain[k:k + width]]
        text = " ".join(t for t in self.display[start:end] if t)
        return Anchor(op, klass, " ".join(before + after), text)
