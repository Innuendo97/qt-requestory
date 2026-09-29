"""The "Filtri del confronto" panel and the control generation's state
(phase 2.5, spec §3.4 and §3.8): contract types shared by the engine, the
service, the fake and the UI (through ``ui/contracts.py``).

**Rows and ids.** Each row of the panel is a :class:`FilterGroup` with a
stable ``id``: the fixed rows in :data:`FILTER_IDS` (``zona.*``,
``variabile.*``, ``decidere.*``) plus one ``avanzate.<rule name>`` row per
regex rule — the noise presets and the initiative's and case's own rules
("Regole avanzate", :func:`advanced_filter_id`). The section a row belongs
to is its ``gruppo`` (:data:`FILTER_GRUPPI`), from the id's prefix
(:func:`filter_gruppo`).

**The switch.** ``attivo=True`` means the filter is ON: the row's occurrences
are SET ASIDE and do not count —

* ``zona.<zone>``: differences in that zone do not count (the engine emits
  them as ``arredo`` instead of ``zona``);
* ``variabile.<proof>``: what that proof recognises is a variable
  (``variabile.listino``: the price-list dictionary matches, ``Prova`` "listino");
* ``decidere.maiuscole`` / ``decidere.punteggiatura``: "Tollera tutte" — the
  case-only / punctuation-only differences are tolerated;
* ``avanzate.<name>``: the regex rule is applied (noise).

``zona.invisibile`` is INFORMATIONAL (ruling F7, :data:`INFORMATIONAL_IDS`):
invisible text is never compared; the row only says how much there is. It
has no switch (``FilterGroup.interruttore`` False, ``attivo`` always True)
and a choice for it is refused.

:attr:`FilterGroup.conta` is the inverse of ``attivo``, for a UI that labels
the switch "conta". Defaults (:data:`FILTER_DEFAULTS`, decisions D4, D9):
page number and watermark set aside; every other zone counts; recognised
variables are variables; case-only and punctuation-only differences count.

**Choices** are a mapping ``id → bool`` saved per case (``caso.json``
``filtri``) and per initiative as the default of its cases
(``iniziativa.json`` ``filtri``). The ``filtri`` map OWNS the state of every
row, advanced rules included (ruling F4): ``NoiseRule.enabled`` is only the
built-in default of an ``avanzate.<name>`` row without a choice (a preset's
default is off). The switch of a row is the case's choice, else the
initiative's, else the built-in default — :func:`filter_switch`.
:func:`apply_choices` merges a ``set_filters`` request (``None`` removes a
choice) and refuses junk with an Italian ``ValueError``. Choices for rules
that no longer exist (renamed, removed) are ignored, and the service drops
them at every save (:func:`prune_choices`). The legacy ``preset_rumore`` of
an initiative is mapped ONCE into its ``filtri`` (:func:`legacy_preset_choices`)
and never written again. A preset renamed since a choice was stored
(:data:`RENAMED_RULES`) keeps that choice under its new name.

**Occurrences** carry the stable ``Anchor`` s of their differences and
their pages (ruling F5). ``diff_ids`` (ids of one ``judged`` list,
renumbered at every comparison, R9) are filled only on
``CaseComparison.filters``, whose ``judged`` they index; they are always
``()`` from ``OfficinaApi.filters``. A row's ``n`` counts what was found
whatever its switch: turning a switch never changes ``n`` (F7).

**Control generation** (spec §3.4): its cache key is :func:`control_sha`,
sha256 of the generated document's bytes followed by the canonical JSON of
the payload — a new document or a replaced call is a new key (F7).

Stdlib only; no Qt, no pypdfium2.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, get_args

if TYPE_CHECKING:  # compare.model imports this module: the annotation stays a string
    from qtrequestory.officina.compare.model import Anchor

__all__ = [
    "ADVANCED_PREFIX", "CONTROL_STATES", "CONTROL_UNAVAILABLE_NOTE", "FILTER_DEFAULTS", "FILTER_GRUPPI",
    "FILTER_IDS", "FILTER_TITLES", "INFORMATIONAL_IDS", "ControlState", "ControlStatus", "FilterGroup",
    "FilterGruppo", "FilterOccurrence", "FilterPanel", "advanced_filter_id", "advanced_rule_name",
    "RENAMED_RULES", "apply_choices", "control_sha", "current_rule_name", "filter_gruppo", "filter_switch",
    "is_filter_id", "legacy_preset_choices", "prune_choices",
]

FilterGruppo = Literal["zone", "variabili", "decidere", "avanzate"]
ControlStatus = Literal["assente", "in_corso", "pronta", "non_disponibile"]

FILTER_GRUPPI: tuple[str, ...] = get_args(FilterGruppo)
#: ``assente``: never run (or cancelled by a regeneration); ``in_corso``: running
#: in the background (in memory only: read back from disk it is ``assente``);
#: ``pronta``: its "esecuzione" proofs are in use; ``non_disponibile``: it
#: failed — silently (D14).
CONTROL_STATES: tuple[str, ...] = get_args(ControlStatus)

#: The discreet note of a failed control generation (spec §3.4).
CONTROL_UNAVAILABLE_NOTE = "riconoscimento esteso non disponibile per questo caso"

#: Prefix of the "Regole avanzate" rows: ``avanzate.<rule name>``.
ADVANCED_PREFIX = "avanzate."

#: The fixed rows, in panel order, with their Italian titles.
FILTER_TITLES: dict[str, str] = {
    "zona.header": "Header",
    "zona.titolo": "Titolo",
    "zona.footer": "Footer",
    "zona.spalla_sx": "Spalla sinistra",
    "zona.spalla_dx": "Spalla destra",
    "zona.numero_pagina": "Numero di pagina",
    "zona.filigrana": "Filigrana",
    "zona.invisibile": "Testo invisibile",
    "variabile.segnaposto": "Segnaposto",
    "variabile.buco": "Buchi del target",
    "variabile.cella": "Celle vuote",
    "variabile.sezione": "Sezioni vuote",
    "variabile.esecuzione": "Cambiano fra due generazioni",
    "variabile.listino": "Listino",
    "decidere.maiuscole": "Solo maiuscole",
    "decidere.punteggiatura": "Solo punteggiatura",
}
FILTER_IDS: tuple[str, ...] = tuple(FILTER_TITLES)

#: Rows without a switch (always ``attivo``): a choice for them is refused.
INFORMATIONAL_IDS: frozenset[str] = frozenset({"zona.invisibile"})

#: Built-in switch of each fixed row (``True`` = set aside), see the module doc.
FILTER_DEFAULTS: dict[str, bool] = {
    fid: fid in ("zona.numero_pagina", "zona.filigrana", "zona.invisibile") or fid.startswith("variabile.")
    for fid in FILTER_IDS
}

#: Presets renamed after choices were stored under the old name (old → new):
#: "Numero di pagina" matches a page number written in the TEXT, not the
#: ``zona.numero_pagina`` zone (U4 M6). Read as the new name, never written.
RENAMED_RULES: dict[str, str] = {"Numero di pagina": "Numero di pagina nel testo"}

_GRUPPO_OF_PREFIX = {"zona": "zone", "variabile": "variabili", "decidere": "decidere", "avanzate": "avanzate"}


def advanced_filter_id(rule_name: str) -> str:
    """The row id of the regex rule (or preset) ``rule_name``."""
    return ADVANCED_PREFIX + rule_name


def advanced_rule_name(filter_id: str) -> str | None:
    """The rule name of an ``avanzate.<name>`` id; None for any other id."""
    return filter_id[len(ADVANCED_PREFIX):] if filter_id.startswith(ADVANCED_PREFIX) else None


def is_filter_id(value: object) -> bool:
    """A fixed id, or ``avanzate.`` followed by a non-blank rule name."""
    if not isinstance(value, str):
        return False
    if value.startswith(ADVANCED_PREFIX):
        return bool(value[len(ADVANCED_PREFIX):].strip())
    return value in FILTER_TITLES


def filter_gruppo(filter_id: str) -> FilterGruppo:
    """The section of ``filter_id``; ``ValueError`` for anything that is not an id."""
    if not is_filter_id(filter_id):
        raise ValueError(f"filtro «{filter_id}» non riconosciuto")
    return _GRUPPO_OF_PREFIX[filter_id.split(".", 1)[0]]  # type: ignore[return-value]


def filter_switch(filter_id: str, case_choices: Mapping[str, bool], initiative_choices: Mapping[str, bool],
                  rules_enabled: Mapping[str, bool] | None = None) -> tuple[bool, bool]:
    """``(attivo, predefinito)`` of a row: ``predefinito`` is the initiative's
    choice, else the built-in default (``rules_enabled[name]`` for an
    ``avanzate.<name>`` row, False for an unknown rule); ``attivo`` is the
    case's choice, else ``predefinito``. An informational row is ``(True, True)``."""
    if filter_id in INFORMATIONAL_IDS:
        return True, True
    if filter_id in initiative_choices:
        default = initiative_choices[filter_id]
    elif (name := advanced_rule_name(filter_id)) is not None:
        default = (rules_enabled or {}).get(name, False)
    else:
        default = FILTER_DEFAULTS.get(filter_id, False)
    return case_choices.get(filter_id, default), default


def apply_choices(current: Mapping[str, bool], choices: Mapping[str, bool | None]) -> dict[str, bool]:
    """``current`` with ``choices`` merged in (``None`` removes that choice).
    ``ValueError`` (Italian) — and nothing merged — for an id that is not a
    filter id, an informational row, or a value that is not a bool/None."""
    for key, value in choices.items():
        if not is_filter_id(key):
            raise ValueError(f"filtro «{key}» non riconosciuto")
        if key in INFORMATIONAL_IDS:
            raise ValueError(f"filtro «{key}»: è solo informativo, non si accende né si spegne")
        if value is not None and type(value) is not bool:
            raise ValueError(f"filtro «{key}»: il valore deve essere acceso o spento")
    merged = dict(current)
    for key, value in choices.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    return merged


def prune_choices(choices: Mapping[str, bool], rule_names: Iterable[str]) -> dict[str, bool]:
    """``choices`` without the ``avanzate.<name>`` entries whose rule is not
    in ``rule_names`` (the presets and the rules in scope): a renamed or
    removed rule leaves a stale key, dropped at every save."""
    names = set(rule_names)
    return {k: v for k, v in choices.items() if (n := advanced_rule_name(k)) is None or n in names}


def current_rule_name(name: str) -> str:
    """``name`` as the rule is called now (:data:`RENAMED_RULES`)."""
    return RENAMED_RULES.get(name, name)


def legacy_preset_choices(preset_names: Iterable[str]) -> dict[str, bool]:
    """The ``filtri`` entries a legacy ``preset_rumore`` list stands for:
    each preset it turned on is its advanced row switched ON (by its current name)."""
    return {advanced_filter_id(current_rule_name(name)): True for name in preset_names if name.strip()}


def control_sha(document: bytes, payload: object) -> str:
    """The key of a control generation: sha256 of the generated document's
    bytes followed by the payload as canonical JSON (sorted keys, no
    spaces, UTF-8)."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(document + canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FilterOccurrence:
    """One occurrence behind a row, for its expandable list: ``testo`` a
    short display text (target side; the generated text when the target has
    none), ``pagine`` the 0-based pages (target side; several for a zone
    "uguale su N pagine"), ``anchors`` the stable keys of the differences it
    stands for (the UI selects a difference by anchor; empty when it is not
    a difference, e.g. invisible text), ``diff_ids`` their ``Diff.id`` s —
    ONLY on ``CaseComparison.filters`` (ids of that ``judged``), always
    ``()`` from ``OfficinaApi.filters`` — ``zona`` its zone (``ZONES``),
    ``dettaglio`` a short extra (the variable's name, the rule's hits...)."""

    testo: str
    pagine: tuple[int, ...] = ()
    anchors: tuple[Anchor, ...] = ()
    diff_ids: tuple[int, ...] = ()
    zona: str = "corpo"
    dettaglio: str = ""


@dataclass(frozen=True)
class FilterGroup:
    """One row of the panel. ``attivo`` the switch now (ON = set aside),
    ``predefinito`` the switch without the case's own choice (initiative →
    built-in), ``n`` the occurrences found in the last comparison WHATEVER
    the switch (0 = none: the row stays, dimmed), ``interruttore`` False for
    an informational row (no switch shown; ``attivo`` always True)."""

    id: str
    titolo: str
    gruppo: FilterGruppo
    attivo: bool
    predefinito: bool
    n: int
    occorrenze: tuple[FilterOccurrence, ...] = ()
    interruttore: bool = True

    @property
    def conta(self) -> bool:
        """The row's occurrences count as differences (the switch is off)."""
        return not self.attivo


@dataclass(frozen=True)
class ControlState:
    """The control generation of a case (D14): ``stato`` (:data:`CONTROL_STATES`),
    ``nota`` Italian and discreet ("" when there is nothing to say; never an
    error message), ``quando`` ISO timestamp of the last change ("" if none)."""

    stato: ControlStatus
    nota: str = ""
    quando: str = ""


@dataclass(frozen=True)
class FilterPanel:
    """What ``OfficinaApi.filters(ini, case)`` returns: the rows in panel
    order (zone, variabili, decidere, avanzate), the control generation's
    state and an optional Italian note about the panel as a whole."""

    groups: tuple[FilterGroup, ...]
    controllo: ControlState
    nota: str = ""

    def group(self, filter_id: str) -> FilterGroup | None:
        """The row ``filter_id``, or None."""
        return next((g for g in self.groups if g.id == filter_id), None)

    def of(self, gruppo: str) -> tuple[FilterGroup, ...]:
        """The rows of one section, in order."""
        return tuple(g for g in self.groups if g.gruppo == gruppo)

    def choices(self) -> dict[str, bool]:
        """``id → attivo`` of every switchable row (what ``set_filters`` takes)."""
        return {g.id: g.attivo for g in self.groups if g.interruttore}
