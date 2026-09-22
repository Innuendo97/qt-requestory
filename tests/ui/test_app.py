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
from qtrequestory.ui.app import (
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
