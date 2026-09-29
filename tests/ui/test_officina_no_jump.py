"""Officina 2.5, U1 (spec §4.2): an action taken on the page never moves the
view. The mini-bar, the right-click menu, a double click and F / T / V in a
viewer act on the difference the user is looking at and leave the selection
on it (R40's "move on" is for F / T / V in the list only); "Togli il segno"
stays on the same difference after the refresh.

Page level on the fake core, like ``test_officina_review_actions``.
"""
from __future__ import annotations

import dataclasses

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import Judged
from qtrequestory.ui.pages.officina_diffs import DiffPanel
from qtrequestory.ui.pages.officina_rows import TABS
from tests.fakes.fake_core import fake_diff
from tests.ui.test_officina_review_actions import (  # noqa: F401 - fixtures
    _click,
    _id_of,
    _idle,
    _menu_at,
    _open,
    _panel_rows,
    _settle,
    page,
    placed,
    shell,
)


def _three(qtbot, page, fake_core, tmp_path):
    """Three differences far apart on the page, the documents zoomed in so
    that only the first is on screen."""
    diffs = [placed(fake_diff("cambiato", "testo", t, t[:-1]), y)
             for t, y in (("12,00", 100), ("Titolo", 420), ("Testo", 720))]
    _open(qtbot, page, fake_core, tmp_path, diffs)
    view = page.case_view
    view.right.view.set_zoom(2.0)
    for doc in (view.left.view, view.right.view):
        doc.verticalScrollBar().setValue(0)
        doc.horizontalScrollBar().setValue(0)
    return diffs


def _where(page) -> list[int]:
    view = page.case_view
    return [bar.value() for doc in (view.left.view, view.right.view)
            for bar in (doc.verticalScrollBar(), doc.horizontalScrollBar())]


def test_the_bars_fatta_keeps_the_selection_and_the_view(qtbot, page, fake_core, tmp_path):
    first, _second, _third = _three(qtbot, page, fake_core, tmp_path)
    view = page.case_view
    _click(view.right.view, _id_of(page, first))
    before = _where(page)
    view.bars["right"].done_button.click()
    assert view.diffs.current_id() == _id_of(page, first), "no move on from the page"
    _idle(qtbot, page)
    assert view.diffs.current_id() == _id_of(page, first), "still on it after the refresh"
    assert view.right.view.focused_difference() == _id_of(page, first)
    assert _where(page) == before


def test_togli_il_segno_stays_on_the_same_difference(qtbot, page, fake_core, tmp_path):
    _first, second, _third = _three(qtbot, page, fake_core, tmp_path)
    view = page.case_view
    doc = view.right.view
    doc.centerOn(doc.difference_rect(_id_of(page, second)).center())
    _click(doc, _id_of(page, second))
    view.bars["right"].done_button.click()
    _idle(qtbot, page)
    _click(doc, _id_of(page, second))
    bar = view.bars["right"]
    assert bar.done_button.text() == strings.AZIONI_BAR_UNMARK
    before = _where(page)
    bar.done_button.click()
    _idle(qtbot, page)
    assert not page._case(page.case_id).review.marks
    assert view.diffs.current_id() == _id_of(page, second), "not the last row"
    assert _where(page) == before


def test_the_menus_fatta_does_not_move_the_view(qtbot, page, fake_core, tmp_path):
    first, _second, _third = _three(qtbot, page, fake_core, tmp_path)
    view = page.case_view
    _click(view.right.view, _id_of(page, first))
    before = _where(page)
    _menu_at(qtbot, page, first).action_for("fatta").trigger()
    _idle(qtbot, page)
    assert view.diffs.current_id() == _id_of(page, first)
    assert _where(page) == before


def test_f_in_the_viewer_acts_without_moving_on(qtbot, page, fake_core, tmp_path):
    first, _second, _third = _three(qtbot, page, fake_core, tmp_path)
    view = page.case_view
    _click(view.right.view, _id_of(page, first))
    before = _where(page)
    QTest.keyClick(view.right.view, Qt.Key.Key_F)
    assert view.diffs.current_id() == _id_of(page, first)
    _idle(qtbot, page)
    assert page._case(page.case_id).review.marks
    assert view.diffs.current_id() == _id_of(page, first)
    assert _where(page) == before


def test_f_in_the_list_still_moves_on(qtbot, page, fake_core, tmp_path):
    first, second, _third = _three(qtbot, page, fake_core, tmp_path)
    view = page.case_view
    view.diffs.list.setFocus()
    view.diffs.select(_id_of(page, first))
    QTest.keyClick(view.diffs.list, Qt.Key.Key_F)
    assert view.diffs.current_id() == _id_of(page, second), "R40 in the list"
    _idle(qtbot, page)
    assert view.right.view.focused_difference() == view.diffs.current_id()


def test_a_followed_difference_is_kept_in_its_new_state(qtbot):
    """The panel: after an action from the page the refill keeps the same
    difference selected even though its state changed (no fallback row)."""
    a, b, _m = _panel_rows()
    m = Judged(placed(fake_diff("cambiato", "testo", "Mu", "M"), 150), "da_fare", marked=True)
    panel = DiffPanel()
    qtbot.addWidget(panel)
    panel.show_judged([a, m, b], 1, {})  # Alfa, Beta · DA VERIFICARE · Mu
    panel.select(m.diff.id)
    unmarked = [a, dataclasses.replace(m, marked=False), b]  # Alfa, Mu, Beta
    panel.show_judged(unmarked, 1, {})
    assert panel.current_id() == b.diff.id, "fixture: without following, the row at the same place"
    panel.show_judged([a, m, b], 1, {})
    panel.select(m.diff.id)
    panel.follow_current()
    panel.show_judged(unmarked, 1, {})
    assert panel.current_id() == m.diff.id


# -- fix round 1: the acted-upon difference stays put in every tab --------------------

def _row(text: str, y: float, verdict="da_fare", klass="testo", **flags) -> Judged:
    return Judged(placed(fake_diff("cambiato", klass, text, text[:-1]), y), verdict, **flags)


def _panel(qtbot, judged, tab: str, selected: Judged) -> DiffPanel:
    panel = DiffPanel()
    qtbot.addWidget(panel)
    panel.show_judged(judged, 1, {})
    panel.set_tab(tab)
    panel.select(selected.diff.id)
    panel.follow_current()  # what the case view does for a page / menu action
    return panel


def _is_dim(panel: DiffPanel, diff_id: int) -> bool:
    row = panel._row_of(diff_id)
    return panel.list.itemWidget(panel.list.item(row)).graphicsEffect() is not None


@pytest.mark.parametrize("tab, before, after", [
    ("verificare", {"marked": True}, {"marked": False}),        # Togli il segno
    ("tollerate", {"verdict": "tollerata"}, {"verdict": "da_fare"}),  # Non tollerare più
    ("fatte", {"verdict": "fatta"}, {"verdict": "regressione"}),
    ("variabili", {"verdict": None, "klass": "variabile"}, {"klass": "testo"}),  # Non è una variabile
])
def test_the_acted_upon_difference_stays_pinned_in_its_tab(qtbot, tab, before, after):
    klass = before.pop("klass", "testo")
    others = [_row("Alfa", 100, **before, klass=klass), _row("Omega", 500, **before, klass=klass)]
    acted = _row("Mu", 300, **before, klass=klass)
    panel = _panel(qtbot, [others[0], acted, others[1]], tab, acted)
    assert panel.current_id() == acted.diff.id
    diff = dataclasses.replace(acted.diff, klass=after.pop("klass", klass),
                               anchor=dataclasses.replace(acted.diff.anchor,
                                                          klass=after.get("klass", klass)))
    changed = dataclasses.replace(acted, diff=diff, **after)
    panel.show_judged([others[0], changed, others[1]], 1, {})
    assert panel.current_tab() == tab
    assert panel.current_id() == acted.diff.id, "still selected, not the next one"
    assert panel.row_ids() == [others[0].diff.id, acted.diff.id, others[1].diff.id], "at its place"
    assert _is_dim(panel, acted.diff.id) and not _is_dim(panel, others[0].diff.id)
    assert panel.tab_texts()[list(TABS).index(tab)].endswith(" 2"), "the count is the real one"


def test_a_tab_emptied_by_the_action_keeps_the_pinned_row(qtbot):
    only = _row("Mu", 300, marked=True)
    panel = _panel(qtbot, [_row("Alfa", 100), only], "verificare", only)
    panel.show_judged([_row("Alfa", 100), dataclasses.replace(only, marked=False)], 1, {})
    assert panel.current_id() == only.diff.id and not panel.list.isHidden()
    assert panel.row_ids() == [only.diff.id]


def test_choosing_another_row_or_tab_recomputes_the_tab(qtbot):
    others = [_row("Alfa", 100, marked=True), _row("Omega", 500, marked=True)]
    acted = _row("Mu", 300, marked=True)
    panel = _panel(qtbot, [others[0], acted, others[1]], "verificare", acted)
    unmarked = [others[0], dataclasses.replace(acted, marked=False), others[1]]
    panel.show_judged(unmarked, 1, {})
    panel.list.setCurrentRow(panel._row_of(others[1].diff.id))  # the user moves on
    qtbot.waitUntil(lambda: panel.row_ids() == [others[0].diff.id, others[1].diff.id], timeout=1000)
    assert panel.current_id() == others[1].diff.id
    # the same through a click on the page (select) and through a tab change
    panel = _panel(qtbot, [others[0], acted, others[1]], "verificare", acted)
    panel.show_judged(unmarked, 1, {})
    panel.select(others[0].diff.id)
    assert panel.row_ids() == [others[0].diff.id, others[1].diff.id]
    assert panel.current_id() == others[0].diff.id
    panel = _panel(qtbot, [others[0], acted, others[1]], "verificare", acted)
    panel.show_judged(unmarked, 1, {})
    panel.set_tab("guardare")
    panel.set_tab("verificare")
    assert acted.diff.id not in panel.row_ids()


def test_right_click_on_an_unselected_difference_follows_it(qtbot, page, fake_core, tmp_path):
    first, second, _third = _three(qtbot, page, fake_core, tmp_path)
    view = page.case_view
    _click(view.right.view, _id_of(page, first))
    before = _where(page)
    _menu_at(qtbot, page, first)  # opened on the first; now act on the second from its menu
    view.open_review_menu(_id_of(page, second), view.mapToGlobal(view.rect().center()))
    view.menu.action_for("fatta").trigger()
    _idle(qtbot, page)
    assert view.diffs.current_id() == _id_of(page, second)
    assert _where(page) == before, "the rings move, the view does not"


def test_two_views_converge_after_ctrl_wheel(qtbot, page, fake_core, tmp_path):
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication

    from qtrequestory.ui.pages.officina_sync import centre_x_fraction

    _three(qtbot, page, fake_core, tmp_path)
    left, right = page.case_view.left.view, page.case_view.right.view
    at = QPoint(left.viewport().width() - 40, 60)
    event = QWheelEvent(QPointF(at), QPointF(left.viewport().mapToGlobal(at)), QPoint(0, 0),
                        QPoint(0, 360), Qt.MouseButton.NoButton, Qt.KeyboardModifier.ControlModifier,
                        Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(left.viewport(), event)
    assert right.zoom() == pytest.approx(left.zoom())
    assert centre_x_fraction(right) == pytest.approx(centre_x_fraction(left), abs=0.02)
    assert right.relative_position()[0] == left.relative_position()[0]
    assert right.relative_position()[1] == pytest.approx(left.relative_position()[1], abs=0.01)


def test_following_never_lands_on_a_twin_with_the_same_text(qtbot):
    """Fix round 2: «Non è una variabile» changes the class, so the anchor
    alone cannot tell the acted-upon difference from an untouched twin with
    the same op, context and text: it is followed by its id first."""
    decoy = Judged(placed(fake_diff("cambiato", "testo", "12,00", "11,00"), 100), "da_fare")
    acted = Judged(placed(fake_diff("cambiato", "variabile", "12,00", "11,00"), 400), None)
    assert (decoy.diff.anchor.context, decoy.diff.anchor.target_text) == (
        acted.diff.anchor.context, acted.diff.anchor.target_text), "fixture: twins but for the class"
    acted = dataclasses.replace(acted, diff=dataclasses.replace(acted.diff, id=7))
    decoy = dataclasses.replace(decoy, diff=dataclasses.replace(decoy.diff, id=3))
    panel = _panel(qtbot, [decoy, acted], "variabili", acted)
    now_text = dataclasses.replace(
        acted, verdict="da_fare",
        diff=dataclasses.replace(acted.diff, klass="testo",
                                 anchor=dataclasses.replace(acted.diff.anchor, klass="testo")))
    panel.show_judged([decoy, now_text], 1, {})  # the twin comes first
    assert panel.current_id() == 7 and panel.row_ids() == [7]
    panel.set_tab("guardare")
    panel.select(7)
    panel.follow_current()
    panel.show_judged([decoy, dataclasses.replace(now_text, marked=True)], 1, {})
    assert panel.current_id() == 7
