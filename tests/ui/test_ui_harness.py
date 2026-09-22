"""The UI test harness itself: offscreen Qt plus the fake core.

Six UI tasks depend on this working before they write a single widget, so it
is checked here rather than assumed.
"""
from __future__ import annotations

import os

from qtrequestory.ui.contracts import CoreServices


def test_qt_runs_offscreen(qapp, qtbot):
    from PySide6.QtWidgets import QLabel

    assert os.environ["QT_QPA_PLATFORM"] == "offscreen"
    assert qapp.platformName() == "offscreen"
    label = QLabel("Ricerca")
    qtbot.addWidget(label)
    label.show()
    assert label.isVisible() and label.text() == "Ricerca"


def test_fake_core_fixture_is_a_complete_bundle(fake_core: CoreServices, app_paths):
    from qtrequestory.core.index.search import SearchQuery

    assert fake_core.paths is app_paths
    assert fake_core.config.load().environments
    assert len(fake_core.index.search(SearchQuery("coll", template_key="_", key_mode="contains"))) == 12
    assert fake_core.sync.env_status("coll").env == "coll"
    assert fake_core.scheduler.status().registered is False
    assert fake_core.extract.output_dir().name == "out"


# ------------------------------------------------------- QSettings isolation ---

def test_every_settings_store_the_ui_opens_is_the_isolated_one(
    qapp, isolated_qsettings, fake_core: CoreServices, runner
):
    """No test may write into the developer's real ``HKCU`` registry.

    ``QSettings(org, app)`` hardcodes ``NativeFormat`` and ignores
    ``setDefaultFormat``, so the ``isolated_qsettings`` fixture cannot catch it:
    the window geometry of every UI test used to land in the real registry.
    Every entry point must therefore go through ``actions.user_settings``,
    which honours the configured format.
    """
    from pathlib import Path

    from PySide6.QtCore import QSettings

    from qtrequestory.ui import actions
    from qtrequestory.ui.main_window import MainWindow
    from qtrequestory.ui.pages.search_page import SearchPage

    window = MainWindow(fake_core, runner)
    page = SearchPage(fake_core, runner)
    try:
        for store in (actions.user_settings(), window.settings(), page._settings()):
            assert store.format() == QSettings.Format.IniFormat
            # Qt reports the path with forward slashes: compare as paths, not text.
            assert isolated_qsettings in Path(store.fileName()).parents, store.fileName()
    finally:
        window.close()


def test_the_window_geometry_lands_in_the_temporary_ini(
    qapp, isolated_qsettings, fake_core: CoreServices, runner
):
    """The end the previous test only implies: something really is written, there."""
    from qtrequestory.ui.main_window import MainWindow

    window = MainWindow(fake_core, runner)
    window.resize(900, 640)
    window.close()  # closeEvent persists geometry and state

    written = chr(10).join(
        p.read_text(encoding="utf-8", errors="replace") for p in isolated_qsettings.rglob("*.ini")
    )
    assert "geometry" in written
