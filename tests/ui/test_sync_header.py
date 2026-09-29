"""D3 (Officina 2.5, D5): the sync status lives in the header.

No "Sincronizzazione" tab any more: a chip-icon on the right of the blue
header (before ⚙) carries the environments' state; when something needs the
user it says so on three channels — the glyph's colour, a dot whose SHAPE
tells amber from red, and text (chip, tooltip, accessible name). A click, Enter
or Space or Ctrl+2 opens a dropdown panel under the chip; the old page stays
reachable from it.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from qtrequestory.ui import strings, theme
from qtrequestory.ui.main_window import PAGES, MainWindow
from qtrequestory.ui.pages import sync_badge as sb
from qtrequestory.ui.sync_chip import StatusChip
from qtrequestory.ui.theme import DARK, LIGHT, Mode
from tests.ui.test_theme import contrast

# -- the attention rule (pure) ----------------------------------------------------

B = sb.badge_for


@pytest.mark.parametrize(("kind", "level"), [
    (sb.LOST, "bad"), (sb.ERRORS, "bad"),
    (sb.PENDING, "warn"), (sb.UNREACHABLE, "warn"), (sb.STALE, "warn"), (sb.NEVER, "warn"),
    (sb.FRESH, ""), (sb.EMPTY_TODAY, ""), (sb.RUNNING, ""), (sb.QUEUED, ""),
])
def test_each_badge_kind_has_an_attention_level(kind, level):
    assert sb.attention_level(kind) == level


def test_the_worst_environment_decides_and_every_problem_is_worded():
    badges = {"coll": B(None, pending=2), "svil": B(None, lost=1), "prod": B(None, running=True)}
    att = sb.attention_for(badges)
    assert att.level == "bad"
    assert att.lines == ("coll: 2 da scaricare", "svil: 1 giorno perso")
    assert att.running is True
    assert att.count == 2


def test_nothing_to_say_when_all_is_fine():
    fresh = sb.Badge(sb.FRESH, "ok", strings.SYNC_BADGE_FRESH)
    att = sb.attention_for({"coll": fresh, "svil": fresh})
    assert (att.level, att.lines, att.running, att.count) == ("", (), False, 0)


def test_the_unreachable_amber_is_the_vpn_not_a_failure():
    att = sb.attention_for({"coll": B(None, reachable=False)})
    assert att.level == "warn"
    assert "VPN" in sb.hint_for(sb.UNREACHABLE)
    assert all(sb.hint_for(k) for k in (sb.LOST, sb.ERRORS, sb.PENDING, sb.STALE, sb.NEVER))
    assert sb.hint_for(sb.FRESH) == ""


# -- the chip ---------------------------------------------------------------------

@pytest.fixture
def chip(qtbot) -> StatusChip:
    widget = StatusChip()
    qtbot.addWidget(widget)
    widget.set_envs([("svil", "ok", "oggi 09:00"), ("coll", "warn", "2 da scaricare")])
    widget.show()
    return widget


def test_the_chip_has_no_dot_when_all_is_fine(chip):
    chip.set_attention(sb.Attention())
    assert chip.glyph.level() == ""
    assert chip.glyph.ink() == theme.tokens().on_header
    assert chip.accessibleName().startswith(strings.SYNC_CHIP_A11Y_OK)


@pytest.mark.parametrize(("level", "token"), [("warn", "identity"), ("bad", "header_bad")])
def test_attention_tints_the_glyph_and_shows_its_dot(chip, level, token):
    chip.set_attention(sb.Attention(level, ("coll: 2 da scaricare",)))
    assert chip.glyph.level() == level
    assert chip.glyph.ink() == getattr(theme.tokens(), token)
    assert "coll: 2 da scaricare" in chip.toolTip()
    assert strings.SYNC_CHIP_A11Y_ATTENTION_ONE in chip.accessibleName()


def test_amber_and_red_dots_differ_in_shape_not_only_in_colour(chip):
    """WCAG 1.4.1: red is a larger disc with an exclamation mark."""
    chip.set_attention(sb.Attention("warn", ("x",)))
    amber = chip.glyph.dot_shape()
    chip.set_attention(sb.Attention("bad", ("x",)))
    red = chip.glyph.dot_shape()
    assert amber != red and red.mark == "!" and red.radius > amber.radius


def test_the_chip_text_is_the_environments_state(chip):
    assert chip.summary() == "svil oggi 09:00 · coll 2 da scaricare"
    assert chip.text_label.text() == chip.summary()


def test_a_running_sync_spins_the_glyph(chip, monkeypatch):
    from qtrequestory.ui.toast import Toast

    monkeypatch.setattr(Toast, "animations_enabled", staticmethod(lambda: True))
    chip.set_attention(sb.Attention(running=True))
    assert chip.glyph.is_spinning()
    before = chip.glyph.angle()
    QTest.qWait(3 * chip.glyph.SPIN_MS)
    assert chip.glyph.angle() != before
    chip.set_attention(sb.Attention())
    assert not chip.glyph.is_spinning() and chip.glyph.angle() == 0
    assert strings.SYNC_CHIP_A11Y_RUNNING in StatusChip.accessible_name(sb.Attention(running=True), "")


def test_reduced_motion_keeps_the_glyph_still(chip, qapp):
    qapp.setProperty("reduce_motion", True)  # the real check, not a stub
    try:
        chip.set_attention(sb.Attention(running=True))
        assert not chip.glyph.is_spinning()
    finally:
        qapp.setProperty("reduce_motion", False)


@pytest.mark.parametrize("key", [Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space])
def test_enter_and_space_press_the_chip(qtbot, chip, key):
    with qtbot.waitSignal(chip.clicked, timeout=1000):
        QTest.keyClick(chip, key)


@pytest.mark.parametrize(("mode", "tokens"), [(Mode.LIGHT, LIGHT), (Mode.DARK, DARK)], ids=["light", "dark"])
def test_the_chip_ink_on_the_header_is_readable(qtbot, themed, mode, tokens):
    """White text >= 4.5:1 on the raised chip; the glyph and dots >= 3:1 (non-text)."""
    theme.apply(themed, mode)
    widget = StatusChip()
    qtbot.addWidget(widget)
    widget.set_envs([("svil", "ok", "oggi 09:00")])
    from qtrequestory.ui.app_bar import AppBar

    bar = AppBar()
    qtbot.addWidget(bar)
    bar.status_chip.set_envs([("svil", "ok", "oggi 09:00")])
    bar.show()
    from PySide6.QtGui import QPalette

    bar.status_chip.text_label.ensurePolished()
    ink = bar.status_chip.text_label.palette().color(QPalette.ColorRole.WindowText).name().upper()
    assert ink == tokens.on_header
    assert contrast(ink, tokens.header_raise) >= 4.5
    for level in ("", "warn", "bad"):
        bar.status_chip.set_attention(sb.Attention(level, ("x",) if level else ()))
        assert contrast(bar.status_chip.glyph.ink(), tokens.header_raise) >= 3.0, level


# -- the shell ----------------------------------------------------------------------

@pytest.fixture
def window(qtbot, fake_core, runner):
    win = MainWindow(fake_core, runner)
    qtbot.addWidget(win)
    win.resize(1366, 768)
    win.show()
    qtbot.waitExposed(win)
    return win


def test_the_sync_tab_is_gone_but_the_page_is_not():
    assert [p.key for p in PAGES if p.placement == "tab"] == ["search", "officina"]
    assert next(p for p in PAGES if p.key == "sync").placement == "hidden"


def test_the_bar_has_two_tabs_and_the_chip_before_the_icons(window):
    bar = window.app_bar
    assert list(bar.tabs) == ["search", "officina"]
    assert "sync" in window.pages()
    chip, settings = bar.status_chip, bar.icon_buttons["settings"]
    assert chip.isVisible()
    assert chip.geometry().right() < settings.geometry().left()
    assert "Ctrl+2" in chip.toolTip()


def test_clicking_the_chip_opens_the_panel_under_it(qtbot, window):
    chip = window.app_bar.status_chip
    qtbot.mouseClick(chip, Qt.MouseButton.LeftButton)
    panel = window.sync_panel
    assert panel is not None and panel.isVisible()
    assert window.current_page_key() == "search", "the panel is not a page switch"
    chip_bottom = chip.mapToGlobal(QPoint(0, chip.height())).y()
    assert panel.geometry().top() >= chip_bottom
    assert abs(panel.geometry().right() - chip.mapToGlobal(QPoint(chip.width(), 0)).x()) <= 2 \
        or panel.geometry().left() >= window.mapToGlobal(QPoint(0, 0)).x()


def test_escape_and_an_outside_click_close_the_panel(qtbot, window):
    window.toggle_sync_panel()
    panel = window.sync_panel
    QTest.keyClick(panel, Qt.Key.Key_Escape)
    assert not panel.isVisible()
    window.toggle_sync_panel()
    assert panel.isVisible()
    QTest.mouseClick(panel, Qt.MouseButton.LeftButton, pos=QPoint(-20, -20))
    assert not panel.isVisible()


def test_ctrl_2_opens_the_panel(qtbot, window):
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow, timeout=2000)
    QTest.keyClick(window, Qt.Key.Key_2, Qt.KeyboardModifier.ControlModifier)
    assert window.sync_panel is not None and window.sync_panel.isVisible()
    assert window.current_page_key() == "search"


def test_the_panel_lists_every_environment_with_its_calendar(window, fake_core):
    fake_core.sync.set_env_status("coll", fresh=True, last_success=datetime.now().replace(second=0))
    window.toggle_sync_panel()
    panel = window.sync_panel
    rows = panel.rows()
    assert [r.env_name for r in rows] == window.page("sync").presenter.environments()
    coll = panel.row("coll")
    assert coll.pill.text() == strings.SYNC_BADGE_FRESH
    assert coll.last_label.text().startswith(strings.SYNC_PANEL_LAST.format(when="oggi"))
    assert coll.hint_label.isHidden()
    assert len(coll.strip.kinds()) == 30
    svil = panel.row("svil")
    assert svil.pill.text() == strings.SYNC_BADGE_NEVER
    assert svil.hint_label.text() == sb.hint_for(sb.NEVER) and not svil.hint_label.isHidden()


def test_sincronizza_ora_runs_without_leaving_the_page(qtbot, window, monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr(window.page("sync"), "start_sync", lambda *a, **k: calls.append((a, k)))
    window.toggle_sync_panel()
    qtbot.mouseClick(window.sync_panel.sync_button, Qt.MouseButton.LeftButton)
    assert calls == [((), {})]
    assert window.current_page_key() == "search"


def test_the_full_page_link_shows_the_old_page_and_marks_the_chip(qtbot, window):
    window.toggle_sync_panel()
    qtbot.mouseClick(window.sync_panel.page_link, Qt.MouseButton.LeftButton)
    assert not window.sync_panel.isVisible()
    assert window.current_page_key() == "sync"
    assert window.app_bar.status_chip.property("current") is True
    window.show_page("search")
    assert window.app_bar.status_chip.property("current") is False


def test_lost_days_make_the_chip_red(window, fake_core):
    today = date.today()
    lost = today - timedelta(days=7)
    fake_core.index.set_server_days("svil", seen={lost})
    fake_core.index.set_local_days("svil", {today - timedelta(days=d) for d in range(1, 20)} - {lost})
    page = window.page("sync")
    page.refresh_cards()
    page.presenter.emit_summary()
    chip = window.app_bar.status_chip
    assert chip.glyph.level() == "bad"
    assert "svil: 1 giorno perso" in chip.toolTip()


def test_a_day_to_download_makes_the_chip_amber_and_the_panel_follows(window, fake_core):
    today = date.today()
    pending = today - timedelta(days=2)
    fake_core.index.set_server_days("coll", listed={pending})
    fake_core.index.set_local_days("coll", {today - timedelta(days=d) for d in range(1, 20)} - {pending})
    for env in ("coll", "svil"):
        fake_core.sync.set_env_status(env, fresh=True, last_success=datetime.now())
    window.toggle_sync_panel()
    page = window.page("sync")
    page.refresh_cards()
    page.presenter.emit_summary()
    assert window.app_bar.status_chip.glyph.level() == "warn"
    assert window.sync_panel.row("coll").pill.text() == strings.SYNC_BADGE_PENDING.format(n=1)


def test_the_slow_refresh_rereads_the_days_while_the_page_is_hidden(window, fake_core):
    """The page is almost never on screen now: a scheduled sync that filled
    the hole must clear the red dot at the next slow refresh."""
    today = date.today()
    lost = today - timedelta(days=7)
    local = {today - timedelta(days=d) for d in range(1, 20)}
    fake_core.index.set_server_days("svil", seen={lost})
    fake_core.index.set_local_days("svil", local - {lost})
    window.sync_state_timer.timeout.emit()
    assert not window.page("sync").isVisible()
    assert window.app_bar.status_chip.glyph.level() == "bad"
    fake_core.index.set_local_days("svil", local)
    window.sync_state_timer.timeout.emit()
    assert window.app_bar.status_chip.glyph.level() != "bad"
