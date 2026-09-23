"""Strings of the Ricerca page (bar, results, empty states) and the preview pane.

Owned by the Search unit (Tasks 14-16); the preview pane's strings are in a
clearly separated block at the END of this file.
Only ``UPPER_CASE`` string constants; the package re-exports every public
name defined here, so keep names unique across the strings package (prefix them
with the page, e.g. ``SEARCH_``, ``SYNC_``).
"""

# --- filter bar -------------------------------------------------------------

SEARCH_ENV_LABEL = "Ambiente"
SEARCH_OMNIBOX_PLACEHOLDER = "Incolla un FDI, una template key o un nome file .json"
#: Placeholder once an FDI chip is in the field.
SEARCH_OMNIBOX_PLACEHOLDER_KEY = "aggiungi una template key…"
#: Placeholder once a key chip (and no FDI) is in the field.
SEARCH_OMNIBOX_PLACEHOLDER_FDI = "aggiungi un FDI…"
SEARCH_OMNIBOX_TOOLTIP = (
    "FDI (anche solo le prime cifre), template key o nome di una chiamata.\n"
    "Ctrl+L: FDI · Ctrl+K: template key · Freccia giù: ricerche recenti"
)
#: The small caption in front of a chip's value.
SEARCH_CHIP_FDI = "FDI"
SEARCH_CHIP_KEY = "KEY"
SEARCH_CHIP_REMOVE = "Rimuovi il filtro"
SEARCH_KEY_MODE_EXACT = "esatta"
SEARCH_KEY_MODE_CONTAINS = "contiene"
SEARCH_KEY_MODE_TOOLTIP = "Come confrontare la template key"
SEARCH_PERIOD_7 = "7 gg"
SEARCH_PERIOD_30 = "30 gg"
SEARCH_PERIOD_90 = "90 gg"
SEARCH_PERIOD_CUSTOM_TOOLTIP = "Scegli un intervallo di date"
#: Tooltip of the calendar button while a custom range is active; {first}/{last} = dd/MM/yyyy.
SEARCH_PERIOD_CUSTOM_ACTIVE_TOOLTIP = "Dal {first} al {last}"
SEARCH_DATE_FROM_LABEL = "Dal"
SEARCH_DATE_TO_LABEL = "Al"
SEARCH_PERIOD_APPLY = "Applica"
#: Qt date format of every date the page shows (also the ``QDateEdit`` mask).
SEARCH_DATE_FORMAT = "dd/MM/yyyy"
SEARCH_BTN = "Cerca"
#: The [Cerca] button while a search runs.
SEARCH_BTN_BUSY = "Cerca…"
SEARCH_BTN_TOOLTIP = "Cerca nei log locali (Invio)"
SEARCH_BTN_DISABLED_TOOLTIP = "Inserisci un FDI (anche solo le prime cifre) oppure una template key."
#: Between the parts of a recent search ("coll · 1a2b3c4d… · MOD_TEST_A").
SEARCH_RECENT_SEPARATOR = " · "
SEARCH_RECENT_TITLE = "Ricerche recenti"
#: A recent search of an environment that is no longer enabled; {env} = its name.
SEARCH_RECENT_ENV_DISABLED = "L'ambiente {env} non è abilitato: ricerca non eseguita."

# --- meta line, banners -----------------------------------------------------

#: Right half of the meta line; {env} = environment, {first}/{last} = dd/MM/yyyy.
SEARCH_COVERAGE = "log {env} dal {first} al {last}"
SEARCH_COVERAGE_TOOLTIP = (
    "Giorni presenti nell'indice locale. Le chiamate di oggi arrivano domani "
    "con il file del giorno."
)
#: {env}: nothing is indexed yet for that environment.
SEARCH_COVERAGE_NONE = "nessun log locale per {env}"
#: The coverage warning; {env} = environment.
SEARCH_GAP_ONE = "manca 1 giorno in {env}"
#: {n} = missing weekdays, {env} = environment.
SEARCH_GAP_MANY = "mancano {n} giorni in {env}"
#: Tooltip of the coverage warning; {days} = the missing days, dd/MM, comma separated.
SEARCH_GAP_TOOLTIP = "Giorni feriali senza file locale: {days}"
SEARCH_GAP_BTN = "Vai a Sincronizzazione"
SEARCH_SUMMARY_TAIL = "ordinate dalla più recente"
#: {column} = the header label of the sort column.
SEARCH_SUMMARY_TAIL_COLUMN = "ordinate per {column}"
#: {calls}/{fdis}/{days} = the three counts below, already pluralised; {tail} = a tail above.
SEARCH_SUMMARY = "{calls} · {fdis} · {days} · {tail}"
SEARCH_SUMMARY_CALLS_ONE = "1 chiamata"
#: {n} = number of hits.
SEARCH_SUMMARY_CALLS_MANY = "{n} chiamate"
SEARCH_SUMMARY_FDIS_ONE = "1 FDI"
#: {n} = number of distinct FDIs.
SEARCH_SUMMARY_FDIS_MANY = "{n} FDI"
SEARCH_SUMMARY_DAYS_ONE = "1 giorno"
#: {n} = number of distinct days.
SEARCH_SUMMARY_DAYS_MANY = "{n} giorni"
#: {error} = the message of the failed search job.
SEARCH_FAILED = "Ricerca non riuscita: {error}"
#: {n} = files the index has not scanned yet.
SEARCH_STALE_BANNER = "Indice in aggiornamento… {n} file non sono ancora ricercabili."

# --- results table ----------------------------------------------------------

SEARCH_COL_WHEN = "Quando"
SEARCH_COL_KEY = "Template key"
SEARCH_COL_FDI = "FDI"
SEARCH_COL_NDOCS = "Doc"
SEARCH_COL_SIZE = "Dim."
#: The row of an FDI group; {fdi} = the whole FDI, {when} = dd/MM/yyyy HH:mm:ss
#: of its newest call, {calls} = SEARCH_SUMMARY_CALLS_ONE / _MANY.
SEARCH_GROUP_LABEL = "{fdi} · {when} · {calls}"
#: The group of the calls the log records without an FDI.
SEARCH_GROUP_NO_FDI = "senza FDI"
SEARCH_GROUP_TOGGLE = "Raggruppa per FDI"
SEARCH_GROUP_TOGGLE_TOOLTIP = "Mostra le chiamate raggruppate per FDI oppure in un elenco unico"
#: Shown where the log carries no value at all (no time, no FDI, no call id).
SEARCH_VALUE_MISSING = "—"
#: Shown where the value should exist but could not be read (unparsable body).
SEARCH_VALUE_UNKNOWN = "?"
# Sizes are NOT spelled here: the whole application formats them through
# ``ui/pages/sync_format.format_size`` and the ``SYNC_UNIT_*`` constants. Three
# private size formatters is exactly how the same body came to read
# "1.434 KB" in this table and "1,4 MB" in the status bar of the same click.

SEARCH_ELLIPSIS = "…"

# --- row context menu -------------------------------------------------------

SEARCH_MENU_OPEN = "Apri in Notepad++"
SEARCH_MENU_COPY_JSON = "Copia JSON"
SEARCH_MENU_COPY_FDI = "Copia FDI"
SEARCH_MENU_COPY_KEY = "Copia template key"
SEARCH_MENU_ONLY_FDI = "Cerca solo questo FDI"
SEARCH_MENU_ONLY_KEY = "Cerca solo questa template key"
SEARCH_MENU_OPEN_DAY_FOLDER = "Apri cartella del log del giorno"
SEARCH_STATUS_COPIED_FDI = "FDI copiato negli appunti."
SEARCH_STATUS_COPIED_KEY = "Template key copiata negli appunti."
#: Ctrl+Shift+C: the selected row as one tab-separated line.
SEARCH_STATUS_COPIED_ROW = "Riga copiata negli appunti (TSV)."
#: A body action (Ctrl+C, Ctrl+O, Ctrl+S…) with no call selected.
SEARCH_NOTHING_SELECTED = "Nessuna chiamata selezionata."
#: Tooltip of the three body actions while no preview pane is installed.
SEARCH_NO_PREVIEW_TOOLTIP = "L'anteprima non è disponibile in questa versione."

# --- empty states -----------------------------------------------------------

#: {env}: the environment has no indexed log at all.
SEARCH_EMPTY_NO_LOG_TITLE = "Nessun log locale per {env}."
SEARCH_EMPTY_NO_LOG_HINT = "Sincronizza l'ambiente per scaricare i log e poterli cercare."
SEARCH_EMPTY_NO_LOG_BTN = "Vai a Sincronizzazione"
SEARCH_EMPTY_NO_RESULTS_TITLE = "Nessuna chiamata trovata."
SEARCH_EMPTY_NO_RESULTS_HINT = "Controlla l'ambiente, il periodo e i filtri."
#: {file} = YYYYMMDD.txt of today; shown when the window ends today.
SEARCH_EMPTY_HINT_TODAY = "Le chiamate di oggi arrivano domani con il file {file}."
SEARCH_EMPTY_HINT_SHORT_FDI = "Prova con l'FDI completo."
#: Shown when an EXACT key search found nothing. Keys come in suffix families
#: (_LUCE / _GAS / _DUAL / _386), so typing half of one is the natural mistake.
SEARCH_EMPTY_HINT_EXACT_KEY = (
    "La template key deve essere completa: scegli la key dall'elenco "
    "oppure passa a «contiene»."
)
SEARCH_EMPTY_WIDEN_BTN = "Allarga a 90 giorni"
#: The no-log state when the mirror has files but the index is empty (after a
#: schema upgrade threw the old index away); {env} = environment.
SEARCH_EMPTY_REBUILDING_TITLE = "L'indice è in ricostruzione."
SEARCH_EMPTY_REBUILDING_HINT = (
    "I log di {env} sono nel mirror locale ma non ancora nell'indice: diventano "
    "ricercabili dopo la prossima indicizzazione o sincronizzazione."
)
SEARCH_START_TITLE = "Incolla un FDI, una template key o un nome file .json"
SEARCH_START_HINT_FDI = "un FDI intero o solo le sue prime cifre"
SEARCH_START_HINT_KEY = "una template key, oppure una sua parte con «contiene»"
SEARCH_START_HINT_NAME = "il nome di una chiamata copiato dal log: compila FDI e key insieme"
SEARCH_START_SHORTCUTS = (
    "Ctrl+L FDI · Ctrl+K template key · Invio apre la chiamata · Ctrl+C copia il JSON · "
    "trascina una riga per ottenere il file"
)
SEARCH_EMPTY_NO_ENV_TITLE = "Nessun ambiente abilitato."
SEARCH_EMPTY_NO_ENV_HINT = "Abilita almeno un ambiente in Impostazioni per poter cercare nei suoi log."
SEARCH_EMPTY_NO_ENV_BTN = "Apri Impostazioni"

# --- preview slot -----------------------------------------------------------

#: Placeholder shown on the right until a preview pane is installed.
SEARCH_PREVIEW_PLACEHOLDER = "L'anteprima del body non è disponibile in questa versione."

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

#: The primary button when Notepad++ is the editor (configured or found).
PREVIEW_BTN_OPEN_EDITOR = "Apri in Notepad++"
#: ... and when it is another editor, or the application Windows associates.
PREVIEW_BTN_OPEN_DEFAULT = "Apri nell'editor"
PREVIEW_TOOLTIP_OPEN_EDITOR = "Apri il body completo nell'editor (Ctrl+O)"
PREVIEW_TOOLTIP_COPY = "Copia JSON (Ctrl+C)"
PREVIEW_TOOLTIP_SAVE_AS = "Salva con nome… (Ctrl+S)"
PREVIEW_TOOLTIP_FOLDER = "Apri cartella (Ctrl+Shift+O)"
#: Tooltip of the file-name label; {name} = the name the actions will produce.
PREVIEW_NAME_TOOLTIP = "Nome del file estratto: {name}"
PREVIEW_MENU_COPY_NAME = "Copia nome file"
PREVIEW_STATUS_COPIED_NAME = "Nome file copiato negli appunti."
PREVIEW_TAB_JSON = "JSON"
PREVIEW_TAB_DETAILS = "Dettagli"

# -- Dettagli tab --------------------------------------------------------------

PREVIEW_DETAIL_ENV = "Ambiente"
PREVIEW_DETAIL_DAY = "Giorno"
PREVIEW_DETAIL_TIME = "Ora"
PREVIEW_DETAIL_LOG = "File di log"
PREVIEW_DETAIL_SIZE = "Dimensione"
PREVIEW_DETAIL_NDOCS = "N. documenti"
PREVIEW_DETAIL_FDI = "FDI"
PREVIEW_DETAIL_KEY = "Template key"
PREVIEW_DETAIL_NAME = "Nome chiamata"

# -- footer ------------------------------------------------------------------

#: {shown} = the cap, {total} = the body's line count, both already formatted
#: with the Italian thousands separator ("4.000", "12.480").
PREVIEW_TRUNCATED = (
    "Anteprima: prime {shown} righe di {total} — apri nell'editor per il body completo"
)
#: {message} = the error text of the failed read.
PREVIEW_ERROR = "Impossibile leggere il body: {message}"

# -- confirmations -----------------------------------------------------------

#: Toast after Copia JSON; {size} = the body's size ("157 KB"), built by
#: ``sync_format.format_size`` — the same formatter as the rest of the UI.
PREVIEW_TOAST_COPIED = "JSON copiato · {size}"
#: Toast after Salva con nome…; {name} = the file name chosen.
PREVIEW_TOAST_SAVED = "Salvato: {name}"
#: After [Apri]: Notepad++ opened it / another configured editor / the app Windows associates.
PREVIEW_STATUS_OPENED_EDITOR = "Aperto in Notepad++"
PREVIEW_STATUS_OPENED_OTHER = "Aperto nell'editor"
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
#: The match is in the part of the body the preview does not show; {shown} = the cap ("4.000").
PREVIEW_FIND_BEYOND = "trovato oltre la riga {shown}: apri nell'editor"

#: Window-title context of the selected call; {env} = environment, {fdi} = first 8 chars.
SEARCH_WINDOW_CONTEXT = "{env} · {fdi}"
