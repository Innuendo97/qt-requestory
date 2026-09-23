"""The real shell with the real pages: what the user gets when the app starts.

Every page has its own tests, each against a hand-built page and, for the
Ricerca page, a stub preview pane. That is exactly how the preview pane came
to be *never installed* in the application while every test was green: the
pane was tested alone, the page was tested with a stand-in, and nothing built
the two together the way ``MainWindow`` does. These tests do — ``MainWindow``
with the real ``PAGES`` registry and the fake core — and assert what a user
would notice first.
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from qtrequestory.ui import strings
from qtrequestory.ui.main_window import MainWindow
from qtrequestory.ui.pages.preview_pane import PreviewPane

from tests.conftest import FDI_A
from tests.fakes.fake_core import DAYS

BODY_PREFIX = '{\n    "documents": ['


@pytest.fixture
def window(qtbot, fake_core, runner):
    win = MainWindow(fake_core, runner)  # the real PAGES
    qtbot.addWidget(win)
    win.show()
    win.activateWindow()
    qtbot.waitUntil(lambda: QApplication.activeWindow() is win, timeout=5000)
    return win


@pytest.fixture
def search_page(window):
    return window.page("search")


def run_search(qtbot, page, fdi: str = FDI_A) -> list:
    page.form.set_fdi(fdi)
    page.form.set_custom_range(min(DAYS) - timedelta(days=1), max(DAYS) + timedelta(days=1))
    with qtbot.waitSignal(page.presenter.results_ready, timeout=5000):
        page.run_search()
    return page.model.hits()


def wait_for_body(qtbot, page) -> str:
    pane = page.preview_widget()
    qtbot.waitUntil(lambda: pane.body_text() != "", timeout=5000)
    return pane.body_text()


def test_the_search_page_of_the_real_shell_has_a_preview_pane(search_page):
    assert isinstance(search_page.preview_widget(), PreviewPane)
    assert not search_page.preview_placeholder.isVisibleTo(search_page.preview_slot)


def test_the_body_actions_of_the_context_menu_are_enabled(qtbot, search_page):
    hits = run_search(qtbot, search_page)
    wait_for_body(qtbot, search_page)
    menu = search_page.build_context_menu(hits[0])
    first_three = [a for a in menu.actions() if not a.isSeparator()][:3]
    assert [a.text() for a in first_three] == [
        search_page.preview_widget().open_label(), strings.BTN_SAVE_AS,
        strings.SEARCH_MENU_COPY_JSON]
    assert all(a.isEnabled() for a in first_three)
    menu.deleteLater()


def test_a_double_click_on_a_row_opens_the_body_in_the_editor(qtbot, search_page, fake_core):
    run_search(qtbot, search_page)
    wait_for_body(qtbot, search_page)
    # The tree's first row is an FDI group (a double click only folds it): the
    # double click goes to the selected call, as a user's would.
    search_page.view.doubleClicked.emit(search_page.view.currentIndex())
    assert len(fake_core.extract.opened) == 1
    opened = fake_core.extract.opened[0][0]
    assert opened.read_text(encoding="utf-8").startswith(BODY_PREFIX)


def test_ctrl_c_on_the_table_copies_the_pretty_json_body(qtbot, search_page):
    run_search(qtbot, search_page)
    body = wait_for_body(qtbot, search_page)
    QGuiApplication.clipboard().setText("")
    search_page.view.setFocus()
    qtbot.keyClick(search_page.view, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert QGuiApplication.clipboard().text() == body
    assert body.startswith(BODY_PREFIX)


def test_ctrl_c_in_the_fdi_field_still_copies_the_selected_text(qtbot, search_page):
    run_search(qtbot, search_page)
    wait_for_body(qtbot, search_page)
    search_page.shortcuts["Ctrl+L"].activated.emit()  # the FDI back into the text, selected
    edit = search_page.form.omnibox.edit
    assert edit.hasFocus() and edit.selectedText() == FDI_A
    QGuiApplication.clipboard().setText("")
    qtbot.keyClick(edit, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert QGuiApplication.clipboard().text() == FDI_A


def test_ctrl_c_on_a_selection_in_the_body_copies_only_the_selection(qtbot, search_page):
    run_search(qtbot, search_page)
    wait_for_body(qtbot, search_page)
    editor = search_page.preview_widget().editor
    editor.setFocus()
    cursor = editor.textCursor()
    cursor.setPosition(0)
    cursor.setPosition(1, cursor.MoveMode.KeepAnchor)
    editor.setTextCursor(cursor)
    QGuiApplication.clipboard().setText("")
    qtbot.keyClick(editor, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert QGuiApplication.clipboard().text() == "{"


def test_ctrl_o_on_the_table_opens_the_body(qtbot, search_page, fake_core):
    run_search(qtbot, search_page)
    wait_for_body(qtbot, search_page)
    search_page.view.setFocus()
    qtbot.keyClick(search_page.view, Qt.Key.Key_O, Qt.KeyboardModifier.ControlModifier)
    assert len(fake_core.extract.opened) == 1


def test_ctrl_shift_o_in_the_pane_fires_once(qtbot, search_page, fake_core):
    """The page owns the binding; a second one in the pane would be ambiguous
    and Qt fires neither."""
    run_search(qtbot, search_page)
    wait_for_body(qtbot, search_page)
    editor = search_page.preview_widget().editor
    editor.setFocus()
    qtbot.keyClick(editor, Qt.Key.Key_O,
                   Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    assert len(fake_core.extract.folders) == 1
