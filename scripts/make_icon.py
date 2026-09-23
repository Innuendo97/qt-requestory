"""Render ``ui/icons/app.svg`` into the multi-resolution ``ui/icons/app.ico``.

Why a script and not a one-liner: Windows wants one icon file holding several
sizes (the 16 px one is what the taskbar and the Alt-Tab list use, the 256 px
one is what the "Large icons" view of Explorer and the SmartScreen dialog show).
Qt can render the SVG but its ICO writer only ever writes a single image, and
Pillow is deliberately not a dependency of this project, so the container is
assembled here by hand.

Format decisions (they matter, a wrong container shows a blank icon):

* every size up to 64 is stored as 32-bit BMP (BITMAPINFOHEADER + bottom-up
  BGRA rows + an all-zero AND mask). This is what every Windows shell since XP reads
  without hesitation.
* 256 is stored as a PNG stream. A 256x256 BMP entry would add ~256 KB and
  Vista+ expects PNG at that size anyway.

The 16 px entry comes from the hand-tuned ``app-16.svg`` (the full design turns
into a blur at that size); every other size is rendered from ``app.svg``.

Run it only when ``app.svg`` or ``app-16.svg`` changes; the produced ``app.ico``
is committed so that a plain ``pyinstaller qtRequestory.spec`` needs no
Qt-based pre-step.

    .venv\\Scripts\\python.exe scripts\\make_icon.py
"""
from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ICON_DIR = ROOT / "src" / "qtrequestory" / "ui" / "icons"
SVG = ICON_DIR / "app.svg"
#: Hand-tuned small variant, used for every size up to SMALL_UP_TO.
SMALL_SVG = ICON_DIR / "app-16.svg"
SMALL_UP_TO = 16
ICO = ICON_DIR / "app.ico"

#: 16/24/32/48/256 for the shell (DESIGN-ui §Visual style) plus 20/40/64, the
#: small/large icon sizes Windows asks for at 125/150/200 % scaling. Same list as
#: ``qtrequestory.ui.icons.APP_ICON_SIZES``.
SIZES = (16, 20, 24, 32, 40, 48, 64, 256)
#: Below this the BMP container is used, at/above it the PNG one (see module docstring).
PNG_FROM = 256


def _render(size: int) -> "QImage":  # noqa: F821 - Qt is imported lazily in main()
    """The right SVG rasterised into a transparent ARGB32 ``size`` x ``size`` image."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    QSvgRenderer(str(SMALL_SVG if size <= SMALL_UP_TO else SVG)).render(painter)
    painter.end()
    return image


def _png_bytes(image: "QImage") -> bytes:  # noqa: F821
    from PySide6.QtCore import QBuffer, QByteArray

    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise RuntimeError("Qt could not encode the icon as PNG")
    buffer.close()
    return bytes(data)


def _bmp_bytes(image: "QImage") -> bytes:  # noqa: F821
    """A 32-bit icon DIB: header, bottom-up BGRA pixels, then the AND mask.

    ``QImage.Format_ARGB32`` stores 0xAARRGGBB words; on a little-endian machine
    that is already the B,G,R,A byte order a DIB wants. The AND mask is left at
    zero — with 32 bits per pixel Windows uses the alpha channel and ignores it,
    but the mask must still be present or the entry is rejected.
    """
    width, height = image.width(), image.height()
    stride = width * 4
    bits = bytes(image.constBits())[: image.bytesPerLine() * height]
    rows = [bits[y * image.bytesPerLine():][:stride] for y in range(height)]

    header = struct.pack(
        "<IiiHHIIiiII",
        40,              # biSize
        width,
        height * 2,      # biHeight: XOR bitmap + AND mask, as the ICO format wants
        1,               # biPlanes
        32,              # biBitCount
        0,               # biCompression = BI_RGB
        stride * height,  # biSizeImage
        0, 0, 0, 0,      # resolution / palette
    )
    mask_stride = ((width + 31) // 32) * 4
    return header + b"".join(reversed(rows)) + bytes(mask_stride * height)


def build_ico() -> Path:
    """Write ``app.ico`` from ``app.svg`` and return its path."""
    images = {size: _render(size) for size in SIZES}
    entries = {
        size: (_png_bytes(image) if size >= PNG_FROM else _bmp_bytes(image))
        for size, image in images.items()
    }

    # ICONDIR, then one 16-byte ICONDIRENTRY per image, then the image data.
    offset = 6 + 16 * len(entries)
    directory = bytearray(struct.pack("<HHH", 0, 1, len(entries)))
    for size, data in entries.items():
        byte = 0 if size >= 256 else size  # 0 means 256 in a one-byte field
        directory += struct.pack("<BBBBHHII", byte, byte, 0, 0, 1, 32, len(data), offset)
        offset += len(data)

    ICO.write_bytes(bytes(directory) + b"".join(entries.values()))
    return ICO


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # no window, no display needed
    from PySide6.QtGui import QGuiApplication

    QGuiApplication(sys.argv[:1])  # QSvgRenderer/QPainter need the GUI plumbing
    path = build_ico()
    print(f"{path} ({path.stat().st_size} bytes, sizes {', '.join(map(str, SIZES))})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
