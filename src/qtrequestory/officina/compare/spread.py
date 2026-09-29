"""A difference never spans distant places (phase 2.5, research
``fase25-analisi-caso-reale``: one highlight over three far-apart spots).

The word diff reads each side as ONE sequence, so a single ``cambiato``,
``mancante`` or ``in_piu`` can hold words that are consecutive in reading
order but far apart on the page: the end of a column and the top of the
next one, the bottom of a page and the top of the next, two lines with a
blank block between them. :func:`split` cuts such a change where two
consecutive words are :func:`far` apart, and where the page zone changes
(the title and the body flow together, final review C1: a zone switched off
must set aside only its own words), and pairs the pieces again:

* a one-sided change (``mancante`` / ``in_piu``) becomes one change per piece;
* a ``cambiato`` whose sides are cut into ``n`` and ``m`` pieces keeps the
  pieces paired in order, most similar first (a monotonic alignment of the
  pieces on their keys; two pieces of different zones never pair); an unpaired piece becomes a ``mancante`` or an
  ``in_piu``; each pair is re-diffed (``worddiff.refine``) so it keeps only
  the words that really differ.

Deterministic and pure; stdlib only, no Qt, no pypdfium2.
"""
from __future__ import annotations

from collections.abc import Sequence
from difflib import SequenceMatcher

from qtrequestory.officina.compare.model import Word
from qtrequestory.officina.compare.worddiff import Change, refine

__all__ = ["BLANK_LINES", "WIDE_GAP", "far", "pieces", "split"]

#: Two lines are far apart when more than this many line heights of blank
#: lie between them (a paragraph gap is about one).
BLANK_LINES = 2.0
#: Two words on one line are far apart when the gap between them is wider
#: than this many line heights (a hole of a few words is not).
WIDE_GAP = 15.0
#: Pairing bonus: pieces with nothing in common still pair, in order.
_BONUS = 0.05
#: The score of two pieces that must never pair (different zones).
_NEVER = -1e9
#: Pieces longer than this together (characters) are compared cheaply.
_LONG = 1200

Members = Sequence[tuple[Word, ...]]


def far(a: Word, b: Word) -> bool:
    """Whether ``b`` (read right after ``a``) is in another place: another
    page, above ``a`` (the next column), more than :data:`BLANK_LINES` lines
    below it, or on its line but more than :data:`WIDE_GAP` heights away."""
    if a.page != b.page:
        return True
    height = max(a.y1 - a.y0, b.y1 - b.y0, 1.0)
    if b.y1 < a.y0:
        return True
    if b.y0 - a.y1 > BLANK_LINES * height:
        return True
    same_line = b.y0 < a.y1 and a.y0 < b.y1
    return same_line and b.x0 - a.x1 > WIDE_GAP * height


def pieces(members: Members, start: int, end: int) -> list[tuple[int, int]]:
    """``[start, end)`` cut where a key's first word is :func:`far` from the
    previous key's last word or lies in another zone; keys without a word
    never cut."""
    out: list[tuple[int, int]] = []
    begin, last = start, None
    for k in range(start, end):
        group = members[k]
        if not group:
            continue
        if last is not None and (far(last, group[0]) or last.zone != group[0].zone):
            out.append((begin, k))
            begin = k
        last = group[-1]
    out.append((begin, end))
    return [(a, b) for a, b in out if b > a]


def split(change: Change, left_keys: Sequence[str], left_members: Members, right_keys: Sequence[str],
          right_members: Members) -> list[Change]:
    """``change`` cut at the far gaps of its sides (module doc). A change
    of a slot, of noise or of style is returned as it is."""
    if change.slot is not None or change.noise or change.style:
        return [change]
    left = pieces(left_members, change.i1, change.i2) if change.i2 > change.i1 else []
    right = pieces(right_members, change.j1, change.j2) if change.j2 > change.j1 else []
    if len(left) <= 1 and len(right) <= 1 and not (left and right and _zone(left_members, left[0][0])
                                                   != _zone(right_members, right[0][0])):
        return [change]
    if not right:
        return [Change("mancante", a, b, change.j1, change.j1) for a, b in left]
    if not left:
        return [Change("in_piu", change.i1, change.i1, a, b) for a, b in right]
    out: list[Change] = []
    i_at, j_at = change.i1, change.j1
    for x, y in _pairs(left, right, left_keys, right_keys, [_zone(left_members, a) for a, _ in left],
                       [_zone(right_members, a) for a, _ in right]):
        if x is not None and y is not None:
            (i1, i2), (j1, j2) = left[x], right[y]
            for a1, a2, b1, b2 in refine(left_keys, right_keys, i1, i2, j1, j2, {}):
                out.append(_plain(a1, a2, b1, b2))
            i_at, j_at = i2, j2
        elif x is not None:
            i1, i2 = left[x]
            out.append(Change("mancante", i1, i2, j_at, j_at))
            i_at = i2
        else:
            j1, j2 = right[y]  # type: ignore[index]
            out.append(Change("in_piu", i_at, i_at, j1, j2))
            j_at = j2
    return out


def _plain(i1: int, i2: int, j1: int, j2: int) -> Change:
    if i2 > i1 and j2 > j1:
        return Change("cambiato", i1, i2, j1, j2)
    if i2 > i1:
        return Change("mancante", i1, i2, j1, j1)
    return Change("in_piu", i1, i1, j1, j2)


def _zone(members: Members, start: int) -> str:
    """The zone of the piece starting at key ``start`` (its first word's)."""
    group = members[start]
    return group[0].zone if group else "corpo"


def _pairs(left: list[tuple[int, int]], right: list[tuple[int, int]], left_keys: Sequence[str],
           right_keys: Sequence[str], left_zones: Sequence[str],
           right_zones: Sequence[str]) -> list[tuple[int | None, int | None]]:
    """The pieces aligned in order, maximising the similarity of the pairs;
    pieces of different zones never pair."""
    n, m = len(left), len(right)
    texts_a = [" ".join(left_keys[a:b]) for a, b in left]
    texts_b = [" ".join(right_keys[a:b]) for a, b in right]
    pair = [[_similar(a, b) + _BONUS if za == zb else _NEVER for b, zb in zip(texts_b, right_zones, strict=True)]
            for a, za in zip(texts_a, left_zones, strict=True)]
    score = [[0.0] * (m + 1) for _ in range(n + 1)]
    for x in range(n - 1, -1, -1):
        for y in range(m - 1, -1, -1):
            score[x][y] = max(pair[x][y] + score[x + 1][y + 1], score[x + 1][y], score[x][y + 1])
    out: list[tuple[int | None, int | None]] = []
    x = y = 0
    while x < n and y < m:
        if abs(score[x][y] - (pair[x][y] + score[x + 1][y + 1])) < 1e-9:
            out.append((x, y))
            x, y = x + 1, y + 1
        elif abs(score[x][y] - score[x + 1][y]) < 1e-9:
            out.append((x, None))
            x += 1
        else:
            out.append((None, y))
            y += 1
    out += [(k, None) for k in range(x, n)] + [(None, k) for k in range(y, m)]
    return out


def _similar(a: str, b: str) -> float:
    """The similarity of two pieces' texts (an upper bound for long ones: cheap)."""
    matcher = SequenceMatcher(None, a, b, autojunk=False)
    return matcher.quick_ratio() if len(a) + len(b) > _LONG else matcher.ratio()
