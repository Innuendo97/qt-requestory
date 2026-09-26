"""The Officina tab: folder chooser, initiatives, board, case workbench.

Offscreen, on the fake core: ``FakeOfficinaApi`` is the real service on real
files under the test's tmp folder, with the HTTP generator answering in
process (a canned PDF), so versions, refusals and reasons are the shipped
behaviour. Modal questions are answered by replacing the functions of
``officina_dialogs`` / ``officina_add`` (a modal cannot be answered offscreen).
"""
from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from qtrequestory.ui import strings
from qtrequestory.ui.main_window import MainWindow
from qtrequestory.ui.pages import officina_add, officina_dialogs
from qtrequestory.ui.pages.officina_add import AddChoice
from qtrequestory.ui.pages.officina_widgets import MiddleElidedLabel
from qtrequestory.ui.pages.officina_page import OfficinaPage
from qtrequestory.ui.workers import OFFICINA_GENERATE_JOBS
from tests.fakes.fake_core import canned_pdf

GENERATE_JOB = OFFICINA_GENERATE_JOBS[0]


class FakeWindow:
    """What the page asks of the shell: status, toast, page switching."""

    def __init__(self) -> None:
        self.statuses: list[str] = []
        self.toasts: list[tuple[str, str]] = []
        #: The toasts that carried an action button: ``(text, tone, (label, callback))``.
        self.actions: list[tuple[str, str, tuple]] = []
        self.shown: list[str] = []

    def set_status(self, text: str) -> None:
        self.statuses.append(text)

    def show_toast(self, text: str, tone: str = "neutral", ms: int = 0, action=None,
                   hint: str = "") -> None:
        self.toasts.append((text, tone))
        if action is not None:
            self.actions.append((text, tone, action))

    def show_page(self, key: str) -> None:
        self.shown.append(key)


@pytest.fixture
def shell() -> FakeWindow:
    return FakeWindow()


@pytest.fixture
def page(qtbot, fake_core, runner, shell) -> OfficinaPage:
    widget = OfficinaPage(fake_core, runner, shell)
    qtbot.addWidget(widget)
    widget.resize(1300, 760)
    widget.show()
    return widget


def payload_file(folder: Path, key: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{key}.json"
    path.write_text(json.dumps({"documents": [{"template": {"templateKey": key}}],
                                "customers": []}), encoding="utf-8")
    return path


def make_initiative(fake_core, name: str, keys: tuple[str, ...], tmp_path: Path):
    api = fake_core.officina
    ini = api.create_initiative(name)
    for key in keys:
        api.case_from_file(ini, payload_file(tmp_path / "payloads", key), key)
    return api.load(name)


def wait_idle(qtbot, page: OfficinaPage) -> None:
    qtbot.waitUntil(lambda: not page.queue.is_busy(), timeout=10000)


# ------------------------------------------------------------- the folder ---

def test_an_empty_root_shows_the_folder_chooser(qtbot, fake_core, runner, shell, tmp_path,
                                                monkeypatch):
    cfg = fake_core.config.config
    fake_core.config.config = dataclasses.replace(
        cfg, officina=dataclasses.replace(cfg.officina, root=None))
    page = OfficinaPage(fake_core, runner, shell)
    qtbot.addWidget(page)
    page.show()
    assert page.view() == "chooser"
    assert page.chooser.button.text() == strings.OFFICINA_ROOT_BUTTON

    chosen = tmp_path / "officina-scelta"
    monkeypatch.setattr(officina_dialogs, "ask_folder", lambda *_a, **_k: chosen)
    seen = []
    page.config_changed.connect(seen.append)
    QTest.mouseClick(page.chooser.button, Qt.MouseButton.LeftButton)

    assert fake_core.config.config.officina.root == chosen
    assert fake_core.config.saved and seen, "saved through services.config and announced"
    assert page.view() == "list"
    assert page.list.onedrive.text() == ""


def test_a_root_inside_onedrive_is_accepted_with_a_warning(qtbot, fake_core, runner, shell,
                                                           tmp_path, monkeypatch):
    cfg = fake_core.config.config
    fake_core.config.config = dataclasses.replace(
        cfg, officina=dataclasses.replace(cfg.officina, root=None))
    page = OfficinaPage(fake_core, runner, shell)
    qtbot.addWidget(page)
    page.show()
    chosen = tmp_path / "OneDrive - Esempio" / "Officina"
    monkeypatch.setattr(officina_dialogs, "ask_folder", lambda *_a, **_k: chosen)
    page.choose_root()
    assert fake_core.config.config.officina.root == chosen
    assert page.view() == "list"
    assert "OneDrive" in page.list.onedrive.text()
    assert any("OneDrive" in text and tone == "warn" for text, tone in shell.toasts)


def test_a_folder_the_configuration_cannot_save_is_a_sentence(qtbot, fake_core, runner, shell,
                                                              tmp_path, monkeypatch):
    cfg = fake_core.config.config
    fake_core.config.config = dataclasses.replace(
        cfg, officina=dataclasses.replace(cfg.officina, root=None))
    page = OfficinaPage(fake_core, runner, shell)
    qtbot.addWidget(page)
    page.show()
    monkeypatch.setattr(officina_dialogs, "ask_folder", lambda *_a, **_k: tmp_path / "scelta")

    def refuse(_cfg):
        raise OSError("disco pieno")

    monkeypatch.setattr(fake_core.config, "save", refuse)
    page.choose_root()
    expected = strings.OFFICINA_ROOT_SAVE_FAILED.format(reason="disco pieno")
    assert page.chooser.error.text() == expected and shell.statuses[-1] == expected
    assert page.view() == "chooser"


def test_in_onedrive_uses_the_environment_and_the_folder_names(monkeypatch, tmp_path):
    monkeypatch.setenv("OneDrive", str(tmp_path / "sync"))
    assert officina_dialogs.in_onedrive(tmp_path / "sync" / "a")
    assert officina_dialogs.in_onedrive(tmp_path / "OneDrive - Ditta" / "b")
    assert not officina_dialogs.in_onedrive(tmp_path / "locale")


# -------------------------------------------------------- the initiatives ---

def test_a_new_initiative_appears_in_the_list(page, monkeypatch):
    assert page.view() == "list"
    assert page.list.body.currentWidget() is page.list.empty
    monkeypatch.setattr(officina_dialogs, "ask_text", lambda *_a, **_k: "Iniziativa di prova")
    QTest.mouseClick(page.list.new_button, Qt.MouseButton.LeftButton)
    assert page.list.names() == ["Iniziativa di prova"]
    assert page.list.selected_name() == "Iniziativa di prova"
    assert page.list.table.item(0, 2).text() == strings.OFFICINA_ACCEPTED_OF.format(
        accepted=0, total=0)


def test_a_duplicate_initiative_is_refused_with_a_sentence(page, shell, monkeypatch):
    page.api.create_initiative("Doppia")
    monkeypatch.setattr(officina_dialogs, "ask_text", lambda *_a, **_k: "Doppia")
    page.new_initiative()
    assert shell.statuses and "Doppia" in shell.statuses[-1]


def test_open_folder_opens_the_officina_root(page, fake_core):
    QTest.mouseClick(page.list.folder_button, Qt.MouseButton.LeftButton)
    assert fake_core.extract.folders == [page.api.workspace_root()]


# ----------------------------------------------------------------- cases ---

def test_a_case_is_added_from_a_file(page, fake_core, tmp_path, monkeypatch, shell):
    page.api.create_initiative("Da file")
    page.refresh()
    page.open_initiative("Da file")
    assert page.view() == "board"
    source = payload_file(tmp_path / "in", "MOD_TEST_FILE")
    monkeypatch.setattr(
        "qtrequestory.ui.pages.officina_actions.ask_add_case",
        lambda *_a, **_k: AddChoice("Da file", False, "abilitato", "MOD_TEST_FILE", source))
    QTest.mouseClick(page.board.add_file_button, Qt.MouseButton.LeftButton)

    assert [c.id for c in page.ini.cases] == ["MOD_TEST_FILE__abilitato"]
    texts = page.board.row_texts("MOD_TEST_FILE__abilitato")
    assert "MOD_TEST_FILE" in texts[0] and "abilitato" in texts[0]
    assert strings.OFFICINA_NONE in texts[1], "no document yet: the tiles say so"
    assert texts[2] == strings.OFFICINA_PILL_NO_TARGET
    assert shell.toasts[-1][1] == "ok"


def test_the_add_dialog_prefills_the_key_from_the_payload(qtbot, tmp_path):
    dialog = officina_add.AddCaseDialog(["Una"], current="Una", from_file=True)
    qtbot.addWidget(dialog)
    dialog.set_file(payload_file(tmp_path, "MOD_TEST_CHIAVE"))
    choice = dialog.choice()
    assert choice == AddChoice("Una", False, "", "MOD_TEST_CHIAVE",
                               tmp_path / "MOD_TEST_CHIAVE.json")
    dialog.initiative.setCurrentIndex(dialog.initiative.count() - 1)  # "Nuova iniziativa…"
    assert dialog.choice() is None
    assert dialog.error.text() == strings.OFFICINA_ADD_NEED_NAME


def open_case(page, fake_core, tmp_path, key: str = "MOD_TEST_A", *, target: bool = True):
    make_initiative(fake_core, "Banco", (key,), tmp_path)
    case = fake_core.officina.load("Banco").cases[0]
    if target:
        source = tmp_path / "cliente" / "Modulo del cliente.pdf"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(canned_pdf("MOD_TEST documento generato dal generatore finto"))
        fake_core.officina.set_target(case, source)
    page.refresh()
    page.open_initiative("Banco")
    page.open_case(case.id)
    return case


def test_f5_in_the_case_view_generates_a_new_tobe(qtbot, page, fake_core, runner, tmp_path):
    case = open_case(page, fake_core, tmp_path)
    assert page.view() == "case"
    qtbot.waitUntil(lambda: page.case_view.right.message_text() == strings.OFFICINA_NO_VERSION,
                    timeout=5000)
    assert page.case_view.isAncestorOf(QApplication.focusWidget()), "focus lands in the case"
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_F5)
    assert runner.job(GENERATE_JOB) is not None, "F5 submits officina-generate"
    wait_idle(qtbot, page)
    qtbot.waitUntil(lambda: page.case_view.current_version_key() == "v1", timeout=5000)
    assert [v.number for v in fake_core.officina.load("Banco").cases[0].tobe_versions()] == [1]
    assert list(page.case_view.switch.buttons) == ["v1"]
    qtbot.waitUntil(lambda: page.case_view.right.showing_document(), timeout=10000)
    assert page.case_view.left.showing_document()
    qtbot.waitUntil(lambda: page.case_view.diffs.summary.text() == strings.OFFICINA_DIFF_EQUAL,
                    timeout=10000)
    assert case.id == page.case_id


def test_a_failed_generation_shows_the_reason_in_a_banner(qtbot, page, fake_core, tmp_path):
    open_case(page, fake_core, tmp_path)
    fake_core.officina.set_response(b"<html>errore del gateway</html>", status=502)
    page.case_view.regenerate_button.click()
    wait_idle(qtbot, page)
    banner = page.case_view.banner.text()
    assert "502" in banner and banner.startswith("Generazione non riuscita")
    assert fake_core.officina.load("Banco").cases[0].tobe_versions() == []


def _no_verdicts_yet(*_args, **_kwargs):
    raise NotImplementedError("Officina fase 2: in arrivo")


def test_the_differences_are_listed_with_their_kind_and_text(qtbot, page, fake_core, tmp_path,
                                                             monkeypatch):
    """Phase-1 path: a core that cannot judge yet (the real one until E7)."""
    monkeypatch.setattr(fake_core.officina, "compare_case", _no_verdicts_yet)
    open_case(page, fake_core, tmp_path)
    fake_core.officina.set_response(canned_pdf("MOD_TEST documento generato dal generatore vero"))
    page.case_view.regenerate_button.click()
    wait_idle(qtbot, page)
    qtbot.waitUntil(lambda: bool(page.case_view.diffs.texts()), timeout=10000)
    texts = page.case_view.diffs.texts()
    assert texts == ["pag. 1 · cambiato\n«finto» → «vero»"]
    assert page.case_view.diffs.summary.text() == strings.OFFICINA_DIFF_COUNT_ONE
    page.case_view.diffs.list.setCurrentRow(0)
    assert page.case_view.right.view.focused_difference() is not None


def test_a_compare_error_is_a_readable_message(qtbot, page, fake_core, tmp_path):
    open_case(page, fake_core, tmp_path)
    page.case_view.regenerate_button.click()
    wait_idle(qtbot, page)
    fake_core.officina.set_compare_error("Edge non trovato: impossibile convertire l'HTML")
    page.open_case(page.case_id, "v1")
    expected = strings.OFFICINA_DIFF_ERROR.format(
        reason="Edge non trovato: impossibile convertire l'HTML")
    qtbot.waitUntil(lambda: page.case_view.diffs.summary.text() == expected, timeout=10000)
    assert "Traceback" not in page.case_view.diffs.summary.text()


def test_an_unexpected_failure_preparing_the_documents_is_a_sentence(qtbot, page, fake_core,
                                                                     tmp_path, monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("PDFium non disponibile")

    monkeypatch.setattr("qtrequestory.ui.pages.officina_compare_jobs.load_case_docs", boom)
    open_case(page, fake_core, tmp_path)
    expected = strings.OFFICINA_DIFF_ERROR.format(reason="PDFium non disponibile")
    qtbot.waitUntil(lambda: page.case_view.diffs.summary.text() == expected, timeout=5000)
    assert page.case_view.left.message_text() == expected


def test_batch_continues_after_one_failure(qtbot, page, fake_core, tmp_path):
    """Review Focus 5: case 2 of 3 fails; 1 and 3 get their version, 2 its reason."""
    make_initiative(fake_core, "Lotto", ("MOD_TEST_A", "MOD_TEST_B", "MOD_TEST_C"), tmp_path)
    fake_core.officina.set_response_for("MOD_TEST_B", b"errore interno", status=500)
    page.refresh()
    page.open_initiative("Lotto")
    page.board.select_cases(["MOD_TEST_A", "MOD_TEST_B", "MOD_TEST_C"])
    assert page.board.regenerate_button.isEnabled()
    QTest.mouseClick(page.board.regenerate_button, Qt.MouseButton.LeftButton)
    wait_idle(qtbot, page)

    cases = {c.id: c for c in fake_core.officina.load("Lotto").cases}
    assert [v.number for v in cases["MOD_TEST_A"].tobe_versions()] == [1]
    assert cases["MOD_TEST_B"].tobe_versions() == []
    assert [v.number for v in cases["MOD_TEST_C"].tobe_versions()] == [1]
    run_b = page.board.row_texts("MOD_TEST_B")[3]
    assert run_b.startswith("Generazione non riuscita") and "HTTP 500" in run_b
    assert "non riuscita" not in page.board.row_texts("MOD_TEST_A")[3]
    assert "v1" in page.board.row_texts("MOD_TEST_C")[1]
    assert len(fake_core.officina.requests) == 3


def test_a_failure_belongs_to_its_initiative_not_to_a_case_id(qtbot, page, fake_core, tmp_path):
    """Case ids repeat across initiatives: MOD_TEST_A of "Prima" failing says
    nothing about MOD_TEST_A of "Seconda"."""
    make_initiative(fake_core, "Prima", ("MOD_TEST_A",), tmp_path / "1")
    make_initiative(fake_core, "Seconda", ("MOD_TEST_A",), tmp_path / "2")
    fake_core.officina.set_response(b"errore", status=500)
    page.refresh()
    page.open_initiative("Prima")
    page.regenerate_tobe(["MOD_TEST_A"])
    wait_idle(qtbot, page)
    assert "HTTP 500" in page.board.row_texts("MOD_TEST_A")[3]
    page.show_list()
    page.open_initiative("Seconda")
    assert "non riuscita" not in page.board.row_texts("MOD_TEST_A")[3]
    assert page.queue.state("Prima", "MOD_TEST_A") is None


def test_the_batch_runs_at_most_three_cases_at_once(qtbot, page, fake_core, tmp_path):
    keys = tuple(f"MOD_TEST_{n}" for n in range(5))
    make_initiative(fake_core, "Cinque", keys, tmp_path)
    fake_core.officina.delay_s = 0.2
    page.refresh()
    page.open_initiative("Cinque")
    page.regenerate_tobe(list(keys))
    states = [page.queue.state("Cinque", k) for k in keys]
    assert states.count("running") == 3 and states.count("queued") == 2
    assert page.board.progress_row.isVisibleTo(page)
    wait_idle(qtbot, page)
    assert all(len(c.tobe_versions()) == 1 for c in fake_core.officina.load("Cinque").cases)
    assert not page.board.progress_row.isVisibleTo(page)


def test_cancel_drops_the_cases_still_waiting(qtbot, page, fake_core, tmp_path):
    keys = tuple(f"MOD_TEST_{n}" for n in range(5))
    make_initiative(fake_core, "Annullo", keys, tmp_path)
    fake_core.officina.delay_s = 0.3
    page.refresh()
    page.open_initiative("Annullo")
    page.regenerate_tobe(list(keys))
    # the three running jobs start on the next event-loop turn: cancelled first,
    # they are refused before sending, and the two waiting ones never run
    QTest.mouseClick(page.board.cancel_button, Qt.MouseButton.LeftButton)
    wait_idle(qtbot, page)
    assert fake_core.officina.requests == []
    assert not any(c.tobe_versions() for c in fake_core.officina.load("Annullo").cases)
    for key in keys[:3]:
        run = page.board.row_texts(key)[3]
        assert run == strings.OFFICINA_RUN_CANCELLED, "a cancelled case is not a failure"
    assert page.failures == {}


def test_a_case_already_queued_is_not_queued_twice(qtbot, page, fake_core, tmp_path, shell):
    make_initiative(fake_core, "Doppio", ("MOD_TEST_A", "MOD_TEST_B"), tmp_path)
    fake_core.officina.delay_s = 0.2
    page.refresh()
    page.open_initiative("Doppio")
    page.regenerate_tobe(["MOD_TEST_A"])
    page.regenerate_tobe(["MOD_TEST_A", "MOD_TEST_B"])
    assert shell.statuses[-1] == strings.OFFICINA_ALREADY_QUEUED.format(cases="MOD_TEST_A")
    wait_idle(qtbot, page)
    assert len(fake_core.officina.requests) == 2
    assert [len(c.tobe_versions()) for c in fake_core.officina.load("Doppio").cases] == [1, 1]


def test_the_batch_line_belongs_to_its_initiative(qtbot, page, fake_core, tmp_path):
    make_initiative(fake_core, "Corre", ("MOD_TEST_A",), tmp_path / "1")
    make_initiative(fake_core, "Ferma", ("MOD_TEST_B",), tmp_path / "2")
    fake_core.officina.delay_s = 0.3
    page.refresh()
    page.open_initiative("Corre")
    page.regenerate_tobe(["MOD_TEST_A"])
    assert page.board.progress_row.isVisibleTo(page)
    page.show_list()
    page.open_initiative("Ferma")
    assert not page.board.progress_row.isVisibleTo(page), "not this initiative's batch"
    wait_idle(qtbot, page)


def test_payload_and_target_are_locked_while_the_case_is_queued(qtbot, page, fake_core,
                                                                tmp_path):
    open_case(page, fake_core, tmp_path)
    fake_core.officina.delay_s = 0.3
    page.case_view.regenerate_button.click()
    view = page.case_view
    assert not view.editor_button.isEnabled() and not view.target_button.isEnabled()
    wait_idle(qtbot, page)
    assert view.editor_button.isEnabled() and view.target_button.isEnabled()


def test_an_unexpected_generation_error_reads_in_italian_and_masked(qtbot, page, fake_core,
                                                                    tmp_path, monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("socket died https://acct.example.invalid/c/f.pdf?sv=1&sig=SEGRETO")

    open_case(page, fake_core, tmp_path)
    monkeypatch.setattr(fake_core.officina, "generate", boom)
    page.case_view.regenerate_button.click()
    wait_idle(qtbot, page)
    banner = page.case_view.banner.text()
    assert banner.startswith("Generazione non riuscita: "
                             + strings.OFFICINA_GENERATION_INTERRUPTED)
    assert "SEGRETO" not in banner and "sig=***" in banner


def test_closing_the_window_drops_the_waiting_cases(qtbot, fake_core, runner, tmp_path,
                                                   monkeypatch):
    from qtrequestory.ui import main_window as mw

    keys = tuple(f"MOD_TEST_{n}" for n in range(5))
    make_initiative(fake_core, "Chiusura", keys, tmp_path)
    fake_core.officina.delay_s = 0.3
    win = MainWindow(fake_core, runner)
    qtbot.addWidget(win)
    win.show()
    win.show_page("officina")
    page = win.page("officina")
    page.open_initiative("Chiusura")
    page.regenerate_tobe(list(keys))
    monkeypatch.setattr(mw, "confirm_quit_during_job", lambda *_a, **_k: True)
    assert win.close() is True
    wait_idle(qtbot, page)
    assert fake_core.officina.requests == [], "nothing is sent after the user quit"


def test_generate_missing_asis_only_touches_cases_without_one(qtbot, page, fake_core, tmp_path):
    ini = make_initiative(fake_core, "Base", ("MOD_TEST_A", "MOD_TEST_B"), tmp_path)
    fake_core.officina.generate(ini, ini.cases[0], "asis")
    page.refresh()
    page.open_initiative("Base")
    QTest.mouseClick(page.board.missing_button, Qt.MouseButton.LeftButton)
    wait_idle(qtbot, page)
    assert len(fake_core.officina.requests) == 2  # the direct one above, then only B
    assert all(c.asis() is not None for c in fake_core.officina.load("Base").cases)


def test_regenerating_the_asis_without_a_note_is_refused(qtbot, page, fake_core, tmp_path,
                                                         monkeypatch, shell):
    open_case(page, fake_core, tmp_path)
    page.case_view.asis_button.click()  # the first AS-IS needs no note
    wait_idle(qtbot, page)
    assert page.case_view.asis_button.text() == strings.OFFICINA_REGENERATE_ASIS
    first = fake_core.officina.load("Banco").cases[0].asis()
    sent = len(fake_core.officina.requests)

    asked = []
    monkeypatch.setattr(officina_dialogs, "ask_note", lambda *a, **_k: asked.append(a) or None)
    page.case_view.asis_button.click()
    assert asked, "a note is asked for"
    assert shell.statuses[-1] == strings.OFFICINA_ASIS_NOTE_REQUIRED
    assert len(fake_core.officina.requests) == sent, "nothing was sent"
    assert fake_core.officina.load("Banco").cases[0].asis() == first

    monkeypatch.setattr(officina_dialogs, "ask_note", lambda *_a, **_k: "nuovo master")
    page.case_view.asis_button.click()
    wait_idle(qtbot, page)
    case = fake_core.officina.load("Banco").cases[0]
    assert case.history[-1]["note"] == "nuovo master"


def test_a_version_deleted_on_disk_while_open_is_shown_missing(qtbot, page, fake_core,
                                                               tmp_path):
    """Review Focus 4 at the UI: a TO-BE file deleted in Explorer."""
    open_case(page, fake_core, tmp_path)
    page.case_view.regenerate_button.click()
    wait_idle(qtbot, page)
    tobe = fake_core.officina.load("Banco").cases[0].latest_tobe()

    def deleted() -> bool:  # the viewer's render thread may hold the file a moment
        try:
            tobe.path.unlink()
        except PermissionError:
            return False
        return True

    qtbot.waitUntil(deleted, timeout=5000)
    page.refresh()  # what showing the tab again does
    qtbot.waitUntil(lambda: page.case_view.right.message_text() not in
                    ("", strings.OFFICINA_LOADING), timeout=10000)
    assert page.case_view.switch.buttons["v1"].toolTip() == strings.OFFICINA_THUMB_MISSING_TIP
    assert page.case_view.diffs.summary.text().startswith("Confronto non riuscito")
    page.show_board()
    tiles = page.board.table.cellWidget(0, 1).findChildren(QLabel)
    assert tiles[2].property("pill") == "bad"
    assert tiles[2].toolTip() == strings.OFFICINA_THUMB_MISSING_TIP


def test_a_long_key_is_shown_whole_at_1366(qtbot, page, fake_core, tmp_path):
    key = "MOD_TEST_ENERGY_SCHEDA_SINT_LUCE_IND_CAMBIOFORN_POWBY_RICHIESTA_B"
    make_initiative(fake_core, "Lunga", (key, "MOD_TEST_A"), tmp_path)
    page.resize(1366, 700)
    page.refresh()
    page.open_initiative("Lunga")
    qtbot.wait(50)
    row = next(r for r, c in enumerate(page.ini.cases) if c.key == key)
    label = page.board.table.cellWidget(row, 0).findChildren(MiddleElidedLabel)[0]
    assert label.text() == key
    assert not label.is_elided(), "the whole key is on screen"
    assert page.board.table.cellWidget(row, 0).toolTip() == key
    page.board.table.setColumnWidth(0, 120)  # squeezed by hand: cut in the middle
    qtbot.wait(20)
    assert label.is_elided()
    shown = label.fontMetrics().elidedText(key, Qt.TextElideMode.ElideMiddle,
                                           label.contentsRect().width())
    assert shown.endswith("_B") and "…" in shown


def test_the_target_is_chosen_from_a_file(qtbot, page, fake_core, tmp_path, monkeypatch):
    open_case(page, fake_core, tmp_path, target=False)
    assert page.case_view.left.message_text() in (strings.OFFICINA_LOADING,
                                                  strings.OFFICINA_NO_TARGET)
    source = tmp_path / "cliente" / "Target cliente.pdf"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(canned_pdf("testo del cliente"))
    monkeypatch.setattr(officina_dialogs, "ask_open_file", lambda *_a, **_k: source)
    page.case_view.target_button.click()
    assert page.case_view.left.name.text() == "Target cliente.pdf"
    qtbot.waitUntil(lambda: page.case_view.left.showing_document(), timeout=10000)


def test_mark_accepted_and_reopen(qtbot, page, fake_core, tmp_path, monkeypatch):
    open_case(page, fake_core, tmp_path)
    monkeypatch.setattr(officina_dialogs, "confirm", lambda *_a, **_k: True)
    page.case_view.accept_button.click()
    assert fake_core.officina.load("Banco").cases[0].status == "accepted"
    assert page.case_view.accept_button.text() == strings.OFFICINA_REOPEN
    page.case_view.accept_button.click()
    assert fake_core.officina.load("Banco").cases[0].status == "open"


def test_the_editor_saves_headers_and_payload(qtbot, page, fake_core, tmp_path):
    from qtrequestory.ui.pages.officina_editor import PayloadHeaderDialog

    case = open_case(page, fake_core, tmp_path)
    dialog = PayloadHeaderDialog(fake_core, page._case(case.id))
    qtbot.addWidget(dialog)
    dialog.editor.setPlainText("{ non json")
    assert dialog.problem().startswith("JSON non valido")
    dialog.editor.setPlainText('{"documents": [], "extra": "MOD_TEST"}')
    dialog._add_row("X-Flag", "active")
    dialog._add_row("x-flag", "doppio")
    assert "duplicata" in dialog.problem()  # the core's header_problems, as in Impostazioni
    dialog.headers.removeRow(1)
    dialog._add_row("Host", "example.invalid")
    assert "client HTTP" in dialog.problem()
    dialog.headers.removeRow(1)
    assert dialog.save() == ""
    saved = fake_core.officina.load("Banco").cases[0]
    assert saved.headers == {"X-Flag": "active"}
    assert fake_core.officina.payload(saved) == {"documents": [], "extra": "MOD_TEST"}


# ------------------------------------------------------- the shell and Ricerca ---

@pytest.fixture
def window(qtbot, fake_core, runner):
    win = MainWindow(fake_core, runner)
    qtbot.addWidget(win)
    win.show()
    return win


def test_ctrl_3_opens_the_officina_tab(qtbot, window):
    assert "officina" in window.pages()
    assert isinstance(window.page("officina"), OfficinaPage)
    assert list(window.app_bar.tabs) == ["search", "sync", "officina"]
    window.shortcuts["Ctrl+3"].activated.emit()
    assert window.current_page_key() == "officina"
    assert window.app_bar.tabs["officina"].toolTip() == "Officina (Ctrl+3)"


def test_closing_during_a_generation_asks_once_for_all_lanes(qtbot, window, runner, monkeypatch):
    import threading

    from qtrequestory.ui import main_window as mw
    from qtrequestory.ui.quit_dialog import QUIT_INFO, job_label

    asked: list[str] = []
    monkeypatch.setattr(mw, "confirm_quit_during_job",
                        lambda _parent, name, _detail="": asked.append(name) or False)
    gate = threading.Event()
    jobs = [runner.submit(lane, lambda *, cancel: gate.wait(5.0))
            for lane in OFFICINA_GENERATE_JOBS[:2]]
    try:
        assert window.close() is False
        assert asked == [GENERATE_JOB], "one question, not one per lane"
        assert job_label(OFFICINA_GENERATE_JOBS[1]) == strings.OFFICINA_JOB_GENERATE
        assert QUIT_INFO[GENERATE_JOB] == strings.OFFICINA_QUIT_INFO
        monkeypatch.setattr(mw, "confirm_quit_during_job", lambda *_a, **_k: True)
        assert window.close() is True
        assert all(job.token.is_set() for job in jobs), "both lanes are cancelled"
    finally:
        gate.set()
    for job in jobs:
        qtbot.waitUntil(lambda j=job: j.finished, timeout=5000)


def test_the_ricerca_menu_adds_a_case_with_the_key_of_the_hit(qtbot, window, fake_core,
                                                              monkeypatch):
    search = window.page("search")
    hit = fake_core.index.hits[0]
    monkeypatch.setattr(officina_add, "ask_add_case",
                        lambda *_a, **k: AddChoice("Dalla ricerca", True, ""))
    menu = search.build_context_menu(hit)
    entry = next(a for a in menu.actions() if a.text() == strings.OFFICINA_ADD_MENU)
    entry.trigger()
    menu.deleteLater()

    cases = fake_core.officina.load("Dalla ricerca").cases
    assert [c.key for c in cases] == [hit.template_key]
    assert cases[0].source_fdi == hit.fdi
    assert fake_core.officina.payload(cases[0]) == json.loads(fake_core.index.read_body(hit))
    window.show_page("officina")
    officina = window.page("officina")
    assert "Dalla ricerca" in officina.list.names()


def test_the_ricerca_menu_refuses_a_vanished_call_and_a_duplicate(qtbot, window, fake_core,
                                                                   monkeypatch):
    search = window.page("search")
    hits = fake_core.index.hits
    monkeypatch.setattr(officina_add, "ask_add_case",
                        lambda *_a, **_k: AddChoice("Rifiuti", True, ""))

    def add(hit):
        menu = search.build_context_menu(hit)
        next(a for a in menu.actions() if a.text() == strings.OFFICINA_ADD_MENU).trigger()
        menu.deleteLater()
        return window.statusBar().currentMessage()

    fake_core.index.set_missing(hits[0])
    message = add(hits[0])
    assert message.startswith("Caso non aggiunto") and "ripetere la ricerca" in message

    monkeypatch.setattr(officina_add, "ask_add_case",
                        lambda *_a, **_k: AddChoice("Rifiuti", False, ""))
    window.statusBar().clearMessage()
    assert add(hits[1]) == ""  # added: a toast, no status message
    assert add(hits[1]) == strings.OFFICINA_ADD_FAILED.format(
        reason=strings.OFFICINA_ADD_DUPLICATE)
    assert [c.key for c in fake_core.officina.load("Rifiuti").cases] == [hits[1].template_key]


def test_the_ricerca_menu_says_when_the_officina_has_no_folder(qtbot, window, fake_core):
    cfg = fake_core.config.config
    fake_core.config.config = dataclasses.replace(
        cfg, officina=dataclasses.replace(cfg.officina, root=None))
    search = window.page("search")
    menu = search.build_context_menu(fake_core.index.hits[0])
    next(a for a in menu.actions() if a.text() == strings.OFFICINA_ADD_MENU).trigger()
    menu.deleteLater()
    assert window.statusBar().currentMessage() == strings.OFFICINA_ADD_NO_ROOT


def test_add_from_search_goes_to_ricerca_with_a_hint(page, fake_core, tmp_path, shell):
    make_initiative(fake_core, "Suggerimento", (), tmp_path)
    page.refresh()
    page.open_initiative("Suggerimento")
    page.board.add_search_button.click()
    assert shell.shown == ["search"]
    assert shell.toasts[-1][0] == strings.OFFICINA_SEARCH_HINT


# ---------------------------------------------------------------- strings ---

def test_officina_strings_have_no_english_words():
    from qtrequestory.ui.strings import officina
    from tests.ui.test_strings import ENGLISH_DENYLIST

    pattern = re.compile(r"\b(" + "|".join(ENGLISH_DENYLIST) + r")\b", re.IGNORECASE)
    names = [n for n in vars(officina) if n.isupper()]
    assert names and all(n.startswith("OFFICINA_") for n in names)
    offenders = {n: v for n, v in vars(officina).items()
                 if n.isupper() and pattern.search(re.sub(r"\{[^}]*\}", "", v))}
    assert not offenders


def test_importing_the_page_does_not_load_pypdfium2():
    from tests.test_officina_boundary import _imported_after

    mods = _imported_after("import qtrequestory.ui.pages.officina_page")
    assert not any(m.startswith("pypdfium2") for m in mods)


def test_a_new_folder_from_impostazioni_goes_quietly_to_the_list(qtbot, page, fake_core, shell,
                                                                  tmp_path):
    """The old initiative is not "gone", and a same-named one in the new folder
    is not silently swapped in."""
    import dataclasses

    make_initiative(fake_core, "Banco", ("MOD_TEST_A",), tmp_path)
    page.refresh()
    page.open_initiative("Banco")
    assert page.view() == "board"
    new_root = tmp_path / "altra-officina"
    fake_core.config.config.officina = dataclasses.replace(fake_core.config.config.officina,
                                                           root=new_root)
    fake_core.officina.create_initiative("Banco")  # same name, other folder
    before = (list(shell.statuses), list(shell.toasts))
    page.on_config_changed(fake_core.config.config)
    assert page.view() == "list"
    assert page.ini is None
    assert (shell.statuses, shell.toasts) == before


def test_is_writing_counts_waiting_cases(qtbot, page, fake_core, runner, tmp_path):
    import threading

    from qtrequestory.ui.workers import OFFICINA_GENERATE_JOBS

    release = threading.Event()
    for lane in OFFICINA_GENERATE_JOBS:  # every lane taken by someone else
        assert runner.submit(lane, lambda: release.wait(10)) is not None
    try:
        ini = make_initiative(fake_core, "Banco", ("MOD_TEST_A",), tmp_path)
        page.queue.enqueue(ini, ini.cases, "tobe")
        assert page.queue.state("Banco", ini.cases[0].id) == "queued"
        assert page.is_writing()
        page.queue.cancel()
    finally:
        release.set()
    qtbot.waitUntil(lambda: not any(runner.is_running(n) for n in OFFICINA_GENERATE_JOBS),
                    timeout=5000)
    assert not page.is_writing()


# ------------------------------------------------ phase 2: verdicts (U1) ---

def _placed(diff, left_y: float | None, right_y: float | None):
    """``diff`` with one word box per side (synthetic boxes on page 1)."""
    from qtrequestory.ui.contracts import Word

    left = (Word(diff.left_text, 0, 60, left_y, 140, left_y + 12),) if left_y is not None else ()
    right = (Word(diff.right_text, 0, 60, right_y, 140, right_y + 12),) if right_y is not None else ()
    return dataclasses.replace(diff, left=left, right=right)


def test_the_case_view_draws_the_verdicts_of_compare_case(qtbot, page, fake_core, tmp_path):
    from tests.fakes.fake_core import fake_diff

    case = open_case(page, fake_core, tmp_path)
    page.case_view.regenerate_button.click()
    wait_idle(qtbot, page)
    api = fake_core.officina
    api.set_canned(case.id, 0, [_placed(fake_diff("cambiato", "testo", "12,00", "11,00"), 100, 100)])
    api.set_canned(case.id, 1, [_placed(fake_diff("cambiato", "testo", "12,00", "11,50"), 100, 100),
                                _placed(fake_diff("in_piu", "testo", "", "Nota"), None, 200)])
    page.open_case(page.case_id, "v1")
    view = page.case_view
    qtbot.waitUntil(lambda: bool(view.right.view.highlight_items(2)), timeout=10000)
    assert [i.look.label for i in view.right.view.highlight_items(1)] == ["in corso"]
    assert [i.look.label for i in view.right.view.highlight_items(2)] == ["regressione"]
    assert [i.look.label for i in view.left.view.highlight_items(1)] == ["in corso"]
    assert view.left.view.highlight_items(2) == [], "an added text has no target words"
    assert len(view.diffs.texts()) == 2, "the list shows the same differences (same ids)"
    view.diffs.list.setCurrentRow(1)
    assert view.right.view.focused_difference() == 2
    assert (case.id, 1) in api.compare_case_calls


def test_without_a_judged_comparison_the_phase_1_one_is_drawn(qtbot, page, fake_core, tmp_path,
                                                                monkeypatch):
    """The AS-IS view, or a core that cannot judge yet (the real one until the
    engine lands: NotImplementedError), keeps the phase-1 text comparison."""
    def not_yet(*_args, **_kwargs):
        raise NotImplementedError("Officina fase 2: in arrivo")

    monkeypatch.setattr(fake_core.officina, "compare_case", not_yet)
    open_case(page, fake_core, tmp_path)
    fake_core.officina.set_response(canned_pdf("MOD_TEST documento generato dal generatore vero"))
    page.case_view.regenerate_button.click()
    wait_idle(qtbot, page)
    qtbot.waitUntil(lambda: bool(page.case_view.diffs.texts()), timeout=10000)
    (item,) = page.case_view.right.view.highlight_items(1)
    assert item.look.label == strings.VERDETTO_NESSUNO


def test_compare_case_and_generation_of_a_case_take_turns(fake_core, tmp_path, monkeypatch):
    """Both write caso.json from a worker: they hold the case's lock (on Windows
    a read during another thread's replace fails and its merge is skipped)."""
    from qtrequestory.ui.pages import officina_judge

    ini = make_initiative(fake_core, "Banco", ("MOD_TEST_A",), tmp_path)
    case = ini.cases[0]
    held = []
    api = fake_core.officina
    monkeypatch.setattr(api, "compare_case",
                        lambda _i, c, _v: held.append(officina_judge.case_lock(_i.id, c.id).locked()))
    monkeypatch.setattr(api, "generate",
                        lambda _i, c, _k, **_kw: held.append(officina_judge.case_lock(_i.id, c.id).locked()))
    officina_judge.judge(fake_core, ini, case, None)
    officina_judge.generate_locked(fake_core, ini, case, "tobe")
    assert held == [True, True]
    assert not officina_judge.case_lock(ini.id, case.id).locked()



def test_a_judged_comparison_without_differences_shows_no_phase_1_ones(qtbot, page, fake_core,
                                                                       tmp_path):
    """The engine judged "nothing to look at" (e.g. only spacing, not counted):
    the phase-1 text differences are not resurrected in grey."""
    open_case(page, fake_core, tmp_path)
    fake_core.officina.set_response(canned_pdf("MOD_TEST documento generato dal generatore vero"))
    page.case_view.regenerate_button.click()
    wait_idle(qtbot, page)
    view = page.case_view
    qtbot.waitUntil(lambda: view.diffs.summary.text() == strings.OFFICINA_DIFF_EQUAL, timeout=10000)
    assert view.right.view.highlight_items(1) == [] and view.diffs.texts() == []


def test_all_fatte_is_not_equal_in_the_list(qtbot, page, fake_core, tmp_path):
    from tests.fakes.fake_core import fake_diff

    case = open_case(page, fake_core, tmp_path)
    page.case_view.regenerate_button.click()
    wait_idle(qtbot, page)
    fake_core.officina.set_canned(case.id, 0, [_placed(fake_diff("cambiato", "testo", "12,00", "11,00"),
                                                       100, 100)])
    page.open_case(page.case_id, "v1")
    expected = strings.ELENCO_ALL_DONE_ONE
    qtbot.waitUntil(lambda: page.case_view.diffs.summary.text() == expected, timeout=10000)
    assert page.case_view.diffs.summary.text() != strings.OFFICINA_DIFF_EQUAL
