"""Officina phase 2.5 (U4): the "Filtri del confronto" dialog (spec §3.8, D3).

Owned by ``ui/pages/officina_filters.py`` (the dialog),
``ui/pages/officina_filters_rows.py`` (its rows) and
``ui/pages/officina_filters_page.py`` (what the page does with it).
"""

# {case}: the case's title (key · variant)
FILTRI_TITLE = "Filtri del confronto — {case}"
FILTRI_HELP = ("Calcolati dal documento. Quel che è messo da parte non conta come differenza; "
               "ogni cambio aggiorna subito il confronto di questo caso.")
FILTRI_SCOPE = "Usa per tutta l'iniziativa"
FILTRI_SCOPE_TIP = ("Acceso: ogni scelta che fai diventa la predefinita di tutti i casi dell'iniziativa "
                    "e questo caso la segue (un altro caso con una scelta sua la tiene).")
FILTRI_CLOSE = "Chiudi"
FILTRI_RESET = "Ripristina predefiniti"
FILTRI_RESET_TIP = "Toglie le scelte proprie di questo caso: ogni riga torna come l'iniziativa."
# {n}: the case's own choices
FILTRI_RESET_TIP_N = "Toglie le {n} scelte proprie di questo caso: ogni riga torna come l'iniziativa."
FILTRI_RESET_DONE = "Filtri: questo caso torna ai predefiniti dell'iniziativa"
FILTRI_RESET_NOTHING = "Filtri: questo caso non ha scelte sue, segue già l'iniziativa"
#: The panel could not be computed (e.g. the engine does not give it yet): the
#: dialog opens anyway, with "Regole avanzate" usable.
FILTRI_UNAVAILABLE = ("I filtri calcolati dal documento non sono ancora disponibili per questo caso; "
                      "le regole avanzate sì.")

#: Section headings. {n}: the occurrences found in that section.
FILTRI_SECTION_ZONE = "Zone · {n}"
FILTRI_SECTION_ZONE_TIP = ("Le differenze nelle zone che contano, come nel pannello laterale; "
                           "ogni riga dice quante ne ha la sua zona.")
FILTRI_SECTION_VARIABILI = "Variabili riconosciute · {n}"
FILTRI_SECTION_DECIDERE = "Da decidere · {n}"
FILTRI_NOTE_ZONE = "Le differenze nelle zone contano; numero di pagina e filigrana no, finché non le riaccendi."
FILTRI_NOTE_VARIABILI = "Valori che cambiano da un documento all'altro: riconosciuti, non contano."
FILTRI_NOTE_DECIDERE = "Contano come differenze: «Tollera tutte» le mette da parte in un colpo."
FILTRI_NOTE_AVANZATE = "Espressioni regolari: quel che trovano è rumore e non conta."

#: The switch of a row, by section (checked = what the label says).
FILTRI_SWITCH_ZONE = "Conta"
FILTRI_SWITCH_VARIABILI = "Variabile"
FILTRI_SWITCH_DECIDERE = "Tollera tutte"
FILTRI_SWITCH_AVANZATE = "Applica"
FILTRI_SWITCH_ZONE_TIP = "Spunta: le differenze in questa zona contano."
FILTRI_SWITCH_VARIABILI_TIP = "Spunta: quel che questa prova riconosce è una variabile e non conta."
FILTRI_SWITCH_DECIDERE_TIP = "Spunta: tutte queste differenze sono tollerate e non contano."
FILTRI_SWITCH_AVANZATE_TIP = "Spunta: la regola si applica, quel che trova è rumore."
#: A switch tooltip's second line. {state}: FILTRI_ON / FILTRI_OFF
FILTRI_DEFAULT_TIP = "Senza una scelta del caso: {state}."
FILTRI_ON = "spuntato"
FILTRI_OFF = "non spuntato"
#: The informational row (invisible text: never compared, ruling F7).
FILTRI_INFORMATIVE = "solo informativo"
FILTRI_INFORMATIVE_TIP = "Il testo invisibile non si confronta mai: qui vedi solo quanto ce n'è."

#: The count of a row. {n}
FILTRI_COUNT_TIP_ONE = "1 occorrenza nell'ultimo confronto"
FILTRI_COUNT_TIP_MANY = "{n} occorrenze nell'ultimo confronto"
FILTRI_COUNT_TIP_NONE = "Nessuna occorrenza nell'ultimo confronto"
#: The expander of a row. {name}: the row's title
FILTRI_EXPAND_NAME = "Occorrenze di «{name}»"
#: One occurrence. {pages}: "1" or "1, 2"; {text}: the text; {detail}: the variable's name, a hit…
FILTRI_OCCURRENCE = "p. {pages} · {text}"
FILTRI_OCCURRENCE_DETAIL = "p. {pages} · {text} · {detail}"
FILTRI_OCCURRENCE_TIP = "Mostrala nei documenti"
FILTRI_OCCURRENCE_NO_DIFF = "Non è una differenza: non c'è niente da mostrare nei documenti"
FILTRI_OCCURRENCE_EMPTY = "(vuoto)"
# {n}: the occurrences not listed
FILTRI_MORE_OCCURRENCES = "… e altre {n}"

#: "Regole avanzate" (the regex editor of the case's own rules, R46).
# {n}: the occurrences the rules found
FILTRI_ADVANCED_SHOW = "Regole avanzate · {n} ▸"
FILTRI_ADVANCED_HIDE = "Regole avanzate · {n} ▾"
FILTRI_ADVANCED_TIP = "Le regole con le espressioni regolari: accenderle e scriverne di nuove per questo caso."
FILTRI_RULES_SAVE = "Salva le regole del caso"
FILTRI_RULES_SAVE_TIP = "Salva le regole scritte qui sotto e rifà il confronto del caso."

#: The control generation (spec §3.4, D14): a discreet note, never an error.
FILTRI_CONTROL_ASSENTE = "Riconoscimento esteso: parte da solo dopo la prossima generazione."
FILTRI_CONTROL_IN_CORSO = "Riconoscimento esteso in corso…"
FILTRI_CONTROL_PRONTA = "Riconoscimento esteso attivo."
FILTRI_CONTROL_NON_DISPONIBILE = "Riconoscimento esteso non disponibile per questo caso."
FILTRI_CONTROL_EMAIL = "Riconoscimento esteso non disponibile per le email: vale solo per i documenti PDF."
FILTRI_CONTROL_TIP = ("Una seconda generazione su svil con valori di prova, in background: le parole che "
                      "cambiano fra le due sono variabili («Cambiano fra due generazioni»).")

#: The toast after a switch (undoable). {name}: the row's title; {state}: below
FILTRI_CHANGED = "Filtri: «{name}» {state}"
FILTRI_CHANGED_INITIATIVE = "Filtri: «{name}» {state}, per tutta l'iniziativa"
# {n}: the switches made in a row (one toast, "Annulla" undoes them all)
FILTRI_CHANGED_MANY = "Filtri: {n} modifiche"
FILTRI_STATE_ZONE_ON = "non conta più"
FILTRI_STATE_ZONE_OFF = "conta"
FILTRI_STATE_VARIABILI_ON = "riconosciute come variabili"
FILTRI_STATE_VARIABILI_OFF = "non più variabili"
FILTRI_STATE_DECIDERE_ON = "tollerate tutte"
FILTRI_STATE_DECIDERE_OFF = "contano di nuovo"
FILTRI_STATE_AVANZATE_ON = "applicata"
FILTRI_STATE_AVANZATE_OFF = "non applicata"

#: The regex preset that shares its name with the zone (the row's title; the
#: stored name of the preset does not change).
FILTRI_PRESET_PAGE_NUMBER = "Numero di pagina nel testo"
FILTRI_PRESET_PAGE_NUMBER_TIP = ("Regola sul testo: «Pag. 1 di 2» ovunque si trovi nel documento. La zona "
                                 "«Numero di pagina» invece mette da parte il numero nella sua posizione a piè di pagina.")

#: Closing with unsaved rules in "Regole avanzate".
FILTRI_UNSAVED_TITLE = "Regole non salvate"
FILTRI_UNSAVED_TEXT = "Le regole del caso sono cambiate e non sono salvate."
FILTRI_UNSAVED_INVALID = "Le regole del caso sono cambiate ma hanno errori: correggile per salvarle, o scartale."
FILTRI_UNSAVED_SAVE = "Salva"
FILTRI_UNSAVED_DISCARD = "Scarta"
FILTRI_UNSAVED_CANCEL = "Annulla"
