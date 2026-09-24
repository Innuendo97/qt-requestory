# qtRequestory — UI design (v1)

Stack: **PySide6 (Qt Widgets)**, `PySide6-Essentials >= 6.7` (built with 6.11), **Fusion**
style themed by `ui/theme.py` (see §Visual style). UI language: **Italian**, all strings in
the `ui/strings/` package (one module per page, re-exported: `from qtrequestory.ui import
strings`). `qtrequestory.ui` is the only package that may import Qt. The UI talks to the
core through plain Python APIs (`ui/contracts.py` ↔ `core/facade.py`, see
`docs/DESIGN-core.md`) and receives progress as core events converted to Qt signals.
Widgets are dumb; presenters hold state.

This document describes the code as it is. When the code and this file disagree, one of
the two is a bug.

## Navigation

Top app bar (`ui/app_bar.py`) + `QStackedWidget` + status bar (redesign option A — the
user's choice). The width goes to the pages; the sync state sits where it is seen.

```
+--------------------------------------------------------------------------------------+
| [icon] qtRequestory   Ricerca  Sincronizzazione    (● coll oggi 11:24 · ● svil mai)  ⚙  ⓘ |
|                       ‾‾‾‾‾‾‾                                                        |
+--------------------------------------------------------------------------------------+
|                                   page                                               |
|                                                              [JSON copiato · 157 KB] |
+--------------------------------------------------------------------------------------+
| status bar: transient hints ("Sincronizzazione coll 3/48…")                          |
+--------------------------------------------------------------------------------------+
```
- Pages are registered in one list in `ui/main_window.py`:
  `PAGES = [PageSpec(key, label, icon, factory, placement)]`, `placement` = `"tab"` (labelled
  tab with icon, accent underline when current) or `"icon"` (icon button on the right,
  label + shortcut as tooltip: "Impostazioni (Ctrl+,)"). Order: Ricerca, Sincronizzazione
  (tabs), Impostazioni ⚙, Info ⓘ (icons). A future page = one tuple + one widget. **No
  disabled placeholders.** A page module that fails to import degrades to a label "La
  pagina «…» non è disponibile in questa versione." — the shell always starts.
- Default page: **Ricerca**, focus in the omnibox (`initial_focus()`).
- **Status chip** (right of the bar, clickable → Sincronizzazione): one toned dot + "env
  when" per enabled environment ("coll oggi 11:24", "svil mai", "svil non
  raggiungibile", "coll in corso"), fed by the sync page's `state_changed(list[(env, tone,
  text)])` → `MainWindow.set_sync_state`. The dot uses **the same badge as the env card**
  (`sync_badge.badge_for`), so chip and card can never disagree: `ok` = aggiornato,
  `neutral` = mai sincronizzato / in corso / in attesa, `warn` = everything that needs a
  look (da aggiornare, N da scaricare, non raggiungibile, errori), `bad` = only days
  purged before they were downloaded ("svil 1 giorno perso"). For pending/lost days the
  chip text is the badge text. After wiring the page hooks the shell calls each page's
  optional `emit_initial_state()`, so the chip is right from the first frame.
  A scheduled `--sync` changes the state behind the window's back, so the shell also runs
  every page's optional `refresh_sync_state()` every `SYNC_STATE_REFRESH_MS` (60 s) and
  whenever the window is activated: Sincronizzazione re-reads `env_status` (and the cards'
  listing when on screen) and re-emits the chip — no lock peek, no `schtasks`, skipped
  while a sync of ours runs.
  `set_sync_summary(text)` remains for a page that only has one line.
- **Page titles**: Sincronizzazione, Impostazioni and Info open with a `pageTitle` label.
  Ricerca has none on purpose: the tab already names it and the results need the height.
- **Window title** = "qtRequestory — {context}" via `MainWindow.set_context`; Ricerca sets
  "{env} · {fdi[:8]}" for the selected call and clears it when nothing is selected.
- **Leaving a page**: `MainWindow.show_page` first asks the current page's optional
  `can_leave()`; Impostazioni with unsaved changes answers through a Salva / Scarta /
  Annulla dialog, and False keeps it on screen (the tab check is put back).
- **Status bar**: transient hints only (`set_status`, 4 s) — progress of a running sync
  ("Sincronizzazione coll 3/48…", "Indicizzazione 2/5…"), "Operazione «…» già in corso."
  when a job is refused. **Toasts** (`ui/toast.py`, `MainWindow.show_toast(text, tone,
  ms=2500)`) carry confirmations such as copy/save: a frame bottom-right of the content,
  16 px from the edges, mouse-transparent, never wider than the window (long text elided in
  the middle), replaced (and its timer restarted) by the next one, fading unless the app
  property `reduce_motion` or the system animation setting says otherwise. Pages reach both
  through duck-typed `getattr(window, …)`.
- Internal job names never reach the user: `quit_dialog.job_label(name)` maps every
  `workers.JOB_NAMES` entry to Italian ("Aggiornamento indice", "Verifica
  raggiungibilità", "Spostamento degli originali nel Cestino"…); a test pins the two lists
  together.
- **Import dialog**: `MainWindow.open_import(sources=None, on_closed=None)` is the one entry
  point (banners, Impostazioni, wizard). `sources` is a list of folders, `None` standing for
  the mirror itself. While `mirror_root` is invalid it opens nothing and puts the reason in
  the status bar (the 1.0.0 gate: nothing is imported into an invalid archive).

## Keyboard shortcuts

| Keys | Where | Action |
|---|---|---|
| Ctrl+1 / Ctrl+2 | window | Ricerca / Sincronizzazione |
| Ctrl+, | window | Impostazioni |
| F1 | window | Info |
| Ctrl+Shift+S | window | Sincronizza ora (switches to Sincronizzazione) |
| Ctrl+L | Ricerca | focus the omnibox with the FDI chip back in the text, selected |
| Ctrl+K | Ricerca | the same for the template key (ambiguous tokens then count as keys) |
| F5 | Ricerca | run the search again |
| Enter | omnibox | turn the text into a chip and search |
| Enter / double-click | results table | open the call in the editor |
| Ctrl+C | Ricerca (not in a text field) | copy the **full** pretty JSON body |
| Ctrl+Shift+C | Ricerca | copy the selected row as TSV (`giorno ora template_key fdi n_doc bytes`) |
| Ctrl+S | Ricerca | Salva con nome… |
| Ctrl+O | Ricerca | open in the editor |
| Ctrl+Shift+O | Ricerca | write the file and open its folder |
| Ctrl+F | preview | find bar (Enter next; Esc closes) |
| Space | omnibox | turn the typed token into a chip |
| Backspace (empty) | omnibox | remove the last chip |
| Esc | omnibox | clear the text, then the chips |
| Down (empty) | omnibox | recent searches |

The Ricerca shortcuts are `QShortcut`s on the **page** (`WidgetWithChildrenShortcut`,
`ui/pages/search_actions.py`), so they work with the focus on the results table; the
preview pane binds none of them (two bindings for one key in one focus chain make Qt fire
neither). A text field keeps its own Ctrl+C: `QLineEdit` and the body editor claim it via
`ShortcutOverride` — in the body a selection is copied, no selection means the whole body.
Enter is not a page shortcut on purpose: it would steal Enter = [Cerca] from the bar. The
context menu shows the same shortcuts (display only).

## First-run wizard (`QWizard`, 3 pages)

Shown when `config.is_first_run()`; also from Impostazioni → Avanzate → "Riesegui
configurazione iniziale" (`MainWindow.rerun_wizard`, which then broadcasts the new
configuration to every page and starts the sync if asked). A cancelled wizard writes
nothing: `load_config` never creates `config.json`, so the next launch is still a first run
(regression test with the real `ConfigService`).

Every page draws its own header (`ui/wizard_step.py`): the app icon at 48 px, the page
title, and a muted "Passo i di 3" (the pages leave `QWizardPage.title()` empty, so Qt draws
no banner of its own). Buttons read Indietro / Avanti / Fine / Annulla; [Avanti]/[Fine]
use the primary role. Closing the wizard in any way (`done`) cancels the jobs its pages
started (file count, reachability, task status).

1. **Archivio e strumenti** — a two-line intro (what the tool does; "Consiglio: scegli una
   cartella su un disco locale capiente, non una cartella sincronizzata nel cloud.").
   Cartella dei log: default `%USERPROFILE%\qtRequestory\logs`, [Sfoglia…]; must be
   writable. If it already contains `<env>/YYYY/MM/*.txt`: "Trovati N file di log già
   presenti: verranno indicizzati, non riscaricati." (`count_local_files(root)` in a
   worker, "conteggio…" meanwhile). **Import offer** (`ui/wizard_import.py`, job
   `wizard-archive-report`: `archive.report(folder, canonical_root=folder)`, so the logs
   already in place do not count): when the folder holds logs outside the structure,
   [x] "Trovati N log da importare: li importerò alla fine" (on by default); "Hai già dei
   log altrove? [Scegli cartella…]" queues one more folder ("<path>: N log da importare
   alla fine", [Non importare]). The count is an estimate on purpose: environments are
   asked on page 2, so a log with an unknown env still counts; the dialog rescans with the
   saved configuration before copying. Notepad++: the configured one on a rerun, else
   detected, [Sfoglia…]; not found → "i file verranno aperti con l'applicazione
   predefinita".
2. **Ambienti** — table [Attivo | Nome | URL] with [Aggiungi] [Rimuovi] [Importa da file…].
   Pre-filled with what is already configured (rerun); else from
   `find_sidecar_environments(exe_dir)` (an `environments.json` next to the exe); else
   empty with the hint "Chiedi al collega il file environments.json oppure inserisci nome
   e URL". Empty cells show a grey placeholder ("nome" / "https://…", painted only, never
   data); a new row is highlighted with the theme's selection colour. [Verifica
   raggiungibilità] is optional, never blocking: "Gli ambienti sono raggiungibili solo da
   rete aziendale o VPN Cisco: se ora non lo sono, va bene lo stesso." The check passes
   each **row of the table** to `sync.check_reachable(env)` — the whole `Environment`, URL
   included, never a name: nothing is saved before [Fine], so a probe resolving names
   against `config.json` would find no environments. The same holds in Impostazioni for a
   row edited before [Salva].
3. **Automazione** — [x] Sincronizza automaticamente i log, with the schedule spelled out
   underneath by `schedule_text.schedule_sentence` from the saved `schedule` block ("Ogni
   giorno alle 09:00, riprova ogni ora fino alle 18:00, e al login. Solo se la rete è
   raggiungibile; nessuna password salvata.") — never a second copy of the hours. Ticked on
   a first run; on a rerun pre-checked from `scheduler.status().registered` (asked in a
   worker; the box stays disabled with "verifica in corso…" until it answers). If
   `detect_legacy_task()`: [ ] Rimuovi il vecchio task NginxLogSync — **unticked by
   default** — with "Puoi tenerli entrambi finché non hai verificato che il nuovo funziona:
   non si danneggiano a vicenda". [x] Avvia la prima sincronizzazione al termine, with the
   muted note "La prima sincronizzazione scarica tutto lo storico ancora presente sul
   server, fino all'ultima pulizia: possono essere diversi GB e richiedere parecchio
   tempo." (F9).

On [Fine] (`FirstRunWizard.accept`): save the config (a failure keeps the wizard open and
says why); register the task if ticked (failure → non-blocking info); on a rerun that found
the task registered and the box now unticked, `unregister()` it (failure → info);
`remove_legacy_task()` **only** if its box is ticked, and not when our task was asked for
but could not be registered. The result carries `WizardResult.import_sources`; when there
are any, the import dialog opens **first** and the sync (or the startup tasks) starts only
when it closes, because the sync would hold the lock the copy needs (`run_gui` on a first
run, `MainWindow.rerun_wizard` on a rerun). Then the main window opens on Ricerca, or
starts the sync on Sincronizzazione if requested.

## Sincronizzazione page

```
| Sincronizzazione                                                                   |
| +--------------------------------------------------------------------------------+ |
| | (●━) Sincronizzazione automatica attiva            [Modifica orari] [Sincronizza ora ▾] | |
| |      Ogni giorno alle 09:00, riprova ogni ora fino alle 18:00, e al login ·     | |
| |      prossimo avvio: … · ultima esecuzione: … (esito 0)                  [Annulla]* | |
| +--------------------------------------------------------------------------------+ |
| Trovati 3 log fuori dalla struttura dell'archivio                       [Importa] | <- warn, only if so
| svil: 1 giorno (21/09/2026) è ancora sul server ma non è stato scaricato. [Sincronizza ora] <- warn
| svil: 1 giorno (14/09/2026) è stato ripulito dal server prima di essere scaricato: … <- bad
| +------------------------------------+ +------------------------------------+      |
| | coll  [aggiornato]      host.example | | svil  [1 giorno perso]      host…   |      |
| | Ultima sincronizzazione  oggi 11:23  | | Ultima sincronizzazione  ieri 18:40 |      |
| | Archivio locale  42 giorni · 3,9 GB · dal 27/07/2026 | …                       |      |
| | ■■■■▪▪■■■■■▪▪■■■■■▪▪■■■■■▪▪■■░        | | ■■■■▪▪■■■■■▪▪■✖■■■▪▪■■■■■▪▪■!■░    |      |
| +------------------------------------+ +------------------------------------+      |
| ■ log presente  ▪ nessuna chiamata  ! da scaricare  ✖ ripulito dal server  ⬚ oggi   |
| ▸ Registro dell'ultima esecuzione · 11:24 · completata                              |
```
(* [Annulla] only while a run is in flight.)

- **Auto-sync card** (`sync_auto_card.py`): a switch, the title "Sincronizzazione
  automatica attiva / non attiva", a muted line with the schedule in words
  (`schedule_text.schedule_sentence`, the same sentence Impostazioni shows), the next and
  the last run. `scheduler.status()` runs **in a worker** (it spawns `schtasks` twice), the
  result is cached, and until it answers the card says "verifica in corso…" with the switch
  disabled. The switch registers/unregisters in a worker (job `scheduler`, shared with
  Impostazioni so the two exclude each other); `is_unstable_location(exe)` asks before
  registering ("Registra lo stesso"). `exe_matches == False` → "L'attività pianificata
  avvia un eseguibile diverso (<path>). [Aggiorna]". Any failure — status, register, a
  registration refused because Impostazioni is updating the task — is a persistent warn
  banner with [Riprova]. [Modifica orari] opens Impostazioni › Sincronizzazione
  automatica (`show_section("automation")`).
- **[Sincronizza ora ▾]** (primary) always = `force=True`; its menu: Tutti gli ambienti ·
  Solo <env> per environment · Anteprima (senza scaricare) (dry run). Ctrl+Shift+S does
  the same as the button.
- **Import banner** (`pages/import_banner.py`, warn): "Trovati N log fuori dalla struttura
  dell'archivio · [Importa]" while the mirror folder itself holds `importable` or
  `needs_env` files; [Importa] opens the import dialog on the mirror. Same banner on
  Ricerca. The count comes from the shared `ArchiveWatch` (§Import).
- **Coverage banners** (`pages/sync_banners.py`, `CoverageBanners`, same height):
  - *pending* (warn, `syncBanner`): "svil: N giorni (dates) sono ancora sul server ma non
    sono stati scaricati." with its own [Sincronizza ora], which syncs only the envs with
    pending days and is disabled while a run is on or the scheduled task holds the lock;
  - *lost* (bad, `syncBannerBad`): "…sono stati ripuliti dal server prima di essere
    scaricati: non recuperabili." — nothing to click.
  Singular forms and "e altri N" are handled; the sentences come from
  `sync_format.pending_days_text` / `lost_days_text`.
- **Env cards** (`env_card.py`, `QFrame[role=card]`, 2 columns when wide enough, else 1):
  name, badge, host (mono, muted); "Ultima sincronizzazione" (+ "· N file scaricati"),
  "Archivio locale" ({n} giorni · {size} · dal {first}), "Indice: N file da indicizzare"
  when there is a backlog, and the **30-day coverage calendar** (`coverage_strip.py`): one
  square per day, drawn from the core's `CoverageDays` by `day_kinds` (plain Python) with
  theme tokens, each with a tooltip "dd/MM/yyyy: …":

  | kind | look | tooltip / legend |
  |---|---|---|
  | `present` | ok fill | presente / log presente |
  | `empty` | muted grey fill | nessuna chiamata (a 0-byte day) |
  | `pending` | warn fill | sul server: da scaricare / da scaricare |
  | `lost` | bad fill | ripulito dal server prima di essere scaricato / ripulito dal server |
  | `unknown` | `neutral_bg`, dashed muted edge | non verificabile (a weekday nobody ever listed) |
  | `weekend` | grey | weekend (a weekend day the core says nothing about) |
  | `today` | dashed outline | oggi (arriva domani) |
  | `before` | empty outline | prima dell'inizio dell'archivio |

  Weekends follow the core like any other day (a weekend with traffic that is not local is
  pending/lost); `weekend` is only for a weekend with no file and no listing, so that before
  the first 1.1.0 sync the strip is not filled with dashed "non verificabile" squares. One
  legend under the grid (`CoverageLegend.set_kinds`) shows only the kinds some card draws;
  each swatch and its label sit in one box, so a hidden item leaves no gap.
  "Archivio locale" counts only days with calls (`EnvStatus` drops 0-byte files); "dal
  {first}" is `CoverageDays.first_local`, which may be a 0-byte day.
- **Badges** (`sync_badge.badge_for(status, running=, queued=, reachable=, failed=,
  pending=, lost=)`, one rule for card and chip; priority: in corso > in attesa > non
  raggiungibile > errori > "1 giorno perso" / "N giorni persi" > "N da scaricare" >
  aggiornato / da aggiornare / mai sincronizzato). Tones `ok` / `warn` / `neutral`, and
  `bad` **only for lost days**: an unreachable endpoint is the normal state outside the
  VPN, so it is never red. A lost day keeps the red badge while it is inside the 30-day
  window.
- **During a run** the environment being processed shows its own progress inside its card:
  current file + size, a bar, "file i di N · done/total", "8,2 MB/s · circa 2 min
  rimanenti" (total from `RemoteIndexRead.bytes_to_download`); the queued ones say "in
  attesa"; the index phase shows in the same card. The status bar carries
  "Sincronizzazione <env> i/n…".
- **Outcome line**: "Sincronizzazione completata" only when every env is ok/fresh;
  otherwise "Completata · svil non raggiungibile · coll con 2 errori" (warn tone); "Nessun
  ambiente raggiungibile: riprova quando sei in VPN"; "Anteprima completata: nessun file
  scaricato"; "Sincronizzazione annullata".
- **Reachability** is probed when the page is shown (`check_reachable` per enabled env in a
  worker, at most once every 5 minutes), so "non raggiungibile" is a resting state, not
  only the leftover of a failed run.
- **Registro**: collapsible, collapsed by default, header "Registro dell'ultima esecuzione
  · {ora} · {esito}", opened automatically when a run ends badly; `theme.mono_font()`,
  max 2000 lines, prefilled with the `sync.log` tail. The lines are the core
  `LoggingSink`'s own wording (Italian, sizes by `events.format_size`), and a sync started
  here is teed into `sync.log` too (`sync_job.py`), exactly like the scheduled `--sync`.
- **Lock held by the scheduled task**: polled every 2 s **only while the page is visible**
  (`showEvent`/`hideEvent`) with the read-only `SyncApi.lock_holder()` (core
  `lock.peek_holder`, never takes the lock). While someone else holds it: "Sincronizzazione
  in corso dall'attività pianificata…" and [Sincronizza ora] disabled. The peek never gates
  `start_sync` itself: if the core finds the real lock busy it runs nothing and the page
  reports "non eseguita".
- **Close while a sync or an index job runs** → "Sincronizzazione in corso: 12 di 48 file.
  Interrompere e uscire?" [Interrompi ed esci] [Continua] (the index job gets its own text).

## Ricerca page

```
| [coll ▾] [🔍 FDI 1a2b3c4d ✕  aggiungi una template key…      ] [esatta|contiene] [7 gg|30 gg|90 gg|📅] [Cerca] |
| 5 chiamate · 1 FDI · 3 giorni · ordinate dalla più recente | log coll dal 15/09 al 18/09   [Raggruppa per FDI] |
| Trovati 3 log fuori dalla struttura dell'archivio                                          [Importa] | <- only if so
| 2 giorni da scaricare in coll · 1 giorno non recuperabile                   [Vai a Sincronizzazione] | <- only if so
+-----------------------------------------------+------------------------------------------------+
| Quando      Template key            Doc  Dim. | 20260918_aaaaaaaa-…_MOD_TEST_A.json            |
| ▾ aaaaaaaa-1111-… · 18/09/2026 10:38:31 · 5 chiamate | [Apri in Notepad++] ⧉ 💾 📂      JSON | Dettagli |
|   18/09 10:38:31  MOD_TEST_A          5  1 KB |  {                                            |
|   18/09 10:38:28  MOD_TEST_B          3  1 KB |      "documents": [ …                         |
```

- **Bar** (one full-width row, outside the splitter, so it never sets the page's minimum
  width): Ambiente `QComboBox` (last used remembered, `search/env`) · **omnibox** · key
  mode · period · [Cerca] (primary; disabled with a tooltip until an FDI or a key is there;
  "Cerca…" and disabled while a search runs — no lingering status-bar message).
- **Omnibox** (`search_omnibox.py`): one field for FDI, template key and entry names. What
  is typed or pasted becomes a **chip** — "FDI …" and/or "KEY …", each with ✕ — on paste,
  Space, Enter, focus-out or a completer pick. Classification (`search_paste.
  classify_token`): hex+dashes that read like the start of a uuid (a dash, ≥ 8 hex
  digits, or digits and hex letters mixed) → FDI (lowercased); letters/digits/underscores
  → key (uppercased); after Ctrl+K ambiguous tokens are keys. Pasting an entry name
  (`<fdi>_<KEY>_<id16>.json`, a `### …` header, even with its body line) fills both
  chips; a name without an FDI (`correlationId_vuoto_…`) fills only the key. Key
  completer over `list_template_keys(env)` (contains, case-insensitive). Text not yet a
  chip still counts when [Cerca] runs.
- **Key mode**: segmented "esatta" (**default**, the user's decision) / "contiene",
  mapped to `SearchQuery.key_mode` `"exact"` / `"contains"`, persisted in QSettings
  `search/key_mode` (also editable in Impostazioni › Ricerca).
- **Period**: segmented 7 gg / 30 gg / 90 gg (default from `default_window_days`) + a
  calendar button opening a popup with Dal / Al `QDateEdit`s and [Applica]; while a custom
  range is active the calendar button is checked and its tooltip shows the range.
  Configuration changes do not reset the user's period.
- **Recents**: the last 10 searches (env, fdi, key, mode) in QSettings `search/recent`
  (JSON); shown in the start state as clickable rows and as a menu on Down in an empty
  omnibox. A recent of a no-longer-enabled env says so instead of searching.
- **Meta line**: summary "{n} chiamate · {n} FDI · {n} giorni · ordinate dalla più
  recente" (the tail follows the active sort: "ordinate per {colonna}") | coverage "log
  {env} dal {first} al {last}" (tooltip: today's calls arrive tomorrow) | [Raggruppa per
  FDI] (checkable, QSettings `search/group_by_fdi`, **default on**).
- **Coverage warning** (`search_meta.GapBanner.set_gap(env, pending, lost)`): counts
  `coverage_days(env).pending` + `lost` only — "1 giorno da scaricare in coll", "2 giorni
  da scaricare in coll · 1 giorno non recuperabile", "N giorni non recuperabili in svil" —
  + [Vai a Sincronizzazione]. Warn tone, `banner="bad"` as soon as one day is lost; the
  tooltip lists both groups ("Ancora sul server, da scaricare: …" / "Ripuliti dal server
  prima di essere scaricati: …"). A mirror that simply stopped syncing, with no listing
  memory, is not a hole here (the Sincronizzazione badge "da aggiornare" says it). A muted
  "Indice in aggiornamento… N file non sono ancora ricercabili." shows while `index.plan`
  has a backlog.
- **Import banner**: the same `ImportBanner` as Sincronizzazione.
- **Results** (`search_results.py` + `results_model.py`, a `QTreeView`):
  - *grouped*: one row per FDI, "{fdi completo} · {dd/MM/yyyy HH:mm:ss} · {n} chiamate"
    spanning the columns, expanded; children Quando (HH:mm:ss) · Template key (mono) · Doc
    · Dim. Calls without an FDI form a "senza FDI" group.
  - *flat*: Quando ("dd/MM HH:mm:ss") · Template key (mono) · FDI (mono, whole) · Doc · Dim.
  - Headers left-aligned, numbers right-aligned; the key column sized to its contents up
    to 420 px and elided in the middle (keys differ at both ends); sizes in whole KB with
    the Italian thousands separator (`format_size(whole_kb=True)`, rounded up); "—" where
    the log has no value, "?" where it could not be read. Header click sorts.
  - **Preselection** after every search (rows arrive newest first): for an **FDI-only**
    search the entry with the most documents on the newest day
    (`pick_best(hits, prefer_most_documents=True)`, the one that holds the whole pratica —
    what README promises); otherwise the newest call.
  - **Drag out**: dragging a call hands out a real `.json` file (written on drag start,
    busy cursor meanwhile; an identical file already in the output folder is reused).
- **Row context menu** (icons + shortcuts shown): Apri in Notepad++ / Apri nell'editor ·
  Salva con nome… · Copia JSON · — · Copia FDI · Copia template key · Cerca solo questo
  FDI · Cerca solo questa template key · — · Apri cartella del log del giorno.
- **States** (`search_states.py`, an icon, a title, left-aligned hints, optional buttons;
  never a modal; the preview half is hidden while one shows):
  - *start*: "Incolla un FDI, una template key o un nome file .json", what can be
    pasted, the recent searches, the shortcut hints;
  - *no results*: "Controlla l'ambiente, il periodo e i filtri." + if the window ends
    today "Le chiamate di oggi arrivano domani con il file YYYYMMDD.txt."; an FDI shorter
    than 8 chars → "Prova con l'FDI completo."; an **exact** key search → "La template key
    deve essere completa: scegli la key dall'elenco oppure passa a «contiene»."; window
    under 90 days → [Allarga a 90 giorni];
  - *no log* for the env → [Vai a Sincronizzazione]; when the mirror has files but the
    index is empty (e.g. after a schema upgrade) "L'indice è in ricostruzione." instead;
  - *no environments* enabled → the bar is disabled, [Apri Impostazioni].
- **Preview pane** (`preview_pane.py`, `preview_body.py`, `preview_details.py`),
  selection → worker, debounced, superseded requests dropped:
  - row 1: the output file name (`output_name(hit)`, mono 600, elided in the middle, full
    name in the tooltip, "Copia nome file" in its context menu);
  - row 2: primary [Apri in Notepad++] — or "Apri nell'editor" when the configured /
    detected editor is not Notepad++ — then icon buttons Copia JSON (Ctrl+C), Salva con
    nome… (Ctrl+S), Apri cartella (Ctrl+Shift+O) with the shortcut in the tooltip, and a
    right-aligned "JSON | Dettagli" switch;
  - **JSON**: read-only `QPlainTextEdit`, `theme.mono_font()`, `JsonHighlighter` with the
    theme's `code_*` tokens, **cap 4000 lines** with the footer "Anteprima: prime 4.000
    righe di N — apri nell'editor per il body completo"; Ctrl+F find bar searching the
    **full** body (a match past the cap says "trovato oltre la riga 4.000: apri
    nell'editor");
  - **Dettagli**: Ambiente, Giorno, Ora, File di log (+ [Apri cartella]), Dimensione, N.
    documenti, FDI and Template key (mono + [Copia] + [Cerca solo questo…]), Nome chiamata;
  - Copy/Save/Open/Drag always use the FULL body. Confirmations are toasts ("JSON copiato ·
    157 KB", "Salvato: <name>"); after Apri the status bar says "Aperto in Notepad++" /
    "Aperto nell'editor" / "Aperto con l'applicazione predefinita" — never naming a
    program that did not open. Apri cartella reuses an identical file already in the output
    folder instead of writing a `_<call_id>` duplicate.
- Output contract: the preview/copy/save/open text is exactly `extract.pretty_json(body)`,
  starts with `{\n    "documents": [`; the UI never adds headers or comments.
- After a sync, index, import or recycle job the page refreshes coverage, keys and the
  backlog banner (`on_data_changed`) and **keeps** the current results and period.

## Impostazioni page

Title, a section list on the left (styled like the app's navigation), one section at a time
on the right inside a `QScrollArea`. Each section is a card with a `QFormLayout` (muted
labels left). Paths are `PathField`s: a mono path elided in the middle (full path in the
tooltip) + [Sfoglia…] + an [Apri cartella] icon — picked, not typed.

1. **Aspetto** — Tema: segmented **Sistema / Chiaro / Scuro**, applied **immediately**
   (`theme.save_mode` + `theme.apply`, outside the Save flow, muted note "Si applica
   subito, senza salvare."); [x] Raggruppa i risultati per FDI (`search/group_by_fdi`).
2. **Archivio** — Cartella dei log locali; Cartella file temporanei (empty = "Cartella
   temporanea di sistema", [Usa predefinita]; `config.validate` refuses one that is the log
   folder, inside it or containing it, because old extracted files are deleted
   automatically); **Log** (`pages/archive_summary.py`): "N log in archivio · M da
   importare · K da assegnare · J ignorati" (+ " · C in conflitto" only when there are
   conflicts), from the shared `ArchiveWatch` (the saved configuration, not the form),
   [Dettagli…] (the import dialog on the mirror) and [Importa log da una cartella…] (a
   folder picker, then the dialog); while the saved log folder is unusable the row says
   why and both buttons are off. Indice: "{files} file · {entries} richieste · fino al
   {last}" + [Ricostruisci indice] (confirmation, then job `index` with
   `full_rebuild=True`).
3. **Ambienti** — the table [Attivo | Nome | URL] with Aggiungi / Rimuovi / Importa da
   file… / [Verifica] (probes the rows on screen, not what is on disk — see the wizard) and
   the VPN note.
4. **Sincronizzazione automatica** — Ora di avvio (`QTimeEdit`), Riprova ogni (1–12 h),
   Ripeti per (0–23 h, 0 shown as "nessuna ripetizione"), [x] Esegui anche al login (with
   why it matters: "…il login recupera la sincronizzazione mancata: sul server i log
   restano solo fino alla prossima pulizia manuale."), and "In breve" = the live `schedule_sentence`. A save re-registers the
   task when one is registered; a refused or failed re-registration is a persistent warn
   banner "Impossibile aggiornare l'attività pianificata: …" with [Riprova].
5. **Ricerca** — Periodo predefinito 7 gg / 30 gg / 90 gg; Template key esatta / contiene
   (`search/key_mode`).
6. **Editor esterno** — Notepad++ path, [Sfoglia…] [Rileva].
7. **Avanzate** — File di configurazione (path + [Apri cartella]), [Riesegui configurazione iniziale].

Nothing is written until [Salva]. The **unsaved bar** — "Modifiche non salvate ·
[Annulla] [Salva]", inverted colours, outside the scroll area — appears only while the
form is dirty; errors from `config.validate` are listed above it instead of saving.
Leaving the page while dirty asks Salva / Scarta / Annulla (`can_leave`). Changing the log
folder asks "Vuoi indicizzare i log presenti nella nuova cartella ora?". The page is the
only writer of `config.json` except for `folder_envs`, which the import dialog writes; so
`save()` re-reads `folder_envs` from disk before writing (a stale form would otherwise drop
the assignments), while `errors` and `to_config` never read the file. It emits `config_changed`, which the window broadcasts to
every *other* page's `on_config_changed`. `show_section(key)` (`appearance`, `archive`,
`environments`, `automation`, `search`, `editor`, `advanced`) lets other pages deep-link.

## Import (`ui/import_dialog.py`, `import_report.py`, `import_result.py`, `import_state.py`)

Logs kept in any folder layout are copied into the archive by the core (DESIGN-core
§Archive import); the UI shows the report, asks what the path cannot tell, and runs the
slow calls in the `JobRunner`.

- **`ArchiveWatch`** (`import_state.py`): ONE per `JobRunner`, shared by the two banners and
  the Impostazioni summary. It runs the `archive-report` job (`archive.report()` on the
  mirror + `index.count_local_files()`) and publishes an `ArchiveSnapshot`. It rescans after
  every `sync`, `index`, `import` or `recycle` job (`JobRunner.job_finished`), when the
  configuration is broadcast and when the dialog closes; it never scans while the mirror
  folder is invalid. Banner count = `importable` + `needs_env`.
- **ImportDialog** (`QDialog`, 960×580 so it fits 1366×768), three steps:
  1. *The report* (`import-scan` job, `archive.report(folder)`): a table Percorso |
     Ambiente | Giorno | Dimensione | Stato, the Stato cell "stato: motivo" coloured with
     theme tokens (recoloured on `theme.signals.changed`), a "Mostra" filter by status with
     counts, and a plan line ("Da copiare: 4 log · già in archivio: 1 · in attesa di un
     ambiente: 2 (per ora saltati)"). Folders needing an environment are grouped in a warn
     panel, one combo each ("Scegli…", the configured env names, "Ignora"); a pick saves
     `Config.folder_envs[<ABSOLUTE folder>] = env | "__ignora__"` and rescans. Nothing
     waiting for an environment is ever copied. [Importa] is enabled when there are
     importable or duplicate files (a verified duplicate may go to the Recycle Bin too).
  2. *The copy* (`import` job, exclusive, cancellable): `archive.import_` with a progress
     bar. [Interrompi], Esc and the close box all cancel, and the dialog stays open until
     the job stops. `ArchiveBusy` (a sync holds the lock) goes back to step 1 with the
     reason in a banner.
  3. *The result*: "Copiati N · già presenti M · conflitti K · errori E", notes for an
     interruption, for conflicts and for the index, the errors listed. Then — only for
     `ImportResult.verified` records whose path is NOT inside the mirror (`real_is_within`),
     and never after an interruption — "Vuoi cancellare gli originali? N file, X MB.
     Andranno nel Cestino." [Cancella originali] [Tienili]. A yes passes exactly those
     records to `archive.recycle` in the `recycle` job (exclusive; a refused submit shows
     the busy status), and refusals are listed.
  The touched envs are indexed through `import_state.index_after_import`: the `index` job
  right away, or — when an index is already running — a runner-owned waiter that merges the
  envs and resubmits once when that `index` finishes (successfully or not), so closing the
  dialog loses nothing; while the application is closing nothing is queued and the next
  start indexes the files. `MainWindow` then refreshes every page (`on_data_changed`).
- **Several sources**: the dialog takes a list (the wizard queues the mirror's strays and a
  folder elsewhere); each is scanned only when its turn comes ([Avanti: <folder>], disabled
  while `recycle` runs), so its report already knows what the previous one copied.
- **Jobs**: `wizard-archive-report`, `archive-report`, `import-scan`, `import`, `recycle` are
  in `JOB_NAMES` with labels; `import` and `recycle` are `EXCLUSIVE`, in `DATA_JOBS` (they
  trigger `on_data_changed`) and ask before quitting (`QUIT_IMPORT_INFO`,
  `QUIT_RECYCLE_INFO`: the originals already moved are in the Recycle Bin and can be
  restored, the others stay where they are).

## Info page

Title and four cards: **Versione** (`__version__`, one-line description); **Percorsi**
(configurazione, indice, log applicazione, log sincronizzazione — each mono, elided in the
middle, never wrapped mid-word, with [Copia], [Apri] and an [Apri cartella] icon);
**Indice** (per enabled env "{files} file · {entries} richieste · dal … al …", [Gestisci
indice…] → Impostazioni › Archivio); **Log** (the last 500 lines of `app.log`, read in a
worker; filter Tutti / Avvisi / Errori that keeps a record's continuation lines —
tracebacks — with it; [Aggiorna], [Copia tutto]).

## Concurrency (`ui/workers.py`)

```python
class CancelToken (core)                       # passed to core calls
class WorkerSignals(QObject): started, progress(object), log(str), result(object), error(str, str), finished, cancelled
class Worker(QRunnable): wraps fn(*args, sink=..., cancel=..., **kw); exceptions -> error
class JobRunner(QObject): submit(name, fn, ...) -> Job | None; busy(str); job_finished(str, bool)
    # pool size = len(JOB_NAMES) + SUPERSEDED_HEADROOM (4): one thread per job name plus room
    # for superseded jobs still finishing a blocking call (read_body, one SQLite query).
    # "sync"/"index"/"scheduler"/"import"/"recycle" are EXCLUSIVE: a second submit is refused -> busy(name);
    # every other name supersedes (the older job is cancelled and silenced by _Delivery).
class QtEventSink(QObject): event = Signal(object); __call__(ev) emits   # core EventSink -> Qt signal
```
- `JOB_NAMES` lists every name a page submits under (a test checks it against the pages'
  constants and against `quit_dialog.JOB_LABELS`).
- `job_finished(name, ok)` drives the refresh: after a `DATA_JOBS` job (`sync`, `index`,
  `import`, `recycle`; even a failed one) the window calls every page's optional
  `on_data_changed()`, and closing the window while one runs asks first.
- Progress coalesced to ~10/s. Widgets never touched from workers.
- Which thread runs what (measured in `tests/ui/test_workers.py`, not assumed): `QtEventSink.
  __call__` — the `FileProgress` throttling included — runs on the **worker**; everything after
  `event.emit` runs on the **GUI thread**. `JobRunner` connects `sink.event` to
  `partial(_relay_event, delivery)`, a callable with no receiver `QObject`, and for those Qt
  takes the **sender** as the connection's context: the sink was created on the GUI thread, so
  the emission is queued there. `Worker._emit` calls `_Delivery.send` from the worker instead,
  and `_forward` — a signal on a GUI-thread `QObject` — queues it to the same event queue, so
  progress and result still reach the page in the order the worker produced them.
- Single instance: `QLocalServer` named `qtrequestory-<username>` (overridable with
  `QTREQUESTORY_INSTANCE_KEY` — a pipe name is machine-global, so the test harness gives each
  pytest process its own); a second launch sends `activate` and exits; the first raises its
  window. The headless modes never use it.
- `QSettings` is opened only through `actions.user_settings()`: `QSettings(org, app)`
  hardcodes `NativeFormat` and would write the developer's real registry during tests.

## Startup order

`cli.main`: parse args → a headless mode (`--sync/--index/--find/--task/--version`) runs
the core only and never imports Qt. Otherwise `ui.app.run_gui`:

1. `set_app_user_model_id()` — **before** the `QApplication` exists (see §Visual style);
2. `QApplication`, `configure_application` (names, window icon, `theme.apply` with the
   saved mode);
3. single-instance guard (a second instance activates the first and exits 0);
4. first-run check → wizard; cancelled → exit 0 with nothing written; import sources from
   the wizard → the import dialog opens first, and step 6 waits for it to close;
5. `MainWindow` built (pages, hooks, `emit_initial_state`) and `show()`n;
6. only then, in workers: if the wizard asked for a sync, that sync (it indexes too);
   otherwise `QTimer.singleShot(0, window.startup_tasks)` → `ui/startup.StartupTasks`:
   `index.plan` for the enabled envs, `index.update` only when the plan is non-empty (job
   `index`, so it excludes [Ricostruisci indice]), then — when that job finishes — a
   **non-forced** sync through the Sincronizzazione page without switching to it, skipped
   silently when `lock_holder()` says the scheduled task is syncing. With no enabled
   environment nothing starts.
   With an empty or relative `mirror_root` (`config.mirror_root_errors`, the CLI's exit 2)
   nothing starts either: the window never syncs or indexes into its working directory.
   The same gate refuses [Sincronizza ora] (the run line says why) and [Ricostruisci
   indice]/index updates in Impostazioni, and Ricerca and Sincronizzazione show a warn
   banner (`pages/mirror_banner.py`) with [Apri Impostazioni › Archivio].

This is best effort: the startup sync is dropped if the index job was refused, and it runs
after an index job that was cancelled (see BACKLOG).

## Visual style

`ui/theme.py` owns every colour, applied as **Fusion + a `QPalette` + a generated
application stylesheet** (`theme.apply`, QSS template in `ui/theme_qss.py`). Fusion is the
built-in style that paints everything from the palette; the native `windows11` style took
its accent from Windows (teal on some machines), painted a selected table row as one pill
per cell and ignored most of the palette in dark mode.

**There is no "no QSS" rule.** An earlier version of this file said "windows11 style, no
QSS": that was a misrecording, **never a decision of the user**, whose only request was not
to copy qtkit's style. The look is our own — not qtkit's either.

- **Mode**: Sistema / Chiaro / Scuro, chosen in Impostazioni › Aspetto, stored under
  QSettings `ui/theme` (unknown value → Sistema). In Sistema the theme follows Windows and
  re-applies on `colorSchemeChanged`; for Chiaro/Scuro `styleHints().setColorScheme` is
  set too, so native title bars follow.
- **Tokens** (`Tokens`, two tables `LIGHT` / `DARK`; a test checks WCAG contrast: text ≥ 7,
  muted ≥ 4.5, pills ≥ 4.5, on_accent ≥ 4.5):

  | token | light | dark |
  |---|---|---|
  | bg / surface / surface2 | `#F3F4F6` / `#FFFFFF` / `#F8F9FB` | `#1C1F24` / `#24282E` / `#282C33` |
  | border | `#E1E4E8` | `#363C45` |
  | text / muted | `#1B1F24` / `#5F6B78` | `#EEF1F4` / `#A3ACB7` |
  | accent / accent_hover / on_accent | `#0F6CBD` / `#115EA3` / `#FFFFFF` | `#4CA0E0` / `#6BB3E8` / `#0B1520` |
  | selection / selection_text | `#DCEBFA` / `#1B1F24` | `#1F4468` / `#EEF1F4` |
  | ok / ok_bg | `#0E7A0D` / `#DFF6DD` | `#6CCB5F` / `#1F3A1D` |
  | warn / warn_bg | `#8A5300` / `#FFF4CE` | `#F2C661` / `#433519` |
  | bad / bad_bg | `#B42318` / `#FDE7E4` | `#FF8A7A` / `#4A1F1A` |
  | neutral_bg | `#EDEFF2` | `#3A3F47` |
  | code key / string / number / literal | `#0B5CAD` / `#A31515` / `#0E7A0D` / `#8250DF` | `#8CC4F2` / `#E9A27A` / `#9BD48F` / `#C4A7F5` |

  The accent is **fixed** (`#0F6CBD`, the app icon's blue; its dark-mode variant
  `#4CA0E0`) and does not follow the Windows accent colour. Spacing scale `SPACE = (4, 8,
  12, 16, 24)`.
- Widgets opt into a look with a property, never with their own stylesheet:
  `theme.set_role(w, "pageTitle" | "section" | "muted" | "card" | "primary" | "icon")`,
  `pill="ok|warn|bad|neutral"`, `segment="true"` (segmented buttons: checked = selection
  background + accent border, not an accent fill), `tab="true"`, chips, the app bar
  (`QWidget#appBar`), the unsaved bar. No module outside `theme.py`/`theme_qss.py` writes
  a colour literal or a stylesheet (`tests/ui/test_theme.py` greps for it). Pill and badge
  colours come from the `ok`/`warn`/`bad`/`neutral_bg` tokens — the old rule "grey pills =
  palette Mid" is gone (Mid was invisible in dark mode). Errors and unreachable endpoints
  are `warn`; red (`bad`) appears only for **lost days** (purged before they were
  downloaded): the calendar square, the badge and chip dot, the `syncBannerBad` banner and
  the Ricerca `banner="bad"` warning.
- Icon tint and the JSON highlighter read `theme.tokens()` and re-derive on
  `theme.signals.changed`; `theme.apply` clears the icon cache.
- Fonts: UI Segoe UI Variable Text → Segoe UI; monospace only through `theme.mono_font()`
  (Cascadia Mono → Consolas → the system fixed font) — the JSON, file names, FDIs, keys,
  paths, the registro.
- **Icons**: Fluent UI System Icons (MIT, `ui/icons/LICENSE.md`) as embedded SVG, tinted
  per theme: search, arrow-sync, settings, info, document-arrow-right, copy, save,
  folder-open, calendar, dismiss, text-bullet-list-tree.
- **App icon**: a rounded blue square (gradient `#2B8AE0` → `#0B4F94`) with three log lines,
  the middle one highlighted amber (the call you were looking for), and a white magnifier;
  a hand-tuned `app-16.svg` (fewer lines, bigger lens) for 16 px. `app.ico`
  (16/20/24/32/40/48/64/256) is generated by `scripts/make_icon.py`, used as the exe's icon
  resource **and bundled as data**; `icons.app_icon()` builds a `QIcon` with every size
  (from `app.ico`, falling back to rendering the SVG) and is never tinted.
- **Taskbar**: `run_gui` calls `SetCurrentProcessExplicitAppUserModelID("qtRequestory.App")`
  before creating the `QApplication` (Windows only, failures logged and ignored). Without an
  explicit AppUserModelID the onefile child process was grouped under a generic identity
  and the taskbar showed the default Windows icon; together with the large sizes in the
  window icon, the taskbar now shows ours.

## Testability

- `ui/strings/` is a package, one module per page (`common`, `search`, `sync`, `settings`,
  `wizard`, `about`, `imports`), all re-exported from `qtrequestory.ui.strings`. `tests/ui/test_strings.py`
  also enforces one vocabulary: no English words in user-facing strings, the same labels
  for the same thing on every page, and no module formatting a size by hand — every size
  goes through `events.format_size` / `ui/pages/sync_format.format_size`. A test also
  asserts that no UI string claims the server keeps logs for "circa un giorno".
- `ui/prefs.py` holds the shared QSettings keys (`search/group_by_fdi`, `search/key_mode`,
  `search/recent`) so Ricerca and Impostazioni never import each other.
- `ui/contracts.py`: Protocols + dataclasses for everything the UI consumes from core
  (`ConfigApi`, `SyncApi`, `SchedulerApi`, `IndexApi`, `ExtractApi`, `ArchiveApi`, gathered
  in `CoreServices`) — the core facade
  satisfies them structurally; `tests/fakes/fake_core.py` implements them in memory
  (synthetic hits, scripted sync progress honouring the cancel token, fake task status,
  `set_local_days(env, days, empty=())` / `set_server_days(env, listed=(), seen=())` for the
  coverage states, the real archive discovery/import on a temp tree with a simulated
  Recycle Bin),
  and `tests/test_fake_core.py` checks the fake against the real facade.
- Presenters (`SearchPresenter`, `SyncPresenter`, `SettingsPresenter`) are plain objects
  with a few Qt signals; widgets render and forward.
- `pytest-qt`, `QT_QPA_PLATFORM=offscreen` and isolated INI `QSettings` in
  `tests/ui/conftest.py`. `tests/ui/test_integration_shell.py` builds the real
  `MainWindow` with the real `PAGES` on the fake core (search → preview is a `PreviewPane`,
  the menu's body actions are enabled, double-click opens, Ctrl+C on the table copies the
  pretty body) — the test that would have caught the preview never being installed.
- `scripts/dev/shoot.py` (not shipped) renders every page state offscreen, light and dark,
  on the fake core with isolated settings: `python scripts/dev/shoot.py --size 1366x768
  --out <dir>` (`--only <scene>`, `--page search`, `--modes light`).
