"""What the side panel says about difference TYPES and page ZONES (phase 2.5,
spec §3.2, §3.5, §5; D8, D9, D15; ruling F3). No widgets here.

**Types** (``Diff.tipo``): every type has an icon and a short name (the chip)
and a whole name (the tooltip); ALL types count (D9). The chips count the
rows of the current verdict tab per type; a difference of the zones set
aside (``klass == "arredo"``: page number, watermark) is never counted and
never filtered by type: it only shows in "Tutte", in its own group at the end
(:data:`ARREDO_GROUP`).

**Groups** (:func:`grouped`): the rows of a tab, grouped by type in
:data:`TYPE_ORDER` — each group a :class:`TypeGroup` header followed by its
rows in the tab's own order (so the non risolte stay first inside their
group); a folded group keeps only its header. In "Da guardare" the marked
rows keep their "DA VERIFICARE" group (``None``) after the type groups.

**Zones** (:func:`zones_summary`): the zones found on either side (their
``ZoneBox`` es, or a difference in them) with ✓ when nothing there is left to
look at, else how many are; page number and watermark are "ignorate" unless
the Filtri turned them back on (then their differences count like any zone's).
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import ARREDO_ZONES, Judged
from qtrequestory.ui.pages.officina_rows import in_document_order, tab_of

__all__ = ["ARREDO_GROUP", "MAIN_ZONES", "TYPE_ORDER", "TYPES", "TypeGroup", "TypeInfo", "ZONE_NAMES",
           "ZONE_TOKENS", "group_key", "grouped", "insert_in_group", "is_arredo", "is_diff", "type_counts",
           "where_zone", "zone_name", "zones_summary"]


@dataclass(frozen=True)
class TypeInfo:
    icon: str
    name: str
    tip: str


#: The chips' order: the most frequent kinds first (draft f25-caso-v2).
TYPE_ORDER = ("parola", "zona", "numeri", "maiuscole", "punteggiatura", "spazi", "frase", "sezione",
              "spostamento", "link", "altro")
TYPES: dict[str, TypeInfo] = {
    "parola": TypeInfo("Aa", strings.PANNELLO_TIPO_PAROLA, strings.PANNELLO_TIPO_PAROLA_TIP),
    "zona": TypeInfo("▭", strings.PANNELLO_TIPO_ZONA, strings.PANNELLO_TIPO_ZONA_TIP),
    "numeri": TypeInfo("#", strings.PANNELLO_TIPO_NUMERI, strings.PANNELLO_TIPO_NUMERI_TIP),
    "maiuscole": TypeInfo("A/a", strings.PANNELLO_TIPO_MAIUSCOLE, strings.PANNELLO_TIPO_MAIUSCOLE_TIP),
    "punteggiatura": TypeInfo(".,", strings.PANNELLO_TIPO_PUNTEGGIATURA, strings.PANNELLO_TIPO_PUNTEGGIATURA_TIP),
    "spazi": TypeInfo("␣", strings.PANNELLO_TIPO_SPAZI, strings.PANNELLO_TIPO_SPAZI_TIP),
    "frase": TypeInfo("≡", strings.PANNELLO_TIPO_FRASE, strings.PANNELLO_TIPO_FRASE_TIP),
    "sezione": TypeInfo("▤", strings.PANNELLO_TIPO_SEZIONE, strings.PANNELLO_TIPO_SEZIONE_TIP),
    "spostamento": TypeInfo("⇄", strings.PANNELLO_TIPO_SPOSTAMENTO, strings.PANNELLO_TIPO_SPOSTAMENTO_TIP),
    "link": TypeInfo("🔗︎", strings.PANNELLO_TIPO_LINK, strings.PANNELLO_TIPO_LINK_TIP),
    "altro": TypeInfo("✱", strings.PANNELLO_TIPO_ALTRO, strings.PANNELLO_TIPO_ALTRO_TIP),
}
#: The group key of the page-number / watermark differences (not a type: never a chip).
ARREDO_GROUP = "arredo"

ZONE_NAMES = {"header": strings.ZONA_HEADER, "titolo": strings.ZONA_TITOLO, "footer": strings.ZONA_FOOTER,
              "spalla_sx": strings.ZONA_SPALLA_SX, "spalla_dx": strings.ZONA_SPALLA_DX,
              "numero_pagina": strings.ZONA_NUMERO_PAGINA, "filigrana": strings.ZONA_FILIGRANA,
              "corpo": strings.ZONA_CORPO}
#: The summary's zones, top to bottom of a page (then the two set aside).
MAIN_ZONES = ("header", "titolo", "spalla_sx", "spalla_dx", "footer")
#: The token of each zone's rail on the page margin (paper values: the page is white).
ZONE_TOKENS = {"header": "accent", "titolo": "variable", "footer": "accent", "spalla_sx": "ok",
               "spalla_dx": "ok", "numero_pagina": "muted", "filigrana": "muted"}


@dataclass(frozen=True)
class TypeGroup:
    """A group header in the list: ``tipo`` (a ``TYPES`` key or
    :data:`ARREDO_GROUP`), how many rows it holds, whether it is folded."""

    tipo: str
    n: int
    folded: bool = False

    @property
    def text(self) -> str:
        if self.tipo == ARREDO_GROUP:
            return strings.PANNELLO_GROUP.format(name=strings.PANNELLO_GROUP_ARREDO, n=self.n)
        return strings.PANNELLO_GROUP.format(name=TYPES[self.tipo].name, n=self.n)

    @property
    def icon(self) -> str:
        if self.tipo == ARREDO_GROUP:
            return strings.VERDETTO_ICON_ARREDO
        return TYPES[self.tipo].icon


def is_diff(entry: object) -> bool:
    """A row that is a difference (not a group header)."""
    return isinstance(entry, Judged)


def is_arredo(j: Judged) -> bool:
    return j.diff.klass == "arredo"


def _tipo(j: Judged) -> str:
    return j.diff.tipo if j.diff.tipo in TYPES else "altro"


def type_counts(rows: Iterable[object]) -> dict[str, int]:
    """How many differences of each type ``rows`` hold (arredo never counts)."""
    counts = dict.fromkeys(TYPE_ORDER, 0)
    for j in rows:
        if is_diff(j) and not is_arredo(j):
            counts[_tipo(j)] += 1
    return counts


def grouped(rows: Sequence[Judged | None], types: frozenset[str] = frozenset(),
            folded: Iterable[str] = ()) -> list[Judged | TypeGroup | None]:
    """``rows`` (a tab's, ``None`` = the "DA VERIFICARE" header) grouped by
    type; ``types`` (empty = all) keeps only those types (and drops the
    arredo group); ``folded`` groups keep only their header."""
    folded = set(folded)
    cut = next((i for i, j in enumerate(rows) if j is None), len(rows))
    main, marked = rows[:cut], [j for j in rows[cut + 1:] if j is not None]

    def keep(j: Judged) -> bool:
        return not types or (not is_arredo(j) and _tipo(j) in types)

    buckets: dict[str, list[Judged]] = {}
    for j in main:
        if j is not None and keep(j):
            buckets.setdefault(ARREDO_GROUP if is_arredo(j) else _tipo(j), []).append(j)
    out: list[Judged | TypeGroup | None] = []
    for key in (*TYPE_ORDER, ARREDO_GROUP):
        members = buckets.get(key)
        if members:
            out.append(TypeGroup(key, len(members), key in folded))
            if key not in folded:
                out += members
    marked = [j for j in marked if keep(j)]
    if marked:
        out += [None, *marked]
    return out


def zone_name(zone: str) -> str:
    return ZONE_NAMES.get(zone, zone)


def where_zone(j: Judged) -> str:
    """"footer · pag. 1" (the zone and the page), or "" without boxes."""
    words = j.diff.left or j.diff.right
    if not words:
        return zone_name(j.diff.zone)
    return strings.PANNELLO_ROW_WHERE.format(zone=zone_name(j.diff.zone), page=words[0].page + 1)


def zones_summary(judged: Sequence[Judged], zones: Iterable[object]) -> tuple[str, bool]:
    """``(text, known)``: "Header ✓ · Spalla sx 1 · … · pag. e filigrana
    ignorate" for the zones in ``zones`` (``ZoneBox`` es of both sides) and
    those the differences are in; ``known`` False when no zone was found."""
    present = {getattr(z, "zone", "") for z in zones} | {j.diff.zone for j in judged}
    present.discard("corpo")
    present.discard("")
    if not present:
        return strings.PANNELLO_ZONES_NONE, False
    counting = {z for z in ARREDO_ZONES if any(j.diff.zone == z and not is_arredo(j) for j in judged)}
    parts = []
    for zone in (*MAIN_ZONES, *sorted(counting)):
        if zone in present:
            n = sum(1 for j in judged if j.diff.zone == zone and tab_of(j) == "guardare")
            parts.append((strings.PANNELLO_ZONE_N.format(zone=zone_name(zone), n=n) if n
                          else strings.PANNELLO_ZONE_OK.format(zone=zone_name(zone))))
    if present & (ARREDO_ZONES - counting):
        parts.append(strings.PANNELLO_ZONE_IGNORED)
    return " · ".join(parts), True


def group_key(j: Judged) -> str:
    """The group ``j`` is listed in (its type, or :data:`ARREDO_GROUP`)."""
    return ARREDO_GROUP if is_arredo(j) else _tipo(j)


def insert_in_group(rows: Sequence[Judged | TypeGroup | None], j: Judged) -> list[Judged | TypeGroup | None]:
    """``rows`` with ``j`` put back under ITS type header (a pinned row, F8):
    at its document place among the group's rows, or — when the group is
    gone from the tab — under a new header of its own (count 0: the tab's
    real counts), at the group's place in :data:`TYPE_ORDER`; always above
    the "DA VERIFICARE" header."""
    out = list(rows)
    key = group_key(j)
    order = (*TYPE_ORDER, ARREDO_GROUP)
    cut = next((i for i, e in enumerate(out) if e is None), len(out))
    head = next((i for i, e in enumerate(out[:cut]) if isinstance(e, TypeGroup) and e.tipo == key), None)
    if head is None:
        at = next((i for i, e in enumerate(out[:cut])
                   if isinstance(e, TypeGroup) and order.index(e.tipo) > order.index(key)), cut)
        return [*out[:at], TypeGroup(key, 0), j, *out[at:]]
    end = head + 1
    while end < len(out) and is_diff(out[end]):
        end += 1
    members = out[head + 1:end]
    place = in_document_order([*members, j]).index(j)
    at = head + 1 + place
    return [*out[:at], j, *out[at:]]
