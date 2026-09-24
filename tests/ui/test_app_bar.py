"""The top app bar: brand, tabs, sync-status chip, icon buttons (navigation A)."""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

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

def test_the_chip_renders_one_dot_and_text_per_env(qtbot):
    chip = StatusChip()
    qtbot.addWidget(chip)
    chip.set_envs([("coll", "ok", "oggi 11:24"), ("svil", "warn", "ieri 18:40")])

    assert chip.summary() == "coll oggi 11:24 · svil ieri 18:40"
    assert [d.property("dot") for d in chip.dots()] == ["ok", "warn"]
    assert chip.accessibleName() == chip.summary()
    assert not chip.isHidden()


def test_a_note_on_an_env_goes_into_the_chip_tooltip(qtbot):
    from qtrequestory.ui import strings

    chip = StatusChip()
    qtbot.addWidget(chip)
    chip.set_envs([("coll", "ok", "oggi 11:24"), ("svil", "ok", "oggi 22:33", "nessuna chiamata")])
    assert chip.summary() == "coll oggi 11:24 · svil oggi 22:33"
    assert [d.property("dot") for d in chip.dots()] == ["ok", "ok"]
    assert chip.toolTip().startswith(strings.STATUS_SYNC_SUMMARY_TOOLTIP)
    assert "svil: nessuna chiamata" in chip.toolTip()
    chip.set_envs([("coll", "ok", "oggi 11:24")])
    assert chip.toolTip() == strings.STATUS_SYNC_SUMMARY_TOOLTIP


def test_replaced_chip_labels_disappear_at_once(qtbot):
    """deleteLater runs on the next event loop turn: until then the old labels
    must not be painted over the new ones."""
    chip = StatusChip()
    qtbot.addWidget(chip)
    chip.show()
    chip.set_envs([("coll", "ok", "oggi 11:24")])
    old = chip.findChildren(QLabel)
    chip.set_envs([("svil", "warn", "ieri 18:40")])
    assert all(label.isHidden() for label in old)


def test_an_empty_chip_hides_itself(qtbot):
    chip = StatusChip()
    qtbot.addWidget(chip)
    chip.set_envs([("coll", "ok", "oggi 11:24")])
    chip.set_envs([])
    assert chip.isHidden()
    assert chip.summary() == ""


def test_an_unknown_tone_falls_back_to_neutral(qtbot):
    chip = StatusChip()
    qtbot.addWidget(chip)
    chip.set_envs([("coll", "purple", "mai")])
    assert [d.property("dot") for d in chip.dots()] == ["neutral"]


def test_the_chip_is_sized_for_its_content(qtbot):
    chip = StatusChip()
    qtbot.addWidget(chip)
    chip.set_envs([("coll", "ok", "oggi 11:24")])
    short = chip.sizeHint().width()
    chip.set_envs([("coll", "ok", "oggi 11:24"), ("svil", "warn", "ieri 18:40")])
    assert chip.sizeHint().width() > short


def test_clicking_the_chip_asks_for_the_sync_page(qtbot, bar):
    bar.status_chip.set_envs([("coll", "ok", "oggi 11:24")])
    asked: list[str] = []
    bar.page_requested.connect(asked.append)
    qtbot.mouseClick(bar.status_chip, Qt.MouseButton.LeftButton)
    assert asked == ["sync"]


def test_a_theme_switch_re_tints_the_tab_icons(bar, themed):
    from qtrequestory.ui import theme

    theme.apply(themed, theme.Mode.LIGHT)
    before = bar.tabs["search"].icon().pixmap(20, 20).toImage()
    theme.apply(themed, theme.Mode.DARK)
    after = bar.tabs["search"].icon().pixmap(20, 20).toImage()
    assert before != after
