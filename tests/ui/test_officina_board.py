"""Officina phase 2 (U5): the board's "TO-BE contro target" pill (spec §7.4).

The pill is read from ``case.review.summary`` (``caso.json`` → ``riepilogo``),
never from a comparison run for the board: the worst state (R15, marks
subtracted so the board matches the case bar), its count and the percentage,
a tooltip with the full breakdown in the case bar's order, and
"vN · da riconfrontare" when the summary is of an older TO-BE.
"""
from __future__ import annotations

import dataclasses

import pytest

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import CaseSummary, Judged
from qtrequestory.ui.pages import officina_board_pill as bp
from qtrequestory.ui.pages.officina_board import summary_pill
from qtrequestory.ui.pages.officina_progress import state_counts
from qtrequestory.ui.pages.officina_verdict_style import pill_counts
from qtrequestory.ui.pages.officina_verdict_style import LOOKS, WORST_ORDER, board_counts, worst
from tests.fakes.fake_core import fake_diff
from tests.fakes.fake_verdict import _summary as fake_summary
from tests.ui.test_officina_page import open_case, wait_idle


def _summary(**counts) -> CaseSummary:
    values = dict(version=2, fatte=0, da_fare=0, in_corso=0, regressioni=0, da_verificare=0,
                  non_risolte=0, tollerate=0, variabili=0, rumore=0, avanzamento=0.5,
                  two_way=False, when="2026-09-25T10:00:00")
    values.update(counts)
    return CaseSummary(**values)


# ------------------------------------------------------------- worst (R15) ---

@pytest.mark.parametrize(("counts", "expected"), [
    (dict(regressioni=1, da_fare=3, non_risolte=1, fatte=2), "regressione"),
    (dict(da_fare=3, non_risolte=1, in_corso=1), "non_risolta"),
    (dict(da_fare=2, in_corso=1, fatte=1), "da_fare"),
    (dict(in_corso=1, fatte=4), "in_corso"),
    (dict(da_fare=1, da_verificare=1, fatte=3), "da_verificare"),
    (dict(da_fare=2, da_verificare=1), "da_fare"),
    (dict(fatte=5, tollerate=2, variabili=3), "fatta"),
    (dict(tollerate=1, rumore=2), ""),
    # the only regression is marked: the marks are subtracted from it (R15)
    (dict(regressioni=1, da_verificare=1, fatte=1), "da_verificare"),
    (dict(regressioni=2, da_verificare=1), "regressione"),
    # R44: a marked non risolta is "da verificare" AND still in the non risolte total
    (dict(da_fare=1, non_risolte=1, da_verificare=1), "non_risolta"),
    # ambiguous (which verdict holds the mark?): the worse one stays on the board
    (dict(regressioni=1, da_fare=1, da_verificare=1), "regressione"),
    (dict(in_corso=1, da_fare=1, da_verificare=1), "da_fare"),
])
def test_worst_state_subtracts_the_marks(counts, expected):
    assert worst(_summary(**counts)) == expected


def test_board_counts_take_the_marks_out_of_the_verdicts_and_keep_every_flag():
    counts = board_counts(_summary(regressioni=1, da_fare=3, non_risolte=1, in_corso=2,
                                   da_verificare=2, fatte=4, tollerate=1, variabili=5, rumore=2))
    # the marks are taken from the mildest verdicts first (in corso), pessimistic;
    # the non risolte are the summary's (R44: also counted in their verdict)
    assert counts == {"regressione": 1, "non_risolta": 1, "da_fare": 3, "in_corso": 0,
                      "da_verificare": 2, "fatta": 4, "tollerata": 1, "variabile": 5,
                      "rumore": 2}


def _j(verdict, *, klass="testo", **flags) -> Judged:
    return Judged(fake_diff("cambiato", klass, f"t{id(flags)}", "g"), verdict, **flags)


@pytest.mark.parametrize("judged", [
    [_j("regressione", marked=True), _j("fatta")],
    [_j("da_fare", marked=True), _j("da_fare", unresolved=True)],
    [_j("da_fare"), _j("da_fare", unresolved=True), _j("in_corso"), _j("fatta")],
    [_j("da_fare", unresolved=True, marked=True), _j("in_corso", marked=True)],
    [_j("regressione"), _j("da_fare", marked=True), _j("tollerata"), _j(None, klass="variabile")],
    [_j("in_corso", marked=True), _j("in_corso", marked=True), _j("fatta"), _j(None, klass="rumore")],
    # R31/R44: a flag on any open verdict, counted in its verdict AND in non risolte
    [_j("in_corso", unresolved=True), _j("in_corso", unresolved=True), _j("fatta")],
    [_j("in_corso"), _j("da_fare", unresolved=True), _j("da_fare"), _j("fatta")],
    [_j("in_corso", unresolved=True), _j("da_fare")],
    [_j("regressione", unresolved=True), _j("da_fare"), _j("in_corso")],
    [_j("regressione", unresolved=True), _j("da_fare", unresolved=True, marked=True)],
])
def test_the_board_matches_the_case_bar_when_the_marks_are_derivable(judged):
    """The fake's summary (the same counting as the engine's verdict._summary)
    read back by the board gives the case bar's totals (R44: ``pill_counts``)."""
    summary = fake_summary(judged, 2, False, "2026-09-25T10:00:00")
    by_state = pill_counts(judged)
    counts = board_counts(summary)
    assert {s: n for s, n in counts.items() if n} == {s: n for s, n in by_state.items()
                                                       if n and s != "nessuno"}


@pytest.mark.parametrize("judged", [
    [_j("in_corso", unresolved=True), _j("regressione"), _j("da_fare", marked=True)],
    [_j("in_corso", marked=True), _j("da_fare")],
    [_j("regressione", marked=True), _j("da_fare"), _j("in_corso", unresolved=True)],
])
def test_an_ambiguous_mark_never_makes_the_board_milder_than_the_case_bar(judged):
    """Which verdict a MARK sits on is not in the summary (flags are exact
    now, R44): the board's split may differ from the bar's, its pill is
    never milder."""
    summary = fake_summary(judged, 2, False, "2026-09-25T10:00:00")
    by_state = pill_counts(judged)
    bar_worst = next(s for s in WORST_ORDER if by_state[s])
    assert WORST_ORDER.index(worst(summary)) <= WORST_ORDER.index(bar_worst)
    counts = board_counts(summary)
    open_states = ("regressione", "non_risolta", "da_fare", "in_corso", "da_verificare")
    assert sum(counts[s] for s in open_states) == sum(by_state[s] for s in open_states)


# ------------------------------------------------------------- the badge ---

class _Case:
    """What ``board_badge`` reads of a case."""

    def __init__(self, summary, *, target=True, latest=2, asis=True,
                 target_at="2026-09-25T09:00:00", asis_at="2026-09-25T09:00:00"):
        self.review = type("R", (), {"summary": summary})()
        self._target, self._latest, self._asis = target, latest, asis
        self._at = {"target": target_at, "asis": asis_at}

    def _version(self, kind):
        from datetime import datetime
        return type("V", (), {"created": datetime.fromisoformat(self._at[kind]) if self._at[kind] else None})()

    def target(self):
        return self._version("target") if self._target else None

    def asis(self):
        return self._version("asis") if self._asis else None

    def latest_tobe(self):
        return type("V", (), {"number": self._latest})() if self._latest else None


@pytest.mark.parametrize(("counts", "state", "text"), [
    (dict(regressioni=1, da_fare=2, fatte=1), "regressione", "▲ 1 regressione · 50%"),
    (dict(da_fare=3, non_risolte=2), "non_risolta", "○! 2 non risolte · 50%"),
    (dict(da_fare=2, fatte=2), "da_fare", "○ 2 da fare · 50%"),
    (dict(in_corso=1, fatte=1), "in_corso", "◐ 1 in corso · 50%"),
    (dict(da_fare=2, da_verificare=2, fatte=2), "da_verificare", "✓? 2 da verificare · 50%"),
    (dict(fatte=6, tollerate=1, avanzamento=1.0), "fatta", "✓ 6 fatte · 100%"),
])
def test_the_pill_shows_the_worst_state_its_count_and_the_percentage(counts, state, text):
    badge = bp.board_badge(_Case(_summary(**counts)))
    assert (badge.state, badge.text, badge.tone, badge.pill) == (state, text, LOOKS[state].pill,
                                                                 True)


def test_the_tooltip_has_the_full_breakdown_in_the_case_bar_order():
    summary = _summary(regressioni=1, da_fare=3, non_risolte=1, in_corso=1, da_verificare=1,
                       fatte=2, tollerate=2, variabili=3, rumore=1, avanzamento=0.33)
    tip = bp.board_badge(_Case(summary)).tooltip
    lines = bp.plain(tip).splitlines()
    assert lines[0] == "v2 contro target · 33%"
    assert lines[1:] == ["▲ 1 regressione", "○! 1 non risolta", "○ 3 da fare",
                         "✓? 1 da verificare", "✓ 2 fatte", "⊘ 2 tollerate", "{x} 3 variabili",
                         "~ 1 rumore", strings.AVANZAMENTO_NON_RISOLTA_TIP]  # R44: two totals


def test_the_tooltip_says_two_way():
    tip = bp.plain(bp.board_badge(_Case(_summary(da_fare=1, two_way=True), asis=False)).tooltip)
    assert strings.BACHECA_TIP_TWO_WAY in tip.splitlines()


@pytest.mark.parametrize("case", [
    # an AS-IS generated after a two-way summary ("Genera AS-IS mancanti" from the board)
    dict(asis=True, summary=dict(two_way=True)),
    # the AS-IS (or the target) newer than the summary
    dict(asis_at="2026-09-25T10:30:00"),
    dict(target_at="2026-09-25T11:00:00"),
])
def test_a_summary_older_than_its_target_or_asis_says_da_riconfrontare(case):
    """U5 minor 1 (R42): not only a newer TO-BE makes the pill stale."""
    summary = _summary(regressioni=1, **case.pop("summary", {}))
    badge = bp.board_badge(_Case(summary, **case))
    assert badge.text == "v2 · da riconfrontare" and badge.state == ""
    assert bp.plain(badge.tooltip).splitlines()[0] == strings.BACHECA_STALE_INPUTS_TIP.format(version=2)


def test_an_asis_of_the_same_second_as_the_summary_is_not_stale():
    badge = bp.board_badge(_Case(_summary(regressioni=1), asis_at="2026-09-25T10:00:00.400000"))
    assert badge.state == "regressione"


def test_a_summary_of_an_older_tobe_says_da_riconfrontare():
    badge = bp.board_badge(_Case(_summary(version=3, regressioni=1), latest=4))
    assert badge.text == "v3 · da riconfrontare"
    assert badge.tone == "neutral" and badge.pill
    tip = bp.plain(badge.tooltip).splitlines()
    assert tip[0] == strings.BACHECA_STALE_TIP.format(version=3, latest=4)
    assert "▲ 1 regressione" in tip


def test_nothing_counting_is_no_pill():
    badge = bp.board_badge(_Case(_summary(tollerate=2, rumore=1, avanzamento=1.0)))
    assert badge.state == "" and not badge.pill
    assert badge.text == strings.BACHECA_NOTHING


def test_missing_target_tobe_or_summary():
    assert bp.board_badge(_Case(None, target=False)).text == strings.OFFICINA_PILL_NO_TARGET
    assert bp.board_badge(_Case(None, latest=0)).text == strings.OFFICINA_PILL_NO_TOBE
    never = bp.board_badge(_Case(None, latest=2))
    assert never.text == strings.BACHECA_NOT_COMPARED and never.tone == "neutral"


def test_summary_pill_is_a_label_with_the_tone_and_the_plain_text(qtbot):
    label = summary_pill(_Case(_summary(regressioni=1)))
    qtbot.addWidget(label)
    assert label.property("pill") == "bad"
    assert label.property("plain") == "▲ 1 regressione · 50%"
    assert "regressione" in label.toolTip()
    nothing = summary_pill(_Case(_summary()))
    qtbot.addWidget(nothing)
    assert nothing.property("pill") is None and nothing.property("role") == "muted"


# ------------------------------------------------------------- page level ---

@pytest.fixture
def page(qtbot, fake_core, runner):
    from qtrequestory.ui.pages.officina_page import OfficinaPage
    from tests.ui.test_officina_page import FakeWindow

    widget = OfficinaPage(fake_core, runner, FakeWindow())
    qtbot.addWidget(widget)
    widget.resize(1300, 760)
    widget.show()
    return widget


def test_the_board_reads_the_summary_and_runs_no_comparison(qtbot, page, fake_core, tmp_path):
    case = open_case(page, fake_core, tmp_path)
    page.case_view.regenerate_button.click()
    wait_idle(qtbot, page)
    api = fake_core.officina
    api.set_canned(case.id, 1, [fake_diff("cambiato", "testo", "12,00", "11,00")])
    before = len(api.compare_case_calls)
    page.open_case(case.id, "v1")
    qtbot.waitUntil(lambda: len(api.compare_case_calls) > before and not page.case_view.judging,
                    timeout=10000)
    compares, judged = len(api.compare_calls), len(api.compare_case_calls)
    page.show_board()
    qtbot.wait(100)
    assert page.board.row_texts(case.id)[2] == "○ 1 da fare · 0%"
    assert (len(api.compare_calls), len(api.compare_case_calls)) == (compares, judged)


def test_a_new_tobe_turns_the_pill_stale(qtbot, page, fake_core, tmp_path):
    case = open_case(page, fake_core, tmp_path)
    page.case_view.regenerate_button.click()
    wait_idle(qtbot, page)
    api = fake_core.officina
    api.set_canned(case.id, 1, [fake_diff("cambiato", "testo", "12,00", "11,00")])
    before = len(api.compare_case_calls)
    page.open_case(case.id, "v1")
    qtbot.waitUntil(lambda: len(api.compare_case_calls) > before and not page.case_view.judging,
                    timeout=10000)
    page.show_board()
    page.regenerate_tobe([case.id])
    wait_idle(qtbot, page)
    qtbot.waitUntil(lambda: page.board.row_texts(case.id)[2] == "v1 · da riconfrontare",
                    timeout=5000)


def test_the_page_keeps_the_summary_it_was_given_by_the_comparison(qtbot, page, fake_core,
                                                                    tmp_path, monkeypatch):
    """A core whose compare_case does not update the case object in memory
    still leaves the board with the new summary (the page copies it)."""
    case = open_case(page, fake_core, tmp_path)
    page.case_view.regenerate_button.click()
    wait_idle(qtbot, page)
    api = fake_core.officina
    api.set_canned(case.id, 1, [fake_diff("cambiato", "testo", "12,00", "11,00")])
    real = api.compare_case

    def detached(ini, c, version):
        return real(ini, dataclasses.replace(c, review=dataclasses.replace(c.review)), version)

    monkeypatch.setattr(api, "compare_case", detached)
    page._case(case.id).review.summary = None
    page.open_case(case.id, "v1")
    qtbot.waitUntil(lambda: page.case_view.docs is not None
                    and page.case_view.docs.judged is not None, timeout=10000)
    page.show_board()
    assert page.board.row_texts(case.id)[2] == "○ 1 da fare · 0%"


def test_a_stuck_regression_stays_a_regression_everywhere():
    """R31/R44: a "non risolta" regressione keeps its verdict and its red
    state (never downgraded); its look carries the flag."""
    from qtrequestory.ui.pages.officina_verdict_style import look_for, state_of

    stuck = _j("regressione", unresolved=True)
    assert state_of(stuck) == "regressione"
    assert look_for(stuck).icon == LOOKS["regressione"].icon + "!"
    assert look_for(stuck).label == strings.VERDETTO_FLAGGED.format(state=strings.VERDETTO_REGRESSIONE)
    judged = [stuck, _j("da_fare")]
    summary = fake_summary(judged, 2, False, "2026-09-25T10:00:00")
    assert worst(summary) == "regressione"
    # R44: in the regressioni AND in the non risolte total, on the bar and on the board alike
    expected = {"regressione": 1, "non_risolta": 1, "da_fare": 1}
    assert {s: n for s, n in board_counts(summary).items() if n} == expected
    assert {s: n for s, n in pill_counts(judged).items() if n} == expected


def test_a_stuck_in_corso_is_non_risolta_with_its_before_and_after():
    """R31/R42: in corso + flag reads "non risolta" (worse than in corso) and
    the row still says what it was before."""
    from qtrequestory.ui.pages.officina_rows import notes_for
    from qtrequestory.ui.pages.officina_verdict_style import state_of

    stuck = dataclasses.replace(_j("in_corso", unresolved=True), previous_text="prima")
    assert state_of(stuck) == "non_risolta"
    notes = [text for text, _tone in notes_for(stuck, 3, {stuck.diff.anchor: 2})]
    assert notes[0] == strings.ELENCO_NON_RISOLTA.format(n=2, m=3)
    assert any("prima" in text for text in notes[1:])
    regression = _j("regressione", unresolved=True)
    notes = [text for text, _tone in notes_for(regression, 3, {regression.diff.anchor: 2})]
    assert notes[0] == strings.ELENCO_NON_RISOLTA.format(n=2, m=3) and strings.ELENCO_REGRESSIONE in notes
