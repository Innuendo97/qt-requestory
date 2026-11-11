"""Ricerca's "Genera documento": what it acts on and what it listens to.

* What is generated is exactly what the user sees selected: a group
  collapsed over selected calls takes them out of the selection, and a
  group row (nothing else selected) still means all its calls.
* The tooltip that warns about the Genera tab's edited headers is right when
  the user comes back from that tab.
* A Ricerca page that is gone hears nothing more from the long-lived runner
  and Genera page.

The real shell (``MainWindow`` on the fake core). Synthetic data only.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import shiboken6
from PySide6.QtCore import QCoreApplication, QEvent, QItemSelectionModel

from qtrequestory.ui import strings
from qtrequestory.ui.main_window import MainWindow
from qtrequestory.ui.pages.search_generate import GENERATE_SHORTCUT
from qtrequestory.ui.pages.search_page import SearchPage
from qtrequestory.ui.workers import GENERA_JOB
from tests.conftest import KEY_SINT
from tests.ui.test_search_page import search

WAIT_MS = 8000
SELECT = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows


@pytest.fixture
def window(qtbot, fake_core, runner, tmp_path: Path) -> MainWindow:
    win = MainWindow(fake_core, runner)
    qtbot.addWidget(win)
    win.resize(1300, 800)
    win.show()
    dest = tmp_path / "dest"
    dest.mkdir()
    win.page("genera").presenter.set_destination(dest)
    return win


@pytest.fixture
def page(window):
    window.show_page("search")
    return window.page("search")


def _two_groups(qtbot, page):
    """A search grouped by FDI; one call of each of its first two groups."""
    hits = search(qtbot, page, key=KEY_SINT)
    page.set_grouped(True)
    fdis = list(dict.fromkeys(h.fdi for h in hits))
    assert len(fdis) >= 2
    first = next(h for h in hits if h.fdi == fdis[0])
    second = next(h for h in hits if h.fdi == fdis[1])
    return first, second


# -- exactly what is seen selected ---------------------------------------------------------------

def test_calls_selected_in_a_group_then_collapsed_are_not_sent(qtbot, window, page, fake_core):
    view, model = page.view, page.model
    hidden, shown = _two_groups(qtbot, page)
    view.setCurrentIndex(model.index_of(hidden))
    view.collapse(model.group_index(hidden.fdi))
    assert view.selected_hits() == []  # off screen: no longer selected
    view.selectionModel().select(model.index_of(shown), SELECT)  # a later Ctrl+click
    assert page.generate.hits() == [shown]
    assert page.generate.button.text() == strings.GENERA_CALLS_ACTION_ONE
    page.generate.generate("svil")
    genera = window.page("genera")
    qtbot.waitUntil(lambda: genera.report is not None and not genera.is_running(), timeout=WAIT_MS)
    (request,) = fake_core.officina.requests
    assert request.payload == json.loads(fake_core.index.bodies[shown.entry_id])
    view.expand(model.group_index(hidden.fdi))
    assert hidden not in view.selected_hits()  # expanding again does not bring it back


def test_select_all_after_a_collapse_takes_only_the_calls_on_screen(qtbot, page):
    view, model = page.view, page.model
    hidden, _shown = _two_groups(qtbot, page)
    group = model.group_index(hidden.fdi)
    view.collapse(group)
    view.selectAll()
    selected = view.selected_hits()
    assert selected and not set(view.group_hits(group)) & set(selected)
    assert page.generate.hits() == selected


def test_a_collapsed_group_row_still_means_all_its_calls(qtbot, page):
    view, model = page.view, page.model
    hidden, _shown = _two_groups(qtbot, page)
    group = model.group_index(hidden.fdi)
    view.setCurrentIndex(model.index_of(hidden))
    view.collapse(group)
    view.setCurrentIndex(group)  # what a click on the group row does: nothing selected
    calls = view.group_hits(group)
    assert view.selected_hits() == [] and page.generate.hits() == calls
    assert page.generate.button.text() == page.generate.label(len(calls))


# -- the tooltip about Genera's headers ------------------------------------------------------------

def test_the_headers_warning_is_there_when_coming_back_from_genera(qtbot, window, page):
    search(qtbot, page, key=KEY_SINT)
    button = page.generate.button
    plain = strings.GENERA_CALLS_TIP.format(shortcut=GENERATE_SHORTCUT)
    assert button.toolTip() == plain
    window.show_page("genera")
    genera = window.page("genera")
    genera.header_table.add_row("X-Test", "1")  # an edit on the tab, as the user makes it
    window.show_page("search")  # no selection change
    assert button.toolTip() == f"{plain}\n{strings.GENERA_CALLS_HEADERS_EDITED.format(m=1)}"
    window.show_page("genera")
    genera.reset_headers_button.click()
    window.show_page("search")
    assert button.toolTip() == plain


# -- a page that is gone hears nothing more ---------------------------------------------------------

def test_a_deleted_search_page_hears_nothing_from_the_runner_or_genera(qtbot, window, fake_core, runner):
    other = SearchPage(fake_core, runner, window)
    # its own start-up jobs (keys, index plan) answer first: only Genera's links are under test
    with qtbot.waitSignals([other.presenter.template_keys_ready, other.presenter.index_pending],
                           timeout=WAIT_MS):
        pass
    genera = window.page("genera")
    other.generate.refresh()
    assert other.generate._connected is genera  # listening to the long-lived Genera page
    generate = other.generate
    other.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not shiboken6.isValid(generate)
    # with slots that outlived their page, each of these raised "already deleted" in a slot
    runner.job_finished.emit(GENERA_JOB, True)
    genera.running_changed.emit(False)
    window.page("search").generate.refresh()  # the window's own page still works
