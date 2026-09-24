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

import dataclasses
from datetime import date, timedelta
from pathlib import Path

import pytest
from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtGui import QGuiApplication, QKeySequence
from PySide6.QtWidgets import QHeaderView, QWidget

from qtrequestory.ui import prefs, strings
from qtrequestory.ui.actions import user_settings
from qtrequestory.ui.contracts import Coverage, pick_best
from qtrequestory.ui.pages.preview_pane import PreviewPane
from qtrequestory.ui.pages.search_actions import row_tsv
from qtrequestory.ui.pages.search_meta import coverage_gap, last_expected_day
from qtrequestory.ui.pages.search_page import SearchPage
from qtrequestory.ui.pages.search_paste import parse_pasted_entry
from qtrequestory.ui.pages.search_period import CUSTOM_ID
from qtrequestory.ui.pages.search_recents import MAX_RECENTS, Recent, load_recents
from qtrequestory.ui.pages.search_results import FDI_MAX_WIDTH, ResultsHeader, mime_for_file
from qtrequestory.ui.results_model import ResultsModel

from tests.conftest import FDI_A, FDI_B, KEY_CTE, KEY_EMAIL, KEY_NUMERIC, KEY_SINT
from tests.fakes.fake_core import DAYS

NOTEPAD_PP = Path("C:/Programmi/Notepad++/notepad++.exe")
#: A window that contains every day the fake core knows about.
WIDE_FROM = min(DAYS) - timedelta(days=1)
WIDE_TO = max(DAYS) + timedelta(days=1)


class FakeWindow:
    """What the page uses of ``MainWindow``: three methods, all recorded."""

    def __init__(self) -> None:
        self.shown: list[str] = []
        self.statuses: list[str] = []
        self.contexts: list[str | None] = []

    def set_context(self, text: str | None) -> None:
        self.contexts.append(text)

    def show_page(self, key: str) -> None:
        self.shown.append(key)

    def set_status(self, text: str, ms: int = 4000) -> None:
        self.statuses.append(text)


class FakePane(QWidget):
    """Stand-in for the preview pane: what the page calls on it."""

    def __init__(self) -> None:
        super().__init__()
        self.hits: list[object] = []
        self.calls: list[str] = []

    def set_hit(self, hit) -> None:
        self.hits.append(hit)

    def current_hit(self):
        return self.hits[-1] if self.hits else None

    def open_in_editor(self) -> None:
        self.calls.append("open")

    def save_as(self) -> None:
        self.calls.append("save")

    def copy_body(self) -> None:
        self.calls.append("copy")

    def open_folder(self) -> None:
        self.calls.append("folder")


@pytest.fixture
def window() -> FakeWindow:
    return FakeWindow()


@pytest.fixture
def make_page(qtbot, fake_core, runner, window):
    """Build the page *after* the test has set the fake core's knobs.

    ``preview_factory=None`` is the degraded mode (no pane); the default is the
    real :class:`PreviewPane`, exactly what the shell builds.
    """

    def build(**kwargs) -> SearchPage:
        page = SearchPage(fake_core, runner, window, **kwargs)
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
        (f"correlationId_vuoto_{KEY_NUMERIC}_1a2b3c0200000031",
         (None, KEY_NUMERIC)),
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
        KEY_EMAIL,                                # a bare template key
        "Ciao, mi mandi il log di ieri?",         # free text with spaces
        f"{FDI_A} {KEY_SINT} 1a2b3c0200000031",   # spaces instead of underscores
    ],
)
def test_parse_pasted_entry_leaves_anything_else_alone(text):
    assert parse_pasted_entry(text) is None


def test_pasting_an_entry_name_into_the_omnibox_fills_both_filters(qtbot, page):
    QGuiApplication.clipboard().setText(f"### {FDI_B}_{KEY_EMAIL}_1a2b3c0100000012.json")
    edit = page.form.omnibox.edit
    edit.setFocus()
    qtbot.keyClick(edit, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    assert page.form.fdi() == FDI_B
    assert page.form.template_key() == KEY_EMAIL
    assert page.form.can_search()


def test_pasting_a_bare_fdi_fills_only_the_fdi(qtbot, page):
    QGuiApplication.clipboard().setText(FDI_B)
    edit = page.form.omnibox.edit
    edit.setFocus()
    qtbot.keyClick(edit, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    assert page.form.fdi() == FDI_B
    assert page.form.template_key() == ""


# --------------------------------------------------------------- the bar ---

def test_the_bar_offers_the_enabled_environments_and_the_default_period(page, fake_core):
    cfg = fake_core.config.load()
    assert page.form.environments() == [e.name for e in cfg.enabled_environments()]
    assert page.form.current_env() == cfg.enabled_environments()[0].name
    assert page.form.preset_days() == cfg.default_window_days


def test_the_bar_is_one_full_width_row_above_the_splitter(page):
    assert page.form.parent() is page
    assert not page.splitter.isAncestorOf(page.form)
    row = page.form.layout()
    items = [row.itemAt(i).widget() for i in range(row.count())]
    assert items[0] is page.form.env_combo
    assert items[1] is page.form.omnibox
    assert items[-1] is page.form.search_button
    assert page.form.search_button.property("role") == "primary"


@pytest.mark.parametrize("days", [7, 30, 90])
def test_a_preset_sets_a_window_of_that_many_days_ending_today(page, days):
    page.form.set_preset(days)
    day_from, day_to = page.form.day_range()
    assert day_to == date.today()
    assert (day_to - day_from).days + 1 == days
    assert page.form.window_days() == days


def test_the_calendar_opens_a_popup_on_the_window_that_was_showing(qtbot, page):
    page.form.set_preset(7)
    page.form.period_group.button(CUSTOM_ID).click()
    popup = page.form.period.popup
    assert popup.isVisible()
    assert popup.date_from.date().toPython() == date.today() - timedelta(days=6)
    assert page.form.preset_days() == 7, "only [Applica] changes the period"
    assert page.form.period_group.button(7).isChecked()
    popup.hide()


def test_applying_a_custom_range_checks_the_calendar_and_names_the_range(qtbot, page):
    page.form.period_group.button(CUSTOM_ID).click()
    popup = page.form.period.popup
    popup.date_from.setDate(date(2026, 9, 1))
    popup.date_to.setDate(date(2026, 9, 30))
    popup.apply_button.click()
    assert not popup.isVisible()
    assert page.form.preset_days() is None
    assert page.form.day_range() == (date(2026, 9, 1), date(2026, 9, 30))
    calendar = page.form.period.calendar_button
    assert calendar.isChecked()
    assert calendar.toolTip() == strings.SEARCH_PERIOD_CUSTOM_ACTIVE_TOOLTIP.format(
        first="01/09/2026", last="30/09/2026")
    page.form.period_group.button(30).click()
    assert page.form.preset_days() == 30
    assert calendar.toolTip() == strings.SEARCH_PERIOD_CUSTOM_TOOLTIP


def test_the_page_fits_in_1100_pixels_with_a_custom_range(page):
    page.form.set_custom_range(date(2026, 9, 1), date(2026, 9, 30))
    assert page.minimumSizeHint().width() <= 1100


def test_the_key_mode_defaults_to_esatta_and_is_remembered(qtbot, make_page):
    first = make_page()
    assert first.form.key_mode() == "exact"
    first.form.key_mode_group.button(1).click()
    assert first.form.key_mode() == "contains"
    assert user_settings().value(prefs.KEY_MODE_KEY) == "contains"
    second = make_page()
    assert second.form.key_mode() == "contains"


def test_the_key_mode_reaches_the_query(qtbot, page):
    page.form.key_mode_group.button(1).click()
    hits = search(qtbot, page, key="summary_offer")
    assert hits and {h.template_key for h in hits} == {KEY_SINT}


def test_cerca_stays_disabled_until_a_filter_is_typed(page):
    assert not page.form.search_button.isEnabled()
    assert page.form.search_button.toolTip() == strings.SEARCH_BTN_DISABLED_TOOLTIP
    page.form.set_fdi("aaaa")
    assert page.form.search_button.isEnabled()
    page.form.set_fdi("")
    assert not page.form.search_button.isEnabled()
    page.form.set_template_key(KEY_SINT)
    assert page.form.search_button.isEnabled()


def test_cerca_shows_it_is_busy_and_the_status_bar_stays_quiet(qtbot, page, window):
    page.form.set_fdi(FDI_A)
    page.form.set_custom_range(WIDE_FROM, WIDE_TO)
    with qtbot.waitSignal(page.presenter.results_ready, timeout=5000):
        page.run_search()
        assert page.form.search_button.text() == strings.SEARCH_BTN_BUSY
        assert not page.form.search_button.isEnabled()
    assert page.form.search_button.text() == strings.SEARCH_BTN
    assert page.form.search_button.isEnabled()
    assert window.statuses == [], "no lingering status-bar line"


def test_enter_in_the_omnibox_runs_the_search(qtbot, page):
    page.form.set_custom_range(WIDE_FROM, WIDE_TO)
    qtbot.keyClicks(page.form.omnibox.edit, "aaaaaaaa")
    with qtbot.waitSignal(page.presenter.results_ready, timeout=5000):
        qtbot.keyClick(page.form.omnibox.edit, Qt.Key.Key_Return)
    assert page.model.hits()


def test_escape_clears_the_omnibox(qtbot, page):
    page.form.set_fdi("aaaa")
    page.form.set_template_key(KEY_SINT)
    page.form.omnibox.edit.setFocus()
    qtbot.keyClick(page.form.omnibox.edit, Qt.Key.Key_Escape)
    assert (page.form.fdi(), page.form.template_key()) == ("", "")


def test_the_template_keys_come_from_the_index_and_reload_on_an_environment_change(qtbot, page):
    qtbot.waitUntil(lambda: page.form.template_keys() != [], timeout=5000)
    assert set(page.form.template_keys()) == {KEY_SINT, KEY_EMAIL, KEY_CTE}
    page.form.set_env("svil")
    qtbot.waitUntil(lambda: page.form.template_keys() == [], timeout=5000)


def test_changing_environment_drops_the_rows_of_the_previous_one(qtbot, page):
    pane = FakePane()
    page.set_preview_widget(pane)
    search(qtbot, page, fdi=FDI_A)
    page.form.set_env("svil")
    assert page.model.hits() == []
    assert page.meta.summary_label.text() == ""
    qtbot.waitUntil(lambda: pane.hits[-1] is None, timeout=5000)


def test_saving_the_settings_keeps_the_results_and_the_period(qtbot, page, fake_core):
    hits = search(qtbot, page, fdi=FDI_A)
    period = page.form.day_range()
    page.on_config_changed(fake_core.config.load())
    assert page.model.hits() == hits
    assert page.form.current_env() == "coll"
    assert page.form.day_range() == period, "a save must not reset the user's period"


def test_the_chosen_environment_is_remembered(qtbot, make_page):
    first = make_page()
    first.form.set_env("svil")
    second = make_page()
    assert second.form.current_env() == "svil"


# --------------------------------------------------------------- recents ---

def test_every_search_is_remembered_newest_first_without_duplicates(qtbot, page):
    search(qtbot, page, fdi=FDI_A)
    search(qtbot, page, key=KEY_SINT)
    search(qtbot, page, fdi=FDI_A)
    recents = load_recents(user_settings())
    assert recents == [Recent("coll", FDI_A, "", "exact"), Recent("coll", "", KEY_SINT, "exact")]
    menu = page.form.omnibox.recent_menu()
    assert menu.actions()[1].text() == recents[0].label()
    menu.deleteLater()


def test_only_the_last_ten_searches_are_kept(qtbot, page):
    for i in range(MAX_RECENTS + 3):
        page.form.set_fdi(f"{i:04x}")
        page.run_search()
    assert len(load_recents(user_settings())) == MAX_RECENTS


def test_choosing_a_recent_search_runs_it_again(qtbot, page):
    recent = Recent("coll", "", KEY_SINT, "contains")
    page.form.set_custom_range(WIDE_FROM, WIDE_TO)
    with qtbot.waitSignal(page.presenter.results_ready, timeout=5000):
        page.form.omnibox.recent_chosen.emit(recent)
    assert page.form.template_key() == KEY_SINT
    assert page.form.key_mode() == "contains"
    assert page.model.hits()


# ------------------------------------------------------ meta line, banner ---

def test_the_meta_line_names_the_first_and_the_last_indexed_day(page, fake_core):
    cov = fake_core.index.coverage("coll")
    assert page.meta.coverage_label.text() == strings.SEARCH_COVERAGE.format(
        env="coll", first=f"{cov.first_day:%d/%m/%Y}", last=f"{cov.last_day:%d/%m/%Y}")
    assert "domani" in page.meta.coverage_label.toolTip()
    assert "domani" not in page.meta.coverage_label.text()


def test_a_mirror_with_holes_raises_the_warning_with_a_way_to_sync(qtbot, fake_core, make_page,
                                                                   window):
    expected = last_expected_day(date.today())
    present = {expected - timedelta(days=d) for d in range(0, 20)}
    hole = max(d for d in present if d.weekday() < 5 and d != expected)
    fake_core.index.set_local_days("coll", present - {hole})
    fake_core.index.set_server_days("coll", listed={hole})  # still on the server: pending
    page = make_page()
    assert page.gap_banner.isVisible()
    assert page.gap_banner.label.text() == strings.SEARCH_GAP_ONE.format(env="coll")
    page.gap_banner.button.click()
    assert window.shown == ["sync"]


def test_a_complete_mirror_shows_no_warning(qtbot, fake_core, make_page):
    expected = last_expected_day(date.today())
    fake_core.index.set_local_days("coll", {expected - timedelta(days=d) for d in range(0, 40)})
    page = make_page()
    assert not page.gap_banner.isVisible()


def test_coverage_gap_counts_the_days_after_the_newest_file(fake_core):
    """A mirror that stopped on Friday, seen the next Wednesday: Mon and Tue."""
    wednesday = date(2026, 9, 23)
    friday = date(2026, 9, 18)
    fake_core.index.set_local_days("coll", {friday - timedelta(days=d) for d in range(0, 5)})
    days = fake_core.index.coverage_days("coll", today=wednesday)
    assert coverage_gap(days, wednesday) == (date(2026, 9, 21), date(2026, 9, 22))
    assert last_expected_day(date(2026, 9, 21)) == friday, "Monday expects Friday's file"


def test_no_enabled_environment_disables_the_bar_and_says_why(qtbot, fake_core, make_page,
                                                              window):
    fake_core.config.config = dataclasses.replace(
        fake_core.config.config,
        environments=[dataclasses.replace(e, enabled=False)
                      for e in fake_core.config.config.environments])
    page = make_page()
    assert page.current_state() == "no_env"
    assert not page.form.isEnabled()
    assert strings.SEARCH_EMPTY_NO_ENV_TITLE in page.states.no_env.text()
    page.states.no_env.button.click()
    assert window.shown == ["settings"]


def test_the_window_title_forgets_the_call_while_another_page_shows(qtbot, page, window):
    hits = search(qtbot, page, fdi=FDI_A)
    qtbot.waitUntil(lambda: bool(window.contexts) and window.contexts[-1] is not None,
                    timeout=5000)
    page.hide()
    assert window.contexts[-1] is None
    page.show()
    assert window.contexts[-1] == f"{hits[0].env} · {FDI_A[:8]}"


# ----------------------------------------------------------------- search ---

def test_an_fdi_fills_the_results_with_a_row_selected(qtbot, page):
    hits = search(qtbot, page, fdi=FDI_A)
    assert hits, "the fake core knows this FDI"
    assert all(hit.fdi == FDI_A for hit in hits)
    assert page.selected_hit() is not None
    assert page.current_state() == "table"


def test_the_rows_arrive_newest_first(qtbot, page):
    hits = search(qtbot, page, fdi=FDI_A)
    days = [hit.day for hit in hits]
    assert days == sorted(days, reverse=True)
    assert page.model.hits() == hits


def test_the_summary_counts_calls_fdis_and_days(qtbot, page):
    hits = search(qtbot, page, key=KEY_SINT)
    text = page.meta.summary_label.text()
    assert strings.SEARCH_SUMMARY_CALLS_MANY.format(n=len(hits)) in text
    assert strings.SEARCH_SUMMARY_FDIS_MANY.format(n=len({h.fdi for h in hits})) in text
    assert strings.SEARCH_SUMMARY_DAYS_MANY.format(n=len({h.day for h in hits})) in text
    assert text.endswith(strings.SEARCH_SUMMARY_TAIL)


def test_a_single_result_is_counted_in_the_singular(qtbot, page):
    hits = search(qtbot, page, fdi=FDI_A, key=KEY_EMAIL, day_from=DAYS[0], day_to=DAYS[0])
    assert len(hits) == 1
    assert strings.SEARCH_SUMMARY_CALLS_ONE in page.meta.summary_label.text()
    assert strings.SEARCH_SUMMARY_DAYS_ONE in page.meta.summary_label.text()


def test_f5_repeats_the_last_search(qtbot, page):
    search(qtbot, page, fdi=FDI_A)
    page.model.set_hits([])
    with qtbot.waitSignal(page.presenter.results_ready, timeout=5000):
        page.shortcuts["F5"].activated.emit()
    assert page.model.hits()


def test_ctrl_l_and_ctrl_k_focus_the_two_filters(page):
    page.form.set_fdi(FDI_A)
    page.form.set_template_key(KEY_SINT)
    page.shortcuts["Ctrl+L"].activated.emit()
    assert page.form.omnibox.edit.hasFocus()
    assert page.form.omnibox.edit.selectedText() == FDI_A
    page.shortcuts["Ctrl+K"].activated.emit()
    assert page.form.omnibox.edit.selectedText() == KEY_SINT
    assert (page.form.fdi(), page.form.template_key()) == (FDI_A, KEY_SINT)


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
    assert page.meta.coverage_label.text() == strings.SEARCH_COVERAGE_NONE.format(env="svil")
    assert strings.SEARCH_EMPTY_NO_LOG_TITLE.format(env="svil") in page.states.no_log.text()
    page.states.no_log.button.click()
    assert window.shown == ["sync"]
    page.form.set_env("coll")
    assert page.current_state() == "start", "coming back must leave the empty state"


def test_switching_environment_clears_the_no_results_state(qtbot, page):
    """"Nessuna chiamata trovata" describes the search that ran, not the new env.

    Leaving it up after switching to an environment that does have logs told the
    user there was nothing there before anything had even been searched.
    """
    from qtrequestory.ui.contracts import Coverage

    search(qtbot, page, fdi="aaaa", day_from=date(2026, 1, 1), day_to=date(2026, 1, 31))
    assert page.current_state() == "no_results"

    page.services.index.coverage = lambda env: Coverage(date(2026, 9, 1), date(2026, 9, 18), 3, 9)
    page.form.set_env("svil")
    assert page.current_state() == "start"


def test_no_results_explains_what_to_try_next(qtbot, page):
    search(qtbot, page, fdi="aaaa", day_from=date(2026, 1, 1), day_to=date(2026, 1, 31))
    assert page.model.hits() == []
    assert page.current_state() == "no_results"
    assert page.meta.summary_label.text() == ""
    text = page.states.no_results.text()
    assert strings.SEARCH_EMPTY_NO_RESULTS_TITLE in text
    assert strings.SEARCH_EMPTY_HINT_SHORT_FDI in text, "an FDI of 4 characters is a prefix"
    assert strings.SEARCH_EMPTY_HINT_TODAY.format(file="20260131.txt") not in text
    assert page.states.no_results.button.isVisible(), "31 days: widening to 90 is worth offering"


def test_a_fruitless_template_key_says_the_key_must_be_complete(qtbot, page):
    """The key match is exact, and nothing on the page says so.

    Keys come in suffix families (``_LUCE`` / ``_GAS`` / ``_DUAL`` / ``_386``),
    so typing half of one and pressing Invio is the natural thing to do — and
    it returns zero rows while the empty state talks about the *period*. Until
    a "contiene / inizia con / esatta" control exists, the hint has to say it
    and point at the list that does hold the complete keys.
    """
    search(qtbot, page, key="MOD_ALPHA_SUMMARY",
           day_from=date(2026, 1, 1), day_to=date(2026, 1, 31))

    assert page.current_state() == "no_results"
    assert strings.SEARCH_EMPTY_HINT_EXACT_KEY in page.states.no_results.text()


def test_the_key_hint_is_absent_when_no_key_was_searched(qtbot, page):
    search(qtbot, page, fdi="aaaa", day_from=date(2026, 1, 1), day_to=date(2026, 1, 31))

    assert strings.SEARCH_EMPTY_HINT_EXACT_KEY not in page.states.no_results.text()


def test_a_window_ending_today_warns_that_today_s_calls_arrive_tomorrow(qtbot, page):
    today = date.today()
    search(qtbot, page, fdi="ffff", day_from=today - timedelta(days=6), day_to=today)
    assert page.current_state() == "no_results"
    expected = strings.SEARCH_EMPTY_HINT_TODAY.format(file=f"{today:%Y%m%d}.txt")
    assert expected in page.states.no_results.text()


def test_a_full_fdi_over_ninety_days_gets_neither_hint_nor_button(qtbot, page):
    today = date.today()
    search(qtbot, page, fdi=FDI_B.replace("b", "f"),
           day_from=today - timedelta(days=200), day_to=today - timedelta(days=1))
    assert page.current_state() == "no_results"
    assert strings.SEARCH_EMPTY_HINT_SHORT_FDI not in page.states.no_results.text()
    assert not page.states.no_results.button.isVisible()


def test_widening_to_ninety_days_re_runs_the_search(qtbot, page):
    search(qtbot, page, fdi="aaaa", day_from=date(2026, 1, 1), day_to=date(2026, 1, 31))
    with qtbot.waitSignal(page.presenter.results_ready, timeout=5000):
        page.states.no_results.button.click()
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

def test_the_page_installs_the_real_preview_pane_by_itself(page):
    assert isinstance(page.preview_widget(), PreviewPane)
    assert not page.preview_placeholder.isVisibleTo(page.preview_slot)


def test_the_preview_factory_receives_the_services_the_runner_and_the_page(
        fake_core, runner, make_page):
    calls: list[tuple] = []

    def factory(services, job_runner, host):
        calls.append((services, job_runner, host))
        return FakePane()

    page = make_page(preview_factory=factory)
    assert calls == [(fake_core, runner, page)]
    assert isinstance(page.preview_widget(), FakePane)


def test_degraded_mode_without_a_preview_pane_shows_a_placeholder(make_page):
    page = make_page(preview_factory=None)
    assert page.preview_widget() is None
    assert page.preview_placeholder.isVisibleTo(page.preview_slot)


def test_the_selected_hit_is_handed_to_the_preview_pane(qtbot, page):
    pane = FakePane()
    page.set_preview_widget(pane)
    assert page.preview_widget() is pane
    assert not page.preview_placeholder.isVisibleTo(page.preview_slot)
    hits = search(qtbot, page, fdi=FDI_A)
    qtbot.waitUntil(lambda: pane.hits and pane.hits[-1] is hits[0], timeout=5000)


def test_the_selected_hit_names_the_window(qtbot, page, window):
    """The title bar says which environment and FDI are on screen."""
    hits = search(qtbot, page, fdi=FDI_A)
    qtbot.waitUntil(lambda: bool(window.contexts) and window.contexts[-1] is not None,
                    timeout=5000)
    assert window.contexts[-1] == f"{hits[0].env} · {FDI_A[:8]}"

    search(qtbot, page, fdi="ffff")
    qtbot.waitUntil(lambda: window.contexts[-1] is None, timeout=5000)


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
    hits = search(qtbot, page, fdi=FDI_A)
    page.view.doubleClicked.emit(page.model.index(0, 0))  # a group row: folds only
    assert pane.calls == []
    page.view.doubleClicked.emit(page.model.index_of(hits[0]))
    assert pane.calls == ["open"]


def test_enter_on_a_row_opens_it_in_the_editor(qtbot, page):
    pane = FakePane()
    page.set_preview_widget(pane)
    search(qtbot, page, fdi=FDI_A)
    page.view.setFocus()
    qtbot.keyClick(page.view, Qt.Key.Key_Return)
    assert pane.calls == ["open"]


# --------------------------------------------------------- context menu -----

@pytest.fixture
def npp_page(fake_core, make_page) -> SearchPage:
    """A page whose editor is Notepad++, as on the users' machines."""
    fake_core.config.editor = NOTEPAD_PP
    return make_page()


def test_the_context_menu_lists_every_row_action(qtbot, npp_page):
    page = npp_page
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


def test_the_open_entry_names_the_editor_the_pane_names(qtbot, page):
    """Without Notepad++ the file opens in whatever editor Windows associates."""
    hits = search(qtbot, page, fdi=FDI_A)
    menu = page.build_context_menu(hits[0])
    assert menu.actions()[0].text() == strings.PREVIEW_BTN_OPEN_DEFAULT
    assert page.preview_widget().open_button.text() == strings.PREVIEW_BTN_OPEN_DEFAULT
    menu.deleteLater()


def test_degraded_mode_disables_the_body_actions(qtbot, make_page):
    page = make_page(preview_factory=None)
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
    assert page.model.hits()
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


# ------------------------------------------------ page-level shortcuts ------

def test_the_page_binds_the_documented_row_shortcuts(page):
    assert {"Ctrl+C", "Ctrl+Shift+C", "Ctrl+S", "Ctrl+O", "Ctrl+Shift+O"} <= set(page.shortcuts)
    for sequence, shortcut in page.shortcuts.items():
        assert shortcut.key() == QKeySequence(sequence)
        assert shortcut.context() == Qt.ShortcutContext.WidgetWithChildrenShortcut


@pytest.mark.parametrize(
    "sequence, expected",
    [("Ctrl+C", "copy"), ("Ctrl+S", "save"), ("Ctrl+O", "open"), ("Ctrl+Shift+O", "folder")],
)
def test_the_row_shortcuts_reach_the_preview_pane(qtbot, page, sequence, expected):
    pane = FakePane()
    page.set_preview_widget(pane)
    search(qtbot, page, fdi=FDI_A)
    page.view.setFocus()
    page.shortcuts[sequence].activated.emit()
    assert pane.calls == [expected]


def test_ctrl_c_leaves_a_text_field_to_its_own_copy(qtbot, page):
    """Reached only if the field did not claim the key itself: the page must
    then copy the field's selection, never swap in the body."""
    pane = FakePane()
    page.set_preview_widget(pane)
    page.form.set_fdi(FDI_A)
    page.form.focus_fdi()
    QGuiApplication.clipboard().setText("")
    page.shortcuts["Ctrl+C"].activated.emit()
    assert pane.calls == []


def test_ctrl_shift_c_copies_the_row_as_tsv(qtbot, page, window):
    hits = search(qtbot, page, fdi=FDI_A)
    page.view.setFocus()
    page.shortcuts["Ctrl+Shift+C"].activated.emit()
    assert QGuiApplication.clipboard().text() == row_tsv(hits[0])


def test_row_tsv_has_the_six_documented_fields(fake_core):
    hit = fake_core.index.hits[0]
    fields = row_tsv(hit).split("\t")
    assert fields == [
        f"{hit.day:%d/%m/%Y}", fields[1], hit.template_key, hit.fdi or "",
        "" if hit.ndocs is None else str(hit.ndocs), str(hit.body_len),
    ]
    assert fields[1] == "" or len(fields[1]) == 8  # HH:MM:SS, or nothing


# ------------------------------------------------- context menu look -------

@pytest.mark.parametrize(
    "label, icon_name, sequence",
    [
        (strings.SEARCH_MENU_OPEN, "document-arrow-right", "Ctrl+O"),
        (strings.BTN_SAVE_AS, "save", "Ctrl+S"),
        (strings.SEARCH_MENU_COPY_JSON, "copy", "Ctrl+C"),
        (strings.SEARCH_MENU_OPEN_DAY_FOLDER, "folder-open", ""),
    ],
)
def test_the_context_menu_shows_icons_and_shortcuts(qtbot, npp_page, label, icon_name, sequence):
    page = npp_page
    hits = search(qtbot, page, fdi=FDI_A)
    menu = page.build_context_menu(hits[0])
    item = action(menu, label)
    assert not item.icon().isNull()
    assert item.property("iconName") == icon_name
    assert item.shortcut() == QKeySequence(sequence)
    assert item.isShortcutVisibleInContextMenu()
    menu.deleteLater()


# ------------------------------------------------------- data changed -------

def test_on_data_changed_refreshes_the_page_and_keeps_the_results(qtbot, page, fake_core):
    hits = search(qtbot, page, fdi=FDI_A)
    period = page.form.day_range()
    fake_core.index.set_pending(2)
    page.on_data_changed()
    qtbot.waitUntil(lambda: page.stale_banner.isVisible(), timeout=5000)
    assert page.model.hits() == hits
    assert page.form.day_range() == period


# ------------------------------------------------------ results: the tree ---

def test_results_are_grouped_by_fdi_by_default_with_the_fdi_column_hidden(qtbot, page):
    search(qtbot, page, key=KEY_SINT)
    assert page.model.grouped()
    assert page.meta.group_button.isChecked()
    assert page.view.isColumnHidden(ResultsModel.COL_FDI)
    top = page.model.index(0, 0)
    assert page.model.is_group(top)
    assert page.view.isFirstColumnSpanned(0, QModelIndex())
    assert page.view.isExpanded(top)


def test_the_grouping_toggle_is_remembered_and_keeps_the_selection(qtbot, page, make_page):
    search(qtbot, page, key=KEY_SINT)
    selected = page.selected_hit()
    page.meta.group_button.click()
    assert not page.model.grouped()
    assert not page.view.isColumnHidden(ResultsModel.COL_FDI)
    assert page.selected_hit() == selected
    assert user_settings().value(prefs.GROUP_BY_FDI_KEY, type=bool) is False
    assert make_page().model.grouped() is False


def test_the_columns_are_readable(qtbot, page):
    search(qtbot, page, key=KEY_SINT)
    header = page.view.header()
    assert not header.highlightSections()
    assert header.defaultAlignment() & Qt.AlignmentFlag.AlignLeft
    assert isinstance(header, ResultsHeader), "numeric labels right-aligned over the numbers"
    assert header.sectionResizeMode(ResultsModel.COL_KEY) == QHeaderView.ResizeMode.Stretch
    for column in (ResultsModel.COL_NDOCS, ResultsModel.COL_SIZE):
        assert header.sectionResizeMode(column) == QHeaderView.ResizeMode.ResizeToContents
    assert not header.stretchLastSection()


def test_doc_and_dim_sit_together_at_the_right_edge(qtbot, page):
    page.resize(1600, 800)
    search(qtbot, page, key=KEY_SINT)
    header = page.view.header()
    doc = header.sectionViewportPosition(ResultsModel.COL_NDOCS)
    dim = header.sectionViewportPosition(ResultsModel.COL_SIZE)
    assert dim == doc + header.sectionSize(ResultsModel.COL_NDOCS), "adjacent"
    assert dim + header.sectionSize(ResultsModel.COL_SIZE) >= page.view.viewport().width() - 2


def test_the_flat_list_fits_without_a_horizontal_scroll_bar(qtbot, page):
    page.resize(1366, 700)
    page.set_grouped(False)
    search(qtbot, page, key=KEY_SINT)
    header = page.view.header()
    assert header.sectionSize(ResultsModel.COL_FDI) <= FDI_MAX_WIDTH
    assert header.length() <= page.view.viewport().width()


def test_an_fdi_search_preselects_the_entry_with_the_most_documents(qtbot, fake_core, make_page):
    index = fake_core.index
    newest = next(h for h in index.hits if h.fdi == FDI_A and h.template_key == KEY_EMAIL)
    index.hits = [dataclasses.replace(h, ndocs=1) if h is newest else h for h in index.hits]
    page = make_page()
    hits = search(qtbot, page, fdi=FDI_A)
    assert hits[0].template_key == KEY_EMAIL, "the newest call is now the poorest"
    best, _rest = pick_best(hits, prefer_most_documents=True)
    assert page.selected_hit() == best != hits[0]
    assert best.ndocs == max(h.ndocs or 0 for h in hits if h.day == hits[0].day)
    assert page.view.currentIndex().parent().isValid(), "selected inside its group"


def test_a_key_search_preselects_the_newest_call(qtbot, page):
    hits = search(qtbot, page, key=KEY_SINT)
    assert page.selected_hit() == hits[0]


def test_the_arrow_keys_never_stop_on_a_group_row(qtbot, page):
    search(qtbot, page, key=KEY_SINT)
    page.view.setFocus()
    seen = [page.selected_hit()]
    for _ in range(len(page.model.hits()) * 2):
        qtbot.keyClick(page.view, Qt.Key.Key_Down)
        seen.append(page.selected_hit())
    assert all(hit is not None for hit in seen)
    assert len({h.entry_id for h in seen}) == len(page.model.hits())


def test_the_summary_tail_follows_the_sort(qtbot, page):
    search(qtbot, page, key=KEY_SINT)
    assert page.meta.summary_label.text().endswith(strings.SEARCH_SUMMARY_TAIL)
    page.view.sortByColumn(ResultsModel.COL_KEY, Qt.SortOrder.AscendingOrder)
    assert page.meta.summary_label.text().endswith(
        strings.SEARCH_SUMMARY_TAIL_COLUMN.format(column=strings.SEARCH_COL_KEY))
    page.view.sortByColumn(ResultsModel.COL_WHEN, Qt.SortOrder.DescendingOrder)
    assert page.meta.summary_label.text().endswith(strings.SEARCH_SUMMARY_TAIL)


# -------------------------------------------------------------- drag out ---

def test_dragging_a_row_hands_out_the_body_as_a_json_file(qtbot, page, fake_core):
    hits = search(qtbot, page, fdi=FDI_A)
    path = page.prepare_drag_file(hits[0])
    body = fake_core.extract.pretty_json(fake_core.index.read_body(hits[0]))
    assert path.read_text(encoding="utf-8") == body
    assert path.name == fake_core.extract.output_name(hits[0])
    mime = mime_for_file(path)
    assert [url.toLocalFile() for url in mime.urls()] == [str(path).replace("\\", "/")]


def test_dragging_the_same_row_twice_reuses_the_file(qtbot, page, fake_core):
    hits = search(qtbot, page, fdi=FDI_A)
    first = page.prepare_drag_file(hits[0])
    second = page.prepare_drag_file(hits[0])
    assert first == second
    assert len(list(fake_core.extract.output_dir().glob("*.json"))) == 1


# ---------------------------------------------------------- start state ---

def test_the_page_starts_on_the_start_state_with_the_preview_hidden(page):
    assert page.current_state() == "start"
    assert not page.preview_slot.isVisible()
    text = page.states.start.text()
    assert strings.SEARCH_START_TITLE in text
    assert strings.SEARCH_START_SHORTCUTS in text


def test_the_start_state_lists_the_recent_searches_as_clickable_rows(qtbot, page):
    search(qtbot, page, key=KEY_SINT)
    page.form.set_env("svil")
    page.form.set_env("coll")
    assert page.current_state() == "start"
    rows = page.states.start.rows()
    assert [row.text() for row in rows] == [Recent("coll", "", KEY_SINT, "exact").label()]
    old = rows[0]
    page.states.set_recents([], page.apply_recent)
    assert not old.isVisible(), "a replaced row must not linger until deleteLater"
    page.states.set_recents(load_recents(user_settings()), page.apply_recent)
    rows = page.states.start.rows()
    page.form.set_custom_range(WIDE_FROM, WIDE_TO)
    with qtbot.waitSignal(page.presenter.results_ready, timeout=5000):
        rows[0].click()
    assert page.current_state() == "table"
    assert page.preview_slot.isVisible()


def test_an_emptied_index_says_it_is_being_rebuilt(qtbot, fake_core, make_page):
    fake_core.index.coverage = lambda env: None
    page = make_page()
    assert page.current_state() == "no_log"
    assert strings.SEARCH_EMPTY_REBUILDING_TITLE in page.states.no_log.text()


def test_hiding_the_page_after_its_window_is_gone_is_harmless(qtbot, fake_core, runner):
    """At shutdown the page is hidden after the window it names is deleted."""
    from PySide6.QtWidgets import QMainWindow

    host = QMainWindow()
    page = SearchPage(fake_core, runner, host)
    qtbot.addWidget(page)
    page.show()
    host.deleteLater()
    qtbot.waitUntil(lambda: not __import__("shiboken6").isValid(host), timeout=2000)
    page.hide()  # must not raise inside the event filter



# ------------------------------------------- actions follow the selection ---

def _click_group_row(qtbot, page):
    """What a click on an FDI header does: current = the group, nothing selected."""
    group = page.model.index(0, 0)
    assert page.model.is_group(group)
    page.view.setCurrentIndex(group)
    assert page.selected_hit() is None


@pytest.mark.parametrize("sequence", ["Ctrl+C", "Ctrl+O", "Ctrl+S"])
def test_body_shortcuts_after_clicking_a_group_row_do_nothing(qtbot, page, window, sequence):
    """Reproduced in review: Ctrl+C copied the previously selected call's body."""
    pane = FakePane()
    page.set_preview_widget(pane)
    search(qtbot, page, fdi=FDI_A)
    qtbot.waitUntil(lambda: pane.current_hit() is not None, timeout=5000)
    _click_group_row(qtbot, page)
    page.view.setFocus()
    page.shortcuts[sequence].activated.emit()
    assert pane.calls == []
    assert window.statuses[-1] == strings.SEARCH_NOTHING_SELECTED


def test_a_row_action_right_after_a_new_selection_acts_on_that_row(qtbot, page):
    """The 150 ms debounce is flushed first: the pane holds the new row."""
    pane = FakePane()
    page.set_preview_widget(pane)
    hits = search(qtbot, page, key=KEY_SINT)
    other = next(h for h in hits if h != page.selected_hit())
    page.view.select_hit(other)
    page.shortcuts["Ctrl+C"].activated.emit()  # no wait
    assert pane.current_hit() == other
    assert pane.calls == ["copy"]


def test_enter_and_drag_on_a_group_row_do_nothing(qtbot, page):
    pane = FakePane()
    page.set_preview_widget(pane)
    search(qtbot, page, fdi=FDI_A)
    _click_group_row(qtbot, page)
    page.view.setFocus()
    qtbot.keyClick(page.view, Qt.Key.Key_Return)
    dragged = []
    page.view.drag_provider = dragged.append
    page.view.startDrag(Qt.DropAction.CopyAction)
    assert pane.calls == [] and dragged == []


def test_a_recent_search_of_a_disabled_environment_is_not_run_elsewhere(qtbot, page, window):
    queries = []
    page.presenter.search = queries.append
    page.apply_recent(Recent("prod", FDI_A, "", "exact"))
    assert queries == []
    assert window.statuses[-1] == strings.SEARCH_RECENT_ENV_DISABLED.format(env="prod")


def test_dragging_the_pane_s_call_reuses_its_loaded_text(qtbot, page, fake_core):
    hits = search(qtbot, page, fdi=FDI_A)
    pane = page.preview_widget()
    qtbot.waitUntil(lambda: pane.body_text() != "", timeout=5000)
    reads = []
    original = fake_core.index.read_body
    fake_core.index.read_body = lambda hit: reads.append(hit) or original(hit)
    path = page.prepare_drag_file(pane.current_hit())
    assert reads == [], "the body on screen is not read again"
    assert path.read_text(encoding="utf-8") == pane.body_text()
    assert hits


# ------------------------------------------------- invalid log folder ------

def test_an_invalid_log_folder_shows_a_banner_to_impostazioni(fake_core, make_page, window, tmp_path):
    """Final review #1: Ricerca says the log folder is not valid and offers
    the way to fix it; saving a good folder hides it again."""
    fake_core.config.config = dataclasses.replace(fake_core.config.config, mirror_root=Path("rel"))
    page = make_page()
    page.show()

    assert page.mirror_banner.isVisible()
    page.mirror_banner.button.click()
    assert window.shown[-1] == "settings"

    fake_core.config.config = dataclasses.replace(fake_core.config.config, mirror_root=tmp_path / "logs")
    page.on_config_changed(fake_core.config.load())
    assert not page.mirror_banner.isVisible()


def test_a_valid_log_folder_shows_no_banner_on_ricerca(page):
    page.show()
    assert not page.mirror_banner.isVisible()
