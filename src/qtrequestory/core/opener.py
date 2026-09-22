"""Find a text editor and hand extracted files to it.

Preference order: the path configured by the user, then Notepad++ in its
standard install locations, then Notepad++ on PATH, and finally whatever
Windows associates with ``.json`` (``os.startfile``). Launching is injectable
so tests never start a process.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Iterable

NOTEPADPP_REL = Path("Notepad++") / "notepad++.exe"

PopenFn = Callable[[list[str]], object]
StartFileFn = Callable[[str], object]


def default_editor_candidates() -> list[Path]:
    """Standard Notepad++ locations, most common first, then PATH."""
    candidates: list[Path] = []
    for var in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(var)
        if base:
            candidates.append(Path(base) / NOTEPADPP_REL)
    on_path = shutil.which("notepad++")
    if on_path is not None:
        candidates.append(Path(on_path))
    return candidates


def find_editor(configured: Path | None, candidates: Iterable[Path] | None = None) -> Path | None:
    """The configured editor if it exists, else the first existing candidate."""
    if configured is not None and Path(configured).is_file():
        return Path(configured)
    if candidates is None:
        candidates = default_editor_candidates()
    for candidate in candidates:
        if Path(candidate).is_file():
            return Path(candidate)
    return None


def _default_startfile() -> StartFileFn:
    # Resolved at call time: os.startfile only exists on Windows and the module
    # must import (and tests must run) on any OS.
    startfile = getattr(os, "startfile", None)
    if startfile is None:
        raise OSError("os.startfile is not available on this platform")
    return startfile


def open_in_editor(
    paths: list[Path],
    editor: Path | None,
    *,
    popen: PopenFn | None = None,
    startfile: StartFileFn | None = None,
) -> str:
    """Open ``paths`` in ``editor`` (one process, all files as tabs) or, without
    an editor, with the Windows default handler one file at a time.

    Returns ``"editor"`` or ``"default"`` so the UI can say what it did.
    """
    if editor is not None:
        (popen or subprocess.Popen)([str(editor), *map(str, paths)])
        return "editor"
    start = startfile or _default_startfile()
    for p in paths:
        start(str(p))
    return "default"


def open_folder(path: Path, *, startfile: StartFileFn | None = None) -> None:
    """Show a folder in Explorer."""
    (startfile or _default_startfile())(str(path))
