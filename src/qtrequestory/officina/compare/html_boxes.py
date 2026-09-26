"""Boxes for the words of HTML blocks, from Edge's print of the page (spec §6).

``extract_html`` gives words with ``page=0`` and zero boxes: the DOM has no
geometry. The viewer shows an HTML side as its Edge print (phase 1), so the
words get their boxes from that print, in this order:

1. **the print's own words** — the HTML words and the print's words (both as
   ``normalise_token`` keys) are matched with one ``SequenceMatcher`` over the
   whole documents; a matched word takes its partner's page and box;
2. **a neighbour** — a word left unmatched in a block that has matched words
   (the print cut it differently: ``e-mail`` against ``e-`` ``mail``) is put
   right after its previous matched word on the same line, as wide as its
   text at that word's character width (before the next one when it has no
   previous);
3. **a search** — a block none of whose words matched (the print reads a
   column in another order) is looked for as text with
   ``extract_html.locate`` and its words are spread over the first place
   found, in proportion to their length;
4. otherwise the words keep their zero boxes: the difference is only in the
   list and the DOM tab.

A document over :data:`PLACE_MAX` words skips step 1 (no size bound on the
matcher): its blocks are searched instead.

``Block.page`` becomes the page of the block's first placed word. Size and
weight are NOT taken from the print: an HTML block has no font of its own
to compare. Pure (the search is injected); stdlib only, no Qt, no pypdfium2.
"""
from __future__ import annotations

import dataclasses
import difflib
from collections.abc import Callable, Sequence

from qtrequestory.officina.compare.extract_html import locate
from qtrequestory.officina.compare.extract_pdf import DocText
from qtrequestory.officina.compare.model import Block, Word
from qtrequestory.officina.compare.normalise import normalise_token

__all__ = ["PLACE_MAX", "place"]

#: Above this many words on either side the whole-document matcher (step 1)
#: is skipped — its cost has no useful bound on a huge, repetitive page —
#: and every block goes to the search (step 3), else keeps zero boxes.
PLACE_MAX = 20000

Box = tuple[float, float, float, float]
Search = Callable[[str], Sequence[tuple[int, Box]]]


def place(blocks: Sequence[Block], printed: DocText | None, search: Search | None = None) -> list[Block]:
    """``blocks`` with their words boxed from ``printed`` (see module doc);
    unchanged when there is no print."""
    if printed is None or not printed.words:
        return list(blocks)
    flat = [(b, k) for b, block in enumerate(blocks) for k in range(len(block.words))]
    html_keys = [normalise_token(blocks[b].words[k].text) for b, k in flat]
    print_keys = [normalise_token(w.text) for w in printed.words]
    found: dict[tuple[int, int], Word] = {}
    if len(html_keys) <= PLACE_MAX and len(print_keys) <= PLACE_MAX:
        matcher = difflib.SequenceMatcher(None, html_keys, print_keys, autojunk=False)
        for m in matcher.get_matching_blocks():
            for n in range(m.size):
                found[flat[m.a + n]] = printed.words[m.b + n]
    return [_block(block, b, found, search) for b, block in enumerate(blocks)]


def _block(block: Block, b: int, found: dict[tuple[int, int], Word], search: Search | None) -> Block:
    words = list(block.words)
    boxes: list[Word | None] = [found.get((b, k)) for k in range(len(words))]
    if words and not any(boxes) and search is not None:
        boxes = _spread(words, locate(" ".join(w.text for w in words), search))
    if any(boxes):
        _neighbours(words, boxes)
    placed = tuple(_boxed(w, box) for w, box in zip(words, boxes, strict=True))
    first = next((box for box in boxes if box is not None), None)
    return dataclasses.replace(block, words=placed, page=first.page if first is not None else block.page)


def _boxed(word: Word, box: Word | None) -> Word:
    if box is None:
        return word
    return dataclasses.replace(word, page=box.page, x0=box.x0, y0=box.y0, x1=box.x1, y1=box.y1)


def _neighbours(words: list[Word], boxes: list[Word | None]) -> None:
    """Fill the unmatched words of a block from their matched neighbours (in place)."""
    for k in range(len(words)):
        if boxes[k] is None and k > 0 and boxes[k - 1] is not None:
            boxes[k] = _next_to(boxes[k - 1], words[k].text, after=True)
    for k in range(len(words) - 1, -1, -1):
        if boxes[k] is None and k + 1 < len(words) and boxes[k + 1] is not None:
            boxes[k] = _next_to(boxes[k + 1], words[k].text, after=False)


def _next_to(ref: Word, text: str, *, after: bool) -> Word:
    """A box for ``text`` on ``ref``'s line, right after (before) it."""
    char = (ref.x1 - ref.x0) / max(len(ref.text), 1)
    width = char * max(len(text), 1)
    x0 = ref.x1 + char if after else ref.x0 - char - width
    return Word(text, ref.page, x0, ref.y0, x0 + width, ref.y1)


def _spread(words: list[Word], hits: list[tuple[int, Box]]) -> list[Word | None]:
    """The block's words laid over the first place found, by text length."""
    if not hits:
        return [None] * len(words)
    page, (x0, y0, x1, y1) = hits[0]
    total = sum(len(w.text) + 1 for w in words)
    out: list[Word | None] = []
    at = x0
    for w in words:
        width = (x1 - x0) * (len(w.text) + 1) / total
        out.append(Word(w.text, page, at, y0, at + width, y1))
        at += width
    return out
