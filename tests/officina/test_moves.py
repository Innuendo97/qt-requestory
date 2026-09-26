"""qtrequestory.officina.compare.moves: moved blocks and moved text (spec §4.2 step 9)."""
from __future__ import annotations

from qtrequestory.officina.compare.model import Block, Word
from qtrequestory.officina.compare.moves import MIN_WORDS, RATIO, out_of_order, reading_order, similar, text_moves


def test_values_are_the_spec_ones():
    assert (MIN_WORDS, RATIO) == (3, 0.85)


def test_pairs_in_order_are_no_move():
    assert out_of_order([(0, 0), (1, None), (None, 1), (2, 2)]) == []


def test_a_block_moved_to_the_end_is_the_one_move():
    assert out_of_order([(0, 3), (1, 0), (2, 1), (3, 2)]) == [([0], [3])]


def test_consecutive_moved_blocks_are_one_run():
    pairs = [(0, 3), (1, 4), (2, 0), (3, 1), (4, 2), (5, 5)]
    assert out_of_order(pairs) == [([0, 1], [3, 4])]


def test_moved_blocks_not_consecutive_on_the_generated_side_are_separate():
    pairs = [(0, 4), (1, 2), (2, 0), (3, 1), (4, 3)]
    runs = out_of_order(pairs)
    assert sum(len(t) for t, _ in runs) == 2
    assert all(len(t) == 1 for t, _ in runs)


def test_two_swapped_blocks_move_one_deterministically():
    assert out_of_order([(0, 1), (1, 0)]) == out_of_order([(0, 1), (1, 0)]) == [([0], [1])]


def test_same_text_deleted_and_inserted_is_one_move():
    moved = ["il", "cliente", "può", "recedere", "in", "ogni", "momento"]
    assert text_moves([["uno", "due"], moved], [["tre", "quattro", "cinque"], moved]) == [(1, 1)]


def test_a_nearly_equal_text_moves_and_a_different_one_does_not():
    base = "il cliente può recedere dal contratto in ogni momento senza penali".split()
    near = base[:-1] + ["penale"]          # 10 of 11 keys: ratio 0.91
    far = base[:6] + ["con", "un", "preavviso", "di", "trenta"]
    assert text_moves([base], [near]) == [(0, 0)]
    assert text_moves([base], [far]) == []


def test_short_texts_never_move_and_each_run_is_used_once():
    assert text_moves([["due", "parole"]], [["due", "parole"]]) == []
    three = ["tre", "parole", "uguali"]
    assert text_moves([three, three], [three]) == [(0, 0)]


def _blocks(*texts: str) -> list[Block]:
    return [Block(k, tuple(Word(t, 0, 0.0, 0.0, 0.0, 0.0) for t in text.split()), 0, "html")
            for k, text in enumerate(texts)]


def test_similar_is_the_move_threshold():
    a, b = _blocks("uno due tre quattro cinque sei sette otto nove dieci",
                   "uno due tre quattro cinque sei sette otto nove undici")
    assert similar(a, b)                            # 9 of 10 keys
    c, d = _blocks("importo € 112,00", "importo € 301,00")
    assert not similar(c, d)


def test_a_strong_pair_out_of_order_is_read_at_its_partners_place():
    left = _blocks("mossa uno due tre", "alfa beta gamma", "delta epsilon zeta")
    right = _blocks("alfa beta gamma", "delta epsilon zeta", "mossa uno due tre")
    order, runs = reading_order([(0, 2), (1, 0), (2, 1)], left, right)
    assert (order, runs) == ([2, 0, 1], [([0], [2])])


def test_a_weak_pair_out_of_order_stays_in_its_own_position():
    left = _blocks("importo € 112,00", "alfa beta gamma", "delta epsilon zeta")
    right = _blocks("alfa beta gamma", "delta epsilon zeta", "importo € 301,00")
    assert reading_order([(0, 2), (1, 0), (2, 1)], left, right) == ([0, 1, 2], [])
