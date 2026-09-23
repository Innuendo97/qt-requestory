"""Loading (and recolouring) the embedded SVG icons.

The icon files are Fluent UI System Icons with a fixed near-black fill. That
is unreadable on a dark window, and Qt's SVG icon engine does not know anything
about the theme, so every glyph is rendered once and then tinted with the
theme's ``text`` token (or the colour asked for) using a ``SourceIn``
composition: the rendered alpha decides *where* to paint, the theme decides
*which* colour. This works for any SVG without editing the files and without
shipping two variants.

Results are cached per (name, colour): the app bar asks for the same four icons on
every theme change and every page rebuild. ``theme.apply`` calls
``clear_cache()`` every time it runs.

``app.svg`` is the exception — the brand mark keeps its own colours, so
``app_icon()`` never tints.
"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

__all__ = ["ICON_DIR", "app_icon", "clear_cache", "icon"]

log = logging.getLogger(__name__)

ICON_DIR = Path(__file__).with_name("icons")

#: The sizes a QIcon is filled with; Qt scales between them for other sizes.
_SIZES = (16, 20, 24, 32, 48)

_cache: dict[tuple[str, str], QIcon] = {}


def icon(name: str, color: QColor | str | None = None) -> QIcon:
    """The ``name`` glyph, tinted with the theme's text colour (or ``color``).

    ``color`` takes a ``QColor`` or a token value, e.g. ``tokens().muted`` for
    a secondary action or ``tokens().on_accent`` on a primary button.

    An unknown name returns an empty ``QIcon`` and logs: a mistyped icon in the
    ``PAGES`` registry must degrade to a label without an icon, never take the
    window down.
    """
    tint = QColor(color) if color is not None else _text_color()
    key = (name, tint.name(QColor.NameFormat.HexArgb))
    cached = _cache.get(key)
    if cached is not None:
        return cached

    path = ICON_DIR / f"{name}.svg"
    if not path.is_file():
        log.warning("icona sconosciuta: %s", name)
        return QIcon()

    source = QIcon(str(path))
    result = QIcon()
    for size in _SIZES:
        result.addPixmap(_tinted(source, size, tint))
    _cache[key] = result
    return result


#: Every size the window icon carries. The large ones matter: with only small
#: pixmaps Qt registers the window class with the generic large icon, which is
#: what the taskbar (and Alt-Tab at 125-200 % scaling) then shows.
APP_ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 256)


def app_icon() -> QIcon:
    """The application icon, untinted, with a pixmap at every ``APP_ICON_SIZES``.

    ``app.ico`` (bundled) holds the hand-tuned small sizes, so it wins; any size
    it lacks — or the whole set, when it is missing — is rendered from
    ``app.svg``.
    """
    from PySide6.QtGui import QImageReader  # only the app icon reads ICO files

    result = QIcon()
    have: set[int] = set()
    ico = ICON_DIR / "app.ico"
    if ico.is_file():
        reader = QImageReader(str(ico))
        for index in range(reader.imageCount()):
            reader.jumpToImage(index)
            image = reader.read()
            if not image.isNull() and image.width() in APP_ICON_SIZES:
                result.addPixmap(QPixmap.fromImage(image))
                have.add(image.width())
    missing = [size for size in APP_ICON_SIZES if size not in have]
    if missing:
        svg = QIcon(str(ICON_DIR / "app.svg"))
        for size in missing:
            result.addPixmap(svg.pixmap(QSize(size, size), 1.0))
    return result


def clear_cache() -> None:
    """Drop the cached pixmaps (after a light/dark switch)."""
    _cache.clear()


def _tinted(source: QIcon, size: int, color: QColor) -> QPixmap:
    pixmap = source.pixmap(QSize(size, size))
    if pixmap.isNull():  # pragma: no cover - only without the Qt SVG plugin
        return pixmap
    painter = QPainter(pixmap)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(pixmap.rect(), color)
    painter.end()
    return pixmap


def _text_color() -> QColor:
    """The theme's text colour — dark on light, light on dark."""
    from qtrequestory.ui import theme  # theme imports this module

    return QColor(theme.tokens().text)
