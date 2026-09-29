"""The type of a difference (phase 2.5, spec §3.5, D8): ``Diff.tipo``.

The type says WHAT changed, orthogonal to the verdict and to the zone
(a footer brand change is ``parola`` in zone ``footer``); every type counts
(D9) — only the class decides what counts. The first rule that applies:

1. ``link`` — a critical HTML attribute (class ``link``);
2. ``spostamento`` — a move (``spostato``);
3. ``sezione`` — a whole section missing or added, or the page count
   (``sezione_assente``, ``sezione_in_piu``, ``pagine``);
4. ``zona`` — a zone difference where the zone has text on one side only
   on that page (header text against a logo), given by ``zonediff``;
5. ``spazi`` — the same text once whitespace is ignored (class ``spaziatura``);
6. ``maiuscole`` — the same text once case is ignored;
7. ``numeri`` — only digits, their separators ``.,/:-`` and meaningful
   signs (below) changed, with a digit among them or next to every change
   (``1.000`` → ``1,000``, ``-10,00`` → ``10,00``, ``10-12`` → ``10/12``,
   ``10 %`` → ``10``: a sign or a decimal mark is part of a number, never
   "punctuation only" — review A3 I3, final review M1), or a number alone
   (with its signs) is missing or added;
8. ``punteggiatura`` — only punctuation changed away from digits
   (``S.p.A`` → ``S.p.A.``, ``zeta.`` → ``zeta:``), or a text of
   punctuation only is missing or added. A meaningful sign is never
   punctuation (final review M1/M8): ``% ‰ ‱ § * # & @ + = < > °`` and every
   currency or math symbol (Unicode ``Sc`` / ``Sm``); a change of such signs
   only (away from digits), or such a sign alone, is ``altro``;
9. ``parola`` — at most :data:`WORDS` words on the longer side;
10. ``frase`` — more words;
11. ``altro`` — the rest: a change of style (same text, another size or
    weight), noise over equal placeholders, meaningful signs (rule 8).

Pure; stdlib only, no Qt, no pypdfium2.
"""
from __future__ import annotations

import unicodedata
from difflib import SequenceMatcher

from qtrequestory.officina.compare.model import Diff, Tipo

__all__ = ["WORDS", "tipo_of"]

#: A change of at most this many words (on the longer side) is a ``parola``.
WORDS = 3
#: Texts longer than this (characters) are not compared by character.
_CHAR_LIMIT = 400
_NUMBER_MARKS = frozenset(".,/:-")
#: Signs with a meaning of their own: never "solo punteggiatura" (final review M1).
_SIGNS = frozenset("%‰‱§*#&@+=<>°")


def tipo_of(diff: Diff, *, zone_alone: bool = False) -> Tipo:
    """The type of ``diff`` (rules in the module doc); ``zone_alone``: a
    zone difference whose zone has text on one side only (rule 4)."""
    if diff.klass == "link":
        return "link"
    if diff.op == "spostato":
        return "spostamento"
    if diff.op in ("sezione_assente", "sezione_in_piu", "pagine"):
        return "sezione"
    if zone_alone:
        return "zona"
    a, b = diff.left_text, diff.right_text
    if a == b or diff.klass == "stile":
        return "altro"
    if a and b:
        kind = _by_characters(a, b)
        if kind:
            return kind
    else:
        kind = _alone(a or b)
        if kind:
            return kind
    words = max(len(a.split()), len(b.split()))
    return "parola" if words <= WORDS else "frase"


def _by_characters(a: str, b: str) -> Tipo | None:
    if "".join(a.split()) == "".join(b.split()):
        return "spazi"
    if a.casefold() == b.casefold() or "".join(a.casefold().split()) == "".join(b.casefold().split()):
        return "maiuscole"
    if len(a) > _CHAR_LIMIT or len(b) > _CHAR_LIMIT:
        return None
    changed = _changed(a, b)
    numeric = all(c.isdigit() or c in _NUMBER_MARKS or _sign(c) or c.isspace() for c in changed)
    if changed and numeric and (any(c.isdigit() for c in changed) or _by_digits(a, b)):
        return "numeri"
    if changed and all(_punctuation(c) or c.isspace() for c in changed):
        return "punteggiatura"
    if changed and all(_punctuation(c) or _sign(c) or c.isspace() for c in changed):
        return "altro"
    return None


def _alone(text: str) -> Tipo | None:
    """The type of a text on one side only, when it is punctuation, a number
    or signs."""
    solid = "".join(text.split())
    if solid and all(_punctuation(c) for c in solid):
        return "punteggiatura"
    if any(c.isdigit() for c in solid) and all(c.isdigit() or c in _NUMBER_MARKS or _sign(c) for c in solid):
        return "numeri"
    if solid and all(_punctuation(c) or _sign(c) for c in solid):
        return "altro"
    return None


def _by_digits(a: str, b: str) -> bool:
    """Whether every changed run touches a digit (a sign, a thousand or
    decimal mark, a range dash: part of a number, review A3 I3)."""
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        near = a[max(0, i1 - 1):i2 + 1] + b[max(0, j1 - 1):j2 + 1]
        if not any(c.isdigit() for c in near):
            return False
    return True


def _changed(a: str, b: str) -> str:
    """The characters of ``a`` and ``b`` outside their common runs."""
    out: list[str] = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag != "equal":
            out.append(a[i1:i2] + b[j1:j2])
    return "".join(out)


def _sign(c: str) -> bool:
    """A meaningful sign: :data:`_SIGNS`, a currency or a math symbol."""
    return c in _SIGNS or unicodedata.category(c) in ("Sc", "Sm")


def _punctuation(c: str) -> bool:
    """Punctuation proper (``P*``), never a meaningful sign."""
    return unicodedata.category(c).startswith("P") and not _sign(c)
