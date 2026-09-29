"""The proofs of the variables' second pass (phase 2.5, spec §3.3; task A4,
ruling F16): what ``variables`` asks of one inserted text, and the
:class:`Context` it reads (both sides' geometry from ``holes``, the target's
text, the :class:`~values.Values`, the zones set aside).

Ruling F16: a text becomes a variable only with BOTH proofs —

* **position** (:func:`hole`, :func:`replaced_hole`): the target leaves room
  at that place whose extent MATCHES the value — a gap on one line that
  stands out from the block's own spacing (:func:`hole_room`), or the end of
  a line after a label ending in «:», whose room / (value width + a space
  each side) lies in ``[RATIO_LOW, RATIO_HIGH]``, never more than one line;
  or a table cell that is empty or holds only a unit. An indented line
  start is layout (a paragraph's first line), never a hole;
* **value** (:func:`value_runs`, :func:`value_source`): the text is
  value-shaped (a number, amount, date, percentage or code: a token with a
  digit, the separators inside it, a unit or a month name next to it), or
  exactly a payload value in Italian format, or exactly a numeric VALUE cell
  of the dictionary (label and header cells only name), or every word of it
  changed in a control generation (``esecuzione``).

Free words (neither value-shaped nor matched) are never inside a value run:
``variables`` leaves them counting.

Deterministic and pure; stdlib only, no Qt, no pypdfium2.
"""
from __future__ import annotations

import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field

from qtrequestory.officina.compare.extract_pdf import DocText
from qtrequestory.officina.compare.holes import Geometry, char_width, on_one_line, width_of
from qtrequestory.officina.compare.model import ARREDO_ZONES, Diff, Word
from qtrequestory.officina.compare.normalise import normalise_token
from qtrequestory.officina.compare.values import Values, word_key

__all__ = ["CHARS", "FLOW", "RATIO_HIGH", "RATIO_LOW", "SPACES", "TOKEN", "Context", "alnum", "centre", "context_of",
           "fits", "hole", "hole_room", "inside", "occupied", "plain", "replaced_hole", "unit_only", "unit_only_text", "value_runs",
           "value_source"]

#: The zones whose words flow as the body (the only ones with holes, cells and sections).
FLOW = frozenset({"corpo", "titolo"})
#: A word or a punctuation mark.
TOKEN = re.compile(r"\w+|[^\w\s]")
#: A room matches a value when room / (value width + a space each side) lies in this band (F16).
RATIO_LOW, RATIO_HIGH = 0.6, 2.0
#: A hole is at least this many times its block's typical inter-word space…
SPACES = 2.5
#: …and at least this many characters (a character = half a text height).
CHARS = 2.5
#: The only label terminator after which the end of a line is a hole (F16; a leader is a slot).
_LABEL_END = ":"
#: A space, in characters (a character = half a text height).
_SPACE = 0.6
_SHOULDERS = frozenset({"spalla_sx", "spalla_dx"})
#: Unit-of-measure words (casefolded) a cell may hold without a value.
_UNITS = frozenset({"euro", "eur", "cent", "centesimi", "anno", "anni", "mese", "mesi", "giorno", "giorni", "gg"})
#: A unit may also be compound: short words joined by «/» («€/unità/anno»).
_COMPOUND_PART = 6
_UNIT_MARKS = frozenset("€%/()-.,:")
_MONTHS = frozenset({"gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre",
                     "ottobre", "novembre", "dicembre"})


@dataclass
class Context:
    """One comparison's inputs to the pass: both sides' geometry
    (``holes.Geometry``, None without boxes), the target's text (for the
    fixed-text rule), the :class:`~values.Values` and the zones set aside."""

    target: Geometry | None
    generated: Geometry | None
    target_text: str
    values: Values = field(default_factory=Values)
    aside: Collection[str] = ARREDO_ZONES
    cells: list[tuple[int, tuple, Diff]] = field(default_factory=list)   # cells a value filled

    @staticmethod
    def of(target_words: Sequence[Word], target_geometry: Geometry | None, generated_geometry: Geometry | None,
           values: Values | None = None, aside: Collection[str] = ARREDO_ZONES) -> Context:
        text = " ".join(t for w in target_words for t in TOKEN.findall(normalise_token(w.text)))
        return Context(target_geometry, generated_geometry, f" {text} ", values or Values(), aside)

    def fixed(self, value: str) -> bool:
        """Whether a value of several words (or one word in capitals: a
        label) is printed as fixed text in the target."""
        tokens = TOKEN.findall(normalise_token(value.replace(" ", "\x00")).replace("\x00", " "))
        words = [t for t in tokens if t[:1].isalnum()]
        if not any(c.isalpha() for c in value):
            return False
        if len(words) < 2 and not (len(words) == 1 and len(words[0]) >= 4 and words[0].isupper()):
            return False                 # one word: only a label in capitals is fixed text
        return f" {' '.join(tokens)} " in self.target_text


def context_of(prepared, values: Values | None = None, aside: Collection[str] = ARREDO_ZONES) -> Context:
    """The :class:`Context` of a ``sides.Prepared`` comparison: each side's
    geometry from its body blocks and zone words (two PDFs; HTML blocks
    without graphics give lines only)."""
    geometries = []
    target_words: list[Word] = []
    for doc, blocks in ((prepared.left, prepared.left_blocks), (prepared.right, prepared.right_blocks)):
        if isinstance(doc, DocText):
            words, graphics = doc.words, doc.graphics
            rotated = [words[i] for i in doc.rotated if 0 <= i < len(words)]
        else:
            words, graphics, rotated = [w for b in blocks for w in b.words], [], []
        geometries.append(Geometry.of([b.words for b in blocks], words, graphics, rotated))
        target_words = target_words or list(words)
    return Context.of(target_words, geometries[0], geometries[1], values, aside)


# ------------------------------------------------------------ position ---

def occupied(value: Sequence[Word]) -> float:
    """The room a value takes in a line: its width and a space on each side."""
    return width_of(value) + 2 * _SPACE * char_width(*value[:1])


def hole_room(tg: Geometry, a: Word, b: Word) -> float:
    """The room between ``a`` and ``b`` when it is a HOLE, else 0: a gap on
    one line that stands out from its line's own spacing — at least
    :data:`SPACES` × the typical inter-word space there (``Geometry.space``: a justified line
    stretches every space alike: none of them is a hole) and at least
    :data:`CHARS` characters."""
    room = tg.gap(a, b)
    if room < SPACES * tg.space(a) or room < CHARS * char_width(a, b):
        return 0.0
    return room


def fits(room: float, value: Sequence[Word]) -> bool:
    """Whether a room in the target matches the value's extent (F16):
    ``RATIO_LOW`` ≤ room / :func:`occupied` ≤ ``RATIO_HIGH``."""
    need = occupied(value)
    return need > 0 and RATIO_LOW <= room / need <= RATIO_HIGH


def _one_line(value: Sequence[Word]) -> bool:
    return bool(value) and all(on_one_line(value[0], w) for w in value)


def hole(a: Word | None, b: Word | None, ga: Word | None, gb: Word | None, value: Sequence[Word], zone: str,
         ctx: Context, d: Diff) -> str | None:
    """The position proof (``cella`` or ``buco``) of a value inserted between
    the target words ``a`` and ``b`` (``ga`` / ``gb``: the generated words
    around it), or None (module doc)."""
    if not _one_line(value):
        return None                  # a hole holds a value of one line
    if zone in _SHOULDERS:
        return "buco" if a is not None and b is None and a.text.rstrip().endswith(_LABEL_END) else None
    tg = ctx.target
    if tg is None or zone not in FLOW:
        return None                  # header / footer: legal text, where a brand changes (slots only)
    if _cell(a, b, value, ctx, d):
        return "cella"
    if a is not None and b is not None and fits(hole_room(tg, a, b), value):
        return "buco"
    if a is not None and tg.ends_line(a) and not tg.same_line(a, b) and a.text.rstrip().endswith(_LABEL_END) \
            and tg.room_after(a) >= RATIO_LOW * occupied(value) and (ga is None or on_one_line(ga, value[0])):
        return "buco"
    return None                      # an indented line start is layout (a first-line indent), never a hole


def replaced_hole(before: Word | None, first: Word, last: Word, after: Word | None, value: Sequence[Word],
                  zone: str, ctx: Context) -> str:
    """Where a value next to replaced target words sits in a matching hole:
    ``"before"`` them, ``"after"`` them, or ``""`` (the replaced words still count)."""
    tg = ctx.target
    if tg is None or zone not in FLOW or not _one_line(value):
        return ""
    if before is not None and fits(hole_room(tg, before, first), value):
        return "before"
    if after is not None and fits(hole_room(tg, last, after), value):
        return "after"
    return ""


def _cell(a: Word | None, b: Word | None, value: Sequence[Word], ctx: Context, d: Diff) -> bool:
    """The target's table cell next to the insertion point (the one holding
    ``a`` or ``b``, or the next one along the row) is empty or holds only a
    unit, and the generated value lies across that cell's columns (the two
    documents share the table's columns; rows move with the text)."""
    tg = ctx.target
    if tg is None or not _value_tokens(value):
        return False
    for w in (a, b):
        if w is None or not tg.knows(w):
            continue
        own = tg.cell(w.page, *centre(w))
        if own is None:
            continue
        cy = centre(w)[1]
        for candidate in (own, tg.cell(w.page, own[2] + 1, cy), tg.cell(w.page, own[0] - 1, cy)):
            if candidate is None or not all(candidate[0] - 2 <= centre(v)[0] <= candidate[2] + 2 for v in value):
                continue
            if all(unit_only([x]) for x in tg.inside(candidate, w.page, _group(w))):
                ctx.cells.append((w.page, candidate, d))
                return True
    return False


# --------------------------------------------------------------- value ---

def value_source(tokens: Sequence[tuple[str, Word]], ctx: Context) -> str | None:
    """The value proof of a whole inserted text by what is known about it
    (F16): ``listino`` (a numeric value cell of the dictionary), ``esecuzione``
    (every word changed in a control generation), ``payload`` (exactly a
    payload value in Italian format); None otherwise."""
    words = [w for w in dict.fromkeys(w for _, w in tokens) if alnum(w.text)]
    if not words:
        return None
    known = ctx.values.proof(plain(tokens))
    if known == "listino":
        return known
    if ctx.values.executed and all(word_key(w) in ctx.values.executed for w in words):
        return "esecuzione"
    return known


def value_runs(tokens: Sequence[tuple[str, Word]], ctx: Context, *,
               replacing: bool = False) -> list[tuple[int, int, str]]:
    """The value runs of inserted tokens, as ``(start, end, source)``: the
    whole text when :func:`value_source` knows it; else each run of tokens
    holding a digit, with the separators inside it and a unit or a month
    name next to it (``source`` "forma", or what :func:`value_source` says of
    the run), or of words a control generation changed. Free words are
    never in a run. ``replacing``: the tokens took the place of target words
    (a ``cambiato``): only words holding a digit or changed in a control
    generation can be the value — a word in place of a target word (a unit,
    a month, a known text) is a change, never inside the value (review A4
    fix 1, I1)."""
    whole = None if replacing else value_source(tokens, ctx)
    if whole and not ctx.fixed(plain(tokens)):
        return [(0, len(tokens), whole)]
    n = len(tokens)
    digit = [any(c.isdigit() for c in t) for t, _ in tokens]
    core = [any(c.isdigit() for c in w.text) for _, w in tokens]     # a word holding a digit: a code, a number
    words = list(dict.fromkeys(w for _, w in tokens))
    numeric = {id(w) for w in words if any(c.isdigit() for c in w.text)}
    beside = set()                       # words right before or after a word holding a digit
    for k, w in enumerate(words):
        if any(id(x) in numeric for x in words[max(0, k - 1):k + 2]):
            beside.add(id(w))
    for k, (t, w) in enumerate(tokens):
        if not replacing and id(w) in beside and (t.casefold() in _MONTHS or unit_only_text(w.text)):
            core[k] = True               # «€/mese» after an amount, «Dicembre» before a year
        if ctx.values.executed and alnum(t) and word_key(w) in ctx.values.executed:
            core[k] = True
    for k in range(1, n - 1):
        if not core[k] and not alnum(tokens[k][0]) and core[k - 1] and core[k + 1]:
            core[k] = True               # a separator inside a number, a date, an amount
    runs: list[tuple[int, int, str]] = []
    k = 0
    while k < n:
        if not core[k]:
            k += 1
            continue
        first = k
        while k < n and core[k]:
            k += 1
        after = k
        start = first
        while start < k - 1 and not alnum(tokens[start][0]) and tokens[start][0] not in "€%":
            start += 1                   # an opening mark stays outside
        while k - 1 > start and not alnum(tokens[k - 1][0]) and tokens[k - 1][0] not in "€%":
            k -= 1                       # a closing mark stays outside
        source = value_source(tokens[start:k], ctx)
        runs.append((start, k, source or ("forma" if any(digit[start:k]) else "esecuzione")))
        k = after
    return runs


def plain(tokens: Sequence[tuple[str, Word]]) -> str:
    """Tokens as text: one space between tokens of different words, none before closing punctuation."""
    out = ""
    last: Word | None = None
    for token, word in tokens:
        space = last is not None and last is not word and token not in ",.;:!?)]»"
        out += (" " if space else "") + token
        last = word
    return out


# ------------------------------------------------------------- helpers ---

def unit_only_text(text: str) -> bool:
    """A unit of measure: currency and percent signs, known units, and in a
    compound unit («€/x/anno») any short word joined by «/»."""
    tokens = TOKEN.findall(normalise_token(text))
    compound = "/" in tokens
    return bool(tokens) and all(t.casefold() in _UNITS or t in _UNIT_MARKS
                                or (compound and t.isalpha() and len(t) <= _COMPOUND_PART) for t in tokens)


def unit_only(words: Sequence[Word]) -> bool:
    return bool(words) and all(unit_only_text(w.text) for w in words)


def _value_tokens(words: Sequence[Word]) -> bool:
    """Whether ``words`` hold a value besides units (a word that is not a unit)."""
    return any(alnum(w.text) and not unit_only_text(w.text) for w in words)


def centre(word: Word) -> tuple[float, float]:
    return (word.x0 + word.x1) / 2, (word.y0 + word.y1) / 2


def inside(box: tuple, word: Word) -> bool:
    x, y = centre(word)
    return box[0] <= x <= box[2] and box[1] <= y <= box[3]


def _group(word: Word) -> str:
    return "flow" if word.zone in FLOW else word.zone


def alnum(text: str) -> bool:
    return any(c.isalnum() for c in text)
