"""Shell strings: window, navigation rail, status bar, dialogs, generic buttons.

Owned by the shell task. A page task adds nothing here — a label that belongs
to one page goes into that page's module. The generic buttons at the bottom are
the exception: they read the same everywhere, so every page reuses them.
"""

# -- application -------------------------------------------------------------

APP_NAME = "qtRequestory"
ORG_NAME = "qtRequestory"
WINDOW_TITLE = "qtRequestory"

# -- navigation rail ---------------------------------------------------------

NAV_SEARCH = "Ricerca"
NAV_SYNC = "Sincronizzazione"
NAV_SETTINGS = "Impostazioni"
NAV_ABOUT = "Info"

# -- status bar --------------------------------------------------------------

#: Right-hand segment before any sync ran; replaced by "svil: oggi 11:23 · …".
STATUS_SYNC_SUMMARY_EMPTY = "Mai sincronizzato"
STATUS_SYNC_SUMMARY_TOOLTIP = "Apri la pagina Sincronizzazione"
#: {name} = the LABEL of the refused operation, never its internal job name —
#: see the ``JOB_*`` constants below and ``main_window.job_label``.
STATUS_BUSY = "Operazione «{name}» già in corso."

# -- operation labels --------------------------------------------------------
# The names ``JobRunner.submit`` is called with are code ("check-envs",
# "search_plan", "about-log"). They must never reach the status bar: the person
# reading it works in Italian and has no way to find out what "scheduler" is.

JOB_SYNC = "Sincronizzazione"
JOB_INDEX = "Aggiornamento indice"
JOB_SCHEDULER = "Sincronizzazione automatica"
JOB_SEARCH = "Ricerca"
JOB_SEARCH_KEYS = "Elenco template key"
JOB_SEARCH_PLAN = "Controllo indice"
JOB_PREVIEW = "Anteprima"
JOB_CHECK_ENVS = "Verifica raggiungibilità"
JOB_ABOUT_LOG = "Lettura del log"
JOB_WIZARD_REACHABILITY = "Verifica raggiungibilità"
#: {message} = the error text of a failed background job.
STATUS_ERROR = "Errore: {message}"

# -- pages -------------------------------------------------------------------

#: A page module is missing from this build; {label} = its rail label.
PAGE_UNAVAILABLE = "La pagina «{label}» non è disponibile in questa versione."
WIZARD_UNAVAILABLE = "La configurazione iniziale non è disponibile in questa versione."

# -- close while syncing -----------------------------------------------------

QUIT_DURING_SYNC_TITLE = "Sincronizzazione in corso"
QUIT_DURING_SYNC_TEXT = (
    "È in corso una sincronizzazione: se esci ora i file non ancora scaricati "
    "verranno ripresi al prossimo avvio."
)
QUIT_STOP = "Interrompi ed esci"
QUIT_CONTINUE = "Continua"

# -- environments table (wizard + Impostazioni) ------------------------------

ENV_COL_ENABLED = "abilitato"
ENV_COL_NAME = "nome"
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
