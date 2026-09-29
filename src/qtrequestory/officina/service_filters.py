"""The "Filtri del confronto" half of ``OfficinaService`` (``officina.service``;
phase 2.5, spec §3.8, rulings F4–F7, F14, F15): ``filters``, ``set_filters``
and the noise rules' save, plus what ``compare_case`` asks of the panel.

* **Switches** (``compare.filter_rows.switches``): the ``filtri`` maps OWN
  every row (F4) — the case's choice, else the initiative's, else the
  built-in default (a rule's own ``enabled`` for its ``avanzate.<name>`` row,
  off for a preset). ``compare_case`` applies them: the zones set aside
  (``aside``), the proofs on (``Values.proofs``), the tipi tolerated
  («Tollera tutte», ``verdict.judge``), the presets and rules applied, the
  tracking preset.
* **Panel**: every ``compare_case`` remembers, per case, what its TO-BE
  comparison found for each row (``filter_rows.found``: counts whatever the
  switches, occurrences with anchors and pages, the invisible text of both
  documents, each rule's hits over the target and the TO-BE — presets here,
  the user's rules in the guard's child process, R46). ``filters(ini, case)``
  lays it out with the choices in hand and the control generation's state
  (quick: no I/O but the control record; before any comparison every row
  has 0); ``CaseComparison.filters`` is the same panel with the ``diff_ids``
  of its ``judged``.
* **Saving** (``set_filters``, ``set_noise_rules``): merged with
  ``filter_model.apply_choices`` (junk → ``ValueError``, nothing saved), then
  stale ``avanzate.<name>`` keys pruned (rules no longer in scope) in the
  same save — the case's through ``_commit`` (review on disk, write lock),
  the initiative's through ``_save_initiative``; the objects in hand change
  only after the save.

Stdlib only; no Qt.
"""
from __future__ import annotations

import dataclasses
import os
import threading
from collections.abc import Iterable, Mapping, Sequence

from qtrequestory.officina.compare import noise, noise_guard
from qtrequestory.officina.compare.extract_pdf import DocText
from qtrequestory.officina.compare.filter_model import FilterPanel, advanced_filter_id, apply_choices, prune_choices
from qtrequestory.officina.compare.filter_rows import Found, Switches, found, panel, rule_rows, switches, with_ids
from qtrequestory.officina.compare.model import Comparison, Judged
from qtrequestory.officina.model import Case, Initiative, Version
from qtrequestory.officina.model_case import load_case
from qtrequestory.officina.model_io import read_json_object
from qtrequestory.officina.model_review import NoiseRule, Review, initiative_settings_from_json

__all__ = ["FiltersMixin"]


class FiltersMixin:
    """Needs ``_commit``, ``_save_initiative``, ``_guarded_hits`` (``ReviewMixin``)
    and ``control_state`` (``ControlMixin``); call :meth:`_init_filters`."""

    def _init_filters(self) -> None:
        self._found_lock = threading.Lock()
        self._found: dict[str, Found] = {}   # case folder -> what its last comparison found

    def _forget_found(self, ini: Initiative) -> None:
        """``ini`` was deleted: what its cases' comparisons found is dropped
        (a new case in the same folder starts from 0, final review I1)."""
        inside = os.path.join(str(ini.folder.resolve()).lower(), "")
        with self._found_lock:
            for key in [k for k in self._found if k.startswith(inside)]:
                del self._found[key]

    # ------------------------------------------------------------ contract ---

    def filters(self, ini: Initiative, case: Case) -> FilterPanel:
        with self._found_lock:
            rows = self._found.get(_key(case), {})
        rules = rule_rows(noise.PRESETS, ini.noise_rules, case.review.noise_rules)
        state = self.control_state(case)  # type: ignore[attr-defined]
        return panel(rows, rules, case.review.filters, ini.filters, state)

    def set_filters(self, ini: Initiative, case: Case | None, choices: Mapping[str, bool | None]) -> None:
        apply_choices({}, choices)  # refuse junk before anything is read or written
        if case is None:
            names = _names(ini.noise_rules, *(c.review.noise_rules for c in ini.cases))
            merged = prune_choices(apply_choices(ini.filters, choices), names)
            self._save_initiative(ini, filters=merged)  # type: ignore[attr-defined]
            return

        def change(review: Review) -> Review:
            names = _names(ini.noise_rules, review.noise_rules)
            return dataclasses.replace(review, filters=prune_choices(apply_choices(review.filters, choices), names))
        self._act("filtri", case, change)  # type: ignore[attr-defined]

    def set_noise_rules(self, ini: Initiative, case: Case | None, rules: list[NoiseRule],
                        presets: list[str] | None = None) -> None:
        """``presets`` (the 1.3.x noise page's checkboxes, legacy): the names
        of the presets turned ON as the initiative's default (``filtri``)."""
        noise_guard.refuse_duplicates(rules)
        _refuse_name_clashes(ini, case, rules)
        copies = [dataclasses.replace(r) for r in rules]
        if case is not None:
            def change(review: Review) -> Review:
                names = _names(ini.noise_rules, copies)
                return dataclasses.replace(review, noise_rules=copies, filters=prune_choices(review.filters, names))
            self._act("regole di rumore", case, change)  # type: ignore[attr-defined]
            return
        filters = prune_choices(ini.filters, _names(copies, *(c.review.noise_rules for c in ini.cases)))
        if presets is not None:
            filters = apply_choices(filters, {advanced_filter_id(p.name): p.name in presets for p in noise.PRESETS})
        self._save_initiative(ini, noise_rules=copies, filters=filters)  # type: ignore[attr-defined]

    # ------------------------------------------------------- compare_case ---

    @staticmethod
    def _view_settings(version: Version) -> tuple[Switches, list[NoiseRule], list[NoiseRule]] | None:
        """The switches of the case ``version`` belongs to and the
        initiative's and the case's own regex rules, read from disk
        (``compare``: the AS-IS view, which has no ``ini``/``case`` in hand);
        None outside a readable case."""
        from qtrequestory.officina.service_compare import _case_folder

        try:
            folder = _case_folder(version)
            case = load_case(folder)
            if case.load_error:
                return None
            _, ini_rules, ini_filters = initiative_settings_from_json(
                read_json_object(folder.parent.parent / "iniziativa.json"), [])
            rules = rule_rows(noise.PRESETS, ini_rules, case.review.noise_rules)
            return switches(case.review.filters, ini_filters, rules), list(ini_rules), list(case.review.noise_rules)
        except Exception:  # noqa: BLE001 - the defaults then, never an error
            return None

    @classmethod
    def _view_switches(cls, version: Version) -> Switches | None:
        """The switches alone of :meth:`_view_settings`."""
        settings = cls._view_settings(version)
        return settings[0] if settings is not None else None

    @staticmethod
    def _switches(ini: Initiative, review: Review) -> tuple[Switches, list[NoiseRule]]:
        """The case's switches (choices ON DISK for the case, in hand for the
        initiative) and the rules behind the ``avanzate.*`` rows."""
        rules = rule_rows(noise.PRESETS, ini.noise_rules, review.noise_rules)
        return switches(review.filters, ini.filters, rules), rules

    def _panel_of(self, ini: Initiative, case: Case, review: Review, rules: Sequence[NoiseRule],
                  tobe: Comparison, inputs: Sequence, judged: Sequence[Judged]) -> FilterPanel:
        """Remember what ``tobe`` found for ``case``'s rows and return the
        panel with the ``diff_ids`` of ``judged`` (``inputs``: the target's and
        the TO-BE's ``CaseInput``, for the invisible text and the rules' hits)."""
        invisible = [(label, item.doc.invisible) for label, item in zip(("target", "TO-BE"), inputs, strict=True)
                     if isinstance(item.doc, DocText)]
        rows = found(tobe.diffs, invisible, self._rule_hits(rules, inputs))
        with self._found_lock:
            self._found[_key(case)] = rows
        made = panel(rows, rules, review.filters, ini.filters, self.control_state(case))  # type: ignore[attr-defined]
        return with_ids(made, judged)

    def _rule_hits(self, rules: Sequence[NoiseRule], inputs: Sequence) -> dict[str, int]:
        """Each rule's hits over ``inputs``, on or off (F7): the presets here,
        the user's rules in the child (``_guarded_hits``); a rule that cannot
        be counted has 0."""
        from qtrequestory.officina.service_case import noise_side

        presets = {(p.name, p.pattern) for p in noise.PRESETS}
        trusted = [r for r in rules if (r.name, r.pattern) in presets]
        custom = [r for r in rules if (r.name, r.pattern) not in presets]
        hits: dict[str, int | str] = {}
        if trusted:
            hits.update(noise_guard.count_trusted([noise_side(i) for i in inputs], trusted))
        if custom:
            hits.update(self._guarded_hits(custom, inputs))  # type: ignore[attr-defined]
        return {name: n if isinstance(n, int) else 0 for name, n in hits.items()}


def _key(case: Case) -> str:
    return str(case.folder.resolve()).lower()


def _names(*levels: Iterable[NoiseRule]) -> list[str]:
    """The rule names in scope: the presets and ``levels``."""
    return [*(p.name for p in noise.PRESETS), *(r.name for level in levels for r in level)]


def _refuse_name_clashes(ini: Initiative, case: Case | None, rules: list[NoiseRule]) -> None:
    """Rule names are keys across levels too (the comparison applies the
    initiative's presets and rules and the case's together): a name of a
    preset (its current or former name), of an initiative rule (saving a
    case's) or of any case's rule (saving the initiative's) is refused with
    an Italian ``ValueError``."""
    from qtrequestory.officina.compare.filter_model import RENAMED_RULES

    taken = {p.name: "da un preset" for p in noise.PRESETS}
    taken.update({old: "da un preset" for old in RENAMED_RULES})
    if case is None:
        for other in ini.cases:
            for rule in other.review.noise_rules:
                taken.setdefault(rule.name, f"da una regola del caso {other.key}")
    else:
        for rule in ini.noise_rules:
            taken.setdefault(rule.name, "da una regola dell'iniziativa")
    for rule in rules:
        if rule.name in taken:
            raise ValueError(f"regola di rumore «{rule.name}»: nome già usato {taken[rule.name]}")
