"""Officina phase 2.5 (U3): the side panel of the case view — 292 px,
collapsible to a 40 px rail remembered for the session, short verdict tabs
never cut, the type chips (icon + name + number, zero dimmed, multi-select,
combined with the tab), the list grouped by type with foldable groups, rows
with zone and page, "arredo" never counted, the zones summary, the legend
behind «?», and the zone rails on the page margins (spec §5, D8, D9, D15, F3).

Offscreen; synthetic data only.
"""
from __future__ import annotations

import dataclasses

import pytest
from PySide6.QtCore import QRectF, Qt
from PySide6.QtTest import QTest

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import TIPI, Judged, ZoneBox
from qtrequestory.ui.pages.officina_diffs import DiffPanel
from qtrequestory.ui.pages.officina_minimap import document_segments
from qtrequestory.ui.pages.officina_panel_legend import legend_states
from qtrequestory.ui.pages.officina_side_panel import OPEN_WIDTH, RAIL_WIDTH, SESSION
from qtrequestory.ui.pages.officina_types import (
    ARREDO_GROUP,
    TYPE_ORDER,
    TYPES,
    TypeGroup,
    grouped,
    type_counts,
    zones_summary,
)
from qtrequestory.ui.pages.officina_verdict_style import LOOKS, state_of
from qtrequestory.ui.pages.officina_zone_rails import ZoneRail, ZoneRails
from tests.fakes.fake_core import fake_diff
from tests.ui.test_officina_diff_list import placed


def jt(diff_id: int, verdict, tipo: str, y: float, *, zone: str = "corpo", klass: str = "testo",
       **flags) -> Judged:
    diff = fake_diff("cambiato", klass, f"t{diff_id}", f"g{diff_id}", diff_id=diff_id, tipo=tipo, zone=zone)
    return Judged(placed(diff, y), verdict, **flags)


#: Two words, one zone change in the shoulder, one in the footer, a number,
#: a marked one, a variable and a page-number "arredo".
ROWS = [
    jt(1, "da_fare", "parola", 100), jt(2, "da_fare", "parola", 110, zone="footer"),
    jt(3, "da_fare", "zona", 120, zone="spalla_sx", klass="zona"), jt(4, "regressione", "numeri", 130),
    jt(5, "da_fare", "zona", 140, zone="header", klass="zona", marked=True),
    jt(6, None, "altro", 150, klass="variabile"),
    jt(7, None, "numeri", 160, zone="numero_pagina", klass="arredo"),
]


@pytest.fixture(autouse=True)
def _open_panel(monkeypatch):
    monkeypatch.setitem(SESSION, "collapsed", False)


@pytest.fixture
def panel(qtbot):
    widget = DiffPanel()
    qtbot.addWidget(widget)
    widget.resize(OPEN_WIDTH, 700)
    widget.show()
    widget.show_judged(ROWS, 2, {})
    return widget


# ------------------------------------------------------------------ pure ---

def test_every_type_has_an_icon_a_name_and_a_tip():
    assert set(TYPE_ORDER) == set(TIPI) == set(TYPES)
    assert all(info.icon and info.name and info.tip for info in TYPES.values())


def test_grouped_by_type_in_order_with_the_marked_group_after():
    from qtrequestory.ui.pages.officina_rows import tab_rows

    out = grouped(tab_rows("guardare", ROWS))
    shape = [(e.tipo, e.n) if isinstance(e, TypeGroup) else (e.diff.id if e is not None else None) for e in out]
    assert shape == [("parola", 2), 1, 2, ("zona", 1), 3, ("numeri", 1), 4, None, 5]
    folded = grouped(tab_rows("guardare", ROWS), folded={"parola"})
    assert folded[0] == TypeGroup("parola", 2, True) and folded[1] == TypeGroup("zona", 1)
    only = grouped(tab_rows("guardare", ROWS), frozenset({"zona"}))
    assert [e.diff.id for e in only if isinstance(e, Judged)] == [3, 5], "the chips filter the marked too"


def test_arredo_is_only_in_tutte_in_its_own_group_and_never_counted():
    from qtrequestory.ui.pages.officina_rows import tab_rows

    tutte = grouped(tab_rows("tutte", ROWS))
    assert isinstance(tutte[-2], TypeGroup) and tutte[-2].tipo == ARREDO_GROUP and tutte[-1].diff.id == 7
    assert type_counts(tab_rows("tutte", ROWS))["numeri"] == 1, "the page number is not a Numeri"
    assert all(ARREDO_GROUP != e.tipo for e in grouped(tab_rows("tutte", ROWS), frozenset({"numeri"}))
               if isinstance(e, TypeGroup))
    assert state_of(ROWS[6]) == "arredo" and LOOKS["arredo"] not in (LOOKS["rumore"], LOOKS["nessuno"])
    segments = document_segments([(ROWS[6], "left")], show_done=False, page_tops=[0.0], height=900.0)
    assert segments == [], "no minimap segment for arredo (F3)"


def test_the_zones_summary_says_ok_or_how_many_and_that_page_and_watermark_are_ignored():
    boxes = [ZoneBox(0, "header", 0, 0, 500, 40), ZoneBox(0, "titolo", 0, 50, 500, 70),
             ZoneBox(0, "filigrana", 100, 300, 400, 500)]
    text, known = zones_summary(ROWS, boxes)
    assert known
    assert text == "Header ✓ · Titolo ✓ · Spalla sx 1 · Footer 1 · pag. e filigrana ignorate"
    assert zones_summary([], []) == (strings.PANNELLO_ZONES_NONE, False)


# ------------------------------------------------------------------ panel ---

def test_the_panel_is_292_px_and_collapses_to_a_40_px_rail_for_the_session(qtbot, panel):
    assert panel.width() == OPEN_WIDTH and not panel.is_collapsed()
    panel.collapse_button.click()
    assert panel.width() == RAIL_WIDTH and panel.is_collapsed()
    assert panel.rail.isVisible() and not panel.body.isVisible()
    assert panel.rail.buttons["guardare"].text() == "4"
    assert {b.accessibleName() for b in panel.rail.buttons.values()} >= {
        strings.PANNELLO_EXPAND_NAME, strings.PANNELLO_RAIL_TYPES_NAME, strings.PANNELLO_RAIL_ZONES_NAME,
        strings.PANNELLO_LEGEND_NAME}
    other = DiffPanel()
    qtbot.addWidget(other)
    assert other.is_collapsed() and other.width() == RAIL_WIDTH, "remembered for the session"
    panel.set_tab("tutte")
    panel.rail.buttons["guardare"].click()
    assert not panel.is_collapsed() and panel.current_tab() == "guardare"


def test_the_tabs_are_short_whole_names_for_accessibility_and_never_cut(qtbot, panel):
    assert panel.tab_labels() == ["Da guardare 4", "Verif. 1", "Fatte 0", "Toll. 0", "Var. 1", "Tutte 6"]
    assert panel.tab_texts()[1] == "Da verificare 1"
    qtbot.wait(20)
    for button in panel.tab_buttons.values():
        assert button.width() >= button.sizeHint().width(), button.text()
        assert button.geometry().right() <= panel.tabs.width(), button.text()
    tip = panel.tab_buttons["tutte"].toolTip()
    assert strings.PANNELLO_TUTTE_ARREDO_TIP.format(n=1) in tip, "arredo is not in the number"


def test_the_chips_show_icon_name_and_count_per_tab_and_are_reachable(panel):
    chips = panel.chips.chips
    assert list(chips) == list(TYPE_ORDER)
    assert (chips["parola"].n, chips["zona"].n, chips["numeri"].n, chips["frase"].n) == (2, 2, 1, 0)
    assert chips["parola"].text() == "Parole 2" and chips["parola"].info.icon == "Aa"
    assert chips["parola"].accessibleName() == strings.PANNELLO_CHIP_NAME.format(name="Parole", n=2)
    assert all(c.focusPolicy() & Qt.FocusPolicy.TabFocus for c in chips.values())
    panel.set_tab("tutte")
    assert chips["zona"].n == 2 and chips["numeri"].n == 1 and chips["altro"].n == 1


def test_a_chip_counts_every_row_it_filters_marked_ones_too(panel):
    """M3: in "Da guardare" the zona chip counts the open row AND the marked
    one of the DA VERIFICARE group, the two rows it leaves when on."""
    assert panel.chips.chips["zona"].n == 2
    panel.chips.chips["zona"].click()
    assert panel.row_ids() == [3, 5]


def test_only_chips_with_rows_show_the_rest_behind_plus_k_altri(qtbot, panel):
    """I1: the band stays short — the zero chips wait behind "+k altri",
    which names them and unfolds them inline, dimmed (D9: every type still
    counts and can be chosen)."""
    chips, more = panel.chips.chips, panel.chips.more
    shown = [t for t, c in chips.items() if not c.isHidden()]
    assert shown == ["parola", "zona", "numeri"]
    assert panel.chips.heightForWidth(OPEN_WIDTH) <= 2 * 20 + 3 + 2 * 8, "one or two short rows"
    hidden = [t for t in TYPE_ORDER if t not in shown]
    assert not more.isHidden() and more.text() == strings.PANNELLO_CHIPS_MORE.format(k=len(hidden))
    assert all(TYPES[t].name in more.accessibleName() for t in hidden)
    assert more.focusPolicy() & Qt.FocusPolicy.TabFocus
    more.click()
    assert all(not c.isHidden() for c in chips.values()) and more.text() == strings.PANNELLO_CHIPS_LESS
    chips["frase"].click()  # a zero chip that is on stays shown when folded again
    more.click()
    assert not chips["frase"].isHidden() and chips["spazi"].isHidden()


def test_chips_are_multi_select_and_combine_with_the_tab(panel):
    panel.chips.chips["zona"].click()
    assert panel.row_ids() == [3, 5]
    panel.chips.chips["numeri"].click()
    assert panel.row_ids() == [3, 4, 5]
    panel.set_tab("variabili")
    assert panel.row_ids() == [] and panel.summary.text() == strings.PANNELLO_EMPTY_TYPES
    panel.chips.chips["zona"].click()
    panel.chips.chips["numeri"].click()
    assert panel.row_ids() == [6]


def test_a_group_folds_with_enter_space_or_a_click_and_the_arrows_reach_its_header(qtbot, panel):
    panel.list.setFocus()
    panel.select(1)
    QTest.keyClick(panel.list, Qt.Key.Key_Up)
    assert panel.current_id() is None and panel._current_group() == "parola"
    QTest.keyClick(panel.list, Qt.Key.Key_Return)
    assert panel.row_ids() == [3, 4, 5] and panel.groups()[0].folded
    QTest.keyClick(panel.list, Qt.Key.Key_F)  # on a header: nothing
    QTest.keyClick(panel.list, Qt.Key.Key_Space)
    assert panel.row_ids() == [1, 2, 3, 4, 5]
    panel._on_item_clicked(panel.list.item(0))
    assert panel.row_ids() == [3, 4, 5]
    panel.select(2)  # from a viewer: its group opens again
    assert panel.current_id() == 2 and not panel.groups()[0].folded


def test_select_brings_back_a_row_the_chips_hide(panel):
    panel.chips.chips["zona"].click()
    panel.select(1)
    assert panel.current_id() == 1 and panel.chips.selected() == frozenset()


def test_a_row_says_its_zone_and_page(panel):
    row = panel.list.itemWidget(panel.list.item(panel._row_of(2)))
    assert row.where.text() == "Footer · pag. 1"
    assert row.where.toolTip() == "pag. 1 · cambiato"


def test_the_legend_shows_every_verdict_look_and_type_icon(qtbot, panel):
    panel.footer.legend_button.click()
    assert panel.popover.isVisible()
    texts = " ".join(label.text() for label in panel.popover.findChildren(type(panel.summary)))
    for state in legend_states():
        assert LOOKS[state].label in texts, state
    for info in TYPES.values():
        assert info.tip in texts
    assert strings.ELENCO_KEY_NOT_VARIABLE.replace(" ", "&nbsp;") in panel.legend.text()
    panel.popover.hide()


def test_the_zones_summary_is_at_the_bottom(panel):
    panel.set_zones([ZoneBox(0, "header", 0, 0, 500, 40)])
    assert panel.zones_text().startswith("Header ✓ · Spalla sx 1 · Footer 1")


# ------------------------------------------------------------- zone rails ---

def test_zone_rails_are_thin_lines_on_the_page_margin_with_the_name_on_hover(qtbot):
    from PySide6.QtWidgets import QGraphicsScene

    scene = QGraphicsScene()
    rails = ZoneRails(scene)
    page = QRectF(12, 12, 595, 842)
    rails.show([ZoneBox(0, "header", 40, 20, 550, 60), ZoneBox(0, "corpo", 40, 80, 550, 700),
                ZoneBox(3, "footer", 0, 800, 595, 830)], [page])
    (rail,) = rails.items
    assert isinstance(rail, ZoneRail) and rail.zone == "header"
    assert rail.rect().right() < page.left() and rail.rect().width() <= 4
    assert rail.rect().top() == page.top() + 20 and rail.rect().bottom() == page.top() + 60
    assert rail.toolTip() == strings.PANNELLO_RAIL_TIP.format(zone="Header", page=1)
    rails.clear()
    assert rails.items == [] and not scene.items()


def test_the_case_view_draws_the_zones_of_the_comparison(qtbot, fake_core, runner, tmp_path):
    from qtrequestory.ui.pages.officina_page import OfficinaPage
    from tests.ui.test_officina_diff_list import _open_v1
    from tests.ui.test_officina_page import FakeWindow

    page = OfficinaPage(fake_core, runner, FakeWindow())
    qtbot.addWidget(page)
    page.resize(1366, 700)
    page.show()
    diffs = [dataclasses.replace(placed(fake_diff("cambiato", "zona", "Ed. 05", "Ed. 01"), 100),
                                 zone="spalla_sx", tipo="zona")]
    zones = (ZoneBox(0, "spalla_sx", 5, 90, 15, 400), ZoneBox(0, "header", 40, 10, 550, 40))
    from tests.fakes.fake_verdict import fake_comparison

    _open_v1(qtbot, page, fake_core, tmp_path, fake_comparison(diffs, left_zones=zones, right_zones=zones[:1]))
    view = page.case_view
    assert [r.zone for r in view.left.view.zone_rails.items] == ["spalla_sx", "header"]
    assert [r.zone for r in view.right.view.zone_rails.items] == ["spalla_sx"]
    assert view.diffs.zones_text() == "Header ✓ · Spalla sx 1"
    assert view.diffs.width() == OPEN_WIDTH


def test_filling_the_list_never_shows_a_stray_window(qtbot, panel):
    """D7: a row's class glyph is shown only once it is in the row (a
    parentless label made visible is a top-level window for a moment; it
    took the keyboard focus from the case window)."""
    from PySide6.QtCore import QEvent, QObject
    from PySide6.QtWidgets import QApplication

    shown = []

    class Watch(QObject):
        def eventFilter(self, obj, event):  # noqa: N802 - Qt naming
            if event.type() == QEvent.Type.Show and getattr(obj, "isWindow", lambda: False)() and obj is not panel:
                shown.append(type(obj).__name__)
            return False

    watch = Watch()
    QApplication.instance().installEventFilter(watch)
    try:
        panel.set_tab("tutte")
        panel.show_judged(ROWS, 2, {})
    finally:
        QApplication.instance().removeEventFilter(watch)
    assert shown == []


def test_the_asis_view_draws_every_listed_row_so_each_one_rings_and_scrolls(qtbot, fake_core, runner, tmp_path):
    """I2 (U3 fix round 1, D15): in the AS-IS view every row of the list is
    drawn on the pages in its own look — tolerated by the profile, variable,
    noise, page number — so selecting it rings a box on both pages and
    scrolls there, exactly as in the TO-BE views."""
    from qtrequestory.ui.pages.officina_page import OfficinaPage
    from tests.fakes.fake_verdict import fake_comparison
    from tests.ui.test_officina_page import FakeWindow, open_case

    page = OfficinaPage(fake_core, runner, FakeWindow())
    qtbot.addWidget(page)
    page.resize(1366, 700)
    page.show()
    case = open_case(page, fake_core, tmp_path)
    api = fake_core.officina
    api.generate(page.ini, page._case(case.id), "asis")
    others = {"stile": 780.0, "variabile": 60.0, "rumore": 790.0, "arredo": 50.0}
    diffs = [placed(fake_diff("cambiato", "testo", "12,00", "11,00"), 400)]
    diffs += [placed(fake_diff("cambiato", klass, f"t-{klass}", f"g-{klass}"), y) for klass, y in others.items()]
    api.set_comparison(fake_comparison(diffs))
    page._reload_initiative()
    page.open_case(case.id, "asis")
    view = page.case_view
    qtbot.waitUntil(lambda: view.docs is not None and view.docs.right.version is not None
                    and view.docs.right.version.kind == "asis" and bool(view.diffs.row_ids()), timeout=10000)
    drawn = {state_of(j) for j, _side in view.right.view._items}
    assert drawn == {"da_fare", "tollerata", "variabile", "rumore", "arredo"}, "every listed row is on the page"
    view.diffs.set_tab("tutte")
    for d in diffs[1:]:
        view.diffs.list.setCurrentRow(view.diffs.list_row(d.id))
        qtbot.wait(20)
        for doc in (view.left.view, view.right.view):
            ring = doc.focus_ring()
            assert doc.focused_difference() == d.id and ring.isVisible(), d.klass
            shown = doc.mapToScene(doc.viewport().rect()).boundingRect()
            assert shown.intersects(ring.sceneBoundingRect()), f"{d.klass}: scrolled to its box"


# ------------------------------------------------- compact rows (fix round 1) ---

def test_a_row_is_one_line_with_an_icon_pill_and_the_second_line_only_when_selected(qtbot):
    """I1: the verdict is its icon (the word is the tooltip and the
    accessible name); "Prima «…» → ora «…»" and the other notes show only
    on the selected row (and always in the row's tooltip)."""
    rows = [jt(1, "da_fare", "parola", 100), jt(2, "in_corso", "parola", 110, previous_text="prima"),
            jt(3, "regressione", "parola", 120)]
    panel = DiffPanel()
    qtbot.addWidget(panel)
    panel.resize(OPEN_WIDTH, 700)
    panel.show()
    panel.show_judged(rows, 2, {})

    def widget(diff_id):
        return panel.list.itemWidget(panel.list.item(panel.list_row(diff_id)))

    first = widget(1)
    assert first.verdict.text() != "" and strings.VERDETTO_DA_FARE not in first.verdict.text()
    assert first.verdict.accessibleName() == strings.VERDETTO_DA_FARE == first.verdict.toolTip()
    assert first.where.text() == "corpo · pag. 1"
    assert not first.snippet.wordWrap()
    note = strings.ELENCO_IN_CORSO.format(before="prima", now="g2")
    assert not widget(2).is_expanded() and note in panel.list.item(panel.list_row(2)).toolTip()
    one_line = panel.list.item(panel.list_row(2)).sizeHint().height()
    panel.list.setCurrentRow(panel.list_row(2))
    assert widget(2).is_expanded() and note in widget(2).notes
    assert panel.list.item(panel.list_row(2)).sizeHint().height() > one_line
    panel.list.setCurrentRow(panel.list_row(3))
    assert not widget(2).is_expanded() and widget(3).is_expanded(), "only the selected row"
    assert panel.list.item(panel.list_row(2)).sizeHint().height() == one_line


def test_the_tabs_are_equal_columns_and_the_collapse_button_is_not_among_them(qtbot, panel):
    qtbot.wait(20)
    widths = {b.width() for b in panel.tab_buttons.values()}
    assert len(widths) == 1, "equal columns"
    assert not panel.tabs.isAncestorOf(panel.collapse_button)
    assert panel.footer.isAncestorOf(panel.collapse_button)


# ------------------------------------------- follow / pin across groups (M1, M2) ---

def test_a_pinned_row_comes_back_under_its_own_type_header(panel):
    """M1: act on a Zone row in "Verif." (its mark removed): it stays, dimmed,
    under a "Zone" header — never under the header of another type."""
    marked = [dataclasses.replace(r, marked=True) if r.diff.id == 1 else r for r in ROWS]
    panel.show_judged(marked, 2, {})
    panel.set_tab("verificare")
    assert [g.tipo for g in panel.groups()] == ["parola", "zona"] and panel.row_ids() == [1, 5]
    panel.select(5)
    panel.follow_current()
    unmarked = [dataclasses.replace(r, marked=False) if r.diff.id == 5 else r for r in marked]
    panel.show_judged(unmarked, 2, {})
    assert panel.current_id() == 5 and panel._pinned == 5
    shape = [(e.tipo if isinstance(e, TypeGroup) else e.diff.id) for e in panel._rows]
    assert shape == ["parola", 1, "zona", 5], "under its own Zone header, not under Parole"


def test_f_walks_from_the_last_row_of_a_group_into_the_next_group(qtbot, panel):
    """M2 (b): R40 across a group header."""
    actions = []
    panel.action_requested.connect(lambda i, a: actions.append((i, a)))
    panel.list.setFocus()
    panel.select(2)  # the last Parole row
    QTest.keyClick(panel.list, Qt.Key.Key_F)
    assert actions == [(2, "fatta")] and panel.current_id() == 3, "the first Zone row, past its header"


def test_the_arrows_stop_on_type_headers_but_skip_the_da_verificare_one(qtbot, panel):
    """M2 (c)."""
    panel.list.setFocus()
    panel.select(4)  # the last open row (Numeri), then DA VERIFICARE, then 5
    QTest.keyClick(panel.list, Qt.Key.Key_Down)
    assert panel.current_id() == 5, "the DA VERIFICARE header is skipped"
    panel.select(3)
    QTest.keyClick(panel.list, Qt.Key.Key_Up)
    assert panel.current_id() is None and panel._current_group() == "zona", "a type header is a stop"


def test_a_followed_row_survives_a_chip_filter_and_a_fold_elsewhere(panel):
    """M2 (d): the followed difference stays selected when the chips or a
    fold change the list around it."""
    panel.select(3)
    panel.follow_current()
    panel.chips.chips["zona"].click()
    assert panel.current_id() == 3
    panel.chips.chips["zona"].click()
    panel.toggle_group("parola")
    assert panel.current_id() == 3 and panel.groups()[0].folded


def test_elide_pieces_cuts_from_the_end_with_an_ellipsis():
    from qtrequestory.ui.pages.officina_rows import elide_pieces

    pieces = [("ctx", "prima "), ("del", "vecchio"), ("ins", "nuovo"), ("ctx", " dopo dopo dopo")]
    assert elide_pieces(pieces, 1000, len, len) == pieces, "it fits: untouched"
    cut = elide_pieces(pieces, 20, len, len)
    assert cut[-1] == ("gap", "…") and sum(len(t) for _k, t in cut) <= 20
    assert ("del", "vecchio") in cut and ("ins", "nuovo") in cut, "the trailing context goes first"


def test_a_long_row_ends_in_an_ellipsis_and_its_zone_and_page_stay_whole(qtbot):
    """D5: a row never ends mid-glyph: the snippet is elided with "…" to the
    room left beside the pill and the zone · page, which is always whole."""
    from PySide6.QtGui import QFont, QFontMetrics, QTextDocument

    long_text = "Acme-Servizi S.p.A. società soggetta a direzione e coordinamento"
    diff = dataclasses.replace(
        placed(fake_diff("cambiato", "zona", long_text, long_text.upper(), diff_id=1, zone="spalla_sx",
                         tipo="zona"), 100),
        context_before="parole prima del cambio", context_after="parole dopo il cambio sulla stessa riga")
    panel = DiffPanel()
    qtbot.addWidget(panel)
    panel.resize(OPEN_WIDTH, 700)
    panel.show()
    panel.show_judged([Judged(diff, "da_fare")], 2, {})
    qtbot.wait(20)
    row = panel.list.itemWidget(panel.list.item(panel.list_row(1)))
    def shown() -> str:
        doc = QTextDocument()
        doc.setHtml(panel.snippet_html(1))
        return doc.toPlainText()

    assert shown().endswith("…"), shown()
    assert row.where.text() == "Spalla sx · pag. 1" and row.where.width() >= row.where.sizeHint().width()
    assert row.snippet.geometry().right() < row.where.geometry().left(), "the zone · page keeps its room"
    width = row.where.sizeHint().width() + row.verdict.width() + 700
    row.fit(width)  # more room: the change, then "…" for the trailing context
    assert "Acme" in shown() and shown().endswith("…") and "stessa riga" not in shown()
    bold = QFont(row.snippet.font())
    bold.setBold(True)
    assert QFontMetrics(bold).horizontalAdvance(shown()) <= 700, "never wider than its room"
