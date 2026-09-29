"""Readable changed tokens in the differences' snippets (``officina_rows``;
phase 2.5, I1b).

Character-level marking reads well only for a pure insertion or deletion
inside one word ("abilitat**o**" → one letter added). Anything else, marked
letter by letter, interleaves the two texts into a token nobody wrote:
"12,50" → "18,40" read «128,540», "04/2026" → "05/2026" read «045/2026»,
"abilitata" → "abilitato" read «abilitatao». So a changed token is shown
whole, «old → new» (old struck, new inserted), when:

* the change replaces characters (something removed AND something added), or
* the token holds more than one changed run, or
* the token is a number, a date or a code (:func:`is_code`: a digit or "_").

When the two sides do not line up (shown one after the other,
:func:`token_spans`) every changed token is marked whole. A token is a run
of non-space characters around the change. The rule
applies wherever a snippet is drawn: the list rows, their tooltips and
plain text (``snippet_html`` / ``snippet_text`` / ``snippet_plain`` all
read :func:`aligned_pieces` or :func:`token_spans` through ``_pieces``).
"""
from __future__ import annotations

from collections.abc import Sequence

__all__ = ["aligned_pieces", "is_code", "token_spans"]

Piece = tuple[str, str]


def is_code(token: str) -> bool:
    """A number, a date, an amount or a code: it holds a digit or "_"."""
    return any(c.isdigit() or c == "_" for c in token)


def _tail(text: str) -> str:
    """The non-space characters at the end of ``text``."""
    n = len(text)
    while n > 0 and not text[n - 1].isspace():
        n -= 1
    return text[n:]


def _head(text: str) -> str:
    """The non-space characters at the start of ``text``."""
    n = 0
    while n < len(text) and not text[n].isspace():
        n += 1
    return text[:n]


def aligned_pieces(lp: Sequence[str], rp: Sequence[str]) -> list[Piece]:
    """The pieces of two texts split as ``[same0, changed0, same1, …]`` whose
    unchanged parts line up (``lp[0::2] == rp[0::2]``): "same", "del", "ins"
    and "to" (the arrow of a whole token shown «old → new»)."""
    same, gone, made = list(lp[0::2]), list(lp[1::2]), list(rp[1::2])
    out: list[Piece] = []
    carry = same[0]
    k, n = 0, len(gone)
    while k < n:
        m = k  # the changes of one token: joined by unchanged text without a space
        while m + 1 < n and not any(c.isspace() for c in same[m + 1]):
            m += 1
        after = same[m + 1]
        prefix, suffix = _tail(carry), _head(after)
        inner = range(k, m + 1)
        old = prefix + "".join(gone[i] + (same[i + 1] if i < m else "") for i in inner) + suffix
        new = prefix + "".join(made[i] + (same[i + 1] if i < m else "") for i in inner) + suffix
        whole = m > k or any(gone[i] and made[i] for i in inner) or is_code(old) or is_code(new)
        if whole:
            out.append(("same", carry[:len(carry) - len(prefix)]))
            if old and new:
                out += [("del", old), ("to", " → "), ("ins", new)]
            else:
                out.append(("del", old) if old else ("ins", new))
            carry = after[len(suffix):]
        else:  # one run only removed or only added inside a word: its letters marked
            out += [("same", carry), ("del", gone[k]), ("ins", made[k])]
            carry = after
        k = m + 1
    out.append(("same", carry))
    return [p for p in out if p[1]]


def token_spans(text: str, spans: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    """``spans`` of ``text`` widened to their whole token (the texts of a
    difference whose sides do not line up, shown one after the other: a
    letter marked there has no counterpart to read against, "ventiquattr"
    + "o"). An empty span (the other side's insertion point) stays empty."""
    tokens: dict[tuple[int, int], list[tuple[int, int]]] = {}  # token extent -> its spans
    for start, end in sorted((max(0, s), min(len(text), e)) for s, e in spans):
        if end <= start:
            continue
        left = start - len(_tail(text[:start]))
        right = end + len(_head(text[end:]))
        tokens.setdefault((left, right), []).append((start, end))
    out: list[tuple[int, int]] = []
    for left, right in tokens:
        out.append((left, right))
    return sorted(out)
