"""Fixtures for the UI tests: an offscreen Qt and an in-memory core.

``QT_QPA_PLATFORM=offscreen`` MUST be set before Qt is imported — the platform
plugin is chosen when ``QGuiApplication`` starts and cannot be changed
afterwards. This module is imported before any test module in ``tests/ui``, and
sets it at import time, so widgets render into a bitmap instead of popping
windows up on the developer's (or CI's) desktop.

The ``qapp`` and ``qtbot`` fixtures come from **pytest-qt** (already a dev
dependency): ``qapp`` is the session-wide ``QApplication``, ``qtbot`` drives
widgets and waits for signals. Nothing here redefines them.

Every UI test takes its core from ``fake_core``: a ``CoreServices`` bundle of
the in-memory implementations in ``tests/fakes/fake_core.py``. The real core is
never touched by a UI test — no network, no SQLite, no schtasks.
"""
from __future__ import annotations

import os
from pathlib import Path

# Before ANY Qt import (pytest-qt imports Qt when it first uses a fixture).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Windows: a missing native style must not make the platform plugin fail.
os.environ.setdefault("QT_ACCESSIBILITY", "0")

import pytest  # noqa: E402  (import order is the point of this module)

from qtrequestory.ui.contracts import CoreServices  # noqa: E402
from tests.fakes.fake_core import build_fake_core  # noqa: E402


@pytest.fixture
def fake_core(tmp_path: Path) -> CoreServices:
    """A complete in-memory core: 12 synthetic hits, scripted sync, fake task."""
    return build_fake_core(tmp_path / "core")


@pytest.fixture
def app_paths(fake_core: CoreServices):
    """The ``AppPaths`` the fake core writes into (already created)."""
    return fake_core.paths


@pytest.fixture(autouse=True)
def isolated_instance_key(monkeypatch, request):
    """A local-server name unique to this process AND this test.

    ``QLocalServer`` names are machine-global: without this, two pytest runs on
    the same machine fight over the same pipe and ``test_app.py`` flakes —
    worse, a run could talk to the developer's real qtRequestory window.
    """
    from qtrequestory.ui.app import INSTANCE_KEY_ENV_VAR

    monkeypatch.setenv(INSTANCE_KEY_ENV_VAR, f"qtrequestory-test-{os.getpid()}-{id(request.node)}")


@pytest.fixture(autouse=True)
def isolated_qsettings(tmp_path: Path):
    """Keep ``QSettings`` out of the developer's registry.

    Window geometry, the last used environment and the last save folder are all
    stored in ``QSettings("qtRequestory", "qtRequestory")``, which on Windows is
    the real registry. Switching the default format to INI and pointing it at a
    temp directory gives every test its own empty store, so tests neither see
    each other's state nor leave anything behind.

    Both settings are global and process-wide, so the previous values are put
    back afterwards: a fixture that exists to stop state leaking must not leak.
    ``QSettings`` has no getter for the configured path, so the original root is
    read back from the file name a probe would use (``<root>/<org>/<app>.ini``).
    """
    from PySide6.QtCore import QSettings

    ini = QSettings.Format.IniFormat
    scopes = (QSettings.Scope.UserScope, QSettings.Scope.SystemScope)
    previous_format = QSettings.defaultFormat()
    previous_roots = {scope: _ini_root(ini, scope) for scope in scopes}

    store = tmp_path / "settings"
    store.mkdir(exist_ok=True)
    QSettings.setDefaultFormat(ini)
    for scope in scopes:
        QSettings.setPath(ini, scope, str(store))
    try:
        yield store
    finally:
        QSettings.setDefaultFormat(previous_format)
        for scope, root in previous_roots.items():
            QSettings.setPath(ini, scope, root)


def _ini_root(fmt, scope) -> str:
    """The directory ``QSettings`` currently writes INI files into."""
    from PySide6.QtCore import QSettings

    probe = QSettings(fmt, scope, "qtrequestory-probe", "probe")
    return str(Path(probe.fileName()).parent.parent)


@pytest.fixture
def runner(qapp):
    """The shared ``JobRunner`` a page factory receives, stopped after the test.

    Without the teardown a worker can outlive the test and touch objects pytest
    has already torn down, which on Windows shows up as a hard crash.
    """
    from qtrequestory.ui.workers import JobRunner

    job_runner = JobRunner()
    yield job_runner
    job_runner.shutdown(3000)
