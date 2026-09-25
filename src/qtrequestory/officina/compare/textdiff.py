"""Word-level text diff between two documents (phase 1: text only).

Left is the reference (TARGET), right the compared version (TO-BE or AS-IS).
The whole document is compared as one word sequence, page-agnostic, so text
that reflows onto another page is not a difference. Before comparing, the
words become comparison *units*:

* each word is :func:`normalise`-d (NFKC, quotes and dashes unified; case kept);
* a word ending in a hyphen (``-``, U+2010 or a soft hyphen; never a dash) at
  a line end, followed by a word starting in lowercase, is joined with it
  ("forni-" + "tura" -> "fornitura");
* a punctuation-only token sticks to its neighbour ("prezzo ," -> "prezzo,",
  "( dodici" -> "(dodici"), so spacing around punctuation is not a difference.

These changes affect the comparison only: a :class:`Difference` carries the
original :class:`Word` objects (text and glyph boxes) of both sides.

Stdlib only (difflib); no Qt, no pypdfium2.
"""
from __future__ import annotations

import difflib
import unicodedata
from dataclasses import dataclass
from typing import Literal

from qtrequestory.officina.compare.extract_pdf import DocText, Word

Kind = Literal["added", "removed", "changed"]

_QUOTES = str.maketrans({
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'", "\u2032": "'", "`": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"', "\u2033": '"',
    "\u00ab": '"', "\u00bb": '"', "\u2039": "'", "\u203a": "'",
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-",
    "\u2015": "-", "\u2212": "-", "\ufe58": "-", "\ufe63": "-", "\uff0d": "-",
})
#: Removed entirely: soft hyphen, zero-width characters, BOM.
_INVISIBLE = dict.fromkeys(map(ord, "\u00ad\u200b\u200c\u200d\u2060\ufeff"))
#: Line-end hyphens that join a split word: hyphen-minus, HYPHEN, soft hyphen.
_HYPHENS = frozenset("-\u2010\u00ad")
#: Punctuation that opens a phrase sticks to the NEXT word, all other to the previous.
_OPENING = set("([{\"'\u00bf\u00a1")


@dataclass(frozen=True)
class Difference:
    id: int
    kind: Kind
    left: list[Word]
    right: list[Word]
    left_text: str
    right_text: str


@dataclass(frozen=True)
class TextComparison:
    differences: list[Difference]
    left_has_text: bool
    right_has_text: bool
    equal: bool
    note: str


def normalise(token: str) -> str:
    """The comparison form of one token. Case is NOT folded."""
    text = unicodedata.normalize("NFKC", token).translate(_INVISIBLE).translate(_QUOTES)
    return "".join(text.split())


def compare_text(left: DocText, right: DocText, *, right_label: str = "TO-BE") -> TextComparison:
    """Compare ``left`` (the target) with ``right`` (``right_label``: TO-BE or AS-IS).

    A side without a text layer is reported in ``note`` and not diffed:
    ``equal=False`` with no differences, rather than every word "removed".
    """
    if not (left.has_text and right.has_text):
        notes = []
        if not left.has_text:
            notes.append("il target non ha testo estraibile")
        if not right.has_text:
            article = "l'" if right_label[:1].upper() in "AEIOU" else "il "
            notes.append(f"{article}{right_label} non ha testo estraibile")
        return TextComparison([], left.has_text, right.has_text, False, "; ".join(notes))

    a_keys, a_words = _units(left.words)
    b_keys, b_words = _units(right.words)
    matcher = difflib.SequenceMatcher(None, a_keys, b_keys, autojunk=False)
    differences: list[Difference] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        kind: Kind = {"replace": "changed", "delete": "removed", "insert": "added"}[tag]
        lw = [w for unit in a_words[i1:i2] for w in unit]
        rw = [w for unit in b_words[j1:j2] for w in unit]
        differences.append(Difference(
            len(differences) + 1, kind, lw, rw,
            " ".join(w.text for w in lw), " ".join(w.text for w in rw),
        ))
    return TextComparison(differences, True, True, not differences, "")


def _units(words: list[Word]) -> tuple[list[str], list[list[Word]]]:
    """Comparison keys and, for each, the original words it stands for."""
    keys: list[str] = []
    members: list[list[Word]] = []
    pending: tuple[str, list[Word]] | None = None  # opening punctuation waiting for its word
    i = 0
    while i < len(words):
        word = words[i]
        key, group = normalise(word.text), [word]
        i += 1
        # Dehyphenate: "forni-" at a line end + "tura" -> "fornitura". Tested on
        # the ORIGINAL text: only a real hyphen joins, never a dash.
        stem = word.text.rstrip()
        if (len(stem) > 1 and stem[-1] in _HYPHENS and i < len(words)
                and _line_end(word, words[i]) and words[i].text[:1].islower()):
            key, group = normalise(stem[:-1]) + normalise(words[i].text), [word, words[i]]
            i += 1
        if not key:
            continue
        if _is_punctuation(key):
            if pending or all(c in _OPENING for c in key):
                pending = (pending[0] + key, pending[1] + group) if pending else (key, group)
                continue
            if keys:
                keys[-1] += key
                members[-1].extend(group)
                continue
        if pending:
            key, group = pending[0] + key, pending[1] + group
            pending = None
        keys.append(key)
        members.append(group)
    if pending:
        keys.append(pending[0])
        members.append(pending[1])
    return keys, members


def _is_punctuation(key: str) -> bool:
    return all(unicodedata.category(c).startswith("P") for c in key)


def _line_end(word: Word, following: Word) -> bool:
    """Whether ``following`` starts a new line (or page) after ``word``."""
    if following.page != word.page:
        return True
    return (following.y0 + following.y1) / 2 > word.y1 or following.x0 < word.x0
