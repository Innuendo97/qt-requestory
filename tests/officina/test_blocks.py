"""Blocks from positioned words (spec §4.2 step 6)."""
from __future__ import annotations

from pathlib import Path

from qtrequestory.officina.compare.blocks import content_keys, make_blocks
from qtrequestory.officina.compare.model import Word

CHAR = 5.5   # synthetic glyph width (points)
HEIGHT = 11.0
PITCH = 12.25        # line pitch inside a paragraph
PARA_PITCH = 21.5    # pitch across a paragraph break


def _line(text: str, bottom: float, *, x: float = 42.0, page: int = 0, size: float = 11.0,
          height: float = HEIGHT) -> list[Word]:
    words = []
    for token in text.split():
        width = CHAR * len(token) * size / 11.0
        words.append(Word(token, page, x, bottom - height, x + width, bottom, size, False))
        x += width + CHAR
    return words


def _text(block) -> str:
    return " ".join(w.text for w in block.words)


def _lines(texts: list[str], start: float = 60.0, pitches: list[float] | None = None, **kw) -> list[Word]:
    words, bottom = [], start
    for k, text in enumerate(texts):
        words += _line(text, bottom, **kw)
        bottom += (pitches[k] if pitches else PITCH)
    return words


def test_no_words_no_blocks():
    assert make_blocks([]) == []


def test_line_gap_splits_paragraphs():
    words = _lines(["alfa beta gamma delta", "epsilon zeta eta", "theta iota kappa", "lambda mu"],
                   pitches=[PITCH, PARA_PITCH, PITCH, PITCH])
    blocks = make_blocks(words)
    assert [_text(b) for b in blocks] == ["alfa beta gamma delta epsilon zeta eta",
                                          "theta iota kappa lambda mu"]
    assert [b.id for b in blocks] == [0, 1]
    assert all(b.kind == "paragrafo" and b.page == 0 for b in blocks)


def test_single_line_paragraphs_still_split():
    """A document made only of one-line paragraphs: the median pitch is the
    paragraph pitch, the line height still tells them apart."""
    words = _lines([f"voce numero {k} del elenco" for k in range(6)], pitches=[PARA_PITCH] * 6)
    assert len(make_blocks(words)) == 6


def test_words_on_one_baseline_make_one_line_in_x_order():
    line = _line("uno due tre", 60.0)
    shuffled = [line[2], line[0], line[1]]
    assert [_text(b) for b in make_blocks(shuffled)] == ["uno due tre"]


def test_first_line_indent_starts_a_paragraph_hanging_indent_does_not():
    first_line = (_line("Primo capoverso rientrato", 60.0, x=60.0) + _line("che continua qui", 60 + PITCH)
                  + _line("e ancora qui", 60 + 2 * PITCH) + _line("Secondo capoverso", 60 + 3 * PITCH, x=60.0)
                  + _line("con seguito", 60 + 4 * PITCH))
    assert len(make_blocks(first_line)) == 2
    hanging = (_line("1. Voce di elenco", 60.0) + _line("rientro sospeso", 60 + PITCH, x=60.0)
               + _line("ancora rientro", 60 + 2 * PITCH, x=60.0))
    assert len(make_blocks(hanging)) == 1


def test_font_size_change_splits_a_heading():
    words = _line("Titolo", 60.0, size=16.0, height=16.0) + _lines(["corpo del testo", "che segue"], start=60 + 17)
    assert [_text(b) for b in make_blocks(words)] == ["Titolo", "corpo del testo che segue"]


def test_form_rows_are_their_own_riga_modulo_blocks():
    words = _lines(["Premessa del modulo", "Nome .......... Cognome ..........",
                    "Nome .......... Cognome ..........", "☐ Accetto le condizioni",
                    "[ x ] Ricevo la bolletta", "Note finali del modulo"])
    blocks = make_blocks(words)
    assert [(b.kind, _text(b)) for b in blocks] == [
        ("paragrafo", "Premessa del modulo"),
        ("riga_modulo", "Nome .......... Cognome .........."),
        ("riga_modulo", "Nome .......... Cognome .........."),
        ("riga_modulo", "☐ Accetto le condizioni"),
        ("riga_modulo", "[ x ] Ricevo la bolletta"),
        ("paragrafo", "Note finali del modulo"),
    ]


def test_a_leader_glued_to_its_label_is_a_form_row():
    words = _lines(["Località.......... Provincia ____", "testo normale"])
    assert [b.kind for b in make_blocks(words)] == ["riga_modulo", "paragrafo"]


def test_blocks_never_span_pages_and_ids_follow_order():
    words = _lines(["pagina uno riga", "pagina uno ancora"]) + _lines(["pagina due riga"], page=1)
    blocks = make_blocks(words)
    assert [(b.id, b.page) for b in blocks] == [(0, 0), (1, 1)]


def test_columns_split_by_an_empty_corridor():
    rows = [("sinistra alfa beta", "destra uno due"), ("sinistra gamma", "destra tre quattro"),
            ("sinistra delta eps", "destra cinque"), ("sinistra zeta", "destra sei sette")]
    words = _line("Intestazione su tutta la larghezza della pagina di prova", 48.0)
    for k, (left, right) in enumerate(rows):
        bottom = 48 + PARA_PITCH + k * PITCH
        words += _line(left, bottom) + _line(right, bottom, x=320.0)
    blocks = make_blocks(words)
    assert [_text(b) for b in blocks] == [
        "Intestazione su tutta la larghezza della pagina di prova",
        "sinistra alfa beta sinistra gamma sinistra delta eps sinistra zeta",
        "destra uno due destra tre quattro destra cinque destra sei sette",
    ]


def test_a_single_wide_gap_is_not_a_column():
    words = _lines(["Luogo e data", "altra riga di testo normale"])
    words += _line("Firma", 60.0, x=400.0)
    blocks = make_blocks(sorted(words, key=lambda w: (w.y1, w.x0)))
    assert [_text(b) for b in blocks] == ["Luogo e data Firma altra riga di testo normale"]


def test_deterministic():
    words = _lines(["alfa beta", "gamma", "Nome .......... Cognome ....", "delta"],
                   pitches=[PITCH, PARA_PITCH, PITCH, PITCH])
    assert make_blocks(words) == make_blocks(list(words))


def test_two_column_pdf_gives_two_column_groups(pdfs: Path):
    from qtrequestory.officina.compare.extract_pdf import extract
    from tests.officina import pdfgen

    left, right = pdfgen.lorem(90, seed=3), pdfgen.lorem(90, seed=4)
    html = ("<p>Intestazione Acme-Servizi del documento di prova</p>"
            "<table width='100%' cellpadding='0' cellspacing='0'><tr>"
            f"<td width='46%' valign='top'>{left}</td><td width='8%'></td>"
            f"<td width='46%' valign='top'>{right}</td></tr></table>")
    blocks = make_blocks(extract(pdfgen.html_pdf(pdfs / "cols.pdf", html)).words)
    assert _text(blocks[0]) == "Intestazione Acme-Servizi del documento di prova"
    columns = blocks[1:]
    assert [" ".join(_text(b) for b in columns if b.words[0].x0 < 297)] == [left]
    assert [" ".join(_text(b) for b in columns if b.words[0].x0 >= 297)] == [right]
    first_right = next(k for k, b in enumerate(columns) if b.words[0].x0 >= 297)
    assert all(b.words[0].x0 < 297 for b in columns[:first_right])
    for block in columns:  # no block straddles the gutter
        assert len({w.x0 < 297 for w in block.words}) == 1


def test_pdf_paragraphs_become_blocks(pdfs: Path):
    from qtrequestory.officina.compare.extract_pdf import extract
    from tests.officina import pdfgen

    paragraphs = [pdfgen.lorem(50, seed=1), pdfgen.lorem(12, seed=2), "Nome .......... Cognome ..........",
                  pdfgen.lorem(30, seed=5)]
    blocks = make_blocks(extract(pdfgen.paragraphs_pdf(pdfs / "p.pdf", paragraphs)).words)
    assert [_text(b) for b in blocks] == paragraphs
    assert [b.kind for b in blocks] == ["paragrafo", "paragrafo", "riga_modulo", "paragrafo"]


def test_content_keys_drop_slot_leaders():
    assert content_keys(_line("Località.......... Provincia ____ Nome ……", 60.0)) == ["Località", "Provincia", "Nome"]
    assert content_keys(_line("Nome .......... Cognome", 60.0)) == ["Nome", "Cognome"]
    assert content_keys(_line("fine. punto...", 60.0)) == ["fine.", "punto..."]
