"""Officina phase 2 (U3): the differences list of the case view — tabs with
counts, rows with verdict pill / class glyph / page / op / snippet, "in corso"
before/after, "non risolta" reason, the DA VERIFICARE group, the key legend,
and the keyboard (↑/↓, Enter, F / T / V) — spec §7.2.

Offscreen; the page-level tests run on the fake core (``compare_case``
scripted by canned diffs, the review state real).
"""
from __future__ import annotations

import dataclasses
import re

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import Anchor, Diff, Judged, Word
from qtrequestory.ui.pages.officina_diffs import DiffPanel
from qtrequestory.ui.pages.officina_page import OfficinaPage
from qtrequestory.ui.pages.officina_progress import glyph_html
from qtrequestory.ui.pages.officina_rows import (
    CONTEXT_WORDS,
    actions_for,
    class_glyph,
    fit_context,
    notes_for,
    snippet_html,
    snippet_plain,
    snippet_text,
    tab_counts,
    tab_rows,
)
from tests.fakes.fake_core import fake_diff
from tests.ui.test_officina_page import FakeWindow, open_case, wait_idle


def placed(diff, y: float, *, page: int = 0, side: str = "both"):
    left = (Word(diff.left_text or "x", page, 60, y, 140, y + 12),) if side in ("both", "left") else ()
    right = (Word(diff.right_text or "x", page, 60, y, 140, y + 12),) if side in ("both", "right") else ()
    return dataclasses.replace(diff, left=left, right=right)


def j(diff_id: int, verdict, y: float = 100.0, *, klass: str = "testo", op: str = "cambiato",
      target: str | None = None, generated: str | None = None, boxes: bool = True, **flags) -> Judged:
    diff = fake_diff(op, klass, target if target is not None else f"t{diff_id}",
                     generated if generated is not None else f"g{diff_id}", diff_id=diff_id)
    return Judged(placed(diff, y) if boxes else diff, verdict, **flags)


def one_letter(diff_id: int = 1, verdict="da_fare", y: float = 100.0) -> Judged:
    """"abilitata" → "abilitato": only the last letter changed."""
    diff = dataclasses.replace(fake_diff("cambiato", "testo", "abilitata", "abilitato", diff_id=diff_id),
                               left_spans=((8, 9),), right_spans=((8, 9),))
    return Judged(placed(diff, y), verdict)


#: One of every state: 2 regressioni, non risolta, 2 da fare, in corso, da verificare,
#: 2 fatte, 2 tollerate, 3 variabili, rumore.
CANNED = [
    j(1, "regressione", 100), j(2, "regressione", 110), j(3, "da_fare", 120, unresolved=True),
    j(4, "da_fare", 130), j(5, "da_fare", 140), j(6, "in_corso", 150, previous_text="prima"),
    j(7, "da_fare", 160, marked=True), j(8, "fatta", 170), j(9, "fatta", 180),
    j(10, "tollerata", 190), j(11, "tollerata", 200, klass="stile"),
    j(12, None, 210, klass="variabile"), j(13, None, 220, klass="variabile"),
    j(14, None, 230, klass="variabile"), j(15, None, 240, klass="rumore"),
]


# ------------------------------------------------------------------ tabs ---

def test_tab_counts_from_a_canned_comparison():
    assert tab_counts(CANNED) == {"guardare": 6, "verificare": 1, "fatte": 2, "tollerate": 2,
                                  "variabili": 3, "tutte": 15}


def test_da_guardare_puts_the_non_risolte_first_then_document_order_then_the_marked_group():
    rows = tab_rows("guardare", CANNED)
    ids = [r.diff.id if r is not None else None for r in rows]
    assert ids == [3, 1, 2, 4, 5, 6, None, 7], "None = the DA VERIFICARE group header"
    assert [r.diff.id for r in tab_rows("verificare", CANNED)] == [7]
    assert [r.diff.id for r in tab_rows("tutte", CANNED)] == list(range(1, 16))


def test_the_panel_shows_the_tabs_with_their_counts(qtbot):
    panel = DiffPanel()
    qtbot.addWidget(panel)
    panel.show_judged(CANNED, 3, {})
    assert panel.tab_texts() == ["Da guardare 6", "Da verificare 1", "Fatte 2", "Tollerate 2",
                                 "Variabili 3", "Tutte 15"]
    assert panel.current_tab() == "guardare"
    assert panel.row_ids() == [3, 1, 2, 4, 5, 6, 7]
    panel.set_tab("variabili")
    assert panel.row_ids() == [12, 13, 14]
    assert panel.legend.isVisible() or not panel.isVisible()
    assert strings.ELENCO_KEY_NOT_VARIABLE.replace(" ", "&nbsp;") in panel.legend.text()


# --------------------------------------------------------------- snippets ---

def _bold_chars(html: str) -> str:
    return "".join(re.findall(r"<b[^>]*>(.*?)</b>", html))


def _struck(html: str) -> str:
    return "".join(re.findall(r"<s[^>]*>(.*?)</s>", html))


def test_a_one_letter_diff_bolds_exactly_that_letter_on_yellow():
    html = snippet_html(one_letter().diff, theme.LIGHT)
    assert _bold_chars(html) == "o", "only the changed character is bold"
    assert _struck(html) == "a", "only the replaced target character is struck"
    assert theme.LIGHT.mark_yellow.lower() in html.lower()
    assert snippet_plain(one_letter().diff) == "abilitat[a→o]"


def test_on_dark_the_yellow_carries_dark_ink():
    html = snippet_html(one_letter().diff, theme.DARK)
    bold = re.search(r"<b style='([^']*)'", html).group(1).lower()
    assert theme.DARK.mark_yellow.lower() in bold
    assert theme.LIGHT.text.lower() in bold, "dark text on the bright yellow in both modes"


def framed_one_letter() -> Diff:
    """The draft's row: "sarà abilitat~~a~~**o** agli acquisti" (context from the fake, R33)."""
    return dataclasses.replace(
        fake_diff("cambiato", "testo", "abilitata", "abilitato", before="La carta sarà",
                  after="agli acquisti online."),
        left_spans=((8, 9),), right_spans=((8, 9),))


def test_the_snippet_shows_the_target_context_around_the_change():
    d = framed_one_letter()
    assert snippet_plain(d) == "La carta sarà abilitat[a→o] agli acquisti online."
    html = snippet_html(d, theme.LIGHT)
    assert _bold_chars(html) == "o" and _struck(html) == "a", "the context is neither bold nor struck"
    assert html.startswith("La carta sarà abilitat<s")
    assert html.endswith("</b> agli acquisti online.")


def test_context_words_are_cut_with_an_ellipsis():
    d = framed_one_letter()
    assert snippet_plain(d, before=1, after=2) == "… sarà abilitat[a→o] agli acquisti …"
    assert snippet_plain(d, before=0, after=0) == "… abilitat[a→o] …"
    assert snippet_text(d, before=1, after=0) == "… sarà abilitatao …"


def test_an_insertion_sits_between_its_context_words():
    d = fake_diff("in_piu", "testo", "", "Nota", before="il testo", after="segue qui")
    assert snippet_plain(d) == "il testo [→Nota] segue qui"


def test_fit_context_drops_words_until_the_line_fits():
    d = framed_one_letter()
    assert fit_context(d, 10_000, len) == (CONTEXT_WORDS, CONTEXT_WORDS)
    before, after = fit_context(d, len("… sarà abilitatao agli …"), len)
    assert (before, after) == (1, 1)
    assert fit_context(d, 3, len) == (0, 0), "the change itself always stays"


def test_the_struck_run_uses_paper_colours_in_both_themes_right_against_the_inserted_one():
    """R34: the target's letter must read on its own, also on dark chrome."""
    for tokens in (theme.LIGHT, theme.DARK):
        html = snippet_html(one_letter().diff, tokens)
        style = re.search(r"<s style='([^']*)'", html).group(1).lower()
        assert theme.LIGHT.bad.lower() in style and theme.LIGHT.bad_bg.lower() in style
        assert "font-weight:700" in style
        assert "</s><b" in html, "no gap: a hair space read as a space (U4)"


def test_a_whole_word_change_is_struck_then_bold_with_a_space():
    d = fake_diff("cambiato", "testo", "Acme-Servizi", "Acme")
    html = snippet_html(d, theme.LIGHT)
    assert _struck(html) == "Acme-Servizi" and _bold_chars(html) == "Acme"
    assert "</s> <b" in html
    assert theme.LIGHT.mark_yellow.lower() not in html.lower(), "no yellow for an entirely changed text"


def test_a_long_context_is_elided_around_the_change():
    target = "a" * 80 + " x " + "b" * 80
    generated = "a" * 80 + " y " + "b" * 80
    d = dataclasses.replace(fake_diff("cambiato", "testo", target, generated),
                            left_spans=((81, 82),), right_spans=((81, 82),))
    plain = snippet_plain(d)
    assert plain.startswith("…") and plain.endswith("…") and "[x→y]" in plain
    assert len(plain) < 80


def test_missing_and_added_texts():
    assert snippet_plain(fake_diff("mancante", "testo", "Titolo", "")) == "[Titolo→]"
    assert snippet_plain(fake_diff("in_piu", "testo", "", "Nota")) == "[→Nota]"


def test_an_unchanged_text_is_shown_plain():
    """A link / attribute difference: the visible text is the same on both
    sides (a link's own text is underlined, U4)."""
    d = fake_diff("cambiato", "link", "Scopri", "Scopri", detail="href: a → b")
    html = snippet_html(d, theme.LIGHT)
    assert html == "<u>Scopri</u>" and snippet_plain(d) == "Scopri"


def test_html_is_escaped():
    html = snippet_html(fake_diff("cambiato", "testo", "<a>", "&b"), theme.LIGHT)
    assert "<a>" not in html and "&lt;a&gt;" in html and "&amp;b" in html


# ------------------------------------------------------------------ notes ---

def test_non_risolta_says_where_it_was_marked():
    row = j(3, "da_fare", unresolved=True)
    assert notes_for(row, 4, {row.diff.anchor: 3}) == [
        ("Segnata fatta in v3, ma in v4 è ancora qui.", "bad")]
    assert notes_for(row, 4, {}) == [("Segnata fatta, ma in v4 è ancora qui.", "bad")]


def test_in_corso_shows_before_and_after():
    row = j(6, "in_corso", generated="addebitate", previous_text="addebitati")
    assert notes_for(row, 2, {}) == [("Prima «addebitati» → ora «addebitate»", "muted")]


def test_a_diff_without_boxes_is_listed_with_the_only_in_the_list_hint(qtbot):
    link = Judged(fake_diff("cambiato", "link", "Scopri", "Scopri", detail="href: a.example.invalid → b.example.invalid"),
                  "da_fare")
    texts = [t for t, _tone in notes_for(link, 1, {})]
    assert strings.ELENCO_ONLY_LIST in texts
    assert "href: a.example.invalid → b.example.invalid" in texts
    panel = DiffPanel()
    qtbot.addWidget(panel)
    panel.show_judged([link], 1, {})
    (text,) = panel.texts()
    assert strings.ELENCO_ONLY_LIST in text and "🔗" in text
    assert "pag." not in text.splitlines()[0], "no page for a difference without boxes"


# --------------------------------------------------------------- keyboard ---

def test_the_link_glyph_is_drawn_as_text_not_as_a_colour_emoji():
    """Minor 1: 🔗 + U+FE0E (text presentation) in the symbol font, one span."""
    glyph, _name = class_glyph(fake_diff("cambiato", "link", "a", "a"))
    assert glyph == "🔗︎"
    html = glyph_html(glyph)
    assert html.count("<span") == 1 and "🔗︎</span>" in html


def test_actions_for_each_state():
    assert actions_for(j(1, "da_fare")) == {"fatta", "tollera"}
    assert actions_for(j(1, "regressione", marked=True)) == {"fatta"}, "F again removes the mark"
    assert actions_for(j(1, "fatta")) == set()
    assert actions_for(j(1, "tollerata")) == {"tollera"}
    assert actions_for(j(1, None, klass="variabile")) == {"non_variabile"}
    turned = Judged(dataclasses.replace(j(1, "da_fare").diff,
                                        anchor=Anchor("cambiato", "variabile", "", "t1")), "da_fare")
    assert actions_for(turned) == {"fatta", "tollera", "non_variabile"}, "V again: a variable again"


@pytest.fixture
def panel(qtbot):
    widget = DiffPanel()
    qtbot.addWidget(widget)
    widget.resize(320, 700)
    widget.show()
    widget.show_judged(CANNED, 3, {})
    return widget


def test_arrows_move_and_skip_the_group_header(qtbot, panel):
    chosen = []
    panel.list.setFocus()  # Qt makes the first row current when the list takes the focus
    panel.select(6)
    panel.difference_chosen.connect(chosen.append)
    QTest.keyClick(panel.list, Qt.Key.Key_Down)
    assert panel.current_id() == 7, "past the DA VERIFICARE header"
    QTest.keyClick(panel.list, Qt.Key.Key_Down)
    assert panel.current_id() == 7, "the last row stays"
    QTest.keyClick(panel.list, Qt.Key.Key_Up)
    assert panel.current_id() == 6
    assert chosen == [7, 6]


def test_enter_activates_and_f_t_v_request_actions(qtbot, panel):
    activated, actions = [], []
    panel.activated.connect(activated.append)
    panel.action_requested.connect(lambda i, a: actions.append((i, a)))
    panel.list.setFocus()
    panel.select(4)
    QTest.keyClick(panel.list, Qt.Key.Key_Return)
    QTest.keyClick(panel.list, Qt.Key.Key_F)  # then the next row at once (R40)
    assert panel.current_id() == 5
    QTest.keyClick(panel.list, Qt.Key.Key_T)
    QTest.keyClick(panel.list, Qt.Key.Key_V)  # not a variable: nothing, and no move
    assert activated == [4]
    assert actions == [(4, "fatta"), (5, "tollera")]
    assert panel.current_id() == 6
    panel.set_tab("variabili")
    panel.select(12)
    QTest.keyClick(panel.list, Qt.Key.Key_F)  # a variable cannot be "fatta"
    assert panel.current_id() == 12
    QTest.keyClick(panel.list, Qt.Key.Key_V)
    QTest.keyClick(panel.list, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    assert actions[2:] == [(12, "non_variabile")]
    assert panel.current_id() == 13


def test_select_switches_to_a_tab_that_holds_the_difference(panel):
    panel.select(10)  # tollerata: not in "Da guardare"
    assert panel.current_tab() == "tollerate" and panel.current_id() == 10
    panel.select(15)  # rumore: only in "Tutte"
    assert panel.current_tab() == "tutte" and panel.current_id() == 15
    panel.select(7)  # already in "Tutte": the tab stays
    assert panel.current_tab() == "tutte" and panel.current_id() == 7


def test_a_refill_keeps_the_tab_and_moves_on_when_the_row_changed_state(panel):
    panel.select(4)
    refilled = [dataclasses.replace(r, marked=True) if r.diff.id == 4 else r for r in CANNED]
    panel.show_judged(refilled, 3, {})
    assert panel.current_tab() == "guardare"
    assert panel.current_id() == 5, "the marked one left the open rows: the next one is selected"
    panel.show_judged(refilled, 3, {})
    assert panel.current_id() == 5, "unchanged: the same row"


def test_empty_da_guardare_wording():
    assert strings.ELENCO_ALL_DONE.format(n=2) == "Niente da guardare: tutto fatto (2 fatte)."


def test_all_fatte_reads_all_done(qtbot):
    panel = DiffPanel()
    qtbot.addWidget(panel)
    panel.show_judged([j(1, "fatta"), j(2, "fatta")], 2, {})
    assert panel.summary.text() == strings.ELENCO_ALL_DONE.format(n=2)
    assert panel.row_ids() == []
    panel.show_judged([j(1, "da_fare", marked=True)], 2, {})
    assert panel.summary.text() == strings.ELENCO_ONLY_MARKED.format(n=1)
    assert panel.row_ids() == [1], "the marked ones stay listed in their group"


def test_a_theme_switch_recolours_the_snippets(qtbot, panel, monkeypatch):
    panel.show_judged([one_letter(1)], 3, {})
    assert theme.LIGHT.mark_yellow.lower() in panel.snippet_html(1).lower()
    monkeypatch.setattr(theme, "tokens", lambda: theme.DARK)
    theme.signals.changed.emit()
    assert theme.DARK.mark_yellow.lower() in panel.snippet_html(1).lower()
    assert theme.DARK.surface2.lower() in panel.legend.text().lower()


# ------------------------------------------------------------ page level ---

@pytest.fixture
def page(qtbot, fake_core, runner) -> OfficinaPage:
    widget = OfficinaPage(fake_core, runner, FakeWindow())
    qtbot.addWidget(widget)
    widget.resize(1300, 760)
    widget.show()
    return widget


def _open_v1(qtbot, page, fake_core, tmp_path, diffs):
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
    return case


def test_f_in_the_list_marks_the_difference_and_the_list_moves_on(qtbot, page, fake_core, tmp_path):
    first = placed(fake_diff("cambiato", "testo", "12,00", "11,00"), 100)
    second = placed(fake_diff("cambiato", "testo", "Titolo", "Titol"), 200)
    case = _open_v1(qtbot, page, fake_core, tmp_path, [first, second])
    view, api = page.case_view, fake_core.officina
    assert view.diffs.tab_texts()[:2] == ["Da guardare 2", "Da verificare 0"]
    view.diffs.list.setFocus()
    view.diffs.list.setCurrentRow(0)
    assert view.right.view.focused_difference() == view.diffs.current_id()
    calls = len(api.compare_case_calls)
    QTest.keyClick(view.diffs.list, Qt.Key.Key_F)  # saved in the review worker (U4)
    qtbot.waitUntil(lambda: len(api.compare_case_calls) > calls and not view.judging
                    and view.diffs.tab_texts()[1] == "Da verificare 1", timeout=10000)
    assert ("mark_done", case.id) in api.review_actions
    assert view.diffs.tab_texts()[0] == "Da guardare 1"
    marked = next(x for x in view.docs.judged.judged if x.marked)
    assert marked.diff.anchor == first.anchor
    assert view.diffs.current_id() != marked.diff.id, "the selection moved to the next open row"
    assert view.right.view.focused_difference() == view.diffs.current_id()
    calls = len(api.compare_case_calls)
    view.diffs.select(marked.diff.id)
    QTest.keyClick(view.diffs.list, Qt.Key.Key_F)  # again: the mark goes
    qtbot.waitUntil(lambda: len(api.compare_case_calls) > calls and not view.judging
                    and view.diffs.tab_texts()[1] == "Da verificare 0", timeout=10000)
    assert ("unmark", case.id) in api.review_actions


def test_t_tolerates_and_v_turns_a_variable_into_text(qtbot, page, fake_core, tmp_path):
    text = placed(fake_diff("cambiato", "testo", "12,00", "11,00"), 100)
    var = placed(fake_diff("cambiato", "variabile", "Nome", "Anna"), 200)
    case = _open_v1(qtbot, page, fake_core, tmp_path, [text, var])
    view, api = page.case_view, fake_core.officina
    view.diffs.list.setFocus()
    view.diffs.select(next(x.diff.id for x in view.docs.judged.judged if x.diff.anchor == text.anchor))
    calls = len(api.compare_case_calls)
    QTest.keyClick(view.diffs.list, Qt.Key.Key_T)
    qtbot.waitUntil(lambda: len(api.compare_case_calls) > calls and not view.judging
                    and view.diffs.tab_texts()[3] == "Tollerate 1", timeout=10000)
    assert ("tolerate", case.id) in api.review_actions
    view.diffs.select(next(x.diff.id for x in view.docs.judged.judged if x.diff.anchor == var.anchor))
    assert view.diffs.current_tab() == "variabili"
    calls = len(api.compare_case_calls)
    QTest.keyClick(view.diffs.list, Qt.Key.Key_V)
    qtbot.waitUntil(lambda: len(api.compare_case_calls) > calls and not view.judging
                    and view.diffs.tab_texts()[4] == "Variabili 0", timeout=10000)
    assert ("not_variable", case.id) in api.review_actions
    assert page._case(case.id).review.not_variables


def test_a_click_on_a_highlight_selects_the_row_in_its_tab(qtbot, page, fake_core, tmp_path):
    open_diff = placed(fake_diff("cambiato", "testo", "12,00", "11,00"), 100)
    styled = placed(fake_diff("cambiato", "stile", "Titolo", "Titolo"), 200)
    _open_v1(qtbot, page, fake_core, tmp_path, [open_diff, styled])
    view = page.case_view
    tolerated = next(x.diff.id for x in view.docs.judged.judged if x.verdict == "tollerata")
    view.right.view.difference_clicked.emit(tolerated)
    assert view.diffs.current_tab() == "tollerate" and view.diffs.current_id() == tolerated
    view.progress.diff_selected.emit(1)
    assert view.diffs.current_id() == 1


def test_enter_centres_the_difference_in_both_documents(qtbot, page, fake_core, tmp_path):
    """Minor 5: Enter "porta alla differenza" — both views scroll it to their
    middle, even when it was already (barely) on screen."""
    low = placed(fake_diff("cambiato", "testo", "12,00", "11,00"), 600)
    _open_v1(qtbot, page, fake_core, tmp_path, [low])
    view = page.case_view
    qtbot.waitUntil(lambda: view.right.view.difference_rect(1).isValid(), timeout=10000)
    view.diffs.list.setFocus()
    view.diffs.select(1)
    for doc in (view.left.view, view.right.view):
        bar = doc.verticalScrollBar()
        middle = doc.viewport().height() / 2
        # the ring on screen, near the bottom edge: visible, far from the middle
        y = doc.mapFromScene(doc.difference_rect(1).center()).y()
        bar.setValue(bar.value() + int(y - (2 * middle - 30)))
        y = doc.mapFromScene(doc.difference_rect(1).center()).y()
        assert doc.viewport().rect().contains(doc.mapFromScene(doc.difference_rect(1)).boundingRect())
        assert y > middle * 1.5, (y, middle)
    QTest.keyClick(view.diffs.list, Qt.Key.Key_Return)
    for doc in (view.left.view, view.right.view):
        assert doc.focused_difference() == 1
        middle = doc.viewport().height() / 2
        assert abs(doc.mapFromScene(doc.difference_rect(1).center()).y() - middle) < middle / 3


def test_a_tab_click_selects_its_first_row_and_keeps_the_keyboard(panel):
    chosen = []
    panel.difference_chosen.connect(chosen.append)
    panel.tab_buttons["tollerate"].click()
    assert panel.current_tab() == "tollerate" and panel.current_id() == 10
    assert chosen == [10]
    assert panel.list.hasFocus() or not panel.isActiveWindow()


def test_the_verdict_pills_share_one_width_and_the_legend_groups_never_break(panel):
    sizes = {panel.list.itemWidget(panel.list.item(r)).verdict.size().toTuple()
             for r in panel.list.selectable_rows()}
    assert len(sizes) == 1, "the class chips line up, every pill the same height"
    groups = panel.legend.text().split(" · ")
    assert len(groups) == 7, "↑↓ · Invio · F / doppio clic · T · V · clic destro · Ctrl+Z (U4)"
    for g in groups:
        assert " " not in re.sub(r"<[^>]*>", "", g), "only &nbsp; inside a group"


def test_a_narrow_row_shows_fewer_context_words(qtbot):
    panel = DiffPanel()
    qtbot.addWidget(panel)
    panel.show()
    d = framed_one_letter()
    panel.show_judged([Judged(d, "da_fare")], 1, {})
    panel.resize(900, 400)
    qtbot.wait(50)
    wide = panel.snippet_html(d.id)
    panel.resize(250, 400)
    qtbot.wait(50)
    narrow = panel.snippet_html(d.id)
    assert "La carta" in wide and "…" not in wide
    assert "…" in narrow and "abilitat" in narrow


def test_the_asis_view_keeps_the_plain_list_without_tabs(qtbot, page, fake_core, tmp_path):
    from tests.fakes.fake_core import canned_pdf

    open_case(page, fake_core, tmp_path)
    fake_core.officina.set_response(canned_pdf("MOD_TEST documento generato dal generatore vero"))
    page.case_view.asis_button.click()
    wait_idle(qtbot, page)
    page.open_case(page.case_id, "asis")
    qtbot.waitUntil(lambda: bool(page.case_view.diffs.texts()), timeout=10000)
    assert page.case_view.diffs.texts() == ["pag. 1 · cambiato\n«finto» → «vero»"]
    assert not page.case_view.diffs.tabs_visible()


def test_the_tutte_tab_counts_the_inactive_entries(qtbot):
    """Review Focus 4 / R30 (I1): tolerances, marks and not-variables that
    match nothing now (e.g. after a new target) are counted on "Tutte"."""
    panel = DiffPanel()
    qtbot.addWidget(panel)
    panel.show_judged(CANNED, 3, {}, inactive=2)
    tutte = panel.tab_buttons["tutte"]
    assert tutte.text() == strings.ELENCO_TAB_TUTTE_INACTIVE.format(n=len(CANNED), k=2)
    assert strings.ELENCO_TAB_TUTTE_INACTIVE_TIP.format(k=2) in tutte.toolTip()
    panel.show_judged(CANNED, 3, {})
    assert tutte.text() == strings.ELENCO_TAB_TUTTE.format(n=len(CANNED))
    assert tutte.toolTip() == strings.ELENCO_TAB_TUTTE_TIP


def test_the_case_view_passes_the_inactive_count_on(qtbot, fake_core, runner, tmp_path):
    from tests.ui.test_officina_page import FakeWindow, open_case
    from tests.ui.test_officina_progress import _open_version, placed
    from qtrequestory.ui.pages.officina_page import OfficinaPage

    page = OfficinaPage(fake_core, runner, FakeWindow())
    qtbot.addWidget(page)
    case = open_case(page, fake_core, tmp_path)
    api = fake_core.officina
    api.generate(page.ini, case, "tobe")
    page.refresh()
    first = placed(fake_diff("cambiato", "testo", "12,00", "11,00"), 100)
    api.set_canned(case.id, 1, [first])
    _open_version(qtbot, page, "v1", len(api.compare_case_calls), api)
    api.tolerate(page._case(case.id), page.case_view.docs.judged.judged[0])
    api.set_canned(case.id, 1, [placed(fake_diff("cambiato", "testo", "Titolo", "Titol"), 100)])
    _open_version(qtbot, page, "v1", len(api.compare_case_calls), api)
    assert page.case_view.docs.judged.inactive == 1
    assert page.case_view.diffs.tab_buttons["tutte"].text() == strings.ELENCO_TAB_TUTTE_INACTIVE.format(n=1, k=1)


# ------------------------------------------ the list without verdicts (I1 fix) ---

LINES = ["Condizioni generali di fornitura per il cliente di prova.",
         "Il prezzo della componente servizio resta fisso per dodici mesi.",
         "Le comunicazioni arrivano all'indirizzo example.invalid indicato."]


@pytest.fixture
def pdf_folder(qapp, tmp_path):
    from tests.officina import pdfgen

    font_id = pdfgen.load_font()
    if font_id is None:
        pytest.skip("no system font to generate PDFs with")
    yield tmp_path
    pdfgen.unload_font(font_id)


def _pair(folder, left_pt: float, right_pt: float, lines=LINES, **right):
    from qtrequestory.officina.compare.extract_pdf import extract
    from qtrequestory.officina.compare.pipeline import compare_docs
    from tests.officina import pdfgen

    a = extract(pdfgen.paragraphs_pdf(folder / "a.pdf", lines, font_pt=left_pt))
    b = extract(pdfgen.paragraphs_pdf(folder / "b.pdf", lines, font_pt=right_pt, **right))
    return compare_docs(a, b, right_label="AS-IS")


def test_the_list_without_verdicts_follows_the_profile(qtbot, pdf_folder):
    """I1 fix (Important 1): the AS-IS view / judge fallback lists only what
    the case's profile counts. Same words, another font size: nothing under
    Tollerante; under Stretto the rows say "stile", never «x» → «x»."""
    comparison = _pair(pdf_folder, 10, 13)
    assert comparison.diffs and {d.klass for d in comparison.diffs} <= {"stile", "spaziatura"}
    assert comparison.equal_for("tollerante") and comparison.equal
    assert not comparison.equal_for("stretto")
    panel = DiffPanel()
    qtbot.addWidget(panel)
    panel.show_comparison(comparison, "tollerante")
    assert panel.summary.text() == strings.OFFICINA_DIFF_EQUAL and not panel.list.isVisibleTo(panel)
    panel.show_comparison(comparison, "stretto")
    rows = [panel.list.item(i).text() for i in range(panel.list.count())]
    assert rows and all(strings.ELENCO_CLASS_STILE in r or strings.ELENCO_CLASS_SPAZIATURA in r for r in rows)
    assert not any("→" in r for r in rows), rows
    assert panel.summary.text() in (strings.OFFICINA_DIFF_COUNT_ANY.format(n=len(rows)),
                                    strings.OFFICINA_DIFF_COUNT_ANY_ONE), "not «differenze di testo»"


def test_a_reflow_lists_only_the_page_count_labelled_as_such(qtbot, pdf_folder):
    from tests.officina import pdfgen

    comparison = _pair(pdf_folder, 10, 15, [pdfgen.lorem(120, seed=n) for n in range(6)], width_mm=120)
    assert comparison.right_pages > comparison.left_pages, "the fixture must really reflow"
    panel = DiffPanel()
    qtbot.addWidget(panel)
    panel.show_comparison(comparison, "tollerante")
    rows = [panel.list.item(i).text() for i in range(panel.list.count())]
    assert len(rows) == 1 and strings.ELENCO_OP_PAGINE in rows[0], rows
    assert "contro" in rows[0] and strings.OFFICINA_KIND_CHANGED not in rows[0]


def test_the_asis_view_uses_the_cases_profile(qtbot, fake_core, runner, pdf_folder):
    """The AS-IS view of a case whose AS-IS differs from the target only in
    font size: "nessuna differenza di testo" under the (default) Tollerante
    profile, style rows once the case is Stretto; no highlight either way
    under Tollerante; accepting asks nothing."""
    from tests.officina import pdfgen

    page = OfficinaPage(fake_core, runner, FakeWindow())
    qtbot.addWidget(page)
    case = open_case(page, fake_core, pdf_folder)
    api = fake_core.officina
    target = pdfgen.paragraphs_pdf(pdf_folder / "target.pdf", LINES, font_pt=10)
    api.set_target(page._case(case.id), target)
    api.set_response(pdfgen.paragraphs_pdf(pdf_folder / "asis.pdf", LINES, font_pt=13).read_bytes())
    api.generate(page.ini, page._case(case.id), "asis")
    page.refresh()

    def open_asis():
        page.open_case(case.id, "asis")
        qtbot.waitUntil(lambda: page.case_view.docs is not None and page.case_view.docs.comparison is not None
                        and not page.case_view.judging, timeout=10000)

    open_asis()
    view = page.case_view
    assert view.docs.profile == "tollerante"
    assert view.diffs.summary.text() == strings.OFFICINA_DIFF_EQUAL
    assert view.acceptance_warning() == ""
    api.set_profile(page.ini, page._case(case.id), "stretto")
    page.refresh()
    open_asis()
    assert view.docs.profile == "stretto"
    rows = [view.diffs.list.item(i).text() for i in range(view.diffs.list.count())]
    assert rows and all(strings.ELENCO_CLASS_STILE in r or strings.ELENCO_CLASS_SPAZIATURA in r for r in rows)
    assert view.acceptance_warning() == strings.OFFICINA_ACCEPT_WITH_DIFFS
