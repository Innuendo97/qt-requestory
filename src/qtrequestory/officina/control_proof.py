"""What a control generation proves (phase 2.5, spec §3.4, ruling F18):
the words of the generated document that print a perturbed value WHOLE
(:func:`proven_words`), and those words carried onto another generation of
the same payload (:func:`map_executed`). The perturbation itself is
``officina.control``.

Stdlib only; no Qt, no pypdfium2.
"""
from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from difflib import SequenceMatcher

from qtrequestory.officina.compare.model import Comparison, Word
from qtrequestory.officina.compare.values import WordKey, parse_number, word_key
from qtrequestory.officina.control import _EDGE, _EPOCH_MS, _ISO_DATE, _PLAIN_NUMBER, _epoch_days, _number

__all__ = ["map_executed", "printed_forms", "printed_sequence", "proven_words"]


def printed_forms(value: object) -> tuple[frozenset[str], frozenset[Decimal]]:
    """How the generator may print ``value``: the words of a text
    (casefolded), a date as dd/mm/yyyy, a number by its value."""
    if isinstance(value, bool) or value is None:
        return frozenset(), frozenset()
    if isinstance(value, (int, float)):
        number = _number(value)
        return frozenset(), frozenset({number}) if number is not None else frozenset()
    text = " ".join(str(value).split())
    if _EPOCH_MS.match(text):
        return frozenset(d.strftime("%d/%m/%Y") for d in _epoch_days(int(text))), frozenset()
    if _PLAIN_NUMBER.match(text):
        number = _number(text)
        return frozenset(), frozenset({number}) if number is not None else frozenset()
    iso = _ISO_DATE.match(text)
    if iso:
        return frozenset({f"{iso.group(3)}/{iso.group(2)}/{iso.group(1)}"}), frozenset()
    return frozenset(t.strip(_EDGE).casefold() for t in text.split() if t.strip(_EDGE)), frozenset()


#: One printed word of a value: the texts it may read (casefolded; a date's
#: possible days) or a number compared by value.
_Token = tuple[frozenset[str], "Decimal | None"]


def printed_sequence(value: object) -> list[_Token]:
    """The words the generator prints for ``value``, IN ORDER: a text's
    words (casefolded), a date as one dd/mm/yyyy word, a number as one word
    compared by value; empty when it has none."""
    texts, numbers = printed_forms(value)
    if numbers:
        return [(frozenset(), next(iter(numbers)))]
    text = " ".join(str(value).split()) if isinstance(value, str) else ""
    if _EPOCH_MS.match(text) or _ISO_DATE.match(text):
        return [(texts, None)] if texts else []
    return [(frozenset({t.strip(_EDGE).casefold()}), None) for t in text.split() if t.strip(_EDGE)]


def _is_token(text: str, token: _Token) -> bool:
    word = text.strip(_EDGE)
    if word.casefold() in token[0]:
        return True
    number = parse_number(word) if token[1] is not None else None
    return number is not None and number.normalize() == token[1]


def _runs(words: Sequence[Word], sequence: Sequence[_Token]) -> list[int]:
    """The starts of the contiguous runs of ``words`` that print the WHOLE ``sequence``."""
    n = len(sequence)
    if not n:
        return []
    return [i for i in range(len(words) - n + 1) if all(_is_token(words[i + k].text, sequence[k]) for k in range(n))]


#: The classes of a text difference (``values.changed_words``).
_TEXT_CHANGES = frozenset({"testo", "zona", "variabile", "rumore", "arredo", "composizione"})


def proven_words(comparison: Comparison, changed: Sequence[tuple[object, object]]) -> frozenset[WordKey]:
    """The words of the generation (the LEFT side of ``comparison`` =
    generation vs control) that the control proves to be values (ruling
    F18): in a text difference, a contiguous run of words printing the WHOLE
    original value of a perturbed leaf (``changed``: ``(original,
    perturbed)``), matched at the same place on the control side by a
    contiguous run printing the whole perturbed value (the same offset in
    the difference, or the same words before it). Nothing else in the
    difference is proven: a word of the value found elsewhere, a label or a
    sentence a condition switched, even on the same line. Known costs,
    conservative (fewer proofs, never a hidden difference): a value printed
    after dot leaders gets no proof (the control splits it into a slot and a
    missing run); upper-case code-like texts are never perturbed (``_ENUM``),
    printed upper-case data included."""
    pairs = [(printed_sequence(old), printed_sequence(new)) for old, new in changed]
    out: set[WordKey] = set()
    for d in comparison.diffs:
        if d.klass not in _TEXT_CHANGES or d.op == "spostato":
            continue
        left, right = list(d.left), list(d.right)
        for old, new in pairs:
            targets = _runs(right, new)
            for i in _runs(left, old):
                before = [w.text for w in left[:i]]
                if any(j == i or [w.text for w in right[:j]] == before for j in targets):
                    out.update(word_key(w) for w in left[i:i + len(old)])
    return frozenset(out)


def map_executed(reference: Sequence[Word], other: Sequence[Word], executed: frozenset[WordKey]
                 ) -> frozenset[WordKey]:
    """``executed`` (keys of ``reference``'s words) carried onto ``other``:
    the words the two documents share in the same order keep their proof."""
    if not executed:
        return frozenset()
    matcher = SequenceMatcher(None, [w.text for w in reference], [w.text for w in other], autojunk=False)
    out = set()
    for block in matcher.get_matching_blocks():
        for k in range(block.size):
            if word_key(reference[block.a + k]) in executed:
                out.add(word_key(other[block.b + k]))
    return frozenset(out)
