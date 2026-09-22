"""The shell: rail, stacked pages, status bar, shortcuts, close behaviour.

Five sibling tasks plug their page into this window through the ``PAGES``
registry, so the tests are mostly about that contract: what a factory is
called with, what happens when a page is missing, and which optional hooks the
window wires up.
"""
from __future__ import annotations

import threading

import pytest
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QWidget

from qtrequestory.ui import main_window as mw
from qtrequestory.ui import strings
from qtrequestory.ui.main_window import PAGES, MainWindow, PageSpec


class Recorder(QWidget):
    """A stand-in page that remembers how its factory was called."""

    def __init__(self, services, runner, window):
        super().__init__()
        self.services = services
        self.runner = runner
        self.window = window


def spec(key: str, section: str = "top", factory=Recorder) -> PageSpec:
    return PageSpec(key, key.title(), "search", factory, section)


@pytest.fixture
def window(qtbot, fake_core, runner):
    win = MainWindow(fake_core, runner)
    qtbot.addWidget(win)
    win.show()
    return win


# --------------------------------------------------------------- the shell ---

def test_the_registry_lists_the_four_v1_pages_in_two_groups():
    assert [p.key for p in PAGES] == ["search", "sync", "settings", "about"]
    assert [p.label for p in PAGES] == [
        strings.NAV_SEARCH, strings.NAV_SYNC, strings.NAV_SETTINGS, strings.NAV_ABOUT
    ]
    assert [p.section for p in PAGES] == ["top", "top", "bottom", "bottom"]
    assert all(isinstance(p.icon_name, str) and p.icon_name for p in PAGES)
    assert all(callable(p.factory) for p in PAGES)
    assert tuple(PAGES[0]) == (
        PAGES[0].key, PAGES[0].label, PAGES[0].icon_name, PAGES[0].factory, PAGES[0].section
    ), "PAGES entries stay plain 5-tuples"


def test_the_window_opens_on_ricerca_with_every_page_loaded(window):
    assert window.windowTitle() == strings.WINDOW_TITLE
    assert window.current_page_key() == "search"
    assert sorted(window.pages()) == ["about", "search", "settings", "sync"]
    assert window.rail_top.count() == 2 and window.rail_bottom.count() == 2


def test_a_factory_receives_the_services_the_runner_and_the_window(qtbot, fake_core, runner):
    win = MainWindow(fake_core, runner, pages=[spec("demo")])
    qtbot.addWidget(win)
    page = win.page("demo")
    assert page.services is fake_core
    assert page.runner is runner
    assert page.window is win


def test_a_missing_page_module_degrades_to_a_placeholder(qtbot, fake_core, runner):
    """Task 9 must run standalone while tasks 10-14 are still being written."""
    def missing(services, runner_, window_):
        raise ModuleNotFoundError("qtrequestory.ui.pages.nope")

    win = MainWindow(fake_core, runner, pages=[PageSpec("nope", "Nope", "info", missing, "top")])
    qtbot.addWidget(win)

    placeholder = win.page("nope")
    assert isinstance(placeholder, QLabel)
    assert placeholder.text() == strings.PAGE_UNAVAILABLE.format(label="Nope")


def test_a_broken_import_inside_a_page_is_reported_as_an_error(qtbot, fake_core, runner, caplog):
    """A page whose own import is missing is a bug, not a task still to land."""
    def factory(services, runner_, window_):
        raise ModuleNotFoundError("No module named 'requests'", name="requests")

    with caplog.at_level("INFO", logger="qtrequestory.ui.main_window"):
        win = MainWindow(fake_core, runner,
                         pages=[PageSpec("x", "X", "info", factory, "top")])
    qtbot.addWidget(win)

    assert isinstance(win.page("x"), QLabel)
    assert [r.levelname for r in caplog.records] == ["ERROR"]


def test_a_page_module_that_does_not_exist_yet_is_only_an_info_line(
    qtbot, fake_core, runner, caplog
):
    def factory(services, runner_, window_):
        raise ModuleNotFoundError("No module named 'qtrequestory.ui.pages.sync_page'",
                                  name="qtrequestory.ui.pages.sync_page")

    with caplog.at_level("INFO", logger="qtrequestory.ui.main_window"):
        win = MainWindow(fake_core, runner,
                         pages=[PageSpec("sync", "Sync", "info", factory, "top")])
    qtbot.addWidget(win)

    assert [r.levelname for r in caplog.records] == ["INFO"]


def test_a_page_that_explodes_does_not_take_the_shell_down(qtbot, fake_core, runner):
    def boom(services, runner_, window_):
        raise RuntimeError("bug nella pagina")

    pages = [spec("ok"), PageSpec("bad", "Bad", "info", boom, "top")]
    win = MainWindow(fake_core, runner, pages=pages)
    qtbot.addWidget(win)
    assert isinstance(win.page("bad"), QLabel)
    assert isinstance(win.page("ok"), Recorder)


# -------------------------------------------------------------- navigation ---

def test_clicking_the_rail_switches_page(window):
    window.rail_top.setCurrentRow(1)
    assert window.current_page_key() == "sync"

    window.rail_bottom.setCurrentRow(0)
    assert window.current_page_key() == "settings"


def test_only_one_rail_group_shows_a_selection(window):
    window.show_page("settings")
    assert window.rail_top.currentRow() == -1
    assert window.rail_bottom.currentRow() == 0

    window.show_page("search")
    assert window.rail_top.currentRow() == 0
    assert window.rail_bottom.currentRow() == -1


def test_show_page_ignores_an_unknown_key(window):
    window.show_page("replay")  # a future page, not registered yet
    assert window.current_page_key() == "search"


@pytest.mark.parametrize(
    ("sequence", "expected"),
    [("Ctrl+1", "search"), ("Ctrl+2", "sync"), ("Ctrl+,", "settings")],
)
def test_the_navigation_shortcuts_reach_their_page(qtbot, window, sequence, expected):
    window.show_page("about")
    assert window.shortcuts[sequence].key().toString() == sequence
    window.shortcuts[sequence].activated.emit()
    assert window.current_page_key() == expected


def test_sincronizza_ora_jumps_to_the_sync_page_and_asks_it_to_start(qtbot, fake_core, runner):
    class StartablePage(Recorder):
        def __init__(self, services, runner_, window_):
            super().__init__(services, runner_, window_)
            self.started = 0

        def start_sync(self):
            self.started += 1

    win = MainWindow(fake_core, runner, pages=[spec("search"), spec("sync", factory=StartablePage)])
    qtbot.addWidget(win)

    win.shortcuts["Ctrl+Shift+S"].activated.emit()

    assert win.current_page_key() == "sync"
    assert win.page("sync").started == 1


# -------------------------------------------------------------- status bar ---

def test_switching_to_dark_mode_re_tints_the_rail_icons(qtbot, window, monkeypatch):
    """The glyphs are tinted for the palette: a theme switch must redo them."""
    from PySide6.QtGui import QColor, QGuiApplication
    from qtrequestory.ui import icons

    before = window.rail_top.item(0).icon().pixmap(20, 20).toImage()
    hints = QGuiApplication.styleHints()
    real_icon = icons.icon
    monkeypatch.setattr(icons, "icon", lambda name, color=None: real_icon(name, QColor("#FF00FF")))

    hints.colorSchemeChanged.emit(hints.colorScheme())

    after = window.rail_top.item(0).icon().pixmap(20, 20).toImage()
    assert before != after


def test_set_status_shows_a_transient_message(window):
    window.set_status("Copiato negli appunti (312 KB)")
    assert window.statusBar().currentMessage() == "Copiato negli appunti (312 KB)"


def test_the_sync_summary_starts_empty_and_can_be_replaced(window):
    assert window.sync_summary.text() == strings.STATUS_SYNC_SUMMARY_EMPTY
    window.set_sync_summary("svil: oggi 11:23 · coll: oggi 11:24")
    assert window.sync_summary.text() == "svil: oggi 11:23 · coll: oggi 11:24"


def test_clicking_the_sync_summary_opens_the_sync_page(qtbot, window):
    assert window.current_page_key() == "search"
    qtbot.mouseClick(window.sync_summary, Qt.MouseButton.LeftButton)
    assert window.current_page_key() == "sync"


def test_a_refused_job_is_reported_in_the_status_bar(window, runner):
    runner.busy.emit("sync")
    assert window.statusBar().currentMessage() == strings.STATUS_BUSY.format(name="sync")


# ---------------------------------------------------------- optional hooks ---

def test_a_page_summary_signal_feeds_the_status_bar(qtbot, fake_core, runner):
    class Syncish(QWidget):
        summary_changed = Signal(str)

        def __init__(self, services, runner_, window_):
            super().__init__()

    win = MainWindow(fake_core, runner, pages=[spec("sync", factory=Syncish)])
    qtbot.addWidget(win)

    win.page("sync").summary_changed.emit("coll: non raggiungibile")

    assert win.sync_summary.text() == "coll: non raggiungibile"


class Listener(Recorder):
    """A page that reloads when Impostazioni saves."""

    def __init__(self, services, runner_, window_):
        super().__init__(services, runner_, window_)
        self.configs: list[object] = []

    def on_config_changed(self, cfg):
        self.configs.append(cfg)


class Emitter(Listener):
    """Impostazioni: emits the new config *and* has a reload handler of its own."""

    config_changed = Signal(object)


def test_a_saved_configuration_is_broadcast_to_the_other_pages(qtbot, fake_core, runner):
    win = MainWindow(
        fake_core, runner,
        pages=[spec("search", factory=Listener), spec("settings", "bottom", Emitter)],
    )
    qtbot.addWidget(win)
    cfg = fake_core.config.load()

    win.page("settings").config_changed.emit(cfg)

    assert win.page("search").configs == [cfg]


def test_the_page_that_saved_does_not_receive_its_own_broadcast(qtbot, fake_core, runner):
    """It already has that config, and a handler that re-emits would loop."""
    win = MainWindow(
        fake_core, runner,
        pages=[spec("search", factory=Listener), spec("settings", "bottom", Emitter)],
    )
    qtbot.addWidget(win)

    win.page("settings").config_changed.emit(fake_core.config.load())

    assert win.page("settings").configs == []


# ------------------------------------------------------------------- close ---

def test_closing_while_a_sync_runs_asks_first(qtbot, window, runner, monkeypatch):
    asked: list[object] = []
    monkeypatch.setattr(
        mw, "confirm_quit_during_sync", lambda parent: asked.append(parent) or False
    )
    gate = threading.Event()
    job = runner.submit("sync", lambda: gate.wait(5.0))
    try:
        assert window.close() is False, "answering Continua keeps the window open"
        assert asked == [window]
        assert job.token.is_set() is False
    finally:
        gate.set()
    with qtbot.waitSignal(job.signals.finished, timeout=5000):
        pass


def test_interrompi_ed_esci_cancels_the_sync_and_closes(qtbot, window, runner, monkeypatch):
    monkeypatch.setattr(mw, "confirm_quit_during_sync", lambda parent: True)
    gate = threading.Event()
    job = runner.submit("sync", lambda *, cancel: gate.wait(5.0))

    assert window.close() is True
    assert job.token.is_set() is True
    gate.set()
    with qtbot.waitSignal(job.signals.finished, timeout=5000):
        pass


def test_closing_without_a_sync_asks_nothing(window, monkeypatch):
    monkeypatch.setattr(mw, "confirm_quit_during_sync", _must_not_be_called)
    assert window.close() is True


def test_the_answer_follows_the_button_the_user_pressed(window, monkeypatch):
    """`confirm_quit_during_sync` maps the two buttons onto True/False."""
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    real_build = mw.build_quit_dialog
    built: list[QMessageBox] = []

    def build(answer_stop: bool):
        def builder(parent):
            box, stop = real_build(parent)
            keep = next(b for b in box.buttons() if b is not stop)
            box.clickedButton = (lambda: stop) if answer_stop else (lambda: keep)
            built.append(box)
            return box, stop
        return builder

    monkeypatch.setattr(mw, "build_quit_dialog", build(answer_stop=True))
    assert mw.confirm_quit_during_sync(window) is True

    monkeypatch.setattr(mw, "build_quit_dialog", build(answer_stop=False))
    assert mw.confirm_quit_during_sync(window) is False

    assert len(built) == 2, "each question builds (and drops) its own dialog"


def test_the_quit_dialog_offers_the_two_documented_choices(qtbot, window):
    box, stop = mw.build_quit_dialog(window)
    qtbot.addWidget(box)
    labels = [b.text() for b in box.buttons()]
    assert stop.text() == strings.QUIT_STOP
    assert strings.QUIT_CONTINUE in labels
    assert box.windowTitle() == strings.QUIT_DURING_SYNC_TITLE


# -------------------------------------------------------------- persistence ---

def test_the_window_geometry_survives_a_restart(qtbot, fake_core, runner):
    first = MainWindow(fake_core, runner, pages=[spec("search")])
    qtbot.addWidget(first)
    first.show()
    first.resize(640, 480)  # the offscreen screen is 800x600: stay inside it
    first.close()

    second = MainWindow(fake_core, runner, pages=[spec("search")])
    qtbot.addWidget(second)
    second.show()

    assert second.size().width() == 640
    assert second.size().height() == 480


def _must_not_be_called(parent):  # pragma: no cover - guard
    raise AssertionError("no question must be asked when nothing is running")


# ------------------------------------------------------- rerun the wizard ---

def test_rerun_wizard_says_so_when_the_wizard_is_not_part_of_this_build(window):
    """Impostazioni offers "Riesegui configurazione iniziale" through this."""
    assert window.rerun_wizard() is None
    assert window.statusBar().currentMessage() == strings.WIZARD_UNAVAILABLE


def test_rerun_wizard_passes_the_window_as_the_parent(window, fake_core, runner, monkeypatch):
    from qtrequestory.ui import app as app_module

    calls: list[tuple] = []
    monkeypatch.setattr(app_module, "wizard_available", lambda: True)
    monkeypatch.setattr(
        app_module, "show_first_run_wizard",
        lambda services, job_runner, parent=None: calls.append((services, job_runner, parent)),
    )

    window.rerun_wizard()

    assert calls == [(fake_core, runner, window)]
