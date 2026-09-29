"""Invisible text (spec §3.1): the ink test and the separate channel.

Text a reader cannot see — white on white, a hidden optional-content layer,
render mode 3, text drawn off the page — never reaches ``DocText.words`` (it
would be compared); it goes to ``DocText.invisible``. White text on a coloured
background IS visible and stays in the words. Synthetic files only: hand-written
PDFs (tests/officina/pdfraw.py) and Qt ones (tests/officina/pdfgen.py).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtGui import QColor

from qtrequestory.officina.compare.extract_pdf import extract
from tests.officina import pdfgen, pdfraw


def _texts(words) -> str:
    return " ".join(w.text for w in words)


PAGE = (pdfraw.text(72, 760, "Testo visibile")
        + pdfraw.hidden_layer(pdfraw.text(72, 740, "Edizione nascosta"))
        + pdfraw.text(72, 720, "Bianco su bianco", fill="1 g")
        + pdfraw.rect(60, 694, 200, 22) + pdfraw.text(72, 700, "Bianco su blu", fill="1 g")
        + pdfraw.text(72, 680, "Modo tre", mode=3)
        + pdfraw.text(72, 660, "Grigio chiarissimo", fill="0.94 g")
        + pdfraw.text(700, 640, "Fuori pagina"))


def test_invisible_text_goes_to_its_own_channel(tmp_path: Path):
    doc = extract(pdfraw.raw_pdf(tmp_path / "inv.pdf", [PAGE]))
    assert _texts(doc.words) == "Testo visibile Bianco su blu Grigio chiarissimo"
    assert _texts(doc.invisible) == "Edizione nascosta Bianco su bianco Modo tre"
    assert all(w.page == 0 for w in doc.invisible)
    hidden = doc.invisible[0]
    assert hidden.y0 == pytest.approx(842 - 740 - 12, abs=4), "invisible words keep their box"


def test_a_layer_switched_on_is_visible(tmp_path: Path):
    doc = extract(pdfraw.raw_pdf(tmp_path / "on.pdf", [PAGE], layer_on=True))
    assert "Edizione nascosta" in _texts(doc.words)
    assert "Edizione" not in _texts(doc.invisible)


def test_hidden_edition_over_the_visible_one_leaves_the_visible_line_whole(tmp_path: Path):
    """Two editions drawn in the same place, one in a layer that is off: the
    line reads as the visible edition only (not interleaved with the hidden one)."""
    page = (pdfraw.text(72, 600, "Ed. Gennaio 2027")
            + pdfraw.hidden_layer(pdfraw.text(72, 600, "Ed. Marzo 2019 ARCHIVIO")))
    doc = extract(pdfraw.raw_pdf(tmp_path / "ed.pdf", [page]))
    assert _texts(doc.words) == "Ed. Gennaio 2027"
    assert _texts(doc.invisible) == "Ed. Marzo 2019 ARCHIVIO"


def test_text_inside_forms_is_judged_where_the_form_is_drawn(tmp_path: Path):
    """Form XObjects report their objects' bounds in the form's own space: the
    ink test must look where the form is PLACED, or a visible white-on-blue
    text in a form would be judged on a blank area and wrongly hidden."""
    forms = [
        pdfraw.rect(0, 0, 200, 40) + pdfraw.text(10, 15, "Bianco nel modulo", fill="1 g"),
        pdfraw.text(10, 15, "Modulo nel livello"),
        pdfraw.text(10, 15, "Bianco nel vuoto", fill="1 g"),
    ]
    page = (b"q 1 0 0 1 300 400 cm /Fm0 Do Q\n"
            + pdfraw.hidden_layer(b"q 1 0 0 1 300 200 cm /Fm1 Do Q\n")
            + b"q 1 0 0 1 300 100 cm /Fm2 Do Q\n")
    doc = extract(pdfraw.raw_pdf(tmp_path / "forms.pdf", [page], forms=forms))
    assert _texts(doc.words) == "Bianco nel modulo"
    assert sorted(_texts(doc.invisible).split(" ")) == sorted("Modulo nel livello Bianco nel vuoto".split())


def test_white_text_painted_by_qt(pdfs: Path):
    """QPdfWriter writes one text object per glyph: each is tested on its own."""
    def paint(painter, _page):
        pdfgen.draw_text(painter, 72, 100, "Riga nera normale")
        pdfgen.draw_text(painter, 72, 130, "Codice bianco 00000", color=QColor("white"))
        pdfgen.fill_rect(painter, 60, 150, 250, 30, QColor(20, 40, 120))
        pdfgen.draw_text(painter, 72, 170, "Intestazione bianca", color=QColor("white"))

    doc = extract(pdfgen.painted_pdf(pdfs / "white.pdf", paint))
    assert _texts(doc.words) == "Riga nera normale Intestazione bianca"
    assert _texts(doc.invisible) == "Codice bianco 00000"


def test_invisible_only_text_is_no_text(tmp_path: Path):
    doc = extract(pdfraw.raw_pdf(tmp_path / "blank.pdf", [pdfraw.text(72, 700, "Solo bianco", fill="1 g")]))
    assert doc.words == [] and doc.has_text is False
    assert _texts(doc.invisible) == "Solo bianco"


def test_extraction_leaves_the_file_untouched(tmp_path: Path):
    path = pdfraw.raw_pdf(tmp_path / "inv.pdf", [PAGE])
    before = path.read_bytes()
    first = extract(path)
    assert path.read_bytes() == before
    assert extract(path) == first, "deterministic"


def test_invisible_chars_from_the_text_layer_are_split_off(monkeypatch):
    from qtrequestory.officina import pdf

    chars = [("a", (0, 0, 5, 10), (0, 0, 5, 10)), ("b", (5, 0, 10, 10), (5, 0, 10, 10)),
             (" ", None, None), ("c", (20, 0, 25, 10), (20, 0, 25, 10)), ("d", (25, 0, 30, 10), (25, 0, 30, 10))]
    page = pdf.PageChars(100, 100, chars, 0, invisible=[True, True, False, False, True])
    monkeypatch.setattr(pdf, "read_chars", lambda path: [page])
    doc = extract(Path("x.pdf"))
    assert [w.text for w in doc.words] == ["c"]
    assert [w.text for w in doc.invisible] == ["ab", "d"]


def test_hidden_glyphs_between_visible_ones_do_not_split_the_visible_word(monkeypatch):
    """Two editions in the same place, their glyphs interleaved in the text
    layer: the visible word stays whole (geometry decides, not the switch)."""
    from qtrequestory.officina import pdf

    def glyph(ch, x):
        return (ch, (x, 0, x + 5, 10), (x, 0, x + 5, 10))

    chars = [glyph("2", 0), glyph("0", 5), glyph("1", 0), glyph("9", 5), glyph("2", 10), glyph("7", 15)]
    page = pdf.PageChars(100, 100, chars, 0, invisible=[False, False, True, True, False, False])
    monkeypatch.setattr(pdf, "read_chars", lambda path: [page])
    doc = extract(Path("x.pdf"))
    assert [w.text for w in doc.words] == ["2027"]
    assert [w.text for w in doc.invisible] == ["19"]


# ------------------------------------------------ ruling F10: OCR layers ---

OCR = pdfraw.text(72, 700, "Testo riconosciuto dalla scansione", mode=3) + pdfraw.text(72, 680, "seconda riga letta", mode=3)


def test_the_invisible_ocr_layer_of_a_scan_is_its_text(tmp_path: Path):
    """A page that is one image covering the page, with invisible (mode 3)
    text on top, is a scan with its OCR layer: that text is the page's only
    reading, so it is kept as words (ruling F10)."""
    doc = extract(pdfraw.raw_pdf(tmp_path / "scan.pdf", [pdfraw.image(0, 0, 595, 842) + OCR]))
    assert _texts(doc.words) == "Testo riconosciuto dalla scansione seconda riga letta"
    assert doc.invisible == [] and doc.has_text is True


def test_invisible_text_next_to_a_small_image_stays_invisible(tmp_path: Path):
    page = pdfraw.image(40, 760, 120, 50) + OCR + pdfraw.text(72, 500, "Corpo visibile del modulo")
    doc = extract(pdfraw.raw_pdf(tmp_path / "logo.pdf", [page]))
    assert _texts(doc.words) == "Corpo visibile del modulo"
    assert _texts(doc.invisible) == "Testo riconosciuto dalla scansione seconda riga letta"


def test_a_full_page_image_under_real_text_keeps_the_hidden_text_hidden(tmp_path: Path):
    """A background image with enough visible text on it is not a scan: its
    white-on-white or mode-3 text stays out of the comparison."""
    visible = pdfraw.text(72, 500, "Uno due tre quattro cinque sei sette")
    doc = extract(pdfraw.raw_pdf(tmp_path / "bg.pdf", [pdfraw.image(0, 0, 595, 842) + visible + OCR]))
    assert _texts(doc.words) == "Uno due tre quattro cinque sei sette"
    assert _texts(doc.invisible) == "Testo riconosciuto dalla scansione seconda riga letta"


# ------------------------------------- review M6: nothing leaks to the viewer ---

def test_extraction_never_changes_what_the_viewer_renders(tmp_path: Path):
    """The ink tests change render modes and matrices IN MEMORY; the viewer's
    renders of the same file, before and after an extraction, are identical."""
    from qtrequestory.officina import pdf

    forms = [pdfraw.rect(0, 0, 200, 40) + pdfraw.text(10, 15, "Bianco nel modulo", fill="1 g")]
    page = PAGE + b"q 1 0 0 1 300 400 cm /Fm0 Do Q\n" + pdfraw.hidden_layer(pdfraw.rect(300, 300, 60, 10, fill="0 g"))
    path = pdfraw.raw_pdf(tmp_path / "leak.pdf", [page], forms=forms)
    before = pdf.render_page(path, 0, 1.5)
    extract(path)
    assert pdf.render_page(path, 0, 1.5) == before


def test_words_drawn_in_a_light_colour_are_marked(tmp_path: Path):
    """Review A2 I1: the zone stage needs to know a pale word (a watermark's
    colour); ``DocText.light`` holds their indices, horizontal or rotated."""
    page = (pdfraw.text(72, 760, "Testo scuro")
            + pdfraw.text(100, 400, "FACSIMILE", size=50, fill="0.8 g")
            + pdfraw.text(300, 300, "BOZZA", size=40, fill="0.75 g", tm="0.7071 0.7071 -0.7071 0.7071")
            + pdfraw.rect(60, 194, 200, 22) + pdfraw.text(72, 200, "Bianco su blu", fill="1 g")
            + pdfraw.text(72, 160, "Grigio medio", fill="0.5 g"))
    doc = extract(pdfraw.raw_pdf(tmp_path / "light.pdf", [page]))
    light = {doc.words[i].text for i in doc.light}
    assert light == {"FACSIMILE", "BOZZA", "Bianco", "su", "blu"}
    assert all(0 <= i < len(doc.words) for i in doc.light)
