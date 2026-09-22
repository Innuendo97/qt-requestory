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
