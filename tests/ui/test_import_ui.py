"""The import entry points: the shared archive watch, the "fuori dalla
struttura" banner, Impostazioni › Archivio, the wizard's offer and the shell.

Synthetic trees only; the fake archive runs the real discovery.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from PySide6.QtWidgets import QFileDialog, QWidget

from qtrequestory.ui import strings
from qtrequestory.ui.import_dialog import ImportDialog
from qtrequestory.ui.import_state import (
    ARCHIVE_REPORT_JOB,
    IMPORT_JOB,
    IMPORT_SCAN_JOB,
    RECYCLE_JOB,
    WIZARD_ARCHIVE_JOB,
    ArchiveWatch,
)
from qtrequestory.ui.main_window import DATA_JOBS, MainWindow, PageSpec
from qtrequestory.ui.pages.archive_summary import ArchiveSummary
from qtrequestory.ui.pages.import_banner import ImportBanner
from qtrequestory.ui.pages.settings_page import SettingsPage
from qtrequestory.ui.quit_dialog import QUIT_INFO
from qtrequestory.ui.workers import JOB_NAMES, JobRunner
from tests.test_archive import LOG, put


class StubWindow:
    def __init__(self) -> None:
        self.opened: list[list] = []
        self.status: list[str] = []

    def open_import(self, sources=None, on_closed=None):
        self.opened.append(list(sources) if sources else [None])

    def set_status(self, text: str, ms: int = 4000) -> None:
        self.status.append(text)


def mirror(core) -> Path:
    return core.config.config.mirror_root


def strays(core, n: int = 2) -> None:
    """``n`` logs inside the mirror but outside its structure."""
    for i in range(n):
        put(mirror(core), f"coll/2026/9/2026091{i}.txt", LOG)


def settled(qtbot, watch: ArchiveWatch) -> None:
    qtbot.waitUntil(lambda: bool(not watch.loading and (watch.snapshot or watch.problem)),
                    timeout=5000)


# ----------------------------------------------------------------- jobs ---

def test_the_new_job_names_are_declared_labelled_and_import_is_exclusive():
    names = {ARCHIVE_REPORT_JOB, IMPORT_SCAN_JOB, IMPORT_JOB, RECYCLE_JOB, WIZARD_ARCHIVE_JOB}
    assert names <= set(JOB_NAMES)
    assert {IMPORT_JOB, RECYCLE_JOB} <= JobRunner.EXCLUSIVE
    assert {IMPORT_JOB, RECYCLE_JOB} <= set(DATA_JOBS) and {IMPORT_JOB, RECYCLE_JOB} <= set(QUIT_INFO)
    assert QUIT_INFO[RECYCLE_JOB] != QUIT_INFO[IMPORT_JOB]


# --------------------------------------------------------------- watch ---

def test_one_watch_per_runner_and_it_rescans_after_an_import(qtbot, fake_core, runner):
    strays(fake_core, 1)
    watch = ArchiveWatch.shared(fake_core, runner)
    assert ArchiveWatch.shared(fake_core, runner) is watch
    settled(qtbot, watch)
    assert watch.snapshot.report.counts()["importable"] == 1
    strays(fake_core, 3)
    with qtbot.waitSignal(watch.changed, timeout=5000):
        runner.job_finished.emit(IMPORT_JOB, True)
    settled(qtbot, watch)
    assert watch.snapshot.report.counts()["importable"] == 3


def test_an_invalid_archive_is_not_scanned(qtbot, fake_core, runner):
    fake_core.config.save(dataclasses.replace(fake_core.config.config, mirror_root=Path("")))
    watch = ArchiveWatch(fake_core, runner)
    watch.refresh()
    assert watch.problem and watch.snapshot is None
    assert runner.job(ARCHIVE_REPORT_JOB) is None


# -------------------------------------------------------------- banner ---

def test_the_banner_counts_the_strays_and_opens_the_dialog_on_the_mirror(
        qtbot, fake_core, runner):
    strays(fake_core, 2)
    put(mirror(fake_core), "vari/20260915.txt", LOG)   # coll/svil unknown: needs_env
    window = StubWindow()
    banner = ImportBanner(fake_core, runner, window)
    qtbot.addWidget(banner)
    settled(qtbot, banner.watch)
    assert not banner.isHidden()
    assert banner.label.text() == strings.IMPORT_BANNER.format(n=3)
    banner.button.click()
    assert window.opened == [[None]]


def test_the_banner_stays_hidden_without_strays(qtbot, fake_core, runner):
    put(mirror(fake_core), "coll/2026/09/20260915.txt", LOG)   # canonical: not a stray
    banner = ImportBanner(fake_core, runner, StubWindow())
    qtbot.addWidget(banner)
    settled(qtbot, banner.watch)
    assert banner.isHidden()


def test_both_pages_show_the_banner(qtbot, fake_core, runner):
    from qtrequestory.ui.pages.search_page import SearchPage
    from qtrequestory.ui.pages.sync_page import SyncPage

    strays(fake_core, 1)
    search = SearchPage(fake_core, runner, StubWindow())
    sync = SyncPage(fake_core, runner, StubWindow())
    for page in (search, sync):
        qtbot.addWidget(page)
    settled(qtbot, search.import_banner.watch)
    assert search.import_banner.watch is sync.import_banner.watch
    assert not search.import_banner.isHidden() and not sync.import_banner.isHidden()
    assert search.import_banner.label.text() == strings.IMPORT_BANNER_ONE


# ---------------------------------------------------- Impostazioni › Archivio ---

def test_the_settings_summary_line(qtbot, fake_core, runner, monkeypatch):
    strays(fake_core, 2)
    put(mirror(fake_core), "vari/20260915.txt", LOG)       # needs_env
    put(mirror(fake_core), "vari/note.txt", b"appunti")    # ignored
    fake_core.index.local_file_counts = {}
    window = StubWindow()
    page = SettingsPage(fake_core, runner, window)
    qtbot.addWidget(page)
    summary: ArchiveSummary = page.archive_summary
    settled(qtbot, summary.watch)
    archived = fake_core.index.count_local_files()
    assert summary.label.text() == strings.ARCHIVE_SUMMARY.format(
        archived=archived, todo=2, assign=1, ignored=1)
    summary.details_button.click()
    chosen = mirror(fake_core).parent / "altrove"
    monkeypatch.setattr(QFileDialog, "getExistingDirectory",
                        staticmethod(lambda *a, **kw: str(chosen)))
    summary.import_button.click()
    assert window.opened == [[None], [chosen]]


def test_the_settings_summary_says_why_it_cannot_look(qtbot, fake_core, runner):
    fake_core.config.save(dataclasses.replace(fake_core.config.config, mirror_root=Path("")))
    summary = ArchiveSummary(fake_core, runner, StubWindow())
    qtbot.addWidget(summary)
    settled(qtbot, summary.watch)
    assert summary.label.text().startswith(strings.ARCHIVE_SUMMARY_UNAVAILABLE.split("{")[0])
    assert not summary.import_button.isEnabled() and not summary.details_button.isEnabled()


def test_a_settings_save_keeps_the_folder_envs_the_dialog_saved(qtbot, fake_core, runner):
    page = SettingsPage(fake_core, runner, StubWindow())
    qtbot.addWidget(page)
    cfg = fake_core.config.load()   # the dialog assigns a folder behind the page's back
    fake_core.config.save(dataclasses.replace(cfg, folder_envs={"C:/vecchi/misti": "svil"}))
    page.set_window_days(7)
    assert page.save()
    assert fake_core.config.config.folder_envs == {"C:/vecchi/misti": "svil"}
    assert fake_core.config.config.default_window_days == 7


def test_validating_the_form_does_not_read_the_config_file(qtbot, fake_core, runner, monkeypatch):
    """Only save() re-reads folder_envs; to_config/errors use what was loaded."""
    page = SettingsPage(fake_core, runner, StubWindow())
    qtbot.addWidget(page)
    loads: list[int] = []
    real = fake_core.config.load
    monkeypatch.setattr(fake_core.config, "load", lambda: (loads.append(1), real())[1])
    page._presenter.errors(page.form_values())
    page._presenter.to_config(page.form_values())
    assert loads == []


# ---------------------------------------------------------------- shell ---

class Plain(QWidget):
    def __init__(self, services, runner, window):
        super().__init__()


def _window(qtbot, fake_core, runner) -> MainWindow:
    win = MainWindow(fake_core, runner, pages=[PageSpec("search", "Ricerca", "search", Plain, "tab")])
    qtbot.addWidget(win)
    return win


def test_open_import_opens_the_dialog_and_runs_on_closed(qtbot, fake_core, runner):
    win = _window(qtbot, fake_core, runner)
    closed: list[int] = []
    dialog = win.open_import([None], on_closed=lambda: closed.append(1))
    assert isinstance(dialog, ImportDialog)
    qtbot.waitUntil(lambda: dialog.report is not None, timeout=5000)
    dialog.reject()
    assert closed == [1]


def test_open_import_is_refused_into_an_invalid_archive(qtbot, fake_core, runner):
    win = _window(qtbot, fake_core, runner)
    fake_core.config.save(dataclasses.replace(fake_core.config.config, mirror_root=Path("")))
    closed: list[int] = []
    assert win.open_import([None], on_closed=lambda: closed.append(1)) is None
    assert win.statusBar().currentMessage().startswith(strings.IMPORT_REFUSED.split("{")[0])
    assert closed == [1]
    assert runner.job(IMPORT_SCAN_JOB) is None


def test_an_import_refreshes_the_pages(qtbot, fake_core, runner):
    class Data(Plain):
        def __init__(self, *a):
            super().__init__(*a)
            self.calls = 0

        def on_data_changed(self):
            self.calls += 1

    win = MainWindow(fake_core, runner, pages=[PageSpec("search", "Ricerca", "search", Data, "tab")])
    qtbot.addWidget(win)
    runner.job_finished.emit(IMPORT_JOB, True)
    assert win.page("search").calls == 1


@pytest.mark.parametrize("start_sync", [True, False])
def test_the_rerun_wizard_imports_first_then_syncs(qtbot, fake_core, runner, monkeypatch,
                                                   start_sync):
    from qtrequestory.ui import app as app_module
    from qtrequestory.ui.wizard import WizardResult

    win = _window(qtbot, fake_core, runner)
    opened: list = []
    monkeypatch.setattr(win, "open_import",
                        lambda sources, on_closed=None: opened.append((sources, on_closed)))
    syncs: list[int] = []
    monkeypatch.setattr(win, "start_sync", lambda: syncs.append(1))
    result = WizardResult(config=fake_core.config.load(), start_sync=start_sync, autosync=False,
                          import_sources=(None, Path("C:/altrove")))
    monkeypatch.setattr(app_module, "wizard_available", lambda: True)
    monkeypatch.setattr(app_module, "show_first_run_wizard", lambda *a, **kw: result)
    win.rerun_wizard()
    [(sources, then)] = opened
    assert sources == (None, Path("C:/altrove"))
    assert syncs == []  # not before the import
    if start_sync:
        then()
        assert syncs == [1]
    else:
        assert then is None


# --------------------------------------------------------------- wizard ---

def test_the_wizard_offers_the_strays_of_the_chosen_folder(qtbot, fake_core, runner, tmp_path):
    from qtrequestory.ui.wizard import FirstRunWizard

    fake_core.config.first_run = True
    folder = tmp_path / "core" / "nuovo"
    put(folder, "coll/2026/09/20260921.txt", LOG)    # already in place: not counted
    put(folder, "vecchi/coll_20260922.txt", LOG)
    put(folder, "vecchi/coll_20260923.txt", LOG)
    wizard = FirstRunWizard(fake_core, runner)
    qtbot.addWidget(wizard)
    offer = wizard.folder_page.import_offer
    wizard.folder_page.set_path(folder)
    qtbot.waitUntil(lambda: offer.found == 2, timeout=5000)
    assert not offer.checkbox.isHidden()
    assert offer.checkbox.text() == strings.WIZARD_IMPORT_FOUND.format(n=2)
    assert offer.sources() == (None,)
    offer.checkbox.setChecked(False)
    assert offer.sources() == ()

    elsewhere = tmp_path / "core" / "altrove"
    put(elsewhere, "svil_20260920.txt", LOG)
    offer.set_extra(elsewhere)
    qtbot.waitUntil(lambda: offer.extra_found == 1, timeout=5000)
    assert offer.extra_label.text() == strings.WIZARD_IMPORT_EXTRA.format(path=elsewhere, n=1)
    assert offer.sources() == (elsewhere,)
    offer.remove_button.click()
    assert offer.sources() == ()


def test_the_wizard_result_carries_the_import_sources(qtbot, fake_core, runner, tmp_path):
    from tests.ui.test_wizard import advance_to_automation
    from qtrequestory.ui.wizard import FirstRunWizard

    fake_core.config.first_run = True
    folder = tmp_path / "core" / "logs"
    put(folder, "vecchi/coll_20260922.txt", LOG)
    wizard = FirstRunWizard(fake_core, runner)
    qtbot.addWidget(wizard)
    advance_to_automation(wizard, folder)
    qtbot.waitUntil(lambda: wizard.folder_page.import_offer.found == 1, timeout=5000)
    wizard.accept()
    assert wizard.wizard_result().import_sources == (None,)
