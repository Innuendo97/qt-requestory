"""The variables' second pass (phase 2.5, spec §3.3; task A4).

Synthetic documents built with ``zonegen`` (no PDF written, no real text):
a value the generated side puts where the target leaves room for one is a
``variabile`` with its proof (``Diff.prova``) and, when the payload or the
dictionary knows it, its name (``Diff.nome``); a value anywhere else, or a
change of punctuation or case only, keeps counting.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

from qtrequestory.officina.compare.classify import counts
from qtrequestory.officina.compare.graphics import PathShape
from qtrequestory.officina.compare.model import PROVE, Block, Comparison, Diff, Word
from qtrequestory.officina.compare.pipeline import compare_docs
from qtrequestory.officina.compare.values import Values, load_dictionary, word_key
from qtrequestory.officina.compare.variables import HOLE, occurrences
from tests.officina.zonegen import BLACK, Page, build

FILLER = "lorem ipsum dolor sitame consec adipis elitse doeius tempor incidi"   # ~262 pt at 8 pt


def _page(*lines: list[tuple[float, str]], step: float = 12.0, top: float = 100.0) -> Page:
    """A page with the given lines (each a list of ``(x, text)`` pieces), one per ``step`` pt."""
    p = Page()
    for k, pieces in enumerate(lines):
        for x, text in pieces:
            p.text(x, top + step * k, text)
    return p


def _filler(n: int) -> list[tuple[float, str]]:
    return [(60.0, " ".join(f"{w}{'abcdefghij'[n % 10]}" for w in FILLER.split()))]


def _around(*middle: list[tuple[float, str]]) -> list[list[tuple[float, str]]]:
    """Two running lines, the ``middle`` lines, two running lines."""
    return [_filler(1), _filler(2), *middle, _filler(3), _filler(4)]


def _one(result: Comparison, text: str) -> Diff:
    found = [d for d in result.diffs if text in d.right_text or text in d.left_text]
    assert len(found) == 1, [(d.op, d.klass, d.left_text, d.right_text) for d in result.diffs]
    return found[0]


def _counting(result: Comparison) -> list[Diff]:
    return [d for d in result.diffs if counts(d, "tollerante")]


# ------------------------------------------------------------------- buco ---

#: «Durata del periodo» ends at 128.8 pt: a gap of 14 pt matches «12» (8 pt wide + a space each side).
GAP_TARGET = _around([(60.0, "Durata del periodo"), (142.8, "mesi dal giorno di avvio")])
GAP_FILLED = _around([(60.0, "Durata del periodo 12 mesi dal giorno di avvio")])


def test_a_value_in_a_gap_between_two_words_is_a_variable():
    result = compare_docs(build(_page(*GAP_TARGET)), build(_page(*GAP_FILLED)))
    diff = _one(result, "12")
    assert (diff.op, diff.klass, diff.prova, diff.nome) == ("in_piu", "variabile", "buco", "")
    assert _counting(result) == []


def test_the_payload_names_a_variable_in_italian_formats():
    values = Values.of({"offerta": {"durata": 12, "template": {"scope": "12"}}})
    diff = _one(compare_docs(build(_page(*GAP_TARGET)), build(_page(*GAP_FILLED)), values=values), "12")
    assert (diff.klass, diff.prova, diff.nome) == ("variabile", "buco", "offerta.durata")


def test_a_value_after_a_label_ending_its_line_is_a_variable():
    target = _around([(60.0, "CODICE PRATICA:")])
    filled = _around([(60.0, "CODICE PRATICA: AB12345")])
    diff = _one(compare_docs(build(_page(*target)), build(_page(*filled))), "AB12345")
    assert (diff.klass, diff.prova) == ("variabile", "buco")


def test_words_after_a_heading_line_without_a_digit_keep_counting():
    target = _around([(60.0, "LISTINO")])
    filled = _around([(60.0, "LISTINO ALFA BETA")])
    diff = _one(compare_docs(build(_page(*target)), build(_page(*filled))), "ALFA")
    assert (diff.klass, diff.prova) == ("testo", "")


def test_a_value_before_an_indented_word_is_never_a_hole():
    # review A4 fix 1: an indented line start is layout (a first-line indent), even when the
    # line before runs on and the indent would fit the value (50 pt for 40 pt)
    target = [_filler(1), _filler(2), [(110.0, "fino al termine del periodo")], _filler(3), _filler(4)]
    filled = [_filler(1), _filler(2), [(60.0, "18/03/2026 fino al termine del periodo")], _filler(3), _filler(4)]
    diff = _one(compare_docs(build(_page(*target)), build(_page(*filled))), "18/03/2026")
    assert (diff.klass, diff.prova) == ("testo", "")


def test_a_value_where_the_target_has_no_room_keeps_counting():
    target = _around([(60.0, "Durata del periodo mesi dal giorno di avvio")])
    filled = _around([(60.0, "Durata del periodo 12 mesi dal giorno di avvio")])
    diff = _one(compare_docs(build(_page(*target)), build(_page(*filled))), "12")
    assert (diff.klass, diff.prova) == ("testo", "")


def test_a_payload_value_alone_never_makes_a_variable():
    values = Values.of({"cliente": {"nome": "Acme-Servizi"}})
    target = _around([(60.0, "Proposta riservata ai soci della zona")])
    filled = _around([(60.0, "Proposta riservata ai soci Acme-Servizi della zona")])
    diff = _one(compare_docs(build(_page(*target)), build(_page(*filled)), values=values), "Acme-Servizi")
    assert (diff.klass, diff.prova, diff.nome) == ("testo", "", "")


def test_punctuation_added_in_a_gap_is_never_a_variable():
    target = _around([(60.0, "Proposta di Acme S.p.A"), (200.0, "con sede legale in via")])
    filled = _around([(60.0, "Proposta di Acme S.p.A. con sede legale in via")])
    diff = _one(compare_docs(build(_page(*target)), build(_page(*filled))), "S.p.A")
    assert (diff.klass, diff.tipo, diff.prova) == ("testo", "punteggiatura", "")


def test_a_case_only_change_is_never_a_variable():
    target = _around([(60.0, "valore ab12"), (122.4, "fine del testo")])       # a room after «ab12» fits «AB12»
    filled = _around([(60.0, "valore AB12 fine del testo")])
    result = compare_docs(build(_page(*target)), build(_page(*filled)))
    assert [(d.op, d.klass, d.tipo) for d in result.diffs] == [("cambiato", "testo", "maiuscole")]


def test_text_printed_elsewhere_in_the_target_is_never_a_variable():
    known = Values.of({"gestore": {"nome": "Acme Servizi Nord"}})
    room = [(60.0, "Servizio curato da"), (198.8, "per la zona")]          # a 70 pt room for a 65 pt name
    filled = [(60.0, "Servizio curato da Acme Servizi Nord per la zona")]
    alone = compare_docs(build(_page(*_around(room))), build(_page(*_around(filled))), values=known)
    assert _one(alone, "Servizi Nord").klass == "variabile"                  # known and in a room
    target = _around(room, [(60.0, "Acme Servizi Nord gestore")])
    result = compare_docs(build(_page(*target)), build(_page(*_around(filled, [(60.0, "Acme Servizi Nord gestore")]))),
                          values=known)
    diff = _one(result, "Servizi Nord")
    assert diff.klass == "testo" and diff.prova == ""


def test_a_cambiato_with_a_value_and_a_real_change_is_split():
    target = _around([(60.0, "vale"), (98.0, "euro (nel periodo corrente)")])     # a 22 pt gap before «euro»
    filled = _around([(60.0, "vale 0,50 euri (nel periodo corrente)")])      # «0,50» in the room, «euri» for «euro»
    result = compare_docs(build(_page(*target)), build(_page(*filled)))
    original = compare_docs(build(_page(*target)), build(_page(*filled)), values=Values.of(proofs=()))
    whole = _one(original, "euro")
    rest, value = [d for d in result.diffs if d.klass != "stile"]
    assert (rest.op, rest.klass, rest.left_text, rest.right_text, rest.anchor) ==         ("cambiato", "testo", "euro", "euri", whole.anchor)
    assert (value.op, value.klass, value.prova, value.right_text) == ("in_piu", "variabile", "buco", "0,50")
    assert value.anchor.target_text.endswith(HOLE) and value.anchor != rest.anchor
    assert [d.id for d in result.diffs] == list(range(1, len(result.diffs) + 1))


# ------------------------------------------------------------ segnaposto ---

def test_a_bracket_placeholder_filled_is_a_segnaposto():
    values = Values.of({"offerta": {"durata": "12"}})
    target = _around([(60.0, "costante per [xx] mesi dal giorno")])
    filled = _around([(60.0, "costante per 12 mesi dal giorno")])
    diff = _one(compare_docs(build(_page(*target)), build(_page(*filled)), values=values), "12")
    assert (diff.klass, diff.prova, diff.nome) == ("variabile", "segnaposto", "offerta.durata")


def test_a_leader_slot_has_the_segnaposto_proof_and_counts_when_switched_off():
    target = _around([(60.0, "Località ..........")])
    filled = _around([(60.0, "Località Springfield")])
    diff = _one(compare_docs(build(_page(*target)), build(_page(*filled))), "Springfield")
    assert (diff.klass, diff.prova) == ("variabile", "segnaposto")
    off = Values.of(proofs=set(PROVE) - {"segnaposto"})
    diff = _one(compare_docs(build(_page(*target)), build(_page(*filled)), values=off), "Springfield")
    assert (diff.klass, diff.prova) == ("testo", "segnaposto") and diff.left_spans


def _html(*texts: str) -> list[Block]:
    return [Block(k, tuple(Word(t, 0, 0.0, 0.0, 0.0, 0.0) for t in text.split()), 0, "html")
            for k, text in enumerate(texts)]


def test_an_html_value_placeholder_is_a_segnaposto_named_by_itself():
    result = compare_docs(_html("Ciao {{NOME}}, benvenuto in Acme"), _html("Ciao Mario, benvenuto in Acme"))
    diff = _one(result, "Mario")
    assert (diff.klass, diff.prova, diff.nome) == ("variabile", "segnaposto", "{{NOME}}")


def test_an_html_conditional_text_compares_without_its_braces():
    result = compare_docs(_html("Allegati {{Modulo Acme}} e contratto"), _html("Allegati Modulo Acme e contratto"))
    assert result.diffs == ()


def test_an_html_conditional_text_left_out_is_a_variable():
    result = compare_docs(_html("Allegati {{Modulo Acme}} e contratto"), _html("Allegati e contratto"))
    diff = _one(result, "Modulo")
    assert (diff.op, diff.klass, diff.prova, diff.nome) == ("mancante", "variabile", "segnaposto", "{{Modulo Acme}}")


def test_a_value_inside_a_conditional_text_is_a_slot():
    result = compare_docs(_html("Voce {{Quota fissa {{X_QF}}}} al mese"),
                          _html("Voce Quota fissa 12,00 al mese"))
    diff = _one(result, "12,00")
    assert (diff.klass, diff.prova) == ("variabile", "segnaposto")


# ------------------------------------------------------------------ cella ---

def _table(right_first: str, right_second: str, *, gen: bool) -> Page:
    rows = [_filler(1), _filler(2), [], [], _filler(3), _filler(4)]
    p = _page(*rows, step=20.0)
    for y in (135.0, 157.0, 179.0):
        p.paths.append(PathShape((60.0, y - 0.25, 400.0, y + 0.25), 0.5, None, BLACK, 2))
    for x in (60.0, 200.0, 400.0):
        p.paths.append(PathShape((x - 0.25, 135.0, x + 0.25, 179.0), 0.5, None, BLACK, 2))
    p.text(65.0, 142.0, "Quota alfa")
    p.text(65.0, 164.0, "Quota beta")
    if right_first:
        p.text(280.0 if gen else 300.0, 142.0, right_first)
    if right_second:
        p.text(300.0, 164.0, right_second)
    return p


def test_a_value_in_a_cell_holding_only_its_unit_is_a_cella():
    result = compare_docs(build(_table("€/anno", "", gen=False)), build(_table("48 €/anno", "", gen=True)))
    diff = _one(result, "48")
    assert (diff.klass, diff.prova) == ("variabile", "cella")


def test_a_value_in_an_empty_cell_is_a_cella():
    result = compare_docs(build(_table("€/anno", "", gen=False)), build(_table("€/anno", "0,50", gen=False)))
    diff = _one(result, "0,50")
    assert (diff.klass, diff.prova) == ("variabile", "cella")


def test_a_cell_holding_other_text_is_no_cella():
    result = compare_docs(build(_table("€/anno fisso", "", gen=False)),
                          build(_table("48 €/anno fisso", "", gen=True)))
    diff = _one(result, "48")
    assert diff.prova != "cella"


# ---------------------------------------------------------------- sezione ---

def test_a_text_under_a_heading_followed_by_a_void_is_a_sezione():
    target = [_filler(1), [(60.0, "RIDUZIONI ACME")], [], [], [], [(60.0, "Opzioni Acme")], _filler(2)]
    filled = [_filler(1), [(60.0, "RIDUZIONI ACME")], [(60.0, "Nessuna riduzione per questo profilo.")],
              [], [], [(60.0, "Opzioni Acme")], _filler(2)]
    known = Values.of({"offerta": {"riduzioni": "Nessuna riduzione per questo profilo."}})
    diff = _one(compare_docs(build(_page(*target)), build(_page(*filled)), values=known), "riduzione per")
    assert (diff.klass, diff.prova, diff.nome) == ("variabile", "sezione", "offerta.riduzioni")
    # the same text nobody knows is a new paragraph: it counts (review A4 C3)
    diff = _one(compare_docs(build(_page(*target)), build(_page(*filled))), "riduzione per")
    assert diff.klass == "testo"


def test_a_text_added_between_two_close_lines_keeps_counting():
    target = [_filler(1), [(60.0, "Riduzioni Acme")], [(60.0, "Opzioni Acme")], _filler(2)]
    filled = [_filler(1), [(60.0, "Riduzioni Acme")], [(60.0, "Nessuna riduzione per questo profilo.")],
              [(60.0, "Opzioni Acme")], _filler(2)]
    diff = _one(compare_docs(build(_page(*target)), build(_page(*filled))), "riduzione per")
    assert diff.klass == "testo"


# ------------------------------------------------------ esecuzione, listino ---

#: «Quota vale» ends at 102.4 pt: a 30 pt gap matches «0,2468» (24 pt) and «alfa» (16 pt).
ROOM_TARGET = _around([(60.0, "Quota vale"), (132.4, "euro al periodo")])
ROOM_FILLED = _around([(60.0, "Quota vale 0,2468 euro al periodo")])
NO_ROOM_TARGET = _around([(60.0, "Quota vale euro al periodo")])
NO_ROOM_FILLED = ROOM_FILLED


def test_a_word_that_changed_in_the_control_generation_is_an_esecuzione_in_a_room():
    filled = build(_page(*_around([(60.0, "Quota vale alfa euro al periodo")])))
    value = [w for w in filled.words if w.text == "alfa"]
    stub = Values.of(executed={word_key(w) for w in value})         # A5 feeds the real ones
    diff = _one(compare_docs(build(_page(*ROOM_TARGET)), filled, values=stub), "alfa")
    assert (diff.klass, diff.prova) == ("variabile", "esecuzione")
    # a free word nobody saw change is never a value (F16)
    assert _one(compare_docs(build(_page(*ROOM_TARGET)), filled), "alfa").klass == "testo"
    # and a changed word where the target leaves no room is no variable either (F16: both proofs)
    other = build(_page(*_around([(60.0, "Quota vale alfa euro al periodo")])))
    stub = Values.of(executed={word_key(w) for w in other.words if w.text == "alfa"})
    assert _one(compare_docs(build(_page(*NO_ROOM_TARGET)), other, values=stub), "alfa").klass == "testo"


def _xlsx(path: Path, rows: list[list[object]]) -> Path:
    strings: list[str] = []
    cells = []
    for r, row in enumerate(rows, 1):
        out = []
        for c, value in enumerate(row):
            ref = f"{'ABCDEFGH'[c]}{r}"
            if isinstance(value, str):
                strings.append(value)
                out.append(f'<c r="{ref}" t="s"><v>{len(strings) - 1}</v></c>')
            else:
                out.append(f'<c r="{ref}"><v>{value}</v></c>')
        cells.append(f'<row r="{r}">{"".join(out)}</row>')
    main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    with zipfile.ZipFile(path, "w") as book:
        book.writestr("xl/workbook.xml", f'<workbook xmlns="{main}" xmlns:r="{rel}"><sheets>'
                                         f'<sheet name="Listino" sheetId="1" r:id="rId1"/></sheets></workbook>')
        book.writestr("xl/_rels/workbook.xml.rels",
                      '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                      '<Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="x"/></Relationships>')
        book.writestr("xl/sharedStrings.xml", f'<sst xmlns="{main}">'
                      + "".join(f"<si><t>{s}</t></si>" for s in strings) + "</sst>")
        book.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{main}"><sheetData>{"".join(cells)}'
                                                  "</sheetData></worksheet>")
    return path


def test_a_price_list_value_where_the_target_has_nothing_is_a_listino(tmp_path: Path):
    dictionary, note = load_dictionary(_xlsx(tmp_path / "dizionario.xlsx", [["Voce", "Valore"], ["Spread", 0.246813]]))
    assert note == ""
    diff = _one(compare_docs(build(_page(*ROOM_TARGET)), build(_page(*ROOM_FILLED)),
                             values=Values.of(dictionary=dictionary)), "0,2468")
    assert (diff.klass, diff.prova, diff.nome) == ("variabile", "listino", "Listino: Spread")
    # without a room the dictionary proves nothing (F16: both proofs)
    diff = _one(compare_docs(build(_page(*NO_ROOM_TARGET)), build(_page(*NO_ROOM_FILLED)),
                             values=Values.of(dictionary=dictionary)), "0,2468")
    assert diff.klass == "testo"


def test_a_whole_number_of_the_dictionary_proves_nothing(tmp_path: Path):
    dictionary, _ = load_dictionary(_xlsx(tmp_path / "d.xlsx", [["Voce", "Valore"], ["Durata", 12]]))
    target = _around([(60.0, "Durata del periodo mesi dalla data")])
    filled = _around([(60.0, "Durata del periodo 12 mesi dalla data")])
    diff = _one(compare_docs(build(_page(*target)), build(_page(*filled)), values=Values.of(dictionary=dictionary)),
                "12")
    assert diff.klass == "testo"


def test_a_malformed_dictionary_gives_a_note_never_an_error(tmp_path: Path):
    bad = tmp_path / "dizionario.xlsx"
    bad.write_bytes(b"not a zip at all")
    dictionary, note = load_dictionary(bad)
    assert not dictionary and "non letto" in note
    empty = tmp_path / "vuoto.xlsx"
    with zipfile.ZipFile(empty, "w") as book:
        book.writestr("xl/workbook.xml", "<workbook")
    dictionary, note = load_dictionary(empty)
    assert not dictionary and "non letto" in note
    assert load_dictionary(tmp_path / "assente.xlsx") == (load_dictionary(tmp_path / "assente.xlsx")[0], "")


# ------------------------------------------------------ switches and panel ---

def test_a_proof_switched_off_leaves_its_difference_counting_with_its_proof():
    off = Values.of(proofs=set(PROVE) - {"buco"})
    result = compare_docs(build(_page(*GAP_TARGET)), build(_page(*GAP_FILLED)), values=off)
    diff = _one(result, "12")
    assert (diff.klass, diff.prova) == ("testo", "buco")
    rows = occurrences(result.diffs)
    assert [(o.testo, o.anchors) for o in rows["variabile.buco"]] == [("12", (diff.anchor,))]
    assert set(rows) == {f"variabile.{p}" for p in PROVE}


def test_a_placeholder_switched_off_keeps_counting_with_its_proof():
    target = _around([(60.0, "costante per [xx] mesi dal giorno")])
    filled = _around([(60.0, "costante per 12 mesi dal giorno")])
    off = Values.of(proofs=set(PROVE) - {"segnaposto"})
    diff = _one(compare_docs(build(_page(*target)), build(_page(*filled)), values=off), "12")
    assert (diff.klass, diff.prova) == ("testo", "segnaposto")


def test_occurrences_group_the_variables_by_proof():
    values = Values.of({"offerta": {"durata": 12}})
    result = compare_docs(build(_page(*GAP_TARGET)), build(_page(*GAP_FILLED)), values=values)
    rows = occurrences(result.diffs)
    (row,) = rows["variabile.buco"]
    assert (row.testo, row.pagine, row.zona, row.dettaglio, row.diff_ids) == ("12", (0,), "corpo", "offerta.durata", ())
    assert all(not rows[f"variabile.{p}"] for p in PROVE if p != "buco")


# ------------------------------------------------------------------- zones ---

def _zoned(footer: tuple[str, str], edition: str, x2: float = 250.0) -> Page:
    p = Page().divider(60.0)
    for k in range(20):
        p.text(60.0, 90.0 + 12 * k, " ".join(f"{w}{'abcdefghij'[k % 10]}{'abcdefghij'[k // 10]}" for w in FILLER.split()))
    p.divider(770.0)
    p.text(60.0, 780.0, footer[0], size=7.0)
    if footer[1]:
        p.text(x2, 780.0, footer[1], size=7.0)
    p.turned_text(18.0, 600.0, edition)
    return p


def test_a_value_in_a_footer_gap_keeps_counting():
    # «sede» ends at 139.8 pt: a 25 pt room matches «12345» (17.5 pt + a space each side)
    target = build(_zoned(("Acme Servizi S.p.A. sede", "legale Springfield"), "Ed. Aprile duemila", x2=164.8))
    filled = build(_zoned(("Acme Servizi S.p.A. sede 12345 legale Springfield", ""), "Ed. Aprile duemila"))
    diff = _one(compare_docs(target, filled), "12345")
    assert (diff.zone, diff.klass) == ("footer", "zona")


def test_a_value_after_a_label_ending_a_shoulder_is_a_variable():
    footer = ("Acme Servizi S.p.A.", "")
    target = build(_zoned(footer, "Ed. Aprile duemila CODICE:"), _zoned(footer, "Ed. Aprile duemila CODICE:"))
    filled = build(_zoned(footer, "Ed. Aprile duemila CODICE: AB123"),
                   _zoned(footer, "Ed. Aprile duemila CODICE: AB123"))
    diff = _one(compare_docs(target, filled), "AB123")
    assert (diff.zone, diff.klass, diff.prova) == ("spalla_sx", "variabile", "buco")
    assert diff.detail == "uguale su 2 pagine"
    # after a dangling dash (no label) the added text counts (F16: «:» only)
    target = build(_zoned(footer, "Ed. Aprile duemila -"), _zoned(footer, "Ed. Aprile duemila -"))
    filled = build(_zoned(footer, "Ed. Aprile duemila - AB123"), _zoned(footer, "Ed. Aprile duemila - AB123"))
    assert _one(compare_docs(target, filled), "AB123").klass == "zona"


# ------------------------------------------------------------------ guards ---

def test_a_word_added_at_an_indented_paragraph_start_keeps_counting():
    # the line before ends short (a paragraph's end): the indent is the paragraph's, not a hole
    target = [_filler(1), [(60.0, "fine del paragrafo")], [(110.0, "fino al termine del periodo")], _filler(3)]
    filled = [_filler(1), [(60.0, "fine del paragrafo")], [(60.0, "18/03/2026 fino al termine del periodo")],
              _filler(3)]
    diff = _one(compare_docs(build(_page(*target)), build(_page(*filled))), "18/03/2026")
    assert diff.klass == "testo"


def test_a_value_running_over_two_lines_is_no_hole_value():
    target = _around([(60.0, "Durata del periodo"), (180.0, "mesi dal giorno di avvio")])
    filled = [_filler(1), _filler(2), [(60.0, "Durata del periodo dodici")], [(60.0, "ventiquattro")],
              [(60.0, "mesi dal giorno di avvio")], _filler(3), _filler(4)]
    result = compare_docs(build(_page(*target)), build(_page(*filled)))
    assert all(d.klass != "variabile" for d in result.diffs), [(d.op, d.klass, d.right_text) for d in result.diffs]


def test_a_heading_over_a_drawn_band_is_no_empty_section():
    known = Values.of({"offerta": {"riduzioni": "Nessuna riduzione per questo profilo."}})
    target = _page(_filler(1), [(60.0, "RIDUZIONI ACME")], [], [], [], [(60.0, "Opzioni Acme")], _filler(2))
    target.rect(60.0, 130.0, 300.0, 150.0)                 # a picture or a table fills the band
    filled = [_filler(1), [(60.0, "RIDUZIONI ACME")], [(60.0, "Nessuna riduzione per questo profilo.")],
              [], [], [(60.0, "Opzioni Acme")], _filler(2)]
    diff = _one(compare_docs(build(target), build(_page(*filled)), values=known), "riduzione per")
    assert diff.klass == "testo"


def test_a_value_placeholder_switched_off_stays_off():
    target, filled = _html("Ciao {{NOME}}, benvenuto in Acme"), _html("Ciao Mario, benvenuto in Acme")
    slot = _one(compare_docs(target, filled), "Mario")
    result = compare_docs(target, filled, disabled_slots=[slot.anchor])
    assert [d.klass for d in result.diffs] == ["testo"]


def test_a_value_replacing_a_target_word_is_a_change():
    # «vale ⎵ euro» → «vale 0,50»: «0,50» took the place of «euro» (a substitution), not the room's value
    target = _around([(60.0, "vale"), (98.0, "euro (nel periodo corrente)")])
    result = compare_docs(build(_page(*target)), build(_page(*_around([(60.0, "vale 0,50 (nel periodo corrente)")]))))
    assert [(d.op, d.klass, d.left_text, d.right_text) for d in result.diffs if d.klass != "stile"] ==         [("cambiato", "testo", "euro", "0,50")]


def test_a_split_does_not_happen_when_its_proof_is_switched_off():
    target = _around([(60.0, "vale"), (98.0, "euro (nel periodo corrente)")])     # a 22 pt gap before «euro»
    filled = _around([(60.0, "vale 0,50 euri (nel periodo corrente)")])      # «0,50» in the room, «euri» for «euro»
    off = Values.of(proofs=set(PROVE) - {"buco"})
    (diff,) = [d for d in compare_docs(build(_page(*target)), build(_page(*filled)), values=off).diffs
               if d.klass != "stile"]
    assert (diff.op, diff.klass, diff.prova, diff.left_text, diff.right_text) == \
        ("cambiato", "testo", "buco", "euro", "0,50 euri")
