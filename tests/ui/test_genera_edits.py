"""What the user is still doing when a run starts: a header cell open in
edit mode, the second release of a double click in the package list.

A header cell's editor commits only when it closes; a run started before
that (Ctrl+Invio from inside the cell, Riprova, Ricerca's "Genera documento")
must send what the cell shows, never the value it had before. Driven like a
user would, on the fake core (see ``test_genera_page``). Synthetic data only.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractItemView, QApplication, QLineEdit

from qtrequestory.ui.pages.genera_packages import PackageList
from qtrequestory.ui.pages.genera_page import GeneraPage
from tests.conftest import FDI_C, KEY_EMAIL, KEY_SINT
from tests.ui.test_genera_page import FakeWindow, _finish, _generate, _type_keys

WAIT_MS = 8000


@pytest.fixture
def page(qtbot, fake_core, runner, tmp_path: Path) -> GeneraPage:
    dest = tmp_path / "dest"
    dest.mkdir()
    page = GeneraPage(fake_core, runner, FakeWindow())
    qtbot.addWidget(page)
    page.resize(1366, 700)
    page.show()
    page.presenter.set_destination(dest)
    page.source_combo.setCurrentText("coll")  # the fake's calls are in coll's logs
    return page


def _sent(fake_core, name: str) -> list[str | None]:
    """The value of header ``name`` in every request sent, in order."""
    return [next((v for k, v in r.headers.items() if k.casefold() == name.casefold()), None)
            for r in fake_core.officina.requests]


def _typing_a_new_header(qtbot, page: GeneraPage, name: str, value: str) -> QLineEdit:
    """[Aggiungi], the name, Tab, the value typed — and the value cell still open."""
    if not page.header_table.isVisible():
        qtbot.mouseClick(page.headers_toggle, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(page.add_header_button, Qt.MouseButton.LeftButton)
    editor = QApplication.focusWidget()
    assert isinstance(editor, QLineEdit)
    QTest.keyClicks(editor, name)
    QTest.keyClick(editor, Qt.Key.Key_Tab)  # the name is committed, the value cell opens
    editor = QApplication.focusWidget()
    assert isinstance(editor, QLineEdit)
    QTest.keyClicks(editor, value)
    assert page.header_table.state() == QAbstractItemView.State.EditingState
    return editor


# -- an open header cell is committed before the request is built ----------------------------

def test_ctrl_enter_inside_an_open_header_cell_sends_what_it_shows(qtbot, page, fake_core):
    _type_keys(qtbot, page, KEY_SINT)
    editor = _typing_a_new_header(qtbot, page, "X-Prova", "active")
    QTest.keyClick(editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    _finish(qtbot, page)
    assert _sent(fake_core, "X-Prova") == ["active"]
    assert ("X-Prova", "active") in page.presenter.header_rows


def test_an_open_name_cell_is_committed_and_its_problem_stops_the_run(qtbot, page, fake_core):
    _type_keys(qtbot, page, KEY_SINT)
    qtbot.mouseClick(page.headers_toggle, Qt.MouseButton.LeftButton)
    row = page.header_table.rowCount()
    qtbot.mouseClick(page.add_header_button, Qt.MouseButton.LeftButton)
    editor = QApplication.focusWidget()
    QTest.keyClicks(editor, "X Prova")  # not a header name: the row has a problem
    QTest.keyClick(editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    assert page.header_table.text(row, page.header_table.COL_NAME) == "X Prova"
    assert not page.is_running() and fake_core.officina.requests == []
    assert not page.start_button.isEnabled() and page.problem_label.isVisible()


def test_riprova_with_an_open_header_cell_sends_what_it_shows(qtbot, page, fake_core):
    fake_core.officina.set_response_for(KEY_EMAIL, b"guasto", 500)
    _type_keys(qtbot, page, f"{KEY_SINT} {KEY_EMAIL}")
    first = _generate(qtbot, page)
    fake_core.officina.set_response_for(KEY_EMAIL, None)
    _typing_a_new_header(qtbot, page, "X-Prova", "riprova")
    page.retry()
    qtbot.waitUntil(lambda: page.report is not None and page.report is not first
                    and not page.is_running(), timeout=WAIT_MS)
    assert _sent(fake_core, "X-Prova") == [None, None, "riprova"]


def test_ricerca_calls_with_an_open_header_cell_send_what_it_shows(qtbot, page, fake_core):
    hit = next(h for h in fake_core.index.hits if h.fdi == FDI_C and h.template_key == KEY_SINT)
    _typing_a_new_header(qtbot, page, "X-Prova", "ricerca")
    assert page.generate_calls([hit], "svil") == (True, "")
    _finish(qtbot, page)
    assert _sent(fake_core, "X-Prova") == ["ricerca"]


# -- the package list: a double click whose second release lands off the rows -----------------

def _send(widget, kind: QEvent.Type, point: QPoint) -> None:
    pos = QPointF(point)
    buttons = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton
    QApplication.sendEvent(widget, QMouseEvent(kind, pos, widget.mapToGlobal(pos), Qt.MouseButton.LeftButton,
                                               buttons, Qt.KeyboardModifier.NoModifier))


def test_a_double_click_released_off_the_rows_does_not_swallow_the_next_click(qtbot):
    packages = PackageList()
    qtbot.addWidget(packages)
    packages.resize(360, 300)  # two 30 px rows: room under them
    packages.fill([("111_LUCE_FIX", 7), ("222_GAS_IND", 5)])
    packages.show()
    qtbot.waitExposed(packages)
    toggled: list[tuple[str, bool]] = []
    packages.toggled.connect(lambda name, on: toggled.append((name, on)))
    viewport = packages.viewport()
    first = packages.visualItemRect(packages.item(0)).center()
    below = QPoint(first.x(), packages.visualItemRect(packages.item(1)).bottom() + 60)
    assert not packages.indexAt(below).isValid()
    for kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease,
                 QEvent.Type.MouseButtonDblClick):
        _send(viewport, kind, first)
    _send(viewport, QEvent.Type.MouseButtonRelease, below)  # the pointer slipped off the rows
    assert toggled == [("111_LUCE_FIX", True)]  # one tick for the double click
    second = packages.visualItemRect(packages.item(1)).center()
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=second)
    assert toggled == [("111_LUCE_FIX", True), ("222_GAS_IND", True)]
    assert packages.item(1).checkState() == Qt.CheckState.Checked
