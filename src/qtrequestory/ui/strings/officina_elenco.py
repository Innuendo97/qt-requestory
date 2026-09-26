"""Officina phase 2: the differences list of the case view (spec §7.2).

Owned by ``ui/pages/officina_diffs.py`` (the panel) and
``ui/pages/officina_rows.py`` (what one row says). The verdict words and glyphs
themselves live in ``officina_verdetto``.
"""

# -- tabs: {n} = how many differences the tab holds ------------------------------
ELENCO_TAB_GUARDARE = "Da guardare {n}"
ELENCO_TAB_VERIFICARE = "Da verificare {n}"
ELENCO_TAB_FATTE = "Fatte {n}"
ELENCO_TAB_TOLLERATE = "Tollerate {n}"
ELENCO_TAB_VARIABILI = "Variabili {n}"
ELENCO_TAB_TUTTE = "Tutte {n}"
ELENCO_TAB_GUARDARE_TIP = "Regressioni, non risolte, da fare e in corso: ciò che resta da sistemare."
ELENCO_TAB_VERIFICARE_TIP = "Segnate fatte: la prossima rigenerazione del TO-BE le verifica."
ELENCO_TAB_FATTE_TIP = "Differenze dell'AS-IS che nel TO-BE non ci sono più."
ELENCO_TAB_TOLLERATE_TIP = "Tollerate a mano o non contate dal profilo."
ELENCO_TAB_VARIABILI_TIP = "Dati variabili riconosciuti nel target: non sono differenze."
ELENCO_TAB_TUTTE_TIP = "Tutte le differenze, rumore compreso."
#: "Tutte" when entries of the case match nothing now (R30): {n} = differences, {k} = inactive
#: entries (⊘: they do nothing; the tooltip says what they are; short: the tab is narrow).
ELENCO_TAB_TUTTE_INACTIVE = "Tutte {n} ⊘{k}"
ELENCO_TAB_TUTTE_INACTIVE_TIP = ("{k} tra tolleranze, segni «fatta» e «non è una variabile» non trovano "
                                 "più la loro differenza (per esempio dopo un nuovo target): restano "
                                 "nel caso, senza effetto, finché non li azzeri.")

#: The group of marked differences at the bottom of "Da guardare".
ELENCO_GROUP_VERIFICARE = "DA VERIFICARE"

# -- an empty tab ------------------------------------------------------------------
#: Nothing left to look at and something is done. {n} = how many "fatte".
ELENCO_ALL_DONE = "Niente da guardare: tutto fatto ({n} fatte)."
ELENCO_ALL_DONE_ONE = "Niente da guardare: l'unica differenza è fatta."
#: Nothing left to look at, but marks wait for the next TO-BE. {n} = how many.
ELENCO_ONLY_MARKED = "Niente da guardare: {n} da verificare con la prossima rigenerazione (F5)."
ELENCO_NOTHING_TO_LOOK = "Niente da guardare: restano solo differenze che non contano."
ELENCO_EMPTY_TAB = "Nessuna differenza in questa scheda."

# -- one row -----------------------------------------------------------------------
#: {page} = 1-based page, {op} = what happened (ELENCO_OP_*).
ELENCO_WHERE = "pag. {page} · {op}"
ELENCO_OP_MANCANTE = "mancante"
ELENCO_OP_IN_PIU = "in più"
ELENCO_OP_CAMBIATO = "cambiato"
ELENCO_OP_SPOSTATO = "spostato"
ELENCO_OP_SEZIONE_ASSENTE = "sezione assente"
ELENCO_OP_SEZIONE_IN_PIU = "sezione in più"
ELENCO_OP_PAGINE = "pagine"
#: A difference that has no place on the page (a link, an image source).
ELENCO_ONLY_LIST = "Solo nell'elenco: nel documento non ha un punto da evidenziare."
#: "non risolta": {n} = the version the mark was made in, {m} = the version compared now.
ELENCO_NON_RISOLTA = "Segnata fatta in v{n}, ma in v{m} è ancora qui."
ELENCO_NON_RISOLTA_NO_N = "Segnata fatta, ma in v{m} è ancora qui."
#: "in corso": {before} = the text generated before, {now} = the text generated now.
ELENCO_IN_CORSO = "Prima «{before}» → ora «{now}»"
ELENCO_REGRESSIONE = "Nell'AS-IS era uguale al target."
#: {note} = the note written when tolerating.
ELENCO_TOLLERATA_NOTE = "Nota: {note}"
#: Tooltip of a row: {target} / {generated} = the two texts, whole.
ELENCO_ROW_TIP = "Target: «{target}»\nGenerato: «{generated}»"

# -- class glyph tooltips (spec §7.2) -------------------------------------------
ELENCO_CLASS_TESTO = "testo"
ELENCO_CLASS_COMPOSIZIONE = "composizione"
ELENCO_CLASS_STILE = "stile"
ELENCO_CLASS_SPAZIATURA = "spaziatura"
ELENCO_CLASS_VARIABILE = "variabile"
ELENCO_CLASS_RUMORE = "rumore"
ELENCO_CLASS_LINK = "link"
ELENCO_CLASS_SPOSTATO = "spostato"

# -- key legend at the bottom of the list --------------------------------------------
ELENCO_KEY_MOVE = "scorri"
ELENCO_KEY_GO = "vai"
ELENCO_KEY_DONE = "fatta"
ELENCO_KEY_TOLERATE = "tollera"
ELENCO_KEY_NOT_VARIABLE = "non è una variabile"
ELENCO_KEY_ENTER = "Invio"
#: U4, approved draft v2: "F / doppio clic fatta · … · clic destro altro · Ctrl+Z annulla".
ELENCO_KEY_OR_DOUBLE_CLICK = "/ doppio clic"
ELENCO_KEY_RIGHT_CLICK = "clic destro"
ELENCO_KEY_MORE = "altro"
ELENCO_KEY_UNDO = "Ctrl+Z"
ELENCO_KEY_UNDO_WHAT = "annulla"

# -- the actions (page side) ---------------------------------------------------------
#: {what} = the elided target text (or the generated one for an added text). The
#: toast adds " · Annulla (Ctrl+Z)" after them (U4, approved draft v2).
ELENCO_MARKED = "Segnata fatta «{what}»"
ELENCO_UNMARKED = "Tolto il segno da «{what}»"
ELENCO_TOLERATED = "Tollerata «{what}»"
ELENCO_UNTOLERATED = "Non più tollerata «{what}»"
ELENCO_NOT_VARIABLE = "Non è una variabile «{what}»: ora conta come testo"
ELENCO_VARIABLE_AGAIN = "Di nuovo variabile «{what}»"
ELENCO_TOLERATED_BY_PROFILE = ("«{what}» è tollerata dal profilo: cambia il profilo del caso "
                               "per farla contare.")
#: {reason} = why caso.json could not be saved.
ELENCO_ACTION_FAILED = "Azione non salvata: {reason}"

# -- R45: "Mostra fatte" next to the tabs, "⋯" → "Azzera tolleranze…" in the case header --
ELENCO_SHOW_DONE = "☐ Mostra fatte"
ELENCO_SHOW_DONE_ON = "☑ Mostra fatte"
ELENCO_SHOW_DONE_TIP = ("Mostra nel target, sottolineate in verde, le differenze già fatte "
                        "(anche nella minimappa).")
CASO_MORE = "⋯"
CASO_MORE_TIP = "Altri comandi del caso"
CASO_RESET_TOLERANCES = "Azzera tolleranze…"
CASO_RESET_TOLERANCES_TIP = "Toglie le tolleranze a mano e le correzioni «non è una variabile» di questo caso."
CASO_RESET_TOLERANCES_TITLE = "Azzera tolleranze"
OFFICINA_RESET_TOLERANCES_CONFIRM = ("Togliere tutte le tolleranze a mano e le correzioni «non è una "
                                     "variabile» di questo caso? Le differenze tornano a contare; "
                                     "non si può annullare.")
CASO_RESET_TOLERANCES_DONE = "Tolleranze azzerate: il confronto riparte"
#: {reason} = why the save was refused.
CASO_RESET_TOLERANCES_FAILED = "Tolleranze non azzerate: {reason}"
