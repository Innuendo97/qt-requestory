"""The "Filtri del confronto" panel computed from one comparison (phase 2.5,
spec §3.8, task A5): what each row found, the switches the engine applies,
and the panel itself (types and switch semantics: ``filter_model``).

* :func:`found` — per row id, ``(n, occurrences)`` of one TO-BE comparison,
  WHATEVER the switches (F7: turning a switch never changes ``n``):

  - ``zona.<zone>``: the differences in that zone that a switch can set
    aside (every class but variables, noise and links — the pipeline's
    ``aside`` rule), one occurrence each ("uguale su N pagine" in ``dettaglio``);
  - ``zona.invisibile``: the invisible text of the target and of the
    generated document, one occurrence per line, without anchors (never a
    difference);
  - ``variabile.<proof>``: ``variables.occurrences`` (every difference
    carrying that proof, switched on or not);
  - ``decidere.maiuscole`` / ``decidere.punteggiatura``: the differences of
    that ``tipo`` that have a verdict;
  - ``avanzate.<name>``: the rule's hits (counted over the texts, on or
    off), no occurrences.
* :func:`rule_rows` — the regex rules behind the ``avanzate.*`` rows: the
  presets, the initiative's rules, the case's, first name wins.
* :func:`switches` — the case's switches as the engine takes them: the
  zones set aside, the proofs on, the tipi tolerated, the rules applied.
* :func:`panel` — the :class:`FilterPanel` of a case from what was found and
  the choices in hand; :func:`with_ids` adds the ``diff_ids`` of a judged
  list (``CaseComparison.filters`` only, F5).

Pure; stdlib only.
"""
from __future__ import annotations

import dataclasses
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from qtrequestory.officina.compare import variables
from qtrequestory.officina.compare.filter_model import (
    FILTER_IDS,
    FILTER_TITLES,
    INFORMATIONAL_IDS,
    ControlState,
    FilterGroup,
    FilterOccurrence,
    FilterPanel,
    advanced_filter_id,
    filter_gruppo,
    filter_switch,
)
from qtrequestory.officina.compare.model import NO_VERDICT, PROVE, Diff, Judged, Word
from qtrequestory.officina.model_review import NoiseRule

__all__ = ["DECIDE_TIPI", "SWITCHED_ZONES", "Found", "Switches", "found", "panel", "rule_rows", "switches",
           "with_ids"]

#: The zones a ``zona.<zone>`` switch sets aside (``zona.invisibile`` is informational).
SWITCHED_ZONES: tuple[str, ...] = ("header", "titolo", "footer", "spalla_sx", "spalla_dx", "numero_pagina",
                                   "filigrana")
#: The tipi of the "Da decidere" rows.
DECIDE_TIPI: tuple[str, ...] = ("maiuscole", "punteggiatura")
#: Classes a zone switch never touches (the pipeline keeps them as they are).
_NOT_ZONED = frozenset({"variabile", "rumore", "link"})

#: Per row id: ``(n, occurrences)``.
Found = Mapping[str, tuple[int, tuple[FilterOccurrence, ...]]]


@dataclass(frozen=True)
class Switches:
    """The switches of a case as the engine applies them."""

    aside: frozenset[str]        # zones whose differences do not count (``arredo``)
    proofs: frozenset[str]       # the variables' proofs switched on (``Values.proofs``)
    tolerated: frozenset[str]    # tipi tolerated by «Tollera tutte» (``verdict.judge``)
    rules_on: frozenset[str]     # names of the regex rules / presets applied


def rule_rows(*levels: Iterable[NoiseRule]) -> list[NoiseRule]:
    """The rules of ``levels`` (presets, initiative, case) in order, the
    first of each name only (the comparison's ``_unique_rules``)."""
    seen: set[str] = set()
    out: list[NoiseRule] = []
    for level in levels:
        for rule in level:
            if rule.name not in seen:
                seen.add(rule.name)
                out.append(rule)
    return out


def _switch(filter_id: str, case_choices: Mapping[str, bool], ini_choices: Mapping[str, bool],
            enabled: Mapping[str, bool]) -> tuple[bool, bool]:
    return filter_switch(filter_id, case_choices, ini_choices, enabled)


def switches(case_choices: Mapping[str, bool], ini_choices: Mapping[str, bool],
             rules: Sequence[NoiseRule]) -> Switches:
    """What the engine applies for these choices (case → initiative →
    built-in; a rule's own ``enabled`` is only its default, F4)."""
    enabled = {r.name: r.enabled for r in rules}

    def on(filter_id: str) -> bool:
        return _switch(filter_id, case_choices, ini_choices, enabled)[0]
    return Switches(
        aside=frozenset(z for z in SWITCHED_ZONES if on(f"zona.{z}")),
        proofs=frozenset(p for p in PROVE if on(f"variabile.{p}")),
        tolerated=frozenset(t for t in DECIDE_TIPI if on(f"decidere.{t}")),
        rules_on=frozenset(r.name for r in rules if on(advanced_filter_id(r.name))),
    )


def _pages(words: Sequence[Word]) -> tuple[int, ...]:
    return tuple(sorted({w.page for w in words}))


def _occurrence(d: Diff) -> FilterOccurrence:
    return FilterOccurrence(d.left_text or d.right_text, _pages(d.left or d.right), (d.anchor,), (), d.zone,
                            d.detail)


def _lines(words: Sequence[Word], label: str) -> list[FilterOccurrence]:
    """The invisible ``words`` as one occurrence per line (page and baseline)."""
    out: list[FilterOccurrence] = []
    line: list[Word] = []
    for word in words:
        if line and (word.page != line[-1].page or abs(word.y1 - line[-1].y1) > max(1.0, 0.5 * (word.y1 - word.y0))):
            out.append(FilterOccurrence(" ".join(w.text for w in line), (line[0].page,), dettaglio=label))
            line = []
        line.append(word)
    if line:
        out.append(FilterOccurrence(" ".join(w.text for w in line), (line[0].page,), dettaglio=label))
    return out


def found(diffs: Sequence[Diff], invisible: Sequence[tuple[str, Sequence[Word]]] = (),
          hits: Mapping[str, int] | None = None) -> dict[str, tuple[int, tuple[FilterOccurrence, ...]]]:
    """Per row id, ``(n, occurrences)`` in ``diffs`` (a TO-BE comparison's,
    before the verdict), ``invisible`` (``(label, words)`` per side) and
    ``hits`` (rule name → hits); see the module doc."""
    out: dict[str, tuple[int, tuple[FilterOccurrence, ...]]] = {}
    for zone in SWITCHED_ZONES:
        occ = tuple(_occurrence(d) for d in diffs
                    if d.zone == zone and d.op != "pagine" and d.klass not in _NOT_ZONED)
        out[f"zona.{zone}"] = (len(occ), occ)
    lines = tuple(o for label, words in invisible for o in _lines(words, label))
    out["zona.invisibile"] = (len(lines), lines)
    for filter_id, occ in variables.occurrences(diffs).items():
        out[filter_id] = (len(occ), occ)
    for tipo in DECIDE_TIPI:
        occ = tuple(_occurrence(d) for d in diffs if d.tipo == tipo and d.klass not in NO_VERDICT)
        out[f"decidere.{tipo}"] = (len(occ), occ)
    for name, n in (hits or {}).items():
        out[advanced_filter_id(name)] = (n, ())
    return out


def panel(rows_found: Found, rules: Sequence[NoiseRule], case_choices: Mapping[str, bool],
          ini_choices: Mapping[str, bool], controllo: ControlState, nota: str = "") -> FilterPanel:
    """Every fixed row then one row per rule (``rule_rows``), with the
    switches of the choices in hand and what was found (0 and none for a
    row nothing was found for)."""
    enabled = {r.name: r.enabled for r in rules}
    groups = []
    for filter_id in (*FILTER_IDS, *(advanced_filter_id(r.name) for r in rules)):
        n, occ = rows_found.get(filter_id, (0, ()))
        attivo, predefinito = _switch(filter_id, case_choices, ini_choices, enabled)
        titolo = FILTER_TITLES.get(filter_id) or filter_id.split(".", 1)[1]
        groups.append(FilterGroup(filter_id, titolo, filter_gruppo(filter_id), attivo, predefinito, n,
                                  tuple(dataclasses.replace(o, diff_ids=()) for o in occ),
                                  interruttore=filter_id not in INFORMATIONAL_IDS))
    return FilterPanel(tuple(groups), controllo, nota)


def with_ids(filters: FilterPanel, judged: Sequence[Judged]) -> FilterPanel:
    """``filters`` whose occurrences carry the ids in ``judged`` of the
    differences with their anchors (``CaseComparison.filters``, F5)."""
    ids: dict[object, list[int]] = {}
    for j in judged:
        ids.setdefault(j.diff.anchor, []).append(j.diff.id)
    groups = tuple(dataclasses.replace(g, occorrenze=tuple(
        dataclasses.replace(o, diff_ids=tuple(i for a in o.anchors for i in ids.get(a, ())))
        for o in g.occorrenze)) for g in filters.groups)
    return dataclasses.replace(filters, groups=groups)
