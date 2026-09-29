"""The one place ``qtrequestory.officina`` imports ``pypdfium2``: this package.

Every other module of ``qtrequestory.officina`` — and everything outside it,
including ``qtrequestory.cli`` — must reach PDF rendering/extraction through
this package's public API (here, in ``__init__``) rather than importing
``pypdfium2`` directly, so that importing ``qtrequestory.officina`` (or running
``--sync``) never loads it. See ``tests/test_officina_boundary.py``.

The private submodules (``_chars``, ``_objects``, ``_ink``, ``_geometry``) hold
the reading of a page; every call into them happens with :data:`_LOCK` held.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

from qtrequestory.officina.compare.graphics import PageGraphics
from qtrequestory.officina.pdf._chars import PageChars, font_name, is_bold
from qtrequestory.officina.pdf._chars import page_chars as _page_chars
from qtrequestory.officina.pdf._geometry import display_transform as _display_transform
from qtrequestory.officina.pdf._ink import hidden_layer_graphics as _hidden_layer_graphics
from qtrequestory.officina.pdf._objects import Reader as _Reader
from qtrequestory.officina.pdf._objects import graphics as _graphics

__all__ = ["Box", "PageChars", "PdfReadError", "RenderedPage", "TextSearch", "font_name", "is_bold",
           "page_count", "page_sizes", "read_chars", "read_graphics", "render_page"]


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
def read_chars(path: Path) -> list[PageChars]:
    """Every page's characters (see :class:`PageChars`: loose glyph boxes,
    tight ones for rotated text, the invisible ones marked after the ink test)
    and its graphics.

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
        layers: set[str] = set()  # optional-content layers seen drawing (document-wide state)
        for i in range(count):
            with _LOCK:
                pages.append(_page_chars(doc[i], layers))
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


def read_graphics(page: pdfium.PdfPage) -> PageGraphics:
    """The paths and images of ``page`` (form XObjects included, those of
    optional-content layers that are OFF left out), boxes on the page as
    DISPLAYED (points, top-left origin, like word boxes). The caller holds
    :data:`_LOCK`; the page is left as it was."""
    width, height = page.get_size()
    to_display = _display_transform(page, width, height)
    reader = _Reader()
    objects = reader.objects(page)
    rotation = page.get_rotation()
    if rotation:
        page.set_rotation(0)
    try:
        hidden = _hidden_layer_graphics(page, reader, objects)
    finally:
        if rotation:
            page.set_rotation(rotation)
    return _graphics(reader, objects, to_display, hidden)
