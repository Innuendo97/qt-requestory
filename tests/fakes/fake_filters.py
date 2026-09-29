"""The fake's "Filtri del confronto" and control generation (phase 2.5, T0):
``FakeFiltersMixin`` is mixed into ``FakeOfficinaApi`` (``fake_officina.py``).

No Qt, no engine. The COUNTS and OCCURRENCES of the rows are scripted; the
SWITCHES are real state, owned by the ``filtri`` maps (ruling F4):
``set_filters`` validates and merges with the contract's own
``filter_model.apply_choices``, prunes stale ``avanzate.*`` keys
(``prune_choices``) and saves with the real model (``Workspace.save_review``
for a case, ``save_initiative_settings`` for the initiative) BEFORE updating
``case.review.filters`` / ``ini.filters`` — a refused save changes nothing.
Every row's ``attivo`` / ``predefinito`` is computed with
``filter_model.filter_switch`` from the ``ini`` and ``case`` passed in
(case choice → initiative choice → built-in default; for ``avanzate.<name>``
the rule's own ``enabled``, a preset's is off). Scripting API (U4)::

    from tests.fakes.fake_filters import fake_group, fake_occurrence
    api.set_filter_groups(case.id, [
        fake_group("zona.footer", n=2, occorrenze=[
            fake_occurrence("Acme-Servizi S.p.A.", pagine=(0, 1), anchors=(diff.anchor,), zona="footer")]),
        fake_group("decidere.maiuscole", n=5),
        fake_group("avanzate.Data", n=4),
    ], nota="")                                   # the panel's own note
    api.set_control_state(case.id, ControlState("in_corso"))   # None: back to the record
    panel = api.filters(ini, case)                # rows in the scripted order

* Without ``set_filter_groups`` the panel has every fixed row
  (``FILTER_IDS``) then one ``avanzate.<name>`` row per preset
  (``FAKE_PRESETS``), initiative rule and case rule — first name wins, like
  the service's ``_unique_rules`` — all with ``n=0`` and no occurrences.
* A scripted row's ``titolo`` defaults to ``FILTER_TITLES`` (the rule name
  for ``avanzate.*``), its ``gruppo`` comes from the id, ``interruttore`` is
  False for ``INFORMATIONAL_IDS``; ``attivo`` / ``predefinito`` are always
  recomputed. ``n`` never depends on the switch.
* ``diff_ids``: always ``()`` from ``filters``; on ``CaseComparison.filters``
  (set for every case, like the real service) they are the ids in that ``judged`` whose anchor is in the occurrence's
  ``anchors``.
* ``control_state`` / ``FilterPanel.controllo``: the scripted state, else the
  ``controllo`` record in ``caso.json`` (``ControlRecord.state()``), else
  ``assente``.
* ``review_actions`` records ``("set_filters", case id or None)``.
"""
from __future__ import annotations

import dataclasses
from collections.abc import Iterable, Mapping, Sequence

from qtrequestory.officina.compare.filter_model import (
    FILTER_IDS,
    FILTER_TITLES,
    INFORMATIONAL_IDS,
    ControlState,
    FilterGroup,
    FilterOccurrence,
    FilterPanel,
    advanced_filter_id,
    advanced_rule_name,
    apply_choices,
    filter_gruppo,
    filter_switch,
    prune_choices,
)
from qtrequestory.officina.compare.filter_rows import rule_rows, switches
from qtrequestory.officina.compare.model import Anchor, Judged
from qtrequestory.officina.model import Case, Initiative
from qtrequestory.officina.model_case import load_case
from qtrequestory.officina.model_review import NoiseRule

from tests.fakes.fake_verdict import FAKE_PRESETS

__all__ = ["FakeFiltersMixin", "fake_group", "fake_occurrence"]


def fake_occurrence(testo: str, *, pagine: Iterable[int] = (0,), anchors: Iterable[Anchor] = (),
                    zona: str = "corpo", dettaglio: str = "") -> FilterOccurrence:
    """One occurrence of a scripted row (0-based pages, the differences' anchors)."""
    return FilterOccurrence(testo, tuple(pagine), tuple(anchors), (), zona, dettaglio)


def fake_group(filter_id: str, *, n: int = 0, occorrenze: Iterable[FilterOccurrence] = (),
               titolo: str | None = None) -> FilterGroup:
    """A scripted row: ``filter_id`` must be a filter id (``ValueError`` else)."""
    name = advanced_rule_name(filter_id)
    if titolo is None:
        titolo = name if name is not None else FILTER_TITLES[filter_id]
    return FilterGroup(filter_id, titolo, filter_gruppo(filter_id), False, False, n, tuple(occorrenze),
                       interruttore=filter_id not in INFORMATIONAL_IDS)


def _unique(rules: Iterable[NoiseRule]) -> list[NoiseRule]:
    """First name wins (the service's ``_unique_rules``)."""
    seen: set[str] = set()
    out = []
    for rule in rules:
        if rule.name not in seen:
            seen.add(rule.name)
            out.append(rule)
    return out


class FakeFiltersMixin:
    """Needs ``_workspace()``, ``_update_review()`` and ``_commit_initiative()``
    of ``FakeOfficinaApi``; call :meth:`_init_filters` from its ``__init__``."""

    def _init_filters(self) -> None:
        #: case id -> (scripted rows, panel note)
        self.filter_groups: dict[str, tuple[tuple[FilterGroup, ...], str]] = {}
        #: case id -> scripted control state
        self.control_states: dict[str, ControlState] = {}

    # -- knobs -------------------------------------------------------------

    def set_filter_groups(self, case_id: str, groups: Iterable[FilterGroup] | None, *, nota: str = "") -> None:
        """The rows ``filters`` returns for ``case_id`` (``None``: the default rows)."""
        if groups is None:
            self.filter_groups.pop(case_id, None)
        else:
            self.filter_groups[case_id] = (tuple(groups), nota)

    def set_control_state(self, case_id: str, state: ControlState | None) -> None:
        """What ``control_state`` answers for ``case_id`` (``None``: from the record)."""
        if state is None:
            self.control_states.pop(case_id, None)
        else:
            self.control_states[case_id] = state

    # -- contract ------------------------------------------------------------

    def filters(self, ini: Initiative, case: Case) -> FilterPanel:
        rules = _unique((*FAKE_PRESETS, *ini.noise_rules, *case.review.noise_rules))
        enabled = {r.name: r.enabled for r in rules}
        scripted, nota = self.filter_groups.get(case.id, (None, ""))
        if scripted is None:
            scripted = tuple(fake_group(fid) for fid in (*FILTER_IDS, *(advanced_filter_id(r.name) for r in rules)))
        rows = []
        for row in scripted:
            attivo, predefinito = filter_switch(row.id, case.review.filters, ini.filters, enabled)
            occorrenze = tuple(dataclasses.replace(o, diff_ids=()) for o in row.occorrenze)
            rows.append(dataclasses.replace(row, attivo=attivo, predefinito=predefinito, occorrenze=occorrenze))
        return FilterPanel(tuple(rows), self.control_state(case), nota)

    def set_filters(self, ini: Initiative, case: Case | None, choices: Mapping[str, bool | None]) -> None:
        presets = [p.name for p in FAKE_PRESETS]
        if case is None:
            names = [*presets, *(r.name for r in ini.noise_rules),
                     *(r.name for c in ini.cases for r in c.review.noise_rules)]
            merged = prune_choices(apply_choices(ini.filters, choices), names)
            self._commit_initiative("set_filters", ini, filters=merged)
        else:
            names = [*presets, *(r.name for r in ini.noise_rules), *(r.name for r in case.review.noise_rules)]
            merged = prune_choices(apply_choices(case.review.filters, choices), names)
            self._update_review("set_filters", case, filters=merged)

    def control_state(self, case: Case) -> ControlState:
        if case.id in self.control_states:
            return self.control_states[case.id]
        loaded = load_case(case.folder)
        record = (case if loaded.load_error else loaded).review.control
        return record.state() if record is not None else ControlState("assente")

    # -- used by compare_case --------------------------------------------------

    def _tolerated(self, ini: Initiative, case: Case) -> frozenset[str]:
        """The tipi «Tollera tutte» tolerates for ``case`` (the real ``filter_rows.switches``)."""
        rules = rule_rows(FAKE_PRESETS, ini.noise_rules, case.review.noise_rules)
        return switches(case.review.filters, ini.filters, rules).tolerated

    def _comparison_filters(self, ini: Initiative, case: Case, judged: Sequence[Judged]) -> FilterPanel:
        """``CaseComparison.filters``, for every case like the real service:
        the panel (scripted rows, else the default ones with n=0) with the
        ``diff_ids`` of ``judged``."""
        panel = self.filters(ini, case)
        rows = tuple(dataclasses.replace(g, occorrenze=tuple(
            dataclasses.replace(o, diff_ids=tuple(j.diff.id for j in judged if j.diff.anchor in o.anchors))
            for o in g.occorrenze)) for g in panel.groups)
        return dataclasses.replace(panel, groups=rows)
