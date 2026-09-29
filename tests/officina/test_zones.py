"""The zone stage (spec §3.2, D4): one synthetic fixture per zone, mixed
pages, a page with no header, and the two sides deciding together.

Synthetic documents only (``zonegen``); no PDF is written: the stage is pure.
"""
from __future__ import annotations

from dataclasses import replace

from qtrequestory.officina.compare.model import Comparison, Word, ZoneBox
from qtrequestory.officina.compare.zones import zone_document, zone_pair
from tests.officina.zonegen import H, W, Page, build, zone_text, zones_of

LEGAL = "Acme-Servizi S.p.A. società soggetta a direzione e coordinamento di Acme Holding"


def _boxes(zoned, page: int) -> dict[str, ZoneBox]:
    return {b.zone: b for b in zoned.boxes if b.page == page}


# ------------------------------------------------------------ header ---

def test_text_header_above_a_divider_is_header():
    doc = build(Page().text(40, 18, "Acme-Servizi Lorem Offerta Casa", 9).divider(47).body(80, 700),
                Page().text(40, 18, "Acme-Servizi Lorem Offerta Casa", 9).divider(47).body(80, 700))
    zoned = zone_document(doc)
    assert zone_text(zoned.doc, "header", 0) == "Acme-Servizi Lorem Offerta Casa"
    assert zone_text(zoned.doc, "header", 1) == "Acme-Servizi Lorem Offerta Casa"
    assert {w.zone for w in zoned.doc.words if w.text.startswith("corpo")} == {"corpo"}
    header = _boxes(zoned, 0)["header"]
    assert header.y0 <= 18 and header.y1 >= 47 and header.x0 <= 28 and header.x1 >= 568  # divider included


def test_logo_only_header_gives_a_header_box_and_no_header_words():
    doc = build(Page().logo(31, 17, 132, 31, letters=6).body(60, 700))
    zoned = zone_document(doc)
    assert zone_text(zoned.doc, "header") == ""
    assert _boxes(zoned, 0)["header"] == ZoneBox(0, "header", 31, 17, 131, 31)
    assert all(w.zone == "corpo" for w in zoned.doc.words)


def test_text_beside_a_logo_is_header():
    doc = build(Page().logo(31, 17, 132, 45).text(400, 25, "Servizio Clienti 800 000 000").body(80, 700))
    zoned = zone_document(doc)
    assert zone_text(zoned.doc, "header") == "Servizio Clienti 800 000 000"


def test_short_big_text_header_without_graphics():
    """The AS-IS of a rebranded module: the brand is TEXT (17 pt), no logo, no divider."""
    doc = build(Page().text(40, 20, "Acmepay", 17).body(80, 700))
    assert zone_text(zone_document(doc).doc, "header") == "Acmepay"


def test_page_with_no_header():
    doc = build(Page().text(60, 30, "Spett.le Cliente via Roma 1 00100 Roma").body(50, 700),
                Page().text(60, 30, "Seconda pagina inizia subito col testo del corpo").body(50, 700))
    zoned = zone_document(doc)
    assert zone_text(zoned.doc, "header") == ""
    assert all(b.zone != "header" for b in zoned.boxes)


def test_repeated_text_header_without_graphics():
    doc = build(Page().text(60, 30, "Modulo di adesione pagina").body(60, 700),
                Page().text(60, 30, "Modulo di adesione pagina").body(60, 700))
    zoned = zone_document(doc)
    assert zone_text(zoned.doc, "header", 0) == "Modulo di adesione pagina"
    assert zone_text(zoned.doc, "header", 1) == "Modulo di adesione pagina"


def test_a_table_rule_below_the_header_band_is_not_a_divider():
    doc = build(Page().divider(47).divider(110).body(60, 700))
    zoned = zone_document(doc)
    assert zone_text(zoned.doc, "header") == ""


# ------------------------------------------------------------ footer ---

def _footer_page(n: int, total: int) -> Page:
    return (Page().divider(47).body(80, 760).divider(792).text(40, 800, LEGAL, 7)
            .text(520, 812, f"{n} di {total}", 8).logo(467, 820, 566, 832))


def test_footer_text_below_a_divider_is_footer_and_counts():
    zoned = zone_document(build(_footer_page(1, 2), _footer_page(2, 2)))
    for page in (0, 1):
        assert zone_text(zoned.doc, "footer", page) == LEGAL
        assert zone_text(zoned.doc, "numero_pagina", page) == f"{page + 1} di 2"
        box = _boxes(zoned, page)["footer"]
        assert box.y0 <= 792 and box.y1 >= 832
    assert zone_text(zoned.doc, "corpo").split()[-1].startswith("corpo")


def test_small_legal_footer_above_the_divider_on_page_one_only():
    """The legal line at 7 pt sits ABOVE the divider, on page 1 only."""
    first = Page().divider(47).body(80, 700).text(40, 770, LEGAL, 7).divider(792)
    second = Page().divider(47).body(80, 760).divider(792)
    zoned = zone_document(build(first, second))
    assert zone_text(zoned.doc, "footer", 0) == LEGAL
    assert zone_text(zoned.doc, "footer", 1) == ""


def test_repeated_footer_line_without_divider():
    doc = build(Page().body(60, 700).text(60, 790, "Acme-Servizi Documento riservato uso interno"),
                Page().body(60, 700).text(60, 790, "Acme-Servizi Documento riservato uso interno"))
    zoned = zone_document(doc)
    assert zone_text(zoned.doc, "footer", 1) == "Acme-Servizi Documento riservato uso interno"


def test_a_body_paragraph_near_the_bottom_stays_body():
    doc = build(Page().divider(47).body(80, 790))
    assert {w.zone for w in zone_document(doc).doc.words} == {"corpo"}


# ------------------------------------------------------------ shoulders ---

def test_left_shoulder_rotated_edition():
    pages = [Page().divider(47).body(80, 700).turned_text(13, 460, "Doc X - Ed. Gennaio 2027") for _ in range(2)]
    zoned = zone_document(build(*pages))
    assert zone_text(zoned.doc, "spalla_sx", 0) == "Doc X - Ed. Gennaio 2027"
    assert zone_text(zoned.doc, "spalla_sx", 1) == "Doc X - Ed. Gennaio 2027"
    box = _boxes(zoned, 1)["spalla_sx"]
    assert box.x1 < 60 and box.y1 == 460


def test_right_shoulder_either_angle():
    page = (Page().body(80, 700).turned_text(575, 700, "Copia per il Cliente", 270)
            .turned_text(560, 100, "Copia per Acme", 90))
    zoned = zone_document(build(page))
    assert zone_text(zoned.doc, "spalla_dx") == "Copia per il Cliente Copia per Acme"
    assert zone_text(zoned.doc, "spalla_sx") == ""


def test_rotated_text_inside_the_body_stays_body():
    page = Page().body(80, 700).turned_text(300, 400, "intestazione colonna", 270, 8)
    zoned = zone_document(build(page))
    assert zones_of(zoned.doc, "intestazione colonna") == ["corpo", "corpo"]


# ------------------------------------------------------------ title ---

def _titled() -> Page:
    return (Page().logo(31, 17, 132, 31).divider(47).text(200, 70, "ALLEGATO 2", 17)
            .text(80, 92, "CONDIZIONI TECNICO ECONOMICHE", 17).body(130, 700))


def test_title_on_page_one():
    zoned = zone_document(build(_titled(), _titled()))
    assert zone_text(zoned.doc, "titolo") == "ALLEGATO 2 CONDIZIONI TECNICO ECONOMICHE"
    assert zone_text(zoned.doc, "corpo", 1).startswith("ALLEGATO 2")  # page 2: not a title


def test_title_a_little_larger_than_the_body():
    zoned = zone_document(build(Page().divider(47).text(200, 70, "RICHIESTA DI ADESIONE", 10).body(90, 700)))
    assert zone_text(zoned.doc, "titolo") == "RICHIESTA DI ADESIONE"


# ------------------------------------------------------------ mixed ---

def test_mixed_page_every_zone():
    page = (Page().logo(31, 17, 132, 31, letters=6).text(400, 25, "Numero Verde 800 000 000").divider(47)
            .text(160, 60, "CONDIZIONI GENERALI DI FORNITURA", 17).body(90, 740)
            .divider(792).text(40, 800, LEGAL, 7).text(520, 815, "1 di 1")
            .turned_text(13, 460, "Mod. 12 - Ed. Marzo 2026").turned_text(575, 700, "Copia per il Cliente")
            .watermark_path(250, 400).turned_text(205, 560, "FACSIMILE", 302, 50, light=True))
    zoned = zone_document(build(page))
    doc = zoned.doc
    assert zone_text(doc, "header") == "Numero Verde 800 000 000"
    assert zone_text(doc, "titolo") == "CONDIZIONI GENERALI DI FORNITURA"
    assert zone_text(doc, "footer") == LEGAL
    assert zone_text(doc, "numero_pagina") == "1 di 1"
    assert zone_text(doc, "spalla_sx") == "Mod. 12 - Ed. Marzo 2026"
    assert zone_text(doc, "spalla_dx") == "Copia per il Cliente"
    assert zone_text(doc, "filigrana") == "FACSIMILE"
    assert all(w.text.startswith("corpo") for w in doc.words if w.zone == "corpo")
    assert [b.zone for b in zoned.boxes] == ["header", "titolo", "footer", "spalla_sx", "spalla_dx",
                                             "numero_pagina", "filigrana"]


def test_mixed_pages_with_and_without_zones():
    plain = Page().body(40, 800)
    zoned = zone_document(build(_footer_page(1, 3), plain, _footer_page(3, 3)))
    assert zone_text(zoned.doc, "footer", 1) == ""
    assert zone_text(zoned.doc, "footer", 2) == LEGAL
    assert {b.page for b in zoned.boxes} == {0, 2}


# ------------------------------------------------------------ both sides ---

def test_footer_limit_of_one_side_guides_the_other():
    """The generated side lost its divider: the target's band still applies."""
    target = build(Page().divider(47).body(80, 760).divider(792).text(40, 800, LEGAL, 8))
    generated = build(Page().divider(47).body(80, 760).text(40, 800, LEGAL.replace("Acme", "Beta"), 8))
    left, right = zone_pair(target, generated)
    assert zone_text(left.doc, "footer") == LEGAL
    assert zone_text(right.doc, "footer") == LEGAL.replace("Acme", "Beta")
    assert zone_text(zone_document(generated).doc, "footer") == ""  # alone it would not know


def test_footer_text_of_one_side_found_in_the_other_bottom_band():
    """The target's legal lines sit under its footer divider; the generated
    side has no divider, its logo lower (its own limit stays below the lines)
    and its block starts higher than the target's: its lines READ like the
    target's footer lines, so they are footer too."""
    lines = ["Acme-Servizi S.p.A. sede legale via Roma uno", "capitale sociale euro mille interamente versato",
             "iscritta al registro delle imprese di Roma"]
    target = Page().logo(31, 17, 132, 31).body(60, 640).divider(745).logo(31, 800, 132, 812)
    generated = Page().body(60, 640)
    for k, line in enumerate(lines):
        target.text(40, 752 + 11 * k, line, 8)
        generated.text(40, 735 + 11 * k, line.replace("Acme", "Beta"), 8)
    generated.logo(31, 800, 132, 812)
    left, right = zone_pair(build(target), build(generated))
    assert zone_text(left.doc, "footer") == " ".join(lines)
    assert zone_text(right.doc, "footer") == " ".join(lines).replace("Acme", "Beta")


def test_header_band_of_one_side_guides_the_other():
    target = build(Page().logo(31, 17, 132, 31).text(400, 22, "Numero Verde").divider(47).body(80, 700))
    generated = build(Page().text(400, 22, "Numero Verde").body(80, 700))
    _, right = zone_pair(target, generated)
    assert zone_text(right.doc, "header") == "Numero Verde"


def test_title_of_one_side_recognises_the_other():
    """The generated title is not larger than its body (filled offer name):
    it reads like the target's title."""
    target = build(Page().divider(47).text(100, 70, "CONDIZIONI ECONOMICHE OFFERTA [xx]", 17).body(100, 700))
    generated = build(Page().divider(47).text(100, 70, "CONDIZIONI ECONOMICHE OFFERTA Luce Facile", 8)
                      .body(100, 700))
    _, right = zone_pair(target, generated)
    assert zone_text(right.doc, "titolo") == "CONDIZIONI ECONOMICHE OFFERTA Luce Facile"


def test_spalle_on_both_sides():
    target = build(Page().body(80, 700).turned_text(13, 460, "Ed. Gennaio 2027"))
    generated = build(Page().body(80, 700).turned_text(13, 470, "Ed. Novembre 2019"))
    left, right = zone_pair(target, generated)
    assert zone_text(left.doc, "spalla_sx") == "Ed. Gennaio 2027"
    assert zone_text(right.doc, "spalla_sx") == "Ed. Novembre 2019"


# ------------------------------------------------------------ contract ---

def test_word_order_rotation_and_invisible_words_are_kept():
    hidden = [Word("00000", 0, 500, 830, 520, 838, 6)]
    doc = build(_footer_page(1, 1).turned_text(13, 460, "Ed. Aprile 2026"), invisible=hidden)
    zoned = zone_document(doc).doc
    assert [(w.text, w.page, w.x0, w.y0) for w in zoned.words] == [(w.text, w.page, w.x0, w.y0) for w in doc.words]
    assert zoned.rotated == doc.rotated and zoned.invisible == hidden
    assert zoned.page_sizes == doc.page_sizes and zoned.graphics == doc.graphics
    assert all(zoned.angle(i) == 270 for i, w in enumerate(zoned.words) if w.zone == "spalla_sx")
    assert [replace(w, zone="corpo") for w in zoned.words] == doc.words


def test_deterministic():
    make = lambda: build(_titled(), _footer_page(2, 2).watermark_path(100, 300)  # noqa: E731
                         .turned_text(13, 460, "Ed. Aprile 2026"))
    assert zone_pair(make(), make()) == zone_pair(make(), make())


def test_empty_and_textless_documents():
    empty = build()
    left, right = zone_pair(empty, empty)
    assert left.boxes == () and right.doc.words == []
    assert zone_document(build(Page().logo(31, 17, 132, 31))).boxes[0].zone == "header"


def test_comparison_zone_boxes_default_to_empty():
    cmp = Comparison((), True, True, 1, 1, "", 0, ())
    assert cmp.left_zones == () and cmp.right_zones == ()
    assert (W, H) == (595.0, 842.0)


# ------------------------------------------------------------ refinements (real corpus) ---

def test_small_company_line_under_the_header_divider_is_header():
    """D4: «Offerta di … S.p.A. – società soggetta a …» in small print right
    under the header divider, set apart from the title."""
    line = "Offerta di Acme-Servizi S.p.A. società soggetta a direzione e coordinamento di Acme Holding"
    page = (Page().logo(31, 17, 132, 31).divider(47).text(31, 58, line, 7)
            .text(200, 80, "ALLEGATO 2", 17).body(120, 700))
    zoned = zone_document(build(page)).doc
    assert zone_text(zoned, "header") == line
    assert zone_text(zoned, "titolo") == "ALLEGATO 2"


def test_small_diagonal_chart_labels_stay_body():
    page = Page().divider(47).body(80, 500)
    for k, month in enumerate("gennaio febbraio marzo aprile".split()):
        page.turned_text(230 + 28 * k, 580, month, 315, 4.6)
    zoned = zone_document(build(page))
    assert zones_of(zoned.doc, "gennaio febbraio marzo aprile") == ["corpo"] * 4
    assert all(b.zone != "filigrana" for b in zoned.boxes)


def test_title_after_an_address_block_and_its_subtitle():
    """A 10 pt address block (1.25×) comes first and is set apart: the title
    is the 17 pt run, with the tight line under it but not the heading after a gap."""
    page = (Page().divider(38).text(357, 58, "Spett.le", 10).text(357, 69, "Acme-Servizi S.p.A.", 10)
            .text(357, 80, "Viale Esempio 1", 10).text(150, 120, "RICHIESTA DI ADESIONE", 17)
            .text(240, 140, "QUADRO NOTIZIE", 11).text(31, 175, "DATI DEL RICHIEDENTE", 10).body(200, 700))
    zoned = zone_document(build(page)).doc
    assert zone_text(zoned, "titolo") == "RICHIESTA DI ADESIONE QUADRO NOTIZIE"
    assert zones_of(zoned, "Spett.le") == ["corpo"]


def test_a_large_word_in_the_body_is_not_the_title():
    page = (Page().divider(47).text(147, 50, "MANDATO DI ADDEBITO", 17).text(31, 68, "Riferimento mandato")
            .text(362, 76, "Acmepay", 23).body(110, 700))
    assert zone_text(zone_document(build(page)).doc, "titolo") == "MANDATO DI ADDEBITO"


def test_small_legal_line_right_above_the_footer_divider():
    """7 pt line two sizes below the last body line, just above the divider."""
    page = Page().divider(47).body(80, 752).text(31, 767, LEGAL, 7).divider(783)
    zoned = zone_document(build(page)).doc
    assert zone_text(zoned, "footer") == LEGAL


def test_bottom_block_where_the_other_side_has_its_footer_text():
    """The generated legal block is printed as large as its body: it is
    footer because the target's footer text starts in the same band."""
    target = Page().body(60, 600).text(46, 745, "Acme-Servizi S.p.A. Patrimonio Destinato Codice Fiscale", 7.5)
    target.text(46, 754, "Sede Legale Viale Esempio 1 Roma", 7.5).logo(31, 805, 130, 818)
    generated = Page().body(60, 600).text(31, 752, "Betapay S.p.A. Patrimonio Separato Registro Imprese", 8)
    generated.text(31, 761, "Capitale Sociale mille euro", 8).logo(31, 805, 130, 818)
    left, right = zone_pair(build(target), build(generated))
    assert zone_text(left.doc, "footer").startswith("Acme-Servizi")
    assert zone_text(right.doc, "footer") == ("Betapay S.p.A. Patrimonio Separato Registro Imprese "
                                              "Capitale Sociale mille euro")


def test_a_form_line_quoting_the_company_is_not_footer():
    """«PER RICEVUTA DA PARTE DI <company>» reads a little like the other
    side's footer «<company> - Patrimonio …» (Jaccard 0.58): not enough."""
    footer = "Acme Servizi S.p.A. - Patrimonio Destinato"
    receipt = "PER RICEVUTA DA PARTE DI ACME SERVIZI S.P.A. - PATRIMONIO DESTINATO"
    target = Page().divider(47).body(80, 700).text(31, 752, receipt, 10).divider(796).text(31, 822, footer, 6)
    generated = Page().divider(47).body(80, 700).text(31, 752, receipt, 10).text(31, 822, footer, 6)
    left, right = zone_pair(build(target), build(generated))
    assert zones_of(right.doc, receipt)[:3] == ["corpo"] * 3
    assert zone_text(left.doc, "footer") == footer
