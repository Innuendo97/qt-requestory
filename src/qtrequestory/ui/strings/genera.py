"""Genera: the tab that generates documents from template keys, the Quadient
list or whole FDIs (``ui/pages/genera_*.py``; spec "Genera").

The outcome words here are the tab's own; ``esito.csv`` has its own fixed
vocabulary (``officina.batch.output``). Header VALUES never appear in these
strings: the header table is the only place they are shown. An HTML answer is
an e-mail to the owner: the tab says "email (HTML)".
"""

GENERA_NAV = "Genera"
GENERA_TITLE = "Genera documenti"

# -- what to generate ------------------------------------------------------------
GENERA_WHAT = "Cosa generare"
GENERA_MODE_KEYS = "Template key"
GENERA_MODE_ELENCO = "Elenco"
GENERA_MODE_FDI = "FDI"
GENERA_KEYS_PLACEHOLDER = ("Una o più template key, separate da spazi, virgole o a capo.\n"
                           "Esempio: MOD_ESEMPIO_LUCE, MOD_ESEMPIO_GAS")
#: Under the keys field. {n} = distinct template keys typed.
GENERA_KEYS_COUNT = "{n} template key"
#: Where the keys typed by hand are written. {folder} = the no-package folder name.
GENERA_KEYS_FOLDER_NONE = "cartella {folder}"
#: The same with a list loaded. {file} = the list's file name.
GENERA_KEYS_FOLDER_ELENCO = "cartelle: i package di {file}"
GENERA_FDI_PLACEHOLDER = ("Un FDI intero per riga, come nei log (non solo l'inizio).\n"
                          "Di ogni FDI si generano tutte le sue template key, dalla chiamata più recente.")
#: Under the FDI field. {n} = distinct FDIs typed.
GENERA_FDI_COUNT = "{n} FDI · una cartella per FDI"

# -- the list (elenco) -------------------------------------------------------------
GENERA_ELENCO_NONE = "Nessun elenco scelto"
GENERA_ELENCO_PICK = "Scegli l'elenco delle template key"
#: The file dialog's filters (Qt syntax).
GENERA_ELENCO_FILTERS = "Elenco CSV (*.csv);;Tutti i file (*)"
GENERA_ELENCO_EMPTY_TITLE = "Carica l'elenco di Quadient"
GENERA_ELENCO_EMPTY_HINT = ("Un file CSV con le colonne «Template key» e «package name», separate da "
                            "punto e virgola. Ogni package diventa una cartella.")
GENERA_ELENCO_FILTER = "Filtra i package"
GENERA_ELENCO_ALL = "Tutti"
GENERA_ELENCO_NO_PACKAGES = "Nessuno"
GENERA_ELENCO_ALL_TIP = "Sceglie tutti i package mostrati (il filtro conta)"
GENERA_ELENCO_NONE_TIP = "Toglie la scelta ai package mostrati (il filtro conta)"
#: A package in the list, as read by a screen reader / a test. {package} = its
#: name, {n} = its distinct template keys.
GENERA_ELENCO_ROW = "{package}  ({n})"
#: The key count drawn at the right of a package row. {n} = its distinct template keys.
GENERA_ELENCO_ROW_KEYS = "{n} key"
GENERA_ELENCO_ROW_TIP = "Clic o Spazio per sceglierlo"
#: {chosen} = packages ticked, {total} = packages in the list, {keys} = their distinct keys.
GENERA_ELENCO_SUMMARY = "{chosen} package scelti su {total} · {keys} template key"
#: Rows of the file without a template key. {n} = how many (more than one).
GENERA_ELENCO_SKIPPED = "{n} righe senza template key scartate"
GENERA_ELENCO_SKIPPED_ONE = "1 riga senza template key scartata"
#: A list that could not be read for an unforeseen reason (the details are in the app's log).
GENERA_ELENCO_UNREADABLE = "Impossibile leggere l'elenco: i dettagli sono nel registro dell'app."

# -- where -------------------------------------------------------------------------
GENERA_WHERE = "Dove"
GENERA_GENERATOR = "Genera su"
GENERA_GENERATOR_TIP = "Il generatore di documenti a cui vanno le chiamate (Impostazioni › Officina)"
GENERA_SOURCE = "Chiamate dai log di"
GENERA_SOURCE_TIP = ("I payload si prendono dai log di questo ambiente: di solito lo stesso del "
                     "generatore, che segue finché non lo cambi")
#: Under the two combos when the logs are not the generator's. {source} = logs, {env} = generator.
GENERA_SOURCE_OTHER = "I payload vengono dai log di {source} e vanno al generatore {env}."
#: The same when there are no logs named like the generator. {env} = generator.
GENERA_SOURCE_NO_LOGS = "Non ci sono log di {env}: i payload vengono da un altro ambiente."
#: One click back to the generator's own logs. {env} = generator.
GENERA_SOURCE_FOLLOW = "Usa i log di {env}"
GENERA_DESTINATION = "Salva in"
GENERA_DESTINATION_NONE = "Nessuna cartella scelta"
GENERA_DESTINATION_PICK = "Scegli dove salvare i documenti"
GENERA_DESTINATION_HINT = "Ogni generazione crea qui una cartella sua, per esempio svil_20261110-143005."

# -- headers -----------------------------------------------------------------------
GENERA_HEADERS = "Header"
#: The collapsed section. {n} = rows that will be sent.
GENERA_HEADERS_SENT = "{n} inviati"
#: Kept for the presenter's one-line summary. {n} as above.
GENERA_HEADERS_SUMMARY = "Header · {n} inviati"
#: The same when the table differs from Impostazioni. {n} as above, {m} = changed rows (more than one).
GENERA_HEADERS_SUMMARY_MODIFIED = "Header · {n} inviati · {m} modificati"
#: {n} as above, exactly one changed row.
GENERA_HEADERS_SUMMARY_MODIFIED_ONE = "Header · {n} inviati · 1 modificato"
#: The pill of the collapsed section. {m} = changed rows (more than one).
GENERA_HEADERS_MODIFIED = "{m} modificati"
GENERA_HEADERS_MODIFIED_ONE = "1 modificato"
GENERA_HEADERS_MODIFIED_TIP = ("Diversi da Impostazioni › Officina: valgono per questa sessione, anche per "
                               "«Genera documento» in Ricerca")
#: Over the button while the Header step is scrolled out of view. {modified} = the pill's text.
GENERA_HEADERS_REMINDER = "Header: {modified}"
GENERA_HEADERS_SHOW = "Mostra"
GENERA_HEADERS_SHOW_TIP = "Apre la tabella degli header"
GENERA_HEADERS_TIP = "La tabella completa di ciò che viene inviato"
GENERA_HEADERS_HINT = ("Un header automatico lasciato vuoto viene calcolato a ogni chiamata; una riga "
                       "rimossa non viene inviata. Le modifiche valgono finché l'app resta aperta, anche "
                       "per «Genera documento» in Ricerca.")
#: The empty value of an automatic header, shown in the table.
GENERA_HEADER_AUTOMATIC = "automatico"
GENERA_HEADERS_RESET = "Ripristina"
GENERA_HEADERS_RESET_TIP = "Torna al «Profilo intestazioni» di Impostazioni › Officina"

# -- options and the button ----------------------------------------------------------
GENERA_ZIP = "Crea anche gli zip"
GENERA_ZIP_TIP = "Uno zip per cartella, accanto alla cartella (che resta)"
GENERA_HTML = "Salva anche le email (HTML)"
GENERA_HTML_TIP = ("Spento: una template key che risponde con un'email (HTML) non viene salvata, e alle "
                   "generazioni successive non viene più chiamata. Acceso: si chiamano tutte.")
GENERA_START = "Genera"
#: {n} = documents to generate (more than one).
GENERA_START_N = "Genera {n} documenti"
GENERA_START_ONE = "Genera 1 documento"
#: {n} = FDIs (more than one): their documents are known only once looked up.
GENERA_START_FDI = "Genera i documenti di {n} FDI"
GENERA_START_FDI_ONE = "Genera i documenti di 1 FDI"
GENERA_START_TIP = "Ctrl+Invio"
GENERA_STOP = "Interrompi"
GENERA_STOP_TIP = "Le chiamate già partite finiscono e vengono salvate; le altre vengono annullate"
#: While the calls are looked up in the logs. {env} = the "Chiamate dai log di" environment.
GENERA_LOOKING_UP = "Cerco le chiamate nei log di {env}…"
#: While the calls go. {env} = the generator.
GENERA_SENDING = "Genero su {env}…"
#: {done} of {total} calls finished.
GENERA_PROGRESS = "{done} di {total}"
GENERA_STOPPING = "Interrompo: aspetto le chiamate già partite…"

# -- what stops the button (one line under it, the first one) --------------------------
GENERA_NEED_KEYS = "Scrivi almeno una template key."
GENERA_NEED_ELENCO = "Scegli il file dell'elenco."
GENERA_NEED_PACKAGE = "Scegli almeno un package dell'elenco."
GENERA_NEED_FDI = "Scrivi almeno un FDI."
GENERA_NEED_GENERATOR = "Nessun generatore di documenti attivo: attivane uno in Impostazioni › Officina."
GENERA_NEED_SOURCE = "Nessun ambiente dei log è abilitato: aggiungine uno in Impostazioni › Ambienti."
GENERA_NEED_DESTINATION = "Scegli la cartella in cui salvare i documenti."
#: {problem} = the first problem of the header table (the core's wording).
GENERA_HEADER_PROBLEM = "Header: {problem}."

# -- confirmation over the threshold ---------------------------------------------------
#: {n} = documents.
GENERA_CONFIRM_TITLE = "Generare {n} documenti?"
#: {n} = calls, {env} = generator, {source} = environment of the logs.
GENERA_CONFIRM_TEXT = "Partono {n} chiamate verso {env}, con i payload dei log di {source}."
#: With FDIs: their calls were looked up first. {n} = calls, {fdis} = FDIs, {env}, {source} as above.
GENERA_CONFIRM_TEXT_FDI = "Partono {n} chiamate ({fdis} FDI) verso {env}, con i payload dei log di {source}."

# -- how a run ended ---------------------------------------------------------------------
#: The run was refused before anything was sent. {reason} = Italian, from the core.
GENERA_REFUSED = "Generazione non partita: {reason}"
GENERA_CRASHED = "Generazione interrotta da un problema imprevisto: i dettagli sono nel registro dell'app."
GENERA_ALREADY_RUNNING = "Una generazione è già in corso."
#: "Apri cartella" on a run folder that is not there. {name} = its folder name.
GENERA_FOLDER_MISSING = "La cartella {name} non c'è: nessun documento è stato salvato, o è stata spostata."
#: A saved document that could not be opened. {name} = its file name.
GENERA_OPEN_FAILED = "Impossibile aprire {name}: è stato spostato, o nessun programma lo apre."

# -- the results -------------------------------------------------------------------------
GENERA_RESULTS = "Esiti"
GENERA_COL_KEY = "Template key"
GENERA_COL_FOLDER = "Cartella"
GENERA_COL_STATUS = "Esito"
GENERA_COL_TYPE = "Tipo"
GENERA_COL_DURATION = "Durata"
GENERA_COL_REASON = "Motivo"
GENERA_RESULTS_EMPTY_TITLE = "Gli esiti compaiono qui, una riga per documento"
#: Before the first run, when nothing can start yet.
GENERA_PLAN_NOT_READY = "Scegli cosa generare e dove, poi premi Genera (Ctrl+Invio)."
#: Before the first run, ready. {what} = the button's words, {env} = generator, {source} = logs.
GENERA_PLAN_WHAT = "{what} su {env}, con i payload dei log di {source}."
#: {path} = where the files go, with placeholders for the run and the folder.
GENERA_PLAN_WHERE = "I file vanno in {path}"
#: The run folder and the per-document folder in GENERA_PLAN_WHERE. {env} = generator.
GENERA_PLAN_RUN = "{env}_<data-ora>"
GENERA_PLAN_FOLDER_PACKAGE = "<package>"
GENERA_PLAN_FOLDER_FDI = "<FDI>"
GENERA_PLAN_OPEN = "Doppio clic (o Invio) su un documento generato lo apre."
GENERA_RESULTS_WAITING = "In attesa dei primi esiti…"
GENERA_STATUS_OK = "generato"
GENERA_STATUS_HTML = "email saltata"
GENERA_STATUS_NO_CALL = "nessuna chiamata"
GENERA_STATUS_FAILED = "non riuscito"
GENERA_STATUS_CANCELLED = "annullato"
# Glyphs next to the word (glyph + word, never colour alone).
GENERA_GLYPH_OK = "✓"
GENERA_GLYPH_HTML = "⊘"
GENERA_GLYPH_NO_CALL = "○"
GENERA_GLYPH_FAILED = "✕"
GENERA_GLYPH_CANCELLED = "–"
#: An outcome cell. {glyph}, {word} as above.
GENERA_STATUS_CELL = "{glyph}  {word}"
#: The duration of a call. {seconds} = with one decimal, comma separated.
GENERA_DURATION = "{seconds} s"
#: A key's folders when it is written into more than one. Between two names.
GENERA_FOLDERS_SEPARATOR = ", "

# The summary after a run, one part per kind that occurred (n = more than one).
#: {n}
GENERA_SUM_OK = "{n} generati"
GENERA_SUM_OK_ONE = "1 generato"
#: {n}
GENERA_SUM_FAILED = "{n} non riusciti"
GENERA_SUM_FAILED_ONE = "1 non riuscito"
#: {n}
GENERA_SUM_NO_CALL = "{n} senza chiamata nei log"
GENERA_SUM_NO_CALL_ONE = "1 senza chiamata nei log"
#: {n}
GENERA_SUM_HTML = "{n} email saltate"
GENERA_SUM_HTML_ONE = "1 email saltata"
#: {n}
GENERA_SUM_CANCELLED = "{n} annullati"
GENERA_SUM_CANCELLED_ONE = "1 annullato"
GENERA_SUM_SEPARATOR = " · "
GENERA_SUM_NOTHING = "Nessun documento: niente da generare."
#: {n} = zip files written.
GENERA_SUM_ZIPS = "{n} zip"
GENERA_SUM_ZIP_ONE = "1 zip"
#: The run folder, after the counts. {name} = its folder name.
GENERA_SUM_FOLDER = "in {name}"

# The chips over the table: one per outcome that occurred, each a filter.
#: {n} = every row.
GENERA_CHIP_ALL = "Tutti {n}"
#: {n}
GENERA_CHIP_NO_CALL = "{n} senza chiamata"
GENERA_CHIP_NO_CALL_ONE = "1 senza chiamata"
#: A chip. {glyph} = the outcome's glyph, {text} = its count and words.
GENERA_CHIP = "{glyph} {text}"
GENERA_CHIP_TIP = "Mostra solo queste righe; un altro clic le mostra tutte"
GENERA_CHIP_HTML_TIP = ("Email (HTML) non salvate: con «Salva anche le email (HTML)» acceso "
                        "vengono salvate anche loro")
#: The chip of the rows "Riprova" sends again (shown when they are of more than one kind).
#: {n}
GENERA_CHIP_RETRY = "{n} da riprovare"
GENERA_CHIP_RETRY_ONE = "1 da riprovare"
#: Its glyph: the one of the Riprova button's icon.
GENERA_GLYPH_RETRY = "↻"
GENERA_CHIP_RETRY_TIP = ("Mostra solo le righe che «Riprova» invia di nuovo: non riuscite, "
                         "senza chiamata o annullate; un altro clic le mostra tutte")

# The heading of the results pane after a run.
GENERA_DONE_TITLE = "Generazione finita"
GENERA_STOPPED_TITLE = "Generazione interrotta"
#: {title} = one of the two above, {name} = the run folder's name.
GENERA_DONE_LINE = "{title} · {name}"
#: {n} = outcomes to call again (more than one).
GENERA_RETRY = "Riprova i {n} non riusciti"
GENERA_RETRY_ONE = "Riprova quello non riuscito"
GENERA_RETRY_TIP = "Di nuovo, con le scelte di ora, solo per le righe non riuscite, senza chiamata o annullate"
#: The toast at the end (only when the tab is not on screen). {summary} = the summary's counts.
GENERA_TOAST_DONE = "Generazione finita: {summary}"
#: {summary} as above.
GENERA_TOAST_STOPPED = "Generazione interrotta: {summary}"
#: The toast's action back to the tab.
GENERA_TOAST_SHOW = "Vedi esiti"

# The row menu of the results.
GENERA_ROW_OPEN = "Apri il documento"
GENERA_ROW_FOLDER = "Apri la cartella del documento"
GENERA_ROW_COPY_KEY = "Copia template key"
GENERA_ROW_COPY_REASON = "Copia motivo"
GENERA_ROW_COPIED = "Copiato negli appunti"
GENERA_ROW_TIP_OPEN = "Doppio clic o Invio: apre il documento"

# -- no generator --------------------------------------------------------------------------
GENERA_NO_GENERATOR_TITLE = "Nessun generatore di documenti attivo"
GENERA_NO_GENERATOR_HINT = ("Genera invia i payload dei log a un generatore di documenti (svil o coll) e "
                            "salva i PDF e le email in cartelle per package. Attivane uno in "
                            "Impostazioni › Officina.")
GENERA_NO_GENERATOR_BTN = "Apri Impostazioni › Officina"
