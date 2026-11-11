"""The Genera results pane: what a filter hides, what it keeps across runs,
and the chip of what "Riprova" sends again.

Driven like a user would, on the fake core (see ``test_genera_page``):
``MOD_TEST_ASSENTE`` has no call in the logs (``no_call``), ``KEY_EMAIL``
answers HTTP 500 when told to (``failed``). Synthetic data only.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from qtrequestory.ui import strings
from qtrequestory.ui.pages.genera_outcomes import COL_KEY
from qtrequestory.ui.pages.genera_page import GeneraPage
from qtrequestory.ui.pages.genera_retry import RETRY_STATUSES
from tests.conftest import KEY_CTE, KEY_EMAIL, KEY_SINT
from tests.ui.test_genera_page import FakeWindow, _generate, _type_keys

WAIT_MS = 8000
MISSING = "MOD_TEST_ASSENTE"
RETRY = "retry"  # the chip of what Riprova sends again (genera_chips.RETRY), as "failed" is a status's


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


def _shown_keys(page: GeneraPage) -> list[str]:
    return [r[COL_KEY] for r in page.results.visible_rows()]


def _next_report(qtbot, page: GeneraPage, start) -> None:
    """``start()`` a run (Genera, Riprova) and wait for its report."""
    first = page.report
    start()
    qtbot.waitUntil(lambda: page.report is not None and page.report is not first
                    and not page.is_running(), timeout=WAIT_MS)


def _click(qtbot, widget) -> None:
    qtbot.mouseClick(widget, Qt.MouseButton.LeftButton)


# -- Enter opens only a row on screen ---------------------------------------------------------

def test_enter_never_opens_a_row_a_chip_has_hidden(qtbot, page, fake_core):
    fake_core.officina.set_response_for(KEY_EMAIL, b"guasto", 500)
    _type_keys(qtbot, page, f"{KEY_SINT} {KEY_EMAIL}")
    _generate(qtbot, page)
    table = page.results.table
    ok_row = next(r for r, o in enumerate(page.results.outcomes()) if o.status == "ok")
    table.setCurrentCell(ok_row, COL_KEY)
    _click(qtbot, page.results.chips.chip("failed"))
    assert table.isRowHidden(ok_row)
    current = table.currentRow()
    assert current != ok_row and (current < 0 or not table.isRowHidden(current))
    table.setFocus()
    QTest.keyClick(table, Qt.Key.Key_Return)
    assert fake_core.extract.files == []  # the generated document is not on screen
    _click(qtbot, page.results.chips.chip("all"))
    table.setCurrentCell(ok_row, COL_KEY)
    QTest.keyClick(table, Qt.Key.Key_Return)
    assert len(fake_core.extract.files) == 1  # on screen again: it opens


# -- "↻ da riprovare": exactly what Riprova sends again ----------------------------------------

def test_the_retry_chip_shows_exactly_the_rows_riprova_sends(qtbot, page, fake_core):
    fake_core.officina.set_response_for(KEY_EMAIL, b"guasto", 500)
    _type_keys(qtbot, page, f"{KEY_SINT} {KEY_CTE} {KEY_EMAIL} {MISSING}")
    report = _generate(qtbot, page)
    chips = page.results.chips
    assert chips.shown() == ["all", "ok", "no_call", "failed", RETRY]  # last, after the outcomes
    retry = chips.chip(RETRY)
    assert retry.text() == strings.GENERA_CHIP.format(glyph=strings.GENERA_GLYPH_RETRY,
                                                      text=strings.GENERA_CHIP_RETRY.format(n=2))
    assert "Riprova" in retry.toolTip()
    _click(qtbot, retry)
    again = [o.key for o in report.outcomes if o.status in RETRY_STATUSES]
    assert _shown_keys(page) == again == [KEY_EMAIL, MISSING]
    assert page.results.retry_button.text() == strings.GENERA_RETRY.format(n=len(again))
    fake_core.officina.set_response_for(KEY_EMAIL, None)
    before = len(fake_core.officina.requests)
    _next_report(qtbot, page, lambda: _click(qtbot, page.results.retry_button))
    sent = [r.template_key for r in fake_core.officina.requests[before:]]
    assert sent == [KEY_EMAIL]  # the one with a call; MISSING still has none
    assert [o.key for o in page.report.outcomes] == again


def test_with_one_kind_to_retry_there_is_no_retry_chip(qtbot, page, fake_core):
    fake_core.officina.set_response_for(KEY_EMAIL, b"guasto", 500)
    _type_keys(qtbot, page, f"{KEY_SINT} {KEY_EMAIL}")
    _generate(qtbot, page)
    assert page.results.chips.shown() == ["all", "ok", "failed"]  # "✕ 1 non riuscito" says it
    _type_keys(qtbot, page, KEY_SINT)
    _next_report(qtbot, page, page.generate)
    assert page.results.chips.shown() == ["all", "ok"]  # nothing to retry: no chip


# -- a new run keeps the filter when it still has rows for it, else "Tutti" -------------------

def test_a_filter_survives_a_new_run_that_still_has_its_rows(qtbot, page, fake_core):
    fake_core.officina.set_response_for(KEY_EMAIL, b"guasto", 500)
    _type_keys(qtbot, page, f"{KEY_SINT} {KEY_EMAIL}")
    _generate(qtbot, page)
    _click(qtbot, page.results.chips.chip("failed"))
    _next_report(qtbot, page, lambda: _click(qtbot, page.start_button))  # still failing
    assert page.results.chips.current() == "failed"
    assert page.results.chips.chip("failed").isChecked()
    assert _shown_keys(page) == [KEY_EMAIL]


def test_a_filter_survives_riprova_when_rows_are_still_to_retry(qtbot, page, fake_core):
    fake_core.officina.set_response_for(KEY_EMAIL, b"guasto", 500)
    _type_keys(qtbot, page, f"{KEY_SINT} {KEY_CTE} {KEY_EMAIL} {MISSING}")
    _generate(qtbot, page)
    _click(qtbot, page.results.chips.chip(RETRY))
    _next_report(qtbot, page, lambda: _click(qtbot, page.results.retry_button))  # both again
    assert page.results.chips.current() == RETRY
    assert _shown_keys(page) == [KEY_EMAIL, MISSING]


def test_a_filter_falls_back_to_tutti_when_the_new_run_has_none(qtbot, page, fake_core):
    fake_core.officina.set_response_for(KEY_EMAIL, b"guasto", 500)
    _type_keys(qtbot, page, f"{KEY_SINT} {KEY_EMAIL}")
    _generate(qtbot, page)
    _click(qtbot, page.results.chips.chip("failed"))
    fake_core.officina.set_response_for(KEY_EMAIL, None)
    _next_report(qtbot, page, lambda: _click(qtbot, page.start_button))  # nothing fails now
    assert page.results.chips.current() == "all" and page.results.chips.chip("all").isChecked()
    assert _shown_keys(page) == [KEY_SINT, KEY_EMAIL]
    fake_core.officina.set_response_for(KEY_EMAIL, b"guasto", 500)
    _next_report(qtbot, page, lambda: _click(qtbot, page.start_button))
    assert page.results.chips.current() == "all"  # the fallback forgot the old choice
    assert len(_shown_keys(page)) == 2
