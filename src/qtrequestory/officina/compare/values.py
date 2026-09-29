"""What the second pass of the variables (``variables``) knows besides the
two documents (phase 2.5, spec §3.3; task A4): the payload's values, the
initiative's price-list dictionary, the words a control generation changed,
and which proofs are switched on.

* **Payload** (:func:`payload_index`): every scalar leaf of the case's
  ``payload.json`` in the formats an Italian document prints it — a number
  by its value (``0.01`` matches «0,010» and «0,01»), an ISO or epoch-millis
  date as «gg/mm/aaaa», a text as it is. Leaves under ``template``,
  ``attributeDescription``, ``attributeAcronym`` and
  ``documentAcquisitionContext`` are left out (template names and form
  labels, not data), and so are texts shorter than 4 characters. The payload
  only NAMES a variable (``Diff.nome`` = the leaf's path): on its own it never
  proves one — it holds the very brand a template change replaces.
* **Dictionary** (:func:`load_dictionary`): an optional ``.xlsx`` per
  initiative (the expected price-list values, spec §3.3), read with
  ``zipfile`` and ``xml.etree`` only. Every short cell of every sheet is an
  entry, named «<sheet>: <label>» (the nearest text cell on its left, else its
  column's header). A number matches a printed value rounded to the printed
  decimals (0,123456 → «0,1235»). Only VALUE cells (numbers, codes holding a
  digit) prove a value (``listino``); label and header texts only name
  (ruling F16). A file that cannot be read — corrupt, truncated, over
  :data:`MAX_BYTES` inflated or :data:`MAX_MEMBERS` members — gives an empty
  dictionary and an Italian note, never an exception.
* **Execution** (:data:`WordKey`, :func:`word_key`, :func:`changed_words`):
  the generated words that changed between the generation and a control
  generation with a perturbed payload (task A5 feeds them; the ``esecuzione``
  proof).
* :class:`Values` bundles them with the proofs switched on (the case's
  ``variabile.<proof>`` filters, ``filter_model``).

Stdlib only; no Qt, no pypdfium2.
"""
from __future__ import annotations

import hashlib
import re
import zipfile
from collections.abc import Collection, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from xml.etree import ElementTree

from qtrequestory.officina.compare.model import PROVE, Comparison, Word

__all__ = ["DICTIONARY_NAME", "MAX_BYTES", "MAX_MEMBERS", "Dictionary", "Values", "WordKey", "changed_words", "load_dictionary",
           "parse_number", "payload_index", "word_key"]

#: The dictionary's file name in the initiative's folder (optional).
DICTIONARY_NAME = "dizionario.xlsx"
#: A dictionary larger than this once inflated, or with more members, is not read (a note).
MAX_BYTES = 20 * 1024 * 1024
MAX_MEMBERS = 2000

#: A generated word's identity across two comparisons of the same document.
WordKey = tuple[int, float, float, str]

#: Path segments whose leaves are never data (research B.1.3 a).
_EXCLUDED = ("template", "attributedescription", "attributeacronym", "documentacquisitioncontext")
_MIN_TEXT = 4
#: An Italian number as printed: optional sign, digits with «.» thousands, «,» decimals.
_IT_NUMBER = re.compile(r"^[-+]?(\d{1,3}(\.\d{3})+|\d+)(,\d+)?$")
_PLAIN_NUMBER = re.compile(r"^[-+]?\d+(\.\d+)?$")
_SCIENTIFIC = re.compile(r"^[-+]?\d+(\.\d+)?[eE][-+]?\d+$")
_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})([T ].*)?$")
_EPOCH_MS = re.compile(r"^\d{12,13}$")
_MAX_CELL = 60
_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
#: A cell reference's column letters.
_COLUMN = re.compile(r"^([A-Z]+)")


def word_key(word: Word) -> WordKey:
    """The identity of a generated word (page, rounded box corner, text)."""
    return (word.page, round(word.x0, 1), round(word.y0, 1), word.text)


def changed_words(control: Comparison) -> frozenset[WordKey]:
    """The generated document's words that a control generation changed:
    ``control`` compares the generated document (its LEFT side) with the
    control generation; every word of its left side in a difference of
    text (not style, spacing or a move) is one."""
    keep = {"testo", "zona", "variabile", "rumore", "arredo", "composizione"}
    return frozenset(word_key(w) for d in control.diffs if d.klass in keep and d.op != "spostato" for w in d.left)


def parse_number(text: str) -> Decimal | None:
    """The value of a number printed the Italian way («1.234,56», «0,010»,
    «89»); None for anything else."""
    text = text.strip()
    if not _IT_NUMBER.match(text):
        return None
    try:
        return Decimal(text.replace(".", "").replace(",", "."))
    except InvalidOperation:  # pragma: no cover - the pattern allows only digits
        return None


def _decimals(text: str) -> int:
    return len(text.split(",", 1)[1]) if "," in text else 0


@dataclass(frozen=True)
class Dictionary:
    """A price-list dictionary: ``numbers`` (value → name) and ``texts``
    (casefolded text → name)."""

    numbers: tuple[tuple[Decimal, str], ...] = ()
    texts: Mapping[str, str] = field(default_factory=dict)

    def name(self, value: str) -> str | None:
        """The entry ``value`` (a printed value) matches; None when none does.
        A number with decimals matches an entry rounded to its decimals; a
        whole number or a text must be equal (texts ignoring case)."""
        number = parse_number(value)
        if number is not None:
            places = _decimals(value)
            step = Decimal(1).scaleb(-places)
            for entry, name in self.numbers:
                if entry.quantize(step) == number if places else entry == number:
                    return name
            return None
        return self.texts.get(value.casefold())

    def __bool__(self) -> bool:
        return bool(self.numbers or self.texts)


@dataclass(frozen=True)
class Values:
    """Everything the variables' second pass takes besides the documents.

    ``payload``: :func:`payload_index` of the case's payload (printed value
    → leaf path); ``dictionary``: the initiative's :class:`Dictionary`;
    ``executed``: the generated words a control generation changed
    (:func:`changed_words`, empty until one ran); ``proofs``: the proofs
    switched on (``PROVE``; a proof switched off leaves its differences
    counting, with their ``prova`` still set for the filter panel)."""

    payload: Mapping[str, str] = field(default_factory=dict)
    dictionary: Dictionary = field(default_factory=Dictionary)
    executed: frozenset[WordKey] = frozenset()
    proofs: frozenset[str] = frozenset(PROVE)
    numbers: Mapping[Decimal, str] = field(default_factory=dict)

    @staticmethod
    def of(payload: object = None, dictionary: Dictionary | None = None,
           executed: Collection[WordKey] = (), proofs: Collection[str] = PROVE) -> Values:
        """The values of a case: the payload is indexed here (:func:`payload_index`)."""
        texts, numbers = payload_index(payload) if payload is not None else ({}, {})
        return Values(texts, dictionary or Dictionary(), frozenset(executed), frozenset(proofs), numbers)

    def key(self) -> str:
        """A fingerprint of these values, for a cache key."""
        digest = hashlib.sha256()
        for part in (sorted(self.payload.items()), sorted((str(k), v) for k, v in self.numbers.items()),
                     self.dictionary.numbers, sorted(self.dictionary.texts.items()), sorted(self.executed),
                     sorted(self.proofs)):
            digest.update(repr(part).encode("utf-8"))
        return digest.hexdigest()

    def name(self, value: str) -> tuple[str, bool]:
        """``(name, listino)`` of a printed value: the dictionary's entry, else
        the payload leaf's path, else ``""``. ``listino`` is True only for a
        dictionary VALUE cell — a number or a code (a text holding a digit):
        a label or header text only names (ruling F16)."""
        printed = " ".join(value.split())
        value = value.strip(" .,;:()[]")
        if not value:
            return "", False
        if printed in self.payload:           # a payload text with its own final mark
            return self.payload[printed], False
        found = self.dictionary.name(value) if self.dictionary else None
        if found:
            return found, any(c.isdigit() for c in value)
        number = parse_number(value)
        if number is not None:
            return self.numbers.get(number.normalize(), ""), False
        return self.payload.get(" ".join(value.split()), ""), False


    def proof(self, value: str) -> str | None:
        """What proves ``value`` a value (ruling F16): ``listino`` for a
        dictionary value cell, ``payload`` for exactly a payload value (text
        or number), None otherwise — a dictionary label only names."""
        name, listino = self.name(value)
        if name and listino:
            return "listino"
        core = value.strip(" .,;:()[]")
        number = parse_number(core)
        if number is not None:
            return "payload" if number.normalize() in self.numbers else None
        printed = " ".join(value.split())
        return "payload" if printed in self.payload or " ".join(core.split()) in self.payload else None


# ------------------------------------------------------------- payload ---

def payload_index(payload: object) -> tuple[dict[str, str], dict[Decimal, str]]:
    """``(texts, numbers)`` of ``payload``'s data leaves (module doc): the
    printed text → path, the numeric value → path; the first leaf in
    document order names a value found in several."""
    texts: dict[str, str] = {}
    numbers: dict[Decimal, str] = {}
    for path, value in _leaves(payload, ""):
        if any(part in path.casefold() for part in _EXCLUDED):
            continue
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, (int, float)):
            _number(numbers, str(value), path)
            continue
        text = " ".join(str(value).split())
        if _PLAIN_NUMBER.match(text):
            _number(numbers, text, path)
            if _EPOCH_MS.match(text):
                for day in _epoch_days(int(text)):
                    texts.setdefault(day, path)
            continue
        iso = _ISO_DATE.match(text)
        if iso:
            texts.setdefault(f"{iso.group(3)}/{iso.group(2)}/{iso.group(1)}", path)
            continue
        if len(text) >= _MIN_TEXT:
            texts.setdefault(text, path)
    return texts, numbers


def _leaves(node: object, path: str) -> Iterator[tuple[str, object]]:
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _leaves(value, f"{path}.{key}" if path else str(key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _leaves(value, f"{path}[{index}]")
    else:
        yield path, node


def _number(numbers: dict[Decimal, str], text: str, path: str) -> None:
    try:
        value = Decimal(text)
    except InvalidOperation:
        return
    if value.is_finite():
        numbers.setdefault(value.normalize(), path)


def _epoch_days(millis: int) -> list[str]:
    """The day of an epoch-millis timestamp in UTC and at Italian offsets."""
    try:
        base = datetime.fromtimestamp(millis / 1000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return []
    days = {(base + timedelta(hours=h)).strftime("%d/%m/%Y") for h in (0, 1, 2)}
    return sorted(days)


# ---------------------------------------------------------- dictionary ---

def load_dictionary(path: Path) -> tuple[Dictionary, str]:
    """The dictionary in the ``.xlsx`` at ``path`` and an Italian note
    (``""`` when read, or when there is no file). Never raises."""
    if not path.is_file():
        return Dictionary(), ""
    try:
        with zipfile.ZipFile(path) as book:
            infos = book.infolist()
            if len(infos) > MAX_MEMBERS or sum(i.file_size for i in infos) > MAX_BYTES:
                return Dictionary(), f"dizionario «{path.name}» non letto: troppo grande"
            budget = [MAX_BYTES]
            strings = _shared_strings(book, budget)
            numbers: list[tuple[Decimal, str]] = []
            texts: dict[str, str] = {}
            for sheet, part in _sheets(book, budget):
                _read_sheet(_read(book, part, budget), sheet, strings, numbers, texts)
    except _TooBig:
        return Dictionary(), f"dizionario «{path.name}» non letto: troppo grande"
    except Exception as exc:  # noqa: BLE001 - a user file: zlib.error, EOFError, BadZipFile, XML... → a note
        return Dictionary(), f"dizionario «{path.name}» non letto: {type(exc).__name__}"
    return Dictionary(tuple(numbers), texts), ""


class _TooBig(Exception):
    """A member inflates past the dictionary's size budget."""


def _read(book: zipfile.ZipFile, name: str, budget: list[int]) -> bytes:
    """A member's bytes, never more than what is left of ``budget`` (the
    declared sizes can lie: the stream is read with a cap)."""
    with book.open(name) as member:
        data = member.read(budget[0] + 1)
    if len(data) > budget[0]:
        raise _TooBig(name)
    budget[0] -= len(data)
    return data


def _shared_strings(book: zipfile.ZipFile, budget: list[int]) -> list[str]:
    if "xl/sharedStrings.xml" not in book.namelist():
        return []
    root = ElementTree.fromstring(_read(book, "xl/sharedStrings.xml", budget))
    return ["".join(t.text or "" for t in item.iter(f"{_NS}t")) for item in root.findall(f"{_NS}si")]


def _sheets(book: zipfile.ZipFile, budget: list[int]) -> list[tuple[str, str]]:
    """``(sheet name, part path)`` in workbook order."""
    workbook = ElementTree.fromstring(_read(book, "xl/workbook.xml", budget))
    rels = ElementTree.fromstring(_read(book, "xl/_rels/workbook.xml.rels", budget))
    targets = {rel.get("Id"): rel.get("Target", "") for rel in rels}
    out = []
    for sheet in workbook.iter(f"{_NS}sheet"):
        target = targets.get(sheet.get(_REL), "")
        if not target:
            continue
        part = target.lstrip("/") if target.startswith("/") else f"xl/{target}"
        out.append((sheet.get("name", ""), part))
    return out


def _read_sheet(data: bytes, sheet: str, strings: list[str], numbers: list[tuple[Decimal, str]],
                texts: dict[str, str]) -> None:
    headers: dict[str, str] = {}
    for row in ElementTree.fromstring(data).iter(f"{_NS}row"):
        label = ""
        cells = []
        for cell in row.findall(f"{_NS}c"):
            column = _COLUMN.match(cell.get("r", ""))
            cells.append((column.group(1) if column else "", _cell_value(cell, strings)))
        first = not headers
        for column, (kind, value) in cells:
            if not value:
                continue
            if first and kind == "text":
                headers[column] = value
                continue
            name = f"{sheet}: {label or headers.get(column, column)}"
            if kind == "number":
                try:
                    numbers.append((Decimal(value), name))
                except InvalidOperation:
                    pass
            elif len(value) <= _MAX_CELL:
                texts.setdefault(value.casefold(), name)
                label = value


def _cell_value(cell: ElementTree.Element, strings: list[str]) -> tuple[str, str]:
    """``(kind, value)``: kind ``number``, ``text`` or ``""`` (empty/other)."""
    kind = cell.get("t", "n")
    if kind == "inlineStr":
        return "text", " ".join("".join(t.text or "" for t in cell.iter(f"{_NS}t")).split())
    raw = cell.find(f"{_NS}v")
    if raw is None or raw.text is None:
        return "", ""
    if kind == "s":
        index = int(raw.text)
        return ("text", " ".join(strings[index].split())) if 0 <= index < len(strings) else ("", "")
    if kind in ("str", "e"):
        return "text", " ".join(raw.text.split())
    text = raw.text.strip()
    if kind == "n" and (_PLAIN_NUMBER.match(text) or _SCIENTIFIC.match(text)):
        return "number", text
    return "", ""
