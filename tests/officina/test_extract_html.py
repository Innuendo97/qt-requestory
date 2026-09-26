"""qtrequestory.officina.compare.extract_html and .urls: HTML through its DOM (spec §6).

Synthetic HTML only (example.invalid, Acme-Servizi).
"""
from __future__ import annotations

import pytest

from qtrequestory.officina.compare import urls
from qtrequestory.officina.compare.extract_html import attr_diffs, extract_html, locate
from qtrequestory.officina.compare.model import Block
from qtrequestory.officina.compare.normalise import units


def _blocks(html: str) -> list[Block]:
    return extract_html(html.encode("utf-8"))[0]


def _texts(blocks: list[Block]) -> list[str]:
    return [" ".join(w.text for w in b.words) for b in blocks]


def _identity(left: list[Block], right: list[Block]) -> list[tuple[int, int]]:
    return [(i, i) for i in range(min(len(left), len(right)))]


def _keep(_key: str) -> bool:
    return False


# ------------------------------------------------------------ blocks ---

NESTED = """<!doctype html><html><head><title>Titolo nascosto</title>
<style>td { color: red }</style><script>var x = "script";</script></head>
<body>
<table><tr><td>Uno</td></tr></table>
<table>
  <tr><td>Intestazione Acme-Servizi</td></tr>
  <tr><td>Prima
      <table><tr><td>Interna A</td><td>Interna B</td></tr></table>
      Dopo</td></tr>
  <tr><td><p>Paragrafo uno</p><p>Paragrafo due</p></td><td>Colonna destra</td></tr>
</table>
<ul><li>Voce uno<li>Voce due</ul>
<h2>Titolo</h2>
</body></html>"""


def test_nested_layout_tables_give_blocks_in_reading_order():
    blocks = _blocks(NESTED)
    assert _texts(blocks) == [
        "Uno", "Intestazione Acme-Servizi", "Prima", "Interna A", "Interna B", "Dopo",
        "Paragrafo uno", "Paragrafo due", "Colonna destra", "Voce uno", "Voce due", "Titolo",
    ]


def test_blocks_are_html_with_page_zero_and_zero_boxes():
    blocks = _blocks(NESTED)
    assert [b.id for b in blocks] == list(range(len(blocks)))
    assert {b.kind for b in blocks} == {"html"}
    assert {b.page for b in blocks} == {0}
    for word in (w for b in blocks for w in b.words):
        assert (word.page, word.x0, word.y0, word.x1, word.y1) == (0, 0.0, 0.0, 0.0, 0.0)


def test_dom_path_counts_same_tag_siblings():
    by_text = dict(zip(_texts(_blocks(NESTED)), (b.dom_path for b in _blocks(NESTED)), strict=True))
    assert by_text["Uno"] == "table[1]/tr[1]/td[1]"
    assert by_text["Intestazione Acme-Servizi"] == "table[2]/tr[1]/td[1]"
    assert by_text["Interna B"] == "table[2]/tr[2]/td[1]/table[1]/tr[1]/td[2]"
    assert by_text["Paragrafo due"] == "table[2]/tr[3]/td[1]/p[2]"
    assert by_text["Colonna destra"] == "table[2]/tr[3]/td[2]"
    assert by_text["Voce due"] == "ul[1]/li[2]"
    assert by_text["Titolo"] == "h2[1]"


def test_head_script_style_never_reach_the_blocks():
    text = " ".join(_texts(_blocks(NESTED)))
    assert "nascosto" not in text and "script" not in text and "color" not in text


def test_unclosed_head_ends_at_the_first_body_content():
    html = "<html><head><meta charset='utf-8'><title>T</title><p>Corpo</p>testo libero"
    assert _texts(_blocks(html)) == ["Corpo", "testo libero"]


def test_mso_conditional_comment_content_is_ignored():
    html = """<body><p>Visibile</p>
    <!--[if mso]><table><tr><td>Solo Outlook</td></tr></table><![endif]-->
    <!-- un commento qualsiasi -->
    <!--[if !mso]><!--><p>Per tutti</p><!--<![endif]-->
    </body>"""
    assert _texts(_blocks(html)) == ["Visibile", "Per tutti"]


def test_display_none_span_is_ignored():
    html = """<body><p>Prezzo <span style="font-size:1px; DISPLAY : none">nascosto</span>finale</p>
    <div hidden>Anche questo</div><p style="display:none">E questo <b>pure</b></p><p>Fine</p></body>"""
    assert _texts(_blocks(html)) == ["Prezzo finale", "Fine"]


def test_inline_tags_do_not_split_words_block_tags_do():
    html = "<body><p><b>Forni</b>tura<br>luce</p><td><div>Riga uno</div><div>Riga due</div></td></body>"
    assert _texts(_blocks(html)) == ["Fornitura luce", "Riga uno Riga due"]


def test_top_level_div_and_span_with_direct_text_are_blocks():
    html = "<body><div>Testo del div<div>Figlio</div></div><span>Testo dello span</span></body>"
    assert _texts(_blocks(html)) == ["Testo del div", "Figlio", "Testo dello span"]


def test_entities_and_encoding_are_decoded():
    html = "<html><head><meta charset='windows-1252'></head><body><p>Qualit\xe0 &amp; costo&nbsp;&euro;</p></body></html>"
    blocks = extract_html(html.encode("cp1252"))[0]
    assert _texts(blocks) == ["Qualità & costo €"]


def test_html_words_go_through_normalise_units_unchanged():
    blocks = _blocks("<body><p>A b c d prezzo , forni- tura [ x ] fine</p></body>")
    keys, _ = units(list(blocks[0].words))
    # zero boxes: no comb field and no line end (so no dehyphenation); punctuation and boxes still apply
    assert keys == ["A", "b", "c", "d", "prezzo,", "forni-", "tura", "☒", "fine"]


def test_pretty_source_is_indented_and_readable():
    _, pretty = extract_html(b"<html><body><table><tr><td>Uno</td></tr></table></body></html>")
    lines = pretty.splitlines()
    assert "<table>" in [line.strip() for line in lines]
    td = next(line for line in lines if line.strip() == "<td>")
    assert td.startswith(" ")
    assert any(line.strip() == "Uno" for line in lines)


def test_garbage_never_raises():
    blocks, _ = extract_html(b"\xff\xfe<<<p>>></td></tr><li>x</b></table><p")
    assert isinstance(blocks, list)


# ------------------------------------------------------------ attrs ---

def test_critical_attributes_are_collected_normalised():
    html = """<body><p>Vai <a href="HTTPS://Www.Example.INVALID/Pagina?b=2&a=1">qui</a>
    <a href="mailto:Info@example.invalid">scrivi</a> <a href="tel:+390000">chiama</a>
    <img src="https://example.invalid/logo.png" alt="Logo Acme-Servizi"></p></body>"""
    (block,) = _blocks(html)
    assert block.attrs == (
        ("href", "https://www.example.invalid/Pagina?a=1&b=2"),
        ("href", "mailto:Info@example.invalid"),
        ("href", "tel:+390000"),
        ("src", "https://example.invalid/logo.png"),
        ("alt", "Logo Acme-Servizi"),
    )


def test_image_only_cell_is_a_block_without_words():
    (block,) = _blocks('<body><table><tr><td><a href="https://example.invalid/x"><img src="a.png" alt=""></a>'
                       "</td></tr></table></body>")
    assert block.words == ()
    assert block.attrs == (("href", "https://example.invalid/x"), ("src", "a.png"), ("alt", ""))


def test_href_change_gives_a_link_detail():
    left = _blocks('<body><p><a href="https://example.invalid/a">Link</a></p></body>')
    right = _blocks('<body><p><a href="https://example.invalid/b">Link</a></p></body>')
    assert attr_diffs(left, right, _identity(left, right), _keep) == [
        (0, 0, "href: https://example.invalid/a → https://example.invalid/b")]


def test_utm_only_change_is_dropped_by_the_tracking_rule_only():
    left = _blocks('<body><p><a href="https://example.invalid/p?id=7&utm_source=mail">Link</a></p></body>')
    right = _blocks('<body><p><a href="https://example.invalid/p?utm_source=web&id=7">Link</a></p></body>')
    pairs = _identity(left, right)
    assert attr_diffs(left, right, pairs, urls.tracking_drop) == []
    assert attr_diffs(left, right, pairs, _keep) == [
        (0, 0, "href: https://example.invalid/p?id=7&utm_source=mail → https://example.invalid/p?id=7&utm_source=web")]


def test_src_change_with_same_alt_is_a_link_detail():
    left = _blocks('<body><p>Logo <img src="https://example.invalid/v1.png" alt="Logo"></p></body>')
    right = _blocks('<body><p>Logo <img src="https://example.invalid/v2.png" alt="Logo"></p></body>')
    assert attr_diffs(left, right, _identity(left, right), _keep) == [
        (0, 0, "src: https://example.invalid/v1.png → https://example.invalid/v2.png")]


def test_added_and_removed_links_name_the_missing_side():
    left = _blocks('<body><p><a href="https://example.invalid/a">A</a> e B</p><p>C</p></body>')
    right = _blocks('<body><p>A e <a href="https://example.invalid/b">B</a></p>'
                    '<p><a href="https://example.invalid/a">C</a> <a href="https://example.invalid/c">D</a></p>'
                    '</body>')
    assert attr_diffs(left, right, [(0, 0), (1, 1)], _keep) == [
        (0, 0, "href: https://example.invalid/a → https://example.invalid/b"),
        (1, 1, "href: (assente) → https://example.invalid/a"),
        (1, 1, "href: (assente) → https://example.invalid/c"),
    ]


def test_equal_attrs_and_unpaired_blocks_give_nothing():
    left = _blocks('<body><p><a href="https://EXAMPLE.invalid/a">A</a></p><p>solo sinistra</p></body>')
    right = _blocks('<body><p><a href="https://example.invalid/a">A</a></p></body>')
    assert attr_diffs(left, right, [(0, 0)], _keep) == []


# ------------------------------------------------------------ urls ---

@pytest.mark.parametrize(("url", "expected"), [
    ("HTTPS://WWW.Example.Invalid/Path/X?Z=1&a=2#Frag", "https://www.example.invalid/Path/X?Z=1&a=2#Frag"),
    ("  https://example.invalid/p?b=2&a=1&a=0  ", "https://example.invalid/p?a=0&a=1&b=2"),
    ("https://example.invalid/p?utm_source=x", "https://example.invalid/p?utm_source=x"),
    ("MAILTO:Info@Example.invalid", "mailto:Info@Example.invalid"),
    ("Tel:+39 000", "tel:+39 000"),
    ("immagini/logo.png", "immagini/logo.png"),
    ("", ""),
])
def test_normalise_keeping_every_key(url, expected):
    assert urls.normalise(url, _keep) == expected


def test_normalise_with_the_tracking_rule():
    url = ("https://example.invalid/p?id=7&UTM_Medium=m&gclid=1&fbclid=2&msclkid=3&mkt_tok=4&mc_cid=5"
           "&mc_eid=6&_hsenc=7&_hsmktg=8&utm_campaign=c")
    assert urls.normalise(url, urls.tracking_drop) == "https://example.invalid/p?id=7"
    assert urls.normalise("https://example.invalid/p?utm_source=x", urls.tracking_drop) == "https://example.invalid/p"


def test_tracking_keys_and_predicate():
    assert "utm_*" in urls.TRACKING_KEYS
    for key in ("gclid", "fbclid", "msclkid", "mkt_tok", "mc_cid", "mc_eid", "_hsenc", "_hsmktg"):
        assert key in urls.TRACKING_KEYS and urls.tracking_drop(key)
    assert urls.tracking_drop("utm_source") and urls.tracking_drop("utm_whatever")
    assert not urls.tracking_drop("id") and not urls.tracking_drop("utm")


def test_normalise_never_raises_on_odd_urls():
    for url in ("http://[::1", "https://example.invalid:99999/", "::::", "%zz?%zz=%zz&&=&"):
        assert isinstance(urls.normalise(url, urls.tracking_drop), str)


# ------------------------------------------------------------ locate ---

Box = tuple[float, float, float, float]


def _fake_search(index: dict[str, list[tuple[int, Box]]]):
    seen: list[str] = []

    def search(text: str) -> list[tuple[int, Box]]:
        seen.append(text)
        return index.get(text, [])
    return search, seen


def test_locate_finds_the_whole_text_with_whitespace_collapsed():
    search, seen = _fake_search({"Prezzo finale del mese": [(1, (10.0, 20.0, 90.0, 30.0))]})
    assert locate("  Prezzo\n finale  del mese ", search) == [(1, (10.0, 20.0, 90.0, 30.0))]
    assert seen == ["Prezzo finale del mese"]


def test_locate_falls_back_to_chunks_in_order_when_the_text_wraps():
    words = " ".join(f"w{i}" for i in range(12))
    first, second = " ".join(f"w{i}" for i in range(6)), " ".join(f"w{i}" for i in range(6, 12))
    search, _ = _fake_search({
        first: [(0, (10.0, 100.0, 200.0, 110.0))],
        # the second chunk appears twice; the one after the first chunk wins
        second: [(0, (10.0, 50.0, 200.0, 60.0)), (0, (10.0, 112.0, 200.0, 122.0))],
    })
    assert locate(words, search) == [(0, (10.0, 100.0, 200.0, 110.0)), (0, (10.0, 112.0, 200.0, 122.0))]


def test_locate_nothing_found_or_empty():
    search, seen = _fake_search({})
    assert locate("   ", search) == []
    assert seen == []
    assert locate("mai trovato qui", search) == []


# ---------------------------------------------- E6 deferred minors (E7) ---

def test_an_unterminated_comment_hides_everything_to_the_end():
    assert _texts(_blocks("<body><p>A</p><!--[if mso]><p>B</p>")) == ["A"]


def test_raw_office_xml_in_head_is_not_text_and_does_not_end_the_head():
    html = ("<html><head><xml><o:OfficeDocumentSettings><o:PixelsPerInch>96</o:PixelsPerInch>"
            "</o:OfficeDocumentSettings></xml><title>Titolo</title></head><body><p>Ciao</p></body></html>")
    assert _texts(_blocks(html)) == ["Ciao"]


def test_a_top_level_link_keeps_its_href_with_its_text():
    blocks = _blocks("<body><a href='https://example.invalid/x'>Clicca qui</a></body>")
    assert [(" ".join(w.text for w in b.words), b.attrs) for b in blocks] == [("Clicca qui", (("href", "https://example.invalid/x"),))]


def test_inline_text_straight_in_body_is_one_block_block_wrappers_still_split():
    assert _texts(_blocks("<body>Gentile <b>cliente</b>, grazie</body>")) == ["Gentile cliente, grazie"]
    assert _texts(_blocks("<body><center>Testo</center><center>Altro</center></body>")) == ["Testo", "Altro"]


def test_attr_diffs_accept_unpaired_blocks():
    left = _blocks('<body><p><img src="https://example.invalid/logo.png" alt="Logo"></p><p>testo</p></body>')
    right = _blocks('<body><p>testo</p><p><a href="https://example.invalid/n"><img src="x.png"></a></p></body>')
    got = attr_diffs(left, right, [(0, None), (1, 0), (None, 1)], _keep)
    assert got == [
        (0, None, "src: https://example.invalid/logo.png → (assente)"),
        (0, None, "alt: Logo → (assente)"),
        (None, 1, "href: (assente) → https://example.invalid/n"),
        (None, 1, "src: (assente) → x.png"),
    ]
