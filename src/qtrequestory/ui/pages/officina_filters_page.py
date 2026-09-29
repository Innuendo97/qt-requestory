""""Filtri del confronto" from the page (a mixin of ``OfficinaPage``; phase 2.5, U4).

"Filtri (n)" on the case bar opens the dialog (``officina_filters``) of the
case on screen — one at a time, modeless, raised again if already open.
The panel comes from ``filters(ini, case)`` (quick, on the GUI thread); if
the service cannot give it (the real one before the engine lands raises
``NotImplementedError``) or fails, the dialog opens anyway with no rows, a
discreet note and "Regole avanzate" open and usable — never a crash.

A switch becomes a "filtri" request on the case's review queue
(``officina_review``, R38): saved with ``set_filters`` in the review worker,
then the version on screen is judged again and redrawn — the documents stay,
nothing is regenerated. Filter choices belong to the case, so their undo
works on any version, the AS-IS included. Switches made in a row share ONE
toast ("Filtri: 3 modifiche") whose "Annulla" undoes them all; Ctrl+Z undoes
one at a time. With "Usa per tutta l'iniziativa" a switch writes the
initiative's default and drops the case's own choice (ruling F15);
"Ripristina predefiniti" drops them all. After every redraw, compare or
reload of the case the dialog gets the new panel (:meth:`_sync_filters`);
leaving the case closes it (unsaved rules: Salva / Scarta).

**The control generation** (spec §3.4): while the case on screen has one
running, the page looks at its state every ``CONTROL_POLL_MS`` (Filtri
dialog open or not); when it becomes ``pronta`` the version on screen is
judged again (the review job with no step: nothing regenerated, the
documents stay), so the case view and «Cambiano fra due generazioni» use it
at once (final review M2). An email case has no control generation: its
line says so (``FILTRI_CONTROL_EMAIL``, M3).

"Regole avanzate" holds the regex editor of the case's own rules
(``officina_noise_editor``): "Salva le regole del caso" saves them with
``set_noise_rules`` (a small file write, on the GUI thread like the profile)
when nothing else writes the case, and compares again.
"""
from __future__ import annotations

import dataclasses
import logging
import time
from functools import partial

from PySide6.QtCore import QTimer

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import Case, ControlState, FilterPanel, Initiative, NoiseRule
from qtrequestory.ui.pages.officina_docside import version_key
from qtrequestory.ui.pages.officina_filters import CONTROL_POLL_MS, FiltersDialog
from qtrequestory.ui.pages.officina_format import case_title
from qtrequestory.ui.pages.officina_judge import act
from qtrequestory.ui.pages.officina_noise_editor import NoiseRulesEditor
from qtrequestory.ui.pages.officina_undo import Entry, Intent
from qtrequestory.ui.workers import OFFICINA_REVIEW_JOB

__all__ = ["FILTER_BURST_S", "FiltersMixin", "is_email_case"]

log = logging.getLogger(__name__)

#: Switches saved within this many seconds of the previous one share its toast.
FILTER_BURST_S = 5.0


def is_email_case(case: Case) -> bool:
    """Whether ``case`` is an email (HTML) case: its target's type, else its
    AS-IS's, else its latest TO-BE's (no document yet: not known, False)."""
    first = next((v for v in (case.target(), case.asis(), case.latest_tobe()) if v is not None), None)
    return first is not None and first.doc_type == "html"


def _email_state() -> ControlState:
    return ControlState("non_disponibile", strings.FILTRI_CONTROL_EMAIL)


class FiltersMixin:
    """``open_filters`` and what its dialog asks (needs the page's
    ``_counter`` / ``_case_busy`` from ``NoiseRulesMixin`` and ``_enqueue``
    / ``_undo_from_toast`` from ``ReviewActionsMixin``)."""

    #: The dialog class (a test may swap it).
    filters_dialog_class = FiltersDialog
    #: The dialog on screen, or None.
    filters_dialog: FiltersDialog | None = None
    #: (case key, entries, when) of the last burst of switches (one toast).
    _filter_burst: tuple[tuple[str, str], list[Entry], float] | None = None
    #: Polls the control generation of the case on screen while it runs (M2).
    control_watch: QTimer | None = None
    #: (initiative id, case id) whose control is being watched.
    _watched: tuple[str, str] | None = None

    def _connect_filters(self) -> None:
        self.case_view.filters_requested.connect(self.open_filters)

    # -- the service, never raising --------------------------------------------------

    def _filter_panel(self, ini: Initiative, case: Case) -> FilterPanel:
        try:
            panel = self.api.filters(ini, case)
            return dataclasses.replace(panel, controllo=_email_state()) if is_email_case(case) else panel
        except NotImplementedError:
            pass
        except Exception:  # noqa: BLE001 - a panel that cannot be computed is a note, never a crash
            log.exception("filtri del confronto non calcolati per %s", case.key)
        return FilterPanel((), ControlState("non_disponibile"), strings.FILTRI_UNAVAILABLE)

    def _control_state(self, case: Case) -> ControlState:
        if is_email_case(case):
            return _email_state()  # never "parte da solo...": an email has no control generation (M3)
        try:
            return self.api.control_state(case)
        except Exception:  # noqa: BLE001 - D14: never an error for the control generation
            return ControlState("non_disponibile")

    # -- the dialog ------------------------------------------------------------------

    def open_filters(self) -> None:
        case, ini = self._case(self.case_id), self.ini
        if case is None or ini is None:
            return
        dialog = self.filters_dialog
        if dialog is not None and dialog.case_id == case.id:
            self._show_filter_panel(dialog, ini, case)
            dialog.raise_()
            dialog.activateWindow()
            return
        self._close_filters()
        reserved = {r.name: strings.RUMORE_WHERE_CASE.format(case=case_title(c))
                    for c in ini.cases if c.id != case.id for r in c.review.noise_rules}
        editor = NoiseRulesEditor(
            list(case.review.noise_rules), own_title=strings.RUMORE_OWN_CASE, presets=self.api.noise_presets(),
            inherited=list(ini.noise_rules), reserved=reserved, counter=self._counter(case),
            counts_note=strings.RUMORE_COUNTS_ON.format(case=case_title(case)))
        panel = self._filter_panel(ini, case)
        dialog = self.filters_dialog_class(
            strings.FILTRI_TITLE.format(case=case_title(case)), panel, case.id,
            editor=editor, control_source=partial(self._control_state, case), parent=self)
        dialog.choices_requested.connect(self._on_filter_choices)
        dialog.occurrence_chosen.connect(self.case_view.show_occurrence)
        dialog.rules_save_requested.connect(partial(self._on_filter_rules, case.id))
        dialog.reset_requested.connect(self._on_filter_reset)
        dialog.finished.connect(lambda _r=0, d=dialog: self._forget_filters(d))
        dialog.set_own_choices(len(case.review.filters))
        if not panel.groups:  # nothing computed: the rules are what the dialog can offer
            dialog.set_advanced(True)
        self.filters_dialog = dialog
        dialog.show()

    # -- what the dialog asks ------------------------------------------------------

    def _on_filter_choices(self, choices: dict, initiative: bool, text: str) -> None:
        if self.ini is None or self._case(self.case_id) is None or self.view() != "case":
            return
        self._enqueue(Intent("filtri", what=text, choices=dict(choices), initiative=initiative))

    def _on_filter_reset(self) -> None:
        if self.ini is not None and self._case(self.case_id) is not None and self.view() == "case":
            self._enqueue(Intent("filtri_reset", what=strings.FILTRI_RESET_DONE))

    def _filter_toast(self, where: tuple[str, str], entry: Entry) -> tuple[str, tuple]:
        """The toast of a saved switch: switches made in a row share one,
        whose "Annulla" undoes them all (Ctrl+Z still goes one at a time)."""
        now = time.monotonic()
        burst = self._filter_burst
        entries = [entry]
        if burst is not None and burst[0] == where and now - burst[2] < FILTER_BURST_S:
            entries = [*burst[1], entry]
        self._filter_burst = (where, entries, now)
        text = entry.text if len(entries) == 1 else strings.FILTRI_CHANGED_MANY.format(n=len(entries))
        return text, (strings.AZIONI_UNDO, partial(self._undo_filter_burst, where, tuple(entries)))

    def _undo_filter_burst(self, where: tuple[str, str], entries: tuple[Entry, ...]) -> None:
        self._filter_burst = None
        for entry in reversed(entries):  # the last switch first, like Ctrl+Z
            self._undo_from_toast(where, entry)

    def _on_filter_rules(self, case_id: str, rules: list[NoiseRule]) -> None:
        case, ini = self._case(case_id), self.ini
        if case is None or ini is None or self._case_busy():
            return
        try:
            self.api.set_noise_rules(ini, case, rules)
        except (OSError, ValueError) as exc:
            self._notify(strings.RUMORE_FAILED.format(reason=exc))
            return
        dialog = self.filters_dialog
        if dialog is not None and dialog.case_id == case_id and dialog.editor is not None:
            dialog.editor.mark_saved()
        self._toast(strings.RUMORE_SAVED, "ok")
        if self._reload_initiative() and self.view() == "case" and self.case_id == case_id:
            self.open_case(case_id)  # the same version, compared again; the dialog follows

    # -- keeping it in step ------------------------------------------------------------

    def _show_filter_panel(self, dialog: FiltersDialog, ini: Initiative, case: Case) -> None:
        dialog.show_panel(self._filter_panel(ini, case))
        dialog.set_own_choices(len(case.review.filters))

    def _sync_filters(self) -> None:
        """The case on screen changed (a redraw, a compare, a reload): the
        dialog shows its panel now, or closes when its case left the screen;
        a control generation running for it is watched."""
        self._watch_control()
        dialog = self.filters_dialog
        if dialog is None:
            return
        case = self._case(self.case_id) if self.view() == "case" else None
        if case is None or case.id != dialog.case_id or self.ini is None:
            self._close_filters()
            return
        self._show_filter_panel(dialog, self.ini, case)

    def _close_filters(self) -> None:
        """Leaving the case: unsaved rules are saved or dropped (asked), then it closes."""
        dialog = self.filters_dialog
        if dialog is not None:
            self.filters_dialog = None
            dialog.leave()
            dialog.deleteLater()

    def _forget_filters(self, dialog: FiltersDialog) -> None:
        if self.filters_dialog is dialog:
            self.filters_dialog = None
            dialog.deleteLater()

    # -- the control generation becoming ready (M2) ------------------------------------

    def _watch_control(self) -> None:
        """Watch the case on screen while its control generation runs."""
        case = self._case(self.case_id) if self.view() == "case" and self.ini is not None else None
        if case is None or self._control_state(case).stato != "in_corso":
            self._stop_watch()
            return
        if self.control_watch is None:
            self.control_watch = QTimer(self, interval=CONTROL_POLL_MS)
            self.control_watch.timeout.connect(self._control_tick)
        self._watched = (self.ini.id, case.id)
        self.control_watch.start()

    def _stop_watch(self) -> None:
        self._watched = None
        if self.control_watch is not None:
            self.control_watch.stop()

    def _control_tick(self) -> None:
        """One look: still running -> wait; ready -> judge the version on
        screen again (once the case is free); anything else -> stop."""
        here = (self.ini.id, self.case_id) if self.ini is not None and self.view() == "case" else None
        case = self._case(self.case_id) if here is not None else None
        if case is None or here != self._watched:
            self._stop_watch()
            return
        state = self._control_state(case)
        if state.stato == "in_corso":
            return
        if state.stato == "pronta":
            if self.case_view.judging or self.case_view.acting:
                return  # a compare or an action runs: look again at the next tick
            self._stop_watch()
            self._rejudge_for_control(here, case)
            return
        self._stop_watch()
        self._sync_filters()  # the dialog's line says why (non disponibile)

    def _rejudge_for_control(self, where: tuple[str, str], case: Case) -> None:
        """The review job with no step: ``compare_case`` of the version on
        screen again (an AS-IS: the case reloads), redrawn in place."""
        docs = self.case_view.docs
        version = docs.right.version if docs is not None else None
        key = version_key(version) if version is not None else None
        job = self.runner.submit(OFFICINA_REVIEW_JOB, act, self.services, self.ini, case,
                                 version if version is not None and version.kind == "tobe" else None, [])
        if job is None:
            return
        self.case_view.set_acting(True)
        job.signals.result.connect(partial(self._refresh_reviewed, where, key))
        job.signals.error.connect(lambda *_a: self._refresh_reviewed(where, None, None))
        job.signals.finished.connect(self._on_review_finished)
