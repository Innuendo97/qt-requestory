# qtRequestory — core design (v1)

The core is the UI-agnostic engine: sync, index, search, extract, scheduler, config.
**Rule: `qtrequestory.core` imports only the standard library** (a test enforces it).
Everything here is callable from the CLI (`--sync`, `--index`, `--find`, `--task`) and
from the PySide6 UI through the same functions.

## Domain facts (measured on real data; fixtures must reproduce them synthetically)

- Server exposes an nginx autoindex page per environment
  (`https://<host>/AutoDeploy/Input/`). Entries: `YYYYMMDD.txt` (one per day; **0 bytes**
  on weekends/holidays), plus loose `<uuid>_<TEMPLATE_KEY>_<id16hex>.json` files for the
  current day (compacted into the daily file at ~18:30). **Server retention is ~1 day**:
  the local mirror is the only archive.
- Daily file format: header line `### <name>.json` followed by ONE line with the request
  body JSON (50–450 KB). Header/body strictly alternate. Files may be CRLF or LF.
- `<name>` shapes seen: `UUID_KEY_ID` (canonical), `correlationId_vuoto_KEY_ID`,
  `UUID-t15_KEY_ID`, `UUID-test-12_KEY_ID`, keys with numeric prefixes
  (`UUID_2_SOME_KEY_ID`, `UUID_3_1_OTHER_KEY_ID`).
  `ID` is 16 lowercase hex chars. The FDI is the UUID token (it is the request
  `correlation_id`, NOT `dossier.id`).
- One FDI (a "pratica") appears in several entries, one per principal template key; each
  body's `documents[]` holds that template plus common attachments.
- `dossier.requestDate` (ISO-8601 Zulu) present in ~82% of bodies; the first
  `"requestDate"` occurrence is always the dossier one.
- Counting `"templateKey"` with a regex is WRONG (appears in `customData`, nested
  `childDocuments`). `ndocs = len(body["documents"])` via `json.loads`.
- Throughput: header scan ≈ 260 MB/s; `json.loads` of every body ≈ 45 MB/s.

## Package layout

```
src/qtrequestory/
├── __init__.py            __version__
├── __main__.py            -> cli.main()
├── cli.py                 argparse; --sync/--index/--find/--task; imports ui lazily
├── core/
│   ├── paths.py           AppPaths
│   ├── config.py          Config, Environment, load/save/validate, UnknownEnvironment, import_environments_file, detect_editor
│   ├── logsetup.py        configure_logging(paths, headless, level), resolve_level
│   ├── events.py          Event dataclasses, EventSink, LoggingSink, CancelToken, Cancelled, format_size
│   ├── daily.py           day/file-name helpers, list_local_daily_files, parse_entry_name, coverage_days
│   ├── autoindex.py       parse_autoindex(html) -> RemoteIndex, AutoindexFormatError
│   ├── http.py            HttpClient Protocol + UrllibHttpClient
│   ├── fsutil.py          replace_with_retry, remove_quietly
│   ├── state.py           SyncState (+ legacy .last-sync.json import)
│   ├── lock.py            ProcessLock, peek_holder (read-only probe)
│   ├── sync.py            SyncEngine
│   ├── index/schema.py    DDL, SCHEMA_VERSION, migrate
│   ├── index/db.py        open_index(path)
│   ├── index/scanner.py   scan_daily_file
│   ├── index/builder.py   IndexBuilder
│   ├── index/search.py    SearchQuery, SearchHit, search, read_body, coverage, list_template_keys
│   ├── extract.py         pretty_json, output_name, write_temp_file, housekeeping
│   ├── opener.py          find_editor, open_in_editor
│   ├── scheduler.py       TaskSpec, build_task_xml, register/unregister/status/run_now, detect_legacy_task
│   ├── jobs.py            run_sync_job, run_index_job
│   └── facade.py          Config/Sync/Scheduler/Index/ExtractService: what the UI calls
└── ui/                    the only package allowed to import PySide6
```

Dependency direction: `ui -> jobs/search/config/scheduler/extract -> core internals`.
`cli.py` is the only module that knows both.

## Locations

- App dir: `%LOCALAPPDATA%\qtRequestory\` (override with env `QTREQUESTORY_HOME`):
  `config.json`, `logs\app.log`, `logs\sync.log` (RotatingFileHandler 1 MB × 3).
  `--config PATH` moves only `config.json`.
- UI preferences (window geometry, last environment, theme mode, search options, recent
  searches) are not files: they live in `QSettings` (`HKCU\Software\qtRequestory\qtRequestory`),
  opened only through `ui/actions.user_settings()`.
- Mirror: `<mirror_root>\<env>\YYYY\MM\YYYYMMDD.txt`, plus the occasional
  `YYYYMMDD.txt.remote-<size>` (a server copy smaller than the local day, see §`core/sync.py`)
  and a `.part` while a download runs; `<mirror_root>\.qtrequestory\` holds
  `sync-state.json`, `sync.lock`, `index.sqlite` (+ `-wal`/`-shm`, and up to 3
  `index.sqlite.broken-*`).
- Output dir default: `%TEMP%\qtrequestory-calls\`.

## `core/events.py`

```python
class Cancelled(Exception): ...
class CancelToken:
    def cancel(self) -> None
    def is_set(self) -> bool
    def check(self) -> None                  # raises Cancelled

@dataclass(frozen=True) class Event: ts: float
# sync
SyncStarted(envs: tuple[str,...], dry_run: bool)
EnvStarted(env) · EnvSkipped(env, reason: Literal["fresh"]) · EnvUnreachable(env, error)
RemoteIndexRead(env, n_daily, n_empty, n_loose, bytes_to_download)     # emitted BEFORE downloads (ETA)
FileSkipped(env, name, reason: Literal["present","empty","shrunk","dry-run"], size=0)   # size: dry-run only
FileStarted(env, name, size) · FileProgress(env, name, done, size) · FileDone(env, name, size, path)
FileFailed(env, name, error) · EnvFinished(env, result: EnvResult) · SyncFinished(report: SyncReport)
# index
IndexStarted(n_files_to_scan) · IndexFileScanned(path, n_entries, i, n) · IndexFinished(scanned, removed, seconds)
# generic
LogMessage(level: int, text: str)

EventSink = Callable[[Event], None]
class LoggingSink: __init__(logger); __call__(ev)      # headless: formats every event to logging
def format_size(n_bytes) -> str       # "512 B" / "2,5 KB" / "80,4 MB" / "1,5 GB": THE size wording
STATUS_LABELS: dict[str, str]         # EnvResult.status in Italian, for sync.log and the UI
```
Every line `LoggingSink` writes to `sync.log` is Italian, and every size in it goes through
`format_size`, which the UI reuses (`ui/pages/sync_format.format_size` delegates to it; its
`whole_kb=True` mode gives the results table's "1.434 KB"). The registro panel, the cards,
the CLI `--dry-run` listing and `sync.log` word the same file the same way.

## `core/config.py`

```json
{
  "schema_version": 1,
  "mirror_root": "C:\\Users\\<u>\\qtRequestory\\logs",
  "environments": [ {"name": "svil", "url": "https://<host>/AutoDeploy/Input/", "enabled": true} ],
  "default_window_days": 30,
  "editor_path": null,
  "output_dir": null,
  "output_retention_hours": 24,
  "compaction_time": "18:30",
  "sync": {"index_timeout_s": 15, "download_timeout_s": 60, "chunk_size": 1048576, "retries": 1},
  "index": {"parse_json": true},
  "schedule": {"start_time": "09:00", "repeat_every_h": 1, "repeat_for_h": 9, "run_at_logon": true},
  "log_level": "INFO"
}
```
```python
@dataclass(frozen=True) class Environment: name: str; url: str; enabled: bool = True
@dataclass class SyncSettings / IndexSettings
@dataclass(frozen=True) class ScheduleSettings   # the scheduled task, edited in Impostazioni;
                                                 # defaults = the previously hard-coded TaskSpec
def parse_hhmm(value) -> time | None             # shared by validate, scheduler and the UI wording
def sanitised_schedule(s) -> ScheduleSettings    # what the task will really run: bad time -> default,
                                                 # counts clamped; used by spec_from_config AND the UI sentence
@dataclass class Config: (fields above; paths as Path; compaction_time as datetime.time)
    index_path / state_path / lock_path / resolved_output_dir  (properties)
    def env(self, name) -> Environment
    def enabled_environments(self) -> list[Environment]
def default_config() -> Config                        # environments = []  (NO hostnames in code)
def load_config(path) -> Config      # missing -> defaults, file NOT created (a cancelled first-run wizard must stay a first run);
                                     # corrupt -> renamed .broken-<ts> + defaults written back; unknown keys ignored; missing keys defaulted
def save_config(cfg, path)           # tmp + os.replace
def validate(cfg) -> list[str]       # env name ^[A-Za-z0-9_-]+$ unique; url http(s)://…/ ; window 1..3650;
                                     # schedule: start_time HH:MM, repeat_every_h 1..12, repeat_for_h 0..23;
                                     # log_level: a name logging knows (via logsetup.resolve_level)
def mirror_root_errors(cfg) -> list[str]  # only the mirror_root part of validate (the CLI gate)
class UnknownEnvironment(ValueError)      # "ambiente sconosciuto: 'x' (configurati: coll, svil)"
Config.require_env(name) -> Environment   # env(name), but UnknownEnvironment instead of KeyError
def import_environments_file(path) -> list[Environment]   # JSON list [{"name","url","enabled"?}] — used by wizard / auto-import of environments.json next to the exe
def find_sidecar_environments(exe_dir) -> Path | None     # environments.json next to the exe
def detect_editor() -> Path | None   # Notepad++ in ProgramFiles / ProgramFiles(x86) / PATH
CONFIG_VERSION = 1; MIGRATIONS: dict[int, Callable[[dict], dict]] = {}
```
`mirror_root`: a *missing* key defaults to `%USERPROFILE%\qtRequestory\logs`, but a key that
is present and empty is **kept empty**, never silently defaulted (that once pointed a
hand-edited config at the live mirror). `validate` then reports "La cartella dei log non è
impostata"; a relative path is "La cartella dei log deve essere un percorso completo…".
Numbers are coerced tolerantly: `1e999` / `Infinity` (`OverflowError`) fall back to the
default like any other bad value, with a warning.

`logsetup.resolve_level(level) -> (int, reason | None)` is shared by `configure_logging` and
`validate`. `logging.getLevelName("VERBOSE")` returns the *string* `"Level VERBOSE"`, so
`setLevel` raised `ValueError` on any hand-edited typo — before a window or a log file
existed, in an exe built with `console=False`: the process died silently. An unknown name
now falls back to `INFO`, and the reason is logged once the handlers are in place (so it
lands in `app.log`) and reported by `validate`.

## `core/daily.py`

```python
DAILY_NAME_RE = r"^(?P<day>\d{8})\.txt$"
def day_from_name(name) -> date | None
def file_name(day) -> str                                   # 'YYYYMMDD.txt'
def local_path(root, env, day) -> Path                      # <root>/<env>/YYYY/MM/YYYYMMDD.txt
def relative_path(env, day) -> str                          # 'coll/2026/09/20260921.txt' (forward slashes)
@dataclass(frozen=True) class LocalDailyFile: env; day; path; size; mtime_ns
def list_local_daily_files(root, env) -> list[LocalDailyFile]   # newest first; ignores .part and junk
@dataclass(frozen=True) class EntryName: raw; fdi: str|None; template_key: str; call_id: str|None; well_formed: bool
def parse_entry_name(raw) -> EntryName
def missing_weekdays(present: set[date], start, end) -> list[date]   # Mon-Fri in [start, end] not present
@dataclass(frozen=True) class CoverageDays: present: frozenset[date]; missing: tuple[date,...]; first_local: date|None
def coverage_days(present, days, today) -> CoverageDays
```
`coverage_days` looks at the window `[today - days + 1, today - 1]` — today is excluded,
its calls arrive tomorrow — and reports as `missing` only weekdays on or after
`first_local` (the oldest local day), so a young archive never flags the days before it
began. It reads the local file listing, not the index, so it is right before any
indexing. Consumers: the Ricerca coverage warning and the Sincronizzazione calendar,
through `IndexService.coverage_days(env, days=30, today=None)`.
`parse_entry_name` rules (total, deterministic): strip trailing `_[0-9a-f]{16}` → `call_id`;
if remainder starts with `correlationId_vuoto_` → `fdi=None`, key = rest; else split on first
`_`: `fdi=left.lower()`, `template_key=right`; no `_` → `fdi=None`, key = whole.
`well_formed = fdi matches canonical UUID regex and call_id is not None`.

## `core/autoindex.py`

```python
DAILY_HREF_RE = r'<a href="(?P<day>\d{8})\.txt">[^<]*</a>\s+(?P<date>\S+ \S+)\s+(?P<size>\d+)'
LOOSE_HREF_RE = r'<a href="[^"]+\.json">'
@dataclass(frozen=True) class RemoteDailyFile: name; day; size
@dataclass(frozen=True) class RemoteIndex: daily: tuple[RemoteDailyFile,...]  # newest first
                                          loose_count: int
def parse_autoindex(html) -> RemoteIndex    # raises AutoindexFormatError(ValueError), see below
```
A size token like `98K` / `1.2M` (nginx `autoindex_exact_size off`) raises
`AutoindexFormatError`: `\d+` would read it as 98 and every download would fail its size
check forever. The sync engine turns it into one `LogMessage(ERROR)` and status `errors`
for that environment, with nothing downloaded.
Autoindex line shape: `<a href="20260921.txt">20260921.txt</a>   21-Sep-2026 18:30   64487564`
(visible name may be truncated with `..&gt;` for long loose names — the href is always full).

## `core/http.py`

```python
class HttpUnreachable(Exception) ; class HttpDownloadError(Exception)
class HttpClient(Protocol):
    def get_text(self, url, timeout) -> str
    def download(self, url, dest_part: Path, *, timeout, chunk_size, on_progress: Callable[[int, int|None], None], cancel: CancelToken) -> int
class UrllibHttpClient(HttpClient)   # stdlib urllib; default SSL context (Windows cert store); honours system proxy
```

## `core/state.py`, `core/lock.py`

```python
@dataclass class EnvSyncState: last_success: datetime|None; last_remote_daily: int; last_downloaded: int; newest_day: date|None
class SyncState(path):
    load()                       # tolerant; imports legacy <root>/.last-sync.json (utf-8-sig, {"svil":"YYYY-MM-DD"}) once
    get(env) -> EnvSyncState
    mark_success(env, when, *, last_remote_daily=0, last_downloaded=0, newest_day=None)     # atomic save
    is_fresh(env, now, compaction_time) -> bool
        # fresh iff ALL of:
        #  1. last_success is not None and <= now (a future timestamp is never fresh, and logs a warning)
        #  2. last_success >= last_compaction_moment, where
        #     last_compaction_moment = today@compaction_time if now >= that else yesterday@compaction_time
        #  3. newest_day is not None and newest_day >= last_compaction_moment.date()
        #     newest_day = the newest NON-EMPTY daily day seen in the *listing that produced this state*
        #     which is now mirrored locally (present, shrunk, or a successful download) — so a run whose
        #     listing was read before the server compacted is NOT fresh even if last_success is already past
        #     compaction_time; the next hourly run retries instead of silently skipping a day the ~1-day
        #     server retention would then lose. A 0-byte day never counts (the server lists one before it
        #     compacts too): a weekend costs one cheap listing per hour until a non-empty day is mirrored.
        #  4. a state loaded from a file written before newest_day existed (rule 3's key missing) -> not fresh
class ProcessLock(path): acquire(blocking=False) -> bool; release(); holder_info(); context manager   # msvcrt.locking
def peek_holder(path) -> str | None     # "<pid> <ISO time>" of a LIVE holder, else None; never takes the lock
```
**Freshness** is the rule above, not "synced recently": `mark_success` receives the clock
reading taken right before the listing GET and the newest listed NON-EMPTY day that ended up
mirrored (present, downloaded, or shrunk — see below; 0-byte days never count). A listing read at 18:29, before the
server compacted, therefore never makes the env fresh for the next day, and a timestamp in
the future is distrusted (`log.warning` "…nel futuro…"). State files from before
`newest_day` existed cost exactly one extra sync.

**Writes never stop a run.** `_save` is temp file + `fsutil.replace_with_retry` (retries only
`PermissionError`: an AV scanner or a reader holding the file). If it still fails, the sync
engine emits `LogMessage(WARNING, "<env>: stato non salvato (…); i file sono al sicuro")`
and the env stays `ok`; the legacy `.last-sync.json` import likewise keeps the imported
values in memory and only warns. Losing a state write costs one redundant sync.

**The lock.** The byte-range lock sits 1 MiB beyond the end of `sync.lock`, so the holder
line (`"<pid> <ISO time>"`, written on acquire, truncated on release) stays readable while
the lock is held. `peek_holder` is the read-only probe the Sincronizzazione page polls
every 2 s while visible (and the startup sync checks): it opens the file `O_RDONLY`,
reads at most 4 KB and decides liveness from the PID, never by taking the lock — a probe
that held it even for an instant could make a scheduled run log "già in corso" and skip an
hour. "Nobody" is answered for a missing/empty/garbled file, a PID that is gone, a PID
whose process started after the line was written (recycled), and **any line written
before the machine last booted** (the holder died with the machine; the PID may now be a
boot-time service). After boot, a process we may not inspect (`ACCESS_DENIED`) counts as
alive — it only greys a button. The peek never *gates* a manual sync: the core takes the
real lock and, if the scheduled task holds it, runs nothing (`JobReport.sync is None`).

## `core/sync.py`

```python
@dataclass(frozen=True) class EnvResult: env; status: Literal["ok","fresh","unreachable","errors","cancelled"]; downloaded; present; empty; failed; bytes; error: str|None
@dataclass(frozen=True) class SyncReport: results: tuple[EnvResult,...]; started; finished; dry_run: bool = False
    exit_code -> int      # 0 ok/nothing, 1 file errors, 2 nothing reachable, 3 cancelled
class SyncEngine(config, http, state, sink, cancel=None, clock=datetime.now):
    run(envs=None, *, force=False, dry_run=False) -> SyncReport
    sync_env(env: Environment, *, force, dry_run) -> EnvResult
```
`run(envs)` resolves every name with `config.require_env` **before** anything starts: an
unknown name raises `UnknownEnvironment` (the CLI prints it and exits 2). `envs=None` means
every enabled environment.

Per env:

1. Not `force` and `state.is_fresh` → `EnvSkipped`, status `fresh`.
2. `listing_at = clock()`, then GET the index (timeout `index_timeout_s`); any error →
   `EnvUnreachable`, status `unreachable`, the other envs continue.
3. `AutoindexFormatError` (abbreviated sizes) → `LogMessage(ERROR)`, status `errors`,
   nothing downloaded. A page with no daily file at all (captive portal, login page,
   proxy error answering 200) → `LogMessage(WARNING)`, status `unreachable`, state
   untouched.
4. Plan every listed daily, newest first, and emit `RemoteIndexRead` with
   `bytes_to_download` over the `download` plans. Per remote file: size 0 → `empty`;
   local size == remote → `present`; **local larger than remote → `shrunk`**; missing or
   smaller locally → `download`.
5. `shrunk` — **never shrink the archive**: `dest` is not touched. The remote copy is
   fetched into `YYYYMMDD.txt.remote-<size>` (skipped if already there with that size; the
   name never matches `DAILY_NAME_RE`, so the indexer ignores it), then `FileSkipped(…,
   "shrunk")` and one warning "… sul server è più piccolo della copia locale (L contro R):
   tenuta la copia locale, quella remota salvata come …" (or "impossibile salvare la copia
   remota (…)" when the sidecar failed). The day counts as mirrored, the status stays `ok`.
   If the local file can no longer be read when the shrunk day is handled (removed or locked
   since the plan), that file is a `FileFailed` "copia locale non più leggibile: …" (status
   `errors`), never an exception out of the run.
6. `download` — to `dest.with_name(name + ".part")`, chunked, `cancel.check()` per chunk,
   `FileProgress` throttled to ~10/s (the last one always sent). An attempt fails on
   `HttpDownloadError` or when the byte count differs from the listing ("troncato: W di S
   byte" / "dimensione inattesa: …"); it is retried **`config.sync.retries` times** (default
   1), each retry announced as a `LogMessage(WARNING, "… nuovo tentativo i/n")`. Then
   `fsutil.replace_with_retry(part, dest)` — a rename refused because a reader (the GUI
   indexer, a preview) holds `dest` open is retried, and if it still fails the file is a
   `FileFailed` "impossibile rinominare …" with the old local file intact. The `.part` is
   removed on every exit path.
7. `--dry-run`: no transfer; `FileSkipped(…, "dry-run", size)` per file that would be
   fetched (the CLI prints `[dry-run] scaricherei <name> (<size>) -> <dest>`); no state
   written and no index phase. `sync.log` still gets the listing line, then — worded as a
   preview so it never reads like a real run — `"<env>: anteprima, N da scaricare, …"`
   (`LoggingSink` remembers `SyncStarted.dry_run`) and the summary `"anteprima della
   sincronizzazione terminata …"` (`SyncReport.dry_run`). The window's "Anteprima" writes
   the same lines.
8. `failed > 0` → status `errors`, state untouched. Otherwise `mark_success(env,
   listing_at, newest_day=max(mirrored))`; a failed state write is a warning, not an error
   (see §state).

Never delete local files. Cancel → `.part` removed, status `cancelled`, state untouched,
exit 3.

The UI facade adds one network call the engine has no use for:
`facade.SyncService.check_reachable(env: Environment, timeout=5.0) -> bool` — one GET of
`env.url`, True only when `parse_autoindex` finds a daily or loose file (a captive portal
answers 200 with no log at all). It takes the `Environment`, never a name: its two callers
probe rows that are still being edited and are not in `config.json` yet. Never raises.

## Index

SQLite at `<mirror>\.qtrequestory\index.sqlite`, WAL, `busy_timeout`, `PRAGMA user_version`.
A damaged file (`sqlite3.DatabaseError` saying "not a database" / "malformed", raised by ANY
statement of `open_index`, which also reads the root page of both tables) is renamed to
`index.sqlite.broken-YYYYMMDD-HHMMSS`, its `-wal`/`-shm` deleted, and a fresh index created
(`log.warning`; at most 3 `.broken-*` copies kept). "locked"/"busy" errors are never treated so.

```sql
CREATE TABLE files (id INTEGER PRIMARY KEY, env TEXT NOT NULL, day TEXT NOT NULL, rel_path TEXT NOT NULL,
  size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL, n_entries INTEGER NOT NULL,
  n_orphans INTEGER NOT NULL DEFAULT 0, scanned_at TEXT NOT NULL, UNIQUE (env, day));
CREATE TABLE entries (id INTEGER PRIMARY KEY, file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  env TEXT NOT NULL, day TEXT NOT NULL, seq INTEGER NOT NULL, name TEXT NOT NULL,
  fdi TEXT, template_key TEXT NOT NULL COLLATE NOCASE, call_id TEXT, well_formed INTEGER NOT NULL,
  header_offset INTEGER NOT NULL, header_len INTEGER NOT NULL, body_offset INTEGER NOT NULL, body_len INTEGER NOT NULL,
  request_date TEXT, ndocs INTEGER, dossier_id TEXT, dossier_number TEXT, json_ok INTEGER NOT NULL DEFAULT 1);
CREATE INDEX ix_entries_env_day ON entries(env, day);
CREATE INDEX ix_entries_fdi ON entries(env, fdi);
CREATE INDEX ix_entries_key ON entries(env, template_key);
```
`SCHEMA_VERSION = 3` (3 added `entries.header_len`). Migration policy: any `user_version != SCHEMA_VERSION` → drop everything
and rebuild (a dropped table keeps its name in `schema.TABLES` so older databases lose it).
The migration runs inside `BEGIN IMMEDIATE` and re-reads the version under the lock (a second
process finds the work done); an "already exists" error re-checks the version and continues if current.

**Version 2 removed `entry_documents`** (one row per document per entry, plus
`ix_entry_documents_key`). Nothing ever selected from it: it was written on every index
build — the one operation the user waits for — and read by neither `search` nor
`list_template_keys`, which both go through `entries.template_key` (the principal key only).
Measured on a synthetic 72 MB / 16 000-entry mirror, a full rebuild went from 2.63 s to
1.78 s median (2.60 → 1.61 s best of five). It was speculative extensibility; the per-entry
document keys are still produced by the scanner as `ScannedEntry.doc_keys`, so a future
"find the pratica that carries attachment X" mode can re-add the table deliberately,
together with the query that reads it.

```python
# scanner.py
HEADER_RE = rb"^### (?P<name>.+?)\.json[ \t]*\r?\n?$" ; REQDATE_RE = rb'"requestDate":"([^"]*)"'
@dataclass(frozen=True) class ScannedEntry: seq; name: EntryName; header_offset; header_len; body_offset; body_len;
    request_date: str|None; ndocs: int|None; dossier_id; dossier_number; doc_keys: tuple[str,...]; json_ok: bool
@dataclass class ScanStats: n_entries; n_orphans
def scan_daily_file(path, *, parse_json=True, cancel=None) -> tuple[list[ScannedEntry], ScanStats]
```
Binary mode, `pos = f.tell(); line = f.readline()`. Header → pending; non-header with pending →
entry; non-header without pending → orphan; header while pending → previous header orphan.
`body_len = len(line.rstrip(b"\r\n"))`; `header_len` = raw header line bytes without terminator
(trailing blanks included). The name is decoded with `surrogateescape` (lossless); the builder stores
it as TEXT, or as the raw bytes (BLOB) if it is not valid UTF-8, and `fdi`/`template_key`/`call_id` with U+FFFD. JSON: `ndocs = len(d.get("documents") or [])`,
`doc_keys = [doc.get("template",{}).get("templateKey") ...]` (skip None), dossier fields.
On decode error: `json_ok=0`, `request_date` via `REQDATE_RE`, `ndocs=None`. `cancel.check()` every 50 entries.

```python
# builder.py
class IndexBuilder(conn, root, sink, cancel=None, *, parse_json=True):   # parse_json is keyword-only
    plan(envs) -> IndexPlan(to_scan: list[LocalDailyFile], to_remove: list[int])   # new or (size,mtime_ns) changed; vanished -> remove
    update(envs, *, full_rebuild=False) -> IndexStats       # one transaction per file; newest first; ANALYZE if >10 files
    rescan_file(env, day) -> int
# search.py
@dataclass(frozen=True) class SearchQuery: env; fdi_prefix: str|None=None; template_key: str|None=None;
    key_mode: Literal["exact","prefix","contains"]="exact"; day_from: date|None=None; day_to: date|None=None; limit: int=1000
@dataclass(frozen=True) class SearchHit: entry_id; env; day; rel_path; seq; name; fdi; template_key; call_id;
    well_formed; request_date; ndocs; dossier_number; header_offset; header_len; body_offset; body_len; json_ok
def search(conn, root, q) -> list[SearchHit]   # requires fdi_prefix or template_key (else ValueError);
                                           # `root` is the mirror root, so every SearchHit carries its file_path
def read_body(hit) -> bytes                # seek(header_offset), readline(max(header_len, len(expected))+8);
                                           # header == '### '+name(surrogateescape)+'.json' after rstrip(b" \t\r\n")
                                           # on both sides, and the line must end exactly at body_offset;
                                           # then read body_len+1: that extra byte must be CR, LF or EOF,
                                           # and the body slice must contain no LF nor END with CR (a shorter
                                           # body); a CR in the middle of a body is data and is returned.
                                           # Any mismatch -> IndexStale(env, day)
class IndexStale(Exception): env; day
@dataclass(frozen=True) class Coverage: first_day; last_day; n_files; n_entries
def coverage(conn, env) -> Coverage | None
def list_template_keys(conn, env, prefix="", limit=500) -> list[str]   # ordered by last day desc, count desc
def list_fdi_prefix(conn, env, prefix, limit=20) -> list[str]
def pick_best(hits, *, prefer_most_documents=False) -> tuple[SearchHit|None, list[SearchHit]]
    # the entry to extract + the other matches of the SAME day ("altre N entry");
    # by FDI alone the fullest documents[] wins (the entry holding the whole pratica),
    # ties keep the query order, ndocs=None ranks last.  Used by cli --find AND by the
    # Ricerca page to preselect the row after an FDI-only search.
```
**Staleness and self-repair.** The index is a cache of byte offsets into files the sync may
rewrite. `read_body` raises `IndexStale` on any mismatch (header name, header end, the byte
after the body, an LF inside the body or a body ending in CR). `IndexService.read_body`
then rescans that one day and retries once; the entry is found again on `(name, seq)`,
and on the name alone only when exactly one candidate has it (a replayed call appears twice
in a day; handing back the other copy's body would be silently wrong). A corrupt
`index.sqlite` is set aside and recreated by `open_index` (above) — `--index --rebuild`
goes through the same function, so it can no longer be stuck on "file is not a database".
Two processes that find the same corrupt file: the second re-opens first and uses the
first one's fresh index instead of setting it aside (a narrower race — the first one
already closed — remains, see BACKLOG).
SQL: `env=:env AND day BETWEEN … AND (fdi >= :p AND fdi < :p_hi) AND template_key = :key`
`ORDER BY day DESC, (request_date IS NULL), request_date DESC, seq DESC LIMIT :limit`.
`p_hi = p[:-1] + chr(ord(p[-1]) + 1)`. `prefix`/`contains` modes use LIKE with `ESCAPE '\'`.

## `core/extract.py`, `core/opener.py`

```python
def pretty_json(raw: bytes) -> str          # json.dumps(json.loads(raw), ensure_ascii=False, indent=4); on error -> {"_parseError": str, "raw": text}
def output_name(day, fdi, template_key, call_id=None) -> str   # '<yyyyMMdd>_<fdi or "nofdi">_<TEMPLATE_KEY>[_<call_id>].json'
                                            # search.output_name_for(hit) / output_name_with_id(hit) wrap it for a SearchHit
def write_temp_file(out_dir, name, text, *, retention_hours=24, alt_name=None) -> Path
                                            # housekeeping (delete files older than N h, best effort: a listing
                                            # or unlink error is skipped) then write; when `name` already
                                            # exists and `alt_name` (the call-id variant) is given, that one is used instead
def save_as(path, text) -> None             # utf-8, no BOM
def find_editor(configured: Path|None) -> Path|None   # configured → Notepad++ standard paths → PATH
def open_in_editor(paths: list[Path], editor: Path|None) -> str   # Popen(editor, *paths) else os.startfile each; returns label
```
Output contract (non-negotiable): the file content is the pure body, starts with
`{\n    "documents": [`, no wrapper, no comments, UTF-8 without BOM, accents intact.

Two differences from the legacy `nginx/find-call.py`, for the user-facing README:

- The extracted file ends with **a single trailing newline** and uses LF; the old
  script wrote CRLF and no final newline (it opened the file in text mode). The body
  is byte-for-byte the same otherwise — Postman, curl and every JSON parser read the
  two identically.
- Extracting the **same entry twice no longer overwrites** the first file: the second
  one is written as `..._<call_id>.json`, so a file still open in the editor is never
  replaced under the user's hands. The old script wiped its whole output folder on
  every run; here the folder is pruned by age (`output_retention_hours`, default 24 h).

## `core/scheduler.py`

```python
TASK_NAME = "qtRequestory Sync"; LEGACY_TASK_NAME = "NginxLogSync"
@dataclass(frozen=True) class TaskSpec: exe: Path; args: str = "--sync"; start_time: time = time(9,0); repeat_every_h=1; repeat_for_h=9; run_at_logon=True; exec_limit_h=3
def spec_from_config(schedule: ScheduleSettings, exe) -> TaskSpec   # the saved schedule (through
                                                                    # config.sanitised_schedule) is what gets registered
@dataclass(frozen=True) class TaskStatus: registered; command: Path|None; args; exe_matches: bool; state; next_run; last_run; last_result: int|None
def build_task_xml(spec, user_id, description, today=None) -> str
# every runner/task_name below is KEYWORD-ONLY (tests inject a fake runner; nothing positional)
def register(spec, *, runner=run_schtasks, user_id=None, description=None, task_name=TASK_NAME)
def unregister(*, runner=run_schtasks, task_name=TASK_NAME)
def status(current_exe, *, runner=run_schtasks, task_name=TASK_NAME) -> TaskStatus
def run_now(*, runner=run_schtasks, task_name=TASK_NAME)
def detect_legacy_task(*, runner=run_schtasks) -> bool ; def remove_legacy_task(*, runner=run_schtasks)
def current_exe_for_task() -> Path | None        # sys.executable when frozen; else None (dev: python -m qtrequestory)
def is_unstable_location(exe: Path) -> str | None   # %TEMP%, Downloads, network/OneDrive -> reason
```
`schtasks /Create /TN "<name>" /XML <utf-16 file> /F`; XML: `CalendarTrigger` (today 09:00,
`ScheduleByDay DaysInterval=1`, `Repetition Interval=PT1H Duration=PT9H` — omitted entirely when
`repeat_for_h == 0`, i.e. a single daily run), `LogonTrigger` (only when `run_at_logon`),
`Principal LogonType=InteractiveToken RunLevel=LeastPrivilege`, `Settings`:
`MultipleInstancesPolicy=IgnoreNew`, `DisallowStartIfOnBatteries=false`,
`StopIfGoingOnBatteries=false`, `StartWhenAvailable=true`, `ExecutionTimeLimit=PT3H`,
`Exec Command=<exe> Arguments=--sync WorkingDirectory=<exe dir>`. subprocess with
`CREATE_NO_WINDOW`, `encoding="oem", errors="replace"`. Status via `/Query /TN name /XML ONE`
(parse Command/Arguments) + `/Query /TN name /V /FO CSV /NH` (positional columns).
Pitfalls: never derive paths from argv[0]/cwd; windowed exe has `sys.stdout is None`.
`status` and `detect_legacy_task` **never raise**: both are called while a UI page (and the
wizard) is being *built*, and `MainWindow._build_page` turns any exception from a factory
into "La pagina … non è disponibile in questa versione". `OSError` from the runner
(`FileNotFoundError` when `%SystemRoot%\System32` is off `PATH`) and `ET.ParseError` from
garbled output are logged and answered with `NOT_REGISTERED` / `False`. A failure of the
*second* (`/V /FO CSV`) query only blanks the runtime columns — the registration already
read from the XML is kept.

## `core/jobs.py`, `cli.py`

```python
@dataclass(frozen=True) class JobReport: sync: SyncReport|None; indexed_files: int; exit_code: int
def run_sync_job(config, *, envs=None, force=False, dry_run=False, sink, cancel, http=None) -> JobReport
    # lock (held -> LogMessage + exit 0) -> SyncEngine.run -> IndexBuilder.update(envs) -> report
def run_index_job(config, *, envs=None, full_rebuild=False, sink, cancel) -> JobReport
```
`run_sync_job` with the lock held by another process logs "sincronizzazione già in corso
(<holder>)" and returns exit 0 with `sync=None` — for the hourly task that is not a failure.
The index phase after a sync covers every configured environment, enabled or not (a
disabled env may still hold history worth searching). Explicit `envs` go through
`config.require_env` in both jobs: an unknown name raises `UnknownEnvironment` (exit 2).

CLI (`cli.main(argv) -> int`), first two things:

1. **Console attach.** The exe is windowed (`console=False`), so a headless mode typed in a
   terminal used to print nothing. For `--sync/--index/--find/--task/--version` (decided on
   the raw argv, before argparse), `AttachConsole(ATTACH_PARENT_PROCESS)`; when it succeeds
   `sys.stdout`/`sys.stderr` are reopened on `CONOUT$` — both, or neither. Under the
   scheduled task or a double-click there is no parent console, the call returns 0 and
   nothing changes. Every failure is swallowed.
2. `_guard_std_streams`: if `sys.stdout` / `sys.stderr` is still `None`, devnull.

```
qtRequestory.exe                                   GUI
qtRequestory.exe --sync [--env X]... [--force] [--dry-run]
qtRequestory.exe --index [--rebuild] [--env X]...
qtRequestory.exe --find -e ENV (-f FDI | -k KEY | both) [--days N | --from D --to D] [--out PATH] [--no-open]
qtRequestory.exe --task install|remove|status|run
qtRequestory.exe --config PATH                     # every mode; only config.json moves, logs stay in the app dir
qtRequestory.exe --version
```

Exit codes:

| code | `--sync` | `--index` | `--find` | `--task` |
|---|---|---|---|---|
| 0 | ok, nothing to do, or lock held by another run | ok | extracted | ok |
| 1 | file errors, or an unexpected exception (logged with traceback to `sync.log`) | index failure / unexpected exception | nothing found | `status`: no task registered; scheduler error |
| 2 | **no environment reachable**, *or* a config error: unknown `-e`, `mirror_root` empty/relative | config error (unknown `-e`, `mirror_root`) | config error (unknown `-e`, `mirror_root`) | — |
| 3 | cancelled (Ctrl+C) | cancelled | — | — |

`EXIT_CONFIG_ERROR = 2` deliberately shares the number with the engine's "nothing
reachable": both mean "nothing was synced, look at the setup/network", but they are
distinguishable only by the printed message (config errors print "Errore…"/"Errore di
configurazione: …" before any job starts). A script that must tell them apart has to read
the output.

The pre-run gate for `--sync/--index/--find` checks **only** `mirror_root`
(`mirror_root_errors`), not the full `validate`: a bad `log_level` or schedule falls back
silently and must never stop the scheduled sync. `_run_job` catches every other exception,
logs it with its traceback to `sync.log` and returns 1 — in the windowed exe an unhandled
exception would be a PyInstaller dialog nobody dismisses, and `IgnoreNew` would then drop
every following hourly trigger.
Every mode: `app_paths()` (+ `--config` -> `AppPaths.config_override`), `load_config`,
`configure_logging(paths, headless=<not GUI>, level=config.log_level)`. `--sync`/`--index`
call the jobs with `LoggingSink(sync_logger())` and a fresh `CancelToken` and return
`report.exit_code`; SIGINT sets the token, so the job unwinds and exits 3. `--find` is the
legacy `nginx/find-call.py` on top of the index (first hit of the newest matching day, the
"altre N entry" hint for the rest of that day, `pretty_json` + `write_temp_file`/`--out`,
editor unless `--no-open`, exit 1 when nothing matches). `--task status` exits 1 when no task
is registered. Qt is imported ONLY inside the GUI branch (`tests/test_cli.py` checks it in a
subprocess).

## Packaging (`qtRequestory.spec`, `scripts/build.ps1`)

One windowed onefile exe, no installer: the colleagues receive it over chat and run
it from wherever it lands. `pyinstaller qtRequestory.spec` from the repo venv
(python.org 3.12.10 / PySide6-Essentials 6.11.2 / PyInstaller 6.22.3); `scripts/build.ps1`
is the real entry point — it refuses a non-venv or Microsoft Store interpreter, runs the
full pytest suite and aborts on red, then builds, then *runs* the produced exe
(`--version`, `--task status`, and `--find` against a throwaway config in `%TEMP%`
pointing at an empty mirror, which must answer "nessuna chiamata trovata" with exit 1).
Entry script: `scripts/entrypoint.py`, not `qtrequestory/__main__.py` — PyInstaller
prepends the entry script's directory to `sys.path`, and from inside the package that
would make `core`/`ui` importable a second time as top-level packages.

`console=False` (no console flash, invisible hourly `--sync`; `cli._guard_std_streams`
covers the resulting `sys.stdout is None`) and `upx=False` (packed exes get quarantined).
Version resource: `scripts/version_info.txt` is generated from `version_info.txt.in` by
`scripts/make_version_info.py`, so `__version__` is written down once. Icon:
`ui/icons/app.ico`, committed, generated by `scripts/make_icon.py` from `app.svg` (and the
hand-tuned `app-16.svg` for 16 px): 16/20/24/32/40/48/64 as 32-bit BMP entries, 256 as PNG.
It is also **bundled** as data (`qtrequestory/ui/icons/app.ico`): at runtime
`icons.app_icon()` loads every size from it, so the window icon carries the large sizes the
taskbar needs (see DESIGN-ui §Visual style for the AppUserModelID).

**Hidden import — the one that matters.** `ui/main_window.py` reaches the four pages
through `importlib.import_module(f"{PAGES_PACKAGE}.{module}")`. A computed module name is
invisible to PyInstaller, so the whole `qtrequestory.ui.pages` package was left out of the
first build; because `MainWindow._build_page` swallows the `ModuleNotFoundError` by
design, the exe started, drew the navigation and showed "La pagina «Ricerca» non è disponibile
in questa versione." on all four pages. Fixed with
`hiddenimports=collect_submodules("qtrequestory.ui.pages")`. `tests/test_packaging.py`
guards two halves of this, and it is worth being precise about which: it fails when a
*new* dynamic importer appears in `src/` (any of `importlib.import_module(`,
a bare `import_module(`, `__import__(`) that is not in `KNOWN_DYNAMIC_IMPORTERS`, and it
fails when the spec stops *calling* `collect_submodules("qtrequestory.ui.pages")` or stops
passing the result as `hiddenimports=PAGE_MODULES`. It does **not** derive the list of
needed entries from the code, so a new dynamic importer still has to be wired into the
spec by hand — the test only refuses to let it pass unnoticed.

**Exclusions that worked** (each verified by running the built exe, GUI included):
`tkinter`, `unittest`, `pydoc`, `doctest`; the Qt Python modules the app never imports
(`QtQml`, `QtQuick*`, `QtDBus`, `QtOpenGL`, `QtOpenGLWidgets`, `QtDesigner`, `QtUiTools`,
`QtHelp`, `QtTest`, `QtSql`, plus the Addons modules so a full `PySide6` wheel in the build
venv cannot quietly fatten the exe). Two binaries are filtered out of `a.binaries`, where
a module exclusion has no effect: `opengl32sw.dll` (19.7 MB — Qt's software GL renderer;
the UI is QtWidgets on the raster engine) and any `libssl-3-*`/`libcrypto-3-*` that does
not come from the Python installation (7.7 MB — PyInstaller's QtNetwork hook ships
whatever OpenSSL it finds on the *build machine's* PATH, which also made the build
non-reproducible; Python's own pair stays, `urllib` needs it for the real HTTPS downloads).

**NOT excluded, on purpose:** `PySide6.QtNetwork` (the `QLocalServer` single-instance
guard in `ui/app.py`) and `PySide6.QtSvg` (`Qt6Svg.dll` backs the `imageformats/qsvg.dll`
plugin that renders every icon).

Measured: 39.81 MB before the two binary filters, **30.18 MB** after. Qt DLLs shipped:
`Qt6Core`, `Qt6Gui`, `Qt6Widgets`, `Qt6Network`, `Qt6Svg` — nothing else. Start-up is
**~7.4 s cold, ~4.9 s warm** (`--version`): onefile unpacks the whole 27 MB payload into
`%TEMP%` on *every* run, hourly scheduled `--sync` included, and the AV scans it. That is
the price of one file to hand out; a onedir build would start in a fraction of the time.

**If anyone ever reports a blank or black window**, the dropped `opengl32sw.dll` is the
first suspect: a VDI/RDP session, a blacklisted GPU driver or `QT_OPENGL=software` in the
environment makes Qt ask for the software GL renderer that is no longer in the bundle.
Confirm by removing `"opengl32sw.dll"` from `DROP_BINARIES` in the spec and rebuilding
(+19.7 MB uncompressed, ~9 MB on the exe) before looking anywhere else.

The scheduled task must point at a copy in a stable folder
(`%LOCALAPPDATA%\qtRequestory\bin\`), never at `dist\` — see `is_unstable_location`.

## Testing (pytest; fixtures are 100% synthetic — no real data ever)

`tests/conftest.py` fixtures:

- `synthetic_body(fdi, key, request_date="2026-09-18T10:38:28.776Z", ndocs=2, noise=True)`
  (includes `customData.templateKey` noise and `childDocuments`). The default `request_date`
  is a **fixed timestamp, not `None`**: a caller that wants no `requestDate` at all passes
  `request_date=None` explicitly. Entries built on the default tie on `request_date`, so a
  test that exercises `pick_best(prefer_most_documents=True)` must give its entries
  distinct dates itself — and give the fuller entry the *older* date, or the newest-first
  order would pick it anyway and the test could not fail.
- `make_daily_file(root, env, day, entries, crlf=True)`; `mirror(tmp_path)` (2 envs, 4 days,
  LF and CRLF files, one orphan body, one header without body, one `correlationId_vuoto_`
  entry, one `-t15` entry, one non-JSON body); `autoindex_html(entries, loose=0)`;
  `stub_server` (`ThreadingHTTPServer` on port 0, dict routes, fault modes: status,
  truncate_after, hang); `fake_clock`; `events` (collecting sink).
- Synthetic identifiers only: FDIs `aaaaaaaa-1111-…`, `bbbbbbbb-…`, `cccccccc-…`; template
  keys `MOD_ALPHA_*`, `CTR_OFFER_FIX_B`, `MOD_TEST_*` — never a real key or FDI.

`tests/test_no_qt_in_core.py` walks `core/` and asserts no `PySide6|PyQt|tkinter` import.
`tests/fakes/fake_core.py` implements the facade in memory for the UI tests;
`tests/test_fake_core.py` runs the same calls against the real facade on temp paths and the
fake (`run(None)` skips disabled envs, unknown env raises, `register` without an exe
fails, ordering of `list_template_keys`, `plan(envs)`, retention…) so the two cannot drift.
