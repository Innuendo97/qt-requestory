"""qtrequestory.officina.compare.noise: noise rules (spec §4.2 step 5, rulings R17, R18).

Only synthetic values: the IBAN and the codice fiscale are built here to have
the right SHAPE and belong to nobody.
"""
from __future__ import annotations

import dataclasses
import time

import pytest

from qtrequestory.officina.compare import noise
from qtrequestory.officina.compare.model import Word
from qtrequestory.officina.compare.noise import (
    LINE_CAP,
    NOISE,
    PRESETS,
    SLOW,
    apply,
    compile_rules,
    placeholder,
)
from qtrequestory.officina.compare.normalise import normalise_token
from qtrequestory.officina.compare.slots import SLOT
from qtrequestory.officina.model_review import NoiseRule

#: Synthetic Italian IBAN shape: IT + 2 check digits + CIN + ABI(5) + CAB(5) + account(12).
FAKE_IBAN = "IT" + "99" + "Z" + "12345" + "67890" + "ABCDEF123456"
#: Synthetic codice fiscale shape: 6 letters, 2 digits, month letter, 2 digits, place code, check letter.
FAKE_CF = "TSTTST" + "80" + "A" + "01" + "Z999" + "X"

PRESET_NAMES = ("Numero di pagina", "Data", "IBAN", "Codice fiscale", "CAP", "Importo",
                "Marcatore di firma", "Parametri di tracciamento")

P = placeholder


def _members(keys: list[str]) -> list[tuple[Word, ...]]:
    return [(Word(k, 0, 10.0 * i, 0.0, 10.0 * i + 8, 10.0),) for i, k in enumerate(keys)]


def _run(keys: list[str], rules, line_ends=()):
    return apply(keys, _members(keys), rules, line_ends)


def _keys(text: str) -> list[str]:
    return [normalise_token(t) for t in text.split()]


def _preset(name: str) -> list[tuple[str, object]]:
    rule = next(r for r in PRESETS if r.name == name)
    usable, errors = compile_rules([dataclasses.replace(rule, enabled=True)])
    assert errors == {}
    return usable


def _masked(name: str, text: str, line_ends=()) -> list[str]:
    return _run(_keys(text), _preset(name), line_ends)[0]


# -------------------------------------------------------- presets ---

def test_presets_names_order_and_all_disabled():
    assert tuple(r.name for r in PRESETS) == PRESET_NAMES
    assert all(isinstance(r, NoiseRule) and r.enabled is False for r in PRESETS)
    usable, errors = compile_rules(PRESETS)
    assert usable == [] and errors == {}          # all valid (none too slow), none active by default


def test_preset_rules_are_copies():
    copies = noise.preset_rules()
    copies[0].enabled = True
    assert PRESETS[0].enabled is False


@pytest.mark.parametrize(("name", "text", "expected"), [
    ("Numero di pagina", "Fine Pag. 2 di 3", ["Fine", P("Numero di pagina")]),
    ("Numero di pagina", "Fine sezione 2/3", ["Fine", "sezione", P("Numero di pagina")]),
    ("Data", "Roma, 01/02/2026 firma", ["Roma,", P("Data"), "firma"]),
    ("Data", "il 1 febbraio 2026.", ["il", P("Data") + "."]),
    ("IBAN", f"IBAN {FAKE_IBAN} intestato", ["IBAN", P("IBAN"), "intestato"]),
    ("IBAN", "IBAN IT99 Z123 4567 890A BCDE F123 456 fine", ["IBAN", P("IBAN"), "fine"]),
    ("Codice fiscale", f"CF {FAKE_CF}.", ["CF", P("Codice fiscale") + "."]),
    ("CAP", "00100 Springfield", [P("CAP"), "Springfield"]),
    ("Importo", "totale € 1.234,56 annui", ["totale", P("Importo"), "annui"]),
    ("Importo", "totale 1.234,56 euro", ["totale", P("Importo")]),
    ("Marcatore di firma", "firma `sig,fd=x,sq=000001` qui", ["firma", P("Marcatore di firma"), "qui"]),
    ("Parametri di tracciamento", "https://example.invalid/p?utm_source=a&id=3",
     ["https://example.invalid/p?" + P("Parametri di tracciamento") + "&id=3"]),
])
def test_preset_matches(name: str, text: str, expected: list[str]):
    assert _masked(name, text) == expected


def test_a_numeric_and_a_textual_date_compare_equal():
    rules = _preset("Data")
    numeric = _run(_keys("Roma, 01/02/2026."), rules)[0]
    textual = _run(_keys("Roma, 1 febbraio 2026."), rules)[0]
    assert numeric == textual == ["Roma,", P("Data") + "."]


def test_page_fraction_only_at_a_line_end():
    assert _masked("Numero di pagina", "da 2/3 a 4") == ["da", "2/3", "a", "4"]
    keys = _masked("Numero di pagina", "da 2/3 a 4", line_ends={1})
    assert keys == ["da", P("Numero di pagina"), "a", "4"]


def test_date_numbers_are_not_page_numbers_and_not_caps():
    assert _masked("Numero di pagina", "il 01/02/2026") == ["il", "01/02/2026"]
    assert _masked("CAP", f"{FAKE_IBAN} 01/02/2026") == [FAKE_IBAN, "01/02/2026"]


def test_non_matches_stay():
    assert _masked("IBAN", "IT99 non è un iban") == ["IT99", "non", "è", "un", "iban"]
    assert _masked("Importo", "articolo 1.234") == ["articolo", "1.234"]


# --------------------------------------------------------- apply ---

def test_hits_are_one_per_match_with_first_and_last_key():
    usable, _ = compile_rules([NoiseRule("Data", r"\d{2}/\d{2}/\d{4}"), NoiseRule("N", r"\bN\d+\b")])
    keys, _members_out, hits = _run(["dal", "01/02/2026", "al", "03/04/2026", "N12"], usable)
    assert keys == ["dal", P("Data"), "al", P("Data"), P("N")]
    assert hits == [(1, 1, "Data"), (3, 3, "Data"), (4, 4, "N")]


def test_a_multi_key_match_is_one_unit_with_all_the_members():
    usable, _ = compile_rules([NoiseRule("Pagina", r"Pag\. \d+ di \d+")])
    source = ["x", "Pag.", "2", "di", "3", "y"]
    members = _members(source)
    keys, out_members, hits = apply(source, members, usable)
    assert keys == ["x", P("Pagina"), "y"] and hits == [(1, 4, "Pagina")]
    assert out_members == [members[0], members[1] + members[2] + members[3] + members[4], members[5]]


def test_matches_sharing_a_key_merge_into_one_unit():
    usable, _ = compile_rules([NoiseRule("A", r"a b"), NoiseRule("B", r"c d")])
    keys, out_members, hits = _run(["a", "bc", "d", "e"], usable)
    assert keys == [P("A") + P("B"), "e"] and hits == [(0, 1, "A"), (1, 2, "B")]
    assert len(out_members[0]) == 3


def test_the_first_rule_wins_overlaps():
    usable, _ = compile_rules([NoiseRule("A", r"\d{5}"), NoiseRule("B", r"\d{3}")])
    keys, _m, hits = _run(["12345", "678"], usable)
    assert keys == [P("A"), P("B")] and hits == [(0, 0, "A"), (1, 1, "B")]


def test_placeholders_and_slots_are_never_matched_again():
    usable, _ = compile_rules([NoiseRule("S", "SLOT"), NoiseRule("N", "NOISE")])
    keys = [SLOT, P("X"), "SLOT"]
    assert _run(keys, usable)[0::2] == ([SLOT, P("X"), P("S")], [(2, 2, "S")])


def test_empty_and_whitespace_matches_are_ignored():
    usable, _ = compile_rules([NoiseRule("vuota", "x*"), NoiseRule("spazio", r"\s")])
    assert _run(["a", "b"], usable) == (["a", "b"], _members(["a", "b"]), [])


def test_no_rules_no_keys():
    assert apply([], [], []) == ([], [], [])
    assert _run(["a"], []) == (["a"], _members(["a"]), [])
    assert NOISE == chr(0x2063) + "NOISE:"


def test_keys_and_members_must_match():
    with pytest.raises(ValueError):
        apply(["a", "b"], _members(["a"]), [])


def test_matching_runs_line_by_line():
    usable, _ = compile_rules([NoiseRule("coppia", r"a\sb")])
    assert _run(["a", "b"], usable, line_ends={0})[0] == ["a", "b"]      # never across a line end
    assert _run(["a", "b"], usable)[0] == [P("coppia")]


def test_a_long_line_is_searched_in_capped_pieces():
    usable, _ = compile_rules([NoiseRule("tutto", r".+")])
    keys = ["x" * 99] * 50                                         # one line of 4,999 characters
    out, _m, hits = _run(keys, usable)
    assert len(hits) >= 3
    assert all(sum(len(keys[k]) + 1 for k in range(first, last + 1)) - 1 <= LINE_CAP
               for first, last, _name in hits)
    assert set(out) == {P("tutto")}


# ------------------------------------------------------- compile ---

def test_a_bad_regex_is_reported_and_the_others_still_apply():
    rules = [NoiseRule("rotta", "("), NoiseRule("CAP", r"\b\d{5}\b")]
    usable, errors = compile_rules(rules)
    assert set(errors) == {"rotta"} and isinstance(errors["rotta"], str) and errors["rotta"]
    assert [name for name, _ in usable] == ["CAP"]
    assert _run(["00100", "("], usable)[0] == [P("CAP"), "("]


@pytest.mark.parametrize("pattern", [r"(\w+\s?)+$", r"(a+)+b", r"(.*)*", r"(x*)*", r"(?:a|b+){2,}",
                                     r"(a)(\1b)+", r"(\d+,?){3,}", r"((ab)+c)*"])
def test_potentially_slow_patterns_are_refused_quickly(pattern: str):
    begin = time.perf_counter()
    usable, errors = compile_rules([NoiseRule("lenta", pattern)])
    assert time.perf_counter() - begin < 0.5
    assert usable == [] and errors == {"lenta": SLOW}


@pytest.mark.parametrize("pattern", [r"\d{2}/\d{2}", r"\b\d{5}\b", r"(?:ab)+", r"(a+)?b", r"(?: ?[0-9A-Z]){22}",
                                     r"\w+\s\w+", r"(\d{3}\.)+"])
def test_ordinary_patterns_are_accepted(pattern: str):
    usable, errors = compile_rules([NoiseRule("ok", pattern)])
    assert errors == {} and [name for name, _ in usable] == ["ok"]


def test_an_accepted_rule_on_a_short_input_is_fast():
    usable, _ = compile_rules([NoiseRule("parole", r"(?:\w+ ){3}\w+!$")])
    begin = time.perf_counter()
    _run(["parola"] * 5 + ["!"], usable)
    assert time.perf_counter() - begin < 0.5


def test_disabled_rules_are_checked_but_not_used():
    usable, errors = compile_rules([NoiseRule("spenta", r"\d", enabled=False), NoiseRule("rotta", "[", False)])
    assert usable == [] and set(errors) == {"rotta"}


def test_a_duplicate_name_is_an_error_for_the_duplicate():
    usable, errors = compile_rules([NoiseRule("CAP", r"\d{5}"), NoiseRule("CAP", r"\d{4}")])
    assert [name for name, _ in usable] == ["CAP"] and usable[0][1].pattern == r"\d{5}"
    assert set(errors) == {"CAP"}


def test_a_name_keeps_its_first_error():
    _usable, errors = compile_rules([NoiseRule("x", "("), NoiseRule("x", r"\d")])
    assert errors["x"].startswith("espressione non valida")


def test_empty_name_or_pattern_is_an_error():
    usable, errors = compile_rules([NoiseRule("", r"\d"), NoiseRule("vuota", "")])
    assert usable == [] and set(errors) == {"", "vuota"}


def test_non_string_name_or_pattern_is_an_error_not_a_crash():
    usable, errors = compile_rules([NoiseRule("strana", 12),            # type: ignore[arg-type]
                                    NoiseRule(["lista"], r"\d")])       # type: ignore[arg-type]
    assert usable == [] and set(errors) == {"strana", "['lista']"}


# --------------------------------------------- R21: one list of tracking keys ---

def test_the_tracking_preset_is_built_from_the_url_tracking_keys():
    import re as _re

    from qtrequestory.officina.compare import urls

    preset = next(p for p in noise.PRESETS if p.name == "Parametri di tracciamento")
    usable, errors = noise.compile_rules([dataclasses.replace(preset, enabled=True)])
    assert errors == {} and len(usable) == 1
    pattern = usable[0][1]
    for key in urls.TRACKING_KEYS:
        name = key.replace("*", "campaign")
        assert urls.tracking_drop(name)
        assert pattern.search(f"https://example.invalid/p?a=1&{name}=x"), key
        assert pattern.search(f"https://example.invalid/p?{name.upper()}=x"), key
    assert not pattern.search("https://example.invalid/p?id=3&utmx=1")
    assert _re.sub(pattern, "", "https://example.invalid/p?msclkid=a&id=3") == "https://example.invalid/p?&id=3"
