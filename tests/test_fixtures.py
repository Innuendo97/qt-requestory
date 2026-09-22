"""Sanity checks on the shared synthetic fixtures themselves."""
import json
import urllib.request
from datetime import date

from tests.conftest import FDI_A, KEY_SINT, autoindex_html, synthetic_body


def test_synthetic_body_is_single_line_json_with_noise():
    raw = synthetic_body(FDI_A, KEY_SINT, ndocs=3)
    assert b"\n" not in raw
    d = json.loads(raw)
    assert len(d["documents"]) == 3
    assert raw.count(b'"templateKey"') > 3  # regex counting would over-count
    assert d["dossier"]["requestDate"].endswith("Z")
    assert "città" in raw.decode("utf-8")


def test_mirror_layout(mirror):
    assert (mirror.root / "coll" / "2026" / "09" / "20260918.txt").exists()
    assert (mirror.root / "coll" / "2026" / "09" / "20260917.txt.part").exists()
    crlf = mirror.files[("coll", date(2026, 9, 18))].read_bytes()
    lf = mirror.files[("coll", date(2026, 9, 15))].read_bytes()
    assert b"\r\n" in crlf and b"\r\n" not in lf
    assert lf.count(b"### ") == 3 and lf.count(b"\n") == 3 + 2 + 1  # 3 headers, 2 bodies, 1 orphan


def test_autoindex_html_shape():
    html = autoindex_html([("20260921.txt", "21-Sep-2026 18:30", 64487564), ("20260920.txt", "20-Sep-2026 18:30", 0)], loose=2)
    assert '<a href="20260921.txt">20260921.txt</a>' in html
    assert html.count('.json">') == 2
    assert "..&gt;" in html


def test_stub_server_serves_and_records(stub_server):
    stub_server.add("/AutoDeploy/Input/", "<html>ok</html>")
    with urllib.request.urlopen(stub_server.url + "/AutoDeploy/Input/", timeout=5) as r:
        assert r.read() == b"<html>ok</html>"
    assert stub_server.requests == [("GET", "/AutoDeploy/Input/")]
