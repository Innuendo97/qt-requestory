"""The first-run wizard: three pages, one saved configuration.

The wizard is the only place that writes a configuration before one exists, so
what is tested here is mostly *what reaches the core*: the folder the user
picked, the environments they typed or imported, the editor, and whether the
scheduled task was registered. Everything goes through the fake services, so no
real folder outside ``tmp_path``, no schtasks and no network is involved.

Modal loops are never entered: ``exec()`` is monkeypatched where the entry point
is tested, and every page is driven through ``QWizard.next()``/``accept()``,
which is exactly what the buttons do.
"""
from __future__ import annotations

import pathlib
from pathlib import Path

import pytest
from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import Environment, SchedulerError
from qtrequestory.ui.wizard import FirstRunWizard, WizardResult, run_first_run_wizard

GOOD_ENVS = [
    Environment("coll", "https://example.invalid/coll/", True),
    Environment("svil", "https://example.invalid/svil/", True),
]


@pytest.fixture
def wizard(qtbot, fake_core, runner):
    widget = FirstRunWizard(fake_core, runner)
    qtbot.addWidget(widget)
    return widget


def advance_to_automation(wizard, folder: Path, envs=GOOD_ENVS) -> None:
    """Drive the wizard the way the [Avanti] button does, twice."""
    wizard.restart()
    wizard.folder_page.set_path(folder)
    wizard.next()
    wizard.environments_page.table.set_environments(envs)
    wizard.next()
    assert wizard.currentPage() is wizard.automation_page


# ------------------------------------------------------- 1. cartella dei log ---

def test_the_folder_page_proposes_the_default_mirror_root(wizard, fake_core):
    wizard.restart()
    assert wizard.folder_page.folder() == fake_core.config.load().mirror_root


def test_a_writable_folder_passes_validation(wizard, tmp_path):
    wizard.folder_page.set_path(tmp_path / "logs")
    assert wizard.folder_page.validatePage() is True
    assert wizard.folder_page.error_label.text() == ""
    assert (tmp_path / "logs").is_dir(), "the folder is created, not just checked"


def test_a_path_that_is_a_file_is_refused_with_an_inline_error(wizard, tmp_path):
    occupied = tmp_path / "not-a-folder.txt"
    occupied.write_text("x", encoding="utf-8")

    wizard.folder_page.set_path(occupied)

    assert wizard.folder_page.validatePage() is False
    assert str(occupied) in wizard.folder_page.error_label.text()


def test_a_folder_that_cannot_be_created_is_refused(wizard, tmp_path, monkeypatch):
    def refuse(self, *args, **kwargs):
        raise PermissionError("accesso negato")

    monkeypatch.setattr(pathlib.Path, "mkdir", refuse)
    wizard.folder_page.set_path(tmp_path / "vietata")

    assert wizard.folder_page.validatePage() is False
    assert wizard.folder_page.error_label.text() != ""


def test_an_empty_folder_field_keeps_avanti_disabled(wizard):
    wizard.folder_page.set_path("")
    assert wizard.folder_page.isComplete() is False

    wizard.folder_page.set_path("C:/qualsiasi")
    assert wizard.folder_page.isComplete() is True


def test_existing_log_files_are_announced(wizard, fake_core, tmp_path):
    root = tmp_path / "mirror"
    fake_core.index.set_local_file_count(root, 7)

    wizard.folder_page.set_path(root)

    assert "7" in wizard.folder_page.info_label.text()
    assert wizard.folder_page.info_label.isVisibleTo(wizard.folder_page)


def test_an_empty_folder_says_nothing(wizard, tmp_path):
    wizard.folder_page.set_path(tmp_path / "vuota")
    assert wizard.folder_page.info_label.text() == ""


def test_browse_fills_the_field(wizard, tmp_path, monkeypatch):
    chosen = tmp_path / "scelta"
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(chosen))
    )

    wizard.folder_page.browse()

    assert wizard.folder_page.folder() == chosen


def test_browse_cancelled_leaves_the_field_alone(wizard, tmp_path, monkeypatch):
    wizard.folder_page.set_path(tmp_path / "prima")
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: ""))

    wizard.folder_page.browse()

    assert wizard.folder_page.folder() == tmp_path / "prima"


# ------------------------------------------------------------- 2. ambienti ---

def test_environments_are_prefilled_from_the_sidecar(wizard, fake_core, tmp_path):
    fake_core.config.sidecar = tmp_path / "environments.json"
    page = wizard.environments_page

    page.initializePage()

    assert page.environments() == fake_core.config.sidecar_environments
    assert page.hint_label.text() != ""
    assert "environments.json" in page.hint_label.text()


def test_without_a_sidecar_the_hint_asks_for_the_file(wizard, fake_core):
    fake_core.config.sidecar = None
    page = wizard.environments_page

    page.initializePage()

    assert page.environments() == []
    assert page.hint_label.text() == strings.WIZARD_P2_HINT


def test_a_malformed_sidecar_is_not_fatal(wizard, fake_core, tmp_path):
    fake_core.config.sidecar = tmp_path / "environments.json"
    fake_core.config.set_import_error("environments.json: JSON non valido")
    page = wizard.environments_page

    page.initializePage()

    assert page.environments() == []
    assert page.hint_label.text() == strings.WIZARD_P2_HINT


def test_import_from_file_loads_the_environments(wizard, fake_core, tmp_path, monkeypatch):
    chosen = tmp_path / "environments.json"
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(chosen), ""))
    )
    page = wizard.environments_page

    page.import_environments()

    assert page.environments() == fake_core.config.sidecar_environments


def test_a_malformed_import_shows_the_error_and_keeps_the_rows(
    wizard, fake_core, tmp_path, monkeypatch
):
    page = wizard.environments_page
    page.table.set_environments(GOOD_ENVS)
    fake_core.config.set_import_error("environments.json: JSON non valido")
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *a, **k: (str(tmp_path / "environments.json"), "")),
    )
    shown: list[tuple] = []
    monkeypatch.setattr(
        QMessageBox, "warning", staticmethod(lambda *args, **kw: shown.append(args))
    )

    page.import_environments()

    assert page.environments() == GOOD_ENVS
    assert shown and "JSON non valido" in shown[0][2]


def test_add_and_remove_edit_the_table(wizard):
    page = wizard.environments_page
    page.add_environment()
    assert page.table.rowCount() == 1

    page.table.selectRow(0)
    page.remove_selected()
    assert page.table.rowCount() == 0


def test_going_back_and_forward_keeps_what_the_user_typed(wizard, fake_core, tmp_path):
    """Re-running the sidecar prefill would undo an edit — including a delete."""
    fake_core.config.sidecar = tmp_path / "environments.json"
    wizard.restart()
    wizard.folder_page.set_path(tmp_path / "logs")
    wizard.next()
    wizard.environments_page.table.set_environments([])

    wizard.back()
    wizard.next()

    assert wizard.environments_page.environments() == []


def test_the_buttons_are_wired_to_the_page(wizard, qtbot, fake_core, monkeypatch):
    """Qt calls a zero-argument slot from ``clicked(bool)``: check, don't assume."""
    fake_core.sync.set_unreachable("coll")
    page = wizard.environments_page

    page.add_button.click()
    assert page.table.rowCount() == 1

    page.table.selectRow(0)
    page.remove_button.click()
    assert page.table.rowCount() == 0

    page.table.set_environments(GOOD_ENVS)
    page.check_button.click()
    qtbot.waitUntil(lambda: strings.WIZARD_P2_UNREACHABLE in page.reachability_label.text(),
                    timeout=3000)


def test_a_bad_url_blocks_the_page(wizard):
    page = wizard.environments_page
    page.table.set_environments([Environment("coll", "ftp://example.invalid/coll", True)])

    assert page.validatePage() is False
    assert "coll" in page.error_label.text()


def test_valid_environments_pass(wizard):
    page = wizard.environments_page
    page.table.set_environments(GOOD_ENVS)

    assert page.validatePage() is True
    assert page.error_label.text() == ""


def test_zero_environments_is_allowed_but_warned_about(wizard):
    page = wizard.environments_page
    page.table.set_environments([])

    assert page.validatePage() is True
    assert page.error_label.text() == strings.WIZARD_P2_NO_ENVIRONMENTS


def test_only_disabled_environments_are_also_warned_about(wizard):
    page = wizard.environments_page
    page.table.set_environments([Environment("coll", "https://example.invalid/coll/", False)])

    assert page.validatePage() is True
    assert page.error_label.text() == strings.WIZARD_P2_NO_ENVIRONMENTS


def test_the_reachability_check_reports_every_environment(wizard, qtbot, fake_core):
    fake_core.sync.set_unreachable("svil")
    page = wizard.environments_page
    page.table.set_environments(GOOD_ENVS)

    job = page.check_reachability()

    with qtbot.waitSignal(job.signals.result, timeout=3000):
        pass
    text = page.reachability_label.text()
    assert f"coll: {strings.WIZARD_P2_REACHABLE}" in text
    assert f"svil: {strings.WIZARD_P2_UNREACHABLE}" in text


def test_the_reachability_check_never_blocks_avanti(wizard, fake_core):
    page = wizard.environments_page
    page.table.set_environments(GOOD_ENVS)

    page.check_reachability()

    assert page.validatePage() is True, "the check is informative, never a gate"


def test_a_cancelled_reachability_check_stops_between_environments(fake_core):
    """Each probe blocks for its timeout: a closed wizard must not hold the pool."""
    from qtrequestory.ui.contracts import CancelToken
    from qtrequestory.ui.wizard_pages import _probe_reachability

    token = CancelToken()
    asked: list[str] = []

    def check(name: str) -> bool:
        asked.append(name)
        token.cancel()
        return True

    outcome = _probe_reachability(check, ["coll", "svil", "prod"], cancel=token)

    assert asked == ["coll"]
    assert outcome == {"coll": True}


def test_checking_without_environments_says_so(wizard):
    page = wizard.environments_page
    page.table.set_environments([])

    assert page.check_reachability() is None
    assert page.reachability_label.text() == strings.WIZARD_P2_CHECK_EMPTY


# ---------------------------------------------------------- 3. automazione ---

def test_the_automation_defaults_are_both_on(wizard):
    page = wizard.automation_page
    page.initializePage()

    assert page.autosync_enabled() is True
    assert page.start_sync_requested() is True


def test_the_legacy_task_notice_appears_only_when_one_is_registered(wizard, fake_core):
    page = wizard.automation_page

    page.initializePage()
    assert page.has_legacy_task() is False
    assert page.legacy_label.text() == ""

    fake_core.scheduler.set_legacy(True)
    page.initializePage()
    assert page.has_legacy_task() is True
    assert "NginxLogSync" in page.legacy_label.text()


def test_the_editor_field_is_prefilled_from_the_detected_editor(wizard, fake_core, tmp_path):
    editor = tmp_path / "notepad++.exe"
    fake_core.config.editor = editor
    page = wizard.automation_page

    page.initializePage()

    assert page.editor_path() == editor


def test_no_detected_editor_leaves_the_field_empty_with_a_hint(wizard, fake_core):
    fake_core.config.editor = None
    page = wizard.automation_page

    page.initializePage()

    assert page.editor_path() is None
    assert page.editor_hint.text() == strings.WIZARD_P3_EDITOR_NOT_FOUND


def test_the_folder_browse_button_is_wired(wizard, tmp_path, monkeypatch):
    chosen = tmp_path / "scelta-dal-pulsante"
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(chosen))
    )

    wizard.folder_page.browse_button.click()

    assert wizard.folder_page.folder() == chosen


def test_browsing_for_the_editor_fills_the_field(wizard, tmp_path, monkeypatch):
    chosen = tmp_path / "notepad++.exe"
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(chosen), ""))
    )
    page = wizard.automation_page

    page.browse_editor()

    assert page.editor_path() == chosen


# ------------------------------------------------------------------- fine ---

def test_fine_saves_the_configuration_through_the_services(wizard, fake_core, tmp_path):
    editor = tmp_path / "notepad++.exe"
    fake_core.config.editor = editor
    advance_to_automation(wizard, tmp_path / "logs")

    wizard.accept()

    saved = fake_core.config.saved[-1]
    assert saved.mirror_root == tmp_path / "logs"
    assert saved.environments == GOOD_ENVS
    assert saved.editor_path == editor


def test_fine_returns_the_result_with_its_flags(wizard, fake_core, tmp_path):
    advance_to_automation(wizard, tmp_path / "logs")
    wizard.automation_page.start_sync_check.setChecked(False)

    wizard.accept()

    result = wizard.wizard_result()
    assert isinstance(result, WizardResult)
    assert result.config is fake_core.config.saved[-1]
    assert result.start_sync is False
    assert result.autosync is True


def test_fine_registers_the_scheduled_task_when_autosync_is_on(wizard, fake_core, tmp_path):
    advance_to_automation(wizard, tmp_path / "logs")

    wizard.accept()

    assert fake_core.scheduler.register_calls == 1


def test_fine_without_autosync_registers_nothing(wizard, fake_core, tmp_path):
    advance_to_automation(wizard, tmp_path / "logs")
    wizard.automation_page.autosync_check.setChecked(False)

    wizard.accept()

    assert fake_core.scheduler.register_calls == 0
    assert wizard.wizard_result().autosync is False


def test_the_legacy_task_is_removed_once_ours_is_registered(wizard, fake_core, tmp_path):
    fake_core.scheduler.set_legacy(True)
    advance_to_automation(wizard, tmp_path / "logs")

    wizard.accept()

    assert fake_core.scheduler.detect_legacy_task() is False


def test_the_legacy_task_survives_when_autosync_is_off(wizard, fake_core, tmp_path):
    fake_core.scheduler.set_legacy(True)
    advance_to_automation(wizard, tmp_path / "logs")
    wizard.automation_page.autosync_check.setChecked(False)

    wizard.accept()

    assert fake_core.scheduler.detect_legacy_task() is True, "nothing replaced it"


def test_a_scheduler_failure_is_reported_but_never_blocks_fine(
    wizard, fake_core, tmp_path, monkeypatch
):
    def boom() -> None:
        raise SchedulerError("schtasks ha restituito 1")

    monkeypatch.setattr(fake_core.scheduler, "register", boom)
    shown: list[tuple] = []
    monkeypatch.setattr(
        QMessageBox, "information", staticmethod(lambda *args, **kw: shown.append(args))
    )
    advance_to_automation(wizard, tmp_path / "logs")

    wizard.accept()

    assert shown and "schtasks" in shown[0][2]
    result = wizard.wizard_result()
    assert result is not None
    assert result.autosync is False, "the task is not active, whatever was ticked"
    assert fake_core.config.saved, "the configuration is saved before the task is touched"


def test_a_failure_removing_the_legacy_task_is_swallowed(
    wizard, fake_core, tmp_path, monkeypatch
):
    fake_core.scheduler.set_legacy(True)

    def boom() -> None:
        raise SchedulerError("accesso negato")

    monkeypatch.setattr(fake_core.scheduler, "remove_legacy_task", boom)
    advance_to_automation(wizard, tmp_path / "logs")

    wizard.accept()

    assert wizard.wizard_result().autosync is True


# --------------------------------------------------------------- entry point ---

def test_run_first_run_wizard_returns_none_when_cancelled(fake_core, runner, monkeypatch):
    monkeypatch.setattr(
        FirstRunWizard, "exec", lambda self: int(QDialog.DialogCode.Rejected)
    )

    assert run_first_run_wizard(fake_core, runner) is None
    assert fake_core.config.saved == []


def test_run_first_run_wizard_returns_the_result_when_accepted(
    fake_core, runner, tmp_path, monkeypatch
):
    def accept_it(self) -> int:
        advance_to_automation(self, tmp_path / "logs")
        self.accept()
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(FirstRunWizard, "exec", accept_it)

    result = run_first_run_wizard(fake_core, runner)

    assert isinstance(result, WizardResult)
    assert result.config.mirror_root == tmp_path / "logs"
    assert fake_core.config.saved[-1] is result.config


def test_the_wizard_has_exactly_the_three_pages_of_the_design(wizard):
    titles = [wizard.page(pid).title() for pid in wizard.pageIds()]
    assert titles == [
        strings.WIZARD_P1_TITLE,
        strings.WIZARD_P2_TITLE,
        strings.WIZARD_P3_TITLE,
    ]
