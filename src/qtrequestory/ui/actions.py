"""The four things the user does with a body — as functions, not as a widget.

Apri in Notepad++, Salva con nome…, Copia negli appunti and Apri cartella are
offered twice on the Ricerca page: as the preview pane's buttons and as the
results table's context menu. They are plain functions taking ``services`` so
both callers run the *same* code — a context menu that saved a slightly
different text from the button would be the worst kind of bug here, because
the whole tool exists to hand out an exact request body.

The output contract is the reason this module is so thin: every function
receives the ``text`` the caller already has (``extract.pretty_json(body)``)
and passes it through untouched. Nothing here formats, truncates, wraps or
annotates — the file the user opens is byte for byte what the log held.
"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFileDialog, QWidget

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import CoreServices, SearchHit

__all__ = [
    "SAVE_DIR_KEY",
    "copy_text",
    "last_save_dir",
    "open_hit_in_editor",
    "open_output_folder",
    "save_hit_as",
]

log = logging.getLogger(__name__)

#: Where the folder of the last "Salva con nome…" is remembered. Saving three
#: bodies in a row into the same folder is the common case, and re-navigating
#: there every time is the kind of friction that makes people stop using a tool.
SAVE_DIR_KEY = "preview/save_dir"


def open_hit_in_editor(services: CoreServices, hit: SearchHit, text: str) -> str:
    """Write ``text`` to the output folder and open it; ``"editor"``/``"default"``.

    The file is written every time: the user asked for *this* body, and an
    older file with the same name (same day, same pratica, same template) would
    silently give them the wrong one.
    """
    path = services.extract.write_temp_file(hit, text)
    return services.extract.open_in_editor([path])


def save_hit_as(services: CoreServices, parent: QWidget | None, hit: SearchHit,
                text: str) -> Path | None:
    """Ask where to save ``text`` and write it; ``None`` when cancelled.

    The dialog opens on the folder of the previous save (or the output folder
    the first time) with ``output_name(hit)`` already filled in.
    """
    start = last_save_dir() or services.extract.output_dir()
    suggestion = Path(start) / services.extract.output_name(hit)
    chosen, _selected_filter = QFileDialog.getSaveFileName(
        parent, strings.PREVIEW_SAVE_CAPTION, str(suggestion), strings.PREVIEW_SAVE_FILTER
    )
    if not chosen:
        return None
    path = Path(chosen)
    services.extract.save_as(path, text)
    _settings().setValue(SAVE_DIR_KEY, str(path.parent))
    log.debug("body salvato in %s", path)
    return path


def copy_text(text: str) -> int:
    """Put ``text`` on the clipboard and return its length in characters."""
    QGuiApplication.clipboard().setText(text)
    return len(text)


def open_output_folder(services: CoreServices, hit: SearchHit, text: str) -> Path:
    """Show the output folder, making sure this body is in it first.

    Unlike :func:`open_hit_in_editor` an existing file is left alone: the point
    of this action is to reach the folder, and rewriting a file the user may
    have open in Notepad++ (with unsaved edits of their own) to achieve that
    would be rude.
    """
    folder = services.extract.output_dir()
    path = folder / services.extract.output_name(hit)
    if not path.is_file():
        path = services.extract.write_temp_file(hit, text)
    services.extract.open_folder(path.parent)
    return path.parent


def last_save_dir() -> Path | None:
    """The folder of the last successful "Salva con nome…", if it still exists."""
    stored = _settings().value(SAVE_DIR_KEY, "")
    if not stored:
        return None
    path = Path(str(stored))
    return path if path.is_dir() else None


def _settings() -> QSettings:
    return QSettings(strings.ORG_NAME, strings.APP_NAME)
