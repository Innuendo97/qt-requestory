"""Officina phase 2.5: the side panel of the case view (spec §5, D8, D15,
draft "f25-caso-v2"): the short verdict tabs, the type chips, the groups by
type, the zones summary, the legend behind «?», the collapsed rail and the
zone rails on the page margins.

Owned by ``ui/pages/officina_side_panel.py``, ``officina_type_chips.py``,
``officina_panel_legend.py``, ``officina_types.py`` and
``officina_zone_rails.py``. The verdict words live in ``officina_verdetto``,
the rows' texts in ``officina_elenco``.
"""

# -- verdict tabs, short (the panel is 292 px): {n} = how many -------------------------
PANNELLO_TAB_GUARDARE = "Da guardare {n}"
PANNELLO_TAB_VERIFICARE = "Verif. {n}"
PANNELLO_TAB_FATTE = "Fatte {n}"
PANNELLO_TAB_TOLLERATE = "Toll. {n}"
PANNELLO_TAB_VARIABILI = "Var. {n}"
PANNELLO_TAB_TUTTE = "Tutte {n}"
#: "Tutte" with entries that match nothing now (R30): {n} differences, {k} inactive entries.
PANNELLO_TAB_TUTTE_INACTIVE = "Tutte {n} ⊘{k}"
#: Added to the "Tutte" tooltip when the case has differences of page number / watermark.
#: {n} = how many.
PANNELLO_TUTTE_ARREDO_TIP = "Più {n} di numero di pagina e filigrana, che non contano."

# -- the difference types (D8): short name on the chip, whole name in the tooltip --------
PANNELLO_TIPO_MAIUSCOLE = "Maiusc."
PANNELLO_TIPO_PUNTEGGIATURA = "Punteg."
PANNELLO_TIPO_SPAZI = "Spazi"
PANNELLO_TIPO_NUMERI = "Numeri"
PANNELLO_TIPO_PAROLA = "Parole"
PANNELLO_TIPO_FRASE = "Frasi"
PANNELLO_TIPO_SEZIONE = "Sezioni"
PANNELLO_TIPO_SPOSTAMENTO = "Spostam."
PANNELLO_TIPO_ZONA = "Zone"
PANNELLO_TIPO_LINK = "Link"
PANNELLO_TIPO_ALTRO = "Altro"
PANNELLO_TIPO_MAIUSCOLE_TIP = "Maiuscole e minuscole: cambia solo la forma delle lettere."
PANNELLO_TIPO_PUNTEGGIATURA_TIP = "Punteggiatura: punti, virgole, trattini, virgolette."
PANNELLO_TIPO_SPAZI_TIP = "Spazi: cambia solo la spaziatura fra le parole."
PANNELLO_TIPO_NUMERI_TIP = "Numeri: importi, date, percentuali, codici."
PANNELLO_TIPO_PAROLA_TIP = "Parole: una o poche parole diverse."
PANNELLO_TIPO_FRASE_TIP = "Frasi: una frase intera diversa, in più o mancante."
PANNELLO_TIPO_SEZIONE_TIP = "Sezioni: un blocco intero in più o mancante."
PANNELLO_TIPO_SPOSTAMENTO_TIP = "Spostamenti: lo stesso testo in un altro punto."
PANNELLO_TIPO_ZONA_TIP = "Zone: testo cambiato in header, titolo, footer o spalle."
PANNELLO_TIPO_LINK_TIP = "Link: l'indirizzo di un collegamento."
PANNELLO_TIPO_ALTRO_TIP = "Altro: tutto ciò che non rientra negli altri tipi."
#: A chip's accessible name: {name} = the type's name, {n} = how many in the verdict tab.
PANNELLO_CHIP_NAME = "Tipo {name}: {n}"
#: Added to a chip's tooltip.
PANNELLO_CHIP_HINT = "Clic: mostra solo questo tipo (anche più di uno insieme)."
PANNELLO_CHIPS_NAME = "Filtra per tipo"
#: The chip that shows the types with nothing in the tab (hidden until asked): {k} = how many.
PANNELLO_CHIPS_MORE = "+{k} altri"
PANNELLO_CHIPS_MORE_ONE = "+1 altro"
PANNELLO_CHIPS_LESS = "meno"
#: Its accessible name and tooltip: {names} = the hidden types, comma-separated.
PANNELLO_CHIPS_MORE_NAME = "Altri tipi, nessuna differenza in questa scheda: {names}"
PANNELLO_CHIPS_LESS_NAME = "Nascondi i tipi senza differenze in questa scheda"
#: The group of the differences of the page number and the watermark (they never count).
PANNELLO_GROUP_ARREDO = "Pagina e filigrana (non contano)"
#: A group header: {icon} {name} · {n}; the tooltip says how to fold it.
PANNELLO_GROUP = "{name} · {n}"
PANNELLO_GROUP_TIP = "Clic, Invio o spazio: chiudi o apri il gruppo."
#: Shown when the type chips leave nothing in the tab.
PANNELLO_EMPTY_TYPES = "Nessuna differenza di questi tipi in questa scheda."

# -- the zones (spec §3.2): display names ------------------------------------------------
ZONA_HEADER = "Header"
ZONA_TITOLO = "Titolo"
ZONA_FOOTER = "Footer"
ZONA_SPALLA_SX = "Spalla sx"
ZONA_SPALLA_DX = "Spalla dx"
ZONA_NUMERO_PAGINA = "Numero di pagina"
ZONA_FILIGRANA = "Filigrana"
ZONA_CORPO = "corpo"
#: The zone and the page on a row: {zone} = the zone's name, {page} = 1-based page.
PANNELLO_ROW_WHERE = "{zone} · pag. {page}"
#: The tooltip of a zone rail on the page margin: {zone} = its name, {page} = 1-based page.
PANNELLO_RAIL_TIP = "{zone} · pag. {page}"

# -- the zones summary at the bottom ---------------------------------------------------
#: One zone: {zone} = name, then ✓ (nothing to look at) or {n} (to look at).
PANNELLO_ZONE_OK = "{zone} ✓"
PANNELLO_ZONE_N = "{zone} {n}"
PANNELLO_ZONE_IGNORED = "pag. e filigrana ignorate"
PANNELLO_ZONES_TIP = ("Le zone riconosciute nei documenti: ✓ = nessuna differenza da guardare, "
                      "un numero = quante ce ne sono. Numero di pagina e filigrana non contano "
                      "(si riattivano da Filtri).")
PANNELLO_ZONES_NONE = "Zone: nessuna riconosciuta"

# -- the legend behind «?» ---------------------------------------------------------------
PANNELLO_LEGEND = "?"
PANNELLO_LEGEND_NAME = "Legenda"
PANNELLO_LEGEND_TIP = "Legenda: aspetto dei verdetti, icone dei tipi, zone e tasti"
PANNELLO_LEGEND_VERDICTS = "Verdetti"
PANNELLO_LEGEND_TYPES = "Tipi di differenza"
PANNELLO_LEGEND_ZONES = "Zone (linea a margine della pagina)"
PANNELLO_LEGEND_KEYS = "Tasti"
#: The verdict "arredo": a difference of the page number or the watermark (ruling F3).
VERDETTO_ARREDO = "non conta"
VERDETTO_ICON_ARREDO = "◌"

# -- open / collapsed ---------------------------------------------------------------------
PANNELLO_COLLAPSE = "❯"
PANNELLO_COLLAPSE_NAME = "Chiudi il pannello"
PANNELLO_EXPAND = "❮"
PANNELLO_EXPAND_NAME = "Apri il pannello"
#: The rail's shortcuts: each opens the panel there.
PANNELLO_RAIL_GUARDARE = "Da guardare: {n}"
PANNELLO_RAIL_TYPES = "Aa"
PANNELLO_RAIL_TYPES_NAME = "Tipi di differenza"
PANNELLO_RAIL_ZONES = "▭"
PANNELLO_RAIL_ZONES_NAME = "Zone"
