"""core/opener.py — editor discovery and launching (fakes only; nothing is launched)."""
from __future__ import annotations

from pathlib import Path

from qtrequestory.core.opener import (
    default_editor_candidates,
    find_editor,
    open_file,
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


# --------------------------------------------------------------- open_file ---

def test_open_file_hands_the_document_to_its_default_application(tmp_path: Path):
    """A generated PDF or HTML opens in what Windows associates with it, never
    in the configured text editor."""
    started: list[str] = []
    document = tmp_path / "MOD_TEST_A.pdf"
    open_file(document, startfile=started.append)
    assert started == [str(document)]


# ------------------------------------------- private DLL directory (frozen) ---

import sys

import pytest

from qtrequestory.core import opener

MEI = "C:\synthetic\_MEI12345"


def _freeze(monkeypatch, *, platform: str = "win32") -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", MEI, raising=False)
    monkeypatch.setattr(sys, "platform", platform)


def _unfreeze(monkeypatch) -> None:
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)


def test_frozen_launch_resets_the_dll_directory_then_restores_it(monkeypatch, tmp_path: Path):
    _freeze(monkeypatch)
    events: list[object] = []

    open_file(
        tmp_path / "MOD_TEST_A.pdf",
        startfile=lambda p: events.append(("launch", p)),
        set_dll_directory=lambda d: events.append(("dll", d)),
    )

    assert events == [("dll", None), ("launch", str(tmp_path / "MOD_TEST_A.pdf")), ("dll", MEI)]


def test_every_launch_function_is_guarded(monkeypatch, tmp_path: Path):
    _freeze(monkeypatch)
    events: list[object] = []
    dll = lambda d: events.append(("dll", d))  # noqa: E731

    open_folder(tmp_path, startfile=lambda p: events.append("launch"), set_dll_directory=dll)
    open_in_editor([tmp_path / "a.json"], None, startfile=lambda p: events.append("launch"), set_dll_directory=dll)
    open_in_editor([tmp_path / "a.json"], tmp_path / "npp.exe", popen=lambda a: events.append("launch"), set_dll_directory=dll)

    assert events == [("dll", None), "launch", ("dll", MEI)] * 3


def test_frozen_restore_happens_when_the_launch_raises(monkeypatch, tmp_path: Path):
    _freeze(monkeypatch)
    events: list[object] = []

    def boom(_path: str):
        events.append("launch")
        raise OSError("no application associated")

    with pytest.raises(OSError, match="no application associated"):
        open_file(tmp_path / "x.pdf", startfile=boom, set_dll_directory=lambda d: events.append(("dll", d)))

    assert events == [("dll", None), "launch", ("dll", MEI)]


def test_not_frozen_never_touches_the_dll_directory(monkeypatch, tmp_path: Path):
    _unfreeze(monkeypatch)
    called: list[object] = []
    open_file(tmp_path / "x.pdf", startfile=lambda p: None, set_dll_directory=called.append)
    open_folder(tmp_path, startfile=lambda p: None, set_dll_directory=called.append)
    assert called == []


def test_frozen_but_not_windows_never_touches_the_dll_directory(monkeypatch, tmp_path: Path):
    _freeze(monkeypatch, platform="linux")
    called: list[object] = []
    open_file(tmp_path / "x.pdf", startfile=lambda p: None, set_dll_directory=called.append)
    assert called == []


def test_frozen_without_meipass_never_touches_the_dll_directory(monkeypatch, tmp_path: Path):
    _freeze(monkeypatch)
    monkeypatch.delattr(sys, "_MEIPASS")
    called: list[object] = []
    open_file(tmp_path / "x.pdf", startfile=lambda p: None, set_dll_directory=called.append)
    assert called == []


# ---------------------------------------------- environment of the children ---

def test_child_env_is_none_when_not_frozen(monkeypatch):
    _unfreeze(monkeypatch)
    assert opener.child_env({"PATH": MEI}) is None


def test_child_env_drops_path_entries_inside_meipass_and_the_loader_variable(monkeypatch):
    _freeze(monkeypatch)
    env = {
        "PATH": f"C:\Windows;{MEI};{MEI}\sub;C:\Tools",
        "_MEIPASS2": MEI,
        "OTHER": "kept",
    }
    cleaned = opener.child_env(env)
    assert cleaned == {"PATH": "C:\Windows;C:\Tools", "OTHER": "kept"}
    assert env["_MEIPASS2"] == MEI  # the caller's mapping is untouched
