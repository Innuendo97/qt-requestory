"""Officina 1.3.2: "Aggiungi chiamata…" — the window that adds cases from the
logged calls or replaces a case's call, its replace-or-new question, and the
"Cambia chiamata…" entries of the case (owner: task A1)."""

CHIAMATA_TITLE = "Aggiungi chiamata"
#: {case} = the case's key (and variant): the window opened from a case.
CHIAMATA_TITLE_CASE = "Cambia chiamata di {case}"
CHIAMATA_ENV = "Ambiente:"
CHIAMATA_QUERY = "Chiamata:"
CHIAMATA_QUERY_HINT = "template key esatta o FDI (anche solo l'inizio)"
CHIAMATA_COL_WHEN = "Data e ora"
CHIAMATA_COL_FDI = "FDI"
CHIAMATA_COL_KEY = "Template key"
CHIAMATA_INITIATIVE = "Iniziativa:"
CHIAMATA_VARIANT = "Variante dei casi nuovi:"
CHIAMATA_ADD = "Aggiungi"
CHIAMATA_ADD_CASE = "Usa questa chiamata"
CHIAMATA_START = "Scrivi una template key o un FDI: le chiamate compaiono mentre scrivi."
CHIAMATA_SEARCHING = "Cerco…"
CHIAMATA_NOT_A_QUERY = "Non è una template key né un FDI: usa lettere, cifre e trattini bassi, o un FDI."
#: {env} = log environment.
CHIAMATA_NONE = "Nessuna chiamata in {env} con questa template key o FDI."
#: {n} = how many calls are listed.
CHIAMATA_FOUND = "{n} chiamate, dalla più recente."
CHIAMATA_FOUND_ONE = "1 chiamata."
#: {n} = the cap (the most recent ones are listed).
CHIAMATA_CAPPED = "Mostrate le prime {n} chiamate, dalla più recente: scrivi un FDI per restringere."
#: {env} = log environment.
CHIAMATA_NO_INDEX = ("Nessun log di {env} è ancora indicizzato: sincronizza {env} da "
                     "Sincronizzazione, poi riprova.")
CHIAMATA_NO_ENV = "Nessun ambiente dei log è abilitato: aggiungine uno in Impostazioni › Ambienti."
#: {reason} = the problem of the log folder or of the query, in Italian.
CHIAMATA_FAILED = "Ricerca non riuscita: {reason}"
CHIAMATA_NEED_SELECTION = "Seleziona almeno una chiamata."
#: {key} = the case's template key.
CHIAMATA_OTHER_KEY = "Scegli una chiamata della template key del caso ({key})."
CHIAMATA_NOT_JSON_TIP = "Il corpo di questa chiamata non è JSON: non può diventare un caso."

# -- the replace-or-new question ---------------------------------------------------

CHIAMATA_ASK_TITLE = "Caso già presente"
#: {key} = template key, {fdi} = the call's FDI (short), {initiative} = initiative name.
CHIAMATA_ASK_TEXT = ("La chiamata {fdi} è della template key {key}, che in «{initiative}» "
                     "ha già un caso. Che cosa ne faccio?")
#: {key} = template key, {fdi} = the call's FDI (short), {initiative} = initiative name.
CHIAMATA_ASK_TEXT_SAME_RUN = ("La chiamata {fdi} ha la template key {key} di un'altra chiamata scelta "
                              "per «{initiative}»: indica una variante per il nuovo caso.")
#: {case} = the case's key (and variant).
CHIAMATA_ASK_REPLACE = "Sostituisci la chiamata di {case}"
CHIAMATA_ASK_REPLACE_HINT = ("Target, AS-IS, versioni TO-BE e revisione restano; il payload di prima "
                             "resta nella cartella del caso. L'AS-IS andrà rigenerato.")
CHIAMATA_ASK_NEW = "Crea un nuovo caso"
CHIAMATA_ASK_VARIANT = "Variante:"
CHIAMATA_ASK_NEED_VARIANT = "Indica una variante diversa da quelle dei casi che ci sono già."
CHIAMATA_ASK_CONTINUE = "Continua"

# -- the job and its outcome ----------------------------------------------------------

CHIAMATA_JOB = "aggiunta delle chiamate all'Officina"
CHIAMATA_JOB_PICK = "ricerca delle chiamate dell'Officina"
CHIAMATA_ADDING = "Aggiungo le chiamate all'Officina…"
CHIAMATA_BUSY = "Sto ancora aggiungendo le chiamate di prima: attendi che finisca."
#: {n} = number of cases.
CHIAMATA_DONE_ADDED_ONE = "1 caso aggiunto"
CHIAMATA_DONE_ADDED = "{n} casi aggiunti"
CHIAMATA_DONE_REPLACED_ONE = "chiamata sostituita in 1 caso"
CHIAMATA_DONE_REPLACED = "chiamata sostituita in {n} casi"
CHIAMATA_DONE_UNCHANGED_ONE = "1 caso aveva già quella chiamata (nulla cambiato)"
CHIAMATA_DONE_UNCHANGED = "{n} casi avevano già quella chiamata (nulla cambiato)"
#: {n} = calls not added, {reasons} = their reasons.
CHIAMATA_DONE_FAILED = "{n} non riuscite ({reasons})"
#: {parts} = the parts above, joined; {initiative} = initiative name.
CHIAMATA_DONE = "«{initiative}»: {parts}."
#: {case} = the case's key (and variant), {initiative} = initiative name.
CHIAMATA_REPLACED_TOAST = "Chiamata di {case} sostituita in «{initiative}»."
#: {reason} = why the initiative could not be used.
CHIAMATA_FAILED_ALL = "Chiamate non aggiunte: {reason}"
#: {what} = key and short FDI of a call, {reason} = why it failed.
CHIAMATA_ITEM_FAILED = "{what}: {reason}"

# -- inside the case ------------------------------------------------------------------

CHIAMATA_CHANGE = "Cambia chiamata…"
CHIAMATA_CHANGE_TIP = "Sostituisce la chiamata del caso con un'altra dei log: target e versioni restano."
CHIAMATA_CHANGE_DISCARD_TITLE = "Cambia chiamata"
CHIAMATA_CHANGE_DISCARD = "Le modifiche non salvate a payload e header andranno perse. Continuo?"
CHIAMATA_STALE_ASIS = ("La chiamata è cambiata: l'AS-IS è stato generato con quella precedente.")
CHIAMATA_REGENERATE_ASIS = "Rigenera AS-IS"
#: The note of the AS-IS replaced from the strip (spec §14: a replacement needs one).
CHIAMATA_ASIS_NOTE = "AS-IS rigenerato dopo il cambio di chiamata"
#: {case} = the case id.
CHIAMATA_CASE_BUSY = ("Il caso {case} è in coda o in generazione: aspetta che finisca, poi cambiane "
                      "la chiamata. Nessuna chiamata aggiunta.")
CHIAMATA_CASE_GONE = "il caso non c'è più nell'iniziativa (ricaricata nel frattempo?)"
#: Suffix of the FDI of the call the case has now, in the window opened from the case.
CHIAMATA_CURRENT = "{fdi}  (attuale)"
CHIAMATA_CURRENT_TIP = ("La chiamata da cui è nato il caso: sceglierla ripristina il suo payload "
                        "se è stato modificato, altrimenti non cambia nulla.")
