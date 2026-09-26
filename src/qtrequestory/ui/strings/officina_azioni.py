"""Officina phase 2: the actions on a difference (spec §7.3, D10).

Owned by ``ui/pages/officina_actions_bar.py`` (the floating mini-bar under a
highlight, the right-click menu, the "Tollera…" note dialog) and
``ui/pages/officina_review.py`` (what the page does: the toast with
"Annulla", Ctrl+Z, copying a text). The toast texts of the actions themselves
("Segnata fatta «…»") live in ``officina_elenco``.
"""

# -- the mini-bar under the selected highlight -------------------------------------
AZIONI_BAR_DONE = "✓ Fatta  F"
AZIONI_BAR_UNMARK = "↺ Togli il segno  F"
AZIONI_BAR_TOLERATE = "⊘ Tollera  T"
AZIONI_BAR_UNTOLERATE = "⊘ Non tollerare  T"
AZIONI_BAR_MORE = "⋯"
AZIONI_BAR_DONE_TIP = "Segna fatta (F o doppio clic): la prossima rigenerazione del TO-BE la verifica."
AZIONI_BAR_UNMARK_TIP = "Togli il segno «fatta» (F o doppio clic)."
AZIONI_BAR_TOLERATE_TIP = "Tollera senza nota (T). Con una nota: clic destro → Tollera…"
AZIONI_BAR_UNTOLERATE_TIP = "Torna a contarla (T)."
AZIONI_BAR_MORE_TIP = "Altre azioni (anche con il clic destro)"

# -- the right-click menu (a tab separates the key shown on the right) ------------------
AZIONI_MENU_DONE = "✓ Fatta\tF"
AZIONI_MENU_UNMARK = "↺ Togli il segno «fatta»\tF"
AZIONI_MENU_TOLERATE = "⊘ Tollera…"
AZIONI_MENU_UNTOLERATE = "⊘ Non tollerare più\tT"
AZIONI_MENU_NOT_VARIABLE = "Non è una variabile\tV"
AZIONI_MENU_VARIABLE_AGAIN = "Di nuovo variabile\tV"
AZIONI_MENU_COPY_TARGET = "Copia testo del target"
AZIONI_MENU_COPY_GENERATED = "Copia testo generato"

# -- "Tollera…": the note dialog --------------------------------------------------------
AZIONI_NOTE_TITLE = "Tollera la differenza"
#: {what} = the elided text of the difference.
AZIONI_NOTE_TEXT = "«{what}» non conterà più, finché il testo generato resta questo."
AZIONI_NOTE_LABEL = "Nota (facoltativa)"
AZIONI_NOTE_PLACEHOLDER = "Perché va bene così"
AZIONI_NOTE_OK = "Tollera"

# -- toast, undo, copy -----------------------------------------------------------------
#: The toast's button: undo the action it reports.
AZIONI_UNDO = "Annulla"
#: After the button: the key that does the same.
AZIONI_UNDO_KEY = "(Ctrl+Z)"
#: {action} = what the toast of the undone action said.
AZIONI_UNDONE = "Annullato: {action}"
AZIONI_NOTHING_TO_UNDO = "Niente da annullare in questo caso."
#: A queued action whose difference changed away meanwhile. {what} = its text.
AZIONI_GONE = "Azione saltata: la differenza «{what}» non c'è più."
#: The case was left with actions still waiting. {n} = how many.
AZIONI_DROPPED = "Azioni in attesa non applicate ({n}): il caso non è più aperto."
AZIONI_UNDO_FAILED = "Annullamento non salvato: {reason}"
AZIONI_COPIED_TARGET = "Testo del target copiato negli appunti."
AZIONI_COPIED_GENERATED = "Testo generato copiato negli appunti."
#: F on a difference that does not count. {what} = its text, {state} = what it is.
AZIONI_NOT_COUNTING = "«{what}» non conta ({state}): non c'è niente da segnare fatta."
#: The review job's name in the status bar (``quit_dialog.JOB_LABELS``).
AZIONI_JOB_REVIEW = "Salvataggio della revisione"
