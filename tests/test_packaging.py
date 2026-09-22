"""Guard: every non-Python file inside the package is declared as package data.

``ui/icons/*.svg`` are read from disk at runtime (``icons.ICON_DIR``). Without a
``[tool.setuptools.package-data]`` entry setuptools silently leaves them out, so
the wheel — and the PyInstaller build that collects the installed package —
produces an application whose navigation rail has no icons at all. Nothing
crashes, which is exactly why this has to be a test.
"""
from __future__ import annotations

import fnmatch
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "qtrequestory"
IGNORED_DIRS = {"__pycache__"}


def _package_data() -> dict[str, list[str]]:
    with (ROOT / "pyproject.toml").open("rb") as f:
        config = tomllib.load(f)
    return config["tool"]["setuptools"]["package-data"]


def _data_files() -> list[Path]:
    """Every shipped non-``.py`` file, relative to ``src/qtrequestory``."""
    return sorted(
        p.relative_to(PACKAGE)
        for p in PACKAGE.rglob("*")
        if p.is_file() and p.suffix != ".py" and not IGNORED_DIRS & set(p.parts)
    )


def _is_declared(relative: Path, declared: dict[str, list[str]]) -> bool:
    """True when some declared pattern covers ``relative`` (as setuptools reads it)."""
    for package, patterns in declared.items():
        prefix = "" if package == "*" else package.removeprefix("qtrequestory.").replace(".", "/")
        for pattern in patterns:
            candidate = f"{prefix}/{pattern}" if prefix else pattern
            if fnmatch.fnmatch(relative.as_posix(), candidate):
                return True
    return False


def test_every_data_file_in_the_package_is_declared():
    declared = _package_data()
    missing = [str(f) for f in _data_files() if not _is_declared(f, declared)]
    assert not missing, f"not covered by [tool.setuptools.package-data]: {missing}"


def test_the_icons_really_are_data_files():
    """A sanity check on the test above: it would pass on an empty package too."""
    names = {f.name for f in _data_files()}
    assert "app.svg" in names
    assert "arrow-sync.svg" in names
