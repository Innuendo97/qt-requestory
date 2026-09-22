"""Info: the version, the four paths, and a readable tail of ``app.log``.

The log is read in a worker, so every assertion about its contents waits for
the job instead of reading the widget straight away.
"""
from __future__ import annotations

import pytest

from qtrequestory.ui import strings
from qtrequestory.ui.pages.about_page import AboutPage, MAX_LOG_LINES, tail_lines

LOG_LINES = [
    "[2026-09-22 09:00:00] avvio dell'applicazione",
    "[2026-09-22 09:00:01] WARNING indice non aggiornato",
    "[2026-09-22 09:00:02] coll: scaricato un file",
    "[2026-09-22 09:00:03] ERROR download non riuscito",
]


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


def test_copia_tutto_puts_the_visible_lines_in_the_clipboard(page, window, qtbot):
    from PySide6.QtGui import QGuiApplication

    page.set_filter(AboutPage.FILTER_ERRORS)
    page.copy_button.click()

    assert QGuiApplication.clipboard().text() == page.log_view.toPlainText()
    assert strings.ABOUT_LOG_COPIED in window.status


def test_a_missing_log_file_shows_a_hint_instead_of_failing(
    qtbot, fake_core, runner, window, app_log
):
    app_log.unlink()
    widget = AboutPage(fake_core, runner, window)
    qtbot.addWidget(widget)
    qtbot.waitUntil(lambda: widget.log_loaded, timeout=3000)
    assert widget.log_view.toPlainText() == strings.ABOUT_LOG_EMPTY


# -- the tail helper ---------------------------------------------------------

def test_tail_lines_keeps_only_the_last_lines(tmp_path):
    path = tmp_path / "app.log"
    path.write_text("\n".join(f"riga {i}" for i in range(MAX_LOG_LINES + 120)), encoding="utf-8")

    lines = tail_lines(path, MAX_LOG_LINES)

    assert len(lines) == MAX_LOG_LINES
    assert lines[-1] == f"riga {MAX_LOG_LINES + 119}"


def test_tail_lines_of_a_missing_file_is_empty(tmp_path):
    assert tail_lines(tmp_path / "assente.log", 10) == []
