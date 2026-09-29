"""``officina.control``: the control generation's safe perturbation and what
it proves (phase 2.5, spec §3.4; task A5). Pure; synthetic data only."""
from __future__ import annotations

import random
import re
from datetime import date
from decimal import Decimal

import pytest

from qtrequestory.officina.compare.model import Anchor, Comparison, Diff, Word
from qtrequestory.officina.compare.values import word_key
from qtrequestory.officina.control import (
    Leaf,
    perturb,
    perturb_value,
    structural,
    structure_changed,
    subsets,
    visible_leaves,
)
from qtrequestory.officina.control_proof import map_executed, printed_forms, proven_words


def _words(text: str, page: int = 0, y: float = 100.0) -> list[Word]:
    out, x = [], 60.0
    for token in text.split():
        out.append(Word(token, page, x, y, x + 5 * len(token), y + 9))
        x += 5 * len(token) + 3
    return out

PAYLOAD = {
    "documents": [{"template": {"templateKey": "MOD_TEST_A"},
                   "attributes": [{"key": "attachmentId", "value": "att-0"},
                                  {"key": "attachmentUrl", "value": "https://example.invalid/blob/doc.pdf"},
                                  {"key": "titoloModulo", "value": "Modulo Acme-Servizi"}]}],
    "cliente": {"nome": "Alfa Beta", "clienteId": "CL-000001", "fiscalCode": "TSTTST80A01Z999X",
                "privacy": True, "note": None},
    "offerta": {"importo": 12.5, "durata": 24, "decorrenza": "2026-03-18", "firma": "1773792000000",
                "stato": "ATTIVA", "sito": "https://example.invalid/offerta", "codiceOfferta": "OFF123"},
}
DOC = _words("Modulo Acme-Servizi per ALFA BETA durata 24 mesi importo 12,50 euro dal 18/03/2026 "
             "firmato il 18/03/2026 codice OFF123 stato ATTIVA TSTTST80A01Z999X CL-000001 att-0")


@pytest.mark.parametrize(("key", "expected"), [
    ("attachmentId", True), ("templateKey", True), ("fiscalCode", True), ("codiceOfferta", True),
    ("codice", True), ("stato", True), ("tipo", True), ("customer_type", True), ("url", True),
    ("attributeOrder", True), ("order", True), ("length", True), ("level", True), ("precision", True),
    ("listRefNumber", True), ("maxSaleableItems", True), ("tipoOfferta", True), ("statoPratica", True),
    ("flagRinnovo", True), ("isActive", True), ("operation", True), ("positionPaper", True), ("quantity", True),
    ("nome", False), ("importo", False), ("ragioneSociale", False), ("IBAN", False), ("", False),
    ("indirizzoSede", False), ("durata", False),
])
def test_structural_keys_by_their_last_or_first_word(key, expected):
    assert structural(key) is expected


def test_only_printed_non_structural_leaves_are_perturbed():
    paths = {leaf.path for leaf in visible_leaves(PAYLOAD, DOC)}
    assert paths == {("cliente", "nome"), ("offerta", "importo"), ("offerta", "durata"),
                     ("offerta", "decorrenza"), ("offerta", "firma")}
    # never: the template, the attachment plumbing (a pair's key), ids, codes, fiscal code, states, URLs,
    # bools, null
    assert visible_leaves(PAYLOAD, _words("nulla di stampato")) == []


def test_plumbing_numbers_enums_and_structural_parents_are_never_perturbed():
    """F18: what a condition or the layout uses, even when "printed" by chance."""
    payload = {
        "voci": [{"attributeOrder": 3, "attributeValue": "1", "length": 12, "level": 2}],
        "righe": [{"order": 1, "quantita": 7, "canone": 9, "mesi": 12}],
        "addresses": [{"type": {"code": "RES", "value": "Residenza"}, "via": "Viale Lorem"}],
        "dossier": {"operation": {"descrizione": "Voltura contratto"}, "tipoPratica": "Nuova"},
        "scelta": "BASE_PLUS", "nome": "Gamma",
    }
    doc = _words("3 1 12 2 7 9 12 Residenza Viale Lorem Voltura contratto Nuova BASE_PLUS Gamma")
    paths = {leaf.path for leaf in visible_leaves(payload, doc)}
    assert paths == {("righe", 0, "canone"), ("righe", 0, "mesi"), ("addresses", 0, "via"), ("nome",)}


def test_a_short_or_unprinted_text_is_never_visible():
    assert visible_leaves({"a": "ab", "b": "zeta"}, _words("ab zetaz")) == []
    assert [leaf.path for leaf in visible_leaves({"b": "zeta"}, _words("la zeta."))] == [("b",)]


@pytest.mark.parametrize("seed", range(20))
def test_numbers_keep_their_digit_count_and_type(seed):
    rnd = random.Random(seed)
    for value in (7, 24, 1500, -305):
        new = perturb_value(value, rnd)
        assert isinstance(new, int) and new != value and len(str(abs(new))) == len(str(abs(value)))
        assert (new < 0) == (value < 0)
    new = perturb_value(12.5, rnd)
    assert isinstance(new, float) and new != 12.5 and re.fullmatch(r"[1-9]\d\.\d", repr(new))
    new = perturb_value(0.075, rnd)
    assert re.fullmatch(r"0\.0\d\d", repr(new)) and new != 0.075
    assert perturb_value(1e-07, rnd) is None


@pytest.mark.parametrize("seed", range(20))
def test_texts_keep_length_case_and_alphabet(seed):
    rnd = random.Random(seed)
    for value in ("Alfa Beta", "OFF123", "12,50", "0,010", "via Roma 1/B"):
        new = perturb_value(value, rnd)
        assert isinstance(new, str) and new != value and len(new) == len(value)
        for a, b in zip(value, new, strict=True):
            assert a.isupper() == b.isupper() and a.islower() == b.islower() and a.isdigit() == b.isdigit()
            if not a.isalnum():
                assert a == b
        assert (new[0] == "0") == (value[0] == "0")


@pytest.mark.parametrize("seed", range(20))
def test_dates_stay_valid_in_their_format(seed):
    rnd = random.Random(seed)
    iso = perturb_value("2026-03-18", rnd)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", iso) and iso != "2026-03-18"
    date.fromisoformat(iso)
    stamped = perturb_value("2026-03-18T10:00:00Z", rnd)
    assert stamped.endswith("T10:00:00Z") and stamped != "2026-03-18T10:00:00Z"
    italian = perturb_value("28/02/2026", rnd)
    d, m, y = italian.split("/")
    assert date(int(y), int(m), int(d)) and italian != "28/02/2026"
    epoch = perturb_value("1773792000000", rnd)
    assert len(epoch) == 13 and (int(epoch) - 1773792000000) % 86_400_000 == 0 and epoch != "1773792000000"


def test_what_cannot_keep_its_format_is_left_alone():
    rnd = random.Random(0)
    assert perturb_value(True, rnd) is None and perturb_value(None, rnd) is None
    assert perturb_value("---", rnd) is None and perturb_value([1], rnd) is None


def test_perturb_is_a_deterministic_copy():
    leaves = visible_leaves(PAYLOAD, DOC)
    first, changed = perturb(PAYLOAD, leaves, "seme")
    again, _ = perturb(PAYLOAD, leaves, "seme")
    assert first == again and first is not PAYLOAD and [leaf for leaf, _ in changed] == leaves
    assert all(new != leaf.value and first["cliente"]["nome"] for leaf, new in changed)
    assert PAYLOAD["cliente"]["nome"] == "Alfa Beta"              # the original is untouched
    assert first["cliente"]["nome"] != "Alfa Beta"
    assert first["documents"] == PAYLOAD["documents"] and first["cliente"]["clienteId"] == "CL-000001"
    assert first["offerta"]["stato"] == "ATTIVA"


def test_subsets_try_all_then_halves_within_the_budget():
    leaves = [Leaf(("k", n), n) for n in range(5)]
    tried = list(subsets(leaves, 3))
    assert [[leaf.value for leaf in group] for group in tried] == [[0, 1, 2, 3, 4], [0, 1, 2], [3, 4]]
    assert len(list(subsets(leaves, 10))) == 9 and list(subsets([], 3)) == []


def _cmp(*diffs: Diff, pages: tuple[int, int] = (1, 1)) -> Comparison:
    return Comparison(tuple(diffs), True, True, pages[0], pages[1], "", 0, ())


def _diff(op: str) -> Diff:
    return Diff(1, op, "testo", (), (), "a", "b", (), (), Anchor(op, "testo", "", "a"))


def test_structure_changes_are_pages_and_sections():
    assert not structure_changed(_cmp(_diff("cambiato"), _diff("in_piu")))
    assert structure_changed(_cmp(pages=(1, 2)))
    assert structure_changed(_cmp(_diff("sezione_in_piu")))
    assert structure_changed(_cmp(_diff("sezione_assente")))


def test_executed_words_follow_the_same_words_into_another_version():
    reference = _words("Quota vale ALFA euro al periodo")
    executed = frozenset({word_key(reference[2])})
    moved = _words("Nuova riga Quota vale ALFA euro al periodo", y=114.0)
    assert map_executed(reference, moved, executed) == {word_key(moved[4])}
    gone = _words("Quota vale euro al periodo")
    assert map_executed(reference, gone, executed) == frozenset()
    assert map_executed(reference, moved, frozenset()) == frozenset()


def _changed(left: str, right: str, op: str = "cambiato", klass: str = "testo") -> Diff:
    return Diff(1, op, klass, tuple(_words(left, y=200.0)), tuple(_words(right, y=200.0)), left, right, (), (),
                Anchor(op, klass, left, left))


def test_printed_forms_of_a_value():
    assert printed_forms("Alfa Beta") == ({"alfa", "beta"}, frozenset())
    assert printed_forms(12.5) == printed_forms("12.50") == (frozenset(), {Decimal("12.5")})
    assert printed_forms("2026-03-18")[0] == {"18/03/2026"}
    assert printed_forms(True) == (frozenset(), frozenset())


def test_only_the_printed_perturbed_values_are_proven():
    """F18: a label a condition switched (it changed too) proves nothing; the
    amount the perturbation changed is proven, and only where the control
    prints the perturbed amount."""
    label = _changed("Tariffa standard", "Tariffa variata")
    amount = _changed("Importo 12,50", "Importo 47,30")
    name = _changed("Sig. ALFA", "Sig. KQZD")
    unrelated = _changed("vale 12,50", "vale 12,50 circa")    # the old amount elsewhere, not replaced there
    proven = proven_words(_cmp(label, amount, name, unrelated), [(12.5, 47.3), ("Alfa", "Kqzd")])
    assert {k[3] for k in proven} == {"12,50", "ALFA"}
    assert word_key(amount.left[1]) in proven and word_key(unrelated.left[1]) not in proven
    assert proven_words(_cmp(label), [(12.5, 47.3)]) == frozenset()


def _two_lines(first: str, second: str) -> tuple[Word, ...]:
    return (*_words(first, y=200.0), *_words(second, y=212.0))


def test_a_template_word_switched_next_to_a_multi_word_value_is_never_proven():
    """Re-review I1: «Alfa Sicura» perturbed to «Kqzd Pbrtwq» also switches
    a template word «alfa» → «gamma» in the SAME difference (same line, or
    across a line break): only the whole value's run is proven."""
    same = _changed("Alfa Sicura alfa", "Kqzd Pbrtwq gamma")
    left, right = _two_lines("Alfa Sicura", "la alfa"), _two_lines("Kqzd Pbrtwq", "il gamma")
    broken = Diff(1, "cambiato", "testo", left, right, "Alfa Sicura la alfa", "Kqzd Pbrtwq il gamma", (), (),
                  Anchor("cambiato", "testo", "x", "x"))
    for d in (same, broken):
        proven = proven_words(_cmp(d), [("Alfa Sicura", "Kqzd Pbrtwq")])
        assert proven == {word_key(d.left[0]), word_key(d.left[1])}, d.left_text
    # a partial run (one word of the value) is never proven, nor a run the control does not print whole
    assert proven_words(_cmp(_changed("Alfa lorem", "Kqzd lorem")), [("Alfa Sicura", "Kqzd Pbrtwq")]) == frozenset()
    assert proven_words(_cmp(_changed("Alfa Sicura", "Kqzd Sicura")), [("Alfa Sicura", "Kqzd Pbrtwq")]) == frozenset()


def test_the_whole_value_runs_on_the_real_pipeline(tmp_path):
    """The same two probes through ``compare_docs`` on synthetic PDFs."""
    from qtrequestory.officina.compare.extract_pdf import extract
    from qtrequestory.officina.compare.pipeline import compare_docs

    from .controlgen import RUNNING, pdf

    def doc(name: str, lines: list[str]):
        path = tmp_path / f"{name}.pdf"
        path.write_bytes(pdf([[(60, 100 + 14 * k, line) for k, line in enumerate([RUNNING[0], *lines, RUNNING[1]])]]))
        return extract(path)

    for lines, perturbed in ((["Prodotto Alfa Sicura alfa verde"], ["Prodotto Kqzd Pbrtwq gamma verde"]),
                             (["Prodotto Alfa Sicura", "la alfa arriva presto"],
                              ["Prodotto Kqzd Pbrtwq", "il gamma arriva presto"])):
        comparison = compare_docs(doc("g", lines), doc("c", perturbed), zones=False)
        proven = proven_words(comparison, [("Alfa Sicura", "Kqzd Pbrtwq")])
        assert sorted(k[3] for k in proven) == ["Alfa", "Sicura"], [(d.left_text, d.right_text)
                                                                    for d in comparison.diffs]
