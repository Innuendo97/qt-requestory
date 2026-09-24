"""Importing logs kept outside the archive: the dialog, the banner, the
Impostazioni summary and the wizard's offer (``ui/import_*.py``,
``ui/pages/import_banner.py``, ``ui/pages/archive_summary.py``).

The archive's own reasons ("giorno mancante in archivio", "archivio compresso:
estrailo nella cartella", ...) come from ``core/archive.py`` and are shown as
they are.
"""

# -- job names (``quit_dialog.JOB_LABELS``) --------------------------------------
JOB_IMPORT = "Importazione dei log"
JOB_IMPORT_SCAN = "Analisi della cartella"
JOB_ARCHIVE_REPORT = "Controllo dell'archivio"
JOB_WIZARD_ARCHIVE = "Ricerca dei log da importare"
QUIT_IMPORT_INFO = ("Le copie già verificate restano nell'archivio; "
                    "gli originali non vengono toccati.")

# -- the banner on Ricerca and Sincronizzazione ----------------------------------
#: {n} = log files found in the archive folder outside its structure.
IMPORT_BANNER = "Trovati {n} log fuori dalla struttura dell'archivio"
IMPORT_BANNER_ONE = "Trovato 1 log fuori dalla struttura dell'archivio"
IMPORT_BANNER_BUTTON = "Importa"
IMPORT_BANNER_TOOLTIP = ("Sono nella cartella dei log ma non in <ambiente>/AAAA/MM/AAAAMMGG.txt: "
                         "la ricerca non li vede finché non vengono importati.")

# -- Impostazioni › Archivio -----------------------------------------------------
ARCHIVE_SUMMARY_LABEL = "Log"
#: {archived} log in the archive; {todo} importable; {assign} waiting for an env;
#: {ignored} ignored.
ARCHIVE_SUMMARY = ("{archived} log in archivio · {todo} da importare · {assign} da assegnare"
                   " · {ignored} ignorati")
#: Appended to ARCHIVE_SUMMARY when there are conflicts; {n} = how many.
ARCHIVE_SUMMARY_CONFLICTS = " · {n} in conflitto"
ARCHIVE_SUMMARY_LOADING = "Controllo dell'archivio in corso…"
ARCHIVE_SUMMARY_UNAVAILABLE = "Archivio non controllabile: {problem}"
ARCHIVE_BTN_DETAILS = "Dettagli…"
ARCHIVE_BTN_IMPORT_FOLDER = "Importa log da una cartella…"
ARCHIVE_IMPORT_CAPTION = "Cartella con i log da importare"
#: {problem} = the first ``mirror_root_errors`` line.
IMPORT_REFUSED = "Importazione non possibile: {problem}"

# -- the dialog ------------------------------------------------------------------
IMPORT_TITLE = "Importa log"
#: {path} = the folder being imported.
IMPORT_SOURCE = "Cartella: {path}"
IMPORT_SOURCE_MIRROR = "Cartella dei log (file fuori dalla struttura): {path}"
#: {i} of {n} folders queued (the wizard can queue two).
IMPORT_SOURCE_STEP = " · cartella {i} di {n}"
IMPORT_SCANNING = "Analisi della cartella in corso…"
#: {error} = why the folder could not be read.
IMPORT_SCAN_FAILED = "Analisi non riuscita: {error}"
IMPORT_EMPTY = "Nessun log trovato in questa cartella."
IMPORT_INTRO = ("I log vengono COPIATI nell'archivio e verificati; gli originali restano dove "
                "sono finché non decidi tu.")

IMPORT_FILTER_LABEL = "Mostra"
#: {n} = how many files have that status.
IMPORT_FILTER_ALL = "Tutti ({n})"
IMPORT_FILTER_IMPORTABLE = "Da importare ({n})"
IMPORT_FILTER_DUPLICATE = "Già in archivio ({n})"
IMPORT_FILTER_NEEDS_ENV = "Da assegnare ({n})"
IMPORT_FILTER_CONFLICT = "In conflitto ({n})"
IMPORT_FILTER_IGNORED = "Ignorati ({n})"

IMPORT_COL_PATH = "Percorso"
IMPORT_COL_ENV = "Ambiente"
IMPORT_COL_DAY = "Giorno"
IMPORT_COL_SIZE = "Dimensione"
IMPORT_COL_STATUS = "Stato"
IMPORT_STATUS_IMPORTABLE = "da importare"
IMPORT_STATUS_DUPLICATE = "già in archivio"
IMPORT_STATUS_NEEDS_ENV = "da assegnare"
IMPORT_STATUS_CONFLICT = "in conflitto"
IMPORT_STATUS_IGNORED = "ignorato"
#: {status} = one IMPORT_STATUS_*; {reason} = the archive's reason.
IMPORT_STATUS_CELL = "{status}: {reason}"
IMPORT_NO_ENV = "—"

IMPORT_FOLDERS_TITLE = "Di che ambiente sono questi log?"
IMPORT_FOLDERS_HINT = ("Il percorso non lo dice. La scelta vale per la cartella e viene "
                       "ricordata; finché non scegli, questi log non vengono importati.")
#: {folder} = folder relative to the scanned one; {n} = files in it.
IMPORT_FOLDER_ROW = "{folder} · {n} log"
IMPORT_FOLDER_ROOT = "(la cartella scelta)"
IMPORT_FOLDER_PICK = "Scegli…"
IMPORT_FOLDER_IGNORE = "Ignora"

#: {n} = files to copy; {dup} = already in the archive.
IMPORT_PLAN = "Da copiare: {n} log · già in archivio: {dup}"
IMPORT_PLAN_NOTHING = "Niente da copiare: i log sono già in archivio, in conflitto o da assegnare."
#: {n} = files still waiting for an environment.
IMPORT_PLAN_WAITING = " · in attesa di un ambiente: {n} (per ora saltati)"
IMPORT_BTN_START = "Importa"
IMPORT_BTN_CLOSE = "Chiudi"
IMPORT_BTN_STOP = "Interrompi"
#: {path} = the next queued folder.
IMPORT_BTN_NEXT = "Avanti: {path}"

IMPORT_COPYING = "Copia e verifica in corso…"
#: {done}/{total} files; {path} = the one being copied.
IMPORT_PROGRESS = "{done} di {total} · {path}"
IMPORT_STOPPING = "Interruzione in corso…"
#: {error} = the core's message (a sync holds the lock, ...).
IMPORT_FAILED = "Importazione non riuscita: {error}"

#: The result line.
IMPORT_RESULT = "Copiati {copied} · già presenti {skipped} · conflitti {conflicts} · errori {errors}"
IMPORT_RESULT_CANCELLED = "Importazione interrotta: i file copiati finora sono verificati e restano."
IMPORT_RESULT_CONFLICTS = ("I file in conflitto restano dove sono: il loro contenuto è diverso "
                           "da quello in archivio e va confrontato a mano.")
#: {path} = the file; {reason} = why it failed.
IMPORT_ERROR_LINE = "{path}: {reason}"
IMPORT_INDEXING = "Aggiornamento dell'indice avviato."
IMPORT_INDEX_BUSY = "L'indice verrà aggiornato al termine dell'operazione in corso."

IMPORT_DELETE_QUESTION = "Vuoi cancellare gli originali?"
#: {n} files, {size} total (format_size).
IMPORT_DELETE_DETAIL = "{n} file, {size}. Andranno nel Cestino."
IMPORT_DELETE_DETAIL_ONE = "1 file, {size}. Andrà nel Cestino."
IMPORT_BTN_DELETE = "Cancella originali"
IMPORT_BTN_KEEP = "Tienili"
IMPORT_DELETING = "Spostamento nel Cestino in corso…"
#: {n} = originals now in the Recycle Bin.
IMPORT_DELETED = "{n} originali spostati nel Cestino."
#: {n} = originals that were NOT deleted.
IMPORT_DELETE_REFUSED = "{n} originali non cancellati:"
IMPORT_KEPT = "Gli originali restano dove sono."

# -- the wizard, page 1 ----------------------------------------------------------
#: {n} = logs outside the structure in the chosen folder.
WIZARD_IMPORT_FOUND = "Trovati {n} log da importare: li importerò alla fine"
WIZARD_IMPORT_FOUND_ONE = "Trovato 1 log da importare: lo importerò alla fine"
WIZARD_IMPORT_ELSEWHERE = "Hai già dei log altrove?"
WIZARD_IMPORT_PICK = "Scegli cartella…"
WIZARD_IMPORT_PICK_CAPTION = "Cartella con i log da importare"
#: {path} = the extra folder; {n} = logs found in it.
WIZARD_IMPORT_EXTRA = "{path}: {n} log da importare alla fine"
WIZARD_IMPORT_EXTRA_NONE = "{path}: nessun log da importare"
WIZARD_IMPORT_EXTRA_REMOVE = "Non importare"
