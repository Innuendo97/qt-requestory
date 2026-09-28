"""Can a folder take new files? Shared by the wizard's folder steps.

Only a real write tells the truth on Windows: a path can be listable and still
refuse new files (a read-only share, a redirected Documents folder), and
``os.access`` does not know that. So the check creates the folder (if needed)
and a throwaway file in it.

``keep=False`` removes again the folders the check itself created, so a step
that is only *validated* (the user may still press Annulla) leaves nothing on
disk; whoever saves creates the folder for real.
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path

__all__ = ["is_writable"]

log = logging.getLogger(__name__)


def _missing_chain(folder: Path) -> list[Path]:
    """The folders of ``folder`` that do not exist yet, deepest first."""
    missing: list[Path] = []
    current = folder
    while not current.exists() and current.parent != current:
        missing.append(current)
        current = current.parent
    return missing


def is_writable(folder: Path, *, keep: bool = True) -> bool:
    """True when a file can be created in ``folder`` (created if missing).

    With ``keep=False`` the folders created here are removed afterwards
    (``rmdir`` only: an empty folder we made, never anything else)."""
    created = [] if keep else _missing_chain(folder)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=folder, prefix=".qtrequestory-", suffix=".tmp"):
            pass
    except OSError as exc:
        log.info("cartella non utilizzabile (%s): %s", folder, exc)
        return False
    finally:
        for path in created:  # deepest first
            try:
                path.rmdir()
            except OSError:
                break
    return True
