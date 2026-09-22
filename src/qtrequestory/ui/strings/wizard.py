"""Strings of the first-run wizard.

Owned by: Task 10.
Only ``UPPER_CASE`` string constants; the package re-exports every public
name defined here, so keep names unique across the strings package (prefix them
with the page, e.g. ``SEARCH_``, ``SYNC_``).

The three pages are numbered as in DESIGN-ui §"First-run wizard": ``P1`` the log
folder, ``P2`` the environments, ``P3`` the automation.
"""

# -- the wizard itself -------------------------------------------------------

WIZARD_TITLE = "Configurazione iniziale"
#: Qt ships its own (possibly English) button texts; the UI is Italian, so the
#: wizard sets all four explicitly.
WIZARD_BTN_NEXT = "Avanti"
WIZARD_BTN_BACK = "Indietro"
WIZARD_BTN_FINISH = "Fine"

# -- 1. cartella dei log -----------------------------------------------------

WIZARD_P1_TITLE = "Cartella dei log"
WIZARD_P1_SUBTITLE = "Dove tenere la copia locale dei log giornalieri."
WIZARD_P1_LABEL = "Cartella:"
WIZARD_P1_BROWSE_CAPTION = "Scegli la cartella dei log"
WIZARD_P1_ERROR_EMPTY = "Indica una cartella."
#: {path} = the folder the user typed or picked.
WIZARD_P1_ERROR_NOT_WRITABLE = (
    "Non è possibile scrivere in «{path}»: scegli un'altra cartella."
)
#: {n} = files already under that folder (core ``count_local_files(root)``).
WIZARD_P1_EXISTING_FILES = (
    "Trovati {n} file di log già presenti: verranno indicizzati, non riscaricati."
)

# -- 2. ambienti -------------------------------------------------------------

WIZARD_P2_TITLE = "Ambienti"
WIZARD_P2_SUBTITLE = "Da quali ambienti scaricare i log."
WIZARD_P2_HINT = (
    "Chiedi al collega il file environments.json oppure inserisci nome e URL."
)
#: {path} = the environments.json found next to the executable.
WIZARD_P2_SIDECAR_LOADED = "Ambienti caricati da {path}."
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
WIZARD_P3_AUTOSYNC = "Sincronizza automaticamente ogni giorno alle 09:00"
WIZARD_P3_AUTOSYNC_NOTE = (
    "Riprova ogni ora fino alle 18:00 e al logon; solo se la rete è raggiungibile; "
    "nessuna password salvata."
)
WIZARD_P3_LEGACY_TASK = (
    "È presente il vecchio task NginxLogSync basato su PowerShell: verrà sostituito."
)
WIZARD_P3_EDITOR_LABEL = "Notepad++:"
WIZARD_P3_EDITOR_CAPTION = "Scegli l'eseguibile di Notepad++"
WIZARD_P3_EDITOR_FILTER = "Eseguibili (*.exe);;Tutti i file (*)"
WIZARD_P3_EDITOR_NOT_FOUND = (
    "Notepad++ non trovato: i file verranno aperti con l'applicazione predefinita."
)
WIZARD_P3_START_SYNC = "Avvia la prima sincronizzazione al termine"

# -- fine --------------------------------------------------------------------

WIZARD_SCHEDULER_FAILED_TITLE = "Automazione non attivata"
#: {error} = the message of the SchedulerError; shown, never fatal.
WIZARD_SCHEDULER_FAILED = (
    "Non è stato possibile registrare la sincronizzazione automatica: {error}\n"
    "Puoi riprovare più tardi dalla pagina Sincronizzazione."
)
