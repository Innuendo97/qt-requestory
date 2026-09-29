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

# -- the compact case bar (phase 2.5, U2: spec §5, D15) ------------------------------
# Owned by ``ui/pages/officina_case_bar.py``: one 36 px bar over the documents; the
# long explanations are tooltips.
#: The "‹" of the bar. {initiative} = the initiative's name.
BARRA_BACK_TIP = "Torna alla bacheca di «{initiative}»"
#: The case's name in the bar. {title} = "KEY · variante", {env} = the generator (or "nessuno").
BARRA_TITLE_TIP = "{title}\nGeneratore: {env}"
#: The AS-IS segment of the version switch.
BARRA_ASIS_TIP = "Prima delle modifiche: la versione generata prima di modificare il template"
#: The chip beside the switch when the version shown has the same text as the AS-IS.
BARRA_SAME_AS_ASIS = "= AS-IS"
#: Its tooltip. {version} = "v1", {env} = the case's generator.
BARRA_SAME_AS_ASIS_TIP = ("{version} ha lo stesso testo dell'AS-IS: nessuna modifica ancora "
                          "pubblicata su {env}")
#: The same, for a case without a generator. {version}.
BARRA_SAME_AS_ASIS_TIP_NO_ENV = ("{version} ha lo stesso testo dell'AS-IS: nessuna modifica ancora "
                                 "pubblicata sul generatore")
#: The primary button.
BARRA_REGENERATE = "Rigenera (F5)"
#: Its tooltip. {env} = the generator.
BARRA_REGENERATE_TIP = "Genera un nuovo TO-BE su {env} (F5)"
#: The filters button without a count (no comparison with filters yet).
BARRA_FILTERS = "Filtri"
#: With a count. {n} = the occurrences the active filters set aside.
BARRA_FILTERS_N = "Filtri ({n})"
BARRA_FILTERS_TIP = ("Filtri del confronto: che cosa è messo da parte (zone, variabili, rumore) "
                     "e non conta come differenza.")
#: The "⋯" menu: the profile submenu. {profile}.
BARRA_PROFILE = "Profilo: {profile}"
BARRA_PROFILE_INHERITED = "Profilo: {profile} (iniziativa)"
#: The "⋯" menu entry that removes every "fatta" mark (enabled while there are some).
BARRA_UNMARK_ALL = "Annulla i segni"
#: A compact pill: {icon} = the verdict glyph, {n} = how many (the full words are its tooltip).
BARRA_PILL = "{icon} {n}"
#: The AS-IS view: its differences from the target are the whole work, drawn as "da fare".
#: {n} = how many.
BARRA_ASIS_TOTAL_TIP = ("AS-IS: {n} differenze dal target, disegnate come «da fare»: è il lavoro "
                        "totale prima delle modifiche.")
#: The chip of an AS-IS made with the case's previous call (click: regenerate it).
BARRA_STALE_ASIS = "AS-IS da rigenerare"
#: The chip of a failed generation (the reason is its tooltip).
BARRA_FAILED = "Generazione non riuscita"
#: The chip of the case's loading notes (the notes are its tooltip).
BARRA_NOTICE = "Avvisi"
#: Accessible names (fix round 1): what a screen reader says for the bare glyphs.
#: {initiative} = the initiative's name.
BARRA_BACK_NAME = "Torna all'iniziativa {initiative}"
BARRA_MORE_NAME = "Altre azioni"
#: The percentage. {pct} = 0..100, {version} = the judged TO-BE.
BARRA_PERCENT_NAME = "Avanzamento {pct}%, v{version} contro target"
