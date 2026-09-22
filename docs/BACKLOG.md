# Backlog — punti noti, non bloccanti

Raccolti dalle review dei singoli task e dalla review finale dell'intero progetto.
La review finale li ha triagati: nessuno di questi tocca l'integrità dell'archivio
(la parte che potrebbe far perdere giorni di log) né la fedeltà del JSON estratto.

## Da fare presto — stessi problemi di fondo, pochi interventi

1. **La UI interroga lo scheduler in modo sincrono.** `SettingsPage` e `SyncPage`
   chiamano `scheduler.status()` sul thread grafico (due processi `schtasks` ognuna),
   alla costruzione della pagina, a ogni salvataggio e dopo ogni job. Inoltre una
   re-registrazione rifiutata viene persa in silenzio e un fallimento non lascia
   traccia visibile. Sistemare `status()` una volta (worker + risultato in cache +
   uno stato di errore visibile) chiude quattro voci.
2. **Il lock viene sondato prendendolo.** `lock_holder()` acquisisce il lock vero e
   `SyncPage` lo interroga ogni 2 s per tutta la vita della pagina, anche quando non
   è visibile: due scritture al secondo nella cartella del mirror, e una finestra in
   cui un run schedulato può vedere il lock occupato e saltare un'ora. Un sondaggio
   in sola lettura più lo stop del timer su `hideEvent` chiude entrambe.
3. **Ricerca per template key solo esatta.** `prefix` e `contains` esistono già nel
   core e nessuna UI li seleziona. Oggi c'è solo un suggerimento testuale. Il vero
   rimedio è un controllo "contiene / inizia con / esatta"; prima però va deciso il
   default e misurato `contains` su un indice reale di 48 giorni (l'indice su
   `template_key` non aiuta le ricerche `%...%`).
4. **Primo avvio dopo questo aggiornamento**: lo schema dell'indice è passato a 2, quindi
   il vecchio `index.sqlite` viene buttato. Finché non parte una sincronizzazione, la
   pagina Ricerca dice "Nessun log locale" anche se il mirror è lì. Il task schedulato
   lo sistema entro un'ora; una frase più onesta in quello stato empty costerebbe poco.

## Papercut della pagina Ricerca (tutti piccoli)

- il banner "indice in aggiornamento" ignora i file da rimuovere e non ha un aggancio
  dopo l'indicizzazione;
- cambiare configurazione resetta il periodo scelto dall'utente;
- con zero ambienti abilitati la tabella resta vuota senza spiegazioni;
- lo smart paste accetta un nome senza FDI e riempie i campi con spazzatura;
- la barra di ricerca (Ctrl+F) cerca solo nelle prime 4000 righe mostrate.

## Robustezza, singoli punti

- `housekeeping` elenca la cartella fuori dal `try`: se sparisce, [Apri cartella] solleva;
- l'import del vecchio `.last-sync.json` non è protetto: un mirror in sola lettura
  interromperebbe tutta la sincronizzazione;
- manca un test sul fallimento di `os.replace` — l'unico modo in cui un download
  completo può ancora andare perso;
- `count_local_files` gira sul thread grafico: il wizard si blocca se si sfoglia una
  cartella molto grande;
- il filtro dei livelli nella pagina Info perde le righe di continuazione di un traceback;
- `SchedulerService.config_source` ha un default che registrerebbe la schedulazione
  sbagliata se qualcuno dimenticasse di passarlo.

## Cosmetici / documentazione

- qualche docstring rimasta indietro (autoindex, EnvironmentsPage, refresh_colors);
- un messaggio di log in inglese tra gli altri in italiano;
- `plugins/tls/qopensslbackend.dll` finisce ancora nell'exe pur essendo inerte;
- nessun controllo che `app.ico` sia aggiornato rispetto a `app.svg`;
- file lunghi (settings_page, preview_pane, wizard_pages) — leggibili, ma sopra la soglia
  che ci eravamo dati.

---

### Voci originali (dal registro di lavorazione)

- Task 2: minor (deferred): `DAILY_NAME_RE` uses `$` not `\Z`; tests import helpers from tests.conftest; autoindex docstring mentions sync behaviour.
- Task 5: minor (deferred): housekeeping listing outside try; input BOM tolerance (utf-8-sig) in pretty_json; empty-string call_id test.
- Task 1: minor (deferred): wrong-typed nested blocks silently defaulted; lenient env-item skip persists on next save (note for wizard); ENV_NAME_RE `$` vs fullmatch; double schema_version coercion warning; weak duplicate-name assertion.
- Task 4: minor (deferred): json_ok=False for valid-JSON-non-object bodies — document on ScannedEntry; blank line under pending header → zero-length body; db.py URI paths.
- Task 6: minor (deferred): _is_under should resolve 8.3 short paths; CSV "N/A"/"" not normalised to None (UI must treat as unknown); ParseError/FileNotFoundError not wrapped in SchedulerError; `description or default` vs `is None`.
- Task 3: minor (deferred): legacy-import save not wrapped in try; state file read as utf-8 not utf-8-sig; holder_info() stale after crash (not a liveness signal — note for Task 7); no finalizer on ProcessLock; SIGTERM race in lock test; HTTPError fp not closed explicitly; O_BINARY for holder line.
- Task 7: minor (deferred): _remove_quietly duplicated in http.py and sync.py; no test for os.replace failure path.
- Task 8: minor (deferred): request_date DESC with distinct values not exercised in the FDI_A ordering test; _hit relies on Row factory; report test-split counts cosmetic.
- Task 8b: parked (deferred, ledgered): `lock_holder()` probes by acquiring the real lock — a 2 s UI poll can, in a tiny window, make a scheduled run log "già in corso" and skip until the next trigger. Ruling: accept for v1 (hourly retries absorb a skipped run); revisit with a read-only probe if it ever shows up in sync.log. Cost if wrong: one missed sync hour.
- Task 8b: parked: facade `check_reachable` returns True for a loose-files-only index while the engine calls that env unreachable. Ruling: harmless (a real listing always has dailies); the engine is the authority.
- Task 8b: minor (deferred): `__protocol_attrs__` private attr in the conformance test; return annotations not compared; jobs.py acquire outside try.
- Task 8c: parked: the fake never emits FileSkipped(present/empty) though it reports those counts — fixing it would rewrite sequences asserted in test_contracts.py. Ruling: leave; UI pages render counts from EnvResult, not from FileSkipped events. Cost if wrong: a UI test counting skip events would need the fake extended.
- Task 9: minor (deferred): main_window.py 369 lines; shortcuts tested via activated.emit not real keypress; colorSchemeChanged reconnected per run_gui; Worker._accepts injects into **kwargs callables; one English log line.
- Deferred to integration task: `SingleInstance` uses a machine-global pipe name, so two concurrent pytest runs (parallel agents) steal it from each other and `tests/ui/test_app.py` can flake. Make the name test-overridable (env var or fixture).
- Deferred to integration task (T15), real user-facing bug: `config.load()` writes config.json with defaults, so CANCELLING the first-run wizard makes `is_first_run()` False on the next launch and the wizard never reappears. Fix in `run_gui`/core (e.g. load without persisting until the wizard finishes, or only write on Fine).
- Task 13: minor (deferred): 388-line pane; setDefault inert on QWidget; refresh_colors docstring; StandardKey alternates; post-error placeholder wording; find bar searches only the capped text.
- Task 14: minor (deferred): double config.load() per page build; _button duplicated across the two pages; set_window_days leaves all buttons unchecked for a non-preset value; no QScrollArea; error list not colour-coded.
- Task 10: minor (deferred): 414-line wizard_pages.py; count_local_files on the GUI thread; reachability job not cancelled on close; tautological default-mirror-root test.
- Deferred to integration task (T15), real bug: `QSettings(org, app)` hardcodes NativeFormat, so `isolated_qsettings` does NOT isolate it — `MainWindow.settings()` writes window geometry into the developer's real registry (HKCU\Software\qtRequestory\qtRequestory) on every test run. Fix in main_window.py (use the format the fixture sets) + conftest.
- Task 12: minor (deferred): _clear_results leaves the NO_RESULTS empty state when switching to another env with logs; on_config_changed resets the user's period; stale banner ignores plan.to_remove and has no post-index hook; exact-key search has no "serve la key completa" hint; smart paste accepts a nameless-FDI entry and fills garbage; zero enabled envs shows a blank table; form is inside the splitter while DESIGN-ui sketches it full-width; context-menu "Incolla" not covered by smart paste (contextMenuEvent route is possible).
- Task 13: minor (deferred): Ctrl+C now needs the body editor focused (a focus proxy would restore pane-wide); repeated "Apri cartella" leaves a duplicate _<call_id> file; one key-press test lacks a clipboard sentinel; 426-line pane.
- Task 14: minor (deferred): settings_page.py still 388 lines vs ~300; lambda error-slot without a context object; multi-line records lose their continuation lines in the level filter.
- Task 10: minor (deferred): EnvironmentsPage class docstring still describes the old sidecar-first rule; a rerun ignores an updated sidecar with no hint; build_config()'s config.load() is outside the try.
- Task 11: minor (deferred): shutdown() marks jobs finished even when waitForDone timed out (now item 6 of Task 15); FileFailed pushes no sample so the rate can go briefly negative; stalled transfer shows 0 B/s; SYNC_AUTO_ON hardcodes the schedule text instead of deriving it from TaskStatus; lock timer polls while the page is hidden; url elision lags one resize; exit codes outside 0-3 read as success; "Non raggiungibile" is never a resting state (check_reachable is never called by the page).
- Task 15: minor (deferred): fnmatch in tests/test_packaging.py::_is_declared lets `*` cross `/`; AppPaths.ensure() does not create --config's parent dir.
- Task 16: minor (deferred): GUI-thread schtasks cost on save (up to 4 subprocesses); no sticky warning after a failed re-registration; SchedulerService.config_source defaults to default_config.
- Task 16: minor (deferred): a refused re-registration in Impostazioni is dropped silently (settings_page.py:319-321) — reuse SETTINGS_SCHEDULE_UPDATE_FAILED or retry once on busy; the shutdown path now runs schtasks on the GUI thread (sync_page.py:445-449); spin ranges still hard-code 1,12/0,23 instead of the new REPEAT_*_RANGE; STATUS_BUSY shows the internal English job name to an Italian user.
- Task 17: minor (deferred): plugins/tls/qopensslbackend.dll still ships; no staleness guard between app.svg and app.ico; the spec's datas glob has no test on its side.
