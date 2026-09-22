"""The Ricerca page: form, search, table, empty states, context menu.

Everything runs against the in-memory core (``fake_core``) and the real
:class:`JobRunner`, so a search really crosses a worker thread and comes back
through a queued signal — which is the part a hand-rolled stub would hide.

Two habits keep these tests deterministic:

* the day window is always set explicitly (``set_custom_range``) before a search
  that must find rows, because the fake's hits are on fixed days and a preset is
  relative to *today*;
* keyboard shortcuts are exercised through ``page.shortcuts[...]`` and mouse
  menus through :meth:`SearchPage.build_context_menu`, never by popping a real
  menu up, which cannot be driven offscreen.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget

from qtrequestory.ui import strings
from qtrequestory.ui.pages.search_page import SearchPage
from qtrequestory.ui.pages.search_paste import parse_pasted_entry
from qtrequestory.ui.results_model import ResultsModel

from tests.conftest import FDI_A, FDI_B, KEY_EMAIL, KEY_SINT
from tests.fakes.fake_core import DAYS

#: A window that contains every day the fake core knows about.
WIDE_FROM = min(DAYS) - timedelta(days=1)
WIDE_TO = max(DAYS) + timedelta(days=1)


class FakeWindow:
    """What the page uses of ``MainWindow``: two methods, both recorded."""

    def __init__(self) -> None:
        self.shown: list[str] = []
        self.statuses: list[str] = []

    def show_page(self, key: str) -> None:
        self.shown.append(key)

    def set_status(self, text: str, ms: int = 4000) -> None:
        self.statuses.append(text)


class FakePane(QWidget):
    """Stand-in for Task 13's preview pane: the four methods the page calls."""

    def __init__(self) -> None:
        super().__init__()
        self.hits: list[object] = []
        self.calls: list[str] = []

    def set_hit(self, hit) -> None:
        self.hits.append(hit)

    def open_in_editor(self) -> None:
        self.calls.append("open")

    def save_as(self) -> None:
        self.calls.append("save")

    def copy_body(self) -> None:
        self.calls.append("copy")


@pytest.fixture
def window() -> FakeWindow:
    return FakeWindow()


@pytest.fixture
def make_page(qtbot, fake_core, runner, window):
    """Build the page *after* the test has set the fake core's knobs."""

    def build() -> SearchPage:
        page = SearchPage(fake_core, runner, window)
        qtbot.addWidget(page)
        page.show()
        return page

    return build


@pytest.fixture
def page(make_page) -> SearchPage:
    return make_page()


def search(qtbot, page: SearchPage, *, fdi: str = "", key: str = "",
           day_from: date = WIDE_FROM, day_to: date = WIDE_TO) -> list:
    """Fill the form, run the search, wait for the results, return the hits."""
    page.form.set_fdi(fdi)
    page.form.set_template_key(key)
    page.form.set_custom_range(day_from, day_to)
    with qtbot.waitSignal(page.presenter.results_ready, timeout=5000):
        page.run_search()
    return page.model.hits()


def action(menu, text: str):
    for item in menu.actions():
        if item.text() == text:
            return item
    raise AssertionError(f"voce di menu assente: {text!r} in {[a.text() for a in menu.actions()]}")


# ------------------------------------------------------------ smart paste ---

@pytest.mark.parametrize(
    "text, expected",
    [
        (f"{FDI_A}_{KEY_SINT}_1a2b3c0200000031", (FDI_A, KEY_SINT)),
        (f"{FDI_A}_{KEY_SINT}_1a2b3c0200000031.json", (FDI_A, KEY_SINT)),
        (f"### {FDI_A}_{KEY_SINT}_1a2b3c0200000031.json", (FDI_A, KEY_SINT)),
        (f"  ### {FDI_A}_{KEY_SINT}_1a2b3c0200000031.json  \n", (FDI_A, KEY_SINT)),
        (f"{FDI_A.upper()}_{KEY_SINT}_1a2b3c0200000031", (FDI_A, KEY_SINT)),
        # A header line copied out of a daily file, body on the next line.
        (f"### {FDI_A}_{KEY_SINT}_1a2b3c0200000031.json\n{{\"documents\": []}}",
         (FDI_A, KEY_SINT)),
        # No FDI at all: the key is still worth filling in.
        ("correlationId_vuoto_2_DECLARATION_CONS_PAPER_RP_1a2b3c0200000031",
         (None, "2_DECLARATION_CONS_PAPER_RP")),
    ],
)
def test_parse_pasted_entry_recognises_an_entry_name(text, expected):
    assert parse_pasted_entry(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        FDI_A,                                    # a bare FDI is an ordinary paste
        f"{FDI_A}_{KEY_SINT}",                    # no call id: not an entry name
        "MOD_TEST_EMAIL_GAS",                   # a bare template key
        "Ciao, mi mandi il log di ieri?",         # free text with spaces
        f"{FDI_A} {KEY_SINT} 1a2b3c0200000031",   # spaces instead of underscores
    ],
)
def test_parse_pasted_entry_leaves_anything_else_alone(text):
    assert parse_pasted_entry(text) is None


def test_pasting_an_entry_name_into_the_fdi_field_fills_both_fields(qtbot, page):
    QGuiApplication.clipboard().setText(f"### {FDI_B}_{KEY_EMAIL}_1a2b3c0100000012.json")
    page.form.fdi_edit.setFocus()
    qtbot.keyClick(page.form.fdi_edit, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    assert page.form.fdi() == FDI_B
    assert page.form.template_key() == KEY_EMAIL
    assert page.form.can_search()


def test_pasting_anything_else_behaves_like_an_ordinary_paste(qtbot, page):
    QGuiApplication.clipboard().setText(FDI_B)
    page.form.fdi_edit.setFocus()
    qtbot.keyClick(page.form.fdi_edit, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    assert page.form.fdi() == FDI_B
    assert page.form.template_key() == ""


# ------------------------------------------------------------------- form ---

def test_the_form_offers_the_enabled_environments_and_the_default_period(page, fake_core):
    cfg = fake_core.config.load()
    assert page.form.environments() == [e.name for e in cfg.enabled_environments()]
    assert page.form.current_env() == cfg.enabled_environments()[0].name
    assert page.form.preset_days() == cfg.default_window_days


@pytest.mark.parametrize("days", [7, 30, 90])
def test_a_preset_sets_a_window_of_that_many_days_ending_today(page, days):
    page.form.set_preset(days)
    day_from, day_to = page.form.day_range()
    assert day_to == date.today()
    assert (day_to - day_from).days + 1 == days
    assert page.form.window_days() == days
    assert not page.form.date_from.isVisible(), "the date editors belong to «Personalizzato»"


def test_personalizzato_reveals_the_two_date_editors(page):
    page.form.set_custom_range(date(2026, 9, 1), date(2026, 9, 30))
    assert page.form.preset_days() is None
    assert page.form.date_from.isVisible() and page.form.date_to.isVisible()
    assert page.form.day_range() == (date(2026, 9, 1), date(2026, 9, 30))
    assert page.form.window_days() == 30


def test_cerca_stays_disabled_until_a_filter_is_typed(page):
    assert not page.form.search_button.isEnabled()
    assert page.form.search_button.toolTip() == strings.SEARCH_BTN_DISABLED_TOOLTIP
    page.form.set_fdi("aaaa")
    assert page.form.search_button.isEnabled()
    page.form.set_fdi("")
    assert not page.form.search_button.isEnabled()
    page.form.set_template_key(KEY_SINT)
    assert page.form.search_button.isEnabled()


def test_the_fdi_field_only_accepts_hexadecimal_and_dashes(page):
    page.form.fdi_edit.setText("")
    QGuiApplication.processEvents()
    for char in "abz-12/":
        page.form.fdi_edit.insert(char)
    assert page.form.fdi() == "ab-12"


def test_enter_in_the_form_runs_the_search(qtbot, page):
    page.form.set_fdi("aaaa")
    page.form.set_custom_range(WIDE_FROM, WIDE_TO)
    with qtbot.waitSignal(page.presenter.results_ready, timeout=5000):
        qtbot.keyClick(page.form.fdi_edit, Qt.Key.Key_Return)
    assert page.model.rowCount() > 0


def test_escape_clears_the_focused_field(qtbot, page):
    page.form.set_fdi("aaaa")
    page.form.set_template_key(KEY_SINT)
    page.form.fdi_edit.setFocus()
    qtbot.keyClick(page.form.fdi_edit, Qt.Key.Key_Escape)
    assert page.form.fdi() == ""
    assert page.form.template_key() == KEY_SINT, "only the focused field is cleared"


def test_the_template_keys_come_from_the_index_and_reload_on_an_environment_change(qtbot, page):
    qtbot.waitUntil(lambda: page.form.template_keys() != [], timeout=5000)
    assert set(page.form.template_keys()) == {KEY_SINT, KEY_EMAIL, "CTR_PLAN_FIX_GAS"}
    page.form.set_env("svil")
    qtbot.waitUntil(lambda: page.form.template_keys() == [], timeout=5000)


def test_changing_environment_drops_the_rows_of_the_previous_one(qtbot, page):
    pane = FakePane()
    page.set_preview_widget(pane)
    search(qtbot, page, fdi=FDI_A)
    page.form.set_env("svil")
    assert page.model.rowCount() == 0
    assert page.summary_label.text() == ""
    qtbot.waitUntil(lambda: pane.hits[-1] is None, timeout=5000)


def test_saving_the_settings_refreshes_the_page_without_losing_the_results(qtbot, page,
                                                                          fake_core):
    hits = search(qtbot, page, fdi=FDI_A)
    page.on_config_changed(fake_core.config.load())
    assert page.model.hits() == hits
    assert page.form.current_env() == "coll"


def test_the_chosen_environment_is_remembered(qtbot, make_page):
    first = make_page()
    first.form.set_env("svil")
    second = make_page()
    assert second.form.current_env() == "svil"


# ----------------------------------------------------------------- search ---

def test_an_fdi_and_enter_fill_the_table_with_the_first_row_selected(qtbot, page):
    hits = search(qtbot, page, fdi=FDI_A)
    assert hits, "the fake core knows this FDI"
    assert page.model.rowCount() == len(hits)
    assert all(hit.fdi == FDI_A for hit in hits)
    assert page.table.selectionModel().selectedRows()[0].row() == 0
    assert page.selected_hit() is hits[0]
    assert page.current_state() == "table"


def test_the_rows_arrive_newest_first(qtbot, page):
    hits = search(qtbot, page, fdi=FDI_A)
    days = [hit.day for hit in hits]
    assert days == sorted(days, reverse=True)
    assert page.model.hit_at(0) is hits[0]


def test_the_summary_counts_calls_fdis_and_days(qtbot, page):
    hits = search(qtbot, page, key=KEY_SINT)
    text = page.summary_label.text()
    assert strings.SEARCH_SUMMARY_CALLS_MANY.format(n=len(hits)) in text
    assert strings.SEARCH_SUMMARY_FDIS_MANY.format(n=len({h.fdi for h in hits})) in text
    assert strings.SEARCH_SUMMARY_DAYS_MANY.format(n=len({h.day for h in hits})) in text
    assert text.endswith(strings.SEARCH_SUMMARY_TAIL)


def test_a_single_result_is_counted_in_the_singular(qtbot, page):
    hits = search(qtbot, page, fdi=FDI_A, key=KEY_EMAIL, day_from=DAYS[0], day_to=DAYS[0])
    assert len(hits) == 1
    assert strings.SEARCH_SUMMARY_CALLS_ONE in page.summary_label.text()
    assert strings.SEARCH_SUMMARY_DAYS_ONE in page.summary_label.text()


def test_the_coverage_line_names_the_first_and_the_last_indexed_day(page, fake_core):
    cov = fake_core.index.coverage("coll")
    assert page.coverage_label.text() == strings.SEARCH_COVERAGE.format(
        env="coll", first=f"{cov.first_day:%d/%m/%Y}", last=f"{cov.last_day:%d/%m/%Y}"
    )


def test_f5_repeats_the_last_search(qtbot, page):
    search(qtbot, page, fdi=FDI_A)
    page.model.set_hits([])
    with qtbot.waitSignal(page.presenter.results_ready, timeout=5000):
        page.shortcuts["F5"].activated.emit()
    assert page.model.rowCount() > 0


def test_ctrl_l_and_ctrl_k_focus_the_two_filters(page):
    page.shortcuts["Ctrl+L"].activated.emit()
    assert page.form.fdi_edit.hasFocus()
    page.shortcuts["Ctrl+K"].activated.emit()
    assert page.form.key_combo.lineEdit().hasFocus()


def test_a_failed_search_is_reported_and_leaves_the_table_alone(qtbot, page, window):
    def boom(_query):
        raise RuntimeError("database occupato")

    hits = search(qtbot, page, fdi=FDI_A)
    page.services.index.search = boom
    page.run_search()
    qtbot.waitUntil(lambda: any("database occupato" in t for t in window.statuses), timeout=5000)
    assert window.statuses[-1] == strings.SEARCH_FAILED.format(error="database occupato")
    assert page.model.hits() == hits, "a failed search does not wipe the previous result"


# ----------------------------------------------------------- empty states ---

def test_an_environment_without_local_logs_offers_the_sync_page(qtbot, page, window):
    page.form.set_env("svil")
    qtbot.waitUntil(lambda: page.current_state() == "no_log", timeout=5000)
    assert page.coverage_label.text() == strings.SEARCH_COVERAGE_NONE.format(env="svil")
    assert strings.SEARCH_EMPTY_NO_LOG_TITLE.format(env="svil") in page.empty_no_log.text()
    page.empty_no_log.button.click()
    assert window.shown == ["sync"]
    page.form.set_env("coll")
    assert page.current_state() == "table", "coming back must leave the empty state"


def test_no_results_explains_what_to_try_next(qtbot, page):
    search(qtbot, page, fdi="aaaa", day_from=date(2026, 1, 1), day_to=date(2026, 1, 31))
    assert page.model.rowCount() == 0
    assert page.current_state() == "no_results"
    assert page.summary_label.text() == ""
    text = page.empty_no_results.text()
    assert strings.SEARCH_EMPTY_NO_RESULTS_TITLE in text
    assert strings.SEARCH_EMPTY_HINT_SHORT_FDI in text, "an FDI of 4 characters is a prefix"
    assert strings.SEARCH_EMPTY_HINT_TODAY.format(file="20260131.txt") not in text
    assert page.empty_no_results.button.isVisible(), "31 days: widening to 90 is worth offering"


def test_a_window_ending_today_warns_that_today_s_calls_arrive_tomorrow(qtbot, page):
    today = date.today()
    search(qtbot, page, fdi="ffff", day_from=today - timedelta(days=6), day_to=today)
    assert page.current_state() == "no_results"
    expected = strings.SEARCH_EMPTY_HINT_TODAY.format(file=f"{today:%Y%m%d}.txt")
    assert expected in page.empty_no_results.text()


def test_a_full_fdi_over_ninety_days_gets_neither_hint_nor_button(qtbot, page):
    today = date.today()
    search(qtbot, page, fdi=FDI_B.replace("b", "f"),
           day_from=today - timedelta(days=200), day_to=today - timedelta(days=1))
    assert page.current_state() == "no_results"
    assert strings.SEARCH_EMPTY_HINT_SHORT_FDI not in page.empty_no_results.text()
    assert not page.empty_no_results.button.isVisible()


def test_widening_to_ninety_days_re_runs_the_search(qtbot, page):
    search(qtbot, page, fdi="aaaa", day_from=date(2026, 1, 1), day_to=date(2026, 1, 31))
    with qtbot.waitSignal(page.presenter.results_ready, timeout=5000):
        page.empty_no_results.button.click()
    assert page.form.preset_days() == 90


# --------------------------------------------------------- stale index ------

def test_pending_files_raise_the_stale_index_banner(qtbot, fake_core, make_page):
    fake_core.index.set_pending(3)
    page = make_page()
    qtbot.waitUntil(lambda: page.stale_banner.isVisible(), timeout=5000)
    assert page.stale_banner.text() == strings.SEARCH_STALE_BANNER.format(n=3)


def test_an_up_to_date_index_shows_no_banner(qtbot, page):
    qtbot.wait(100)
    assert not page.stale_banner.isVisible()


# --------------------------------------------------------- preview slot -----

def test_without_a_preview_pane_the_slot_shows_a_placeholder(page):
    assert page.preview_widget() is None
    assert page.preview_placeholder.isVisible()


def test_the_selected_hit_is_handed_to_the_preview_pane(qtbot, page):
    pane = FakePane()
    page.set_preview_widget(pane)
    assert page.preview_widget() is pane
    assert not page.preview_placeholder.isVisible()
    hits = search(qtbot, page, fdi=FDI_A)
    qtbot.waitUntil(lambda: pane.hits and pane.hits[-1] is hits[0], timeout=5000)


def test_clearing_the_results_tells_the_pane_there_is_nothing_to_show(qtbot, page):
    pane = FakePane()
    page.set_preview_widget(pane)
    search(qtbot, page, fdi=FDI_A)
    qtbot.waitUntil(lambda: bool(pane.hits), timeout=5000)
    search(qtbot, page, fdi="ffff")
    qtbot.waitUntil(lambda: pane.hits[-1] is None, timeout=5000)


def test_a_double_click_opens_the_row_in_the_editor(qtbot, page):
    pane = FakePane()
    page.set_preview_widget(pane)
    search(qtbot, page, fdi=FDI_A)
    page.table.doubleClicked.emit(page.table.model().index(0, 0))
    assert pane.calls == ["open"]


def test_enter_on_a_row_opens_it_in_the_editor(qtbot, page):
    pane = FakePane()
    page.set_preview_widget(pane)
    search(qtbot, page, fdi=FDI_A)
    page.table.setFocus()
    qtbot.keyClick(page.table, Qt.Key.Key_Return)
    assert pane.calls == ["open"]


# --------------------------------------------------------- context menu -----

def test_the_context_menu_lists_every_row_action(qtbot, page):
    hits = search(qtbot, page, fdi=FDI_A)
    menu = page.build_context_menu(hits[0])
    labels = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert labels == [
        strings.SEARCH_MENU_OPEN, strings.BTN_SAVE_AS, strings.SEARCH_MENU_COPY_JSON,
        strings.SEARCH_MENU_COPY_FDI, strings.SEARCH_MENU_COPY_KEY,
        strings.SEARCH_MENU_ONLY_FDI, strings.SEARCH_MENU_ONLY_KEY,
        strings.SEARCH_MENU_OPEN_DAY_FOLDER,
    ]
    menu.deleteLater()


def test_the_body_actions_are_disabled_without_a_preview_pane(qtbot, page):
    hits = search(qtbot, page, fdi=FDI_A)
    menu = page.build_context_menu(hits[0])
    for label in (strings.SEARCH_MENU_OPEN, strings.BTN_SAVE_AS, strings.SEARCH_MENU_COPY_JSON):
        assert not action(menu, label).isEnabled()
    assert action(menu, strings.SEARCH_MENU_COPY_FDI).isEnabled()
    menu.deleteLater()


@pytest.mark.parametrize(
    "label, expected",
    [
        (strings.SEARCH_MENU_OPEN, "open"),
        (strings.BTN_SAVE_AS, "save"),
        (strings.SEARCH_MENU_COPY_JSON, "copy"),
    ],
)
def test_the_body_actions_are_delegated_to_the_preview_pane(qtbot, page, label, expected):
    pane = FakePane()
    page.set_preview_widget(pane)
    hits = search(qtbot, page, fdi=FDI_A)
    menu = page.build_context_menu(hits[0])
    action(menu, label).trigger()
    assert pane.calls == [expected]
    menu.deleteLater()


def test_copying_the_fdi_and_the_key_puts_them_on_the_clipboard(qtbot, page, window):
    hits = search(qtbot, page, fdi=FDI_A)
    menu = page.build_context_menu(hits[0])
    action(menu, strings.SEARCH_MENU_COPY_FDI).trigger()
    assert QGuiApplication.clipboard().text() == FDI_A
    assert window.statuses[-1] == strings.SEARCH_STATUS_COPIED_FDI
    action(menu, strings.SEARCH_MENU_COPY_KEY).trigger()
    assert QGuiApplication.clipboard().text() == hits[0].template_key
    assert window.statuses[-1] == strings.SEARCH_STATUS_COPIED_KEY
    menu.deleteLater()


def test_cerca_solo_questo_fdi_refills_the_form_and_searches_again(qtbot, page):
    hits = search(qtbot, page, key=KEY_SINT)
    target = hits[0]
    menu = page.build_context_menu(target)
    with qtbot.waitSignal(page.presenter.results_ready, timeout=5000):
        action(menu, strings.SEARCH_MENU_ONLY_FDI).trigger()
    assert page.form.fdi() == target.fdi
    assert page.form.template_key() == ""
    assert page.model.rowCount() > 0
    assert {hit.fdi for hit in page.model.hits()} == {target.fdi}
    menu.deleteLater()


def test_cerca_solo_questa_template_key_refills_the_form_and_searches_again(qtbot, page):
    hits = search(qtbot, page, fdi=FDI_A)
    target = hits[0]
    menu = page.build_context_menu(target)
    with qtbot.waitSignal(page.presenter.results_ready, timeout=5000):
        action(menu, strings.SEARCH_MENU_ONLY_KEY).trigger()
    assert page.form.fdi() == ""
    assert page.form.template_key() == target.template_key
    assert {hit.template_key for hit in page.model.hits()} == {target.template_key}
    menu.deleteLater()


def test_opening_the_day_s_log_folder_asks_the_core_for_its_directory(qtbot, page, fake_core):
    hits = search(qtbot, page, fdi=FDI_A)
    menu = page.build_context_menu(hits[0])
    action(menu, strings.SEARCH_MENU_OPEN_DAY_FOLDER).trigger()
    assert fake_core.extract.folders == [hits[0].file_path.parent]
    menu.deleteLater()


# ------------------------------------------------------------ integration ---

def test_the_page_registers_under_the_search_key():
    from qtrequestory.ui.main_window import PAGES

    spec = next(p for p in PAGES if p.key == "search")
    assert spec.factory.__name__ == "make_search_page"


def test_the_shell_builds_the_real_page(qtbot, fake_core, runner):
    from qtrequestory.ui.main_window import MainWindow

    win = MainWindow(fake_core, runner)
    qtbot.addWidget(win)
    assert isinstance(win.page("search"), SearchPage)


def test_the_table_hides_the_two_technical_columns(page):
    for column in ResultsModel.HIDDEN_COLUMNS:
        assert page.table.isColumnHidden(column)
