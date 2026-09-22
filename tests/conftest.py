"""Shared fixtures. Everything here is SYNTHETIC: this repository is public and
must never contain real log data, hostnames or customer information.
"""
from __future__ import annotations

import http.server
import json
import threading
import time as _time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Callable

import pytest

from qtrequestory.core.events import CollectingSink

# ------------------------------------------------------------ log bodies ---

FDI_A = "aaaaaaaa-1111-4222-8333-444444444444"
FDI_B = "bbbbbbbb-1111-4222-8333-444444444444"
FDI_C = "cccccccc-1111-4222-8333-444444444444"
KEY_CTE = "CTR_PLAN_FIX_GAS"
KEY_SINT = "MOD_TEST_SUMMARY_PLAN_FIX_GAS"
KEY_EMAIL = "MOD_TEST_EMAIL_GAS"
KEY_NUMERIC = "2_DECLARATION_CONS_PAPER_RP"


def synthetic_body(
    fdi: str,
    key: str,
    *,
    request_date: str | None = "2026-09-18T10:38:28.776Z",
    ndocs: int = 2,
    noise: bool = True,
    dossier_number: str = "DA00000001",
) -> bytes:
    """One request body on ONE line, shaped like the real payloads.

    ``noise=True`` adds a ``templateKey`` inside ``customData`` and nested
    ``childDocuments`` so that counting the string with a regex over-counts;
    the correct ``ndocs`` is ``len(documents)``.
    """
    documents = []
    for i in range(ndocs):
        doc = {
            "aggregateType": "SINGOLO",
            "template": {"templateKey": key if i == 0 else f"ATTACH_{i}"},
            "attributes": [{"key": "attachmentId", "value": f"att-{i}"}],
        }
        if noise and i == 0:
            doc["childDocuments"] = [{"template": {"templateKey": "CHILD_DOC"}}]
        documents.append(doc)
    dossier: dict = {"id": "dossier-" + fdi[:8], "number": dossier_number, "operation": "Attivazione"}
    if request_date is not None:
        dossier["requestDate"] = request_date
    body: dict = {
        "documents": documents,
        "dossier": dossier,
        "customers": [{"name": "Màrio", "surname": "Rossì", "note": "città"}],
        "products": [],
        "customData": {"templateKey": "NOISE"} if noise else None,
    }
    return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def entry_name(fdi: str, key: str, call_id: str = "1a2b3c0200000031") -> str:
    return f"{fdi}_{key}_{call_id}"


def make_daily_file(
    root: Path,
    env: str,
    day: date,
    entries: list[tuple[str, bytes | None]],
    *,
    crlf: bool = True,
    orphan_body_at: int | None = None,
) -> Path:
    """Write ``<root>/<env>/YYYY/MM/YYYYMMDD.txt``.

    ``entries`` is a list of ``(name, body)``; ``body=None`` writes a header with
    no body (the next line is another header). ``orphan_body_at=i`` inserts a
    body line without header before entry ``i``.
    """
    nl = b"\r\n" if crlf else b"\n"
    path = root / env / f"{day:%Y}" / f"{day:%m}" / f"{day:%Y%m%d}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    chunks: list[bytes] = []
    for i, (name, body) in enumerate(entries):
        if orphan_body_at == i:
            chunks.append(b'{"orphan":true}' + nl)
        chunks.append(b"### " + name.encode() + b".json" + nl)
        if body is not None:
            chunks.append(body + nl)
    path.write_bytes(b"".join(chunks))
    return path


@dataclass
class Mirror:
    root: Path
    files: dict[tuple[str, date], Path] = field(default_factory=dict)
    entries: dict[tuple[str, date], list[tuple[str, bytes | None]]] = field(default_factory=dict)


@pytest.fixture
def mirror(tmp_path: Path) -> Mirror:
    """Two envs, several days, every awkward shape found in real data."""
    root = tmp_path / "mirror"
    m = Mirror(root)

    def add(env, day, entries, **kw):
        m.files[(env, day)] = make_daily_file(root, env, day, entries, **kw)
        m.entries[(env, day)] = entries

    # coll, CRLF: newest day has a full "pratica" for FDI_A (3 entries), one for FDI_B,
    # a correlationId_vuoto entry, a -t15 test entry and a non-JSON body.
    add("coll", date(2026, 9, 18), [
        (entry_name(FDI_A, KEY_SINT, "1a2b3c0200000033"), synthetic_body(FDI_A, KEY_SINT, ndocs=3)),
        (entry_name(FDI_B, KEY_SINT, "1a2b3c0100000040"), synthetic_body(FDI_B, KEY_SINT, request_date="2026-09-18T12:10:43.279Z")),
        (entry_name(FDI_A, KEY_EMAIL, "1a2b3c0200000031"), synthetic_body(FDI_A, KEY_EMAIL, ndocs=5)),
        (entry_name(FDI_A, KEY_CTE, "1a2b3c0200000032"), synthetic_body(FDI_A, KEY_CTE, request_date=None)),
        ("correlationId_vuoto_MOD_TEST_R_1a2b3c0300000000", synthetic_body("00000000-0000-4000-8000-000000000000", "MOD_TEST_R")),
        (f"{FDI_C}-t15_{KEY_CTE}_1a2b3c0200000099", synthetic_body(FDI_C, KEY_CTE)),
        (entry_name(FDI_B, KEY_NUMERIC, "1a2b3c0100000041"), b'{"documents": [ not json'),
    ], crlf=True)
    # coll, older day, LF, with an orphan body line and a header without body
    add("coll", date(2026, 9, 15), [
        (entry_name(FDI_A, KEY_SINT, "1a2b3c0200000011"), synthetic_body(FDI_A, KEY_SINT, request_date="2026-09-15T08:00:00.000Z")),
        (entry_name(FDI_B, KEY_EMAIL, "1a2b3c0100000012"), None),
        (entry_name(FDI_C, KEY_CTE, "1a2b3c0200000013"), synthetic_body(FDI_C, KEY_CTE, request_date="2026-09-15T09:00:00.000Z")),
    ], crlf=False, orphan_body_at=0)
    # coll, much older
    add("coll", date(2026, 8, 3), [
        (entry_name(FDI_C, KEY_CTE, "1a2b3c0200000001"), synthetic_body(FDI_C, KEY_CTE, request_date="2026-08-03T07:26:09.78Z")),
    ])
    # svil, one small day
    add("svil", date(2026, 9, 16), [
        (entry_name(FDI_A, KEY_CTE, "1a2b3c0200000077"), synthetic_body(FDI_A, KEY_CTE, request_date="2026-09-16T10:00:00.000Z")),
    ], crlf=False)
    # a stray .part must be ignored by listings
    (root / "coll" / "2026" / "09" / "20260917.txt.part").write_bytes(b"partial")
    return m


# ------------------------------------------------------------- autoindex ---

def autoindex_html(entries: list[tuple[str, str, int]], loose: int = 0) -> str:
    """Reproduce the nginx autoindex layout: ``(name, 'dd-Mon-yyyy HH:MM', size)``."""
    lines = ['<html>', '<head><title>Index of /AutoDeploy/Input/</title></head>', '<body>',
             '<h1>Index of /AutoDeploy/Input/</h1><hr><pre><a href="../">../</a>']
    for i in range(loose):
        name = f"{FDI_A}_{KEY_SINT}_10b60136000000{i:02x}.json"
        shown = name[:50] + "..&gt;"
        lines.append(f'<a href="{name}">{shown}</a> 21-Sep-2026 10:03              147430')
    for name, when, size in entries:
        pad = " " * max(1, 51 - len(name))
        lines.append(f'<a href="{name}">{name}</a>{pad}{when}{size:>20}')
    lines += ['</pre><hr></body>', '</html>', '']
    return "\n".join(lines)


# ----------------------------------------------------------- stub server ---

@dataclass
class Route:
    body: bytes = b""
    status: int = 200
    truncate_after: int | None = None   # send only N bytes of body, then close
    hang: bool = False                  # never answer (timeouts)
    content_type: str = "text/html"


class StubServer:
    def __init__(self) -> None:
        self.routes: dict[str, Route] = {}
        self.requests: list[tuple[str, str]] = []
        self._server: http.server.ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def add(self, path: str, body: bytes | str, **kw) -> Route:
        if isinstance(body, str):
            body = body.encode("utf-8")
        r = Route(body=body, **kw)
        self.routes[path] = r
        return r

    @property
    def url(self) -> str:
        assert self._server is not None
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def start(self) -> None:
        stub = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):  # silence
                pass

            def _serve(self, send_body: bool) -> None:
                stub.requests.append((self.command, self.path))
                route = stub.routes.get(self.path)
                if route is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                if route.hang:
                    _time.sleep(30)
                    return
                self.send_response(route.status)
                self.send_header("Content-Type", route.content_type)
                self.send_header("Content-Length", str(len(route.body)))
                self.end_headers()
                if send_body and route.status == 200:
                    data = route.body if route.truncate_after is None else route.body[: route.truncate_after]
                    try:
                        self.wfile.write(data)
                    except ConnectionError:
                        pass
                    if route.truncate_after is not None:
                        self.close_connection = True

            def do_GET(self):
                self._serve(True)

            def do_HEAD(self):
                self._serve(False)

        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()


@pytest.fixture
def stub_server():
    s = StubServer()
    s.start()
    try:
        yield s
    finally:
        s.stop()


# ------------------------------------------------------------------ misc ---

class FakeClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw) -> None:
        from datetime import timedelta
        self.now += timedelta(**kw)


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock(datetime(2026, 9, 22, 9, 30))


@pytest.fixture
def events() -> CollectingSink:
    return CollectingSink()


@pytest.fixture
def app_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point %LOCALAPPDATA%-style app dir at a temp folder."""
    home = tmp_path / "apphome"
    monkeypatch.setenv("QTREQUESTORY_HOME", str(home))
    return home
