"""Block alignment: which target block goes with which generated block
(spec §4.2 step 7, risks in §11).

``left`` is the TARGET, ``right`` the generated document. The result is the
list of pairs in TARGET order: ``(i, j)`` paired, ``(i, None)`` a target block
with no counterpart, ``(None, j)`` a generated block with none — placed right
after the pair holding the nearest paired generated block before it (or
before the pair holding the next one, when none precedes it).

How pairs are chosen:

1. **exact matches** — blocks whose normalised text (``blocks.content_keys``:
   the ``normalise.units`` keys without slot leaders) is identical and occurs the same number of times on both sides are
   paired in order (a form's repeated rows pair first with first);
2. **score** for the rest, per candidate pair: ``0.70·content + 0.20·position
   + 0.10·structure``. Content: Jaccard on 3-key shingles, or the
   ``SequenceMatcher`` ratio of the keys when either block has fewer than
   :data:`SHORT_WORDS` keys. Position: relative order in the document (never
   the page), with a strictly convex penalty so that among equal contents the
   in-order pairing is the ONE optimum (ten identical rows never cross).
   Structure: kind, number of lines, font size;
3. **Hungarian** (``hungarian.solve``) on the pairs scoring at least
   :data:`THRESHOLD`, one connected group of candidates at a time; a group
   with more than :data:`WINDOW_BLOCKS` blocks on a side is cut into windows
   of :data:`WINDOW_PAGES` TARGET pages (the O(n³) guard).

Candidates are the blocks sharing a key; a key shared by very many blocks
(repeated form rows) yields only the :data:`POSTING_CAP` nearest to where the
block is expected — its proportional position and the offsets of the exact
matches around it — looking :data:`WIDEN` times wider when that finds nothing.

HTML blocks (kind ``html``, zero boxes) work the same: position is order anyway.
Deterministic: stable orders everywhere, no set order reaches a result.
Stdlib only; no Qt, no pypdfium2.
"""
from __future__ import annotations

import bisect
from collections.abc import Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher

from qtrequestory.officina.compare.blocks import content_keys
from qtrequestory.officina.compare.hungarian import solve
from qtrequestory.officina.compare.model import Block

__all__ = ["POSTING_CAP", "SHORT_WORDS", "THRESHOLD", "WIDEN", "WINDOW_BLOCKS", "WINDOW_PAGES", "align"]

#: The minimum score of a pair.
THRESHOLD = 0.35
W_CONTENT, W_POSITION, W_STRUCTURE = 0.70, 0.20, 0.10
#: Below this many keys a block is "short": content by SequenceMatcher ratio.
SHORT_WORDS = 8
#: A candidate group above this many blocks on a side is windowed…
WINDOW_BLOCKS = 300
#: …by this many pages.
WINDOW_PAGES = 30
#: A key or shingle shared by more blocks than this only suggests the ones
#: nearest in order (repetitive forms: the O(n²) guard of the candidates).
POSTING_CAP = 48
#: A block with no pair inside its capped windows looks again this many times wider.
WIDEN = 8
#: HTML has no pages: windows count this many blocks as a page.
_HTML_BLOCKS_PER_PAGE = 10
_FORM_KINDS = frozenset({"paragrafo", "riga_modulo"})

Pair = tuple[int | None, int | None]


@dataclass(frozen=True)
class _Info:
    keys: tuple[str, ...]
    shingles: frozenset[tuple[str, ...]]
    vocabulary: frozenset[str]
    bag: dict[str, int]
    lines: int
    size: float
    kind: str
    pos: float
    window: int

    @property
    def short(self) -> bool:
        return len(self.keys) < SHORT_WORDS


def align(left: list[Block], right: list[Block]) -> list[Pair]:
    """Pairs ``(target index, generated index)`` in target order (see module doc)."""
    html = any(b.kind == "html" for b in (*left, *right))
    li, ri = _infos(left, html), _infos(right, html)
    match: dict[int, int] = _exact(li, ri)
    rest_l = [i for i in range(len(li)) if i not in match]
    taken = set(match.values())
    rest_r = [j for j in range(len(ri)) if j not in taken]
    edges = _edges(li, ri, rest_l, rest_r, sorted(match.items()))
    for rows, cols in _groups(edges):
        match.update(_assign(rows, cols, edges, li))
    return _in_target_order(match, len(li), len(ri))


# ------------------------------------------------------------ block facts ---

def _infos(blocks: Sequence[Block], html: bool) -> list[_Info]:
    last = max(len(blocks) - 1, 1)
    return [_info(b, k / last if len(blocks) > 1 else 0.5,
                  k // _HTML_BLOCKS_PER_PAGE if html else b.page // WINDOW_PAGES)
            for k, b in enumerate(blocks)]


def _info(block: Block, pos: float, window: int) -> _Info:
    keys = tuple(content_keys(block.words))
    if len(keys) >= 3:
        shingles = frozenset(keys[k:k + 3] for k in range(len(keys) - 2))
    else:
        shingles = frozenset([keys]) if keys else frozenset()
    words = block.words
    lines = 1 + sum(1 for a, b in zip(words, words[1:]) if b.page != a.page or (b.y0 + b.y1) / 2 > a.y1)
    sizes = sorted(w.size for w in words if w.size > 0)
    size = sizes[len(sizes) // 2] if sizes else 0.0
    bag: dict[str, int] = {}
    for key in keys:
        bag[key] = bag.get(key, 0) + 1
    return _Info(keys, shingles, frozenset(keys), bag, lines if words else 0, size, block.kind, pos, window)


# ---------------------------------------------------------------- scoring ---

def _content(a: _Info, b: _Info) -> float:
    if not a.keys or not b.keys:
        return 1.0 if a.keys == b.keys else 0.0
    if a.short or b.short:
        return SequenceMatcher(None, a.keys, b.keys, autojunk=False).ratio()
    return len(a.shingles & b.shingles) / len(a.shingles | b.shingles)


def _content_bound(a: _Info, b: _Info) -> float:
    """An upper bound of :func:`_content`, cheap."""
    if not a.keys or not b.keys:
        return 1.0
    if a.short or b.short:  # SequenceMatcher matches at most the common keys
        common = sum(min(n, b.bag[k]) for k, n in a.bag.items() if k in b.bag)
        return 2 * common / (len(a.keys) + len(b.keys))
    return min(len(a.shingles), len(b.shingles)) / max(len(a.shingles), len(b.shingles))


def _position(a: _Info, b: _Info) -> float:
    # Strictly convex in the distance: among equal contents the in-order
    # pairing is the unique best (a linear term would tie on shifted rows).
    d = abs(a.pos - b.pos)
    return 1.0 - (d + d * d) / 2


def _structure(a: _Info, b: _Info) -> float:
    if a.kind == b.kind:
        kind = 1.0
    else:
        kind = 0.5 if a.kind in _FORM_KINDS and b.kind in _FORM_KINDS else 0.0
    lines = min(a.lines, b.lines) / max(a.lines, b.lines) if max(a.lines, b.lines) else 1.0
    size = min(a.size, b.size) / max(a.size, b.size) if a.size > 0 and b.size > 0 else 1.0
    return (kind + lines + size) / 3


# ---------------------------------------------------------- exact matches ---

def _exact(li: list[_Info], ri: list[_Info]) -> dict[int, int]:
    """Identical, equally frequent texts paired in order."""
    by_left: dict[tuple[str, ...], list[int]] = {}
    by_right: dict[tuple[str, ...], list[int]] = {}
    for i, info in enumerate(li):
        if info.keys:
            by_left.setdefault(info.keys, []).append(i)
    for j, info in enumerate(ri):
        if info.keys:
            by_right.setdefault(info.keys, []).append(j)
    match: dict[int, int] = {}
    for keys, lefts in by_left.items():  # insertion order = target order
        rights = by_right.get(keys, [])
        if len(rights) == len(lefts):
            match.update(zip(lefts, rights, strict=True))
    return match


# ------------------------------------------------------------- candidates ---

def _edges(li: list[_Info], ri: list[_Info], rest_l: list[int], rest_r: list[int],
           anchors: list[tuple[int, int]]) -> dict[tuple[int, int], float]:
    """Scores ≥ THRESHOLD of the pairs that share at least a key (a shingle
    when both blocks are long): others have no content and cannot reach it.

    A posting list longer than :data:`POSTING_CAP` only yields the entries
    nearest to where the block is expected on the generated side (see
    :func:`_centres`); a block that finds no pair that way looks again with
    windows :data:`WIDEN` times wider."""
    index = _Index(ri, rest_r)
    # Virtual anchors at both ends: a block always has one before and one
    # after, so rows closing the document still see an insertion's offset.
    anchors = [(-1, -1), *anchors, (len(li), len(ri))]
    anchor_rows = [i for i, _ in anchors]
    edges: dict[tuple[int, int], float] = {}
    for i in rest_l:
        a = li[i]
        centres = _centres(i, a, anchors, anchor_rows, len(ri))
        found, truncated = index.candidates(a, centres, POSTING_CAP)
        pairs = _scored(a, i, found, ri)
        if not pairs and truncated:
            pairs = _scored(a, i, index.candidates(a, centres, POSTING_CAP * WIDEN)[0], ri)
        edges.update(pairs)
    return edges


def _centres(i: int, a: _Info, anchors: list[tuple[int, int]], anchor_rows: list[int], m: int) -> list[float]:
    """Where target block ``i`` is expected among the generated blocks: its
    proportional position, and the offsets of the nearest exact matches
    (or document ends) before and after it (a local insertion shifts only one
    of the two)."""
    centres = [a.pos * (m - 1)]
    k = bisect.bisect_left(anchor_rows, i)
    if k > 0:
        before_i, before_j = anchors[k - 1]
        centres.append(before_j + (i - before_i))
    if k < len(anchors):
        after_i, after_j = anchors[k]
        centres.append(after_j - (after_i - i))
    return centres


def _scored(a: _Info, i: int, found: list[int], ri: list[_Info]) -> dict[tuple[int, int], float]:
    out: dict[tuple[int, int], float] = {}
    for j in found:
        b = ri[j]
        rest = W_POSITION * _position(a, b) + W_STRUCTURE * _structure(a, b)
        if W_CONTENT * _content_bound(a, b) + rest < THRESHOLD:
            continue
        value = W_CONTENT * _content(a, b) + rest
        if value >= THRESHOLD:
            out[i, j] = value
    return out


class _Index:
    """Posting lists of the remaining generated blocks (ascending indices)."""

    def __init__(self, ri: list[_Info], rest_r: list[int]) -> None:
        self.by_key: dict[str, list[int]] = {}        # every block, by key
        self.by_short_key: dict[str, list[int]] = {}  # short blocks only
        self.by_shingle: dict[tuple[str, ...], list[int]] = {}  # long blocks only
        self.empty: list[int] = []
        for j in rest_r:
            info = ri[j]
            if not info.keys:
                self.empty.append(j)
            for key in sorted(info.vocabulary):
                self.by_key.setdefault(key, []).append(j)
                if info.short:
                    self.by_short_key.setdefault(key, []).append(j)
            if not info.short:
                for shingle in sorted(info.shingles):
                    self.by_shingle.setdefault(shingle, []).append(j)

    def candidates(self, a: _Info, centres: list[float], cap: int) -> tuple[list[int], bool]:
        """Sorted candidates of ``a``, and whether a posting list was cut."""
        if not a.keys:
            lists = [self.empty]
        elif a.short:
            lists = [self.by_key.get(k, []) for k in sorted(a.vocabulary)]
        else:
            lists = ([self.by_shingle.get(s, []) for s in sorted(a.shingles)]
                     + [self.by_short_key.get(k, []) for k in sorted(a.vocabulary)])
        found: set[int] = set()
        truncated = False
        for postings in lists:
            if len(postings) <= cap:
                found.update(postings)
                continue
            truncated = True
            for centre in centres:
                found.update(_near(postings, centre, cap))
        return sorted(found), truncated


def _near(postings: list[int], centre: float, cap: int) -> list[int]:
    """The ``cap`` entries of a posting list (ascending) nearest to ``centre``."""
    lo = hi = bisect.bisect_left(postings, centre)
    while hi - lo < cap:
        if lo > 0 and (hi >= len(postings) or centre - postings[lo - 1] <= postings[hi] - centre):
            lo -= 1
        else:
            hi += 1
    return postings[lo:hi]


def _groups(edges: dict[tuple[int, int], float]) -> list[tuple[list[int], list[int]]]:
    """Connected groups of candidate pairs: (target rows, generated columns),
    sorted, groups ordered by their first target block."""
    parent: dict[tuple[str, int], tuple[str, int]] = {}

    def find(node: tuple[str, int]) -> tuple[str, int]:
        parent.setdefault(node, node)
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for i, j in edges:  # insertion order: deterministic
        a, b = find(("l", i)), find(("r", j))
        if a != b:
            parent[max(a, b)] = min(a, b)
    members: dict[tuple[str, int], tuple[set[int], set[int]]] = {}
    for i, j in edges:
        rows, cols = members.setdefault(find(("l", i)), (set(), set()))
        rows.add(i)
        cols.add(j)
    groups = [(sorted(rows), sorted(cols)) for rows, cols in members.values()]
    return sorted(groups, key=lambda g: g[0][0])


# ------------------------------------------------------------- assignment ---

def _assign(rows: list[int], cols: list[int], edges: dict[tuple[int, int], float],
            li: list[_Info]) -> dict[int, int]:
    """One Hungarian for a group; a group too big is cut on TARGET pages only
    (windows of :data:`WINDOW_PAGES`), each window taking the still free
    generated blocks its rows have candidates with — so a page gained or lost
    on the generated side never separates partners at a window edge."""
    if len(rows) <= WINDOW_BLOCKS and len(cols) <= WINDOW_BLOCKS:
        return _hungarian(rows, cols, edges)
    partners: dict[int, list[int]] = {}
    for i, j in edges:
        partners.setdefault(i, []).append(j)
    match: dict[int, int] = {}
    taken: set[int] = set()
    for window in sorted({li[i].window for i in rows}):
        w_rows = [i for i in rows if li[i].window == window]
        w_cols = sorted({j for i in w_rows for j in partners.get(i, ()) if j not in taken})
        if w_cols:
            found = _hungarian(w_rows, w_cols, edges)
            match.update(found)
            taken.update(found.values())
    return match


def _hungarian(rows: list[int], cols: list[int], edges: dict[tuple[int, int], float]) -> dict[int, int]:
    """Maximise the sum of (score − THRESHOLD) over pairs with an edge: a
    non-edge costs 0, the same as leaving both blocks unpaired."""
    cost = [[THRESHOLD - edges[i, j] if (i, j) in edges else 0.0 for j in cols] for i in rows]
    out: dict[int, int] = {}
    for r, c in enumerate(solve(cost)):
        if c >= 0 and (rows[r], cols[c]) in edges:
            out[rows[r]] = cols[c]
    return out


# ------------------------------------------------------------------ order ---

def _in_target_order(match: dict[int, int], n: int, m: int) -> list[Pair]:
    owner = {j: i for i, j in match.items()}
    before: dict[int, list[int]] = {}
    after: dict[int, list[int]] = {}
    tail: list[int] = []
    previous: int | None = None  # target block holding the last paired generated block
    pending: list[int] = []      # generated blocks before any paired one
    for j in range(m):
        if j in owner:
            if pending:
                before.setdefault(owner[j], []).extend(pending)
                pending = []
            previous = owner[j]
        elif previous is None:
            pending.append(j)
        else:
            after.setdefault(previous, []).append(j)
    tail.extend(pending)
    pairs: list[Pair] = []
    for i in range(n):
        pairs += [(None, j) for j in before.get(i, ())]
        pairs.append((i, match.get(i)))
        pairs += [(None, j) for j in after.get(i, ())]
    pairs += [(None, j) for j in tail]
    return pairs
