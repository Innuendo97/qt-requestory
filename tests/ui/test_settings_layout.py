"""Impostazioni: sections, the live theme selector, the unsaved-changes bar.

The form rules (what is saved, when, and validation) are in
``test_settings_page.py``; this file is about how the page is organised and
the two things that happen *outside* the Save flow: the theme, applied the
moment it is picked, and the question asked when leaving a dirty form.

Dialogs are monkeypatched, never opened: a modal in a test suite is a hang.
"""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox, QScrollArea

from qtrequestory.ui import prefs, strings, theme
from qtrequestory.ui.actions import user_settings
from qtrequestory.ui.pages.settings_page import SECTION_KEYS, SettingsPage
from qtrequestory.ui.pages.settings_widgets import ElidedLabel, PathField
from qtrequestory.ui.theme import DARK, LIGHT, Mode


class StubWindow:
    def __init__(self) -> None:
        self.status: list[str] = []
        self.toasts: list[str] = []

    def set_status(self, text: str, ms: int = 4000) -> None:
        self.status.append(text)

    def show_toast(self, text: str, tone: str = "neutral", ms: int = 0) -> None:
        self.toasts.append(text)


@pytest.fixture
def page(qtbot, fake_core, runner):
    widget = SettingsPage(fake_core, runner, StubWindow())
    qtbot.addWidget(widget)
    return widget


def _answer_leave(monkeypatch, label: str) -> list[QMessageBox]:
    """Make the leave question answer the button labelled ``label``."""
    asked: list[QMessageBox] = []

    def exec_(box: QMessageBox) -> int:
        asked.append(box)
        box._answer = next(b for b in box.buttons() if b.text() == label)
        return 0

    monkeypatch.setattr(QMessageBox, "exec", exec_)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda box: box._answer)
    return asked


# -- sections ----------------------------------------------------------------

def test_the_sections_are_listed_in_order_with_aspetto_first(page):
    assert SECTION_KEYS == (
        "appearance", "archive", "environments", "automation", "search", "editor", "advanced",
    )
    labels = [page.nav.item(i).text() for i in range(page.nav.count())]
    assert labels == [
        "Aspetto", "Archivio", "Ambienti", "Sincronizzazione automatica", "Ricerca",
        "Editor esterno", "Avanzate",
    ]
    assert page.current_section() == "appearance", "the theme selector is the first thing seen"


def test_show_section_switches_the_list_and_the_stack(page):
    page.show_section("automation")
    assert page.current_section() == "automation"
    assert page.nav.currentRow() == SECTION_KEYS.index("automation")
    assert page.sections.currentWidget() is page.section_widgets["automation"]
    assert page.section_widgets["automation"].isAncestorOf(page.schedule_start)


def test_show_section_ignores_an_unknown_key(page):
    page.show_section("archive")
    page.show_section("nonesiste")
    assert page.current_section() == "archive"


def test_clicking_a_section_in_the_list_shows_it(page):
    page.nav.setCurrentRow(SECTION_KEYS.index("editor"))
    assert page.current_section() == "editor"


@pytest.mark.parametrize("key, widget", [
    ("appearance", "group_by_fdi"),
    ("archive", "mirror_path"),
    ("archive", "rebuild_button"),
    ("environments", "env_table"),
    ("search", "window_buttons"),
    ("editor", "editor_path"),
    ("advanced", "wizard_button"),
])
def test_each_setting_lives_in_its_section(page, key, widget):
    found = getattr(page, widget)
    if isinstance(found, dict):
        found = next(iter(found.values()))
    assert page.section_widgets[key].isAncestorOf(found)


def test_the_sections_scroll_and_nothing_is_clipped_on_a_small_screen(qtbot, page):
    """1366x768: the page gets roughly 420 px of height. The sections scroll;
    the save bar sits outside the scroll area so it can never be scrolled away."""
    page.resize(1000, 420)
    page.show()
    qtbot.waitExposed(page)
    page.set_window_days(7)  # dirty: the bar appears

    scroll = page.findChild(QScrollArea)
    assert scroll.widget().isAncestorOf(page.sections)
    assert not scroll.widget().isAncestorOf(page.save_button)
    assert page.minimumSizeHint().height() <= 420
    assert page.save_bar.isVisible()
    assert page.save_bar.geometry().bottom() <= page.height()


def test_a_short_section_does_not_inherit_the_height_of_the_tallest(qtbot, page):
    page.resize(1000, 600)
    page.show()
    qtbot.waitExposed(page)
    page.show_section("environments")
    tall = page.sections.sizeHint().height()
    page.show_section("editor")
    assert page.sections.sizeHint().height() < tall


def test_the_title_is_inset_like_the_other_pages(page):
    """Sincronizzazione uses 16 px margins; Impostazioni used Qt's default 11."""
    margins = page.layout().contentsMargins()
    assert (margins.left(), margins.top()) == (16, 16)


# -- Aspetto: the theme ------------------------------------------------------

def test_the_theme_selector_shows_the_saved_mode(qtbot, fake_core, runner):
    theme.save_mode(Mode.LIGHT)
    widget = SettingsPage(fake_core, runner, StubWindow())
    qtbot.addWidget(widget)
    assert [m for m, b in widget.theme_buttons.items() if b.isChecked()] == [Mode.LIGHT]
    assert [b.text() for b in widget.theme_buttons.values()] == ["Sistema", "Chiaro", "Scuro"]


def test_picking_scuro_applies_the_dark_theme_at_once(themed, page):
    page.theme_buttons[Mode.DARK].click()

    assert theme.saved_mode() is Mode.DARK
    assert QApplication.instance().palette().window().color().name() == DARK.bg.lower()
    assert not page.is_dirty(), "the theme is outside the Save flow"
    assert page.save_bar.isHidden()

    page.theme_buttons[Mode.LIGHT].click()
    assert theme.saved_mode() is Mode.LIGHT
    assert QApplication.instance().palette().window().color().name() == LIGHT.bg.lower()


def test_the_theme_note_says_it_applies_immediately(page):
    assert page.theme_note.text() == strings.SETTINGS_THEME_NOTE
    assert page.theme_note.property("role") == "muted"


# -- Aspetto / Ricerca: the search preferences ------------------------------

def test_the_search_preferences_default_to_grouped_and_exact(page):
    assert page.group_by_fdi.isChecked() is True
    assert page.key_mode() == "exact"
    assert page.key_mode_buttons["exact"].isChecked()


def test_the_search_preferences_are_saved_with_the_form(page):
    page.group_by_fdi.setChecked(False)
    page.set_key_mode("contains")
    assert page.is_dirty()

    page.save_button.click()

    stored = user_settings()
    assert stored.value(prefs.GROUP_BY_FDI_KEY, type=bool) is False
    assert stored.value(prefs.KEY_MODE_KEY) == "contains"
    assert not page.is_dirty()


def test_stored_search_preferences_are_loaded(qtbot, fake_core, runner):
    user_settings().setValue(prefs.GROUP_BY_FDI_KEY, False)
    user_settings().setValue(prefs.KEY_MODE_KEY, "contains")
    widget = SettingsPage(fake_core, runner, StubWindow())
    qtbot.addWidget(widget)
    assert widget.group_by_fdi.isChecked() is False
    assert widget.key_mode() == "contains"
    assert not widget.is_dirty()


def test_a_preference_only_change_does_not_rewrite_the_configuration(page, fake_core):
    page.group_by_fdi.setChecked(False)
    page.save_button.click()
    assert fake_core.config.saved == []


def test_the_period_labels_match_ricerca(page):
    assert [b.text() for b in page.window_buttons.values()] == ["7 gg", "30 gg", "90 gg"]


# -- paths -------------------------------------------------------------------

def test_paths_are_elided_in_the_middle_with_the_full_path_as_tooltip(qtbot, page, tmp_path):
    long_path = str(tmp_path / ("cartella-molto-lunga-" * 6) / "log")
    page.mirror_path.setText(long_path)
    page.mirror_path.resize(260, 30)
    page.show()
    qtbot.waitExposed(page)
    page.show_section("archive")
    label = page.mirror_path.label
    label.resize(160, label.height())

    assert isinstance(page.mirror_path, PathField)
    assert isinstance(label, ElidedLabel)
    assert label.full_text() == long_path
    assert label.toolTip() == long_path
    assert "…" in label.text()
    assert label.text().endswith("log"), "the end of a path is the informative part"


def test_an_empty_output_folder_shows_the_system_default(page):
    page.output_path.setText("")
    assert page.output_path.label.full_text() == ""
    assert strings.SETTINGS_OUTPUT_DEFAULT in page.output_path.label.text()


def test_usa_predefinita_clears_the_output_folder(page, tmp_path):
    page.output_path.setText(str(tmp_path))
    page.output_default_button.click()
    assert page.output_path.text() == ""


# -- the unsaved-changes bar -------------------------------------------------

def test_the_bar_is_hidden_until_something_changes(page):
    assert page.save_bar.isHidden()
    page.set_window_days(90)
    assert not page.save_bar.isHidden()
    assert page.save_bar_label.text() == strings.SETTINGS_UNSAVED
    page.cancel_button.click()
    assert page.save_bar.isHidden()


def test_saving_hides_the_bar(page, fake_core):
    page.set_window_days(90)
    page.save_button.click()
    assert fake_core.config.saved
    assert page.save_bar.isHidden()


def test_salva_is_the_primary_button_of_the_bar(page):
    assert page.save_button.property("role") == "primary"
    assert page.save_bar.isAncestorOf(page.cancel_button)


# -- leaving a dirty page ----------------------------------------------------

def test_a_clean_page_can_be_left_without_a_question(page, monkeypatch):
    asked = _answer_leave(monkeypatch, strings.BTN_CANCEL)
    assert page.can_leave() is True
    assert asked == []


def test_annulla_keeps_the_user_on_the_dirty_page(page, monkeypatch, fake_core):
    asked = _answer_leave(monkeypatch, strings.BTN_CANCEL)
    page.set_window_days(90)

    assert page.can_leave() is False
    assert asked and asked[0].text() == strings.SETTINGS_LEAVE_QUESTION
    assert page.is_dirty(), "nothing was thrown away"
    assert fake_core.config.saved == []


def test_scarta_throws_the_edits_away(page, monkeypatch, fake_core):
    _answer_leave(monkeypatch, strings.SETTINGS_LEAVE_DISCARD)
    page.set_window_days(90)

    assert page.can_leave() is True
    assert not page.is_dirty()
    assert fake_core.config.saved == []


def test_salva_saves_then_leaves(page, monkeypatch, fake_core):
    _answer_leave(monkeypatch, strings.SETTINGS_LEAVE_SAVE)
    page.set_window_days(90)

    assert page.can_leave() is True
    assert fake_core.config.saved[-1].default_window_days == 90


def test_salva_with_errors_stays(page, monkeypatch, fake_core):
    _answer_leave(monkeypatch, strings.SETTINGS_LEAVE_SAVE)
    page.mirror_path.setText("")

    assert page.can_leave() is False
    assert fake_core.config.saved == []
    assert not page.errors_label.isHidden()


def test_the_window_asks_before_leaving_a_dirty_settings_page(qtbot, fake_core, runner, monkeypatch):
    from qtrequestory.ui.main_window import MainWindow

    window = MainWindow(fake_core, runner)
    qtbot.addWidget(window)
    window.show_page("settings")
    settings = window.page("settings")
    settings.set_window_days(90)

    _answer_leave(monkeypatch, strings.BTN_CANCEL)
    window.show_page("search")
    assert window.current_page_key() == "settings"
    bar = {**window.app_bar.tabs, **window.app_bar.icon_buttons}
    assert [k for k, b in bar.items() if b.isChecked()] == ["settings"], "the bar is put back"

    _answer_leave(monkeypatch, strings.SETTINGS_LEAVE_DISCARD)
    window.show_page("search")
    assert window.current_page_key() == "search"
    assert not settings.is_dirty()


def test_start_sync_does_not_run_when_the_page_refuses_to_leave(qtbot, fake_core, runner, monkeypatch):
    from qtrequestory.ui.main_window import MainWindow

    window = MainWindow(fake_core, runner)
    qtbot.addWidget(window)
    window.show_page("settings")
    window.page("settings").set_window_days(90)
    started: list[bool] = []
    monkeypatch.setattr(window.page("sync"), "start_sync", lambda *a, **k: started.append(True))
    _answer_leave(monkeypatch, strings.BTN_CANCEL)

    window.start_sync()

    assert started == []
    assert window.current_page_key() == "settings"


# -- the schedule re-registration banner -------------------------------------

def test_a_failed_re_registration_shows_a_banner_with_riprova(page, fake_core, qtbot):
    from qtrequestory.ui.contracts import SchedulerError

    fake_core.scheduler.set_status(registered=True, exe_matches=True)
    calls: list[int] = []

    def boom() -> None:
        calls.append(1)
        raise SchedulerError("schtasks: accesso negato")

    fake_core.scheduler.register = boom
    page.schedule_every.setValue(3)
    page.save_button.click()

    qtbot.waitUntil(lambda: not page.schedule_banner.isHidden(), timeout=5000)
    assert "accesso negato" in page.schedule_banner_label.text()
    assert page.schedule_banner_label.text().startswith(
        strings.SETTINGS_SCHEDULE_UPDATE_FAILED.split("{")[0])
    assert page.section_widgets["automation"].isAncestorOf(page.schedule_banner)

    fake_core.scheduler.register = lambda: calls.append(2)
    page.schedule_retry_button.click()
    qtbot.waitUntil(lambda: calls == [1, 2], timeout=5000)
    qtbot.wait(100)
    assert page.schedule_banner.isHidden(), "a successful retry clears the banner"


def test_a_refused_re_registration_is_not_dropped_silently(page, fake_core, runner, qtbot):
    """The Sincronizzazione page may be driving schtasks at that very moment:
    the runner refuses the second job, and the user must hear about it."""
    import threading

    from qtrequestory.ui.workers import SCHEDULER_JOB

    fake_core.scheduler.set_status(registered=True, exe_matches=True)
    gate = threading.Event()
    busy = runner.submit(SCHEDULER_JOB, lambda: gate.wait(5.0))
    try:
        page.schedule_every.setValue(3)
        page.save_button.click()
        assert not page.schedule_banner.isHidden()
        assert strings.SETTINGS_SCHEDULE_BUSY in page.schedule_banner_label.text()
    finally:
        gate.set()
    with qtbot.waitSignal(busy.signals.finished, timeout=5000):
        pass


# -- the looks the page relies on -------------------------------------------

@pytest.mark.parametrize("tokens", [LIGHT, DARK], ids=["light", "dark"])
def test_the_stylesheet_styles_the_settings_widgets(tokens):
    qss = theme.build_qss(tokens)
    for needle in ("QListWidget#settingsNav::item:selected", "QLabel#pathField",
                   'QLabel#pathField[empty="true"]', "QFrame#settingsSaveBar",
                   "QFrame#settingsBanner"):
        assert needle in qss, needle
    save_bar = qss[qss.index("QFrame#settingsSaveBar {"):]
    assert f"background: {tokens.text}" in save_bar.split("}")[0], "inverted colours"


def test_the_widgets_carry_the_names_the_stylesheet_uses(page):
    assert page.nav.objectName() == "settingsNav"
    assert page.save_bar.objectName() == "settingsSaveBar"
    assert page.schedule_banner.objectName() == "settingsBanner"
    assert page.mirror_path.label.objectName() == "pathField"


# -- re-running the wizard from a dirty form ---------------------------------

def _window_with_fake_wizard(qtbot, fake_core, runner, monkeypatch, tmp_path, *, start_sync=True):
    """A real MainWindow whose wizard writes a new configuration and asks for a sync."""
    import dataclasses

    from qtrequestory.ui import app as app_module
    from qtrequestory.ui.main_window import MainWindow
    from qtrequestory.ui.wizard import WizardResult

    window = MainWindow(fake_core, runner)
    qtbot.addWidget(window)
    wizard_cfg = dataclasses.replace(fake_core.config.load(), mirror_root=tmp_path / "dal-wizard",
                                     default_window_days=7)
    opened: list[bool] = []

    def wizard(*_args, **_kwargs):
        opened.append(True)
        fake_core.config.save(wizard_cfg)
        return WizardResult(config=wizard_cfg, start_sync=start_sync, autosync=True)

    monkeypatch.setattr(app_module, "wizard_available", lambda: True)
    monkeypatch.setattr(app_module, "show_first_run_wizard", wizard)
    syncs: list[bool] = []
    monkeypatch.setattr(window.page("sync"), "start_sync", lambda *a, **k: syncs.append(True))
    window.show_page("settings")
    return window, wizard_cfg, opened, syncs


@pytest.mark.parametrize("answer", ["discard", "save"])
def test_a_dirty_form_is_resolved_before_the_wizard_and_never_overwrites_it(
        qtbot, fake_core, runner, monkeypatch, tmp_path, answer):
    """The wizard writes config.json and then asks for a sync, which switches
    page: a still-dirty form would pop "Salvare le modifiche?" and, on Salva,
    write its stale values over what the wizard just saved."""
    window, wizard_cfg, opened, syncs = _window_with_fake_wizard(
        qtbot, fake_core, runner, monkeypatch, tmp_path)
    page = window.page("settings")
    page.set_window_days(90)
    label = strings.SETTINGS_LEAVE_SAVE if answer == "save" else strings.SETTINGS_LEAVE_DISCARD
    asked = _answer_leave(monkeypatch, label)

    page.wizard_button.click()

    assert len(asked) == 1, "asked once, before the wizard; never again after it"
    assert opened == [True]
    assert fake_core.config.load() == wizard_cfg, "config.json holds the wizard's values"
    assert fake_core.config.saved[-1] == wizard_cfg
    assert page.mirror_path.text() == str(wizard_cfg.mirror_root), "the form shows them"
    assert page.window_days() == 7
    assert not page.is_dirty()
    assert window.current_page_key() == "sync" and syncs == [True]


def test_annulla_before_the_wizard_does_not_open_it(qtbot, fake_core, runner, monkeypatch, tmp_path):
    window, _cfg, opened, _syncs = _window_with_fake_wizard(
        qtbot, fake_core, runner, monkeypatch, tmp_path)
    page = window.page("settings")
    page.set_window_days(90)
    _answer_leave(monkeypatch, strings.BTN_CANCEL)

    page.wizard_button.click()

    assert opened == []
    assert page.is_dirty() and page.window_days() == 90, "the edits are still there"
    assert window.current_page_key() == "settings"


def test_a_clean_form_opens_the_wizard_without_asking(qtbot, fake_core, runner, monkeypatch, tmp_path):
    window, wizard_cfg, opened, _syncs = _window_with_fake_wizard(
        qtbot, fake_core, runner, monkeypatch, tmp_path, start_sync=False)
    page = window.page("settings")
    asked = _answer_leave(monkeypatch, strings.BTN_CANCEL)

    page.wizard_button.click()

    assert asked == [] and opened == [True]
    assert page.mirror_path.text() == str(wizard_cfg.mirror_root)
    assert window.current_page_key() == "settings"
