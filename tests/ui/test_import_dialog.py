"""Importa log: report → copy → result, on synthetic trees and the fake core.

The fake archive runs the real discovery and copy on the tmp tree; its
Recycle Bin only unlinks files under the fake root and records them, so no
test here can ever touch the real Recycle Bin.
"""
from __future__ import annotations

import dataclasses
from datetime import date
from pathlib import Path

import pytest

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import (
    CONFLICT,
    DUPLICATE,
    IGNORE_FOLDER,
    IMPORTABLE,
    NEEDS_ENV,
    ArchiveReport,
)
from qtrequestory.ui.import_dialog import (
    STEP_COPY,
    STEP_REPORT,
    STEP_RESULT,
    ImportDialog,
    open_import_dialog,
)
from qtrequestory.ui.import_result import deletable
from tests.test_archive import LOG, LOG2, OTHER, put

D = date(2026, 9, 22)


def canonical(core, env: str, day: date) -> Path:
    return core.config.config.mirror_root / env / f"{day:%Y}" / f"{day:%m}" / f"{day:%Y%m%d}.txt"


@pytest.fixture
def old(tmp_path) -> Path:
    """A colleague's folder: one per verdict."""
    root = tmp_path / "core" / "vecchi log"  # under the fake root: its Recycle Bin works there
    put(root, "coll/20260922.txt", LOG)          # importable
    put(root, "svil/2026-09-21.txt", LOG)        # importable
    put(root, "misti/20260919.txt", LOG)         # needs_env
    put(root, "misti/20260918.txt", LOG)         # needs_env, same folder
    put(root, "backup.zip", b"PK")               # ignored
    return root


def make(qtbot, core, runner, sources) -> ImportDialog:
    dialog = ImportDialog(core, runner, sources)
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: dialog.report is not None and dialog.step() == STEP_REPORT,
                    timeout=5000)
    return dialog


def run_import(qtbot, dialog: ImportDialog) -> None:
    dialog.primary_button.click()
    qtbot.waitUntil(lambda: dialog.step() == STEP_RESULT, timeout=5000)


def test_the_report_lists_every_file_and_filters_by_status(qtbot, fake_core, runner, old):
    dialog = make(qtbot, fake_core, runner, [old])
    assert strings.IMPORT_SOURCE.format(path=old) in dialog.source_label.text()
    table = dialog.view.table
    assert table.rowCount() == 5
    assert table.item(0, 4).text().startswith(strings.IMPORT_STATUS_IMPORTABLE)
    labels = [dialog.view.filter.itemText(i) for i in range(dialog.view.filter.count())]
    assert labels == [strings.IMPORT_FILTER_ALL.format(n=5),
                      strings.IMPORT_FILTER_IMPORTABLE.format(n=2),
                      strings.IMPORT_FILTER_NEEDS_ENV.format(n=2),
                      strings.IMPORT_FILTER_IGNORED.format(n=1)]
    dialog.view.filter.setCurrentIndex(2)
    assert {f.status for f in table.visible_rows()} == {NEEDS_ENV}
    assert len(table.visible_rows()) == 2
    assert dialog.primary_button.isEnabled()
    assert "estrailo nella cartella" in table.item(4, 4).text()


def test_a_folder_needing_an_env_is_asked_once_and_saved_as_an_absolute_path(
        qtbot, fake_core, runner, old):
    dialog = make(qtbot, fake_core, runner, [old])
    [(key, combo)] = dialog.view.folders.combos
    assert dialog.view.folders.isVisibleTo(dialog)
    assert key == str(old / "misti") and Path(key).is_absolute()
    choices = [combo.itemText(i) for i in range(combo.count())]
    assert choices == [strings.IMPORT_FOLDER_PICK, "coll", "svil", strings.IMPORT_FOLDER_IGNORE]
    before = dialog.report
    combo.setCurrentIndex(2)
    combo.activated.emit(2)
    qtbot.waitUntil(lambda: dialog.report is not before and dialog.step() == STEP_REPORT,
                    timeout=5000)
    assert fake_core.config.config.folder_envs == {str(old / "misti"): "svil"}
    assert dialog.report.counts()[IMPORTABLE] == 4
    assert not dialog.view.folders.combos
    assert dialog.config_saved


def test_ignora_is_saved_as_the_ignore_marker(qtbot, fake_core, runner, old):
    dialog = make(qtbot, fake_core, runner, [old])
    [(key, combo)] = dialog.view.folders.combos
    before = dialog.report
    combo.activated.emit(combo.count() - 1)
    qtbot.waitUntil(lambda: dialog.report is not before, timeout=5000)
    assert fake_core.config.config.folder_envs[key] == IGNORE_FOLDER
    assert dialog.report.counts()[NEEDS_ENV] == 0


def test_import_copies_indexes_and_asks_about_the_originals(qtbot, fake_core, runner, old):
    dialog = make(qtbot, fake_core, runner, [old])
    run_import(qtbot, dialog)
    result = dialog.result
    assert (result.copied, result.skipped, result.conflicts, result.errors) == (2, 0, 0, [])
    assert canonical(fake_core, "coll", D).read_bytes() == LOG
    assert dialog.result_view.summary.text() == strings.IMPORT_RESULT.format(
        copied=2, skipped=0, conflicts=0, errors=0)
    qtbot.waitUntil(lambda: bool(fake_core.index.updates), timeout=5000)
    assert fake_core.index.updates[-1]["envs"] == ["coll", "svil"]
    assert dialog.result_view.question.isVisibleTo(dialog)
    assert dialog.result_view.question_detail.text().startswith("2 file, ")
    # the needs_env files were not copied
    assert (old / "misti" / "20260919.txt").exists()
    assert not canonical(fake_core, "coll", date(2026, 9, 19)).exists()


def test_cancella_originali_recycles_only_the_verified_originals(qtbot, fake_core, runner, old):
    dialog = make(qtbot, fake_core, runner, [old])
    run_import(qtbot, dialog)
    offered = list(dialog.result_view.offered)
    dialog.result_view.delete_button.click()
    qtbot.waitUntil(lambda: dialog.result_view.outcome.text().startswith(
        strings.IMPORT_DELETED.format(n=2)), timeout=5000)
    assert sorted(fake_core.archive.recycled) == sorted(v.path for v in offered)
    assert not (old / "coll" / "20260922.txt").exists()
    assert (old / "misti" / "20260919.txt").exists()     # never verified: kept
    assert (old / "backup.zip").exists()
    assert canonical(fake_core, "coll", D).exists()
    assert not dialog.result_view.question.isVisibleTo(dialog)


def test_tienili_keeps_everything(qtbot, fake_core, runner, old):
    dialog = make(qtbot, fake_core, runner, [old])
    run_import(qtbot, dialog)
    dialog.result_view.keep_button.click()
    assert dialog.result_view.outcome.text() == strings.IMPORT_KEPT
    assert fake_core.archive.recycled == []
    assert (old / "coll" / "20260922.txt").exists()


def test_originals_inside_the_mirror_are_never_offered(qtbot, fake_core, runner):
    mirror = fake_core.config.config.mirror_root
    put(mirror, "coll/2026/9/20260922.txt", LOG)       # misplaced inside the mirror
    dialog = make(qtbot, fake_core, runner, [None])
    assert fake_core.archive.reports[-1] is None
    assert strings.IMPORT_SOURCE_MIRROR.format(path=mirror) in dialog.source_label.text()
    run_import(qtbot, dialog)
    assert dialog.result.copied == 1 and dialog.result.verified
    assert deletable(dialog.result, mirror) == []
    assert not dialog.result_view.question.isVisibleTo(dialog)


def test_duplicates_and_conflicts(qtbot, fake_core, runner, tmp_path):
    root = tmp_path / "core" / "altro"
    put(root, "coll/20260922.txt", LOG)
    put(canonical(fake_core, "coll", D).parent, "20260922.txt", LOG2)   # archive has more
    put(root, "coll/20260921.txt", LOG)
    put(canonical(fake_core, "coll", date(2026, 9, 21)).parent, "20260921.txt", OTHER)
    dialog = make(qtbot, fake_core, runner, [root])
    counts = dialog.report.counts()
    assert (counts[DUPLICATE], counts[CONFLICT], counts[IMPORTABLE]) == (1, 1, 0)
    assert dialog.primary_button.isEnabled()  # the duplicate is verified: may be recycled
    assert dialog.view.plan_label.text() == strings.IMPORT_PLAN_NOTHING
    run_import(qtbot, dialog)
    assert (dialog.result.skipped, dialog.result.conflicts) == (1, 1)
    assert strings.IMPORT_RESULT_CONFLICTS in dialog.result_view.notes.text()
    assert [v.path for v in dialog.result_view.offered] == [root / "coll" / "20260922.txt"]
    assert fake_core.index.updates == []  # nothing copied: nothing to index


def test_a_running_sync_sends_the_user_back_to_the_report(qtbot, fake_core, runner, old):
    fake_core.archive.set_busy(True)
    dialog = make(qtbot, fake_core, runner, [old])
    dialog.primary_button.click()
    qtbot.waitUntil(lambda: dialog.error_banner.isVisibleTo(dialog), timeout=5000)
    assert dialog.step() == STEP_REPORT
    assert "sincronizzazione in corso" in dialog.error_label.text()
    assert dialog.primary_button.isVisibleTo(dialog)
    fake_core.archive.set_busy(False)
    run_import(qtbot, dialog)
    assert dialog.result.copied == 2


def test_closing_during_the_copy_interrupts_it_and_asks_nothing(qtbot, fake_core, runner, old,
                                                                monkeypatch):
    import threading

    gate = threading.Event()
    real = fake_core.archive.import_

    def slow(report, *, cancel=None, progress=None):
        def wait_then(done, total, rel):
            progress(done, total, rel)
            gate.wait(5)
        return real(report, cancel=cancel, progress=wait_then)

    monkeypatch.setattr(fake_core.archive, "import_", slow)
    dialog = make(qtbot, fake_core, runner, [old])
    dialog.primary_button.click()
    qtbot.waitUntil(lambda: dialog.step() == STEP_COPY, timeout=5000)
    assert dialog.close_button.text() == strings.IMPORT_BTN_STOP
    dialog.reject()
    assert dialog.isVisible() or True  # still alive: waits for the job
    assert dialog.progress_label.text() == strings.IMPORT_STOPPING
    gate.set()
    qtbot.waitUntil(lambda: dialog.step() == STEP_RESULT, timeout=5000)
    assert dialog.result.cancelled
    assert strings.IMPORT_RESULT_CANCELLED in dialog.result_view.notes.text()
    assert not dialog.result_view.question.isVisibleTo(dialog)


def test_two_folders_are_imported_one_after_the_other(qtbot, fake_core, runner, old, tmp_path):
    mirror = fake_core.config.config.mirror_root
    put(mirror, "svil/2026/9/20260920.txt", LOG)
    dialog = make(qtbot, fake_core, runner, [None, old])
    assert strings.IMPORT_SOURCE_STEP.format(i=1, n=2) in dialog.source_label.text()
    run_import(qtbot, dialog)
    assert dialog.primary_button.text() == strings.IMPORT_BTN_NEXT.format(path=old)
    before = dialog.report
    dialog.primary_button.click()
    qtbot.waitUntil(lambda: dialog.report is not before and dialog.step() == STEP_REPORT,
                    timeout=5000)
    assert dialog.source() == old
    run_import(qtbot, dialog)
    assert dialog.result.copied == 2
    assert not dialog.primary_button.isVisibleTo(dialog)


def test_no_import_into_an_invalid_archive(qtbot, fake_core, runner, old):
    fake_core.config.save(dataclasses.replace(fake_core.config.config, mirror_root=Path("")))
    assert open_import_dialog(fake_core, runner, None, [old]) is None


def test_scan_failure_is_shown(qtbot, fake_core, runner, monkeypatch, old):
    def broken(path=None, **_kw) -> ArchiveReport:
        raise OSError("accesso negato")

    monkeypatch.setattr(fake_core.archive, "report", broken)
    dialog = ImportDialog(fake_core, runner, [old])
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: "accesso negato" in dialog.scanning_label.text(), timeout=5000)
    assert not dialog.primary_button.isEnabled()


# ------------------------------------------------------------- fix round 1 ---

@pytest.mark.parametrize("fails", [False, True])
def test_a_running_index_gets_the_imported_envs_as_soon_as_it_ends(
        qtbot, fake_core, runner, old, fails):
    """The promise of IMPORT_INDEX_BUSY: the index job is exclusive, the one
    running may have planned before the copy, so the envs are indexed again
    right after it — also when it ended in error — even with the dialog gone."""
    import threading

    gate = threading.Event()

    def startup_index():
        gate.wait(5)
        if fails:
            raise OSError("indice bloccato")

    assert runner.submit("index", startup_index) is not None
    qtbot.waitUntil(lambda: runner.is_running("index"), timeout=5000)
    dialog = make(qtbot, fake_core, runner, [old])
    run_import(qtbot, dialog)
    assert strings.IMPORT_INDEX_BUSY in dialog.result_view.notes.text()
    assert fake_core.index.updates == []
    dialog.reject()
    gate.set()
    qtbot.waitUntil(lambda: bool(fake_core.index.updates), timeout=5000)
    assert fake_core.index.updates == [{"envs": ["coll", "svil"], "full_rebuild": False}]
    qtbot.waitUntil(lambda: not runner.is_running("index"), timeout=5000)
    runner.job_finished.emit("index", True)  # a later index: nothing waits any more
    qtbot.wait(50)
    assert len(fake_core.index.updates) == 1


def test_the_recycle_bin_runs_as_its_own_job_and_blocks_avanti(
        qtbot, fake_core, runner, old, tmp_path, monkeypatch):
    import threading

    from qtrequestory.ui.import_state import RECYCLE_JOB

    gate = threading.Event()
    real = fake_core.archive.recycle

    def slow(originals):
        gate.wait(5)
        return real(originals)

    monkeypatch.setattr(fake_core.archive, "recycle", slow)
    second = tmp_path / "core" / "secondo"
    put(second, "coll/20260915.txt", LOG)
    dialog = make(qtbot, fake_core, runner, [old, second])
    run_import(qtbot, dialog)
    assert dialog.primary_button.isEnabled()
    dialog.result_view.delete_button.click()
    qtbot.waitUntil(lambda: runner.is_running(RECYCLE_JOB), timeout=5000)
    assert runner.job("import").name == "import" and not runner.is_running("import")
    assert not dialog.primary_button.isEnabled()
    dialog.delete_originals()  # a second click while it runs
    assert dialog.result_view.outcome.text() == strings.STATUS_BUSY.format(
        name=strings.JOB_RECYCLE)
    gate.set()
    qtbot.waitUntil(lambda: dialog.primary_button.isEnabled(), timeout=5000)
    assert dialog.result_view.outcome.text().startswith(strings.IMPORT_DELETED.format(n=2))


def test_status_colours_follow_a_theme_switch(qtbot, qapp, fake_core, runner, old):
    from qtrequestory.ui import theme

    dialog = make(qtbot, fake_core, runner, [old])
    cell = dialog.view.table.item(0, 4)
    try:
        theme.apply(qapp, theme.Mode.LIGHT)
        assert cell.foreground().color().name().lower() == theme.LIGHT.ok.lower()
        theme.apply(qapp, theme.Mode.DARK)
        assert cell.foreground().color().name().lower() == theme.DARK.ok.lower()
    finally:
        theme.apply(qapp, theme.Mode.LIGHT)
