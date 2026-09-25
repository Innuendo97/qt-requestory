"""The "Consegna…" dialog: cases, destination, preview, conflicts, summary.

Offscreen, on the fake core (the real Officina service on real files under
the test's tmp folder). Modal questions are answered by replacing the
functions of ``officina_dialogs``.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from qtrequestory.ui import strings
from qtrequestory.ui.pages import officina_delivery, officina_dialogs
from qtrequestory.ui.pages.officina_delivery import DeliveryDialog
from qtrequestory.ui.pages.officina_page import OfficinaPage
from tests.fakes.fake_core import canned_pdf


def _payload(folder: Path, key: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{key}.json"
    path.write_text(json.dumps({"documents": [{"template": {"templateKey": key}}]}), encoding="utf-8")
    return path


@pytest.fixture
def ini(fake_core, tmp_path: Path):
    """Three cases: MOD_TEST_A (accepted, complete), MOD_TEST_B (accepted,
    no TO-BE), MOD_TEST_C (open, complete)."""
    api = fake_core.officina
    ini = api.create_initiative("Prezzi ottobre")
    target = tmp_path / "Contratto atteso.pdf"
    target.write_bytes(canned_pdf("atteso"))
    for key, accepted, tobe in (("MOD_TEST_A", True, True), ("MOD_TEST_B", True, False),
                                ("MOD_TEST_C", False, True)):
        case = api.case_from_file(ini, _payload(tmp_path / "payloads", key), key)
        api.set_target(case, target)
        assert api.generate(ini, case, "asis")[0] is not None
        if tobe:
            assert api.generate(ini, case, "tobe")[0] is not None
        if accepted:
            case.mark_accepted()
            api.save_case(case)
    return api.load("Prezzi ottobre")


@pytest.fixture
def dialog(qtbot, fake_core, runner, ini) -> DeliveryDialog:
    widget = DeliveryDialog(fake_core, runner, ini)
    qtbot.addWidget(widget)
    widget.show()
    return widget


def _ids(ini) -> dict[str, str]:
    return {c.key: c.id for c in ini.cases}


def test_accepted_cases_are_preselected_without_warning(dialog, ini):
    ids = _ids(ini)
    assert dialog.checked_case_ids() == [ids["MOD_TEST_A"], ids["MOD_TEST_B"]]
    assert dialog.warning.isHidden()


def test_a_non_accepted_case_shows_a_warning(dialog, ini):
    dialog.set_checked(_ids(ini)["MOD_TEST_C"], True)

    assert not dialog.warning.isHidden()
    assert "MOD_TEST_C" in dialog.warning.text()
    dialog.set_checked(_ids(ini)["MOD_TEST_C"], False)
    assert dialog.warning.isHidden()


def test_the_preview_shows_the_tree_the_missing_slots_and_the_zip(dialog, tmp_path: Path):
    dialog.set_destination(tmp_path / "consegne")

    lines = dialog.preview_lines()

    assert lines[0].endswith("Prezzi ottobre")
    assert "  MOD_TEST_A" in lines and "    MOD_TEST_A_ASIS.pdf" in lines
    assert "    MOD_TEST_A_TOBE.pdf" in lines and "    Contratto atteso.pdf" in lines
    b = lines.index("  MOD_TEST_B")
    assert lines[b + 1:b + 3] == ["    MOD_TEST_B_ASIS.pdf", "    Contratto atteso.pdf"]
    assert lines[b + 3] == f"    {strings.OFFICINA_DELIVERY_MISSING_TOBE}", "under its folder, no key again"
    assert not any(line.endswith(".zip") for line in lines)
    dialog.zip_box.setChecked(True)
    assert dialog.preview_lines()[-1].strip() == "Prezzi ottobre.zip"


def test_deliver_needs_a_destination_and_a_case(dialog, ini, tmp_path: Path):
    assert not dialog.deliver_button.isEnabled(), "no destination yet"
    dialog.set_destination(tmp_path / "consegne")
    assert dialog.deliver_button.isEnabled()
    for case_id in dialog.checked_case_ids():
        dialog.set_checked(case_id, False)
    assert not dialog.deliver_button.isEnabled()


def _deliver(qtbot, dialog) -> None:
    QTest.mouseClick(dialog.deliver_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: dialog.showing_summary(), timeout=10000)


def test_a_delivery_writes_the_folder_and_the_zip_and_ends_with_a_summary(qtbot, dialog, fake_core, runner,
                                                                          ini, tmp_path: Path):
    dest = tmp_path / "consegne"
    dest.mkdir()
    dialog.set_destination(dest)
    dialog.zip_box.setChecked(True)

    _deliver(qtbot, dialog)

    folder = dest / "Prezzi ottobre"
    assert (folder / "MOD_TEST_A" / "MOD_TEST_A_TOBE.pdf").is_file()
    assert (folder / "MOD_TEST_B" / "MOD_TEST_B_ASIS.pdf").is_file()
    assert not (folder / "MOD_TEST_C").exists(), "not chosen"
    with zipfile.ZipFile(dest / "Prezzi ottobre.zip") as zf:
        assert "MOD_TEST_A/MOD_TEST_A_TOBE.pdf" in zf.namelist()
    summary = dialog.summary_text()
    assert strings.OFFICINA_DELIVERY_DONE_TITLE in summary
    assert "MOD_TEST_B" in summary and strings.OFFICINA_DELIVERY_MISSING_TOBE in summary

    QTest.mouseClick(dialog.open_folder_button, Qt.MouseButton.LeftButton)
    assert fake_core.extract.folders == [folder]

    again = DeliveryDialog(fake_core, runner, fake_core.officina.load("Prezzi ottobre"))
    qtbot.addWidget(again)
    assert again.destination() == dest, "the last destination of this initiative"


def test_conflicts_are_asked_with_apply_to_all(qtbot, dialog, tmp_path: Path, monkeypatch):
    dest = tmp_path / "consegne"
    existing = dest / "Prezzi ottobre" / "MOD_TEST_A"
    existing.mkdir(parents=True)
    (existing / "MOD_TEST_A_ASIS.pdf").write_bytes(b"vecchio")
    (existing / "MOD_TEST_A_TOBE.pdf").write_bytes(b"vecchio")
    asked: list[tuple[Path, int]] = []

    def answer(_parent, path: Path, remaining: int):
        asked.append((path, remaining))
        return "keep_both", True

    monkeypatch.setattr(officina_dialogs, "ask_conflict", answer)
    dialog.set_destination(dest)
    _deliver(qtbot, dialog)

    assert len(asked) == 1 and asked[0][1] == 2, "asked once, applied to both"
    summary = dialog.summary_text()
    assert strings.OFFICINA_DELIVERY_RENAMED.split("(")[0] in summary
    assert "MOD_TEST_A/MOD_TEST_A_ASIS.pdf → MOD_TEST_A_ASIS (2).pdf" in summary
    assert (existing / "MOD_TEST_A_ASIS.pdf").read_bytes() == b"vecchio"
    assert (existing / "MOD_TEST_A_ASIS (2).pdf").is_file() and (existing / "MOD_TEST_A_TOBE (2).pdf").is_file()


def test_each_conflict_can_get_its_own_answer(qtbot, dialog, tmp_path: Path, monkeypatch):
    dest = tmp_path / "consegne"
    existing = dest / "Prezzi ottobre" / "MOD_TEST_A"
    existing.mkdir(parents=True)
    (existing / "MOD_TEST_A_ASIS.pdf").write_bytes(b"vecchio")
    (existing / "MOD_TEST_A_TOBE.pdf").write_bytes(b"vecchio")
    answers = iter([("replace", False), ("skip", False)])
    monkeypatch.setattr(officina_dialogs, "ask_conflict", lambda *_a: next(answers))
    dialog.set_destination(dest)

    _deliver(qtbot, dialog)

    assert (existing / "MOD_TEST_A_ASIS.pdf").read_bytes() != b"vecchio", "replaced"
    assert (existing / "MOD_TEST_A_TOBE.pdf").read_bytes() == b"vecchio", "skipped"
    assert strings.OFFICINA_DELIVERY_SKIPPED.split("{")[0] in dialog.summary_text()


def test_a_failed_file_is_reported_in_the_summary(qtbot, dialog, ini, tmp_path: Path):
    dest = tmp_path / "consegne"
    blocker = dest / "Prezzi ottobre" / "MOD_TEST_A"
    blocker.parent.mkdir(parents=True)
    blocker.write_bytes(b"un file dove serve una cartella")
    dialog.set_destination(dest)

    _deliver(qtbot, dialog)

    summary = dialog.summary_text()
    assert strings.OFFICINA_DELIVERY_PARTIAL_TITLE in summary
    assert "MOD_TEST_A/MOD_TEST_A_ASIS.pdf" in summary
    assert (dest / "Prezzi ottobre" / "MOD_TEST_B" / "MOD_TEST_B_ASIS.pdf").is_file(), "the others delivered"


def test_the_board_button_opens_the_dialog(qtbot, fake_core, runner, ini, monkeypatch):
    page = OfficinaPage(fake_core, runner, None)
    qtbot.addWidget(page)
    page.show()
    page.open_initiative("Prezzi ottobre")
    opened = []
    monkeypatch.setattr(officina_delivery, "open_delivery_dialog",
                        lambda parent, services, job_runner, initiative: opened.append(initiative.name))

    assert page.board.deliver_button.isEnabled()
    QTest.mouseClick(page.board.deliver_button, Qt.MouseButton.LeftButton)

    assert opened == ["Prezzi ottobre"]


def test_an_unexpected_error_ends_in_a_readable_summary(qtbot, dialog, fake_core, tmp_path: Path,
                                                        monkeypatch):
    def broken(*_a, **_k):
        raise OSError("rete non raggiungibile")

    monkeypatch.setattr(fake_core.officina, "deliver", broken)
    dialog.set_destination(tmp_path / "consegne")

    _deliver(qtbot, dialog)

    assert "rete non raggiungibile" in dialog.summary_text()
    assert not dialog.open_folder_button.isEnabled()


def test_a_file_that_appears_during_the_copy_is_kept_and_flagged(qtbot, dialog, fake_core, tmp_path: Path,
                                                                 monkeypatch):
    """Not there at the check, there at the copy: nobody was asked, so it is
    kept next to the new one — and the summary says so."""
    dest = tmp_path / "consegne"
    real = fake_core.officina.delivery_conflicts

    def check_then_plant(ini, items, destination, *, make_zip):
        found = real(ini, items, destination, make_zip=make_zip)
        late = dest / "Prezzi ottobre" / "MOD_TEST_A"
        late.mkdir(parents=True, exist_ok=True)
        (late / "MOD_TEST_A_TOBE.pdf").write_bytes(b"arrivato dopo")
        return found

    monkeypatch.setattr(fake_core.officina, "delivery_conflicts", check_then_plant)
    monkeypatch.setattr(officina_dialogs, "ask_conflict",
                        lambda *_a: pytest.fail("nothing existed at the check"))
    dialog.set_destination(dest)

    _deliver(qtbot, dialog)

    late = dest / "Prezzi ottobre" / "MOD_TEST_A"
    assert (late / "MOD_TEST_A_TOBE.pdf").read_bytes() == b"arrivato dopo"
    assert (late / "MOD_TEST_A_TOBE (2).pdf").is_file()
    assert "MOD_TEST_A/MOD_TEST_A_TOBE.pdf → MOD_TEST_A_TOBE (2).pdf" in dialog.summary_text()
    assert dialog.open_folder_button.isEnabled()
