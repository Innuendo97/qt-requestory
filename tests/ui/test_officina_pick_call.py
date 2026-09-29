""""Aggiungi chiamata…" (task A1): the window, its question, the page's add
and replace, the case's "Cambia chiamata…" and its call strip.

Offscreen, on the fake core (the real ``OfficinaService`` on tmp files, the
12 synthetic hits of ``FakeIndexApi``). Modal questions are answered by
replacing ``officina_pick_question.ask_resolution`` / the dialog's ``exec``.
"""
from __future__ import annotations

import json

import pytest
from PySide6.QtWidgets import QDialog

from qtrequestory.ui import actions, strings
from qtrequestory.ui.pages import officina_add, officina_pick_call, officina_pick_question
from qtrequestory.ui.pages.officina_add import AddChoice
from qtrequestory.ui.pages.officina_add_plan import AddTarget, PlanItem, outcome_text, run_plan
from qtrequestory.ui.pages.officina_case_extras import asis_predates_call
from qtrequestory.ui.pages.officina_pick_call import PickCallDialog, parse_query
from qtrequestory.ui.pages.officina_pick_question import ReplaceOrNewDialog, Resolution
from qtrequestory.ui.workers import OFFICINA_ADD_JOB, OFFICINA_PICK_JOB
from tests.conftest import FDI_A, FDI_B, FDI_C, KEY_CTE, KEY_EMAIL, KEY_SINT

from .test_officina_page import make_initiative, page, shell  # noqa: F401 - fixtures


def _dialog(qtbot, fake_core, runner, *, case=None, current=None) -> PickCallDialog:
    dialog = PickCallDialog(fake_core, runner, fake_core.officina.initiatives(), current=current,
                            case=case)
    qtbot.addWidget(dialog)
    return dialog


def _searched(qtbot, dialog: PickCallDialog, text: str) -> list:
    dialog.query.setText(text)
    qtbot.waitUntil(lambda: dialog.note.text() not in (strings.CHIAMATA_START, strings.CHIAMATA_SEARCHING)
                    and not dialog.timer.isActive(), timeout=3000)
    return dialog.hits()


# ------------------------------------------------------------------ query ---

def test_parse_query_follows_the_omnibox_rules():
    assert parse_query(KEY_SINT.lower()) == (None, KEY_SINT)
    assert parse_query("aaaaaaaa") == ("aaaaaaaa", None)
    assert parse_query(f"### {FDI_A}_{KEY_SINT}_1a2b3c0200000031.json") == (FDI_A, KEY_SINT)
    assert parse_query("due parole") is None


# ------------------------------------------------------------ the window ---

def test_the_search_waits_for_the_typing_to_stop(qtbot, fake_core, runner, monkeypatch):
    calls = []
    real = fake_core.index.search
    monkeypatch.setattr(fake_core.index, "search", lambda q: calls.append(q) or real(q))
    dialog = _dialog(qtbot, fake_core, runner)
    for n in range(1, len(KEY_SINT) + 1):
        dialog.query.setText(KEY_SINT[:n])
    assert runner.job(OFFICINA_PICK_JOB) is None, "nothing is searched while typing"
    assert dialog.timer.isActive() and dialog.timer.interval() == officina_pick_call.DEBOUNCE_MS
    qtbot.waitUntil(lambda: bool(dialog.hits()), timeout=3000)
    assert len(calls) == 1 and calls[0].template_key == KEY_SINT and calls[0].key_mode == "exact"
    hits = dialog.hits()
    assert {h.template_key for h in hits} == {KEY_SINT}
    assert [h.day for h in hits] == sorted((h.day for h in hits), reverse=True), "most recent first"
    assert dialog.table.rowCount() == len(hits)
    assert dialog.table.item(0, 1).text() == hits[0].fdi
    assert dialog.note.text() == strings.CHIAMATA_FOUND.format(n=len(hits))


def test_an_fdi_prefix_lists_every_key_of_that_fdi(qtbot, fake_core, runner):
    dialog = _dialog(qtbot, fake_core, runner)
    hits = _searched(qtbot, dialog, FDI_C[:8])
    assert hits and {h.fdi for h in hits} == {FDI_C}
    assert {h.template_key for h in hits} == {KEY_SINT, KEY_EMAIL, KEY_CTE}


def test_the_list_is_capped_with_a_note(qtbot, fake_core, runner, monkeypatch):
    monkeypatch.setattr(officina_pick_call, "PICK_LIMIT", 2)
    dialog = _dialog(qtbot, fake_core, runner)
    hits = _searched(qtbot, dialog, KEY_SINT)
    assert len(hits) == 2 and dialog.table.rowCount() == 2
    assert dialog.note.text() == strings.CHIAMATA_CAPPED.format(n=2)


def test_problems_are_sentences_in_the_window(qtbot, fake_core, runner):
    dialog = _dialog(qtbot, fake_core, runner)
    dialog.env.setCurrentText("svil")  # no hit indexed there
    _searched(qtbot, dialog, KEY_SINT)
    assert dialog.note.text() == strings.CHIAMATA_NO_INDEX.format(env="svil")
    dialog.env.setCurrentText("coll")
    _searched(qtbot, dialog, "due parole")
    assert dialog.note.text() == strings.CHIAMATA_NOT_A_QUERY
    _searched(qtbot, dialog, "MOD_TEST_NESSUNO")
    assert dialog.note.text() == strings.CHIAMATA_NONE.format(env="coll")
    assert dialog.table.rowCount() == 0


def test_the_environment_is_the_one_ricerca_last_used(qtbot, fake_core, runner):
    actions.user_settings().setValue("search/env", "svil")
    assert _dialog(qtbot, fake_core, runner).env.currentText() == "svil"
    actions.user_settings().setValue("search/env", "prod-sparito")
    assert _dialog(qtbot, fake_core, runner).env.currentText() == "coll"


def test_several_calls_become_one_plan_of_new_cases(qtbot, fake_core, runner, tmp_path, monkeypatch):
    make_initiative(fake_core, "Piano", (), tmp_path)
    monkeypatch.setattr(officina_pick_question, "ask_resolution",
                        lambda *_a, **_k: Resolution(None, "prova-2"))
    dialog = _dialog(qtbot, fake_core, runner, current="Piano")
    hits = _searched(qtbot, dialog, FDI_A[:8])
    dialog.table.selectAll()
    dialog.variant.setText("prova")
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    target, items = dialog.plan()
    assert target == AddTarget("Piano", False)
    assert [i.hit for i in items] == hits and all(i.replace is None for i in items)
    variants = {}
    for item in items:
        variants.setdefault(item.hit.template_key, []).append(item.variant)
    assert variants == {KEY_SINT: ["prova", "prova-2"], KEY_EMAIL: ["prova"], KEY_CTE: ["prova", "prova-2"]}


def test_a_key_that_has_a_case_is_asked_about(qtbot, fake_core, runner, tmp_path, monkeypatch):
    ini = make_initiative(fake_core, "Doppio", (KEY_SINT,), tmp_path)
    asked = []

    def answer(_parent, hit, cases, **kw):
        asked.append((hit.template_key, [c.id for c in cases], kw["default_replace"]))
        return Resolution(cases[0].id) if cases else Resolution(None, "bis")

    monkeypatch.setattr(officina_pick_question, "ask_resolution", answer)
    dialog = _dialog(qtbot, fake_core, runner, current=ini.id)
    hits = _searched(qtbot, dialog, FDI_A[:8])
    dialog.table.selectAll()
    dialog.accept()
    _target, items = dialog.plan()
    sint = [i for i in items if i.hit.template_key == KEY_SINT]
    assert len(sint) == 2 and asked[0] == (KEY_SINT, [KEY_SINT], None)
    assert sint[0].replace == KEY_SINT
    assert sint[1].replace is None, "a case is replaced once per run; later calls are new cases"
    assert len(items) == len(hits)


def test_cancelling_the_question_keeps_the_window_open(qtbot, fake_core, runner, tmp_path, monkeypatch):
    ini = make_initiative(fake_core, "Annullo", (KEY_SINT,), tmp_path)
    monkeypatch.setattr(officina_pick_question, "ask_resolution", lambda *_a, **_k: None)
    dialog = _dialog(qtbot, fake_core, runner, current=ini.id)
    _searched(qtbot, dialog, KEY_SINT)
    dialog.table.selectRow(0)
    dialog.accept()
    assert dialog.plan() is None and dialog.result() != QDialog.DialogCode.Accepted


def test_opened_from_a_case_it_prefilters_and_defaults_to_replacing(qtbot, fake_core, runner, tmp_path,
                                                                    monkeypatch):
    ini = make_initiative(fake_core, "Dal caso", (KEY_SINT,), tmp_path)
    case = fake_core.officina.load(ini.id).cases[0]
    defaults = []
    monkeypatch.setattr(officina_pick_question, "ask_resolution",
                        lambda _p, _h, cases, **kw: defaults.append(kw["default_replace"]) or Resolution(
                            kw["default_replace"]))
    dialog = _dialog(qtbot, fake_core, runner, case=case, current=ini.id)
    assert dialog.query.text() == KEY_SINT and dialog.windowTitle() == strings.CHIAMATA_TITLE_CASE.format(
        case=KEY_SINT)
    qtbot.waitUntil(lambda: bool(dialog.hits()), timeout=3000)
    assert not dialog.initiative.isEnabled() and dialog.variant.isHidden()
    dialog.table.selectRow(1)
    dialog.accept()
    assert defaults == [case.id]
    assert dialog.plan()[1] == [PlanItem(dialog.hits()[1], case.id, "")]


def test_from_a_case_a_call_of_another_key_is_refused(qtbot, fake_core, runner, tmp_path):
    ini = make_initiative(fake_core, "Altra key", (KEY_SINT,), tmp_path)
    case = fake_core.officina.load(ini.id).cases[0]
    dialog = _dialog(qtbot, fake_core, runner, case=case, current=ini.id)
    hits = _searched(qtbot, dialog, FDI_B[:8])
    dialog.table.selectRow(next(n for n, h in enumerate(hits) if h.template_key != KEY_SINT))
    dialog.accept()
    assert dialog.plan() is None and dialog.error.text() == strings.CHIAMATA_OTHER_KEY.format(key=KEY_SINT)


# -------------------------------------------------------------- question ---

def test_the_question_defaults_and_validates(qtbot, fake_core, tmp_path):
    ini = make_initiative(fake_core, "Domanda", (KEY_SINT,), tmp_path)
    cases = fake_core.officina.load(ini.id).cases
    hit = fake_core.index.hits[0]
    dialog = ReplaceOrNewDialog(hit, cases, initiative=ini.name, default_replace=cases[0].id)
    qtbot.addWidget(dialog)
    assert dialog.replace_buttons[cases[0].id].isChecked()
    assert dialog.replace_buttons[cases[0].id].text() == strings.CHIAMATA_ASK_REPLACE.format(case=KEY_SINT)
    assert dialog.resolution() == Resolution(cases[0].id)
    elsewhere = ReplaceOrNewDialog(hit, cases, initiative=ini.name)
    qtbot.addWidget(elsewhere)
    assert elsewhere.new_button.isChecked(), "outside a case a new case is the default"
    # the default is valid at once: a free variant from the short FDI (one Enter, review minor 3)
    assert elsewhere.resolution() == Resolution(None, hit.fdi[:8])
    elsewhere.variant.setText("")
    assert elsewhere.resolution() is None and elsewhere.error.text() == strings.CHIAMATA_ASK_NEED_VARIANT
    elsewhere.variant.setText("bis")
    assert elsewhere.resolution() == Resolution(None, "bis")


# ------------------------------------------------------------------ plan ---

def test_run_plan_adds_and_replaces_and_never_raises(fake_core, tmp_path):
    api = fake_core.officina
    ini = make_initiative(fake_core, "Esecuzione", (KEY_SINT,), tmp_path)
    case = api.load(ini.id).cases[0]
    by_key = {(h.fdi, h.template_key): h for h in fake_core.index.hits}
    missing = by_key[(FDI_B, KEY_CTE)]
    fake_core.index.set_missing(missing)
    out = run_plan(api, AddTarget(ini.id), [
        PlanItem(by_key[(FDI_C, KEY_SINT)], case.id),
        PlanItem(by_key[(FDI_A, KEY_EMAIL)]),
        PlanItem(by_key[(FDI_A, KEY_CTE)], None, "uno"),
        PlanItem(missing, None, "due"),
    ])
    assert [c.id for c in out.replaced] == [case.id] and len(out.added) == 2
    assert len(out.failed) == 1 and "ripetere la ricerca" in out.failed[0][1]
    text = outcome_text(out)
    assert text.startswith("«Esecuzione»: 2 casi aggiunti, chiamata sostituita in 1 caso, 1 non riuscite")
    assert run_plan(api, AddTarget("Non esiste"), []).error


# ------------------------------------------------------------------ page ---

def _answer_window(monkeypatch, pick):
    """``PickCallDialog.exec`` accepted after ``pick(dialog)`` (offscreen: no modal)."""
    def exec_(dialog):
        pick(dialog)
        dialog.accept()
        return int(dialog.result())

    monkeypatch.setattr(PickCallDialog, "exec", exec_)


def test_the_board_adds_several_calls_in_one_go(qtbot, page, fake_core, tmp_path, shell, monkeypatch):  # noqa: F811
    make_initiative(fake_core, "Bacheca", (), tmp_path)
    page.refresh()
    page.open_initiative("Bacheca")
    assert page.board.add_search_button.text() == "Aggiungi chiamata…"
    boards = []
    real = page.show_board
    monkeypatch.setattr(page, "show_board", lambda: boards.append(1) or real())

    def pick(dialog):
        dialog.query.setText(FDI_A[:8])
        dialog.search_now()
        qtbot.waitUntil(lambda: bool(dialog.hits()), timeout=3000)
        dialog.table.selectAll()

    asked = []
    monkeypatch.setattr(officina_pick_question, "ask_resolution",
                        lambda _p, hit, cases, **kw: asked.append((hit.template_key, cases, kw["taken"]))
                        or Resolution(None, "bis"))
    _answer_window(monkeypatch, pick)
    page.board.add_search_button.click()
    job = page.runner.job(OFFICINA_ADD_JOB)
    qtbot.waitUntil(lambda: job.finished, timeout=5000)
    qtbot.waitUntil(lambda: bool(boards), timeout=3000)
    # FDI_A: two calls of KEY_SINT and of KEY_CTE: the second of each is asked about
    assert sorted((k, c, t) for k, c, t in asked) == [(KEY_CTE, [], [""]), (KEY_SINT, [], [""])]
    cases = fake_core.officina.load("Bacheca").cases
    assert sorted((c.key, c.variant) for c in cases) == sorted(
        [(KEY_SINT, ""), (KEY_SINT, "bis"), (KEY_EMAIL, ""), (KEY_CTE, ""), (KEY_CTE, "bis")])
    assert shell.statuses[-1] == "«Bacheca»: 5 casi aggiunti."
    assert boards == [1], "the board refreshes once"
    assert page.board.table.rowCount() == 5


def test_changing_a_case_call_keeps_the_versions_and_offers_the_asis(qtbot, page, fake_core, tmp_path,  # noqa: F811
                                                                     shell, monkeypatch):
    api = fake_core.officina
    ini = make_initiative(fake_core, "Cambio", (KEY_SINT,), tmp_path)
    case = api.load(ini.id).cases[0]
    api.generate(api.load(ini.id), case, "asis")
    page.refresh()
    page.open_initiative(ini.id)
    page.open_case(case.id)
    assert page.case_view.call_strip.message() == ""
    assert page.case_view.change_call_action.isEnabled()
    newer = next(h for h in fake_core.index.hits if h.template_key == KEY_SINT and h.fdi == FDI_C)
    monkeypatch.setattr(officina_pick_question, "ask_resolution",
                        lambda _p, _h, _c, **kw: Resolution(kw["default_replace"]))

    def pick(dialog):
        dialog.search_now()
        qtbot.waitUntil(lambda: bool(dialog.hits()), timeout=3000)
        dialog.table.selectRow(dialog.hits().index(newer))

    _answer_window(monkeypatch, pick)
    page.case_view.change_call_action.trigger()
    qtbot.waitUntil(lambda: page.case_view.call_strip.message() == strings.CHIAMATA_STALE_ASIS, timeout=5000)
    again = api.load(ini.id).cases[0]
    assert again.source_fdi == FDI_C and again.asis() is not None
    assert api.payload(again) == json.loads(fake_core.index.read_body(newer))
    assert asis_predates_call(again)
    assert shell.statuses[-1] == "«Cambio»: chiamata sostituita in 1 caso."

    page.case_view.call_strip.click()  # "Rigenera AS-IS": the note is given for the user
    qtbot.waitUntil(lambda: api.load(ini.id).cases[0].history[-1]["note"] == strings.CHIAMATA_ASIS_NOTE,
                    timeout=5000)
    qtbot.waitUntil(lambda: not page.queue.is_busy(), timeout=5000)
    assert not asis_predates_call(api.load(ini.id).cases[0])
    qtbot.waitUntil(lambda: page.case_view.call_strip.message() == "", timeout=5000)


def test_the_editor_link_opens_the_window_on_the_case(qtbot, page, fake_core, tmp_path, monkeypatch):  # noqa: F811
    from qtrequestory.ui.pages.officina_editor import PayloadHeaderDialog

    ini = make_initiative(fake_core, "Editor", (KEY_SINT,), tmp_path)
    page.refresh()
    page.open_initiative(ini.id)
    case = page._case(page.ini.cases[0].id)
    page.open_case(case.id)
    opened = []
    monkeypatch.setattr(PayloadHeaderDialog, "exec",
                        lambda dialog: dialog.change_call_button.click() or int(dialog.result()))
    monkeypatch.setattr(page, "pick_calls", lambda case=None: opened.append(case.id if case else None))
    page.case_view.editor_action.trigger()
    assert opened == [case.id]


def test_the_editor_link_asks_before_dropping_edits(qtbot, fake_core, tmp_path, monkeypatch):
    from qtrequestory.ui.pages import officina_dialogs
    from qtrequestory.ui.pages.officina_editor import PayloadHeaderDialog

    ini = make_initiative(fake_core, "Modifiche", (KEY_SINT,), tmp_path)
    case = fake_core.officina.load(ini.id).cases[0]
    dialog = PayloadHeaderDialog(fake_core, case)
    qtbot.addWidget(dialog)
    dialog.editor.setPlainText('{"modificato": true}')
    monkeypatch.setattr(officina_dialogs, "confirm", lambda *_a: False)
    dialog.change_call_button.click()
    assert not dialog.wants_change_call
    monkeypatch.setattr(officina_dialogs, "confirm", lambda *_a: True)
    dialog.change_call_button.click()
    assert dialog.wants_change_call and dialog.result() == QDialog.DialogCode.Rejected


# --------------------------------------------------------------- Ricerca ---

@pytest.fixture
def window(qtbot, fake_core, runner):
    from qtrequestory.ui.main_window import MainWindow

    win = MainWindow(fake_core, runner)
    qtbot.addWidget(win)
    return win


def test_the_ricerca_menu_asks_and_replaces_a_case_call(qtbot, window, fake_core, tmp_path, monkeypatch):
    ini = make_initiative(fake_core, "Da Ricerca", (KEY_SINT,), tmp_path)
    hit = next(h for h in fake_core.index.hits if h.template_key == KEY_SINT)
    monkeypatch.setattr(officina_add, "ask_add_case", lambda *_a, **_k: AddChoice(ini.id, False, ""))
    asked = []
    monkeypatch.setattr(officina_pick_question, "ask_resolution",
                        lambda _p, _h, cases, **_k: asked.append([c.id for c in cases]) or Resolution(
                            cases[0].id))
    search = window.page("search")
    menu = search.build_context_menu(hit)
    next(a for a in menu.actions() if a.text() == strings.OFFICINA_ADD_MENU).trigger()
    menu.deleteLater()
    assert asked == [[KEY_SINT]]
    cases = fake_core.officina.load(ini.id).cases
    assert len(cases) == 1 and cases[0].source_fdi == hit.fdi
    assert fake_core.officina.payload(cases[0]) == json.loads(fake_core.index.read_body(hit))


def test_the_officina_writes_while_calls_become_cases(page):  # noqa: F811
    assert page.is_writing() is False
    assert OFFICINA_ADD_JOB in type(page.runner).EXCLUSIVE


def test_a_case_on_its_way_keeps_its_call(page, fake_core, tmp_path, shell, monkeypatch):  # noqa: F811
    ini = make_initiative(fake_core, "In coda", (KEY_SINT,), tmp_path)
    page.refresh()
    page.open_initiative(ini.id)
    monkeypatch.setattr(page.queue, "state", lambda ini_id, case_id: "queued")
    hit = next(h for h in fake_core.index.hits if h.template_key == KEY_SINT)
    page.run_add_plan(AddTarget(ini.id), [PlanItem(hit, KEY_SINT)])
    assert shell.statuses[-1] == strings.CHIAMATA_CASE_BUSY.format(case=KEY_SINT)
    assert page.runner.job(OFFICINA_ADD_JOB) is None


def test_free_variant_is_one_enter_away():
    from qtrequestory.ui.pages.officina_pick_question import free_variant

    hit = FakeHit(FDI_A)
    assert free_variant("bis", hit, {""}) == "bis"
    assert free_variant("", hit, {""}) == "aaaaaaaa"
    assert free_variant("", hit, {"", "aaaaaaaa"}) == "aaaaaaaa-2"
    assert free_variant("abilitato", hit, {"abilitato"}) == "abilitato-aaaaaaaa"


class FakeHit:
    def __init__(self, fdi):
        self.fdi = fdi


def test_the_ricerca_menu_leaves_a_case_on_its_way_alone(qtbot, window, fake_core, tmp_path, monkeypatch):
    """Review Important 1: the right-click path refuses like the board does."""
    ini = make_initiative(fake_core, "Ricerca in coda", (KEY_SINT,), tmp_path)
    hit = next(h for h in fake_core.index.hits if h.template_key == KEY_SINT)
    monkeypatch.setattr(officina_add, "ask_add_case", lambda *_a, **_k: AddChoice(ini.id, False, ""))
    monkeypatch.setattr(officina_pick_question, "ask_resolution",
                        lambda _p, _h, cases, **_k: Resolution(cases[0].id))
    officina = window.page("officina")
    monkeypatch.setattr(officina.queue, "state", lambda ini_id, case_id: "running")
    before = fake_core.officina.payload(fake_core.officina.load(ini.id).cases[0])
    search = window.page("search")
    menu = search.build_context_menu(hit)
    next(a for a in menu.actions() if a.text() == strings.OFFICINA_ADD_MENU).trigger()
    menu.deleteLater()
    assert window.statusBar().currentMessage() == strings.CHIAMATA_CASE_BUSY.format(case=KEY_SINT)
    case = fake_core.officina.load(ini.id).cases[0]
    assert fake_core.officina.payload(case) == before and case.history == []


def test_a_busy_case_is_said_before_any_question(qtbot, fake_core, runner, tmp_path, monkeypatch):
    ini = make_initiative(fake_core, "Prima", (KEY_SINT,), tmp_path)
    asked = []
    monkeypatch.setattr(officina_pick_question, "ask_resolution", lambda *a, **k: asked.append(1))
    dialog = PickCallDialog(fake_core, runner, fake_core.officina.initiatives(), current=ini.id,
                            busy=lambda ini_id, case_id: (ini_id, case_id) == (ini.id, KEY_SINT))
    qtbot.addWidget(dialog)
    _searched(qtbot, dialog, KEY_SINT)
    dialog.table.selectRow(0)
    dialog.accept()
    assert asked == [] and dialog.plan() is None
    assert dialog.error.text() == strings.CHIAMATA_CASE_BUSY.format(case=KEY_SINT)


def test_a_stale_answer_never_overwrites_the_window(qtbot, fake_core, runner):
    dialog = _dialog(qtbot, fake_core, runner)
    _searched(qtbot, dialog, KEY_SINT)
    old_seq = dialog._seq
    dialog.query.setText("")
    dialog.search_now()  # the field was cleared: an answer for the old text is dropped
    dialog._on_hits("coll", fake_core.index.hits, old_seq)
    assert dialog.table.rowCount() == 0 and dialog.note.text() == strings.CHIAMATA_START


def test_the_field_has_the_focus_and_the_forms_are_aligned(qtbot, fake_core, runner):
    dialog = _dialog(qtbot, fake_core, runner)
    dialog.show()
    qtbot.waitExposed(dialog)
    assert dialog.focusWidget() is dialog.query
    x = dialog.env.mapTo(dialog, dialog.env.rect().topLeft()).x()
    assert dialog.initiative.mapTo(dialog, dialog.initiative.rect().topLeft()).x() == x
    assert dialog.variant.mapTo(dialog, dialog.variant.rect().topLeft()).x() == x


def _same_call_case(qtbot, page, fake_core, monkeypatch):  # noqa: F811
    """A case made from ``hit``, open on screen; the window answers "replace"."""
    api = fake_core.officina
    hit = next(h for h in fake_core.index.hits if h.template_key == KEY_SINT)
    ini = api.create_initiative("Stessa")
    api.case_from_hit(ini, hit)
    page.refresh()
    page.open_initiative(ini.id)
    case = page.ini.cases[0]
    page.open_case(case.id)
    monkeypatch.setattr(officina_pick_question, "ask_resolution",
                        lambda _p, _h, _c, **kw: Resolution(kw["default_replace"]))

    def pick(d):
        d.search_now()
        qtbot.waitUntil(lambda: bool(d.hits()), timeout=3000)
        d.table.selectRow(d.hits().index(hit))

    _answer_window(monkeypatch, pick)
    return api, ini, case, hit


def _change_call(qtbot, page):  # noqa: F811
    page.case_view.change_call_action.trigger()
    job = page.runner.job(OFFICINA_ADD_JOB)
    qtbot.waitUntil(lambda: job.finished, timeout=5000)
    qtbot.wait(50)


def test_the_current_call_is_only_a_label(qtbot, fake_core, runner, tmp_path):
    api = fake_core.officina
    hit = next(h for h in fake_core.index.hits if h.template_key == KEY_SINT)
    ini = api.create_initiative("Etichetta")
    case = api.case_from_hit(ini, hit)
    dialog = _dialog(qtbot, fake_core, runner, case=case, current=ini.id)
    hits = _searched(qtbot, dialog, KEY_SINT)
    assert dialog.table.item(hits.index(hit), 1).text() == strings.CHIAMATA_CURRENT.format(fdi=hit.fdi)


def test_the_same_call_with_an_unchanged_payload_changes_nothing(qtbot, page, fake_core, shell,  # noqa: F811
                                                                  monkeypatch):
    api, ini, case, _hit = _same_call_case(qtbot, page, fake_core, monkeypatch)
    _change_call(qtbot, page)
    assert shell.statuses[-1] == "«Stessa»: " + strings.CHIAMATA_DONE_UNCHANGED_ONE + "."
    again = api.load(ini.id).cases[0]
    assert again.history == [] and not list(again.folder.glob("payload.*.json"))
    assert page.case_view.call_strip.message() == ""


def test_the_same_call_restores_an_edited_payload(qtbot, page, fake_core, shell, monkeypatch):  # noqa: F811
    """Re-review Important: the FDI alone does not say "nothing to do"."""
    api, ini, case, hit = _same_call_case(qtbot, page, fake_core, monkeypatch)
    original = api.payload(case)
    api.save_payload(case, {"modificato": True})  # source_fdi stays the same
    _change_call(qtbot, page)
    again = api.load(ini.id).cases[0]
    assert api.payload(again) == original == json.loads(fake_core.index.read_body(hit))
    assert shell.statuses[-1] == "«Stessa»: " + strings.CHIAMATA_DONE_REPLACED_ONE + "."
    assert again.history[-1]["kind"] == "chiamata_sostituita"
    backups = [p for p in again.folder.glob("payload.2*.json")]
    assert len(backups) == 1 and json.loads(backups[0].read_text(encoding="utf-8")) == {"modificato": True}
