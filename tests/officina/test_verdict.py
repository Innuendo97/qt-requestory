"""qtrequestory.officina.compare.verdict: three-way verdict, tolerances, marks (spec §5.1–5.3).

Built from hand-made :class:`Comparison` objects — no PDFs. The last part runs
the fake's verdict engine (``tests/fakes/fake_verdict.py``, which the UI track
uses) on the same scripted inputs and checks both give identical results.
"""
from __future__ import annotations

import dataclasses

import pytest

from qtrequestory.officina.compare.anchors import disambiguate
from qtrequestory.officina.compare.model import Anchor, Comparison, Diff, Judged, Verification
from qtrequestory.officina.compare.verdict import generated_text, inactive, judge
from qtrequestory.officina.model_review import Mark, Review, Tolerance
from tests.fakes.fake_verdict import fake_judge

WHEN = "2026-09-25T10:00:00"


def _diff(target: str, generated: str, *, op: str = "cambiato", klass: str = "testo", context: str = "",
          diff_id: int = 99) -> Diff:
    anchor = Anchor(op, klass, context, " ".join(target.split()))  # type: ignore[arg-type]
    return Diff(diff_id, op, klass, (), (), target, generated,  # type: ignore[arg-type]
                ((0, len(target)),) if target else (), ((0, len(generated)),) if generated else (), anchor)


def _cmp(*diffs: Diff) -> Comparison:
    return Comparison(tuple(diffs), True, True, 1, 1, "", sum(d.klass == "variabile" for d in diffs), ())


def _run(tobe, asis, review=None, profile="tollerante", version=2):
    return judge(tobe, asis, review if review is not None else Review(), profile, version, when=WHEN)


def _by_target(judged) -> dict[str, Judged]:
    return {j.diff.left_text: j for j in judged}


# ---------------------------------------------------------------- five verdicts ---

def test_the_five_verdicts():
    asis = _cmp(_diff("uno", "one"), _diff("due", "two"), _diff("tre", "three"))
    tobe = _cmp(_diff("due", "two"), _diff("tre", "tres"), _diff("quattro", "four"),
                _diff("cinque", "5", klass="stile"))
    judged, summary, verification, _ = _run(tobe, asis)
    got = {t: j.verdict for t, j in _by_target(judged).items()}
    assert got == {"uno": "fatta", "due": "da_fare", "tre": "in_corso", "quattro": "regressione",
                   "cinque": "tollerata"}
    assert _by_target(judged)["tre"].previous_text == "three"
    assert verification is None
    assert (summary.fatte, summary.da_fare, summary.in_corso, summary.regressioni, summary.tollerate) == (1, 1, 1, 1, 1)
    assert summary.avanzamento == pytest.approx(0.25)
    assert summary.two_way is False and summary.version == 2 and summary.when == WHEN


def test_fatta_carries_the_asis_diff_for_the_target_side():
    asis_diff = _diff("uno", "one", diff_id=7)
    judged, *_ = _run(_cmp(), _cmp(asis_diff))
    (entry,) = judged
    assert entry.verdict == "fatta"
    assert entry.diff.left_text == "uno" and entry.diff.right_text == "one"
    assert entry.diff.anchor == asis_diff.anchor


def test_a_non_counting_asis_diff_that_disappears_is_not_fatta():
    judged, summary, *_ = _run(_cmp(), _cmp(_diff("uno", "one", klass="stile")))
    assert judged == () and summary.fatte == 0


def test_variabile_and_rumore_have_no_verdict():
    tobe = _cmp(_diff("....", "Rossi", klass="variabile"), _diff("Pag. 1", "Pag. 2", klass="rumore"))
    judged, summary, *_ = _run(tobe, _cmp())
    assert [j.verdict for j in judged] == [None, None]
    assert (summary.variabili, summary.rumore) == (1, 1)
    assert summary.avanzamento == 1.0


def test_not_variable_turns_a_variabile_into_a_counting_diff():
    slot = _diff("....", "Rossi", klass="variabile")
    review = Review(not_variables=[(slot.anchor, WHEN)])
    judged, summary, *_ = _run(_cmp(slot), None, review)
    assert judged[0].verdict == "da_fare" and judged[0].diff.klass == "testo"
    assert judged[0].diff.anchor == slot.anchor
    assert summary.variabili == 0


@pytest.mark.parametrize("profile, verdict", [("tollerante", "tollerata"), ("stretto", "da_fare"),
                                              ("solo_testo", "tollerata")])
def test_the_profile_decides_what_counts(profile, verdict):
    d = _diff("uno", "uno", klass="spaziatura")
    judged, *_ = _run(_cmp(d), _cmp(d), profile=profile)
    assert judged[0].verdict == verdict


def test_two_way_without_asis():
    tobe = _cmp(_diff("uno", "one"), _diff("due", "two", klass="stile"), _diff("....", "x", klass="variabile"))
    judged, summary, *_ = _run(tobe, None)
    assert [j.verdict for j in judged] == ["da_fare", "tollerata", None]
    assert summary.two_way is True
    assert summary.regressioni == 0 and summary.fatte == 0
    assert summary.avanzamento == 0.0


def test_avanzamento_is_100_when_nothing_counts():
    tobe = _cmp(_diff("uno", "one", klass="stile"), _diff("....", "x", klass="variabile"))
    _, summary, _, updated = _run(tobe, _cmp())
    assert summary.avanzamento == 1.0
    assert updated.summary == summary


def test_ids_are_renumbered_in_judged_order():
    asis = _cmp(_diff("uno", "one", diff_id=1))
    tobe = _cmp(_diff("due", "two", diff_id=1), _diff("tre", "three", diff_id=2))
    judged, *_ = _run(tobe, asis)
    assert [j.diff.id for j in judged] == [1, 2, 3]
    assert [j.diff.left_text for j in judged] == ["due", "tre", "uno"]


def test_summary_counts_equal_the_judged_list():
    asis = _cmp(_diff("a", "1"), _diff("b", "2"), _diff("c", "3"), _diff("f", "6"))
    tobe = _cmp(_diff("b", "2"), _diff("c", "33"), _diff("d", "4"), _diff("e", "5", klass="stile"),
                _diff("f", "6"), _diff("....", "v", klass="variabile"), _diff("n", "n", klass="rumore"))
    review = Review(marks=[Mark(_diff("d", "4").anchor, "4", 2, WHEN)],
                    unresolved=[(_diff("f", "6").anchor, 1, "6")])
    judged, s, _, _ = _run(tobe, asis, review)
    verdicts = [j.verdict for j in judged]
    assert s.fatte == verdicts.count("fatta") == 1
    assert s.da_fare == verdicts.count("da_fare") == 2
    assert s.in_corso == verdicts.count("in_corso") == 1
    assert s.regressioni == verdicts.count("regressione") == 1
    assert s.tollerate == verdicts.count("tollerata") == 1
    assert s.da_verificare == sum(j.marked for j in judged) == 1
    assert s.non_risolte == sum(j.unresolved for j in judged) == 1
    assert (s.variabili, s.rumore) == (1, 1)
    # the marked regression still counts as a regression (R15), not as done
    assert s.avanzamento == pytest.approx(1 / 5)


# ------------------------------------------------------------------ tolerances ---

def test_tolerance_survives_a_regeneration_with_the_same_text():
    d = _diff("uno", "one  more")
    review = Review(tolerances=[Tolerance(d.anchor, generated_text(d), "va bene così", WHEN)])
    judged, summary, _, updated = _run(_cmp(_diff("uno", "one more")), _cmp(d), review, version=3)
    assert judged[0].verdict == "tollerata" and judged[0].tolerated_note == "va bene così"
    assert summary.tollerate == 1
    assert updated.tolerances == review.tolerances


def test_tolerance_lapses_when_the_generated_text_changes():
    d = _diff("uno", "one")
    review = Review(tolerances=[Tolerance(d.anchor, generated_text(d), "", WHEN)])
    judged, _, _, updated = _run(_cmp(_diff("uno", "uno!")), _cmp(d), review, version=3)
    assert judged[0].verdict == "in_corso"
    assert updated.tolerances == review.tolerances       # kept in the file, inactive
    assert inactive(updated, judged) == 1


def test_generated_text_is_normalised_per_word():
    d = _diff("uno", "l’ offerta – fine")
    assert generated_text(d) == "l' offerta - fine"


# ----------------------------------------------------------------------- marks ---

def test_a_mark_made_in_the_same_version_is_not_verified():
    d = _diff("uno", "one")
    review = Review(marks=[Mark(d.anchor, generated_text(d), 2, WHEN)])
    judged, summary, verification, updated = _run(_cmp(d), _cmp(d), review, version=2)
    assert verification is None
    assert judged[0].verdict == "da_fare" and judged[0].marked
    assert summary.da_verificare == 1 and summary.da_fare == 1
    assert updated.marks == review.marks


def test_mark_resolved_on_the_next_version():
    d = _diff("uno", "one")
    review = Review(marks=[Mark(d.anchor, generated_text(d), 2, WHEN)])
    judged, summary, verification, updated = _run(_cmp(), _cmp(d), review, version=3)
    assert [j.verdict for j in judged] == ["fatta"]
    assert verification == Verification(checked=1, resolved=1, unresolved=0, changed=0, version=3)
    assert updated.marks == [] and summary.da_verificare == 0


def test_mark_unresolved_on_the_next_version_stays_flagged_until_the_diff_changes_state():
    d = _diff("uno", "one")
    review = Review(marks=[Mark(d.anchor, generated_text(d), 2, WHEN)])
    judged, summary, verification, updated = _run(_cmp(d), _cmp(d), review, version=3)
    assert judged[0].verdict == "da_fare" and judged[0].unresolved and not judged[0].marked
    assert (verification.checked, verification.resolved, verification.unresolved, verification.changed) == (1, 0, 1, 0)
    assert updated.marks == [] and updated.unresolved == [(d.anchor, 2, "one")]      # R10: the version it was made in
    assert summary.non_risolte == 1

    # v4: still the same → still flagged, nothing verified any more
    judged, summary, verification, updated = _run(_cmp(d), _cmp(d), updated, version=4)
    assert verification is None and judged[0].unresolved and updated.unresolved == [(d.anchor, 2, "one")]

    # v5: the generated text changes → in corso, the flag is gone
    judged, summary, _, updated = _run(_cmp(_diff("uno", "uno?")), _cmp(d), updated, version=5)
    assert judged[0].verdict == "in_corso" and not judged[0].unresolved
    assert updated.unresolved == [] and summary.non_risolte == 0


def test_mark_changed_on_the_next_version_is_in_corso_with_the_marked_text():
    d = _diff("uno", "one")
    review = Review(marks=[Mark(d.anchor, generated_text(d), 2, WHEN)])
    judged, _, verification, updated = _run(_cmp(_diff("uno", "une")), None, review, version=3)
    assert judged[0].verdict == "in_corso" and judged[0].previous_text == "one"
    assert (verification.resolved, verification.unresolved, verification.changed) == (0, 0, 1)
    assert updated.marks == []


def test_marks_are_verified_per_mark():
    a, b = _diff("uno", "one"), _diff("due", "two")
    review = Review(marks=[Mark(a.anchor, "one", 2, WHEN), Mark(b.anchor, "two", 3, WHEN)])
    judged, summary, verification, updated = _run(_cmp(b), _cmp(a, b), review, version=3)
    assert verification.checked == 1 and verification.resolved == 1
    assert updated.marks == [review.marks[1]]
    assert _by_target(judged)["due"].marked and summary.da_verificare == 1


def test_judge_does_not_mutate_the_review():
    d = _diff("uno", "one")
    review = Review(marks=[Mark(d.anchor, "one", 1, WHEN)], unresolved=[(d.anchor, 1, "one")])
    before = dataclasses.replace(review, marks=list(review.marks), unresolved=list(review.unresolved))
    _run(_cmp(), _cmp(d), review, version=3)
    assert review == before


def test_unresolved_regression_keeps_its_verdict_and_flag_across_versions():
    """R31: a stuck regressione is never downgraded to da fare."""
    d = _diff("uno", "one")
    review = Review(marks=[Mark(d.anchor, generated_text(d), 2, WHEN)])
    judged, summary, verification, updated = _run(_cmp(d), _cmp(), review, version=3)
    assert judged[0].verdict == "regressione" and judged[0].unresolved
    assert verification.unresolved == 1 and updated.unresolved == [(d.anchor, 2, "one")]
    assert (summary.regressioni, summary.da_fare, summary.non_risolte) == (1, 0, 1)

    judged, summary, verification, updated = _run(_cmp(d), _cmp(), updated, version=4)   # identical TO-BE
    assert verification is None
    assert judged[0].verdict == "regressione" and judged[0].unresolved
    assert updated.unresolved == [(d.anchor, 2, "one")]

    judged, summary, _, updated = _run(_cmp(_diff("uno", "one!")), _cmp(), updated, version=5)
    assert judged[0].verdict == "regressione" and not judged[0].unresolved
    assert updated.unresolved == [] and summary.non_risolte == 0


def test_unresolved_in_corso_keeps_its_verdict_and_flag_across_versions():
    before, now = _diff("uno", "one"), _diff("uno", "une")
    review = Review(marks=[Mark(now.anchor, generated_text(now), 2, WHEN)])
    judged, _, verification, updated = _run(_cmp(now), _cmp(before), review, version=3)
    assert judged[0].verdict == "in_corso" and judged[0].unresolved
    assert judged[0].previous_text == "one"                      # refreshed: the AS-IS text
    assert verification.unresolved == 1

    judged, _, _, updated = _run(_cmp(now), _cmp(before), updated, version=4)
    assert judged[0].verdict == "in_corso" and judged[0].unresolved and judged[0].previous_text == "one"

    judged, _, _, updated = _run(_cmp(_diff("uno", "unx")), _cmp(before), updated, version=5)
    assert judged[0].verdict == "in_corso" and not judged[0].unresolved
    assert updated.unresolved == []


def test_unresolved_clears_when_the_difference_disappears():
    d = _diff("uno", "one")
    review = Review(unresolved=[(d.anchor, 2, "one")])
    judged, summary, _, updated = _run(_cmp(), _cmp(d), review, version=4)
    assert [j.verdict for j in judged] == ["fatta"] and not judged[0].unresolved
    assert updated.unresolved == []


def test_unresolved_without_a_known_text_takes_the_current_one():
    d = _diff("uno", "one")
    _, _, _, updated = _run(_cmp(d), _cmp(d), Review(unresolved=[(d.anchor, 2, "")]), version=4)
    assert updated.unresolved == [(d.anchor, 2, "one")]


def test_mark_on_a_diff_tolerated_by_the_profile_is_dormant():
    """R32: marked under "stretto", then the profile goes to "tollerante"."""
    d = _diff("uno", "uno", klass="stile")
    review = Review(marks=[Mark(d.anchor, generated_text(d), 1, WHEN)])

    judged, summary, verification, updated = _run(_cmp(d), _cmp(d), review, profile="tollerante", version=1)
    assert judged[0].verdict == "tollerata" and not judged[0].marked
    assert summary.da_verificare == 0 and updated.marks == review.marks
    assert inactive(updated, judged) == 1

    judged, summary, verification, updated = _run(_cmp(d), _cmp(d), review, profile="tollerante", version=2)
    assert verification is None                                  # not verified, not "resolved"
    assert updated.marks == review.marks and summary.da_verificare == 0

    judged, summary, verification, updated = _run(_cmp(d), _cmp(d), updated, profile="stretto", version=2)
    assert judged[0].verdict == "da_fare" and judged[0].unresolved   # live again: verified now
    assert (verification.checked, verification.unresolved) == (1, 1) and updated.marks == []


def test_mark_on_a_hand_tolerated_diff_is_dormant():
    d = _diff("uno", "one")
    review = Review(tolerances=[Tolerance(d.anchor, "one", "", WHEN)], marks=[Mark(d.anchor, "one", 1, WHEN)])
    judged, _, verification, updated = _run(_cmp(d), _cmp(d), review, version=2)
    assert judged[0].verdict == "tollerata" and verification is None and updated.marks == review.marks


def test_a_dormant_and_a_live_mark_are_verified_separately():
    style, text = _diff("uno", "uno", klass="stile"), _diff("due", "two")
    review = Review(marks=[Mark(style.anchor, "uno", 1, WHEN), Mark(text.anchor, "two", 1, WHEN)])
    _, _, verification, updated = _run(_cmp(style), _cmp(style, text), review, version=2)
    assert (verification.checked, verification.resolved) == (1, 1)
    assert updated.marks == [review.marks[0]]


# ------------------------------------------------------------ anchors (R19) ---

def _rows(*pairs: tuple[str, str]) -> list[Diff]:
    """Diffs in target order with their anchors disambiguated like E4 does."""
    raw = [_diff(t, g, context="riga") for t, g in pairs]
    anchors = disambiguate([d.anchor for d in raw])
    return [dataclasses.replace(d, anchor=a, id=n) for n, (d, a) in enumerate(zip(raw, anchors), 1)]


def test_duplicate_rows_are_judged_independently_with_one_tolerated():
    rows = _rows(("prezzo", "costo"), ("prezzo", "costo"))
    review = Review(tolerances=[Tolerance(rows[1].anchor, "costo", "seconda riga", WHEN)])
    judged, *_ = _run(_cmp(*rows), _cmp(*rows), review)
    assert [j.verdict for j in judged] == ["da_fare", "tollerata"]
    judged, *_ = _run(_cmp(*rows), None, review)
    assert [j.verdict for j in judged] == ["da_fare", "tollerata"]


def test_fixing_the_first_of_two_identical_rows_marks_the_second_as_fatta():
    """Accepted R19 cost, pinned: occurrences are renumbered, so when row 1 is
    fixed the remaining diff (really row 2) takes row 1's anchor, and the
    "fatta" entry is AS-IS row 2 (context "... #2") — counts right, rows swapped."""
    asis = _rows(("prezzo", "costo"), ("prezzo", "costo"))
    tobe = _rows(("prezzo", "costo"))                       # row 2 still wrong, now the only one
    judged, summary, *_ = _run(_cmp(*tobe), _cmp(*asis))
    assert [j.verdict for j in judged] == ["da_fare", "fatta"]
    assert judged[1].diff.anchor.context == "riga #2"
    assert (summary.fatte, summary.da_fare) == (1, 1)


def test_an_inserted_identical_row_shifts_the_occurrences():
    """Accepted R19 cost, pinned: row 1 breaks too, so AS-IS's only diff (row
    2) is matched with TO-BE row 1 and TO-BE row 2 ("#2") reads as regressione."""
    asis = _rows(("prezzo", "costo"))
    tobe = _rows(("prezzo", "costo"), ("prezzo", "costo"))
    judged, summary, *_ = _run(_cmp(*tobe), _cmp(*asis))
    assert [j.verdict for j in judged] == ["da_fare", "regressione"]
    assert (summary.da_fare, summary.regressioni) == (1, 1)


def test_duplicate_anchors_no_longer_fail_an_assertion():
    """R35 replaced the precondition assertion: two-way with twins judges both."""
    d = _diff("uno", "one")
    judged, *_ = _run(_cmp(d, dataclasses.replace(d, id=2)), None)
    assert [j.verdict for j in judged] == ["da_fare", "da_fare"]


# ------------------------------------------------- Review Focus 4: target replaced ---

def test_replaced_target_leaves_entries_inactive():
    old = _diff("vecchio testo", "generato", context="prima")
    tol = _diff("altro vecchio", "x", context="prima")
    review = Review(
        tolerances=[Tolerance(tol.anchor, generated_text(tol), "nota", WHEN)],
        not_variables=[(_diff("....", "v", klass="variabile").anchor, WHEN)],
        marks=[Mark(old.anchor, generated_text(old), 3, WHEN)],
        unresolved=[(_diff("sparito", "y").anchor, 2, "y")],
    )
    # a new target: every anchor is different now
    tobe = _cmp(_diff("nuovo testo", "generato"), _diff("altro nuovo", "x"), _diff("__", "v", klass="variabile"))
    judged, summary, verification, updated = _run(tobe, None, review, version=3)
    assert [j.verdict for j in judged] == ["da_fare", "da_fare", None]
    assert not any(j.marked or j.unresolved or j.tolerated_note for j in judged)
    assert verification is None                             # the mark was made in this version
    assert updated.tolerances == review.tolerances          # kept, inactive
    assert updated.not_variables == review.not_variables
    assert updated.marks == review.marks
    assert updated.unresolved == []                         # its difference is gone: no longer "non risolta"
    assert summary.da_verificare == 0 and summary.tollerate == 0
    assert inactive(updated, judged) == 3                   # tolerance + not-variable + mark


# ------------------------------------------------------ a side without text (R49) ---

def _textless(side: str) -> Comparison:
    return dataclasses.replace(_cmp(), **{f"{side}_has_text": False}, note=f"il {side} non ha testo estraibile")


@pytest.mark.parametrize("side", ["left", "right"])
def test_a_tobe_comparison_without_text_judges_nothing_and_keeps_the_review(side):
    """Final review C1: an empty diff list for lack of text is not "everything fixed"."""
    a = _diff("foo", "bar")
    review = Review(marks=[Mark(a.anchor, "bar", 1, WHEN)], unresolved=[(a.anchor, 1, "bar")])
    judged, summary, verification, updated = _run(_textless(side), _cmp(a), review, version=2)
    assert judged == () and verification is None
    assert (summary.fatte, summary.avanzamento) == (0, 0.0)
    assert updated == review and updated.summary is None


def test_an_asis_comparison_without_text_is_two_way():
    a = _diff("foo", "bar")
    judged, summary, _, _ = _run(_cmp(a), _textless("right"))
    assert [j.verdict for j in judged] == ["da_fare"] and summary.two_way


# ------------------------------------------------------ fidelity with the fake ---

def _scenarios():
    a, b, c = _diff("uno", "one"), _diff("due", "two"), _diff("tre", "three")
    d_new, e_style = _diff("quattro", "four"), _diff("cinque", "5", klass="stile")
    var, noise = _diff("....", "Rossi", klass="variabile"), _diff("Pag. 1", "Pag. 2", klass="rumore")
    c2 = _diff("tre", "tres")
    yield "five verdicts", _cmp(b, c2, d_new, e_style, var, noise), _cmp(a, b, c), Review(), "tollerante", 2
    yield "two way", _cmp(a, e_style, var), None, Review(), "stretto", 1
    yield "solo testo", _cmp(a, e_style, _diff("sei", "6", op="spostato", klass="composizione")), _cmp(a), \
        Review(), "solo_testo", 2
    yield "tolerance on", _cmp(a), _cmp(a), Review(tolerances=[Tolerance(a.anchor, "one", "ok", WHEN)]), \
        "tollerante", 2
    yield "tolerance lapsed", _cmp(_diff("uno", "uno")), _cmp(a), \
        Review(tolerances=[Tolerance(a.anchor, "one", "ok", WHEN)]), "tollerante", 2
    yield "not variable", _cmp(var), _cmp(var), Review(not_variables=[(var.anchor, WHEN)]), "tollerante", 2
    marks = [Mark(a.anchor, "one", 1, WHEN), Mark(b.anchor, "two", 1, WHEN), Mark(c.anchor, "three", 1, WHEN),
             Mark(d_new.anchor, "four", 2, WHEN)]
    yield "marks", _cmp(b, c2, d_new), _cmp(a, b, c), Review(marks=marks), "tollerante", 2
    yield "stuck regression", _cmp(d_new), _cmp(), Review(marks=[Mark(d_new.anchor, "four", 1, WHEN)]), \
        "tollerante", 2
    yield "tolerated mark", _cmp(e_style), _cmp(), Review(marks=[Mark(e_style.anchor, "5", 1, WHEN)]), \
        "tollerante", 2
    yield "remembered", _cmp(b, c2), _cmp(b, c), Review(unresolved=[(b.anchor, 1, "two"), (c.anchor, 1, "three")]), \
        "tollerante", 3
    yield "same version mark", _cmp(a, b), _cmp(a), Review(marks=[Mark(a.anchor, "one", 2, WHEN),
                                                                   Mark(b.anchor, "two", 2, WHEN)]), "stretto", 2
    yield "remembered unknown text", _cmp(b), _cmp(b), Review(unresolved=[(b.anchor, 1, "")]), "tollerante", 3
    yield "stuck regression twice", _cmp(d_new), _cmp(), Review(unresolved=[(d_new.anchor, 1, "four")]),         "tollerante", 3
    yield "stuck in corso", _cmp(c2), _cmp(c), Review(marks=[Mark(c.anchor, "tres", 1, WHEN)]), "tollerante", 2
    yield "dormant by profile", _cmp(e_style), _cmp(e_style), Review(marks=[Mark(e_style.anchor, "5", 1, WHEN)]),         "tollerante", 2
    yield "dormant back to life", _cmp(e_style), _cmp(), Review(marks=[Mark(e_style.anchor, "5", 1, WHEN)]),         "stretto", 3
    yield "nothing", _cmp(), None, Review(), "tollerante", 1
    yield "tobe without text", dataclasses.replace(_cmp(), right_has_text=False), _cmp(a),         Review(marks=[Mark(a.anchor, "one", 1, WHEN)]), "tollerante", 2
    yield "target without text", dataclasses.replace(_cmp(), left_has_text=False), None,         Review(marks=[Mark(a.anchor, "one", 1, WHEN)]), "tollerante", 2
    yield "asis without text", _cmp(a, b), dataclasses.replace(_cmp(), right_has_text=False), Review(),         "tollerante", 2


@pytest.mark.parametrize("name, tobe, asis, review, profile, version", list(_scenarios()),
                         ids=[s[0] for s in _scenarios()])
def test_engine_and_fake_agree(name, tobe, asis, review, profile, version):
    engine = judge(tobe, asis, review, profile, version, when=WHEN)
    fake = fake_judge(tobe, asis, review, profile, version, WHEN)
    assert engine == fake


# ------------------------------------------------------ duplicates (R35) ---

def test_duplicate_anchors_warn_and_are_judged_apart_instead_of_raising(caplog):
    twin_a, twin_b = _diff("prezzo", "costo", diff_id=1), _diff("prezzo", "costo", diff_id=2)
    assert twin_a.anchor == twin_b.anchor
    with caplog.at_level("WARNING"):
        judged, summary, _, _ = _run(_cmp(twin_a, twin_b), _cmp(twin_a, twin_b))
    assert len({j.diff.anchor for j in judged}) == 2
    assert [j.verdict for j in judged] == ["da_fare", "da_fare"]
    assert "ancore" in caplog.text or "anchor" in caplog.text
