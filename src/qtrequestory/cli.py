"""Entry point. Headless modes (--sync/--index/--find/--task) must never import Qt.

Filled in by the integration task; this stub only fixes the contract.
"""
from __future__ import annotations

import os
import sys


def _guard_std_streams() -> None:
    """A windowed PyInstaller exe has sys.stdout/stderr == None: any print would raise."""
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115


def main(argv: list[str] | None = None) -> int:
    _guard_std_streams()
    raise NotImplementedError("cli.main is implemented in the integration task")
