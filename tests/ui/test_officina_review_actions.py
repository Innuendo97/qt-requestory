"""Officina phase 2 (U4): the actions on a difference — the mini-bar under a
clicked highlight, double click, the right-click menu, F / T / V in the
viewer, the toast with "Annulla" and Ctrl+Z (spec §7.3, D10).

Offscreen; the page-level tests run on the fake core (``compare_case``
scripted by canned diffs, the review state real). Every action goes through
the ``officina-review`` worker, so the tests wait for the refresh.
"""
from __future__ import annotations

import dataclasses

import pytest
from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import Anchor, Judged, Mark, Review, Tolerance, Word
from qtrequestory.ui.pages import officina_dialogs
from qtrequestory.ui.pages.officina_actions_bar import place_bar
from qtrequestory.ui.pages.officina_page import OfficinaPage
from qtrequestory.ui.pages.officina_diffs import DiffPanel
from qtrequestory.ui.pages.officina_rows import snippet_html, snippet_width
from qtrequestory.ui.pages.officina_undo import (
    Entry,
    UndoStack,
    mark_steps,
    tolerate_steps,
    unmark_all_steps,
    variable_steps,
)
from qtrequestory.ui.theme import LIGHT
from qtrequestory.ui.toast import Toast
from tests.fakes.fake_core import fake_diff
from tests.ui.test_officina_page import FakeWindow, open_case, wait_idle


def placed(diff, y: float, *, x0: float = 60.0, x1: float = 140.0):
    left = (Word(diff.left_text or "x", 0, x0, y, x1, y + 12),)
    right = (Word(diff.right_text or "x", 0, x0, y, x1, y + 12),)
    return dataclasses.replace(diff, left=left, right=right)


# ------------------------------------------------------------ pure planning ---

def _j(verdict="da_fare", **flags) -> Judged:
    return Judged(fake_diff("cambiato", "testo", "12,00", "11,00"), verdict, **flags)


def test_f_marks_and_its_undo_unmarks():
    j = _j()
    forward, undo = mark_steps(j, Review(), 3)
    assert forward == [("mark_done", (j, 3))] and undo == [("unmark", (j,))]


def test_f_on_a_marked_diff_unmarks_and_its_undo_marks_again_in_the_marks_version():
    j = _j(marked=True)
    review = Review(marks=[Mark(j.diff.anchor, "11,00", 2, "")])
    forward, undo = mark_steps(j, review, 3)
    assert forward == [("unmark", (j,))] and undo == [("mark_done", (j, 2))]


def test_tolerate_and_untolerate_keep_the_note_for_the_undo():
    j = _j()
    assert tolerate_steps(j, Review(), "ok così") == ([("tolerate", (j, "ok così"))],
                                                      [("untolerate", (j,))])
    t = _j("tollerata")
    review = Review(tolerances=[Tolerance(t.diff.anchor, "11,00", "nota vecchia", "")])
    assert tolerate_steps(t, review) == ([("untolerate", (t,))], [("tolerate", (t, "nota vecchia"))])


def test_not_variable_and_variable_again_are_each_others_undo():
    v = Judged(fake_diff("cambiato", "variabile", "Nome", "Anna"), None)
    assert variable_steps(v, Review()) == ([("not_variable", (v,))], [("variable_again", (v,))])
    review = Review(not_variables=[(v.diff.anchor, "")])
    assert variable_steps(v, review) == ([("variable_again", (v,))], [("not_variable", (v,))])


def test_unmark_all_is_undone_by_marking_each_mark_again():
    on_screen = _j(marked=True)
    gone = Anchor("cambiato", "testo", "", "Titolo")
    review = Review(marks=[Mark(on_screen.diff.anchor, "11,00", 2, ""), Mark(gone, "Titol", 1, "")])
    forward, undo = unmark_all_steps(review, [on_screen])
    assert forward == [("unmark_all", ())]
    assert undo[0] == ("mark_done", (on_screen, 2))
    method, (stand_in, version) = undo[1]
    assert (method, version) == ("mark_done", 1)
    assert stand_in.diff.anchor == gone and stand_in.diff.right_text == "Titol"


def test_the_undo_stack_is_per_case_and_per_version():
    stack = UndoStack(depth=2)
    a, b, c = (Entry(t, 1, ()) for t in "abc")
    stack.push(("I", "1"), a)
    stack.push(("I", "2"), b)
    assert stack.top(("I", "1"), 1) is a
    stack.push(("I", "1"), c)  # depth 2: a goes
    d = Entry("d", 2, ())
    stack.push(("I", "1"), d)
    assert stack.top(("I", "1"), 1) is None, "the last action is on v2: not from v1"
    assert stack.top(("I", "1"), 2) is d, "nothing was dropped"
    stack.discard(("I", "1"), d)
    assert stack.top(("I", "1"), 1) is c
    stack.discard(("I", "1"), c)
    assert stack.top(("I", "1"), 1) is None and stack.top(("I", "2"), 1) is b


# ------------------------------------------------------------- bar geometry ---

AREA = QRect(0, 0, 600, 400)


def test_the_bar_sits_under_the_highlight():
    at = place_bar(QRect(100, 100, 80, 14), QSize(200, 28), AREA)
    assert at.x() == 100 and at.y() > 114


@pytest.mark.parametrize("anchor", [QRect(560, 100, 60, 14), QRect(590, 100, 200, 14),
                                    QRect(-50, 100, 40, 14), QRect(100, 385, 80, 14),
                                    QRect(560, 390, 60, 14)])
def test_the_bar_never_leaves_the_area(anchor):
    size = QSize(220, 28)
    at = place_bar(anchor, size, AREA)
    assert AREA.contains(QRect(at, size)), (anchor, at)


def test_at_the_bottom_the_bar_goes_above_the_highlight():
    at = place_bar(QRect(100, 380, 80, 14), QSize(200, 28), AREA)
    assert at.y() + 28 <= 380


# --------------------------------------------------------------- the toast ---

def test_a_toast_with_an_action_takes_clicks_and_calls_it(qtbot):
    parent = QWidget()
    qtbot.addWidget(parent)
    parent.resize(800, 400)
    parent.show()
    toast = Toast(parent)
    toast.show_message("primo")
    assert toast.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert not toast.action_button.isVisible()
    called = []
    toast.show_message("Segnata fatta «x»", "ok", action=("Annulla", lambda: called.append(1)))
    assert toast.action_button.isVisible() and toast.action_button.text() == "Annulla"
    assert not toast.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert parent.rect().contains(toast.geometry())
    QTest.mouseClick(toast.action_button, Qt.MouseButton.LeftButton)
    assert called == [1]
    assert not toast.isVisible() or toast.animations_enabled(), "a click dismisses it"
    toast.show_message("terzo")
    assert not toast.action_button.isVisible(), "a plain message drops the action"


# ------------------------------------------------------- U3 minors in rows ---

def test_the_struck_and_inserted_runs_touch_without_a_space():
    """U3 deferred minor: the hairline read as a space ("senpelmo a")."""
    diff = dataclasses.replace(fake_diff("cambiato", "testo", "abilitata", "abilitato"),
                               left_spans=((8, 9),), right_spans=((8, 9),))
    html = snippet_html(diff, LIGHT)
    assert "</s><b" in html
    assert "&#8202;" not in html and " " not in html


def test_a_link_rows_link_text_is_underlined():
    link = fake_diff("cambiato", "link", "Scopri le condizioni", "Scopri le condizioni",
                     before="Per i dettagli", after="del servizio.")
    html = snippet_html(link, LIGHT)
    assert "<u>Scopri le condizioni</u>" in html
    assert "<u>" not in snippet_html(fake_diff("cambiato", "testo", "a b", "a c"), LIGHT)


def test_fit_context_measures_the_changed_runs_in_bold_only():
    """U3 leftover: the context is drawn normal, only the change bold."""
    diff = dataclasses.replace(fake_diff("cambiato", "testo", "abilitata", "abilitato",
                                         before="La carta sarà", after="agli acquisti"),
                               left_spans=((8, 9),), right_spans=((8, 9),))
    plain = snippet_width(diff, len)
    weighted = snippet_width(diff, len, lambda text: 2 * len(text))
    assert weighted - plain == len("a") + len("o"), "only the struck and the inserted letter"


def test_rows_are_refitted_when_the_scroll_bar_appears(qtbot):
    """U3 leftover: the vertical scroll bar narrows the viewport without
    resizing the list; the rows follow the new width."""
    panel = DiffPanel()
    qtbot.addWidget(panel)
    panel.resize(420, 320)
    panel.show()
    rows = [Judged(placed(fake_diff("cambiato", "testo", f"parola{i}", f"parolo{i}"), 20.0 * i),
                   "da_fare") for i in range(40)]
    panel.show_judged(rows, 1, {})
    qtbot.wait(50)
    assert panel.list.verticalScrollBar().isVisible()
    assert panel.list._fitted_width == panel.list.viewport().width()


# ------------------------------------------------------------ page level ---

@pytest.fixture
def shell() -> FakeWindow:
    return FakeWindow()


@pytest.fixture
def page(qtbot, fake_core, runner, shell) -> OfficinaPage:
    widget = OfficinaPage(fake_core, runner, shell)
    qtbot.addWidget(widget)
    widget.resize(1300, 760)
    widget.show()
    return widget


def _open(qtbot, page, fake_core, tmp_path, diffs):
    case = open_case(page, fake_core, tmp_path)
    page.case_view.regenerate_button.click()
    wait_idle(qtbot, page)
    api = fake_core.officina
    api.set_canned(case.id, 1, diffs)
    calls = len(api.compare_case_calls)
    page.open_case(page.case_id, "v1")
    qtbot.waitUntil(lambda: len(api.compare_case_calls) > calls and not page.case_view.judging
                    and page.case_view.docs is not None and page.case_view.docs.judged is not None,
                    timeout=10000)
    view = page.case_view.right.view
    qtbot.waitUntil(lambda: bool(view.highlight_items(1)), timeout=10000)
    return case


def _id_of(page, diff) -> int:
    return next(j.diff.id for j in page.case_view.docs.judged.judged if j.diff.anchor == diff.anchor)


def _point(view, diff_id: int) -> QPoint:
    return view.mapFromScene(view.highlight_items(diff_id)[0].rect().center())


def _click(view, diff_id: int) -> None:
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=_point(view, diff_id))


def _actions(api, case) -> list[str]:
    return [name for name, cid in api.review_actions if cid == case.id]


def _settle(qtbot, page, before: int):
    """Wait for the review job to save and re-judge."""
    api = page.services.officina
    qtbot.waitUntil(lambda: len(api.compare_case_calls) > before and not page.case_view.acting,
                    timeout=10000)


def test_a_click_shows_the_bar_and_its_fatta_marks_once(qtbot, page, fake_core, tmp_path):
    first = placed(fake_diff("cambiato", "testo", "12,00", "11,00"), 100)
    case = _open(qtbot, page, fake_core, tmp_path, [first])
    view, api = page.case_view.right.view, fake_core.officina
    diff_id = _id_of(page, first)
    _click(view, diff_id)
    bar = page.case_view.bars["right"]
    assert bar.isVisible() and bar.diff_id == diff_id
    assert page.case_view.diffs.current_id() == diff_id, "the click selects too"
    assert bar.done_button.isVisible() and bar.tolerate_button.isVisible()
    assert bar.done_button.text() == strings.AZIONI_BAR_DONE
    below = view.mapFromScene(view.difference_rect(diff_id)).boundingRect().bottom()
    assert bar.y() - view.viewport().y() > below, "under the highlight"
    calls = len(api.compare_case_calls)
    bar.done_button.click()
    _settle(qtbot, page, calls)
    assert _actions(api, case) == ["mark_done"]
    assert page._case(case.id).review.marks
    assert not bar.isVisible(), "the refresh closes the bar"
    assert page.case_view.diffs.tab_texts()[1] == "Da verificare 1"


def test_the_bar_tollera_tolerates_without_a_note(qtbot, page, fake_core, tmp_path):
    first = placed(fake_diff("cambiato", "testo", "12,00", "11,00"), 100)
    case = _open(qtbot, page, fake_core, tmp_path, [first])
    view, api = page.case_view.right.view, fake_core.officina
    _click(view, _id_of(page, first))
    calls = len(api.compare_case_calls)
    page.case_view.bars["right"].tolerate_button.click()
    _settle(qtbot, page, calls)
    assert _actions(api, case) == ["tolerate"]
    (tolerance,) = page._case(case.id).review.tolerances
    assert tolerance.note == ""


def test_the_bar_stays_inside_the_viewport_at_the_right_page_edge(qtbot, page, fake_core, tmp_path):
    edge = placed(fake_diff("cambiato", "testo", "fine riga", "fine rigo"), 300, x0=540, x1=594)
    _open(qtbot, page, fake_core, tmp_path, [edge])
    view = page.case_view.right.view
    diff_id = _id_of(page, edge)
    _click(view, diff_id)
    bar = page.case_view.bars["right"]
    assert bar.isVisible()
    assert view.viewport().geometry().contains(bar.geometry()), (bar.geometry(),
                                                                 view.viewport().geometry())
    view.verticalScrollBar().setValue(view.verticalScrollBar().value() + 40)
    assert view.viewport().geometry().contains(bar.geometry()), "it follows the scroll"


def test_a_double_click_toggles_the_mark(qtbot, page, fake_core, tmp_path):
    first = placed(fake_diff("cambiato", "testo", "12,00", "11,00"), 100)
    case = _open(qtbot, page, fake_core, tmp_path, [first])
    view, api = page.case_view.right.view, fake_core.officina
    calls = len(api.compare_case_calls)
    QTest.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, pos=_point(view, _id_of(page, first)))
    _settle(qtbot, page, calls)
    assert _actions(api, case) == ["mark_done"]
    qtbot.waitUntil(lambda: bool(view.highlight_items(_id_of(page, first))), timeout=5000)
    calls = len(api.compare_case_calls)
    QTest.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, pos=_point(view, _id_of(page, first)))
    _settle(qtbot, page, calls)
    assert _actions(api, case) == ["mark_done", "unmark"]
    assert not page._case(case.id).review.marks


def test_a_double_click_on_a_variable_does_nothing(qtbot, page, fake_core, tmp_path, shell):
    var = placed(fake_diff("cambiato", "variabile", "Nome", "Anna"), 100)
    case = _open(qtbot, page, fake_core, tmp_path, [var])
    view, api = page.case_view.right.view, fake_core.officina
    calls = len(api.compare_case_calls)
    toasts = len(shell.toasts)
    QTest.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, pos=_point(view, _id_of(page, var)))
    qtbot.wait(200)
    assert _actions(api, case) == [] and len(api.compare_case_calls) == calls
    assert not page.case_view.acting and len(shell.toasts) == toasts, "silent"


def test_f_on_a_variable_explains_with_a_toast(qtbot, page, fake_core, tmp_path, shell):
    var = placed(fake_diff("cambiato", "variabile", "Nome", "Anna"), 100)
    case = _open(qtbot, page, fake_core, tmp_path, [var])
    view, api = page.case_view.right.view, fake_core.officina
    _click(view, _id_of(page, var))
    QTest.keyClick(view, Qt.Key.Key_F)
    assert _actions(api, case) == []
    assert shell.toasts[-1][0] == strings.AZIONI_NOT_COUNTING.format(
        what="Nome", state=strings.VERDETTO_VARIABILE)


def test_f_and_t_in_the_viewer_act_on_the_clicked_highlight(qtbot, page, fake_core, tmp_path):
    first = placed(fake_diff("cambiato", "testo", "12,00", "11,00"), 100)
    second = placed(fake_diff("cambiato", "testo", "Titolo", "Titol"), 200)
    case = _open(qtbot, page, fake_core, tmp_path, [first, second])
    view, api = page.case_view.right.view, fake_core.officina
    _click(view, _id_of(page, second))
    calls = len(api.compare_case_calls)
    QTest.keyClick(view, Qt.Key.Key_F)
    _settle(qtbot, page, calls)
    assert _actions(api, case) == ["mark_done"]
    assert page._case(case.id).review.marks[0].anchor == second.anchor
    _click(view, _id_of(page, first))
    calls = len(api.compare_case_calls)
    QTest.keyClick(view, Qt.Key.Key_T)
    _settle(qtbot, page, calls)
    assert _actions(api, case) == ["mark_done", "tolerate"]
    assert page._case(case.id).review.tolerances[0].anchor == first.anchor


def _menu_at(qtbot, page, diff):
    view = page.case_view.right.view
    pos = _point(view, _id_of(page, diff))
    event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, pos, view.viewport().mapToGlobal(pos))
    QApplication.sendEvent(view.viewport(), event)
    menu = page.case_view.menu
    assert menu is not None and menu.isVisible()
    return menu


def test_the_menu_offers_the_five_entries(qtbot, page, fake_core, tmp_path):
    first = placed(fake_diff("cambiato", "testo", "12,00", "11,00"), 100)
    _open(qtbot, page, fake_core, tmp_path, [first])
    menu = _menu_at(qtbot, page, first)
    texts = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert texts == [strings.AZIONI_MENU_DONE, strings.AZIONI_MENU_TOLERATE,
                     strings.AZIONI_MENU_NOT_VARIABLE, strings.AZIONI_MENU_COPY_TARGET,
                     strings.AZIONI_MENU_COPY_GENERATED]
    enabled = {a.text(): a.isEnabled() for a in menu.actions() if not a.isSeparator()}
    assert not enabled[strings.AZIONI_MENU_NOT_VARIABLE], "only on a variable"
    menu.hide()


def test_menu_tollera_asks_a_note_and_saves_it(qtbot, page, fake_core, tmp_path, monkeypatch):
    first = placed(fake_diff("cambiato", "testo", "12,00", "11,00"), 100)
    case = _open(qtbot, page, fake_core, tmp_path, [first])
    asked = []
    monkeypatch.setattr(officina_dialogs, "ask_tolerate_note",
                        lambda _parent, what: asked.append(what) or "scelta del cliente")
    api = fake_core.officina
    menu = _menu_at(qtbot, page, first)
    calls = len(api.compare_case_calls)
    menu.action_for("tollera_nota").trigger()
    _settle(qtbot, page, calls)
    assert asked == ["12,00"]
    assert _actions(api, case) == ["tolerate"]
    assert page._case(case.id).review.tolerances[0].note == "scelta del cliente"


def test_menu_tollera_cancelled_does_nothing(qtbot, page, fake_core, tmp_path, monkeypatch):
    first = placed(fake_diff("cambiato", "testo", "12,00", "11,00"), 100)
    case = _open(qtbot, page, fake_core, tmp_path, [first])
    monkeypatch.setattr(officina_dialogs, "ask_tolerate_note", lambda *_a: None)
    _menu_at(qtbot, page, first).action_for("tollera_nota").trigger()
    qtbot.wait(100)
    assert _actions(fake_core.officina, case) == [] and not page.case_view.acting


def test_menu_non_e_una_variabile_and_copies(qtbot, page, fake_core, tmp_path, shell):
    var = placed(fake_diff("cambiato", "variabile", "Nome", "Anna"), 100)
    case = _open(qtbot, page, fake_core, tmp_path, [var])
    api = fake_core.officina
    menu = _menu_at(qtbot, page, var)
    menu.action_for("copia_target").trigger()
    assert QApplication.clipboard().text() == "Nome"
    assert shell.toasts[-1][0] == strings.AZIONI_COPIED_TARGET
    menu = _menu_at(qtbot, page, var)
    menu.action_for("copia_generato").trigger()
    assert QApplication.clipboard().text() == "Anna"
    menu = _menu_at(qtbot, page, var)
    assert not menu.action_for("fatta").isEnabled()
    calls = len(api.compare_case_calls)
    menu.action_for("non_variabile").trigger()
    _settle(qtbot, page, calls)
    assert _actions(api, case) == ["not_variable"]


def test_every_action_toasts_with_annulla_and_the_toast_undoes_it(qtbot, page, fake_core, tmp_path,
                                                                    shell):
    first = placed(fake_diff("cambiato", "testo", "12,00", "11,00"), 100)
    case = _open(qtbot, page, fake_core, tmp_path, [first])
    view, api = page.case_view.right.view, fake_core.officina
    _click(view, _id_of(page, first))
    calls = len(api.compare_case_calls)
    QTest.keyClick(view, Qt.Key.Key_F)
    _settle(qtbot, page, calls)
    text, tone, action = shell.actions[-1]
    assert text == strings.ELENCO_MARKED.format(what="12,00") and tone == "ok"
    label, undo = action
    assert label == strings.AZIONI_UNDO
    calls = len(api.compare_case_calls)
    undo()
    _settle(qtbot, page, calls)
    assert _actions(api, case) == ["mark_done", "unmark"]
    assert not page._case(case.id).review.marks
    assert page.case_view.diffs.tab_texts()[:2] == ["Da guardare 1", "Da verificare 0"]
    assert shell.toasts[-1][0] == strings.AZIONI_UNDONE.format(action=text)
    undo()  # a stale toast: its action is already undone
    qtbot.wait(100)
    assert _actions(api, case) == ["mark_done", "unmark"]


def test_ctrl_z_undoes_the_last_actions_in_turn(qtbot, page, fake_core, tmp_path, shell):
    first = placed(fake_diff("cambiato", "testo", "12,00", "11,00"), 100)
    var = placed(fake_diff("cambiato", "variabile", "Nome", "Anna"), 200)
    case = _open(qtbot, page, fake_core, tmp_path, [first, var])
    view, api = page.case_view.right.view, fake_core.officina
    _click(view, _id_of(page, first))
    calls = len(api.compare_case_calls)
    QTest.keyClick(view, Qt.Key.Key_T)
    _settle(qtbot, page, calls)
    page.case_view.diffs.select(_id_of(page, var))
    page.case_view.diffs.list.setFocus()
    calls = len(api.compare_case_calls)
    QTest.keyClick(page.case_view.diffs.list, Qt.Key.Key_V)
    _settle(qtbot, page, calls)
    assert _actions(api, case) == ["tolerate", "not_variable"]
    focus = QApplication.focusWidget()
    assert focus is not None and page.case_view.isAncestorOf(focus),         "the Variabili tab emptied: the keyboard stays in the case"
    calls = len(api.compare_case_calls)
    QTest.keyClick(focus, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    _settle(qtbot, page, calls)
    assert _actions(api, case)[-1] == "variable_again"
    assert not page._case(case.id).review.not_variables
    calls = len(api.compare_case_calls)
    QTest.keyClick(view, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    _settle(qtbot, page, calls)
    assert _actions(api, case)[-1] == "untolerate"
    assert not page._case(case.id).review.tolerances
    QTest.keyClick(view, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert shell.statuses[-1] == strings.AZIONI_NOTHING_TO_UNDO


def test_annulla_i_segni_is_undone_by_ctrl_z(qtbot, page, fake_core, tmp_path):
    first = placed(fake_diff("cambiato", "testo", "12,00", "11,00"), 100)
    second = placed(fake_diff("cambiato", "testo", "Titolo", "Titol"), 200)
    case = _open(qtbot, page, fake_core, tmp_path, [first, second])
    view, api = page.case_view.right.view, fake_core.officina
    for diff in (first, second):
        _click(view, _id_of(page, diff))
        calls = len(api.compare_case_calls)
        QTest.keyClick(view, Qt.Key.Key_F)
        _settle(qtbot, page, calls)
    before = sorted((m.anchor.target_text, m.version) for m in page._case(case.id).review.marks)
    assert len(before) == 2
    calls = len(api.compare_case_calls)
    page.case_view.banners.unmark_all_requested.emit()
    _settle(qtbot, page, calls)
    assert not page._case(case.id).review.marks
    calls = len(api.compare_case_calls)
    page.undo_review()
    _settle(qtbot, page, calls)
    after = sorted((m.anchor.target_text, m.version) for m in page._case(case.id).review.marks)
    assert after == before
    assert page.case_view.diffs.tab_texts()[1] == "Da verificare 2"


def _idle(qtbot, page):
    """Every queued review request applied and the view redrawn."""
    view = page.case_view
    qtbot.waitUntil(lambda: not view.acting and not view.judging
                    and not any(page.review_queue.values()), timeout=15000)


def test_f_on_three_rows_quickly_marks_three_and_ctrl_z_three_times_unmarks_them(
        qtbot, page, fake_core, tmp_path):
    """R38: requests made while one is saving are QUEUED, never refused."""
    diffs = [placed(fake_diff("cambiato", "testo", t, t[:-1]), y)
             for t, y in (("12,00", 100), ("Titolo", 200), ("Testo", 300))]
    case = _open(qtbot, page, fake_core, tmp_path, diffs)
    view, api = page.case_view, fake_core.officina
    view.diffs.list.setFocus()
    for diff in diffs:  # no event loop in between: the first save is still running
        view.diffs.select(_id_of(page, diff))
        QTest.keyClick(view.diffs.list, Qt.Key.Key_F)
    assert view.acting
    _idle(qtbot, page)
    assert _actions(api, case) == ["mark_done"] * 3
    assert {m.anchor for m in page._case(case.id).review.marks} == {d.anchor for d in diffs}
    assert len(page.undo) == 3
    assert view.diffs.tab_texts()[1] == "Da verificare 3"
    focus = QApplication.focusWidget()
    assert focus is not None and view.isAncestorOf(focus)
    for _ in range(3):
        QTest.keyClick(focus, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    _idle(qtbot, page)
    assert _actions(api, case) == ["mark_done"] * 3 + ["unmark"] * 3
    assert not page._case(case.id).review.marks and len(page.undo) == 0


def test_f_three_times_on_row_one_marks_rows_one_two_three(qtbot, page, fake_core, tmp_path):
    """R40: F acts on the selected row and moves the selection on at once,
    before the refresh; the viewer follows."""
    diffs = [placed(fake_diff("cambiato", "testo", t, t[:-1]), y)
             for t, y in (("12,00", 100), ("Titolo", 200), ("Testo", 300))]
    case = _open(qtbot, page, fake_core, tmp_path, diffs)
    view, api = page.case_view, fake_core.officina
    view.diffs.list.setFocus()
    view.diffs.select(_id_of(page, diffs[0]))
    QTest.keyClick(view.diffs.list, Qt.Key.Key_F)
    assert view.diffs.current_id() == _id_of(page, diffs[1]), "moved on before the refresh"
    assert view.right.view.focused_difference() == view.diffs.current_id(), "the viewer follows"
    QTest.keyClick(view.diffs.list, Qt.Key.Key_F)
    QTest.keyClick(view.diffs.list, Qt.Key.Key_F)
    _idle(qtbot, page)
    assert _actions(api, case) == ["mark_done"] * 3
    assert [m.anchor for m in page._case(case.id).review.marks] == [d.anchor for d in diffs]
    focus = QApplication.focusWidget()
    assert focus is not None and view.isAncestorOf(focus)
    for _ in range(3):
        QTest.keyClick(focus, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    _idle(qtbot, page)
    assert _actions(api, case) == ["mark_done"] * 3 + ["unmark"] * 3
    assert not page._case(case.id).review.marks


def test_the_bars_fatta_moves_the_selection_on(qtbot, page, fake_core, tmp_path):
    first = placed(fake_diff("cambiato", "testo", "12,00", "11,00"), 100)
    second = placed(fake_diff("cambiato", "testo", "Titolo", "Titol"), 200)
    _open(qtbot, page, fake_core, tmp_path, [first, second])
    _click(page.case_view.right.view, _id_of(page, first))
    page.case_view.bars["right"].done_button.click()
    assert page.case_view.diffs.current_id() == _id_of(page, second)
    _idle(qtbot, page)


def test_a_mark_records_the_latest_tobe_not_the_version_on_screen(qtbot, page, fake_core, tmp_path):
    """R47 (final review M2): F on an older version stamps the latest TO-BE
    existing now, so only a NEWER generation verifies the mark."""
    first = placed(fake_diff("cambiato", "testo", "12,00", "11,00"), 100)
    case = _open(qtbot, page, fake_core, tmp_path, [first])
    api = fake_core.officina
    api.set_canned(case.id, 2, [first])
    page.case_view.regenerate_button.click()
    wait_idle(qtbot, page)
    page.open_case(page.case_id, "v1")
    _idle(qtbot, page)
    diff_id = _id_of(page, first)
    page.open_case(page.case_id, "v2")  # v1 still on screen while v2 is compared
    page.review_action(diff_id, "fatta")
    _idle(qtbot, page)
    assert page.case_view.docs.judged.version == 2
    assert _actions(api, case) == ["mark_done"]
    # stamped v2 (the latest), so the re-judge of v2 does not verify it: "da verificare"
    review = page._case(case.id).review
    assert [(m.anchor, m.version) for m in review.marks] == [(first.anchor, 2)] and not review.unresolved
    assert page.case_view.docs.judged.judged[0].marked


def test_a_queued_tollera_note_survives_an_earlier_t(qtbot, page, fake_core, tmp_path,
                                                     monkeypatch):
    first = placed(fake_diff("cambiato", "testo", "12,00", "11,00"), 100)
    case = _open(qtbot, page, fake_core, tmp_path, [first])
    monkeypatch.setattr(officina_dialogs, "ask_tolerate_note", lambda *_a: "con nota")
    diff_id = _id_of(page, first)
    page.review_action(diff_id, "tollera")       # saving...
    page.review_action(diff_id, "tollera_nota")  # ...queued behind it, on the same row
    _idle(qtbot, page)
    assert _actions(fake_core.officina, case) == ["tolerate", "tolerate"]
    (tolerance,) = page._case(case.id).review.tolerances
    assert tolerance.note == "con nota"


def test_an_action_asked_during_a_compare_runs_after_it(qtbot, page, fake_core, tmp_path):
    first = placed(fake_diff("cambiato", "testo", "12,00", "11,00"), 100)
    case = _open(qtbot, page, fake_core, tmp_path, [first])
    view, api = page.case_view, fake_core.officina
    diff_id = _id_of(page, first)
    before = len(api.compare_case_calls)
    page.open_case(page.case_id)  # the same version compared again: a compare runs
    assert view.judging
    page.review_action(diff_id, "fatta")
    assert not view.acting and _actions(api, case) == [], "it waits, it is not refused"
    _idle(qtbot, page)
    assert _actions(api, case) == ["mark_done"]
    assert len(api.compare_case_calls) >= before + 2, "the compare, then the action's re-judge"
    assert view.diffs.tab_texts()[1] == "Da verificare 1"


def test_the_toasts_annulla_during_a_save_is_applied_after_it(qtbot, page, fake_core, tmp_path,
                                                              shell):
    first = placed(fake_diff("cambiato", "testo", "12,00", "11,00"), 100)
    second = placed(fake_diff("cambiato", "testo", "Titolo", "Titol"), 200)
    case = _open(qtbot, page, fake_core, tmp_path, [first, second])
    view, api = page.case_view, fake_core.officina
    page.review_action(_id_of(page, first), "fatta")
    _idle(qtbot, page)
    _text, _tone, (_label, undo_first) = shell.actions[-1]
    page.review_action(_id_of(page, second), "fatta")
    assert view.acting
    undo_first()  # while the second one saves
    _idle(qtbot, page)
    assert _actions(api, case) == ["mark_done", "mark_done", "unmark"]
    assert [m.anchor for m in page._case(case.id).review.marks] == [second.anchor]


def test_the_toasts_annulla_does_nothing_on_another_version(qtbot, page, fake_core, tmp_path):
    """Minor 1: like Ctrl+Z, the toast undoes only on the version it was made on."""
    first = placed(fake_diff("cambiato", "testo", "12,00", "11,00"), 100)
    case = _open(qtbot, page, fake_core, tmp_path, [first])
    api = fake_core.officina
    page.review_action(_id_of(page, first), "fatta")
    _idle(qtbot, page)
    undo = page._window.actions[-1][2][1]
    api.set_canned(case.id, 2, [first])
    page.case_view.regenerate_button.click()
    wait_idle(qtbot, page)
    page.open_case(page.case_id, "v2")
    qtbot.waitUntil(lambda: page.case_view.docs is not None and page.case_view.docs.judged is not None
                    and page.case_view.docs.judged.version == 2, timeout=10000)
    _idle(qtbot, page)
    undo()
    _idle(qtbot, page)
    assert "unmark" not in _actions(api, case)


def test_a_queued_action_on_a_difference_gone_meanwhile_is_skipped(qtbot, page, fake_core, tmp_path,
                                                                   shell):
    first = placed(fake_diff("cambiato", "testo", "12,00", "11,00"), 100)
    case = _open(qtbot, page, fake_core, tmp_path, [first])
    api = fake_core.officina
    diff_id = _id_of(page, first)
    page.open_case(page.case_id)  # a compare runs: the request waits
    api.set_canned(case.id, 1, [])  # ... and that compare finds the difference gone
    page.review_action(diff_id, "fatta")
    _idle(qtbot, page)
    assert _actions(api, case) == []
    assert shell.statuses[-1] == strings.AZIONI_GONE.format(what="12,00")


def test_menu_fatta_marks(qtbot, page, fake_core, tmp_path):
    first = placed(fake_diff("cambiato", "testo", "12,00", "11,00"), 100)
    case = _open(qtbot, page, fake_core, tmp_path, [first])
    _menu_at(qtbot, page, first).action_for("fatta").trigger()
    _idle(qtbot, page)
    assert _actions(fake_core.officina, case) == ["mark_done"]


def test_menu_untolerates_a_difference_tolerated_by_hand(qtbot, page, fake_core, tmp_path):
    first = placed(fake_diff("cambiato", "testo", "12,00", "11,00"), 100)
    case = _open(qtbot, page, fake_core, tmp_path, [first])
    page.review_action(_id_of(page, first), "tollera")
    _idle(qtbot, page)
    menu = _menu_at(qtbot, page, first)
    entry = menu.action_for("tollera")
    assert entry.text() == strings.AZIONI_MENU_UNTOLERATE and entry.isEnabled()
    entry.trigger()
    _idle(qtbot, page)
    assert _actions(fake_core.officina, case) == ["tolerate", "untolerate"]
    assert not page._case(case.id).review.tolerances


def test_the_bars_more_button_opens_the_menu(qtbot, page, fake_core, tmp_path):
    first = placed(fake_diff("cambiato", "testo", "12,00", "11,00"), 100)
    _open(qtbot, page, fake_core, tmp_path, [first])
    view = page.case_view.right.view
    _click(view, _id_of(page, first))
    bar = page.case_view.bars["right"]
    bar.more_button.click()
    menu = page.case_view.menu
    assert menu is not None and menu.isVisible()
    assert menu.actions()[0].text() == strings.AZIONI_MENU_DONE
    menu.hide()


def test_the_toasts_button_never_takes_the_focus(qtbot):
    parent = QWidget()
    qtbot.addWidget(parent)
    toast = Toast(parent)
    assert toast.action_button.focusPolicy() == Qt.FocusPolicy.NoFocus


def test_a_refused_save_says_why_and_pushes_no_undo(qtbot, page, fake_core, tmp_path, shell):
    first = placed(fake_diff("cambiato", "testo", "12,00", "11,00"), 100)
    case = _open(qtbot, page, fake_core, tmp_path, [first])
    (case.folder / "caso.json").write_text("{rotto", encoding="utf-8")
    page.review_action(_id_of(page, first), "fatta")
    qtbot.waitUntil(lambda: not page.case_view.acting, timeout=10000)
    assert shell.statuses[-1].startswith(strings.ELENCO_ACTION_FAILED.format(reason="")[:10])
    assert len(page.undo) == 0


# ------------------------------------------------ U4 deferred minors (U5) ---

def _panel_rows():
    a = Judged(placed(fake_diff("cambiato", "testo", "Alfa", "Alf"), 100), "da_fare")
    b = Judged(placed(fake_diff("cambiato", "testo", "Beta", "Bet"), 200), "da_fare")
    m = Judged(placed(fake_diff("cambiato", "testo", "Mu", "M"), 300), "da_fare", marked=True)
    return a, b, m


def test_f_on_the_last_open_row_stays_there_not_in_the_marked_group(qtbot):
    a, b, m = _panel_rows()
    panel = DiffPanel()
    qtbot.addWidget(panel)
    panel.show_judged([a, b, m], 1, {})
    panel.select(b.diff.id)
    with qtbot.waitSignal(panel.action_requested) as got:
        panel.trigger("fatta")
    assert got.args == [b.diff.id, "fatta"]
    assert panel.current_id() == b.diff.id, "never into the dimmed DA VERIFICARE group"
    # the refresh: b is marked now; the selection stays among the open rows
    panel.show_judged([a, dataclasses.replace(b, marked=True), m], 1, {})
    assert panel.current_id() == a.diff.id


def test_f_twice_fast_on_the_last_open_row_marks_it_once(qtbot, monkeypatch):
    """U5 minor 4 (R42): the selection cannot move on from the last open row,
    so a second F before the refresh would be planned against the MARKED row
    and take the mark away: within 1 s it does nothing; later it toggles."""
    from qtrequestory.ui.pages import officina_diffs

    a, b, m = _panel_rows()
    panel = DiffPanel()
    qtbot.addWidget(panel)
    panel.show_judged([a, b, m], 1, {})
    panel.select(b.diff.id)
    clock = [100.0]
    monkeypatch.setattr(officina_diffs.time, "monotonic", lambda: clock[0])
    got: list = []
    panel.action_requested.connect(lambda *args: got.append(args))
    panel.trigger("fatta")
    clock[0] += 0.4
    panel.trigger("fatta")
    assert got == [(b.diff.id, "fatta")]
    clock[0] += officina_diffs.REPEAT_GUARD_S
    panel.trigger("fatta")
    assert got == [(b.diff.id, "fatta")] * 2, "a deliberate F later still toggles"


def test_the_arrows_still_walk_into_the_marked_group(qtbot):
    a, b, m = _panel_rows()
    panel = DiffPanel()
    qtbot.addWidget(panel)
    panel.show_judged([a, b, m], 1, {})
    panel.select(b.diff.id)
    panel.list.step(1)
    assert panel.current_id() == m.diff.id


def test_t_refused_on_a_row_the_profile_tolerates_does_not_move_on(qtbot, page, fake_core,
                                                                   tmp_path, shell):
    styled = [placed(fake_diff("cambiato", "stile", t, t, context=t), y)
              for t, y in (("Grassetto", 100), ("Corsivo", 200))]
    _open(qtbot, page, fake_core, tmp_path, styled)
    view = page.case_view
    view.diffs.set_tab("tollerate")
    first = _id_of(page, styled[0])
    view.diffs.select(first)
    view.diffs.list.setFocus()
    QTest.keyClick(view.diffs.list, Qt.Key.Key_T)
    assert view.diffs.current_id() == first, "refused: the selection stays"
    _idle(qtbot, page)
    assert any("tollerata dal profilo" in s for s in shell.statuses)
    assert view.diffs.current_id() == first
