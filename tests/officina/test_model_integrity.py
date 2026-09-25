"""qtrequestory.officina.model: damaged or hand-edited files never lose data.

Final fix wave of phase 1: an unreadable ``iniziativa.json`` or ``caso.json``
is reported and never written over; the initiative's identity is its folder;
acceptance is tied to a TO-BE version; hand-edited metadata that could point
outside the case is treated as broken. Synthetic data only.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from qtrequestory.officina import model_io
from qtrequestory.officina.model import Workspace


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    return Workspace(tmp_path / "officina-root")


def _payload() -> dict:
    return {"documents": [{"template": {"templateKey": "MOD_TEST_A"}}]}


def _caso(case) -> dict:
    return json.loads((case.folder / "caso.json").read_text(encoding="utf-8"))


# ------------------------------------------------------- iniziativa.json damaged ---

def test_a_corrupt_iniziativa_json_is_reported_not_silently_defaulted(ws: Workspace):
    ini = ws.create_initiative("Banco")
    (ini.folder / "iniziativa.json").write_text("{ non è json", encoding="utf-8")

    loaded = ws.load(ini.folder.name)

    assert loaded.load_error and "iniziativa.json" in loaded.load_error
    assert loaded.name == "Banco"  # the folder's name, for display
    assert [i.load_error for i in ws.initiatives()] == [loaded.load_error]


def test_a_readable_iniziativa_json_has_no_load_error(ws: Workspace):
    ini = ws.create_initiative("Banco")
    assert ws.load(ini.folder.name).load_error is None


def test_remember_delivery_destination_never_writes_over_an_unreadable_file(ws: Workspace,
                                                                            tmp_path: Path):
    ini = ws.create_initiative("Banco")
    meta = ini.folder / "iniziativa.json"
    meta.write_text('{"name": "Banco", "header_defaults": {"X-Flag": "on"}', encoding="utf-8")
    broken = ws.load(ini.folder.name)

    with pytest.raises(ValueError, match="iniziativa.json"):
        ws.remember_delivery_destination(broken, tmp_path / "consegne")

    assert meta.read_text(encoding="utf-8") == '{"name": "Banco", "header_defaults": {"X-Flag": "on"}'


def test_remember_delivery_destination_rereads_the_file_before_writing(ws: Workspace,
                                                                       tmp_path: Path):
    """Loaded fine, damaged afterwards: still never overwritten."""
    ini = ws.create_initiative("Banco")
    meta = ini.folder / "iniziativa.json"
    meta.write_text("[1, 2]", encoding="utf-8")

    with pytest.raises(ValueError):
        ws.remember_delivery_destination(ini, tmp_path / "consegne")

    assert meta.read_text(encoding="utf-8") == "[1, 2]"


# ------------------------------------------------------------ caso.json damaged ---

def test_save_case_refuses_a_case_loaded_with_a_load_error(ws: Workspace):
    ini = ws.create_initiative("Banco")
    case = ws.add_case(ini, "MOD_TEST_A", "", _payload(), env="svil", source_fdi="fdi-1")
    (case.folder / "caso.json").write_text("{rotto", encoding="utf-8")
    broken = ws.load(ini.folder.name).cases[0]
    assert broken.load_error

    broken.status = "accepted"
    with pytest.raises(ValueError, match="caso.json"):
        ws.save_case(broken)

    assert (case.folder / "caso.json").read_text(encoding="utf-8") == "{rotto"


def test_save_case_refuses_when_the_file_was_damaged_after_loading(ws: Workspace):
    ini = ws.create_initiative("Banco")
    case = ws.add_case(ini, "MOD_TEST_A", "", _payload(), env="svil", source_fdi="fdi-1")
    (case.folder / "caso.json").write_text("{rotto", encoding="utf-8")

    case.notes = "nuova nota"
    with pytest.raises(ValueError, match="caso.json"):
        ws.save_case(case)

    assert (case.folder / "caso.json").read_text(encoding="utf-8") == "{rotto"


def test_replacing_the_asis_never_writes_over_an_unreadable_caso_json(ws: Workspace):
    ini = ws.create_initiative("Banco")
    case = ws.add_case(ini, "MOD_TEST_A", "", _payload(), env="svil", source_fdi=None)
    ws.add_version(case, "asis", b"%PDF-1 old", "pdf", {})
    (case.folder / "caso.json").write_text("{rotto", encoding="utf-8")

    with pytest.raises(ValueError, match="caso.json"):
        ws.add_version(case, "asis", b"%PDF-1 new", "pdf", {}, replace_asis_note="motivo")

    assert (case.folder / "caso.json").read_text(encoding="utf-8") == "{rotto"
    assert (case.folder / "asis" / "asis.pdf").read_bytes() == b"%PDF-1 old"


# ------------------------------------------------------ identity is the folder ---

def test_two_folders_with_the_same_display_name_are_two_initiatives(ws: Workspace):
    original = ws.create_initiative("Banco")
    ws.add_case(original, "MOD_TEST_A", "", _payload(), env="svil", source_fdi=None)
    copy = ws.root / "Banco - Copia"
    copy.mkdir()
    (copy / "casi").mkdir()
    (copy / "iniziativa.json").write_text(json.dumps({"name": "Banco"}), encoding="utf-8")

    both = ws.initiatives()
    assert sorted(i.folder.name for i in both) == ["Banco", "Banco - Copia"]
    assert [i.name for i in both] == ["Banco", "Banco"]

    assert ws.load("Banco - Copia").folder == copy
    assert ws.load("Banco - Copia").cases == []
    assert len(ws.load("Banco").cases) == 1
    assert ws.load("Banco - Copia").id == "Banco - Copia"


def test_load_is_by_folder_never_by_display_name(ws: Workspace):
    folder = ws.root / "cartella-x"
    folder.mkdir(parents=True)
    (folder / "iniziativa.json").write_text(json.dumps({"name": "Nome mostrato"}), encoding="utf-8")

    assert ws.load("cartella-x").name == "Nome mostrato"
    with pytest.raises(FileNotFoundError):
        ws.load("Nome mostrato")


@pytest.mark.parametrize("bad", ["..", ".", "", "a/b", "a\\b", "C:x"])
def test_load_refuses_anything_but_one_folder_name(ws: Workspace, bad: str):
    ws.create_initiative("Banco")
    with pytest.raises(FileNotFoundError):
        ws.load(bad)


# ------------------------------------------------- acceptance tied to a version ---

def test_accept_records_the_accepted_tobe_version(ws: Workspace):
    ini = ws.create_initiative("Banco")
    case = ws.add_case(ini, "MOD_TEST_A", "", _payload(), env="svil", source_fdi=None)
    ws.add_version(case, "tobe", b"%PDF-1 v1", "pdf", {})
    ws.add_version(case, "tobe", b"%PDF-1 v2", "pdf", {})

    case.mark_accepted()
    ws.save_case(case)

    assert _caso(case)["accepted_version"] == 2
    reloaded = ws.load(ini.id).cases[0]
    assert reloaded.status == "accepted" and reloaded.accepted_version == 2
    assert reloaded.acceptance_is_current()


def test_a_new_tobe_after_acceptance_reopens_the_case(ws: Workspace):
    ini = ws.create_initiative("Banco")
    case = ws.add_case(ini, "MOD_TEST_A", "", _payload(), env="svil", source_fdi=None)
    ws.add_version(case, "tobe", b"%PDF-1 v1", "pdf", {})
    ws.add_version(case, "tobe", b"%PDF-1 v2", "pdf", {})
    case.mark_accepted()
    ws.save_case(case)

    ws.add_version(case, "tobe", b"%PDF-1 v3", "pdf", {})

    assert case.status == "open" and case.reopened
    reloaded = ws.load(ini.id).cases[0]
    assert reloaded.status == "open"
    assert reloaded.reopened
    assert reloaded.accepted_version == 2  # what was accepted, kept for the record
    assert not reloaded.acceptance_is_current()


def test_a_new_asis_after_acceptance_reopens_the_case(ws: Workspace):
    ini = ws.create_initiative("Banco")
    case = ws.add_case(ini, "MOD_TEST_A", "", _payload(), env="svil", source_fdi=None)
    ws.add_version(case, "asis", b"%PDF-1 a", "pdf", {})
    ws.add_version(case, "tobe", b"%PDF-1 v1", "pdf", {})
    case.mark_accepted()
    ws.save_case(case)

    ws.add_version(case, "asis", b"%PDF-1 b", "pdf", {}, replace_asis_note="rifatto")

    reloaded = ws.load(ini.id).cases[0]
    assert reloaded.status == "open" and reloaded.reopened
    assert reloaded.history, "the AS-IS note is still recorded"


def test_accepting_again_clears_the_reopened_notice(ws: Workspace):
    ini = ws.create_initiative("Banco")
    case = ws.add_case(ini, "MOD_TEST_A", "", _payload(), env="svil", source_fdi=None)
    ws.add_version(case, "tobe", b"%PDF-1 v1", "pdf", {})
    case.mark_accepted()
    ws.save_case(case)
    ws.add_version(case, "tobe", b"%PDF-1 v2", "pdf", {})

    case = ws.load(ini.id).cases[0]
    case.mark_accepted()
    ws.save_case(case)

    reloaded = ws.load(ini.id).cases[0]
    assert not reloaded.reopened and reloaded.accepted_version == 2
    assert reloaded.acceptance_is_current()


def test_accepted_without_a_recorded_version_is_not_current(ws: Workspace):
    """A hand-edited "accepted" with no accepted_version: delivery must warn."""
    ini = ws.create_initiative("Banco")
    case = ws.add_case(ini, "MOD_TEST_A", "", _payload(), env="svil", source_fdi=None)
    ws.add_version(case, "tobe", b"%PDF-1 v1", "pdf", {})
    raw = _caso(case)
    raw["status"] = "accepted"
    (case.folder / "caso.json").write_text(json.dumps(raw), encoding="utf-8")

    assert not ws.load(ini.id).cases[0].acceptance_is_current()


# ------------------------------------------------------- hand-edited metadata ---

def test_drop_postman_token_is_only_the_json_true(ws: Workspace):
    ini = ws.create_initiative("Banco")
    case = ws.add_case(ini, "MOD_TEST_A", "", _payload(), env="svil", source_fdi=None)
    for value, expected in (("false", False), ("true", False), (1, False), (True, True)):
        raw = _caso(case)
        raw["drop_postman_token"] = value
        (case.folder / "caso.json").write_text(json.dumps(raw), encoding="utf-8")
        assert ws.load(ini.id).cases[0].drop_postman_token is expected, value


def test_null_header_values_are_dropped_with_a_note_never_the_string_none(ws: Workspace):
    ini = ws.create_initiative("Banco")
    meta = ini.folder / "iniziativa.json"
    raw_ini = json.loads(meta.read_text(encoding="utf-8"))
    raw_ini["header_defaults"] = {"X-Flag": None, "office_id": "00001"}
    meta.write_text(json.dumps(raw_ini), encoding="utf-8")
    case = ws.add_case(ini, "MOD_TEST_A", "", _payload(), env="svil", source_fdi=None)
    raw = _caso(case)
    raw["headers"] = {"branch_id": None, "service_number": "S1"}
    (case.folder / "caso.json").write_text(json.dumps(raw), encoding="utf-8")

    loaded = ws.load(ini.id)

    assert loaded.header_defaults == {"office_id": "00001"}
    assert any("X-Flag" in note for note in loaded.load_notes)
    loaded_case = loaded.cases[0]
    assert loaded_case.headers == {"service_number": "S1"}
    assert any("branch_id" in note for note in loaded_case.load_notes)
    assert loaded_case.load_error is None


@pytest.mark.parametrize("name", ["../../fuori.pdf", "..", "sub/dir.pdf", "sub\\dir.pdf",
                                  "C:\\altro.pdf", ""])
def test_a_target_name_that_is_not_one_safe_component_is_broken(ws: Workspace, tmp_path: Path,
                                                                name: str):
    ini = ws.create_initiative("Banco")
    case = ws.add_case(ini, "MOD_TEST_A", "", _payload(), env="svil", source_fdi=None)
    src = tmp_path / "cliente.pdf"
    src.write_bytes(b"%PDF-1 target")
    ws.set_target(case, src)
    (tmp_path / "officina-root" / "fuori.pdf").write_bytes(b"%PDF-1 outside")
    meta = case.folder / "target" / "target.meta.json"
    raw = json.loads(meta.read_text(encoding="utf-8"))
    raw["original_name"] = name
    meta.write_text(json.dumps(raw), encoding="utf-8")

    target = case.target()

    assert target is not None
    assert target.broken and target.missing
    assert target.path.parent == case.folder / "target" or target.path == case.folder / "target"
    assert not target.path.is_file()


def test_a_target_doc_type_that_is_not_pdf_or_html_falls_back_to_the_name(ws: Workspace,
                                                                          tmp_path: Path):
    ini = ws.create_initiative("Banco")
    case = ws.add_case(ini, "MOD_TEST_A", "", _payload(), env="svil", source_fdi=None)
    src = tmp_path / "cliente.html"
    src.write_text("<html>x</html>", encoding="utf-8")
    ws.set_target(case, src)
    meta = case.folder / "target" / "target.meta.json"
    raw = json.loads(meta.read_text(encoding="utf-8"))
    raw["doc_type"] = "exe"
    meta.write_text(json.dumps(raw), encoding="utf-8")

    assert case.target().doc_type == "html"


@pytest.mark.parametrize("doc_type", ["exe", "../../x", "", None, 3])
def test_a_version_doc_type_that_is_not_pdf_or_html_never_builds_a_path(ws: Workspace,
                                                                        doc_type):
    ini = ws.create_initiative("Banco")
    case = ws.add_case(ini, "MOD_TEST_A", "", _payload(), env="svil", source_fdi=None)
    ws.add_version(case, "tobe", b"%PDF-1 v1", "pdf", {"env": "svil"})
    ws.add_version(case, "asis", b"%PDF-1 a", "pdf", {})
    for meta in (case.folder / "tobe" / "v001.meta.json", case.folder / "asis" / "asis.meta.json"):
        raw = json.loads(meta.read_text(encoding="utf-8"))
        raw["doc_type"] = doc_type
        meta.write_text(json.dumps(raw), encoding="utf-8")

    tobe, asis = case.latest_tobe(), case.asis()

    # the content file on disk is found by its own name, never by the meta's word
    assert (tobe.doc_type, tobe.path.name, tobe.missing) == ("pdf", "v001.pdf", False)
    assert (asis.doc_type, asis.path.name, asis.missing) == ("pdf", "asis.pdf", False)


def test_a_version_with_a_bad_doc_type_and_no_content_is_broken(ws: Workspace):
    ini = ws.create_initiative("Banco")
    case = ws.add_case(ini, "MOD_TEST_A", "", _payload(), env="svil", source_fdi=None)
    ws.add_version(case, "asis", b"%PDF-1 a", "pdf", {})
    (case.folder / "asis" / "asis.pdf").unlink()
    meta = case.folder / "asis" / "asis.meta.json"
    raw = json.loads(meta.read_text(encoding="utf-8"))
    raw["doc_type"] = "../../x"
    meta.write_text(json.dumps(raw), encoding="utf-8")

    asis = case.asis()

    assert asis is not None and asis.broken and asis.missing


def test_replacing_an_asis_whose_meta_names_a_bad_type_moves_nothing_outside(ws: Workspace,
                                                                             tmp_path: Path):
    ini = ws.create_initiative("Banco")
    case = ws.add_case(ini, "MOD_TEST_A", "", _payload(), env="svil", source_fdi=None)
    ws.add_version(case, "asis", b"%PDF-1 a", "pdf", {})
    outside = case.folder / "payload.json"
    before = outside.read_bytes()
    meta = case.folder / "asis" / "asis.meta.json"
    raw = json.loads(meta.read_text(encoding="utf-8"))
    raw["doc_type"] = "../payload.json"  # would be asis/asis.../payload.json
    meta.write_text(json.dumps(raw), encoding="utf-8")

    ws.add_version(case, "asis", b"%PDF-1 b", "pdf", {}, replace_asis_note="rifatto")

    assert outside.read_bytes() == before
    assert (case.folder / "asis" / "asis.previous-1.pdf").read_bytes() == b"%PDF-1 a"


# ------------------------------------------------------------- atomic writes ---

def test_json_writes_use_a_unique_temporary_file(tmp_path: Path):
    """Two writers of the same file never share its temporary file: the old
    fixed ``<name>.tmp`` is taken here (a folder), and the write still works."""
    target = tmp_path / "caso.json"
    (tmp_path / "caso.json.tmp").mkdir()

    model_io.write_json_atomic(target, {"a": 1})
    model_io.write_json_atomic(target, {"a": 2})

    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 2}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["caso.json", "caso.json.tmp"]
