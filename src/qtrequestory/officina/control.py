"""The control generation's pure half (phase 2.5, spec §3.4, D14): which
payload leaves may be perturbed, how, and what a control generation proves.
The background job that sends it is ``officina.service_control``.

**Safe perturbation.** Only scalar leaves whose value is printed in the
generated document (:func:`visible_leaves`) are touched, never a structural
one (:func:`structural`: identifiers, keys, codes, types, states, flags,
templates, roles, versions, orders, lengths, levels, operations, links, by
the last or first word of the key or of any key above it, or the
``key``/``code`` of a ``{"key": ..., "value": ...}`` pair; never a URL, a
boolean, null, an enum-like code (capitals without spaces) or a number of
1-2 digits unless its key names a printed amount, duration or rate; never
under the template, the document's attributes (the upload link and its id:
``attachmentUrl`` is sent unchanged, so on the generator's side the last
writer of that blob is the control document — the app never reads the
blob, only the HTTP answer), its roles or the form labels). The new
value keeps the format (:func:`perturb_value`): digits become other digits
(same count, a leading non-zero digit stays non-zero), letters other letters
of the same case, everything else stays; a date stays a valid date in the
same format (ISO, «gg/mm/aaaa», epoch millis), shifted by some days. The
choice is deterministic for a seed.

**Structure.** A leaf used in a condition may change what the document
contains: :func:`structure_changed` says a control generation added or
removed pages or sections; the job then retries with part of the leaves
(:func:`subsets`: all, then each half — at most ``calls`` generations).

**What it proves** (ruling F18): ``officina.control_proof``. Only a
contiguous run of words printing a perturbed value WHOLE, at the place
where the control prints the whole perturbed value, is the ``esecuzione``
proof; nothing else that changed (a label, a sentence, a template word next
to the value). Conservative costs: a value printed after dot leaders gets
no proof, and upper-case code-like texts (``_ENUM``, printed upper-case
data included) are never perturbed.

Stdlib only; no Qt, no pypdfium2.
"""
from __future__ import annotations

import copy
import random
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from qtrequestory.officina.compare.model import Comparison, Word
from qtrequestory.officina.compare.values import parse_number

__all__ = ["Leaf", "perturb", "perturb_value", "structural", "structure_changed", "subsets", "visible_leaves"]

Path = tuple["str | int", ...]

#: The last word of a key that makes a leaf structural (compared casefolded).
_STRUCTURAL_WORDS = frozenset({
    "id", "ids", "key", "keys", "code", "codes", "codice", "codici", "tipo", "type", "types", "status", "stato",
    "state", "flag", "flags", "template", "ruolo", "role", "roles", "version", "versione", "lang", "language",
    "locale", "lingua", "currency", "valuta", "url", "uri", "href", "link", "mode", "modalita", "enum",
    "channel", "canale", "format", "formato", "timestamp", "order", "ordine", "length", "level", "livello",
    "precision", "number", "position", "quantity", "operation", "count", "index", "sequence", "seq", "ref",
    "paper",
})
#: The first word of a key that makes it structural (Italian puts the qualifier first: tipoOfferta).
_QUALIFIERS = frozenset({"tipo", "type", "codice", "cod", "code", "stato", "state", "status", "flag", "is",
                         "has", "id", "max", "min", "num", "list", "ref", "order", "ordine"})
#: The last word of a key whose small numbers are printed data (a 1-2 digit number elsewhere is plumbing).
_PRINTED_NUMBERS = frozenset({
    "importo", "importi", "prezzo", "prezzi", "price", "amount", "costo", "cost", "quota", "sconto", "discount",
    "durata", "duration", "mesi", "months", "giorni", "days", "anni", "years", "percentuale", "percent",
    "tasso", "rate", "potenza", "power", "consumo", "consumption", "canone", "fee", "spread", "totale", "total",
    "rata",
})
#: A code-like text (capitals, digits, underscores, no space): an enum, never perturbed.
_ENUM = re.compile(r"^[A-Z][A-Z0-9_]*$")
#: Path segments under which nothing is data (``values._EXCLUDED``, plus the request plumbing).
_EXCLUDED = ("template", "attributedescription", "attributeacronym", "documentacquisitioncontext",
             "associatedroles", "attachment", "attributes")
_WORDS = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")
_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(.*)$")
_IT_DATE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")
_EPOCH_MS = re.compile(r"^\d{12,13}$")
_PLAIN_NUMBER = re.compile(r"^[-+]?\d+(?:[.,]\d+)?$")
_EDGE = " .,;:()[]€%\"'«»"
#: A text shorter than this is too common to tell whether it is printed.
_MIN_TEXT = 3
_MAX_TEXT = 200
_DAY_MS = 86_400_000
_SECTION_OPS = frozenset({"pagine", "sezione_assente", "sezione_in_piu"})


@dataclass(frozen=True)
class Leaf:
    """A scalar of the payload: where it is and its value."""

    path: Path
    value: object


def _key_words(key: str) -> list[str]:
    return [w.casefold() for w in _WORDS.findall(key.replace("_", " ").replace("-", " ").replace(".", " "))]


def structural(key: str) -> bool:
    """True when a leaf under ``key`` is plumbing, not printed data: the
    key's last word (``attributeOrder``, ``listRefNumber``) or its first one
    (``tipoOfferta``, ``maxSaleableItems``), camelCase / snake_case / dotted."""
    words = _key_words(key)
    return bool(words) and (words[-1] in _STRUCTURAL_WORDS or (len(words) > 1 and words[0] in _QUALIFIERS))


def _small_number(value: object) -> bool:
    """A number (or numeric text) of at most two digits."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return False
    text = str(value).strip()
    return _PLAIN_NUMBER.match(text) is not None and sum(c.isdigit() for c in text) <= 2


def _leaves(node: object, path: Path, label: str) -> Iterator[tuple[Path, str, object]]:
    """``(path, name, value)`` of every scalar: ``name`` is the key it sits
    under — or the ``key``/``name``/``code`` of its ``{"key": ..., "value": ...}`` pair."""
    if isinstance(node, dict):
        pair = node.get("key", node.get("name", node.get("code")))
        for key, value in node.items():
            name = str(pair) if key == "value" and isinstance(pair, str) else str(key)
            yield from _leaves(value, (*path, key), name)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _leaves(value, (*path, index), label)
    else:
        yield path, label, node


@dataclass(frozen=True)
class _Doc:
    text: str                 # the words casefolded, one space apart, padded
    numbers: frozenset[Decimal]


def _doc(words: Sequence[Word]) -> _Doc:
    numbers = set()
    for w in words:
        value = parse_number(w.text.strip(_EDGE))
        if value is not None:
            numbers.add(value.normalize())
    return _Doc(" " + " ".join(w.text.casefold() for w in words) + " ", frozenset(numbers))


def _printed(text: str, doc: _Doc) -> bool:
    needle = " ".join(text.casefold().split())
    return bool(needle) and re.search(rf"(?<![\w]){re.escape(needle)}(?![\w])", doc.text) is not None


def _number(value: object) -> Decimal | None:
    try:
        number = Decimal(str(value).replace(",", "."))
    except InvalidOperation:
        return None
    return number.normalize() if number.is_finite() else None


def _visible(value: object, doc: _Doc) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, (int, float)):
        number = _number(value)
        return number is not None and number in doc.numbers
    if not isinstance(value, str):
        return False
    text = " ".join(value.split())
    if "://" in text or len(text) > _MAX_TEXT:
        return False
    if _EPOCH_MS.match(text):
        return any(_printed(day.strftime("%d/%m/%Y"), doc) for day in _epoch_days(int(text)))
    if _PLAIN_NUMBER.match(text):
        return _number(text) in doc.numbers
    iso = _ISO_DATE.match(text)
    if iso:
        return _printed(f"{iso.group(3)}/{iso.group(2)}/{iso.group(1)}", doc)
    return len(text) >= _MIN_TEXT and _printed(text, doc)


def _epoch_days(millis: int) -> list[date]:
    base = date(1970, 1, 1) + timedelta(milliseconds=millis)
    return [base, base + timedelta(days=1)]


def visible_leaves(payload: object, words: Sequence[Word]) -> list[Leaf]:
    """The leaves of ``payload`` that may be perturbed: printed in ``words``
    (the generated document) and not structural (module doc)."""
    doc = _doc(words)
    out = []
    for path, name, value in _leaves(payload, (), ""):
        where = ".".join(str(p) for p in path).casefold()
        if any(part in where for part in _EXCLUDED) or structural(name):
            continue
        if any(structural(p) for p in path[:-1] if isinstance(p, str)):
            continue  # under a structural key: {"type": {"code": .., "value": ..}}, dossier.operation.x
        if isinstance(value, str) and _ENUM.match(value.strip()):
            continue  # an enum-like code: a condition, not data
        last = _key_words(name)[-1:]
        if _small_number(value) and not (last and last[0] in _PRINTED_NUMBERS):
            continue  # 1-2 digits: an order, a flag, a level... unless a known printed field
        if _visible(value, doc):
            out.append(Leaf(path, value))
    return out


# ------------------------------------------------------------ perturbation ---

def _digits(text: str, rnd: random.Random) -> str:
    """Every digit another digit, but the first digit of a run: a leading
    zero stays zero (``0,50``, ``007``), a leading non-zero digit stays non-zero."""
    out = []
    for i, ch in enumerate(text):
        if not ("0" <= ch <= "9"):
            out.append(ch)
            continue
        first = i == 0 or not ("0" <= text[i - 1] <= "9")
        if first and ch == "0":
            out.append(ch)
            continue
        pool = [d for d in ("123456789" if first else "0123456789") if d != ch]
        out.append(rnd.choice(pool))
    return "".join(out)


def _letters(text: str, rnd: random.Random) -> str:
    out = []
    for ch in text:
        if "a" <= ch <= "z":
            out.append(rnd.choice([c for c in "abcdefghijklmnopqrstuvwxyz" if c != ch]))
        elif "A" <= ch <= "Z":
            out.append(rnd.choice([c for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if c != ch]))
        else:
            out.append(ch)
    return _digits("".join(out), rnd)


def _shifted(day: date, rnd: random.Random) -> date:
    return day + timedelta(days=rnd.randint(1, 27))


def perturb_value(value: object, rnd: random.Random) -> object | None:
    """``value`` changed with its format kept (module doc); None when it
    cannot be changed that way (a boolean, null, a number in exponent form,
    a text without a letter or a digit)."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        sign = "-" if value < 0 else ""
        return int(sign + _digits(str(abs(value)), rnd))
    if isinstance(value, float):
        text = repr(value)
        if "e" in text or "n" in text:
            return None
        for _ in range(20):  # the same printed precision: no new trailing zero
            new = float(_digits(text, rnd))
            if len(repr(new)) == len(text):
                return new
        return None
    if not isinstance(value, str):
        return None
    if _EPOCH_MS.match(value):
        new = str(int(value) + rnd.randint(1, 27) * _DAY_MS)
        return new if len(new) == len(value) else None
    iso = _ISO_DATE.match(value)
    if iso:
        try:
            day = _shifted(date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3))), rnd)
        except ValueError:
            return None
        return day.strftime("%Y-%m-%d") + iso.group(4)
    italian = _IT_DATE.match(value)
    if italian:
        try:
            day = _shifted(date(int(italian.group(3)), int(italian.group(2)), int(italian.group(1))), rnd)
        except ValueError:
            return None
        return day.strftime("%d/%m/%Y")
    new = _letters(value, rnd)
    return new if new != value else None


def _set(node: object, path: Path, value: object) -> None:
    for step in path[:-1]:
        node = node[step]  # type: ignore[index]
    node[path[-1]] = value  # type: ignore[index]


def perturb(payload: object, leaves: Sequence[Leaf], seed: str) -> tuple[object, list[tuple[Leaf, object]]]:
    """A deep copy of ``payload`` with ``leaves`` perturbed (deterministic
    for ``seed``), and ``(leaf, new value)`` of the leaves actually changed."""
    rnd = random.Random(seed)
    out = copy.deepcopy(payload)
    changed = []
    for leaf in leaves:
        new = perturb_value(leaf.value, rnd)
        if new is not None and new != leaf.value:
            _set(out, leaf.path, new)
            changed.append((leaf, new))
    return out, changed


def subsets(leaves: Sequence[Leaf], calls: int) -> Iterator[list[Leaf]]:
    """The leaf sets to try in turn, at most ``calls``: all of them, then
    halves, then quarters... (breadth first): a leaf that changes the
    structure is left out of the later tries' half without it."""
    pending: list[list[Leaf]] = [list(leaves)] if leaves else []
    tried = 0
    while pending and tried < calls:
        group = pending.pop(0)
        tried += 1
        yield group
        if len(group) > 1:
            half = (len(group) + 1) // 2
            pending += [group[:half], group[half:]]


def structure_changed(comparison: Comparison) -> bool:
    """The control generation has other pages or sections than the
    generation (``comparison`` = generation ↔ control)."""
    return comparison.left_pages != comparison.right_pages or any(d.op in _SECTION_OPS for d in comparison.diffs)
