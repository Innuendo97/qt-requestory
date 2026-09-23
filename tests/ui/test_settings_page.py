"""Impostazioni: the form *is* the configuration, and [Salva] is its only writer.

Three behaviours carry the whole page and are tested here rather than through
the widgets' looks: nothing is written until the form is valid, nothing is
written twice (dirty tracking), and a changed mirror folder offers to index
what is already in it.

Dialogs are monkeypatched, never opened: a modal in a test suite is a hang.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from PySide6.QtCore import QTime
from PySide6.QtWidgets import QFileDialog, QMessageBox

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import Environment
from qtrequestory.ui.env_table import EnvTable
from qtrequestory.ui.pages.settings_page import SettingsPage
from qtrequestory.ui.pages.settings_presenter import form_of, normalised


class StubWindow:
    """Everything the page uses from ``MainWindow``: status line + wizard hook."""

    def __init__(self) -> None:
        self.status: list[str] = []
        self.wizard_calls = 0

    def set_status(self, text: str, ms: int = 4000) -> None:
        self.status.append(text)

    def rerun_wizard(self) -> None:
        self.wizard_calls += 1


@pytest.fixture
def window() -> StubWindow:
    return StubWindow()


@pytest.fixture
def page(qtbot, fake_core, runner, window):
    widget = SettingsPage(fake_core, runner, window)
    qtbot.addWidget(widget)
    return widget


def _answer(monkeypatch, button: QMessageBox.StandardButton) -> list[tuple]:
    """Make every ``QMessageBox.question`` answer ``button`` and record the call."""
    asked: list[tuple] = []

    def question(*args, **kwargs):
        asked.append(args)
        return button

    monkeypatch.setattr(QMessageBox, "question", staticmethod(question))
    return asked


# -- loading -----------------------------------------------------------------

def test_the_form_shows_the_loaded_configuration(page, fake_core):
    cfg = fake_core.config.load()
    assert page.mirror_path.text() == str(cfg.mirror_root)
    assert page.env_table.environments() == cfg.environments
    assert page.window_days() == cfg.default_window_days
    assert page.output_path.text() == str(cfg.output_dir)


def test_a_freshly_loaded_form_is_not_dirty(page):
    assert not page.is_dirty()
    assert not page.save_button.isEnabled()


# -- dirty tracking ----------------------------------------------------------

def test_editing_a_field_enables_the_save_button(page, tmp_path):
    page.mirror_path.setText(str(tmp_path / "altrove"))
    assert page.is_dirty()
    assert page.save_button.isEnabled()


def test_editing_the_environments_table_enables_the_save_button(page):
    page.env_table.item(0, EnvTable.COL_NAME).setText("prod")
    assert page.save_button.isEnabled()


def test_annulla_puts_the_loaded_configuration_back(page, fake_core, tmp_path):
    cfg = fake_core.config.load()
    page.mirror_path.setText(str(tmp_path / "altrove"))
    page.cancel_button.click()
    assert page.mirror_path.text() == str(cfg.mirror_root)
    assert not page.save_button.isEnabled()
    assert fake_core.config.saved == []


# -- validation --------------------------------------------------------------

def test_an_invalid_url_blocks_the_save_and_is_shown_inline(page, fake_core):
    page.env_table.item(0, EnvTable.COL_URL).setText("ftp://example.invalid/coll/")

    page.save_button.click()

    assert fake_core.config.saved == [], "an invalid configuration is never written"
    assert not page.errors_label.isHidden()
    assert "http://" in page.errors_label.text()
    assert page.save_button.isEnabled(), "the form stays dirty so it can be corrected"


def test_a_missing_mirror_folder_blocks_the_save(page, fake_core):
    page.mirror_path.setText("   ")
    page.save_button.click()
    assert fake_core.config.saved == []
    assert strings.SETTINGS_ERROR_NO_MIRROR in page.errors_label.text()


def test_a_successful_save_clears_a_previous_error(page, fake_core):
    page.env_table.item(0, EnvTable.COL_URL).setText("ftp://example.invalid/coll/")
    page.save_button.click()
    assert not page.errors_label.isHidden()

    page.env_table.item(0, EnvTable.COL_URL).setText("https://example.invalid/coll-2/")
    page.save_button.click()

    assert fake_core.config.saved, "the corrected form is written"
    assert page.errors_label.isHidden()


# -- saving ------------------------------------------------------------------

def test_a_valid_save_persists_and_announces_the_new_configuration(
    page, fake_core, window, qtbot
):
    page.set_window_days(7)

    with qtbot.waitSignal(page.config_changed, timeout=1000) as announced:
        page.save_button.click()

    saved = fake_core.config.saved[-1]
    assert saved.default_window_days == 7
    assert announced.args[0] is saved
    assert not page.save_button.isEnabled(), "a saved form is no longer dirty"
    assert strings.SETTINGS_SAVED in window.status


def test_an_empty_temporary_folder_means_the_system_default(page, fake_core):
    page.output_path.setText("")
    page.save_button.click()
    assert fake_core.config.saved[-1].output_dir is None


def test_saving_keeps_the_fields_the_page_does_not_edit(page, fake_core, tmp_path):
    before = fake_core.config.load()
    page.set_window_days(90)
    page.save_button.click()
    saved = fake_core.config.saved[-1]
    assert saved.compaction_time == before.compaction_time
    assert saved.sync == before.sync
    assert saved.log_level == before.log_level


# -- the reindex question ----------------------------------------------------

def test_a_new_mirror_folder_offers_to_index_it(page, fake_core, tmp_path, monkeypatch, qtbot):
    _answer(monkeypatch, QMessageBox.StandardButton.Yes)
    page.mirror_path.setText(str(tmp_path / "nuovi-log"))

    page.save_button.click()

    qtbot.waitUntil(lambda: bool(fake_core.index.updates), timeout=3000)
    assert fake_core.index.updates[-1]["full_rebuild"] is False


def test_declining_the_reindex_question_starts_nothing(
    page, fake_core, tmp_path, monkeypatch, qtbot
):
    asked = _answer(monkeypatch, QMessageBox.StandardButton.No)
    page.mirror_path.setText(str(tmp_path / "nuovi-log"))

    page.save_button.click()
    qtbot.wait(150)

    assert asked, "the question is still asked"
    assert fake_core.index.updates == []


def test_saving_without_moving_the_mirror_asks_nothing(page, fake_core, monkeypatch, qtbot):
    asked = _answer(monkeypatch, QMessageBox.StandardButton.Yes)
    page.set_window_days(90)

    page.save_button.click()
    qtbot.wait(150)

    assert asked == []
    assert fake_core.index.updates == []


# -- automatic synchronisation -----------------------------------------------

def _set_schedule(page, start: str, every: int, hours: int, logon: bool) -> None:
    page.schedule_start.setTime(QTime.fromString(start, "HH:mm"))
    page.schedule_every.setValue(every)
    page.schedule_for.setValue(hours)
    page.schedule_logon.setChecked(logon)


def test_the_four_schedule_fields_show_the_saved_schedule(page, fake_core):
    cfg = fake_core.config.load()
    assert page.schedule_start.time().toString("HH:mm") == cfg.schedule.start_time
    assert page.schedule_every.value() == cfg.schedule.repeat_every_h
    assert page.schedule_for.value() == cfg.schedule.repeat_for_h
    assert page.schedule_logon.isChecked() == cfg.schedule.run_at_logon
    assert not page.is_dirty()


@pytest.mark.parametrize("stored", ["09:00", "7:30", "23:05"])
def test_a_start_time_the_core_accepts_loads_as_it_is(qtbot, fake_core, runner, window, stored):
    """``config.validate`` accepts a one-digit hour, and the task registers it.

    ``QTime.fromString(…, "HH:mm")`` does not: reading the field through Qt's
    parser would show 09:00 for a stored "7:30", light [Salva] without a single
    edit, disagree with the Sincronizzazione line — and rewrite the user's hour
    on the next save.
    """
    from qtrequestory.ui.contracts import ScheduleSettings, parse_hhmm

    fake_core.config.config = dataclasses.replace(
        fake_core.config.load(), schedule=ScheduleSettings(start_time=stored)
    )
    page = SettingsPage(fake_core, runner, window)
    qtbot.addWidget(page)

    hour, minute = (int(part) for part in stored.split(":"))
    assert page.schedule_start.time() == QTime(hour, minute)
    assert f"{hour:02d}:{minute:02d}" in page.schedule_summary.text()
    assert not page.is_dirty(), "loading a valid configuration is not an edit"

    page.save_button.click()
    assert fake_core.config.saved == [], "nothing was edited, so nothing is written"

    page.set_window_days(90)  # an unrelated edit must not move the start time
    page.save_button.click()
    assert parse_hhmm(fake_core.config.saved[-1].schedule.start_time) == parse_hhmm(stored)


@pytest.mark.parametrize(
    "edit",
    [
        lambda p: p.schedule_start.setTime(QTime(7, 30)),
        lambda p: p.schedule_every.setValue(3),
        lambda p: p.schedule_for.setValue(0),
        lambda p: p.schedule_logon.setChecked(False),
    ],
)
def test_editing_any_schedule_field_enables_the_save_button(page, edit):
    edit(page)
    assert page.is_dirty()
    assert page.save_button.isEnabled()


def test_the_summary_says_in_words_what_the_fields_mean(page):
    """The user should not have to add 6 to 07:30 in their head to find out
    when the retry window closes."""
    _set_schedule(page, "07:30", 2, 6, False)
    assert page.schedule_summary.text() == (
        "Ogni giorno alle 07:30, riprova ogni 2 ore fino alle 13:30."
    )
    page.schedule_logon.setChecked(True)
    assert page.schedule_summary.text().endswith(", e al login.")


def test_the_spin_boxes_cannot_be_driven_out_of_the_valid_range(page):
    """The validation in ``config.validate`` is the safety net; the widgets are
    the first line, so an invalid schedule cannot even be typed. The ranges
    come from the core's own constants, not a copy of them."""
    from qtrequestory.core.config import REPEAT_EVERY_RANGE, REPEAT_FOR_RANGE

    assert (page.schedule_every.minimum(), page.schedule_every.maximum()) == REPEAT_EVERY_RANGE
    assert (page.schedule_for.minimum(), page.schedule_for.maximum()) == REPEAT_FOR_RANGE
    assert REPEAT_EVERY_RANGE == (1, 12) and REPEAT_FOR_RANGE == (0, 23)
    page.schedule_for.setValue(99)
    assert page.schedule_for.value() == 23
    page.schedule_every.setValue(0)
    assert page.schedule_every.value() == 1


def test_no_repetition_is_spelled_out_instead_of_a_bare_zero(page):
    page.schedule_for.setValue(0)
    assert page.schedule_for.text() == strings.SETTINGS_SCHEDULE_NO_REPEAT


def test_saving_writes_the_schedule(page, fake_core):
    _set_schedule(page, "07:30", 2, 6, False)

    page.save_button.click()

    saved = fake_core.config.saved[-1].schedule
    assert (saved.start_time, saved.repeat_every_h, saved.repeat_for_h, saved.run_at_logon) == (
        "07:30", 2, 6, False,
    )
    assert not page.save_button.isEnabled()


def test_an_invalid_schedule_blocks_the_save_and_says_why(qapp, fake_core):
    """The widgets cannot produce one, but a hand-edited ``config.json`` can:
    the rules live in the core, and the page shows what it reports."""
    from qtrequestory.ui.contracts import ScheduleSettings
    from qtrequestory.ui.pages.settings_presenter import FormValues, SettingsPresenter

    presenter = SettingsPresenter(fake_core)
    form = dataclasses.replace(
        form_of(fake_core.config.load()),
        schedule=ScheduleSettings(start_time="25:00", repeat_every_h=99),
    )

    errors = presenter.save(form)

    assert fake_core.config.saved == []
    assert any("start_time" in e for e in errors) and any("repeat_every_h" in e for e in errors)


def test_a_registered_task_is_re_registered_with_the_new_schedule(page, fake_core, qtbot):
    """Saving a schedule that never reaches Task Scheduler is the one failure
    the user cannot see: the form would show 07:30 and the task keep 09:00."""
    fake_core.scheduler.set_status(registered=True, exe_matches=True)
    _set_schedule(page, "07:30", 2, 6, False)

    page.save_button.click()

    assert page.scheduler_job is not None
    with qtbot.waitSignal(page.scheduler_job.signals.finished, timeout=5000):
        pass
    assert fake_core.scheduler.register_calls == 1


def test_a_task_that_is_not_registered_is_left_alone(page, fake_core, qtbot):
    assert fake_core.scheduler.status().registered is False
    _set_schedule(page, "07:30", 2, 6, False)

    page.save_button.click()
    qtbot.wait(150)

    assert fake_core.scheduler.register_calls == 0
    assert page.scheduler_job is None


def test_a_failed_re_registration_is_a_banner_not_a_dialog(page, fake_core, window, qtbot):
    from qtrequestory.ui.contracts import SchedulerError

    fake_core.scheduler.set_status(registered=True, exe_matches=True)

    def boom() -> None:
        raise SchedulerError("schtasks: accesso negato")

    fake_core.scheduler.register = boom
    _set_schedule(page, "07:30", 2, 6, False)

    page.save_button.click()

    qtbot.waitUntil(lambda: not page.schedule_banner.isHidden(), timeout=5000)
    assert "accesso negato" in page.schedule_banner_label.text()
    assert strings.SETTINGS_SAVED in window.status, "the configuration itself was saved"


# -- environments ------------------------------------------------------------

def test_verifica_reports_every_environment(page, fake_core, qtbot):
    fake_core.sync.set_unreachable("svil")

    page.check_button.click()

    qtbot.waitUntil(lambda: "svil" in page.check_label.text(), timeout=3000)
    text = page.check_label.text()
    assert strings.SETTINGS_CHECK_REACHABLE.format(name="coll") in text
    assert strings.SETTINGS_CHECK_UNREACHABLE.format(name="svil") in text


def test_verifica_probes_the_url_on_screen_not_the_one_already_saved(
    page, fake_core, qtbot, monkeypatch
):
    """A URL corrected in the table is probed before [Salva] — that correction
    is the whole reason the user presses [Verifica]."""
    probed: list[Environment] = []
    monkeypatch.setattr(fake_core.sync, "check_reachable",
                        lambda env, timeout=5.0: probed.append(env) or True)
    edited = [Environment("coll", "https://example.invalid/coll-corretto/", True)]
    page.env_table.set_environments(edited)

    page.check_button.click()

    qtbot.waitUntil(lambda: bool(probed), timeout=3000)
    assert probed == edited


def test_a_malformed_environments_file_is_reported_and_changes_nothing(
    page, fake_core, tmp_path, monkeypatch
):
    fake_core.config.set_import_error("environments.json: JSON non valido")
    chosen = tmp_path / "environments.json"
    chosen.write_text("{", encoding="utf-8")
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(chosen), ""))
    )
    warned: list[tuple] = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warned.append(a)))
    before = page.env_table.environments()

    page.import_button.click()

    assert warned, "the user is told why the file was refused"
    assert "JSON non valido" in warned[-1][2]
    assert page.env_table.environments() == before


def test_importing_a_valid_file_replaces_the_rows(page, fake_core, tmp_path, monkeypatch):
    chosen = tmp_path / "environments.json"
    chosen.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(chosen), ""))
    )
    page.env_table.item(0, EnvTable.COL_NAME).setText("scarabocchio")

    page.import_button.click()

    assert page.env_table.environments() == fake_core.config.sidecar_environments


def test_aggiungi_and_rimuovi_edit_the_table(page):
    before = page.env_table.rowCount()
    page.add_button.click()
    assert page.env_table.rowCount() == before + 1
    page.env_table.selectRow(before)
    page.remove_button.click()
    assert page.env_table.rowCount() == before


# -- editor ------------------------------------------------------------------

def test_rileva_fills_in_the_detected_editor(page, fake_core, tmp_path):
    exe = tmp_path / "notepad++.exe"
    exe.write_bytes(b"")
    fake_core.config.editor = exe

    page.detect_button.click()

    assert page.editor_path.text() == str(exe)
    assert page.save_button.isEnabled()


def test_rileva_says_so_when_nothing_is_found(page, fake_core, window):
    fake_core.config.editor = None
    page.detect_button.click()
    assert page.editor_path.text() == ""
    assert strings.SETTINGS_EDITOR_NOT_FOUND in window.status


# -- Avanzate ----------------------------------------------------------------

def test_ricostruisci_indice_asks_first_then_rebuilds(page, fake_core, monkeypatch, qtbot):
    asked = _answer(monkeypatch, QMessageBox.StandardButton.Yes)

    page.rebuild_button.click()

    assert asked, "a full rebuild is never started without asking"
    qtbot.waitUntil(lambda: bool(fake_core.index.updates), timeout=3000)
    assert fake_core.index.updates[-1]["full_rebuild"] is True


def test_a_refused_rebuild_does_nothing(page, fake_core, monkeypatch, qtbot):
    _answer(monkeypatch, QMessageBox.StandardButton.No)
    page.rebuild_button.click()
    qtbot.wait(150)
    assert fake_core.index.updates == []


def test_riesegui_configurazione_iniziale_calls_the_window_hook(page, window):
    page.wizard_button.click()
    assert window.wizard_calls == 1


def test_the_configuration_file_is_shown_and_its_folder_can_be_opened(page, fake_core):
    path = fake_core.config.config_path()
    assert page.config_path_label.full_text() == str(path)

    page.open_config_button.click()

    assert fake_core.extract.folders[-1] == path.parent


def test_apri_opens_the_mirror_folder(page, fake_core):
    page.open_mirror_button.click()
    assert fake_core.extract.folders[-1] == Path(page.mirror_path.text())


# -- browsing ----------------------------------------------------------------

def test_sfoglia_writes_the_chosen_folder_into_the_field(page, tmp_path, monkeypatch):
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(tmp_path))
    )
    page.browse_mirror_button.click()
    assert page.mirror_path.text() == str(tmp_path)


def test_a_cancelled_browse_leaves_the_field_alone(page, monkeypatch):
    before = page.mirror_path.text()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: ""))
    page.browse_mirror_button.click()
    assert page.mirror_path.text() == before
    assert not page.is_dirty()


def test_repicking_the_configured_folder_is_not_an_edit(page, fake_core, monkeypatch):
    """Qt's dialogs hand back forward slashes even on Windows, so without
    normalisation picking the folder that is already configured would enable
    [Salva] and broadcast a ``config_changed`` that changed nothing."""
    configured = str(fake_core.config.load().mirror_root)
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory",
        staticmethod(lambda *a, **k: configured.replace("\\", "/")),
    )

    page.browse_mirror_button.click()

    assert not page.is_dirty()
    assert not page.save_button.isEnabled()


def test_normalised_uses_the_platform_spelling_and_keeps_empty_empty(tmp_path):
    assert normalised(str(tmp_path).replace("\\", "/")) == str(tmp_path)
    assert normalised("   ") == ""


def test_a_failing_reachability_check_reports_instead_of_spinning(
    page, fake_core, monkeypatch, qtbot
):
    def boom(env_name: str, timeout: float = 5.0) -> bool:
        raise OSError("rete non disponibile")

    monkeypatch.setattr(fake_core.sync, "check_reachable", boom)

    page.check_button.click()

    qtbot.waitUntil(lambda: "rete non disponibile" in page.check_label.text(), timeout=3000)
    assert page.check_label.text() != strings.SETTINGS_CHECK_RUNNING


# -- inside the shell --------------------------------------------------------

def test_the_window_builds_the_real_page_and_broadcasts_its_saves(qtbot, fake_core, runner):
    """``MainWindow`` degrades a page that raises to a placeholder label, which
    is what would otherwise hide a broken factory signature from every test in
    this file — and the broadcast is how the other pages learn about a save."""
    from qtrequestory.ui.main_window import MainWindow
    from qtrequestory.ui.pages.about_page import AboutPage

    window = MainWindow(fake_core, runner)
    qtbot.addWidget(window)
    page = window.page("settings")
    assert isinstance(page, SettingsPage)
    assert isinstance(window.page("about"), AboutPage)

    page.set_window_days(7)
    page.save_button.click()

    assert fake_core.config.saved[-1].default_window_days == 7
    assert str(fake_core.index_db_path()) in window.page("about").path_labels["index"].full_text()


def test_the_page_has_a_title(page):
    """The app bar only shows a gear: the page itself says where you are."""
    assert page.title_label.text() == strings.SETTINGS_TITLE == "Impostazioni"
    assert page.title_label.property("role") == "pageTitle"


def test_ricostruisci_indice_refuses_an_invalid_log_folder(qtbot, fake_core, runner, window, monkeypatch):
    """Final review #1: no index job into the process CWD."""
    fake_core.config.config = dataclasses.replace(fake_core.config.config, mirror_root=Path(""))
    page = SettingsPage(fake_core, runner, window)
    qtbot.addWidget(page)
    asked = _answer(monkeypatch, QMessageBox.StandardButton.Yes)

    page.rebuild_button.click()
    qtbot.wait(150)

    assert not asked, "nothing to ask: it cannot run"
    assert fake_core.index.updates == [] and runner.job("index") is None
    assert any("cartella dei log" in text.lower() for text in window.status), window.status
