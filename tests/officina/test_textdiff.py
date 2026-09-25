"""qtrequestory.officina.compare.textdiff: word diff between two documents.

Left = reference (TARGET), right = compared (TO-BE / AS-IS). PDFs are generated
by Qt from synthetic text (tests/officina/pdfgen.py).
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from qtrequestory.officina.compare.extract_pdf import DocText, Word, extract
from qtrequestory.officina.compare.textdiff import (
    Difference,
    TextComparison,
    compare_text,
    normalise,
)
from tests.officina import pdfgen

BASE = [
    "Condizioni generali di fornitura per il cliente di prova.",
    "Il prezzo della componente servizio resta fisso per dodici mesi.",
    "Le comunicazioni arrivano all'indirizzo example.invalid indicato nel modulo.",
]


def _doc(*texts: str, page: int = 0) -> DocText:
    """A synthetic DocText: one line per text, words 10 pt apart."""
    words = []
    for line, text in enumerate(texts):
        for i, token in enumerate(text.split()):
            y = 50.0 + 14 * line
            words.append(Word(token, page, 40.0 + 30 * i, y, 40.0 + 30 * i + 25, y + 10))
    return DocText(words, [(595.0, 842.0)], True)


# ------------------------------------------------------------------ PDFs ---

def test_identical_text_is_equal(pdfs: Path):
    a = extract(pdfgen.paragraphs_pdf(pdfs / "a.pdf", BASE))
    b = extract(pdfgen.paragraphs_pdf(pdfs / "b.pdf", BASE))
    result = compare_text(a, b)
    assert isinstance(result, TextComparison)
    assert result.equal and result.differences == [] and result.note == ""
    assert result.left_has_text and result.right_has_text


def test_one_changed_word_has_boxes_on_both_sides(pdfs: Path):
    changed = [BASE[0], BASE[1].replace("dodici", "ventiquattro"), BASE[2]]
    a = extract(pdfgen.paragraphs_pdf(pdfs / "a.pdf", BASE))
    b = extract(pdfgen.paragraphs_pdf(pdfs / "b.pdf", changed))
    result = compare_text(a, b)
    assert not result.equal
    assert len(result.differences) == 1
    diff = result.differences[0]
    assert isinstance(diff, Difference)
    assert diff.kind == "changed"
    assert (diff.left_text, diff.right_text) == ("dodici", "ventiquattro")
    left_word = next(w for w in a.words if w.text == "dodici")
    right_word = next(w for w in b.words if w.text == "ventiquattro")
    assert diff.left == [left_word] and diff.right == [right_word]
    assert right_word.x0 == pytest.approx(left_word.x0, abs=0.5), "same place on both pages"
    assert right_word.x1 > left_word.x1, "the longer word has the wider box"


def test_inserted_paragraph_is_added(pdfs: Path):
    extra = "Paragrafo aggiunto solo nella nuova versione."
    a = extract(pdfgen.paragraphs_pdf(pdfs / "a.pdf", BASE))
    b = extract(pdfgen.paragraphs_pdf(pdfs / "b.pdf", [BASE[0], extra, BASE[1], BASE[2]]))
    result = compare_text(a, b)
    assert [d.kind for d in result.differences] == ["added"]
    diff = result.differences[0]
    assert diff.left == [] and diff.left_text == ""
    assert diff.right_text == extra
    assert [w.text for w in diff.right] == extra.split()


def test_removed_paragraph_is_removed(pdfs: Path):
    a = extract(pdfgen.paragraphs_pdf(pdfs / "a.pdf", BASE))
    b = extract(pdfgen.paragraphs_pdf(pdfs / "b.pdf", [BASE[0], BASE[2]]))
    result = compare_text(a, b)
    assert [d.kind for d in result.differences] == ["removed"]
    assert result.differences[0].left_text == BASE[1]
    assert result.differences[0].right == []


def test_text_reflowed_onto_the_next_page_is_equal(pdfs: Path):
    paragraphs = [pdfgen.lorem(120, seed=n) for n in range(6)]
    a = extract(pdfgen.paragraphs_pdf(pdfs / "a.pdf", paragraphs, font_pt=10))
    b = extract(pdfgen.paragraphs_pdf(pdfs / "b.pdf", paragraphs, font_pt=15, width_mm=120))
    assert len(b.page_sizes) > len(a.page_sizes), "the fixture must really reflow"
    result = compare_text(a, b)
    assert result.equal, [(d.left_text, d.right_text) for d in result.differences]


def test_hyphenated_line_end_equals_the_whole_word(pdfs: Path):
    a = extract(pdfgen.html_pdf(pdfs / "a.pdf", "<p>Il contratto di forni-<br>tura resta valido</p>"))
    b = extract(pdfgen.html_pdf(pdfs / "b.pdf", "<p>Il contratto di fornitura resta valido</p>"))
    assert "forni-" in [w.text for w in a.words]
    assert compare_text(a, b).equal


def test_target_without_text_is_reported_not_diffed(pdfs: Path):
    scan = extract(pdfgen.image_only_pdf(pdfs / "scan.pdf"))
    tobe = extract(pdfgen.paragraphs_pdf(pdfs / "tobe.pdf", BASE))
    result = compare_text(scan, tobe)
    assert result.equal is False
    assert result.differences == []
    assert result.left_has_text is False and result.right_has_text is True
    assert result.note == "il target non ha testo estraibile"


def test_compared_side_without_text_names_its_label(pdfs: Path):
    target = extract(pdfgen.paragraphs_pdf(pdfs / "t.pdf", BASE))
    scan = extract(pdfgen.image_only_pdf(pdfs / "scan.pdf"))
    assert compare_text(target, scan).note == "il TO-BE non ha testo estraibile"
    assert compare_text(target, scan, right_label="AS-IS").note == "l'AS-IS non ha testo estraibile"


def test_two_ten_page_documents_compare_quickly(pdfs: Path):
    paragraphs = [pdfgen.lorem(90, seed=n) for n in range(75)]
    edited = list(paragraphs)
    edited[10] = edited[10].replace(edited[10].split()[3], "modificata", 1)
    del edited[30]
    edited.insert(45, "Paragrafo nuovo di prova.")
    a = extract(pdfgen.paragraphs_pdf(pdfs / "a.pdf", paragraphs, font_pt=11))
    b = extract(pdfgen.paragraphs_pdf(pdfs / "b.pdf", edited, font_pt=11))
    assert len(a.page_sizes) >= 10
    started = time.perf_counter()
    result = compare_text(extract(pdfs / "a.pdf"), extract(pdfs / "b.pdf"))
    elapsed = time.perf_counter() - started
    assert elapsed < 5, f"extract + compare of two 10-page PDFs took {elapsed:.2f} s"
    assert sorted(d.kind for d in result.differences) == ["added", "changed", "removed"]
    assert compare_text(a, b) == compare_text(a, b), "deterministic"


# --------------------------------------------------------- pure (no PDF) ---

def test_normalise_unifies_quotes_dashes_and_compatibility_forms():
    assert normalise("“ciao”") == '"ciao"'
    assert normalise("«ciao»") == '"ciao"'
    assert normalise("l’offerta") == "l'offerta"
    assert normalise("A–B") == "A-B" and normalise("A—B") == "A-B"
    assert normalise("ﬁne") == "fine"            # NFKC ligature
    assert normalise("Prezzo") == "Prezzo"            # case is kept
    assert normalise(" soft­hyphen​ ") == "softhyphen"


def test_punctuation_spacing_does_not_make_a_difference():
    left = _doc("Il prezzo , fisso ( dodici mesi ) .")
    right = _doc("Il prezzo, fisso (dodici mesi).")
    assert compare_text(left, right).equal


def test_hyphen_is_joined_only_at_a_line_end_before_a_lowercase_word():
    joined = _doc("contratto di forni-", "tura valido")
    whole = _doc("contratto di fornitura valido")
    assert compare_text(joined, whole).equal
    same_line = _doc("contratto di forni- tura valido")
    assert not compare_text(same_line, whole).equal
    upper = _doc("contratto Acme-", "Servizi valido")
    assert not compare_text(upper, _doc("contratto AcmeServizi valido")).equal


def test_joined_hyphen_difference_keeps_both_original_boxes():
    left = _doc("contratto di forni-", "tura valido")
    right = _doc("contratto di consegna valido")
    (diff,) = compare_text(left, right).differences
    assert diff.kind == "changed"
    assert [w.text for w in diff.left] == ["forni-", "tura"]
    assert diff.left_text == "forni- tura"


def test_case_change_is_a_difference():
    assert not compare_text(_doc("Acme servizi"), _doc("Acme Servizi")).equal


def test_differences_are_numbered_in_order():
    left = _doc("uno due tre quattro cinque sei sette")
    right = _doc("uno DUE tre quattro sei sette otto")
    diffs = compare_text(left, right).differences
    assert [d.id for d in diffs] == [1, 2, 3]
    assert [d.kind for d in diffs] == ["changed", "removed", "added"]


def test_page_boundaries_are_ignored():
    one_page = _doc("alfa beta gamma delta")
    words = [Word("alfa", 0, 40, 800, 60, 810), Word("beta", 0, 70, 800, 90, 810),
             Word("gamma", 1, 40, 50, 60, 60), Word("delta", 1, 70, 50, 90, 60)]
    two_pages = DocText(words, [(595.0, 842.0), (595.0, 842.0)], True)
    assert compare_text(one_page, two_pages).equal


@pytest.mark.parametrize("hyphen", ["-", "\u2010", "\u00ad"])
def test_every_real_hyphen_joins_at_a_line_end(hyphen: str):
    assert compare_text(_doc(f"di forni{hyphen}", "tura valido"), _doc("di fornitura valido")).equal


@pytest.mark.parametrize("dash", ["\u2014", "\u2013"])
def test_a_dash_at_a_line_end_never_joins(dash: str):
    left = _doc(f"prezzo fisso{dash}", "variabile dopo")
    assert not compare_text(left, _doc("prezzo fissovariabile dopo")).equal
    assert compare_text(left, _doc(f"prezzo fisso{dash} variabile dopo")).equal
