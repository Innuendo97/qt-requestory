"""Officina phase 2: the progress bar, the verdict strip, the review banners
and the profile menu of the case view (spec §5.3, §7.1).

Owned by ``ui/pages/officina_progress.py`` and ``ui/pages/officina_banners.py``;
the board's "TO-BE contro target" pill (``BACHECA_*``) by ``ui/pages/officina_board_pill.py``
and the minimap beside each document (``MINIMAPPA_*``) by ``ui/pages/officina_minimap.py``.
The verdict words and glyphs themselves live in ``officina_verdetto``. Every
count has a ``_ONE`` and a ``_MANY`` form: {icon} = the verdict glyph, {n} = how many.
"""

# -- progress bar -------------------------------------------------------------
#: {pct} = 0..100, rounded.
AVANZAMENTO_PERCENT = "{pct}%"
#: {version} = the TO-BE number the summary is of.
AVANZAMENTO_VERSION = "v{version} contro target"
AVANZAMENTO_TOOLTIP = ("Avanzamento: fatte / (fatte + da fare + in corso + regressioni). "
                       "Una modifica «da verificare» conta ancora come prima: il segno è una "
                       "promessa, non un risultato.")
#: Nothing counts (no difference, or only tolerated / variables / noise).
AVANZAMENTO_NOTHING = "Nessuna differenza che conta"

AVANZAMENTO_REGRESSIONE_ONE = "{icon} {n} regressione"
AVANZAMENTO_REGRESSIONE_MANY = "{icon} {n} regressioni"
AVANZAMENTO_NON_RISOLTA_ONE = "{icon} {n} non risolta"
AVANZAMENTO_NON_RISOLTA_MANY = "{icon} {n} non risolte"
#: R44: the non risolte are counted apart AND in their verdict.
AVANZAMENTO_NON_RISOLTA_TIP = ("Segnate fatte e ancora presenti dopo la rigenerazione. Ognuna conta "
                               "anche nel suo verdetto (regressione, da fare, in corso): la stessa "
                               "differenza può comparire in due totali.")
AVANZAMENTO_DA_FARE_ONE = "{icon} {n} da fare"
AVANZAMENTO_DA_FARE_MANY = "{icon} {n} da fare"
AVANZAMENTO_IN_CORSO_ONE = "{icon} {n} in corso"
AVANZAMENTO_IN_CORSO_MANY = "{icon} {n} in corso"
AVANZAMENTO_DA_VERIFICARE_ONE = "{icon} {n} da verificare"
AVANZAMENTO_DA_VERIFICARE_MANY = "{icon} {n} da verificare"
AVANZAMENTO_FATTA_ONE = "{icon} {n} fatta"
AVANZAMENTO_FATTA_MANY = "{icon} {n} fatte"
AVANZAMENTO_TOLLERATA_ONE = "{icon} {n} tollerata"
AVANZAMENTO_TOLLERATA_MANY = "{icon} {n} tollerate"
AVANZAMENTO_VARIABILE_ONE = "{icon} {n} variabile"
AVANZAMENTO_VARIABILE_MANY = "{icon} {n} variabili"
AVANZAMENTO_RUMORE_ONE = "{icon} {n} rumore"
AVANZAMENTO_RUMORE_MANY = "{icon} {n} rumore"

#: One segment of the verdict strip. {label} = the verdict word, {page} = 1-based, {text} = a snippet.
AVANZAMENTO_SEGMENT_TIP = "{label} · pag. {page}: {text}"
#: A segment whose difference has no words (a link, an attribute). {label}, {text}.
AVANZAMENTO_SEGMENT_TIP_NO_PAGE = "{label}: {text}"
AVANZAMENTO_STRIP_TIP = "Una tacca per differenza, in ordine di documento: clic per andarci."

# -- banners (spec §5.3) ----------------------------------------------------------
#: {n} = marks still to verify, {env} = the generator of the case.
REVISIONE_MARKS_ONE = "✓? 1 modifica da verificare: pubblica su {env} e rigenera il TO-BE (F5)."
REVISIONE_MARKS_MANY = "✓? {n} modifiche da verificare: pubblica su {env} e rigenera il TO-BE (F5)."
#: The same, for a case with no generator chosen. {n}.
REVISIONE_MARKS_ONE_NO_ENV = ("✓? 1 modifica da verificare: pubblica sul generatore e rigenera "
                              "il TO-BE (F5).")
REVISIONE_MARKS_MANY_NO_ENV = ("✓? {n} modifiche da verificare: pubblica sul generatore e "
                               "rigenera il TO-BE (F5).")
REVISIONE_UNMARK_ALL = "Annulla i segni"
REVISIONE_UNMARK_ALL_TIP = "Toglie tutti i segni «fatta» di questo caso: le differenze tornano a contare."
#: Toast after "Annulla i segni". {n} = how many marks were removed.
REVISIONE_UNMARKED = "Segni annullati: {n}"
#: "Annulla i segni" refused. {reason}.
REVISIONE_UNMARK_FAILED = "Segni non annullati: {reason}"

#: Outcome of the verification of the marks against a newer TO-BE.
#: {version} = the TO-BE just compared, {n} = marks checked.
REVISIONE_OUTCOME_HEAD_ONE = "v{version}: verificata 1 modifica segnata"
REVISIONE_OUTCOME_HEAD_MANY = "v{version}: verificate {n} modifiche segnate"
REVISIONE_OUTCOME_RESOLVED_ONE = "{n} risolta"
REVISIONE_OUTCOME_RESOLVED_MANY = "{n} risolte"
REVISIONE_OUTCOME_UNRESOLVED_ONE = "{n} non risolta"
REVISIONE_OUTCOME_UNRESOLVED_MANY = "{n} non risolte"
REVISIONE_OUTCOME_CHANGED_ONE = "{n} cambiata ma ancora diversa"
REVISIONE_OUTCOME_CHANGED_MANY = "{n} cambiate ma ancora diverse"
#: {head} — {parts}  (parts joined by ", ")
REVISIONE_OUTCOME = "{head} — {parts}"

REVISIONE_TWO_WAY = ("Verdetto a due vie: manca l'AS-IS, quindi ogni differenza dal target è «da "
                     "fare» e le regressioni non si vedono. Genera l'AS-IS per il confronto completo.")
#: The same pill when the case has an AS-IS but it has no extractable text (R49).
REVISIONE_TWO_WAY_NO_TEXT = ("Verdetto a due vie: l'AS-IS non ha testo estraibile, quindi ogni differenza dal "
                             "target è «da fare» e le regressioni non si vedono. Rigenera l'AS-IS per il "
                             "confronto completo.")

# -- profile menu (spec §7.1) -----------------------------------------------------
PROFILO_TOLLERANTE = "Tollerante"
PROFILO_STRETTO = "Stretto"
PROFILO_SOLO_TESTO = "Solo testo"
#: The case follows its initiative. {profile} = the initiative's profile.
PROFILO_INIZIATIVA = "Come l'iniziativa ({profile})"
#: The header button. {profile} = the profile in use.
PROFILO_BUTTON = "Profilo: {profile} ▾"
#: The header button while the case follows the initiative. {profile}.
PROFILO_BUTTON_INHERITED = "Profilo: {profile} (iniziativa) ▾"
PROFILO_TIP = ("Che cosa conta come differenza. Tollerante: testo, composizione e link. "
               "Stretto: anche stile e spaziatura. Solo testo: solo il testo.")
#: Toast after a profile change. {profile}.
PROFILO_SET = "Profilo del caso: {profile}"
#: set_profile refused. {reason}.
PROFILO_FAILED = "Profilo non cambiato: {reason}"

# -- fix round 1 (R28): compact strips, pills in the bar ---------------------------
#: The folded outcome in the bar. {version}, {resolved}, {checked}.
REVISIONE_OUTCOME_SHORT = "v{version}: {resolved}/{checked} risolte"
#: The two-way pill of the bar (its tooltip is REVISIONE_TWO_WAY).
AVANZAMENTO_TWO_WAY = "⚠ a due vie"
#: The action next to the two-way pill.
AVANZAMENTO_GENERATE_ASIS = "Genera l'AS-IS"
#: A review action refused while the case is being compared.
REVISIONE_WAIT_COMPARE = "Attendi la fine del confronto del caso, poi riprova."

# -- the board's "TO-BE contro target" pill (spec §7.4, U5) ------------------------
#: {counts} = the worst state's count text ("▲ 1 regressione"), {pct} = 0..100.
BACHECA_PILL = "{counts} · {pct}%"
#: The summary is of an older TO-BE than the latest. {version}.
BACHECA_STALE = "v{version} · da riconfrontare"
#: First line of the stale pill's tooltip. {version} = the summary's, {latest} = the latest TO-BE.
BACHECA_STALE_TIP = ("Riepilogo di v{version}: l'ultimo TO-BE è v{latest}, aprilo per "
                     "confrontarlo di nuovo.")
#: First line of the stale pill's tooltip when the target or the AS-IS changed after the summary.
BACHECA_STALE_INPUTS_TIP = ("Riepilogo di v{version}: il target o l'AS-IS sono cambiati dopo, "
                            "apri il caso per confrontarlo di nuovo.")
#: A TO-BE and a target, but no comparison saved yet.
BACHECA_NOT_COMPARED = "da confrontare"
#: {latest} = the latest TO-BE.
BACHECA_NOT_COMPARED_TIP = "v{latest} non è ancora stato confrontato con il target: apri il caso."
#: Nothing counts (no difference, or only tolerated / variables / noise): no pill, this text.
BACHECA_NOTHING = "nessuna differenza che conta"
#: First line of the tooltip. {version}, {pct}.
BACHECA_TIP_HEAD = "v{version} contro target · {pct}%"
BACHECA_TIP_TWO_WAY = "⚠ a due vie: manca l'AS-IS"

# -- the minimap beside each document (spec §7.1, U5) ------------------------------
#: Anywhere but on a segment.
MINIMAPPA_TIP = "Una tacca per differenza, all'altezza in cui si trova: clic per andarci."
#: On a segment. {label} = the verdict word, {page} = 1-based.
MINIMAPPA_SEGMENT_TIP = "{label} · pag. {page}"
