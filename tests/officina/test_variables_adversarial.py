"""Adversarial cases of the variables' second pass (task A4 review, ruling
F16): a real change next to, instead of, or shaped like a value must still
count, with its words. Synthetic text only.

Ruling F16: a variable needs a POSITION proof (a room in the target whose
extent matches the value) AND a VALUE proof (value-shaped, or exactly a
payload value / dictionary value cell, or changed in a control generation);
free words are never inside a variable.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from qtrequestory.officina.compare import values as values_mod
from qtrequestory.officina.compare.classify import counts
from qtrequestory.officina.compare.model import Comparison
from qtrequestory.officina.compare.pipeline import compare_docs
from qtrequestory.officina.compare.values import Values, load_dictionary
from tests.officina.test_variables import GAP_TARGET, ROOM_TARGET, _around, _filler, _one, _page, _table, _xlsx
from tests.officina.zonegen import Page, build


def _run(target, filled, **kwargs) -> Comparison:
    return compare_docs(build(_page(*target)), build(_page(*filled)), **kwargs)


def _counted(result: Comparison) -> str:
    return " ".join(f"{d.left_text} | {d.right_text}" for d in result.diffs if counts(d, "tollerante"))


def _variables(result: Comparison) -> list[str]:
    return [d.right_text for d in result.diffs if d.klass == "variabile"]


#: The reviewer's loose room: a 51 pt gap after «Durata del periodo» (far wider than «12»).
LOOSE = _around([(60.0, "Durata del periodo"), (180.0, "mesi dal giorno di avvio")])


# ------------------------------------------------------------------- buco ---

@pytest.mark.parametrize("target", [LOOSE, GAP_TARGET], ids=["loose", "matching"])
def test_words_next_to_a_value_in_a_room_count(target):
    after = _run(target, _around([(60.0, "Durata del periodo 12 NON rinnovabili mesi dal giorno di avvio")]))
    assert "NON rinnovabili" in _counted(after)
    before = _run(target, _around([(60.0, "Durata del periodo NON 12 mesi dal giorno di avvio")]))
    assert "NON" in _counted(before)


def test_in_a_matching_room_only_the_value_is_the_variable():
    result = _run(GAP_TARGET, _around([(60.0, "Durata del periodo 12 NON rinnovabili mesi dal giorno di avvio")]))
    assert _variables(result) == ["12"]


def test_a_free_word_in_a_room_counts():
    result = _run(GAP_TARGET, _around([(60.0, "Durata del periodo minimo mesi dal giorno di avvio")]))
    assert "minimo" in _counted(result) and not _variables(result)


def test_a_value_much_wider_than_the_room_counts():
    result = _run(GAP_TARGET, _around([(60.0, "Durata del periodo 1234567890123 mesi dal giorno di avvio")]))
    assert "1234567890123" in _counted(result)


@pytest.mark.parametrize("target", [LOOSE, GAP_TARGET], ids=["loose", "matching"])
def test_words_replaced_next_to_a_room_count_with_their_new_words(target):
    label = _run(target, _around([(60.0, "Durata della fase 12 mesi dal giorno di avvio")]))
    assert "periodo" in _counted(label) and "fase" in _counted(label)
    unit = _run(target, _around([(60.0, "Durata del periodo 12 settimane dal giorno di avvio")]))
    assert "settimane" in _counted(unit) and "mesi" in _counted(unit)


def test_a_word_replaced_next_to_a_matching_room_is_a_cambiato_and_the_value_a_variable():
    result = _run(GAP_TARGET, _around([(60.0, "Durata del periodo 12 settimane dal giorno di avvio")]))
    rest = [(d.op, d.left_text, d.right_text) for d in result.diffs if counts(d, "tollerante")]
    assert rest == [("cambiato", "mesi", "settimane")] and _variables(result) == ["12"]


def test_a_payload_text_in_a_matching_room_is_a_variable_by_position():
    known = Values.of({"offerta": {"marca": "Acme Nuova"}})
    target = _around([(60.0, "Proposta di"), (148.8, "per te")])          # «Acme Nuova» is 42.4 pt wide
    filled = _around([(60.0, "Proposta di Acme Nuova per te")])
    diff = _one(_run(target, filled, values=known), "Acme Nuova")
    assert (diff.klass, diff.prova, diff.nome) == ("variabile", "buco", "offerta.marca")
    assert _one(_run(target, filled), "Acme Nuova").klass == "testo"        # free words: nobody knows them


# ----------------------------------------------------------------- label ---

def test_a_short_line_is_no_label():
    target = [_filler(1), _filler(2), [(60.0, "condizioni generali vigenti")], [(60.0, "Nuovo paragrafo qui")],
              _filler(3)]
    filled = [_filler(1), _filler(2), [(60.0, "condizioni generali vigenti entro 30 giorni")],
              [(60.0, "Nuovo paragrafo qui")], _filler(3)]
    assert "30" in _counted(_run(target, filled))


def test_a_label_without_colon_is_no_label():
    result = _run(_around([(60.0, "CODICE PRATICA")]), _around([(60.0, "CODICE PRATICA AB12345")]))
    assert "AB12345" in _counted(result)


def test_a_word_after_the_value_of_a_label_counts():
    result = _run(_around([(60.0, "CODICE PRATICA:")]), _around([(60.0, "CODICE PRATICA: AB12345 SCADUTA")]))
    assert "SCADUTA" in _counted(result) and _variables(result) == ["AB12345"]


# --------------------------------------------------------------- sezione ---

def test_a_new_sentence_after_a_paragraph_end_counts():
    target = [_filler(1), [(60.0, "fine del paragrafo precedente.")], [], [], [], [(60.0, "ARTICOLO SUCCESSIVO")],
              _filler(2)]
    filled = [_filler(1), [(60.0, "fine del paragrafo precedente.")],
              [(60.0, "Il cliente paga una penale di cento euro.")], [], [], [(60.0, "ARTICOLO SUCCESSIVO")],
              _filler(2)]
    assert "penale" in _counted(_run(target, filled))


def test_new_paragraphs_under_an_empty_heading_count():
    target = [_filler(1), [(60.0, "RIDUZIONI ACME")], [], [], [], [], [], [(60.0, "Opzioni Acme")], _filler(2)]
    filled = [_filler(1), [(60.0, "RIDUZIONI ACME")], [(60.0, "Sconto del dieci per cento sul totale annuo.")],
              [(60.0, "Penale di recesso anticipato pari a cento euro.")],
              [(60.0, "Rinnovo tacito ogni anno salvo disdetta.")], [], [], [(60.0, "Opzioni Acme")], _filler(2)]
    assert "Penale" in _counted(_run(target, filled))


def test_a_known_text_under_a_heading_that_is_not_one_counts():
    target = [_filler(1), [(60.0, "riduzioni acme")], [], [], [], [(60.0, "Opzioni Acme")], _filler(2)]
    filled = [_filler(1), [(60.0, "riduzioni acme")], [(60.0, "Nessuna riduzione per questo profilo.")],
              [], [], [(60.0, "Opzioni Acme")], _filler(2)]
    known = Values.of({"offerta": {"riduzioni": "Nessuna riduzione per questo profilo."}})
    assert "riduzione" in _counted(_run(target, filled, values=known))


# ----------------------------------------------------------------- cella ---

@pytest.mark.parametrize("text", ["Gratuita", "Non incluso", "Esclusi domestici",
                                  "Non applicabile ai clienti domestici"])
def test_words_in_an_empty_cell_count(text):
    result = compare_docs(build(_table("€/anno", "", gen=False)), build(_table("€/anno", text, gen=False)))
    assert text.split()[0] in _counted(result)


def test_words_in_an_empty_cell_known_to_the_payload_are_a_cella():
    known = Values.of({"voce": {"costo": "Gratuita"}})
    result = compare_docs(build(_table("€/anno", "", gen=False)), build(_table("€/anno", "Gratuita", gen=False)),
                          values=known)
    diff = _one(result, "Gratuita")
    assert (diff.klass, diff.prova, diff.nome) == ("variabile", "cella", "voce.costo")


def test_a_label_changed_next_to_a_filled_cell_counts():
    target = _table("€/anno", "", gen=False)
    filled = _table("€/anno", "0,50", gen=False)
    renamed = Page()
    renamed.paths = filled.paths
    renamed.flat = [w if w.text != "beta" else type(w)("gamma", w.page, w.x0, w.y0, w.x1, w.y1, w.size, w.bold)
                    for w in filled.flat]
    result = compare_docs(build(target), build(renamed))
    assert "beta" in _counted(result) and "gamma" in _counted(result)


# --------------------------------------------------------------- listino ---

def test_a_dictionary_label_text_proves_nothing(tmp_path: Path):
    dictionary, _ = load_dictionary(_xlsx(tmp_path / "d.xlsx", [["Voce", "Valore"], ["Spread", 0.246813],
                                                                 ["Maggiorazione", 0.1]]))
    known = Values.of(dictionary=dictionary)
    tail = _run(_around([(60.0, "Quota vale euro al periodo")]),
                _around([(60.0, "Quota vale euro al periodo Maggiorazione")]), values=known)
    assert "Maggiorazione" in _counted(tail)
    room = _run(ROOM_TARGET, _around([(60.0, "Quota vale Spread euro al periodo")]), values=known)
    assert "Spread" in _counted(room)


# ------------------------------------------------------------------ xlsx ---

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def _book(path: Path, sheet: bytes) -> Path:
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as book:
        book.writestr("xl/workbook.xml", f'<workbook xmlns="{MAIN}" xmlns:r="{rel}"><sheets>'
                                         f'<sheet name="L" sheetId="1" r:id="rId1"/></sheets></workbook>')
        book.writestr("xl/_rels/workbook.xml.rels",
                      '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                      '<Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="x"/></Relationships>')
        book.writestr("xl/worksheets/sheet1.xml", sheet)
    return path


def test_a_corrupt_deflate_stream_is_a_note(tmp_path: Path):
    path = _book(tmp_path / "c.xlsx", b"<worksheet>" + b"<row/>" * 5000 + b"</worksheet>")
    data = bytearray(path.read_bytes())
    start = data.find(b"xl/worksheets/sheet1.xml") + len("xl/worksheets/sheet1.xml") + 10
    for k in range(start, start + 12):
        data[k] ^= 0x5A
    path.write_bytes(bytes(data))
    dictionary, note = load_dictionary(path)
    assert not dictionary and "non letto" in note


def test_a_truncated_workbook_is_a_note(tmp_path: Path):
    path = _book(tmp_path / "t.xlsx", b"<worksheet>" + b"<row/>" * 5000 + b"</worksheet>")
    path.write_bytes(path.read_bytes()[: path.stat().st_size // 2])
    assert "non letto" in load_dictionary(path)[1]


def test_a_bad_shared_string_and_entity_expansion_are_notes(tmp_path: Path):
    bad = _book(tmp_path / "i.xlsx", f'<worksheet xmlns="{MAIN}"><sheetData><row><c r="A1" t="s"><v>x1</v></c>'
                                     f'</row></sheetData></worksheet>'.encode())
    assert "non letto" in load_dictionary(bad)[1]
    entities = "".join(f'<!ENTITY l{i} "{("&l" + str(i - 1) + ";") * 10}">' for i in range(1, 9))
    doc = f'<?xml version="1.0"?><!DOCTYPE w [<!ENTITY l0 "lol">{entities}]><worksheet>&l8;</worksheet>'
    assert "non letto" in load_dictionary(_book(tmp_path / "b.xlsx", doc.encode()))[1]


def test_a_workbook_inflating_past_the_cap_is_not_read(tmp_path: Path, monkeypatch):
    path = _book(tmp_path / "z.xlsx", b"<worksheet>" + b" " * 200_000 + b"</worksheet>")
    monkeypatch.setattr(values_mod, "MAX_BYTES", 50_000)
    dictionary, note = load_dictionary(path)
    assert not dictionary and "troppo grande" in note


def test_a_workbook_with_too_many_members_is_not_read(tmp_path: Path, monkeypatch):
    path = _book(tmp_path / "m.xlsx", b"<worksheet/>")
    monkeypatch.setattr(values_mod, "MAX_MEMBERS", 2)
    assert "troppo grande" in load_dictionary(path)[1]


def test_a_room_far_wider_than_the_value_is_no_hole():
    # 51 pt of room for «12» (13.5 pt with its spaces): a tab stop or a column, not a hole sized for it
    result = _run(LOOSE, _around([(60.0, "Durata del periodo 12 mesi dal giorno di avvio")]))
    assert "12" in _counted(result) and not _variables(result)


def test_a_room_holds_one_value():
    result = _run(GAP_TARGET, _around([(60.0, "Durata del periodo 12 NON 34 mesi dal giorno di avvio")]))
    assert _variables(result) == ["12"] and "34" in _counted(result)


def test_a_unit_next_to_its_amount_is_part_of_the_value():
    result = compare_docs(build(_table("", "", gen=False)), build(_table("48 €/anno", "", gen=True)))
    assert _variables(result) == ["48 €/anno"]


# ------------------------------------------------------ fix round 2 probes ---

def _spaced(x: float, text: str, space: float) -> list[tuple[float, str]]:
    """Words of 8 pt (4 pt a character) separated by ``space`` pt: a justified line."""
    out = []
    for word in text.split():
        out.append((x, word))
        x += 4.0 * len(word) + space
    return out


@pytest.mark.parametrize("space", [4.0, 6.5, 9.0])
def test_a_digit_in_a_stretched_justified_space_counts(space):
    target = _around(_spaced(60.0, "ai sensi dell'articolo del Codice civile vigente", space))
    result = _run(target, _around([(60.0, "ai sensi dell'articolo 5 del Codice civile vigente")]))
    assert "5" in _counted(result) and not _variables(result)


def test_a_justified_block_has_no_hole_even_when_its_spaces_are_wide():
    # every space of the block is 14 pt: the space before «mesi» does not stand out
    lines = [_spaced(60.0, "alfa beta gamma delta epsilon", 14.0), _spaced(60.0, "Durata del periodo mesi dal", 14.0),
             _spaced(60.0, "zeta eta theta iota kappa", 14.0)]
    target = [_filler(1), *lines, _filler(2)]
    filled = [_filler(1), lines[0], [(60.0, "Durata del periodo 12 mesi dal")], lines[2], _filler(2)]
    assert "12" in _counted(_run(target, filled))


def test_a_number_in_a_first_line_indent_counts():
    target = [_filler(1), _filler(2), [(71.0, "Il cliente può recedere")], _filler(3), _filler(4)]
    filled = [_filler(1), _filler(2), [(60.0, "2) Il cliente può recedere")], _filler(3), _filler(4)]
    result = _run(target, filled)
    assert "2" in _counted(result) and not _variables(result)


def test_a_unit_that_replaces_a_target_word_counts_with_both_words():
    # the reviewer's probe: a room of 31 pt (sized for «12 mesi»)
    target = _around([(60.0, "Durata del periodo"), (160.0, "anni dal giorno")])
    result = _run(target, _around([(60.0, "Durata del periodo 12 mesi dal giorno")]))
    assert "anni" in _counted(result) and "mesi" in _counted(result)


def test_a_unit_that_replaces_a_target_word_is_a_change_not_part_of_the_value():
    target = _around([(60.0, "Durata del periodo"), (145.0, "anni dal giorno")])     # a 16 pt room: «12» fits
    result = _run(target, _around([(60.0, "Durata del periodo 12 mesi dal giorno")]))
    rest = [(d.op, d.left_text, d.right_text) for d in result.diffs if counts(d, "tollerante")]
    assert rest == [("cambiato", "anni", "mesi")] and _variables(result) == ["12"]


def test_a_value_away_from_the_room_is_no_variable():
    # the room is BEFORE «anni»; «12» lands after «mesi», which took the place of «anni»: not in the room
    target = _around([(60.0, "Durata del periodo"), (145.0, "anni dal giorno")])
    result = _run(target, _around([(60.0, "Durata del periodo mesi 12 dal giorno")]))
    assert not _variables(result) and "anni" in _counted(result) and "12" in _counted(result)


def test_a_gap_below_the_absolute_floor_is_no_hole():
    # spaces of 1 pt elsewhere on the line: a 6 pt gap stands out, but is under 2.5 characters (11.5 pt)
    first = _spaced(60.0, "ai sensi dell'articolo", 1.0)
    rest = _spaced(60.0 + 4.0 * len("aisensidell'articolo") + 2.0 + 6.0, "del Codice civile", 1.0)
    target = _around(first + rest)
    result = _run(target, _around([(60.0, "ai sensi dell'articolo 5 del Codice civile")]))
    assert "5" in _counted(result) and not _variables(result)


# ------------------------------------------------------ fix round 3 probes ---

def _laid(x: float, words_and_gaps: list[tuple[str, float]]) -> list[tuple[float, str]]:
    """``(word, space after it)`` pieces of 8 pt text (4 pt a character)."""
    out = []
    for word, gap in words_and_gaps:
        out.append((x, word))
        x += 4.0 * len(word) + gap
    return out


def test_a_number_replacing_a_number_after_a_room_is_a_change():
    # «periodo ⎵ 12 mesi» → «periodo 18 mesi»: «18» took the place of «12», it is not the room's value
    target = _around(_laid(60.0, [("Durata", 4.0), ("del", 4.0), ("periodo", 16.0), ("12", 4.0), ("mesi", 4.0),
                                  ("dal", 4.0), ("giorno", 4.0)]))
    result = _run(target, _around([(60.0, "Durata del periodo 18 mesi dal giorno")]))
    rest = [(d.op, d.left_text, d.right_text) for d in result.diffs if counts(d, "tollerante")]
    assert rest == [("cambiato", "12", "18")] and not _variables(result)


def test_a_number_replacing_a_number_before_a_room_is_a_change():
    target = _around(_laid(60.0, [("per", 4.0), ("mesi", 4.0), ("12", 16.0), ("dal", 4.0), ("giorno", 4.0),
                                  ("di", 4.0), ("avvio", 4.0)]))
    result = _run(target, _around([(60.0, "per mesi 18 dal giorno di avvio")]))
    rest = [(d.op, d.left_text, d.right_text) for d in result.diffs if counts(d, "tollerante")]
    assert rest == [("cambiato", "12", "18")] and not _variables(result)


def test_a_one_gap_line_is_never_a_hole():
    # a two-word line stretched to 20 pt in a paragraph of 6 pt spaces: nothing on the line to compare with
    lines = [_laid(60.0, [("alfa", 6.0), ("beta", 6.0), ("gamma", 6.0), ("delta", 6.0)]),
             _laid(60.0, [("corrispettivo", 20.0), ("dell'onere", 0.0)]),
             _laid(60.0, [("zeta", 6.0), ("eta", 6.0), ("theta", 6.0), ("iota", 6.0)])]
    target = [_filler(1), *lines, _filler(2)]
    filled = [_filler(1), lines[0], [(60.0, "corrispettivo 12 dell'onere")], lines[2], _filler(2)]
    result = _run(target, filled)
    assert "12" in _counted(result) and not _variables(result)


def test_a_value_run_reaching_into_a_substitution_is_no_variable():
    # «periodo ⎵ 12» → «periodo 7 18»: «7» is the inserted word, «18» took the place of «12» —
    # a run «7 18» holds a substitution: never a value
    target = _around(_laid(60.0, [("Durata", 4.0), ("del", 4.0), ("periodo", 16.0), ("12", 4.0), ("mesi", 4.0),
                                  ("dal", 4.0), ("giorno", 4.0)]))
    result = _run(target, _around([(60.0, "Durata del periodo 7 18 mesi dal giorno")]))
    assert "18" in _counted(result) and "12" in _counted(result) and not _variables(result)
