"""qtrequestory.officina.compare.sanitise: the allow-list HTML sanitiser.

Every reference that could leave the machine (http/https, protocol-relative,
cid:, UNC, file://host, any other scheme) must be gone, however it is written.
Synthetic HTML only (example.invalid).
"""
from __future__ import annotations

import pytest

from qtrequestory.officina.compare.sanitise import CSP, allowed_url, clean_css, sanitise_html


CSP_META = f'<meta http-equiv="Content-Security-Policy" content="{CSP}">'


def clean(html: str) -> str:
    return sanitise_html(html.encode("utf-8")).decode("utf-8")


def assert_offline(out: str) -> None:
    lowered = out.replace(CSP_META, "").lower()
    for needle in ("example.invalid", "http", "cid:", "file:", "javascript", "\\\\host", "//host"):
        assert needle not in lowered, (needle, out)


@pytest.mark.parametrize("url", [
    "https://x.example.invalid/a.png", "http://x.example.invalid/a.png", "HTTPS://x.example.invalid",
    "//x.example.invalid/a.png", "cid:logo@example.invalid", "file://host/share/a.png",
    "file:///C:/a.png", "\\\\host\\share\\a.png", "/abs/a.png", "\\abs\\a.png",
    "javascript:alert(1)", "ftp://x.example.invalid/a", " \thttps://x.example.invalid",
    "ht\ntps://x.example.invalid", "C:\\a.png", "blob:x",
])
def test_non_local_urls_are_refused(url: str):
    assert not allowed_url(url)


@pytest.mark.parametrize("url", ["local.png", "img/a.png", "../a.png", "#top", "", "data:image/png;base64,AAAA"])
def test_local_urls_are_allowed(url: str):
    assert allowed_url(url)


def test_data_urls_are_refused_in_frames():
    assert not allowed_url("data:text/html,<p>x</p>", frame=True)
    assert "data:" not in clean('<iframe src="data:text/html,x"></iframe>').replace(CSP_META, "")


def test_quoted_greater_than_in_an_attribute_does_not_end_the_tag():
    out = clean('<img alt="a > b" src="https://x.example.invalid/p.gif">')
    assert_offline(out)
    assert 'alt="a > b"' in out


def test_slash_before_an_attribute_name():
    out = clean("<img/src=https://x.example.invalid/p.gif>")
    assert_offline(out)
    assert out == CSP_META + "<img/src=\"\">"


def test_entity_encoded_scheme():
    assert_offline(clean('<img src="&#104;ttps://x.example.invalid/p.gif">'))
    assert_offline(clean('<img src="&#x68;ttps&colon;//x.example.invalid/p.gif">'))
    assert_offline(clean('<img src="https&#58;//x.example.invalid/p.gif">'))


def test_unc_and_file_host_paths():
    assert_offline(clean('<img src="\\\\host\\share\\p.gif">'))
    assert_offline(clean('<img src="file://host/share/p.gif">'))
    assert_offline(clean('<div style="background:url(\\\\host\\share\\p.gif)">x</div>'))


def test_event_handlers_and_srcdoc_are_dropped():
    out = clean('<img src="a.png" onerror="fetch(\'https://x.example.invalid\')">'
                '<body onload=go()><iframe srcdoc="<img src=https://x.example.invalid>"></iframe>')
    assert "onerror" not in out and "onload" not in out and "srcdoc" not in out
    assert_offline(out)
    assert 'src="a.png"' in out
    assert "<img" in clean('<img/onerror="x"src="a.png">') and "onerror" not in clean('<img/onerror="x"src="a.png">')


def test_srcset_with_any_external_candidate_is_blanked():
    out = clean('<img srcset="a.png 1x, https://x.example.invalid/b.png 2x" src="a.png">')
    assert_offline(out)
    assert 'srcset=""' in out and 'src="a.png"' in out
    assert 'srcset="a.png 1x, b.png 2x"' in clean('<img srcset="a.png 1x, b.png 2x">')


def test_image_set_and_url_in_style_blocks_and_attributes():
    css = """<style>
    .a { background-image: image-set("https://x.example.invalid/a.png" 1x, 'local.png' 2x); }
    .b { background-image: -webkit-image-set(url(https://x.example.invalid/b.png) 1x); }
    .c { background: url( "https://x.example.invalid/c.png" ) }
    .d { background: url(local.png) }
    </style>
    <div style="background-image:image-set('https://x.example.invalid/e.png' 1x)">x</div>
    <div style="background:url(&quot;https://x.example.invalid/f.png&quot;)">y</div>"""
    out = clean(css)
    assert_offline(out)
    assert "'local.png' 2x" in out and "url(local.png)" in out


def test_css_escapes_are_decoded_before_testing():
    out = clean_css("a { background: url(\\68 ttps://x.example.invalid/a.png) } @\\69mport 'https://x.example.invalid/b.css';")
    assert_offline(out)


def test_import_link_base_and_meta_refresh():
    out = clean(
        '<head><base href="https://x.example.invalid/">'
        '<link rel="stylesheet" href="https://x.example.invalid/s.css">'
        '<meta http-equiv="refresh" content="0;url=https://x.example.invalid/">'
        '<meta charset="utf-8">'
        "<style>@import url(https://x.example.invalid/i.css); @import 'https://x.example.invalid/j.css';"
        " p { color: red }</style></head><body><p>ciao</p></body>"
    )
    assert_offline(out)
    assert "<base" not in out and "refresh" not in out
    assert '<meta charset="utf-8">' in out and "p { color: red }" in out


def test_scripts_and_javascript_urls_are_removed():
    out = clean('<script>fetch("https://x.example.invalid")</script><a href="javascript:go()">x</a>'
                '<script src="https://x.example.invalid/t.js">')
    assert "<script" not in out.lower()
    assert '<a href="#">x</a>' in out
    assert_offline(out)


def test_external_anchor_keeps_its_link_styling():
    assert clean('<a href="https://x.example.invalid/o">Scopri</a>').endswith('<a href="#">Scopri</a>')


def test_text_and_local_references_are_untouched():
    html = ('<p class="x">Gentile cliente, l\'offerta &egrave; &lt;valida&gt;.</p>'
            '<img src="local.png" alt="logo"><a href="#sez">vai</a><a href="pagina.html">p</a>')
    assert clean(html) == CSP_META + html


def test_declared_encoding_round_trips():
    raw = '<meta charset="windows-1252"><p>perch\u00e9 \u20ac</p><img src="https://x.example.invalid/a">'.encode("cp1252")
    out = sanitise_html(raw)
    assert "perch\u00e9 \u20ac".encode("cp1252") in out
    assert b"example.invalid" not in out


def test_utf16_with_bom_round_trips():
    raw = '<p>\u00e8</p><img src="https://x.example.invalid/a">'.encode("utf-16")
    out = sanitise_html(raw).decode("utf-16")
    assert "\u00e8" in out and "example.invalid" not in out


@pytest.mark.parametrize("html, expected", [
    ("<!doctype html><html lang=it><head><title>t</title></head>",
     "<!doctype html><html lang=it><head>{m}<title>t</title></head>"),
    ("<!DOCTYPE html><html><body>x</body></html>", "<!DOCTYPE html><html>{m}<body>x</body></html>"),
    ("<!doctype html><p>x</p>", "<!doctype html>{m}<p>x</p>"),
    ("<p>x</p>", "{m}<p>x</p>"),
])
def test_a_csp_switching_scripts_off_goes_first_in_head(html: str, expected: str):
    assert clean(html) == expected.format(m=CSP_META)
    assert "script-src 'none'" in CSP


def test_the_csp_itself_blocks_every_fetch_but_data_images_and_inline_styles():
    directives = {d.split()[0]: d.split()[1:] for d in CSP.split(";") if d.strip()}
    assert directives["default-src"] == ["'none'"]
    assert directives["img-src"] == ["data:"] and directives["font-src"] == ["data:"]
    assert directives["style-src"] == ["'unsafe-inline'"]
    for name in ("script-src", "object-src", "frame-src", "worker-src", "base-uri", "form-action"):
        assert directives[name] == ["'none'"], name


def test_link_elements_stay_with_a_blanked_href():
    out = clean('<link rel="stylesheet" href="https://x.example.invalid/s.css"><link rel="icon" href="i.png">')
    assert out.endswith('<link rel="stylesheet" href=""><link rel="icon" href="i.png">')
