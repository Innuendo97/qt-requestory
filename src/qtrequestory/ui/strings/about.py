"""Strings of the Info page.

Owned by: Task 14; cards and elided paths: Task 18.
Only ``UPPER_CASE`` string constants; the package re-exports every public
name defined here, so keep names unique across the strings package (prefix them
with the page, e.g. ``SEARCH_``, ``SYNC_``).
"""

ABOUT_TITLE = "Info"

# -- identity ----------------------------------------------------------------

ABOUT_VERSION_LABEL = "Versione"
ABOUT_SUBTITLE = "Specchio locale e ricerca dei log giornalieri delle richieste."
#: {version} = the application version.
ABOUT_VERSION = "Versione {version}"

# -- paths -------------------------------------------------------------------

ABOUT_PATHS_LABEL = "Percorsi"
ABOUT_PATH_CONFIG = "Configurazione"
ABOUT_PATH_INDEX = "Indice"
ABOUT_PATH_APP_LOG = "Log applicazione"
ABOUT_PATH_SYNC_LOG = "Log sincronizzazione"
ABOUT_PATH_COPIED = "Percorso copiato negli appunti"

# -- index -------------------------------------------------------------------

ABOUT_INDEX_LABEL = "Indice"
#: {files} = indexed daily files, {entries} = requests, {first}/{last} = dd/mm/yyyy.
ABOUT_INDEX_ENV = "{files} file · {entries} richieste · dal {first} al {last}"
ABOUT_INDEX_NONE = "non indicizzato"
ABOUT_INDEX_NO_ENVS = "Nessun ambiente attivo."
ABOUT_BTN_INDEX_SETTINGS = "Gestisci indice…"

# -- log viewer --------------------------------------------------------------

ABOUT_LOG_LABEL = "Log"
ABOUT_LOG_HINT = "Ultime righe del log applicazione"
ABOUT_FILTER_ALL = "Tutti"
ABOUT_FILTER_WARNINGS = "Avvisi"
ABOUT_FILTER_ERRORS = "Errori"
ABOUT_BTN_COPY_ALL = "Copia tutto"
ABOUT_LOG_LOADING = "Lettura del log in corso…"
ABOUT_LOG_EMPTY = "Nessuna riga di log da mostrare."
ABOUT_LOG_NO_MATCH = "Nessuna riga corrisponde al filtro selezionato."
ABOUT_LOG_COPIED = "Log copiato negli appunti"
#: {message} = why the log file could not be read.
ABOUT_LOG_FAILED = "Impossibile leggere il log: {message}"
