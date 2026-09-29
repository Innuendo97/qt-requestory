"""Officina phase 2.5 (U2): the compact case bar (spec §5, D15, draft "f25-caso-v2").

ONE 36 px bar over the documents — ‹ · case · AS-IS/v1/v2 · "= AS-IS" ·
compact progress · chips · Rigenera (F5) · Filtri (n) · ⋯ — the documents
right under it, and the AS-IS drawn in the same visual language ("da fare").
Offscreen, on the fake core (``compare_case`` scripted by canned diffs).
"""
from __future__ import annotations

import dataclasses

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QToolButton

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import Judged, Verification
from qtrequestory.ui.pages.officina_case_bar import BAR_HEIGHT, same_as_asis
from qtrequestory.ui.pages.officina_page import OfficinaPage
from qtrequestory.ui.pages.officina_verdict_style import state_of
from tests.fakes.fake_core import fake_comparison, fake_diff
from tests.fakes.fake_filters import fake_group
from tests.ui.test_officina_page import FakeWindow, open_case, wait_idle
from tests.ui.test_officina_progress import _open_version, placed

#: The case view's size inside the 1366x768 window: the app header (~46 px),
#: the page margins and the status bar take the rest (measured on the real
#: window by scripts/dev/shoot.py: the view starts at y=58).
VIEW_W, VIEW_H = 1342, 690
#: The documents start at most this far under the case view's top (spec §5, D15).
DOCS_TOP_MAX = 80


@pytest.fixture
def page(qtbot, fake_core, runner) -> OfficinaPage:
    widget = OfficinaPage(fake_core, runner, FakeWindow())
    qtbot.addWidget(widget)
    widget.resize(VIEW_W, VIEW_H)
    widget.show()
    return widget


def _v1(qtbot, page, fake_core, tmp_path):
    case = open_case(page, fake_core, tmp_path)
    page.case_view.regenerate_button.click()
    wait_idle(qtbot, page)
    return case


def _docs_top(view) -> int:
    return view.left.view.mapTo(view, QPoint(0, 0)).y()


# ------------------------------------------------------------ the layout ---

def test_the_documents_start_within_80_px_of_the_case_view_top(qtbot, page, fake_core, tmp_path):
    """Every message on at once — marks, verification outcome, two-way, an
    AS-IS older than the call, a failed generation, a loading note, "= AS-IS",
    a send running — and the documents still start right under the one bar."""
    case = _v1(qtbot, page, fake_core, tmp_path)
    api = fake_core.officina
    todo = placed(fake_diff("cambiato", "testo", "12,00", "11,00"), 100)
    api.set_canned(case.id, 1, [todo])  # no AS-IS entry: two-way
    _open_version(qtbot, page, "v1", len(api.compare_case_calls), api)
    api.mark_done(page._case(case.id), page.case_view.docs.judged.judged[0], 1)
    _open_version(qtbot, page, "v1", len(api.compare_case_calls), api)
    view = page.case_view
    view.set_failure("il generatore ha risposto 502")
    view.notice.set_message("nota di caricamento", strings.BARRA_NOTICE)
    view.call_strip.set_message(strings.CHIAMATA_STALE_ASIS, strings.BARRA_STALE_ASIS)
    view.progress.set_outcome(("v1: 0/1 risolte", "v1: verificata 1 modifica segnata", "warn"))
    view.bar.set_same_as_asis("v1", "svil")
    view.busy.setText(strings.OFFICINA_GENERATING_ON.format(env="svil"))
    view.busy.setVisible(True)
    view.resize(VIEW_W, VIEW_H)
    qtbot.wait(50)
    assert view.bar.height() == BAR_HEIGHT
    assert view.bar.mapTo(view, QPoint(0, 0)).y() == 0
    assert not view.progress.two_way.isHidden() and view.banners.marks_text()
    assert not view.bar.same_chip.isHidden() and not view.busy.isHidden()
    top = _docs_top(view)
    assert top <= DOCS_TOP_MAX, f"the documents start {top} px under the case view's top"
    assert _docs_top(view) == view.right.view.mapTo(view, QPoint(0, 0)).y(), "pages line up"


def test_the_bar_holds_one_row_and_the_rest_is_in_the_more_menu(qtbot, page, fake_core, tmp_path):
    _v1(qtbot, page, fake_core, tmp_path)
    view = page.case_view
    assert view.regenerate_button.text() == strings.BARRA_REGENERATE
    assert view.regenerate_button.property("role") == "primary"
    assert view.title.text() == "MOD_TEST_A"
    assert strings.OFFICINA_CASE_ENV.format(env="").strip() in view.title.toolTip()
    menu = view.more_button.menu()
    texts = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert texts == [strings.OFFICINA_GENERATE_ASIS, strings.OFFICINA_CHOOSE_TARGET,
                     strings.OFFICINA_PAYLOAD_HEADERS, strings.CHIAMATA_CHANGE,
                     view.profile_menu.title(), strings.CASO_RESET_TOLERANCES,
                     strings.BARRA_UNMARK_ALL, strings.OFFICINA_MARK_ACCEPTED]
    assert view.profile_menu.title().startswith(strings.BARRA_PROFILE.format(profile="")[:8])
    assert not view.unmark_action.isEnabled(), "no marks: nothing to undo"
    assert strings.RUMORE_BUTTON not in texts, "U4: one entry point, Filtri (n)"


def test_every_command_is_reachable_by_keyboard(qtbot, page, fake_core, tmp_path):
    _v1(qtbot, page, fake_core, tmp_path)
    view = page.case_view
    for button in (view.back_button, view.regenerate_button, view.filters_button, view.more_button):
        assert button.focusPolicy() & Qt.FocusPolicy.TabFocus, button.text()
    assert view.more_button.popupMode() == QToolButton.ToolButtonPopupMode.InstantPopup  # Space opens it
    assert view.shortcut.key().toString() == "F5"
    assert view.call_strip.focusPolicy() & Qt.FocusPolicy.TabFocus, "the clickable chip too"


def test_the_asis_segment_explains_before_the_changes(qtbot, page, fake_core, tmp_path):
    case = _v1(qtbot, page, fake_core, tmp_path)
    fake_core.officina.generate(page.ini, page._case(case.id), "asis")
    page._reload_initiative()
    page.open_case(case.id, "v1")
    button = page.case_view.switch.buttons["asis"]
    assert button.toolTip().startswith(strings.BARRA_ASIS_TIP)
    assert "prima delle modifiche" in button.toolTip().lower()
    assert page.case_view.switch.buttons["v1"].toolTip() == ""


# --------------------------------------------------------- "= AS-IS" chip ---

def test_same_as_asis_compares_the_counted_differences():
    one = placed(fake_diff("cambiato", "testo", "Acme Pay", "Acme Servizi"), 100)
    date = placed(fake_diff("cambiato", "variabile", "01/01/2026", "02/01/2026"), 200)
    later = dataclasses.replace(date, right_text="03/01/2026")

    def cc(tobe, asis):
        summary = None
        return dataclasses.make_dataclass("CC", ["tobe", "asis", "profile", "summary"])(
            fake_comparison(tobe), None if asis is None else fake_comparison(asis), "tollerante", summary)

    assert same_as_asis(cc([one, date], [one, later])), "a variable may change between generations"
    assert not same_as_asis(cc([one], [dataclasses.replace(one, right_text="Acme")]))
    assert not same_as_asis(cc([one], None)), "no AS-IS: nothing to compare with"
    assert not same_as_asis(cc([], [])), "no difference: nothing to warn about"
    assert not same_as_asis(None)


def test_the_same_as_asis_chip_shows_while_the_version_reads_as_the_asis(qtbot, page, fake_core, tmp_path):
    case = _v1(qtbot, page, fake_core, tmp_path)
    api = fake_core.officina
    todo = placed(fake_diff("cambiato", "testo", "12,00", "11,00"), 100)
    api.set_canned(case.id, 0, [todo])
    api.set_canned(case.id, 1, [todo])
    _open_version(qtbot, page, "v1", len(api.compare_case_calls), api)
    chip = page.case_view.bar.same_chip
    assert not chip.isHidden() and chip.text() == strings.BARRA_SAME_AS_ASIS
    env = page._case(case.id).env
    assert chip.toolTip() == (strings.BARRA_SAME_AS_ASIS_TIP.format(version="v1", env=env) if env
                              else strings.BARRA_SAME_AS_ASIS_TIP_NO_ENV.format(version="v1"))
    assert chip.toolTip().startswith("v1 ha lo stesso testo dell'AS-IS: nessuna modifica ancora pubblicata")

    api.set_canned(case.id, 1, [dataclasses.replace(todo, right_text="11,50")])  # in corso: changed
    _open_version(qtbot, page, "v1", len(api.compare_case_calls), api)
    assert chip.isHidden()


# ------------------------------------------- the AS-IS: the same language ---

def test_the_asis_view_draws_its_differences_as_da_fare(qtbot, page, fake_core, tmp_path):
    case = _v1(qtbot, page, fake_core, tmp_path)
    api = fake_core.officina
    api.generate(page.ini, page._case(case.id), "asis")
    diffs = [placed(fake_diff("cambiato", "testo", "12,00", "11,00"), 100),
             placed(fake_diff("mancante", "testo", "Nota", ""), 200),
             placed(fake_diff("cambiato", "variabile", "01/01", "02/01"), 300)]
    api.set_comparison(fake_comparison(diffs))
    page._reload_initiative()
    page.open_case(page.case_id, "asis")
    qtbot.waitUntil(lambda: page.case_view.docs is not None
                    and page.case_view.docs.right.version is not None
                    and page.case_view.docs.right.version.kind == "asis", timeout=10000)
    view = page.case_view
    states = [state_of(j) for j, _side in view.right.view._items]
    assert states == ["da_fare", "da_fare", "variabile"], (
        "the counted ones as the whole work (not the neutral phase-1 look), the rest in its own look (U3, D15)")
    assert not view.progress.isHidden() and view.progress.percent.isHidden()
    assert view.progress.pill_texts() == ["○ 2 da fare"]
    assert view.progress.pill_for("da_fare").toolTip().startswith(strings.BARRA_ASIS_TOTAL_TIP.format(n=2)[:20])
    assert view.right.slot.text() == strings.OFFICINA_VERSION_ASIS and not view.right.slot.isHidden()
    assert view.bar.same_chip.isHidden()


# --------------------------------------------------------------- filters ---

def test_filters_shows_how_many_occurrences_are_set_aside_and_opens_the_panel(qtbot, page, fake_core, tmp_path):
    case = _v1(qtbot, page, fake_core, tmp_path)
    api = fake_core.officina
    assert page.case_view.filters_button.text() == strings.BARRA_FILTERS
    api.set_filter_groups(case.id, [fake_group("zona.numero_pagina", n=2),   # set aside by default
                                    fake_group("zona.invisibile", n=3),       # informational: always
                                    fake_group("decidere.maiuscole", n=4)])   # counts by default
    api.set_canned(case.id, 1, [placed(fake_diff("cambiato", "testo", "12,00", "11,00"), 100)])
    _open_version(qtbot, page, "v1", len(api.compare_case_calls), api)
    button = page.case_view.filters_button
    assert button.text() == strings.BARRA_FILTERS_N.format(n=5)
    with qtbot.waitSignal(page.case_view.filters_requested, timeout=2000):
        button.click()
    dialog = page.filters_dialog
    assert dialog is not None and not dialog.isModal(), "U4: the Filtri del confronto panel, modeless"
    assert dialog.row("zona.numero_pagina").group.n == 2
    dialog.close()


# ----------------------------------------------------------------- chips ---

def test_the_strips_became_chips_with_their_message_as_tooltip(qtbot, page, fake_core, tmp_path):
    _v1(qtbot, page, fake_core, tmp_path)
    view = page.case_view
    view.set_failure("il generatore ha risposto 502")
    assert view.banner.message() == "il generatore ha risposto 502"
    assert view.banner.text() == strings.BARRA_FAILED and view.banner.toolTip() == view.banner.message()
    assert view.banner.height() < BAR_HEIGHT
    view.set_failure("")
    assert view.banner.isHidden() and view.banner.message() == ""


def test_the_verification_outcome_is_a_chip_kept_on_its_version(qtbot, page, fake_core, tmp_path):
    case = _v1(qtbot, page, fake_core, tmp_path)
    api = fake_core.officina
    fixed = placed(fake_diff("cambiato", "testo", "12,00", "11,00"), 100)
    stuck = placed(fake_diff("cambiato", "testo", "Titolo", "Titol"), 200)
    api.set_canned(case.id, 0, [fixed, stuck])
    api.set_canned(case.id, 1, [fixed, stuck])
    api.set_canned(case.id, 2, [stuck])
    _open_version(qtbot, page, "v1", len(api.compare_case_calls), api)
    for j in page.case_view.docs.judged.judged:
        api.mark_done(page._case(case.id), j, 1)
    _open_version(qtbot, page, "v1", len(api.compare_case_calls), api)
    view = page.case_view
    tip = view.progress.pill_for("da_verificare").toolTip()
    assert "2 modifiche da verificare" in tip and "rigenera il TO-BE (F5)" in tip
    assert view.unmark_action.isEnabled()
    calls = len(api.compare_case_calls)
    view.regenerate_button.click()
    wait_idle(qtbot, page)
    qtbot.waitUntil(lambda: len(api.compare_case_calls) > calls and view.docs is not None
                    and view.docs.judged is not None and view.docs.judged.version == 2, timeout=10000)
    outcome = view.progress.outcome
    assert not outcome.isHidden() and outcome.text() == "v2: 1/2 risolte"
    assert outcome.toolTip() == "v2: verificate 2 modifiche segnate — 1 risolta, 1 non risolta"
    assert outcome.property("pill") == "warn"
    view.diffs.list.setCurrentRow(0)  # an action in the case: the chip stays (no fold any more)
    assert not outcome.isHidden()
    _open_version(qtbot, page, "v1", len(api.compare_case_calls), api)
    assert outcome.isHidden(), "the outcome belongs to v2"
    assert view.banners.outcome() is None


def test_an_ok_outcome_has_an_ok_chip(qtbot):
    from qtrequestory.ui.pages.officina_banners import ReviewBanners

    banners = ReviewBanners()
    judged = dataclasses.make_dataclass("J", ["verification", "version"])(Verification(2, 2, 0, 0, 3), 3)
    from pathlib import Path

    banners.show_judged(Path("caso"), judged, 3)
    assert banners.outcome() == ("v3: 2/2 risolte", "v3: verificate 2 modifiche segnate — 2 risolte", "ok")
    banners.forget()
    assert banners.outcome() is None and banners.outcome_text() == ""


def test_marks_pill_counts_the_marks_even_as_da_verificare(qtbot, page, fake_core, tmp_path):
    """A mark shows as the "✓? N" pill, never as a strip (R32: dormant marks
    are left out, as before)."""
    case = _v1(qtbot, page, fake_core, tmp_path)
    api = fake_core.officina
    todo = placed(fake_diff("cambiato", "testo", "12,00", "11,00"), 100)
    api.set_canned(case.id, 1, [todo])
    _open_version(qtbot, page, "v1", len(api.compare_case_calls), api)
    api.mark_done(page._case(case.id), Judged(page.case_view.docs.judged.judged[0].diff, "da_fare"), 1)
    _open_version(qtbot, page, "v1", len(api.compare_case_calls), api)
    view = page.case_view
    assert "✓? 1 da verificare" in view.progress.pill_texts()
    assert view.progress.pill_for("da_verificare").text().endswith("1")


# ------------------------------------------------------- accessible names ---

def test_the_bare_glyphs_have_full_accessible_names(qtbot, page, fake_core, tmp_path):
    """Fix round 1: "‹", the compact pills, the chips, "Filtri (n)" and "⋯"
    are read out in full words (the tooltips' wording), like app_bar.py."""
    case = _v1(qtbot, page, fake_core, tmp_path)
    api = fake_core.officina
    todo = placed(fake_diff("cambiato", "testo", "12,00", "11,00"), 100)
    other = placed(fake_diff("mancante", "testo", "Nota", ""), 200)
    extra = placed(fake_diff("in_piu", "testo", "", "Extra"), 300)
    api.set_canned(case.id, 0, [todo, other])
    api.set_canned(case.id, 1, [todo, other, extra])
    api.set_filter_groups(case.id, [fake_group("zona.numero_pagina", n=2)])
    _open_version(qtbot, page, "v1", len(api.compare_case_calls), api)
    view = page.case_view
    assert view.back_button.accessibleName() == strings.BARRA_BACK_NAME.format(initiative="Banco")
    assert view.back_button.accessibleName() == "Torna all'iniziativa Banco"
    assert view.progress.pill_for("regressione").accessibleName() == "1 regressione"
    assert view.progress.pill_for("da_fare").accessibleName() == "2 da fare"
    assert view.progress.pill_for("regressione").toolTip().endswith("1 regressione")
    assert view.progress.percent.accessibleName() == strings.BARRA_PERCENT_NAME.format(pct=0, version=1)
    assert view.filters_button.accessibleName() == view.filters_button.text() == "Filtri (2)"
    assert view.more_button.accessibleName() == "Altre azioni"
    view.bar.set_same_as_asis("v1", "svil")
    chip = view.bar.same_chip
    assert chip.accessibleName() == chip.toolTip() and chip.accessibleName().startswith("v1 ha lo stesso testo")
    view.set_failure("il generatore ha risposto 502")
    assert view.banner.accessibleName() == "il generatore ha risposto 502"
    api.set_canned(case.id, 0, None)
    _open_version(qtbot, page, "v1", len(api.compare_case_calls), api)
    assert view.progress.two_way.accessibleName() == strings.REVISIONE_TWO_WAY
