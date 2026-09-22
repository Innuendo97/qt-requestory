"""Strings of the Info page.

Owned by: Task 14.
Only ``UPPER_CASE`` string constants; the package re-exports every public
name defined here, so keep names unique across the strings package (prefix them
with the page, e.g. ``SEARCH_``, ``SYNC_``).
"""

# -- identity ----------------------------------------------------------------

ABOUT_SUBTITLE = "Specchio locale e ricerca dei log giornalieri delle richieste."
#: {version} = the application version.
ABOUT_VERSION = "Versione {version}"

# -- paths -------------------------------------------------------------------

ABOUT_PATHS_LABEL = "Percorsi"
ABOUT_PATH_CONFIG = "Configurazione"
ABOUT_PATH_INDEX = "Indice"
ABOUT_PATH_APP_LOG = "Log applicazione"
ABOUT_PATH_SYNC_LOG = "Log sincronizzazione"

# -- log viewer --------------------------------------------------------------

ABOUT_LOG_LABEL = "Ultime righe del log applicazione"
ABOUT_FILTER_ALL = "Tutti"
ABOUT_FILTER_WARNINGS = "Avvisi"
ABOUT_FILTER_ERRORS = "Errori"
ABOUT_BTN_COPY_ALL = "Copia tutto"
ABOUT_LOG_LOADING = "Lettura del log in corso…"
ABOUT_LOG_EMPTY = "Nessuna riga di log da mostrare."
ABOUT_LOG_COPIED = "Log copiato negli appunti"
#: {message} = why the log file could not be read.
ABOUT_LOG_FAILED = "Impossibile leggere il log: {message}"
