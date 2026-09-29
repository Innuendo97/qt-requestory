"""Rotated text (spec §3.1): words read in their own direction.

Margin text drawn at 90/270 degrees has zero-area loose glyph boxes; its words
are built from the TIGHT boxes and grouped into lines by the glyph ORIGIN
(the baseline), then read along the text. ``DocText.angle(i)`` gives each
word's angle (clockwise degrees, PDFium's convention: 270 reads bottom-up,
90 top-down; 0 horizontal). Synthetic files only.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from qtrequestory.officina.compare.extract_pdf import DocText, extract
from tests.officina import pdfgen, pdfraw

EDITION = "Doc X - Ed. Gennaio 2027"  # Qt maps an en dash to U+FFFD: a hyphen
COPY = "Copia per il Cliente"


def _by_angle(doc: DocText, angle: int) -> list[str]:
    return [w.text for i, w in enumerate(doc.words) if doc.angle(i) == angle]


def _margins(painter, _page):
    pdfgen.draw_text(painter, 100, 100, "Corpo del documento riga uno")
    pdfgen.draw_text(painter, 100, 116, "Corpo del documento riga due")
    pdfgen.draw_text(painter, 30, 700, EDITION, angle=-90)
    pdfgen.draw_text(painter, 44, 700, COPY, angle=-90)
    pdfgen.draw_text(painter, 570, 100, "Destra dall alto", angle=90)


def test_margin_text_reads_along_its_direction(pdfs: Path):
    doc = extract(pdfgen.painted_pdf(pdfs / "rot.pdf", _margins))
    assert _by_angle(doc, 0) == "Corpo del documento riga uno Corpo del documento riga due".split()
    assert _by_angle(doc, 270) == (EDITION + " " + COPY).split()
    assert _by_angle(doc, 90) == "Destra dall alto".split()
    assert len(doc.words) == len(_by_angle(doc, 0)) + len(_by_angle(doc, 270)) + len(_by_angle(doc, 90))


def test_horizontal_words_come_first_and_have_no_angle(pdfs: Path):
    doc = extract(pdfgen.painted_pdf(pdfs / "rot.pdf", _margins))
    assert [doc.angle(i) for i in range(10)] == [0] * 10
    assert all(angle in (90, 270) for angle in doc.rotated.values())
    assert min(doc.rotated) == 10


def test_rotated_words_have_real_boxes_in_the_margin(pdfs: Path):
    doc = extract(pdfgen.painted_pdf(pdfs / "rot.pdf", _margins))
    left = [w for i, w in enumerate(doc.words) if doc.angle(i) == 270]
    for w in left:
        assert w.x1 - w.x0 > 0.5 and w.y1 - w.y0 > 0.5, w  # a real area (a hyphen is ~1 pt thick)
        assert 15 < w.x0 < w.x1 < 50, w
        assert 400 < w.y0 < w.y1 < 702, w
    assert left[0].y0 > left[1].y0 > left[2].y0, "bottom-up text: each word is higher on the page"
    right = [w for i, w in enumerate(doc.words) if doc.angle(i) == 90]
    assert right[0].y0 < right[1].y0 < right[2].y0, "top-down text"
    assert all(w.x0 > 560 for w in right)


def test_a_rotated_margin_is_the_same_on_every_page(pdfs: Path):
    doc = extract(pdfgen.painted_pdf(pdfs / "rot2.pdf", _margins, pages=2))
    per_page = [[w.text for i, w in enumerate(doc.words) if w.page == p and doc.angle(i) == 270] for p in (0, 1)]
    assert per_page[0] == per_page[1] == (EDITION + " " + COPY).split()


def test_rotated_text_matrix_in_a_hand_written_pdf(tmp_path: Path):
    """A text matrix ``0 1 -1 0`` turns the text counter-clockwise: it reads
    bottom-up, which PDFium reports as 270."""
    page = pdfraw.text(100, 700, "Riga orizzontale") + pdfraw.text(40, 300, "Margine ruotato qui", tm="0 1 -1 0")
    doc = extract(pdfraw.raw_pdf(tmp_path / "tm.pdf", [page]))
    assert _by_angle(doc, 0) == ["Riga", "orizzontale"]
    assert _by_angle(doc, 270) == ["Margine", "ruotato", "qui"]


def test_rotated_line_is_grouped_by_origin_not_by_box(monkeypatch):
    """A dash's tight box sits 2 pt off the line (it is a short glyph in the
    middle of the x-height); grouped by box it would open a line of its own.
    Grouped by origin it stays in its line, and in reading order."""
    from qtrequestory.officina import pdf

    # Text space (x right, y down = minus the PDF's y); the text reads
    # bottom-up (angle 270): each glyph starts 6 pt above the previous one.
    # Baseline at x = 30: glyph bodies to its left (x 22-30); the dash box is
    # off the line (x 31-32): grouped by box it would read after the line.
    def glyph(ch, y, x0=22.0, x1=30.0):
        return (ch, (x0, y - 6, x1, y), (x0, 842 + y - 6, x1, 842 + y))

    sep = (" ", None, None)
    chars = [glyph("E", -114), glyph("d", -120), sep, glyph("–", -132, 31.0, 32.0), sep,
             glyph("2", -144), glyph("0", -150)]
    origins = [None if c[1] is None else (30.0, c[1][3]) for c in chars]
    angles = [0 if c[1] is None else 270 for c in chars]
    fonts = [None if c[1] is None else (8.0, False) for c in chars]
    page = pdf.PageChars(595, 842, chars, 0, fonts, angles=angles, origins=origins)
    monkeypatch.setattr(pdf, "read_chars", lambda path: [page])
    doc = extract(Path("x.pdf"))
    assert [w.text for w in doc.words] == ["Ed", "–", "20"]
    assert doc.rotated == {0: 270, 1: 270, 2: 270}


def test_documents_without_rotation_have_an_empty_map(pdfs: Path):
    doc = extract(pdfgen.paragraphs_pdf(pdfs / "a.pdf", ["Alfa beta gamma"]))
    assert doc.rotated == {}
    assert doc.angle(0) == 0
    with pytest.raises(IndexError):
        doc.angle(len(doc.words))
