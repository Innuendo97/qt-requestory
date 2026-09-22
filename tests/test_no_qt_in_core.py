"""Guard: qtrequestory.core must stay standard-library only (no Qt, no tkinter)."""
import re
from pathlib import Path

CORE = Path(__file__).resolve().parents[1] / "src" / "qtrequestory" / "core"
FORBIDDEN = re.compile(r"^\s*(from|import)\s+(PySide6|PyQt\d|tkinter|shiboken6)\b", re.M)


def test_core_has_no_gui_imports():
    offenders = [p for p in CORE.rglob("*.py") if FORBIDDEN.search(p.read_text(encoding="utf-8"))]
    assert not offenders, f"GUI imports in core: {offenders}"


def test_cli_does_not_import_qt_at_module_level():
    cli = CORE.parent / "cli.py"
    assert not FORBIDDEN.search(cli.read_text(encoding="utf-8"))
