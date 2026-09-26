"""The Officina tab, final fix wave of phase 1.

Unreadable ``iniziativa.json`` / ``caso.json`` shown and never written over,
the initiative's identity is its folder, the folder chooser validates,
acceptance is tied to a TO-BE version, the generator is named on every send,
the board's comparison job is cancelled when the board is left. Offscreen, on
the fake core (the real service on real files). Synthetic data only.
"""
from __future__ import annotations

import dataclasses
import json
import shutil
from pathlib import Path

import pytest

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import DeliveryReport
from qtrequestory.ui.pages import officina_dialogs
from qtrequestory.ui.pages.officina_delivery import DeliveryDialog
from qtrequestory.ui.pages.officina_format import delivery_summary
from qtrequestory.ui.pages.officina_page import OfficinaPage

from .test_officina_page import FakeWindow, make_initiative, open_case, wait_idle


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


def _break(path: Path) -> None:
    path.write_text("{ rotto", encoding="utf-8")


# ------------------------------------------------ unreadable iniziativa.json ---

def test_the_board_shows_an_unreadable_iniziativa_json_and_refuses_generation(
        qtbot, page, fake_core, tmp_path):
    ini = make_initiative(fake_core, "Banco", ("MOD_TEST_A",), tmp_path)
    _break(ini.folder / "iniziativa.json")
    page.refresh()
    page.open_initiative(ini.id)

    assert "iniziativa.json" in page.board.notice.text()
    page.board.select_cases(["MOD_TEST_A"])
    assert not page.board.regenerate_button.isEnabled()
    assert not page.board.missing_button.isEnabled()

    page.regenerate_tobe(["MOD_TEST_A"])  # e.g. F5 from a stale view
    wait_idle(qtbot, page)
    assert fake_core.officina.requests == []
    assert "iniziativa.json" in page.board.row_texts("MOD_TEST_A")[3]


# ------------------------------------------------------ unreadable caso.json ---

def test_a_case_with_an_unreadable_caso_json_cannot_be_edited_accepted_or_generated(
        qtbot, page, fake_core, tmp_path):
    case = open_case(page, fake_core, tmp_path)
    _break(case.folder / "caso.json")
    page.refresh()

    view = page.case_view
    assert view.case.load_error
    for button in (view.editor_button, view.accept_button, view.regenerate_button,
                   view.asis_button):
        assert not button.isEnabled(), button.text()
    page.show_board()
    page.board.select_cases([case.id])
    assert not page.board.regenerate_button.isEnabled()


def test_accepting_a_case_whose_file_broke_meanwhile_writes_nothing(qtbot, page, fake_core,
                                                                   tmp_path, shell, monkeypatch):
    case = open_case(page, fake_core, tmp_path)
    monkeypatch.setattr(officina_dialogs, "confirm", lambda *_a, **_k: True)
    _break(case.folder / "caso.json")  # after the page read it

    page.toggle_status()

    assert (case.folder / "caso.json").read_text(encoding="utf-8") == "{ rotto"
    assert any("caso.json" in text for text in shell.statuses)


# ------------------------------------------------------- identity: the folder ---

def test_two_folders_with_one_name_are_listed_apart_and_open_their_own(qtbot, page, fake_core,
                                                                       tmp_path):
    ini = make_initiative(fake_core, "Banco", ("MOD_TEST_A",), tmp_path)
    copy = ini.folder.with_name("Banco - Copia")
    shutil.copytree(ini.folder, copy)
    shutil.rmtree(copy / "casi" / "MOD_TEST_A")
    page.refresh()

    names = page.list.names()
    assert len(names) == 2 and len(set(names)) == 2, names
    assert any("Banco - Copia" in n for n in names)

    page.open_initiative("Banco - Copia")
    assert page.ini.folder == copy and page.ini.cases == []
    page.show_list()
    assert page.list.selected_name() == "Banco - Copia"
    page.open_initiative("Banco")
    assert [c.key for c in page.ini.cases] == ["MOD_TEST_A"]


def test_a_generation_finishing_in_the_copy_does_not_touch_the_original(qtbot, page, fake_core,
                                                                        tmp_path):
    ini = make_initiative(fake_core, "Banco", ("MOD_TEST_A",), tmp_path)
    copy = ini.folder.with_name("Banco - Copia")
    shutil.copytree(ini.folder, copy)
    fake_core.officina.delay_s = 0.2
    page.refresh()
    page.open_initiative("Banco - Copia")
    page.regenerate_tobe(["MOD_TEST_A"])
    assert page.queue.state("Banco - Copia", "MOD_TEST_A") == "running"
    page.show_list()
    page.open_initiative("Banco")
    assert page.queue.state("Banco", "MOD_TEST_A") is None
    assert page.board.row_texts("MOD_TEST_A")[3] != strings.OFFICINA_GENERATING_ON.format(env="svil")
    wait_idle(qtbot, page)
    assert fake_core.officina.load("Banco").cases[0].tobe_versions() == []
    assert len(fake_core.officina.load("Banco - Copia").cases[0].tobe_versions()) == 1


# ------------------------------------------------------- the folder chooser ---

def test_the_folder_chooser_refuses_a_folder_inside_the_log_mirror(qtbot, fake_core, runner,
                                                                  shell, monkeypatch):
    cfg = fake_core.config.config
    fake_core.config.config = dataclasses.replace(
        cfg, officina=dataclasses.replace(cfg.officina, root=None))
    page = OfficinaPage(fake_core, runner, shell)
    qtbot.addWidget(page)
    page.show()
    inside = cfg.mirror_root / "officina"
    monkeypatch.setattr(officina_dialogs, "ask_folder", lambda *_a, **_k: inside)

    page.choose_root()

    assert fake_core.config.config.officina.root is None
    assert not fake_core.config.saved
    assert "log" in page.chooser.error.text()
    assert page.view() == "chooser"
    assert not inside.exists(), "nothing is created before the folder is accepted"


# ------------------------------------------------------ acceptance and versions ---

def test_a_new_version_after_acceptance_reopens_and_is_not_preselected(qtbot, page, fake_core,
                                                                      runner, tmp_path,
                                                                      monkeypatch):
    case = open_case(page, fake_core, tmp_path)
    monkeypatch.setattr(officina_dialogs, "confirm", lambda *_a, **_k: True)
    for _ in range(2):
        page.regenerate_tobe([case.id])
        wait_idle(qtbot, page)
    page.toggle_status()  # accept v2
    saved = json.loads((case.folder / "caso.json").read_text(encoding="utf-8"))
    assert saved["status"] == "accepted" and saved["accepted_version"] == 2

    page.regenerate_tobe([case.id])  # v3
    wait_idle(qtbot, page)

    assert page.case_view.case.status == "open"
    assert page.case_view.notice.text() == strings.OFFICINA_CASE_REOPENED
    page.show_board()
    assert strings.OFFICINA_STATUS_REOPENED in page.board.row_texts(case.id)[4]
    dialog = DeliveryDialog(fake_core, runner, page.ini)
    qtbot.addWidget(dialog)
    assert dialog.checked_case_ids() == []


def test_delivery_warns_when_the_latest_tobe_is_not_the_accepted_one(qtbot, fake_core, runner,
                                                                    tmp_path):
    ini = make_initiative(fake_core, "Banco", ("MOD_TEST_A",), tmp_path)
    api = fake_core.officina
    case = ini.cases[0]
    api.generate(ini, case, "tobe")
    raw = json.loads((case.folder / "caso.json").read_text(encoding="utf-8"))
    raw.update(status="accepted", accepted_version=None)  # hand-edited, no version
    (case.folder / "caso.json").write_text(json.dumps(raw), encoding="utf-8")
    dialog = DeliveryDialog(fake_core, runner, api.load(ini.id))
    qtbot.addWidget(dialog)
    dialog.show()

    assert dialog.checked_case_ids() == []
    dialog.set_checked(case.id, True)
    assert not dialog.warning.isHidden()
    assert strings.OFFICINA_DELIVERY_STALE.format(cases="MOD_TEST_A") in dialog.warning.text()


def test_accept_is_disabled_while_the_case_runs(qtbot, page, fake_core, tmp_path):
    case = open_case(page, fake_core, tmp_path)
    fake_core.officina.delay_s = 0.3
    page.regenerate_tobe([case.id])
    assert not page.case_view.accept_button.isEnabled()
    wait_idle(qtbot, page)
    assert page.case_view.accept_button.isEnabled()


# ------------------------------------------------ the generator on every send ---

def test_the_busy_labels_name_the_generator(qtbot, page, fake_core, tmp_path):
    case = open_case(page, fake_core, tmp_path)
    assert "svil" in page.case_view.env_label.text()
    fake_core.officina.delay_s = 0.3
    page.regenerate_tobe([case.id])
    running = strings.OFFICINA_GENERATING_ON.format(env="svil")
    assert page.case_view.busy.text() == running
    assert page.case_view.busy.isVisibleTo(page)
    page.show_board()
    assert page.board.row_texts(case.id)[3] == running
    wait_idle(qtbot, page)


# ------------------------------------------------------ the board's pills ---

def test_the_board_submits_no_comparison_job(qtbot, page, fake_core, tmp_path, monkeypatch):
    """U5: the pills are read from ``riepilogo``; showing the board runs nothing."""
    case = open_case(page, fake_core, tmp_path)
    wait_idle(qtbot, page)
    submitted: list[str] = []
    real_submit = page.runner.submit
    monkeypatch.setattr(page.runner, "submit", lambda name, *a, **k: (submitted.append(name),
                                                                     real_submit(name, *a, **k))[1])
    page.show_board()
    page.show_list()
    page.open_initiative("Banco")
    assert submitted == []
    assert page.board.row_texts(case.id)[2] == strings.OFFICINA_PILL_NO_TOBE


# ------------------------------------------------------------ delivery summary ---

def test_the_delivery_summary_says_the_destination_was_not_remembered(tmp_path):
    report = DeliveryReport(folder=tmp_path / "Banco", remember_problem="iniziativa.json rotto")
    _title, body = delivery_summary(report, [], zip_asked=False)
    assert strings.OFFICINA_DELIVERY_NOT_REMEMBERED.format(reason="iniziativa.json rotto") in body


def test_the_add_dialog_answers_with_the_folder_of_the_initiative(qtbot):
    from qtrequestory.ui.pages.officina_add import AddCaseDialog

    dialog = AddCaseDialog([("Banco", "Banco (Banco)"), ("Banco - Copia", "Banco (Banco - Copia)")],
                           current="Banco - Copia", key="MOD_TEST_A")
    qtbot.addWidget(dialog)
    assert dialog.initiative.currentText() == "Banco (Banco - Copia)"
    assert dialog.choice().initiative == "Banco - Copia"
