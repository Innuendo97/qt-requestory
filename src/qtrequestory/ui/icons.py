"""Loading (and recolouring) the embedded SVG icons.

The icon files are Fluent UI System Icons with a fixed dark fill (``#212121``).
That is unreadable on a dark window, and Qt's SVG icon engine does not know
anything about the palette, so every glyph is rendered once and then tinted
with the current text colour using a ``SourceIn`` composition: the rendered
alpha decides *where* to paint, the palette decides *which* colour. This works
for any SVG without editing the files and without shipping two variants.

Results are cached per (name, colour): the rail asks for the same four icons on
every palette change and every page rebuild. ``clear_cache()`` is called when
the system switches between light and dark.

``app.svg`` is the exception — the brand mark keeps its own colours, so
``app_icon()`` never tints.
"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPalette, QPixmap

__all__ = ["ICON_DIR", "app_icon", "clear_cache", "icon"]

log = logging.getLogger(__name__)

ICON_DIR = Path(__file__).with_name("icons")

#: The sizes a QIcon is filled with; Qt scales between them for other sizes.
_SIZES = (16, 20, 24, 32, 48)

_cache: dict[tuple[str, str], QIcon] = {}


def icon(name: str, color: QColor | None = None) -> QIcon:
    """The ``name`` glyph, tinted for the current palette (or with ``color``).

    An unknown name returns an empty ``QIcon`` and logs: a mistyped icon in the
    ``PAGES`` registry must degrade to a label without an icon, never take the
    window down.
    """
    tint = color if color is not None else _text_color()
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


def app_icon() -> QIcon:
    """The application icon, untinted."""
    return QIcon(str(ICON_DIR / "app.svg"))


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
    """The palette's normal text colour — dark on light, light on dark."""
    app = QGuiApplication.instance()
    if app is None:  # pragma: no cover - icons are only used with a running app
        return QColor(Qt.GlobalColor.black)
    return app.palette().color(QPalette.ColorGroup.Normal, QPalette.ColorRole.WindowText)
