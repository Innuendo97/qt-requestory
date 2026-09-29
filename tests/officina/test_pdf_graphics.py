"""The page's graphics (spec §3.1): paths and images, for the zones stage.

``DocText.graphics[page]`` lists every path (box on the displayed page, stroke
width, fill and stroke colour — None when the path is not filled / not
stroked —, segment count) and every image box. Boxes are in the same space as
the words: points of the page as displayed, origin top-left. Synthetic files only.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtGui import QColor

from qtrequestory.officina.compare.extract_pdf import PageGraphics, PathShape, extract
from tests.officina import pdfgen, pdfraw


def test_divider_line_and_filled_rectangle(pdfs: Path):
    def paint(painter, _page):
        pdfgen.draw_text(painter, 72, 100, "Testo sopra il divisore")
        pdfgen.draw_line(painter, 20, 800, 575, 800, width=2)
        pdfgen.fill_rect(painter, 100, 300, 50, 20, QColor(200, 30, 30))

    doc = extract(pdfgen.painted_pdf(pdfs / "div.pdf", paint))
    graphics = doc.graphics[0]
    assert isinstance(graphics, PageGraphics) and graphics.images == ()
    stroked = [p for p in graphics.paths if p.stroke is not None]
    filled = [p for p in graphics.paths if p.fill is not None]
    assert len(stroked) == 1 and len(filled) == 1
    line = stroked[0]
    assert isinstance(line, PathShape)
    # the bounds include the stroke and its caps (up to the pen width past each end)
    assert line.box[0] == pytest.approx(20, abs=2.5) and line.box[2] == pytest.approx(575, abs=2.5)
    assert line.box[1] == pytest.approx(800, abs=2.5) and line.box[3] == pytest.approx(800, abs=2.5)
    assert line.stroke_width == pytest.approx(2, abs=0.1)
    assert line.stroke == (0, 0, 0, 255) and line.fill is None
    assert 1 <= line.segments <= 6
    box = filled[0]
    assert box.box == pytest.approx((100, 300, 150, 320), abs=0.5)
    assert box.fill == (200, 30, 30, 255) and box.stroke is None


def test_images_are_listed_with_their_boxes(pdfs: Path):
    doc = extract(pdfgen.image_only_pdf(pdfs / "scan.pdf", pages=2))
    assert [len(g.images) for g in doc.graphics] == [1, 1]
    assert doc.graphics[0].images[0] == pytest.approx((0, 0, 595, 842), abs=1)


def test_graphics_follow_the_page_rotation(tmp_path: Path):
    page = pdfraw.rect(100, 700, 50, 20)  # user space: x 100-150, y 700-720
    upright = extract(pdfraw.raw_pdf(tmp_path / "up.pdf", [page])).graphics[0].paths
    turned = extract(pdfraw.raw_pdf(tmp_path / "rot.pdf", [page], rotate=90)).graphics[0].paths
    assert upright[0].box == pytest.approx((100, 122, 150, 142), abs=0.05)
    # /Rotate 90 turns the page clockwise: (x0, y0, x1, y1) -> (H - y1, x0, H - y0, x1)
    assert turned[0].box == pytest.approx((842 - 142, 100, 842 - 122, 150), abs=0.05)
    assert turned[0].fill == (0, 0, 128, 255)


def test_paths_inside_forms_are_placed_where_the_form_is_drawn(tmp_path: Path):
    forms = [pdfraw.rect(10, 10, 30, 5, fill="0 g")]
    doc = extract(pdfraw.raw_pdf(tmp_path / "form.pdf", [b"q 1 0 0 1 300 400 cm /Fm0 Do Q\n"], forms=forms))
    boxes = [p.box for p in doc.graphics[0].paths]
    assert boxes == [pytest.approx((310, 842 - 415, 340, 842 - 410), abs=0.05)]


def test_one_graphics_entry_per_page_even_without_graphics(pdfs: Path):
    doc = extract(pdfgen.paragraphs_pdf(pdfs / "a.pdf", ["Solo testo"]))
    assert doc.graphics == [PageGraphics()]


def test_graphics_of_a_hidden_layer_are_left_out(tmp_path: Path):
    """Review M1: a logo or divider in an optional-content layer that is OFF
    is not drawn, so the zones must not see it; switched ON it is there."""
    page = (pdfraw.rect(100, 700, 50, 20)
            + pdfraw.hidden_layer(pdfraw.rect(20, 40, 555, 3, fill="0 g") + pdfraw.image(400, 700, 100, 40)))
    off = extract(pdfraw.raw_pdf(tmp_path / "off.pdf", [page])).graphics[0]
    on = extract(pdfraw.raw_pdf(tmp_path / "on.pdf", [page], layer_on=True)).graphics[0]
    assert [p.box for p in off.paths] == [pytest.approx((100, 122, 150, 142), abs=0.05)]
    assert off.images == ()
    assert len(on.paths) == 2 and len(on.images) == 1


def test_read_graphics_on_a_page_matches_the_extraction(tmp_path: Path):
    import pypdfium2 as pdfium  # test-only: hands a page to the public read_graphics

    from qtrequestory.officina import pdf

    page = pdfraw.rect(100, 700, 50, 20) + pdfraw.hidden_layer(pdfraw.rect(20, 40, 555, 3, fill="0 g"))
    path = pdfraw.raw_pdf(tmp_path / "rg.pdf", [page], rotate=90)
    doc = pdfium.PdfDocument(str(path))
    try:
        with pdf._LOCK:
            shapes = pdf.read_graphics(doc[0])
    finally:
        doc.close()
    assert shapes == extract(path).graphics[0]
