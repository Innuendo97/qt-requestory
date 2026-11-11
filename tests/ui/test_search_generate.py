"""Ricerca's "Genera documento": the selected calls, as logged, through Genera.

The real shell (``MainWindow`` on the fake core): Ricerca hands the calls to
the Genera page, whose run goes to the fake core's in-process generator
(every request recorded; nothing is ever launched — ``open_file`` /
``open_folder`` are recorded by the fake). Synthetic data only.
"""
from __future__ import annotations

import dataclasses
import json
import threading
from pathlib import Path

import pytest
from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtTest import QTest

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import GeneratorEndpoint
from qtrequestory.ui.main_window import MainWindow
from qtrequestory.ui.pages.genera_outcomes import report_summary
from qtrequestory.ui.pages.search_generate import GENERATE_SHORTCUT
from tests.conftest import FDI_A, FDI_C, KEY_EMAIL, KEY_SINT
from tests.ui.test_genera_page import _held_until
from tests.ui.test_search_page import search

WAIT_MS = 8000
HTML = b"<!DOCTYPE html>\n<html><body>" + b"<p>MOD_TEST e-mail</p>" * 40 + b"</body></html>"


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
    return window.page("search")


def _select(page, *hits) -> None:
    view, model = page.view, page.model
    view.clearSelection()
    for n, hit in enumerate(hits):
        index = model.index_of(hit)
        flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
        if n == 0:
            view.setCurrentIndex(index)
        else:
            view.selectionModel().select(index, flags)


def _hit(page, fdi: str, key: str):
    return next(h for h in page.model.hits() if h.fdi == fdi and h.template_key == key)


def _finished(qtbot, window):
    genera = window.page("genera")
    qtbot.waitUntil(lambda: genera.report is not None and not genera.is_running(), timeout=WAIT_MS)
    return genera.report


def _two_generators(window, fake_core) -> None:
    cfg = fake_core.config.config
    coll = GeneratorEndpoint("coll", "https://example.invalid/coll/rest/api/submit-job/documentGenerator")
    fake_core.config.config = dataclasses.replace(cfg, officina=dataclasses.replace(
        cfg.officina, generators=[*cfg.officina.generators, coll]))
    window._broadcast_config(None, fake_core.config.config)


def _labels(menu) -> list[str]:
    return [a.text() for a in menu.actions() if not a.isSeparator()]


# -- the entry points --------------------------------------------------------------------------

def test_the_button_follows_the_selection(qtbot, page):
    hits = search(qtbot, page, key=KEY_SINT)
    button = page.generate.button
    assert button.isVisible() and button.isEnabled()  # a call is preselected
    assert button.text() == strings.GENERA_CALLS_ACTION_ONE
    assert page.meta.isAncestorOf(button)
    page.view.clearSelection()
    assert not button.isEnabled() and button.toolTip() == strings.GENERA_CALLS_TIP_NOTHING
    _select(page, hits[0], hits[1])
    assert button.isEnabled() and button.text() == strings.GENERA_CALLS_ACTION_N.format(n=2)


def test_the_tooltip_warns_when_genera_headers_are_edited(qtbot, window, page):
    """The Genera tab's header edits are sent with Ricerca's calls too: say so."""
    hits = search(qtbot, page, key=KEY_SINT)
    button = page.generate.button
    assert button.toolTip() == strings.GENERA_CALLS_TIP.format(shortcut=GENERATE_SHORTCUT)
    genera = window.page("genera").presenter
    genera.activate()
    genera.set_header_rows([*genera.header_rows, ("X-Test", "1")])
    _select(page, hits[0], hits[1])
    assert button.toolTip().endswith(strings.GENERA_CALLS_HEADERS_EDITED.format(m=1))


def test_several_calls_can_be_selected(qtbot, page):
    hits = search(qtbot, page, key=KEY_SINT)
    _select(page, *hits)
    assert page.generate.hits() == page.view.selected_hits() and len(hits) > 2
    assert set(page.generate.hits()) == set(hits)


def test_an_fdi_group_row_means_its_calls(qtbot, page):
    search(qtbot, page, fdi=FDI_C)
    group = page.model.index(0, 0)
    assert page.model.is_group(group)
    page.view.setCurrentIndex(group)  # what a click on the header does: nothing selected
    shown = [page.model.hit_of(page.model.index(r, 0, group)) for r in range(page.model.rowCount(group))]
    assert page.generate.hits() == shown and len(shown) == 4  # FDI_C: four calls in the fake
    assert page.generate.button.text() == strings.GENERA_CALLS_ACTION_N.format(n=4)
    menu = page.generate.group_menu(group)
    assert _labels(menu) == [strings.GENERA_CALLS_ACTION_N.format(n=4)]


def test_the_row_menu_offers_it(qtbot, page):
    hits = search(qtbot, page, fdi=FDI_A)
    menu = page.build_context_menu(hits[0])
    assert strings.GENERA_CALLS_ACTION_ONE in _labels(menu)


def test_a_right_click_inside_a_selection_keeps_it(qtbot, page):
    from qtrequestory.ui.pages.search_actions import context_menu_at

    hits = search(qtbot, page, key=KEY_SINT)
    _select(page, hits[0], hits[1])
    pos = page.view.visualRect(page.model.index_of(hits[1])).center()
    menu = context_menu_at(page, pos)
    assert set(page.view.selected_hits()) == {hits[0], hits[1]}
    assert strings.GENERA_CALLS_ACTION_N.format(n=2) in _labels(menu)
    group = page.model.group_index(hits[0].fdi)
    menu = context_menu_at(page, page.view.visualRect(group).center())
    assert page.view.selected_hits() == []
    assert _labels(menu) == [strings.GENERA_CALLS_ACTION_ONE if len(page.view.group_hits(group)) == 1
                         else strings.GENERA_CALLS_ACTION_N.format(n=len(page.view.group_hits(group)))]


def test_ctrl_g_on_the_results_generates_the_selected_call(qtbot, window, page, fake_core):
    assert GENERATE_SHORTCUT == "Ctrl+G"
    search(qtbot, page, key=KEY_SINT)
    older = _hit(page, FDI_C, KEY_SINT)
    _select(page, older)
    window.activateWindow()
    page.view.setFocus()
    QTest.keyClick(page.view, Qt.Key.Key_G, Qt.KeyboardModifier.ControlModifier)
    _finished(qtbot, window)
    (request,) = fake_core.officina.requests
    assert request.payload == json.loads(fake_core.index.bodies[older.entry_id])


# -- what is sent, what is said -------------------------------------------------------------------

def test_one_call_is_generated_opened_and_announced(qtbot, window, page, fake_core):
    search(qtbot, page, key=KEY_SINT)
    older = _hit(page, FDI_C, KEY_SINT)  # not the newest call of the key
    _select(page, older)
    page.shortcuts[GENERATE_SHORTCUT].activated.emit()
    report = _finished(qtbot, window)
    (request,) = fake_core.officina.requests
    assert request.payload == json.loads(fake_core.index.bodies[older.entry_id])
    (outcome,) = report.outcomes
    pdf = report.run_dir / FDI_C / f"{KEY_SINT}.pdf"
    assert outcome.files == (pdf,) and pdf.is_file()
    assert fake_core.extract.files == [pdf]  # opened with its default application
    assert window.toast.text() == strings.GENERA_CALLS_SAVED.format(name=pdf.name, folder=FDI_C)
    assert window.toast.property("tone") == "ok"
    (button, _second) = window.toast.action_buttons()
    assert button.text() == strings.BTN_OPEN_FOLDER and not _second.isVisible()
    button.click()
    assert fake_core.extract.folders == [pdf.parent]
    assert window.current_page_key() == "search"  # the user stays where they are


def test_a_document_saved_but_not_opened_says_so(qtbot, window, page, fake_core):
    fake_core.extract.open_file_error = OSError("nessun programma associato")
    search(qtbot, page, key=KEY_SINT)
    _select(page, _hit(page, FDI_C, KEY_SINT))
    page.generate.generate("svil")
    (outcome,) = _finished(qtbot, window).outcomes
    pdf = outcome.files[0]
    assert pdf.is_file() and fake_core.extract.files == [pdf]  # saved, and the open was tried
    assert window.toast.text() == strings.GENERA_CALLS_SAVED_NOT_OPENED.format(name=pdf.name)
    assert window.toast.property("tone") == "ok"  # the document is there all the same
    (button, _second) = window.toast.action_buttons()
    assert button.text() == strings.BTN_OPEN_FOLDER
    button.click()
    assert fake_core.extract.folders == [pdf.parent]


def test_interrompi_stops_a_run_started_from_ricerca(qtbot, window, page, fake_core):
    release = threading.Event()
    fake_core.officina.set_responder(_held_until(release))
    search(qtbot, page, fdi=FDI_C)
    page.view.clearSelection()  # not the preselected call: the FDI's group row, its four calls
    page.view.setCurrentIndex(page.model.index(0, 0))
    assert page.model.is_group(page.model.index(0, 0)) and len(page.generate.hits()) == 4
    genera = window.page("genera")
    try:
        page.generate.generate("svil")
        assert genera.is_running(), window.toast.text()
        qtbot.waitUntil(lambda: len(fake_core.officina.requests) == 3, timeout=WAIT_MS)  # three lanes
        assert genera.is_running() and not page.generate.button.isEnabled()
        window.show_page("genera")
        assert genera.start_button.text() == strings.GENERA_STOP
        qtbot.mouseClick(genera.start_button, Qt.MouseButton.LeftButton)  # Interrompi
        assert genera.progress_label.text() == strings.GENERA_STOPPING
    finally:
        release.set()  # never a lane left waiting, whatever failed
    report = _finished(qtbot, window)
    assert report.cancelled
    assert [o.status for o in report.outcomes] == ["ok", "ok", "ok", "cancelled"]
    assert len(fake_core.officina.requests) == 3  # the fourth was never sent
    assert window.toast.text() == strings.GENERA_TOAST_STOPPED.format(
        summary=report_summary(report, with_folder=False))
    assert window.toast.property("tone") == "warn" and fake_core.extract.files == []
    assert genera.results.retry_button.text() == strings.GENERA_RETRY_ONE
    qtbot.waitUntil(page.generate.button.isEnabled, timeout=WAIT_MS)


def test_an_email_is_saved_as_html_even_with_the_tab_option_off(qtbot, window, page, fake_core):
    window.page("genera").presenter.set_save_html(False)
    fake_core.officina.set_response(HTML)
    search(qtbot, page, key=KEY_EMAIL)
    _select(page, _hit(page, FDI_C, KEY_EMAIL))
    page.generate.generate("svil")
    (outcome,) = _finished(qtbot, window).outcomes
    assert outcome.files[0].suffix == ".html" and fake_core.extract.files == [outcome.files[0]]


def test_several_calls_end_with_a_summary_and_two_actions(qtbot, window, page, fake_core):
    hits = search(qtbot, page, key=KEY_SINT)
    _select(page, hits[0], hits[1])
    page.generate.generate("svil")
    report = _finished(qtbot, window)
    assert [o.status for o in report.outcomes] == ["ok", "ok"]
    assert fake_core.extract.files == []  # several: nothing is opened by itself
    assert window.toast.text().startswith(strings.GENERA_TOAST_DONE.split("{")[0])
    first, second = window.toast.action_buttons()
    assert (first.text(), second.text()) == (strings.BTN_OPEN_FOLDER, strings.GENERA_CALLS_SEE_RESULTS)
    first.click()
    assert fake_core.extract.folders == [report.run_dir]
    page.generate._on_done(report, "")  # the same toast again, to reach its second button
    window.toast.action_buttons()[1].click()
    assert window.current_page_key() == "genera"
    assert len(window.page("genera").results.row_texts()) == 2  # the tab shows the run


def test_nothing_generated_says_why(qtbot, window, page, fake_core):
    fake_core.officina.set_response(b"guasto", 500)
    search(qtbot, page, key=KEY_SINT)
    page.generate.generate("svil")
    report = _finished(qtbot, window)
    (outcome,) = report.outcomes
    assert outcome.status == "failed"
    assert window.toast.text() == strings.GENERA_CALLS_NOTHING.format(reason=outcome.reason)
    assert "500" in window.toast.text() and window.toast.property("tone") == "warn"
    assert [b.text() for b in window.toast.action_buttons() if b.isVisible()] == [
        strings.GENERA_CALLS_SEE_RESULTS]
    assert fake_core.extract.files == []


def test_no_destination_sends_nothing(qtbot, window, page, fake_core):
    window.page("genera").presenter.set_destination(None)
    search(qtbot, page, key=KEY_SINT)
    page.shortcuts[GENERATE_SHORTCUT].activated.emit()
    assert window.toast.text() == strings.GENERA_CALLS_NEED_DESTINATION
    assert window.toast.property("tone") == "warn"
    assert fake_core.officina.requests == [] and not window.page("genera").is_running()


def test_the_entry_points_wait_for_a_running_generation(qtbot, window, page, fake_core):
    release = threading.Event()

    def held(_request):
        release.wait(60)
        return 200, b"%PDF-1.7\n" + b"0" * 100 + b"\n%%EOF\n"

    fake_core.officina.set_responder(held)
    hits = search(qtbot, page, key=KEY_SINT)
    page.generate.generate("svil")
    qtbot.waitUntil(lambda: len(fake_core.officina.requests) == 1, timeout=WAIT_MS)
    button = page.generate.button
    assert not button.isEnabled() and button.toolTip() == strings.GENERA_CALLS_TIP_RUNNING
    entry = next(a for a in page.build_context_menu(hits[0]).actions()
                 if a.text() == strings.GENERA_CALLS_ACTION_ONE)
    assert not entry.isEnabled() and entry.toolTip() == strings.GENERA_CALLS_TIP_RUNNING
    page.shortcuts[GENERATE_SHORTCUT].activated.emit()  # refused: nothing more is sent
    release.set()
    _finished(qtbot, window)
    qtbot.waitUntil(button.isEnabled, timeout=WAIT_MS)
    assert len(fake_core.officina.requests) == 1


# -- two generators -------------------------------------------------------------------------------

def test_with_two_generators_the_user_picks_one(qtbot, window, page, fake_core, monkeypatch):
    _two_generators(window, fake_core)
    hits = search(qtbot, page, key=KEY_SINT)  # the fake's calls are in coll's logs
    menu = page.generate.button.menu()
    assert menu is not None
    page.generate.refresh_menu()
    assert _labels(menu) == [strings.GENERA_CALLS_ON_ENV.format(env=e) for e in ("coll", "svil")]
    row_menu = page.build_context_menu(hits[0])
    sub = next(a for a in row_menu.actions() if a.text() == strings.GENERA_CALLS_ACTION_ONE).menu()
    assert sub is not None and _labels(sub) == _labels(menu)

    popped: list[object] = []
    monkeypatch.setattr(page.generate, "_popup", lambda: popped.append(True))
    page.shortcuts[GENERATE_SHORTCUT].activated.emit()
    assert popped == [True] and fake_core.officina.requests == []  # Ctrl+G asks where

    sub.actions()[1].trigger()  # "su svil"
    report = _finished(qtbot, window)
    assert report.run_dir.name.startswith("svil_")
    assert "/svil/" in fake_core.officina.requests[0].url


def test_with_one_generator_there_is_no_menu(qtbot, page):
    hits = search(qtbot, page, key=KEY_SINT)
    assert page.generate.button.menu() is None
    entry = next(a for a in page.build_context_menu(hits[0]).actions()
                 if a.text() == strings.GENERA_CALLS_ACTION_ONE)
    assert entry.menu() is None
