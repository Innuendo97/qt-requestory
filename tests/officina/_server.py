"""A fake documentGenerator on loopback, shared by the Officina and Genera tests.

Every HTTP call of the test suite goes to this local ``http.server`` in a
thread — never to a real endpoint. Synthetic data only (public repository).

By default every POST gets ``server.canned``. A test that needs a different
answer per request (or to hold a request on the wire) sets ``server.route``:
a callable ``(headers, body) -> Canned`` run in the request's thread.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PDF = b"%PDF-1.7\n" + b"0" * 2000 + b"\n%%EOF\n"
HTML = b"<!DOCTYPE html>\n<html><body>" + b"<p>MOD_TEST corpo email</p>" * 40 + b"</body></html>"


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
        #: When set, picks the answer of each request instead of ``canned``.
        self.route: Callable[[dict[str, str], bytes], Canned] | None = None
        self.requests: list[tuple[dict[str, str], bytes]] = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                headers, body = dict(self.headers.items()), self.rfile.read(length)
                server.requests.append((headers, body))
                route = server.route
                canned = route(headers, body) if route is not None else server.canned
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
