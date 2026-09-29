"""The top app bar: brand, tabs, sync-status chip, icon buttons (navigation A)."""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt

from qtrequestory.ui.app_bar import AppBar, StatusChip


@pytest.fixture
def bar(qtbot) -> AppBar:
    widget = AppBar()
    widget.add_tab("search", "Ricerca", "search")
    widget.add_tab("sync", "Sincronizzazione", "arrow-sync")
    widget.add_icon_button("settings", "settings", "Impostazioni (Ctrl+,)")
    widget.add_icon_button("about", "info", "Info (F1)")
    qtbot.addWidget(widget)
    widget.show()
    return widget


def test_the_bar_is_styled_by_its_object_name(bar):
    assert bar.objectName() == "appBar"
    assert bar.testAttribute(Qt.WidgetAttribute.WA_StyledBackground)


def test_tabs_are_checkable_tab_buttons_in_order(bar):
    assert list(bar.tabs) == ["search", "sync"]
    assert [b.text() for b in bar.tabs.values()] == ["Ricerca", "Sincronizzazione"]
    assert all(b.property("tab") is True and b.isCheckable() for b in bar.tabs.values())


def test_icon_buttons_carry_their_tooltip_and_no_text(bar):
    assert list(bar.icon_buttons) == ["settings", "about"]
    settings = bar.icon_buttons["settings"]
    assert settings.toolTip() == "Impostazioni (Ctrl+,)"
    assert settings.text() == "" and not settings.icon().isNull()
    assert settings.property("role") == "icon"


def test_clicking_a_tab_or_an_icon_asks_for_its_page(qtbot, bar):
    asked: list[str] = []
    bar.page_requested.connect(asked.append)
    qtbot.mouseClick(bar.tabs["sync"], Qt.MouseButton.LeftButton)
    qtbot.mouseClick(bar.icon_buttons["about"], Qt.MouseButton.LeftButton)
    assert asked == ["sync", "about"]


def test_set_current_checks_exactly_one_entry(bar):
    bar.set_current("sync")
    assert [k for k, b in bar.tabs.items() if b.isChecked()] == ["sync"]
    assert not any(b.isChecked() for b in bar.icon_buttons.values())

    bar.set_current("settings")
    assert not any(b.isChecked() for b in bar.tabs.values())
    assert [k for k, b in bar.icon_buttons.items() if b.isChecked()] == ["settings"]


def test_the_brand_names_the_application(bar):
    assert bar.brand_label.text() == "qtRequestory"
    assert not bar.brand_icon.pixmap().isNull()


# ------------------------------------------------------------------ chip ---

def test_the_chip_renders_the_text_of_every_env(qtbot):
    chip = StatusChip()
    qtbot.addWidget(chip)
    chip.set_envs([("coll", "ok", "oggi 11:24"), ("svil", "warn", "ieri 18:40")])

    assert chip.summary() == "coll oggi 11:24 · svil ieri 18:40"
    assert chip.text_label.text() == chip.summary()
    assert chip.accessibleName().endswith(chip.summary())
    assert not chip.isHidden()


def test_a_note_on_an_env_goes_into_the_chip_tooltip(qtbot):
    from qtrequestory.ui import strings

    chip = StatusChip()
    qtbot.addWidget(chip)
    chip.set_envs([("coll", "ok", "oggi 11:24"), ("svil", "ok", "oggi 22:33", "nessuna chiamata")])
    assert chip.summary() == "coll oggi 11:24 · svil oggi 22:33"
    head = strings.SYNC_CHIP_TOOLTIP.format(shortcut="Ctrl+2")
    assert chip.toolTip().startswith(head)
    assert "svil: nessuna chiamata" in chip.toolTip()
    chip.set_envs([("coll", "ok", "oggi 11:24")])
    assert chip.toolTip() == head


def test_an_empty_chip_hides_itself(qtbot):
    chip = StatusChip()
    qtbot.addWidget(chip)
    chip.set_envs([("coll", "ok", "oggi 11:24")])
    chip.set_envs([])
    assert chip.isHidden()
    assert chip.summary() == ""


def test_the_chip_is_sized_for_its_content(qtbot):
    chip = StatusChip()
    qtbot.addWidget(chip)
    chip.set_envs([("coll", "ok", "oggi 11:24")])
    short = chip.sizeHint().width()
    chip.set_envs([("coll", "ok", "oggi 11:24"), ("svil", "warn", "ieri 18:40")])
    assert chip.sizeHint().width() > short


def test_clicking_the_chip_asks_for_the_sync_panel(qtbot, bar):
    bar.status_chip.set_envs([("coll", "ok", "oggi 11:24")])
    asked: list[str] = []
    bar.page_requested.connect(asked.append)
    with qtbot.waitSignal(bar.sync_requested, timeout=1000):
        qtbot.mouseClick(bar.status_chip, Qt.MouseButton.LeftButton)
    assert asked == [], "the chip opens a panel, not a page"


def test_the_chip_reads_as_current_on_the_sync_page(bar):
    bar.set_current("sync")
    assert bar.status_chip.property("current") is True
    bar.set_current("search")
    assert bar.status_chip.property("current") is False


def ink(icon) -> str:
    """The colour of the most opaque pixel of ``icon`` (the tint it was given)."""
    image = icon.pixmap(20, 20).toImage()
    pixels = [image.pixelColor(x, y) for x in range(20) for y in range(20)]
    return max(pixels, key=lambda c: c.alpha()).name().upper()


def test_a_theme_switch_re_tints_the_tab_icons_with_the_header_ink(bar, themed):
    """Palette B: the glyphs sit on the blue header, so they take ``on_header``
    (white in both modes) — and are re-tinted on every switch."""
    from qtrequestory.ui import theme

    for mode, tokens in ((theme.Mode.LIGHT, theme.LIGHT), (theme.Mode.DARK, theme.DARK)):
        theme.apply(themed, mode)
        for button in (*bar.tabs.values(), *bar.icon_buttons.values()):
            assert ink(button.icon()) == tokens.on_header
