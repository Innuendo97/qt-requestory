"""core/opener.py — editor discovery and launching (fakes only; nothing is launched)."""
from __future__ import annotations

from pathlib import Path

from qtrequestory.core.opener import (
    default_editor_candidates,
    find_editor,
    open_folder,
    open_in_editor,
)


# ------------------------------------------------------------- find_editor ---

def test_find_editor_configured_existing_wins(tmp_path: Path):
    configured = tmp_path / "myeditor.exe"
    configured.write_bytes(b"")
    candidate = tmp_path / "npp.exe"
    candidate.write_bytes(b"")
    assert find_editor(configured, [candidate]) == configured


def test_find_editor_configured_missing_falls_back_to_first_existing_candidate(tmp_path: Path):
    missing = tmp_path / "gone.exe"
    absent_candidate = tmp_path / "absent.exe"
    present_candidate = tmp_path / "present.exe"
    present_candidate.write_bytes(b"")
    assert find_editor(missing, [absent_candidate, present_candidate]) == present_candidate


def test_find_editor_none_when_nothing_exists(tmp_path: Path):
    assert find_editor(None, [tmp_path / "a.exe", tmp_path / "b.exe"]) is None
    assert find_editor(tmp_path / "c.exe", []) is None


def test_find_editor_uses_default_candidates_when_none_given(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "pf"))
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "pf86"))
    monkeypatch.setattr("qtrequestory.core.opener.shutil.which", lambda name: None)
    npp = tmp_path / "pf86" / "Notepad++" / "notepad++.exe"
    npp.parent.mkdir(parents=True)
    npp.write_bytes(b"")
    assert find_editor(None) == npp


def test_default_editor_candidates_order(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "pf"))
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "pf86"))
    monkeypatch.setattr("qtrequestory.core.opener.shutil.which", lambda name: str(tmp_path / "onpath" / "notepad++.exe"))
    assert default_editor_candidates() == [
        tmp_path / "pf" / "Notepad++" / "notepad++.exe",
        tmp_path / "pf86" / "Notepad++" / "notepad++.exe",
        tmp_path / "onpath" / "notepad++.exe",
    ]


def test_default_editor_candidates_skips_which_when_not_found(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "pf"))
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "pf86"))
    monkeypatch.setattr("qtrequestory.core.opener.shutil.which", lambda name: None)
    assert len(default_editor_candidates()) == 2


# ---------------------------------------------------------- open_in_editor ---

def test_open_in_editor_with_editor_uses_single_popen(tmp_path: Path):
    calls: list[list[str]] = []
    started: list[str] = []
    editor = tmp_path / "npp.exe"
    p1, p2 = tmp_path / "one.json", tmp_path / "two.json"

    label = open_in_editor([p1, p2], editor, popen=lambda args: calls.append(list(args)), startfile=started.append)

    assert label == "editor"
    assert calls == [[str(editor), str(p1), str(p2)]]
    assert started == []


def test_open_in_editor_without_editor_uses_startfile_per_path(tmp_path: Path):
    calls: list[list[str]] = []
    started: list[str] = []
    p1, p2 = tmp_path / "one.json", tmp_path / "two.json"

    label = open_in_editor([p1, p2], None, popen=lambda args: calls.append(list(args)), startfile=started.append)

    assert label == "default"
    assert started == [str(p1), str(p2)]
    assert calls == []


# ------------------------------------------------------------- open_folder ---

def test_open_folder_calls_startfile(tmp_path: Path):
    started: list[str] = []
    open_folder(tmp_path, startfile=started.append)
    assert started == [str(tmp_path)]
