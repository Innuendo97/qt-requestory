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

import dataclasses
import threading
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
    """A genuine first run: no configuration saved yet (see ``rerun_wizard``)."""
    fake_core.config.first_run = True
    widget = FirstRunWizard(fake_core, runner)
    qtbot.addWidget(widget)
    return widget


@pytest.fixture
def shown_wizard(wizard):
    """The wizard on screen, so ``isVisible()`` means what it says.

    A widget only reports itself visible once its window is shown, and a
    warning the user cannot see is the bug this fixture exists to catch.
    """
    wizard.show()
    return wizard


def first_run(fake_core) -> None:
    """A genuine first run: ``default_config()`` ships with no environments, and
    the fake starts with two."""
    fake_core.config.config = dataclasses.replace(fake_core.config.config, environments=[])


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


def test_the_default_never_overwrites_what_the_user_chose(wizard, tmp_path):
    """[Indietro] onto page 1 must not put the proposal back."""
    wizard.restart()
    wizard.folder_page.set_path(tmp_path / "la-mia-cartella")

    wizard.folder_page.initializePage()

    assert wizard.folder_page.folder() == tmp_path / "la-mia-cartella"


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

    monkeypatch.setattr(Path, "mkdir", refuse)
    wizard.folder_page.set_path(tmp_path / "vietata")

    assert wizard.folder_page.validatePage() is False
    assert wizard.folder_page.error_label.text() != ""


def test_an_empty_folder_field_keeps_avanti_disabled(wizard):
    wizard.folder_page.set_path("")
    assert wizard.folder_page.isComplete() is False

    wizard.folder_page.set_path("C:/qualsiasi")
    assert wizard.folder_page.isComplete() is True


def wait_count(qtbot, page) -> None:
    """Until the file count running in the worker has answered."""
    qtbot.waitUntil(lambda: not page.counting(), timeout=3000)


def test_existing_log_files_are_announced(qtbot, wizard, fake_core, tmp_path):
    root = tmp_path / "mirror"
    fake_core.index.set_local_file_count(root, 7)

    wizard.folder_page.set_path(root)
    wait_count(qtbot, wizard.folder_page)

    assert "7" in wizard.folder_page.info_label.text()
    assert wizard.folder_page.info_label.isVisibleTo(wizard.folder_page)


def test_an_empty_folder_says_nothing(qtbot, wizard, tmp_path):
    wizard.folder_page.set_path(tmp_path / "vuota")
    wait_count(qtbot, wizard.folder_page)
    assert wizard.folder_page.info_label.text() == ""


def test_the_files_are_counted_off_the_gui_thread_with_a_placeholder(
        qtbot, wizard, fake_core, tmp_path, monkeypatch):
    """Walking a big folder on the GUI thread froze the wizard (BACKLOG)."""
    gate = threading.Event()
    threads: list[int] = []

    def slow_count(root=None) -> int:
        threads.append(threading.get_ident())
        gate.wait(5.0)
        return 3

    monkeypatch.setattr(fake_core.index, "count_local_files", slow_count)
    page = wizard.folder_page
    try:
        page.set_path(tmp_path / "grande")
        assert page.counting()
        assert page.info_label.text() == strings.WIZARD_P1_COUNTING
    finally:
        gate.set()
    wait_count(qtbot, page)
    assert threads and threads[0] != threading.get_ident()
    assert "3" in page.info_label.text()


def test_a_folder_that_cannot_be_counted_says_nothing(qtbot, wizard, fake_core, tmp_path,
                                                     monkeypatch):
    def unreadable(root=None) -> int:
        raise PermissionError("accesso negato")

    monkeypatch.setattr(fake_core.index, "count_local_files", unreadable)
    page = wizard.folder_page
    page.set_path(tmp_path / "vietata")
    wait_count(qtbot, page)
    assert page.info_label.text() == ""


def test_only_the_last_folder_counted_is_announced(qtbot, wizard, fake_core, tmp_path):
    fake_core.index.set_local_file_count(tmp_path / "a", 5)
    fake_core.index.set_local_file_count(tmp_path / "b", 9)
    page = wizard.folder_page

    page.set_path(tmp_path / "a")
    page.set_path(tmp_path / "b")
    wait_count(qtbot, page)
    qtbot.wait(50)

    assert "9" in page.info_label.text()


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

def test_environments_are_prefilled_from_the_sidecar_on_a_first_run(wizard, fake_core, tmp_path):
    first_run(fake_core)
    fake_core.config.sidecar = tmp_path / "environments.json"
    page = wizard.environments_page

    page.initializePage()

    assert page.environments() == fake_core.config.sidecar_environments
    assert "environments.json" in page.hint_label.text()


def test_a_rerun_shows_the_environments_already_configured(wizard, fake_core):
    """Impostazioni re-runs the wizard: an empty table would be saved over them."""
    fake_core.config.config = dataclasses.replace(
        fake_core.config.config, environments=GOOD_ENVS
    )
    page = wizard.environments_page

    page.initializePage()

    assert page.environments() == GOOD_ENVS
    assert page.hint_label.text() == strings.WIZARD_P2_CONFIGURED_LOADED


def test_what_is_configured_wins_over_the_sidecar(wizard, fake_core, tmp_path):
    """The sidecar is the *first-run* source, not a reset button."""
    fake_core.config.config = dataclasses.replace(
        fake_core.config.config, environments=GOOD_ENVS
    )
    fake_core.config.sidecar = tmp_path / "environments.json"
    fake_core.config.sidecar_environments = [
        Environment("altro", "https://example.invalid/altro/", True)
    ]
    page = wizard.environments_page

    page.initializePage()

    assert page.environments() == GOOD_ENVS


def test_a_rerun_never_saves_an_empty_list_over_the_configured_environments(
    wizard, fake_core, tmp_path
):
    """The whole point of the prefill, checked end to end at [Fine]."""
    fake_core.config.config = dataclasses.replace(
        fake_core.config.config, environments=GOOD_ENVS
    )
    fake_core.config.sidecar = None

    wizard.restart()
    wizard.folder_page.set_path(tmp_path / "logs")
    wizard.next()
    wizard.next()
    wizard.accept()

    assert fake_core.config.saved[-1].environments == GOOD_ENVS


def test_without_a_sidecar_or_a_configuration_the_hint_asks_for_the_file(wizard, fake_core):
    first_run(fake_core)
    fake_core.config.sidecar = None
    page = wizard.environments_page

    page.initializePage()

    assert page.environments() == []
    assert page.hint_label.text() == strings.WIZARD_P2_HINT


def test_a_malformed_sidecar_is_not_fatal(wizard, fake_core, tmp_path):
    first_run(fake_core)
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


def open_environments_page(wizard, fake_core, tmp_path):
    """Put the wizard on page 2, on screen, the way the user gets there."""
    first_run(fake_core)
    fake_core.config.sidecar = None
    wizard.restart()
    wizard.folder_page.set_path(tmp_path / "logs")
    wizard.next()
    assert wizard.currentPage() is wizard.environments_page
    return wizard.environments_page


def test_an_empty_table_warns_where_the_user_can_see_it(shown_wizard, fake_core, tmp_path):
    """A warning written at [Avanti] time lands on a page that is leaving: the
    user never sees it. It has to be visible *while page 2 is open*."""
    page = open_environments_page(shown_wizard, fake_core, tmp_path)

    assert page.warning_label.isVisible() is True
    assert page.warning_label.text() == strings.WIZARD_P2_NO_ENVIRONMENTS


def test_the_warning_appears_and_clears_as_the_table_is_edited(
    shown_wizard, fake_core, tmp_path
):
    page = open_environments_page(shown_wizard, fake_core, tmp_path)

    page.table.add_row(GOOD_ENVS[0])
    assert page.warning_label.isVisible() is False

    page.table.selectAll()
    page.remove_selected()
    assert page.warning_label.isVisible() is True


def test_only_disabled_environments_warn_too(shown_wizard, fake_core, tmp_path):
    page = open_environments_page(shown_wizard, fake_core, tmp_path)

    page.table.add_row(Environment("coll", "https://example.invalid/coll/", False))

    assert page.warning_label.isVisible() is True
    assert page.warning_label.text() == strings.WIZARD_P2_NO_ENVIRONMENTS


def test_zero_environments_still_does_not_block_avanti(shown_wizard, fake_core, tmp_path):
    page = open_environments_page(shown_wizard, fake_core, tmp_path)

    assert page.validatePage() is True
    assert page.error_label.text() == "", "a warning is not an error"


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


def test_the_reachability_check_probes_the_url_in_the_table_not_the_saved_config(
    wizard, qtbot, fake_core, monkeypatch
):
    """Nothing is saved during the wizard, so a name is not enough to probe.

    This is the bug the check shipped with: ``check_reachable`` resolved the
    name against ``config.json``, which the wizard writes only on [Fine], so
    every row came back "non raggiungibile" on a perfectly reachable network.
    """
    probed: list[Environment] = []
    monkeypatch.setattr(fake_core.sync, "check_reachable",
                        lambda env, timeout=5.0: probed.append(env) or True)
    page = wizard.environments_page
    typed = [Environment("nuovo", "https://example.invalid/appena-scritto/", True)]
    page.table.set_environments(typed)

    job = page.check_reachability()

    with qtbot.waitSignal(job.signals.result, timeout=3000):
        pass
    assert probed == typed


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
    asked: list[Environment] = []

    def check(env: Environment) -> bool:
        asked.append(env)
        token.cancel()
        return True

    envs = [Environment(name, f"https://example.invalid/{name}/")
            for name in ("coll", "svil", "prod")]
    outcome = _probe_reachability(check, envs, cancel=token)

    assert asked == envs[:1], "the whole row is probed, URL included"
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


def test_the_legacy_task_checkbox_appears_only_when_one_is_registered(
        shown_wizard, fake_core, tmp_path):
    advance_to_automation(shown_wizard, tmp_path / "logs")
    page = shown_wizard.automation_page
    assert page.has_legacy_task() is False
    assert not page.legacy_check.isVisible()
    assert not page.legacy_note.isVisible()

    fake_core.scheduler.set_legacy(True)
    page.initializePage()
    assert page.has_legacy_task() is True
    assert page.legacy_check.isVisible()
    assert page.legacy_note.isVisible()


def test_the_legacy_task_is_kept_by_default(shown_wizard, fake_core, tmp_path):
    """Removing a working sync the user never asked us to touch was the bug:
    the two tasks coexist safely (README), so removal is opt-in."""
    fake_core.scheduler.set_legacy(True)
    advance_to_automation(shown_wizard, tmp_path / "logs")
    page = shown_wizard.automation_page

    assert page.legacy_check.text() == strings.WIZARD_P3_LEGACY_REMOVE
    assert page.legacy_check.text() == "Rimuovi il vecchio task NginxLogSync"
    assert page.legacy_check.isChecked() is False
    assert page.legacy_note.text() == (
        "Puoi tenerli entrambi finché non hai verificato che il nuovo funziona: "
        "non si danneggiano a vicenda"
    )
    assert page.remove_legacy_requested() is False


def test_the_automation_note_describes_the_schedule_that_would_be_registered(
    qtbot, fake_core, runner
):
    """``wizard.py`` registers whatever ``config.json`` holds, so offering a
    09:00 task to someone who moved the start to 07:30 — which is what
    "Riesegui configurazione iniziale" used to do — is a promise it breaks."""
    from qtrequestory.ui.contracts import ScheduleSettings

    fake_core.config.config = dataclasses.replace(
        fake_core.config.load(),
        schedule=ScheduleSettings(start_time="07:30", repeat_every_h=2, repeat_for_h=6,
                                  run_at_logon=False),
    )
    widget = FirstRunWizard(fake_core, runner)
    qtbot.addWidget(widget)
    page = widget.automation_page
    page.initializePage()

    note = page.autosync_note.text()
    assert "Ogni giorno alle 07:30, riprova ogni 2 ore fino alle 13:30." in note
    assert "09:00" not in note and "18:00" not in note
    assert "09:00" not in page.autosync_check.text()


def test_the_automation_note_follows_a_schedule_saved_after_the_page_was_built(
    qtbot, fake_core, runner
):
    from qtrequestory.ui.contracts import ScheduleSettings

    widget = FirstRunWizard(fake_core, runner)
    qtbot.addWidget(widget)
    page = widget.automation_page
    fake_core.config.config = dataclasses.replace(
        fake_core.config.load(), schedule=ScheduleSettings(start_time="06:00", repeat_for_h=0)
    )

    page.initializePage()

    assert "Ogni giorno alle 06:00, e al login." in page.autosync_note.text()


def test_no_legacy_task_means_nothing_to_remove(wizard, fake_core):
    page = wizard.automation_page
    page.initializePage()

    page.legacy_check.setChecked(True)  # hidden, but even so

    assert page.remove_legacy_requested() is False


def test_the_automation_page_no_longer_asks_for_the_editor(wizard):
    """Notepad++ has nothing to do with automation: it is on page 1."""
    assert not hasattr(wizard.automation_page, "editor_edit")


def test_the_editor_field_is_prefilled_from_the_detected_editor(wizard, fake_core, tmp_path):
    editor = tmp_path / "notepad++.exe"
    fake_core.config.editor = editor
    page = wizard.folder_page

    page.initializePage()

    assert page.editor_path() == editor


def test_no_detected_editor_leaves_the_field_empty_with_a_hint(wizard, fake_core):
    fake_core.config.editor = None
    page = wizard.folder_page

    page.initializePage()

    assert page.editor_path() is None
    assert page.editor_hint.text() == strings.WIZARD_P1_EDITOR_NOT_FOUND


def test_a_configured_editor_wins_over_detection_on_a_rerun(rerun_wizard, fake_core, tmp_path):
    mine = tmp_path / "mio" / "notepad++.exe"
    fake_core.config.config = dataclasses.replace(fake_core.config.config, editor_path=mine)
    fake_core.config.editor = tmp_path / "rilevato.exe"
    page = rerun_wizard.folder_page

    page.initializePage()

    assert page.editor_path() == mine


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
    page = wizard.folder_page

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


@pytest.fixture
def legacy_removals(fake_core, monkeypatch) -> list[int]:
    """Every ``remove_legacy_task`` call (the fake has no counter of its own)."""
    calls: list[int] = []
    real = fake_core.scheduler.remove_legacy_task

    def counted() -> None:
        calls.append(1)
        real()

    monkeypatch.setattr(fake_core.scheduler, "remove_legacy_task", counted)
    return calls


def test_by_default_fine_never_removes_the_legacy_task(wizard, fake_core, tmp_path,
                                                       legacy_removals):
    fake_core.scheduler.set_legacy(True)
    advance_to_automation(wizard, tmp_path / "logs")

    wizard.accept()

    assert fake_core.scheduler.register_calls == 1
    assert legacy_removals == [], "remove_legacy_task must not even be called"
    assert fake_core.scheduler.detect_legacy_task() is True


def test_the_legacy_task_is_removed_when_the_user_ticks_it(wizard, fake_core, tmp_path,
                                                           legacy_removals):
    fake_core.scheduler.set_legacy(True)
    advance_to_automation(wizard, tmp_path / "logs")
    wizard.automation_page.legacy_check.setChecked(True)

    wizard.accept()

    assert legacy_removals == [1]
    assert fake_core.scheduler.detect_legacy_task() is False


def test_the_legacy_task_is_removed_on_request_even_without_autosync(
        wizard, fake_core, tmp_path, legacy_removals):
    """An explicit choice: the user may be dropping the old sync altogether."""
    fake_core.scheduler.set_legacy(True)
    advance_to_automation(wizard, tmp_path / "logs")
    wizard.automation_page.autosync_check.setChecked(False)
    wizard.automation_page.legacy_check.setChecked(True)

    wizard.accept()

    assert legacy_removals == [1]
    assert fake_core.scheduler.register_calls == 0


def test_the_legacy_task_survives_when_ours_could_not_be_registered(
        wizard, fake_core, tmp_path, monkeypatch, legacy_removals):
    """Asked to replace the old task, failing to register the new one: keep
    the old one, or the user is left with no sync at all."""
    def boom() -> None:
        raise SchedulerError("schtasks ha restituito 1")

    monkeypatch.setattr(fake_core.scheduler, "register", boom)
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    fake_core.scheduler.set_legacy(True)
    advance_to_automation(wizard, tmp_path / "logs")
    wizard.automation_page.legacy_check.setChecked(True)

    wizard.accept()

    assert legacy_removals == []


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


def test_a_save_failure_keeps_the_wizard_open_and_says_why(
    wizard, fake_core, tmp_path, monkeypatch
):
    """Closing on a failed save would throw away everything the user entered."""
    def boom(_cfg) -> None:
        raise OSError("disco pieno")

    monkeypatch.setattr(fake_core.config, "save", boom)
    shown: list[tuple] = []
    monkeypatch.setattr(
        QMessageBox, "critical", staticmethod(lambda *args, **kw: shown.append(args))
    )
    advance_to_automation(wizard, tmp_path / "logs")

    wizard.accept()

    assert shown and "disco pieno" in shown[0][2]
    assert wizard.wizard_result() is None
    assert wizard.result() != int(QDialog.DialogCode.Accepted), "still open on page 3"
    assert fake_core.scheduler.register_calls == 0, "no task for a config that is not saved"


def test_a_failure_removing_the_legacy_task_is_swallowed(
    wizard, fake_core, tmp_path, monkeypatch
):
    fake_core.scheduler.set_legacy(True)

    def boom() -> None:
        raise SchedulerError("accesso negato")

    monkeypatch.setattr(fake_core.scheduler, "remove_legacy_task", boom)
    advance_to_automation(wizard, tmp_path / "logs")
    wizard.automation_page.legacy_check.setChecked(True)

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
    titles = [wizard.page(pid).step_title() for pid in wizard.pageIds()]
    assert titles == [
        strings.WIZARD_P1_TITLE,
        strings.WIZARD_P2_TITLE,
        strings.WIZARD_P3_TITLE,
    ]


# ------------------------------------------- 3. automazione, on a rerun ---

@pytest.fixture
def rerun_wizard(qtbot, fake_core, runner):
    """"Riesegui configurazione iniziale": a configuration already exists."""
    fake_core.config.first_run = False
    widget = FirstRunWizard(fake_core, runner)
    qtbot.addWidget(widget)
    return widget


@pytest.mark.parametrize("registered", [True, False])
def test_a_rerun_pre_checks_autosync_from_the_scheduled_task(
        qtbot, rerun_wizard, fake_core, tmp_path, registered):
    """Rerunning the wizard must not silently turn automation back on."""
    fake_core.scheduler.set_status(registered=registered)
    advance_to_automation(rerun_wizard, tmp_path / "logs")
    page = rerun_wizard.automation_page
    qtbot.waitUntil(page.autosync_check.isEnabled, timeout=5000)
    assert page.autosync_check.isChecked() is registered
    assert not page.autosync_checking.isVisible()


def test_the_checkbox_waits_disabled_while_the_task_is_being_checked(
        qtbot, rerun_wizard, fake_core, tmp_path, monkeypatch):
    gate = threading.Event()
    real_status = fake_core.scheduler.status

    def slow_status():
        gate.wait(5.0)
        return real_status()

    monkeypatch.setattr(fake_core.scheduler, "status", slow_status)
    rerun_wizard.show()
    advance_to_automation(rerun_wizard, tmp_path / "logs")
    page = rerun_wizard.automation_page
    try:
        assert not page.autosync_check.isEnabled()
        assert page.autosync_checking.isVisible()
        assert page.autosync_checking.text() == strings.WIZARD_P3_AUTOSYNC_CHECKING
    finally:
        gate.set()
    qtbot.waitUntil(page.autosync_check.isEnabled, timeout=5000)
    assert not page.autosync_checking.isVisible()


def test_a_first_run_keeps_autosync_on_without_asking(qtbot, wizard, fake_core, tmp_path,
                                                      monkeypatch):
    monkeypatch.setattr(fake_core.scheduler, "status",
                        lambda: pytest.fail("a first run has no task to ask about"))
    advance_to_automation(wizard, tmp_path / "logs")
    page = wizard.automation_page
    assert page.autosync_check.isEnabled()
    assert page.autosync_check.isChecked()


def test_the_answer_does_not_override_a_choice_made_meanwhile(
        qtbot, rerun_wizard, fake_core, tmp_path):
    """Going back and forth does not ask again and undo what the user ticked."""
    fake_core.scheduler.set_status(registered=False)
    advance_to_automation(rerun_wizard, tmp_path / "logs")
    page = rerun_wizard.automation_page
    qtbot.waitUntil(page.autosync_check.isEnabled, timeout=5000)
    page.autosync_check.setChecked(True)
    rerun_wizard.back()
    rerun_wizard.next()
    qtbot.wait(100)
    assert page.autosync_check.isChecked()


def test_fine_before_the_answer_registers_nothing(qtbot, rerun_wizard, fake_core, tmp_path,
                                                  monkeypatch):
    gate = threading.Event()
    real_status = fake_core.scheduler.status

    def slow_status():
        gate.wait(5.0)
        return real_status()

    monkeypatch.setattr(fake_core.scheduler, "status", slow_status)
    advance_to_automation(rerun_wizard, tmp_path / "logs")
    try:
        rerun_wizard.accept()
    finally:
        gate.set()
    assert fake_core.scheduler.register_calls == 0
    assert rerun_wizard.wizard_result().autosync is False


# ------------------------------------------------ header, intro, stepper ---

def test_every_page_has_the_header_with_icon_title_and_step(wizard):
    pages = [wizard.page(pid) for pid in wizard.pageIds()]
    for number, page in enumerate(pages, 1):
        header = page.header
        assert header.title_label.text() == page.step_title()
        assert header.step_label.text() == f"Passo {number} di 3"
        assert header.step_label.property("role") == "muted"
        pixmap = header.icon_label.pixmap()
        assert not pixmap.isNull()
        assert pixmap.deviceIndependentSize().toSize().width() == 48


def test_qt_draws_no_second_title_above_ours(wizard):
    """QWizard renders ``title()`` in its own banner: ours replaces it."""
    for pid in wizard.pageIds():
        assert wizard.page(pid).title() == ""
        assert wizard.page(pid).subTitle() == ""


def test_page_one_introduces_the_tool_and_gives_the_readme_advice(wizard):
    intro = wizard.folder_page.intro_label.text()
    assert strings.WIZARD_P1_INTRO in intro
    assert ("scegli una cartella su un disco locale capiente, "
            "non una cartella sincronizzata nel cloud") in intro


def test_only_page_one_has_the_intro(wizard):
    assert not hasattr(wizard.environments_page, "intro_label")
    assert not hasattr(wizard.automation_page, "intro_label")


# ------------------------------------ 3. automazione: unticking on a rerun ---

def _answered_rerun(qtbot, rerun_wizard, fake_core, tmp_path, *, registered: bool):
    fake_core.scheduler.set_status(registered=registered)
    advance_to_automation(rerun_wizard, tmp_path / "logs")
    page = rerun_wizard.automation_page
    qtbot.waitUntil(page.autosync_check.isEnabled, timeout=5000)
    return page


def test_unticking_a_registered_task_on_a_rerun_removes_it(qtbot, rerun_wizard, fake_core,
                                                          tmp_path):
    """The box is pre-checked from the real task: unticking it must mean "off"."""
    page = _answered_rerun(qtbot, rerun_wizard, fake_core, tmp_path, registered=True)
    page.autosync_check.setChecked(False)

    rerun_wizard.accept()

    assert fake_core.scheduler.unregister_calls == 1
    assert fake_core.scheduler.register_calls == 0
    assert rerun_wizard.wizard_result().autosync is False


def test_leaving_an_unregistered_task_off_touches_nothing(qtbot, rerun_wizard, fake_core,
                                                         tmp_path):
    _answered_rerun(qtbot, rerun_wizard, fake_core, tmp_path, registered=False)

    rerun_wizard.accept()

    assert fake_core.scheduler.unregister_calls == 0
    assert fake_core.scheduler.register_calls == 0


def test_a_first_run_without_autosync_never_unregisters(wizard, fake_core, tmp_path):
    advance_to_automation(wizard, tmp_path / "logs")
    wizard.automation_page.autosync_check.setChecked(False)

    wizard.accept()

    assert fake_core.scheduler.unregister_calls == 0


def test_fine_before_the_answer_unregisters_nothing(qtbot, rerun_wizard, fake_core, tmp_path,
                                                    monkeypatch):
    """No answer yet means we do not know the task exists: touch nothing."""
    gate = threading.Event()
    real_status = fake_core.scheduler.status
    fake_core.scheduler.set_status(registered=True)

    def slow_status():
        gate.wait(5.0)
        return real_status()

    monkeypatch.setattr(fake_core.scheduler, "status", slow_status)
    advance_to_automation(rerun_wizard, tmp_path / "logs")
    try:
        rerun_wizard.accept()
    finally:
        gate.set()
    assert fake_core.scheduler.unregister_calls == 0


def test_a_failure_unregistering_is_reported_but_never_blocks_fine(
        qtbot, rerun_wizard, fake_core, tmp_path, monkeypatch):
    page = _answered_rerun(qtbot, rerun_wizard, fake_core, tmp_path, registered=True)

    def boom() -> None:
        raise SchedulerError("accesso negato")

    monkeypatch.setattr(fake_core.scheduler, "unregister", boom)
    shown: list[tuple] = []
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *args, **kw: shown.append(args)))
    page.autosync_check.setChecked(False)

    rerun_wizard.accept()

    assert shown and "accesso negato" in shown[0][2]
    assert rerun_wizard.wizard_result() is not None
    assert rerun_wizard.wizard_result().autosync is True, "the task is still there"


# ------------------------------------------------ closing cancels the jobs ---

@pytest.mark.parametrize("close", ["reject", "accept"])
def test_closing_the_wizard_cancels_the_reachability_check(qtbot, wizard, fake_core, tmp_path,
                                                          monkeypatch, close):
    gate = threading.Event()
    monkeypatch.setattr(fake_core.sync, "check_reachable",
                        lambda env, timeout=5.0: gate.wait(5.0) or True)
    advance_to_automation(wizard, tmp_path / "logs")
    wizard.environments_page.table.set_environments(GOOD_ENVS)
    job = wizard.environments_page.check_reachability()
    try:
        getattr(wizard, close)()
        assert job.token.is_set(), "a closed wizard must not keep probing"
    finally:
        gate.set()


def test_closing_the_wizard_cancels_the_file_count(qtbot, wizard, fake_core, tmp_path,
                                                  monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(fake_core.index, "count_local_files",
                        lambda root=None: gate.wait(5.0) and 0)
    wizard.folder_page.set_path(tmp_path / "grande")
    job = wizard.folder_page.count_job()
    try:
        wizard.reject()
        assert job is not None and job.token.is_set()
    finally:
        gate.set()


# ------------------------------------------------- the environments table ---

def test_empty_cells_show_a_placeholder(wizard):
    from PySide6.QtWidgets import QStyleOptionViewItem

    page = wizard.environments_page
    page.add_environment()
    table = page.table
    delegate = table.itemDelegate()

    def shown(column: int) -> str:
        option = QStyleOptionViewItem()
        delegate.initStyleOption(option, table.model().index(0, column))
        return option.text

    assert shown(table.COL_NAME) == "nome"
    assert shown(table.COL_URL) == "https://…"

    table.item(0, table.COL_NAME).setText("coll")
    assert shown(table.COL_NAME) == "coll"
    assert page.environments() == [Environment("coll", "", True)], "never saved as data"


def test_the_cell_editor_carries_the_placeholder_too(wizard):
    from PySide6.QtWidgets import QLineEdit, QStyleOptionViewItem

    page = wizard.environments_page
    page.add_environment()
    table = page.table
    editor = table.itemDelegate().createEditor(
        table.viewport(), QStyleOptionViewItem(), table.model().index(0, table.COL_URL))
    assert isinstance(editor, QLineEdit)
    assert editor.placeholderText() == "https://…"


def test_a_new_row_is_highlighted_with_the_theme_selection(qtbot, themed, fake_core, runner):
    """Not an accent block: the theme's quiet selection colour."""
    from PySide6.QtGui import QPalette

    from qtrequestory.ui import theme

    theme.apply(themed, theme.Mode.LIGHT)
    widget = FirstRunWizard(fake_core, runner)
    qtbot.addWidget(widget)
    table = widget.environments_page.table
    assert table.styleSheet() == ""
    assert table.palette().color(QPalette.ColorRole.Highlight).name().upper() == \
        theme.LIGHT.selection
    widget.environments_page.add_environment()
    assert table.currentRow() == 0


# ------------------------------------ cancelling keeps it a first run ---

def test_cancelling_the_first_run_wizard_keeps_it_a_first_run(qtbot, fake_core, runner, tmp_path):
    """BACKLOG: a cancelled wizard used to leave a config.json behind, so it
    never came back. Reproduced with the REAL config service in a temp home."""
    from qtrequestory.core import facade
    from qtrequestory.core.paths import AppPaths

    real_config = facade.ConfigService(AppPaths(tmp_path / "home").ensure(),
                                       exe_dir=tmp_path / "exe", editor_candidates=[])
    services = dataclasses.replace(fake_core, config=real_config)
    assert real_config.is_first_run()

    widget = FirstRunWizard(services, runner)
    qtbot.addWidget(widget)
    advance_to_automation(widget, tmp_path / "logs")  # every page read the config
    widget.reject()

    assert real_config.is_first_run(), "the wizard must come back next time"
    assert not real_config.config_path().exists()
    assert fake_core.scheduler.register_calls == 0
