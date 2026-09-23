"""Application entry point: single instance, first run, main window.

``run_gui`` is exercised with a stubbed ``QApplication.exec`` — everything that
happens before and after the event loop is what matters here.
"""
from __future__ import annotations

import builtins
import os
import sys
import types

import pytest
from PySide6.QtWidgets import QApplication

from qtrequestory.ui import app as app_module
from qtrequestory.ui import theme
from qtrequestory.ui.app import (
    configure_application,
    INSTANCE_KEY_ENV_VAR,
    SingleInstance,
    instance_key,
    run_gui,
    show_first_run_wizard,
)
from qtrequestory.ui.main_window import MainWindow


@pytest.fixture
def key(request) -> str:
    """A pipe name unique to this test AND this process.

    Pipe names are machine-global: with only the test name in it, two pytest
    runs on the same box steal the name from each other and this file flakes.
    """
    return f"qtrequestory-test-{os.getpid()}-{request.node.name}"


@pytest.fixture(autouse=True)
def restore_theme(themed):
    """``run_gui`` applies the theme to the shared QApplication; undo it."""
    yield


@pytest.fixture
def stub_exec(monkeypatch):
    """Replace the event loop with a callback that inspects the open windows."""
    windows: list[MainWindow] = []

    def fake_exec(self) -> int:
        windows.extend(
            w for w in QApplication.topLevelWidgets() if isinstance(w, MainWindow) and w.isVisible()
        )
        return 7

    monkeypatch.setattr(QApplication, "exec", fake_exec)
    yield windows
    for window in windows:
        window.close()


# ---------------------------------------------------------------- theme ---

def test_configure_application_applies_the_saved_theme(qapp):
    theme.save_mode(theme.Mode.DARK)

    configure_application(qapp, "1.2.3")

    assert qapp.styleSheet() == theme.build_qss(theme.DARK)
    assert qapp.palette().window().color().name().upper() == theme.DARK.bg
    qapp.setStyleSheet("")  # the stylesheet wrapper has no name of its own
    assert qapp.style().name().lower() == "fusion", "never the native windows11 style"


# --------------------------------------------------------- single instance ---

def test_the_instance_key_is_per_user(monkeypatch):
    monkeypatch.delenv(INSTANCE_KEY_ENV_VAR, raising=False)
    monkeypatch.setenv("USERNAME", "mrossi")
    assert instance_key() == "qtrequestory-mrossi"


def test_the_instance_key_can_be_overridden_for_a_test_run(monkeypatch):
    """Two pytest runs on one machine must not share the pipe (see the fixture)."""
    monkeypatch.setenv("USERNAME", "mrossi")
    monkeypatch.setenv(INSTANCE_KEY_ENV_VAR, "qtrequestory-test-1234")
    assert instance_key() == "qtrequestory-test-1234"


def test_a_second_instance_activates_the_first_and_does_not_start(qtbot, key):
    primary = SingleInstance(key)
    assert primary.try_acquire() is True

    second = SingleInstance(key)
    try:
        with qtbot.waitSignal(primary.activated, timeout=3000):
            assert second.try_acquire() is False
    finally:
        second.close()
        primary.close()


def test_the_key_is_free_again_after_the_first_instance_stops(qtbot, key):
    first = SingleInstance(key)
    assert first.try_acquire() is True
    first.close()

    second = SingleInstance(key)
    try:
        assert second.try_acquire() is True
    finally:
        second.close()


# ------------------------------------------------------------ first run ---

@pytest.fixture
def without_wizard(monkeypatch):
    """A build that does not ship ``ui/wizard.py``.

    It does ship now (Task 10), so the absence is simulated at the seam both
    ``wizard_available`` and ``show_first_run_wizard`` go through — which is
    what these two tests were always about: the shell must survive a wizard
    that is not there, not the wizard being genuinely missing.
    """
    monkeypatch.setattr(app_module, "_wizard_entry_point", lambda: None)


def test_this_build_ships_the_wizard():
    assert app_module.wizard_available() is True


def test_a_build_packaged_without_the_wizard_has_no_entry_point(monkeypatch):
    """The lazy import's ``except ImportError`` branch.

    ``_wizard_entry_point`` is what makes the shell tolerate a build that does
    not bundle ``ui/wizard.py``; the other tests stub the seam itself, so the
    real import failure is exercised here by making that one import raise.
    """
    real_import = builtins.__import__

    def refuse_the_wizard(name, *args, **kwargs):
        if name == "qtrequestory.ui.wizard":
            raise ImportError("No module named 'qtrequestory.ui.wizard'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse_the_wizard)

    assert app_module._wizard_entry_point() is None
    assert app_module.wizard_available() is False


def test_without_the_wizard_module_the_app_still_starts(fake_core, runner, without_wizard):
    assert app_module.wizard_available() is False
    assert show_first_run_wizard(fake_core, runner) is None


def test_a_first_run_without_the_wizard_still_opens_the_window(
    qtbot, fake_core, monkeypatch, key, stub_exec, without_wizard
):
    monkeypatch.setattr(app_module, "instance_key", lambda: key)
    fake_core.config.first_run = True

    assert run_gui(fake_core) == 7
    assert len(stub_exec) == 1


def test_the_wizard_is_called_with_the_services_the_runner_and_the_parent(
    monkeypatch, fake_core, runner
):
    calls: list[tuple] = []
    module = types.ModuleType("qtrequestory.ui.wizard")
    module.run_first_run_wizard = lambda services, job_runner, parent=None: (
        calls.append((services, job_runner, parent)) or "risultato"
    )
    monkeypatch.setitem(sys.modules, "qtrequestory.ui.wizard", module)

    assert app_module.wizard_available() is True
    assert show_first_run_wizard(fake_core, runner) == "risultato"
    assert calls == [(fake_core, runner, None)]


# ---------------------------------------------------------------- run_gui ---

def test_run_gui_opens_the_window_and_returns_the_event_loop_code(
    qtbot, fake_core, monkeypatch, key, stub_exec
):
    monkeypatch.setattr(app_module, "instance_key", lambda: key)

    assert run_gui(fake_core) == 7
    assert len(stub_exec) == 1
    assert stub_exec[0].current_page_key() == "search"
    assert QApplication.instance().applicationName() == "qtRequestory"


def test_run_gui_runs_the_wizard_on_a_first_run(qtbot, fake_core, monkeypatch, key, stub_exec):
    monkeypatch.setattr(app_module, "instance_key", lambda: key)
    fake_core.config.first_run = True
    monkeypatch.setattr(app_module, "wizard_available", lambda: True)
    shown: list[str] = []
    monkeypatch.setattr(
        app_module, "show_first_run_wizard",
        lambda services, runner, parent=None: shown.append("wizard") or _Result(start_sync=False),
    )

    assert run_gui(fake_core) == 7
    assert shown == ["wizard"]
    assert len(stub_exec) == 1


def test_a_cancelled_wizard_quits_without_a_window(qtbot, fake_core, monkeypatch, key, stub_exec):
    monkeypatch.setattr(app_module, "instance_key", lambda: key)
    fake_core.config.first_run = True
    monkeypatch.setattr(app_module, "wizard_available", lambda: True)
    monkeypatch.setattr(app_module, "show_first_run_wizard", lambda *a, **kw: None)

    assert run_gui(fake_core) == 0
    assert stub_exec == [], "the event loop is never entered"


def test_a_cancelled_wizard_leaves_the_next_launch_a_first_run(
    qtbot, fake_core, monkeypatch, key, stub_exec, tmp_path
):
    """Against the REAL config service: cancelling must leave no config behind.

    ``load_config`` used to write the defaults on a first run, so the second
    launch found a ``config.json`` and the wizard was never offered again — the
    user was stuck with an unconfigured tool and no way back short of deleting
    the file by hand.
    """
    import dataclasses

    from qtrequestory.core.facade import ConfigService
    from qtrequestory.core.paths import AppPaths

    paths = AppPaths(tmp_path / "home").ensure()
    config = ConfigService(paths)
    services = dataclasses.replace(fake_core, config=config, paths=paths)
    monkeypatch.setattr(app_module, "instance_key", lambda: key)
    monkeypatch.setattr(app_module, "wizard_available", lambda: True)
    monkeypatch.setattr(app_module, "show_first_run_wizard", lambda *a, **kw: None)

    assert config.is_first_run() is True
    assert run_gui(services) == 0

    assert not paths.config_file.exists()
    assert ConfigService(paths).is_first_run() is True


def test_the_wizard_can_ask_for_a_first_sync(qtbot, fake_core, monkeypatch, key, stub_exec):
    monkeypatch.setattr(app_module, "instance_key", lambda: key)
    fake_core.config.first_run = True
    monkeypatch.setattr(app_module, "wizard_available", lambda: True)
    monkeypatch.setattr(
        app_module, "show_first_run_wizard", lambda *a, **kw: _Result(start_sync=True)
    )

    assert run_gui(fake_core) == 7
    assert stub_exec[0].current_page_key() == "sync"


def test_a_second_process_returns_immediately_without_a_window(
    qtbot, fake_core, monkeypatch, key, stub_exec
):
    monkeypatch.setattr(app_module, "instance_key", lambda: key)
    primary = SingleInstance(key)
    assert primary.try_acquire() is True
    try:
        assert run_gui(fake_core) == 0
        assert stub_exec == []
    finally:
        primary.close()


class _Result:
    """Stand-in for Task 10's ``WizardResult``."""

    def __init__(self, start_sync: bool) -> None:
        self.start_sync = start_sync
        self.autosync = True
        self.config = None


# ------------------------------------------------------ AppUserModelID ---
#
# Without an explicit AppUserModelID the onefile child process is grouped under
# a generic identity and the taskbar shows the default Windows icon.

def test_run_gui_sets_app_user_model_id_before_the_application(
    qtbot, fake_core, monkeypatch, key, stub_exec
):
    monkeypatch.setattr(app_module, "instance_key", lambda: key)
    calls: list[str] = []
    real_app = QApplication.instance()

    class RecordingApplication:
        """Stands in for QApplication: records when run_gui first reaches for it."""

        @staticmethod
        def instance():
            calls.append("QApplication.instance")
            return None

        def __new__(cls, *args, **kwargs):
            calls.append("QApplication()")
            return real_app

    monkeypatch.setattr(app_module, "QApplication", RecordingApplication)
    monkeypatch.setattr(app_module, "set_app_user_model_id", lambda: calls.append("aumid"))

    assert run_gui(fake_core) == 7
    assert calls[:3] == ["aumid", "QApplication.instance", "QApplication()"]


def test_set_app_user_model_id_calls_shell32_on_windows(monkeypatch):
    received: list[str] = []
    shell32 = types.SimpleNamespace(
        SetCurrentProcessExplicitAppUserModelID=lambda value: received.append(value) or 0
    )
    fake_ctypes = types.SimpleNamespace(windll=types.SimpleNamespace(shell32=shell32))
    monkeypatch.setattr(app_module, "ctypes", fake_ctypes)
    monkeypatch.setattr(app_module.sys, "platform", "win32")

    app_module.set_app_user_model_id()

    assert received == [app_module.APP_USER_MODEL_ID]
    assert app_module.APP_USER_MODEL_ID == "qtRequestory.App"


def test_set_app_user_model_id_tolerates_missing_windll(monkeypatch):
    monkeypatch.setattr(app_module, "ctypes", types.SimpleNamespace())  # no windll
    monkeypatch.setattr(app_module.sys, "platform", "win32")
    app_module.set_app_user_model_id()  # must not raise


def test_set_app_user_model_id_tolerates_an_os_error(monkeypatch):
    def refuse(_value):
        raise OSError("denied")

    shell32 = types.SimpleNamespace(SetCurrentProcessExplicitAppUserModelID=refuse)
    monkeypatch.setattr(app_module, "ctypes",
                        types.SimpleNamespace(windll=types.SimpleNamespace(shell32=shell32)))
    monkeypatch.setattr(app_module.sys, "platform", "win32")
    app_module.set_app_user_model_id()


def test_set_app_user_model_id_does_nothing_off_windows(monkeypatch):
    touched: list[str] = []

    class Explodes:
        def __getattr__(self, name):
            touched.append(name)
            raise AssertionError("ctypes touched off Windows")

    monkeypatch.setattr(app_module, "ctypes", Explodes())
    monkeypatch.setattr(app_module.sys, "platform", "linux")
    app_module.set_app_user_model_id()
    assert touched == []


# ----------------------------------------------------------- startup tasks ---

@pytest.fixture
def looping_exec(monkeypatch):
    """An event loop that turns a few times, so a ``singleShot(0)`` fires."""
    windows: list[MainWindow] = []

    def fake_exec(self) -> int:
        for _ in range(5):
            QApplication.processEvents()
        windows.extend(
            w for w in QApplication.topLevelWidgets() if isinstance(w, MainWindow) and w.isVisible()
        )
        return 7

    monkeypatch.setattr(QApplication, "exec", fake_exec)
    yield windows
    for window in windows:
        window.close()


@pytest.fixture
def startup_calls(monkeypatch) -> list[bool]:
    """Replaces ``MainWindow.startup_tasks``: records whether the window was
    already visible when it ran (DESIGN-ui: never before the window shows)."""
    calls: list[bool] = []
    monkeypatch.setattr(MainWindow, "startup_tasks", lambda self: calls.append(self.isVisible()))
    return calls


def test_run_gui_starts_the_startup_tasks_after_the_window_is_shown(
    qtbot, fake_core, monkeypatch, key, looping_exec, startup_calls
):
    monkeypatch.setattr(app_module, "instance_key", lambda: key)

    assert run_gui(fake_core) == 7
    assert startup_calls == [True]


def test_run_gui_can_be_told_not_to_start_them(
    qtbot, fake_core, monkeypatch, key, looping_exec, startup_calls
):
    monkeypatch.setattr(app_module, "instance_key", lambda: key)

    assert run_gui(fake_core, run_startup_tasks=False) == 7
    assert startup_calls == []


def test_a_sync_asked_for_by_the_wizard_replaces_the_startup_tasks(
    qtbot, fake_core, monkeypatch, key, looping_exec, startup_calls
):
    """The wizard's first sync indexes too: a second run would only be refused."""
    monkeypatch.setattr(app_module, "instance_key", lambda: key)
    fake_core.config.first_run = True
    monkeypatch.setattr(app_module, "wizard_available", lambda: True)
    monkeypatch.setattr(
        app_module, "show_first_run_wizard", lambda *a, **kw: _Result(start_sync=True)
    )

    assert run_gui(fake_core) == 7
    assert startup_calls == []
