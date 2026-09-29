"""The pipeline with zones (phase 2.5, spec §3.2, §3.5, §3.6; task A3).

Synthetic documents built with ``zonegen`` (no PDF written, no real text):
the body and the title flow across pages without header, footer and
shoulders; every other zone is compared page by page, and an identical
difference on N pages is ONE difference "uguale su N pagine".
"""
from __future__ import annotations

from qtrequestory.officina.compare.classify import counts
from qtrequestory.officina.compare.model import Comparison
from qtrequestory.officina.compare.pipeline import compare_docs
from tests.officina.zonegen import Page, build

_ALPHABET = "bcdfglmnprstvz"
_VOWELS = "aeiou"


def word(n: int) -> str:
    """A unique made-up word for ``n`` (letters only: the zone rules mask digits)."""
    out = ""
    while True:
        n, c = divmod(n, len(_ALPHABET))
        n, v = divmod(n, len(_VOWELS))
        out += _ALPHABET[c] + _VOWELS[v]
        if not n:
            return out + "r"
        n -= 1


def line(n: int, words: int = 9) -> str:
    return " ".join(word(n * 20 + k) for k in range(words))


FOOTER = "Offerta di Acme-Servizi S.p.A. società soggetta a direzione e coordinamento"


def page(lines: range, *, footer: str = FOOTER, number: str = "", edition: str = "",
         top: float = 90.0, extra: tuple = ()) -> Page:
    """A page with a header divider, body ``lines`` (one per 12 pt from
    ``top``), a footer divider with ``footer`` text below it, an optional page
    number at the bottom and an optional rotated edition in the left margin."""
    p = Page().divider(60.0)
    y = top
    for n in lines:
        p.text(60.0, y, line(n))
        y += 12.0
    p.divider(770.0)
    if footer:
        p.text(60.0, 780.0, footer, size=7.0)
    if number:
        p.text(280.0, 815.0, number, size=7.0)
    if edition:
        p.turned_text(18.0, 600.0, edition)
    for call in extra:
        call(p)
    return p


def _counting(result: Comparison) -> list:
    return [d for d in result.diffs if counts(d, "tollerante")]


def _brief(result: Comparison) -> list[tuple]:
    return [(d.op, d.klass, d.zone, d.left_text, d.right_text, d.detail) for d in result.diffs]


# ------------------------------------------------------------- brief tests ---

def test_reflow_across_a_footer_is_no_difference():
    target = build(page(range(0, 40), number="1 di 2"), page(range(40, 60), number="2 di 2"))
    moved = build(page(range(0, 45), number="1 di 2"), page(range(45, 60), number="2 di 2"))
    result = compare_docs(target, moved)
    assert result.diffs == (), _brief(result)


def test_edition_change_in_the_left_shoulder_is_one_zona_difference_on_two_pages():
    target = build(page(range(0, 20), edition="Ed. Aprile duemila"), page(range(20, 40), edition="Ed. Aprile duemila"))
    changed = build(page(range(0, 20), edition="Ed. Maggio duemila"), page(range(20, 40), edition="Ed. Maggio duemila"))
    result = compare_docs(target, changed)
    assert len(result.diffs) == 1, _brief(result)
    diff = result.diffs[0]
    assert (diff.op, diff.klass, diff.zone) == ("cambiato", "zona", "spalla_sx")
    assert "uguale su 2 pagine" in diff.detail
    assert (diff.left_text, diff.right_text) == ("Aprile", "Maggio")
    assert {w.page for w in diff.left} == {0, 1} and {w.page for w in diff.right} == {0, 1}
    assert counts(diff, "tollerante") and counts(diff, "solo_testo")


def test_brand_change_in_the_footer_text_is_one_difference():
    other = FOOTER.replace("Acme-Servizi", "Beta-Servizi")
    target = build(page(range(0, 20)), page(range(20, 40)))
    changed = build(page(range(0, 20), footer=other), page(range(20, 40), footer=other))
    result = compare_docs(target, changed)
    assert len(result.diffs) == 1, _brief(result)
    diff = result.diffs[0]
    assert (diff.klass, diff.zone, diff.left_text, diff.right_text) == ("zona", "footer", "Acme-Servizi",
                                                                        "Beta-Servizi")
    assert diff.detail == "uguale su 2 pagine"
    assert _counting(result) == [diff]


def test_brand_change_in_a_footer_on_one_page_only_is_one_difference_without_pages_detail():
    other = FOOTER.replace("Acme-Servizi", "Beta-Servizi")
    target = build(page(range(0, 20)), page(range(20, 40), footer=""))
    changed = build(page(range(0, 20), footer=other), page(range(20, 40), footer=""))
    result = compare_docs(target, changed)
    assert [(d.klass, d.zone, d.detail) for d in result.diffs] == [("zona", "footer", "")]


def test_a_watermark_change_is_ignored_by_default():
    def facsimile(text):
        return lambda p: p.turned_text(150.0, 600.0, text, angle=302, size=50.0, light=True)

    target = build(page(range(0, 20)), page(range(20, 40)))
    marked = build(page(range(0, 20), extra=(facsimile("CAMPIONE"),)),
                   page(range(20, 40), extra=(facsimile("CAMPIONE"),)))
    result = compare_docs(target, marked)
    assert result.diffs, "the watermark is still reported"
    assert {(d.klass, d.zone) for d in result.diffs} == {("arredo", "filigrana")}
    assert len(result.diffs) == 1 and "uguale su 2 pagine" in result.diffs[0].detail
    assert result.equal and not _counting(result)


# ------------------------------------------------------------- zones ---

def test_page_numbers_are_arredo_and_a_page_count_change_is_one_pagine():
    target = build(page(range(0, 20), number="1 di 2"), page(range(20, 30), number="2 di 2"))
    longer = build(page(range(0, 20), number="1 di 3"), page(range(20, 30), number="2 di 3"),
                   page(range(30, 32), number="3 di 3"))
    result = compare_docs(target, longer)
    kinds = {(d.op, d.klass, d.zone) for d in result.diffs}
    assert ("pagine", "composizione", "corpo") in kinds
    assert all(d.klass == "arredo" for d in result.diffs if d.zone == "numero_pagina")
    assert not [d for d in result.diffs if d.zone == "footer"], _brief(result)


def test_every_difference_has_its_zone_and_the_zone_boxes_are_filled():
    def title(text):
        return lambda p: p.text(150.0, 70.0, text, size=16.0)

    target = build(page(range(0, 20), extra=(title("CONDIZIONI OFFERTA SEMPLICE"),)), page(range(20, 40)))
    changed_lines = [*range(0, 5), 99, *range(6, 20)]
    changed = build(page(changed_lines, extra=(title("CONDIZIONI OFFERTA DOPPIA"),)), page(range(20, 40)))
    result = compare_docs(target, changed)
    zones = {(d.zone, d.left_text, d.right_text) for d in result.diffs}
    assert ("titolo", "SEMPLICE", "DOPPIA") in zones
    assert ("corpo", line(5), line(99)) in zones
    assert all(d.klass == "testo" for d in result.diffs)
    assert {z.zone for z in result.left_zones} >= {"header", "footer", "titolo"}
    assert {z.zone for z in result.right_zones} >= {"header", "footer", "titolo"}


def test_a_zone_can_be_set_aside_and_then_is_arredo():
    other = FOOTER.replace("Acme-Servizi", "Beta-Servizi")
    target = build(page(range(0, 20)))
    changed = build(page(range(0, 20), footer=other))
    result = compare_docs(target, changed, aside=frozenset({"footer"}))
    assert [(d.klass, d.zone) for d in result.diffs] == [("arredo", "footer")]
    shown = compare_docs(target, changed, aside=frozenset())
    assert [(d.klass, d.zone) for d in shown.diffs] == [("zona", "footer")]


def test_a_page_number_can_be_turned_back_on():
    target = build(page(range(0, 20), number="1 di 2"), page(range(20, 30), number="2 di 2"))
    other = build(page(range(0, 20), number="1 di 3"), page(range(20, 30), number="2 di 3"))
    result = compare_docs(target, other, aside=frozenset({"filigrana"}))
    assert {(d.klass, d.zone) for d in result.diffs} == {("zona", "numero_pagina")}


def test_a_style_change_in_a_zone_keeps_its_class():
    target = build(page(range(0, 20)))
    bold = build(page(range(0, 20), footer="", extra=(lambda p: p.text(60.0, 780.0, FOOTER, size=7.0, bold=True),)))
    result = compare_docs(target, bold)
    assert [(d.klass, d.zone) for d in result.diffs] == [("stile", "footer")]


def test_zone_text_on_one_side_only_is_a_zona_difference():
    target = build(page(range(0, 20), footer=""))
    changed = build(page(range(0, 20)))
    result = compare_docs(target, changed)
    assert [(d.op, d.klass, d.zone, d.tipo) for d in result.diffs] == [("in_piu", "zona", "footer", "zona")]


# -------------------------------------------------------- far-apart words ---

def test_a_difference_never_spans_two_pages():
    target = build(page(range(0, 40)), page(range(40, 60)))
    gone = build(page([*range(0, 39)]), page(range(41, 60)))
    result = compare_docs(target, gone)
    for diff in result.diffs:
        assert len({w.page for w in diff.left}) <= 1 and len({w.page for w in diff.right}) <= 1, _brief(result)
    assert sorted(d.left_text for d in result.diffs) == sorted([line(39), line(40)])


def gapped(first: list[int], second: list[int]) -> Page:
    """A page whose body is ``first`` from the top and ``second`` 150 pt
    lower: the last line of one and the first of the other are consecutive
    in reading order but far apart on the page."""
    def rest(p):
        for k, n in enumerate(second):
            p.text(60.0, 450.0 + 12.0 * k, line(n))
    return page(first, extra=(rest,))


def test_a_missing_run_over_a_blank_block_is_two_differences():
    target = build(gapped(list(range(0, 11)), list(range(11, 20))))
    gone = build(gapped(list(range(0, 10)), list(range(12, 20))))
    result = compare_docs(target, gone)
    assert [(d.op, d.left_text) for d in result.diffs] == [("mancante", line(10)), ("mancante", line(11))]


def test_a_change_split_at_a_far_gap_pairs_its_pieces():
    target = build(gapped(list(range(0, 11)), list(range(11, 20))))
    # the last line before the gap and the first after it both replaced: one replacement for the word diff
    changed = build(gapped([*range(0, 10), 90], [91, *range(12, 20)]))
    result = compare_docs(target, changed)
    assert [(d.op, d.left_text, d.right_text) for d in result.diffs] == [
        ("cambiato", line(10), line(90)), ("cambiato", line(11), line(91))]


# -------------------------------------------------------- baseline jitter ---

def test_a_glyph_drawn_a_little_higher_is_no_difference():
    target = build(page(range(0, 20)))
    jitter = build(page(range(0, 20)))
    k = next(i for i, w in enumerate(jitter.words) if w.text == word(5 * 20 + 3))
    w = jitter.words[k]
    from dataclasses import replace
    jitter.words[k] = replace(w, y0=w.y0 - 1.7, y1=w.y1 - 1.7)
    result = compare_docs(target, jitter)
    assert result.diffs == (), _brief(result)


def test_a_line_start_glyph_drawn_higher_stays_on_its_line():
    target = build(page(range(0, 20)))
    jitter = build(page(range(0, 20)))
    k = next(i for i, w in enumerate(jitter.words) if w.text == word(6 * 20))
    w = jitter.words[k]
    from dataclasses import replace
    jitter.words[k] = replace(w, y0=w.y0 - 2.5, y1=w.y1 - 2.5)
    result = compare_docs(target, jitter)
    assert result.diffs == (), _brief(result)


# ------------------------------------------------------ zones, more rules ---

def test_a_page_number_change_on_every_page_is_one_arredo_difference():
    target = build(page(range(0, 20), number="1 di 2"), page(range(20, 40), number="2 di 2"))
    other = build(page(range(0, 20), number="1 di 3"), page(range(20, 40), number="2 di 3"))
    result = compare_docs(target, other)
    assert [(d.klass, d.zone, d.left_text, d.right_text, d.detail, d.tipo) for d in result.diffs] == [
        ("arredo", "numero_pagina", "2", "3", "uguale su 2 pagine", "numeri")]


def test_a_longer_document_repeats_its_footer_difference_without_reporting_a_word_twice():
    other = FOOTER.replace("Acme-Servizi", "Beta-Servizi")
    target = build(page(range(0, 20)), page(range(20, 40)), page(range(40, 45)))
    shorter = build(page(range(0, 22), footer=other), page(range(22, 45), footer=other))
    result = compare_docs(target, shorter)
    footer = [d for d in result.diffs if d.zone == "footer"]
    assert [(d.left_text, d.right_text, d.detail) for d in footer] == [
        ("Acme-Servizi", "Beta-Servizi", "uguale su 3 pagine")]
    assert {w.page for w in footer[0].left} == {0, 1, 2} and {w.page for w in footer[0].right} == {0, 1}
    seen = [id(w) for d in result.diffs for w in d.right]
    assert len(seen) == len(set(seen)), "a generated word is reported twice"


def test_a_wingdings_box_in_a_shoulder_reads_like_the_mapped_one():
    def copies(box):
        # the rest of the line a fraction left of the box, as extracted rotated text is
        return lambda p: p.turned_text(570.0, 700.0, box, angle=270).turned_text(
            569.7, 700.0 - 0.5 * 6.0 - 0.3 * 6.0, "Copia per il Cliente", angle=270)

    target = build(page(range(0, 20), extra=(copies("❏"),)))
    unmapped = build(page(range(0, 20), extra=(copies("q"),)))
    assert compare_docs(target, unmapped).diffs == ()


def test_small_print_moved_to_the_next_page_is_one_move():
    def note(p):
        return p.text(60.0, 745.0, "nota uno testo della nota in corpo piccolo", size=6.0)

    target = build(page(range(0, 20), extra=(note,)), page(range(20, 40)))
    moved = build(page(range(0, 20)), page(range(20, 40), extra=(note,)))
    result = compare_docs(target, moved)
    assert [(d.op, d.klass, d.zone, d.tipo) for d in result.diffs] == [
        ("spostato", "composizione", "footer", "spostamento")]


def test_a_one_sided_difference_says_where_it_sits_on_the_empty_side():
    target = build(page(range(0, 20)))
    added = build(page([*range(0, 5), 99, *range(5, 20)]))
    [diff] = compare_docs(target, added).diffs
    assert diff.op == "in_piu" and diff.left == ()
    before = next(w for w in target.words if w.text == line(4).split()[-1])
    assert diff.empty_at == (before.page, before.x0, before.y0, before.x1, before.y1)
    changed = compare_docs(target, build(page(range(0, 20), footer=FOOTER + " aggiunta")))
    [zone] = changed.diffs
    assert zone.zone == "footer" and zone.empty_at is not None and zone.empty_at[0] == 0
    both = compare_docs(target, build(page(range(0, 20), footer=FOOTER.replace("Acme", "Beta"))))
    assert both.diffs[0].empty_at is None


def test_a_form_row_repeated_on_a_few_pages_stays_in_the_body():
    """A row with a fill-in leader on 2 of 5 pages, at the same height near
    the bottom: its filled copy on the other side differs, so it is body."""
    from qtrequestory.officina.compare.sides import prepare

    def row(p):
        return p.text(60.0, 740.0, "Firma del cliente ....................")

    pages = [page(range(20 * k, 20 * k + 20), extra=(row,) if k < 2 else ()) for k in range(5)]
    target = build(*pages)
    prepared = prepare(target, target)
    assert {w.zone for w in prepared.left.words if w.text == "Firma"} == {"corpo"}
    assert all(d.zone == "corpo" for d in compare_docs(target, target).diffs)


def test_a_form_row_on_every_page_near_the_bottom_is_footer_and_swallows_its_value():
    """Review A3 M5: page furniture with a leader («Firma ......» on every
    page, in the bottom band) is footer; its slot swallows the value."""
    from qtrequestory.officina.compare.sides import prepare

    def row(text):
        return lambda p: p.text(60.0, 745.0, text)

    target = build(*[page(range(20 * k, 20 * k + 20), extra=(row("Firma del cliente ...................."),))
                     for k in range(3)])
    filled = build(*[page(range(20 * k, 20 * k + 20), extra=(row("Firma del cliente Lorem Ipsum"),))
                     for k in range(3)])
    assert {w.zone for w in prepare(target, filled).left.words if w.text == "Firma"} == {"footer"}
    result = compare_docs(target, filled)
    assert {(d.klass, d.zone) for d in result.diffs} == {("variabile", "footer")}, _brief(result)


def test_a_body_line_shared_by_two_pages_of_a_long_document_is_not_furniture():
    """Review A3 I2: two of twelve pages happen to hold the same (digits
    aside) line at the same height near the bottom: it stays in the flow."""
    from qtrequestory.officina.compare.sides import prepare

    def amount(n):
        return lambda p: p.text(60.0, 750.0, f"importo dovuto lorem {n},00 ipsum")

    pages = [page(range(20 * k, 20 * k + 20), extra=(amount(k),) if k in (3, 7) else ()) for k in range(12)]
    target = build(*pages)
    assert {w.zone for w in prepare(target, target).left.words if w.text == "importo"} == {"corpo"}


def test_types_of_zone_and_body_differences():
    target = build(page(range(0, 20), edition="Ed. Aprile duemila"))
    other = build(page([*range(0, 3), 77, *range(4, 20)], edition="Ed. Maggio duemila",
                       footer=FOOTER.replace("S.p.A.", "S.p.A")))
    tipi = {(d.zone, d.tipo) for d in compare_docs(target, other).diffs}
    assert tipi == {("corpo", "frase"), ("spalla_sx", "parola"), ("footer", "punteggiatura")}


# ------------------------------------- review A3 I2 (ruling F13): rules in zones ---

def _presets(*names: str):
    from dataclasses import replace as _replace

    from qtrequestory.officina.compare.noise import PRESETS
    return [_replace(p, enabled=True) for p in PRESETS if p.name in names]


def test_a_noise_preset_silences_a_date_in_the_footer():
    target = build(page(range(0, 20), footer="Acme-Servizi documento del 01/02/2030 lorem"),
                   page(range(20, 40), footer="Acme-Servizi documento del 01/02/2030 lorem"))
    other = build(page(range(0, 20), footer="Acme-Servizi documento del 03/04/2031 lorem"),
                  page(range(20, 40), footer="Acme-Servizi documento del 03/04/2031 lorem"))
    result = compare_docs(target, other, rules=_presets("Data"))
    assert {(d.klass, d.zone) for d in result.diffs} == {("rumore", "footer")}, _brief(result)
    assert result.equal
    assert dict(result.noise_hits)["Data"] == 4, "two pages on each side"


def test_a_users_rule_matched_on_the_noise_sides_silences_zone_text():
    """R46: the guard's child matches the user's rule on ``noise_sides``;
    the spans it returns silence a code in the header and in the body alike."""
    import re

    from qtrequestory.officina.compare import noise
    from qtrequestory.officina.compare.pipeline import finish
    from qtrequestory.officina.compare.sides import prepare

    def head(code):
        return lambda p: p.text(60.0, 40.0, f"Acme-Servizi pratica {code} lorem ipsum", size=7.0)

    target = build(page(range(0, 20), extra=(head("ZZ111"),)))
    other = build(page([*range(0, 5), 99, *range(6, 20)], extra=(head("ZZ222"),)))
    prepared = prepare(target, other)
    pattern = re.compile(r"ZZ\d{3}", re.MULTILINE)
    (lk, le), (rk, re_) = prepared.noise_sides()
    hits = [("Codice pratica", noise.spans(lk, le, pattern), noise.spans(rk, re_, pattern))]
    result = finish(prepared, custom_hits=hits)
    kinds = {(d.klass, d.zone) for d in result.diffs}
    assert ("rumore", "header") in kinds and ("testo", "corpo") in kinds, _brief(result)
    assert not [d for d in result.diffs if d.klass == "zona"], _brief(result)
    assert dict(result.noise_hits)["Codice pratica"] == 2


def test_a_fill_in_slot_in_the_footer_swallows_the_value():
    def sign(text):
        return lambda p: p.text(60.0, 790.0, text, size=7.0)

    target = build(page(range(0, 20), extra=(sign("Firma del cliente ...................."),)))
    other = build(page(range(0, 20), extra=(sign("Firma del cliente Lorem Ipsum"),)))
    result = compare_docs(target, other)
    assert [(d.klass, d.zone) for d in result.diffs] == [("variabile", "footer")], _brief(result)
    [slot] = result.diffs
    off = compare_docs(target, other, disabled_slots={slot.anchor})
    assert {d.klass for d in off.diffs} == {"zona"}, "non è una variabile works in a zone too"


# ------------------------------------------ review A3 re-review I1: zone slot anchors ---

def _sign(text: str):
    return lambda p: p.text(60.0, 790.0, text, size=7.0)


def test_a_footer_slot_with_another_value_on_each_page_is_one_decision():
    """«Non è una variabile» on a footer slot applies to that slot on every
    page of the zone: ONE difference for all pages, and once switched off
    (the verdict's ``not_variables``) it counts on all of them."""
    from qtrequestory.officina.compare.verdict import judge
    from qtrequestory.officina.model_review import Review

    target = build(*[page(range(20 * k, 20 * k + 20), extra=(_sign("Firma del cliente ...................."),))
                     for k in range(3)])
    filled = build(*[page(range(20 * k, 20 * k + 20), extra=(_sign(f"Firma del cliente Lorem {name}"),))
                     for k, name in enumerate(("Alfa", "Beta", "Gamma"))])
    result = compare_docs(target, filled)
    slots = [d for d in result.diffs if d.klass == "variabile"]
    assert len(slots) == 1, _brief(result)
    assert {w.page for w in slots[0].right} == {0, 1, 2} and slots[0].zone == "footer"
    assert slots[0].anchor.context.startswith("footer: ")
    review = Review(not_variables=[(slots[0].anchor, "2030-01-01T00:00:00")])
    judged, *_ = judge(result, None, review, "tollerante", 1)
    [counted] = [j for j in judged if j.diff.anchor == slots[0].anchor]
    assert counted.diff.klass == "testo" and counted.verdict == "da_fare"
    assert {w.page for w in counted.diff.right} == {0, 1, 2}


def test_a_body_slot_and_a_footer_slot_with_the_same_context_are_independent():
    row = "Firma del cliente ...................."
    target = build(page(range(0, 20), extra=(_sign(row), lambda p: p.text(60.0, 400.0, row))))
    filled = build(page(range(0, 20), extra=(_sign("Firma del cliente Lorem Alfa"),
                                             lambda p: p.text(60.0, 400.0, "Firma del cliente Lorem Beta"))))
    result = compare_docs(target, filled)
    slots = [d for d in result.diffs if d.klass == "variabile"]
    assert sorted(d.zone for d in slots) == ["corpo", "footer"], _brief(result)
    assert len({d.anchor for d in slots}) == 2 and not any("#" in d.anchor.context for d in slots)
    body = next(d for d in slots if d.zone == "corpo")
    off = compare_docs(target, filled, disabled_slots={body.anchor})
    assert {(d.klass, d.zone) for d in off.diffs if d.klass == "variabile"} == {("variabile", "footer")}


def test_furniture_on_alternate_pages_of_an_odd_page_count_falls_to_the_body_and_still_counts():
    """Review A3 minor 3 (documented trade-off): a header without a divider
    or small print on 4 pages of 9 (under half) is read as body; its brand
    change is still reported, per page, and counts."""
    def bare(k: int, name: str) -> Page:
        p = Page()     # no divider, no logo, body-size print
        if k % 2:
            p.text(60.0, 40.0, f"{name} Servizi lorem ipsum dolor sit")
        for row, n in enumerate(range(20 * k, 20 * k + 20)):
            p.text(60.0, 90.0 + 12.0 * row, line(n))
        return p

    def doc(name):
        return build(*[bare(k, name) for k in range(9)])

    result = compare_docs(doc("Acme"), doc("Beta"))
    brand = [d for d in result.diffs if d.left_text == "Acme" and d.right_text == "Beta"]
    assert len(brand) == 4 and all(d.zone == "corpo" and counts(d, "tollerante") for d in brand), _brief(result)


# ----------------------------------------- a zone set aside hides no body ---

def _titled(text: str):
    return lambda p: p.text(150.0, 70.0, text, size=16.0)


def test_title_and_first_body_line_changed_together_the_body_part_still_counts_with_titolo_aside():
    target = build(page(range(0, 20), extra=(_titled("CONDIZIONI OFFERTA SEMPLICE"),)), page(range(20, 40)))
    changed = build(page([99, *range(1, 20)], extra=(_titled("CONDIZIONI OFFERTA DOPPIA"),)), page(range(20, 40)))
    for aside in (frozenset(), frozenset({"titolo"})):
        result = compare_docs(target, changed, aside=aside)
        body = [d for d in result.diffs if any(w.zone == "corpo" for w in (*d.left, *d.right))]
        assert body, _brief(result)
        assert all(d.klass != "arredo" and d.zone == "corpo" for d in body), _brief(result)
        assert all(w.zone == "corpo" for d in body for w in (*d.left, *d.right)), _brief(result)
        assert any(line(0).split()[0] in d.left_text for d in _counting(result)), _brief(result)
    result = compare_docs(target, changed, aside=frozenset({"titolo"}))
    assert [(d.klass, d.left_text, d.right_text) for d in result.diffs if d.zone == "titolo"] == \
        [("arredo", "SEMPLICE", "DOPPIA")]


def test_title_changed_and_first_body_line_missing_the_missing_line_still_counts_with_titolo_aside():
    target = build(page(range(0, 20), extra=(_titled("CONDIZIONI OFFERTA SEMPLICE"),)), page(range(20, 40)))
    changed = build(page(range(1, 20), extra=(_titled("CONDIZIONI OFFERTA DOPPIA"),)), page(range(20, 40)))
    result = compare_docs(target, changed, aside=frozenset({"titolo"}))
    counting = _counting(result)
    assert any(line(0) in d.left_text and d.zone == "corpo" for d in counting), _brief(result)
    assert all(w.zone == "titolo" for d in result.diffs if d.klass == "arredo" for w in (*d.left, *d.right))


def test_a_title_only_difference_is_set_aside_whole():
    target = build(page(range(0, 20), extra=(_titled("CONDIZIONI OFFERTA SEMPLICE"),)))
    changed = build(page(range(0, 20), extra=(_titled("CONDIZIONI OFFERTA DOPPIA"),)))
    result = compare_docs(target, changed, aside=frozenset({"titolo"}))
    assert [(d.klass, d.zone) for d in result.diffs] == [("arredo", "titolo")]


def test_a_single_title_word_replaced_by_a_single_body_word_is_split_by_zone():
    from qtrequestory.officina.compare.model import Word
    from qtrequestory.officina.compare.spread import split
    from qtrequestory.officina.compare.worddiff import Change

    title = Word("SEMPLICE", 0, 150.0, 70.0, 214.0, 88.4, 16.0, zone="titolo")
    body = Word("bar", 0, 60.0, 90.0, 72.0, 99.2, 8.0, zone="corpo")
    parts = split(Change("cambiato", 0, 1, 0, 1), ["semplice"], [(title,)], ["bar"], [(body,)])
    assert [p.op for p in parts] == ["mancante", "in_piu"]


def test_a_footer_set_aside_next_to_a_changed_last_body_line_hides_only_the_footer():
    other = FOOTER.replace("Acme-Servizi", "Beta-Servizi")
    target = build(page(range(0, 20)))
    changed = build(page([*range(0, 19), 99], footer=other))
    result = compare_docs(target, changed, aside=frozenset({"footer"}))
    assert ("corpo", line(19), line(99)) in {(d.zone, d.left_text, d.right_text) for d in _counting(result)}
    assert [(d.klass, d.zone) for d in result.diffs if d.klass == "arredo"] == [("arredo", "footer")]
