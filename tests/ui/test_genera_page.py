"""The Genera tab, driven like a user would, on the fake core.

``fake_core``'s Officina is the REAL ``OfficinaService`` with an in-process
generator (``FakeOfficinaApi``: canned PDF, every request recorded) and the
fake index (12 synthetic calls in the logs of ``coll``). One test runs the
app's own wiring instead (``CoreServices.real``, a real index over a synthetic
mirror, the loopback ``FakeServer``). Synthetic data only.
"""
from __future__ import annotations

import dataclasses
import threading
import time
from datetime import date
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import NO_PACKAGE, BatchReport, Outcome
from qtrequestory.ui.pages import officina_dialogs
from qtrequestory.ui.pages.genera_outcomes import COL_FOLDER, COL_KEY, COL_REASON, COL_STATUS
from qtrequestory.ui.pages.genera_page import GeneraPage
from qtrequestory.ui.workers import GENERA_JOB
from tests.conftest import FDI_A, FDI_B, KEY_CTE, KEY_EMAIL, KEY_SINT

WAIT_MS = 8000


class FakeWindow:
    """What the page asks of the main window: a toast and a page switch."""

    def __init__(self) -> None:
        self.toasts: list[tuple[str, str]] = []
        self.shown: list[str] = []

    def show_toast(self, text: str, tone: str = "neutral", *_a, **_k) -> None:
        self.toasts.append((text, tone))

    def show_page(self, key: str) -> None:
        self.shown.append(key)

    def page(self, _key: str):
        return None


@pytest.fixture
def window() -> FakeWindow:
    return FakeWindow()


@pytest.fixture
def dest(tmp_path: Path) -> Path:
    folder = tmp_path / "dest"
    folder.mkdir()
    return folder


def _page(qtbot, services, runner, window) -> GeneraPage:
    page = GeneraPage(services, runner, window)
    qtbot.addWidget(page)
    page.resize(1200, 900)
    page.show()
    return page


@pytest.fixture
def page(qtbot, fake_core, runner, window, dest) -> GeneraPage:
    page = _page(qtbot, fake_core, runner, window)
    page.presenter.set_destination(dest)
    page.source_combo.setCurrentText("coll")  # the fake's calls are in coll's logs
    return page


def _type_keys(qtbot, page: GeneraPage, text: str) -> None:
    page.source.keys_edit.setFocus()
    page.source.keys_edit.selectAll()
    QTest.keyClicks(page.source.keys_edit, text)


def _finish(qtbot, page: GeneraPage) -> BatchReport:
    qtbot.waitUntil(lambda: page.report is not None and not page.is_running(), timeout=WAIT_MS)
    return page.report


def _generate(qtbot, page: GeneraPage) -> BatchReport:
    assert page.start_button.isEnabled(), page.problem_label.text()
    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
    return _finish(qtbot, page)


# -- the one-key path ---------------------------------------------------------------------

def test_generate_single_key_fills_results_and_writes_pdf(qtbot, page, fake_core, window, dest):
    _type_keys(qtbot, page, KEY_SINT)
    assert page.start_button.text() == strings.GENERA_START_ONE
    report = _generate(qtbot, page)
    (outcome,) = report.outcomes
    pdf = report.run_dir / NO_PACKAGE / f"{KEY_SINT}.pdf"
    assert outcome.status == "ok" and outcome.files == (pdf,) and pdf.is_file()
    assert report.run_dir.parent == dest
    assert [r.template_key for r in fake_core.officina.requests] == [KEY_SINT]
    (row,) = page.results.row_texts()
    assert row[COL_KEY] == KEY_SINT and row[COL_FOLDER] == NO_PACKAGE
    assert row[COL_STATUS] == strings.GENERA_STATUS_CELL.format(glyph=strings.GENERA_GLYPH_OK,
                                                                word=strings.GENERA_STATUS_OK)
    assert page.results.summary.text() == strings.GENERA_DONE_LINE.format(
        title=strings.GENERA_DONE_TITLE, name=report.run_dir.name)
    assert page.results.chips.chip("ok").text().endswith(strings.GENERA_SUM_OK_ONE)
    assert page.results.open_folder_button.isVisible()
    assert not page.results.retry_button.isVisible()  # nothing to retry
    assert not window.toasts  # the tab is on screen: its results say it
    qtbot.mouseClick(page.results.open_folder_button, Qt.MouseButton.LeftButton)
    assert fake_core.extract.folders == [report.run_dir]


def test_button_disabled_with_problem_shown_inline(qtbot, fake_core, runner, window, dest):
    page = _page(qtbot, fake_core, runner, window)
    assert not page.start_button.isEnabled()
    assert page.problem_label.isVisible() and page.problem_label.text() == strings.GENERA_NEED_KEYS
    _type_keys(qtbot, page, KEY_SINT)
    assert page.problem_label.text() == strings.GENERA_NEED_DESTINATION  # the next one
    page.presenter.set_destination(dest)
    assert page.start_button.isEnabled() and not page.problem_label.isVisible()


def test_over_twenty_calls_asks_confirmation(qtbot, page, monkeypatch, runner):
    asked: list[tuple[str, str]] = []
    answer = {"yes": False}

    def confirm(_parent, title, text, **_kw):
        asked.append((title, text))
        return answer["yes"]

    monkeypatch.setattr(officina_dialogs, "confirm", confirm)
    _type_keys(qtbot, page, " ".join(f"MOD_TEST_{i:02d}" for i in range(21)))
    assert page.start_button.text() == strings.GENERA_START_N.format(n=21)
    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
    (title, text), = asked
    assert "21" in title and "svil" in text and "coll" in text
    assert runner.job(GENERA_JOB) is None and page.report is None  # refused: nothing ran
    answer["yes"] = True
    report = _generate(qtbot, page)
    assert len(asked) == 2 and len(report.outcomes) == 21
    assert {o.status for o in report.outcomes} == {"no_call"}


def test_twenty_calls_or_fewer_ask_nothing(qtbot, page, monkeypatch):
    monkeypatch.setattr(officina_dialogs, "confirm", lambda *_a, **_k: pytest.fail("no question under 21"))
    _type_keys(qtbot, page, " ".join(f"MOD_TEST_{i:02d}" for i in range(20)))
    assert len(_generate(qtbot, page).outcomes) == 20


def test_ctrl_enter_generates(qtbot, page):
    _type_keys(qtbot, page, KEY_SINT)
    QTest.keyClick(page.source.keys_edit, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    assert _finish(qtbot, page).outcomes[0].status == "ok"
    assert page.source.keys_edit.toPlainText() == KEY_SINT  # no line break typed


# -- running ----------------------------------------------------------------------------------

def _held_until(release: threading.Event):
    """A responder that answers only once ``release`` is set — never "after a
    while": a slow machine must not change what the test sees."""
    def held(_request):
        if not release.wait(60):  # a guard against a hung test, not a timing
            raise TimeoutError("test non rilasciato")
        return 200, b"%PDF-1.7\n" + b"0" * 100 + b"\n%%EOF\n"
    return held


def test_stop_cancels_job(qtbot, page, fake_core):
    release = threading.Event()
    held = _held_until(release)

    fake_core.officina.set_responder(held)
    _type_keys(qtbot, page, " ".join([KEY_SINT, KEY_EMAIL, KEY_CTE, "MOD_TEST_X1", "MOD_TEST_X2"]))
    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: len(fake_core.officina.requests) == 3, timeout=WAIT_MS)
    assert page.is_running() and page.start_button.text() == strings.GENERA_STOP
    assert page.progress_bar.isVisible()
    for widget in (page.source, page.generator_combo, page.zip_box):
        assert not widget.isEnabled()
    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)  # Interrompi
    assert page.progress_label.text() == strings.GENERA_STOPPING
    release.set()
    report = _finish(qtbot, page)
    assert report.cancelled
    statuses = [o.status for o in report.outcomes]
    assert statuses[:3] == ["ok", "ok", "ok"]  # already on the wire: finished and saved
    assert statuses[3:] == ["cancelled", "cancelled"]
    assert page.start_button.text() == strings.GENERA_START_N.format(n=5)
    assert page.results.retry_button.text() == strings.GENERA_RETRY.format(n=2)


def _double_click(widget) -> None:
    """What Windows delivers for a double click: press, release, double-click, release."""
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    pos = QPointF(widget.rect().center())
    for kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease,
                 QEvent.Type.MouseButtonDblClick, QEvent.Type.MouseButtonRelease):
        buttons = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton
        QApplication.sendEvent(widget, QMouseEvent(kind, pos, widget.mapToGlobal(pos), Qt.MouseButton.LeftButton,
                                                   buttons, Qt.KeyboardModifier.NoModifier))


def test_double_click_on_genera_generates_once(qtbot, page, fake_core):
    """Review item 2: the second click of a double click hit [Interrompi] at once."""
    _type_keys(qtbot, page, f"{KEY_SINT} {KEY_EMAIL} {KEY_CTE}")
    _double_click(page.start_button)
    assert page.is_running() and page.start_button.text() == strings.GENERA_STOP
    report = _finish(qtbot, page)
    assert not report.cancelled and [o.status for o in report.outcomes] == ["ok"] * 3
    assert len(fake_core.officina.requests) == 3


def test_interrompi_works_right_after_the_start(qtbot, page, fake_core):
    """The double-click guard must not swallow a deliberate single click."""
    release = threading.Event()
    fake_core.officina.set_responder(_held_until(release))
    _type_keys(qtbot, page, " ".join([KEY_SINT, KEY_EMAIL, KEY_CTE, "MOD_TEST_X1"]))
    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)  # at once: Interrompi
    assert page.progress_label.text() == strings.GENERA_STOPPING
    release.set()
    assert _finish(qtbot, page).cancelled


def test_generator_disabled_during_a_run_keeps_the_form(qtbot, page, fake_core):
    """Review item 3: the page swapped to "Nessun generatore" mid-run (no
    Interrompi, no results) and the engine kept sending to the old endpoint."""
    release = threading.Event()
    fake_core.officina.set_responder(_held_until(release))
    qtbot.mouseClick(page.source.mode_buttons["fdi"], Qt.MouseButton.LeftButton)
    page.source.fdi_edit.setPlainText(f"{FDI_A}\n{FDI_B}")  # 3 + 3 calls in the fake's logs
    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: len(fake_core.officina.requests) == 3, timeout=WAIT_MS)
    cfg = fake_core.config.config
    fake_core.config.config = dataclasses.replace(cfg, officina=dataclasses.replace(
        cfg.officina, generators=[dataclasses.replace(g, enabled=False) for g in cfg.officina.generators]))
    page.on_config_changed(fake_core.config.config)
    assert page.stack.currentWidget() is page.form and page.start_button.isVisible()
    assert page.start_button.text() == strings.GENERA_STOP
    release.set()
    report = _finish(qtbot, page)
    assert page.stack.currentWidget() is page.form  # the results stay
    assert [o.status for o in report.outcomes] == ["ok"] * 3 + ["failed"] * 3
    assert all("disattivato" in o.reason for o in report.outcomes[3:])
    assert len(fake_core.officina.requests) == 3  # nothing more went to the old endpoint
    assert page.problem_label.text() == strings.GENERA_NEED_GENERATOR
    assert not page.start_button.isEnabled()


def test_fdi_mode_confirms_the_real_number_of_calls(qtbot, page, fake_core, monkeypatch, runner):
    """Review item 6: in FDI mode the question counts CALLS, looked up first."""
    from qtrequestory.ui.pages import genera_presenter

    asked: list[tuple[str, str]] = []
    answer = {"yes": False}

    def confirm(_parent, title, text, **_kw):
        asked.append((title, text))
        return answer["yes"]

    monkeypatch.setattr(officina_dialogs, "confirm", confirm)
    monkeypatch.setattr(genera_presenter, "CONFIRM_ABOVE", 2)  # FDI_A has 3 template keys
    qtbot.mouseClick(page.source.mode_buttons["fdi"], Qt.MouseButton.LeftButton)
    page.source.fdi_edit.setPlainText(FDI_A)
    assert page.start_button.text() == strings.GENERA_START_FDI_ONE
    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
    assert page.is_running() and page.progress_label.text() == strings.GENERA_LOOKING_UP.format(env="coll")
    qtbot.waitUntil(lambda: bool(asked), timeout=WAIT_MS)
    (title, text), = asked
    assert "3" in title and "1 FDI" in text
    qtbot.waitUntil(lambda: not page.is_running(), timeout=WAIT_MS)
    assert fake_core.officina.requests == [] and page.report is None  # refused: nothing sent
    answer["yes"] = True
    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
    report = _finish(qtbot, page)
    assert len(asked) == 2 and len(report.outcomes) == 3 and len(fake_core.officina.requests) == 3


def test_stop_during_the_count_sends_nothing(qtbot, page, fake_core, monkeypatch):
    from qtrequestory.ui.contracts import Cancelled

    started = threading.Event()

    def slow_count(_request, *, cancel=None):
        started.set()
        while not cancel.is_set():
            time.sleep(0.01)
        raise Cancelled()

    monkeypatch.setattr(fake_core.officina, "batch_count", slow_count)
    monkeypatch.setattr(officina_dialogs, "confirm", lambda *_a, **_k: pytest.fail("no question"))
    qtbot.mouseClick(page.source.mode_buttons["fdi"], Qt.MouseButton.LeftButton)
    page.source.fdi_edit.setPlainText(FDI_A)
    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(started.is_set, timeout=WAIT_MS)
    _double_click(page.start_button)  # pressed twice meanwhile: still one stop, nothing else
    qtbot.waitUntil(lambda: not page.is_running(), timeout=WAIT_MS)
    assert fake_core.officina.requests == [] and page.report is None
    assert page.start_button.text() == strings.GENERA_START_FDI_ONE and page.start_button.isEnabled()


def test_open_folder_of_a_run_that_made_none_is_said_inline(qtbot, page, fake_core, dest):
    """Review item 5: os.startfile on a missing folder raised out of the slot."""
    page.report = BatchReport(dest / "svil_mai_creata", (
        Outcome(KEY_SINT, (NO_PACKAGE,), None, "cancelled", None, (), 0, None, "annullato"),), (), True)
    page.results.show_report(page.report, 1)
    qtbot.mouseClick(page.results.open_folder_button, Qt.MouseButton.LeftButton)
    assert fake_core.extract.folders == []
    assert page.results.message.text() == strings.GENERA_FOLDER_MISSING.format(name="svil_mai_creata")
    assert page.results.message_banner.isVisible()


def test_cancel_during_lookup_fills_the_table_from_the_report(qtbot, page, fake_core, monkeypatch, dest):
    started = threading.Event()

    def lookup_then_stop(request, *, sink=None, cancel=None):
        started.set()
        while not cancel.is_set():
            time.sleep(0.01)
        return BatchReport(dest / "svil_x", tuple(
            Outcome(t.value, t.folders, None, "cancelled", None, (), 0, None, "annullato")
            for t in request.targets), (), True)

    monkeypatch.setattr(fake_core.officina, "batch_run", lookup_then_stop)
    _type_keys(qtbot, page, f"{KEY_SINT} {KEY_EMAIL}")
    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(started.is_set, timeout=WAIT_MS)
    assert page.progress_label.text() == strings.GENERA_LOOKING_UP.format(env="coll")
    assert page.progress_bar.maximum() == 0  # indeterminate: no total yet
    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
    _finish(qtbot, page)
    assert [r[COL_KEY] for r in page.results.row_texts()] == [KEY_SINT, KEY_EMAIL]
    assert page.results.summary.text().startswith(strings.GENERA_STOPPED_TITLE)
    assert page.results.chips.chip("cancelled").text().endswith(strings.GENERA_SUM_CANCELLED.format(n=2))


def test_a_refusal_is_said_inline_not_in_a_dialog(qtbot, page, fake_core, monkeypatch, window):
    def refuse(_request, **_kw):
        raise ValueError("ricerca non disponibile: impossibile trovare le chiamate da generare")

    monkeypatch.setattr(fake_core.officina, "batch_run", refuse)
    monkeypatch.setattr(officina_dialogs, "confirm", lambda *_a, **_k: pytest.fail("no dialog"))
    _type_keys(qtbot, page, KEY_SINT)
    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: not page.is_running() and bool(page.results.message.text()), timeout=WAIT_MS)
    assert page.results.message.text() == strings.GENERA_REFUSED.format(
        reason="ricerca non disponibile: impossibile trovare le chiamate da generare")
    assert page.results.message_banner.isVisible() and page.start_button.isEnabled()
    assert page.report is None and not window.toasts


def test_retry_runs_only_failed(qtbot, page, fake_core):
    fake_core.officina.set_response_for(KEY_EMAIL, b"guasto", 500)
    _type_keys(qtbot, page, f"{KEY_SINT} {KEY_EMAIL}")
    first = _generate(qtbot, page)
    assert [o.status for o in first.outcomes] == ["ok", "failed"]
    row = page.results.row_texts()[1]
    assert row[COL_STATUS] == strings.GENERA_STATUS_CELL.format(glyph=strings.GENERA_GLYPH_FAILED,
                                                                word=strings.GENERA_STATUS_FAILED)
    assert "500" in row[COL_REASON]
    assert page.results.retry_button.isVisible()
    assert page.results.retry_button.text() == strings.GENERA_RETRY_ONE
    fake_core.officina.set_response_for(KEY_EMAIL, None)
    before = len(fake_core.officina.requests)
    page.source.keys_edit.clear()  # the retry does not need the field any more
    qtbot.mouseClick(page.results.retry_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: page.report is not None and page.report is not first
                    and not page.is_running(), timeout=WAIT_MS)
    second = page.report
    assert [r.template_key for r in fake_core.officina.requests[before:]] == [KEY_EMAIL]
    assert [(o.key, o.status) for o in second.outcomes] == [(KEY_EMAIL, "ok")]
    assert second.run_dir != first.run_dir


def test_an_outcome_chip_hides_the_other_rows(qtbot, page, fake_core):
    fake_core.officina.set_response_for(KEY_EMAIL, b"guasto", 500)
    _type_keys(qtbot, page, f"{KEY_SINT} {KEY_EMAIL} MOD_TEST_ASSENTE")
    _generate(qtbot, page)
    chips = page.results.chips
    assert len(page.results.visible_rows()) == 3
    qtbot.mouseClick(chips.chip("failed"), Qt.MouseButton.LeftButton)
    assert [r[COL_KEY] for r in page.results.visible_rows()] == [KEY_EMAIL]
    qtbot.mouseClick(chips.chip("no_call"), Qt.MouseButton.LeftButton)
    assert [r[COL_KEY] for r in page.results.visible_rows()] == ["MOD_TEST_ASSENTE"]
    qtbot.mouseClick(chips.chip("all"), Qt.MouseButton.LeftButton)
    assert len(page.results.visible_rows()) == 3


# -- headers ------------------------------------------------------------------------------------

def test_remove_header_row_not_sent(qtbot, page, fake_core):
    table = page.header_table
    names = [table.text(r, table.COL_NAME) for r in range(table.rowCount())]
    assert "Postman-Token" in names
    page.headers_toggle.setChecked(True)
    assert table.isVisible()
    assert table.shown_value(names.index("correlation_id")) == strings.GENERA_HEADER_AUTOMATIC
    table.selectRow(names.index("Postman-Token"))
    qtbot.mouseClick(page.remove_header_button, Qt.MouseButton.LeftButton)
    state = page.setup.headers
    assert state.sent.text() == strings.GENERA_HEADERS_SENT.format(n=len(names) - 1)
    assert state.modified_pill.isVisible()
    assert state.modified_pill.text() == strings.GENERA_HEADERS_MODIFIED_ONE
    _type_keys(qtbot, page, KEY_SINT)
    _generate(qtbot, page)
    (sent,) = fake_core.officina.requests
    assert "postman-token" not in {k.casefold() for k in sent.headers}
    assert {k.casefold(): v for k, v in sent.headers.items()}["template_key"] == KEY_SINT
    qtbot.mouseClick(page.reset_headers_button, Qt.MouseButton.LeftButton)
    assert table.rowCount() == len(names)


def test_a_bad_header_stops_the_button(qtbot, page):
    _type_keys(qtbot, page, KEY_SINT)
    page.headers_toggle.setChecked(True)
    row = page.header_table.add_row("Content-Length", "3")
    assert row >= 0
    assert not page.start_button.isEnabled()
    assert page.problem_label.text().startswith("Header: ")


# -- the other sources --------------------------------------------------------------------------

def test_elenco_lists_packages_and_feeds_the_button(qtbot, page, monkeypatch, tmp_path):
    csv = tmp_path / "elenco.csv"
    csv.write_bytes((f"Template key;a;b;c;package name\r\n{KEY_SINT};;;;111_PKG\r\n"
                     f"{KEY_EMAIL};;;;111_PKG\r\n{KEY_CTE};;;;222_PKG\r\n").encode("cp1252"))
    monkeypatch.setattr(officina_dialogs, "ask_open_file", lambda *_a, **_k: csv)
    qtbot.mouseClick(page.source.mode_buttons["elenco"], Qt.MouseButton.LeftButton)
    assert page.presenter.mode == "elenco"
    assert page.problem_label.text() == strings.GENERA_NEED_ELENCO
    qtbot.mouseClick(page.source.browse_elenco_button, Qt.MouseButton.LeftButton)
    assert page.source.package_texts() == [
        strings.GENERA_ELENCO_ROW.format(package="111_PKG", n=2),
        strings.GENERA_ELENCO_ROW.format(package="222_PKG", n=1)]
    assert page.problem_label.text() == strings.GENERA_NEED_PACKAGE
    page.source.filter_edit.setText("111")
    qtbot.mouseClick(page.source.all_button, Qt.MouseButton.LeftButton)
    assert page.presenter.checked_packages == {"111_PKG"}  # only the packages shown
    assert page.start_button.text() == strings.GENERA_START_N.format(n=2)
    report = _generate(qtbot, page)
    assert {p.parent.name for o in report.outcomes for p in o.files} == {"111_PKG"}


def test_fdi_mode_generates_every_key_of_the_fdi(qtbot, page, fake_core):
    qtbot.mouseClick(page.source.mode_buttons["fdi"], Qt.MouseButton.LeftButton)
    page.source.fdi_edit.setPlainText(FDI_A)
    assert page.start_button.text() == strings.GENERA_START_FDI_ONE
    report = _generate(qtbot, page)
    assert {o.key for o in report.outcomes} == {KEY_SINT, KEY_EMAIL, KEY_CTE}
    assert {o.folders for o in report.outcomes} == {(FDI_A,)}


def _on_screen(page: GeneraPage, widget) -> bool:
    """``widget`` is shown and wholly inside the page and every scroll area
    that holds it: nothing to scroll to find it."""
    from PySide6.QtCore import QPoint, QRect

    if not widget.isVisible():
        return False
    rect = QRect(widget.mapTo(page, QPoint(0, 0)), widget.size())
    if not page.rect().contains(rect):
        return False
    parent = widget.parentWidget()
    while parent is not None and parent is not page:
        if parent.objectName() == "qt_scrollarea_viewport":
            area = QRect(parent.mapTo(page, QPoint(0, 0)), parent.size())
            if not area.contains(rect):
                return False
        parent = parent.parentWidget()
    return True


@pytest.mark.parametrize("mode", ["keys", "elenco", "fdi"])
def test_the_button_is_always_on_screen(qtbot, page, tmp_path, mode):
    """Review item 9: in Elenco mode at 1366×768 the button fell below the fold."""
    csv = tmp_path / "elenco.csv"
    csv.write_bytes(("Template key;a;b;c;package name\r\n" + "".join(
        f"MOD_TEST_{i:02d};;;;{i % 9}_PKG\r\n" for i in range(40))).encode("cp1252"))
    page.resize(1366, 600)  # the tab's share of a 1366×768 screen
    page.presenter.set_mode(mode)
    page.presenter.load_elenco(csv)
    page.presenter.set_packages_checked(["1_PKG", "2_PKG"], True)
    qtbot.wait(50)
    for widget in (page.start_button, page.zip_box, page.html_box):
        assert _on_screen(page, widget), widget
    assert not page.setup.scroll.isAncestorOf(page.start_button)  # pinned, outside what scrolls


def test_the_results_come_into_view_when_a_run_starts(qtbot, page):
    page.resize(1366, 600)
    page.presenter.set_mode("keys")
    _type_keys(qtbot, page, KEY_SINT)
    _generate(qtbot, page)
    qtbot.wait(50)
    assert _on_screen(page, page.results.summary)


def test_an_unshown_page_builds_no_service_and_reads_no_list(qtbot, fake_core, runner, window, tmp_path):
    """Review item 8: the window builds every page at startup."""
    from qtrequestory.ui import actions, prefs

    officina = fake_core.officina
    built: list[int] = []
    services = dataclasses.replace(fake_core, officina_factory=lambda: built.append(1) or officina)
    csv = tmp_path / "elenco.csv"
    csv.write_bytes(f"Template key;a;b;c;package name\r\n{KEY_SINT};;;;111_PKG\r\n".encode("cp1252"))
    actions.user_settings().setValue(prefs.GENERA_ELENCO_KEY, str(csv))
    page = GeneraPage(services, runner, window)
    qtbot.addWidget(page)
    assert built == [] and page.presenter.elenco is None and not page.presenter.activated
    page.show()
    assert built == [1] and page.presenter.elenco is not None
    assert page.header_table.rowCount() > 0  # the table arrived with the first show


# -- state across pages and configurations ------------------------------------------------------

def test_prefs_restored_on_new_page(qtbot, page, fake_core, runner, window, dest):
    qtbot.mouseClick(page.source.mode_buttons["fdi"], Qt.MouseButton.LeftButton)
    page.zip_box.setChecked(True)
    again = _page(qtbot, fake_core, runner, window)
    assert again.presenter.mode == "fdi" and again.source.mode_buttons["fdi"].isChecked()
    assert again.destination.text() == str(dest)
    assert again.source_combo.currentText() == "coll"
    assert again.zip_box.isChecked() and not again.html_box.isChecked()


def test_no_generator_shows_empty_state(qtbot, fake_core, runner, window):
    fake_core.config.config.officina.generators = []
    page = _page(qtbot, fake_core, runner, window)
    assert page.stack.currentWidget() is page.no_generator
    qtbot.mouseClick(page.no_generator.button, Qt.MouseButton.LeftButton)
    assert window.shown == ["settings"]
    cfg = fake_core.config.config
    from tests.fakes.fake_core import FAKE_GENERATOR

    fake_core.config.config = dataclasses.replace(
        cfg, officina=dataclasses.replace(cfg.officina, generators=[FAKE_GENERATOR]))
    page.on_config_changed(fake_core.config.config)
    assert page.stack.currentWidget() is page.form
    assert page.generator_combo.currentText() == "svil"


# -- the app's own wiring ------------------------------------------------------------------------

def test_real_core_on_loopback_writes_the_pdf(qtbot, tmp_path, runner, window):
    from qtrequestory.core.config import Environment, GeneratorEndpoint, default_config, save_config
    from qtrequestory.core.events import CancelToken, null_sink
    from qtrequestory.core.paths import AppPaths
    from qtrequestory.ui.contracts import CoreServices
    from tests.conftest import entry_name, make_daily_file, synthetic_body
    from tests.officina._server import PDF, FakeServer

    server = FakeServer()
    try:
        paths = AppPaths(tmp_path / "apphome").ensure()
        make_daily_file(tmp_path / "mirror", "coll", date(2026, 11, 9),
                        [(entry_name(FDI_A, "MOD_TEST_A", "0a0a0a0a00000001"),
                          synthetic_body(FDI_A, "MOD_TEST_A"))])
        base = default_config()
        save_config(dataclasses.replace(
            base, mirror_root=tmp_path / "mirror",
            environments=[Environment("coll", "https://example.invalid/coll/")],
            officina=dataclasses.replace(base.officina, generators=[GeneratorEndpoint("svil", server.url)],
                                         default_generator="svil", header_profile={"IMEL": "active"}),
        ), paths.config_file)
        services = CoreServices.real(paths)
        services.index.update(["coll"], sink=null_sink, cancel=CancelToken())
        page = _page(qtbot, services, runner, window)
        assert page.source_combo.currentText() == "coll"  # no "svil" logs: the first environment
        page.presenter.set_destination(tmp_path / "dest")
        _type_keys(qtbot, page, "mod_test_a")
        report = _generate(qtbot, page)
        (outcome,) = report.outcomes
        assert outcome.status == "ok" and outcome.files[0].read_bytes() == PDF
        (headers, _body), = server.requests
        sent = {k.casefold(): v for k, v in headers.items()}
        assert sent["template_key"] == "MOD_TEST_A" and sent["imel"] == "active"
    finally:
        server.close()
