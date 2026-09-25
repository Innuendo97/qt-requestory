"""Test helper: synthetic PDFs generated with Qt (QPdfWriter + QTextDocument).

Only synthetic text goes in here (public repository). Qt needs a running
``QGuiApplication`` to lay text out, so every caller must hold the ``pdfs``
fixture (tests/officina/conftest.py). ``QT_QPA_PLATFORM=offscreen`` is set
before Qt is imported so nothing pops up on the desktop (same reason as
``tests/ui/conftest.py``). The offscreen platform has NO fonts, and a PDF
written without a font has no text layer, so :func:`load_font` registers one
system font for the duration of a test.
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_ACCESSIBILITY", "0")

from PySide6.QtCore import QMarginsF, QRectF, QSizeF  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QColor,
    QFont,
    QFontDatabase,
    QImage,
    QPageLayout,
    QPageSize,
    QPainter,
    QPdfWriter,
    QTextDocument,
)

FONT_FAMILY = "Arial"
_FONT_FILES = [
    Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "arial.ttf",
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
]


def load_font() -> int | None:
    """Register a system font with Qt; the id to remove it, None if none found."""
    global FONT_FAMILY
    for file in _FONT_FILES:
        if file.is_file():
            font_id = QFontDatabase.addApplicationFont(str(file))
            if font_id >= 0:
                FONT_FAMILY = QFontDatabase.applicationFontFamilies(font_id)[0]
                return font_id
    return None


def unload_font(font_id: int) -> None:
    QFontDatabase.removeApplicationFont(font_id)


MARGIN_MM = 15.0


def _writer(path: Path) -> QPdfWriter:
    """An A4 writer with NO page margins: the margins live in the document's
    root frame, so text laid out for the next page falls off this page instead
    of into its bottom margin (where the text layer would still hold it)."""
    writer = QPdfWriter(str(path))
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Millimeter)
    writer.setResolution(300)
    writer.setTitle("MOD_TEST synthetic")
    return writer


def html_pdf(path: Path, html: str, *, font_pt: float = 11.0, width_mm: float | None = None) -> Path:
    """Render ``html`` into a paginated A4 PDF at ``path``.

    ``width_mm`` narrows the text column (reflow: same words, other lines).
    """
    writer = _writer(path)
    doc = QTextDocument()
    font = QFont(FONT_FAMILY)
    font.setPointSizeF(font_pt)
    doc.setDefaultFont(font)
    doc.setHtml(html)
    mm = 96 / 25.4  # frame margins are in 96-dpi logical pixels, scaled to the device
    right = MARGIN_MM if width_mm is None else max(MARGIN_MM, 210 - MARGIN_MM - width_mm)
    frame = doc.rootFrame().frameFormat()
    frame.setTopMargin(MARGIN_MM * mm)
    frame.setBottomMargin(MARGIN_MM * mm)
    frame.setLeftMargin(MARGIN_MM * mm)
    frame.setRightMargin(right * mm)
    doc.rootFrame().setFrameFormat(frame)
    _paint(doc, writer)
    return path


def _paint(doc: QTextDocument, writer: QPdfWriter) -> None:
    """Paginate ``doc`` onto ``writer`` WITHOUT the page numbers print_() adds."""
    rect = writer.pageLayout().fullRectPixels(writer.resolution())
    width, height = float(rect.width()), float(rect.height())
    doc.documentLayout().setPaintDevice(writer)
    doc.setPageSize(QSizeF(width, height))
    painter = QPainter(writer)
    for page in range(doc.pageCount()):
        if page:
            writer.newPage()
        painter.save()
        painter.translate(0, -page * height)
        doc.drawContents(painter, QRectF(0, page * height, width, height))
        painter.restore()
    painter.end()


def paragraphs_pdf(path: Path, paragraphs: list[str], **kwargs) -> Path:
    html = "".join(f"<p>{p}</p>" for p in paragraphs)
    return html_pdf(path, html, **kwargs)


def image_only_pdf(path: Path, *, pages: int = 1) -> Path:
    """A 'scanned' PDF: each page is one raster image and no text layer."""
    writer = _writer(path)
    image = QImage(400, 560, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    img_painter = QPainter(image)
    for row in range(40, 520, 24):
        img_painter.fillRect(40, row, 320 - (row % 70), 10, QColor("black"))
    img_painter.end()
    painter = QPainter(writer)
    for n in range(pages):
        if n:
            writer.newPage()
        target = QRectF(0, 0, writer.width(), writer.height())
        painter.drawImage(target, image)
    painter.end()
    return path


def lorem(n_words: int, *, seed: int = 0) -> str:
    """Deterministic synthetic words (not real Latin, no customer data)."""
    syll = ["ta", "re", "mo", "li", "sen", "ca", "vo", "du", "ri", "pel", "no", "gri"]
    out = []
    state = seed * 7919 + 17
    for _ in range(n_words):
        state = (state * 1103515245 + 12345) % (2**31)
        k = 2 + state % 3
        word = "".join(syll[(state >> (4 * i)) % len(syll)] for i in range(k))
        out.append(word)
    return " ".join(out)

