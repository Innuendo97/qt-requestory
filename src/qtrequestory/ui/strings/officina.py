"""Strings of the Officina tab.

Owned by: Officina phase 1 — Task 6 (document viewer) started it; Task 7 (the
page, board and workbench) adds its own below. Only ``UPPER_CASE`` string
constants, prefixed ``OFFICINA_``.
"""

# -- document viewer (ui/pages/officina_viewer.py) -----------------------------

#: {n} = page number (1-based), shown on a page not rendered yet.
OFFICINA_VIEWER_PAGE = "Pagina {n}"
#: {n} = page number (1-based), {reason} = why the page could not be drawn.
OFFICINA_VIEWER_PAGE_ERROR = "Impossibile mostrare la pagina {n}: {reason}"

# -- navigation and operation names (main_window, quit_dialog) ------------------

OFFICINA_NAV = "Officina"
OFFICINA_JOB_GENERATE = "Generazione dell'Officina"
OFFICINA_JOB_COMPARE = "Confronto dell'Officina"
OFFICINA_JOB_SUMMARY = "Confronto dei casi dell'iniziativa"
OFFICINA_JOB_DELIVERY = "Consegna dell'Officina"
OFFICINA_DELIVERY_QUIT_INFO = ("La consegna si ferma: i file già copiati restano, nessun file "
                               "resta scritto a metà.")
OFFICINA_QUIT_INFO = ("I casi non ancora inviati vengono annullati; un documento già in arrivo "
                      "potrebbe non essere salvato.")

# -- folder chooser (the empty state) -------------------------------------------

OFFICINA_ROOT_TITLE = "Scegli la cartella dell'Officina"
OFFICINA_ROOT_TEXT = ("Iniziative, casi, payload e documenti generati stanno in una cartella "
                      "locale scelta da te. I payload contengono dati reali dei clienti: "
                      "scegli una cartella sul tuo PC, fuori da ogni repository.")
OFFICINA_ROOT_BUTTON = "Scegli cartella…"
#: {path} = the chosen folder.
OFFICINA_ROOT_ONEDRIVE = ("La cartella dell'Officina è in OneDrive ({path}): payload e documenti "
                          "con dati reali vengono copiati nel cloud. È ammesso, ma una cartella "
                          "locale è più sicura.")
#: {path} = the chosen folder; {reason} = the system's message.
OFFICINA_ROOT_FAILED = "Impossibile usare la cartella {path}: {reason}"

# -- initiatives list -------------------------------------------------------------

OFFICINA_LIST_TITLE = "Iniziative"
OFFICINA_NEW_INITIATIVE = "Nuova iniziativa"
OFFICINA_OPEN_INITIATIVE = "Apri"
OFFICINA_OPEN_FOLDER = "Apri cartella"
OFFICINA_CHANGE_ROOT = "Cambia cartella…"
#: {path} = the Officina folder.
OFFICINA_ROOT_LABEL = "Cartella: {path}"
OFFICINA_COL_INITIATIVE = "Iniziativa"
OFFICINA_COL_CASES = "Casi"
OFFICINA_COL_ACCEPTED = "Accettati"
OFFICINA_COL_ACTIVITY = "Ultima attività"
#: {accepted} of {total} cases accepted (the list's column).
OFFICINA_ACCEPTED_OF = "{accepted} su {total}"
#: {accepted} of {total} cases accepted (the board's title pill).
OFFICINA_ACCEPTED_PILL = "{accepted} su {total} accettati"
OFFICINA_LIST_EMPTY = ("Nessuna iniziativa. Creane una con «Nuova iniziativa»: raccoglie i "
                       "casi da consegnare insieme.")
OFFICINA_NEW_INITIATIVE_LABEL = "Nome dell'iniziativa:"
#: {reason} = why the initiative could not be created.
OFFICINA_NEW_INITIATIVE_FAILED = "Iniziativa non creata: {reason}"
#: {name} = the initiative's name.
OFFICINA_INITIATIVE_EXISTS = "esiste già un'iniziativa «{name}»"
#: {name} = the initiative's name.
OFFICINA_INITIATIVE_GONE = "L'iniziativa «{name}» non è più nella cartella dell'Officina."
#: Two initiatives share a display name: {name} = the name, {folder} = its folder.
OFFICINA_INITIATIVE_LABEL = "{name} ({folder})"
#: {reason} = the load error ("iniziativa.json non è leggibile: ...").
OFFICINA_INITIATIVE_BROKEN = ("{reason}. Gli header predefiniti dell'iniziativa non sono noti: "
                              "nessuna generazione finché il file non viene corretto o ripristinato.")

# -- relative times -----------------------------------------------------------------

#: {time} = HH:MM.
OFFICINA_TODAY = "oggi {time}"
#: {time} = HH:MM.
OFFICINA_YESTERDAY = "ieri {time}"
#: {date} = dd/MM/yyyy, {time} = HH:MM.
OFFICINA_ON_DAY = "{date} {time}"
OFFICINA_NONE = "—"

# -- initiative board -----------------------------------------------------------------

OFFICINA_BACK_TO_LIST = "‹ Iniziative"
OFFICINA_ADD_FROM_SEARCH = "+ Caso da ricerca"
OFFICINA_ADD_FROM_FILE = "+ Caso da file…"
OFFICINA_GENERATE_MISSING_ASIS = "Genera AS-IS mancanti"
OFFICINA_REGENERATE_SELECTED = "Rigenera TO-BE selezionati"
OFFICINA_DELIVER = "Consegna…"
OFFICINA_DELIVER_TIP = "Copia i documenti dei casi scelti nella cartella dei tester."
OFFICINA_COL_CASE = "Caso"
OFFICINA_COL_DOCUMENTS = "Documenti"
OFFICINA_COL_TOBE_VS_TARGET = "TO-BE contro target"
OFFICINA_COL_LAST_RUN = "Ultima generazione"
OFFICINA_COL_STATUS = "Stato"
OFFICINA_BOARD_EMPTY = ("Nessun caso. Aggiungine uno da Ricerca (tasto destro su una chiamata › "
                        "«Aggiungi all'Officina…») oppure da un file JSON.")
OFFICINA_SEARCH_HINT = ("Cerca la chiamata, poi tasto destro sulla riga › «Aggiungi "
                        "all'Officina…».")
OFFICINA_THUMB_TARGET = "T"
OFFICINA_THUMB_ASIS = "A"
#: {n} = TO-BE version number.
OFFICINA_THUMB_TOBE = "v{n}"
#: {name} = the target's original file name.
OFFICINA_THUMB_TARGET_TIP = "TARGET: {name}"
OFFICINA_THUMB_ASIS_TIP = "AS-IS"
#: {n} = TO-BE version number.
OFFICINA_THUMB_TOBE_TIP = "TO-BE v{n}"
OFFICINA_THUMB_MISSING_TIP = "Il file non c'è più nella cartella del caso."
OFFICINA_PILL_EQUAL = "uguale"
#: {n} = number of text differences (2 or more).
OFFICINA_PILL_DIFFS = "{n} differenze"
OFFICINA_PILL_ONE_DIFF = "1 differenza"
OFFICINA_PILL_NO_TEXT = "senza testo"
OFFICINA_PILL_ERROR = "confronto non riuscito"
OFFICINA_PILL_PENDING = "confronto…"
OFFICINA_PILL_NO_TARGET = "manca il target"
OFFICINA_PILL_NO_TOBE = "manca il TO-BE"
OFFICINA_STATUS_OPEN = "aperto"
OFFICINA_STATUS_ACCEPTED = "accettato"
OFFICINA_STATUS_BROKEN = "caso.json illeggibile"
OFFICINA_STATUS_REOPENED = "da ricontrollare"
#: {when} = relative time, {env} = generator name.
OFFICINA_LAST_RUN = "{when} · {env}"
#: {when} = relative time of the AS-IS.
OFFICINA_LAST_RUN_ASIS = "AS-IS {when}"
OFFICINA_RUN_QUEUED = "in coda…"
#: {env} = the generator the case is sent to (board row and workbench).
OFFICINA_GENERATING_ON = "Generazione su {env}…"
#: {done} of {total} cases generated.
OFFICINA_BATCH_PROGRESS = "Generazione: {done} di {total}"
OFFICINA_BATCH_CANCEL = "Annulla generazioni"
OFFICINA_NOTHING_SELECTED = "Seleziona almeno un caso nella tabella."
OFFICINA_NO_MISSING_ASIS = "Tutti i casi hanno già l'AS-IS."
#: {ok} generated, {failed} not.
OFFICINA_BATCH_DONE = "Generazione finita: {ok} riuscite, {failed} non riuscite."

# -- adding a case (from Ricerca or from a file) --------------------------------------

OFFICINA_ADD_MENU = "Aggiungi all'Officina…"
OFFICINA_ADD_TITLE = "Aggiungi all'Officina"
OFFICINA_ADD_INITIATIVE = "Iniziativa:"
OFFICINA_ADD_NEW_INITIATIVE = "Nuova iniziativa…"
OFFICINA_ADD_NEW_NAME = "Nome della nuova iniziativa:"
OFFICINA_ADD_FILE = "File JSON:"
OFFICINA_ADD_KEY = "Template key:"
OFFICINA_ADD_VARIANT = "Variante:"
OFFICINA_ADD_VARIANT_HINT = "facoltativa, es. abilitato: serve quando più casi hanno la stessa key"
OFFICINA_ADD_BUTTON = "Aggiungi"
OFFICINA_ADD_PICK_FILE = "Scegli il payload JSON"
OFFICINA_JSON_FILTER = "JSON (*.json *.txt);;Tutti i file (*)"
OFFICINA_ADD_NO_ROOT = ("La cartella dell'Officina non è ancora scelta: apri la scheda Officina "
                        "e sceglila.")
OFFICINA_ADD_NEED_NAME = "Indica il nome della nuova iniziativa."
OFFICINA_ADD_NEED_FILE = "Scegli il file JSON del payload."
OFFICINA_ADD_NEED_KEY = "Indica la template key."
#: {key} = template key, {initiative} = initiative name.
OFFICINA_ADDED = "Caso {key} aggiunto a «{initiative}»."
#: {reason} = why the case was not created.
OFFICINA_ADD_FAILED = "Caso non aggiunto: {reason}"
OFFICINA_ADD_DUPLICATE = ("in questa iniziativa c'è già un caso con la stessa key e variante: "
                          "indica una variante diversa")

# -- case workbench -------------------------------------------------------------------

#: {initiative} = initiative name.
OFFICINA_BACK_TO_BOARD = "‹ {initiative}"
OFFICINA_REGENERATE_TOBE = "Rigenera TO-BE (F5)"
OFFICINA_GENERATE_ASIS = "Genera AS-IS"
OFFICINA_REGENERATE_ASIS = "Rigenera AS-IS…"
OFFICINA_CHOOSE_TARGET = "Target…"
OFFICINA_PAYLOAD_HEADERS = "Payload e header…"
OFFICINA_MARK_ACCEPTED = "Segna accettato"
OFFICINA_REOPEN = "Riapri"
#: {env} = the case's generator (the workbench header).
OFFICINA_CASE_ENV = "Generatore: {env}"
OFFICINA_CASE_NO_ENV = "nessuno"
OFFICINA_SIDE_TARGET = "TARGET"
OFFICINA_VERSION_ASIS = "AS-IS"
#: {n} = TO-BE version number.
OFFICINA_VERSION_TOBE = "v{n}"
#: {env} = generator, {when} = relative time.
OFFICINA_VERSION_INFO = "{env} · {when}"
OFFICINA_NO_TARGET = "Nessun target. Usa «Target…» per scegliere il file del cliente (PDF o HTML)."
OFFICINA_NO_VERSION = ("Nessun documento generato: «Genera AS-IS» per il documento di oggi, "
                       "«Rigenera TO-BE (F5)» dopo ogni pubblicazione.")
OFFICINA_LOADING = "Preparazione dei documenti…"
OFFICINA_DIFF_TITLE = "Differenze con il target"
OFFICINA_DIFF_EQUAL = "Nessuna differenza di testo: uguale al target."
OFFICINA_DIFF_NEED_BOTH = ("Il confronto compare quando ci sono sia il target sia un documento "
                           "generato.")
#: {n} = number of differences (2 or more).
OFFICINA_DIFF_COUNT = "{n} differenze di testo"
OFFICINA_DIFF_COUNT_ONE = "1 differenza di testo"
#: {reason} = the CompareError message.
OFFICINA_DIFF_ERROR = "Confronto non riuscito: {reason}"
OFFICINA_KIND_ADDED = "in più"
OFFICINA_KIND_REMOVED = "mancante"
OFFICINA_KIND_CHANGED = "cambiato"
#: {page} = 1-based page, {kind} = OFFICINA_KIND_*.
OFFICINA_DIFF_WHERE = "pag. {page} · {kind}"
#: {left} = target text, {right} = compared text.
OFFICINA_DIFF_CHANGE = "«{left}» → «{right}»"
#: {text} = the text that is only in the target.
OFFICINA_DIFF_ONLY_LEFT = "nel target: «{text}»"
#: {text} = the text that is only in the generated document.
OFFICINA_DIFF_ONLY_RIGHT = "non nel target: «{text}»"
#: {status} = " (HTTP 500)" or "", {reason} = the masked reason.
OFFICINA_GENERATION_FAILED = "Generazione non riuscita{status}: {reason}"
#: {status} = the HTTP status code.
OFFICINA_HTTP_STATUS = " (HTTP {status})"
#: The reason shown when a generation stopped without an answer of its own.
OFFICINA_GENERATION_INTERRUPTED = "errore imprevisto durante la generazione"
OFFICINA_RUN_CANCELLED = "annullata prima dell'invio"
#: {cases} = the case ids, comma separated.
OFFICINA_ALREADY_QUEUED = "Già in coda o in generazione, non aggiunti di nuovo: {cases}"
#: {reason} = why the configuration could not be saved.
OFFICINA_ROOT_SAVE_FAILED = "La cartella non è stata salvata nella configurazione: {reason}"
OFFICINA_ASIS_NOTE_TITLE = "Rigenera AS-IS"
OFFICINA_ASIS_NOTE_LABEL = ("L'AS-IS è la base del confronto. Quello attuale resta conservato, "
                            "ma serve una nota che spieghi perché lo sostituisci:")
OFFICINA_ASIS_NOTE_REQUIRED = "AS-IS non rigenerato: serve una nota che spieghi il motivo."
OFFICINA_TARGET_TITLE = "Scegli il target (il file del cliente)"
OFFICINA_TARGET_FILTER = "Documenti (*.pdf *.html *.htm);;Tutti i file (*)"
#: {reason} = why the target could not be copied.
OFFICINA_TARGET_FAILED = "Target non salvato: {reason}"
#: {name} = file name.
OFFICINA_TARGET_SET = "Target impostato: {name}"
OFFICINA_ACCEPT_WITH_DIFFS = ("Il documento mostrato ha ancora differenze di testo con il target. "
                              "Segnare il caso accettato lo stesso?")
OFFICINA_ACCEPTED = "Caso segnato accettato."
OFFICINA_REOPENED = "Caso riaperto."
#: {reason} = the load error of a damaged caso.json.
OFFICINA_CASE_BROKEN = ("caso.json non è leggibile ({reason}): il caso è mostrato con i valori "
                        "predefiniti e non si può modificare, accettare né generare finché il file "
                        "non viene corretto o ripristinato.")
OFFICINA_CASE_REOPENED = "Nuova versione dopo l'accettazione: da ricontrollare."
OFFICINA_CASE_STALE = "Il TO-BE più recente non è quello accettato: da ricontrollare."

# -- payload and header editor -----------------------------------------------------------

OFFICINA_EDITOR_TITLE = "Payload e header"
OFFICINA_EDITOR_PAYLOAD_TAB = "Payload"
OFFICINA_EDITOR_HEADERS_TAB = "Header e invio"
OFFICINA_EDITOR_FORMAT = "Formatta"
OFFICINA_EDITOR_JSON_OK = "JSON valido."
#: {line}, {column}, {message} of the JSON error.
OFFICINA_EDITOR_JSON_ERROR = "JSON non valido (riga {line}, colonna {column}): {message}"
OFFICINA_EDITOR_JSON_NOT_OBJECT = "Il payload deve essere un oggetto JSON, tra parentesi graffe."
OFFICINA_EDITOR_HEADER_NAME = "Header"
OFFICINA_EDITOR_HEADER_VALUE = "Valore"
OFFICINA_EDITOR_ADD_HEADER = "Aggiungi header"
OFFICINA_EDITOR_REMOVE_HEADER = "Rimuovi"
OFFICINA_EDITOR_HEADERS_HINT = (
    "Automatici: template_key, current_timestamp, correlation_id e Postman-Token. Dal profilo "
    "di Impostazioni: service_number, office_id, branch_id. Poi i predefiniti dell'iniziativa. "
    "Una riga qui prevale su tutti; un valore vuoto non viene inviato.")
OFFICINA_EDITOR_ENV = "Generatore:"
OFFICINA_EDITOR_CORRELATION = "correlation_id:"
OFFICINA_EDITOR_CORRELATION_NEW = "nuovo a ogni invio"
OFFICINA_EDITOR_CORRELATION_SOURCE = "FDI della chiamata di origine"
OFFICINA_EDITOR_CORRELATION_FIXED = "valore fisso"
OFFICINA_EDITOR_LINKS = "Link di upload:"
OFFICINA_EDITOR_LINKS_REMOVE = "Rimuovi (consigliato)"
OFFICINA_EDITOR_LINKS_KEEP = "Lascia solo se tutti scaduti"
OFFICINA_EDITOR_DROP_TOKEN = "Non inviare Postman-Token (la chiamata finirà nei log nginx)"
OFFICINA_EDITOR_FIXED_EMPTY = "Indica il valore fisso di correlation_id."
OFFICINA_EDITOR_SAVED = "Payload e header salvati."
#: {reason} = why saving failed.
OFFICINA_EDITOR_SAVE_FAILED = "Salvataggio non riuscito: {reason}"

# -- delivery to the testers (ui/pages/officina_delivery.py) ------------------------------

#: {initiative} = initiative name.
OFFICINA_DELIVERY_TITLE = "Consegna ai tester — {initiative}"
OFFICINA_DELIVERY_CASES = "Casi da consegnare"
OFFICINA_DELIVERY_CASE_ACCEPTED = "accettato"
OFFICINA_DELIVERY_CASE_OPEN = "non accettato"
OFFICINA_DELIVERY_CASE_STALE = "accettato su un TO-BE precedente"
#: {cases} = the keys of the chosen cases whose latest TO-BE is not the accepted one.
OFFICINA_DELIVERY_STALE = "Il TO-BE più recente non è quello accettato: {cases}."
#: {n} = how many non-accepted cases are chosen, {cases} = their keys.
OFFICINA_DELIVERY_NOT_ACCEPTED = ("Stai consegnando {n} casi non ancora accettati: {cases}. "
                                  "I tester li riceveranno come gli altri.")
#: {cases} = the key of the one non-accepted case chosen.
OFFICINA_DELIVERY_NOT_ACCEPTED_ONE = ("Stai consegnando un caso non ancora accettato: {cases}. "
                                      "I tester lo riceveranno come gli altri.")
OFFICINA_DELIVERY_DESTINATION = "Cartella di destinazione:"
OFFICINA_DELIVERY_DESTINATION_HINT = "la cartella condivisa con i tester (anche OneDrive o SharePoint)"
OFFICINA_DELIVERY_PICK = "Scegli la cartella di consegna"
OFFICINA_DELIVERY_ZIP = "Crea anche lo zip"
OFFICINA_DELIVERY_PREVIEW = "Anteprima"
OFFICINA_DELIVERY_NO_DESTINATION = "‹cartella di destinazione›"
OFFICINA_DELIVERY_MISSING_ASIS = "manca l'AS-IS"
OFFICINA_DELIVERY_MISSING_TOBE = "manca il TO-BE"
OFFICINA_DELIVERY_MISSING_TARGET = "manca il target"
#: {what} = one of the MISSING strings: the file was deleted from disk.
OFFICINA_DELIVERY_GONE = "{what} (file non più su disco)"
#: {what} = one of the MISSING strings: the metadata points outside the case.
OFFICINA_DELIVERY_OUTSIDE = "{what} (il file indicato è fuori dalla cartella del caso)"
#: {what} = one of the MISSING strings: the *.meta.json was edited into something unusable.
OFFICINA_DELIVERY_BROKEN = "{what} (i metadati del file non sono validi)"
#: {reason} = why iniziativa.json was not updated.
OFFICINA_DELIVERY_NOT_REMEMBERED = "La destinazione non è stata ricordata per la prossima volta: {reason}"
OFFICINA_DELIVERY_NOTHING = "Nessun documento da consegnare per i casi scelti."
OFFICINA_DELIVERY_START = "Consegna"
OFFICINA_DELIVERY_CHECKING = "Controllo dei file già presenti nella destinazione…"
OFFICINA_DELIVERY_COPYING = "Copia dei documenti in corso…"
OFFICINA_DELIVERY_STOP = "Interrompi"
OFFICINA_CONFLICT_TITLE = "File già presente"
#: {name} = the existing file (relative to the destination).
OFFICINA_CONFLICT_TEXT = "Nella destinazione c'è già «{name}»."
OFFICINA_CONFLICT_REPLACE = "Sostituisci"
OFFICINA_CONFLICT_KEEP_BOTH = "Mantieni entrambi"
OFFICINA_CONFLICT_SKIP = "Salta"
#: {n} = how many existing files are still to be decided, this one included.
OFFICINA_CONFLICT_APPLY_ALL = "Applica a tutti ({n})"
OFFICINA_DELIVERY_DONE_TITLE = "Consegna completata"
OFFICINA_DELIVERY_PARTIAL_TITLE = "Consegna incompleta"
OFFICINA_DELIVERY_CANCELLED_TITLE = "Consegna interrotta"
#: {n} = files written, {folder} = the delivery folder.
OFFICINA_DELIVERY_DELIVERED = "{n} file consegnati in {folder}"
#: {path} = the zip written.
OFFICINA_DELIVERY_ZIP_DONE = "Zip: {path}"
OFFICINA_DELIVERY_ZIP_NOT_MADE = "Lo zip non è stato creato: la consegna non è completa."
#: {n} = files left as they were (the user chose "Salta").
OFFICINA_DELIVERY_SKIPPED = "Lasciati com'erano ({n}):"
#: {n} = files written under another name (a file with the planned name was
#: already there: "Mantieni entrambi", or one that appeared during the copy).
OFFICINA_DELIVERY_RENAMED = "Salvati con un altro nome perché il nome era già usato ({n}):"
#: {planned} = the planned relative path, {name} = the name actually written.
OFFICINA_DELIVERY_RENAMED_ENTRY = "{planned} → {name}"
#: {n} = files not put in the zip (symbolic links are never read).
OFFICINA_DELIVERY_ZIP_LEFT_OUT = "Non messi nello zip perché collegamenti simbolici ({n}):"
#: {n} = slots not delivered.
OFFICINA_DELIVERY_MISSING = "Non consegnati perché mancanti ({n}):"
#: {n} = files that failed.
OFFICINA_DELIVERY_FAILED = "Non riusciti ({n}), da rifare:"
OFFICINA_DELIVERY_CANCELLED = "Interrotta prima della fine: i file già copiati restano."
#: {reason} = an unexpected error.
OFFICINA_DELIVERY_ERROR = "Consegna non riuscita: {reason}"
