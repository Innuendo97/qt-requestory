"""qtrequestory.officina.model: initiatives, cases and versions on disk.

Synthetic data only (this repository is public): template keys are
``MOD_TEST_*``, payloads hold no real customer data.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from qtrequestory.officina import model
from qtrequestory.officina.model import AsisAlreadyExistsError, Workspace


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    return Workspace(tmp_path / "officina-root")


def _payload(n: int = 1) -> dict:
    return {"documents": [{"template": {"templateKey": "MOD_TEST_A"}}], "note": f"synthetic-{n}"}


# --------------------------------------------------------------- initiatives ---

def test_create_and_list_initiatives(ws: Workspace):
    ws.create_initiative("Alpha")
    ws.create_initiative("Beta")

    names = sorted(i.name for i in ws.initiatives())

    assert names == ["Alpha", "Beta"]


def test_initiative_folder_name_with_spaces_and_accents_stays_readable(ws: Workspace):
    ini = ws.create_initiative("Offerte Città 2026")

    assert ini.folder.name == "Offerte Città 2026"
    assert ini.folder.is_dir()
    loaded = ws.load("Offerte Città 2026")
    assert loaded.name == "Offerte Città 2026"


def test_initiative_folder_name_replaces_reserved_windows_characters(ws: Workspace):
    ini = ws.create_initiative('Offerte: "Luce/Gas" <2026>')

    for bad in '\\/:*?"<>|':
        assert bad not in ini.folder.name
    assert ini.folder.is_dir()
    # the readable original name is still recoverable from disk
    assert ini.name == 'Offerte: "Luce/Gas" <2026>'


def test_create_initiative_refuses_duplicates(ws: Workspace):
    ws.create_initiative("Alpha")

    with pytest.raises(FileExistsError):
        ws.create_initiative("Alpha")


def test_load_unknown_initiative_raises(ws: Workspace):
    with pytest.raises(FileNotFoundError):
        ws.load("Non esiste")


# --------------------------------------------------------------------- cases ---

def test_add_case_twice_same_key_different_variant_gives_two_ids(ws: Workspace):
    ini = ws.create_initiative("Alpha")

    c1 = ws.add_case(ini, "MOD_TEST_A", "abilitato", _payload(1), env="svil", source_fdi=None)
    c2 = ws.add_case(ini, "MOD_TEST_A", "disabilitato", _payload(2), env="svil", source_fdi=None)

    assert c1.id != c2.id
    assert c1.id == "MOD_TEST_A__abilitato"
    assert c2.id == "MOD_TEST_A__disabilitato"
    assert c1.folder.is_dir() and c2.folder.is_dir()


def test_add_case_without_variant_uses_bare_key_as_id(ws: Workspace):
    ini = ws.create_initiative("Alpha")

    case = ws.add_case(ini, "MOD_TEST_A", "", _payload(), env="svil", source_fdi=None)

    assert case.id == "MOD_TEST_A"


# ------------------------------------------------------------------- payload ---

def test_payload_round_trip_and_original_kept_only_on_first_edit(ws: Workspace):
    ini = ws.create_initiative("Alpha")
    case = ws.add_case(ini, "MOD_TEST_A", "", _payload(1), env="svil", source_fdi=None)

    assert ws.payload(case) == _payload(1)
    original_path = case.folder / "payload.original.json"
    assert not original_path.exists()

    ws.save_payload(case, _payload(2))

    assert ws.payload(case) == _payload(2)
    assert original_path.exists()
    assert json.loads(original_path.read_text(encoding="utf-8")) == _payload(1)

    # a second edit must NOT touch payload.original.json again
    ws.save_payload(case, _payload(3))

    assert ws.payload(case) == _payload(3)
    assert json.loads(original_path.read_text(encoding="utf-8")) == _payload(1)


# --------------------------------------------------------------------- target ---

def test_set_target_keeps_original_name_and_second_call_replaces(ws: Workspace, tmp_path: Path):
    ini = ws.create_initiative("Alpha")
    case = ws.add_case(ini, "MOD_TEST_A", "", _payload(), env="svil", source_fdi=None)
    src1 = tmp_path / "Fattura Cliente.pdf"
    src1.write_bytes(b"%PDF-1.4 synthetic one")

    v1 = ws.set_target(case, src1)

    assert v1.path.name == "Fattura Cliente.pdf"
    assert v1.path.read_bytes() == b"%PDF-1.4 synthetic one"
    assert v1.doc_type == "pdf"
    assert v1.meta == {"original_name": "Fattura Cliente.pdf"}
    assert case.target() == v1

    src2 = tmp_path / "Fattura Cliente v2.pdf"
    src2.write_bytes(b"%PDF-1.4 synthetic two")

    v2 = ws.set_target(case, src2)

    assert v2.path.name == "Fattura Cliente v2.pdf"
    assert v2.path.read_bytes() == b"%PDF-1.4 synthetic two"
    # the old file must be gone, not left behind next to the new one
    assert not (case.folder / "target" / "Fattura Cliente.pdf").exists()
    assert case.target() == v2


# ------------------------------------------------------------------- versions ---

def test_add_version_tobe_numbering_is_sequential(ws: Workspace):
    ini = ws.create_initiative("Alpha")
    case = ws.add_case(ini, "MOD_TEST_A", "", _payload(), env="svil", source_fdi=None)

    v1 = ws.add_version(case, "tobe", b"one", "pdf", {"status": "ok"})
    v2 = ws.add_version(case, "tobe", b"two", "pdf", {"status": "ok"})
    v3 = ws.add_version(case, "tobe", b"three", "pdf", {"status": "ok"})

    assert [v.number for v in (v1, v2, v3)] == [1, 2, 3]
    assert v1.path.name == "v001.pdf"
    assert v3.path.name == "v003.pdf"
    assert [v.number for v in case.tobe_versions()] == [1, 2, 3]
    assert case.latest_tobe() == v3


def test_add_version_asis_refuses_without_a_note(ws: Workspace):
    ini = ws.create_initiative("Alpha")
    case = ws.add_case(ini, "MOD_TEST_A", "", _payload(), env="svil", source_fdi=None)
    ws.add_version(case, "asis", b"first", "pdf", {"status": "ok"})

    with pytest.raises(AsisAlreadyExistsError):
        ws.add_version(case, "asis", b"second", "pdf", {"status": "ok"})

    # an empty note is not a note
    with pytest.raises(AsisAlreadyExistsError):
        ws.add_version(case, "asis", b"second", "pdf", {"status": "ok"}, replace_asis_note="")

    assert case.asis().path.read_bytes() == b"first"


def test_add_version_asis_replace_keeps_the_previous_file_and_records_a_note(ws: Workspace):
    ini = ws.create_initiative("Alpha")
    case = ws.add_case(ini, "MOD_TEST_A", "", _payload(), env="svil", source_fdi=None)
    ws.add_version(case, "asis", b"first", "pdf", {"status": "ok"})

    new_asis = ws.add_version(case, "asis", b"second", "pdf", {"status": "ok"},
                               replace_asis_note="rigenerato dopo fix template")

    assert new_asis.path.read_bytes() == b"second"
    assert case.asis().path.read_bytes() == b"second"
    previous = case.folder / "asis" / "asis.previous-1.pdf"
    assert previous.exists()
    assert previous.read_bytes() == b"first"

    caso_raw = json.loads((case.folder / "caso.json").read_text(encoding="utf-8"))
    notes = [h["note"] for h in caso_raw["history"]]
    assert "rigenerato dopo fix template" in notes


# ----------------------------------------------------------------- resilience ---

def test_missing_version_file_is_reported(ws: Workspace):
    ini = ws.create_initiative("Alpha")
    case = ws.add_case(ini, "MOD_TEST_A", "", _payload(), env="svil", source_fdi=None)
    ws.add_version(case, "tobe", b"one", "pdf", {"status": "ok"})
    ws.add_version(case, "tobe", b"two", "pdf", {"status": "ok"})

    (case.folder / "tobe" / "v002.pdf").unlink()

    reloaded = ws.load("Alpha")
    reloaded_case = next(c for c in reloaded.cases if c.id == case.id)
    versions = reloaded_case.tobe_versions()

    assert len(versions) == 2
    assert versions[0].missing is False
    assert versions[1].missing is True
    assert versions[1].number == 2


def test_corrupt_caso_json_is_reported_without_raising(ws: Workspace):
    ini = ws.create_initiative("Alpha")
    case = ws.add_case(ini, "MOD_TEST_A", "", _payload(), env="svil", source_fdi=None)
    (case.folder / "caso.json").write_text("{not valid json", encoding="utf-8")

    reloaded = ws.load("Alpha")

    reloaded_case = next(c for c in reloaded.cases if c.id == case.id)
    assert reloaded_case.status == "open"
    assert reloaded_case.load_error is not None


def test_save_case_round_trip_and_preserves_history(ws: Workspace):
    ini = ws.create_initiative("Alpha")
    case = ws.add_case(ini, "MOD_TEST_A", "", _payload(), env="svil", source_fdi=None)
    ws.add_version(case, "asis", b"first", "pdf", {"status": "ok"})
    ws.add_version(case, "asis", b"second", "pdf", {"status": "ok"}, replace_asis_note="nota")

    case.status = "accepted"
    case.notes = "pronto"
    ws.save_case(case)

    reloaded = ws.load("Alpha")
    reloaded_case = next(c for c in reloaded.cases if c.id == case.id)
    assert reloaded_case.status == "accepted"
    assert reloaded_case.notes == "pronto"
    raw = json.loads((case.folder / "caso.json").read_text(encoding="utf-8"))
    assert raw["history"], "save_case must not wipe out history written by add_version"


# ------------------------------------------------------- fix round 1: source_fdi/history ---

def test_case_exposes_source_fdi_and_a_read_only_history_view(ws: Workspace):
    ini = ws.create_initiative("Alpha")
    case = ws.add_case(ini, "MOD_TEST_A", "", _payload(), env="svil", source_fdi="fdi-synthetic-1")

    assert case.source_fdi == "fdi-synthetic-1"
    assert case.history == []

    ws.add_version(case, "asis", b"first", "pdf", {"status": "ok"})
    ws.add_version(case, "asis", b"second", "pdf", {"status": "ok"}, replace_asis_note="nota-1")

    assert [h["note"] for h in case.history] == ["nota-1"]

    reloaded = ws.load("Alpha")
    reloaded_case = next(c for c in reloaded.cases if c.id == case.id)
    assert reloaded_case.source_fdi == "fdi-synthetic-1"
    assert [h["note"] for h in reloaded_case.history] == ["nota-1"]


def test_case_without_source_fdi_round_trips_as_none(ws: Workspace):
    ini = ws.create_initiative("Alpha")
    case = ws.add_case(ini, "MOD_TEST_A", "", _payload(), env="svil", source_fdi=None)

    assert case.source_fdi is None
    reloaded = ws.load("Alpha")
    reloaded_case = next(c for c in reloaded.cases if c.id == case.id)
    assert reloaded_case.source_fdi is None


# --------------------------------------------------- fix round 1: set_target crash safety ---

def test_set_target_shows_old_target_if_the_crash_is_before_the_new_meta_is_written(
    ws: Workspace, tmp_path: Path, monkeypatch,
):
    ini = ws.create_initiative("Alpha")
    case = ws.add_case(ini, "MOD_TEST_A", "", _payload(), env="svil", source_fdi=None)
    old_src = tmp_path / "old.pdf"
    old_src.write_bytes(b"old-content")
    ws.set_target(case, old_src)

    new_src = tmp_path / "new-name.pdf"
    new_src.write_bytes(b"new-content")

    real_write_json_atomic = model._write_json_atomic

    def boom(path, data):
        if path.name == "target.meta.json":
            raise RuntimeError("simulated crash before the new meta is committed")
        return real_write_json_atomic(path, data)

    monkeypatch.setattr(model, "_write_json_atomic", boom)

    with pytest.raises(RuntimeError):
        ws.set_target(case, new_src)

    version = case.target()
    assert version is not None
    assert not version.missing
    assert version.path.exists()
    # the new content was already written to disk (step 1), but the OLD
    # meta (still pointing at the old name) is what a reload sees, and that
    # file is still there untouched — never neither.
    assert version.path.name == "old.pdf"
    assert version.path.read_bytes() == b"old-content"


def test_set_target_shows_new_target_if_the_crash_is_during_stray_cleanup(
    ws: Workspace, tmp_path: Path, monkeypatch,
):
    ini = ws.create_initiative("Alpha")
    case = ws.add_case(ini, "MOD_TEST_A", "", _payload(), env="svil", source_fdi=None)
    old_src = tmp_path / "old.pdf"
    old_src.write_bytes(b"old-content")
    ws.set_target(case, old_src)

    new_src = tmp_path / "new-name.pdf"
    new_src.write_bytes(b"new-content")

    def boom(path):
        raise RuntimeError("simulated crash during stray cleanup")

    monkeypatch.setattr(model, "remove_quietly", boom)

    with pytest.raises(RuntimeError):
        ws.set_target(case, new_src)

    version = case.target()
    assert version is not None
    assert not version.missing
    assert version.path.name == "new-name.pdf"
    assert version.path.read_bytes() == b"new-content"


# ------------------------------------------------ fix round 1: reserved Windows names ---

@pytest.mark.parametrize("raw_name", ["NUL", "nul", "CON", "con", "PRN", "AUX",
                                       "COM1", "com3", "LPT9", "nul.txt"])
def test_safe_folder_name_escapes_every_reserved_device_name(raw_name: str):
    safe = model._safe_folder_name(raw_name)

    stem = safe.split(".", 1)[0]
    assert stem.upper() not in model._RESERVED_NAMES


def test_create_initiative_with_a_reserved_device_name(ws: Workspace):
    ini = ws.create_initiative("NUL")

    assert ini.folder.name.upper() != "NUL"
    assert ini.folder.is_dir()
    assert ini.name == "NUL"
    reloaded = ws.load(ini.id)
    assert reloaded.name == "NUL"


def test_add_case_with_a_reserved_device_name_key_gets_a_safe_folder(ws: Workspace):
    ini = ws.create_initiative("Alpha")

    case = ws.add_case(ini, "NUL", "", _payload(), env="svil", source_fdi=None)

    assert case.key == "NUL"  # the semantic key is untouched
    assert case.id.upper() != "NUL"
    assert case.folder.is_dir()
    assert case.folder.name == case.id


# ------------------------------------------------- fix round 1: tobe meta missing/corrupt ---

def test_tobe_version_with_a_missing_meta_file_still_shows_up_by_its_content(ws: Workspace):
    ini = ws.create_initiative("Alpha")
    case = ws.add_case(ini, "MOD_TEST_A", "", _payload(), env="svil", source_fdi=None)
    ws.add_version(case, "tobe", b"one", "pdf", {"status": "ok"})
    ws.add_version(case, "tobe", b"two", "pdf", {"status": "ok"})
    (case.folder / "tobe" / "v002.meta.json").unlink()

    versions = case.tobe_versions()

    assert [v.number for v in versions] == [1, 2]
    v2 = versions[1]
    assert v2.missing is False
    assert v2.meta == {}
    assert v2.path.read_bytes() == b"two"
    assert isinstance(v2.created, datetime)


def test_tobe_version_with_a_corrupt_meta_file_still_shows_up_by_its_content(ws: Workspace):
    ini = ws.create_initiative("Alpha")
    case = ws.add_case(ini, "MOD_TEST_A", "", _payload(), env="svil", source_fdi=None)
    ws.add_version(case, "tobe", b"one", "pdf", {"status": "ok"})
    (case.folder / "tobe" / "v001.meta.json").write_text("{not valid json", encoding="utf-8")

    versions = case.tobe_versions()

    assert len(versions) == 1
    assert versions[0].missing is False
    assert versions[0].meta == {}
    assert versions[0].path.read_bytes() == b"one"


def test_add_version_tobe_numbering_survives_a_missing_meta_file(ws: Workspace):
    ini = ws.create_initiative("Alpha")
    case = ws.add_case(ini, "MOD_TEST_A", "", _payload(), env="svil", source_fdi=None)
    ws.add_version(case, "tobe", b"one", "pdf", {"status": "ok"})
    ws.add_version(case, "tobe", b"two", "pdf", {"status": "ok"})
    (case.folder / "tobe" / "v002.meta.json").unlink()

    v3 = ws.add_version(case, "tobe", b"three", "pdf", {"status": "ok"})

    assert v3.number == 3
    # the number-2 content file (whose meta is gone) must be left untouched
    assert (case.folder / "tobe" / "v002.pdf").read_bytes() == b"two"
