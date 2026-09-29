"""The noise rules and the DOM tab, from the page (a mixin of ``OfficinaPage``).

"Regole di rumore…" on the board edits the initiative's own regex rules —
names and patterns only (ruling F14: presets and every switch, including
the initiative's defaults, are set from "Filtri del confronto") — with
counts on the selected case, if any. OK saves with ``set_noise_rules`` (on
the UI thread, like the profile: a small file write). Rule names are unique
across the initiative AND every case (the engine refuses a clash): the
dialog knows the names in use elsewhere and says where on the row. The
case's own rules are edited in "Filtri del confronto" → "Regole avanzate"
(phase 2.5, U4: ``officina_filters_page``), with the helpers here
(``_counter``, ``_case_busy``).

The DOM tab asks for its two sources (``dom_view``) in the ``officina-dom``
worker; the dialog's live counts run in ``officina-noise``.
"""
from __future__ import annotations

from functools import partial

from PySide6.QtWidgets import QDialog

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import Case, CoreServices, NoiseRule, Version
from qtrequestory.ui.pages.officina_format import case_title
from qtrequestory.ui.pages.officina_noise import NoiseDialog
from qtrequestory.ui.workers import OFFICINA_DOM_JOB, OFFICINA_NOISE_JOB

__all__ = ["DOM_JOB", "NOISE_JOB", "NoiseRulesMixin", "count_hits", "dom_sources"]

NOISE_JOB = OFFICINA_NOISE_JOB
DOM_JOB = OFFICINA_DOM_JOB


def count_hits(services: CoreServices, case: Case, rules: list[NoiseRule]) -> dict[str, int | str]:
    """Worker call: ``count_noise_hits`` (a user rule may take ~2 s: R22)."""
    return services.officina.count_noise_hits(case, rules)


def dom_sources(services: CoreServices, case: Case, version: Version) -> tuple[str, str]:
    """Worker call: the two pretty sources of the DOM tab."""
    return services.officina.dom_view(case, version)


class NoiseRulesMixin:
    """``edit_initiative_noise`` and the DOM sources."""

    #: The dialog class (a test swaps in one that answers by itself).
    noise_dialog = NoiseDialog

    def _connect_noise(self) -> None:
        self.board.noise_rules_requested.connect(self.edit_initiative_noise)
        self.case_view.dom_requested.connect(self._load_dom)

    def _counter(self, case: Case | None):
        if case is None:
            return None
        return lambda rules: self.runner.submit(NOISE_JOB, count_hits, self.services, case, rules)

    @staticmethod
    def _answer(dialog) -> tuple[list[NoiseRule], list[str]] | None:
        """The rules when the user saved, else None; the dialog is deleted
        either way (its timers and theme connection go with it)."""
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return None
            return dialog.rules()
        finally:
            dialog.deleteLater()

    def _generating(self) -> bool:
        """Generations are running: their summaries would come back computed
        with the old rules, so the initiative's rules wait."""
        if self.queue.is_busy():
            self._notify(strings.RUMORE_WAIT_GENERATION)
            return True
        return False

    def _case_busy(self) -> bool:
        """A compare of the case on screen runs, an action is being saved, or
        actions wait in its queue (R38): the rules wait (with a status line)."""
        queued = self.review_queue.get((self.ini.id, self.case_id)) if self.ini is not None else None
        if self.case_view.judging or self.case_view.acting or queued:
            self._notify(strings.REVISIONE_WAIT_COMPARE)
            return True
        return False

    def edit_initiative_noise(self) -> None:
        ini = self.ini
        if ini is None or self._generating():
            return
        selected = self.board.selected_case_ids()
        case = self._case(selected[0]) if selected else None
        reserved = {r.name: strings.RUMORE_WHERE_CASE.format(case=case_title(c))
                    for c in ini.cases for r in c.review.noise_rules}
        dialog = self.noise_dialog(
            strings.RUMORE_TITLE_INITIATIVE.format(name=ini.name), list(ini.noise_rules),
            own_title=strings.RUMORE_OWN_INITIATIVE, presets=self.api.noise_presets(),
            reserved=reserved, counter=self._counter(case),
            counts_note=(strings.RUMORE_COUNTS_ON.format(case=case_title(case)) if case is not None
                         else strings.RUMORE_COUNTS_NONE), parent=self)
        rules = self._answer(dialog)
        if rules is None or self._generating():
            return
        try:  # the rules only: presets and switches are the Filtri's (F14)
            self.api.set_noise_rules(ini, None, rules)
        except (OSError, ValueError) as exc:
            self._notify(strings.RUMORE_FAILED.format(reason=exc))
            return
        self._toast(strings.RUMORE_SAVED_INITIATIVE, "ok")
        if self._reload_initiative():  # the board re-reads the saved summaries (U5)
            self.show_board()

    # -- the DOM tab ------------------------------------------------------------------

    def _load_dom(self, key: object, case: Case, version: Version) -> None:
        job = self.runner.submit(DOM_JOB, dom_sources, self.services, case, version)
        if job is not None:
            job.signals.result.connect(partial(self._on_dom, key))
            job.signals.error.connect(partial(self._on_dom_failed, key))

    def _on_dom(self, key: object, sources: tuple[str, str]) -> None:
        self.case_view.show_dom(key, *sources)

    def _on_dom_failed(self, key: object, _kind: str, message: str) -> None:
        self.case_view.dom_failed(key, strings.DOM_FAILED.format(reason=message))
