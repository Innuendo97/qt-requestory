"""Officina phase 2: the noise rules dialog and the DOM tab (spec §6, §7.5).

Owned by ``ui/pages/officina_noise.py`` / ``officina_noise_editor.py`` (the "Regole di rumore…" dialog),
``ui/pages/officina_noise_page.py`` (what the page does with it) and
``ui/pages/officina_dom.py`` (the "DOM" tab of an HTML case).
"""

# -- entry points -------------------------------------------------------------------
RUMORE_BUTTON = "Regole di rumore…"
RUMORE_BUTTON_TIP = "Testo che cambia a ogni generazione (date, numeri di pagina…): non conta come differenza."

# -- the dialog -----------------------------------------------------------------------
# {name}: the initiative's name
RUMORE_TITLE_INITIATIVE = "Regole di rumore — iniziativa «{name}»"
RUMORE_HELP = ("Le regole cercano nel testo normalizzato (virgolette e trattini uniformati, "
               "spazi ridotti a uno).")
RUMORE_SWITCH_NOTE = ("Qui scrivi le regole; le accendi e le spegni dai «Filtri del confronto» di un caso "
                      "(con «Usa per tutta l'iniziativa» per tutti i casi).")
RUMORE_OWN_INITIATIVE = "Regole dell'iniziativa"
RUMORE_OWN_CASE = "Regole di questo caso"
RUMORE_COL_NAME = "Nome"
RUMORE_COL_PATTERN = "Espressione regolare"
RUMORE_COL_HITS = "Occorrenze"
RUMORE_ADD = "+ Regola"
RUMORE_REMOVE = "Rimuovi"
RUMORE_OK = "Salva e riconfronta"
RUMORE_NEW_NAME = "Regola {n}"
# {case}: the case the counts are taken on ("MOD_TEST_A · abilitato")
RUMORE_COUNTS_ON = "Occorrenze nel target e nell'ultimo TO-BE di {case}."
RUMORE_COUNTS_NONE = "Seleziona un caso nella bacheca per vedere le occorrenze."

# -- the count column ---------------------------------------------------------------
RUMORE_HITS_NONE = "nessuna"
RUMORE_HITS_ONE = "1 occorrenza"
# {n}: occurrences
RUMORE_HITS_MANY = "{n} occorrenze"
RUMORE_HITS_UNKNOWN = "—"
RUMORE_HITS_FAILED = "conteggio non riuscito"

# -- errors on a row (they block "Salva") ----------------------------------------------
RUMORE_ERR_NAME_EMPTY = "manca il nome"
RUMORE_ERR_PATTERN_EMPTY = "manca l'espressione"
# {reason}: Python's own message, e.g. "missing ), unterminated subpattern at position 0"
RUMORE_ERR_REGEX = "espressione non valida: {reason}"
# {where}: RUMORE_WHERE_* below
RUMORE_ERR_DUPLICATE = "nome già usato {where}"
RUMORE_WHERE_HERE = "da un'altra regola qui"
RUMORE_WHERE_PRESET = "da un preset"
RUMORE_WHERE_INITIATIVE = "da una regola dell'iniziativa"
# {case}: the key of the case whose rule has that name
RUMORE_WHERE_CASE = "dalla regola del caso {case}"
RUMORE_BLOCKED = "Correggi le righe in rosso per salvare."

# -- what the page says ------------------------------------------------------------------
RUMORE_SAVED = "Regole di rumore salvate: il confronto riparte"
RUMORE_SAVED_INITIATIVE = "Regole di rumore dell'iniziativa salvate"
RUMORE_WAIT_GENERATION = "Generazioni in corso: le regole dell'iniziativa si cambiano quando finiscono"
# {reason}: why the save was refused
RUMORE_FAILED = "Regole di rumore non salvate: {reason}"

# -- the jobs (status bar, quit dialog) --------------------------------------------
RUMORE_JOB_COUNT = "Conteggio delle regole di rumore"
DOM_JOB = "Sorgente HTML del caso"

# -- the DOM tab ----------------------------------------------------------------------
DOM_VIEW_DOCS = "Documenti"
DOM_VIEW_DOM = "DOM"
DOM_VIEW_TIP = "Il sorgente HTML dei due lati, con i blocchi che differiscono."
DOM_TREE = "Blocchi del target"
DOM_TARGET = "Sorgente del target"
DOM_GENERATED = "Sorgente generato"
DOM_LOADING = "Preparazione del sorgente…"
DOM_EMPTY = "Il sorgente non è disponibile per questa versione."
# {reason}: why dom_view failed
DOM_FAILED = "Sorgente non disponibile: {reason}"
