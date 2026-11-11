"""The Genera tab's redesign (two panes) and the three defects the owner saw
in the real app: an English confirmation, invisible unticked boxes in the
package list, and a header table whose last row was cut in half.

Driven like a user would, on the fake core (see ``test_genera_page``).
Synthetic data only.
"""
from __future__ import annotations

import threading
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QColor, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractItemView, QApplication, QLineEdit, QStyle, QStyleOptionViewItem

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import NO_PACKAGE
from qtrequestory.ui.pages import officina_dialogs
from qtrequestory.ui.pages.genera_outcomes import COL_KEY, COL_REASON, COL_STATUS
from qtrequestory.ui.pages.genera_packages import PackageList
from qtrequestory.ui.pages.genera_page import GeneraPage
from tests.conftest import FDI_C, KEY_CTE, KEY_EMAIL, KEY_SINT
from tests.ui.test_genera_page import FakeWindow, _finish, _generate, _held_until, _on_screen, _type_keys

WAIT_MS = 8000


@pytest.fixture
def window() -> FakeWindow:
    return FakeWindow()


@pytest.fixture
def page(qtbot, fake_core, runner, window, tmp_path: Path) -> GeneraPage:
    dest = tmp_path / "dest"
    dest.mkdir()
    page = GeneraPage(fake_core, runner, window)
    qtbot.addWidget(page)
    page.resize(1366, 700)  # the tab's share of a 1366×768 screen
    page.show()
    page.presenter.set_destination(dest)
    page.source_combo.setCurrentText("coll")  # the fake's calls are in coll's logs
    return page


def _elenco(tmp_path: Path, packages: int = 42) -> Path:
    csv = tmp_path / "elenco.csv"
    csv.write_bytes(("Template key;a;b;c;package name\r\n" + "".join(
        f"MOD_TEST_{i:03d};;;;{i % packages:02d}_PKG\r\n" for i in range(packages * 2))).encode("cp1252"))
    return csv


# -- defect 1: the confirmation is Italian, says what it does, defaults to the safe button --------

def test_the_confirmation_box_says_what_each_button_does(qtbot):
    box, yes = officina_dialogs.confirm_box(None, "Generare 56 documenti?", "Partono 56 chiamate.",
                                            yes="Genera 56 documenti", no=strings.BTN_CANCEL)
    qtbot.addWidget(box)
    labels = {b.text() for b in box.buttons()}
    assert labels == {"Genera 56 documenti", strings.BTN_CANCEL}
    assert yes.text() == "Genera 56 documenti"
    assert box.defaultButton().text() == strings.BTN_CANCEL  # Enter does not send 56 calls
    assert box.escapeButton() is box.defaultButton()


def test_a_plain_confirmation_is_italian_too(qtbot):
    box, yes = officina_dialogs.confirm_box(None, "Titolo", "Testo")
    qtbot.addWidget(box)
    assert {b.text() for b in box.buttons()} == {strings.BTN_YES, strings.BTN_NO}
    assert box.defaultButton().text() == strings.BTN_NO and yes.text() == strings.BTN_YES


def test_genera_asks_with_its_own_words(qtbot, page, monkeypatch):
    asked: list[dict] = []
    monkeypatch.setattr(officina_dialogs, "confirm",
                        lambda _p, title, text, **kw: asked.append(dict(kw, title=title)) or False)
    _type_keys(qtbot, page, " ".join(f"MOD_TEST_{i:02d}" for i in range(21)))
    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
    (kw,) = asked
    assert kw["yes"] == strings.GENERA_START_N.format(n=21) and kw["no"] == strings.BTN_CANCEL


def test_ricerca_generation_asks_with_the_same_words(qtbot, page, fake_core, monkeypatch):
    import dataclasses

    asked: list[dict] = []
    monkeypatch.setattr(officina_dialogs, "confirm", lambda _p, _t, _x, **kw: asked.append(kw) or False)
    base = next(h for h in fake_core.index.hits if h.fdi == FDI_C and h.template_key == KEY_SINT)
    hits = [dataclasses.replace(base, seq=base.seq + n) for n in range(21)]
    assert page.generate_calls(hits, "svil") == (False, "")
    assert asked == [{"yes": strings.GENERA_START_N.format(n=21), "no": strings.BTN_CANCEL}]


# -- defect 2: an unticked box is visible on the dark theme --------------------------------------

def _max_contrast(image, rect: QRect, background: QColor) -> float:
    def lum(c: QColor) -> float:
        out = []
        for v in (c.redF(), c.greenF(), c.blueF()):
            out.append(v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4)
        return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]

    bg = lum(background)
    best = 1.0
    for x in range(rect.left(), rect.right()):
        for y in range(rect.top(), rect.bottom()):
            fg = lum(QColor(image.pixel(x, y)))
            hi, lo = max(fg, bg), min(fg, bg)
            best = max(best, (hi + 0.05) / (lo + 0.05))
    return best


@pytest.mark.parametrize("mode", [theme.Mode.DARK, theme.Mode.LIGHT])
def test_an_unticked_package_has_a_visible_box(qtbot, themed, mode):
    theme.apply(themed, mode)
    packages = PackageList()
    qtbot.addWidget(packages)
    packages.resize(360, 200)
    packages.fill([("111_LUCE_FIX", 7), ("222_GAS_IND", 5)])
    packages.show()
    qtbot.waitExposed(packages)
    image = packages.viewport().grab().toImage()
    box = _indicator_rect(packages, packages.item(0))  # the box alone, not the name beside it
    assert box.width() >= 10 and box.height() >= 10
    assert _max_contrast(image, box, QColor(theme.tokens().surface)) >= 3.0


def _indicator_rect(view, item) -> QRect:
    """Where the style draws ``item``'s check box (what the delegate draws too)."""
    option = QStyleOptionViewItem()
    option.initFrom(view.viewport())
    option.rect = view.visualItemRect(item)
    option.features |= QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
    option.checkState = item.checkState()
    style = view.style()
    return style.subElementRect(QStyle.SubElement.SE_ItemViewItemCheckIndicator, option, view)


def test_item_views_style_their_check_indicators():
    qss = theme.build_qss(theme.DARK)
    rule = next(body for selectors, body in _rules(qss) if "QListView::indicator" in selectors)
    assert f"border: 1px solid {theme.DARK.muted}" in rule
    assert any("QTreeView::indicator" in selectors for selectors, _b in _rules(qss))


def _rules(qss: str) -> list[tuple[str, str]]:
    import re

    return [(m.group(1), m.group(2)) for m in re.finditer(r"([^{}]+)\{([^}]*)\}", qss)]


# -- defect 3: whole header rows, and "Aggiungi" lands in the new name cell ------------------------

def _row_inside(table, row: int, column: int) -> bool:
    rect = table.visualRect(table.model().index(row, column))
    return rect.isValid() and table.viewport().rect().contains(rect)


def test_the_header_table_never_cuts_its_last_row(qtbot, page):
    qtbot.mouseClick(page.headers_toggle, Qt.MouseButton.LeftButton)
    table = page.header_table
    assert table.isVisible() and table.rowCount() >= 4
    last = table.rowCount() - 1
    assert _row_inside(table, last, table.COL_NAME)
    shown = sum(table.rowHeight(r) for r in range(table.rowCount()))
    assert table.viewport().height() == shown  # as tall as its rows: no half row, no gap


def test_a_long_header_table_scrolls_by_whole_rows(qtbot, page):
    qtbot.mouseClick(page.headers_toggle, Qt.MouseButton.LeftButton)
    table = page.header_table
    for n in range(12):
        table.add_row(f"X-Prova-{n}", "1")
    qtbot.wait(20)
    height = table.rowHeight(0)
    assert table.viewport().height() % height == 0  # whole rows only
    assert _row_inside(table, table.rowCount() - 1, table.COL_NAME)  # the newest is on screen


def test_aggiungi_opens_the_new_name_cell_for_typing(qtbot, page):
    qtbot.mouseClick(page.headers_toggle, Qt.MouseButton.LeftButton)
    table = page.header_table
    before = table.rowCount()
    qtbot.mouseClick(page.add_header_button, Qt.MouseButton.LeftButton)
    row = before
    assert table.rowCount() == before + 1
    assert _row_inside(table, row, table.COL_NAME)
    assert table.state() == QAbstractItemView.State.EditingState
    editor = QApplication.focusWidget()
    assert isinstance(editor, QLineEdit) and table.viewport().isAncestorOf(editor)
    assert (table.currentRow(), table.currentColumn()) == (row, table.COL_NAME)
    assert _on_screen(page, editor)  # the setup pane scrolled to it too
    QTest.keyClicks(editor, "IMEL")
    QTest.keyClick(editor, Qt.Key.Key_Tab)
    assert table.text(row, table.COL_NAME) == "IMEL"


# -- the layout: two panes, nothing to scroll for the button or the outcome -------------------------

@pytest.mark.parametrize("mode", ["keys", "elenco", "fdi"])
def test_wide_window_has_setup_and_results_side_by_side(qtbot, page, tmp_path, mode):
    page.presenter.set_mode(mode)
    page.presenter.load_elenco(_elenco(tmp_path))
    page.presenter.set_packages_checked(["01_PKG", "02_PKG"], True)
    qtbot.wait(20)
    assert page.is_wide()
    setup, results = page.setup, page.results
    assert results.mapTo(page, QPoint(0, 0)).x() >= setup.mapTo(page, QPoint(0, 0)).x() + setup.width()
    for widget in (page.start_button, page.zip_box, page.html_box, page.source.mode_buttons[mode],
                   results.empty):
        assert _on_screen(page, widget), widget
    if mode == "elenco":
        assert page.source.package_list.height() >= 200  # a list, not a slot


def test_narrow_window_stacks_the_panes_and_keeps_the_button(qtbot, page):
    page.resize(900, 700)
    qtbot.wait(20)
    assert not page.is_wide()
    top = page.setup.mapTo(page, QPoint(0, 0)).y() + page.setup.height()
    assert page.results.mapTo(page, QPoint(0, 0)).y() >= top
    assert _on_screen(page, page.start_button) and _on_screen(page, page.results.empty)
    page.resize(1366, 700)
    qtbot.wait(20)
    assert page.is_wide()


def test_results_stay_on_screen_after_a_run(qtbot, page, fake_core):
    fake_core.officina.set_response_for(KEY_EMAIL, b"guasto", 500)
    _type_keys(qtbot, page, f"{KEY_SINT} {KEY_EMAIL} MOD_TEST_ASSENTE")
    _generate(qtbot, page)
    qtbot.wait(20)
    assert _on_screen(page, page.results.table) and _on_screen(page, page.results.chips)
    assert _on_screen(page, page.results.retry_button) and _on_screen(page, page.results.open_folder_button)


def test_the_empty_results_say_what_will_happen(qtbot, page):
    assert strings.GENERA_RESULTS_EMPTY_TITLE in page.results.empty.text()
    _type_keys(qtbot, page, KEY_SINT)
    text = page.results.empty.text()
    assert "svil" in text and "coll" in text and NO_PACKAGE in text


# -- results: chips that filter, progress at the top, rows that open --------------------------------

def test_outcome_chips_count_and_filter(qtbot, page, fake_core):
    fake_core.officina.set_response_for(KEY_EMAIL, b"guasto", 500)
    _type_keys(qtbot, page, f"{KEY_SINT} {KEY_CTE} {KEY_EMAIL} MOD_TEST_ASSENTE")
    _generate(qtbot, page)
    chips = page.results.chips
    # only what occurred, in order; then what Riprova sends again (two kinds here)
    assert chips.shown() == ["all", "ok", "no_call", "failed", "retry"]
    assert chips.chip("ok").text().endswith(strings.GENERA_SUM_OK.format(n=2))
    qtbot.mouseClick(chips.chip("failed"), Qt.MouseButton.LeftButton)
    assert [r[COL_KEY] for r in page.results.visible_rows()] == [KEY_EMAIL]
    qtbot.mouseClick(chips.chip("no_call"), Qt.MouseButton.LeftButton)
    assert [r[COL_KEY] for r in page.results.visible_rows()] == ["MOD_TEST_ASSENTE"]
    qtbot.mouseClick(chips.chip("all"), Qt.MouseButton.LeftButton)
    assert len(page.results.visible_rows()) == 4


# (what a filter does across runs, and the chip of what Riprova sends: test_genera_results)


def test_progress_is_at_the_top_of_the_results_while_running(qtbot, page, fake_core):
    release = threading.Event()
    fake_core.officina.set_responder(_held_until(release))
    _type_keys(qtbot, page, " ".join([KEY_SINT, KEY_EMAIL, KEY_CTE, "MOD_TEST_X1"]))
    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: len(fake_core.officina.requests) == 3, timeout=WAIT_MS)
    strip = page.results.progress
    assert _on_screen(page, strip) and _on_screen(page, page.progress_bar)
    assert strip.mapTo(page, QPoint(0, 0)).y() < page.results.stack.mapTo(page, QPoint(0, 0)).y()
    release.set()
    _finish(qtbot, page)
    assert not strip.isVisible()


def _ok_row(page) -> int:
    return next(r for r, o in enumerate(page.results.outcomes()) if o.status == "ok")


def _double_click_at(widget, point: QPoint) -> None:
    """What Windows delivers for a double click (QTest's own sends no
    double-click event an item view acts on): press, release, double-click, release."""
    pos = QPointF(point)
    for kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease,
                 QEvent.Type.MouseButtonDblClick, QEvent.Type.MouseButtonRelease):
        buttons = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton
        QApplication.sendEvent(widget, QMouseEvent(kind, pos, widget.mapToGlobal(pos), Qt.MouseButton.LeftButton,
                                                   buttons, Qt.KeyboardModifier.NoModifier))


def test_double_click_on_a_generated_row_opens_the_document(qtbot, page, fake_core):
    _type_keys(qtbot, page, f"{KEY_SINT} MOD_TEST_ASSENTE")
    report = _generate(qtbot, page)
    table = page.results.table
    row = _ok_row(page)
    rect = table.visualRect(table.model().index(row, COL_KEY))
    _double_click_at(table.viewport(), rect.center())
    assert fake_core.extract.files == [report.outcomes[row].files[0]]
    missing = 1 - row
    table.setCurrentCell(missing, COL_KEY)
    table.setFocus()
    QTest.keyClick(table, Qt.Key.Key_Return)  # no document: nothing is opened
    assert len(fake_core.extract.files) == 1
    table.setCurrentCell(row, COL_KEY)
    QTest.keyClick(table, Qt.Key.Key_Return)
    assert len(fake_core.extract.files) == 2


def test_the_row_menu_opens_shows_and_copies(qtbot, page, fake_core, window):
    fake_core.officina.set_response_for(KEY_EMAIL, b"guasto", 500)
    _type_keys(qtbot, page, f"{KEY_SINT} {KEY_EMAIL}")
    report = _generate(qtbot, page)
    ok, failed = report.outcomes
    menu = page.results.menu_for_row(0)
    actions = {a.text(): a for a in menu.actions() if not a.isSeparator()}
    assert list(actions) == [strings.GENERA_ROW_OPEN, strings.GENERA_ROW_FOLDER,
                             strings.GENERA_ROW_COPY_KEY, strings.GENERA_ROW_COPY_REASON]
    assert not actions[strings.GENERA_ROW_COPY_REASON].isEnabled()  # nothing went wrong
    actions[strings.GENERA_ROW_FOLDER].trigger()
    assert fake_core.extract.folders == [ok.files[0].parent]
    menu = page.results.menu_for_row(1)
    actions = {a.text(): a for a in menu.actions() if not a.isSeparator()}
    assert not actions[strings.GENERA_ROW_OPEN].isEnabled()
    actions[strings.GENERA_ROW_COPY_REASON].trigger()
    assert QApplication.clipboard().text() == failed.reason
    assert page.results.table.item(1, COL_REASON).text() == failed.reason
    assert window.toasts[-1][0] == strings.GENERA_ROW_COPIED


def test_the_tab_says_nothing_in_a_toast_while_it_is_on_screen(qtbot, page, window):
    _type_keys(qtbot, page, KEY_SINT)
    _generate(qtbot, page)
    assert window.toasts == []  # the results pane says it
    assert page.results.summary.text().startswith(strings.GENERA_DONE_TITLE)


# -- the package list ---------------------------------------------------------------------------

def test_package_rows_are_tall_and_toggle_on_a_click_anywhere(qtbot, page, tmp_path):
    page.presenter.set_mode("elenco")
    page.presenter.load_elenco(_elenco(tmp_path, packages=6))
    packages = page.source.package_list
    first = packages.item(0)
    rect = packages.visualItemRect(first)
    assert rect.height() >= 26
    QTest.mouseClick(packages.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(rect.right() - 60, rect.center().y()))
    assert page.presenter.checked_packages == {"00_PKG"}
    assert page.source.elenco_summary.text() == strings.GENERA_ELENCO_SUMMARY.format(chosen=1, total=6, keys=2)
    packages.setFocus()
    packages.setCurrentRow(1)
    QTest.keyClick(packages, Qt.Key.Key_Space)
    assert page.presenter.checked_packages == {"00_PKG", "01_PKG"}
    assert page.start_button.text() == strings.GENERA_START_N.format(n=4)


# -- where, headers, options ------------------------------------------------------------------------

def test_logs_from_another_environment_are_explained_and_revertible(qtbot, page):
    where = page.setup.where
    assert page.presenter.generator == "svil" and page.presenter.source_env == "coll"
    assert where.source_note.isVisible()
    assert where.source_note_text.text() == strings.GENERA_SOURCE_OTHER.format(source="coll", env="svil")
    qtbot.mouseClick(where.follow_button, Qt.MouseButton.LeftButton)
    assert page.presenter.source_env == "svil" and not where.source_note.isVisible()


def test_edited_headers_are_obvious_and_resettable_while_closed(qtbot, page):
    headers = page.setup.headers
    assert not headers.modified_pill.isVisible() and not page.reset_headers_button.isVisible()
    rows = page.presenter.header_rows
    page.header_table.add_row("IMEL", "active")
    assert not page.header_table.isVisible()  # still closed
    assert headers.modified_pill.isVisible()
    assert headers.modified_pill.text() == strings.GENERA_HEADERS_MODIFIED_ONE
    assert page.reset_headers_button.isVisible()
    qtbot.mouseClick(page.reset_headers_button, Qt.MouseButton.LeftButton)
    assert page.presenter.header_rows == rows and not headers.modified_pill.isVisible()


def test_edited_headers_out_of_view_are_recalled_over_the_button(qtbot, page, tmp_path):
    """In Elenco mode on a 768 px screen the Header step is below the fold:
    the footer recalls an edit there, with Mostra and Ripristina."""
    bar = page.action_bar
    page.header_table.add_row("IMEL", "active")
    qtbot.wait(20)
    assert page.setup.headers_in_view() and not bar.headers_reminder.isVisible()  # in view: once is enough
    page.presenter.set_mode("elenco")
    page.presenter.load_elenco(_elenco(tmp_path))
    qtbot.wait(20)
    assert not page.setup.headers_in_view()
    assert _on_screen(page, bar.headers_reminder)
    assert bar.headers_note.text() == strings.GENERA_HEADERS_REMINDER.format(
        modified=strings.GENERA_HEADERS_MODIFIED_ONE)
    qtbot.mouseClick(bar.headers_show, Qt.MouseButton.LeftButton)
    qtbot.wait(20)
    assert page.header_table.isVisible() and page.setup.headers_in_view()
    assert not bar.headers_reminder.isVisible()
    page.setup.scroll.verticalScrollBar().setValue(0)
    qtbot.wait(20)
    assert bar.headers_reminder.isVisible()
    rows = len(page.presenter.header_rows)
    qtbot.mouseClick(bar.headers_reset, Qt.MouseButton.LeftButton)
    assert len(page.presenter.header_rows) == rows - 1 and not bar.headers_reminder.isVisible()


def test_the_panes_never_hold_the_window_wide(qtbot, page, fake_core):
    """The two panes side by side once made the page's minimum width (summary
    + five chips + setup) larger than the width that stacks them: the window
    could not get narrow enough for the single-column layout."""
    from qtrequestory.ui.pages.genera_page import WIDE_MIN

    fake_core.officina.set_response_for(KEY_CTE, b"guasto", 500)
    _type_keys(qtbot, page, f"{KEY_SINT} {KEY_EMAIL} {KEY_CTE} MOD_TEST_ASSENTE")
    _generate(qtbot, page)
    assert page.minimumSizeHint().width() < WIDE_MIN and page.minimumWidth() < WIDE_MIN
    page.resize(WIDE_MIN - 100, 700)
    qtbot.wait(20)
    assert page.width() == WIDE_MIN - 100 and not page.is_wide()
    assert _on_screen(page, page.results.chips) and _on_screen(page, page.start_button)


def test_html_is_called_email(page):
    assert page.html_box.text() == strings.GENERA_HTML and "email" in strings.GENERA_HTML


def test_enter_on_the_focused_button_generates(qtbot, page):
    _type_keys(qtbot, page, KEY_SINT)
    page.start_button.setFocus()
    QTest.keyClick(page.start_button, Qt.Key.Key_Return)
    assert _finish(qtbot, page).outcomes[0].status == "ok"
