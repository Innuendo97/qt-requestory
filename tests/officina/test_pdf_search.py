"""qtrequestory.officina.pdf.TextSearch: occurrences of a text in a PDF, for
``extract_html.locate`` (spec §6). Hand-built PDFs (no Qt)."""
from __future__ import annotations

from pathlib import Path

import pytest

from qtrequestory.officina.compare.extract_html import locate
from qtrequestory.officina.compare.extract_pdf import extract
from tests.fakes.fake_core import canned_pdf


def test_every_occurrence_with_its_page_and_display_box(tmp_path: Path):
    from qtrequestory.officina.pdf import TextSearch

    path = tmp_path / "stampa.pdf"
    path.write_bytes(canned_pdf("Gentile cliente di prova\nil prezzo resta fisso\nprezzo finale"))
    words = {w.text: w for w in extract(path).words if w.y0 < 80}  # the first two lines
    with TextSearch(path) as search:
        hits = search("prezzo resta")
        again = search("prezzo")
        none = search("assente del tutto")
        located = locate("il prezzo resta fisso", search)
    assert len(hits) == 1
    page, (x0, y0, x1, y1) = hits[0]
    assert page == 0
    assert x0 == pytest.approx(words["prezzo"].x0, abs=1.5) and x1 == pytest.approx(words["resta"].x1, abs=1.5)
    assert y0 == pytest.approx(words["prezzo"].y0, abs=2) and y1 == pytest.approx(words["prezzo"].y1, abs=2)
    assert len(again) == 2 and none == []
    assert [page for page, _ in located] == [0]


def test_a_search_after_close_finds_nothing_and_an_unreadable_file_raises(tmp_path: Path):
    from qtrequestory.officina.pdf import PdfReadError, TextSearch

    path = tmp_path / "stampa.pdf"
    path.write_bytes(canned_pdf("uno due"))
    search = TextSearch(path)
    search.close()
    assert search("uno") == []
    bad = tmp_path / "rotto.pdf"
    bad.write_bytes(b"non un pdf")
    with pytest.raises(PdfReadError):
        TextSearch(bad)
