"""Make an HTML file safe to render offline (before Edge prints it to PDF).

ALLOW-list, not block-list: a reference survives only when it is

* relative (no scheme, no leading ``/`` or ``\\``) — it stays in the local
  folder; a UNC path (``\\\\host\\share``), ``file://host/…``, ``//host`` and
  every scheme (``http``, ``https``, ``cid``, ``javascript``, ``ftp``…) are
  blanked, because Edge would reach the network (SMB leaks NTLM credentials);
* ``data:`` (except in frames and plugins, which could load a whole page);
* a fragment (``#…``) or empty.

Values are HTML-entity-decoded (attributes) and CSS-unescaped (styles) before
being tested, so ``&#104;ttps:`` or ``\\68 ttps:`` cannot slip through. Also:
``<script>`` elements, ``on*`` handlers, ``srcdoc``, ``<base>`` and
``http-equiv`` metas (refresh…) are removed; CSS ``@import`` is removed; CSS
``url(…)`` and ``image-set(…)`` strings are tested like attributes, in
``<style>`` blocks and ``style=""`` attributes. ``<link>`` elements stay, with
a non-local ``href`` blanked.

A Content-Security-Policy meta (:data:`CSP`) goes first in ``<head>``: it
blocks every fetch (``default-src 'none'``) except ``data:`` images and fonts
and inline styles, and switches JavaScript, plugins and frames off. So the
policy itself stops the network even if the sanitiser missed a reference; a
consequence is that relative references (a local image or stylesheet next to
the original) do not load either — harmless, since the copy is rendered from
the output folder, away from the original's files. Edge's dead proxy and
blackhole resolver (see ``edge``) are the second layer.

Works on the document's own encoding (BOM, ``<meta charset>``, else UTF-8,
else cp1252/latin-1) and writes it back in that encoding.

Stdlib only.
"""
from __future__ import annotations

import codecs
import html
import re

#: Attributes whose value is a URL (or, for srcset, a list of URLs).
URL_ATTRS = frozenset({
    "src", "href", "xlink:href", "srcset", "imagesrcset", "background", "poster", "data",
    "action", "formaction", "longdesc", "cite", "lowsrc", "dynsrc", "profile", "manifest",
    "codebase", "archive", "usemap", "ping", "icon", "classid",
})
_SRCSET = frozenset({"srcset", "imagesrcset"})
#: Tags where ``data:`` could load a whole document.
_FRAMES = frozenset({"iframe", "frame", "object", "embed"})
#: http-equiv values that are harmless (the rest — refresh, link… — is dropped).
_SAFE_EQUIV = frozenset({"content-type", "content-language", "x-ua-compatible"})

_SCRIPT = re.compile(r"<script\b.*?(?:</script\s*>|\Z)", re.IGNORECASE | re.DOTALL)
_STYLE_BLOCK = re.compile(r"(<style\b(?:\"[^\"]*\"|'[^']*'|[^'\">])*>)(.*?)(</style\s*>|\Z)",
                          re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<(?P<name>[a-zA-Z][^\s/>]*)(?P<attrs>(?:\"[^\"]*\"|'[^']*'|[^'\">])*)>")
_ATTR = re.compile(
    r"(?P<sep>[\s/]*)(?P<name>[^\s/>=\"']+)"
    r"(?:(?P<eq>\s*=\s*)(?P<value>\"[^\"]*\"|'[^']*'|[^\s\"'>]+))?"
)
_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:")
_IGNORED_IN_URL = re.compile(r"[\x00-\x20\x7f]")
_CSS_ESCAPE = re.compile(r"\\(?:([0-9a-fA-F]{1,6})[ \t\r\n\f]?|([^\n\r\f0-9a-fA-F\"'\\]))")
_CSS_IMPORT = re.compile(r"@import\b(?:\"[^\"]*\"|'[^']*'|[^;\"'])*;?", re.IGNORECASE)
_CSS_URL = re.compile(r"url\(\s*(?:\"([^\"]*)\"|'([^']*)'|([^)\"']*?))\s*\)", re.IGNORECASE)
_CSS_STRING = re.compile(r"\"([^\"]*)\"|'([^']*)'")
_IMAGE_SET = re.compile(r"(?:-webkit-)?image-set\(", re.IGNORECASE)
#: JavaScript off (Edge's --blink-settings=scriptEnabled=false breaks
#: --print-to-pdf), no plugins or frames; resources as the sanitiser left them.
CSP = (
    "default-src 'none'; img-src data:; style-src 'unsafe-inline'; font-src data:; "
    "script-src 'none'; object-src 'none'; frame-src 'none'; worker-src 'none'; "
    "base-uri 'none'; form-action 'none'"
)
_HEAD = re.compile(r"<head\b(?:\"[^\"]*\"|'[^']*'|[^'\">])*>", re.IGNORECASE)
_HTML = re.compile(r"<html\b(?:\"[^\"]*\"|'[^']*'|[^'\">])*>", re.IGNORECASE)
_DOCTYPE = re.compile(r"<!doctype\b[^>]*>", re.IGNORECASE)
_META_CHARSET = re.compile(rb"<meta\b[^>]*?charset\s*=\s*[\"']?\s*([A-Za-z0-9_.:\-]+)", re.IGNORECASE)


def sanitise_html(data: bytes) -> bytes:
    """``data`` with every reference that could leave the machine removed."""
    encoding = _encoding(data)
    text = data.decode(encoding)
    text = _SCRIPT.sub("", text)
    text = _STYLE_BLOCK.sub(lambda m: m.group(1) + clean_css(m.group(2)) + m.group(3), text)
    text = _TAG.sub(_clean_tag, text)
    text = _with_csp(text)
    return text.encode(encoding, errors="xmlcharrefreplace")


def _with_csp(text: str) -> str:
    """Insert :data:`CSP` as the first thing in <head> (after the doctype if
    there is no head/html tag, so the page does not drop into quirks mode)."""
    meta = f'<meta http-equiv="Content-Security-Policy" content="{CSP}">'
    for pattern in (_HEAD, _HTML, _DOCTYPE):
        if match := pattern.search(text):
            return text[:match.end()] + meta + text[match.end():]
    return meta + text


def allowed_url(value: str, *, frame: bool = False) -> bool:
    """Whether a (decoded) URL stays local: relative, ``data:`` or ``#``."""
    url = _IGNORED_IN_URL.sub("", value)
    if url == "" or url.startswith("#"):
        return True
    if url[:5].lower() == "data:":
        return not frame
    if _SCHEME.match(url):
        return False
    return not url.startswith(("/", "\\"))


def clean_css(css: str) -> str:
    """CSS without ``@import`` and with non-local ``url()``/``image-set()`` blanked."""
    css = _CSS_ESCAPE.sub(_css_unescape, css)
    css = _CSS_IMPORT.sub("", css)
    css = _clean_image_sets(css)
    return _CSS_URL.sub(
        lambda m: m.group(0) if allowed_url(_first(m)) else 'url("")', css)


# ------------------------------------------------------------- internals ---

def _encoding(data: bytes) -> str:
    for bom, name in ((codecs.BOM_UTF8, "utf-8-sig"), (codecs.BOM_UTF16_LE, "utf-16"),
                      (codecs.BOM_UTF16_BE, "utf-16")):
        if data.startswith(bom):
            return name
    candidates = []
    if match := _META_CHARSET.search(data[:4096]):
        candidates.append(match.group(1).decode("ascii"))
    candidates += ["utf-8", "cp1252"]
    for name in candidates:
        try:
            codecs.lookup(name)
            data.decode(name)
        except (LookupError, UnicodeDecodeError):
            continue
        return name
    return "latin-1"  # decodes anything, round-trips byte for byte


def _clean_tag(match: re.Match[str]) -> str:
    tag = match.group("name").lower()
    raw_attrs = match.group("attrs")
    attrs = {m.group("name").lower(): _value(m) for m in _ATTR.finditer(raw_attrs)}
    if tag == "base" or tag == "script":
        return ""
    if tag == "meta" and "http-equiv" in attrs and attrs["http-equiv"].strip().lower() not in _SAFE_EQUIV:
        return ""
    out = []
    last = 0
    for m in _ATTR.finditer(raw_attrs):
        out.append(raw_attrs[last:m.start()])
        last = m.end()
        out.append(_clean_attr(tag, m))
    out.append(raw_attrs[last:])
    return f"<{match.group('name')}{''.join(out)}>"


def _value(m: re.Match[str]) -> str:
    raw = m.group("value") or ""
    if raw[:1] in "\"'" and raw[-1:] == raw[:1] and len(raw) >= 2:
        raw = raw[1:-1]
    return html.unescape(raw)


def _clean_attr(tag: str, m: re.Match[str]) -> str:
    name = m.group("name").lower()
    sep = m.group("sep") or " "
    if name.startswith("on") or name == "srcdoc":
        return " "  # dropped; a space keeps the neighbours apart
    if m.group("value") is None:
        return m.group(0)
    value = _value(m)
    if name in URL_ATTRS:
        frame = tag in _FRAMES
        if name in _SRCSET:
            ok = all(allowed_url(c.split()[0], frame=frame)
                     for c in value.split(",") if c.strip())
        else:
            ok = allowed_url(value, frame=frame)
        if ok:
            return m.group(0)
        replacement = "#" if name == "href" and tag in ("a", "area") else ""
        return f'{sep}{m.group("name")}="{replacement}"'
    if name == "style":
        cleaned = clean_css(value)
        if cleaned != value:
            return f'{sep}{m.group("name")}="{html.escape(cleaned, quote=True)}"'
    return m.group(0)


def _css_unescape(m: re.Match[str]) -> str:
    if m.group(1):
        code = int(m.group(1), 16)
        if code in (0x22, 0x27, 0x5C) or code == 0 or code > 0x10FFFF or 0xD800 <= code <= 0xDFFF:
            return m.group(0)  # keep quotes, backslash and invalid code points escaped
        return chr(code)
    return m.group(2)


def _first(m: re.Match[str]) -> str:
    return next((g for g in m.groups() if g is not None), "")


def _clean_image_sets(css: str) -> str:
    """Blank the non-local string URLs inside every ``image-set(...)``."""
    out = []
    pos = 0
    for start in _IMAGE_SET.finditer(css):
        if start.start() < pos:
            continue
        end = _closing_paren(css, start.end())
        inner = _CSS_STRING.sub(
            lambda s: s.group(0) if allowed_url(_first(s)) else '""', css[start.end():end])
        out.append(css[pos:start.end()] + inner)
        pos = end
    out.append(css[pos:])
    return "".join(out)


def _closing_paren(css: str, i: int) -> int:
    depth, quote = 1, ""
    while i < len(css):
        ch = css[i]
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return len(css)
