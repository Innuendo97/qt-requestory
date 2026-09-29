"""Test helper: tiny PDFs written by hand, for what Qt cannot produce.

QPdfWriter has no optional content (OCG layers), no render mode 3 and no form
XObjects; the extraction must handle all three. These files use the standard
Helvetica font (no font file embedded; PDFium supplies its own metrics) and
synthetic text only (public repository).

A page is a content stream (bytes). Its resources name the font ``/F1``, the
optional-content group ``/oc1`` (OFF unless ``layer_on``) and, if ``forms``
is given, the form XObjects ``/Fm0``, ``/Fm1``… (each a content stream drawn
in a 200 x 100 box; the page places it with ``cm`` and ``Do``), and the image
``/Im0``: 2 x 2 grey pixels, drawn by :func:`image` (a scan, a logo).
"""
from __future__ import annotations

from pathlib import Path


def text(x: float, y: float, words: str, *, size: float = 12, fill: str = "0 g", mode: int = 0,
         tm: str = "") -> bytes:
    """One line of text at baseline ``(x, y)`` (PDF user space, origin bottom-left).

    ``fill`` is a colour operator (``"1 g"`` = white); ``mode`` the render mode
    (3 = invisible); ``tm`` an optional ``a b c d`` text matrix (rotation)."""
    place = f"{tm} {x} {y} Tm" if tm else f"{x} {y} Td"
    return f"q {fill} BT {mode} Tr /F1 {size} Tf {place} ({words}) Tj ET Q\n".encode("latin-1")


def hidden_layer(content: bytes) -> bytes:
    """``content`` marked as belonging to the optional-content group ``/oc1``."""
    return b"/OC /oc1 BDC\n" + content + b"EMC\n"


def image(x: float, y: float, w: float, h: float) -> bytes:
    """The image ``/Im0`` stretched over a ``w`` x ``h`` box at ``(x, y)``."""
    return f"q {w} 0 0 {h} {x} {y} cm /Im0 Do Q\n".encode("latin-1")


def rect(x: float, y: float, w: float, h: float, *, fill: str = "0 0 0.5 rg") -> bytes:
    """A filled rectangle (a coloured background)."""
    return f"q {fill} {x} {y} {w} {h} re f Q\n".encode("latin-1")


def raw_pdf(path: Path, pages: list[bytes], *, layer_on: bool = False, forms: list[bytes] = (),
            size: tuple[float, float] = (595, 842), rotate: int = 0) -> Path:
    """Write ``pages`` (content streams) as a PDF at ``path``."""
    objects: list[bytes | None] = []

    def add(body: bytes | None) -> int:
        objects.append(body)
        return len(objects)

    def stream(body: bytes, extra: bytes = b"") -> bytes:
        return b"<< /Length %d %s>>\nstream\n" % (len(body), extra) + body + b"\nendstream"

    catalog, tree = add(None), add(None)
    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    layer = add(b"<< /Type /OCG /Name (Livello di prova) >>")
    shared = b"/Font << /F1 %d 0 R >> /Properties << /oc1 %d 0 R >>" % (font, layer)
    form_ids = [add(stream(body, b"/Type /XObject /Subtype /Form /BBox [0 0 200 100] /Resources << %s >> "
                           % shared)) for body in forms]
    pixels = bytes([200, 180, 160, 220])
    picture = add(stream(pixels, b"/Type /XObject /Subtype /Image /Width 2 /Height 2 /ColorSpace /DeviceGray "
                                 b"/BitsPerComponent 8 "))
    xobjects = b" ".join([b"/Fm%d %d 0 R" % (i, ref) for i, ref in enumerate(form_ids)] + [b"/Im0 %d 0 R" % picture])
    kids = []
    for content in pages:
        body = add(stream(content))
        kids.append(add(b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %g %g] /Rotate %d /Contents %d 0 R "
                        b"/Resources << %s /XObject << %s >> >> >>"
                        % (tree, size[0], size[1], rotate, body, shared, xobjects)))
    objects[tree - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
        b" ".join(b"%d 0 R" % k for k in kids), len(kids))
    state = b"/ON" if layer_on else b"/OFF"
    objects[catalog - 1] = (b"<< /Type /Catalog /Pages %d 0 R /OCProperties << /OCGs [%d 0 R] /D << %s [%d 0 R] >> >> >>"
                            % (tree, layer, state, layer))
    out = bytearray(b"%PDF-1.7\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, catalog, xref)
    Path(path).write_bytes(bytes(out))
    return Path(path)
