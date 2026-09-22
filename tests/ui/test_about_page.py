"""Info: the version, the four paths, and a readable tail of ``app.log``.

The log is read in a worker, so every assertion about its contents waits for
the job instead of reading the widget straight away.

``LOG_LINES`` is written in the format ``core.logsetup.APP_LOG_FORMAT``
produces — a fixture in a shape the application never writes would let the
level filter pass here and match nothing in the field, so one test below feeds
the page a file written by ``configure_logging`` itself.
"""
from __future__ import annotations

import logging

import pytest

from qtrequestory.ui import strings
from qtrequestory.ui.pages.about_page import (
    AboutPage,
    MAX_LOG_LINES,
    line_level,
    tail_lines,
)

LOG_LINES = [
    "[2026-09-22 09:00:00] INFO avvio dell'applicazione",
    "[2026-09-22 09:00:01] WARNING indice non aggiornato",
    "[2026-09-22 09:00:02] INFO coll: scaricato un file",
    "[2026-09-22 09:00:03] ERROR download non riuscito",
]
#: What builds before this one wrote: ``[timestamp] message``, no level.
LEGACY_LINE = "[2026-09-21 18:00:00] riga di una versione precedente"


class StubWindow:
    def __init__(self) -> None:
        self.status: list[str] = []

    def set_status(self, text: str, ms: int = 4000) -> None:
        self.status.append(text)


@pytest.fixture
def window() -> StubWindow:
    return StubWindow()


@pytest.fixture
def app_log(fake_core):
    path = fake_core.app_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(LOG_LINES) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def real_app_log(fake_core):
    """``app.log`` as ``core.logsetup`` writes it, into the fake core's paths.

    ``configure_logging`` reconfigures the *global* root logger, so the
    previous handlers are put back (and the new ones closed, or Windows keeps
    the temp file locked) whatever the test does.
    """
    from qtrequestory.core.logsetup import SYNC_LOGGER, configure_logging

    loggers = (logging.getLogger(), logging.getLogger(SYNC_LOGGER))
    saved = [(lg, list(lg.handlers), lg.level, lg.propagate) for lg in loggers]
    configure_logging(fake_core.paths, headless=True, level="DEBUG")
    try:
        yield fake_core.paths.app_log
    finally:
        for logger, handlers, level, propagate in saved:
            for handler in list(logger.handlers):
                logger.removeHandler(handler)
                handler.close()
            logger.handlers.extend(handlers)
            logger.setLevel(level)
            logger.propagate = propagate


@pytest.fixture
def page(qtbot, fake_core, runner, window, app_log):
    widget = AboutPage(fake_core, runner, window)
    qtbot.addWidget(widget)
    qtbot.waitUntil(lambda: widget.log_loaded, timeout=3000)
    return widget


# -- identity and paths ------------------------------------------------------

def test_the_page_shows_the_application_name_and_version(page, fake_core):
    assert strings.APP_NAME in page.title_label.text()
    assert fake_core.version() in page.version_label.text()


def test_the_four_paths_are_shown(page, fake_core):
    shown = {key: label.text() for key, label in page.path_labels.items()}
    assert str(fake_core.config.config_path()) in shown["config"]
    assert str(fake_core.index_db_path()) in shown["index"]
    assert str(fake_core.app_log_path()) in shown["app_log"]
    assert str(fake_core.sync_log_path()) in shown["sync_log"]


def test_each_path_can_reveal_its_folder(page, fake_core):
    page.folder_buttons["index"].click()
    assert fake_core.extract.folders[-1] == fake_core.index_db_path().parent


def test_a_log_file_can_be_opened_in_the_editor(page, fake_core):
    page.open_buttons["app_log"].click()
    assert fake_core.extract.opened[-1] == [fake_core.app_log_path()]


# -- the log viewer ----------------------------------------------------------

def test_the_log_tail_is_shown(page):
    text = page.log_view.toPlainText()
    assert "avvio dell'applicazione" in text
    assert page.log_view.isReadOnly()


def test_the_errors_filter_keeps_only_the_error_lines(page):
    page.set_filter(AboutPage.FILTER_ERRORS)
    text = page.log_view.toPlainText()
    assert "download non riuscito" in text
    assert "avvio dell'applicazione" not in text
    assert "indice non aggiornato" not in text


def test_the_warnings_filter_keeps_only_the_warning_lines(page):
    page.set_filter(AboutPage.FILTER_WARNINGS)
    text = page.log_view.toPlainText()
    assert "indice non aggiornato" in text
    assert "download non riuscito" not in text


def test_tutti_shows_every_line_again(page):
    page.set_filter(AboutPage.FILTER_ERRORS)
    page.set_filter(AboutPage.FILTER_ALL)
    assert page.log_view.toPlainText().splitlines() == LOG_LINES


def test_aggiorna_rereads_the_file(page, app_log, qtbot):
    app_log.write_text("\n".join(LOG_LINES + ["[2026-09-22 09:01:00] riga nuova"]), encoding="utf-8")

    page.refresh_button.click()

    qtbot.waitUntil(lambda: "riga nuova" in page.log_view.toPlainText(), timeout=3000)


def test_copia_tutto_copies_the_whole_tail_not_the_filtered_view(page, window):
    """A filter is for reading with: pasting three lines (or a placeholder)
    into a chat is not what [Copia tutto] promises."""
    from PySide6.QtGui import QGuiApplication

    page.set_filter(AboutPage.FILTER_ERRORS)
    page.copy_button.click()

    assert QGuiApplication.clipboard().text() == "\n".join(LOG_LINES)
    assert strings.ABOUT_LOG_COPIED in window.status


def test_a_missing_log_file_shows_a_hint_instead_of_failing(
    qtbot, fake_core, runner, window, app_log
):
    app_log.unlink()
    widget = AboutPage(fake_core, runner, window)
    qtbot.addWidget(widget)
    qtbot.waitUntil(lambda: widget.log_loaded, timeout=3000)
    assert widget.log_view.toPlainText() == strings.ABOUT_LOG_EMPTY


def test_an_empty_filter_result_is_not_an_empty_log(qtbot, fake_core, runner, window, app_log):
    """"Nessuna riga di log" would make the user think the log is empty when it
    is only the filter that matched nothing."""
    app_log.write_text(LOG_LINES[0] + "\n", encoding="utf-8")
    widget = AboutPage(fake_core, runner, window)
    qtbot.addWidget(widget)
    qtbot.waitUntil(lambda: widget.log_loaded, timeout=3000)

    widget.set_filter(AboutPage.FILTER_ERRORS)

    assert widget.log_view.toPlainText() == strings.ABOUT_LOG_NO_MATCH


def test_a_line_from_an_older_build_survives_the_filter(
    qtbot, fake_core, runner, window, app_log
):
    """``app.log`` only gained its level field in this version."""
    app_log.write_text("\n".join([LEGACY_LINE, *LOG_LINES]), encoding="utf-8")
    widget = AboutPage(fake_core, runner, window)
    qtbot.addWidget(widget)
    qtbot.waitUntil(lambda: widget.log_loaded, timeout=3000)

    assert LEGACY_LINE in widget.log_view.toPlainText()
    widget.set_filter(AboutPage.FILTER_ERRORS)
    assert LEGACY_LINE not in widget.log_view.toPlainText()
    assert "download non riuscito" in widget.log_view.toPlainText()


def test_the_filter_matches_what_configure_logging_really_writes(
    qtbot, fake_core, runner, window, real_app_log
):
    """The one test the level filter is actually worth anything on: the file is
    written by ``core.logsetup``, not by this module."""
    log = logging.getLogger("qtrequestory.test.about")
    log.info("avvio dell'applicazione")
    log.warning("indice non aggiornato")
    log.error("download non riuscito")

    widget = AboutPage(fake_core, runner, window)
    qtbot.addWidget(widget)
    qtbot.waitUntil(lambda: widget.log_loaded, timeout=3000)

    widget.set_filter(AboutPage.FILTER_WARNINGS)
    shown = widget.log_view.toPlainText().splitlines()
    assert len(shown) == 1
    assert shown[0].endswith("WARNING indice non aggiornato")

    widget.set_filter(AboutPage.FILTER_ERRORS)
    shown = widget.log_view.toPlainText().splitlines()
    assert len(shown) == 1
    assert shown[0].endswith("ERROR download non riuscito")

    widget.set_filter(AboutPage.FILTER_ALL)
    assert len(widget.log_view.toPlainText().splitlines()) == 3


# -- the tail helper ---------------------------------------------------------

def test_tail_lines_keeps_only_the_last_lines(tmp_path):
    path = tmp_path / "app.log"
    path.write_text("\n".join(f"riga {i}" for i in range(MAX_LOG_LINES + 120)), encoding="utf-8")

    lines = tail_lines(path, MAX_LOG_LINES)

    assert len(lines) == MAX_LOG_LINES
    assert lines[-1] == f"riga {MAX_LOG_LINES + 119}"


def test_tail_lines_of_a_missing_file_is_empty(tmp_path):
    assert tail_lines(tmp_path / "assente.log", 10) == []


# -- the level parser --------------------------------------------------------

@pytest.mark.parametrize(
    ("line", "expected"),
    [
        (LOG_LINES[1], "WARNING"),
        (LOG_LINES[3], "ERROR"),
        (LEGACY_LINE, None),
        ("", None),
        # Only the level FIELD counts: a message that talks about an ERROR is
        # not one, and neither is an Italian "errore".
        ("[2026-09-22 09:00:00] INFO nessun ERROR qui", "INFO"),
        ("[2026-09-22 09:00:00] errore di rete", None),
    ],
)
def test_line_level_reads_the_level_field_only(line: str, expected: str | None):
    assert line_level(line) == expected


def test_line_level_agrees_with_the_real_formatter(real_app_log):
    logging.getLogger("qtrequestory.test.level").critical("disco pieno")
    assert line_level(real_app_log.read_text(encoding="utf-8").splitlines()[-1]) == "CRITICAL"
