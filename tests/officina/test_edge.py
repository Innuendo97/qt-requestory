"""qtrequestory.officina.compare.edge: HTML -> PDF with the installed Edge.

The real-Edge test is skipped where Edge is missing. Every other test uses a
fake ``msedge`` (a .cmd that writes nothing) or a fake runner — no real Edge,
no network. Synthetic HTML only.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from qtrequestory.officina.compare import edge
from qtrequestory.officina.compare.edge import find_edge, html_to_pdf, sanitise_html

HTML = """<!doctype html>
<html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://cdn.example.invalid/style.css">
<style>@import url("https://cdn.example.invalid/more.css");
body { background: url('https://cdn.example.invalid/bg.png'); }
.logo { background-image: url(//cdn.example.invalid/logo.png) }
.local { background-image: url(local.png) }</style>
<script src="https://cdn.example.invalid/track.js"></script>
<script>fetch("https://api.example.invalid/beacon")</script>
</head><body>
<h1>Offerta di prova MOD_TEST_EMAIL</h1>
<p style="font-size: 32px; color: #336699">Stile grande</p>
<img alt="punto" width="40" height="40" src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==">
<p>Gentile cliente, questa &egrave; una email sintetica.</p>
<img src="https://img.example.invalid/pixel.gif" alt="pixel">
<img src='cid:logo@example.invalid' alt="logo">
<img src=//img.example.invalid/x.png>
<img srcset="https://img.example.invalid/a.png 1x, b.png 2x" src="local.png">
<a href="https://www.example.invalid/offerta">Scopri l'offerta</a>
<table background="http://img.example.invalid/t.png"><tr><td>cella</td></tr></table>
</body></html>
"""


def test_sanitise_removes_every_external_reference():
    out = sanitise_html(HTML.encode("utf-8")).decode("utf-8")
    lowered = out.lower()
    for needle in ("https:", "http:", "//cdn.", "//img.", "cid:", "<script", "fetch("):
        assert needle not in lowered, needle
    assert "Offerta di prova MOD_TEST_EMAIL" in out
    assert "Scopri l'offerta" in out
    assert 'alt="pixel"' in out
    assert "url(local.png)" in out and 'src="local.png"' in out, "local refs stay"


def test_sanitise_keeps_the_original_encoding_bytes():
    raw = HTML.replace("&egrave;", "è").encode("latin-1", errors="replace")
    out = sanitise_html(raw)
    assert "è".encode("latin-1") in out


def test_html_to_pdf_writes_a_sanitised_copy_next_to_the_output(tmp_path: Path, monkeypatch):
    src = tmp_path / "in" / "email.html"
    src.parent.mkdir()
    src.write_text(HTML, encoding="utf-8")
    out = tmp_path / "out" / "email.pdf"
    out.parent.mkdir()
    seen: list[list[str]] = []

    def fake_run(argv: list[str], timeout_s: int) -> str | None:
        seen.append(argv)
        return None  # "exit 0" but nothing written

    monkeypatch.setattr(edge, "_run", fake_run)
    error = html_to_pdf(src, out, edge=Path("msedge.exe"))
    copy = out.parent / "email.sanitised.html"
    assert copy.is_file()
    assert "https:" not in copy.read_text(encoding="utf-8").lower()
    assert all(copy.as_uri() == argv[-1] for argv in seen), "Edge renders the sanitised copy"
    assert error is not None


def _valid_pdf(path: Path) -> None:
    path.write_bytes(b"%PDF-1.7\n" + b"0" * 2048 + b"\n%%EOF\n")


def test_retries_with_headless_old_when_new_writes_no_pdf(tmp_path: Path, monkeypatch):
    src = tmp_path / "a.html"
    src.write_text("<p>ciao</p>", encoding="utf-8")
    out = tmp_path / "a.pdf"
    modes: list[str] = []

    def fake_run(argv: list[str], timeout_s: int) -> str | None:
        mode = next(a for a in argv if a.startswith("--headless"))
        modes.append(mode)
        target = Path(next(a for a in argv if a.startswith("--print-to-pdf=")).split("=", 1)[1])
        if mode == "--headless=old":
            _valid_pdf(target)
        return None

    monkeypatch.setattr(edge, "_run", fake_run)
    assert html_to_pdf(src, out, edge=Path("msedge.exe")) is None
    assert modes == ["--headless=new", "--headless=old"]
    assert out.read_bytes().startswith(b"%PDF-")


def test_a_non_pdf_or_tiny_output_is_rejected(tmp_path: Path, monkeypatch):
    src = tmp_path / "a.html"
    src.write_text("<p>ciao</p>", encoding="utf-8")
    out = tmp_path / "a.pdf"

    def fake_run(argv: list[str], timeout_s: int) -> str | None:
        target = Path(next(a for a in argv if a.startswith("--print-to-pdf=")).split("=", 1)[1])
        target.write_bytes(b"%PDF-1.7 too small" if "--headless=new" in argv else b"<html>no</html>" * 200)
        return None

    monkeypatch.setattr(edge, "_run", fake_run)
    error = html_to_pdf(src, out, edge=Path("msedge.exe"))
    assert error and "PDF" in error
    assert not out.exists(), "an invalid output is never left behind as a document"


def test_a_stale_output_does_not_count_as_success(tmp_path: Path, monkeypatch):
    src = tmp_path / "a.html"
    src.write_text("<p>ciao</p>", encoding="utf-8")
    out = tmp_path / "a.pdf"
    _valid_pdf(out)
    monkeypatch.setattr(edge, "_run", lambda argv, timeout_s: None)
    assert html_to_pdf(src, out, edge=Path("msedge.exe")) is not None


def test_edge_missing_is_reported(tmp_path: Path, monkeypatch):
    src = tmp_path / "a.html"
    src.write_text("<p>ciao</p>", encoding="utf-8")
    monkeypatch.setattr(edge, "find_edge", lambda: None)
    error = html_to_pdf(src, tmp_path / "a.pdf")
    assert error and "Edge" in error


def test_edge_is_started_offline_with_a_throwaway_profile(tmp_path: Path, monkeypatch):
    src = tmp_path / "a.html"
    src.write_text("<p>ciao</p>", encoding="utf-8")
    seen: list[list[str]] = []
    monkeypatch.setattr(edge, "_run", lambda argv, timeout_s: seen.append(argv))
    html_to_pdf(src, tmp_path / "a.pdf", edge=Path("msedge.exe"))
    argv = seen[0]
    assert any(a.startswith("--user-data-dir=") for a in argv)
    assert any(a.startswith("--proxy-server=") for a in argv)
    assert any(a.startswith("--host-resolver-rules=") for a in argv)
    assert not any(a.startswith("--blink-settings") for a in argv), "it breaks --print-to-pdf"


def test_stale_edge_profiles_are_swept(tmp_path: Path, monkeypatch):
    import os
    import tempfile
    import time

    temp = tmp_path / "temp"
    temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temp))
    old = temp / "qtr-edge-old"
    fresh = temp / "qtr-edge-fresh"
    other = temp / "someone-else"
    for d in (old, fresh, other):
        (d / "Default").mkdir(parents=True)
    two_days_ago = time.time() - 2 * 24 * 3600
    for d in (old, other):
        os.utime(d, (two_days_ago, two_days_ago))
    src = tmp_path / "a.html"
    src.write_text("<p>ciao</p>", encoding="utf-8")
    monkeypatch.setattr(edge, "_run", lambda argv, timeout_s: None)
    html_to_pdf(src, tmp_path / "a.pdf", edge=Path("msedge.exe"))
    assert not old.exists()
    assert fresh.exists() and other.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="the fake msedge is a Windows .cmd")
def test_edge_failure_is_reported(tmp_path: Path):
    """A fake msedge that exits 0 and writes nothing (the known regression)."""
    log = tmp_path / "calls.txt"
    fake = tmp_path / "msedge.cmd"
    fake.write_text(f'@echo off\r\necho %*>>"{log}"\r\nexit /b 0\r\n', encoding="ascii")
    src = tmp_path / "a.html"
    src.write_text("<p>ciao</p>", encoding="utf-8")
    out = tmp_path / "a.pdf"
    error = html_to_pdf(src, out, edge=fake, timeout_s=30)
    assert error is not None and "PDF" in error
    assert not out.exists()
    calls = log.read_text(encoding="ascii").splitlines()
    assert len(calls) == 2, "tried once, retried once"
    assert "--headless=new" in calls[0] and "--headless=old" in calls[1]


def test_timeout_is_reported(tmp_path: Path, monkeypatch):
    src = tmp_path / "a.html"
    src.write_text("<p>ciao</p>", encoding="utf-8")
    monkeypatch.setattr(edge, "_run", lambda argv, timeout_s: f"Edge non ha risposto entro {timeout_s} s")
    error = html_to_pdf(src, tmp_path / "a.pdf", edge=Path("msedge.exe"), timeout_s=7)
    assert error and "7 s" in error


@pytest.mark.skipif(find_edge() is None, reason="Microsoft Edge not installed")
def test_real_edge_renders_synthetic_html(tmp_path: Path):
    src = tmp_path / "email.html"
    src.write_text(HTML, encoding="utf-8")
    out = tmp_path / "email.pdf"
    assert html_to_pdf(src, out, timeout_s=60) is None
    data = out.read_bytes()
    assert data.startswith(b"%PDF-") and len(data) > 1024
    from qtrequestory.officina.compare.extract_pdf import extract

    doc = extract(out)
    words = {w.text: w for w in doc.words}
    assert "MOD_TEST_EMAIL" in words and "sintetica." in words
    # The inline style (32px paragraph) applied under the CSP:
    styled, body = words["grande"], words["sintetica."]
    assert styled.y1 - styled.y0 > 1.6 * (body.y1 - body.y0)
    # The data: image rendered under the CSP (img-src data:): a blocked image
    # would print its alt text instead, as the blanked external ones do.
    assert "punto" not in words
    assert "pixel" in words, "a blanked image prints its alt text (the check above is meaningful)"
