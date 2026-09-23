"""Shell strings: window, app bar, status bar, dialogs, generic buttons.

Owned by the shell task. A page task adds nothing here — a label that belongs
to one page goes into that page's module. The generic buttons at the bottom are
the exception: they read the same everywhere, so every page reuses them.
"""

# -- application -------------------------------------------------------------

APP_NAME = "qtRequestory"
ORG_NAME = "qtRequestory"
WINDOW_TITLE = "qtRequestory"
#: The title while something is on screen; {context} = e.g. "coll · 1a2b3c4d".
WINDOW_TITLE_CONTEXT = "qtRequestory — {context}"

# -- app bar -----------------------------------------------------------------

NAV_SEARCH = "Ricerca"
NAV_SYNC = "Sincronizzazione"
NAV_SETTINGS = "Impostazioni"
NAV_ABOUT = "Info"
#: Tooltip of a tab or icon button; {label} = the NAV_* label, {shortcut} = "Ctrl+1".
NAV_TOOLTIP = "{label} ({shortcut})"

#: The sync-status chip: one "env when" entry per environment, joined by this.
CHIP_SEPARATOR = " · "
STATUS_SYNC_SUMMARY_TOOLTIP = "Apri la pagina Sincronizzazione"

# -- status bar --------------------------------------------------------------
#: {name} = the LABEL of the refused operation, never its internal job name —
#: see the ``JOB_*`` constants below and ``main_window.job_label``.
STATUS_BUSY = "Operazione «{name}» già in corso."

# -- operation labels --------------------------------------------------------
# The names ``JobRunner.submit`` is called with are code ("check-envs",
# "search_plan", "about-log"). They must never reach the status bar: the person
# reading it works in Italian and has no way to find out what "scheduler" is.

JOB_SYNC = "Sincronizzazione"
JOB_SYNC_TASK_STATUS = "Verifica sincronizzazione automatica"
JOB_SYNC_REACHABILITY = "Verifica raggiungibilità"
JOB_INDEX = "Aggiornamento indice"
JOB_SCHEDULER = "Sincronizzazione automatica"
JOB_SEARCH = "Ricerca"
JOB_SEARCH_KEYS = "Elenco template key"
JOB_SEARCH_PLAN = "Controllo indice"
JOB_PREVIEW = "Anteprima"
JOB_CHECK_ENVS = "Verifica raggiungibilità"
JOB_ABOUT_LOG = "Lettura del log"
JOB_WIZARD_REACHABILITY = "Verifica raggiungibilità"
JOB_WIZARD_TASK_STATUS = "Verifica sincronizzazione automatica"
#: {message} = the error text of a failed background job.
STATUS_ERROR = "Errore: {message}"

# -- pages -------------------------------------------------------------------

#: A page module is missing from this build; {label} = its navigation label.
PAGE_UNAVAILABLE = "La pagina «{label}» non è disponibile in questa versione."
WIZARD_UNAVAILABLE = "La configurazione iniziale non è disponibile in questa versione."

# -- invalid log folder (banner on Ricerca and Sincronizzazione) -------------

#: {problem} = the core's own sentence ("La cartella dei log non è impostata").
MIRROR_ROOT_BANNER = ("{problem}. Sincronizzazione e indicizzazione restano ferme "
                      "finché non la correggi.")
MIRROR_ROOT_BUTTON = "Apri Impostazioni › Archivio"

# -- close while a sync or an index job runs ---------------------------------

#: {label} = the JOB_* label of the running operation ("Sincronizzazione").
QUIT_DURING_JOB_TITLE = "{label} in corso"
#: {label} = as above; {progress} = QUIT_PROGRESS with a leading ": ", or "".
QUIT_DURING_JOB_TEXT = "{label} in corso{progress}. Interrompere e uscire?"
#: {done} = files handled so far, {total} = files announced ("12 di 48 file").
QUIT_PROGRESS = "{done} di {total} file"
QUIT_SYNC_INFO = "I file non ancora scaricati verranno ripresi al prossimo avvio."
QUIT_INDEX_INFO = "I file non ancora indicizzati verranno ripresi al prossimo avvio."
QUIT_STOP = "Interrompi ed esci"
QUIT_CONTINUE = "Continua"

# -- environments table (wizard + Impostazioni) ------------------------------

ENV_COL_ENABLED = "Attivo"
ENV_COL_NAME = "Nome"
ENV_COL_URL = "URL"
ENV_IMPORT_CAPTION = "Seleziona il file environments.json"
#: Qt file dialog filter for the environments file.
ENV_IMPORT_FILTER = "File JSON (*.json);;Tutti i file (*)"
ENV_IMPORT_ERROR_TITLE = "File non valido"
#: {error} = the message of the ValueError raised by the importer.
ENV_IMPORT_ERROR = "Impossibile leggere il file degli ambienti: {error}"

# -- generic buttons ---------------------------------------------------------

BTN_CANCEL = "Annulla"
BTN_SAVE = "Salva"
BTN_SAVE_AS = "Salva con nome…"
BTN_BROWSE = "Sfoglia…"
BTN_OPEN = "Apri"
BTN_OPEN_FOLDER = "Apri cartella"
BTN_ADD = "Aggiungi"
BTN_REMOVE = "Rimuovi"
BTN_IMPORT_FILE = "Importa da file…"
BTN_REFRESH = "Aggiorna"
BTN_COPY = "Copia"
BTN_CLOSE = "Chiudi"
