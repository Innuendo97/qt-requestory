"""qtrequestory.officina.generator: headers, upload-link policy, HTTP client.

Every HTTP call goes to a local ``http.server`` in a thread — never to a real
endpoint. Synthetic data only (public repository).
"""
from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from qtrequestory.core.config import OfficinaSettings
from qtrequestory.officina import generator
from qtrequestory.officina.generator import (
    HeaderError,
    SendResult,
    prepare_payload,
    resolve_headers,
    send,
    sniff,
)
from qtrequestory.officina.links import find_links
from qtrequestory.officina.model import Case, Initiative

from .test_links import SIG, nested_payload, sas

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
EXPIRED = "2026-09-20T10%3A00%3A00Z"
VALID = "2026-12-31T23%3A59%3A59Z"
PDF = b"%PDF-1.7\n" + b"0" * 2000 + b"\n%%EOF\n"
HTML = b"<!DOCTYPE html>\n<html><body>" + b"<p>MOD_TEST corpo email</p>" * 40 + b"</body></html>"


# ------------------------------------------------------------------ fixtures ---

def make_case(tmp_path: Path, **kw) -> Case:
    values = dict(
        id="MOD_TEST_A", key="MOD_TEST_A", variant="", env="svil", headers={},
        drop_postman_token=False, correlation="new", correlation_value="",
        link_policy="remove", status="open", notes="", folder=tmp_path / "caso",
        source_fdi=None,
    )
    values.update(kw)
    return Case(**values)


def make_ini(tmp_path: Path, defaults: dict[str, str] | None = None) -> Initiative:
    return Initiative(name="Test", folder=tmp_path, header_defaults=dict(defaults or {}))


def uuids() -> Iterator[str]:
    n = 0
    while True:
        n += 1
        yield f"00000000-0000-4000-8000-{n:012d}"


def resolve(case: Case, ini: Initiative, settings: OfficinaSettings | None = None, **kw) -> dict[str, str]:
    gen = uuids()
    kw.setdefault("source_fdi", case.source_fdi)
    return resolve_headers(case, ini, settings or OfficinaSettings(), now_ms=1_790_000_000_000,
                           new_uuid=lambda: next(gen), **kw)


@dataclass
class Canned:
    status: int = 200
    body: bytes = PDF
    delay_s: float = 0.0  # before the answer, or (partial=True) after half the body
    headers: dict[str, str] = field(default_factory=dict)
    partial: bool = False
    trickle_s: float = 0.0  # pause between 200-byte chunks of the body


class FakeServer:
    def __init__(self) -> None:
        self.canned = Canned()
        self.requests: list[tuple[dict[str, str], bytes]] = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                server.requests.append((dict(self.headers.items()), self.rfile.read(length)))
                canned = server.canned
                if canned.delay_s and not canned.partial:
                    time.sleep(canned.delay_s)
                try:
                    self.send_response(canned.status)
                    for k, v in canned.headers.items():
                        self.send_header(k, v)
                    self.send_header("Content-Length", str(len(canned.body)))
                    self.end_headers()  # deliberately NO Content-Type (spec §11)
                    body = canned.body
                    if canned.partial:
                        half = len(body) // 2
                        self.wfile.write(body[:half])
                        self.wfile.flush()
                        time.sleep(canned.delay_s)
                        body = body[half:]
                    if canned.trickle_s:
                        for i in range(0, len(body), 200):
                            self.wfile.write(body[i:i + 200])
                            self.wfile.flush()
                            time.sleep(canned.trickle_s)
                    else:
                        self.wfile.write(body)
                except OSError:
                    pass  # the client gave up (timeout test)

            def log_message(self, *args) -> None:
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.httpd.handle_error = lambda *a: None  # type: ignore[method-assign]
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/rest/api/submit-job/documentGenerator"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def server() -> Iterator[FakeServer]:
    s = FakeServer()
    yield s
    s.close()


def post(server: FakeServer, *, timeout_s: int = 10, headers: dict[str, str] | None = None) -> SendResult:
    return send(server.url, {"documents": []}, headers or {"template_key": "MOD_TEST_A"}, timeout_s=timeout_s)


# ------------------------------------------------------------------- headers ---

def test_headers_precedence_and_automatic_values(tmp_path: Path):
    settings = OfficinaSettings(header_profile={"service_number": "SN-PROFILE", "office_id": "OFF-PROFILE",
                                                "branch_id": "BR-PROFILE"})
    ini = make_ini(tmp_path, {"office_id": "OFF-INI", "X-Flag": "active", "branch_id": "BR-INI"})
    case = make_case(tmp_path, headers={"branch_id": "BR-CASE", "x-flag": "", "X-Extra": "1", "Vuoto": ""})

    h = resolve(case, ini, settings)

    assert h["current_timestamp"] == "1790000000000"
    assert h["template_key"] == "MOD_TEST_A"
    assert h["correlation_id"] == "00000000-0000-4000-8000-000000000001"
    assert h["service_number"] == "SN-PROFILE"           # profile only
    assert h["office_id"] == "OFF-INI"                   # initiative beats profile
    assert h["branch_id"] == "BR-CASE"                   # case beats initiative
    assert h["X-Extra"] == "1"
    # empty values are dropped, and header names compare case-insensitively:
    # the case's empty "x-flag" removes the initiative's "X-Flag"
    assert "Vuoto" not in h
    assert not any(k.lower() == "x-flag" for k in h)
    # a case override may even replace an automatic value
    h2 = resolve(make_case(tmp_path, headers={"template_key": "MOD_TEST_OVERRIDE"}), ini, settings)
    assert h2["template_key"] == "MOD_TEST_OVERRIDE"


def test_postman_token_default_and_explicit_drop(tmp_path: Path):
    ini = make_ini(tmp_path)
    assert resolve(make_case(tmp_path), ini)["Postman-Token"] == "qtRequestory"
    custom = OfficinaSettings(postman_token="tok-test")
    assert resolve(make_case(tmp_path), ini, custom)["Postman-Token"] == "tok-test"
    # an empty override can NOT remove it: only the explicit toggle can
    emptied = make_case(tmp_path, headers={"postman-token": ""})
    assert resolve(emptied, make_ini(tmp_path, {"Postman-Token": ""}))["Postman-Token"] == "qtRequestory"
    # a non-empty override replaces the value
    assert resolve(make_case(tmp_path, headers={"Postman-Token": "mio"}), ini)["Postman-Token"] == "mio"
    dropped = make_case(tmp_path, drop_postman_token=True, headers={"Postman-Token": "mio"})
    assert not any(k.lower() == "postman-token" for k in resolve(dropped, ini))


def test_correlation_modes(tmp_path: Path):
    ini = make_ini(tmp_path)
    fdi = "11111111-2222-4333-8444-555555555555"
    new_case = make_case(tmp_path)
    assert resolve(new_case, ini)["correlation_id"] == "00000000-0000-4000-8000-000000000001"
    # a new uuid on every call
    gen = uuids()
    first = resolve_headers(new_case, ini, OfficinaSettings(), now_ms=1, new_uuid=lambda: next(gen), source_fdi=None)
    second = resolve_headers(new_case, ini, OfficinaSettings(), now_ms=1, new_uuid=lambda: next(gen), source_fdi=None)
    assert first["correlation_id"] != second["correlation_id"]

    source_case = make_case(tmp_path, correlation="source", source_fdi=fdi)
    assert resolve(source_case, ini)["correlation_id"] == fdi
    assert resolve(source_case, ini, source_fdi="99999999-0000-4000-8000-000000000000")["correlation_id"] \
        == "99999999-0000-4000-8000-000000000000"
    # the case's own source_fdi is the default when the caller passes nothing
    gen2 = uuids()
    assert resolve_headers(source_case, ini, OfficinaSettings(), now_ms=1,
                           new_uuid=lambda: next(gen2))["correlation_id"] == fdi

    fixed = make_case(tmp_path, correlation="fixed", correlation_value="FIXED-CORR")
    assert resolve(fixed, ini)["correlation_id"] == "FIXED-CORR"

    with pytest.raises(HeaderError, match="FDI"):
        resolve(make_case(tmp_path, correlation="source"), ini)
    with pytest.raises(HeaderError):
        resolve(make_case(tmp_path, correlation="fixed", correlation_value="  "), ini)
    # ...unless the case sets correlation_id explicitly
    explicit = make_case(tmp_path, correlation="source", headers={"correlation_id": "CASE-CORR"})
    assert resolve(explicit, ini)["correlation_id"] == "CASE-CORR"


# ------------------------------------------------------------ payload policy ---

def test_remove_policy_strips_nested_links():
    payload = nested_payload(sas(se=EXPIRED), sas(se=EXPIRED))

    sent, reason = prepare_payload(payload, "remove", now=NOW)

    assert reason == ""
    assert sent is not None
    assert find_links(sent) == []
    assert "attachmentId" not in json.dumps(sent)
    assert find_links(payload)  # the original is untouched


def test_keep_if_expired_sends_expired_links_unchanged():
    payload = nested_payload(sas(se=EXPIRED), sas(se=EXPIRED))
    sent, reason = prepare_payload(payload, "keep_if_expired", now=NOW)
    assert (sent, reason) == (payload, "")
    assert sent is not payload


@pytest.mark.parametrize("se", [VALID, None, "garbage"])
def test_keep_if_expired_refuses_a_link_that_is_not_provably_expired(se):
    payload = nested_payload(sas(se=EXPIRED), sas(se=se))
    sent, reason = prepare_payload(payload, "keep_if_expired", now=NOW)
    assert sent is None
    assert "dossier.dossierItems[0]" in reason
    assert SIG not in reason and "sig=***" in reason


@pytest.mark.parametrize("policy", ["remove", "keep_if_expired", "replace", ""])
def test_valid_link_is_never_sent_whatever_the_policy(policy):
    # a valid SAS link hidden OUTSIDE the attachmentUrl attributes: remove can't
    # strip it, keep_if_expired can't keep it, an unknown policy refuses anyway
    payload = nested_payload(sas(se=VALID), sas(se=VALID))
    payload["customData"] = {"note": f"vedi {sas(se=VALID, name='other.pdf')}"}

    sent, reason = prepare_payload(payload, policy, now=NOW)

    assert sent is None
    assert reason
    assert SIG not in reason


def test_remove_policy_with_valid_attachment_links_only_is_safe():
    # remove really drops them, so nothing valid is sent: this is allowed
    sent, reason = prepare_payload(nested_payload(sas(se=VALID), sas(se=VALID)), "remove", now=NOW)
    assert reason == ""
    assert sent is not None and SIG not in json.dumps(sent)


def test_mask_hides_signature(server: FakeServer):
    # in the refusal reason ...
    _, reason = prepare_payload(nested_payload(sas(se=VALID), sas(se=VALID)), "keep_if_expired", now=NOW)
    assert SIG not in reason and "sig=***" in reason
    # ... in the headers echoed back ...
    server.canned = Canned(status=200, body=PDF)
    res = post(server, headers={"template_key": "MOD_TEST_A", "X-Link": sas(), "Authorization": "Bearer abc"})
    assert res.ok
    assert SIG not in json.dumps(res.headers_sent)
    assert res.headers_sent["Authorization"] == "***"
    # ... and in a failed response shown to the user
    server.canned = Canned(status=500, body=f"errore: {sas()}".encode())
    res = post(server)
    assert SIG.encode() not in res.content and SIG not in res.reason


# -------------------------------------------------------------------- sniff ---

def test_sniff():
    assert sniff(PDF) == "pdf"
    assert sniff(b"\xef\xbb\xbf  <!doctype HTML><html></html>") == "html"
    assert sniff(b"\n<html lang='it'>") == "html"
    assert sniff(b'{"error": "<html>"}') is None
    assert sniff(b"") is None
    assert sniff(b"plain text") is None


def test_pdf_and_html_are_sniffed_without_content_type(server: FakeServer):
    res = post(server)
    assert res.ok, res.reason
    assert (res.status, res.doc_type, res.content, res.reason) == (200, "pdf", PDF, "")
    assert res.duration_ms >= 0
    received, body = server.requests[-1]
    received = {k.lower(): v for k, v in received.items()}  # HTTP names are case-insensitive
    assert json.loads(body) == {"documents": []}
    assert received["template_key"] == "MOD_TEST_A"
    assert received["content-type"] == "application/json"
    assert res.headers_sent["template_key"] == "MOD_TEST_A"

    server.canned = Canned(body=HTML)
    res = post(server)
    assert res.ok and res.doc_type == "html" and res.content == HTML


def test_non_document_response_is_a_failed_run(server: FakeServer):
    server.canned = Canned(status=200, body=b'{"status": "KO", "message": "MOD_TEST errore"}')
    res = post(server)
    assert res.ok is False
    assert res.status == 200
    assert res.doc_type is None
    assert res.reason == "la risposta non è un PDF né un HTML"
    assert res.content.startswith(b'{"status"')  # the first 4 KB, to show the user

    server.canned = Canned(status=200, body=b"")
    res = post(server)
    assert res.ok is False and res.reason == "la risposta non è un PDF né un HTML"


def test_tiny_html_is_suspicious(server: FakeServer):
    server.canned = Canned(status=200, body=b"<html><body>Bad gateway</body></html>")
    res = post(server)
    assert res.ok is False
    assert res.doc_type == "html"
    assert res.reason == "risposta HTML sospetta: troppo corta"


def test_http_500_is_failed(server: FakeServer):
    server.canned = Canned(status=500, body=b"x" * 10_000)
    res = post(server)
    assert res.ok is False
    assert res.status == 500
    assert "500" in res.reason
    assert len(res.content) == 4096


def test_http_error_with_a_pdf_body_is_still_failed(server: FakeServer):
    server.canned = Canned(status=502, body=PDF)
    res = post(server)
    assert res.ok is False and res.status == 502


def test_timeout_writes_no_version(server: FakeServer):
    server.canned = Canned(status=200, body=PDF, delay_s=3)
    started = time.monotonic()
    res = post(server, timeout_s=1)
    assert time.monotonic() - started < 2.5
    assert res.ok is False
    assert res.content == b""
    assert res.status is None
    assert res.reason


def test_network_error_is_a_failed_run():
    s = FakeServer()
    url = s.url
    s.close()  # nothing listens there any more
    res = send(url, {}, {}, timeout_s=2)
    assert res.ok is False and res.content == b"" and res.reason


def test_send_refuses_prod_and_plain_http_to_a_remote_host():
    calls = []

    def opener(*a, **kw):
        calls.append(a)
        raise AssertionError("must not be called")

    for url in ("https://generator-PROD.example.invalid/x", "http://example.invalid/x"):
        res = send(url, {}, {}, timeout_s=1, opener=opener)
        assert res.ok is False and res.reason
    assert calls == []


def test_module_has_no_real_hostnames():
    import re
    src = Path(generator.__file__).read_text(encoding="utf-8")
    assert not re.search(r"https?://[A-Za-z0-9.-]+\.[A-Za-z]{2,}", src)


# ------------------------------------------------------------ fix round 1 ---

VALID_Q = f"sv=2022-11-02&se={VALID}&sr=b&sp=cw&sig={SIG}"
PCT_Q = VALID_Q.replace("&", "%26").replace("=", "%3D")
JSON_Q = VALID_Q.replace("&", "\\u0026").replace("=", "\\u003d")
HTML_Q = VALID_Q.replace("&", "&amp;")


@pytest.mark.parametrize("policy", ["remove", "keep_if_expired"])
@pytest.mark.parametrize("url", [
    f"https://example.invalid:abc/b?{VALID_Q}",
    f"https://[example.invalid/b?{VALID_Q}",
])
def test_a_malformed_signed_url_is_refused_not_raised(policy, url):
    payload = {"documents": [{"attributes": [{"key": "attachmentUrl", "value": url}]}],
               "customData": {"u": url}}
    sent, reason = prepare_payload(payload, policy, now=NOW)
    assert sent is None and reason and SIG not in reason


@pytest.mark.parametrize("value", [
    f"https%3A%2F%2Fexample.invalid%2Fc%2Fb.pdf%3F{PCT_Q}",
    f"https:\\/\\/example.invalid\\/c?{JSON_Q}",
    f"&lt;a href=&quot;https://example.invalid/c?{HTML_Q}&quot;&gt;",
    f"//example.invalid/c/b.pdf?{VALID_Q}",
    f"example.invalid/c/b.pdf?sig={SIG}",  # signed, no expiry at all
])
@pytest.mark.parametrize("policy", ["remove", "keep_if_expired"])
def test_signed_strings_in_any_encoding_are_refused(policy, value):
    payload = {"documents": [], "customData": {"blob": value}}
    sent, reason = prepare_payload(payload, policy, now=NOW)
    assert sent is None
    assert "customData.blob" in reason and SIG not in reason


def test_expired_links_in_other_encodings_pass():
    exp_q = f"sv=1&se={EXPIRED}&sr=b&sp=cw&sig={SIG}"
    payload = {"customData": {"a": f"//example.invalid/c?{exp_q}",
                              "b": exp_q.replace("&", "%26").replace("=", "%3D")}}
    sent, reason = prepare_payload(payload, "remove", now=NOW)
    assert (sent, reason) == (payload, "")


def test_a_link_expiring_within_the_clock_skew_is_still_refused():
    just = "2026-09-25T11%3A58%3A00Z"  # 2 minutes before NOW
    payload = nested_payload(sas(se=just), sas(se=EXPIRED))
    sent, _ = prepare_payload(payload, "keep_if_expired", now=NOW)
    assert sent is None


@pytest.mark.parametrize("url", [
    "https://generator-ｐｒｏｄ.example.invalid/x",   # fullwidth "prod"
    "https://generator-ＰＲＯＤ.example.invalid/x",   # fullwidth "PROD"
    "https://générateur.example.invalid/x",
    "https://example.invalid:abc/x",
    "https:///x",
])
def test_send_refuses_fullwidth_prod_non_ascii_and_hostless_urls(url):
    def opener(*a, **kw):
        raise AssertionError("must not be called")
    res = send(url, {}, {}, timeout_s=1, opener=opener)
    assert res.ok is False and res.reason and res.content == b""


def test_a_redirect_is_never_followed(server: FakeServer):
    server.canned = Canned(status=302, body=b"", headers={"Location": server.url + "/altrove"})
    res = post(server)
    assert res.ok is False
    assert res.status == 302
    assert "reindirizzamento non consentito" in res.reason
    assert len(server.requests) == 1
    server.canned = Canned(status=307, body=b"", headers={"Location": "https://example.invalid/x"})
    res = post(server)
    assert res.ok is False and "reindirizzamento non consentito" in res.reason
    assert len(server.requests) == 2


def test_timeout_in_the_middle_of_the_body(server: FakeServer):
    server.canned = Canned(status=200, body=PDF, delay_s=3, partial=True)
    started = time.monotonic()
    res = post(server, timeout_s=1)
    assert time.monotonic() - started < 2.5
    assert res.ok is False and res.content == b"" and res.status is None


def test_a_slow_trickle_is_bounded_by_the_overall_deadline(server: FakeServer):
    server.canned = Canned(status=200, body=PDF, trickle_s=0.3)
    started = time.monotonic()
    res = post(server, timeout_s=1)
    assert time.monotonic() - started < 2.0
    assert res.ok is False and res.content == b""


def test_a_huge_body_is_refused(server: FakeServer, monkeypatch):
    monkeypatch.setattr(generator, "MAX_BODY_BYTES", 1000)
    res = post(server)
    assert res.ok is False and res.content == b""
    assert "troppo grande" in res.reason


def test_sniff_wants_the_pdf_header_at_the_start():
    assert sniff(b"\xef\xbb\xbf \r\n%PDF-1.7") == "pdf"
    assert sniff(b" " * 8 + b"%PDF-1.7") == "pdf"
    assert sniff(b" " * 9 + b"%PDF-1.7") is None
    assert sniff(b"<error>%PDF-1.7</error>") is None
    assert sniff(b'{"x": "%PDF-"}') is None


def test_a_non_latin1_header_value_is_refused(tmp_path: Path):
    with pytest.raises(HeaderError, match="caratteri"):
        resolve(make_case(tmp_path, headers={"X-Nome": "città ✓"}), make_ini(tmp_path))
    ok = resolve(make_case(tmp_path, headers={"X-Nome": "città"}), make_ini(tmp_path))
    assert ok["X-Nome"] == "città"


def test_send_never_raises():
    def boom(*a, **kw):
        raise RuntimeError(f"guasto su https://example.invalid/c?sig={SIG}")
    res = send("https://example.invalid/g", {}, {}, timeout_s=1, opener=boom)
    assert res.ok is False and SIG not in res.reason
    res = send("https://example.invalid/g", {"x": object()}, {}, timeout_s=1, opener=boom)
    assert res.ok is False
    res = send("https://example.invalid/g", {}, {"X-Bad": "✓"}, timeout_s=1, opener=boom)
    assert res.ok is False


@pytest.mark.parametrize("name", ["Host", "Content-Length", "transfer-encoding", "Connection"])
def test_a_header_the_http_client_owns_is_refused(tmp_path: Path, name: str):
    """The same rule as the Impostazioni profile (core ``header_name_problem``)."""
    with pytest.raises(HeaderError, match="client HTTP"):
        resolve(make_case(tmp_path, headers={name: "x"}), make_ini(tmp_path))


@pytest.mark.parametrize("where, expected", [("case", "caso"), ("ini", "iniziativa"),
                                             ("profile", "profilo")])
def test_a_header_error_names_its_layer(tmp_path: Path, where: str, expected: str):
    bad = {"Host": "x"}
    case = make_case(tmp_path, headers=bad if where == "case" else {})
    ini = make_ini(tmp_path, bad if where == "ini" else None)
    settings = OfficinaSettings(header_profile=bad) if where == "profile" else None
    with pytest.raises(HeaderError, match=expected):
        resolve(case, ini, settings)
