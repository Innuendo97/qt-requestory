"""Guard: pypdfium2 must load only behind the ``qtrequestory.officina.pdf`` package.

The hourly ``--sync`` run (``qtrequestory.cli``) and merely importing the
``qtrequestory.officina`` package must never pull pypdfium2 in — it is a
~10 MB binary dependency that only the PDF viewer/extractor needs. Each check
runs in a subprocess so ``sys.modules`` reflects a single, fresh import.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

# The package is not pip-installed in the dev/build venv (pytest runs with
# pythonpath=src, see pyproject.toml); a plain subprocess would not find
# `qtrequestory` at all, so PYTHONPATH is set explicitly — same pattern as
# tests/test_cli.py's `_headless_subprocess`.
SRC = Path(__file__).resolve().parents[1] / "src"


def _imported_after(stmt: str) -> set[str]:
    code = f"import sys; {stmt}; print('\\n'.join(sorted(sys.modules)))"
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True, env=env,
    ).stdout
    return set(out.split())


def test_cli_import_never_loads_pypdfium2():
    mods = _imported_after("import qtrequestory.cli")
    assert not any(m.startswith("pypdfium2") for m in mods)


def test_officina_package_import_is_light():
    mods = _imported_after("import qtrequestory.officina")
    assert not any(m.startswith("pypdfium2") for m in mods)


def test_pdf_helper_loads_pypdfium2():
    mods = _imported_after("import qtrequestory.officina.pdf")
    assert "pypdfium2" in mods


def test_only_the_officina_pdf_package_imports_pypdfium2():
    """Ruling F9: ``officina/pdf/`` is a package (public API in ``__init__``,
    private submodules); no module outside it imports pypdfium2."""
    package = SRC / "qtrequestory" / "officina" / "pdf"
    importing = re.compile(r"^\s*(import|from)\s+pypdfium2", re.MULTILINE)
    outside = [path.relative_to(SRC).as_posix() for path in (SRC / "qtrequestory").rglob("*.py")
               if package not in path.parents and importing.search(path.read_text(encoding="utf-8"))]
    assert outside == []
    assert (package / "__init__.py").is_file()
    assert not (SRC / "qtrequestory" / "officina" / "pdf.py").exists()
