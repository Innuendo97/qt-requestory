"""Test helper for the control generation (task A5): a LOCAL fake document
generator that renders the payload it receives into a PDF (so a perturbed
payload gives a different document), and a tiny PDF writer with positioned
text. Never a real endpoint; synthetic data only (public repository).

The fake generator's "template" (:func:`render`) prints, on one A4 page in
Helvetica 8 pt, two running lines, «Quota vale <NOME> euro al periodo»
(``cliente.nome`` in capitals), «Importo <importo> euro», «Decorrenza
<gg/mm/aaaa>», two running lines; ``offerta.piano`` other than «BASE» adds a
second page (a condition: the structure changes). ``extra_top`` shifts
everything down by one line (a template change between two versions).
"""
from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from tests.fakes.fake_officina import canned_pdf

#: Helvetica advance widths (per 1000 em) of the characters the tests print.
_WIDTHS = {" ": 278, ",": 278, ".": 278, "/": 278, "-": 333, ":": 278}
_WIDTHS.update({c: 556 for c in "0123456789"})
_WIDTHS.update(dict(zip("abcdefghijklmnopqrstuvwxyz",
                        (556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333,
                         500, 278, 556, 500, 722, 500, 500, 500), strict=True)))
_WIDTHS.update(dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ",
                        (667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778, 667, 778, 722,
                         667, 611, 722, 667, 944, 667, 667, 611), strict=True)))
SIZE = 8.0
LEFT = 60.0
STEP = 14.0
TOP = 100.0

RUNNING = ("lorem ipsum dolor sitame consec adipis elitse doeius tempor incidi utlabo",
           "magna aliqua enimad minimv eniamq nostru exerci tation ullamc laboris nisiut",
           "aliquip exeaco commod consequ duisau irured dolori reprehe volupt velites",
           "cillum dolore fugiat nullap pariat excepte sintoc cupida proide suntin culpaq")


def width(text: str) -> float:
    """The width of ``text`` in Helvetica at :data:`SIZE` pt."""
    return sum(_WIDTHS.get(c, 556) for c in text) * SIZE / 1000


def pdf(pages: list[list[tuple]]) -> bytes:
    """A PDF whose pages hold ``(x, top, text)`` pieces (Helvetica 8 pt; ``top``
    from the top of an A4 page); a fourth item is the text render mode (3: invisible)."""
    objects: list[bytes] = [b"<< /Type /Catalog /Pages 2 0 R >>", b""]
    kids = []
    for pieces in pages:
        ops = ["BT", f"/F1 {SIZE:g} Tf"]
        for x, top, text, *mode in pieces:
            esc = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            ops.append(f"{mode[0] if mode else 0} Tr 1 0 0 1 {x:.2f} {842 - top - SIZE:.2f} Tm ({esc}) Tj")
        ops.append("ET")
        stream = "\n".join(ops).encode("cp1252")
        page_no = len(objects) + 1
        kids.append(page_no)
        objects.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                       b"/Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>" % (page_no + 2, page_no + 1))
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    objects[1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (b" ".join(b"%d 0 R" % k for k in kids), len(kids))
    out = bytearray(b"%PDF-1.4\n%" + b"0" * 1100 + b"\n")
    offsets = []
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % off for off in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


def _lines(middle: list[str], extra_top: bool) -> list[tuple[float, float, str]]:
    lines = ([RUNNING[3]] if extra_top else []) + [RUNNING[0], RUNNING[1], *middle, RUNNING[2], RUNNING[3]]
    return [(LEFT, TOP + STEP * k, line) for k, line in enumerate(lines)]


def render(payload: dict, *, extra_top: bool = False, label: bool = False) -> bytes:
    """The fake template applied to ``payload`` (module doc); ``label``: one
    more line whose WORDING depends on the amount (a condition, not a value)."""
    cliente = payload.get("cliente", {})
    offerta = payload.get("offerta", {})
    importo = f"{float(offerta.get('importo', 0)):.2f}".replace(".", ",")
    day = str(offerta.get("decorrenza", "2026-01-01"))[:10].split("-")
    pages = [_lines([f"Quota vale {str(cliente.get('nome', '')).upper()} euro al periodo",
                     f"Importo {importo} euro", f"Decorrenza {day[2]}/{day[1]}/{day[0]}"]
                    + ([f"Tariffa {'standard' if importo == '12,50' else 'variata'} applicata"] if label else []),
                    extra_top)]
    if offerta.get("piano", "BASE") != "BASE":
        pages.append([(LEFT, TOP, "Condizioni aggiuntive del piano")])
    return pdf(pages)


def target() -> bytes:
    """The customer's TARGET: «Quota vale» and «euro al periodo» with a room
    for a four-capital value between them; the other values as generated."""
    room = width(" ") + width("ALFA") + width(" ")
    quota = [(LEFT, TOP + 2 * STEP, "Quota vale"), (LEFT + width("Quota vale") + room, TOP + 2 * STEP,
                                                     "euro al periodo")]
    lines = [p for p in _lines(["", "Importo 12,50 euro", "Decorrenza 18/03/2026"], False) if p[2]]
    return pdf([lines[:2] + quota + lines[2:]])


def payload(nome: str = "Alfa", **offerta) -> dict:
    """A synthetic payload: the template key and the upload link are plumbing."""
    return {
        "documents": [{"template": {"templateKey": "MOD_TEST_A"},
                       "attributes": [{"key": "attachmentId", "value": "att-0"},
                                      {"key": "attachmentUrl", "value": "https://example.invalid/blob/doc.pdf"}]}],
        "cliente": {"nome": nome, "clienteId": "CL-000001"},
        "offerta": {"importo": 12.5, "decorrenza": "2026-03-18", "tipoOfferta": "FISSA", **offerta},
    }


@dataclass
class Answer:
    status: int = 200
    body: bytes | None = None       # None: the rendered payload
    delay_s: float = 0.0


@dataclass
class ControlServer:
    """A local generator: every request is recorded; ``answer(n, payload)``
    (``n`` = 0 for the first request) decides the reply (default: the render)."""

    answer: Callable[[int, dict], Answer] = lambda n, body: Answer()
    extra_top: bool = False
    requests: list[tuple[dict[str, str], dict]] = field(default_factory=list)

    def __post_init__(self) -> None:
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                n = len(server.requests)
                server.requests.append((dict(self.headers.items()), body))
                reply = server.answer(n, body)
                if reply.delay_s:
                    time.sleep(reply.delay_s)
                content = reply.body if reply.body is not None else render(body, extra_top=server.extra_top)
                try:
                    self.send_response(reply.status)
                    self.send_header("Content-Length", str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)
                except OSError:
                    pass  # the client gave up (timeout)

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


__all__ = ["Answer", "ControlServer", "canned_pdf", "payload", "pdf", "render", "target", "width"]
