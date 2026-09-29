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
    """Spec §4.2 step 10 + phase 2.5 (§3.2, §3.5): what each profile counts;
    ``zona`` counts in every profile (D4), variabile, rumore and arredo never."""
    assert COUNTING == {
        "tollerante": frozenset({"testo", "composizione", "link", "zona"}),
        "stretto": frozenset({"testo", "composizione", "link", "stile", "spaziatura", "zona"}),
        "solo_testo": frozenset({"testo", "zona"}),
    }
    for counted in COUNTING.values():
        assert not counted & {"variabile", "rumore", "arredo"}


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


# ------------------------------------------------ phase 2.5: the T0 contract ---

def test_klasses_gain_zona_and_arredo_and_keep_the_13x_ones():
    from qtrequestory.officina.compare.model import KLASSES

    assert KLASSES == ("testo", "composizione", "stile", "spaziatura", "variabile", "rumore", "link",
                       "zona", "arredo")


def test_zones_tipi_and_proofs_are_the_spec_words():
    from qtrequestory.officina.compare.model import ARREDO_ZONES, PROVE, TIPI, ZONES

    assert ZONES == ("header", "titolo", "footer", "spalla_sx", "spalla_dx", "numero_pagina", "filigrana",
                     "corpo")
    assert TIPI == ("maiuscole", "punteggiatura", "spazi", "numeri", "parola", "frase", "sezione",
                    "spostamento", "zona", "link", "altro")
    assert PROVE == ("segnaposto", "buco", "cella", "sezione", "esecuzione", "listino")
    assert ARREDO_ZONES == frozenset({"numero_pagina", "filigrana"}) and ARREDO_ZONES <= set(ZONES)


def test_word_and_diff_new_fields_default_to_the_13x_meaning():
    """A 1.3.x call site (no zone/tipo/prova/nome) builds a body difference of type "altro"."""
    word = Word("prezzo", 0, 1.0, 2.0, 3.0, 4.0)
    diff = Diff(1, "cambiato", "testo", (word,), (), "prezzo", "costo", ((0, 6),), ((0, 5),), _anchor())

    assert word.zone == "corpo"
    assert (diff.zone, diff.tipo, diff.prova, diff.nome) == ("corpo", "altro", "", "")
    zoned = dataclasses.replace(diff, klass="zona", zone="footer", tipo="parola", prova="buco", nome="cliente.nome")
    assert (zoned.zone, zoned.tipo, zoned.prova, zoned.nome) == ("footer", "parola", "buco", "cliente.nome")
    assert zoned.anchor == diff.anchor  # the anchor never carries zone or tipo


def test_an_anchor_of_a_new_klass_round_trips():
    for klass in ("zona", "arredo"):
        anchor = Anchor("cambiato", klass, "a | b", "Edizione 09/2026")
        assert Anchor.from_json(json.loads(json.dumps(anchor.to_json()))) == anchor


def test_zona_counts_and_arredo_does_not():
    from qtrequestory.officina.compare.model import Comparison

    zona = Diff(1, "cambiato", "zona", (), (), "a", "b", (), (), Anchor("cambiato", "zona", "", "a"), zone="footer")
    arredo = Diff(2, "cambiato", "arredo", (), (), "1", "2", (), (), Anchor("cambiato", "arredo", "", "1"),
                  zone="numero_pagina")
    comparison = Comparison((zona, arredo), True, True, 1, 1, "", 0, ())

    for profile in COUNTING:
        assert comparison.counting(profile) == (zona,)


def test_case_comparison_filters_is_optional():
    from qtrequestory.officina.compare.model import CaseComparison, Comparison
    from qtrequestory.officina.compare.filter_model import ControlState, FilterPanel

    empty = Comparison((), True, True, 1, 1, "", 0, ())
    summary = CaseSummary(1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1.0, True, "2026-09-28T10:00:00")
    cc = CaseComparison(1, (), summary, empty, None, None, "tollerante")

    assert cc.filters is None and cc.inactive == 0
    panel = FilterPanel((), ControlState("assente"))
    assert dataclasses.replace(cc, filters=panel).filters is panel


def test_arredo_has_no_verdict_like_variables_and_noise():
    """F3: arredo is never judged (never in "Tollerate") and is counted apart."""
    from qtrequestory.officina.compare.model import NO_VERDICT

    assert NO_VERDICT == frozenset({"variabile", "rumore", "arredo"})


def test_case_summary_gains_arredo_defaulted_and_round_trips():
    assert _summary().arredo == 0
    summary = _summary(arredo=3)
    raw = json.loads(json.dumps(summary.to_json()))
    assert raw["arredo"] == 3 and CaseSummary.from_json(raw) == summary
    raw.pop("arredo")  # a 1.3.x riepilogo
    assert CaseSummary.from_json(raw) == _summary()
    for junk in (-1, "3", True, None):
        assert CaseSummary.from_json({**summary.to_json(), "arredo": junk}) is None
