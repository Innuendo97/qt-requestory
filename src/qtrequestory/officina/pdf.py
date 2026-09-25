"""The one place ``qtrequestory.officina`` imports ``pypdfium2``.

Every other module in this package — and everything outside it, including
``qtrequestory.cli`` — must reach PDF rendering/extraction through this
module rather than importing ``pypdfium2`` directly, so that importing
``qtrequestory.officina`` (or running ``--sync``) never loads it. See
``tests/test_officina_boundary.py``.
"""
from __future__ import annotations

import ctypes
import threading
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c


#: PDFium is not thread-safe: every call into it from this module holds this
#: lock, so the viewer's render threads and an extraction running in a worker
#: never enter PDFium at the same time.
_LOCK = threading.RLock()


class PdfReadError(ValueError):
    """The file is not a PDF PDFium can read (damaged, encrypted, not a PDF).

    The message is Italian and meant for the user. A missing file still raises
    ``FileNotFoundError``.
    """


def _open_pdf(path: Path) -> pdfium.PdfDocument:
    """Open ``path`` as a pypdfium2 document (:class:`PdfReadError` if unreadable).

    Private: the caller must hold :data:`_LOCK` for as long as it uses the
    document (PDFium is not thread-safe).
    """
    try:
        return pdfium.PdfDocument(str(path))
    except pdfium.PdfiumError as exc:
        raise PdfReadError(f"impossibile leggere il PDF {Path(path).name}: {exc}") from exc


Box = tuple[float, float, float, float]


@dataclass(frozen=True)
class PageChars:
    """The raw text layer of one page, for ``compare.extract_pdf``.

    ``width``/``height`` are the page as DISPLAYED (after its CropBox and
    /Rotate). ``chars`` holds ``(text, text_box, display_box)`` per character
    in PDFium's order; a box is ``(x0, y0, x1, y1)``:

    * ``display_box``: points of the displayed page, origin at its TOP-left —
      where a viewer shows the glyph;
    * ``text_box``: unrotated user space with y pointing down — the text's own
      direction, for grouping characters into words and lines even on a
      rotated page.

    Whitespace and characters PDFium generated (implicit spaces, line breaks)
    come with ``None`` boxes: they only separate words. PDFium reports
    a hyphen at a line end as U+0002; it is returned as ``"-"``. A glyph with
    no Unicode mapping becomes U+FFFD, so its word stays whole.
    """
    width: float
    height: float
    chars: list[tuple[str, Box | None, Box | None]]
    image_count: int


def read_chars(path: Path) -> list[PageChars]:
    """Every page's characters with loose glyph boxes, and its image count.

    The lock is taken per page, not for the whole document, so a long
    extraction in a worker never keeps the viewer's render threads waiting
    for more than one page. Safe: this document object is private to the
    call and every PDFium call on it (open, page, close) still holds the lock.
    """
    with _LOCK:
        doc = _open_pdf(path)
    try:
        with _LOCK:
            count = len(doc)
        pages = []
        for i in range(count):
            with _LOCK:
                pages.append(_page_chars(doc[i]))
        return pages
    except pdfium.PdfiumError as exc:
        raise PdfReadError(f"impossibile leggere il PDF {Path(path).name}: {exc}") from exc
    finally:
        with _LOCK:
            doc.close()


def page_count(path: Path) -> int:
    """How many pages ``path`` has (:class:`PdfReadError` if unreadable)."""
    with _LOCK:
        doc = _open_pdf(path)
        try:
            return len(doc)
        finally:
            doc.close()


def page_sizes(path: Path) -> list[tuple[float, float]]:
    """Every page's DISPLAYED size in points (CropBox and /Rotate applied) —
    the sizes ``compare.extract_pdf`` reports and the viewer lays out, without
    reading the text (:class:`PdfReadError` if unreadable)."""
    with _LOCK:
        doc = _open_pdf(path)
        try:
            sizes = []
            for i in range(len(doc)):
                page = doc[i]
                try:
                    sizes.append(tuple(page.get_size()))
                finally:
                    page.close()
            return sizes
        except pdfium.PdfiumError as exc:
            raise PdfReadError(f"impossibile leggere il PDF {Path(path).name}: {exc}") from exc
        finally:
            doc.close()


@dataclass(frozen=True)
class RenderedPage:
    """One page as pixels: 32-bit ``B, G, R, x`` rows of ``stride`` bytes.

    That is ``QImage.Format_RGB32`` on a little-endian machine; this module
    stays Qt-free, the viewer wraps the bytes.
    """
    width: int
    height: int
    stride: int
    data: bytes


def render_page(path: Path, page: int, scale: float) -> RenderedPage:
    """Render page ``page`` (0-based) of ``path`` at ``scale`` pixels per point.

    The page is rendered as DISPLAYED — its CropBox and /Rotate applied, on a
    white background — which is the space the ``compare.extract_pdf`` Word
    boxes live in, so a box times ``scale`` lands on its word's ink. Raises
    ``IndexError`` for a page the document does not have, :class:`PdfReadError`
    for a file PDFium cannot read, ``FileNotFoundError`` for a missing one.
    """
    with _LOCK:
        doc = _open_pdf(path)
        try:
            if not 0 <= page < len(doc):
                raise IndexError(f"{Path(path).name} non ha la pagina {page + 1}")
            pdf_page = doc[page]
            try:
                bitmap = pdf_page.render(
                    scale=scale,
                    rotation=0,  # extra rotation only: the page's own /Rotate is always applied
                    may_draw_forms=True,
                    fill_color=(255, 255, 255, 255),
                    force_bitmap_format=pdfium_c.FPDFBitmap_BGRx,
                    draw_annots=True,
                )
                try:
                    return RenderedPage(bitmap.width, bitmap.height, bitmap.stride,
                                        bytes(bitmap.buffer))
                finally:
                    bitmap.close()
            finally:
                pdf_page.close()
        except pdfium.PdfiumError as exc:
            raise PdfReadError(f"impossibile leggere il PDF {Path(path).name}: {exc}") from exc
        finally:
            doc.close()


#: Device scale used to read PDFium's page-to-display transform exactly
#: (FPDF_PageToDevice returns whole device pixels).
_SCALE = 1000


def _display_transform(page: pdfium.PdfPage, width: float, height: float):
    """PDF user space -> displayed page (points, top-left origin).

    Built from ``FPDF_PageToDevice``, so it applies the CropBox offset and the
    page's /Rotate exactly as a viewer does.
    """
    dev_w, dev_h = round(width * _SCALE), round(height * _SCALE)

    def device(x: float, y: float) -> tuple[float, float]:
        dx, dy = ctypes.c_int(), ctypes.c_int()
        pdfium_c.FPDF_PageToDevice(page.raw, 0, 0, dev_w, dev_h, 0, x, y, dx, dy)
        return dx.value / _SCALE, dy.value / _SCALE

    ox, oy = device(0, 0)
    ax, ay = device(1000, 0)
    bx, by = device(0, 1000)
    a, b = (ax - ox) / 1000, (ay - oy) / 1000   # d(display)/dx
    c, d = (bx - ox) / 1000, (by - oy) / 1000   # d(display)/dy

    def apply(x: float, y: float) -> tuple[float, float]:
        return ox + a * x + c * y, oy + b * x + d * y

    return apply


def _page_chars(page: pdfium.PdfPage) -> PageChars:
    """One page's characters.

    The text page is built with the page's /Rotate neutralised (in memory only;
    the document is never saved): on a page rotated 180°, PDFium's text page
    takes the upside-down text for right-to-left and returns it reversed and
    split. Glyph boxes are in user space either way; the REAL rotation is then
    applied to them by the display transform, computed before neutralising.
    """
    textpage = None
    rotation = 0
    try:
        width, height = page.get_size()
        images = sum(1 for _ in page.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE]))
        to_display = _display_transform(page, width, height)
        chars: list[tuple[str, Box | None, Box | None]] = []
        rotation = page.get_rotation()
        if rotation:
            page.set_rotation(0)
        textpage = page.get_textpage()
        raw = textpage.raw
        for i in range(textpage.count_chars()):
            code = pdfium_c.FPDFText_GetUnicode(raw, i)
            generated = pdfium_c.FPDFText_IsGenerated(raw, i) == 1
            if code == 2:
                ch = "-"
            elif 0 < code < 0x110000:
                ch = chr(code)
            else:
                ch = " " if generated else "\ufffd"
            if ch.isspace() or (generated and code != 2):
                chars.append((" ", None, None))
                continue
            left, bottom, right, top = textpage.get_charbox(i, loose=True)
            x_a, y_a = to_display(left, bottom)
            x_b, y_b = to_display(right, top)
            chars.append((
                ch,
                (left, -top, right, -bottom),
                (min(x_a, x_b), min(y_a, y_b), max(x_a, x_b), max(y_a, y_b)),
            ))
        return PageChars(width, height, chars, images)
    finally:
        if textpage is not None:
            textpage.close()
        if rotation:
            page.set_rotation(rotation)  # leave the in-memory document as it was
        page.close()
