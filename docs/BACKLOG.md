# Backlog — punti noti, non bloccanti

Raccolti dalle review dei singoli task e dalle review finali. Nessuno di questi tocca
l'integrità dell'archivio (la parte che potrebbe far perdere giorni di log) né la fedeltà
del JSON estratto. Le voci chiuse dal giro "redesign + review fixes" (settembre 2026) sono
state tolte: freschezza della sincronizzazione, lock sondato in sola lettura, ricerca
«contiene», indice che si ripara da solo, anteprima installata, scheduler letto in un
worker nella pagina Sincronizzazione, nessuna scrittura nel registro durante i test, ecc.
La 1.1.0 ha chiuso anche: la falsa regola «il server tiene i log circa un giorno», i
giorni vuoti (0 byte) segnalati come mancanti, la freschezza che non si confermava dopo un
weekend, i file fuori posto nell'archivio che facevano ciclare l'indice, gli avvisi
ripetuti per le copie con a capo CRLF, il BOM e le righe vuote nello scanner (una riga
vuota sotto un header dava un body vuoto più un orfano), la cartella dei file estratti
sovrapposta a quella dei log, i weekend con traffico mai segnalati.

## Da fare presto

1. **Scheduler ancora sul thread grafico in due punti.** Un salvataggio in Impostazioni
   chiama `scheduler.status()` (due processi `schtasks`) prima di ri-registrare
   l'attività, e la pagina Automazione della configurazione iniziale chiama
   `detect_legacy_task()` mentre si apre. Stessa cura già applicata altrove: un worker.
2. **Avvio: indice e sincronizzazione "best effort".** Se il job `index` iniziale viene
   rifiutato (un *Ricostruisci indice* già in corso) la sincronizzazione di avvio salta; se
   l'indicizzazione viene annullata, la sincronizzazione parte lo stesso.
3. **«contiene» non è misurato su un indice reale.** Usa `LIKE '%…%'`, che l'indice su
   `template_key` non aiuta: da misurare su un archivio di qualche mese prima di farne il
   default da qualche parte.
4. **Chiudere la finestra con impostazioni non salvate non chiede nulla** (lo fa solo il
   cambio di pagina).

## Officina

La fase 1 (generazione, confronto del solo testo, visore, consegna) è descritta in README
§Officina, DESIGN-core §Officina e DESIGN-ui §Officina. Il resto del progetto arriva a fasi.

### Fase 2 — confronto a tre vie

- **Verdetto a tre vie**: per ogni differenza, TO-BE contro target combinato con AS-IS
  contro target → *fatta*, *da fare*, *in corso*, *regressione*, *tollerata*; l'avanzamento
  del caso (fatte / (fatte + da fare + regressioni)) e le pillole sulla bacheca. *Segna
  accettato* diventa bloccante (0 da fare, 0 regressioni) invece della conferma di oggi.
- **Allineamento dei blocchi**: pagine e blocchi non si abbinano per indice ma con un
  punteggio pesato (contenuto, posizione, struttura) risolto come assegnamento, con pagine
  inserite e tolte; tabelle confrontate cella per cella; OCR solo come ripiego, segnalato,
  per le pagine con il livello di testo inutilizzabile (oggi un documento misto conta come
  «con testo» e la pagina scansionata esce come differenze normali).
- **Profili di tolleranza** *Tollerante* (predefinito: testo, composizione e immagini
  contano; stile e spaziatura tollerati), *Stretto*, *Solo testo*, per iniziativa e per
  caso; classi `testo`, `composizione`, `stile`, `spaziatura`, `immagine`, `spostato`.
- **Differenze DOM per l'HTML**: testo visibile e struttura (inscriptis + xmldiff),
  confronto esatto degli attributi critici (`href`, `src`), una scheda «DOM» accanto al
  visore.
- **Spostamenti**: un blocco tolto e uno aggiunto con lo stesso testo normalizzato diventano
  una sola differenza «spostato» (in blu; il colore è già previsto negli overlay). Oggi
  escono come «mancante» più «in più».

### Fase 3 — rifiniture

- **Confronto delle immagini**: pHash come filtro veloce, SSIM su ritagli in scala di
  grigi come criterio (tollerante a renderer e antialiasing diversi).
- **Regole di rumore nell'interfaccia**: regex per iniziativa (date di generazione, numeri
  di pratica, codici a barre, marcatori di firma, timestamp) → segnaposto; piccole e
  visibili, mai pulizie globali silenziose. Oggi `noise_rules` esiste in `iniziativa.json`
  ma non viene usato, e numeri di pagina e date escono come differenze.
- **`riepilogo-differenze.pdf`** nella consegna: per caso il verdetto, le differenze
  tollerate con le note, versioni e date (QPdfWriter). Serve il verdetto della fase 2.
- **Minimappa delle differenze** (heat-strip) lungo la barra di scorrimento del visore.
- **Annotazioni**: segnare una differenza «tollerata» con una nota (tasto T), annotarla
  (tasto N), con ↑/↓ e Invio nell'elenco; salvate in `caso.json` e ritrovate dopo una
  rigenerazione (ancora di testo indipendente dalla pagina + tipo).
- **Editor dei predefiniti degli header dell'iniziativa** nell'interfaccia: oggi
  `header_defaults` si scrive a mano in `iniziativa.json` (il generatore lo usa già).
- Rigenerazione in blocco con i verdetti; «Condividi caso anonimizzato» (pseudonimi
  deterministici, elenco dei campi non personali).

### Limiti noti della fase 1

- Il motivo di una generazione fallita vive solo in memoria (il modello salva solo le
  generazioni riuscite): si perde alla chiusura.
- La cache delle estrazioni è solo in memoria (le stampe HTML di Edge invece sono in
  `cache\`): dopo un riavvio il primo confronto rilegge i PDF.
- Edge con un profilo nuovo a ogni stampa impiega circa 3,5 s; un timeout su
  `--headless=new` viene ritentato, quindi il caso peggiore è il doppio del timeout.
- Una chiamata già partita non si interrompe: *Annulla* agisce tra un caso e l'altro, e
  chiudendo la finestra durante un invio lungo l'attesa di `JobRunner.shutdown()` (5 s) può
  scadere.
- Il controllo dei link firmati rifiuta anche un link SAS valido di sola lettura fuori dagli
  attributi di upload (es. in `customData`): più sicuro, e il motivo indica il percorso.
- urllib invia i nomi degli header con le iniziali maiuscole (`Template_Key`): HTTP non
  distingue, ma se il generatore si rivelasse sensibile servirebbe `http.client`.
- `compare_text` ha solo `right_label`: quando a sinistra non c'è il target il servizio
  riscrive la nota a mano (un `left_label` sarebbe più pulito).
- L'eseguibile non è stato rimisurato dopo l'aggiunta di pypdfium2 (`pdfium.dll` ~5,4 MB).
- `officina/delivery.py` (~450 righe) e `officina/service.py` (~560) sono sopra la soglia
  delle ~400 righe (moduli del motore, non dell'interfaccia).

## Codici di uscita e CLI

- `EXIT_CONFIG_ERROR = 2` coincide con il 2 "nessun ambiente raggiungibile" di `--sync`:
  uno script li distingue solo leggendo l'output (documentato in README e DESIGN-core).
- `cli.py` è a ~500 righe, sopra la soglia che ci eravamo dati (la parte archivio è già
  in `cli_archive.py`).

## Archivio, giorni vuoti e importazione (dalla 1.1.0)

- `count_local_files` conta anche i giorni vuoti (0 byte): la riga «N log in archivio» di
  Impostazioni e il conteggio della configurazione iniziale li includono, mentre le schede
  della Sincronizzazione (`EnvStatus`) contano solo i giorni con chiamate.
- `EnvSyncState.oldest_listed` viene salvato ma nessuno lo usa (la classificazione dei
  giorni non ne ha bisogno).
- Dopo l'aggiornamento, finché la prima sincronizzazione non ha letto l'elenco del server,
  i buchi vecchi sono «non verificabile»: avvisi e badge restano muti.
- La Ricerca non avvisa più di un archivio che ha semplicemente smesso di sincronizzarsi
  senza memoria dell'elenco del server: lo dice solo il badge «da aggiornare».
- Un giorno perso tiene il badge rosso (e il punto rosso nel riepilogo in alto) finché
  resta nei 30 giorni del calendario: voluto, ma dura fino a un mese.
- `count_crlf` rilegge a ogni esecuzione un file locale più grande di quello remoto (solo
  per i giorni «shrunk», rari). Se il download della copia remota `.remote-<n>` fallisce,
  l'avviso si ripete a ogni esecuzione.
- `ArchiveWatch` rilegge tutta la cartella dei log dopo ogni sincronizzazione,
  indicizzazione o importazione: poco per un archivio in ordine, cresce con i file fuori
  struttura.
- I file fuori posto dentro la cartella dei log vengono importati ma mai cestinati (tutta
  la cartella dei log è intoccabile): restano lì, ignorati dall'indice, come «già in
  archivio» nel resoconto.
- Il conteggio «Trovati N log da importare» della configurazione iniziale è una stima: gli
  ambienti non sono ancora noti; la finestra di importazione rifà la ricerca prima di
  copiare.
- L'avviso «perso» prende la sua altezza minima una volta sola, alla costruzione, da
  quella dell'avviso «da scaricare» con una riga: se uno dei due testi va a capo (finestra
  stretta, molte date) le due altezze tornano diverse.
- Alcuni test dell'interfaccia di importazione sono stati scritti subito dopo il codice,
  non prima.

## Sincronizzazione e indice

- `last_downloaded` non conta i giorni "shrunk" (solo informativo).
- La riparazione concorrente di un indice corrotto è solo ristretta: se il primo processo
  ha già chiuso, il secondo può ancora mettere da parte un indice nuovo e vuoto (viene
  ricostruito). La soluzione completa richiede un lock di riparazione tra processi.
- Un "database is locked" nel passaggio a WAL ha un solo nuovo tentativo.
- I nomi di entry non UTF-8 finiscono come BLOB in `entries.name`.
- Il pulsante *Sincronizza* può restare grigio se il PID rimasto nel file di lock viene
  riusato da un processo protetto (il controllo "processo vivo" non riesce ad aprirlo e lo
  crede il titolare). La scorciatoia Ctrl+Shift+S funziona comunque: il core prende il lock
  vero e scopre che è libero.
- La finestra e la `--sync` pianificata scrivono entrambe `sync.log` con un proprio
  `RotatingFileHandler`: su Windows la rotazione può fallire mentre l'altro processo tiene
  il file aperto (il log continua sul file corrente, oltre la dimensione prevista).
- `ABBREVIATED_SIZE_RE` ripete a mano la forma di `DAILY_HREF_RE`.
- `replace_with_retry(attempts=0)` solleverebbe `TypeError` (nessun errore da rilanciare).
- `remove_quietly` ha perso la dicitura "file parziale" nel messaggio di log.
- `FakeIndexApi.update()` ignora `envs` (come faceva `plan()`); oggi innocuo.
- Il fake di `check_reachable` non guarda l'URL: coperto dai test d'identità
  sull'`Environment` passato, ma un bug di raggiungibilità lato UI resterebbe mascherato.

## Pagina Ricerca e anteprima

- il banner "indice in aggiornamento" conta solo i file da indicizzare, non quelli da
  rimuovere;
- "trova successivo" oltre il limite di 4000 righe non ricomincia dall'inizio;
- il trascinamento di una riga legge il body in modo sincrono (con cursore di attesa);
- "Incolla" dal menu contestuale del campo non passa dal riconoscimento del nome file;
- `search_actions` chiama metodi privati di `SearchPage`; `KEY_MIN_WIDTH` in
  `search_results.py` è una costante morta;
- alcuni test sono stati scritti dopo la correzione (Important-2 del task 14-16) o sono
  deboli (`test_search_page`, `test_sync_page`); qualche test `stub_exec` lascia un
  `singleShot` pendente.

## Impostazioni, Info, configurazione iniziale

- i percorsi si scelgono solo con Sfoglia (non si possono scrivere) e il percorso
  dell'editor non ha un pulsante per svuotarlo;
- `about_page.py` è a ~405 righe;
- nessun test per "rieseguo la configurazione, tolgo la spunta e poi Annulla" (sicuro per
  costruzione);
- `count_local_files` non rispetta l'annullamento dentro la scansione della cartella;
- i segnaposto grigi della tabella ambienti ci sono solo nella configurazione iniziale;
- `quit_dialog.py` è stato toccato dal task della configurazione iniziale (solo aggiunte).

## Tema e icone

- il test "nessun colore esadecimale fuori da theme.py" non vede `#RGB`/`#AARRGGBB` ed
  esclude i file per nome;
- `resolved_scheme(SYSTEM)` riporta l'override dopo `apply(LIGHT/DARK)` e confronta con
  `is`; `_is_fusion` è fragile;
- `theme_qss` restituisce un percorso relativo se non riesce a scrivere i glifi;
- `app-16.svg` è usato solo per 16 px (non 16/24: scelta visiva); `QImageReader` importato
  localmente in `app_icon`; nessun test con un `.ico` corrotto; `SIZES` duplicato tra
  `make_icon.py` e `icons.py`; nessun controllo che `app.ico` sia aggiornato rispetto a
  `app.svg`;
- l'icona sulla barra delle applicazioni va verificata a mano sull'exe costruito.

## Robustezza, singoli punti

- `SchedulerService.config_source` ha un default che registrerebbe la schedulazione
  sbagliata se qualcuno dimenticasse di passarlo;
- `plugins/tls/qopensslbackend.dll` finisce ancora nell'exe pur essendo inerte;
- file lunghi sopra la soglia (~400 righe): `workers.py`, `main_window.py` (~470),
  `sync_page.py` (~425), `search_page.py`;
- `tests/ui/test_settings_page.py::test_aggiungi_and_rimuovi_edit_the_table` fallisce se
  eseguito subito dopo `tests/ui/test_preview_pane.py` (passa nell'ordine della suite
  completa; c'era già prima della 1.1.0).

---

### Voci originali (dal registro di lavorazione, ancora aperte)

- Task 2: minor (deferred): `DAILY_NAME_RE` uses `$` not `\Z`; tests import helpers from tests.conftest; autoindex docstring mentions sync behaviour.
- Task 5: minor (deferred): input BOM tolerance (utf-8-sig) in pretty_json; empty-string call_id test.
- Task 1: minor (deferred): wrong-typed nested blocks silently defaulted; lenient env-item skip persists on next save (note for wizard); ENV_NAME_RE `$` vs fullmatch; double schema_version coercion warning; weak duplicate-name assertion.
- Task 4: minor (deferred): json_ok=False for valid-JSON-non-object bodies — document on ScannedEntry; db.py URI paths.
- Task 6: minor (deferred): _is_under should resolve 8.3 short paths; CSV "N/A"/"" not normalised to None (UI must treat as unknown); ParseError/FileNotFoundError not wrapped in SchedulerError; `description or default` vs `is None`.
- Task 3: minor (deferred): state file read as utf-8 not utf-8-sig; no finalizer on ProcessLock; SIGTERM race in lock test; HTTPError fp not closed explicitly; O_BINARY for holder line.
- Task 8: minor (deferred): request_date DESC with distinct values not exercised in the FDI_A ordering test; _hit relies on Row factory; report test-split counts cosmetic.
- Task 8b: parked: facade `check_reachable` returns True for a loose-files-only index while the engine calls that env unreachable. Ruling: harmless (a real listing always has dailies); the engine is the authority.
- Task 8b: minor (deferred): `__protocol_attrs__` private attr in the conformance test; return annotations not compared; jobs.py acquire outside try.
- Task 8c: parked: the fake never emits FileSkipped(present/empty) though it reports those counts — fixing it would rewrite sequences asserted in test_contracts.py. Ruling: leave; UI pages render counts from EnvResult, not from FileSkipped events.
- Task 9: minor (deferred): colorSchemeChanged reconnected per run_gui; Worker._accepts injects into **kwargs callables.
- Task 12: minor (deferred): context-menu "Incolla" not covered by smart paste (contextMenuEvent route is possible).
- Task 13: minor (deferred): setDefault inert on QWidget; refresh_colors docstring; StandardKey alternates; post-error placeholder wording; one key-press test lacks a clipboard sentinel.
- Task 14: minor (deferred): double config.load() per page build; _button duplicated across pages; set_window_days leaves all buttons unchecked for a non-preset value; error list not colour-coded; lambda error-slot without a context object.
- Task 10: minor (deferred): tautological default-mirror-root test; EnvironmentsPage class docstring may still describe the old sidecar-first rule; a rerun ignores an updated sidecar with no hint; build_config()'s config.load() is outside the try.
- Task 11: minor (deferred): shutdown() marks jobs finished even when waitForDone timed out; FileFailed pushes no sample so the rate can go briefly negative; stalled transfer shows 0 B/s; url elision lags one resize; exit codes outside 0-3 read as success.
- Task 15: minor (deferred): fnmatch in tests/test_packaging.py::_is_declared lets `*` cross `/`; AppPaths.ensure() does not create --config's parent dir.
- Task 17: minor (deferred): the spec's datas glob has no test on its side.
