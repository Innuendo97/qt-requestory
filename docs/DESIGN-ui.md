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
| [icon] qtRequestory   Ricerca  Sincronizzazione  Officina  (● coll oggi 11:24 · ● svil mai) ⚙ ⓘ |
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
  label + shortcut as tooltip: "Impostazioni (Ctrl+,)"). Order: Ricerca, Sincronizzazione,
  Officina (tabs), Impostazioni ⚙, Info ⓘ (icons). A future page = one tuple + one widget. **No
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
| Ctrl+1 / Ctrl+2 / Ctrl+3 | window | Ricerca / Sincronizzazione / Officina |
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
| Enter / double-click | Officina list, board | open the initiative / the case |
| F5 | Officina case | Rigenera TO-BE (the same `GenerationQueue` as the board) |
| Enter / click | Officina differences list | focus the difference in both viewers |
| ↑ / ↓ | Officina differences list | previous / next row (over the "DA VERIFICARE" header) |
| F / T / V | Officina list or viewer | segna fatta / tollera / non è una variabile (toggles), then the next row |
| Ctrl+Z | Officina case | undo the last review action of this case |
| click / double-click / right-click | Officina highlight | select + mini-bar / segna fatta / action menu |
| Ctrl+wheel | Officina viewer | zoom (the other viewer follows while in sync) |

The Ricerca shortcuts are `QShortcut`s on the **page** (`WidgetWithChildrenShortcut`,
`ui/pages/search_actions.py`), so they work with the focus on the results table; the
preview pane binds none of them (two bindings for one key in one focus chain make Qt fire
neither). A text field keeps its own Ctrl+C: `QLineEdit` and the body editor claim it via
`ShortcutOverride` — in the body a selection is copied, no selection means the whole body.
Enter is not a page shortcut on purpose: it would steal Enter = [Cerca] from the bar. The
context menu shows the same shortcuts (display only).
The Officina's F5 is a `WidgetWithChildrenShortcut` on the case workbench (so it never fires
on the board or on Ricerca's own F5), and opening a case puts the focus inside it so F5 works
at once. The board's Enter is a `WidgetShortcut` on its table.

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

## Officina tab (phases 1 and 2)

The template developer's workbench (README §Officina): initiatives of cases, each case
brought from its AS-IS to the customer's TARGET through TO-BE versions, then delivered to
the testers. The page reaches the Officina **only** through `services.officina`
(`OfficinaApi` in `ui/contracts.py`, DESIGN-core §Officina), plus one lazy call to
`officina.pdf.page_sizes` inside a worker. Importing any `officina_*` UI module never loads
PDFium (subprocess tests); `officina_page` is reached only through the page factory.
Phase 2 (release 1.3.0) turned the case workbench into a verdict-first view: every
difference of a TO-BE is drawn and listed by its **verdict** (DESIGN-core §Comparison
engine), with progress, marks to verify, keyboard actions, a minimap and, for HTML, a DOM
tab. The phase-2 modules are `officina_{progress,strip,banners,verdict_style,minimap,
diffs,difflist,rows,actions_bar,review,undo,judge,compare_jobs,board_pill,noise,
noise_cells,noise_page,dom,dom_map,dom_view,case_docs,case_extras,judged,viewer_input}.py`,
each ≲ 400 lines.

**Structure** — `officina_page.OfficinaPage` (the controller, with the user actions in the
`officina_actions.CaseActionsMixin`) is a `QStackedWidget` with four screens:

```
chooser ──► list ──► board ──► case
(no folder)  Iniziative  ‹ Iniziative   ‹ <Iniziativa>
```

- **Chooser** (`officina_list.RootChooser`) while `workspace_root()` is None: why the folder
  matters (real customer data, local, outside any repository) + [Scegli cartella…]. The
  folder is checked with `officina_root_errors` first (inside or around the log mirror or
  the output folder → refused, the reason in the chooser's banner, nothing created or
  saved), then created and saved as `officina.root` through `services.config.save`; the page
  emits `config_changed`. A OneDrive path is accepted with a warn toast and a persistent warn
  banner on the list; a save error stays on the chooser as a sentence.
- **List** (`InitiativeList`): Iniziativa · Casi · Accettati ("n su m") · Ultima attività
  ("oggi 10:42"); [Nuova iniziativa] [Apri] [Apri cartella] [Cambia cartella…]; the folder
  path above. Enter or double-click opens. Each row carries `Initiative.id` (the folder),
  never the name: two initiatives with one name (a folder copied in Explorer) read
  "Banco (Banco - Copia)" and open their own folder; the queue, the failure reasons and
  the "Aggiungi all'Officina…" choice are keyed on the id too.
- **Board** (`officina_board.Board`), one row per case:
  - *Caso*: the key (bold) and the variant (muted) in `MiddleElidedLabel`s
    (`officina_widgets.py`: elided in the **middle**, never at the end — keys differ at both
    ends — full text in the tooltip); columns are fitted from the cell widgets on show and on
    font/style/DPI/theme changes;
  - *Documenti*: T / A / `vN` tiles, "—" for an empty slot, a `bad` tile when the file is gone
    from disk;
  - *TO-BE contro target* (`officina_board_pill.board_badge`, pure): read from
    `case.review.summary` (`caso.json` → `riepilogo`, saved by the `compare_case` of the
    latest TO-BE when it has text, R48/R49) — the
    board never runs a comparison. The pill shows the **worst state** present
    (regressione > non risolta > da fare > in corso > da verificare > fatta) with its count
    and the percentage ("▲ 1 regressione · 60%"), in the state's `Look.pill` tone, and a
    tooltip with the full breakdown in the case bar's order and words. The counts are the
    case bar's totals rebuilt from the summary (`board_counts`): "non risolte" is
    `summary.non_risolte` as it is (every flagged difference, R44, exact); a mark counts as
    "da verificare" only (the summary counts it in both, R15), taken out of the open
    verdicts mildest first — exact when nothing is marked or one open verdict is present,
    otherwise never milder than the bar (R42). "vN · da
    riconfrontare" (neutral) when the summary is of an older TO-BE than the latest, or the
    target or AS-IS changed after it (an AS-IS generated after a two-way summary, a newer
    AS-IS or target); a muted "nessuna differenza che conta" when nothing counts; "da
    confrontare" with a target and a TO-BE never compared; the phase-1 "manca il target" /
    "manca il TO-BE" otherwise. After a change of the noise rules the pills keep the old
    summaries until each case is compared again (there is no "rules changed at" time);
  - *Ultima generazione*: "oggi 11:05 · svil", "AS-IS …", "in coda…" / "Generazione su
    svil…" (the case's generator), the masked failure reason in `bad`, or "annullata prima
    dell'invio" (muted);
  - *Stato*: aperto / accettato / *da ricontrollare* (warn: a new version after the
    acceptance) / accettato in warn (the latest TO-BE is not the accepted one) / caso.json
    illeggibile.
  A warn banner under the toolbar shows an unreadable `iniziativa.json` (then [Genera AS-IS
  mancanti] and [Rigenera TO-BE selezionati] are disabled: the header defaults are unknown)
  or what loading left out (a null header default). [Rigenera TO-BE selezionati] is also
  disabled while the selection holds a case with an unreadable `caso.json`.
  Toolbar: [+ Caso da ricerca] (switches to Ricerca with a hint toast), [+ Caso da file…],
  [Genera AS-IS mancanti], [Rigenera TO-BE selezionati], [Consegna…], [Regole di rumore…]
  (the initiative's rules and presets, counts on the selected case), [Apri cartella]; a
  "Generazione: n di m" line with [Annulla generazioni] shown only on the board of an
  initiative that has cases in the queue.
- **Case workbench** (`officina_case.CaseView` + the `officina_case_docs` mixin), top to
  bottom (approved draft "caso-fase2" v1/v2):

  ```
  ‹ Iniziativa  MOD_TEST_A · abilitato  [aperto]  Generatore: svil  [Regole di rumore…] [Profilo: Tollerante ▾] [⋯]
  [Rigenera TO-BE (F5)] [Genera AS-IS] [Target…] [Payload e header…]  [Documenti|DOM]  [Segna accettato]
  60%  v3 contro target   ▲ 1 regressione  ○! 1 non risolta  ○ 2 da fare  ◐ 1 in corso  ✓ 6 fatte │ ⊘ 3  {x} 14
       ▮▮▮▮▮▮▮▮▮▮▮▮▮▮ (verdict strip)                       [⚠ a due vie · Genera l'AS-IS] / [v3: 2/3 risolte]
  ✓? 2 modifiche da verificare: pubblica su svil e rigenera il TO-BE (F5).       [Annulla i segni]
  v3: verificate 3 modifiche segnate — 2 risolte, 1 non risolta
  +---- TARGET ----+m+---- [AS-IS|v1|v2|v3] ----+m+-- Differenze con il target --+
  | DocView        | | DocView                   | | tabs, rows, key legend        |
  +----------------+-+---------------------------+-+-------------------------------+
  ```
  The header carries the case's generator, [Regole di rumore…] (the case's own rules) and
  the **profile menu** (`officina_banners.ProfileButton`: Tollerante / Stretto / Solo testo
  / "Come l'iniziativa (…)"; "Profilo: X (iniziativa) ▾" when inherited; it waits while the
  case is being compared, then `set_profile` on the UI thread and a new comparison), then
  a **"⋯" menu** (`officina_case_extras`, R45) with *Azzera tolleranze…*: after a question
  ("… non si può annullare"; no undo entry) `reset_tolerances` clears the case's manual
  tolerances and «non è una variabile», and the same version is judged again; it waits
  ("Attendi la fine del confronto…") while the case is being compared or has queued
  actions. The toolbar is the phase-1 one plus the *Documenti | DOM* switch (HTML cases only). Under it:
  the progress bar, the review strips, the phase-1 notices (a damaged `caso.json`, "Nuova
  versione dopo l'accettazione: da ricontrollare.") and the failed-generation banner. The
  splitter holds TARGET | generated document (with the `VersionSwitch`: AS-IS | v1…vn, the
  newest five, older ones in a "…" menu) | the DOM tab (hidden unless switched on, in place
  of the two viewers) | the differences list, 5 : 5 : 3 on first show; each `DocView` has
  its minimap (m) beside its scroll bar. Everything that changes the case (payload,
  target, status) is disabled while it is queued or running; a case with an unreadable
  `caso.json` can be looked at only; generations are disabled while the initiative's
  `iniziativa.json` is unreadable.
  Documents and comparisons are prepared in the `officina-compare` job
  (`officina_jobs.load_case_docs`: `render_path` + `page_sizes`, then for a TO-BE
  `compare_case`; `compare` only when there is no judged comparison — the AS-IS view, a
  case being generated, a failed judge). A `CompareError` or any worker failure is a
  sentence ("Confronto non riuscito: …"), never a stuck "Preparazione…". After a
  successful generation the right side switches to the new version and the comparison
  refreshes by itself; after a review action only the verdicts are redrawn
  (`show_rejudged`: no reload, no jump to the top). The **AS-IS view** (and the fallback
  when a judge fails) has no verdicts: no progress bar, neutral boxes with the changed
  characters in yellow, the plain list (`DiffPanel.show_comparison`, no tabs, no keys).
  It shows only `Comparison.counting(profile)` for the case's effective profile
  (`CaseDocs.profile`: case → initiative → Tollerante) — variables, noise and the classes
  the profile tolerates are left out, and highlights and the acceptance question follow
  the same filter. Rows are named by operation and class (`officina_judged.
  difference_lines`: "pag. 1 · cambiato · stile", "«…» (stesse parole)" for a style,
  spacing or move, the page count's detail), never «x» → «x»; the count line says "N
  differenze di testo", or "N differenze" when some are not text.
  **HTML without the Edge print** (R45): when a side's print fails (Edge missing or
  failing), a TO-BE is still judged through the DOM (`load_case_docs` marks the side
  `no_print`): each such viewer shows "Stampa dell'HTML non disponibile (<reason>). Le
  differenze sono nell'elenco e nella scheda DOM.", the DOM tab becomes the main view
  (the switch is set to DOM and the sources are fetched), and the list, strip, verdicts and
  actions work as usual. The AS-IS view (no judge) still needs the print and shows the
  error.
  - Regenerating an existing AS-IS asks for a mandatory note (`QInputDialog`
    multi-line); blank or Cancel sends nothing.
  - "Segna accettato" (D2) never blocks, and describes the **latest** TO-BE — the one it
    stamps (`accepted_version` in `caso.json`): its judged comparison when it is on
    screen, else its saved summary — "Restano 1 regressione, 2 da fare, 1 da verificare.
    Segnare il caso accettato lo stesso?" (no question when nothing is open); "L'ultimo
    TO-BE (vN) non è ancora stato confrontato con il target." when it never was; "Il
    confronto non è stato possibile: <note>." when a side has no extractable text (such a
    comparison is never shown as "uguale"); without verdicts, the profile-filtered
    question of the AS-IS view.
  - "Target…" on a case with marks, "non risolte" or a summary first asks
    (`OFFICINA_TARGET_REPLACE`): those are cleared, tolerances and "non è una variabile"
    stay, active only where the text still matches (R29); "No" changes nothing.
- **Verdict looks** (`officina_verdict_style.py`, Qt-free): one `Look` per *state* — the
  verdict refined by the "da verificare" mark and the "non risolta" flag, or the class
  when there is no verdict — naming theme **tokens**, never colours, so viewer, list,
  strip, minimap and board re-derive on a theme switch. Every state is colour + glyph +
  word (never colour alone):

  | state | fill | edge | dash | px | glyph |
  |---|---|---|---|---|---|
  | regressione | `bad_bg` | `bad` | no | 1.5 | ▲ (flagged: ▲!) |
  | non risolta | `warn_bg` | `warn` | no | 1.5 | ○! |
  | da fare | `warn_bg` | `warn` | no | 1.5 | ○ |
  | in corso | `progress_bg` | `accent` | no | 1.5 | ◐ |
  | da verificare | — | `ok` | yes | **2** | ✓? |
  | fatta | — (underline, target side) | `ok` | no | 1 | ✓ |
  | tollerata | — | `muted` | yes | 1 | ⊘ |
  | rumore | — | `muted` | yes | 1 | ~ |
  | variabile | — (underline) | `variable` | yes | 1 | {x} |

  "Non risolta" is a flag (R31, R42): on da fare and in corso the state is `non_risolta`
  (worse than either); a flagged regressione stays `regressione` (never downgraded) with
  the `▲!` glyph and the reason line in the list; a marked difference is "da verificare"
  whatever its flag. A flagged regressione's label reads "regressione · non risolta" (in the
  narrow row pill, in its tooltip). Anything the page draws **on the paper** uses the LIGHT token values
  in both themes (`officina_overlays.PAPER`, R13: the page is white, dark tokens would be
  faint on it); the chrome around it (pills, list, strip, minimap, bars) follows the theme.
  Changed characters (R14): `mark_yellow` sub-rects of the word boxes, proportional to the
  `left_spans` / `right_spans`, plus a 2 px underline in the page's ink colour, so they
  stay visible on a `warn_bg` fill. "Fatta" is drawn only with **Mostra fatte** on (below),
  as a thin `ok` underline on the target side.
- **Progress bar** (`officina_progress.ProgressBar`, `officina_strip.VerdictStrip`; hidden
  while nothing is judged): the percentage (`CaseSummary.avanzamento`, "pageTitle" role),
  "vN contro target", then the pills in the order regressioni · non risolte · da fare · in
  corso · da verificare · fatte and, apart and dimmed, tollerate · variabili · rumore (a
  zero count has no pill). With the judged list at hand the totals are `pill_counts`: each
  difference in its verdict's pill ("da verificare" when marked), and every flagged one
  ALSO in "non risolte", whatever its verdict (R44) — so a difference can be in two totals,
  as the "non risolte" pill's tooltip says; the pills, the outcome strip and the board
  (`board_counts` of the summary, the same counting) agree. The **verdict strip** draws one segment per judged
  difference that has a verdict, in document order, like the `coverage_strip` squares (a
  non risolta amber with a red band; da verificare a dashed green outline); a click selects
  that difference, the tooltip gives verdict, page and text. On the strip's row: the
  two-way pill "⚠ a due vie" (the full warning as tooltip) with a flat [Genera l'AS-IS],
  and the folded verification outcome ("v3: 2/3 risolte").
- **Review strips** (`officina_banners.ReviewBanners`, R28: one line each, at most
  `STRIP_MAX_H` = 28 px, small flat buttons, hidden when empty): *da verificare* (blue)
  while the case has live marks — "✓? N modifiche da verificare: pubblica su <generatore>
  e rigenera il TO-BE (F5)." with [Annulla i segni]; the count is the live marks
  (`live_marks`: dormant marks, R32, left out); *esito della verifica* after the first
  comparison of a TO-BE newer than the marks — "**vM: verificate N modifiche segnate** — X
  risolte, Y non risolte, Z cambiate ma ancora diverse" (zero parts left out; green when
  all resolved, amber otherwise). The outcome lives while the case stays open, on that
  version; the user's next action folds it into the bar's pill; leaving the case forgets
  it. With both strips and the bar, the documents still start at ~38% of a 768 px window.
- **Differences list** (`officina_diffs.DiffPanel`, `officina_difflist`, `officina_rows`):
  "Differenze con il target" and six tabs with counts — *Da guardare* (regressioni, non
  risolte, da fare, in corso; then a dimmed "DA VERIFICARE" group of the marked ones, not
  counted), *Da verificare*, *Fatte*, *Tollerate*, *Variabili*, *Tutte* (noise included;
  "Tutte n ⊘k" when k review entries match nothing any more — `CaseComparison.inactive`,
  explained in the tooltip). Under the tabs, a row of its own holds the checkable **"☐
  Mostra fatte"** (`officina_case_extras`, R45): on ("☑ Mostra fatte"), both viewers'
  `set_show_done(True)` draw the fatte on the target side and in the minimap; clicking the
  *Fatte* tab turns it on. *Da guardare* puts the non risolte first, then document order
  (page, top, left); every other tab is in document order. A row: verdict pill, class glyph
  (Aa testo, ▦ composizione, ¶ stile, ↔ spaziatura, ⇄ spostato, 🔗 link, {x} variabile, ~
  rumore), "pag. N · <operation>", and the **snippet** (R33/R34): the target context around
  the change once (`Diff.context_before/after`, up to 5 words), the target's changed
  characters struck in paper colours (`LIGHT.bad` on `LIGHT.bad_bg`, weight 700), the
  generated ones **bold**, and, when only part of a word changed, on `mark_yellow` with the
  paper ink — "abilitat~~a~~**o**"; when the unchanged parts do not line up, "target →
  generated", each marked; long stretches elided around the change. Notes under the
  snippet: "Prima «…» → ora «…»" for in corso, "Segnata fatta in vN, ma in vM è ancora
  qui." for a flagged row, "Nell'AS-IS era uguale al target." for a regression, the note
  of a tolerance. The key legend sits at the bottom ("↑ ↓ scorri · Invio vai · F fatta · T
  tollera · V non è una variabile"). Selection is shared both ways with the viewers, the
  strip, the minimap and the DOM tab; a difference outside the current tab switches to
  the tab that holds it. A refill after an action keeps the tab and the selected
  difference, or — when it just changed state — the row at the same place. Rows are
  widgets: ~2–3 ms each (BACKLOG: a delegate beyond ~1,000 rows).
- **Actions** (`officina_actions_bar`, `officina_viewer_input`, `officina_review`,
  `officina_undo`; D10 — no long press): a **click** on a highlight selects it (list and
  both viewers: the other document aligns, a halo rings the box) and opens the floating
  **mini-bar** "✓ Fatta F · ⊘ Tollera T · ⋯" under it (above when there is no room, pushed
  in from the page edge, following scroll and zoom; UI chrome, so it follows the theme);
  its buttons flip to "↺ Togli il segno" / "⊘ Non tollerare" on a marked / hand-tolerated
  difference. **Double click** = segna fatta / toglie il segno (nothing on a difference
  that does not count). **Right click** (or ⋯) = menu Fatta · Tollera… · Non è una
  variabile · Copia testo del target · Copia testo generato. **F / T / V** in the list or a
  viewer act on the selected row ("Tollera…" asks an optional note in `TolerateDialog`;
  T and the bar's button tolerate without one). Every request becomes an `Intent` on the
  case's **FIFO queue** (R38: queued, never refused) and runs when the case is free (no
  compare of it running, no action being saved); it is planned only then, against the
  difference found by its **anchor** in the verdicts the previous item left, so F on three
  rows marks three. F / T / V move the selection to the next row of the tab **at once**,
  before the refresh (R40), so F, F, F marks three consecutive rows; on the last open row
  a second F within `REPEAT_GUARD_S` = 1 s is a no-op (it does not unmark). A request keeps
  the version on screen when it was made (for its undo); a "segna fatta" records the
  LATEST TO-BE existing when it runs (R47), so only a newer generation verifies it. The plan (forward calls + the calls that undo
  them, `officina_undo`) is saved in the `officina-review` worker (under the case's review
  lock, then the same version judged again); a **toast** says what was done with
  "Annulla", and **Ctrl+Z** undoes the last action — one stack per case, in memory, an
  entry pushed only after the save succeeded and undone only on the version it was made
  on. Undoing "Annulla i segni" re-marks every removed mark, from a stand-in built from the
  mark when its difference is not on screen. A difference gone by the time its item runs
  is skipped with a status line; leaving the case with items waiting drops them, and says
  so.
- **Worker locks** (`officina_judge`): a case is keyed `(initiative id, case id)`. A
  generation and `compare_case` take turns on the case's lock (a judge never waits for a
  generation: the reload after it judges again); review actions and `compare_case` take
  turns on a second, short **review** lock, so an action never races the verification of
  the marks and never waits for an HTTP call. `judge` takes case then review lock, `act`
  only the review lock: no cycle. The "being generated" state is a counter.
- **Minimap** (`officina_minimap.MiniMap`, one per `DocView`, beside its scroll bar): one
  segment per difference the viewer draws on that side, at the vertical position of its
  words in the whole document, in the strip's colours (theme chrome); variables and noise
  have none; a faint band shows the part on screen and follows the viewport (a horizontal
  scroll bar appearing included). A click on or near a segment goes to that difference,
  elsewhere centres that point of the document.
- **Noise rules dialog** (`officina_noise.NoiseDialog`, `officina_noise_page`): from
  the board (the initiative's rules and presets) and from the case header (the case's own
  rules; the initiative's listed read-only, since they add up; the presets are always the
  initiative's). Help line: rules match the normalised text. Presets with a checkbox (all
  off by default), then the rules table (on/off, Nome, Espressione regolare, Occorrenze)
  with [+ Regola] [Rimuovi]. Each row shows how often it matches the target and the latest
  TO-BE of the case — counted **before** saving, in the `officina-noise` worker, debounced,
  with a small spinner (a custom rule may take up to ~2 s in the guarded child). A row
  error — no name, no pattern, a regex that does not compile, a name used at any level
  ("nome già usato da un preset / da una regola dell'iniziativa / dalla regola del caso
  KEY"), or the service's "espressione potenzialmente troppo lenta: semplificala" — is red
  on that row (long ones elided, full text in the tooltip) and keeps [Salva e riconfronta]
  disabled. Saving (`set_noise_rules`, UI thread) waits while the case is being compared or
  has queued review actions; the initiative's rules and presets also wait for running
  generations. Then the case is compared again.
- **DOM tab** (`officina_dom.DomTab`, `officina_dom_map`, `officina_dom_view`; HTML cases,
  *Documenti | DOM*): a tree of the TARGET's block elements (parsed back from the pretty
  source's indentation), each marked with the worst verdict of the differences inside it
  (glyph + edge colour of its look); the two pretty sources (`dom_view`, fetched once per
  (target, version) in the `officina-dom` worker) in read-only `QPlainTextEdit`s that scroll
  together, each located difference's line tinted by its verdict (`ExtraSelection`), the
  selected one stronger. A difference is located by its attribute value (a link) or its
  text in the stream of text lines, searched from the previous difference onwards;
  selection is shared with the list both ways. Without the Edge print the tab is the case's
  main view (R45, above).
- **Adding a case** (`officina_add.AddCaseDialog`): Ricerca's row menu "Aggiungi
  all'Officina…" (wrench icon, lazy import) and "+ Caso da file…" share one dialog:
  Iniziativa (existing or "Nuova iniziativa…" + its name), File JSON + [Sfoglia…] (file flow
  only), Template key (read-only for a hit; for a file prefilled from
  `documents[0].template.templateKey` and editable), Variante. Every refusal (duplicate key+variant, initiative gone, a call no longer in the
  local log, no Officina folder) is a status-bar sentence; success is a toast.
- **Payload e header** (`officina_editor.PayloadHeaderDialog`): tab *Payload* (a JSON editor
  with live validation — Save refused until it is a JSON object — and [Formatta]); tab
  *Header e invio*: Generatore (the enabled generators, the case's own value kept even when
  it is not among them), correlation_id (nuovo a ogni invio / FDI della chiamata di origine,
  offered only with a known FDI / valore fisso + value), Link di upload (Rimuovi
  (consigliato) / Lascia solo se tutti scaduti), [ ] Non inviare Postman-Token, and the
  case's header table, checked with the core's `header_problems`. The hint spells out the
  precedence: automatic < profile (Impostazioni) < initiative < case. It reads
  `config.load()` whenever it opens and saves through `save_case`, and `save_payload` only
  when the payload changed.

**Generation queue** (`officina_jobs.GenerationQueue`): every AS-IS/TO-BE — a single F5 or
a batch — goes through it. Each case is one `JobRunner` job on one of the three **lanes**
`officina-generate`, `officina-generate-2`, `officina-generate-3` (`JobRunner` keeps one
live job per name, so three names = three cases on the wire at once). The lanes are
`EXCLUSIVE`, never superseded (a superseded job's document would still be written, its
result silenced), and a lane is free again only after its `finished` has been **delivered**.
A failed case (a failed `SendResult`, or an unexpected error turned into one, masked) never
stops the others. [Annulla generazioni] drops the waiting cases and sets the cancel token of
the running ones; `generate` checks it just before sending, so a call already on the wire
runs to its end. A case already queued is not queued twice (the status bar names it).
Failure reasons live in memory per (initiative, case id), until the next success or a
restart. Other Officina jobs: `officina-compare` (the workbench's documents and
`compare_case`; a newer request supersedes), `officina-review` (a review action then the
same version judged again; exclusive, fed by the per-case queue), `officina-noise` (the
dialog's live counts; superseding), `officina-dom` (the DOM tab's sources; superseding),
`officina-delivery` (exclusive). Phase 1's `officina-summary` is gone: the board reads the
saved summaries. All are in `JOB_NAMES` with Italian labels in `quit_dialog`.

**Viewer** (`officina_viewer.DocView`, `officina_render.PageRenderer`,
`officina_sync.SyncController`, `officina_overlays.py`):
- `DocView` is a `QGraphicsView` (not QPdfView: that needs PySide6-Addons and has no
  overlay API). The scene is in PDF points of the *displayed* page (CropBox and /Rotate
  applied — the space of the extracted Word boxes), pages stacked with a 12 pt gap, the
  vertical scroll bar always on (so fit-width does not oscillate), hand-drag scrolling,
  Ctrl+wheel zoom. Zoom 1.0 = printed size (96/72 px per pt); both views open at
  `fit_width`, and a fit mode is re-applied on resize.
- **Only visible pages are rendered** (Review Focus 3): each page starts as a `surface2`
  placeholder "Pagina N"; the visible pages plus one before and after (`PREFETCH`) are
  requested on a coalescing timer, and pages more than `KEEP` = 3 pages away give their image
  back. Render scale = zoom × px-per-pt × devicePixelRatio (HiDPI), snapped to buckets of
  2^(1/6), capped at 4 px/pt; the lower-resolution image stays until the sharper one arrives.
  After a zoom change rendering waits 150 ms (`ZOOM_SETTLE_MS`) so a Ctrl+wheel burst renders
  only the final scale. A failed page is retried once after 500 ms, then shows "Impossibile
  mostrare la pagina N: …" in `bad`.
- `PageRenderer(pool, cache_pages=24, cache_bytes=256 MB)`: dedups in-flight requests; an
  LRU keyed by (doc_id, file identity, page, bucket) bounded by **both** 24 images and a
  **256 MB byte budget** (the newest image is always kept, and a page's older buckets are
  dropped when a new one arrives); `forget(doc_id, keep, keep_scale)` takes queued jobs back
  (`QThreadPool.tryTake`) after a scroll or a zoom. A new file under the same doc_id (path,
  size or mtime) drops the old images. The two views use distinct doc_ids
  (`officina-target`, `officina-generated`); each `DocView` owns a one-thread pool. The
  worker imports `officina.pdf` lazily and gets 32-bit BGRx bytes (`QImage.Format_RGB32`)
  from the Qt-free `render_page`.
- **PDFium lock**: PDFium is not thread-safe, so every call into it — rendering, text
  extraction, page sizes — runs under one process-wide `RLock` in `officina.pdf`. The pools
  keep the GUI responsive but never render in parallel. On Windows the render thread may
  hold a PDF open for a moment (a test that deletes a version retries).
- **Overlays** (`officina_overlays.py`, input `set_highlights(items: list[tuple[Judged,
  str]])`, "left"/"right" = side, R4): a difference is one `HighlightItem` per run of words
  on a line, styled by its **verdict look** (above): a fill in the look's soft token and a
  solid or dashed edge, or a line under the words (variabile, fatta); changed characters
  in `mark_yellow` with an ink underline. Everything is drawn with the LIGHT token values
  (paper, R13), fills in *multiply* mode so black text stays black. A neutral look (no
  verdict: the AS-IS view) uses a grey box. `focus_difference` rings the difference with a
  halo and scrolls only when it is not already fully visible; Enter in the list centres it
  in both documents even when visible. A click emits `difference_clicked` on release, only if the mouse
  moved less than the drag distance. Everything re-derives on `theme.signals.changed`.
- `SyncController(left, right)` keeps scroll (by **relative page position**: page index +
  fraction of the page, so documents with different page lengths still show the same page
  side by side; a view past the other's last page puts the other at its end) and zoom (fit
  mode or factor) in step; `set_enabled(False)` lets them move freely and re-enabling
  aligns zoom, then position. It disconnects itself when either view is destroyed.

**Delivery dialog** (`officina_delivery.DeliveryDialog`, opened by [Consegna…]): a checkable
case list with the cases accepted as of their latest TO-BE preselected and a warn line
naming the chosen ones that are not accepted, or whose latest TO-BE is not the accepted one; Cartella di destinazione (prefilled with the initiative's last one, [Sfoglia…]);
[x] Crea anche lo zip; a preview tree (root elided on the left so the initiative stays
visible, key folders and files, the missing slots greyed under their folder, the zip line
last). [Consegna] is enabled only with a destination and at least one file. The
`officina-delivery` job first lists the conflicts (the destination may be a synced folder,
so off the GUI thread); on its **`finished`** each conflict is asked on the GUI thread
(Sostituisci / Mantieni entrambi / Salta + "Applica a tutti (n)"; Esc = Salta); then the same
job name runs `deliver` with the answers — a file nobody was asked about is kept next to the
new one, never overwritten. During the copy the button reads [Interrompi] and the dialog
cannot be closed. The summary page: completata / incompleta / interrotta, files and folder,
the zip (or why it was not made), renamed, skipped, missing and failed files, [Apri
cartella] [Chiudi].

**Shell hooks**: `config_changed` (the chosen folder), `on_config_changed` (refresh; a new
folder goes back to the list), `on_quit()` (drop the waiting cases), `is_writing()` (asked
by Impostazioni before a folder change). Strings: `ui/strings/officina.py` and the phase-2
modules `officina_{avanzamento,verdetto,elenco,azioni,rumore}.py`. Screenshot scenes in
`scripts/dev/shoot.py`, on the fake core: `officina-cartella`, `-iniziative`, `-bacheca`,
`-caso`, `-payload-header`, `-aggiungi`, `-visore`, `-visore-pagina`, `-consegna`,
`-consegna-riepilogo`; phase 2: `-caso-verdetti`, `-caso-verifica`, `-caso-due-vie`,
`-caso-profilo`, `-caso-minimappa`, `-caso-dom`, `-elenco-*` (una lettera, in corso, non
risolta, da verificare, link), `-azioni-*` (mini-barra, menu, toast, tollera-nota),
`-bacheca-pillole`, `-rumore`, the R45 scenes (azzera tolleranze, mostra fatte, HTML
senza stampa), and `-motore-*` (including a Stretto AS-IS) (the REAL engine's comparisons of synthetic
PDFs, canned into the fake: caso, regressione non risolta, in corso, tutte inattive, AS-IS,
bacheca, the target and accept confirmations); `impostazioni-officina*` /
`impostazioni-salva-bloccato` for the settings section.

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
6. **Officina** (`settings_officina.py`, tables in `settings_officina_tables.py`) — three
   cards over `Config.officina`:
   - *Officina*: Cartella dell'Officina (a `PathField`; a live warn line when it is in
     OneDrive — `officina_dialogs.in_onedrive` — or on a network path — `on_network`, UNC or
     a mapped drive; never blocking), Timeout di generazione (secondi) (a spin box bounded
     by `OFFICINA_TIMEOUT_RANGE`, 1–600), Postman-Token predefinito (with why it matters:
     nginx).
   - *Generatori*: table [Attivo | Nome | URL | Problema] + Aggiungi / Rimuovi, and
     "Generatore predefinito" (a combo of the **enabled** rows only). The URL cell shows
     only scheme, host and path + `?***` (`shown_url`); the full URL lives only in the cell
     editor. Disabling or deleting the default clears it with an inline message; re-ticking
     the row makes it the default again; renaming the row keeps it the default.
   - *Profilo intestazioni*: table [Nome | Valore | Problema] + Aggiungi / Rimuovi.
   Every rule comes from the core (`generator_problems`, `default_generator_problem`,
   `postman_token_problem`, `header_problems`, `officina_root_errors`, re-exported by
   `ui/contracts.py`); the UI re-implements none. Problems are shown **inline**, in the row's
   "Problema" column (`bad` colour, visible only while some row has one) or under the field.
   While a problem exists and the config part of the form is dirty, [Salva] is disabled and
   the unsaved bar says why — "Officina: correggi gli errori segnalati accanto alle righe"
   — with a [Mostra] button (`show_section("officina")`); a preference-only save still
   goes through. A save that **changes the folder** is refused while the Officina is
   writing (`OfficinaPage.is_writing()`: queued or running generations, or a delivery;
   `workers.officina_writing(runner)` is the fallback when the page is not built). The
   form carries `FormValues.officina` (a deep copy, the timeout clamped by
   `canonical_officina`, so a hand-edited value does not open the form dirty). After Salva
   the Officina tab refreshes (`on_config_changed`) and goes quietly back to the list when
   the folder changed; `OfficinaService` reads the config on every call.
7. **Editor esterno** — Notepad++ path, [Sfoglia…] [Rileva].
8. **Avanzate** — File di configurazione (path + [Apri cartella]), [Riesegui configurazione iniziale].

Nothing is written until [Salva]. The **unsaved bar** — "Modifiche non salvate ·
[Annulla] [Salva]", inverted colours, outside the scroll area — appears only while the
form is dirty; errors from `config.validate` are listed above it instead of saving.
Leaving the page while dirty asks Salva / Scarta / Annulla (`can_leave`). Changing the log
folder asks "Vuoi indicizzare i log presenti nella nuova cartella ora?". The page is the
only writer of `config.json` except for `folder_envs`, which the import dialog writes; so
`save()` re-reads `folder_envs` from disk before writing (a stale form would otherwise drop
the assignments), while `errors` and `to_config` never read the file. It emits `config_changed`, which the window broadcasts to
every *other* page's `on_config_changed`. `show_section(key)` (`appearance`, `archive`,
`environments`, `automation`, `search`, `officina`, `editor`, `advanced`) lets other pages
deep-link.

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
    # "sync"/"index"/"scheduler"/"import"/"recycle", the three "officina-generate*" lanes,
    # "officina-delivery" and "officina-review" are EXCLUSIVE: a second submit is refused -> busy(name);
    # every other name supersedes (the older job is cancelled and silenced by _Delivery).
class QtEventSink(QObject): event = Signal(object); __call__(ev) emits   # core EventSink -> Qt signal
```
- `JOB_NAMES` lists every name a page submits under (a test checks it against the pages'
  constants and against `quit_dialog.JOB_LABELS`).
- `job_finished(name, ok)` drives the refresh: after a `DATA_JOBS` job (`sync`, `index`,
  `import`, `recycle`; even a failed one) the window calls every page's optional
  `on_data_changed()`, and closing the window while one runs asks first. `QUIT_JOBS` =
  `DATA_JOBS` + the Officina's generation lanes + `officina-delivery`: closing asks **once**
  for all of them, then calls every page's optional `on_quit()` (the Officina drops its
  waiting cases) and cancels them.
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
  | progress / progress_bg (Officina "in corso") | `#0F6CBD` / `#E6F0FB` | `#6BB3E8` / `#1B3A5C` |
  | variable / variable_bg (Officina variables) | `#6B5BB5` / `#EEEBFA` | `#B8A9F5` / `#2F2A4D` |
  | mark_yellow (changed characters) / shadow | `#FFD24D` / `#000000` | `#E8C04A` / `#000000` |
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
  the Ricerca `banner="bad"` warning — and, in the Officina, for **regressions** and the
  struck target text of a difference (§Officina).
- Icon tint and the JSON highlighter read `theme.tokens()` and re-derive on
  `theme.signals.changed`; `theme.apply` clears the icon cache.
- Fonts: UI Segoe UI Variable Text → Segoe UI; monospace only through `theme.mono_font()`
  (Cascadia Mono → Consolas → the system fixed font) — the JSON, file names, FDIs, keys,
  paths, the registro.
- **Icons**: Fluent UI System Icons (MIT, `ui/icons/LICENSE.md`) as embedded SVG, tinted
  per theme: search, arrow-sync, settings, info, document-arrow-right, copy, save,
  folder-open, calendar, dismiss, text-bullet-list-tree, wrench (the Officina tab).
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
  `wizard`, `about`, `imports`, `officina` — phase-1 Officina strings prefixed `OFFICINA_` —
  and the phase-2 Officina modules `officina_avanzamento` (progress bar, strips, profile,
  board pill), `officina_verdetto` (verdict words and glyphs), `officina_elenco` (the
  list), `officina_azioni` (mini-bar, menu, toasts), `officina_rumore` (noise dialog, DOM
  tab)),
  all re-exported from `qtrequestory.ui.strings`. `tests/ui/test_strings.py`
  also enforces one vocabulary: no English words in user-facing strings, the same labels
  for the same thing on every page, and no module formatting a size by hand — every size
  goes through `events.format_size` / `ui/pages/sync_format.format_size`. A test also
  asserts that no UI string claims the server keeps logs for "circa un giorno".
- `ui/prefs.py` holds the shared QSettings keys (`search/group_by_fdi`, `search/key_mode`,
  `search/recent`) so Ricerca and Impostazioni never import each other.
- `ui/contracts.py`: Protocols + dataclasses for everything the UI consumes from core
  (`ConfigApi`, `SyncApi`, `SchedulerApi`, `IndexApi`, `ExtractApi`, `ArchiveApi`, gathered
  in `CoreServices`; plus `OfficinaApi`, see §Officina) — the core facade
  satisfies them structurally; `tests/fakes/fake_core.py` implements them in memory
  (synthetic hits, scripted sync progress honouring the cancel token, fake task status,
  `set_local_days(env, days, empty=())` / `set_server_days(env, listed=(), seen=())` for the
  coverage states, the real archive discovery/import on a temp tree with a simulated
  Recycle Bin; `FakeOfficinaApi` wraps the real `OfficinaService` on real files and replaces
  only the HTTP opener and the Edge print, while its comparisons and verdicts are scripted
  by `tests/fakes/fake_verdict.py` — DESIGN-core §Testing),
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
