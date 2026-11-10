"""The list of template keys and their packages (Genera, "Elenco CSV").

A ``;``-separated file, UTF-8 (with or without BOM) falling back to cp1252.
The columns are found from the header ("Template key", "package name"; case
and surrounding spaces ignored); without a header they are the 1st and 5th.
Values are stripped. A row without a template key is dropped and counted; a
blank package becomes :data:`NO_PACKAGE`. Rows are unique per (key
casefolded, package), so a package spelled twice with trailing spaces is one.

**Not a CSV.** Every file that cannot be read as such is an
:class:`ElencoError`, never another exception and never a list of junk: a
binary file (a NUL byte: an ``.xlsx`` picked by mistake), a cell the ``csv``
module refuses (an unterminated quote running past its field limit), a key
or package cell holding a line break or a control character, or any cell
that swallowed whole rows (a line break AND a ``;`` inside one cell: an
unterminated quote would otherwise silently eat every row after it).

Stdlib only, Qt-free.
"""
from __future__ import annotations

import csv
import io
import re
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

NO_PACKAGE = "_senza_pacchetto"

_KEY_COLUMN = 0
_PACKAGE_COLUMN = 4
_KEY_HEADER = "template key"
_PACKAGE_HEADER = "package name"
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_NOT_CSV = "Il file non sembra un elenco CSV (testo con le colonne separate da punto e virgola)."
_UNCLOSED = ("Il file non sembra un elenco CSV: una virgoletta non chiusa unisce più righe "
             "in una cella. Correggilo e ricaricalo.")


class ElencoError(ValueError):
    """The list cannot be read; the message is Italian and shown to the user."""


@dataclass(frozen=True)
class ElencoRow:
    template_key: str
    package: str


@dataclass(frozen=True)
class Elenco:
    rows: tuple[ElencoRow, ...]   # unique per (key casefolded, package), file order
    skipped: int                  # rows without a template key

    def packages(self) -> list[tuple[str, int]]:
        """(package, number of distinct keys), sorted by name."""
        keys: dict[str, set[str]] = {}
        for row in self.rows:
            keys.setdefault(row.package, set()).add(row.template_key.casefold())
        return sorted(
            ((package, len(found)) for package, found in keys.items()),
            key=lambda item: (item[0].casefold(), item[0]),
        )

    def keys_of(self, packages: Collection[str]) -> list[str]:
        """Keys of the given packages in file order, each once."""
        wanted = set(packages)
        seen: set[str] = set()
        result: list[str] = []
        for row in self.rows:
            folded = row.template_key.casefold()
            if row.package in wanted and folded not in seen:
                seen.add(folded)
                result.append(row.template_key)
        return result

    def packages_of(self, key: str) -> tuple[str, ...]:
        """Packages holding ``key`` (casefolded match); ``()`` if absent."""
        folded = key.strip().casefold()
        return tuple(r.package for r in self.rows if r.template_key.casefold() == folded)


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def _column(header: list[str], name: str) -> int | None:
    for index, cell in enumerate(header):
        if cell.strip().casefold() == name:
            return index
    return None


def load_elenco(path: Path) -> Elenco:
    """Read the list at ``path``; raises :class:`ElencoError` if it is unusable."""
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        raise ElencoError(f"Impossibile leggere l'elenco: {exc.strerror or exc}") from exc
    if b"\x00" in data:  # no text file has one: a spreadsheet, a zip, an image...
        raise ElencoError(_NOT_CSV)
    try:
        table = [
            row for row in csv.reader(io.StringIO(_decode(data), newline=""), delimiter=";")
            if any(cell.strip() for cell in row)
        ]
    except csv.Error:  # e.g. an unterminated quote past the field size limit
        raise ElencoError(_UNCLOSED) from None
    for row in table:
        if any(("\n" in cell or "\r" in cell) and ";" in cell for cell in row):
            raise ElencoError(_UNCLOSED)
    if not table:
        raise ElencoError("L'elenco è vuoto.")

    key_col, package_col = _KEY_COLUMN, _PACKAGE_COLUMN
    body = table
    header_key = _column(table[0], _KEY_HEADER)
    if header_key is not None:
        key_col = header_key
        found = _column(table[0], _PACKAGE_HEADER)
        if found is None:
            raise ElencoError('Nell\'elenco manca la colonna "package name".')
        package_col = found
        body = table[1:]
    elif max(len(row) for row in table) <= package_col:
        raise ElencoError(
            "L'elenco ha meno di 5 colonne: servono la template key (colonna 1) "
            "e il package name (colonna 5), oppure un'intestazione."
        )

    rows: list[ElencoRow] = []
    seen: set[tuple[str, str]] = set()
    skipped = 0
    for cells in body:
        key = cells[key_col].strip() if key_col < len(cells) else ""
        package = cells[package_col].strip() if package_col < len(cells) else ""
        if _CONTROL.search(key) or _CONTROL.search(package):  # a line break, a control byte
            raise ElencoError(_NOT_CSV)
        if not key:
            skipped += 1
            continue
        package = package or NO_PACKAGE
        ident = (key.casefold(), package)
        if ident in seen:
            continue
        seen.add(ident)
        rows.append(ElencoRow(key, package))
    return Elenco(rows=tuple(rows), skipped=skipped)
