"""Strings of the Impostazioni page.

Owned by: Task 14.
Only ``UPPER_CASE`` string constants; the package re-exports every public
name defined here, so keep names unique across the strings package (prefix them
with the page, e.g. ``SEARCH_``, ``SYNC_``).
"""

# -- sections ----------------------------------------------------------------

SETTINGS_MIRROR_LABEL = "Cartella dei log locali"
SETTINGS_MIRROR_CAPTION = "Seleziona la cartella dei log locali"
SETTINGS_ENVS_LABEL = "Ambienti"
SETTINGS_EDITOR_LABEL = "Notepad++"
SETTINGS_EDITOR_CAPTION = "Seleziona notepad++.exe"
#: Qt file dialog filter for the editor executable.
SETTINGS_EDITOR_FILTER = "Programmi (*.exe);;Tutti i file (*)"
SETTINGS_WINDOW_LABEL = "Periodo predefinito"
SETTINGS_OUTPUT_LABEL = "Cartella file temporanei"
SETTINGS_OUTPUT_CAPTION = "Seleziona la cartella dei file temporanei"
SETTINGS_OUTPUT_HINT = "Lascia vuoto per usare la cartella temporanea di sistema."
SETTINGS_SCHEDULE_LABEL = "Sincronizzazione automatica"
SETTINGS_ADVANCED_LABEL = "Avanzate"

# -- environments ------------------------------------------------------------

SETTINGS_BTN_CHECK = "Verifica"
SETTINGS_CHECK_RUNNING = "Verifica in corso…"
SETTINGS_CHECK_NONE = "Nessun ambiente da verificare."
#: {name} = the environment name.
SETTINGS_CHECK_REACHABLE = "{name}: raggiungibile"
SETTINGS_CHECK_UNREACHABLE = "{name}: non raggiungibile"
SETTINGS_CHECK_SEPARATOR = " · "
#: {message} = why the reachability check could not be completed.
SETTINGS_CHECK_FAILED = "Verifica non riuscita: {message}"
SETTINGS_CHECK_HINT = (
    "Gli ambienti sono raggiungibili solo da rete aziendale o VPN: "
    "se ora non lo sono, va bene lo stesso."
)

# -- editor ------------------------------------------------------------------

SETTINGS_BTN_DETECT = "Rileva"
SETTINGS_EDITOR_NOT_FOUND = "Notepad++ non trovato: indica il percorso con Sfoglia…"
#: {path} = the detected executable.
SETTINGS_EDITOR_FOUND = "Notepad++ trovato in {path}"

# -- default window ----------------------------------------------------------

#: {days} = 7, 30 or 90.
SETTINGS_WINDOW_DAYS = "{days} giorni"

# -- automatic synchronisation -----------------------------------------------
#
# The four fields of the scheduled task. The sentence that summarises them is
# NOT here: it is shared with the Sincronizzazione page and lives in
# ``strings/sync.py`` (``SYNC_SCHEDULE_*``), assembled by
# ``ui/pages/schedule_text.py``, so the two pages cannot describe the same task
# differently.

SETTINGS_SCHEDULE_START = "Ora di avvio"
SETTINGS_SCHEDULE_EVERY = "Riprova ogni"
SETTINGS_SCHEDULE_FOR = "per"
#: QSpinBox suffixes; the singular avoids "ogni 1 ore".
SETTINGS_SCHEDULE_HOUR_ONE = " ora"
SETTINGS_SCHEDULE_HOURS = " ore"
#: Shown instead of a bare 0 in the "per" box: 0 hours means a single daily run.
SETTINGS_SCHEDULE_NO_REPEAT = "nessuna ripetizione"
SETTINGS_SCHEDULE_LOGON = "Esegui anche al login"
SETTINGS_SCHEDULE_LOGON_HINT = (
    "Se il PC è spento all'ora di avvio, il login è ciò che recupera la giornata: "
    "sul server i log restano disponibili per circa un giorno."
)
#: {schedule} = the shared sentence, which carries no final full stop of its own.
SETTINGS_SCHEDULE_SUMMARY = "{schedule}."
#: {message} = why schtasks refused to update the already registered task.
SETTINGS_SCHEDULE_UPDATE_FAILED = "Impossibile aggiornare l'attività pianificata: {message}"

# -- advanced ----------------------------------------------------------------

SETTINGS_BTN_REBUILD = "Ricostruisci indice"
SETTINGS_REBUILD_TITLE = "Ricostruisci indice"
SETTINGS_REBUILD_QUESTION = (
    "L'indice verrà ricostruito da zero rileggendo tutti i file già scaricati. "
    "Può richiedere qualche minuto. Vuoi continuare?"
)
SETTINGS_BTN_RERUN_WIZARD = "Riesegui configurazione iniziale"
#: {path} = the config.json the application is using.
SETTINGS_CONFIG_PATH = "File di configurazione: {path}"

# -- saving ------------------------------------------------------------------

SETTINGS_SAVED = "Impostazioni salvate"
SETTINGS_ERRORS_TITLE = "Correggi questi errori prima di salvare:"
#: Prefix of each line of that list.
SETTINGS_ERROR_BULLET = "• "
SETTINGS_ERROR_NO_MIRROR = "indica la cartella dei log locali"
SETTINGS_REINDEX_TITLE = "Cartella dei log cambiata"
SETTINGS_REINDEX_QUESTION = "Vuoi indicizzare i log presenti nella nuova cartella ora?"
SETTINGS_INDEX_STARTED = "Indicizzazione avviata…"
#: {n} = files scanned.
SETTINGS_INDEX_DONE = "Indicizzazione completata: {n} file."
#: {message} = the error text of the failed job.
SETTINGS_INDEX_FAILED = "Indicizzazione non riuscita: {message}"
