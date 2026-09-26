"""Noise rules (spec §4.2 step 5).

A noise rule is a named regular expression over the NORMALISED keys of one
side: quotes, dashes and ligatures are already unified, so a rule must be
written against that form (``'`` not ``’``; a backtick arrives as ``'``). The
noise dialog's help must say so (note for the U-noise task). What a rule
matches becomes the placeholder ``NOISE + name`` on both sides, so a page
number or a date that differs by design compares equal; the word diff classes
what the placeholders cover as ``rumore``, which never counts.

Matching (:func:`apply`): the keys are joined by single spaces — by a newline
after the keys listed in ``line_ends`` — and every rule is compiled with
:data:`re.MULTILINE`, so ``^``/``$`` mean line start/end when the caller passes
the line ends. Each rule runs LINE BY LINE, on at most :data:`LINE_CAP`
characters at a time (a longer line is cut at key boundaries), so no search
sees the whole document (ruling R17). A match may span keys: all the keys it
touches become ONE unit (ruling R18) — the placeholder with any unmatched text
of the first and last key around it (``?utm_source=a&id=3`` keeps ``&id=3``) —
whose members are the members of those keys. So ``01/02/2026.`` and
``1 febbraio 2026.`` both become the one key ``NOISE + "Data" + "."``. Rules
apply in order and never inside text an earlier rule (or a slot, or a
placeholder) already holds.

:func:`compile_rules` reports every rule that cannot be used — a regex that
does not compile, one that risks catastrophic backtracking (a repeat whose
body holds an unbounded repeat, or a backreference inside a repeat: CPython's
``re`` cannot be interrupted, so such a rule could freeze the application), an
empty name or pattern, a duplicate name — by name, and leaves it out: a bad
rule is never half-applied.

A user's rule is never matched (executed) in the application process
(ruling R46; the noise dialog only compiles it, to validate its syntax):
the noise guard's child process runs :func:`check` and :func:`spans` on the
exact keys and line ends the pipeline's noise stage sees, and the pipeline
applies the spans it found through :class:`Found`, which :func:`apply` takes
like a compiled pattern. :func:`precheck` is the part of the checks that
needs no compiling.

Stdlib only; no Qt, no pypdfium2.
"""
from __future__ import annotations

import dataclasses
import re
from collections.abc import Collection, Iterator, Sequence

from qtrequestory.officina.compare import urls
from qtrequestory.officina.compare.model import Word
from qtrequestory.officina.model_review import NoiseRule

try:  # Python >= 3.11
    from re import _constants as _sre_constants
    from re import _parser as _sre_parse
except ImportError:  # pragma: no cover - older Pythons
    import sre_constants as _sre_constants  # type: ignore[no-redef]
    import sre_parse as _sre_parse  # type: ignore[no-redef]

__all__ = ["LINE_CAP", "NOISE", "PRESETS", "SLOW", "TRACKING_PRESET", "Found", "apply", "check", "compile_rules",
           "placeholder", "precheck", "preset_rules", "spans"]

#: Placeholder prefix; the full placeholder is ``NOISE + rule name``. Keys
#: starting with U+2063 (placeholders, slots) are never matched again.
NOISE = "\u2063NOISE:"
_RESERVED = "\u2063"
#: Longest stretch of text one search sees.
LINE_CAP = 2000
#: The error for a pattern refused as potentially too slow (ruling R17).
SLOW = "espressione potenzialmente troppo lenta: semplificala"
#: The preset that also drops tracking keys from HTML URLs (ruling R21).
TRACKING_PRESET = "Parametri di tracciamento"

_MONTHS = "gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre"
#: Omocodia replaces a codice fiscale's digits with these letters.
_CF_DIGIT = r"[\dLMNP-V]"


def _tracking() -> str:
    """The "Parametri di tracciamento" pattern, built from ``urls.TRACKING_KEYS``
    (ruling R21: one list for the text preset and the HTML attributes; a
    trailing ``*`` is a prefix; case-insensitive like ``urls.tracking_drop``)."""
    keys = [re.escape(k[:-1]) + r"\w*" if k.endswith("*") else re.escape(k) for k in urls.TRACKING_KEYS]
    return rf"(?<=[?&])(?i:{'|'.join(keys)})=[^&#\s]*"


#: Built-in presets, all off (spec §4.2 step 5). Names are part of the contract
#: (ruling R11). Use :func:`preset_rules` for copies to edit.
PRESETS: tuple[NoiseRule, ...] = (
    NoiseRule("Numero di pagina",
              r"\b[Pp]ag(?:ina|\.)? ?\d+ ?(?:di|/) ?\d+\b|(?<![\d/.,])\b\d{1,3} ?/ ?\d{1,3}$", False),
    NoiseRule("Data",
              r"\b\d{1,2}[/.-]\d{1,2}[/.-](?:\d{4}|\d{2})\b"
              rf"|\b\d{{1,2}}°? (?i:{_MONTHS}) \d{{4}}\b", False),
    NoiseRule("IBAN", r"\bIT\d{2} ?[A-Z](?: ?[0-9A-Z]){22}\b|\b[A-Z]{2}\d{2}[0-9A-Z]{11,30}\b", False),
    NoiseRule("Codice fiscale",
              rf"\b[A-Z]{{6}}{_CF_DIGIT}{{2}}[A-EHLMPR-T]{_CF_DIGIT}{{2}}[A-Z]{_CF_DIGIT}{{3}}[A-Z]\b", False),
    NoiseRule("CAP", r"(?<![\d.,/])\b\d{5}\b(?![.,/]\d)", False),
    NoiseRule("Importo",
              r"€ ?-?\d+(?:\.\d{3})*(?:,\d+)?|\b\d+(?:\.\d{3})*,\d{2} ?(?:€|[Ee]uro\b|EUR\b)", False),
    NoiseRule("Marcatore di firma", r"['`]sig,[^'`\n]*['`]", False),
    NoiseRule(TRACKING_PRESET, _tracking(), False),
)


def preset_rules() -> list[NoiseRule]:
    """Fresh copies of :data:`PRESETS` (NoiseRule is mutable)."""
    return [dataclasses.replace(rule) for rule in PRESETS]


def placeholder(name: str) -> str:
    """The key that stands for text rule ``name`` matched."""
    return NOISE + name


def compile_rules(rules: Sequence[NoiseRule]) -> tuple[list[tuple[str, re.Pattern]], dict[str, str]]:
    """``(usable, errors)``: the ENABLED valid rules compiled, in order, and an
    Italian message per rule name that cannot be used (enabled or not). For a
    duplicate name the first rule is kept and the name gets an error; a name
    keeps its FIRST error. A name that is not a string is reported under its
    ``str()``."""
    usable: list[tuple[str, re.Pattern]] = []
    errors: dict[str, str] = {}
    seen: set[str] = set()
    for rule in rules:
        name = rule.name
        if not isinstance(name, str):
            errors.setdefault(str(name), "nome non valido")
            continue
        if name in seen:
            errors.setdefault(name, "nome già usato da un'altra regola")
            continue
        seen.add(name)
        result = _check(name, rule.pattern)
        if isinstance(result, str):
            errors[name] = result
        elif rule.enabled:
            usable.append((name, result))
    return usable, errors


def apply(keys: Sequence[str], members: Sequence[tuple[Word, ...]], rules: Sequence[tuple[str, re.Pattern]],
          line_ends: Collection[int] = ()) -> tuple[list[str], list[tuple[Word, ...]], list[tuple[int, int, str]]]:
    """``(keys, members, hits)``: the keys with every match's keys merged into
    one placeholder unit (members concatenated), and one hit per match as
    ``(first key, last key, rule name)`` in the ORIGINAL indexing, in text
    order. ``rules`` as :func:`compile_rules` returns them; ``line_ends`` =
    indices of keys a line ends after. Pure."""
    if len(keys) != len(members):
        raise ValueError("keys and members differ in length")
    if not rules or not keys:
        return list(keys), list(members), []
    text, owner, starts = _join(keys, line_ends)
    # per character: 0 free, -1 reserved (slot, placeholder), n = rule n-1 matched it
    taken = [-1 if index >= 0 and keys[index].startswith(_RESERVED) else 0 for index in owner]
    chunks = _chunks(text, starts, keys)
    hits: list[tuple[int, int, str]] = []
    for number, (name, pattern) in enumerate(rules, start=1):
        for chunk_start, chunk_end in chunks:
            for match in pattern.finditer(text, chunk_start, chunk_end):
                start, end = match.span()
                touched = [owner[p] for p in range(start, end) if owner[p] >= 0]
                if not touched or any(taken[start:end]):
                    continue
                taken[start:end] = [number] * (end - start)
                hits.append((touched[0], touched[-1], name))
    hits.sort(key=lambda hit: (hit[0], hit[1]))
    out_keys: list[str] = []
    out_members: list[tuple[Word, ...]] = []
    index = 0
    for first, last in _groups(hits):
        out_keys.extend(keys[index:first])
        out_members.extend(members[index:first])
        out_keys.append(_rebuild(text, owner, taken, starts[first], starts[last] + len(keys[last]), rules))
        out_members.append(tuple(w for group in members[first:last + 1] for w in group))
        index = last + 1
    out_keys.extend(keys[index:])
    out_members.extend(members[index:])
    return out_keys, out_members, hits


class Found:
    """The matches of a rule found elsewhere (the noise guard's child, R46),
    as :func:`apply` takes a compiled pattern: ``finditer`` gives back the
    ``(start, end)`` spans :func:`spans` returned that lie in the searched
    stretch, in their order. Matches nothing new: no regex runs here."""

    def __init__(self, found: Sequence[tuple[int, int]]) -> None:
        self._found = [(int(s), int(e)) for s, e in found]

    def finditer(self, _text: str, start: int, end: int) -> list[_Span]:
        return [_Span(s, e) for s, e in self._found if start <= s and e <= end]


class _Span:
    __slots__ = ("_span",)

    def __init__(self, start: int, end: int) -> None:
        self._span = (start, end)

    def span(self) -> tuple[int, int]:
        return self._span


def spans(keys: Sequence[str], line_ends: Collection[int], pattern: re.Pattern) -> list[tuple[int, int]]:
    """Every non-empty match of ``pattern`` as :func:`apply` searches it over
    ``keys`` joined with ``line_ends`` (line by line, at most LINE_CAP
    characters at a time), as ``(start, end)`` in the joined text. What the
    guard's child sends back for :class:`Found`. An empty match changes
    nothing in :func:`apply`, so it is left out."""
    if not keys:
        return []
    text, _owner, starts = _join(keys, line_ends)
    return [match.span() for chunk_start, chunk_end in _chunks(text, starts, keys)
            for match in pattern.finditer(text, chunk_start, chunk_end) if match.end() > match.start()]


def precheck(name: object, pattern: object) -> str | None:
    """The error message of a rule that is unusable whatever its regex does
    (a name or pattern that is not text, or empty), else None — no compiling."""
    if not isinstance(name, str):
        return "nome non valido"
    if not name.strip():
        return "nome vuoto"
    if not isinstance(pattern, str):
        return "espressione non valida"
    if not pattern:
        return "espressione vuota"
    return None


def check(name: str, pattern: object) -> str | re.Pattern:
    """The compiled pattern, or the error message (:func:`compile_rules` for
    one rule). Compiles: for a user's rule, only in the guard's child (R46)."""
    return _check(name, pattern)


# ------------------------------------------------------------ helpers ---

def _check(name: str, pattern: object) -> str | re.Pattern:
    """The compiled pattern, or the error message."""
    problem = precheck(name, pattern)
    if problem is not None:
        return problem
    try:
        compiled = re.compile(pattern, re.MULTILINE)
        parsed = _sre_parse.parse(pattern, re.MULTILINE)
    except (re.error, OverflowError, RecursionError, ValueError, TypeError) as exc:
        return f"espressione non valida: {exc}"
    try:
        risky = _risky(parsed)
    except RecursionError:
        risky = True
    return SLOW if risky else compiled


def _ops(*names: str) -> frozenset:
    return frozenset(op for op in (getattr(_sre_constants, n, None) for n in names) if op is not None)


_REPEATS = _ops("MAX_REPEAT", "MIN_REPEAT", "POSSESSIVE_REPEAT")
_BACKREFS = _ops("GROUPREF", "GROUPREF_IGNORE", "GROUPREF_LOC_IGNORE", "GROUPREF_UNI_IGNORE", "GROUPREF_EXISTS")
_MAXREPEAT = _sre_constants.MAXREPEAT


def _risky(sub) -> bool:
    """A repeat (more than once) whose body holds an unbounded repeat or a backreference."""
    for op, av in _walk(sub):
        if op in _REPEATS and av[1] > 1:
            for inner_op, inner_av in _walk(av[2]):
                if inner_op in _BACKREFS or (inner_op in _REPEATS and inner_av[1] == _MAXREPEAT):
                    return True
    return False


def _walk(sub) -> Iterator[tuple]:
    """Every (op, argument) in a parsed pattern, at any depth."""
    for op, av in sub:
        yield op, av
        for child in _children(av):
            yield from _walk(child)


def _children(av) -> list:
    if isinstance(av, _sre_parse.SubPattern):
        return [av]
    if isinstance(av, (tuple, list)):
        return [child for item in av for child in _children(item)]
    return []


def _join(keys: Sequence[str], line_ends: Collection[int]) -> tuple[str, list[int], list[int]]:
    """The joined text, each character's key (-1 for a separator), each key's start."""
    parts: list[str] = []
    owner: list[int] = []
    starts: list[int] = []
    pos = 0
    for index, key in enumerate(keys):
        if index:
            parts.append("\n" if index - 1 in line_ends else " ")
            owner.append(-1)
            pos += 1
        starts.append(pos)
        parts.append(key)
        owner.extend([index] * len(key))
        pos += len(key)
    return "".join(parts), owner, starts


def _chunks(text: str, starts: list[int], keys: Sequence[str]) -> list[tuple[int, int]]:
    """Each line's span, cut at key boundaries into pieces of at most LINE_CAP characters."""
    chunks: list[tuple[int, int]] = []
    chunk_start = chunk_end = -1
    for index, key in enumerate(keys):
        start, end = starts[index], starts[index] + len(key)
        if chunk_start < 0:
            chunk_start = start
        elif text[start - 1] == "\n" or end - chunk_start > LINE_CAP:
            chunks.append((chunk_start, chunk_end))
            chunk_start = start
        while end - chunk_start > LINE_CAP:          # one key longer than the cap
            chunks.append((chunk_start, chunk_start + LINE_CAP))
            chunk_start += LINE_CAP
        chunk_end = end
    chunks.append((chunk_start, chunk_end))
    return chunks


def _groups(hits: list[tuple[int, int, str]]) -> list[tuple[int, int]]:
    """Key ranges to merge: matches sharing a key form one range (hits sorted)."""
    groups: list[list[int]] = []
    for first, last, _name in hits:
        if groups and first <= groups[-1][1]:
            groups[-1][1] = max(groups[-1][1], last)
        else:
            groups.append([first, last])
    return [(first, last) for first, last in groups]


def _rebuild(text: str, owner: list[int], taken: list[int], start: int, end: int,
             rules: Sequence[tuple[str, re.Pattern]]) -> str:
    """The merged key for ``text[start:end]``: matched runs as placeholders,
    unmatched key characters as they are, unmatched separators dropped."""
    out: list[str] = []
    previous = 0
    for pos in range(start, end):
        rule = max(taken[pos], 0)
        if rule:
            if rule != previous:
                out.append(placeholder(rules[rule - 1][0]))
        elif owner[pos] >= 0:
            out.append(text[pos])
        previous = rule
    return "".join(out)
