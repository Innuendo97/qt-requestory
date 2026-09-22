"""Impostazioni: the form *is* the configuration, and [Salva] is its only writer.

Three behaviours carry the whole page and are tested here rather than through
the widgets' looks: nothing is written until the form is valid, nothing is
written twice (dirty tracking), and a changed mirror folder offers to index
what is already in it.

Dialogs are monkeypatched, never opened: a modal in a test suite is a hang.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QFileDialog, QMessageBox

from qtrequestory.ui import strings
from qtrequestory.ui.env_table import EnvTable
from qtrequestory.ui.pages.settings_page import SettingsPage


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
    assert page.mirror_edit.text() == str(cfg.mirror_root)
    assert page.env_table.environments() == cfg.environments
    assert page.window_days() == cfg.default_window_days
    assert page.output_edit.text() == str(cfg.output_dir)


def test_a_freshly_loaded_form_is_not_dirty(page):
    assert not page.is_dirty()
    assert not page.save_button.isEnabled()


# -- dirty tracking ----------------------------------------------------------

def test_editing_a_field_enables_the_save_button(page, tmp_path):
    page.mirror_edit.setText(str(tmp_path / "altrove"))
    assert page.is_dirty()
    assert page.save_button.isEnabled()


def test_editing_the_environments_table_enables_the_save_button(page):
    page.env_table.item(0, EnvTable.COL_NAME).setText("prod")
    assert page.save_button.isEnabled()


def test_annulla_puts_the_loaded_configuration_back(page, fake_core, tmp_path):
    cfg = fake_core.config.load()
    page.mirror_edit.setText(str(tmp_path / "altrove"))
    page.cancel_button.click()
    assert page.mirror_edit.text() == str(cfg.mirror_root)
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
    page.mirror_edit.setText("   ")
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
    page.output_edit.setText("")
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
    page.mirror_edit.setText(str(tmp_path / "nuovi-log"))

    page.save_button.click()

    qtbot.waitUntil(lambda: bool(fake_core.index.updates), timeout=3000)
    assert fake_core.index.updates[-1]["full_rebuild"] is False


def test_declining_the_reindex_question_starts_nothing(
    page, fake_core, tmp_path, monkeypatch, qtbot
):
    asked = _answer(monkeypatch, QMessageBox.StandardButton.No)
    page.mirror_edit.setText(str(tmp_path / "nuovi-log"))

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


# -- environments ------------------------------------------------------------

def test_verifica_reports_every_environment(page, fake_core, qtbot):
    fake_core.sync.set_unreachable("svil")

    page.check_button.click()

    qtbot.waitUntil(lambda: "svil" in page.check_label.text(), timeout=3000)
    text = page.check_label.text()
    assert strings.SETTINGS_CHECK_REACHABLE.format(name="coll") in text
    assert strings.SETTINGS_CHECK_UNREACHABLE.format(name="svil") in text


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

    assert page.editor_edit.text() == str(exe)
    assert page.save_button.isEnabled()


def test_rileva_says_so_when_nothing_is_found(page, fake_core, window):
    fake_core.config.editor = None
    page.detect_button.click()
    assert page.editor_edit.text() == ""
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
    assert str(path) in page.config_path_label.text()

    page.open_config_button.click()

    assert fake_core.extract.folders[-1] == path.parent


def test_apri_opens_the_mirror_folder(page, fake_core):
    page.open_mirror_button.click()
    assert fake_core.extract.folders[-1] == Path(page.mirror_edit.text())


# -- browsing ----------------------------------------------------------------

def test_sfoglia_writes_the_chosen_folder_into_the_field(page, tmp_path, monkeypatch):
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(tmp_path))
    )
    page.browse_mirror_button.click()
    assert page.mirror_edit.text() == str(tmp_path)


def test_a_cancelled_browse_leaves_the_field_alone(page, monkeypatch):
    before = page.mirror_edit.text()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: ""))
    page.browse_mirror_button.click()
    assert page.mirror_edit.text() == before
    assert not page.is_dirty()


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
    assert str(fake_core.index_db_path()) in window.page("about").path_labels["index"].text()
