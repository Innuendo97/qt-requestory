"""Impostazioni → Officina: folder, generators, default, Postman-Token,
header profile and timeout, through the page's own Save / Annulla flow.

The rules (PROD, https, header names, duplicates) are the core's own
(``core.config``); these tests check that the section shows them inline on the
offending row and that Save stays blocked while any is there.
"""
from __future__ import annotations

import dataclasses
import threading

import pytest
from PySide6.QtCore import QLocale, Qt

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import OFFICINA_TIMEOUT_RANGE, GeneratorEndpoint, OfficinaSettings
from qtrequestory.ui.main_window import MainWindow
from qtrequestory.ui.pages.settings_officina import OfficinaSection
from qtrequestory.ui.pages.settings_officina_tables import GeneratorTable, HeaderTable
from qtrequestory.ui.pages.settings_page import SettingsPage
from qtrequestory.ui.workers import OFFICINA_GENERATE_JOBS

SVIL = GeneratorEndpoint("svil", "https://example.invalid/svil/rest/api/submit-job/documentGenerator")
COLL = GeneratorEndpoint("coll", "https://example.invalid/coll/rest/api/submit-job/documentGenerator")


class StubWindow:
    def __init__(self) -> None:
        self.status: list[str] = []

    def set_status(self, text: str, ms: int = 4000) -> None:
        self.status.append(text)

    def show_toast(self, text: str, tone: str = "neutral", ms: int = 0) -> None:
        self.status.append(text)


@pytest.fixture
def page(qtbot, fake_core, runner):
    fake_core.config.config.officina = dataclasses.replace(
        fake_core.config.config.officina, generators=[SVIL, COLL], default_generator="svil",
        header_profile={"office_id": "OFF", "X-Flag": "active"}, timeout_s=90)
    widget = SettingsPage(fake_core, runner, StubWindow())
    qtbot.addWidget(widget)
    widget.show_section("officina")
    return widget


def section(page) -> OfficinaSection:
    return page.officina_section


def set_cell(table, row: int, column: int, text: str) -> None:
    table.item(row, column).setText(text)


def set_enabled(table: GeneratorTable, row: int, enabled: bool) -> None:
    table.item(row, table.COL_ENABLED).setCheckState(
        Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked)


def saved_officina(fake_core) -> OfficinaSettings:
    return fake_core.config.config.officina


# -- loading -----------------------------------------------------------------

def test_the_section_shows_the_configuration(page, fake_core):
    s = section(page)
    o = saved_officina(fake_core)
    assert s.folder.text() == str(o.root)
    assert s.generators.generators() == [SVIL, COLL]
    assert s.default_combo.currentText() == "svil"
    assert s.token.text() == "qtRequestory"
    assert s.headers.rows() == [("office_id", "OFF"), ("X-Flag", "active")]
    assert s.timeout.value() == 90
    assert s.values() == o
    assert not page.is_dirty()
    assert page.save_bar.isHidden()


def test_the_timeout_is_a_bounded_box_with_the_unit_in_the_label(page):
    s = section(page)
    assert (s.timeout.minimum(), s.timeout.maximum()) == OFFICINA_TIMEOUT_RANGE
    assert "secondi" in s.timeout_label.text()


def test_the_postman_token_explains_why_it_is_not_empty(page):
    assert "nginx" in section(page).token_hint.text()


# -- round trip --------------------------------------------------------------

def test_every_field_round_trips_through_the_real_save(page, fake_core, tmp_path):
    s = section(page)
    new_root = tmp_path / "altrove" / "officina"
    s.folder.setText(str(new_root))
    row = s.generators.add_row()
    set_cell(s.generators, row, s.generators.COL_NAME, "svil2")
    set_cell(s.generators, row, s.generators.COL_URL, "https://example.invalid/svil2/g")
    s.default_combo.setCurrentText("svil2")
    s.token.setText("prova-token")
    r = s.headers.add_row()
    set_cell(s.headers, r, s.headers.COL_NAME, "branch_id")
    set_cell(s.headers, r, s.headers.COL_VALUE, "BR1")
    s.timeout.setValue(45)
    assert page.is_dirty() and not page.save_bar.isHidden() and page.save_button.isEnabled()

    assert page.save() is True
    o = saved_officina(fake_core)
    assert o.root == new_root
    assert o.generators == [SVIL, COLL, GeneratorEndpoint("svil2", "https://example.invalid/svil2/g")]
    assert o.default_generator == "svil2"
    assert o.postman_token == "prova-token"
    assert o.header_profile == {"office_id": "OFF", "X-Flag": "active", "branch_id": "BR1"}
    assert o.timeout_s == 45
    assert not page.is_dirty() and page.save_bar.isHidden()
    assert s.values() == o  # the reloaded form is the saved configuration


def test_annulla_puts_the_saved_values_back(page, fake_core):
    s = section(page)
    s.token.setText("altro")
    s.generators.remove_rows([1])
    assert not page.save_bar.isHidden()
    page.reload()
    assert s.token.text() == "qtRequestory"
    assert s.generators.generators() == [SVIL, COLL]
    assert page.save_bar.isHidden()


def test_the_other_settings_survive_an_officina_save(page, fake_core):
    before = fake_core.config.load()
    section(page).timeout.setValue(30)
    assert page.save()
    after = fake_core.config.load()
    assert dataclasses.replace(after, officina=before.officina) == before


# -- PROD and the other generator rules, inline ----------------------------------------

@pytest.mark.parametrize("name, url", [
    ("PROD", "https://example.invalid/g"),
    ("svil3", "https://inspire-prod.example.invalid/g"),
    ("ｐｒｏｄ", "https://example.invalid/g"),  # fullwidth: the core's NFKC guard
])
def test_a_prod_row_shows_an_inline_error_and_blocks_save(page, fake_core, name, url):
    s = section(page)
    row = s.generators.add_row()
    set_cell(s.generators, row, s.generators.COL_NAME, name)
    set_cell(s.generators, row, s.generators.COL_URL, url)
    problem = s.generators.problem_text(row)
    assert "prod" in problem
    assert not s.generators.isColumnHidden(s.generators.COL_PROBLEM)
    assert s.generators.problem_text(0) == ""
    assert not page.save_button.isEnabled()
    before = list(fake_core.config.saved)
    assert page.save() is False
    assert fake_core.config.saved == before


def test_fixing_the_row_clears_the_error_and_unblocks_save(page):
    s = section(page)
    row = s.generators.add_row()
    set_cell(s.generators, row, s.generators.COL_NAME, "PROD")
    set_cell(s.generators, row, s.generators.COL_URL, "https://example.invalid/g")
    assert not page.save_button.isEnabled()
    set_cell(s.generators, row, s.generators.COL_NAME, "svil2")
    assert s.generators.problem_text(row) == ""
    assert s.generators.isColumnHidden(s.generators.COL_PROBLEM)
    assert page.save_button.isEnabled()


def test_plain_http_is_refused_inline(page):
    s = section(page)
    set_cell(s.generators, 1, s.generators.COL_URL, "http://example.invalid/g")
    assert "https://" in s.generators.problem_text(1)
    assert not page.save_button.isEnabled()


def test_generator_names_are_unique_ignoring_case(page):
    s = section(page)
    row = s.generators.add_row()
    set_cell(s.generators, row, s.generators.COL_NAME, "SVIL")
    set_cell(s.generators, row, s.generators.COL_URL, "https://example.invalid/x")
    assert "duplicato" in s.generators.problem_text(row)
    assert s.generators.problem_text(0) == ""
    assert not page.save_button.isEnabled()


def test_a_blank_new_row_is_not_an_error(page):
    s = section(page)
    s.generators.add_row()
    assert s.problems() == []
    assert s.generators.generators() == [SVIL, COLL]


def test_urls_with_a_query_are_masked_in_the_table(page):
    s = section(page)
    secret = "SEGRETO123"
    set_cell(s.generators, 1, s.generators.COL_URL, f"https://example.invalid/coll/g?sv=1&sig={secret}")
    item = s.generators.item(1, s.generators.COL_URL)
    shown = s.generators.itemDelegateForColumn(s.generators.COL_URL).displayText(item.text(), QLocale())
    assert secret not in shown and "example.invalid/coll/g" in shown
    assert secret not in (item.toolTip() or "")
    plain = s.generators.item(0, s.generators.COL_URL).text()
    assert s.generators.itemDelegateForColumn(s.generators.COL_URL).displayText(plain, QLocale()) == plain


# -- the default generator ----------------------------------------------------

def test_the_default_offers_only_enabled_generators(page):
    s = section(page)
    set_enabled(s.generators, 1, False)
    assert [s.default_combo.itemText(i) for i in range(s.default_combo.count())] == ["svil"]


@pytest.mark.parametrize("how", ["disable", "delete"])
def test_losing_the_default_clears_it_with_an_inline_message(page, fake_core, how):
    s = section(page)
    if how == "disable":
        set_enabled(s.generators, 0, False)
    else:
        s.generators.remove_rows([0])
    assert s.default_combo.currentIndex() == -1
    assert "svil" in s.default_problem.text() and s.default_problem.isVisibleTo(s)
    assert s.values().default_generator == ""
    assert not page.save_button.isEnabled()
    assert page.save() is False

    s.default_combo.setCurrentText("coll")
    assert not s.default_problem.isVisibleTo(s)
    assert page.save()
    assert saved_officina(fake_core).default_generator == "coll"


def test_renaming_the_default_row_keeps_it_the_default(page):
    s = section(page)
    set_cell(s.generators, 0, s.generators.COL_NAME, "sviluppo")
    assert s.values().default_generator == "sviluppo"
    assert s.default_combo.currentText() == "sviluppo"


def test_a_default_configuration_is_not_dirty(qtbot, fake_core, runner):
    """Shipped defaults: no generators, default "svil". Nothing to choose,
    nothing to report, and the form is clean."""
    fake_core.config.config.officina = OfficinaSettings()
    widget = SettingsPage(fake_core, runner, StubWindow())
    qtbot.addWidget(widget)
    assert not widget.is_dirty()
    assert widget.officina_section.problems() == []


def test_adding_the_generator_named_by_the_default_selects_it(qtbot, fake_core, runner):
    fake_core.config.config.officina = OfficinaSettings()
    widget = SettingsPage(fake_core, runner, StubWindow())
    qtbot.addWidget(widget)
    s = widget.officina_section
    row = s.generators.add_row()
    set_cell(s.generators, row, s.generators.COL_URL, SVIL.url)
    set_cell(s.generators, row, s.generators.COL_NAME, "svil")
    assert s.default_combo.currentText() == "svil"
    assert widget.save_button.isEnabled()


# -- Postman-Token ------------------------------------------------------------

def test_an_empty_postman_token_is_refused_inline(page):
    s = section(page)
    s.token.setText("  ")
    assert s.token_problem.isVisibleTo(s) and "Postman-Token" in s.token_problem.text()
    assert not page.save_button.isEnabled()


# -- header profile -------------------------------------------------------------

@pytest.mark.parametrize("name, value, expected", [
    ("", "orfano", "nome"),
    ("bad name", "x", "valido"),
    ("Host", "example.invalid", "client HTTP"),
    ("Content-Length", "10", "client HTTP"),
    ("Transfer-Encoding", "chunked", "client HTTP"),
    ("Connection", "close", "client HTTP"),
    ("x_riga", "a\r\nb", "a capo"),
    ("OFFICE_ID", "dup", "duplicat"),
])
def test_a_bad_header_row_shows_an_inline_error_and_blocks_save(page, fake_core, name, value,
                                                                 expected):
    s = section(page)
    row = s.headers.add_row()
    set_cell(s.headers, row, s.headers.COL_VALUE, value)
    set_cell(s.headers, row, s.headers.COL_NAME, name)
    assert expected in s.headers.problem_text(row)
    assert s.headers.problem_text(0) == ""
    assert not page.save_button.isEnabled()
    before = list(fake_core.config.saved)
    assert page.save() is False
    assert fake_core.config.saved == before


def test_a_blank_header_row_is_ignored(page):
    s = section(page)
    s.headers.add_row()
    assert s.problems() == []
    assert s.values().header_profile == {"office_id": "OFF", "X-Flag": "active"}


def test_header_rows_can_be_removed(page, fake_core):
    s = section(page)
    s.headers.selectRow(1)
    s.remove_header_button.click()
    assert page.save()
    assert saved_officina(fake_core).header_profile == {"office_id": "OFF"}


# -- the folder -------------------------------------------------------------------

def test_a_onedrive_folder_warns_without_blocking(page, fake_core, tmp_path, monkeypatch):
    onedrive = tmp_path / "OneDrive - Esempio"
    monkeypatch.setenv("OneDrive", str(onedrive))
    s = section(page)
    s.folder.setText(str(onedrive / "officina"))
    assert s.folder_warning.isVisibleTo(s)
    assert "OneDrive" in s.folder_warning.text()
    assert page.save_button.isEnabled()
    assert page.save()
    assert saved_officina(fake_core).root == onedrive / "officina"


def test_a_local_folder_has_no_warning(page, tmp_path, monkeypatch):
    for var in ("OneDrive", "OneDriveCommercial", "OneDriveConsumer"):
        monkeypatch.delenv(var, raising=False)
    s = section(page)
    s.folder.setText(str(tmp_path / "locale"))
    assert not s.folder_warning.isVisibleTo(s)


def test_a_network_folder_warns(page):
    s = section(page)
    s.folder.setText(r"\\server.example.invalid\condivisa\officina")
    assert s.folder_warning.isVisibleTo(s)
    assert "rete" in s.folder_warning.text()


def test_a_folder_inside_the_logs_is_reported_inline_on_save(page, fake_core):
    s = section(page)
    s.folder.setText(str(fake_core.config.config.mirror_root / "officina"))
    assert page.save() is False
    assert s.folder_problem.isVisibleTo(s)
    assert "log" in s.folder_problem.text()


def _busy(runner) -> threading.Event:
    release = threading.Event()
    job = runner.submit(OFFICINA_GENERATE_JOBS[0], lambda: release.wait(10))
    assert job is not None
    return release


def test_the_folder_cannot_change_while_officina_is_generating(page, fake_core, runner, qtbot,
                                                             tmp_path):
    s = section(page)
    release = _busy(runner)
    try:
        s.folder.setText(str(tmp_path / "nuova"))
        before = list(fake_core.config.saved)
        assert page.save() is False
        assert fake_core.config.saved == before
        assert strings.SETTINGS_OFFICINA_BUSY in s.folder_problem.text()
        assert strings.SETTINGS_OFFICINA_BUSY in page.errors_label.text()
    finally:
        release.set()
    qtbot.waitUntil(lambda: not runner.is_running(OFFICINA_GENERATE_JOBS[0]), timeout=5000)
    assert page.save() is True
    assert saved_officina(fake_core).root == tmp_path / "nuova"


def test_other_officina_settings_can_be_saved_while_generating(page, fake_core, runner, qtbot):
    release = _busy(runner)
    try:
        section(page).timeout.setValue(60)
        assert page.save() is True
        assert saved_officina(fake_core).timeout_s == 60
    finally:
        release.set()
    qtbot.waitUntil(lambda: not runner.is_running(OFFICINA_GENERATE_JOBS[0]), timeout=5000)


# -- live update of the Officina tab ----------------------------------------------------

def test_the_officina_tab_follows_a_save_without_a_restart(qtbot, fake_core, runner, tmp_path):
    win = MainWindow(fake_core, runner)
    qtbot.addWidget(win)
    win.show()
    win.show_page("officina")
    officina = win.page("officina")
    assert officina.view() in ("list", "chooser")

    settings = win.page("settings")
    win.show_page("settings")
    s = settings.officina_section
    new_root = tmp_path / "nuova-officina"
    s.folder.setText(str(new_root))
    row = s.generators.add_row()
    set_cell(s.generators, row, s.generators.COL_NAME, "coll")
    set_cell(s.generators, row, s.generators.COL_URL, COLL.url)
    s.default_combo.setCurrentText("coll")
    assert settings.save()

    assert fake_core.officina.workspace_root() == new_root
    assert str(new_root) in officina.list.root_label.text()
    ini = fake_core.officina.create_initiative("Iniziativa di prova")
    payload = tmp_path / "payload.json"
    payload.write_text('{"documents": []}', encoding="utf-8")
    case = fake_core.officina.case_from_file(ini, payload, "MOD_TEST_LIVE")
    assert case.env == "coll"  # the new default generator, at once


def test_section_widgets_are_tables_of_the_right_kind(page):
    assert isinstance(section(page).generators, GeneratorTable)
    assert isinstance(section(page).headers, HeaderTable)
    assert page.section_widgets["officina"].isAncestorOf(section(page).generators)


def test_the_folder_field_is_the_shared_path_field(page):
    from qtrequestory.ui.pages.settings_widgets import PathField

    assert isinstance(section(page).folder, PathField)


def test_problem_rows_repaint_on_a_theme_switch(themed, page):
    from qtrequestory.ui import theme

    s = section(page)
    row = s.generators.add_row()
    set_cell(s.generators, row, s.generators.COL_NAME, "PROD")
    theme.apply(themed, theme.Mode.LIGHT)
    light = s.generators.item(row, s.generators.COL_PROBLEM).foreground().color().name()
    theme.apply(themed, theme.Mode.DARK)
    dark = s.generators.item(row, s.generators.COL_PROBLEM).foreground().color().name()
    assert light.lower() == theme.LIGHT.bad.lower() and dark.lower() == theme.DARK.bad.lower()



def test_a_blocked_save_looks_disabled_in_the_bar():
    """The bar's own primary rule must not paint a disabled Salva as clickable."""
    from qtrequestory.ui import theme

    qss = theme.build_qss(theme.LIGHT)
    assert 'QFrame#settingsSaveBar QPushButton[role="primary"]:disabled' in qss


# -- fix round 1 -------------------------------------------------------------------

def _hand_edited_prod(fake_core) -> None:
    fake_core.config.config.officina = dataclasses.replace(
        fake_core.config.config.officina,
        generators=[SVIL, GeneratorEndpoint("PROD", "https://example.invalid/p")])


def test_a_preference_only_save_passes_with_a_prod_row_present(qtbot, fake_core, runner):
    from qtrequestory.ui.pages.settings_presenter import load_prefs

    _hand_edited_prod(fake_core)
    widget = SettingsPage(fake_core, runner, StubWindow())
    qtbot.addWidget(widget)
    widget.show_section("search")
    assert widget.officina_section.problems()  # the hand-edited row is reported inline
    widget.set_key_mode("contains")
    assert widget.save_button.isEnabled()
    assert widget.save_blocked_label.isHidden() and widget.show_officina_button.isHidden()
    assert widget.save() is True
    assert load_prefs().key_mode == "contains"


def test_a_block_from_another_section_says_why_and_links_to_officina(qtbot, fake_core, runner):
    _hand_edited_prod(fake_core)
    widget = SettingsPage(fake_core, runner, StubWindow())
    qtbot.addWidget(widget)
    widget.show_section("search")
    widget.set_window_days(7)  # a config edit: the PROD row now blocks
    assert not widget.save_button.isEnabled()
    assert not widget.save_blocked_label.isHidden()
    assert strings.SETTINGS_OFFICINA_FIX_ROWS in widget.save_blocked_label.text()
    assert strings.SETTINGS_OFFICINA_FIX_ROWS in widget.save_button.toolTip()
    assert not widget.show_officina_button.isHidden()
    widget.show_officina_button.click()
    assert widget.current_section() == "officina"
    widget.officina_section.generators.remove_rows([1])
    assert widget.save_button.isEnabled()
    assert widget.save_blocked_label.isHidden() and widget.save_button.toolTip() == ""


class WindowWithOfficina(StubWindow):
    def __init__(self, writing: bool) -> None:
        super().__init__()
        self.officina = type("P", (), {"is_writing": lambda _self: writing})()

    def page(self, key: str):
        return self.officina if key == "officina" else None


def test_the_officina_page_hook_is_asked_about_pending_cases(qtbot, fake_core, runner, tmp_path):
    widget = SettingsPage(fake_core, runner, WindowWithOfficina(writing=True))
    qtbot.addWidget(widget)
    widget.officina_section.folder.setText(str(tmp_path / "nuova"))
    assert not runner.is_running(OFFICINA_GENERATE_JOBS[0])
    assert widget.save() is False
    assert strings.SETTINGS_OFFICINA_BUSY in widget.officina_section.folder_problem.text()


def test_a_running_delivery_refuses_a_new_folder(page, fake_core, runner, qtbot, tmp_path):
    from qtrequestory.ui.workers import OFFICINA_DELIVERY_JOB

    release = threading.Event()
    assert runner.submit(OFFICINA_DELIVERY_JOB, lambda: release.wait(10)) is not None
    try:
        section(page).folder.setText(str(tmp_path / "nuova"))
        assert page.save() is False
    finally:
        release.set()
    qtbot.waitUntil(lambda: not runner.is_running(OFFICINA_DELIVERY_JOB), timeout=5000)


def test_an_out_of_range_timeout_does_not_open_the_form_dirty(qtbot, fake_core, runner):
    fake_core.config.config.officina = dataclasses.replace(fake_core.config.config.officina,
                                                           timeout_s=0)
    widget = SettingsPage(fake_core, runner, StubWindow())
    qtbot.addWidget(widget)
    assert widget.officina_section.timeout.value() == OFFICINA_TIMEOUT_RANGE[0]
    assert not widget.is_dirty()


def test_re_enabling_the_default_row_restores_it(page):
    s = section(page)
    set_enabled(s.generators, 0, False)
    assert s.default_problem.isVisibleTo(s)
    set_enabled(s.generators, 0, True)
    assert s.default_combo.currentText() == "svil"
    assert not s.default_problem.isVisibleTo(s)
    assert s.values().default_generator == "svil"
    assert page.save_button.isEnabled() is False  # back to the saved form: nothing to save
    assert not page.is_dirty()


def test_shown_url_masks_the_whole_query():
    from qtrequestory.ui.pages.settings_officina_tables import shown_url

    assert shown_url("https://example.invalid/g?sv=1&sig=SEGRETO") == "https://example.invalid/g?***"
    assert shown_url("https://utente:pw@example.invalid/g#x") == "https://example.invalid/g?***"
    assert shown_url("https://example.invalid/g") == "https://example.invalid/g"
    assert "SEGRETO" not in shown_url("non un url?sig=SEGRETO")
