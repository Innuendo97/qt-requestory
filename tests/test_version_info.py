"""The Windows version resource must carry the version the package reports.

``qtRequestory.exe --version`` prints ``qtrequestory.__version__``; the
Properties > Details tab of the same file shows the version *resource*. When
the two drift apart, a colleague reporting "I'm on 1.0.0" is telling you
something that may not be true — which is why the resource is generated from
``__version__`` instead of being edited by hand.

These tests run the generator (``scripts/make_version_info.py``) rather than
reading the committed output: the output is a build artefact and is not
committed.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "scripts" / "make_version_info.py"


def _generator():
    """Import ``scripts/make_version_info.py`` — it lives outside the package."""
    spec = importlib.util.spec_from_file_location("_make_version_info", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def generator():
    return _generator()


def test_the_resource_carries_the_package_version(generator, tmp_path):
    from qtrequestory import __version__

    out = tmp_path / "version_info.txt"
    generator.write_version_info(out)
    text = out.read_text(encoding="utf-8")

    major, minor, patch = (int(p) for p in __version__.split("."))
    assert f"filevers=({major}, {minor}, {patch}, 0)" in text
    assert f"prodvers=({major}, {minor}, {patch}, 0)" in text
    assert text.count(f"'{__version__}'") == 2  # FileVersion and ProductVersion


def test_the_resource_is_what_pyinstaller_can_parse(generator, tmp_path):
    """PyInstaller ``exec``s this file; a template typo must fail here, not mid-build."""
    pytest.importorskip("PyInstaller", reason="only the build environment has PyInstaller")
    from PyInstaller.utils.win32.versioninfo import load_version_info_from_text_file

    out = tmp_path / "version_info.txt"
    generator.write_version_info(out)
    info = load_version_info_from_text_file(str(out))
    assert "qtRequestory.exe" in str(info)


def test_the_resource_is_pure_ascii(generator, tmp_path):
    """No em dashes: the resource is read back by tools with assorted code pages."""
    out = tmp_path / "version_info.txt"
    generator.write_version_info(out)
    out.read_bytes().decode("ascii")


def test_running_it_as_a_script_writes_the_default_file(tmp_path, monkeypatch):
    """``build.ps1`` calls it with no arguments; that path must work too."""
    monkeypatch.setattr(sys, "argv", ["make_version_info.py", str(tmp_path / "out.txt")])
    module = _generator()
    assert module.main() == 0
    assert (tmp_path / "out.txt").is_file()
