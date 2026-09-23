"""The icon set: the eight rail/toolbar glyphs plus the application icon."""
from __future__ import annotations

import pytest
from PySide6.QtGui import QColor

from qtrequestory.ui import icons

NAMES = (
    "search", "arrow-sync", "settings", "info",
    "document-arrow-right", "copy", "save", "folder-open",
)


@pytest.mark.parametrize("name", [*NAMES, "app"])
def test_every_documented_icon_ships_with_the_package(name: str):
    assert (icons.ICON_DIR / f"{name}.svg").is_file()


def test_the_icon_set_is_attributed(qapp):
    assert (icons.ICON_DIR / "LICENSE.md").is_file()


@pytest.mark.parametrize("name", NAMES)
def test_icons_render_to_a_pixmap(qapp, name: str):
    pixmap = icons.icon(name).pixmap(20, 20)
    assert not pixmap.isNull()
    assert pixmap.size().width() > 0


def test_an_unknown_name_returns_an_empty_icon_instead_of_raising(qapp):
    """A page must not be able to crash the shell with a typo in PAGES."""
    assert icons.icon("nope-does-not-exist").isNull()


def test_glyphs_are_tinted_with_the_requested_colour(qapp):
    red = icons.icon("search", QColor("#FF0000")).pixmap(20, 20).toImage()
    blue = icons.icon("search", QColor("#0000FF")).pixmap(20, 20).toImage()
    assert red != blue

    opaque = [
        QColor(red.pixelColor(x, y))
        for x in range(red.width())
        for y in range(red.height())
        if red.pixelColor(x, y).alpha() > 200
    ]
    assert opaque, "the glyph must have visible pixels"
    assert all(c.red() > 200 and c.green() < 60 and c.blue() < 60 for c in opaque)


def test_the_application_icon_keeps_its_own_colours(qapp):
    """`app.svg` is the brand mark: tinting it would turn it into a blob."""
    image = icons.app_icon().pixmap(48, 48).toImage()
    colours = {
        QColor(image.pixelColor(x, y)).name()
        for x in range(image.width())
        for y in range(image.height())
        if image.pixelColor(x, y).alpha() > 200
    }
    assert "#ffc857" in colours, "the highlighted (amber) log line"


def test_app_icon_has_all_sizes(qapp):
    """The window icon must carry the large sizes too.

    With only small pixmaps Qt registers the window class with a fallback large
    icon, and the taskbar shows the generic Windows one.
    """
    app_icon = icons.app_icon()
    available = {size.width() for size in app_icon.availableSizes()}
    assert set(icons.APP_ICON_SIZES) <= available
    for size in icons.APP_ICON_SIZES:
        pixmap = app_icon.pixmap(size, size)
        assert not pixmap.isNull(), f"{size}px"


def test_app_icon_sizes_are_what_the_shell_asks_for():
    assert icons.APP_ICON_SIZES == (16, 20, 24, 32, 40, 48, 64, 256)


def test_app_icon_falls_back_to_the_svg_without_the_ico(qapp, tmp_path, monkeypatch):
    """A source checkout without a regenerated ``app.ico`` still gets every size."""
    (tmp_path / "app.svg").write_bytes((icons.ICON_DIR / "app.svg").read_bytes())
    monkeypatch.setattr(icons, "ICON_DIR", tmp_path)
    available = {size.width() for size in icons.app_icon().availableSizes()}
    assert set(icons.APP_ICON_SIZES) <= available


def test_the_cache_can_be_cleared_when_the_palette_changes(qapp):
    first = icons.icon("save")
    icons.clear_cache()
    assert not icons.icon("save").isNull()
    assert not first.isNull()
