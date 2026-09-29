"""Startup shows one splash, then the main window — and nothing else (D7).

The user saw several small white "qtRequestory" windows open and close at
launch. That is Qt's classic symptom of a widget shown while it still has no
parent: ``setVisible(True)`` on a child not yet in a layout, or a
``QStackedLayout`` filled before it belongs to a widget (its ``addWidget``
calls ``show()`` on the first page). Every such widget becomes a top-level
window for an instant. These tests record every window that receives a Show
event during ``run_gui`` and allow exactly two kinds: the splash and the
main window.
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QEventLoop, QObject, QSize, QTimer
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import QApplication, QSplashScreen, QWidget

from qtrequestory.ui import app as app_module
from qtrequestory.ui import splash as splash_module
from qtrequestory.ui import strings, theme
from qtrequestory.ui.main_window import MainWindow
from qtrequestory.ui.splash import Splash, start_splash

#: How long the stubbed event loop turns: long enough for the zero-delay
#: startup tasks (index, sync) and anything they would pop up.
SPIN_MS = 400


class _ShownWindows(QObject):
    """Application-wide filter: every widget that is shown as a window."""

    def __init__(self) -> None:
        super().__init__()
        self.shown: list[QWidget] = []

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802 (Qt API)
        if event.type() == QEvent.Type.Show and isinstance(obj, QWidget) and obj.isWindow():
            self.shown.append(obj)
        return False

    def describe(self) -> list[str]:
        return [f"{type(w).__name__}({w.objectName()}) {w.size().toTuple()}" for w in self.shown]


@pytest.fixture
def shown_windows(qapp):
    recorder = _ShownWindows()
    qapp.installEventFilter(recorder)
    yield recorder
    qapp.removeEventFilter(recorder)


@pytest.fixture(autouse=True)
def restore_theme(themed):
    """``run_gui`` applies the theme to the shared QApplication; undo it."""
    yield


@pytest.fixture
def spin_exec(monkeypatch):
    """The event loop turns for ``SPIN_MS`` instead of forever; windows are kept."""
    windows: list[MainWindow] = []

    def fake_exec(self) -> int:
        loop = QEventLoop()
        QTimer.singleShot(SPIN_MS, loop.quit)
        loop.exec()
        windows.extend(w for w in QApplication.topLevelWidgets()
                       if isinstance(w, MainWindow) and w.isVisible())
        return 7

    monkeypatch.setattr(QApplication, "exec", fake_exec)
    yield windows
    for window in windows:
        window.close()


def test_startup_shows_only_the_splash_and_the_main_window(
    qtbot, fake_core, shown_windows, spin_exec
):
    assert app_module.run_gui(fake_core) == 7

    kinds = {type(w) for w in shown_windows.shown}
    assert kinds <= {Splash, MainWindow}, shown_windows.describe()
    assert Splash in kinds, "the splash is shown while the pages are built"
    assert len(spin_exec) == 1
    splashes = [w for w in shown_windows.shown if isinstance(w, Splash)]
    assert not any(s.isVisible() for s in splashes), "finish() closed the splash"


def test_a_first_run_hides_the_splash_behind_the_wizard(
    qtbot, fake_core, monkeypatch, shown_windows, spin_exec
):
    fake_core.config.first_run = True
    monkeypatch.setattr(app_module, "wizard_available", lambda: True)
    visible_at_wizard: list[bool] = []

    def wizard(*_args, **_kwargs):
        visible_at_wizard.append(any(isinstance(w, Splash) and w.isVisible()
                                     for w in QApplication.topLevelWidgets()))
        return None  # cancelled

    monkeypatch.setattr(app_module, "show_first_run_wizard", wizard)

    assert app_module.run_gui(fake_core) == 0
    assert visible_at_wizard == [False], "the splash never covers the wizard"
    assert not any(isinstance(w, Splash) and w.isVisible() for w in QApplication.topLevelWidgets())


def test_a_second_instance_shows_no_window_at_all(qtbot, fake_core, shown_windows, spin_exec):
    primary = app_module.SingleInstance(app_module.instance_key())
    assert primary.try_acquire() is True
    try:
        assert app_module.run_gui(fake_core) == 0
    finally:
        primary.close()
    assert shown_windows.shown == [], shown_windows.describe()


# ----------------------------------------------------------------- splash ---

def test_the_splash_carries_the_name_the_version_and_the_phase(qtbot, themed):
    theme.apply(themed, theme.Mode.LIGHT)
    splash = start_splash(themed, "9.8.7")
    assert isinstance(splash, QSplashScreen)
    qtbot.addWidget(splash)

    assert splash.isVisible()
    assert splash.app_name == strings.APP_NAME
    assert splash.version_text == strings.SPLASH_VERSION.format(version="9.8.7")
    assert splash.message() == strings.SPLASH_OPENING
    splash.phase(strings.SPLASH_PAGES)
    assert splash.message() == strings.SPLASH_PAGES
    flags = splash.windowFlags()
    assert flags & flags.FramelessWindowHint


def test_the_splash_is_rendered_at_the_screen_pixel_ratio(qtbot, themed, monkeypatch):
    """HiDPI: the pixmap has device pixels for every logical pixel, not an upscale."""
    monkeypatch.setattr(splash_module, "_pixel_ratio", lambda _screen: 2.0)
    splash = start_splash(themed, "1.0.0")
    qtbot.addWidget(splash)

    pixmap = splash.pixmap()
    assert pixmap.devicePixelRatio() == 2.0
    assert pixmap.size() == QSize(splash_module.WIDTH * 2, splash_module.HEIGHT * 2)


@pytest.mark.parametrize("mode", [theme.Mode.LIGHT, theme.Mode.DARK])
def test_the_splash_follows_the_theme(qtbot, themed, mode):
    """The gradient is the app bar's, so it darkens with the dark theme."""
    theme.apply(themed, mode)
    splash = start_splash(themed, "1.0.0")
    qtbot.addWidget(splash)

    image = splash.pixmap().toImage()
    ratio = splash.pixmap().devicePixelRatio()
    left = image.pixelColor(int(2 * ratio), int(splash_module.HEIGHT * ratio / 2))
    expected = QColor(theme.tokens().header_start)
    assert left.alpha() == 255, "opaque inside the rounded shape"
    assert max(abs(left.red() - expected.red()), abs(left.green() - expected.green()),
               abs(left.blue() - expected.blue())) <= 4, (left.name(), expected.name())


def test_no_screen_means_no_splash_and_no_wait(qapp, monkeypatch):
    monkeypatch.setattr(QGuiApplication, "primaryScreen", staticmethod(lambda: None))
    monkeypatch.setattr(QGuiApplication, "screenAt", staticmethod(lambda _pos: None))
    assert start_splash(qapp, "1.0.0") is None


def test_finish_closes_the_splash_once_the_window_is_shown(qtbot, themed):
    splash = start_splash(themed, "1.0.0")
    window = QWidget()
    qtbot.addWidget(window)
    window.show()
    splash.finish(window)
    assert not splash.isVisible()
