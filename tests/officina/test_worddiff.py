"""qtrequestory.officina.compare.worddiff: word and character diff (spec §4.2 step 8).

Units are built here from synthetic words on explicit lines.
"""
from __future__ import annotations

from qtrequestory.officina.compare.model import Word
from qtrequestory.officina.compare.noise import placeholder
from qtrequestory.officina.compare.normalise import units
from qtrequestory.officina.compare.slots import find_slots
from qtrequestory.officina.compare.worddiff import CHAR_LIMIT, Change, changes, char_spans, opcodes


def _lines(*lines: str, size: float = 11.0, bold: frozenset[str] = frozenset(), top: float = 50.0) -> list[Word]:
    words: list[Word] = []
    for row, line in enumerate(lines):
        y, x = top + 20.0 * row, 40.0
        for token in line.split():
            words.append(Word(token, 0, x, y, x + 6.0 * len(token), y + 11.0, size, token in bold))
            x += 6.0 * (len(token) + 1)
    return words


def _side(*lines: str, **kw):
    keys, members = units(_lines(*lines, **kw))
    return keys, members


def _diff(left: tuple[str, ...], right: tuple[str, ...], *, slotted: bool = False, **kw) -> tuple[list[Change], list, list]:
    lk, lm = _side(*left)
    rk, rm = _side(*right, **kw)
    slots = {}
    if slotted:
        lk, lm, found = find_slots(lk, lm, ())
        slots = {s.index: s for s in found}
    return changes(lk, lm, rk, rm, slots), lk, rk


# ------------------------------------------------------------ opcodes ---

def test_opcodes_match_sequence_matcher_without_fixed_ranges():
    a, b = list("abcdef"), list("abXdef")
    assert opcodes(a, b) == [("equal", 0, 2, 0, 2), ("replace", 2, 3, 2, 3), ("equal", 3, 6, 3, 6)]


def test_fixed_ranges_are_equal_and_the_matcher_runs_between_them():
    a = ["x", "p", "q", "y", "p", "q"]
    b = ["p", "q", "z", "p", "q"]
    assert opcodes(a, b, fixed=[(4, 6, 3, 5)]) == [
        ("delete", 0, 1, 0, 0), ("equal", 1, 3, 0, 2), ("replace", 3, 4, 2, 3), ("equal", 4, 6, 3, 5)]


def test_a_fixed_range_out_of_order_is_ignored():
    a, b = ["p", "q", "r"], ["p", "q", "r"]
    assert opcodes(a, b, fixed=[(1, 2, 1, 2), (0, 1, 0, 1)]) == [("equal", 0, 3, 0, 3)]


def test_adjacent_equal_opcodes_are_merged():
    a = b = ["uno", "due", "tre", "quattro"]
    assert opcodes(a, b, fixed=[(0, 2, 0, 2), (2, 4, 2, 4)]) == [("equal", 0, 4, 0, 4)]


def test_long_gaps_are_cut_at_patience_anchors_and_stay_fast():
    import time

    from qtrequestory.officina.compare.worddiff import PATIENCE_MIN

    a = [f"w{k % 700}" if k % 3 else f"u{k}" for k in range(20_000)]    # common and unique keys
    b = list(a)
    changed = list(range(10, 20_000, 20))
    for k in changed:
        b[k] = "cambiata"
    assert len(a) > PATIENCE_MIN
    started = time.perf_counter()
    got = opcodes(a, b)
    elapsed = time.perf_counter() - started
    assert elapsed < 3, f"{elapsed:.2f} s"
    assert [k for tag, i1, i2, _, _ in got if tag != "equal" for k in range(i1, i2)] == changed
    assert all(tag in ("equal", "replace") for tag, *_ in got)
    assert [k for _, i1, i2, _, _ in got for k in a[i1:i2]] == a


def test_a_long_form_without_unique_words_is_cut_at_the_given_points():
    import time

    rows = 1500
    a = ["Nome", "⁣SLOT", "Cognome", "⁣SLOT"] * rows
    b = ["Nome", "Anna", "Cognome", "Neri"] * rows          # nothing occurs once
    cuts = [(4 * k, 4 * k) for k in range(1, rows)]
    started = time.perf_counter()
    got = opcodes(a, b, cuts=cuts)
    elapsed = time.perf_counter() - started
    assert elapsed < 3, f"{elapsed:.2f} s"
    assert [code for code in got if code[0] != "equal"] == [
        ("replace", 4 * k + d, 4 * k + d + 1, 4 * k + d, 4 * k + d + 1) for k in range(rows) for d in (1, 3)]
    short = opcodes(a[:40], b[:40], cuts=[(20, 21)])     # short: the cuts are not used
    assert short == opcodes(a[:40], b[:40])


def test_a_lone_unique_word_is_no_anchor():
    from qtrequestory.officina.compare.worddiff import _patience

    a = ["x"] * 5 + ["solo"] + ["y"] * 5
    b = ["z"] * 5 + ["solo"] + ["k"] * 5
    assert _patience(a, b, 0, len(a), 0, len(b)) == []
    b2 = ["z"] * 4 + ["x", "solo", "y"] + ["k"] * 4
    assert _patience(a, b2, 0, len(a), 0, len(b2)) == [(4, 7, 4, 7)]


# ---------------------------------------------------------- char spans ---

def test_char_spans_mark_the_changed_letter_on_both_sides():
    assert char_spans("dodici", "dodoci") == (((3, 4),), ((3, 4),))


def test_char_spans_of_an_insertion_are_one_sided():
    assert char_spans("copia", "coppia") == ((), ((3, 4),))


def test_char_spans_of_a_huge_text_are_the_whole_texts():
    big = "a" * (CHAR_LIMIT + 1)
    assert char_spans(big, "b") == (((0, CHAR_LIMIT + 1),), ((0, 1),))
    assert char_spans("", big) == ((), ((0, CHAR_LIMIT + 1),))


# ------------------------------------------------------------- changes ---

def test_replace_delete_insert_become_cambiato_mancante_in_piu():
    found, _, _ = _diff(("uno due tre quattro cinque",), ("uno DUE tre cinque sei",))
    assert [(c.op, c.i1, c.i2, c.j1, c.j2) for c in found] == [
        ("cambiato", 1, 2, 1, 2), ("mancante", 3, 4, 3, 3), ("in_piu", 5, 5, 4, 5)]


def test_a_sure_slot_swallows_the_value():
    found, lk, rk = _diff(("Nome .......... Cognome ..........",), ("Nome Maria Luisa Cognome Neri",), slotted=True)
    assert [(c.op, rk[c.j1:c.j2], c.slot is not None) for c in found] == [
        ("cambiato", ["Maria", "Luisa"], True), ("cambiato", ["Neri"], True)]


def test_a_slot_after_a_changed_label_splits_the_region():
    found, _, rk = _diff(("Comune: ..........", "Fine"), ("Città: Springfield", "Fine"), slotted=True)
    assert [(c.op, rk[c.j1:c.j2], c.slot is not None) for c in found] == [
        ("cambiato", ["Città:"], False), ("cambiato", ["Springfield"], True)]


def test_a_slot_that_swallows_nothing_stays_in_the_missing_run():
    found, lk, _ = _diff(("Prima riga", "Nome .......... Cognome ..........", "Ultima riga"),
                         ("Prima riga", "Ultima riga"), slotted=True)
    assert len(found) == 1 and found[0].op == "mancante" and found[0].slot is None
    assert found[0].i2 - found[0].i1 == 4            # Nome SLOT Cognome SLOT


def test_a_probable_slot_refuses_a_long_value():
    found, _, rk = _diff(("Note:", "Firma"), ("Note: questa frase è decisamente troppo lunga per un campo", "Firma"),
                         slotted=True)
    assert [(c.op, c.slot) for c in found] == [("in_piu", None)]
    assert len(rk[found[0].j1:found[0].j2]) == 9


def test_bold_or_size_change_of_equal_words_is_one_style_change_per_run():
    found, _, _ = _diff(("il prezzo resta fisso", "per dodici mesi"), ("il prezzo resta fisso", "per dodici mesi"),
                        bold=frozenset({"resta", "fisso", "per"}))
    assert [(c.op, c.style, c.i1, c.i2) for c in found] == [("cambiato", True, 2, 5)]   # across the line end
    lk, lm = _side("il prezzo")
    rk, rm = _side("il prezzo", size=11.4)
    assert changes(lk, lm, rk, rm, {}) == []         # within ±0.5 pt
    rk, rm = _side("il prezzo", size=12.0)
    assert [c.style for c in changes(lk, lm, rk, rm, {})] == [True]


def test_unknown_sizes_are_never_a_style_change():
    lk, lm = _side("il prezzo", size=0.0)
    rk, rm = _side("il prezzo", size=14.0, bold=frozenset({"prezzo"}))
    assert changes(lk, lm, rk, rm, {}) == []


def test_equal_placeholders_over_different_texts_are_a_noise_change():
    key = placeholder("Data")
    lm = [tuple(_lines("01/02/2026"))]
    rm = [tuple(_lines("1 febbraio 2026"))]
    assert changes([key], lm, [key], rm, {}) == [Change("cambiato", 0, 1, 0, 1, noise=True)]
    assert changes([key], lm, [key], [tuple(_lines("01/02/2026"))], {}) == []


def test_hard_bounds_split_a_region_around_a_whole_range():
    a = ["x", "s1", "s2", "s3", "Il", "y"]
    b = ["x", "Lo", "y"]
    found = changes(a, [()] * 6, b, [()] * 3, {}, bounds=([(1, 4)], []))
    assert [(c.op, c.i1, c.i2, c.j1, c.j2) for c in found] == [("mancante", 1, 4, 1, 1), ("cambiato", 4, 5, 1, 2)]
    found = changes(b, [()] * 3, a, [()] * 6, {}, bounds=([], [(1, 4)]))
    assert [(c.op, c.i1, c.i2, c.j1, c.j2) for c in found] == [("in_piu", 1, 1, 1, 4), ("cambiato", 1, 2, 4, 5)]
    # a range only partly inside the region is no boundary
    assert [c.op for c in changes(a, [()] * 6, b, [()] * 3, {}, bounds=([(0, 3)], []))] == ["cambiato"]


def test_a_style_run_stops_at_a_block_break():
    lk, lm = _side("uno due tre")
    rk, rm = _side("uno due tre", size=14.0)
    found = changes(lk, lm, rk, rm, {}, breaks=({2}, {2}))
    assert [(c.i1, c.i2) for c in found] == [(0, 2), (2, 3)]


# ------------------------------------------- refined split parts (E4 deferred → E7) ---

def test_refine_keeps_only_the_changed_words_of_a_part():
    from qtrequestory.officina.compare.worddiff import refine

    a = ["X", "H", "i", "l", "m", "n"]
    b = ["Y", "i", "l", "m", "n"]
    assert refine(a, b, 1, 6, 0, 5, {}) == [(1, 2, 0, 1)]
    assert refine(["a", "b", "c"], ["a", "c"], 0, 3, 0, 2, {}) == [(1, 2, 1, 1)]
    assert refine(["a"], ["b"], 0, 1, 0, 1, {}) == [(0, 1, 0, 1)]
    assert refine(["a", "b"], ["a", "b"], 0, 2, 0, 2, {}) == []


def test_refine_leaves_a_part_with_a_slot_or_one_side_alone():
    from qtrequestory.officina.compare.worddiff import refine

    assert refine(["a", "S", "c"], ["a", "v", "c"], 0, 3, 0, 3, {1: object()}) == [(0, 3, 0, 3)]
    assert refine(["a", "b"], [], 0, 2, 0, 0, {}) == [(0, 2, 0, 0)]
