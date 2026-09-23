"""In-window toasts: a confirmation that shows up where the eyes are, then goes."""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QWidget

from qtrequestory.ui.main_window import MainWindow
from qtrequestory.ui.toast import MARGIN, Toast


@pytest.fixture
def window(qtbot, fake_core, runner):
    win = MainWindow(fake_core, runner)
    qtbot.addWidget(win)
    win.resize(900, 600)
    win.show()
    return win


def test_show_toast_makes_it_visible_with_the_text(window):
    window.show_toast("JSON copiato · 157 KB", tone="ok")
    assert window.toast.isVisible()
    assert window.toast.text() == "JSON copiato · 157 KB"
    assert window.toast.property("tone") == "ok"


def test_it_hides_itself_after_the_given_time(qtbot, window):
    window.show_toast("Salvato: a.json", ms=150)
    assert window.toast.isVisible()
    qtbot.waitUntil(lambda: not window.toast.isVisible(), timeout=3000)


def test_a_second_call_replaces_the_text_and_restarts_the_timer(qtbot, window):
    window.show_toast("primo", ms=1000)
    qtbot.wait(600)
    window.show_toast("secondo", ms=1000)
    qtbot.wait(600)  # 1200 ms: past the first deadline, still up with the new text
    assert window.toast.isVisible()
    assert window.toast.text() == "secondo"
    qtbot.waitUntil(lambda: not window.toast.isVisible(), timeout=3000)


def test_it_sits_in_the_bottom_right_corner_of_the_central_widget(qtbot, window):
    window.show_toast("JSON copiato")
    central = window.centralWidget()
    assert window.toast.parent() is central
    geometry = window.toast.geometry()
    assert central.width() - geometry.right() - 1 == MARGIN
    assert central.height() - geometry.bottom() - 1 == MARGIN


def test_it_follows_a_resize(qtbot, window):
    window.show_toast("JSON copiato")
    window.resize(1000, 700)
    central = window.centralWidget()
    qtbot.waitUntil(lambda: central.width() - window.toast.geometry().right() - 1 == MARGIN,
                    timeout=2000)
    assert central.height() - window.toast.geometry().bottom() - 1 == MARGIN


def test_it_does_not_steal_clicks(window):
    """A click on the toast's centre reaches whatever is underneath."""
    window.show_toast("JSON copiato")
    central = window.centralWidget()
    under = central.childAt(window.toast.geometry().center())
    assert under is not None
    assert under is not window.toast and not window.toast.isAncestorOf(under)


def test_a_long_message_stays_inside_the_window(qtbot, window):
    """Task 16 sends "Salvato: <full path>": the toast must not run off the edge."""
    long_text = "Salvato: C:/" + "cartella/" * 21 + "fine.json"
    assert len(long_text) >= 200
    window.show_toast(long_text)
    central = window.centralWidget()
    geometry = window.toast.geometry()
    assert geometry.left() >= MARGIN
    assert central.width() - geometry.right() - 1 == MARGIN
    assert window.toast.text() == long_text, "text() keeps the whole message"

    window.resize(500, 400)  # narrower: still inside
    qtbot.waitUntil(lambda: window.toast.geometry().left() >= MARGIN, timeout=2000)
    assert central.width() - window.toast.geometry().right() - 1 == MARGIN


def test_reduce_motion_skips_the_fade(qtbot, qapp):
    host = QWidget()
    qtbot.addWidget(host)
    host.resize(400, 300)
    host.show()
    toast = Toast(host)
    qapp.setProperty("reduce_motion", True)
    try:
        assert toast.animations_enabled() is False
        toast.show_message("ciao", ms=50)
        qtbot.waitUntil(lambda: not toast.isVisible(), timeout=2000)
    finally:
        qapp.setProperty("reduce_motion", None)


def test_an_unknown_tone_is_neutral(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    toast = Toast(host)
    toast.show_message("x", tone="fuchsia")
    assert toast.property("tone") == "neutral"
