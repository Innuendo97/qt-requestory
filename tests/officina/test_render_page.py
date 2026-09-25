"""qtrequestory.officina.pdf.render_page: one page to a BGRx pixel buffer.

The viewer draws the Word boxes of ``compare.extract_pdf`` over these images,
so a page must be rendered in its DISPLAYED orientation (CropBox and /Rotate
applied): the ink of a word must sit inside that word's box.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from qtrequestory.officina import pdf
from qtrequestory.officina.compare.extract_pdf import extract
from tests.officina import pdfgen
from tests.officina.test_extract import _variant


def _dark_pixels(page: pdf.RenderedPage, box, scale: float) -> int:
    """How many pixels darker than mid-grey lie inside ``box`` (points)."""
    x0, y0, x1, y1 = (round(v * scale) for v in box)
    count = 0
    for y in range(max(0, y0), min(page.height, y1)):
        row = y * page.stride
        for x in range(max(0, x0), min(page.width, x1)):
            b, g, r = page.data[row + 4 * x: row + 4 * x + 3]
            if r + g + b < 3 * 128:
                count += 1
    return count


def test_page_is_rendered_at_the_requested_scale(pdfs: Path):
    path = pdfgen.paragraphs_pdf(pdfs / "a.pdf", ["Alfa beta gamma"])
    page = pdf.render_page(path, 0, 2.0)
    assert (page.width, page.height) == (pytest.approx(1190, abs=2), pytest.approx(1684, abs=2))
    assert page.stride >= 4 * page.width
    assert len(page.data) == page.stride * page.height


def test_page_count(pdfs: Path):
    path = pdfgen.paragraphs_pdf(pdfs / "a.pdf", [pdfgen.lorem(1500)])
    assert pdf.page_count(path) == len(extract(path).page_sizes) >= 2


@pytest.mark.parametrize("rotation", [0, 90, 270])
def test_page_sizes_are_the_displayed_sizes_extract_reports(pdfs: Path, rotation: int):
    """The workbench lays pages out with ``page_sizes`` (no text read) and puts
    the ``extract`` word boxes on them: both must mean the same page."""
    base = pdfgen.paragraphs_pdf(pdfs / "base.pdf", [pdfgen.lorem(1500)])

    def change(page):
        page.set_cropbox(20, 30, 580, 830)
        page.set_rotation(rotation)

    path = _variant(base, pdfs / "turned.pdf", change)
    assert pdf.page_sizes(path) == [pytest.approx(s) for s in extract(path).page_sizes]


def test_page_sizes_of_a_broken_file_is_a_readable_error(pdfs: Path):
    broken = pdfs / "rotto.pdf"
    broken.write_bytes(b"%PDF-1.4 non un pdf")
    with pytest.raises(pdf.PdfReadError):
        pdf.page_sizes(broken)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_ink_lies_inside_the_word_boxes_on_rotated_and_cropped_pages(pdfs: Path, rotation: int):
    base = pdfgen.paragraphs_pdf(pdfs / "base.pdf", ["Alfa beta gamma"] + ["riempitivo parola"] * 20)

    def change(page):
        page.set_cropbox(20, 30, 580, 830)
        page.set_rotation(rotation)

    path = _variant(base, pdfs / "turned.pdf", change)
    doc = extract(path)
    scale = 1.5
    page = pdf.render_page(path, 0, scale)
    width, height = doc.page_sizes[0]
    assert (page.width, page.height) == (pytest.approx(width * scale, abs=2),
                                         pytest.approx(height * scale, abs=2))
    first = doc.words[0]
    assert _dark_pixels(page, (first.x0, first.y0, first.x1, first.y1), scale) > 20
    # the same box moved away from any text holds no ink
    blank = (width / 2 - 5, height / 2 - 5, width / 2 + 5, height / 2 + 5)
    words_there = [w for w in doc.words if w.x0 < blank[2] and w.x1 > blank[0]
                   and w.y0 < blank[3] and w.y1 > blank[1]]
    if not words_there:
        assert _dark_pixels(page, blank, scale) == 0


def test_bad_page_or_file_is_a_readable_error(pdfs: Path):
    path = pdfgen.paragraphs_pdf(pdfs / "a.pdf", ["uno"])
    with pytest.raises(IndexError):
        pdf.render_page(path, 5, 1.0)
    broken = pdfs / "broken.pdf"
    broken.write_bytes(b"%PDF-1.4 not really")
    with pytest.raises(pdf.PdfReadError):
        pdf.render_page(broken, 0, 1.0)


class _RecordingLock:
    """Stands in for ``pdf._LOCK``: records when it is held."""

    def __init__(self) -> None:
        self.depth = 0
        self.acquisitions = 0

    def __enter__(self):
        self.depth += 1
        self.acquisitions += 1
        return self

    def __exit__(self, *_exc) -> None:
        self.depth -= 1


def test_read_chars_lets_go_of_pdfium_between_pages(pdfs: Path, monkeypatch):
    """A long extraction must not starve the viewer's render threads: the
    global PDFium lock is held per page, not for the whole document (and
    PDFium itself is only ever entered with the lock held)."""
    path = pdfgen.image_only_pdf(pdfs / "tre.pdf", pages=3)
    lock = _RecordingLock()
    monkeypatch.setattr(pdf, "_LOCK", lock)
    held_per_page: list[int] = []
    real_page_chars = pdf._page_chars

    def page_chars(page):
        held_per_page.append(lock.depth)
        return real_page_chars(page)

    monkeypatch.setattr(pdf, "_page_chars", page_chars)

    pages = pdf.read_chars(path)

    assert len(pages) == 3
    assert held_per_page == [1, 1, 1], "each page is read with the lock held"
    assert lock.acquisitions >= 4, "released and taken again between pages"
    assert lock.depth == 0
