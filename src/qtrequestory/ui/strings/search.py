"""Strings of the Ricerca page (form, results table) and the preview pane.

Owned by: Task 12 (form + table) and Task 13 (preview pane, in a clearly
separated block at the END of this file).
Only ``UPPER_CASE`` string constants; the package re-exports every public
name defined here, so keep names unique across the strings package (prefix them
with the page, e.g. ``SEARCH_``, ``SYNC_``).
"""

# --- preview pane -----------------------------------------------------------
# Owned by Task 13. Everything below belongs to the preview pane on the right
# of the Ricerca page; the ``PREVIEW_`` prefix keeps it apart from the form and
# the results table above, which use ``SEARCH_``.

# -- empty / loading state ---------------------------------------------------

#: Placeholder of the body view while no row is selected.
PREVIEW_EMPTY = "Seleziona una chiamata per vedere il body."
#: Shown while the worker reads and pretty-prints the body.
PREVIEW_LOADING = "Lettura del body…"

# -- header ------------------------------------------------------------------

PREVIEW_BTN_OPEN_EDITOR = "Apri in Notepad++"
PREVIEW_BTN_COPY = "Copia negli appunti"
PREVIEW_TOOLTIP_OPEN_EDITOR = "Apri il body completo nell'editor (Ctrl+O)"
PREVIEW_TOOLTIP_SAVE_AS = "Salva il body completo in un file (Ctrl+S)"
PREVIEW_TOOLTIP_COPY = "Copia il body completo negli appunti (Ctrl+C)"
PREVIEW_TOOLTIP_FOLDER = "Apri la cartella dei file estratti (Ctrl+Shift+O)"
#: Tooltip of the file-name label; {name} = the name the actions will produce.
PREVIEW_NAME_TOOLTIP = "Nome del file estratto: {name}"

# -- footer ------------------------------------------------------------------

#: {shown} = the cap, {total} = the body's line count, both already formatted
#: with the Italian thousands separator ("4.000", "12.480").
PREVIEW_TRUNCATED = (
    "Anteprima: prime {shown} righe di {total} — Apri in Notepad++ per il body completo"
)
#: {message} = the error text of the failed read.
PREVIEW_ERROR = "Impossibile leggere il body: {message}"

# -- status bar messages -----------------------------------------------------

#: {size} = the size of the copied text ("312 KB").
PREVIEW_STATUS_COPIED = "Copiato negli appunti ({size})"
#: {path} = the file the user chose in the save dialog.
PREVIEW_STATUS_SAVED = "Salvato in {path}"
PREVIEW_STATUS_OPENED_EDITOR = "Aperto in Notepad++"
PREVIEW_STATUS_OPENED_DEFAULT = "Aperto con l'applicazione predefinita"
#: {path} = the folder the extracted files are written into.
PREVIEW_STATUS_FOLDER = "Aperta la cartella {path}"

# -- save dialog -------------------------------------------------------------

PREVIEW_SAVE_CAPTION = "Salva il body come…"
PREVIEW_SAVE_FILTER = "File JSON (*.json);;Tutti i file (*)"

# -- find bar ----------------------------------------------------------------

PREVIEW_FIND_PLACEHOLDER = "Trova nel body"
PREVIEW_FIND_NEXT = "Successivo (Invio)"
PREVIEW_FIND_PREVIOUS = "Precedente"
PREVIEW_FIND_CLOSE = "Chiudi la barra di ricerca (Esc)"
#: Glyphs of the three find-bar buttons; the words are in the tooltips above.
PREVIEW_FIND_NEXT_GLYPH = "▼"
PREVIEW_FIND_PREVIOUS_GLYPH = "▲"
PREVIEW_FIND_CLOSE_GLYPH = "✕"
#: {text} = what the user typed in the find bar.
PREVIEW_FIND_NOT_FOUND = "«{text}» non è presente nel body."
