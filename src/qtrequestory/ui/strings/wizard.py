"""Strings of the first-run wizard.

Owned by: Task 10 (reworked by Task 19).
Only ``UPPER_CASE`` string constants; the package re-exports every public
name defined here, so keep names unique across the strings package (prefix them
with the page, e.g. ``SEARCH_``, ``SYNC_``).

The three pages are numbered as in DESIGN-ui §"First-run wizard": ``P1`` the log
folder and the editor, ``P2`` the environments, ``P3`` the automation.
"""

# -- the wizard itself -------------------------------------------------------

WIZARD_TITLE = "Configurazione iniziale"
#: Qt ships its own (possibly English) button texts; the UI is Italian, so the
#: wizard sets all four explicitly.
WIZARD_BTN_NEXT = "Avanti"
WIZARD_BTN_BACK = "Indietro"
WIZARD_BTN_FINISH = "Fine"
#: The muted stepper line in each page header; {i} = 1, 2 or 3.
WIZARD_STEP = "Passo {i} di 3"
#: ``main_window.job_label`` of the page-1 file count.
JOB_WIZARD_COUNT_FILES = "Conteggio dei file di log"

# -- 1. archivio e strumenti -------------------------------------------------

WIZARD_P1_TITLE = "Archivio e strumenti"
WIZARD_P1_SUBTITLE = "Dove tenere la copia locale dei log e con cosa aprire le chiamate."
#: The two-line intro of the first page: what the tool does, then the README advice.
WIZARD_P1_INTRO = (
    "qtRequestory tiene una copia locale dei log giornalieri degli ambienti e ti fa "
    "cercare ed estrarre le chiamate anche dopo che il server le ha cancellate."
)
WIZARD_P1_ADVICE = (
    "Consiglio: scegli una cartella su un disco locale capiente, non una cartella "
    "sincronizzata nel cloud."
)
WIZARD_P1_LABEL = "Cartella dei log:"
WIZARD_P1_BROWSE_CAPTION = "Scegli la cartella dei log"
WIZARD_P1_ERROR_EMPTY = "Indica una cartella."
#: {path} = the folder the user typed or picked.
WIZARD_P1_ERROR_NOT_WRITABLE = (
    "Non è possibile scrivere in «{path}»: scegli un'altra cartella."
)
#: While ``count_local_files`` walks the folder in a worker.
WIZARD_P1_COUNTING = "conteggio…"
#: {n} = files already under that folder (core ``count_local_files(root)``).
WIZARD_P1_EXISTING_FILES = (
    "Trovati {n} file di log già presenti: verranno indicizzati, non riscaricati."
)
WIZARD_P1_EDITOR_LABEL = "Notepad++:"
WIZARD_P1_EDITOR_CAPTION = "Scegli l'eseguibile di Notepad++"
WIZARD_P1_EDITOR_FILTER = "Eseguibili (*.exe);;Tutti i file (*)"
WIZARD_P1_EDITOR_NOT_FOUND = (
    "Notepad++ non trovato: i file verranno aperti con l'applicazione predefinita."
)

# -- 2. ambienti -------------------------------------------------------------

WIZARD_P2_TITLE = "Ambienti"
WIZARD_P2_SUBTITLE = "Da quali ambienti scaricare i log."
WIZARD_P2_HINT = (
    "Chiedi al collega il file environments.json oppure inserisci nome e URL."
)
#: {path} = the environments.json found next to the executable.
WIZARD_P2_SIDECAR_LOADED = "Ambienti caricati da {path}."
#: The wizard is being re-run: the table shows what is already in config.json.
WIZARD_P2_CONFIGURED_LOADED = (
    "Ambienti già configurati: modificali, aggiungine altri oppure importali da file."
)
#: Grey text in the empty cells of a row (never saved as data).
WIZARD_P2_NAME_PLACEHOLDER = "nome"
WIZARD_P2_URL_PLACEHOLDER = "https://…"
WIZARD_P2_BTN_CHECK = "Verifica raggiungibilità"
WIZARD_P2_CHECK_NOTE = (
    "Gli ambienti sono raggiungibili solo da rete aziendale o VPN Cisco: "
    "se ora non lo sono, va bene lo stesso."
)
WIZARD_P2_CHECK_RUNNING = "Verifica in corso…"
WIZARD_P2_CHECK_EMPTY = "Aggiungi almeno un ambiente per verificarne la raggiungibilità."
WIZARD_P2_REACHABLE = "raggiungibile"
WIZARD_P2_UNREACHABLE = "non raggiungibile"
#: {env} = environment name, {state} = one of the two above.
WIZARD_P2_CHECK_RESULT = "{env}: {state}"
WIZARD_P2_CHECK_SEPARATOR = " · "
#: Not an error: zero environments is allowed, the user can add them later.
WIZARD_P2_NO_ENVIRONMENTS = (
    "Nessun ambiente abilitato: potrai aggiungerli più avanti da Impostazioni."
)

# -- 3. automazione ----------------------------------------------------------

WIZARD_P3_TITLE = "Automazione"
WIZARD_P3_SUBTITLE = "Come tenere aggiornata la copia locale senza pensarci."
WIZARD_P3_AUTOSYNC = "Sincronizza automaticamente i log"
#: While the wizard asks the scheduler whether the task is already registered.
WIZARD_P3_AUTOSYNC_CHECKING = "verifica in corso…"
#: {schedule} = the sentence of ``ui/pages/schedule_text.py``, built from the
#: saved configuration — the wizard registers exactly that schedule, so the
#: hours must not be written here a third time.
WIZARD_P3_AUTOSYNC_NOTE = (
    "{schedule}. Solo se la rete è raggiungibile; nessuna password salvata."
)
#: Shown only when the old PowerShell task is detected, and unticked by
#: default: the two tasks coexist safely, so removing it is the user's call.
WIZARD_P3_LEGACY_REMOVE = "Rimuovi il vecchio task NginxLogSync"
WIZARD_P3_LEGACY_NOTE = (
    "Puoi tenerli entrambi finché non hai verificato che il nuovo funziona: "
    "non si danneggiano a vicenda"
)
WIZARD_P3_START_SYNC = "Avvia la prima sincronizzazione al termine"
#: Under the checkbox above (F9): the first run is not "yesterday's file".
WIZARD_P3_FIRST_SYNC_NOTE = (
    "La prima sincronizzazione scarica tutto lo storico ancora presente sul server, "
    "fino all'ultima pulizia: possono essere diversi GB e richiedere parecchio tempo."
)

# -- fine --------------------------------------------------------------------

WIZARD_SAVE_FAILED_TITLE = "Configurazione non salvata"
#: {error} = the exception from config.save; the wizard stays open afterwards.
WIZARD_SAVE_FAILED = (
    "Non è stato possibile salvare la configurazione: {error}\n"
    "Correggi il problema e riprova, oppure annulla la procedura."
)
WIZARD_SCHEDULER_FAILED_TITLE = "Automazione non attivata"
#: {error} = the message of the SchedulerError; shown, never fatal.
WIZARD_SCHEDULER_FAILED = (
    "Non è stato possibile registrare la sincronizzazione automatica: {error}\n"
    "Puoi riprovare più tardi dalla pagina Sincronizzazione."
)
WIZARD_UNREGISTER_FAILED_TITLE = "Automazione ancora attiva"
#: {error} = the SchedulerError of ``unregister`` (a rerun that turned
#: automation off); shown, never fatal.
WIZARD_UNREGISTER_FAILED = (
    "Non è stato possibile disattivare la sincronizzazione automatica: {error}\n"
    "Puoi riprovare più tardi dalla pagina Sincronizzazione."
)
