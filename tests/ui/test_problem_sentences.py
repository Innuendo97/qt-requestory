"""The core's mirror-folder sentence inserted after a colon starts lowercase.

``config.mirror_root_errors`` answers full sentences ("La cartella dei log non
è impostata") because the banner shows one on a line of its own. After
"Importazione non possibile:" a capital reads wrong, so every
"<what failed>: {problem}" string lowercases the first letter; the banner,
where the sentence starts the line, keeps it.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

from qtrequestory.ui import strings
from qtrequestory.ui.import_state import ArchiveWatch
from qtrequestory.ui.pages.archive_summary import summary_text

SENTENCE = "La cartella dei log non è impostata"
LOWER = "la cartella dei log non è impostata"


def _no_mirror(fake_core) -> None:
    fake_core.config.save(dataclasses.replace(fake_core.config.config, mirror_root=Path("")))


def test_lower_first():
    assert strings.lower_first(SENTENCE) == LOWER
    assert strings.lower_first("") == ""
    assert strings.lower_first("[WinError 3] x") == "[WinError 3] x"


def test_archive_summary(fake_core, runner):
    watch = ArchiveWatch.__new__(ArchiveWatch)
    watch.problem, watch.snapshot = SENTENCE, None
    assert summary_text(watch) == strings.ARCHIVE_SUMMARY_UNAVAILABLE.format(problem=LOWER)


def test_import_refused_in_the_status_bar(qtbot, fake_core, runner):
    from qtrequestory.ui.main_window import MainWindow, PageSpec
    from PySide6.QtWidgets import QWidget

    class Plain(QWidget):
        def __init__(self, services, runner, window):
            super().__init__()

    win = MainWindow(fake_core, runner, pages=[PageSpec("search", "Ricerca", "search", Plain, "tab")])
    qtbot.addWidget(win)
    _no_mirror(fake_core)
    win.open_import([None])
    assert win.statusBar().currentMessage() == strings.IMPORT_REFUSED.format(problem=LOWER)


def test_sync_refused(qtbot, fake_core, runner):
    from qtrequestory.ui.pages.sync_page import SyncPage
    from tests.ui.test_sync_page import FakeWindow

    _no_mirror(fake_core)
    page = SyncPage(fake_core, runner, FakeWindow())
    qtbot.addWidget(page)
    page.start_sync()
    assert page.run_label.text() == strings.SYNC_REFUSED_MIRROR_ROOT.format(problem=LOWER)
    assert page.mirror_banner.label.text() == strings.MIRROR_ROOT_BANNER.format(problem=SENTENCE)


def test_import_refused_in_the_dialog(qtbot, fake_core, runner, tmp_path):
    from tests.ui.test_import_dialog import LOG, make, put

    old = tmp_path / "core" / "vecchi log"
    put(old, "coll/20260922.txt", LOG)
    dialog = make(qtbot, fake_core, runner, [old])
    _no_mirror(fake_core)   # the folder went away between the scan and the click
    dialog.start_import()
    assert dialog.error_label.text() == strings.IMPORT_REFUSED.format(problem=LOWER)


def test_index_refused_in_impostazioni(qtbot, fake_core, runner, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from qtrequestory.ui.pages.settings_page import SettingsPage
    from tests.ui.test_settings_page import StubWindow, _answer

    fake_core.config.config = dataclasses.replace(fake_core.config.config, mirror_root=Path(""))
    window = StubWindow()
    page = SettingsPage(fake_core, runner, window)
    qtbot.addWidget(page)
    _answer(monkeypatch, QMessageBox.StandardButton.Yes)
    page.rebuild_button.click()
    assert strings.SETTINGS_INDEX_REFUSED.format(problem=LOWER) in window.status
