"""UrllibHttpClient against the synthetic stub server (no real hosts ever)."""
from __future__ import annotations

import http.server
import threading
import time
from pathlib import Path

import pytest

from qtrequestory import __version__
from qtrequestory.core.events import CancelToken, Cancelled
from qtrequestory.core.http import HttpDownloadError, HttpUnreachable, UrllibHttpClient


@pytest.fixture
def client() -> UrllibHttpClient:
    return UrllibHttpClient()


# --------------------------------------------------------------- get_text ---

def test_get_text_returns_body(stub_server, client):
    stub_server.add("/AutoDeploy/Input/", "<html>cità</html>", content_type="text/html; charset=utf-8")
    assert client.get_text(stub_server.url + "/AutoDeploy/Input/", timeout=5) == "<html>cità</html>"
    assert stub_server.requests == [("GET", "/AutoDeploy/Input/")]


def test_get_text_sends_user_agent(client):
    """The stub fixture does not record headers, so use a tiny capturing server."""
    seen: dict[str, str] = {}

    class Capture(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            seen["ua"] = self.headers.get("User-Agent", "")
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Capture)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        client.get_text(f"http://127.0.0.1:{srv.server_address[1]}/ua", timeout=5)
    finally:
        srv.shutdown()
        srv.server_close()
    assert seen["ua"] == f"qtRequestory/{__version__}"


@pytest.mark.parametrize("status", [404, 500])
def test_get_text_http_error_is_unreachable(stub_server, client, status):
    stub_server.add("/err", "boom", status=status)
    with pytest.raises(HttpUnreachable):
        client.get_text(stub_server.url + "/err", timeout=5)


def test_get_text_closed_port_is_unreachable(stub_server, client):
    stub_server.stop()  # port is now closed; fixture teardown tolerates a second stop
    with pytest.raises(HttpUnreachable):
        client.get_text(stub_server.url + "/AutoDeploy/Input/", timeout=5)


def test_get_text_hang_times_out_quickly(stub_server, client):
    stub_server.add("/slow", "never", hang=True)
    t0 = time.monotonic()
    with pytest.raises(HttpUnreachable):
        client.get_text(stub_server.url + "/slow", timeout=0.5)
    assert time.monotonic() - t0 < 2.0


# --------------------------------------------------------------- download ---

def _payload(n: int) -> bytes:
    return bytes(range(256)) * (n // 256) + bytes(range(n % 256))


def test_download_writes_exact_bytes_and_reports_progress(stub_server, client, tmp_path: Path):
    body = _payload(10_000)
    stub_server.add("/20260918.txt", body)
    dest = tmp_path / "coll" / "2026" / "09" / "20260918.txt.part"  # parent must be created
    progress: list[tuple[int, int | None]] = []

    n = client.download(
        stub_server.url + "/20260918.txt", dest,
        timeout=5, chunk_size=1024, on_progress=lambda d, t: progress.append((d, t)), cancel=CancelToken(),
    )

    assert n == len(body)
    assert dest.read_bytes() == body
    assert progress, "on_progress never called"
    dones = [d for d, _ in progress]
    assert dones == sorted(dones)
    assert dones[-1] == len(body)
    assert all(t == len(body) for _, t in progress)


def test_download_truncated_returns_fewer_bytes_without_raising(stub_server, client, tmp_path: Path):
    body = _payload(10_000)
    stub_server.add("/trunc.txt", body, truncate_after=4_000)
    dest = tmp_path / "trunc.txt.part"

    n = client.download(stub_server.url + "/trunc.txt", dest, timeout=5, chunk_size=1000,
                        on_progress=lambda d, t: None, cancel=CancelToken())

    assert n == 4_000 < len(body)
    assert dest.stat().st_size == 4_000


def test_download_cancelled_before_start_leaves_no_file(stub_server, client, tmp_path: Path):
    stub_server.add("/c.txt", _payload(5_000))
    dest = tmp_path / "c.txt.part"
    cancel = CancelToken()
    cancel.cancel()

    with pytest.raises(Cancelled):
        client.download(stub_server.url + "/c.txt", dest, timeout=5, chunk_size=1024,
                        on_progress=lambda d, t: None, cancel=cancel)
    assert not dest.exists()


def test_download_cancelled_mid_way_removes_partial(stub_server, client, tmp_path: Path):
    stub_server.add("/m.txt", _payload(50_000))
    dest = tmp_path / "m.txt.part"
    cancel = CancelToken()

    def progress(done: int, total: int | None) -> None:
        if done >= 2048:
            cancel.cancel()

    with pytest.raises(Cancelled):
        client.download(stub_server.url + "/m.txt", dest, timeout=5, chunk_size=1024,
                        on_progress=progress, cancel=cancel)
    assert not dest.exists()


def test_download_server_error_raises_and_leaves_no_file(stub_server, client, tmp_path: Path):
    stub_server.add("/e.txt", b"x" * 100, status=500)
    dest = tmp_path / "e.txt.part"
    with pytest.raises(HttpDownloadError):
        client.download(stub_server.url + "/e.txt", dest, timeout=5, chunk_size=1024,
                        on_progress=lambda d, t: None, cancel=CancelToken())
    assert not dest.exists()


def test_download_closed_port_raises_download_error(stub_server, client, tmp_path: Path):
    url = stub_server.url + "/x.txt"
    stub_server.stop()
    dest = tmp_path / "x.txt.part"
    with pytest.raises(HttpDownloadError):
        client.download(url, dest, timeout=5, chunk_size=1024,
                        on_progress=lambda d, t: None, cancel=CancelToken())
    assert not dest.exists()
