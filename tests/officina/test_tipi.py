"""qtrequestory.officina.compare.tipi: the type of a difference (spec §3.5, D8)."""
from __future__ import annotations

import pytest

from qtrequestory.officina.compare.model import TIPI, Anchor, Diff
from qtrequestory.officina.compare.tipi import tipo_of


def diff(left: str, right: str, *, op: str = "", klass: str = "testo") -> Diff:
    op = op or ("cambiato" if left and right else "mancante" if left else "in_piu")
    return Diff(1, op, klass, (), (), left, right, (), (), Anchor(op, klass, "", left))  # type: ignore[arg-type]


@pytest.mark.parametrize(("left", "right", "tipo"), [
    ("lorem", "Lorem", "maiuscole"),
    ("ACME verde", "Acme Verde", "maiuscole"),
    ("S.p.A", "S.p.A.", "punteggiatura"),
    ("zeta.", "zeta:", "punteggiatura"),
    ("Acme", "Acme:", "punteggiatura"),
    ("0,021", "0,022", "numeri"),
    ("il .", "il 01/02/2030.", "numeri"),
    ("€/mese", "0,021 €/mese", "numeri"),
    ("Acme-Servizi", "Beta-Servizi", "parola"),
    ("BetaAcme", "Acme Servizi Lorem", "parola"),
    ("lorem ipsum dolor sit amet", "lorem consectetur adipiscing", "frase"),
])
def test_a_change_gets_the_kind_of_what_changed(left, right, tipo):
    assert tipo_of(diff(left, right)) == tipo


@pytest.mark.parametrize(("left", "right"), [
    ("1.000", "1,000"), ("-10,00", "10,00"), ("10-12", "10/12"), ("0,5", "0.5"), ("€ 5,00", "€ 5.00"),
])
def test_a_change_of_signs_between_digits_is_numeri_not_punteggiatura(left, right):
    """Review A3 I3: a sign flip or a thousand/decimal swap must never be
    tolerated in bulk as "solo punteggiatura"."""
    assert tipo_of(diff(left, right)) == "numeri"


def test_punctuation_away_from_digits_stays_punteggiatura():
    assert tipo_of(diff("Acme, 12 lorem", "Acme 12 lorem")) == "punteggiatura"


def test_spacing_is_spazi():
    assert tipo_of(diff("lo rem", "lorem", klass="spaziatura")) == "spazi"


@pytest.mark.parametrize(("left", "right", "tipo"), [
    ("", "12", "numeri"),
    ("31/12/2026", "", "numeri"),
    ("", ",", "punteggiatura"),
    ("", "Acme", "parola"),
    ("uno due tre quattro", "", "frase"),
])
def test_a_text_on_one_side_only(left, right, tipo):
    assert tipo_of(diff(left, right)) == tipo


@pytest.mark.parametrize(("op", "klass", "tipo"), [
    ("spostato", "composizione", "spostamento"),
    ("sezione_assente", "composizione", "sezione"),
    ("sezione_in_piu", "composizione", "sezione"),
    ("pagine", "composizione", "sezione"),
    ("cambiato", "link", "link"),
])
def test_layout_and_links(op, klass, tipo):
    assert tipo_of(diff("a b", "c d", op=op, klass=klass)) == tipo


def test_a_zone_with_text_on_one_side_only_is_zona():
    assert tipo_of(diff("", "Acme Servizi", klass="zona"), zone_alone=True) == "zona"
    assert tipo_of(diff("", "Acme Servizi", klass="zona")) == "parola"


def test_a_style_change_is_altro():
    assert tipo_of(diff("Titolo", "Titolo", klass="stile")) == "altro"


def test_every_type_is_a_contract_type():
    samples = [diff("a", "A"), diff("a.", "a:"), diff("1", "2"), diff("a", "b"), diff("a b c d", "e"),
               diff("a", "b", op="spostato", klass="composizione"), diff("a", "b", klass="link"),
               diff("a", "a", klass="stile")]
    assert {tipo_of(d) for d in samples} <= set(TIPI)


# --------------------------------- meaningful signs are never punctuation ---

@pytest.mark.parametrize(("left", "right"), [
    ("10 %", "10"), ("10%", "10"), ("5 ‰", "5"), ("+10", "10"), ("10 €", "10"), ("10°", "10"),
    ("< 10", "10"), ("= 10", "10"), ("$ 5", "5"), ("£ 5", "5"),
])
def test_a_meaningful_sign_next_to_digits_is_numeri(left, right):
    """Final review M1: «Tollera tutte: solo punteggiatura» must never take a
    percentage, a currency or a comparison sign."""
    assert tipo_of(diff(left, right)) == "numeri"


@pytest.mark.parametrize(("left", "right"), [
    ("§ lorem", "lorem"), ("Acme §", "Acme"), ("lorem*", "lorem"), ("lorem #", "lorem"), ("Acme & Beta", "Acme Beta"),
    ("lorem@acme", "loremacme"), ("a + b", "a b"), ("a = b", "a b"), ("a < b", "a > b"), ("lorem €", "lorem $"),
    ("gradi°", "gradi"), ("lorem ¥", "lorem"), ("x ± y", "x y"),
])
def test_a_meaningful_sign_away_from_digits_is_altro_not_punteggiatura(left, right):
    assert tipo_of(diff(left, right)) == "altro"


@pytest.mark.parametrize("alone", ["%", "§", "*", "#", "&", "@", "+", "=", "<", ">", "°", "€", "$", "£", "‰", "∑"])
def test_a_meaningful_sign_alone_missing_or_added_is_altro(alone):
    assert tipo_of(diff(alone, "")) == "altro"
    assert tipo_of(diff("", alone)) == "altro"


def test_a_percentage_alone_is_numeri():
    assert tipo_of(diff("", "10 %")) == "numeri"


def test_plain_punctuation_is_still_punteggiatura():
    assert tipo_of(diff("", ";")) == "punteggiatura"
    assert tipo_of(diff("lorem, ipsum", "lorem ipsum")) == "punteggiatura"
    assert tipo_of(diff("«lorem»", "\"lorem\"")) == "punteggiatura"
