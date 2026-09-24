"""core/extract.py — the output contract: pure body, pretty-printed, UTF-8 no BOM."""
from __future__ import annotations

import json
import os
import time
from datetime import date
from pathlib import Path

import pytest

from qtrequestory.core.extract import (
    housekeeping,
    output_name,
    pretty_json,
    save_as,
    write_temp_file,
)
from tests.conftest import FDI_A, KEY_SINT, synthetic_body

DAY = date(2026, 9, 18)


# ------------------------------------------------------------- pretty_json ---

def test_pretty_json_four_space_indent_and_trailing_newline():
    text = pretty_json(b'{"b":1,"a":[1,2]}')
    assert text == '{\n    "b": 1,\n    "a": [\n        1,\n        2\n    ]\n}\n'


def test_pretty_json_preserves_key_order_and_accents():
    text = pretty_json('{"z":"città","a":"Màrio"}'.encode("utf-8"))
    assert text.index('"z"') < text.index('"a"')
    assert "città" in text and "Màrio" in text
    assert "\\u" not in text  # ensure_ascii=False


def test_pretty_json_ends_with_exactly_one_newline():
    text = pretty_json(b'{"a": 1}')
    assert text.endswith("}\n")
    assert not text.endswith("\n\n")


def test_pretty_json_invalid_json_becomes_parse_error_object():
    text = pretty_json(b'{"documents": [ not json')
    obj = json.loads(text)
    assert set(obj) == {"_parseError", "raw"}
    assert obj["raw"] == '{"documents": [ not json'
    assert obj["_parseError"]
    assert text.endswith("\n")


def test_pretty_json_invalid_utf8_becomes_parse_error_object():
    text = pretty_json(b'{"a": "\xff"}')
    obj = json.loads(text)
    assert "_parseError" in obj
    assert "�" in obj["raw"]  # decoded with errors="replace"


def test_pretty_json_synthetic_body_starts_with_documents():
    text = pretty_json(synthetic_body(FDI_A, KEY_SINT))
    assert text.startswith('{\n    "documents": [')
    assert "Màrio" in text and "città" in text


# ------------------------------------------------------------- output_name ---

def test_output_name_with_fdi():
    assert output_name(DAY, FDI_A, KEY_SINT) == f"20260918_{FDI_A}_{KEY_SINT}.json"


def test_output_name_without_fdi():
    assert output_name(DAY, None, KEY_SINT) == f"20260918_nofdi_{KEY_SINT}.json"


def test_output_name_with_call_id():
    assert output_name(DAY, FDI_A, KEY_SINT, "1a2b3c0200000033") == (
        f"20260918_{FDI_A}_{KEY_SINT}_1a2b3c0200000033.json"
    )


# ------------------------------------------------------------ housekeeping ---

def _touch(path: Path, age_hours: float) -> Path:
    path.write_text("x", encoding="utf-8")
    old = time.time() - age_hours * 3600
    os.utime(path, (old, old))
    return path


def test_housekeeping_deletes_only_old_files(tmp_path: Path):
    old = _touch(tmp_path / "old.json", age_hours=30)
    recent = _touch(tmp_path / "recent.json", age_hours=1)
    sub = tmp_path / "subdir"
    sub.mkdir()
    old_in_sub = _touch(sub / "old-in-sub.json", age_hours=30)
    os.utime(sub, (time.time() - 30 * 3600,) * 2)

    assert housekeeping(tmp_path, 24) == 1
    assert not old.exists()
    assert recent.exists()
    assert sub.is_dir() and old_in_sub.exists()


def test_housekeeping_missing_dir_returns_zero(tmp_path: Path):
    assert housekeeping(tmp_path / "missing", 24) == 0


def test_housekeeping_an_unlistable_dir_returns_zero(tmp_path: Path, monkeypatch):
    """A folder that exists but cannot be listed (permissions, a network share
    that dropped) is housekeeping skipped, never an error in the extraction."""
    def refuse(self):
        raise PermissionError("accesso negato")

    monkeypatch.setattr(Path, "iterdir", refuse)
    assert housekeeping(tmp_path, 24) == 0


# --------------------------------------------------------- write_temp_file ---

def test_write_temp_file_creates_dir_and_writes_pure_body(tmp_path: Path):
    out_dir = tmp_path / "calls" / "nested"
    text = pretty_json(synthetic_body(FDI_A, KEY_SINT))
    path = write_temp_file(out_dir, "a.json", text)
    assert path == out_dir / "a.json"
    data = path.read_bytes()
    assert data[:1] == b"{"  # no BOM
    assert data == text.encode("utf-8")
    assert data.startswith(b'{\n    "documents": [')
    assert "Màrio".encode("utf-8") in data and "città".encode("utf-8") in data
    assert b"\r\n" not in data


def test_write_temp_file_collision_with_alt_name_writes_alt(tmp_path: Path):
    first = write_temp_file(tmp_path, "a.json", "first\n")
    second = write_temp_file(tmp_path, "a.json", "second\n", alt_name="a_call.json")
    assert second == tmp_path / "a_call.json"
    assert first.read_text(encoding="utf-8") == "first\n"
    assert second.read_text(encoding="utf-8") == "second\n"


def test_write_temp_file_collision_without_alt_overwrites(tmp_path: Path):
    write_temp_file(tmp_path, "a.json", "first\n")
    path = write_temp_file(tmp_path, "a.json", "second\n")
    assert path == tmp_path / "a.json"
    assert path.read_text(encoding="utf-8") == "second\n"


def test_write_temp_file_runs_housekeeping(tmp_path: Path):
    stale = _touch(tmp_path / "stale.json", age_hours=48)
    write_temp_file(tmp_path, "new.json", "{}\n", retention_hours=24)
    assert not stale.exists()


# ----------------------------------------------------------------- save_as ---

def test_save_as_creates_parents_and_writes_utf8_no_bom(tmp_path: Path):
    target = tmp_path / "deep" / "er" / "out.json"
    save_as(target, '{"n": "città"}\n')
    data = target.read_bytes()
    assert data == '{"n": "città"}\n'.encode("utf-8")
    assert data[:1] == b"{"


@pytest.mark.parametrize("inside", [True, False])
def test_housekeeping_refuses_to_run_where_it_overlaps_the_protected_mirror(tmp_path: Path, inside: bool):
    """F7, defence in depth: validate() already refuses the configuration, but
    a hand-edited config.json must never make housekeeping delete logs."""
    mirror = tmp_path / "mirror"
    mirror.mkdir()
    out = mirror if inside else tmp_path
    old = _touch(out / "20260101.txt", age_hours=300)
    assert housekeeping(out, 24, protected=mirror) == 0
    assert old.exists()


def test_housekeeping_with_an_unrelated_protected_dir_still_runs(tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir()
    old = _touch(out / "old.json", age_hours=30)
    assert housekeeping(out, 24, protected=tmp_path / "mirror") == 1
    assert not old.exists()


def test_write_temp_file_passes_the_protected_dir_to_housekeeping(tmp_path: Path):
    old = _touch(tmp_path / "20260101.txt", age_hours=300)
    write_temp_file(tmp_path, "a.json", "{}\n", retention_hours=1, protected=tmp_path)
    assert old.exists()
