"""Strings of the Ricerca page (form, results table) and the preview pane.

Owned by: Task 12 (form + table) and Task 13 (preview pane, in a clearly
separated block at the END of this file).
Only ``UPPER_CASE`` string constants; the package re-exports every public
name defined here, so keep names unique across the strings package (prefix them
with the page, e.g. ``SEARCH_``, ``SYNC_``).
"""

# --- form -------------------------------------------------------------------

SEARCH_ENV_LABEL = "Ambiente"
SEARCH_FDI_LABEL = "FDI"
SEARCH_FDI_PLACEHOLDER = "uuid o prefisso"
SEARCH_FDI_TOOLTIP = (
    "Identificativo della pratica: uuid completo o solo le prime cifre.\n"
    "Incollando il nome di una chiamata viene compilata anche la template key."
)
SEARCH_KEY_LABEL = "Template key"
SEARCH_KEY_PLACEHOLDER = "tutte le template key"
SEARCH_KEY_TOOLTIP = "Nome del modello richiesto; scrivi una parte del nome per filtrare l'elenco."
SEARCH_PERIOD_LABEL = "Periodo"
SEARCH_PERIOD_7 = "7 gg"
SEARCH_PERIOD_30 = "30 gg"
SEARCH_PERIOD_90 = "90 gg"
SEARCH_PERIOD_CUSTOM = "Personalizzato"
SEARCH_DATE_FROM_LABEL = "dal"
SEARCH_DATE_TO_LABEL = "al"
#: Qt date format of every date the page shows (also the ``QDateEdit`` mask).
SEARCH_DATE_FORMAT = "dd/MM/yyyy"
SEARCH_BTN = "Cerca"
SEARCH_BTN_TOOLTIP = "Cerca nei log locali (Invio)"
SEARCH_BTN_DISABLED_TOOLTIP = "Inserisci un FDI (anche solo le prime cifre) oppure una template key."

# --- coverage, summary, banner ----------------------------------------------

#: {env} = environment name, {first}/{last} = dd/MM/yyyy of the indexed range.
SEARCH_COVERAGE = "Log locali {env}: dal {first} al {last} · le chiamate di oggi arrivano domani"
#: {env}: nothing is indexed yet for that environment.
SEARCH_COVERAGE_NONE = "Nessun log locale per {env}: non c'è ancora niente da cercare."
SEARCH_SUMMARY_TAIL = "ordinate dalla più recente"
#: {calls}/{fdis}/{days} = the three counts below, already pluralised.
SEARCH_SUMMARY = "{calls} · {fdis} · {days} · " + SEARCH_SUMMARY_TAIL
SEARCH_SUMMARY_CALLS_ONE = "1 chiamata"
#: {n} = number of hits.
SEARCH_SUMMARY_CALLS_MANY = "{n} chiamate"
SEARCH_SUMMARY_FDIS_ONE = "1 FDI"
#: {n} = number of distinct FDIs.
SEARCH_SUMMARY_FDIS_MANY = "{n} FDI"
SEARCH_SUMMARY_DAYS_ONE = "1 giorno"
#: {n} = number of distinct days.
SEARCH_SUMMARY_DAYS_MANY = "{n} giorni"
SEARCH_RUNNING = "Ricerca in corso…"
#: {error} = the message of the failed search job.
SEARCH_FAILED = "Ricerca non riuscita: {error}"
#: {n} = files the index has not scanned yet.
SEARCH_STALE_BANNER = "Indice in aggiornamento… {n} file non sono ancora ricercabili."

# --- results table ----------------------------------------------------------

SEARCH_COL_DAY = "Giorno"
SEARCH_COL_TIME = "Ora"
SEARCH_COL_KEY = "Template key"
SEARCH_COL_FDI = "FDI"
SEARCH_COL_NDOCS = "N. doc"
SEARCH_COL_SIZE = "Dim."
SEARCH_COL_CALL_ID = "ID chiamata"
SEARCH_COL_FILE = "File"
#: Shown where the log carries no value at all (no time, no FDI, no call id).
SEARCH_VALUE_MISSING = "—"
#: Shown where the value should exist but could not be read (unparsable body).
SEARCH_VALUE_UNKNOWN = "?"
#: {n} = kilobytes, already grouped with the Italian thousands separator.
SEARCH_SIZE_KB = "{n} KB"
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
SEARCH_EMPTY_WIDEN_BTN = "Cerca negli ultimi 90 giorni"

# --- preview slot -----------------------------------------------------------

#: Placeholder shown on the right until a preview pane is installed.
SEARCH_PREVIEW_PLACEHOLDER = "L'anteprima del body non è disponibile in questa versione."
