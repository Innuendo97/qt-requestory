"""What the user can do to a row of the Ricerca table: keys, context menu, TSV.

Split from ``search_page.py`` so the page stays a renderer of its states. Every
function here takes the :class:`~qtrequestory.ui.pages.search_page.SearchPage`
and calls back into its public row actions — ``delegate`` above all, the one place
that hands Apri / Salva / Copia JSON / cartella to whoever holds the body (the
preview pane).

**Where the keys live.** The row shortcuts are ``QShortcut`` objects on the
PAGE with ``WidgetWithChildrenShortcut``, not on the pane: they have to work
with the focus on the results table, which is where the user is after clicking
a row. The pane binds none of them — two shortcuts for one key in the same
focus chain are ambiguous and Qt fires *neither*.

**Ctrl+C.** A text field keeps its own Ctrl+C: ``QLineEdit`` (and the body
editor, see ``preview_body.BodyEdit``) claim the key through
``ShortcutOverride`` before a shortcut is even considered, so the page's
binding never fires there. :func:`copy_shortcut` still checks the focus, so a
text widget that does not claim the key gets its selection copied rather than a
body swapped in under the user's cursor.
"""
from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QTextEdit,
)

from qtrequestory.ui import actions, icons, strings
from qtrequestory.ui.contracts import SearchHit
from qtrequestory.ui.results_model import format_day, format_time

if TYPE_CHECKING:
    from qtrequestory.ui.pages.search_page import SearchPage

__all__ = [
    "BODY_ACTIONS", "add_to_officina", "build_context_menu", "copy_shortcut", "install_shortcuts",
    "prepare_drag_file", "row_tsv", "show_context_menu",
]

#: The body actions the page delegates to the pane: menu label, pane method,
#: icon, shortcut. The menu shows the same shortcut the page binds.
BODY_ACTIONS: tuple[tuple[str, str, str, str], ...] = (
    (strings.SEARCH_MENU_OPEN, "open_in_editor", "document-arrow-right", "Ctrl+O"),
    (strings.BTN_SAVE_AS, "save_as", "save", "Ctrl+S"),
    (strings.SEARCH_MENU_COPY_JSON, "copy_body", "copy", "Ctrl+C"),
)
#: The page's own keys: search again, and the two filters of the omnibox.
PAGE_SHORTCUTS: tuple[tuple[str, str], ...] = (
    ("F5", "search"),
    ("Ctrl+L", "focus_fdi"),
    ("Ctrl+K", "focus_key"),
)
#: Row bindings (DESIGN-ui §"Ricerca page").
#: Enter is not here: it opens the row only when the TABLE has the focus (the
#: page's event filter) — as a page shortcut it would steal Enter = [Cerca]
#: from the form.
ROW_SHORTCUTS: tuple[tuple[str, str], ...] = (
    ("Ctrl+C", "copy"),
    ("Ctrl+Shift+C", "tsv"),
    ("Ctrl+S", "save_as"),
    ("Ctrl+O", "open_in_editor"),
    ("Ctrl+Shift+O", "open_folder"),
)

_TEXT_INPUTS = (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)


def row_tsv(hit: SearchHit) -> str:
    """``giorno\\tora\\ttemplate_key\\tfdi\\tn_doc\\tbytes`` — one line for a sheet.

    Day and time read like the table (dd/MM/yyyy, HH:MM:SS); the key and the
    FDI are whole, never elided; the size is the exact byte count. A missing
    value is an empty cell, not the table's em dash.
    """
    time = format_time(hit.request_date) if hit.request_date else ""
    fields = (
        format_day(hit.day), time, hit.template_key, hit.fdi or "",
        "" if hit.ndocs is None else str(hit.ndocs), str(hit.body_len),
    )
    return "\t".join(fields)


def install_shortcuts(page: SearchPage) -> dict[str, QShortcut]:
    """Bind F5 / Ctrl+L / Ctrl+K and :data:`ROW_SHORTCUTS` on ``page``; by sequence."""
    slots = {
        "copy": partial(copy_shortcut, page),
        "tsv": partial(copy_row_tsv, page),
        "search": page.run_search,
        "focus_fdi": page.form.focus_fdi,
        "focus_key": page.form.focus_key,
    }
    bound: dict[str, QShortcut] = {}
    for sequence, name in PAGE_SHORTCUTS + ROW_SHORTCUTS:
        slot = slots.get(name) or partial(page.delegate, name)
        shortcut = QShortcut(QKeySequence(sequence), page)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.activated.connect(slot)
        bound[sequence] = shortcut
    return bound


def prepare_drag_file(page: SearchPage, hit: SearchHit) -> Path | None:
    """The file a dragged row hands out, written now (bodies are small).

    Read synchronously on purpose: the drag has already started and needs its
    data; the busy cursor says why the mouse paused. The file is reused when an
    identical one is already in the output folder (``actions.extract_file``).
    """
    pane = page.preview_widget()
    current = getattr(pane, "current_hit", None)
    loaded = getattr(pane, "body_text", None)
    if callable(current) and callable(loaded) and current() == hit and loaded():
        return actions.extract_file(page.services, hit, loaded())  # already on screen
    QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)
    try:
        services = page.services
        text = services.extract.pretty_json(services.index.read_body(hit))
        return actions.extract_file(services, hit, text)
    except Exception as exc:  # noqa: BLE001 - a failed drag must not crash the page
        page.set_status(strings.PREVIEW_ERROR.format(message=exc))
        return None
    finally:
        QApplication.restoreOverrideCursor()


def copy_shortcut(page: SearchPage) -> None:
    """Ctrl+C on the page: the full body, unless the focus is typing text."""
    focus = page.focusWidget()
    if isinstance(focus, _TEXT_INPUTS):
        copier = getattr(focus, "copy", None)
        if callable(copier):
            copier()  # the field's own selection, as the user expects
        return
    page.delegate("copy_body")


def copy_row_tsv(page: SearchPage) -> None:
    """Ctrl+Shift+C: the selected row as one TSV line."""
    hit = page.selected_hit()
    if hit is None:
        return
    QGuiApplication.clipboard().setText(row_tsv(hit))
    page.confirm(strings.SEARCH_STATUS_COPIED_ROW)


def show_context_menu(page: SearchPage, pos) -> None:
    """Right click on a call (a group row has no menu)."""
    view = page.view
    hit = view.results.hit_of(view.indexAt(pos))
    if hit is None:
        return
    view.select_hit(hit)
    menu = build_context_menu(page, hit)
    menu.exec(view.viewport().mapToGlobal(pos))
    menu.deleteLater()


def build_context_menu(page: SearchPage, hit: SearchHit) -> QMenu:
    """The row menu, built without showing it (so it can be tested)."""
    menu = QMenu(page)
    has_pane = page.preview_widget() is not None
    open_label = getattr(page.preview_widget(), "open_label", None)
    for label, method, icon_name, sequence in BODY_ACTIONS:
        if method == "open_in_editor" and callable(open_label):
            label = open_label()  # the pane's button: "Apri in Notepad++" or "nell'editor"
        action = _add(menu, label, partial(page.delegate, method), enabled=has_pane,
                      icon_name=icon_name, sequence=sequence)
        if not has_pane:
            action.setToolTip(strings.SEARCH_NO_PREVIEW_TOOLTIP)
    menu.addSeparator()
    _add(menu, strings.SEARCH_MENU_COPY_FDI,
         partial(page.copy_value, hit.fdi, strings.SEARCH_STATUS_COPIED_FDI), enabled=bool(hit.fdi))
    _add(menu, strings.SEARCH_MENU_COPY_KEY,
         partial(page.copy_value, hit.template_key, strings.SEARCH_STATUS_COPIED_KEY))
    _add(menu, strings.SEARCH_MENU_ONLY_FDI, partial(page.search_only, hit.fdi, None),
         enabled=bool(hit.fdi))
    _add(menu, strings.SEARCH_MENU_ONLY_KEY, partial(page.search_only, None, hit.template_key))
    menu.addSeparator()
    _add(menu, strings.SEARCH_MENU_OPEN_DAY_FOLDER, partial(page.open_day_folder, hit),
         icon_name="folder-open")
    menu.addSeparator()
    _add(menu, strings.OFFICINA_ADD_MENU, partial(add_to_officina, page, hit), icon_name="wrench")
    for extra in page.context_menu_actions:
        menu.addAction(extra)
    return menu


def add_to_officina(page: SearchPage, hit: SearchHit) -> None:
    """"Aggiungi all'Officina…": the call becomes a case (``officina_add``).

    Imported on use: the Officina's modules are not Ricerca's business until
    the user asks for them.
    """
    from qtrequestory.ui.pages.officina_add import add_hit_to_officina

    add_hit_to_officina(page, page.services, hit)


def _add(menu: QMenu, label: str, slot, *, enabled: bool = True, icon_name: str = "",
         sequence: str = "") -> QAction:
    action = menu.addAction(label)
    action.setEnabled(enabled)
    if icon_name:
        action.setIcon(icons.icon(icon_name))
        action.setProperty("iconName", icon_name)
    if sequence:
        action.setShortcut(QKeySequence(sequence))
        # Display only: the page's own QShortcut is what fires the key.
        action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
    action.setShortcutVisibleInContextMenu(True)
    action.triggered.connect(lambda _checked=False: slot())
    return action
