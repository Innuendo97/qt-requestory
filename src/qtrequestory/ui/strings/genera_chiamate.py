"""Strings of "Genera documento" in Ricerca: the document of the selected calls.

Owned by the Ricerca entry points (``ui/pages/search_generate.py``) and by
the Genera side that runs them (``ui/pages/genera_calls.py``). The run itself
is a Genera run: its rows, summary and confirmation use ``genera.py``'s words.
"""

# -- the entry points (button, menu, shortcut) -------------------------------------------
GENERA_CALLS_ACTION_ONE = "Genera documento"
#: {n} = selected calls (more than one).
GENERA_CALLS_ACTION_N = "Genera {n} documenti"
#: One entry of the generator menu. {env} = the generator.
GENERA_CALLS_ON_ENV = "su {env}"
#: Tooltip of the button. {shortcut} = its key.
GENERA_CALLS_TIP = ("Invia al generatore i payload delle chiamate selezionate, così come sono nei log, "
                    "e salva il documento (PDF o HTML) nella cartella di Genera ({shortcut})")
GENERA_CALLS_TIP_NOTHING = "Seleziona una o più chiamate (o un FDI) per generarne il documento"
GENERA_CALLS_TIP_RUNNING = ("Genera sta già generando: attendi la fine o interrompila dalla scheda Genera, "
                            "poi riprova")
GENERA_CALLS_TIP_NO_GENERATOR = ("Nessun generatore di documenti attivo: attivane uno in "
                                 "Impostazioni › Officina")
#: Added to the tooltip while the Genera tab's headers differ from Impostazioni. {m} = changed rows.
GENERA_CALLS_HEADERS_EDITED = "Attenzione: gli header della scheda Genera sono modificati ({m}) e valgono anche qui."
GENERA_CALLS_UNAVAILABLE ="La scheda Genera non è disponibile: impossibile generare il documento."

# -- why nothing was sent (before anything starts) ------------------------------------------
GENERA_CALLS_NEED_DESTINATION = ("Nessuna chiamata inviata: scegli prima la cartella di destinazione "
                                 "nella scheda Genera.")
#: {name} = the generator asked for.
GENERA_CALLS_GENERATOR_OFF = ("Nessuna chiamata inviata: il generatore {name} non è attivo in "
                              "Impostazioni › Officina.")
#: {problem} = the first problem of the Genera tab's header table (the core's wording).
GENERA_CALLS_HEADER_PROBLEM = "Nessuna chiamata inviata: correggi gli header nella scheda Genera ({problem})."

# -- toasts -----------------------------------------------------------------------------------
#: The run started. {n} = calls, {env} = the generator.
GENERA_CALLS_STARTED = "Genero {n} documenti su {env}…"
#: {env} = the generator.
GENERA_CALLS_STARTED_ONE = "Genero il documento su {env}…"
#: One document, opened. {name} = its file name, {folder} = its folder name.
GENERA_CALLS_SAVED = "Salvato {name} in {folder}"
#: The document was saved but could not be opened. {name} = its file name.
GENERA_CALLS_SAVED_NOT_OPENED = "Salvato {name}, ma non è stato possibile aprirlo"
# Several calls: genera.py's GENERA_TOAST_DONE / GENERA_TOAST_STOPPED, as the tab says it.
#: Nothing generated, one call. {reason} = its outcome's reason (or its status word).
GENERA_CALLS_NOTHING = "Nessun documento generato: {reason}"
#: Nothing generated, several calls. {summary} = the counts, {reason} = the first reason.
GENERA_CALLS_NOTHING_MANY = "Nessun documento generato ({summary}): {reason}"
GENERA_CALLS_SEE_RESULTS = "Vedi esiti"
#: After a refusal: the Genera tab, where the folder and the headers are chosen.
GENERA_CALLS_OPEN_GENERA = "Apri Genera"
