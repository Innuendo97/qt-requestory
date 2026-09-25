"""Strings of the Impostazioni page.

Owned by: Task 14; sections, theme and unsaved bar: Task 18.
Only ``UPPER_CASE`` string constants; the package re-exports every public
name defined here, so keep names unique across the strings package (prefix them
with the page, e.g. ``SEARCH_``, ``SYNC_``).
"""

SETTINGS_TITLE = "Impostazioni"

# -- section list (in page order) --------------------------------------------

SETTINGS_SECTION_APPEARANCE = "Aspetto"
SETTINGS_SECTION_ARCHIVE = "Archivio"
SETTINGS_SECTION_ENVIRONMENTS = "Ambienti"
SETTINGS_SECTION_AUTOMATION = "Sincronizzazione automatica"
SETTINGS_SECTION_SEARCH = "Ricerca"
SETTINGS_SECTION_EDITOR = "Editor esterno"
SETTINGS_SECTION_ADVANCED = "Avanzate"

SETTINGS_SECTION_OFFICINA = "Officina"

# -- Aspetto -----------------------------------------------------------------

SETTINGS_THEME_LABEL = "Tema"
SETTINGS_THEME_SYSTEM = "Sistema"
SETTINGS_THEME_LIGHT = "Chiaro"
SETTINGS_THEME_DARK = "Scuro"
SETTINGS_THEME_NOTE = "Si applica subito, senza salvare."
SETTINGS_RESULTS_LABEL = "Risultati"
SETTINGS_GROUP_BY_FDI = "Raggruppa i risultati per FDI"

# -- Archivio ----------------------------------------------------------------

SETTINGS_MIRROR_LABEL = "Cartella dei log locali"
SETTINGS_MIRROR_CAPTION = "Seleziona la cartella dei log locali"
SETTINGS_OUTPUT_LABEL = "Cartella file temporanei"
SETTINGS_OUTPUT_CAPTION = "Seleziona la cartella dei file temporanei"
#: Shown in place of an empty output folder.
SETTINGS_OUTPUT_DEFAULT = "Cartella temporanea di sistema"
SETTINGS_BTN_OUTPUT_DEFAULT = "Usa predefinita"
SETTINGS_INDEX_LABEL = "Indice"
#: {files} = indexed daily files, {entries} = indexed requests, {last} = dd/mm/yyyy.
SETTINGS_INDEX_STATE = "{files} file · {entries} richieste · fino al {last}"
SETTINGS_INDEX_EMPTY = "Nessun file indicizzato"

# -- Editor esterno ----------------------------------------------------------

SETTINGS_EDITOR_LABEL = "Notepad++"
SETTINGS_EDITOR_CAPTION = "Seleziona notepad++.exe"
#: Qt file dialog filter for the editor executable.
SETTINGS_EDITOR_FILTER = "Programmi (*.exe);;Tutti i file (*)"
SETTINGS_EDITOR_NONE = "Non impostato"

# -- Ricerca -----------------------------------------------------------------

SETTINGS_WINDOW_LABEL = "Periodo predefinito"
SETTINGS_KEY_MODE_LABEL = "Template key"
#: The same words as the segmented control of the Ricerca bar.
SETTINGS_KEY_MODE_EXACT = "esatta"
SETTINGS_KEY_MODE_CONTAINS = "contiene"

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
    "Gli ambienti sono raggiungibili solo da rete aziendale o VPN Cisco: "
    "se ora non lo sono, va bene lo stesso."
)

# -- editor ------------------------------------------------------------------

SETTINGS_BTN_DETECT = "Rileva"
SETTINGS_EDITOR_NOT_FOUND = "Notepad++ non trovato: indica il percorso con Sfoglia…"
#: {path} = the detected executable.
SETTINGS_EDITOR_FOUND = "Notepad++ trovato in {path}"

# -- default window ----------------------------------------------------------

#: {days} = 7, 30 or 90; the same "7 gg" labels as the Ricerca page.
SETTINGS_WINDOW_DAYS = "{days} gg"

# -- automatic synchronisation -----------------------------------------------
#
# The four fields of the scheduled task. The sentence that summarises them is
# NOT here: it is shared with the Sincronizzazione page and lives in
# ``strings/sync.py`` (``SYNC_SCHEDULE_*``), assembled by
# ``ui/pages/schedule_text.py``, so the two pages cannot describe the same task
# differently.

SETTINGS_SCHEDULE_START = "Ora di avvio"
SETTINGS_SCHEDULE_EVERY = "Riprova ogni"
SETTINGS_SCHEDULE_FOR = "Ripeti per"
#: QSpinBox suffixes; the singular avoids "ogni 1 ore".
SETTINGS_SCHEDULE_HOUR_ONE = " ora"
SETTINGS_SCHEDULE_HOURS = " ore"
#: Shown instead of a bare 0 in the "per" box: 0 hours means a single daily run.
SETTINGS_SCHEDULE_NO_REPEAT = "nessuna ripetizione"
SETTINGS_SCHEDULE_LOGON_LABEL = "Al login"
SETTINGS_SCHEDULE_LOGON = "Esegui anche al login"
SETTINGS_SCHEDULE_LOGON_HINT = (
    "Se il PC è spento all'ora di avvio, il login recupera la sincronizzazione mancata: "
    "sul server i log restano solo fino alla prossima pulizia manuale."
)
#: {schedule} = the shared sentence, which carries no final full stop of its own.
SETTINGS_SCHEDULE_SUMMARY = "{schedule}."
SETTINGS_SCHEDULE_SUMMARY_LABEL = "In breve"
#: {message} = why schtasks refused to update the already registered task.
SETTINGS_SCHEDULE_UPDATE_FAILED = "Impossibile aggiornare l'attività pianificata: {message}"
#: The {message} of SETTINGS_SCHEDULE_UPDATE_FAILED when another schtasks call is running.
SETTINGS_SCHEDULE_BUSY = "è in corso un'altra operazione sull'attività pianificata"
SETTINGS_BTN_RETRY = "Riprova"

# -- Officina ----------------------------------------------------------------

SETTINGS_OFFICINA_GENERAL = "Officina"
SETTINGS_OFFICINA_FOLDER_LABEL = "Cartella dell'Officina"
SETTINGS_OFFICINA_FOLDER_CAPTION = "Seleziona la cartella dell'Officina"
SETTINGS_OFFICINA_FOLDER_NONE = "Non impostata"
#: Allowed: a warning, not an error.
SETTINGS_OFFICINA_ONEDRIVE = (
    "La cartella è in OneDrive: payload e documenti contengono dati reali dei clienti "
    "e verranno sincronizzati nel cloud."
)
SETTINGS_OFFICINA_NETWORK = (
    "La cartella è su un disco di rete: payload e documenti contengono dati reali dei clienti, "
    "e le generazioni possono rallentare o fallire se la rete cade."
)
SETTINGS_OFFICINA_BUSY = (
    "L'Officina sta generando o consegnando documenti: la cartella si può cambiare "
    "quando ha finito (o dopo averli annullati)."
)
SETTINGS_OFFICINA_TIMEOUT_LABEL = "Timeout di generazione (secondi)"
SETTINGS_OFFICINA_TOKEN_LABEL = "Postman-Token predefinito"
SETTINGS_OFFICINA_TOKEN_HINT = (
    "Con un Postman-Token non vuoto lo Scaler non scrive la chiamata nei log nginx: "
    "le prove restano fuori dai log. Si toglie solo dal singolo caso, con l'apposita opzione."
)
SETTINGS_OFFICINA_GENERATORS = "Generatori"
SETTINGS_OFFICINA_GENERATORS_HINT = (
    "Gli endpoint documentGenerator a cui l'Officina invia i payload. Solo https; "
    "nome e URL non possono contenere 'prod' o 'prd': la produzione non è mai configurabile."
)
SETTINGS_OFFICINA_COL_PROBLEM = "Problema"
SETTINGS_OFFICINA_DEFAULT_LABEL = "Generatore predefinito"
SETTINGS_OFFICINA_DEFAULT_NONE = "— scegli —"
#: {name} = the generator that was the default.
SETTINGS_OFFICINA_DEFAULT_REMOVED = (
    "Il generatore predefinito '{name}' è stato eliminato: scegline un altro tra quelli attivi."
)
SETTINGS_OFFICINA_DEFAULT_DISABLED = (
    "Il generatore predefinito '{name}' è stato disattivato: scegline un altro tra quelli attivi."
)
SETTINGS_OFFICINA_HEADERS = "Profilo intestazioni"
SETTINGS_OFFICINA_HEADERS_HINT = (
    "Inviate a ogni generazione; le intestazioni dell'iniziativa e del caso hanno la precedenza. "
    "Host, Content-Length, Transfer-Encoding e le altre intestazioni gestite dal client HTTP "
    "non sono ammesse."
)
SETTINGS_OFFICINA_COL_HEADER = "Nome"
SETTINGS_OFFICINA_COL_VALUE = "Valore"
#: The page's error list, when the tables still show problems.
SETTINGS_OFFICINA_FIX_ROWS = "Officina: correggi gli errori segnalati accanto alle righe"
#: The save bar's button that opens the Officina section while it blocks Salva.
SETTINGS_OFFICINA_SHOW = "Mostra"


# -- advanced ----------------------------------------------------------------

SETTINGS_BTN_REBUILD = "Ricostruisci indice"
SETTINGS_REBUILD_TITLE = "Ricostruisci indice"
SETTINGS_REBUILD_QUESTION = (
    "L'indice verrà ricostruito da zero rileggendo tutti i file già scaricati. "
    "Può richiedere qualche minuto. Vuoi continuare?"
)
SETTINGS_BTN_RERUN_WIZARD = "Riesegui configurazione iniziale"
SETTINGS_CONFIG_LABEL = "File di configurazione"
SETTINGS_WIZARD_LABEL = "Configurazione iniziale"

# -- saving ------------------------------------------------------------------

SETTINGS_SAVED = "Impostazioni salvate"
SETTINGS_UNSAVED = "Modifiche non salvate"
SETTINGS_LEAVE_TITLE = "Modifiche non salvate"
SETTINGS_LEAVE_QUESTION = "Salvare le modifiche?"
SETTINGS_LEAVE_INFO = "Le modifiche alle impostazioni non sono ancora state salvate."
SETTINGS_LEAVE_SAVE = "Salva"
SETTINGS_LEAVE_DISCARD = "Scarta"
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
#: {problem} = the core's sentence about the log folder (config.mirror_root), through ``lower_first``.
SETTINGS_INDEX_REFUSED = "Indicizzazione non avviata: {problem}"
