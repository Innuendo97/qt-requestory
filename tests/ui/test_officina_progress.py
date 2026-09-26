"""Officina phase 2 (U2): the progress bar, the verdict strip, the review
banners and the profile menu of the case view (spec §5.3, §7.1).

Offscreen, on the fake core: ``compare_case`` is scripted by canned diffs
(``tests/fakes/fake_verdict``), the review state (marks, profile) is real.
"""
from __future__ import annotations

import dataclasses
import threading
import time

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import CaseSummary, Judged, Verification, Word
from qtrequestory.ui.pages.officina_page import OfficinaPage
from qtrequestory.ui.pages.officina_banners import STRIP_MAX_H
from qtrequestory.ui.pages.officina_progress import (
    ProgressBar,
    VerdictStrip,
    glyph_html,
    percent,
    pill_texts,
)
from tests.fakes.fake_core import fake_diff
from tests.ui.test_officina_page import FakeWindow, open_case, wait_idle


#: As the engine saves it (R15): the mark is also in in_corso, the non risolta also in da_fare.
SUMMARY = CaseSummary(version=3, fatte=6, da_fare=3, in_corso=2, regressioni=1, da_verificare=1,
                      non_risolte=1, tollerate=3, variabili=14, rumore=2, avanzamento=0.6,
                      two_way=False, when="2026-09-25T10:00:00")


@pytest.fixture
def page(qtbot, fake_core, runner) -> OfficinaPage:
    widget = OfficinaPage(fake_core, runner, FakeWindow())
    qtbot.addWidget(widget)
    widget.resize(1300, 760)
    widget.show()
    return widget


def placed(diff, y: float, *, page: int = 0, side: str = "both"):
    """``diff`` with one word box on each side at height ``y``."""
    left = (Word(diff.left_text or "x", page, 60, y, 140, y + 12),) if side in ("both", "left") else ()
    right = (Word(diff.right_text or "x", page, 60, y, 140, y + 12),) if side in ("both", "right") else ()
    return dataclasses.replace(diff, left=left, right=right)


def judged(diff_id: int, verdict, y: float, *, page: int = 0, klass: str = "testo", **flags) -> Judged:
    diff = placed(fake_diff("cambiato", klass, f"t{diff_id}", f"g{diff_id}", diff_id=diff_id), y, page=page)
    return Judged(diff, verdict, **flags)


# ------------------------------------------------------------------ pills ---

def test_the_pills_follow_the_spec_order_then_the_dimmed_ones():
    """From the summary alone the counts are the board's (U5, R15, R44): the
    mark out of the mildest verdict, the non risolta also in its verdict."""
    assert pill_texts(SUMMARY) == [
        ("▲ 1 regressione", "bad", False),
        ("○! 1 non risolta", "warn", False),
        ("○ 3 da fare", "warn", False),
        ("◐ 1 in corso", "progress", False),
        ("✓? 1 da verificare", "ok", False),
        ("✓ 6 fatte", "ok", False),
        ("⊘ 3 tollerate", "neutral", True),
        ("{x} 14 variabili", "variable", True),
        ("~ 2 rumore", "neutral", True),
    ]


def test_zero_counts_have_no_pill_and_plurals_agree():
    summary = dataclasses.replace(SUMMARY, fatte=1, da_fare=2, in_corso=0, regressioni=2,
                                  da_verificare=0, non_risolte=2, tollerate=1, variabili=1, rumore=0)
    assert [text for text, _tone, _dim in pill_texts(summary)] == [
        "▲ 2 regressioni", "○! 2 non risolte", "○ 2 da fare", "✓ 1 fatta", "⊘ 1 tollerata",
        "{x} 1 variabile"]


def test_with_the_judged_diffs_flags_are_in_their_verdict_and_in_non_risolte():
    """The summary counts a mark in its verdict AND in da_verificare (R15);
    the case view counts a mark once (da verificare), and a flagged
    difference in its verdict AND in non risolte (R44)."""
    items = [judged(1, "da_fare", 10), judged(2, "da_fare", 20, marked=True),
             judged(3, "da_fare", 30, unresolved=True), judged(4, "regressione", 40, marked=True),
             judged(5, "fatta", 50), judged(6, None, 60, klass="variabile")]
    assert [text for text, _tone, _dim in pill_texts(SUMMARY, items)] == [
        "○! 1 non risolta", "○ 2 da fare", "✓? 2 da verificare", "✓ 1 fatta", "{x} 1 variabile"]


def test_the_bar_shows_the_percentage_the_version_and_the_pills(qtbot):
    bar = ProgressBar()
    qtbot.addWidget(bar)
    assert bar.isHidden(), "nothing judged: no bar"
    bar.show_summary(SUMMARY, [])
    assert not bar.isHidden()
    assert bar.percent.text() == "60%"
    assert bar.version_label.text() == "v3 contro target"
    assert bar.pill_texts() == [t for t, _tone, _dim in pill_texts(SUMMARY)]
    main, dimmed = bar.pill_groups()
    assert len(main) == 6 and len(dimmed) == 3
    assert bar.dimmed_box.graphicsEffect() is not None, "tollerate/variabili/rumore are dimmed"
    assert main[0].property("pill") == "bad" and dimmed[1].property("pill") == "variable"
    bar.show_summary(None, [])
    assert bar.isHidden()


# ------------------------------------------------------------------ strip ---

def test_the_strip_has_one_segment_per_judged_diff_in_document_order(qtbot):
    strip = VerdictStrip()
    qtbot.addWidget(strip)
    strip.set_judged([
        judged(1, "da_fare", 300),
        judged(2, "regressione", 100, page=1),
        judged(3, "fatta", 100),
        judged(4, None, 50, klass="variabile"),         # no verdict: not on the strip
        judged(5, "da_fare", 200, marked=True),
        judged(6, "da_fare", 250, unresolved=True),
        judged(7, "tollerata", 400),
        judged(8, None, 60, klass="rumore"),
    ])
    assert strip.segments() == [(3, "fatta"), (5, "da_verificare"), (6, "non_risolta"),
                                (1, "da_fare"), (7, "tollerata"), (2, "regressione")]


def test_clicking_a_segment_emits_its_diff_id(qtbot):
    strip = VerdictStrip()
    qtbot.addWidget(strip)
    strip.resize(300, 20)
    strip.show()
    strip.set_judged([judged(4, "da_fare", 100), judged(9, "in_corso", 200), judged(2, "fatta", 300)])
    with qtbot.waitSignal(strip.diff_selected) as blocker:
        rect = strip.segment_rect(1)
        QTest.mouseClick(strip, Qt.MouseButton.LeftButton, pos=QPoint(int(rect.center().x()), 5))
    assert blocker.args == [9]
    assert strip.tooltip_at(1).startswith(strings.VERDETTO_IN_CORSO)


def test_the_strip_repaints_offscreen_in_both_themes(qtbot):
    from qtrequestory.ui import theme

    strip = VerdictStrip()
    qtbot.addWidget(strip)
    strip.resize(200, 16)
    strip.set_judged([judged(i, v, i * 10, **f) for i, (v, f) in enumerate([
        ("regressione", {}), ("da_fare", {"unresolved": True}), ("da_fare", {}), ("in_corso", {}),
        ("da_fare", {"marked": True}), ("fatta", {}), ("tollerata", {})], 1)])
    assert not strip.grab().isNull()
    theme.signals.changed.emit()
    assert not strip.grab().isNull()


# ---------------------------------------------------------- the case view ---

def _generate_v1(qtbot, page, fake_core, tmp_path):
    case = open_case(page, fake_core, tmp_path)
    page.case_view.regenerate_button.click()
    wait_idle(qtbot, page)
    return case


def _open_version(qtbot, page, key: str, calls_before: int, api, case_id: str | None = None):
    page.open_case(case_id or page.case_id, key)
    qtbot.waitUntil(lambda: len(api.compare_case_calls) > calls_before
                    and page.case_view.docs is not None
                    and page.case_view.docs.judged is not None
                    and not page.case_view.judging, timeout=10000)
    qtbot.wait(50)


def test_the_case_view_shows_the_progress_of_the_judged_version(qtbot, page, fake_core, tmp_path):
    case = _generate_v1(qtbot, page, fake_core, tmp_path)
    api = fake_core.officina
    keep = placed(fake_diff("cambiato", "testo", "12,00", "11,00"), 100)
    api.set_canned(case.id, 0, [keep, placed(fake_diff("mancante", "testo", "Nota", ""), 200)])
    api.set_canned(case.id, 1, [keep, placed(fake_diff("in_piu", "testo", "", "Extra"), 300)])
    _open_version(qtbot, page, "v1", len(api.compare_case_calls), api)
    bar = page.case_view.progress
    assert not bar.isHidden()
    assert bar.percent.text() == "33%"  # 1 fatta / (1 + 1 da fare + 1 regressione)
    assert bar.version_label.text() == "v1 contro target"
    assert bar.pill_texts() == ["▲ 1 regressione", "○ 1 da fare", "✓ 1 fatta"]
    ids = [diff_id for diff_id, _state in bar.strip.segments()]
    regression = next(i for i, s in bar.strip.segments() if s == "regressione")
    bar.strip.diff_selected.emit(regression)
    assert page.case_view.right.view.focused_difference() == regression
    assert len(ids) == 3

    api.generate(page.ini, page._case(case.id), "asis")
    page._reload_initiative()
    page.open_case(page.case_id, "asis")  # the AS-IS is not judged: no bar
    qtbot.waitUntil(lambda: page.case_view.docs is not None
                    and page.case_view.docs.right.version.kind == "asis", timeout=10000)
    assert page.case_view.progress.isHidden()


def test_a_tobe_without_text_shows_its_note_not_a_verdict(qtbot, page, fake_core, tmp_path):
    """Final review C1 / R49: no "fatte" at 100%, no bar, the marks wait."""
    case = _generate_v1(qtbot, page, fake_core, tmp_path)
    api = fake_core.officina
    todo = placed(fake_diff("cambiato", "testo", "12,00", "11,00"), 100)
    api.set_canned(case.id, 0, [todo])
    api.set_canned(case.id, 1, [todo])
    _open_version(qtbot, page, "v1", len(api.compare_case_calls), api)
    api.mark_done(page._case(case.id), page.case_view.docs.judged.judged[0], 0)
    note = "il TO-BE non ha testo estraibile"
    api.set_canned(case.id, 1, [], right_has_text=False, note=note)
    _open_version(qtbot, page, "v1", len(api.compare_case_calls), api)
    view = page.case_view
    assert view.docs.judged.judged == ()
    assert view.progress.isHidden()
    assert view.diffs.summary.text() == note
    assert len(page._case(case.id).review.marks) == 1

    api.set_canned(case.id, 0, [], right_has_text=False, note="l'AS-IS non ha testo estraibile")
    api.set_canned(case.id, 1, [todo])
    _open_version(qtbot, page, "v1", len(api.compare_case_calls), api)
    assert not view.progress.isHidden() and view.docs.judged.summary.two_way
    assert view.progress.two_way.toolTip() == strings.REVISIONE_TWO_WAY_NO_TEXT


def test_the_marks_banner_comes_and_goes_with_the_marks(qtbot, page, fake_core, tmp_path):
    case = _generate_v1(qtbot, page, fake_core, tmp_path)
    api = fake_core.officina
    todo = placed(fake_diff("cambiato", "testo", "12,00", "11,00"), 100)
    other = placed(fake_diff("cambiato", "testo", "Titolo", "Titol"), 200)
    api.set_canned(case.id, 0, [todo, other])
    api.set_canned(case.id, 1, [todo, other])
    _open_version(qtbot, page, "v1", len(api.compare_case_calls), api)
    banners = page.case_view.banners
    assert banners.marks_text() == ""
    for j in page.case_view.docs.judged.judged:
        api.mark_done(page._case(case.id), j, 1)
    _open_version(qtbot, page, "v1", len(api.compare_case_calls), api)
    env = page._case(case.id).env
    expected = (strings.REVISIONE_MARKS_MANY.format(n=2, env=env) if env
                else strings.REVISIONE_MARKS_MANY_NO_ENV.format(n=2))
    assert banners.marks_text() == expected
    assert "2 modifiche da verificare" in banners.marks_text()
    assert "rigenera il TO-BE (F5)" in banners.marks_text()

    calls = len(api.compare_case_calls)
    banners.unmark_button.click()  # saved in the review worker (U4), then judged again
    qtbot.waitUntil(lambda: len(api.compare_case_calls) > calls and not page.case_view.acting,
                    timeout=10000)
    assert ("unmark_all", case.id) in api.review_actions
    assert banners.marks_text() == ""
    assert page._case(case.id).review.marks == []


def test_the_marks_banner_leaves_out_dormant_marks(qtbot, page, fake_core, tmp_path):
    """E5/I1: a mark on a difference that does not count now (tolerated by
    hand after it was marked) is dormant (R32): the strip counts the
    summary's "da verificare", not every mark in the file."""
    case = _generate_v1(qtbot, page, fake_core, tmp_path)
    api = fake_core.officina
    first = placed(fake_diff("cambiato", "testo", "12,00", "11,00"), 100)
    second = placed(fake_diff("cambiato", "testo", "Titolo", "Titol"), 200)
    api.set_canned(case.id, 0, [first, second])
    api.set_canned(case.id, 1, [first, second])
    _open_version(qtbot, page, "v1", len(api.compare_case_calls), api)
    for j in page.case_view.docs.judged.judged:
        api.mark_done(page._case(case.id), j, 1)
    api.tolerate(page._case(case.id), page.case_view.docs.judged.judged[0])
    _open_version(qtbot, page, "v1", len(api.compare_case_calls), api)
    assert len(page._case(case.id).review.marks) == 2
    assert page.case_view.docs.judged.summary.da_verificare == 1
    env = page._case(case.id).env
    assert page.case_view.banners.marks_text() == (
        strings.REVISIONE_MARKS_ONE.format(n=1, env=env) if env
        else strings.REVISIONE_MARKS_ONE_NO_ENV.format(n=1))


def test_a_newer_tobe_shows_the_outcome_of_the_verification(qtbot, page, fake_core, tmp_path):
    case = _generate_v1(qtbot, page, fake_core, tmp_path)
    api = fake_core.officina
    fixed = placed(fake_diff("cambiato", "testo", "12,00", "11,00"), 100)
    stuck = placed(fake_diff("cambiato", "testo", "Titolo", "Titol"), 200)
    api.set_canned(case.id, 0, [fixed, stuck])
    api.set_canned(case.id, 1, [fixed, stuck])
    api.set_canned(case.id, 2, [stuck])  # "12,00" is fixed in v2, "Titolo" is not
    _open_version(qtbot, page, "v1", len(api.compare_case_calls), api)
    for j in page.case_view.docs.judged.judged:
        api.mark_done(page._case(case.id), j, 1)
    page.case_view.diffs.list.setCurrentRow(0)  # refilling the list must not count as an action
    calls = len(api.compare_case_calls)
    page.case_view.regenerate_button.click()  # v2: the page opens it and judges it
    wait_idle(qtbot, page)
    qtbot.waitUntil(lambda: len(api.compare_case_calls) > calls and page.case_view.docs is not None
                    and page.case_view.docs.judged is not None
                    and page.case_view.docs.judged.version == 2, timeout=10000)
    banners = page.case_view.banners
    assert banners.outcome_text() == "v2: verificate 2 modifiche segnate — 1 risolta, 1 non risolta"
    assert banners.outcome.property("banner") == "warn"
    assert "<b>v2: verificate 2 modifiche segnate</b>" in banners.outcome.label.text()
    assert banners.outcome.height() <= STRIP_MAX_H and banners.marks.maximumHeight() <= STRIP_MAX_H
    assert banners.marks_text() == "", "the verified marks are gone"

    _open_version(qtbot, page, "v1", len(api.compare_case_calls), api)
    assert banners.outcome_text() == "", "the outcome belongs to v2"
    _open_version(qtbot, page, "v2", len(api.compare_case_calls), api)
    assert banners.outcome_text().startswith("v2: verificate 2")
    view = page.case_view
    assert view.progress.outcome.isHidden()
    view.progress.strip.diff_selected.emit(view.progress.strip.segments()[0][0])  # next action
    assert banners.outcome_text() == "", "the outcome folds into the bar"
    assert not view.progress.outcome.isHidden()
    assert view.progress.outcome.text() == "v2: 1/2 risolte"
    assert view.progress.outcome.toolTip().startswith("v2: verificate 2 modifiche segnate")
    assert view.progress.outcome.property("pill") == "warn"
    page.show_board()
    _open_version(qtbot, page, "v2", len(api.compare_case_calls), api, case.id)
    assert banners.outcome_text() == "", "leaving the case forgets the outcome"
    assert view.progress.outcome.isHidden()


def test_every_mark_resolved_is_an_ok_outcome(qtbot):
    from qtrequestory.ui.pages.officina_banners import outcome_text

    assert outcome_text(Verification(1, 1, 0, 0, 4)) == (
        "v4: verificata 1 modifica segnata — 1 risolta", "ok"), "zero parts are left out"
    assert outcome_text(Verification(3, 1, 0, 2, 5)) == (
        "v5: verificate 3 modifiche segnate — 1 risolta, 2 cambiate ma ancora diverse", "warn")
    assert outcome_text(Verification(2, 0, 2, 0, 5)) == (
        "v5: verificate 2 modifiche segnate — 2 non risolte", "warn")
    assert outcome_text(Verification(0, 0, 0, 0, 5)) is None


def test_without_an_asis_the_two_way_warning_shows(qtbot, page, fake_core, tmp_path):
    case = _generate_v1(qtbot, page, fake_core, tmp_path)
    api = fake_core.officina
    api.set_canned(case.id, 1, [placed(fake_diff("cambiato", "testo", "12,00", "11,00"), 100)])
    _open_version(qtbot, page, "v1", len(api.compare_case_calls), api)  # no canned 0: two-way
    bar = page.case_view.progress
    assert not bar.two_way.isHidden(), "a pill in the bar, not a banner"
    assert bar.two_way.toolTip() == strings.REVISIONE_TWO_WAY
    assert not bar.asis_button.isHidden()
    with qtbot.waitSignal(page.case_view.asis_requested, timeout=2000):
        bar.asis_button.click()
    wait_idle(qtbot, page)
    api.set_canned(case.id, 0, [])
    _open_version(qtbot, page, "v1", len(api.compare_case_calls), api)
    assert bar.two_way.isHidden() and bar.asis_button.isHidden()


def test_the_review_writes_wait_for_a_running_compare(qtbot, page, fake_core, tmp_path):
    case = _generate_v1(qtbot, page, fake_core, tmp_path)
    api = fake_core.officina
    api.set_canned(case.id, 1, [placed(fake_diff("cambiato", "testo", "12,00", "11,00"), 100)])
    _open_version(qtbot, page, "v1", len(api.compare_case_calls), api)
    api.mark_done(page._case(case.id), page.case_view.docs.judged.judged[0], 1)
    _open_version(qtbot, page, "v1", len(api.compare_case_calls), api)
    view = page.case_view
    assert view.profile_button.isEnabled() and view.banners.unmark_button.isEnabled()
    view.set_judging(True)
    assert not view.profile_button.isEnabled() and not view.banners.unmark_button.isEnabled()
    page.unmark_all()
    page.set_case_profile("stretto")
    assert ("unmark_all", case.id) not in api.review_actions
    assert ("set_profile", case.id) not in api.review_actions
    assert page._window.statuses[-1] == strings.REVISIONE_WAIT_COMPARE
    view.set_judging(False)
    assert view.profile_button.isEnabled()


def test_the_percentage_rounds_down():
    assert [percent(a) for a in (0.0, 0.004, 0.29, 0.333, 0.995, 0.9999, 1.0)] == [
        0, 0, 29, 33, 99, 99, 100]


def test_the_percentage_is_total_on_junk():
    """Final review I3 (U2 minor): never raises, whatever the float."""
    assert [percent(a) for a in (float("nan"), float("-inf"), float("inf"), -3.0, 7.0)] == [0, 0, 100, 0, 100]


def test_symbol_glyphs_are_drawn_from_a_symbol_font():
    html = glyph_html("◐ 1 in corso")
    assert "Segoe UI Symbol" in html and html.endswith(" 1 in corso")
    assert glyph_html("{x} 1 variabile") == "{x} 1 variabile"


# ---------------------------------------------------------------- profile ---

def test_the_profile_menu_saves_the_profile_and_compares_again(qtbot, page, fake_core, tmp_path):
    case = _generate_v1(qtbot, page, fake_core, tmp_path)
    api = fake_core.officina
    api.set_canned(case.id, 1, [placed(fake_diff("cambiato", "stile", "Titolo", "Titolo"), 100)])
    _open_version(qtbot, page, "v1", len(api.compare_case_calls), api)
    view = page.case_view
    button = view.profile_button
    assert [a.text() for a in button.menu().actions() if not a.isSeparator()] == [
        strings.PROFILO_TOLLERANTE, strings.PROFILO_STRETTO, strings.PROFILO_SOLO_TESTO,
        strings.PROFILO_INIZIATIVA.format(profile=strings.PROFILO_TOLLERANTE)]
    assert button.current() is None and strings.PROFILO_TOLLERANTE in button.text()
    assert view.docs.judged.judged[0].verdict == "tollerata"

    calls = len(api.compare_case_calls)
    button.action_for("stretto").trigger()
    assert ("set_profile", case.id) in api.review_actions
    qtbot.waitUntil(lambda: len(api.compare_case_calls) > calls and view.docs is not None
                    and view.docs.judged is not None and view.docs.judged.profile == "stretto",
                    timeout=10000)
    assert page._case(case.id).review.profile == "stretto"
    assert view.docs.judged.judged[0].verdict == "da_fare", "stile counts when strict"
    assert button.current() == "stretto" and strings.PROFILO_STRETTO in button.text()

    button.action_for(None).trigger()  # "Come l'iniziativa"
    qtbot.waitUntil(lambda: view.docs is not None and view.docs.judged is not None
                    and view.docs.judged.profile == "tollerante", timeout=10000)
    assert page._case(case.id).review.profile is None
    assert button.current() is None


def test_a_refused_profile_save_is_said_and_changes_nothing(qtbot, page, fake_core, tmp_path,
                                                            monkeypatch):
    _generate_v1(qtbot, page, fake_core, tmp_path)
    qtbot.waitUntil(lambda: not page.case_view.judging, timeout=10000)

    def refuse(*_a):
        raise ValueError("caso.json non è leggibile")

    monkeypatch.setattr(fake_core.officina, "set_profile", refuse)
    page.case_view.profile_button.action_for("solo_testo").trigger()
    assert any("caso.json non è leggibile" in s for s in page._window.statuses)
    assert page.case_view.profile_button.current() is None


# ------------------------------------------------- the lock of a case (U1) ---

def test_the_same_case_id_in_two_initiatives_has_two_locks(fake_core, monkeypatch):
    from qtrequestory.ui.pages import officina_judge

    class Ini:
        def __init__(self, ident):
            self.id = ident

    class Case:
        id, key = "MOD_TEST_A", "MOD_TEST_A"

    started, release = threading.Event(), threading.Event()

    def slow_generate(*_a, **_k):
        started.set()
        release.wait(10)

    monkeypatch.setattr(fake_core.officina, "generate", slow_generate)
    monkeypatch.setattr(fake_core.officina, "compare_case", lambda *_a: "giudicato")
    worker = threading.Thread(target=officina_judge.generate_locked,
                              args=(fake_core, Ini("uno"), Case, "tobe"))
    worker.start()
    try:
        assert started.wait(5)
        assert officina_judge.is_generating("uno", Case.id)
        assert not officina_judge.is_generating("due", Case.id)
        t0 = time.monotonic()
        assert officina_judge.judge(fake_core, Ini("due"), Case, None) == "giudicato"
        assert time.monotonic() - t0 < 1.0
    finally:
        release.set()
        worker.join(5)


def test_two_generations_of_one_case_are_counted(fake_core, monkeypatch):
    from qtrequestory.ui.pages import officina_judge

    class Ini:
        id = "uno"

    class Case:
        id, key = "MOD_TEST_B", "MOD_TEST_B"

    first_in, release_first = threading.Event(), threading.Event()
    calls = []

    def generate(*_a, **_k):
        calls.append(1)
        if len(calls) == 1:
            first_in.set()
            release_first.wait(10)

    monkeypatch.setattr(fake_core.officina, "generate", generate)
    first = threading.Thread(target=officina_judge.generate_locked, args=(fake_core, Ini, Case, "tobe"))
    second = threading.Thread(target=officina_judge.generate_locked, args=(fake_core, Ini, Case, "asis"))
    first.start()
    assert first_in.wait(5)
    second.start()  # waits on the lock: counted too
    deadline = time.monotonic() + 5
    while officina_judge._generating[(Ini.id, Case.id)] < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert officina_judge._generating[(Ini.id, Case.id)] == 2
    release_first.set()
    first.join(5)
    second.join(5)
    assert not officina_judge.is_generating(Ini.id, Case.id)
    assert len(calls) == 2


def test_accepting_with_open_differences_says_what_is_left(qtbot, page, fake_core, tmp_path, monkeypatch):
    """Spec §5.4 (D2): the confirmation of "Segna accettato" sums up what is
    left ("Restano …"), and never blocks; nothing left → no question."""
    from qtrequestory.ui.pages import officina_dialogs

    case = _generate_v1(qtbot, page, fake_core, tmp_path)
    api = fake_core.officina
    todo = placed(fake_diff("cambiato", "testo", "12,00", "11,00"), 100)
    other = placed(fake_diff("cambiato", "testo", "Titolo", "Titol"), 200)
    extra = placed(fake_diff("in_piu", "testo", "", "Extra"), 300)
    api.set_canned(case.id, 0, [todo, other])
    api.set_canned(case.id, 1, [todo, other, extra])
    _open_version(qtbot, page, "v1", len(api.compare_case_calls), api)
    api.mark_done(page._case(case.id), page.case_view.docs.judged.judged[1], 1)
    _open_version(qtbot, page, "v1", len(api.compare_case_calls), api)
    asked: list[str] = []
    monkeypatch.setattr(officina_dialogs, "confirm", lambda _p, _t, text: asked.append(text) or True)
    page.case_view.accept_button.click()
    assert asked == [strings.OFFICINA_ACCEPT_REMAINING.format(
        parts="1 regressione, 1 da fare, 1 da verificare")]
    assert api.load(page.ini.id).cases[0].status == "accepted"
    page.case_view.accept_button.click()  # reopen

    api.set_canned(case.id, 1, [])
    api.unmark_all(page._case(case.id))
    _open_version(qtbot, page, "v1", len(api.compare_case_calls), api)
    asked.clear()
    page.case_view.accept_button.click()
    assert asked == [], "nothing left: no question"


def test_replacing_the_target_asks_first_and_says_what_is_cleared(qtbot, page, fake_core, tmp_path,
                                                                   monkeypatch):
    """R29 (I1): "Target…" on a case with review state asks first, saying
    that marks, non risolte and the summary go and tolerances stay; "No"
    keeps everything. Without review state it does not ask."""
    from qtrequestory.ui.contracts import Mark
    from qtrequestory.ui.pages import officina_dialogs
    from tests.fakes.fake_core import canned_pdf

    case = _generate_v1(qtbot, page, fake_core, tmp_path)
    api = fake_core.officina
    api.set_canned(case.id, 1, [placed(fake_diff("cambiato", "testo", "12,00", "11,00"), 100)])
    _open_version(qtbot, page, "v1", len(api.compare_case_calls), api)
    api.mark_done(page._case(case.id), page.case_view.docs.judged.judged[0], 1)
    page.refresh()
    source = tmp_path / "nuovo target.pdf"
    source.write_bytes(canned_pdf("testo del nuovo target"))
    monkeypatch.setattr(officina_dialogs, "ask_open_file", lambda *_a, **_k: source)
    asked: list[str] = []
    monkeypatch.setattr(officina_dialogs, "confirm", lambda _p, _t, text: asked.append(text) or False)
    before = page._case(case.id).target().path
    page.choose_target()
    assert asked == [strings.OFFICINA_TARGET_REPLACE]
    assert page._case(case.id).target().path == before, "No: nothing replaced"
    assert [isinstance(m, Mark) for m in page._case(case.id).review.marks] == [True]

    monkeypatch.setattr(officina_dialogs, "confirm", lambda _p, _t, text: asked.append(text) or True)
    page.choose_target()
    assert page._case(case.id).target().meta.get("original_name") == "nuovo target.pdf"
    fresh = next(c for c in api.load(page.ini.id).cases if c.id == case.id)
    assert fresh.review.marks == [] and fresh.review.summary is None

    asked.clear()
    page.choose_target()  # nothing to clear any more: no question
    assert asked == []


def test_accepting_describes_the_latest_tobe_and_a_side_without_text(qtbot, page, fake_core, tmp_path):
    """I1 fix (Minor 5): accepting stamps the LATEST TO-BE, so the question is
    about it — from its summary when another version is on screen, "not
    compared yet" without one — and a side without text is said."""
    case = _generate_v1(qtbot, page, fake_core, tmp_path)
    api = fake_core.officina
    api.set_canned(case.id, 1, [], right_has_text=False, note="il TO-BE non ha testo estraibile")
    _open_version(qtbot, page, "v1", len(api.compare_case_calls), api)
    view = page.case_view
    assert view.acceptance_warning() == strings.OFFICINA_ACCEPT_NO_TEXT.format(
        note="il TO-BE non ha testo estraibile")
    api.set_canned(case.id, 1, [placed(fake_diff("cambiato", "testo", "12,00", "11,00"), 100)])
    _open_version(qtbot, page, "v1", len(api.compare_case_calls), api)
    page.case_view.regenerate_button.click()  # v2, never compared...
    wait_idle(qtbot, page)
    page.refresh()
    fresh = page._case(case.id)
    assert fresh.latest_tobe().number == 2
    view.case = fresh
    view.docs = dataclasses.replace(view.docs, judged=None)  # ...while v1's docs are still on screen
    assert view.acceptance_warning() == strings.OFFICINA_ACCEPT_NOT_COMPARED.format(version=2)
