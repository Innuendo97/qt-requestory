"""The one place ``qtrequestory.officina`` imports ``pypdfium2``.

Every other module in this package — and everything outside it, including
``qtrequestory.cli`` — must reach PDF rendering/extraction through this
module rather than importing ``pypdfium2`` directly, so that importing
``qtrequestory.officina`` (or running ``--sync``) never loads it. See
``tests/test_officina_boundary.py``.
"""
from __future__ import annotations

import ctypes
import math
import re
import threading
from dataclasses import dataclass, field
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

    ``fonts`` runs parallel to ``chars``: ``(size in points, bold)`` for a
    character that may open a word — the first of the page and every one
    after a separator — and ``None`` elsewhere (sampling every glyph would
    cost ~30% of the extraction). The size is the one DISPLAYED (the font
    size times the text matrix and CTM scale); bold comes from :func:`is_bold`.
    Empty when nothing was sampled.
    """
    width: float
    height: float
    chars: list[tuple[str, Box | None, Box | None]]
    image_count: int
    fonts: list[tuple[float, bool] | None] = field(default_factory=list)


#: Font-name markers of a bold face (matched case-insensitively).
_BOLD_NAMES = ("bold", "black", "heavy")  # "bold" also covers "Semibold"
#: A font subset's tag: six capitals and a plus ("ABCDEF+Arial-BoldMT").
_SUBSET = re.compile(r"^[A-Z]{6}\+")


def font_name(raw: bytes) -> str:
    """A font's base name as PDFium returns it, without the subset tag."""
    return _SUBSET.sub("", raw.decode("latin-1").rstrip("\0"))


def is_bold(weight: int, name: str) -> bool:
    """Whether a font is bold: by its weight when PDFium knows it (≥ 600), and
    by its name either way ("Bold", "Black", "Heavy", "Semibold"): PDFium
    derives the weight from the stem width, which puts a real bold face well
    under 600 (Arial Bold reads 520)."""
    lowered = name.lower()
    return weight >= 600 or any(marker in lowered for marker in _BOLD_NAMES)


class _FontSampler:
    """Reads one character's font from a text page (buffers reused)."""

    def __init__(self, textpage_raw) -> None:
        self._raw = textpage_raw
        self._name = ctypes.create_string_buffer(256)
        self._flags = ctypes.c_int()
        self._matrix = pdfium_c.FS_MATRIX()

    def __call__(self, index: int) -> tuple[float, bool]:
        size = pdfium_c.FPDFText_GetFontSize(self._raw, index)
        if pdfium_c.FPDFText_GetMatrix(self._raw, index, ctypes.byref(self._matrix)):
            m = self._matrix
            size *= math.sqrt(abs(m.a * m.d - m.b * m.c))
        length = pdfium_c.FPDFText_GetFontInfo(self._raw, index, self._name, len(self._name),
                                               ctypes.byref(self._flags))
        name = font_name(self._name.raw[:length]) if 0 < length <= len(self._name) else ""
        weight = pdfium_c.FPDFText_GetFontWeight(self._raw, index)
        return round(size, 2), is_bold(weight, name)


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


class TextSearch:
    """Where a text occurs in a PDF: ``search(text)`` gives ``(page, box)``
    per occurrence, the box in points of the page as DISPLAYED, origin
    top-left (the viewer's space), the union of the occurrence's rects on its
    page. Case-sensitive; PDFium's own search (a text broken over two lines
    in the file is not found as a whole). For ``compare.extract_html.locate``.

    The document stays open until :meth:`close` (a context manager); every
    PDFium call holds :data:`_LOCK`. After ``close`` a search finds nothing.
    :class:`PdfReadError` when the file cannot be read.
    """

    def __init__(self, path: Path) -> None:
        with _LOCK:
            self._doc: pdfium.PdfDocument | None = _open_pdf(path)

    def __enter__(self) -> TextSearch:
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def close(self) -> None:
        with _LOCK:
            if self._doc is not None:
                self._doc.close()
                self._doc = None

    def __call__(self, text: str) -> list[tuple[int, Box]]:
        out: list[tuple[int, Box]] = []
        if not text:
            return out
        with _LOCK:
            if self._doc is None:
                return out
            try:
                for number in range(len(self._doc)):
                    out.extend((number, box) for box in _occurrences(self._doc[number], text))
            except pdfium.PdfiumError:
                return []
        return out


def _occurrences(page: pdfium.PdfPage, text: str) -> list[Box]:
    """Display boxes of ``text`` on ``page`` (the caller holds the lock)."""
    textpage = searcher = None
    try:
        width, height = page.get_size()
        to_display = _display_transform(page, width, height)
        textpage = page.get_textpage()
        searcher = textpage.search(text, match_case=True)
        boxes: list[Box] = []
        while (found := searcher.get_next()) is not None:
            index, count = found
            corners = []
            for i in range(textpage.count_rects(index, count)):
                left, bottom, right, top = textpage.get_rect(i)
                corners += [to_display(left, bottom), to_display(right, top)]
            if corners:
                xs, ys = [x for x, _ in corners], [y for _, y in corners]
                boxes.append((min(xs), min(ys), max(xs), max(ys)))
        return boxes
    finally:
        if searcher is not None:
            searcher.close()
        if textpage is not None:
            textpage.close()
        page.close()


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
        fonts: list[tuple[float, bool] | None] = []
        rotation = page.get_rotation()
        if rotation:
            page.set_rotation(0)
        textpage = page.get_textpage()
        raw = textpage.raw
        sample = _FontSampler(raw)
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
                fonts.append(None)
                continue
            left, bottom, right, top = textpage.get_charbox(i, loose=True)
            x_a, y_a = to_display(left, bottom)
            x_b, y_b = to_display(right, top)
            chars.append((
                ch,
                (left, -top, right, -bottom),
                (min(x_a, x_b), min(y_a, y_b), max(x_a, x_b), max(y_a, y_b)),
            ))
            opens_word = len(chars) == 1 or chars[-2][1] is None
            fonts.append(sample(i) if opens_word else None)
        return PageChars(width, height, chars, images, fonts)
    finally:
        if textpage is not None:
            textpage.close()
        if rotation:
            page.set_rotation(rotation)  # leave the in-memory document as it was
        page.close()
