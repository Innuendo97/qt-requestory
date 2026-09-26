"""qtrequestory.officina.compare.model: the phase-2 comparison contract.

Synthetic data only (this repository is public).
"""
from __future__ import annotations

import dataclasses
import json

import pytest

from qtrequestory.officina.compare import extract_pdf
from qtrequestory.officina.compare.model import (
    COUNTING,
    Anchor,
    CaseSummary,
    Diff,
    Word,
)


def _anchor() -> Anchor:
    return Anchor(op="cambiato", klass="testo", context="il prezzo | al mese", target_text="12,00 euro")


def test_anchor_round_trips_through_json():
    anchor = _anchor()

    raw = json.loads(json.dumps(anchor.to_json()))

    assert Anchor.from_json(raw) == anchor


def test_anchor_to_json_has_a_deterministic_key_order():
    assert list(_anchor().to_json()) == ["op", "klass", "context", "target_text"]


@pytest.mark.parametrize("junk", [
    {}, None, {"op": "x"}, [], "cambiato", 5,
    {"op": "cambiato", "klass": "boh", "context": "", "target_text": ""},
    {"op": "cambiato", "klass": "testo", "context": 3, "target_text": ""},
    {"op": "cambiato", "klass": "testo", "context": ""},
])
def test_anchor_from_junk_is_none(junk):
    assert Anchor.from_json(junk) is None


def _summary(**kw) -> CaseSummary:
    values = dict(version=4, fatte=6, da_fare=2, in_corso=1, regressioni=1, da_verificare=0,
                  non_risolte=1, tollerate=3, variabili=14, rumore=2, avanzamento=0.6,
                  two_way=False, when="2026-09-25T10:00:00")
    values.update(kw)
    return CaseSummary(**values)


def test_case_summary_round_trips_through_json():
    summary = _summary()

    assert CaseSummary.from_json(json.loads(json.dumps(summary.to_json()))) == summary


def test_case_summary_uses_the_spec_keys():
    keys = list(_summary().to_json())

    assert keys[:12] == ["versione", "fatte", "da_fare", "in_corso", "regressioni", "da_verificare",
                         "non_risolte", "tollerate", "variabili", "rumore", "avanzamento", "quando"]


def test_case_summary_written_without_two_way_reads_as_three_way():
    raw = _summary().to_json()
    raw.pop("due_vie")

    assert CaseSummary.from_json(raw) == _summary(two_way=False)


@pytest.mark.parametrize("junk", [
    None, {}, [], {"versione": "4"},
    {**_summary().to_json(), "fatte": True},
    {**_summary().to_json(), "avanzamento": "60%"},
    {**_summary().to_json(), "quando": None},
])
def test_case_summary_from_junk_is_none(junk):
    assert CaseSummary.from_json(junk) is None


def test_counting_matches_the_spec_table():
    """Spec §4.2 step 10: what each profile counts; variabile and rumore never."""
    assert COUNTING == {
        "tollerante": frozenset({"testo", "composizione", "link"}),
        "stretto": frozenset({"testo", "composizione", "link", "stile", "spaziatura"}),
        "solo_testo": frozenset({"testo"}),
    }
    for counted in COUNTING.values():
        assert not counted & {"variabile", "rumore"}


def test_word_gains_size_and_bold_and_extract_pdf_reexports_it():
    word = Word("prezzo", 0, 1.0, 2.0, 3.0, 4.0)

    assert (word.size, word.bold) == (0.0, False)
    assert extract_pdf.Word is Word


def test_diff_display_context_defaults_to_empty_and_is_kept():
    """R33: target-side display context around the change, for the list's snippet."""
    anchor = Anchor("cambiato", "testo", "sara agli", "abilitata")
    plain = Diff(1, "cambiato", "testo", (), (), "abilitata", "abilitato", ((8, 9),), ((8, 9),), anchor)
    assert (plain.context_before, plain.context_after) == ("", "")
    framed = dataclasses.replace(plain, context_before="La carta sarà", context_after="agli acquisti online.")
    assert framed.context_before == "La carta sarà" and framed.context_after == "agli acquisti online."
    assert framed.anchor == plain.anchor, "the context is display only, never part of the key"


def test_case_comparison_inactive_defaults_to_zero():
    """R30: how many tolerances / not-variables / marks do nothing right now."""
    from qtrequestory.officina.compare.model import CaseComparison, Comparison

    empty = Comparison((), True, True, 1, 1, "", 0, ())
    summary = CaseSummary(1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1.0, True, "2026-09-25T10:00:00")
    cc = CaseComparison(1, (), summary, empty, None, None, "tollerante")
    assert cc.inactive == 0
    assert dataclasses.replace(cc, inactive=3).inactive == 3
