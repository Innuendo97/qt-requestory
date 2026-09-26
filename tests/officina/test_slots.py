"""qtrequestory.officina.compare.slots: variable slots in the target (spec §4.2 step 4).

Words are synthetic, built here on explicit lines.
"""
from __future__ import annotations

from qtrequestory.officina.compare.model import Anchor, Word
from qtrequestory.officina.compare.normalise import units
from qtrequestory.officina.compare.slots import (
    MAX_PROBABLE_WORDS,
    SLOT,
    Slot,
    absorb,
    find_slots,
    slot_anchor,
)


def _lines(*lines: tuple[str, ...], pitch: float = 60.0) -> list[Word]:
    """Words laid out on consecutive lines (one tuple per line)."""
    words: list[Word] = []
    for row, tokens in enumerate(lines):
        y = 50.0 + 20.0 * row
        words += [Word(t, 0, 40.0 + pitch * i, y, 40.0 + pitch * i + 50.0, y + 10.0) for i, t in enumerate(tokens)]
    return words


def _slots(*lines: tuple[str, ...], disabled=()):
    keys, members = units(_lines(*lines))
    return find_slots(keys, members, disabled)


# ---------------------------------------------------------- sicuro ---

def test_two_leaders_on_a_line_are_two_sure_slots_with_labels():
    keys, members, slots = _slots(("Località", "..........", "Provincia", "......"))
    assert keys == ["Località", SLOT, "Provincia", SLOT]
    assert [(s.kind, s.label, s.index) for s in slots] == [("sicuro", "Località", 1), ("sicuro", "Provincia", 3)]
    assert [w.text for w in slots[0].words] == [".........."]
    assert [w.text for w in members[0]] == ["Località"]
    assert members[1] == slots[0].words


def test_a_leader_split_over_tokens_is_one_slot():
    keys, members, slots = _slots(("Nome", ".....", "....."))
    assert keys == ["Nome", SLOT]
    assert len(slots) == 1
    assert [w.text for w in slots[0].words] == [".....", "....."]


def test_a_leader_going_on_to_the_next_line_is_one_slot_per_line():
    keys, members, slots = _slots(("Indirizzo", "..........", "....."), ("..........",), ("Fine",))
    assert keys == ["Indirizzo", SLOT, SLOT, "Fine"]
    assert [(s.label, s.leader) for s in slots] == [("Indirizzo", "..............."), ("", "..........")]
    assert [[w.text for w in s.words] for s in slots] == [["..........", "....."], [".........."]]
    assert members[1] == slots[0].words and members[2] == slots[1].words


def test_a_leader_without_label_at_the_start():
    keys, _members, slots = _slots((".....", "....."), ("Firma",))
    assert keys[0] == SLOT and slots[0].label == "" and slots[0].kind == "sicuro"


def test_a_leader_glued_to_its_label_in_one_word():
    keys, members, slots = _slots(("Località..........", "Provincia"))
    assert keys[:2] == ["Località", SLOT]
    assert slots[0].label == "Località"
    assert [w.text for w in members[0]] == ["Località.........."]
    assert [w.text for w in slots[0].words] == ["Località.........."]


def test_underscores_and_ellipses_are_leaders_and_short_runs_are_not():
    keys, _m, slots = _slots(("Firma", "________", "e", "così", "via..."))
    assert keys == ["Firma", SLOT, "e", "così", "via..."]
    assert len(slots) == 1
    keys, _m, slots = _slots(("Data", "……", "fine."))       # two ellipses = six dots
    assert keys[:2] == ["Data", SLOT] and slots[0].kind == "sicuro"


def test_punctuation_around_a_leader_goes_with_the_slot():
    keys, _m, slots = _slots(("Nome", "(..........)", "Cognome", "..........,", "grazie"))
    assert keys == ["Nome", SLOT, "Cognome", SLOT, "grazie"]
    assert slots[0].label == "Nome" and slots[1].label == "Cognome"


# ------------------------------------------------------- probabile ---

def test_a_comma_label_alone_on_its_line_is_a_probable_slot():
    keys, members, slots = _slots(("Città,",), ("Gentile", "cliente,"), ("la", "presente"))
    assert keys == ["Città,", SLOT, "Gentile", "cliente,", "la", "presente"]
    assert [(s.kind, s.label, s.index, s.words) for s in slots] == [("probabile", "Città,", 1, ())]
    assert members[1] == ()


def test_a_comma_label_followed_by_a_value_is_no_slot():
    keys, _m, slots = _slots(("Città,", "01/02/2026"), ("Gentile", "cliente"))
    assert SLOT not in keys and slots == []


def test_colon_and_known_labels_before_a_line_end_or_another_label():
    keys, _m, slots = _slots(("Intestatario:",), ("CAP", "Provincia"), ("Testo", "normale"))
    assert keys == ["Intestatario:", SLOT, "CAP", SLOT, "Provincia", SLOT, "Testo", "normale"]
    assert [s.kind for s in slots] == ["probabile"] * 3
    assert [s.label for s in slots] == ["Intestatario:", "CAP", "Provincia"]


def test_prose_words_are_not_labels():
    # "data" lower case mid-sentence, a comma word not opening its line
    keys, _m, slots = _slots(("dalla", "data"), ("di", "attivazione,"), ("il", "cliente"))
    assert slots == [] and SLOT not in keys


# ------------------------------------------------------- anchors ---

def test_slot_anchor():
    keys, _m, slots = _slots(("Dati", "del", "cliente", "Località", "..........", "Provincia", "......"))
    anchor = slot_anchor(keys, slots[0])
    assert anchor == Anchor("cambiato", "variabile", "del cliente Località Provincia", "Località ..........")
    assert slot_anchor(keys, slots[1]).context == "cliente Località Provincia"


def test_a_disabled_anchor_suppresses_its_slot_only():
    line = ("Località", "..........", "Provincia", "......")
    keys, _m, slots = _slots(line)
    first = slot_anchor(keys, slots[0])
    keys2, members2, slots2 = _slots(line, disabled={first})
    assert keys2 == ["Località", "..........", "Provincia", SLOT]
    assert [w.text for w in members2[1]] == [".........."]
    assert [s.label for s in slots2] == ["Provincia"] and slots2[0].index == 3
    # the surviving slot keeps the SAME anchor it had with its neighbour enabled
    assert slot_anchor(keys2, slots2[0]) == slot_anchor(keys, slots[1])


def test_a_disabled_probable_slot_disappears():
    lines = (("Città,",), ("Gentile", "cliente"))
    keys, _m, slots = _slots(*lines)
    keys2, _m2, slots2 = _slots(*lines, disabled=[slot_anchor(keys, slots[0])])
    assert keys2 == ["Città,", "Gentile", "cliente"] and slots2 == []


def test_ten_identical_form_rows_have_ten_distinct_anchors():
    rows = [("Nome", "..........", "Cognome", "..........")] * 10
    keys, _m, slots = _slots(*rows)
    names = [s for s in slots if s.label == "Nome"]
    anchors = [slot_anchor(keys, s) for s in names]
    assert len(names) == 10 and len(set(anchors)) == 10
    assert len({slot_anchor(keys, s) for s in slots}) == 20
    # disabling row 3 switches off row 3 only, and the other rows keep their anchors
    keys2, _m2, slots2 = _slots(*rows, disabled={anchors[2]})
    assert len(slots2) == 19
    survivors = [slot_anchor(keys2, s) for s in slots2 if s.label == "Nome"]
    assert survivors == anchors[:2] + anchors[3:]
    assert keys2[8:11] == ["Nome", "..........", "Cognome"]      # row 3 (keys 8..11) keeps its leader


def test_occurrence_numbers_go_in_the_context():
    keys, _m, slots = _slots(*[("Nome", "..........")] * 6)
    contexts = [slot_anchor(keys, s).context for s in slots]
    assert len(set(contexts)) == 6
    assert contexts[3] == contexts[1] + " #2"          # both "Nome" x5: the later one is numbered
    assert not any(c.endswith("#1") for c in contexts)


def test_a_leader_key_without_words_does_not_crash():
    keys, members, slots = find_slots(["Nome.........."], [()], ())
    assert keys == ["Nome", SLOT] and members == [(), ()] and slots[0].words == ()


def test_find_slots_is_pure():
    keys, members = units(_lines(("Località", "..........")))
    before = (list(keys), list(members))
    find_slots(keys, members, ())
    assert (keys, members) == before


# -------------------------------------------------------- absorb ---

def _right(*lines: tuple[str, ...]):
    return units(_lines(*lines))


def test_a_sure_slot_swallows_up_to_the_next_target_word():
    keys, members = _right(("Località", "Springfield", "Provincia", "XX"))
    slot = Slot(1, "sicuro", "Località", ())
    assert absorb(slot, keys, 1, "Provincia", members) == 1
    assert absorb(slot, keys, 1, None, members) == 3          # no next word: to the line end


def test_a_sure_slot_stops_at_the_line_end():
    keys, members = _right(("Località", "Nuova", "Springfield"), ("Altro", "testo"))
    slot = Slot(1, "sicuro", "Località", ())
    assert absorb(slot, keys, 1, "Provincia", members) == 2


def test_nothing_to_swallow():
    keys, members = _right(("Località", "Provincia"))
    assert absorb(Slot(1, "sicuro", "Località", ()), keys, 1, "Provincia", members) == 0
    assert absorb(Slot(1, "sicuro", "Località", ()), keys, 2, None, members) == 0


def test_a_probable_slot_takes_a_short_value():
    keys, members = _right(("Città,", "Springfield,", "1", "febbraio", "2026"), ("Gentile", "cliente"))
    slot = Slot(1, "probabile", "Città,", ())
    assert absorb(slot, keys, 1, "Gentile", members) == 4


def test_a_probable_slot_refuses_a_long_sentence():
    sentence = ("Città,", "questo", "testo", "è", "una", "frase", "lunga", "di", "nove", "parole")
    keys, members = _right(sentence, ("Gentile",))
    assert len(sentence) - 1 > MAX_PROBABLE_WORDS
    assert absorb(Slot(1, "probabile", "Città,", ()), keys, 1, "Gentile", members) == 0


def test_a_probable_slot_value_must_start_on_the_label_line():
    keys, members = _right(("Città,",), ("Springfield",), ("Gentile",))
    assert absorb(Slot(1, "probabile", "Città,", ()), keys, 1, "Gentile", members) == 0
