"""Normalisation: from extracted words to comparison units (spec §4.2 step 3).

The comparison channel never sees a word as extracted: each becomes a *unit*
with a comparison key, standing for one or more original words. What changes
is the KEY only — a unit keeps the original :class:`Word` objects (text and
glyph boxes), so highlights always use the original boxes.

Per token (:func:`normalise_token`): NFKC (ligatures, NBSP, full-width forms),
invisible characters dropped, quotes and dashes unified, whitespace removed,
checkbox glyphs unified to :data:`CHECK_OFF` / :data:`CHECK_ON`. Case is kept.

Across tokens (:func:`units`), in this order at each position:

* **comb field** — ≥4 consecutive one-character letters/digits on one line
  whose horizontal pitch (centre to centre) stays within ±25% of the first
  pitch become ONE unit ("I T 6 0 X" → "IT60X"): a form's boxed field;
* **checkboxes** — ``[`` ``]`` → ``☐``, ``[`` ``x`` ``]`` → ``☒`` (``[]``,
  ``[x]``, ``[X]`` as one token too), and a lone ``q`` opening a line that
  goes on (a Wingdings box without a Unicode mapping) → ``☐``;
* **dehyphenation** — a word ending in a hyphen (``-``, U+2010 or a soft
  hyphen; never a dash) at a line end, followed by a word starting in
  lowercase, is joined with it ("forni-" + "tura" → "fornitura");
* **punctuation** — a punctuation-only token sticks to its neighbour
  ("prezzo ," → "prezzo,", "( dodici" → "(dodici"): opening punctuation to
  the next word, all other to the previous one.

Stdlib only; no Qt, no pypdfium2.
"""
from __future__ import annotations

import unicodedata
from collections.abc import Sequence

from qtrequestory.officina.compare.model import Word

__all__ = ["CHECK_OFF", "CHECK_ON", "COMB_MIN", "COMB_TOLERANCE", "line_end", "normalise_token", "units"]

CHECK_OFF, CHECK_ON = "☐", "☒"   # ☐ ☒

#: A comb field has at least this many one-character tokens…
COMB_MIN = 4
#: …whose pitch stays within this share of the first pitch.
COMB_TOLERANCE = 0.25

_QUOTES = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'", "`": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"', "″": '"',
    "«": '"', "»": '"', "‹": "'", "›": "'",
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-",
    "―": "-", "−": "-", "﹘": "-", "﹣": "-", "－": "-",
}
#: Empty boxes: ❏ ❐ ❑ ❒ ☐ □ ◻ ⬜, and the Wingdings boxes as the Private Use
#: Area code points a symbol font maps to (U+F000 + the Wingdings byte).
_BOXES_OFF = "❏❐❑❒☐□◻⬜"
#: Ticked or crossed boxes: ☒ ☑ ⊠ and Wingdings x, ý, þ.
_BOXES_ON = "☒☑⊠"
_TABLE = str.maketrans({
    **_QUOTES,
    **dict.fromkeys(_BOXES_OFF, CHECK_OFF),
    **dict.fromkeys(_BOXES_ON, CHECK_ON),
    # Removed entirely: soft hyphen, zero-width characters, BOM.
    **dict.fromkeys("­​‌‍⁠﻿", None),
})
#: Line-end hyphens that join a split word: hyphen-minus, HYPHEN, soft hyphen.
_HYPHENS = frozenset("-‐­")
#: Punctuation that opens a phrase sticks to the NEXT word, all other to the previous.
_OPENING = set("([{\"'¿¡")
_BRACKET_BOXES = {"[]": CHECK_OFF, "[x]": CHECK_ON, "[X]": CHECK_ON}

_Unit = tuple[str, tuple[Word, ...]]


def normalise_token(text: str) -> str:
    """The comparison form of one token. Case is NOT folded."""
    # Phase-1 order (ruling R3): NFKC first, then the table — so ″ (U+2033)
    # decomposes into two primes and reads '' exactly as in phase 1.
    text = unicodedata.normalize("NFKC", text).translate(_TABLE)
    return "".join(text.split())


def units(words: Sequence[Word]) -> tuple[list[str], list[tuple[Word, ...]]]:
    """Comparison keys and, for each, the original words it stands for.

    Deterministic and pure; ``words`` are in reading order. A word whose key
    is empty (only invisible characters) is dropped.
    """
    keys: list[str] = []
    members: list[tuple[Word, ...]] = []
    pending: _Unit | None = None  # opening punctuation waiting for its word
    for key, group in _tokens(words):
        if _is_punctuation(key):
            if pending or all(c in _OPENING for c in key):
                pending = (pending[0] + key, pending[1] + group) if pending else (key, group)
                continue
            if keys:
                keys[-1] += key
                members[-1] += group
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


def _tokens(words: Sequence[Word]) -> list[_Unit]:
    """Every rule but punctuation: comb fields, checkboxes, dehyphenation."""
    norm = [normalise_token(w.text) for w in words]  # once per word
    out: list[_Unit] = []
    i, n = 0, len(words)
    while i < n:
        end = _comb_end(words, norm, i)
        if end:
            out.append(("".join(norm[i:end]), tuple(words[i:end])))
            i = end
            continue
        box = _bracket_box(words, norm, i)
        if box:
            key, end = box
            out.append((key, tuple(words[i:end])))
            i = end
            continue
        word = words[i]
        key, group = norm[i], (word,)
        i += 1
        if key in _BRACKET_BOXES:
            key = _BRACKET_BOXES[key]
        elif word.text == "q" and _starts_line(words, i - 1) and i < n and not line_end(word, words[i]):
            key = CHECK_OFF  # a Wingdings box ("q") with no Unicode mapping
        else:
            # Dehyphenate: "forni-" at a line end + "tura" -> "fornitura". Tested
            # on the ORIGINAL text: only a real hyphen joins, never a dash.
            stem = word.text.rstrip()
            if (len(stem) > 1 and stem[-1] in _HYPHENS and i < n
                    and line_end(word, words[i]) and words[i].text[:1].islower()):
                key = normalise_token(stem[:-1]) + norm[i]
                group = (word, words[i])
                i += 1
        if key:
            out.append((key, group))
    return out


def _comb_end(words: Sequence[Word], norm: list[str], start: int) -> int:
    """End (exclusive) of the comb field starting at ``start``; 0 if none."""
    if not _comb_char(norm[start]):
        return 0
    end, reference = start + 1, 0.0
    while end < len(words) and _comb_char(norm[end]) and not line_end(words[end - 1], words[end]):
        pitch = _centre(words[end]) - _centre(words[end - 1])
        if pitch <= 0:
            break
        if not reference:
            reference = pitch
        elif abs(pitch - reference) > COMB_TOLERANCE * reference:
            break
        end += 1
    return end if end - start >= COMB_MIN else 0


def _comb_char(key: str) -> bool:
    return len(key) == 1 and key.isalnum()


def _centre(word: Word) -> float:
    return (word.x0 + word.x1) / 2


def _bracket_box(words: Sequence[Word], norm: list[str], start: int) -> tuple[str, int] | None:
    """``[`` ``]`` or ``[`` ``x`` ``]`` on one line at ``start``: (key, end)."""
    if norm[start] != "[":
        return None
    for inner, key in (((), CHECK_OFF), (("x",), CHECK_ON), (("X",), CHECK_ON)):
        end = start + len(inner) + 2
        if end > len(words):
            continue
        texts = norm[start + 1:end]
        same_line = all(not line_end(words[k - 1], words[k]) for k in range(start + 1, end))
        if texts == [*inner, "]"] and same_line:
            return key, end
    return None


def _starts_line(words: Sequence[Word], index: int) -> bool:
    return index == 0 or line_end(words[index - 1], words[index])


def _is_punctuation(key: str) -> bool:
    return all(unicodedata.category(c).startswith("P") for c in key)


def line_end(word: Word, following: Word) -> bool:
    """Whether ``following`` starts a new line (or page) after ``word``."""
    if following.page != word.page:
        return True
    return (following.y0 + following.y1) / 2 > word.y1 or following.x0 < word.x0
