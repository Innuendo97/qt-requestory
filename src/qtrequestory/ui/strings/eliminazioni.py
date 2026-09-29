"""Phase 2.5 (D6): undoable deletions — the bar at the bottom of the window
(``ui/pending_delete``), "Elimina iniziativa" in the Officina list, and the
words the quit question adds while deletions are pending."""

# -- the bar (any delicate deletion) --------------------------------------------
#: A single pending deletion reads as the owner's own sentence (ELIMINA_DONE…).
#: {count}: how many deletions are waiting (2 or more).
ELIMINA_MANY = "{count} elementi eliminati"
ELIMINA_UNDO = "Annulla"
ELIMINA_UNDO_ALL = "Annulla tutto"
ELIMINA_UNDO_TIP = "Annulla l'eliminazione (Ctrl+Z)"
ELIMINA_UNDO_ALL_TIP = "Annulla tutte le eliminazioni in attesa (Ctrl+Z annulla l'ultima)"
#: {name}: the row of the expanded list ("Iniziativa «Banco»").
ELIMINA_UNDO_ONE_A11Y = "Annulla l'eliminazione di {name}"
#: {seconds}: whole seconds left before the deletion becomes permanent.
ELIMINA_SECONDS = "{seconds} s"
ELIMINA_COUNTDOWN_TIP = "Allo scadere l'eliminazione è definitiva"
#: The expand button of the grouped bar (followed by ▾ / ▴).
ELIMINA_LIST = "Elenco"
ELIMINA_SHOW_LIST = "Mostra quali"
ELIMINA_HIDE_LIST = "Nascondi l'elenco"
ELIMINA_BAR_A11Y = "Eliminazioni in attesa"

# -- "Elimina iniziativa" (Officina list) ------------------------------------------
ELIMINA_INITIATIVE = "Elimina iniziativa"
ELIMINA_INITIATIVE_TIP = "Elimina l'iniziativa (Canc): 5 secondi per annullare, poi è definitivo"
ELIMINA_OPEN = "Apri"
#: {name}: the initiative's name. The bar's sentence while one is pending.
ELIMINA_INITIATIVE_DONE = "Iniziativa «{name}» eliminata"
#: {name}: one row of the bar's expanded list.
ELIMINA_INITIATIVE_ROW = "Iniziativa «{name}»"
#: {name}, {reason}: the deletion failed at the end of the 5 s; the row is back.
ELIMINA_FAILED = "Iniziativa «{name}» non eliminata: {reason}. È di nuovo nell'elenco."
ELIMINA_REASON_LOCKED = ("un file è in uso o protetto (chiudi il PDF o la finestra aperta sulla "
                         "cartella e riprova)")
ELIMINA_REASON_REFUSED = "la cartella non è un'iniziativa dentro la cartella dell'Officina"
ELIMINA_REASON_BUSY = ("è stata riaperta o ha generazioni, consegne o chiamate in aggiunta in corso: "
                      "riprova quando hanno finito")
#: {name}: refused because the Officina folder changed during the countdown; the
#: initiative stays in the previous folder (so it is NOT back in this list).
ELIMINA_FAILED_ROOT_CHANGED = ("Iniziativa «{name}» non eliminata: la cartella dell'Officina è cambiata "
                               "nel frattempo, l'iniziativa resta nella cartella di prima.")
ELIMINA_REASON_ROOT_CHANGED = ("la cartella dell'Officina è cambiata nel frattempo: l'iniziativa resta "
                               "nella cartella di prima")
#: {name}: "Nuova iniziativa" with the name of one being deleted.
ELIMINA_NAME_PENDING = "«{name}» è in eliminazione: annulla l'eliminazione o attendi qualche secondo"
#: {name}: an initiative being deleted cannot be opened.
ELIMINA_PENDING_OPEN = "«{name}» è in eliminazione: annullala dalla barra in basso per aprirla"
#: {error}: the system's own words.
ELIMINA_REASON_OTHER = "errore del disco ({error})"
#: {name}: the initiative with cases waiting or being generated.
ELIMINA_BUSY = "«{name}» ha generazioni o consegne in corso: attendi che finiscano per eliminarla"

# -- closing the window ------------------------------------------------------------
#: {count}: deletions still in their 5 s; the quit question mentions them.
QUIT_PENDING_DELETIONS = ("Le eliminazioni in attesa ({count}) saranno completate prima di uscire: "
                          "non si potranno più annullare.")
QUIT_DELETIONS_FAILED_TITLE = "Eliminazioni non completate"
#: {lines}: one "Iniziativa «X»: <reason>" per line.
QUIT_DELETIONS_FAILED_TEXT = "Questi elementi non sono stati eliminati e restano sul disco:\n\n{lines}"
