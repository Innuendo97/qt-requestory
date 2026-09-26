"""Hard boundaries of the word diff (ruling R27).

Blocks the alignment left unpaired, when they could become a section (≥ 2
lines, R24), must never be swallowed by a neighbouring change: a missing
clause next to an edited word is ONE ``sezione_assente`` and ONE small
``cambiato``, not a wall of words. :func:`split` cuts a non-equal region of
the word diff at such ranges and pairs what is left around them.

Deterministic and pure; stdlib only, no Qt, no pypdfium2.
"""
from __future__ import annotations

import bisect
import difflib
from collections.abc import Sequence

__all__ = ["SHARE_MAX", "split"]

#: A piece shared between the two neighbours of a boundary is cut by trying
#: every position only up to this many keys (else it goes to one of them).
SHARE_MAX = 60


def split(a: Sequence[str], b: Sequence[str], i1: int, i2: int, j1: int, j2: int,
           bounds: tuple[Sequence[tuple[int, int]], Sequence[tuple[int, int]]]) -> list[tuple[int, int, int, int]]:
    """A non-equal region cut at the whole ``bounds`` ranges inside it: each
    such range becomes a region of its own (target only, or generated only),
    and what is left on each side is paired: a single piece facing two is cut
    between them (:func:`_share`); otherwise a single piece goes with the most
    similar piece on the other side, else pieces pair in order; an unpaired
    piece stays one-sided. Regions in target order."""
    left = _inside(bounds[0], i1, i2)
    right = _inside(bounds[1], j1, j2)
    if not left and not right:
        return [(i1, i2, j1, j2)]
    rest_l, rest_r = _gaps(i1, i2, left), _gaps(j1, j2, right)
    paired: list[tuple[tuple[int, int], tuple[int, int]]] = []
    if sorted((len(rest_l), len(rest_r))) == [1, 2]:
        paired = _share(a, b, rest_l, rest_r)
        if paired:     # the single piece is used up by its parts
            if len(rest_l) == 1:
                rest_l = [p[0] for p in paired]
            else:
                rest_r = [p[1] for p in paired]
    if not paired and rest_l and rest_r:
        if len(rest_l) == 1 or len(rest_r) == 1:
            single_left = len(rest_l) == 1
            one, many = (rest_l[0], rest_r) if single_left else (rest_r[0], rest_l)
            best = max(many, key=lambda piece: _similarity(a, b, one, piece, single_left))
            paired = [(one, best)] if single_left else [(best, one)]
        else:
            paired = list(zip(rest_l, rest_r))
    used_l = {p[0] for p in paired}
    used_r = {p[1] for p in paired}
    first_l = min((p[0][0] for p in paired), default=i2)
    first_r = min((p[1][0] for p in paired), default=j2)
    out = [(pl[0], pl[1], pr[0], pr[1]) for pl, pr in paired]
    for start, end in [*left, *(p for p in rest_l if p not in used_l)]:
        at = j1 if start < first_l else j2
        out.append((start, end, at, at))
    for start, end in [*right, *(p for p in rest_r if p not in used_r)]:
        # the target position of a one-sided generated piece is only the
        # region's edge (not the gap between two target bounds): enough for
        # the order; its anchor's neighbours may be the region's
        at = i1 if start < first_r else i2
        out.append((at, at, start, end))
    return sorted(out, key=lambda r: (r[0], r[2], r[1], r[3]))


def _share(a: Sequence[str], b: Sequence[str], rest_l: list[tuple[int, int]],
           rest_r: list[tuple[int, int]]) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    """One piece facing two (the text around a boundary changed on both sides
    of it): the single piece is cut in two, each part going with its own
    neighbour — at the cut that makes both pairs most similar, ties broken
    towards the cut proportional to the two pieces' lengths. Empty parts are
    dropped (the piece they would face stays one-sided)."""
    single_left = len(rest_l) == 1
    one, (first, second) = (rest_l[0], rest_r) if single_left else (rest_r[0], rest_l)
    size = one[1] - one[0]
    if size > SHARE_MAX:
        return []
    own, other = (a, b) if single_left else (b, a)
    x, y = other[first[0]:first[1]], other[second[0]:second[1]]
    ideal = size * len(x) / (len(x) + len(y))

    def score(k: int) -> tuple[float, float]:
        head, tail = own[one[0]:one[0] + k], own[one[0] + k:one[1]]
        value = (difflib.SequenceMatcher(None, list(head), list(x), autojunk=False).ratio()
                 + difflib.SequenceMatcher(None, list(tail), list(y), autojunk=False).ratio())
        return value, -abs(k - ideal)

    k = max(range(size + 1), key=score)
    parts = [((one[0], one[0] + k), first), ((one[0] + k, one[1]), second)]
    return [(p, q) if single_left else (q, p) for p, q in parts if p[1] > p[0]]


def _inside(ranges: Sequence[tuple[int, int]], lo: int, hi: int) -> list[tuple[int, int]]:
    k = bisect.bisect_left(ranges, (lo, lo))
    out = []
    while k < len(ranges) and ranges[k][0] < hi:
        if ranges[k][1] <= hi and ranges[k][1] > ranges[k][0]:
            out.append(ranges[k])
        k += 1
    return out


def _gaps(lo: int, hi: int, taken: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out, pos = [], lo
    for start, end in taken:
        if start > pos:
            out.append((pos, start))
        pos = end
    if hi > pos:
        out.append((pos, hi))
    return out


def _similarity(a: Sequence[str], b: Sequence[str], one: tuple[int, int], other: tuple[int, int],
                one_is_left: bool) -> float:
    x = a[one[0]:one[1]] if one_is_left else b[one[0]:one[1]]
    y = b[other[0]:other[1]] if one_is_left else a[other[0]:other[1]]
    return difflib.SequenceMatcher(None, list(x), list(y), autojunk=False).ratio()
