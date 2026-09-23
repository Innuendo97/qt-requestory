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

import hashlib
import logging
import os
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFileDialog, QWidget

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import CoreServices, SearchHit

__all__ = [
    "SAVE_DIR_KEY",
    "copy_text",
    "extract_file",
    "last_save_dir",
    "open_hit_in_editor",
    "open_output_folder",
    "save_hit_as",
    "user_settings",
]

log = logging.getLogger(__name__)

#: Where the folder of the last "Salva con nome…" is remembered. Saving three
#: bodies in a row into the same folder is the common case, and re-navigating
#: there every time is the kind of friction that makes people stop using a tool.
SAVE_DIR_KEY = "preview/save_dir"


def open_hit_in_editor(services: CoreServices, hit: SearchHit, text: str) -> str:
    """Write ``text`` to the output folder and open it; ``"editor"``/``"default"``.

    Through :func:`extract_file`: an older file with the same name is reused
    only when it holds exactly this body — a different call of the same day,
    pratica and template is never passed off as this one.
    """
    path = extract_file(services, hit, text)
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
    user_settings().setValue(SAVE_DIR_KEY, str(path.parent))
    log.debug("body salvato in %s", path)
    return path


def copy_text(text: str) -> int:
    """Put ``text`` on the clipboard and return its length in characters."""
    QGuiApplication.clipboard().setText(text)
    return len(text)


def open_output_folder(services: CoreServices, hit: SearchHit, text: str) -> Path:
    """Write this body to the output folder and show that folder.

    ``output_name`` is ``<day>_<fdi>_<template key>.json`` with no call id, so
    two calls of the same pratica, day and template share it. A file of that
    name is therefore reused only when its bytes ARE this body
    (:func:`extract_file`); otherwise the core writes the call-id name rather
    than overwriting a file the user may still have open. Pressing [Apri
    cartella] twice no longer leaves a ``_<call id>`` duplicate.
    """
    path = extract_file(services, hit, text)
    services.extract.open_folder(path.parent)
    return path.parent


def extract_file(services: CoreServices, hit: SearchHit, text: str) -> Path:
    """The output file of ``hit`` holding exactly ``text``: reused when it is there.

    ``write_temp_file`` never overwrites: when ``output_name(hit)`` exists it
    writes the call-id name instead, so opening the same call twice left a
    ``_<call id>`` duplicate beside an identical file. A file of that name
    whose bytes ARE this body (same size, same SHA-256) is simply reused — its
    time is refreshed so the output housekeeping does not delete it while it
    is in use. Anything else — another call's body under the same name — is
    never reused: the core writes the call-id name, as before.
    """
    data = text.encode("utf-8")
    existing = Path(services.extract.output_dir()) / services.extract.output_name(hit)
    try:
        if (existing.is_file() and existing.stat().st_size == len(data)
                and hashlib.sha256(existing.read_bytes()).digest() == hashlib.sha256(data).digest()):
            os.utime(existing)
            return existing
    except OSError:
        log.debug("file estratto non riutilizzabile: %s", existing, exc_info=True)
    return services.extract.write_temp_file(hit, text)


def last_save_dir() -> Path | None:
    """The folder of the last successful "Salva con nome…", if it still exists."""
    stored = user_settings().value(SAVE_DIR_KEY, "")
    if not stored:
        return None
    path = Path(str(stored))
    return path if path.is_dir() else None


def user_settings() -> QSettings:
    """The application's ``QSettings`` store — the ONE way to open it.

    Never ``QSettings(org, app)``: that constructor hardcodes ``NativeFormat``
    (the Windows registry) and ignores ``QSettings.setDefaultFormat`` entirely,
    so the redirection ``tests/ui/conftest.py`` installs would not catch it and
    the suite would write window geometry, the last used environment and the
    last save folder into the developer's real registry
    (``HKCU\\Software\\qtRequestory``). In the application ``defaultFormat``
    *is* NativeFormat, so production behaviour is unchanged.
    """
    return QSettings(QSettings.defaultFormat(), QSettings.Scope.UserScope,
                     strings.ORG_NAME, strings.APP_NAME)
