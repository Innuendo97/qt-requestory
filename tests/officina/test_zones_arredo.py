"""The zones set aside by default (D4: ``numero_pagina`` and ``filigrana``
are not counted): page numbers and text/path watermarks. A false positive
here HIDES a difference, so these tests are mostly negatives (review A2 C1,
I1): edition and revision codes, instalments, large body text stay counted.

Synthetic documents only (``zonegen``).
"""
from __future__ import annotations

from qtrequestory.officina.compare.model import ZoneBox
from qtrequestory.officina.compare.zones import zone_document, zone_pair
from tests.officina.zonegen import Page, build, zone_text, zones_of


def _boxes(zoned, page: int) -> dict[str, ZoneBox]:
    return {b.zone: b for b in zoned.boxes if b.page == page}


# ------------------------------------------------------------ page numbers ---

def _numbered(text: str, y: float = 812) -> Page:
    return Page().divider(47).body(80, 760).divider(792).text(450, y, text)


def _numbers(zoned) -> str:
    return zone_text(zoned.doc, "numero_pagina")


def test_page_number_variants():
    for pattern in ("{n} di {m}", "Pag. {n} di {m}", "Pagina {n}/{m}", "{n}/{m}"):
        pages = [_numbered(pattern.format(n=n, m=3)) for n in (1, 2, 3)]
        zoned = zone_document(build(*pages))
        for n in (1, 2, 3):
            assert zone_text(zoned.doc, "numero_pagina", n - 1) == pattern.format(n=n, m=3), pattern


def test_page_number_set_apart_at_the_end_of_a_footer_line():
    """«…Patrimonio Destinato      1 di 2»: a right-aligned tail, a gap before it."""
    pages = [Page().body(60, 700).divider(792).text(40, 812, "Acme-Servizi Patrimonio Destinato")
             .text(520, 812, f"{n} di 2") for n in (1, 2)]
    zoned = zone_document(build(*pages))
    assert _numbers(zoned) == "1 di 2 2 di 2"
    assert zone_text(zoned.doc, "footer") == "Acme-Servizi Patrimonio Destinato Acme-Servizi Patrimonio Destinato"


def test_a_tail_glued_to_the_footer_text_is_not_a_page_number():
    pages = [_numbered(f"Acme-Servizi Patrimonio Destinato {n} di 2") for n in (1, 2)]
    assert _numbers(zone_document(build(*pages))) == ""


def test_single_page_needs_the_whole_line_form():
    assert _numbers(zone_document(build(_numbered("7 di 7")))) == "7 di 7"  # an extract of a longer document
    assert _numbers(zone_document(build(Page().body(60, 700).divider(792).text(40, 812, "Acme-Servizi")
                                        .text(520, 812, "1 di 3")))) == ""


def test_number_alone_follows_the_page_sequence():
    zoned = zone_document(build(*[Page().body(60, 700).text(290, 815, str(n)) for n in (1, 2)]))
    assert _numbers(zoned) == "1 2"
    assert _numbers(zone_document(build(Page().body(60, 700).text(290, 815, "100")))) == ""
    assert _numbers(zone_document(build(Page().body(60, 700).text(290, 815, "1")))) == ""  # lone, one page


def test_not_page_numbers():
    zoned = zone_document(build(_numbered("Ed. 12/2025").text(60, 300, "vedi art. 2 di 3")))
    assert _numbers(zoned) == ""
    assert _numbers(zone_document(build(_numbered("Allegato 3 di 2")))) == ""


def test_edition_revision_and_version_in_a_footer_stay_counted():
    for text in ("Mod. ABC Ed. 04/26", "Mod. ABC Rev. 1/2", "Mod. ABC versione 2 di 3"):
        zoned = zone_document(build(*[_numbered(text) for _ in range(3)]))
        assert _numbers(zoned) == "", text
        assert zone_text(zoned.doc, "footer", 0) == text


def test_numbers_that_do_not_follow_the_pages_stay_counted():
    """Whole-line «2 di 3» on every page: n does not move with the page."""
    assert _numbers(zone_document(build(*[_numbered("2 di 3") for _ in range(3)]))) == ""


def test_an_instalment_on_the_last_body_line_stays_counted():
    for pages in (1, 2):
        doc = build(*[Page().body(60, 760).text(60, 790, "importo pagato in rata 1 di 12") for _ in range(pages)])
        assert _numbers(zone_document(doc)) == ""


# ------------------------------------------------------------ watermark ---

def test_diagonal_text_watermark_repeated_on_the_pages():
    pages = [Page().divider(47).body(80, 700).turned_text(205, 560, "FACSIMILE", 302, 50) for _ in range(2)]
    zoned = zone_document(build(*pages))
    assert zone_text(zoned.doc, "filigrana") == "FACSIMILE FACSIMILE"
    assert "filigrana" in _boxes(zoned, 0)


def test_single_page_text_watermark_needs_a_light_colour():
    light = Page().divider(47).body(80, 700).turned_text(205, 560, "FACSIMILE", 302, 50, light=True)
    assert zone_text(zone_document(build(light)).doc, "filigrana") == "FACSIMILE"
    dark = Page().divider(47).body(80, 700).turned_text(205, 560, "FACSIMILE", 302, 50)
    assert zones_of(zone_document(build(dark)).doc, "FACSIMILE") == ["corpo"]


def test_light_text_on_a_dark_band_is_not_a_watermark():
    """White heading on a coloured band: light, but it is printed content."""
    page = (Page().divider(47).body(80, 300).rect(40, 390, 555, 470, fill=(0, 60, 140, 255))
            .text(150, 400, "OFFERTA", 60, light=True).body(500, 700))
    assert zones_of(zone_document(build(page)).doc, "OFFERTA") == ["corpo"]


def test_huge_horizontal_text_watermark_in_the_middle():
    """Horizontal (or vertical) large text is a watermark only when light;
    repetition alone is enough only for DIAGONAL text (review A2 R1)."""
    light = [Page().divider(47).body(80, 700).text(150, 400, "FACSIMILE", 60, light=True) for _ in range(2)]
    assert zone_text(zone_document(build(*light)).doc, "filigrana") == "FACSIMILE FACSIMILE"
    dark = [Page().divider(47).body(80, 700).text(150, 400, "FACSIMILE", 60) for _ in range(2)]
    assert zones_of(zone_document(build(*dark)).doc, "FACSIMILE") == ["corpo", "corpo"]
    vertical = [Page().divider(47).body(80, 500).turned_text(300, 700, "SCONTO", 270, 26) for _ in range(2)]
    assert zones_of(zone_document(build(*vertical)).doc, "SCONTO") == ["corpo", "corpo"]


def test_large_body_text_stays_counted():
    """A 30 pt price mid-page, a 26 pt vertical label, a 16 pt diagonal chart label."""
    page = (Page().divider(47).body(80, 300).text(200, 400, "0,12 €/kWh", 30)
            .turned_text(300, 600, "SCONTO", 270, 26).turned_text(400, 650, "gennaio-26", 315, 16).body(500, 520))
    zoned = zone_document(build(page)).doc
    assert zones_of(zoned, "0,12 €/kWh SCONTO gennaio-26") == ["corpo"] * 4
    two = zone_document(build(page, Page().divider(47).body(80, 700).text(200, 420, "0,15 €/kWh", 30))).doc
    assert zones_of(two, "0,12 0,15 €/kWh") == ["corpo"] * 4  # a different price on page 2


def test_path_watermark_gives_a_box_and_takes_no_words():
    page = Page().divider(47).body(80, 700).watermark_path(174, 300)
    zoned = zone_document(build(page))
    assert _boxes(zoned, 0)["filigrana"] == ZoneBox(0, "filigrana", 174, 300, 253, 357)
    assert {w.zone for w in zoned.doc.words} == {"corpo"}


def test_light_background_rectangle_is_not_a_watermark():
    zoned = zone_document(build(Page().divider(47).rect(31, 73, 564, 780).body(80, 700)))
    assert all(b.zone != "filigrana" for b in zoned.boxes)


def test_single_page_bare_fraction_is_not_a_page_number():
    """M6: «04/26» or «1/2» alone on a one-page footer line is an edition or a
    revision, not a page number (only «n di m» whole lines count alone)."""
    for text in ("04/26", "1/2"):
        page = Page().divider(47).body(80, 760).divider(792).text(450, 812, text)
        assert zone_text(zone_document(build(page)).doc, "numero_pagina") == "", text


# ------------------------------------------------------------ watermark on both sides (R1) ---

def _slot(text: str, pages: int = 2, *, light: bool = False, size: float = 30) -> list[Page]:
    return [Page().divider(47).body(80, 300).text(200, 400, text, size, light=light).body(500, 700)
            for _ in range(pages)]


def _both(target: list[Page], generated: list[Page], text: str) -> tuple[list[str], list[str]]:
    left, right = zone_pair(build(*target), build(*generated))
    return zones_of(left.doc, text), zones_of(right.doc, text)


def test_same_slot_with_different_text_is_compared_on_both_sides():
    """A price or heading repeated (or light) on each side, different between
    the sides: neither is a watermark, the change is counted."""
    cases = [(_slot("0,12 €/kWh", light=True), _slot("0,15 €/kWh", light=True), "0,12 0,15 €/kWh"),
             (_slot("0,12 €/kWh"), _slot("0,15 €/kWh"), "0,12 0,15 €/kWh"),
             (_slot("OFFERTA LUCE", light=True), _slot("OFFERTA GAS", light=True), "OFFERTA LUCE GAS"),
             (_slot("0,20 €/kWh", 1, light=True), _slot("0,25 €/kWh", 1, light=True), "0,20 0,25 €/kWh")]
    for target, generated, text in cases:
        left, right = _both(target, generated, text)
        assert set(left) == {"corpo"} and set(right) == {"corpo"}, text


def test_diagonal_vertical_label_repeated_different_between_sides():
    target = [Page().divider(47).body(80, 700).turned_text(205, 560, "BOZZA", 302, 50) for _ in range(2)]
    generated = [Page().divider(47).body(80, 700).turned_text(205, 560, "ANNULLATO", 302, 50) for _ in range(2)]
    left, right = _both(target, generated, "BOZZA ANNULLATO")
    assert set(left) == {"corpo"} and set(right) == {"corpo"}


def test_same_watermark_on_both_sides_stays_a_watermark():
    make = lambda: [Page().divider(47).body(80, 700).turned_text(205, 560, "FAC-SIMILE", 302, 50)  # noqa: E731
                    .watermark_path(100, 300) for _ in range(3)]
    left, right = zone_pair(build(*make()), build(*make()))
    assert zone_text(left.doc, "filigrana") == zone_text(right.doc, "filigrana") == "FAC-SIMILE FAC-SIMILE FAC-SIMILE"
    assert sum(b.zone == "filigrana" for b in right.boxes) == 3


def test_watermark_on_one_side_only_stays_a_watermark():
    target = [Page().divider(47).body(80, 700).turned_text(205, 560, "FAC-SIMILE", 302, 50, light=True)]
    left, right = zone_pair(build(*target), build(Page().divider(47).body(80, 700)))
    assert zone_text(left.doc, "filigrana") == "FAC-SIMILE"
    assert zone_text(right.doc, "filigrana") == ""


def test_a_changed_text_of_another_length_is_the_same_slot():
    """Re-review 2: a longer text moves the centre, not the slot (overlapping
    boxes or the same top-left corner)."""
    left, right = _both(_slot("OFFERTA LUCE", 1, light=True), _slot("OFFERTA LUCE E GAS CASA", 1, light=True),
                        "OFFERTA LUCE E GAS CASA")
    assert set(left) == {"corpo"} and set(right) == {"corpo"}
    target = [Page().divider(47).body(80, 700).turned_text(205, 560, "BOZZA", 302, 50) for _ in range(2)]
    generated = [Page().divider(47).body(80, 700).turned_text(260, 560, "ANNULLATO", 302, 50) for _ in range(2)]
    left, right = _both(target, generated, "BOZZA ANNULLATO")
    assert set(left) == {"corpo"} and set(right) == {"corpo"}
