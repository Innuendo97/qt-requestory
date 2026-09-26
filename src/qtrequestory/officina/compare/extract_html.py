"""HTML through its DOM (spec §6): blocks, critical attributes, positions.

:func:`extract_html` parses an HTML document with the stdlib ``html.parser``
(no lxml, no inscriptis: the user's decision, no new dependency) and returns
the :class:`Block` list the comparison stages 3–10 work on, plus a pretty
source for the "DOM" tab.

* **Blocks** — one per block element with text: ``p``, ``td``, ``th``,
  ``li``, ``h1``–``h6``; text outside them belongs to the innermost ``div``,
  else to the top-level ``span`` or block-level element holding it, else to
  ``body`` itself (inline text straight in ``body`` — a link, a bold word —
  is ONE block, its ``href`` with it).
  Text around a nested block is split around it ("Prima" / inner table /
  "Dopo"), so the list is in reading order. Inline tags (``b``, ``span``…)
  never split a word; block tags and ``br`` do.
* **Invisible content is skipped** — ``head`` (with ``title``), ``script``,
  ``style``, ``template``, Office's ``<xml>`` (with ``o:``/``v:``/``w:`` tags,
  which never end ``head``), every comment (MSO conditionals included: html.parser
  gives ``<!--[if mso]>…<![endif]-->`` as ONE comment; an unterminated one hides
  everything to the end, as in a browser), and every element with
  ``display:none`` in its ``style`` or a ``hidden`` attribute, with its subtree.
* **dom_path** — the element's path below ``body``, each step counted among
  same-tag siblings: ``table[2]/tr[3]/td[1]``. The source's own structure (no
  implied ``tbody``); a few implied end tags are applied (``li``, ``td``/``th``,
  ``tr``, ``p``…) so sloppy email HTML still nests sensibly.
* **attrs** — critical attributes of the block, in document order: ``href``
  (``a``/``area``; ``mailto:``/``tel:`` too), ``src`` and ``alt`` (``img``).
  URLs pass :func:`urls.normalise` with ``drop`` (default: keep every key, so
  the extraction does not depend on the noise preset); ``alt`` is
  whitespace-collapsed. A block may have attrs and no words (an image cell).
* **Words** — the text split on whitespace like the PDF words, ``page=0``
  and zero boxes, so ``normalise.units`` applies unchanged (zero boxes mean no
  line ends: no comb field, no dehyphenation). The service fills the boxes
  from the Edge print with :func:`locate`.

The ``link`` class comes from the pure :func:`attr_diffs` /
:func:`attr_changes`: given the aligned block pairs (an unpaired side may be
``None``), every critical attribute that differs, ``detail`` like
``"href: a → b"`` (a missing side reads ``(assente)``). ``compare.linkdiff``
turns them into ``link`` differences inside the pipeline.

Stdlib only; no Qt, no pypdfium2 (``locate`` gets the PDF search injected).
"""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from difflib import SequenceMatcher
from html.parser import HTMLParser

from qtrequestory.officina.compare import urls
from qtrequestory.officina.compare.model import Block, Word
from qtrequestory.officina.compare.sanitise import _encoding

__all__ = ["ABSENT", "CHUNK", "attr_changes", "attr_diffs", "extract_html", "locate"]

Box = tuple[float, float, float, float]
Search = Callable[[str], Sequence[tuple[int, Box]]]

#: How a missing attribute reads in a ``link`` detail.
ABSENT = "(assente)"
#: Words per piece when :func:`locate` falls back to searching in pieces.
CHUNK = 6

_HEADINGS = frozenset(f"h{n}" for n in range(1, 7))
_BLOCKS = frozenset({"p", "td", "th", "li"}) | _HEADINGS
_SKIP = frozenset({"head", "title", "script", "style", "template", "xml"})
#: What may sit in ``head``; anything else ends an unclosed head (as browsers do).
_HEAD_CONTENT = frozenset({"base", "link", "meta", "noscript", "script", "style", "template", "title"})
_HEAD = frozenset({"head"})
_VOID = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param",
                   "source", "track", "wbr"})
_TRANSPARENT = frozenset({"html", "body"})
#: Tags whose boundaries separate words (all other tags are inline).
_BREAKS = frozenset({
    "address", "article", "aside", "blockquote", "br", "caption", "center", "dd", "div", "dl", "dt",
    "fieldset", "figcaption", "figure", "footer", "form", "header", "hr", "li", "main", "nav", "ol", "p",
    "pre", "section", "table", "tbody", "td", "tfoot", "th", "thead", "tr", "ul",
}) | _HEADINGS
#: A start tag closes an open element of the first set, not beyond the second.
_IMPLIED: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "li": (frozenset({"li"}), frozenset({"ul", "ol", "table", "td", "th"})),
    "dt": (frozenset({"dt", "dd"}), frozenset({"dl", "table"})),
    "dd": (frozenset({"dt", "dd"}), frozenset({"dl", "table"})),
    "td": (frozenset({"td", "th"}), frozenset({"tr", "table"})),
    "th": (frozenset({"td", "th"}), frozenset({"tr", "table"})),
    "tr": (frozenset({"tr"}), frozenset({"table", "tbody", "thead", "tfoot"})),
    "tbody": (frozenset({"tbody", "thead", "tfoot"}), frozenset({"table"})),
    "thead": (frozenset({"tbody", "thead", "tfoot"}), frozenset({"table"})),
    "tfoot": (frozenset({"tbody", "thead", "tfoot"}), frozenset({"table"})),
}
_CLOSES_P = (_BREAKS - {"br", "td", "th", "tr", "tbody", "thead", "tfoot", "caption"})
_P_SCOPE = frozenset({"td", "th", "table", "caption", "button"})
_DISPLAY_NONE = re.compile(r"display\s*:\s*none", re.IGNORECASE)
_URL_ATTRS = frozenset({"href", "src"})


class _Frame:
    __slots__ = ("children", "hidden", "path", "tag")

    def __init__(self, tag: str, path: str, hidden: bool) -> None:
        self.tag, self.path, self.hidden = tag, path, hidden
        self.children: Counter[str] = Counter()


def extract_html(data: bytes, *, drop: Callable[[str], bool] = urls.keep_all) -> tuple[list[Block], str]:
    """(blocks in reading order, pretty source) of an HTML document. Never raises."""
    parser = _Parser(drop)
    parser.feed(data.decode(_encoding(data), errors="replace"))
    parser.close()
    return parser.blocks, "\n".join(parser.lines) + "\n"


def attr_diffs(left: Sequence[Block], right: Sequence[Block], pairs: Iterable[tuple[int | None, int | None]],
               drop: Callable[[str], bool]) -> list[tuple[int | None, int | None, str]]:
    """``(left index, right index, "name: a → b")`` for each critical attribute
    that differs between the paired blocks (indices into the two lists).
    URLs are compared after :func:`urls.normalise` with ``drop``; each
    attribute name is aligned on its own (a link added in the middle is ONE
    detail, not a shift of every following link). An unpaired block (``None``
    on one side, as ``align`` gives them) has no attributes on that side: each
    of its attributes reads ``(assente)`` on the other."""
    return [(li, ri, f"{name}: {x} → {y}") for li, ri, name, x, y in attr_changes(left, right, pairs, drop)]


def attr_changes(left: Sequence[Block], right: Sequence[Block], pairs: Iterable[tuple[int | None, int | None]],
                 drop: Callable[[str], bool]) -> list[tuple[int | None, int | None, str, str, str]]:
    """:func:`attr_diffs` as ``(left index, right index, name, old, new)``
    (a missing value is :data:`ABSENT`)."""
    out: list[tuple[int | None, int | None, str, str, str]] = []
    for li, ri in pairs:
        a = left[li].attrs if li is not None else ()
        b = right[ri].attrs if ri is not None else ()
        if a == b:
            continue
        names = sorted({n for n, _ in a + b}, key=lambda n: (_ORDER.get(n, len(_ORDER)), n))
        for name in names:
            out.extend((li, ri, name, x, y) for x, y in _changes(_values(a, name, drop), _values(b, name, drop)))
    return out


def locate(blocks_text: str, search: Search) -> list[tuple[int, Box]]:
    """Where a block's text sits in the Edge print: ``(page, box)`` entries.

    ``search(text)`` returns the occurrences of ``text`` in the print (a
    wrapper of ``pdf.TextPage.search``; boxes as the viewer's, origin top-left).
    The whole text (whitespace collapsed) is tried first and every occurrence
    returned; when it is not found (it wraps over lines in the print), the
    text is searched in pieces of :data:`CHUNK` words and each piece keeps its
    first occurrence at or after the previous piece's. Nothing found → ``[]``.
    """
    words = blocks_text.split()
    if not words:
        return []
    hits = list(search(" ".join(words)))
    if hits or len(words) <= CHUNK:
        return hits
    starts = list(range(0, len(words), CHUNK))
    if len(words) - starts[-1] < CHUNK // 2:
        starts.pop()  # a short tail joins the previous piece (a lone word matches anywhere)
    out: list[tuple[int, Box]] = []
    for k, start in enumerate(starts):
        end = starts[k + 1] if k + 1 < len(starts) else len(words)
        found = list(search(" ".join(words[start:end])))
        if not found:
            continue
        last = _position(out[-1]) if out else None
        out.append(next((h for h in found if last is None or _position(h) >= last), found[0]))
    return out


# ------------------------------------------------------------- internals ---

_ORDER = {"href": 0, "src": 1, "alt": 2}


def _values(attrs: tuple[tuple[str, str], ...], name: str, drop: Callable[[str], bool]) -> list[str]:
    if name in _URL_ATTRS:
        return [urls.normalise(v, drop) for n, v in attrs if n == name]
    return [v for n, v in attrs if n == name]


def _changes(a: list[str], b: list[str]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for op, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        old, new = a[i1:i2], b[j1:j2]
        for k in range(max(len(old), len(new))):
            out.append((old[k] if k < len(old) else ABSENT, new[k] if k < len(new) else ABSENT))
    return out


def _position(hit: tuple[int, Box]) -> tuple[int, float, float]:
    page, (x0, y0, _x1, _y1) = hit
    return page, y0, x0


def _office(tag: str) -> bool:
    """Office markup that sits in ``head`` (``<xml>``, ``<o:…>``, ``<v:…>``, ``<w:…>``)."""
    return tag == "xml" or tag[:2] in ("o:", "v:", "w:")


def _one_line(text: str) -> str:
    return " ".join(text.split())


class _Parser(HTMLParser):
    """Builds the blocks and the pretty source in one pass."""

    def __init__(self, drop: Callable[[str], bool]) -> None:
        super().__init__(convert_charrefs=True)
        self.drop = drop
        self.stack: list[_Frame] = [_Frame("", "", False)]
        self.skip = 0          # open elements of _SKIP
        self.blocks: list[Block] = []
        self.lines: list[str] = []
        self.owner: _Frame | None = None   # the element the pending text belongs to
        self.pieces: list[str] = []
        self.attrs: list[tuple[str, str]] = []

    # --- html.parser callbacks ---

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._emit(self.get_starttag_text() or f"<{tag}>", len(self.stack) - 1)
        if tag not in _HEAD_CONTENT and not _office(tag):
            self._close_through(_HEAD, frozenset())
        if tag in _IMPLIED:
            self._close_through(*_IMPLIED[tag])
        if tag in _CLOSES_P:
            self._close_through(frozenset({"p"}), _P_SCOPE)
        if tag in _BREAKS:
            self.pieces.append(" ")
        values = {k: v or "" for k, v in attrs}
        hidden = self.stack[-1].hidden or "hidden" in values or bool(_DISPLAY_NONE.search(values.get("style", "")))
        if not hidden and not self.skip:
            self._collect(tag, values)
        if tag in _VOID:
            return
        parent = self.stack[-1]
        if tag in _TRANSPARENT:
            path = parent.path
        else:
            parent.children[tag] += 1
            step = f"{tag}[{parent.children[tag]}]"
            path = f"{parent.path}/{step}" if parent.path else step
        self.stack.append(_Frame(tag, path, hidden))
        self.skip += tag in _SKIP

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in _BREAKS:
            self.pieces.append(" ")
        crossing = frozenset() if tag in ("table", "html", "body") else frozenset({"table"})
        depth = self._close_through(frozenset({tag}), crossing)
        self._emit(f"</{tag}>", len(self.stack) - 1 if depth is None else depth - 1)

    def handle_data(self, data: str) -> None:
        self._emit(_one_line(data), len(self.stack) - 1)
        if self.stack[-1].tag == "head" and data.strip():
            self._close_through(_HEAD, frozenset())
        if self.skip or self.stack[-1].hidden:
            return
        self._own()
        self.pieces.append(data)

    def handle_comment(self, data: str) -> None:
        self._emit(f"<!--{_one_line(data)}-->", len(self.stack) - 1)

    def handle_decl(self, decl: str) -> None:
        self._emit(f"<!{decl}>", 0)

    def close(self) -> None:
        if self.rawdata.startswith("<!--"):
            # an unterminated comment (a truncated email): a browser hides it
            # to the end of the file; html.parser would hand it over as text
            self._emit(f"<!--{_one_line(self.rawdata[4:])}", len(self.stack) - 1)
            self.rawdata = ""
        super().close()
        self._flush()

    # --- helpers ---

    def _emit(self, text: str, depth: int) -> None:
        text = _one_line(text)
        if text:
            self.lines.append("  " * max(depth, 0) + text)

    def _close_through(self, targets: frozenset[str], boundaries: frozenset[str]) -> int | None:
        """Pop the innermost open element of ``targets`` (and everything above
        it) unless a ``boundaries`` element comes first; its index, or None."""
        for i in range(len(self.stack) - 1, 0, -1):
            tag = self.stack[i].tag
            if tag in targets:
                self.skip -= sum(f.tag in _SKIP for f in self.stack[i:])
                del self.stack[i:]
                return i
            if tag in boundaries:
                return None
        return None

    def _collect(self, tag: str, values: dict[str, str]) -> None:
        found: list[tuple[str, str]] = []
        if tag in ("a", "area") and "href" in values:
            found.append(("href", urls.normalise(values["href"], self.drop)))
        if tag == "img":
            if "src" in values:
                found.append(("src", urls.normalise(values["src"], self.drop)))
            if "alt" in values:
                found.append(("alt", _one_line(values["alt"])))
        if found:
            self._own()
            self.attrs.extend(found)

    def _own(self) -> None:
        """Make the element owning the current position the pending one."""
        owner = self._owner()
        if owner is not self.owner:
            self._flush()
            self.owner = owner

    def _owner(self) -> _Frame:
        frames = self.stack[1:]
        for frame in reversed(frames):
            if frame.tag in _BLOCKS:
                return frame
        for frame in reversed(frames):
            if frame.tag == "div":
                return frame
        top = next((f for f in frames if f.tag not in _TRANSPARENT), None)
        if top is not None and (top.tag == "span" or top.tag in _BREAKS):
            return top
        return self.stack[0]  # inline text straight in body (a link, a bold word): one block

    def _flush(self) -> None:
        words = "".join(self.pieces).split()
        if self.owner is not None and (words or self.attrs):
            self.blocks.append(Block(
                id=len(self.blocks),
                words=tuple(Word(w, 0, 0.0, 0.0, 0.0, 0.0) for w in words),
                page=0, kind="html", dom_path=self.owner.path, attrs=tuple(self.attrs)))
        self.pieces, self.attrs = [], []
