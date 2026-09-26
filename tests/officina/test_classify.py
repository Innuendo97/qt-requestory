"""qtrequestory.officina.compare.classify: classes and profiles (spec §4.2 step 10)."""
from __future__ import annotations

import pytest

from qtrequestory.officina.compare.classify import classify, counts
from qtrequestory.officina.compare.model import Anchor, Diff
from qtrequestory.officina.compare.noise import placeholder

DATE = placeholder("Data")


def _diff(klass: str) -> Diff:
    return Diff(1, "cambiato", klass, (), (), "", "", (), (), Anchor("cambiato", klass, "", ""))  # type: ignore[arg-type]


def test_plain_text_is_testo():
    assert classify("cambiato", ["dodici"], ["dodoci"]) == "testo"
    assert classify("mancante", ["dodici"], []) == "testo"
    assert classify("in_piu", [], ["dodici"]) == "testo"


def test_slot_wins_over_everything():
    assert classify("cambiato", ["x"], [DATE], slot=True) == "variabile"


@pytest.mark.parametrize("op", ["sezione_assente", "sezione_in_piu", "spostato", "pagine"])
def test_layout_operations_are_composizione(op: str):
    assert classify(op, ["uno"], ["due"]) == "composizione"  # type: ignore[arg-type]


def test_noise_covered_text_is_rumore():
    assert classify("cambiato", [DATE + "."], [DATE + "."]) == "rumore"
    assert classify("mancante", [DATE], []) == "rumore"
    assert classify("in_piu", [], [DATE, placeholder("IBAN")]) == "rumore"


def test_a_placeholder_with_other_residue_or_rule_is_testo():
    assert classify("cambiato", [DATE], [DATE + "."]) == "testo"
    assert classify("cambiato", [DATE], [placeholder("IBAN")]) == "testo"
    assert classify("cambiato", [DATE, "e"], [DATE]) == "testo"


def test_equal_keys_in_another_style_are_stile():
    assert classify("cambiato", ["fisso"], ["fisso"], style=True) == "stile"


def test_only_spaces_moved_is_spaziatura():
    assert classify("cambiato", ["fornitura"], ["forni", "tura"]) == "spaziatura"
    assert classify("cambiato", ["il", "prezzo"], ["ilprezzo"]) == "spaziatura"
    assert classify("cambiato", ["fornitura"], ["forni", "ture"]) == "testo"


@pytest.mark.parametrize(("profile", "counting"), [
    ("tollerante", {"testo", "composizione", "link"}),
    ("stretto", {"testo", "composizione", "link", "stile", "spaziatura"}),
    ("solo_testo", {"testo"}),
])
def test_counts_follows_the_profile(profile: str, counting: set[str]):
    for klass in ("testo", "composizione", "stile", "spaziatura", "variabile", "rumore", "link"):
        assert counts(_diff(klass), profile) is (klass in counting), (profile, klass)  # type: ignore[arg-type]
