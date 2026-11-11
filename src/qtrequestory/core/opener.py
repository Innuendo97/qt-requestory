"""Find a text editor and hand extracted files to it.

Preference order: the path configured by the user, then Notepad++ in its
standard install locations, then Notepad++ on PATH, and finally whatever
Windows associates with ``.json`` (``os.startfile``). Launching is injectable
so tests never start a process.

Every program launched here starts without the app's private DLL directory:
the PyInstaller onefile bootloader calls ``SetDllDirectoryW(<_MEIxxxx>)`` and
every child inherits it, so e.g. Acrobat would load ``VCRUNTIME140.dll`` from
the temp directory and keep it locked after the app exits.
"""
from __future__ import annotations

import ntpath
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterable, Iterator, Mapping

NOTEPADPP_REL = Path("Notepad++") / "notepad++.exe"

PopenFn = Callable[[list[str]], object]
StartFileFn = Callable[[str], object]
SetDllDirectoryFn = Callable[["str | None"], object]


def _meipass() -> str | None:
    """The onefile extraction directory, only when frozen on Windows."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return None
    return getattr(sys, "_MEIPASS", None) or None


def _kernel_set_dll_directory() -> SetDllDirectoryFn:
    import ctypes
    from ctypes import wintypes

    fn = ctypes.WinDLL("kernel32", use_last_error=True).SetDllDirectoryW
    fn.argtypes = [wintypes.LPCWSTR]
    fn.restype = wintypes.BOOL
    return fn


@contextmanager
def clean_dll_directory(set_dll_directory: SetDllDirectoryFn | None = None) -> Iterator[None]:
    """Run a launch without the app's private DLL search directory.

    Frozen on Windows: ``SetDllDirectoryW(None)`` before, ``SetDllDirectoryW(_MEIPASS)``
    after — also when the launch raises. Otherwise nothing is called.
    ``set_dll_directory`` is injectable so tests never touch the process state.
    """
    mei = _meipass()
    if mei is None:
        yield
        return
    setter = set_dll_directory or _kernel_set_dll_directory()
    setter(None)
    try:
        yield
    finally:
        setter(mei)


def child_env(env: Mapping[str, str] | None = None) -> dict[str, str] | None:
    """Environment for a spawned program, free of ``_MEIPASS`` leftovers.

    ``None`` (inherit as is) when not frozen. Frozen: ``PATH`` entries inside the
    extraction directory and the loader variable ``_MEIPASS2`` are dropped.
    """
    mei = _meipass()
    if mei is None:
        return None
    root = ntpath.normcase(ntpath.normpath(mei))
    out: dict[str, str] = {}
    for key, value in (os.environ if env is None else env).items():
        if key.upper() == "_MEIPASS2":
            continue
        if key.upper() == "PATH":
            kept = []
            for entry in value.split(";"):
                norm = ntpath.normcase(ntpath.normpath(entry)) if entry else entry
                if entry and (norm == root or norm.startswith(root + "\\")):
                    continue
                kept.append(entry)
            value = ";".join(kept)
        out[key] = value
    return out


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
    set_dll_directory: SetDllDirectoryFn | None = None,
) -> str:
    """Open ``paths`` in ``editor`` (one process, all files as tabs) or, without
    an editor, with the Windows default handler one file at a time.

    Returns ``"editor"`` or ``"default"`` so the UI can say what it did.
    """
    if editor is not None:
        launch = popen or (lambda argv: subprocess.Popen(argv, env=child_env()))
        with clean_dll_directory(set_dll_directory):
            launch([str(editor), *map(str, paths)])
        return "editor"
    start = startfile or _default_startfile()
    with clean_dll_directory(set_dll_directory):
        for p in paths:
            start(str(p))
    return "default"


def open_folder(
    path: Path, *, startfile: StartFileFn | None = None, set_dll_directory: SetDllDirectoryFn | None = None
) -> None:
    """Show a folder in Explorer."""
    start = startfile or _default_startfile()
    with clean_dll_directory(set_dll_directory):
        start(str(path))


def open_file(
    path: Path, *, startfile: StartFileFn | None = None, set_dll_directory: SetDllDirectoryFn | None = None
) -> None:
    """Open a document (a generated PDF or HTML) with the application Windows
    associates with it — never the text editor of :func:`open_in_editor`."""
    start = startfile or _default_startfile()
    with clean_dll_directory(set_dll_directory):
        start(str(path))
