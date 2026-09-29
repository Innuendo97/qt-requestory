"""The variables' second pass (phase 2.5, spec §3.3; task A4, ruling F16):
after the word diff, part of a text difference becomes a ``variabile`` when
BOTH a position proof and a value proof hold (``proofs``).

What the generated side adds (an ``in_piu``, or each added part of a
``cambiato``) is cut into VALUE RUNS (``proofs.value_runs``: value-shaped
tokens, or a text known to the payload, the dictionary's value cells or a
control generation). A run becomes the variable when the target leaves a
matching room for it; ``Diff.prova`` says which:

* ``segnaposto`` — the target holds a placeholder there (``[xx]``, ``XXXX``,
  ``gg/mm/aaaa``), or a target leader / ``{{…}}`` slot swallowed it
  (``slots``); a conditional ``{{…}}`` text the generated side leaves out is
  one too. An explicit placeholder is the template's own declaration of a
  value: whatever fills it on one line is the value;
* ``cella`` — a table cell empty in the target, or holding only a unit (a
  lone target unit left behind in a cell its value filled is part of it);
* ``buco`` — a gap in one line, an indented line start in running text, or
  the end of a line after a label ending in «:», whose extent matches the
  value (``proofs.fits``); in a shoulder, after a «:» ending its line;
* ``sezione`` — a whole inserted text under a heading (bold, larger or in
  capitals) followed by an empty band, known to the payload or to a
  control generation;
* ``listino`` / ``esecuzione`` — the run is proven in position AND its value
  is a numeric value cell of the dictionary / changed in a control
  generation: the proof names what made it a value.

**Never a variable**: a type ``maiuscole``, ``punteggiatura`` or ``spazi``;
free words (neither value-shaped nor known); a text of several words that
the target prints as fixed text elsewhere; header and footer text (slots
only). The payload alone never proves: it names (``Diff.nome``), and proves
a value only together with a position.

**Split**: the tokens outside the value runs (and the target words a value
replaced) keep counting as one difference with their words — the original
anchor and class, so the verdicts, tolerances and marks stored on the
original anchor stay on this rest — and the value becomes its own
``variabile`` right after it, anchored on the same context with
``target_text`` + «⎵» («periodo ⎵ mesi» → «periodo 12 settimane»: «mesi →
settimane» counts, «12» is the variable). A difference proven whole keeps
its anchor, so "non è una variabile" (``verdict.judge``) turns it back.

**Switches**: a proof not in ``Values.proofs`` proves nothing — nothing is
split, the difference counts, but keeps ``prova`` and ``nome`` so the
filter panel still counts it (F7). A slot's ``variabile`` whose proof is
switched off counts again (``testo``, ``zona``, ``arredo`` in a zone set aside).

:func:`occurrences` gives the "Variabili riconosciute" rows' occurrences.

Deterministic and pure; stdlib only, no Qt, no pypdfium2.
"""
from __future__ import annotations

import dataclasses
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from qtrequestory.officina.compare.filter_model import FilterOccurrence
from qtrequestory.officina.compare.holes import on_one_line
from qtrequestory.officina.compare.model import PROVE, Anchor, Diff, Word
from qtrequestory.officina.compare.normalise import normalise_token
from qtrequestory.officina.compare.placeholders import is_conditional, is_placeholder
from qtrequestory.officina.compare.proofs import (
    FLOW,
    TOKEN,
    Context,
    alnum,
    context_of,
    hole,
    inside,
    plain,
    replaced_hole,
    unit_only,
    unit_only_text,
    value_runs,
    value_source,
)
from qtrequestory.officina.compare.tipi import tipo_of
from qtrequestory.officina.compare.worddiff import char_spans

__all__ = ["HOLE", "NO_NAME", "NO_SITE", "Context", "Site", "context_of", "occurrences", "recognise", "site"]

#: Appended to ``target_text`` in the anchor of a value split off a difference.
HOLE = "⎵"
#: An occurrence's ``dettaglio`` when no payload leaf or dictionary entry names the value.
NO_NAME = "nome non trovato"
#: The words around a difference: the target's before and after it, the generated side's before and after it.
Site = tuple[Word | None, Word | None, Word | None, Word | None]
NO_SITE: Site = (None, None, None, None)

_NEVER_TIPI = frozenset({"maiuscole", "punteggiatura", "spazi"})
_TEXT_KLASSES = frozenset({"testo", "zona"})
_LEADER = re.compile(r"[._…]{4,}")
_VALUE_PROOFS = frozenset({"listino", "esecuzione"})

Tokens = list[tuple[str, Word]]


def site(left: Sequence[tuple[Word, ...]], right: Sequence[tuple[Word, ...]], i1: int, i2: int,
         j1: int, j2: int) -> Site:
    """The :data:`Site` of a difference over the keys ``[i1, i2)`` / ``[j1, j2)``
    of two sides whose keys hold the words ``left`` / ``right`` (keys
    without words, a probable slot, are skipped)."""
    return _near(left, i1 - 1, -1), _near(left, i2, 1), _near(right, j1 - 1, -1), _near(right, j2, 1)


def _near(members: Sequence[tuple[Word, ...]], k: int, step: int) -> Word | None:
    while 0 <= k < len(members):
        if members[k]:
            return members[k][-1] if step < 0 else members[k][0]
        k += step
    return None


def recognise(diffs: Sequence[Diff], sites: Sequence[Site], ctx: Context) -> list[Diff]:
    """The differences after the second pass (module doc), in order; a
    split difference gives two. Ids are left as they are (the caller
    renumbers)."""
    out: list[Diff] = []
    for diff, where in zip(diffs, sites, strict=True):
        out += _one(diff, where, ctx)
    return [_lone_unit(d, ctx) for d in out]


def occurrences(diffs: Sequence[Diff]) -> dict[str, tuple[FilterOccurrence, ...]]:
    """``variabile.<proof>`` → the occurrences of the differences carrying
    that proof, variables or not (a proof switched off still counts them);
    ``dettaglio`` is the value's name, or :data:`NO_NAME`."""
    out: dict[str, list[FilterOccurrence]] = {f"variabile.{p}": [] for p in PROVE}
    for d in diffs:
        if not d.prova:
            continue
        words = d.left or d.right
        pages = tuple(sorted({w.page for w in words}))
        text = d.right_text or d.left_text
        out[f"variabile.{d.prova}"].append(FilterOccurrence(text, pages, (d.anchor,), (), d.zone,
                                                            d.nome or NO_NAME))
    return {k: tuple(v) for k, v in out.items()}


# ------------------------------------------------------------- per diff ---

def _one(d: Diff, where: Site, ctx: Context) -> list[Diff]:
    if d.klass == "variabile":
        return _slot(d, ctx)
    if d.tipo in _NEVER_TIPI:
        return [d]
    if d.klass in _TEXT_KLASSES and d.op == "mancante":
        return [_missing(d, ctx)]
    if d.klass in _TEXT_KLASSES and d.op in ("in_piu", "cambiato"):
        return _added(d, where, ctx)
    if d.op == "sezione_in_piu" and d.klass == "composizione":
        return [_section(d, where, ctx) or d]
    return [d]


def _slot(d: Diff, ctx: Context) -> list[Diff]:
    """A target slot's ``variabile``: its proof, its name, and its class
    back to a counting one when that proof is switched off. A leader or a
    placeholder declares a value: its fill is the value. A probable slot is
    only a label: what it swallowed is cut to its value run (F16), the free
    words around it count (with the slot's anchor), and a fill without a
    value counts whole."""
    placeholder = _braces(d.left_text)
    marked = placeholder or _LEADER.search(d.anchor.target_text) or any(is_placeholder(w.text) for w in d.left)
    prova = "segnaposto" if marked else "buco"
    name = placeholder or _name(ctx, d.right_text)
    d = dataclasses.replace(d, prova=prova, nome=name)
    counting = "testo" if d.zone in FLOW else ("arredo" if d.zone in ctx.aside else "zona")
    if prova not in ctx.values.proofs:
        spans = char_spans(d.left_text, d.right_text) if d.op == "cambiato" else ((), ())
        return [dataclasses.replace(d, klass=counting, left_spans=spans[0], right_spans=spans[1])]
    if marked:
        return [d]
    tokens = _tokens(d.right)
    runs = [r for r in value_runs(tokens, ctx) if not ctx.fixed(plain(tokens[r[0]:r[1]]))]
    if not runs:
        return [_rebuilt(d, [], tokens, d.anchor, counting)]
    start, end, _ = runs[0]
    rest = tokens[:start] + tokens[end:]
    if not rest:
        return [d]
    value = tokens[start:end]
    anchor = dataclasses.replace(d.anchor, target_text=f"{d.anchor.target_text} {HOLE}".strip())
    variable = _rebuilt(d, [], value, anchor, "variabile")
    return [_rebuilt(d, [], rest, d.anchor, counting),
            dataclasses.replace(variable, prova="buco", nome=_name(ctx, plain(value)))]


def _missing(d: Diff, ctx: Context) -> Diff:
    """A target text the generated side leaves out: a conditional ``{{…}}``
    text or a placeholder is a ``segnaposto`` variable."""
    text = d.left_text.strip()
    if (_braces(text) == text and _conditional(text)) or (d.left and all(_is_placeholder_token(w) for w in d.left)):
        return _as_variable(d, "segnaposto", text, ctx)
    return d


def _section(d: Diff, where: Site, ctx: Context) -> Diff | None:
    """A whole text under a heading over an empty band, known to the payload
    or a control generation (never free text alone: new paragraphs count)."""
    tb, ta, _, _ = where
    tokens = _tokens(d.right)
    if tb is None or ta is None or ctx.target is None or d.zone not in FLOW or not tokens:
        return None
    if not ctx.target.void_below(tb, ta) or value_source(tokens, ctx) is None or ctx.fixed(d.right_text):
        return None
    return _as_variable(d, "sezione", _name(ctx, d.right_text), ctx)


@dataclass
class _Piece:
    left: Tokens
    right: Tokens
    prova: str | None = None
    run: tuple[int, int] = (0, 0)          # the value's tokens in ``right``
    value_left: Tokens = field(default_factory=list)   # placeholder tokens the value replaces


def _added(d: Diff, where: Site, ctx: Context) -> list[Diff]:
    """An ``in_piu`` or ``cambiato``: each added part's value run proven (module doc)."""
    if d.op == "in_piu":
        section = _section(d, where, ctx)
        if section is not None:
            return [section]
    tb, ta, gb, ga = where
    lt, rt = _tokens(d.left), _tokens(d.right)
    if d.op == "in_piu":
        ops = [("insert", 0, 0, 0, len(rt))]
    else:
        ops = SequenceMatcher(None, [t for t, _ in lt], [t for t, _ in rt], autojunk=False).get_opcodes()
    pieces: list[_Piece] = []
    for tag, i1, i2, j1, j2 in ops:
        if tag == "equal":
            continue
        piece = _Piece(lt[i1:i2], rt[j1:j2])
        pieces.append(piece)
        if piece.left and all(_is_placeholder_token(w) for _, w in piece.left):
            filled = _words(piece.right)
            if not filled or (alnum(plain(piece.right)) and all(on_one_line(filled[0], w) for w in filled)):
                piece.prova, piece.value_left, piece.run = "segnaposto", piece.left, (0, len(piece.right))
            continue
        before = lt[i1 - 1][1] if i1 > 0 else tb
        after = lt[i2][1] if i2 < len(lt) else ta
        if not piece.left and before is not None and before is after:
            continue                       # inside one target word: no room there
        for start, end, source in value_runs(piece.right, ctx, replacing=bool(piece.left)):
            run = piece.right[start:end]
            value = _words(run)
            if ctx.fixed(plain(run)):
                continue
            if piece.left:
                # the value is what the room took: the run next to it; the other words replace target words
                side = replaced_hole(before, piece.left[0][1], piece.left[-1][1], after, value, d.zone, ctx)
                position = "buco" if _inserted_at(piece, side, start, end) else None
            else:
                g_before = piece.right[start - 1][1] if start > 0 else (rt[j1 - 1][1] if j1 > 0 else gb)
                g_after = piece.right[end][1] if end < len(piece.right) else (rt[j2][1] if j2 < len(rt) else ga)
                position = hole(before, after, g_before, g_after, value, d.zone, ctx, d)
            if position:
                piece.prova = source if source in _VALUE_PROOFS else position
                piece.run = (start, end)
                break                      # a room holds one value
    return _assembled(d, pieces, ctx)


def _inserted_at(piece: _Piece, side: str, start: int, end: int) -> bool:
    """Whether the run ``[start, end)`` of a replacing piece is made only of
    words INSERTED at the room's side: a piece of n target words replaced by
    m generated words has m − n inserted words, the first ones (room before)
    or the last ones (room after); the other generated words take the
    places of target words — a substitution («12 → 18», «anni → mesi»), never
    a value (review A4 fix 2, Important 1)."""
    generated, replaced = _words(piece.right), _words(piece.left)
    extra = len(generated) - len(replaced)
    if extra <= 0 or side not in ("before", "after"):
        return False
    room = generated[:extra] if side == "before" else generated[-extra:]
    run = _words(piece.right[start:end])
    at_edge = start == 0 if side == "before" else end == len(piece.right)
    return at_edge and all(any(w is x for x in room) for w in run)


def _assembled(d: Diff, pieces: list[_Piece], ctx: Context) -> list[Diff]:
    """The difference after its pieces were proven: unchanged, a variable
    whole, or split into the counting rest and the variable (module doc)."""
    proven = [p for p in pieces if p.prova]
    if not proven:
        return [d]
    values_right = [t for p in proven for t in p.right[p.run[0]:p.run[1]]]
    placeholders = [t for p in proven for t in p.value_left]
    name = _braces(" ".join(w.text for w in _words(placeholders))) or _name(ctx, plain(values_right))
    on = [p for p in proven if p.prova in ctx.values.proofs]
    if not on:
        return [dataclasses.replace(d, prova=proven[0].prova, nome=name)]
    rest_left = [t for p in pieces for t in p.left if not (p in on and p.value_left)]
    rest_right = [t for p in pieces for k, t in enumerate(p.right) if not (p in on and p.run[0] <= k < p.run[1])]
    value_left = [t for p in on for t in p.value_left]
    value_right = [t for p in on for t in p.right[p.run[0]:p.run[1]]]
    if not rest_left and not rest_right:
        return [_as_variable(d, on[0].prova, name, ctx)]
    rest = _rebuilt(d, rest_left, rest_right, d.anchor, d.klass)
    anchor = Anchor("cambiato" if value_left else "in_piu", "variabile", d.anchor.context,
                    f"{d.anchor.target_text} {HOLE}".strip())
    variable = _rebuilt(d, value_left, value_right, anchor, "variabile")
    return [rest, dataclasses.replace(variable, prova=on[0].prova, nome=name)]


def _lone_unit(d: Diff, ctx: Context) -> Diff:
    """A target unit left alone (``mancante``) in a cell a value filled with
    that same unit: part of that value."""
    if d.op != "mancante" or d.klass not in _TEXT_KLASSES or not d.left or not unit_only(d.left):
        return d
    for page, box, filled in ctx.cells:
        if all(w.page == page and inside(box, w) for w in d.left) and d.left_text.strip() in filled.right_text:
            return _as_variable(d, "cella", _name(ctx, filled.right_text), ctx)
    return d


# --------------------------------------------------------------- helpers ---

def _name(ctx: Context, text: str) -> str:
    """The name of a value: the whole text's (dictionary, else payload), else
    that of the text without its units, else that of its last word holding a
    digit (a code or an amount after its label)."""
    tries = [text, " ".join(w for w in text.split() if not unit_only_text(w))]
    tries += [w for w in reversed(text.split()) if any(c.isdigit() for c in w)]
    for candidate in tries:
        name = ctx.values.name(candidate)[0] if candidate else ""
        if name:
            return name
    return ""


def _as_variable(d: Diff, prova: str, name: str, ctx: Context) -> Diff:
    if prova not in ctx.values.proofs:
        return dataclasses.replace(d, prova=prova, nome=name)
    return dataclasses.replace(d, klass="variabile", left_spans=(), right_spans=(), prova=prova, nome=name)


def _rebuilt(d: Diff, left: Tokens, right: Tokens, anchor: Anchor, klass: str) -> Diff:
    op = "cambiato" if left and right else ("mancante" if left else "in_piu")
    lw, rw = _words(left), _words(right)
    left_text, right_text = plain(left), plain(right)
    spans = char_spans(left_text, right_text) if op == "cambiato" and klass != "variabile" else ((), ())
    empty = None
    if bool(lw) != bool(rw):
        near = (d.left or d.right)[:1] if not lw else (d.right or d.left)[:1]
        empty = (near[0].page, near[0].x0, near[0].y0, near[0].x1, near[0].y1) if near else d.empty_at
    made = dataclasses.replace(d, op=op, klass=klass, left=lw, right=rw, left_text=left_text, right_text=right_text,
                               left_spans=spans[0], right_spans=spans[1], anchor=anchor, empty_at=empty,
                               prova="", nome="")
    return dataclasses.replace(made, tipo=tipo_of(made))


def _tokens(words: Sequence[Word]) -> Tokens:
    return [(t, w) for w in words for t in TOKEN.findall(normalise_token(w.text))]


def _words(tokens: Sequence[tuple[str, Word]]) -> tuple[Word, ...]:
    out: list[Word] = []
    for _, w in tokens:
        if not any(x is w for x in out):
            out.append(w)
    return tuple(out)


def _conditional(text: str) -> bool:
    """Whether ``{{…}}`` (outermost) holds a conditional text, not a value."""
    return is_conditional(re.sub(r"\{\{[^{}]*\}\}", "", text[2:-2]))


def _braces(text: str) -> str:
    """The ``{{…}}`` placeholder in ``text`` (outermost), or ``""``."""
    start, end = text.find("{{"), text.rfind("}}")
    return text[start:end + 2] if 0 <= start < end else ""


def _is_placeholder_token(word: Word) -> bool:
    """A placeholder the slots do not own: ``[xx]``, an ``X`` or date mask —
    a leader or a ``{{…}}`` value is a slot (``slots``), and a slot the user
    switched off must stay off."""
    text = word.text
    return is_placeholder(text) and not _LEADER.search(normalise_token(text)) and "{{" not in text
