"""Where a difference sits in the pretty HTML source of the DOM tab (spec §6).

``dom_view`` gives each side as a pretty source: one tag or one run of text
per line, indented two spaces per depth. :func:`parse` rebuilds the element
tree from the indentation (the blocks the tab lists), :func:`locate` finds
each difference's line on both sides:

* a ``link`` difference: the line holding its attribute value (the target's
  old value on the left, the generated one on the right; the URL without its
  query when the normalised value is not in the source verbatim);
* any other: its text in the stream of text lines (whitespace collapsed, so
  a phrase split by an inline tag — ``Scopri le <b>condizioni</b>`` — is
  still found), searched from the previous difference onwards (the list is in
  document order: repeated words land on the right occurrence), else its
  first three words, else its context; an insertion (no target text) is
  placed after its context on the target side.

Qt-free: the widget is ``officina_dom``.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from qtrequestory.ui.contracts import Diff

__all__ = ["INLINE", "Node", "Source", "locate", "node_at", "parse"]

#: Inline elements: never a node of their own, their text belongs to the block around them.
INLINE = frozenset({"a", "abbr", "b", "bdi", "bdo", "br", "cite", "code", "em", "font", "i", "img",
                    "kbd", "mark", "q", "s", "small", "span", "strike", "strong", "sub", "sup",
                    "u", "wbr", "o:p"})
_START = re.compile(r"<([A-Za-z][\w:.-]*)")
_END = re.compile(r"</([A-Za-z][\w:.-]*)")
#: Never shown: no node, and their text is not searched.
_HIDDEN = frozenset({"head", "title", "style", "script", "template", "xml", "meta", "link"})
#: A preview in the tree is this long at most.
PREVIEW = 56


@dataclass
class Node:
    """One block element: its start line, the line after its end, its depth,
    ``step`` like ``td[2]``, the path of steps and the text it holds directly
    (inline children included)."""

    line: int
    depth: int
    tag: str
    step: str
    path: str
    end: int = -1
    text: list[str] = field(default_factory=list)
    children: list[Node] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    def preview(self) -> str:
        text = " ".join(" ".join(self.text).split())
        return text if len(text) <= PREVIEW else text[:PREVIEW - 1] + "…"


@dataclass
class Source:
    """One side: its lines, the block tree (roots) and every node in order."""

    lines: list[str]
    roots: list[Node]
    nodes: list[Node]
    #: The text stream: collapsed text lines joined by one space, and the line of each char run.
    stream: str = ""
    starts: list[tuple[int, int]] = field(default_factory=list)  # (offset in stream, line)
    #: Lines inside ``head``, ``title``, ``style``, ``script``…: never a place for a difference.
    hidden: set[int] = field(default_factory=set)

    def line_of(self, offset: int) -> int:
        line = self.starts[0][1] if self.starts else 0
        for start, number in self.starts:
            if start > offset:
                break
            line = number
        return line


def _depth(raw: str) -> int:
    return (len(raw) - len(raw.lstrip(" "))) // 2


def parse(source: str) -> Source:
    """The block tree and the text stream of one pretty source."""
    lines = source.splitlines()
    roots: list[Node] = []
    nodes: list[Node] = []
    stack: list[tuple[int, str, Node | None]] = []   # (depth, tag, block node or None if inline)
    top = Node(-1, -1, "", "", "")                    # holds the counters of the roots
    pieces: list[str] = []
    starts: list[tuple[int, int]] = []
    hidden: set[int] = set()
    offset = 0

    def close_to(depth: int, at: int) -> None:
        while stack and stack[-1][0] >= depth:
            _d, _t, node = stack.pop()
            if node is not None:
                node.end = at

    def inside_hidden() -> bool:
        return any(t in _HIDDEN for _d, t, _n in stack)

    def block() -> Node | None:
        return next((n for _d, _t, n in reversed(stack) if n is not None), None)

    for i, raw in enumerate(lines):
        text, depth = raw.strip(), _depth(raw)
        end = _END.match(text)
        start = None if end else _START.match(text)
        if end:
            close_to(depth + 1, i)
            if inside_hidden():
                hidden.add(i)
            if stack and stack[-1][0] == depth and stack[-1][1] == end.group(1).lower():
                _d, _t, node = stack.pop()
                if node is not None:
                    node.end = i + 1
        elif start:
            close_to(depth, i)
            tag = start.group(1).lower()
            if tag in _HIDDEN or inside_hidden():
                hidden.add(i)
            if tag in INLINE or tag in _HIDDEN:
                stack.append((depth, tag, None))
                if text.endswith("/>") or tag in ("br", "img", "wbr"):
                    stack.pop()
                continue
            parent = block() or top
            parent.counts[tag] = parent.counts.get(tag, 0) + 1
            step = f"{tag}[{parent.counts[tag]}]"
            node = Node(i, depth, tag, step, f"{parent.path}/{step}" if parent.path else step)
            (parent.children if parent is not top else roots).append(node)
            nodes.append(node)
            stack.append((depth, tag, node))
        elif text and not text.startswith("<!"):
            close_to(depth, i)
            if inside_hidden():
                hidden.add(i)
                continue  # the title, a style sheet, a script: never shown
            owner = block()
            if owner is not None:
                owner.text.append(text)
            words = " ".join(text.split())
            if pieces:
                offset += 1
            starts.append((offset, i))
            pieces.append(words)
            offset += len(words)
    close_to(-1, len(lines))
    return Source(lines, roots, nodes, " ".join(pieces), starts, hidden)


def node_at(src: Source, line: int) -> Node | None:
    """The innermost block holding ``line``."""
    best = None
    for node in src.nodes:
        if node.line <= line < (node.end if node.end >= 0 else len(src.lines)):
            if best is None or node.depth >= best.depth:
                best = node
    return best


def _words(text: str) -> str:
    return " ".join(text.split())


def _find_text(src: Source, needle: str, cursor: int) -> tuple[int, int] | None:
    """``(line, stream offset after the match)`` of ``needle``, searched from
    ``cursor`` onwards, then from the start."""
    if not needle:
        return None
    for begin in (cursor, 0):
        at = src.stream.find(needle, begin)
        if at >= 0:
            return src.line_of(at), at + len(needle)
    return None


def _find_line(src: Source, needles: Iterable[str], after: int) -> int | None:
    for needle in needles:
        if not needle:
            continue
        low = needle.lower()
        order = list(range(after, len(src.lines))) + list(range(0, after))
        for i in order:
            if i not in src.hidden and low in src.lines[i].lower():
                return i
    return None


def _link_needles(value: str, detail: str) -> list[str]:
    """``name="value`` first (``detail`` is "href: a → b": the attribute's
    name), then the bare value; each also without its query."""
    value = value.strip()
    if not value or value.startswith("("):
        return []
    base = value.split("#", 1)[0].split("?", 1)[0]
    values = [value, base] if base and base != value else [value]
    name = detail.split(":", 1)[0].strip().lower() if ":" in detail else ""
    named = [f'{name}="{v}' for v in values] if re.fullmatch(r"[a-z][\w-]*", name) else []
    return [*named, *values]


def _text_needles(diff: Diff, side: str) -> list[str]:
    text = _words(diff.left_text if side == "left" else diff.right_text)
    words = text.split()
    out = [text] if text else []
    if len(words) > 3:
        out.append(" ".join(words[:3]))
    return out


def _unique_word(src: Source, diff: Diff, side: str) -> str:
    """The longest word of the text when it occurs exactly once in the
    source (a common word would put the difference anywhere), else ""."""
    words = _words(diff.left_text if side == "left" else diff.right_text).split()
    if len(words) < 2:
        return ""
    word = max(words, key=len)
    count = len(re.findall(rf"(?<!\S){re.escape(word)}(?!\S)", src.stream))
    return word if count == 1 else ""


def locate(diffs: Sequence[Diff], left: Source, right: Source) -> dict[int, tuple[int | None, int | None]]:
    """``{Diff.id: (target line, generated line)}``; None where it is not found."""
    out: dict[int, tuple[int | None, int | None]] = {}
    cursors = {"left": 0, "right": 0}
    lines = {"left": 0, "right": 0}
    for diff in diffs:
        found: list[int | None] = []
        for side, src in (("left", left), ("right", right)):
            if diff.klass == "link":
                value = diff.left_text if side == "left" else diff.right_text
                line = _find_line(src, _link_needles(value, diff.detail), lines[side])
                if line is None:
                    hit = _find_text(src, _words(value), cursors[side]) if value else None
                    line = hit[0] if hit else None
                found.append(line)
                if line is not None:
                    lines[side] = line
                continue
            hit = None
            for needle in (*_text_needles(diff, side), _unique_word(src, diff, side)):
                hit = _find_text(src, needle, cursors[side])
                if hit:
                    break
            if hit is None:  # an insertion / a deletion: next to its context
                before = _words(diff.context_before).split()[-3:]
                after = _words(diff.context_after).split()[:3]
                hit = _find_text(src, " ".join(before), cursors[side]) if before else None
                if hit is not None:  # after the context: the line where it ends
                    hit = (src.line_of(hit[1] - 1), hit[1])
                elif after:
                    hit = _find_text(src, " ".join(after), cursors[side])
            if hit is not None:
                cursors[side] = hit[1]
                lines[side] = hit[0]
            found.append(hit[0] if hit else None)
        out[diff.id] = (found[0], found[1])
    return out
