"""The shell: app bar, stacked pages, status bar, shortcuts, close behaviour.

Five sibling tasks plug their page into this window through the ``PAGES``
registry, so the tests are mostly about that contract: what a factory is
called with, what happens when a page is missing, and which optional hooks the
window wires up.
"""
from __future__ import annotations

import threading
from datetime import datetime

import pytest
from PySide6.QtCore import Qt, Signal
from PySide6.QtTest import QTest
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


def spec(key: str, placement: str = "tab", factory=Recorder) -> PageSpec:
    return PageSpec(key, key.title(), "search", factory, placement)


@pytest.fixture
def window(qtbot, fake_core, runner):
    win = MainWindow(fake_core, runner)
    qtbot.addWidget(win)
    win.show()
    return win


# --------------------------------------------------------------- the shell ---

def test_the_registry_lists_two_tabs_then_two_icon_buttons():
    assert [p.key for p in PAGES] == ["search", "sync", "settings", "about"]
    assert [p.label for p in PAGES] == [
        strings.NAV_SEARCH, strings.NAV_SYNC, strings.NAV_SETTINGS, strings.NAV_ABOUT
    ]
    assert [p.placement for p in PAGES] == ["tab", "tab", "icon", "icon"]
    assert [p.icon_name for p in PAGES][2:] == ["settings", "info"]
    assert all(isinstance(p.icon_name, str) and p.icon_name for p in PAGES)
    assert all(callable(p.factory) for p in PAGES)
    assert tuple(PAGES[0]) == (
        PAGES[0].key, PAGES[0].label, PAGES[0].icon_name, PAGES[0].factory, PAGES[0].placement
    ), "PAGES entries stay plain 5-tuples"


def test_the_window_opens_on_ricerca_with_every_page_loaded(window):
    assert window.windowTitle() == strings.WINDOW_TITLE
    assert window.current_page_key() == "search"
    assert sorted(window.pages()) == ["about", "search", "settings", "sync"]


def test_the_app_bar_has_two_tabs_and_two_icon_buttons_in_order(window):
    bar = window.app_bar
    assert list(bar.tabs) == ["search", "sync"]
    assert [b.text() for b in bar.tabs.values()] == [strings.NAV_SEARCH, strings.NAV_SYNC]
    assert list(bar.icon_buttons) == ["settings", "about"]
    assert bar.icon_buttons["settings"].toolTip() == "Impostazioni (Ctrl+,)"
    assert bar.icon_buttons["about"].toolTip() == "Info (F1)"


def test_the_app_bar_sits_above_the_pages(window):
    assert window.app_bar.geometry().bottom() < window.stack.geometry().top()
    assert window.app_bar.width() == window.centralWidget().width()


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

    win = MainWindow(fake_core, runner, pages=[PageSpec("nope", "Nope", "info", missing, "tab")])
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
                         pages=[PageSpec("x", "X", "info", factory, "tab")])
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
                         pages=[PageSpec("sync", "Sync", "info", factory, "tab")])
    qtbot.addWidget(win)

    assert [r.levelname for r in caplog.records] == ["INFO"]


def test_a_page_that_explodes_does_not_take_the_shell_down(qtbot, fake_core, runner):
    def boom(services, runner_, window_):
        raise RuntimeError("bug nella pagina")

    pages = [spec("ok"), PageSpec("bad", "Bad", "info", boom, "tab")]
    win = MainWindow(fake_core, runner, pages=pages)
    qtbot.addWidget(win)
    assert isinstance(win.page("bad"), QLabel)
    assert isinstance(win.page("ok"), Recorder)


# -------------------------------------------------------------- navigation ---

def test_the_window_starts_with_the_focus_in_the_fdi_field(qtbot, window):
    """Typing an FDI right after launch must land in the form, and a stray
    Space/Enter must not press the status chip."""
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow, timeout=2000)
    assert window.focusWidget() is window.page("search").form.omnibox.edit


def test_tab_walks_the_app_bar_in_order_then_enters_the_page(qtbot, window):
    bar = window.app_bar
    expected = [bar.tabs["search"], bar.tabs["sync"], bar.status_chip,
                bar.icon_buttons["settings"], bar.icon_buttons["about"]]
    walked = [expected[0]]
    widget = expected[0]
    for _ in expected[1:]:
        widget = widget.nextInFocusChain()
        while not (widget.focusPolicy() & Qt.FocusPolicy.TabFocus):
            widget = widget.nextInFocusChain()
        walked.append(widget)
    assert walked == expected
    after = widget.nextInFocusChain()
    assert window.stack.isAncestorOf(after), "after the last icon button comes a page"


def test_the_bar_buttons_do_not_take_the_focus_on_click(window):
    bar = window.app_bar
    for button in (*bar.tabs.values(), bar.status_chip, *bar.icon_buttons.values()):
        assert button.focusPolicy() == Qt.FocusPolicy.TabFocus, button


def test_clicking_a_tab_switches_the_stack(qtbot, window):
    qtbot.mouseClick(window.app_bar.tabs["sync"], Qt.MouseButton.LeftButton)
    assert window.current_page_key() == "sync"
    assert window.stack.currentWidget() is window.page("sync")

    qtbot.mouseClick(window.app_bar.icon_buttons["settings"], Qt.MouseButton.LeftButton)
    assert window.current_page_key() == "settings"


def test_the_app_bar_follows_show_page(window):
    window.show_page("about")
    assert not any(b.isChecked() for b in window.app_bar.tabs.values())
    assert window.app_bar.icon_buttons["about"].isChecked()

    window.show_page("search")
    assert window.app_bar.tabs["search"].isChecked()
    assert not window.app_bar.icon_buttons["about"].isChecked()


def test_show_page_ignores_an_unknown_key(window):
    window.show_page("replay")  # a future page, not registered yet
    assert window.current_page_key() == "search"


@pytest.mark.parametrize(
    ("key", "modifier", "expected"),
    [
        (Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier, "search"),
        (Qt.Key.Key_2, Qt.KeyboardModifier.ControlModifier, "sync"),
        (Qt.Key.Key_Comma, Qt.KeyboardModifier.ControlModifier, "settings"),
        (Qt.Key.Key_F1, Qt.KeyboardModifier.NoModifier, "about"),
    ],
)
def test_the_navigation_shortcuts_reach_their_page(qtbot, window, key, modifier, expected):
    """Real key presses, not ``activated.emit()``: the binding itself is under test."""
    window.show_page("search" if expected == "about" else "about")
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow, timeout=2000)
    QTest.keyClick(window, key, modifier)
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

def test_set_status_shows_a_transient_message(window):
    window.set_status("Copiato negli appunti (312 KB)")
    assert window.statusBar().currentMessage() == "Copiato negli appunti (312 KB)"


def test_set_sync_summary_still_fills_the_chip(window):
    """Kept for compatibility: a page that only has a line of text."""
    window.set_sync_summary("svil: oggi 11:23 · coll: oggi 11:24")
    assert window.app_bar.status_chip.summary() == "svil: oggi 11:23 · coll: oggi 11:24"


def test_set_sync_state_fills_the_chip(window):
    window.set_sync_state([("coll", "ok", "oggi 11:24"), ("svil", "warn", "ieri 18:40")])
    chip = window.app_bar.status_chip
    assert chip.summary() == "coll oggi 11:24 · svil ieri 18:40"
    assert [d.property("dot") for d in chip.dots()] == ["ok", "warn"]


def test_clicking_the_chip_opens_the_sync_page(qtbot, window):
    assert window.current_page_key() == "search"
    qtbot.mouseClick(window.app_bar.status_chip, Qt.MouseButton.LeftButton)
    assert window.current_page_key() == "sync"


def test_the_chip_shows_the_state_the_sync_page_had_at_startup(qtbot, fake_core, runner):
    """Important #9: the page computed its state in ``__init__``, before the
    shell connected to it, and the bar said "Mai sincronizzato" until the first
    run. ``emit_initial_state`` is called once every hook is wired."""
    fake_core.sync.set_env_status("coll", last_success=datetime.now().replace(second=0))
    win = MainWindow(fake_core, runner)
    qtbot.addWidget(win)

    summary = win.app_bar.status_chip.summary()
    assert "coll oggi" in summary
    assert "svil mai" in summary


def test_emit_initial_state_is_called_after_the_hooks_are_wired(qtbot, fake_core, runner):
    class Early(QWidget):
        state_changed = Signal(list)

        def __init__(self, services, runner_, window_):
            super().__init__()
            self.state_changed.emit([("coll", "ok", "troppo presto")])  # nobody listens yet

        def emit_initial_state(self):
            self.state_changed.emit([("coll", "ok", "oggi 08:00")])

    win = MainWindow(fake_core, runner, pages=[spec("sync", factory=Early)])
    qtbot.addWidget(win)
    assert win.app_bar.status_chip.summary() == "coll oggi 08:00"


# ------------------------------------------------------------ window title ---

def test_set_context_names_what_is_being_looked_at(window):
    window.set_context("coll · aaaaaaaa")
    assert window.windowTitle() == "qtRequestory — coll · aaaaaaaa"
    window.set_context(None)
    assert window.windowTitle() == strings.WINDOW_TITLE
    window.set_context("")
    assert window.windowTitle() == strings.WINDOW_TITLE


@pytest.mark.parametrize(("job", "label"), [
    ("sync", strings.JOB_SYNC),
    ("index", strings.JOB_INDEX),
    ("scheduler", strings.JOB_SCHEDULER),
])
def test_a_refused_job_is_reported_in_the_status_bar(window, runner, job: str, label: str):
    """The user reads this line, so it names the operation in their language.

    It used to interpolate the internal job name, which put «scheduler» and
    «check-envs» in front of an Italian colleague who has no idea what those
    are — and no way to find out.
    """
    runner.busy.emit(job)
    assert window.statusBar().currentMessage() == strings.STATUS_BUSY.format(name=label)
    assert job not in window.statusBar().currentMessage() or job == label


def test_an_unmapped_job_name_still_says_something(window, runner):
    """A name with no label must not swallow the message: the raw name is a
    poor answer, silence is a worse one."""
    runner.busy.emit("qualcosa-di-nuovo")
    assert "qualcosa-di-nuovo" in window.statusBar().currentMessage()


# ---------------------------------------------------------- optional hooks ---

def test_a_page_summary_signal_feeds_the_chip(qtbot, fake_core, runner):
    class Syncish(QWidget):
        summary_changed = Signal(str)

        def __init__(self, services, runner_, window_):
            super().__init__()

    win = MainWindow(fake_core, runner, pages=[spec("sync", factory=Syncish)])
    qtbot.addWidget(win)

    win.page("sync").summary_changed.emit("coll: non raggiungibile")

    assert win.app_bar.status_chip.summary() == "coll: non raggiungibile"


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
        pages=[spec("search", factory=Listener), spec("settings", "icon", Emitter)],
    )
    qtbot.addWidget(win)
    cfg = fake_core.config.load()

    win.page("settings").config_changed.emit(cfg)

    assert win.page("search").configs == [cfg]


def test_the_page_that_saved_does_not_receive_its_own_broadcast(qtbot, fake_core, runner):
    """It already has that config, and a handler that re-emits would loop."""
    win = MainWindow(
        fake_core, runner,
        pages=[spec("search", factory=Listener), spec("settings", "icon", Emitter)],
    )
    qtbot.addWidget(win)

    win.page("settings").config_changed.emit(fake_core.config.load())

    assert win.page("settings").configs == []


# ------------------------------------------------------------------- close ---

def test_closing_while_a_sync_runs_asks_first(qtbot, window, runner, monkeypatch):
    asked: list[object] = []
    monkeypatch.setattr(
        mw, "confirm_quit_during_job",
        lambda parent, name, detail="": asked.append(parent) or False,
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
    monkeypatch.setattr(mw, "confirm_quit_during_job", lambda parent, name, detail="": True)
    gate = threading.Event()
    job = runner.submit("sync", lambda *, cancel: gate.wait(5.0))

    assert window.close() is True
    assert job.token.is_set() is True
    gate.set()
    with qtbot.waitSignal(job.signals.finished, timeout=5000):
        pass


def test_closing_without_a_sync_asks_nothing(window, monkeypatch):
    monkeypatch.setattr(mw, "confirm_quit_during_job", _must_not_be_called)
    assert window.close() is True


def test_the_answer_follows_the_button_the_user_pressed(window, monkeypatch):
    """`confirm_quit_during_job` maps the two buttons onto True/False."""
    from PySide6.QtWidgets import QMessageBox

    from qtrequestory.ui import quit_dialog as qd

    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    real_build = qd.build_quit_dialog
    built: list[QMessageBox] = []

    def build(answer_stop: bool):
        def builder(parent, name, detail=""):
            box, stop = real_build(parent, name, detail)
            keep = next(b for b in box.buttons() if b is not stop)
            box.clickedButton = (lambda: stop) if answer_stop else (lambda: keep)
            built.append(box)
            return box, stop
        return builder

    monkeypatch.setattr(qd, "build_quit_dialog", build(answer_stop=True))
    assert qd.confirm_quit_during_job(window, "sync") is True

    monkeypatch.setattr(qd, "build_quit_dialog", build(answer_stop=False))
    assert qd.confirm_quit_during_job(window, "sync") is False

    assert len(built) == 2, "each question builds (and drops) its own dialog"


def test_the_quit_dialog_offers_the_two_documented_choices(qtbot, window):
    box, stop = mw.build_quit_dialog(window, "sync")
    qtbot.addWidget(box)
    labels = [b.text() for b in box.buttons()]
    assert stop.text() == strings.QUIT_STOP
    assert strings.QUIT_CONTINUE in labels
    assert box.windowTitle() == strings.QUIT_DURING_JOB_TITLE.format(label=strings.JOB_SYNC)


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


def _must_not_be_called(parent, *_args):  # pragma: no cover - guard
    raise AssertionError("no question must be asked when nothing is running")


# ------------------------------------------------------- rerun the wizard ---

def test_rerun_wizard_says_so_when_the_wizard_is_not_part_of_this_build(window, monkeypatch):
    """Impostazioni offers "Riesegui configurazione iniziale" through this.

    This build ships the wizard (Task 10) and running it would open a modal
    dialog, so the missing-module case is simulated at the seam the window
    asks — the point of the test is the message, not the absence.
    """
    from qtrequestory.ui import app as app_module

    monkeypatch.setattr(app_module, "wizard_available", lambda: False)

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


# ------------------------------------------------------- data changed ------

class DataPage(QWidget):
    """A page that counts the shell's ``on_data_changed`` calls."""

    def __init__(self, services, runner, window):
        super().__init__()
        self.data_changes = 0

    def on_data_changed(self):
        self.data_changes += 1


@pytest.mark.parametrize("job, refreshed", [("sync", True), ("index", True), ("search", False)])
def test_pages_are_refreshed_after_a_sync_or_an_index(qtbot, fake_core, runner, job, refreshed):
    win = MainWindow(fake_core, runner, pages=[spec("a", factory=DataPage),
                                                spec("b", factory=DataPage)])
    qtbot.addWidget(win)
    runner.submit(job, lambda: None)
    with qtbot.waitSignal(runner.job_finished, timeout=5000):
        pass
    expected = 1 if refreshed else 0
    assert [win.page(k).data_changes for k in ("a", "b")] == [expected, expected]


def test_a_failed_sync_still_refreshes_the_pages(qtbot, fake_core, runner):
    """A run that ended in errors may still have downloaded half the files."""
    win = MainWindow(fake_core, runner, pages=[spec("a", factory=DataPage)])
    qtbot.addWidget(win)

    def boom():
        raise RuntimeError("rete")

    runner.submit("sync", boom)
    with qtbot.waitSignal(runner.job_finished, timeout=5000):
        pass
    assert win.page("a").data_changes == 1


# ----------------------------------------------------------- startup ------

def wait_idle(qtbot, runner, *names):
    qtbot.waitUntil(lambda: not any(runner.is_running(n) for n in names), timeout=15000)


def test_startup_indexes_pending_files_then_syncs_without_forcing(qtbot, fake_core, runner):
    fake_core.index.set_pending(2)
    win = MainWindow(fake_core, runner)
    qtbot.addWidget(win)

    win.startup_tasks()
    qtbot.waitUntil(lambda: bool(fake_core.sync.runs), timeout=15000)
    wait_idle(qtbot, runner, "index", "sync")

    assert fake_core.index.updates == [{"envs": ["coll", "svil"], "full_rebuild": False}]
    assert fake_core.sync.runs == [{"envs": ("coll", "svil"), "force": False, "dry_run": False}]
    assert win.current_page_key() == "search", "a background sync must not steal the page"


def test_startup_skips_the_index_when_nothing_is_pending(qtbot, fake_core, runner):
    win = MainWindow(fake_core, runner)
    qtbot.addWidget(win)

    win.startup_tasks()
    qtbot.waitUntil(lambda: bool(fake_core.sync.runs), timeout=15000)
    wait_idle(qtbot, runner, "index", "sync")

    assert fake_core.index.updates == []


def test_startup_does_not_sync_while_the_scheduled_task_holds_the_lock(qtbot, fake_core, runner):
    fake_core.index.set_pending(1)
    fake_core.sync.set_lock_holder("pid 1234")
    win = MainWindow(fake_core, runner)
    qtbot.addWidget(win)

    win.startup_tasks()
    qtbot.waitUntil(lambda: bool(fake_core.index.updates), timeout=15000)
    wait_idle(qtbot, runner, "index")
    qtbot.wait(100)

    assert fake_core.sync.runs == []


def test_startup_with_nothing_configured_starts_nothing(qtbot, fake_core, runner):
    import dataclasses

    fake_core.config.config = dataclasses.replace(fake_core.config.config, environments=[])
    win = MainWindow(fake_core, runner)
    qtbot.addWidget(win)

    win.startup_tasks()
    qtbot.wait(100)

    assert runner.job("index") is None and runner.job("sync") is None


# ------------------------------------------------------- wizard rerun ------

class ConfigPage(QWidget):
    def __init__(self, services, runner, window):
        super().__init__()
        self.configs: list[object] = []
        self.syncs = 0

    def on_config_changed(self, cfg):
        self.configs.append(cfg)

    def start_sync(self):
        self.syncs += 1


@pytest.mark.parametrize("start_sync", [True, False])
def test_rerun_wizard_broadcasts_the_new_config_and_honours_start_sync(
        qtbot, fake_core, runner, monkeypatch, start_sync):
    from qtrequestory.ui import app as app_module
    from qtrequestory.ui.wizard import WizardResult

    win = MainWindow(fake_core, runner, pages=[spec("search", factory=ConfigPage),
                                                spec("sync", factory=ConfigPage)])
    qtbot.addWidget(win)
    cfg = fake_core.config.load()
    result = WizardResult(config=cfg, start_sync=start_sync, autosync=True)
    monkeypatch.setattr(app_module, "wizard_available", lambda: True)
    monkeypatch.setattr(app_module, "show_first_run_wizard", lambda *a, **kw: result)

    assert win.rerun_wizard() is result

    assert win.page("search").configs == [cfg]
    assert win.page("sync").configs == [cfg]
    assert win.page("sync").syncs == (1 if start_sync else 0)


def test_a_cancelled_rerun_broadcasts_nothing(qtbot, fake_core, runner, monkeypatch):
    from qtrequestory.ui import app as app_module

    win = MainWindow(fake_core, runner, pages=[spec("search", factory=ConfigPage)])
    qtbot.addWidget(win)
    monkeypatch.setattr(app_module, "wizard_available", lambda: True)
    monkeypatch.setattr(app_module, "show_first_run_wizard", lambda *a, **kw: None)

    assert win.rerun_wizard() is None
    assert win.page("search").configs == []


# ------------------------------------------- close during an index job ------

def _recording_confirm(asked: list, answer: bool):
    def confirm(parent, name, detail=""):
        asked.append((name, detail))
        return answer
    return confirm


def test_closing_while_the_index_is_rebuilt_asks_first(qtbot, window, runner, monkeypatch):
    asked: list[tuple] = []
    monkeypatch.setattr(mw, "confirm_quit_during_job", _recording_confirm(asked, False))
    gate = threading.Event()
    job = runner.submit("index", lambda: gate.wait(5.0))
    try:
        assert window.close() is False
        assert asked == [("index", "")]
    finally:
        gate.set()
    with qtbot.waitSignal(job.signals.finished, timeout=5000):
        pass


def test_stopping_the_index_on_close_cancels_it(qtbot, window, runner, monkeypatch):
    monkeypatch.setattr(mw, "confirm_quit_during_job", _recording_confirm([], True))
    gate = threading.Event()
    job = runner.submit("index", lambda *, cancel: gate.wait(5.0))
    assert window.close() is True
    assert job.token.is_set() is True
    gate.set()
    with qtbot.waitSignal(job.signals.finished, timeout=5000):
        pass


def test_the_sync_question_counts_the_files(qtbot, window, runner, monkeypatch):
    from qtrequestory.ui.contracts import FileStarted, RemoteIndexRead, SyncStarted

    asked: list[tuple] = []
    monkeypatch.setattr(mw, "confirm_quit_during_job", _recording_confirm(asked, False))
    sync_page = window.page("sync")
    events = [SyncStarted(("coll",), False), RemoteIndexRead("coll", 48, 0, 0, 10)]
    events += [FileStarted("coll", f"2026010{i}.txt", 1) for i in range(1, 4)]
    for ev in events:
        sync_page.presenter.handle(ev)
    gate = threading.Event()
    job = runner.submit("sync", lambda: gate.wait(5.0))
    try:
        assert window.close() is False
        assert asked == [("sync", strings.QUIT_PROGRESS.format(done=3, total=48))]
    finally:
        gate.set()
    with qtbot.waitSignal(job.signals.finished, timeout=5000):
        pass


@pytest.mark.parametrize("job, detail", [("sync", "3 di 48 file"), ("index", "")])
def test_the_quit_dialog_names_the_running_operation(qtbot, window, job, detail):
    box, stop = mw.build_quit_dialog(window, job, detail)
    qtbot.addWidget(box)
    label = mw.job_label(job)
    assert box.windowTitle() == strings.QUIT_DURING_JOB_TITLE.format(label=label)
    assert label in box.text()
    if detail:
        assert detail in box.text()
    assert stop.text() == strings.QUIT_STOP


def test_startup_does_nothing_when_the_log_folder_is_not_valid(qtbot, fake_core, runner):
    """Final review #1: the CLI refuses an empty/relative mirror_root; the
    window's own startup jobs must not index or sync into the CWD either."""
    import dataclasses
    from pathlib import Path

    fake_core.index.set_pending(2)
    fake_core.config.config = dataclasses.replace(fake_core.config.config, mirror_root=Path(""))
    win = MainWindow(fake_core, runner)
    qtbot.addWidget(win)

    win.startup_tasks()
    qtbot.wait(150)

    assert runner.job("index") is None and runner.job("sync") is None
    assert fake_core.index.updates == [] and fake_core.sync.runs == []


# ------------------------------------------------- chip stays current ------

OLD_RUN = datetime(2020, 1, 2, 3, 4)


def test_the_window_refreshes_the_chip_after_a_run_it_did_not_start(qtbot, fake_core, runner):
    """Final review #5: a scheduled --sync changes env_status behind the
    window's back; the slow window-level refresh re-emits the chip state."""
    win = MainWindow(fake_core, runner)
    qtbot.addWidget(win)
    assert "svil mai" in win.app_bar.status_chip.summary()

    fake_core.sync.set_env_status("svil", last_success=OLD_RUN)
    win.sync_state_timer.timeout.emit()

    assert "svil 02/01/2020 03:04" in win.app_bar.status_chip.summary()


def test_the_chip_refresh_is_slow_and_also_runs_when_the_window_is_activated(
        qtbot, fake_core, runner, monkeypatch):
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication

    win = MainWindow(fake_core, runner)
    qtbot.addWidget(win)
    assert win.sync_state_timer.interval() == mw.SYNC_STATE_REFRESH_MS >= 60_000
    assert win.sync_state_timer.isActive()

    fake_core.sync.set_env_status("svil", last_success=OLD_RUN)
    monkeypatch.setattr(win, "isActiveWindow", lambda: True)
    QApplication.sendEvent(win, QEvent(QEvent.Type.ActivationChange))

    assert "svil 02/01/2020 03:04" in win.app_bar.status_chip.summary()


def test_the_chip_refresh_takes_no_lock_and_calls_no_scheduler(qtbot, fake_core, runner, monkeypatch):
    win = MainWindow(fake_core, runner)
    qtbot.addWidget(win)
    monkeypatch.setattr(fake_core.sync, "lock_holder", lambda: pytest.fail("no lock peek"))
    monkeypatch.setattr(fake_core.scheduler, "status", lambda: pytest.fail("no schtasks"))
    win.sync_state_timer.timeout.emit()
