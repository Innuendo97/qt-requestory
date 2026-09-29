"""The variables' inputs (phase 2.5, task A4): the payload index in Italian
formats, the price-list dictionary, the control generation's words, the
target's placeholders and holes. Synthetic values only."""
from __future__ import annotations

from decimal import Decimal

import pytest

from qtrequestory.officina.compare.graphics import PageGraphics, PathShape
from qtrequestory.officina.compare.holes import Geometry
from qtrequestory.officina.compare.model import Anchor, Comparison, Diff, Word
from qtrequestory.officina.compare.placeholders import LEADER, is_conditional, is_placeholder, rewrite
from qtrequestory.officina.compare.values import (
    Dictionary,
    Values,
    changed_words,
    parse_number,
    payload_index,
    word_key,
)

PAYLOAD = {
    "documents": [{"template": {"scope": "Marca Nuova", "templateKey": "MOD_TEST_A"}}],
    "dossier": {
        "description": "Acme Base Semplice",
        "items": [{"attributes": [{"attributeDescription": "ETICHETTA", "value": "0.01"},
                                  {"attributeAcronym": "NAZ", "value": "89"}]}],
        "start": "2026-03-18T00:00:00+01:00",
        "signed": "1773792000000",
        "short": "abc",
        "flag": True,
        "amount": 1234.5,
    },
}


def test_the_payload_index_holds_data_leaves_in_italian_formats():
    texts, numbers = payload_index(PAYLOAD)
    assert texts["Acme Base Semplice"] == "dossier.description"
    assert texts["18/03/2026"] == "dossier.start"
    assert "18/03/2026" in texts and texts.get("18/03/2026") in ("dossier.start", "dossier.signed")
    assert numbers[Decimal("0.01")] == "dossier.items[0].attributes[0].value"
    assert numbers[Decimal("89")] == "dossier.items[0].attributes[1].value"
    assert "Marca Nuova" not in texts and "ETICHETTA" not in texts and "NAZ" not in texts   # never data
    assert "abc" not in texts                                                             # too short


def test_values_name_printed_values_by_their_value():
    values = Values.of(PAYLOAD)
    assert values.name("0,010") == ("dossier.items[0].attributes[0].value", False)
    assert values.name("1.234,50") == ("dossier.amount", False)
    assert values.name("(89)") == ("dossier.items[0].attributes[1].value", False)
    assert values.name("Marca Nuova") == ("", False)
    assert values.name("  ") == ("", False)


def test_the_values_key_changes_with_what_the_pass_uses():
    assert Values.of(PAYLOAD).key() == Values.of(PAYLOAD).key()
    assert Values.of(PAYLOAD).key() != Values.of({}).key()
    assert Values.of().key() != Values.of(proofs=("buco",)).key()


@pytest.mark.parametrize(("text", "value"), [
    ("0,010", Decimal("0.010")), ("1.234,56", Decimal("1234.56")), ("89", Decimal("89")),
    ("-3,5", Decimal("-3.5")), ("12a", None), ("1,2,3", None), ("", None)])
def test_italian_numbers(text, value):
    assert parse_number(text) == value


def test_a_dictionary_number_matches_rounded_to_the_printed_decimals():
    dictionary = Dictionary(((Decimal("0.246813"), "Listino: quota"), (Decimal("12"), "Listino: mesi")),
                            {"dicembre": "Listino: mese"})
    assert dictionary.name("0,2468") == "Listino: quota"
    assert dictionary.name("0,247") == "Listino: quota"
    assert dictionary.name("12") == "Listino: mesi"
    assert dictionary.name("0,2469") is None
    assert dictionary.name("Dicembre") == "Listino: mese"


def test_changed_words_are_the_left_words_of_text_differences():
    a, b = Word("12", 0, 1, 2, 3, 4), Word("Acme", 0, 5, 2, 9, 4)
    anchor = Anchor("cambiato", "testo", "", "")
    diffs = (Diff(1, "cambiato", "testo", (a,), (), "12", "13", (), (), anchor),
             Diff(2, "cambiato", "stile", (b,), (b,), "Acme", "Acme", (), (), anchor))
    comparison = Comparison(diffs, True, True, 1, 1, "", 0, ())
    assert changed_words(comparison) == frozenset({word_key(a)})


# ------------------------------------------------------------ placeholders ---

@pytest.mark.parametrize("text", ["[xx]", "[X]", "XXXX", "X,XXXX", "XX.XXX,XX", "gg/mm/aaaa", "(gg/mm/aaaa)",
                                  "..........", "____", "{{NOME}}", "{{NOME}},"])
def test_placeholders(text):
    assert is_placeholder(text)


@pytest.mark.parametrize("text", ["xxx", "Xavier", "12", "mesi", "[", "..."])
def test_not_placeholders(text):
    assert not is_placeholder(text)


def test_conditional_or_value_braces():
    assert not is_conditional("NOME") and not is_conditional("CODICE_CLIENTE") and not is_conditional("X,XXXX")
    assert not is_conditional("gg mese aaaa")
    assert is_conditional("Modulo Acme") and is_conditional("Servizio extra (se previsto)")


def test_rewrite_makes_values_leaders_and_drops_conditional_braces():
    assert rewrite(["Ciao", "{{NOME}},", "a", "te"]) == ["Ciao", LEADER + ",", "a", "te"]
    assert rewrite(["il", "{{gg", "mese", "aaaa}}"]) == ["il", LEADER, LEADER, LEADER]
    assert rewrite(["{{Modulo", "Acme}}", "firmato"]) == ["Modulo", "Acme", "firmato"]
    assert rewrite(["{{Voce", "{{E_PCV}}}}", "fine"]) == ["Voce", LEADER, "fine"]
    assert rewrite(["senza", "graffe"]) == ["senza", "graffe"]


# ------------------------------------------------------------------ holes ---

def _line(y: float, *pieces: tuple[float, str]) -> list[Word]:
    out = []
    for x, text in pieces:
        for token in text.split():
            out.append(Word(token, 0, x, y, x + 4.0 * len(token), y + 9.2, 8.0))
            x += 4.0 * len(token) + 2.4
    return out


def test_a_gutter_between_two_columns_is_no_hole():
    lines = [_line(100 + 12 * k, (60.0, "alfa beta gamma delta"), (200.0, "epsilon zeta eta theta")) for k in range(4)]
    geometry = Geometry([[w for line in lines for w in line]], [PageGraphics()])
    a, b = lines[1][3], lines[1][4]
    assert geometry.gap(a, b) == 0.0
    holed = [_line(100, (60.0, "alfa beta gamma delta epsilon zeta eta theta")),
             _line(112, (60.0, "alfa beta"), (160.0, "zeta eta theta")),
             _line(124, (60.0, "alfa beta gamma delta epsilon zeta eta theta"))]
    geometry = Geometry([[w for line in holed for w in line]], [PageGraphics()])
    assert geometry.gap(holed[1][1], holed[1][2]) == pytest.approx(160.0 - holed[1][1].x1)


def test_cells_come_from_thin_rules():
    rules = [PathShape((60.0, y, 400.0, y + 0.5), 0.5, None, (0, 0, 0, 255), 2) for y in (100.0, 120.0)]
    rules += [PathShape((x, 100.0, x + 0.5, 120.0), 0.5, None, (0, 0, 0, 255), 2) for x in (60.0, 200.0, 400.0)]
    geometry = Geometry([], [PageGraphics(tuple(rules))])
    assert geometry.cell(0, 300.0, 110.0) == pytest.approx((200.25, 100.25, 400.25, 120.25))
    assert geometry.cell(0, 300.0, 200.0) is None
