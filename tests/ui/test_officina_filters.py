"""Officina phase 2.5 (U4): "Filtri del confronto" (spec §3.8, D3, D4, D9, D14;
rulings F3, F4, F5, F7).

The dialog alone on panels built by the fake (sections with counts, the
switches and what they mean, expandable occurrences, "Regole avanzate" with
the regex editor, the control generation's discreet line), then from the
page on the fake core: "Filtri (n)" opens it modeless, a switch is saved and
the version on screen judged again (no generation), undoable; an occurrence
shows its difference; the case's own rules are saved from "Regole avanzate".
"""
from __future__ import annotations

from collections import deque

from PySide6.QtWidgets import QMessageBox

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import ControlState, NoiseRule
from qtrequestory.ui.pages.officina_filters import FiltersDialog, control_text
from qtrequestory.ui.pages.officina_filters_rows import MAX_OCCURRENCES, occurrence_text
from qtrequestory.ui.pages.officina_noise_editor import NoiseRulesEditor
from qtrequestory.ui.pages.officina_undo import Intent
from tests.fakes.fake_core import fake_diff
from tests.fakes.fake_filters import fake_group, fake_occurrence
from tests.ui.test_officina_page import open_case, page, shell, wait_idle  # noqa: F401 - fixtures
from tests.ui.test_officina_progress import _open_version, placed

FOOTER = fake_diff("cambiato", "testo", "Acme-Servizi S.p.A.", "Acme-Servizi SpA", zone="footer")
CAPS = fake_diff("cambiato", "testo", "Offerta", "OFFERTA", tipo="maiuscole")


def _groups(*, many: int = 0):
    return [
        fake_group("zona.footer", n=2, occorrenze=[
            fake_occurrence("Acme-Servizi S.p.A.", pagine=(0, 1), anchors=(FOOTER.anchor,), zona="footer")]),
        fake_group("zona.numero_pagina", n=2),
        fake_group("zona.invisibile", n=3, occorrenze=[fake_occurrence("MOD_TEST_CODICE")]),
        fake_group("variabile.buco", n=1, occorrenze=[
            fake_occurrence("12/05/2026", pagine=(0,), dettaglio="dataFirma")]),
        fake_group("decidere.maiuscole", n=max(1, many), occorrenze=[
            fake_occurrence(f"OFFERTA {i}", anchors=(CAPS.anchor,)) for i in range(max(1, many))]),
        fake_group("decidere.punteggiatura", n=0),
        fake_group("avanzate.Data", n=4),
    ]


def _panel(fake_core, tmp_path, page, **kw):
    case = open_case(page, fake_core, tmp_path)
    fake_core.officina.set_filter_groups(case.id, _groups(**kw))
    return case, fake_core.officina.filters(page.ini, case)


def _dialog(qtbot, panel, *, editor=None, control=None) -> FiltersDialog:
    d = FiltersDialog("Filtri", panel, "case", editor=editor, control_source=control)
    qtbot.addWidget(d)
    d.show()
    return d


# ------------------------------------------------------------ the dialog ---

def test_three_sections_with_real_counts_and_the_advanced_rules_folded(qtbot, page, fake_core, tmp_path):
    _case, panel = _panel(fake_core, tmp_path, page)
    d = _dialog(qtbot, panel)
    assert d.section_title("zone") == strings.FILTRI_SECTION_ZONE.format(n=2), \
        "M5: only the zone differences that count (the footer), as the side panel"
    assert d.section_title("variabili") == strings.FILTRI_SECTION_VARIABILI.format(n=1)
    assert d.section_title("decidere") == strings.FILTRI_SECTION_DECIDERE.format(n=1)
    assert not d.advanced_open() and d.advanced_button.text() == strings.FILTRI_ADVANCED_SHOW.format(n=4)
    d.advanced_button.click()
    assert d.advanced_open() and d.row("avanzate.Data").isVisibleTo(d)
    d.resize(700, 300)
    d.set_advanced(False)
    d.set_advanced(True)
    bar = d.scroll.verticalScrollBar()
    qtbot.waitUntil(lambda: bar.value() == min(bar.maximum(), d.advanced_button.y()) > 0, timeout=2000)
    assert d.section_title("avanzate") == strings.FILTRI_ADVANCED_HIDE.format(n=4)
    assert not d.isModal(), "live: the case view behind stays usable"


def test_the_switches_read_as_their_section_says(qtbot, page, fake_core, tmp_path):
    _case, panel = _panel(fake_core, tmp_path, page)
    d = _dialog(qtbot, panel)
    footer, pages_n = d.row("zona.footer"), d.row("zona.numero_pagina")
    assert footer.switch.text() == strings.FILTRI_SWITCH_ZONE and footer.switch.isChecked(), "a zone counts (D4)"
    assert not pages_n.switch.isChecked(), "page number and watermark do not count by default (F3)"
    assert d.row("variabile.buco").switch.text() == strings.FILTRI_SWITCH_VARIABILI
    assert d.row("variabile.buco").switch.isChecked()
    caps = d.row("decidere.maiuscole")
    assert caps.switch.text() == strings.FILTRI_SWITCH_DECIDERE == "Tollera tutte"
    assert not caps.switch.isChecked(), "case-only differences count (D9) until «Tollera tutte»"
    assert d.row("avanzate.Data").switch.text() == strings.FILTRI_SWITCH_AVANZATE
    tollera = [fid for fid, row in d.rows.items() if row.switch.text() == strings.FILTRI_SWITCH_DECIDERE]
    assert tollera == ["decidere.maiuscole", "decidere.punteggiatura"], "«Tollera tutte» only there"


def test_invisible_text_is_informational_and_empty_rows_are_dimmed(qtbot, page, fake_core, tmp_path):
    _case, panel = _panel(fake_core, tmp_path, page)
    d = _dialog(qtbot, panel)
    invisible = d.row("zona.invisibile")
    assert not invisible.switch.isVisibleTo(d) and invisible.informative.isVisibleTo(d)
    assert invisible.count.text() == "3", "F7: shown with its count, no switch"
    empty = d.row("decidere.punteggiatura")
    assert empty.title.property("role") == "muted" and empty.count.text() == "0"
    assert not empty.expander.isEnabled(), "nothing to expand"
    assert d.row("zona.footer").title.property("role") != "muted"


def test_a_switch_asks_for_that_choice_and_says_what_it_does(qtbot, page, fake_core, tmp_path):
    _case, panel = _panel(fake_core, tmp_path, page)
    d = _dialog(qtbot, panel)
    with qtbot.waitSignal(d.choices_requested) as asked:
        d.row("zona.footer").switch.click()   # unchecked: the footer stops counting
    assert asked.args == [{"zona.footer": True}, False, strings.FILTRI_CHANGED.format(
        name="Footer", state=strings.FILTRI_STATE_ZONE_ON)]
    d.scope.setChecked(True)
    with qtbot.waitSignal(d.choices_requested) as asked:
        d.row("decidere.maiuscole").switch.click()  # «Tollera tutte»
    assert asked.args[:2] == [{"decidere.maiuscole": True}, True]
    assert asked.args[2] == strings.FILTRI_CHANGED_INITIATIVE.format(
        name="Solo maiuscole", state=strings.FILTRI_STATE_DECIDERE_ON)


def test_a_row_expands_into_its_occurrences_and_a_click_asks_to_show_one(qtbot, page, fake_core, tmp_path):
    _case, panel = _panel(fake_core, tmp_path, page)
    d = _dialog(qtbot, panel)
    footer = d.row("zona.footer")
    assert not footer.is_expanded()
    footer.expander.click()
    assert footer.is_expanded() and footer.expander.text() == "▾"
    [button] = footer.occurrence_buttons()
    assert button.text() == "p. 1, 2 · Acme-Servizi S.p.A."
    with qtbot.waitSignal(d.occurrence_chosen) as chosen:
        button.click()
    assert chosen.args == [(FOOTER.anchor,), (0, 1)]
    d.row("zona.invisibile").expander.click()
    [hidden] = d.row("zona.invisibile").occurrence_buttons()
    assert not hidden.isEnabled() and hidden.toolTip() == strings.FILTRI_OCCURRENCE_NO_DIFF
    variable = d.row("variabile.buco").group.occorrenze[0]
    assert occurrence_text(variable) == "p. 1 · 12/05/2026 · dataFirma"


def test_long_lists_are_cut_and_a_new_panel_keeps_what_is_expanded(qtbot, page, fake_core, tmp_path):
    case, panel = _panel(fake_core, tmp_path, page, many=MAX_OCCURRENCES + 5)
    d = _dialog(qtbot, panel)
    caps = d.row("decidere.maiuscole")
    caps.expander.click()
    assert len(caps.occurrence_buttons()) == MAX_OCCURRENCES
    assert caps.findChildren(type(caps.title))[-1].text() == strings.FILTRI_MORE_OCCURRENCES.format(n=5)
    fake_core.officina.set_filters(page.ini, case, {"decidere.maiuscole": True})
    d.show_panel(fake_core.officina.filters(page.ini, case))
    assert d.row("decidere.maiuscole") is caps and caps.is_expanded() and caps.switch.isChecked()


def test_the_control_generation_is_a_discreet_line_polled_while_it_runs(qtbot, page, fake_core, tmp_path):
    case, _panel_ = _panel(fake_core, tmp_path, page)
    api = fake_core.officina
    api.set_control_state(case.id, ControlState("in_corso"))
    d = _dialog(qtbot, api.filters(page.ini, case), control=lambda: api.control_state(case))
    assert d.control.text() == strings.FILTRI_CONTROL_IN_CORSO and d.poll.isActive()
    d.poll.setInterval(20)
    api.set_control_state(case.id, ControlState("non_disponibile", "riconoscimento esteso non disponibile "
                                                                   "per questo caso"))
    qtbot.waitUntil(lambda: not d.poll.isActive(), timeout=2000)
    assert d.control.text() == "Riconoscimento esteso non disponibile per questo caso", "a note, not an error (D14)"
    assert d.control.property("role") == "muted" and not d.findChildren(QMessageBox)
    assert control_text(ControlState("pronta")) == strings.FILTRI_CONTROL_PRONTA
    assert control_text(ControlState("assente")) == strings.FILTRI_CONTROL_ASSENTE
    assert control_text(ControlState("non_disponibile")) == strings.FILTRI_CONTROL_NON_DISPONIBILE


def test_advanced_rules_hold_the_regex_editor_of_the_case(qtbot, page, fake_core, tmp_path):
    _case, panel = _panel(fake_core, tmp_path, page)
    editor = NoiseRulesEditor([NoiseRule("Pratica", r"PR-\d{6}")], own_title=strings.RUMORE_OWN_CASE,
                              presets=fake_core.officina.noise_presets())
    d = _dialog(qtbot, panel, editor=editor)
    d.set_advanced(True)
    assert editor.isVisibleTo(d)
    assert not editor.own.item(0, 0).flags() & editor.own.item(0, 0).flags().ItemIsUserCheckable, \
        "the on/off of a rule is the panel's switch (F4)"
    bad = editor.add_rule("Rotta", "(a+")
    assert not d.save_rules_button.isEnabled()
    editor.set_pattern(bad, "a+")
    with qtbot.waitSignal(d.rules_save_requested) as saved:
        d.save_rules_button.click()
    assert saved.args[0] == [NoiseRule("Pratica", r"PR-\d{6}"), NoiseRule("Rotta", "a+")]


# ----------------------------------------------------------- from the page ---

def _judged(qtbot, page, fake_core, tmp_path):
    case = open_case(page, fake_core, tmp_path)
    page.case_view.regenerate_button.click()
    wait_idle(qtbot, page)
    api = fake_core.officina
    api.set_canned(case.id, 1, [placed(FOOTER, 100), placed(CAPS, 200)])
    api.set_filter_groups(case.id, _groups())
    _open_version(qtbot, page, "v1", len(api.compare_case_calls), api)
    return page._case(case.id)


def test_filtri_opens_one_modeless_dialog_and_the_menu_has_no_old_rules(qtbot, page, fake_core, tmp_path):
    _judged(qtbot, page, fake_core, tmp_path)
    view = page.case_view
    view.filters_button.click()
    first = page.filters_dialog
    assert first is not None and first.isVisible() and not first.isModal()
    assert first.windowTitle().startswith(strings.FILTRI_TITLE.format(case="")[:10])
    view.filters_button.click()
    assert page.filters_dialog is first, "one at a time: raised again"
    texts = [a.text() for a in view.more_button.menu().actions()]
    assert strings.RUMORE_BUTTON not in texts
    page.show_board()
    assert page.filters_dialog is None and not first.isVisible(), "leaving the case closes it"


def test_a_switch_is_saved_and_the_version_judged_again_without_generating(qtbot, page, fake_core, tmp_path):
    case = _judged(qtbot, page, fake_core, tmp_path)
    api = fake_core.officina
    page.open_filters()
    d = page.filters_dialog
    latest, compares = page._case(case.id).latest_tobe().number, len(api.compare_case_calls)
    d.row("zona.footer").switch.click()
    qtbot.waitUntil(lambda: len(api.compare_case_calls) > compares and not page.case_view.acting, timeout=10000)
    assert ("set_filters", case.id) in api.review_actions
    assert page._case(case.id).review.filters == {"zona.footer": True}
    assert api.load(page.ini.id).cases[0].latest_tobe().number == latest, "re-filtered, not regenerated"
    assert page.case_view.docs is not None, "the documents stayed"
    qtbot.waitUntil(lambda: not d.row("zona.footer").switch.isChecked(), timeout=2000)
    assert d.row("zona.footer").group.attivo, "the dialog shows the saved switch"
    text = strings.FILTRI_CHANGED.format(name="Footer", state=strings.FILTRI_STATE_ZONE_ON)
    assert any(t == text for t, _tone, _action in page._window.actions), "a toast with «Annulla»"
    page.undo_review()
    qtbot.waitUntil(lambda: page._case(case.id).review.filters == {}, timeout=10000)
    qtbot.waitUntil(lambda: d.row("zona.footer").switch.isChecked(), timeout=2000)


def test_for_the_whole_initiative_the_choice_becomes_its_default(qtbot, page, fake_core, tmp_path):
    case = _judged(qtbot, page, fake_core, tmp_path)
    api = fake_core.officina
    page.open_filters()
    d = page.filters_dialog
    d.scope.setChecked(True)
    d.row("zona.numero_pagina").switch.click()   # checked: the page number counts
    qtbot.waitUntil(lambda: ("set_filters", case.id) in api.review_actions and not page.case_view.acting,
                    timeout=10000)
    assert api.load(page.ini.id).filters == {"zona.numero_pagina": False}
    assert page._case(case.id).review.filters == {}, "F15: the case follows the default"
    qtbot.waitUntil(lambda: page.filters_dialog.row("zona.numero_pagina").switch.isChecked(), timeout=5000)


def test_a_switch_waits_for_the_compare_or_an_action_running(qtbot, page, fake_core, tmp_path):
    case = _judged(qtbot, page, fake_core, tmp_path)
    api = fake_core.officina
    page.open_filters()
    page.review_queue[(page.ini.id, case.id)] = deque()
    page.case_view.judging = True
    page.filters_dialog.row("zona.footer").switch.click()
    assert ("set_filters", case.id) not in api.review_actions, "queued behind the compare (R38)"
    page.case_view.set_judging(False)
    page._pump_review()
    qtbot.waitUntil(lambda: ("set_filters", case.id) in api.review_actions, timeout=10000)


def test_an_occurrence_selects_its_difference_in_the_case_view(qtbot, page, fake_core, tmp_path):
    _judged(qtbot, page, fake_core, tmp_path)
    page.open_filters()
    d = page.filters_dialog
    d.row("zona.footer").expander.click()
    d.row("zona.footer").occurrence_buttons()[0].click()
    view = page.case_view
    selected = next(j for j in view.docs.judged.judged if j.diff.id == view.diffs.current_id())
    assert selected.diff.anchor == FOOTER.anchor, "F5: selected and ringed by anchor"
    assert view.show_occurrence((), (0,)), "no difference: the target at that page"


def test_the_case_rules_are_saved_from_the_advanced_rules(qtbot, page, fake_core, tmp_path):
    case = _judged(qtbot, page, fake_core, tmp_path)
    api = fake_core.officina
    page.open_filters()
    d = page.filters_dialog
    d.set_advanced(True)
    api.set_filter_groups(case.id, None)  # the default rows: one per preset and rule
    d.editor.add_rule("Pratica", r"PR-\d{6}")
    compares = len(api.compare_case_calls)
    d.save_rules_button.click()
    assert ("set_noise_rules", case.id) in api.review_actions
    assert (strings.RUMORE_SAVED, "ok") in page._window.toasts
    qtbot.waitUntil(lambda: len(api.compare_case_calls) > compares, timeout=10000)
    reloaded = api.load(page.ini.id)
    assert next(c for c in reloaded.cases if c.id == case.id).review.noise_rules == [
        NoiseRule("Pratica", r"PR-\d{6}")]
    assert page.filters_dialog is d and d.row("avanzate.Pratica") is not None, "a row of its own now"


def test_a_refused_rules_save_says_so_and_saving_waits_for_queued_actions(qtbot, page, fake_core, tmp_path,
                                                                          monkeypatch):
    case = _judged(qtbot, page, fake_core, tmp_path)
    api = fake_core.officina
    page.open_filters()
    d = page.filters_dialog
    d.editor.add_rule("Pratica", "PR")

    def refuse(ini, where, rules, presets=None):
        raise ValueError("caso.json illeggibile")

    monkeypatch.setattr(api, "set_noise_rules", refuse)
    d.save_rules_button.click()
    assert strings.RUMORE_FAILED.format(reason="caso.json illeggibile") in page._window.statuses
    monkeypatch.undo()
    page.review_queue[(page.ini.id, case.id)] = deque([Intent("unmark_all")])
    d.save_rules_button.click()
    assert strings.REVISIONE_WAIT_COMPARE in page._window.statuses
    assert ("set_noise_rules", case.id) not in api.review_actions


# ------------------------------------------------------------ fix round 1 ---

def test_a_panel_the_service_cannot_give_opens_empty_with_a_note(qtbot, page, fake_core, tmp_path, monkeypatch):
    """I1: a service that cannot give the panel (NotImplementedError, or a
    failure): the dialog opens with no rows, a discreet note, "Regole avanzate"
    open, and the control reads "non disponibile"."""

    def not_implemented(*_a):
        raise NotImplementedError

    case = _judged(qtbot, page, fake_core, tmp_path)
    api = fake_core.officina
    monkeypatch.setattr(api, "filters", not_implemented)
    monkeypatch.setattr(api, "control_state", not_implemented)
    page.case_view.filters_button.click()
    d = page.filters_dialog
    assert d is not None and d.isVisible() and not d.rows
    assert d.panel_note.text() == strings.FILTRI_UNAVAILABLE and d.advanced_open()
    assert d.control.text() == strings.FILTRI_CONTROL_NON_DISPONIBILE
    page._sync_filters()  # after a redraw: no crash either
    d.editor.add_rule("Pratica", "PR")
    d.save_rules_button.click()
    assert ("set_noise_rules", case.id) in api.review_actions, "the case's rules can still be edited"

    def broken(*_a):
        raise OSError("disco pieno")

    monkeypatch.setattr(api, "filters", broken)
    page._sync_filters()
    assert page.filters_dialog is d and d.panel_note.text() == strings.FILTRI_UNAVAILABLE


def test_filter_undo_works_on_the_asis_too(qtbot, page, fake_core, tmp_path):
    """M1: filter choices belong to the case, not to a version."""
    case = open_case(page, fake_core, tmp_path)
    api = fake_core.officina
    api.generate(page.ini, case, "asis")
    api.set_filter_groups(case.id, _groups())
    page.refresh()
    page.open_case(case.id, "asis")
    qtbot.waitUntil(lambda: page.case_view.docs is not None and not page.case_view.judging, timeout=10000)
    page.open_filters()
    page.filters_dialog.row("zona.footer").switch.click()
    qtbot.waitUntil(lambda: page._case(case.id).review.filters == {"zona.footer": True}
                    and not page.case_view.acting and not page.case_view.judging, timeout=10000)
    _text, _tone, (_label, undo) = page._window.actions[-1]
    undo()
    qtbot.waitUntil(lambda: page._case(case.id).review.filters == {}, timeout=10000)
    qtbot.waitUntil(lambda: not page.case_view.acting and not page.case_view.judging, timeout=10000)
    page.filters_dialog.row("zona.footer").switch.click()
    qtbot.waitUntil(lambda: page._case(case.id).review.filters == {"zona.footer": True}
                    and not page.case_view.acting and not page.case_view.judging, timeout=10000)
    page.undo_review()   # Ctrl+Z on the AS-IS
    qtbot.waitUntil(lambda: page._case(case.id).review.filters == {}, timeout=10000)


def test_a_burst_of_switches_shares_one_toast_whose_annulla_undoes_them_all(qtbot, page, fake_core, tmp_path):
    """M2: one toast for switches made in a row; Ctrl+Z still goes one by one."""
    case = _judged(qtbot, page, fake_core, tmp_path)
    page.open_filters()
    d = page.filters_dialog

    def settled():
        return not page.case_view.acting and not page.case_view.judging and not page.review_queue.get(
            (page.ini.id, case.id))

    d.row("zona.footer").switch.click()
    d.row("decidere.maiuscole").switch.click()
    qtbot.waitUntil(lambda: len(page._case(case.id).review.filters) == 2 and settled(), timeout=10000)
    text, _tone, (_label, undo) = page._window.actions[-1]
    assert text == strings.FILTRI_CHANGED_MANY.format(n=2)
    undo()
    qtbot.waitUntil(lambda: page._case(case.id).review.filters == {} and settled(), timeout=10000)
    d = page.filters_dialog
    d.row("zona.footer").switch.click()
    d.row("decidere.maiuscole").switch.click()
    qtbot.waitUntil(lambda: len(page._case(case.id).review.filters) == 2 and settled(), timeout=10000)
    page.undo_review()
    qtbot.waitUntil(lambda: page._case(case.id).review.filters == {"zona.footer": True} and settled(),
                    timeout=10000)


def test_for_the_initiative_the_case_follows_the_default_and_can_be_reset(qtbot, page, fake_core, tmp_path,
                                                                          monkeypatch):
    """M3 (F15): with the scope on, the default is written and the case's own
    choice for that row dropped; "Ripristina predefiniti" drops them all (undoable)."""
    from qtrequestory.ui.pages import officina_filters_page

    monkeypatch.setattr(officina_filters_page, "FILTER_BURST_S", 0.0)  # one toast each, to read them
    case = _judged(qtbot, page, fake_core, tmp_path)
    api = fake_core.officina
    page.open_filters()
    d = page.filters_dialog
    assert not d.reset_button.isEnabled(), "no own choice yet"

    def settled():
        return not page.case_view.acting and not page.case_view.judging

    d.row("zona.footer").switch.click()   # the case's own choice
    qtbot.waitUntil(lambda: page._case(case.id).review.filters == {"zona.footer": True} and settled(),
                    timeout=10000)
    assert page.filters_dialog.reset_button.isEnabled()
    d = page.filters_dialog
    d.scope.setChecked(True)
    d.row("zona.footer").switch.click()   # back on, for the whole initiative
    qtbot.waitUntil(lambda: api.load(page.ini.id).filters == {"zona.footer": False} and settled(), timeout=10000)
    assert page._case(case.id).review.filters == {}, "the case follows the default"
    d = page.filters_dialog
    d.scope.setChecked(False)
    d.row("decidere.maiuscole").switch.click()
    qtbot.waitUntil(lambda: page._case(case.id).review.filters == {"decidere.maiuscole": True} and settled(),
                    timeout=10000)
    page.filters_dialog.reset_button.click()
    qtbot.waitUntil(lambda: page._case(case.id).review.filters == {} and settled(), timeout=10000)
    assert api.load(page.ini.id).filters == {"zona.footer": False}, "the defaults stay"
    assert (strings.FILTRI_RESET_DONE, "ok") in page._window.toasts
    page.undo_review()
    qtbot.waitUntil(lambda: page._case(case.id).review.filters == {"decidere.maiuscole": True}, timeout=10000)


def test_the_page_number_preset_reads_apart_from_the_zone(qtbot, page, fake_core, tmp_path):
    """M6: the regex preset named like the zone reads "… nel testo" and says why."""
    case = open_case(page, fake_core, tmp_path)
    d = _dialog(qtbot, fake_core.officina.filters(page.ini, case))   # the default rows
    rule = d.row("avanzate.Numero di pagina nel testo")
    assert rule.title.text() == strings.FILTRI_PRESET_PAGE_NUMBER == "Numero di pagina nel testo"
    assert rule.title.toolTip() == strings.FILTRI_PRESET_PAGE_NUMBER_TIP
    assert d.row("zona.numero_pagina").title.text() == "Numero di pagina"


def test_disabled_occurrences_are_greyed_in_both_themes():
    """M4: a disabled occurrence (not a difference) reads apart from the others."""
    from qtrequestory.ui import theme_qss

    assert 'QPushButton[role="row"]:disabled {{ color: {muted}; font-style: italic; }}' in theme_qss.QSS


def test_closing_with_unsaved_rules_asks_first(qtbot, page, fake_core, tmp_path, monkeypatch):
    """M7: Salva / Scarta / Annulla; leaving the case: Salva / Scarta."""
    case = _judged(qtbot, page, fake_core, tmp_path)
    api = fake_core.officina
    page.open_filters()
    d = page.filters_dialog
    asked = []
    answers = ["cancel", "save"]
    monkeypatch.setattr(type(d), "ask_unsaved", lambda self, **kw: (asked.append(kw), answers.pop(0))[1])
    d.close_button.click()
    assert asked == [] and not d.isVisible(), "nothing unsaved: no question"
    page.open_filters()
    d = page.filters_dialog
    d.editor.add_rule("Pratica", "PR")
    d.close_button.click()
    assert asked[-1] == {"valid": True, "cancellable": True} and d.isVisible(), "Annulla: it stays"
    d.close_button.click()
    assert not d.isVisible() and ("set_noise_rules", case.id) in api.review_actions, "Salva"
    qtbot.waitUntil(lambda: not page.case_view.judging, timeout=10000)
    page.open_filters()
    d = page.filters_dialog
    d.editor.add_rule("Altra", "(a+")
    answers.append("discard")
    page.show_board()
    assert asked[-1] == {"valid": False, "cancellable": False}, "leaving: no Annulla, no Salva with errors"
    assert page.filters_dialog is None
    assert [r.name for r in api.load(page.ini.id).cases[0].review.noise_rules] == ["Pratica"]


# ---------------------------------- the control generation (final review) ---

def test_a_control_becoming_ready_judges_the_version_on_screen_again(qtbot, page, fake_core, tmp_path):
    """M2: «pronta» re-judges the version on screen (no generation), dialog open or not."""
    from tests.ui.test_officina_progress import _generate_v1

    case = _generate_v1(qtbot, page, fake_core, tmp_path)
    api = fake_core.officina
    qtbot.waitUntil(lambda: page.case_view.docs is not None and page.case_view.docs.judged is not None
                    and not page.case_view.judging, timeout=10000)
    api.set_control_state(case.id, ControlState("in_corso"))
    page._sync_filters()
    assert page.control_watch is not None and page.control_watch.isActive()
    generated, compared = len(case.tobe_versions()), len(api.compare_case_calls)
    page.control_watch.setInterval(20)
    qtbot.wait(100)
    assert len(api.compare_case_calls) == compared, "still running: nothing judged again"
    api.set_control_state(case.id, ControlState("pronta"))
    qtbot.waitUntil(lambda: len(api.compare_case_calls) > compared and not page.case_view.acting, timeout=10000)
    assert not page.control_watch.isActive()
    assert api.compare_case_calls[-1] == (case.id, 1), "the version on screen, judged again"
    assert len(api.load("Banco").cases[0].tobe_versions()) == generated, "nothing regenerated"
    qtbot.wait(100)
    assert len(api.compare_case_calls) == compared + 1, "once"


def test_a_control_that_ends_unavailable_stops_watching_without_judging(qtbot, page, fake_core, tmp_path):
    from tests.ui.test_officina_progress import _generate_v1

    case = _generate_v1(qtbot, page, fake_core, tmp_path)
    api = fake_core.officina
    qtbot.waitUntil(lambda: page.case_view.docs is not None and not page.case_view.judging, timeout=10000)
    api.set_control_state(case.id, ControlState("in_corso"))
    page._sync_filters()
    page.control_watch.setInterval(20)
    compared = len(api.compare_case_calls)
    api.set_control_state(case.id, ControlState("non_disponibile"))
    qtbot.waitUntil(lambda: not page.control_watch.isActive(), timeout=5000)
    qtbot.wait(50)
    assert len(api.compare_case_calls) == compared


def test_an_email_case_says_the_control_is_not_available_for_emails(qtbot, page, fake_core, tmp_path):
    """M3: never «parte da solo dopo la prossima generazione» for an email."""
    from qtrequestory.ui.pages.officina_filters_page import is_email_case

    case = open_case(page, fake_core, tmp_path, target=False)
    source = tmp_path / "cliente" / "Email del cliente.html"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("<html><body><p>Gentile cliente, Acme-Servizi.</p></body></html>", encoding="utf-8")
    fake_core.officina.set_target(case, source)
    page.refresh()
    page.open_case(case.id)
    case = page._case(case.id)
    assert is_email_case(case)
    page.open_filters()
    d = page.filters_dialog
    qtbot.addWidget(d)
    assert d.control.text() == strings.FILTRI_CONTROL_EMAIL != strings.FILTRI_CONTROL_ASSENTE
    assert not d.poll.isActive()
    fake_core.officina.set_control_state(case.id, ControlState("in_corso"))
    page._sync_filters()
    assert d.control.text() == strings.FILTRI_CONTROL_EMAIL
    assert page.control_watch is None or not page.control_watch.isActive()


def test_a_pdf_case_without_a_control_keeps_the_usual_line(qtbot, page, fake_core, tmp_path):
    case = open_case(page, fake_core, tmp_path)
    page.open_filters()
    d = page.filters_dialog
    qtbot.addWidget(d)
    assert d.control.text() == strings.FILTRI_CONTROL_ASSENTE
