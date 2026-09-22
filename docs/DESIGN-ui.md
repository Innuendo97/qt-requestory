# qtRequestory — UI design (v1)

Stack: **PySide6 (Qt Widgets)**, `PySide6-Essentials >= 6.7`, Qt `windows11` style (native
look, system light/dark). UI language: **Italian**, all strings in `ui/strings.py`.
`qtrequestory.ui` is the only package that may import Qt. The UI talks to the core through
plain Python APIs (`docs/DESIGN-core.md`) and receives progress as core events converted to
Qt signals. Widgets are dumb; presenters hold state.

## Navigation

Left navigation rail + `QStackedWidget` + global status bar (Windows Settings idiom).

```
+---------------+-------------------------------------------------------------+
| [icon] Ricerca|                                                             |
| [icon] Sincr. |                        page                                 |
|               |                                                             |
| -- bottom --  |                                                             |
| [icon] Impost.|                                                             |
| [icon] Info   |                                                             |
+---------------+-------------------------------------------------------------+
| Copiato negli appunti (312 KB)        | svil: oggi 11:23 · coll: oggi 11:24 |
+---------------+-------------------------------------------------------------+
```
- Default page: **Ricerca**. Status bar right segment = last sync per env / "Sincronizzazione
  3/48…" while running; clicking it jumps to Sincronizzazione.
- Pages registered in one list `PAGES = [(key, label, icon, factory, section)]`; future
  Replay / Statistiche / Diff = one tuple + one widget. **No disabled placeholders in v1.**
  Search page exposes `selected_entries()` and a `context_menu_actions` hook for them.
- Shortcuts: Ctrl+1 Ricerca, Ctrl+2 Sincronizzazione, Ctrl+, Impostazioni, Ctrl+Shift+S
  Sincronizza ora.

## First-run wizard (`QWizard`, 3 pages)

Shown when `config.is_first_run()`; also from Impostazioni → "Riesegui configurazione iniziale".

1. **Cartella dei log** — default `%USERPROFILE%\qtRequestory\logs`, [Sfoglia…]; must be
   writable. If it already contains `<env>/YYYY/MM/*.txt`: "(i) Trovati N file di log già
   presenti: verranno indicizzati, non riscaricati." (core `count_local_files(root)`).
2. **Ambienti** — table [abilitato | nome | URL] with [Aggiungi] [Rimuovi] [Importa da file…];
   pre-filled from `find_sidecar_environments(exe_dir)` (an `environments.json` next to the
   exe) when present, otherwise empty with the hint "Chiedi al collega il file
   environments.json oppure inserisci nome e URL". [Verifica raggiungibilità] optional,
   never blocking: "Gli ambienti sono raggiungibili solo da rete aziendale o VPN Cisco: se
   ora non lo sono, va bene lo stesso."
3. **Automazione** — [x] Sincronizza automaticamente ogni giorno alle 09:00 (riprova ogni ora
   fino alle 18:00 e al logon; solo se la rete è raggiungibile; nessuna password salvata).
   If `detect_legacy_task()`: "(!) È presente il vecchio task NginxLogSync basato su
   PowerShell: verrà sostituito." Notepad++ path (detected, [Sfoglia…]). [x] Avvia la prima
   sincronizzazione al termine.
   On Fine: save config, register task (failure → non-blocking info), open main window on
   Sincronizzazione with sync running if requested, else on Ricerca.

## Sincronizzazione page

```
| Sincronizzazione                                  [Sincronizza ora ▾] [Annulla]|
|                                                     ├ Tutti gli ambienti      |
|                                                     ├ Solo svil / Solo coll   |
|                                                     └ Anteprima (senza scaricare)|
| +--------------------------------+ +--------------------------------+       |
| | svil            ● Aggiornato   | | coll         ○ Non raggiungibile|       |
| | Ultimo sync: oggi 11:23        | | Ultimo sync: ieri 15:48        |       |
| | Log locali: 39 giorni · 41 MB  | | Log locali: 48 giorni · 1,5 GB |       |
| | Ultimo giorno: 21/09/2026      | | Ultimo giorno: 21/09/2026      |       |
| | Indice: aggiornato             | | Indice: 1 file da indicizzare  |       |
| +--------------------------------+ +--------------------------------+       |
| coll · 20260716.txt (80,4 MB)                    file 12 di 48 · 212 MB/1,4 GB|
| [██████████████░░░░░░░░░░]  8,2 MB/s · circa 2 min rimanenti                 |
| Registro  (QPlainTextEdit, monospace, max 2000 righe, prefilled with sync.log tail) |
| Sincronizzazione automatica                                    [x]          |
| Attiva · ogni giorno 09:00, riprova ogni ora fino alle 18:00 e al logon      |
| Prossimo avvio: domani 09:00 · Ultima esecuzione: oggi 11:24 (esito 0)      |
```
- Pills (muted colours, never red): `● Aggiornato` (fresh) · `● Da aggiornare` · `○ Non
  raggiungibile` (grey) · `◐ In corso` · `○ Mai sincronizzato` · `▲ Completato con N errori`
  (amber).
- "Sincronizza ora" always = `force=True`. Progress strip: current file + per-file bar +
  "file i di N · MB/total · rate · ETA" (total from `RemoteIndexRead.bytes_to_download`);
  indexing phase shown in the same strip.
- Auto-sync checkbox → `scheduler.register/unregister` in a worker; status line from
  `scheduler.status`; if `exe_matches` is False: "Il task punta a un eseguibile diverso
  (<path>). [Aggiorna]". If `is_unstable_location(exe)`: warn before registering.
- If the lock is held by the scheduled run: button disabled, "Sincronizzazione in corso dal
  task pianificato…", poll every 2 s.
- Close while syncing → QMessageBox "Sincronizzazione in corso: 12 di 48 file. Interrompere e
  uscire?" [Interrompi ed esci] [Continua].

## Ricerca page

```
| Ambiente [coll ▾]  FDI [aaaaaaaa-…          ]  Template key [MOD_TEST_SC… ▾] |
| Periodo ( 7 gg ) (•30 gg ) ( 90 gg ) ( Personalizzato )  dal [..] al [..]  [ Cerca ] |
| Log locali coll: dal 16/07/2026 al 21/09/2026 · le chiamate di oggi arrivano domani |
+---------------------------------------------------------------------------------+
| 12 chiamate · 1 FDI · 4 giorni      | 20260921_aaaaaaaa-…_MOD_TEST_SHEET….json |
| Giorno  Ora  Template key  FDI  N.doc  Dim. | [Apri in Notepad++][Salva con nome…][Copia][Cartella] |
| …rows, most recent first, first row auto-selected… | { "documents": [ … (preview) |
```
- Ambiente: `QComboBox` (last used remembered). FDI: `QLineEdit`, validator `[0-9a-fA-F-]*`,
  placeholder "uuid o prefisso"; **smart paste**: pasting `<fdi>_<KEY>_<id>.json` or a
  `### …` header fills both fields. Template key: editable `QComboBox` + `QCompleter`
  (MatchContains, CaseInsensitive) over `list_template_keys(env)`. Periodo: exclusive toggle
  buttons 7/30/90 + Personalizzato → two `QDateEdit`. Cerca = default button (Enter);
  disabled until FDI or key non-empty.
- Coverage line from `coverage(env)`.
- Results: `QTableView` + `ResultsModel(QAbstractTableModel)` + `QSortFilterProxyModel`.
  Columns: Giorno (dd/MM/yyyy) · Ora (HH:mm:ss from requestDate, "—" if absent, tooltip full
  ISO) · Template key (elided, tooltip) · FDI (8 chars + "…", tooltip full) · N. doc · Dim.
  (KB); hidden: ID chiamata, File. Order as delivered by core (most recent first); header
  click sorts. Summary line "12 chiamate · 1 FDI · 4 giorni" (+ stale-index banner).
- Row context menu: Apri in Notepad++ · Salva con nome… · Copia JSON · — · Copia FDI · Copia
  template key · Cerca solo questo FDI · Cerca solo questa template key · — · Apri cartella
  del log del giorno.
- Selection → preview via worker (debounced 150 ms, superseded requests dropped).
- Preview pane: file name (`output_name(hit)`, selectable) + buttons [Apri in Notepad++]
  (primary) [Salva con nome…] [Copia negli appunti] [Apri cartella]; `QPlainTextEdit`
  read-only, monospace (Cascadia Mono → Consolas), `JsonHighlighter(QSyntaxHighlighter)`
  with palette-derived colours; **cap 4000 lines** with footer "Anteprima: prime 4.000 righe
  di N — Apri in Notepad++ per il body completo". Copy/Save/Open always use the FULL body.
  Ctrl+F inline find bar.
- Keyboard: Enter/double-click row = Apri; **Ctrl+C = full pretty JSON body**; Ctrl+Shift+C
  row as TSV; Ctrl+S Salva; Ctrl+O Apri; Ctrl+Shift+O cartella; F5 rerun; Ctrl+L focus FDI;
  Ctrl+K focus key; Esc clears the focused field.
- Empty states (centred icon + 2 lines + 1 button, never a modal): no local log for env →
  [Vai a Sincronizzazione]; no results → hints: if `al` = today "Le chiamate di oggi
  arrivano domani con il file YYYYMMDD.txt."; window < 90 days → [Cerca negli ultimi 90
  giorni]; FDI shorter than 8 chars → "Prova con l'FDI completo".
- Output contract: the preview/copy/save/open text is exactly `extract.pretty_json(body)`,
  starts with `{\n    "documents": [`; the UI never adds headers or comments.

## Impostazioni page

Cartella dei log locali [Sfoglia…][Apri] (change → "Vuoi indicizzare i log presenti nella
nuova cartella ora?") · Ambienti table (abilitato/nome/URL, Aggiungi/Rimuovi/Verifica/Importa
da file…) · Notepad++ [Sfoglia…][Rileva] · Periodo predefinito (7/30/90) · Cartella file
temporanei · Avanzate: [Ricostruisci indice] [Riesegui configurazione iniziale] · Config path
[Apri cartella]. [Annulla] [Salva] (Salva enabled only when dirty; inline validation via
`config.validate`). Emits `config_changed` consumed by Sync/Search.

## Info page

App name, `__version__`, paths (config, index DB, app log, sync log) each with [Apri]; app log
tail (last 500 lines, filter Tutti/Avvisi/Errori, [Aggiorna], [Copia tutto]).

## Concurrency (`ui/workers.py`)

```python
class CancelToken (core)                       # passed to core calls
class WorkerSignals(QObject): started, progress(object), log(str), result(object), error(str, str), finished, cancelled
class Worker(QRunnable): wraps fn(*args, sink=..., cancel=..., **kw); exceptions -> error
class JobRunner(QObject): QThreadPool(maxThreadCount=3); submit(name, fn, ...) -> Job
    # named singleton jobs: "sync" refused if running; "search"/"preview" supersede (older results dropped by request id)
class QtEventSink(QObject): event = Signal(object); __call__(ev) emits   # core EventSink -> queued signal
```
- Progress coalesced to ~10/s. Widgets never touched from workers.
- Single instance: `QLocalServer` named `qtrequestory-<username>` (overridable with
  `QTREQUESTORY_INSTANCE_KEY` — a pipe name is machine-global, so the test harness gives each
  pytest process its own); second launch sends `activate` and exits; primary raises its
  window. The headless `--sync` path never uses it.
- `QSettings` is opened only through `actions.user_settings()`: `QSettings(org, app)`
  hardcodes `NativeFormat` and would write the developer's real registry during tests.
- Startup order (`cli.main`): parse args → `--sync/--index/--find/--task` → core only; else
  import Qt, single-instance guard, `QApplication`, first-run check, `MainWindow.show()`,
  then `index.plan` + opportunistic sync in workers (never before the window is visible).

## Visual style

Qt `windows11` style; follow `QStyleHints.colorScheme` (+ `colorSchemeChanged` → re-derive
highlighter/pill colours). No QSS beyond rail width (200 px), card frame padding, pill
colours (palette `Mid`, amber `#B7791F` light / `#E3A23A` dark). Fonts: system default;
monospace Cascadia Mono → Consolas. Icons: Fluent UI System Icons (MIT) as embedded SVG:
search, arrow-sync, settings, info, document-arrow-right, copy, save, folder-open. App icon:
page with three log lines + magnifier, accent `#0F6CBD`, exported `.ico` 16/24/32/48/256.

## Testability

- `ui/contracts.py`: Protocols + dataclasses for everything the UI consumes from core
  (`ConfigApi`, `SyncApi`, `SchedulerApi`, `IndexApi`, `ExtractApi`) — the core modules
  satisfy them structurally; `tests/fakes/fake_core.py` implements them in memory (synthetic
  hits, scripted sync progress honouring the cancel token, fake task status).
- Presenters (`SearchPresenter`, `SyncPresenter`, `SettingsPresenter`) are plain objects
  with a few Qt signals; widgets render and forward.
- `pytest-qt`, `QT_QPA_PLATFORM=offscreen` in `tests/ui/conftest.py`. ~10 tests: results
  model rows/format/sort; presenter supersede; highlighter formats; smart paste; wizard
  validation; workers (cancel, supersede); one end-to-end smoke with the fake core
  (type FDI → Enter → first row selected → preview starts with `{\n    "documents": [` →
  Ctrl+C puts the full body in the clipboard).
