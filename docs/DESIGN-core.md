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
  (`UUID_2_DECLARATION_CONS_PAPER_RP_ID`, `UUID_3_1_REQUEST_SAMPLE_DEBIT_ID`).
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
│   ├── config.py          Config, Environment, load/save/validate, import_environments_file, detect_editor
│   ├── logsetup.py        configure_logging(paths, headless)
│   ├── events.py          Event dataclasses, EventSink, LoggingSink, CancelToken, Cancelled
│   ├── daily.py           day/file-name helpers, list_local_daily_files, parse_entry_name
│   ├── autoindex.py       parse_autoindex(html) -> RemoteIndex
│   ├── http.py            HttpClient Protocol + UrllibHttpClient
│   ├── state.py           SyncState (+ legacy .last-sync.json import)
│   ├── lock.py            ProcessLock
│   ├── sync.py            SyncEngine
│   ├── index/schema.py    DDL, SCHEMA_VERSION, migrate
│   ├── index/db.py        open_index(path)
│   ├── index/scanner.py   scan_daily_file
│   ├── index/builder.py   IndexBuilder
│   ├── index/search.py    SearchQuery, SearchHit, search, read_body, coverage, list_template_keys
│   ├── extract.py         pretty_json, output_name, write_temp_file, housekeeping
│   ├── opener.py          find_editor, open_in_editor
│   ├── scheduler.py       TaskSpec, build_task_xml, register/unregister/status/run_now, detect_legacy_task
│   └── jobs.py            run_sync_job, run_index_job
└── ui/                    the only package allowed to import PySide6
```

Dependency direction: `ui -> jobs/search/config/scheduler/extract -> core internals`.
`cli.py` is the only module that knows both.

## Locations

- App dir: `%LOCALAPPDATA%\qtRequestory\` (override with env `QTREQUESTORY_HOME`):
  `config.json`, `logs\app.log`, `logs\sync.log` (RotatingFileHandler 1 MB × 3),
  `ui-state.json` (UI only).
- Mirror: `<mirror_root>\<env>\YYYY\MM\YYYYMMDD.txt`;
  `<mirror_root>\.qtrequestory\` holds `sync-state.json`, `sync.lock`, `index.sqlite`.
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
FileSkipped(env, name, reason: Literal["present","empty"])
FileStarted(env, name, size) · FileProgress(env, name, done, size) · FileDone(env, name, size, path)
FileFailed(env, name, error) · EnvFinished(env, result: EnvResult) · SyncFinished(report: SyncReport)
# index
IndexStarted(n_files_to_scan) · IndexFileScanned(path, n_entries, i, n) · IndexFinished(scanned, removed, seconds)
# generic
LogMessage(level: int, text: str)

EventSink = Callable[[Event], None]
class LoggingSink: __init__(logger); __call__(ev)      # headless: formats every event to logging
```

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
  "log_level": "INFO"
}
```
```python
@dataclass(frozen=True) class Environment: name: str; url: str; enabled: bool = True
@dataclass class SyncSettings / IndexSettings
@dataclass class Config: (fields above; paths as Path; compaction_time as datetime.time)
    index_path / state_path / lock_path / resolved_output_dir  (properties)
    def env(self, name) -> Environment
    def enabled_environments(self) -> list[Environment]
def default_config() -> Config                        # environments = []  (NO hostnames in code)
def load_config(path) -> Config      # missing -> defaults, file NOT created (a cancelled first-run wizard must stay a first run);
                                     # corrupt -> renamed .broken-<ts> + defaults written back; unknown keys ignored; missing keys defaulted
def save_config(cfg, path)           # tmp + os.replace
def validate(cfg) -> list[str]       # env name ^[A-Za-z0-9_-]+$ unique; url http(s)://…/ ; window 1..3650
def import_environments_file(path) -> list[Environment]   # JSON list [{"name","url","enabled"?}] — used by wizard / auto-import of environments.json next to the exe
def find_sidecar_environments(exe_dir) -> Path | None     # environments.json next to the exe
def detect_editor() -> Path | None   # Notepad++ in ProgramFiles / ProgramFiles(x86) / PATH
CONFIG_VERSION = 1; MIGRATIONS: dict[int, Callable[[dict], dict]] = {}
```

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
```
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
def parse_autoindex(html) -> RemoteIndex
```
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
@dataclass class EnvSyncState: last_success: datetime|None; last_remote_daily: int; last_downloaded: int
class SyncState(path):
    load()                       # tolerant; imports legacy <root>/.last-sync.json (utf-8-sig, {"svil":"YYYY-MM-DD"}) once
    get(env) -> EnvSyncState
    mark_success(env, when, **counts)     # atomic save
    is_fresh(env, now, compaction_time) -> bool
        # fresh iff last_success >= last_compaction_moment, where
        # last_compaction_moment = today@compaction_time if now >= that else yesterday@compaction_time
class ProcessLock(path): acquire(blocking=False) -> bool; release(); context manager   # msvcrt.locking
```

## `core/sync.py`

```python
@dataclass(frozen=True) class EnvResult: env; status: Literal["ok","fresh","unreachable","errors","cancelled"]; downloaded; present; empty; failed; bytes; error: str|None
@dataclass(frozen=True) class SyncReport: results: tuple[EnvResult,...]; started; finished
    exit_code -> int      # 0 ok/nothing, 1 file errors, 2 nothing reachable, 3 cancelled
class SyncEngine(config, http, state, sink, cancel=None, clock=datetime.now):
    run(envs=None, *, force=False, dry_run=False) -> SyncReport
    sync_env(env: Environment, *, force, dry_run) -> EnvResult
```
Per env: if not force and `state.is_fresh` → `EnvSkipped`, status `fresh`. GET index
(timeout `index_timeout_s`; any error → `EnvUnreachable`, status `unreachable`, other envs
continue). Emit `RemoteIndexRead` with `bytes_to_download` computed over files to fetch.
Newest first: size 0 → skip `empty`; local exists with same size → skip `present`; else
download to `dest.with_name(name + ".part")` chunked with `cancel.check()` per chunk and
throttled `FileProgress` (~10/s); verify `written == size` (else `FileFailed` "truncated");
`os.replace(part, dest)`; on any exception delete `.part`; one retry on `HttpDownloadError`.
Never delete local files. `mark_success` only when `failed == 0` and not dry_run.
Cancel → `.part` removed, status `cancelled`, state untouched, exit 3.

## Index

SQLite at `<mirror>\.qtrequestory\index.sqlite`, WAL, `busy_timeout`, `PRAGMA user_version`.

```sql
CREATE TABLE files (id INTEGER PRIMARY KEY, env TEXT NOT NULL, day TEXT NOT NULL, rel_path TEXT NOT NULL,
  size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL, n_entries INTEGER NOT NULL,
  n_orphans INTEGER NOT NULL DEFAULT 0, scanned_at TEXT NOT NULL, UNIQUE (env, day));
CREATE TABLE entries (id INTEGER PRIMARY KEY, file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  env TEXT NOT NULL, day TEXT NOT NULL, seq INTEGER NOT NULL, name TEXT NOT NULL,
  fdi TEXT, template_key TEXT NOT NULL COLLATE NOCASE, call_id TEXT, well_formed INTEGER NOT NULL,
  header_offset INTEGER NOT NULL, body_offset INTEGER NOT NULL, body_len INTEGER NOT NULL,
  request_date TEXT, ndocs INTEGER, dossier_id TEXT, dossier_number TEXT, json_ok INTEGER NOT NULL DEFAULT 1);
CREATE INDEX ix_entries_env_day ON entries(env, day);
CREATE INDEX ix_entries_fdi ON entries(env, fdi);
CREATE INDEX ix_entries_key ON entries(env, template_key);
CREATE TABLE entry_documents (entry_id INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
  pos INTEGER NOT NULL, template_key TEXT NOT NULL COLLATE NOCASE, PRIMARY KEY (entry_id, pos));
CREATE INDEX ix_entry_documents_key ON entry_documents(template_key);
```
Migration policy: any `user_version != SCHEMA_VERSION` → drop everything and rebuild.

```python
# scanner.py
HEADER_RE = rb"^### (?P<name>.+?)\.json[ \t]*\r?\n?$" ; REQDATE_RE = rb'"requestDate":"([^"]*)"'
@dataclass(frozen=True) class ScannedEntry: seq; name: EntryName; header_offset; body_offset; body_len;
    request_date: str|None; ndocs: int|None; dossier_id; dossier_number; doc_keys: tuple[str,...]; json_ok: bool
@dataclass class ScanStats: n_entries; n_orphans
def scan_daily_file(path, *, parse_json=True, cancel=None) -> tuple[list[ScannedEntry], ScanStats]
```
Binary mode, `pos = f.tell(); line = f.readline()`. Header → pending; non-header with pending →
entry; non-header without pending → orphan; header while pending → previous header orphan.
`body_len = len(line.rstrip(b"\r\n"))`. JSON: `ndocs = len(d.get("documents") or [])`,
`doc_keys = [doc.get("template",{}).get("templateKey") ...]` (skip None), dossier fields.
On decode error: `json_ok=0`, `request_date` via `REQDATE_RE`, `ndocs=None`. `cancel.check()` every 50 entries.

```python
# builder.py
class IndexBuilder(conn, root, sink, cancel=None):
    plan(envs) -> IndexPlan(to_scan: list[LocalDailyFile], to_remove: list[int])   # new or (size,mtime_ns) changed; vanished -> remove
    update(envs, *, full_rebuild=False) -> IndexStats       # one transaction per file; newest first; ANALYZE if >10 files
    rescan_file(env, day) -> int
# search.py
@dataclass(frozen=True) class SearchQuery: env; fdi_prefix: str|None=None; template_key: str|None=None;
    key_mode: Literal["exact","prefix","contains"]="exact"; day_from: date|None=None; day_to: date|None=None; limit: int=1000
@dataclass(frozen=True) class SearchHit: entry_id; env; day; rel_path; seq; name; fdi; template_key; call_id;
    well_formed; request_date; ndocs; dossier_number; header_offset; body_offset; body_len; json_ok
def search(conn, q) -> list[SearchHit]     # requires fdi_prefix or template_key (else ValueError)
def read_body(root, hit) -> bytes          # seek(header_offset), verify header line == '### '+name+'.json', then seek(body_offset).read(body_len); mismatch -> IndexStale(env, day)
class IndexStale(Exception): env; day
@dataclass(frozen=True) class Coverage: first_day; last_day; n_files; n_entries
def coverage(conn, env) -> Coverage | None
def list_template_keys(conn, env, prefix="", limit=500) -> list[str]   # ordered by last day desc, count desc
def list_fdi_prefix(conn, env, prefix, limit=20) -> list[str]
def pick_best(hits, *, prefer_most_documents=False) -> tuple[SearchHit|None, list[SearchHit]]
    # the entry to extract + the other matches of the SAME day ("altre N entry");
    # by FDI alone the fullest documents[] wins (the entry holding the whole pratica),
    # ties keep the query order, ndocs=None ranks last.  Used by cli --find.
```
SQL: `env=:env AND day BETWEEN … AND (fdi >= :p AND fdi < :p_hi) AND template_key = :key`
`ORDER BY day DESC, (request_date IS NULL), request_date DESC, seq DESC LIMIT :limit`.
`p_hi = p[:-1] + chr(ord(p[-1]) + 1)`. `prefix`/`contains` modes use LIKE with `ESCAPE '\'`.

## `core/extract.py`, `core/opener.py`

```python
def pretty_json(raw: bytes) -> str          # json.dumps(json.loads(raw), ensure_ascii=False, indent=4); on error -> {"_parseError": str, "raw": text}
def output_name(hit) -> str                 # '<yyyyMMdd>_<fdi or "nofdi">_<TEMPLATE_KEY>.json'
def write_temp_file(out_dir, hit, text, *, retention_hours=24) -> Path   # housekeeping (delete files older than N h) then write; on name collision append '_<call_id>'
def save_as(path, text) -> None             # utf-8, no BOM
def find_editor(configured: Path|None) -> Path|None   # configured → Notepad++ standard paths → PATH
def open_in_editor(paths: list[Path], editor: Path|None) -> str   # Popen(editor, *paths) else os.startfile each; returns label
```
Output contract (non-negotiable): the file content is the pure body, starts with
`{\n    "documents": [`, no wrapper, no comments, UTF-8 without BOM, accents intact.

## `core/scheduler.py`

```python
TASK_NAME = "qtRequestory Sync"; LEGACY_TASK_NAME = "NginxLogSync"
@dataclass(frozen=True) class TaskSpec: exe: Path; args: str = "--sync"; start_time: time = time(9,0); repeat_every_h=1; repeat_for_h=9; run_at_logon=True; exec_limit_h=3
@dataclass(frozen=True) class TaskStatus: registered; command: Path|None; args; exe_matches: bool; state; next_run; last_run; last_result: int|None
def build_task_xml(spec, user_id, description) -> str
def register(spec, runner=run_schtasks) ; def unregister(runner) ; def status(current_exe, runner) -> TaskStatus
def run_now(runner) ; def detect_legacy_task(runner) -> bool ; def remove_legacy_task(runner)
def current_exe_for_task() -> Path | None        # sys.executable when frozen; else None (dev: python -m qtrequestory)
def is_unstable_location(exe: Path) -> str | None   # %TEMP%, Downloads, network/OneDrive -> reason
```
`schtasks /Create /TN "<name>" /XML <utf-16 file> /F`; XML: `CalendarTrigger` (today 09:00,
`ScheduleByDay DaysInterval=1`, `Repetition Interval=PT1H Duration=PT9H`), `LogonTrigger`,
`Principal LogonType=InteractiveToken RunLevel=LeastPrivilege`, `Settings`:
`MultipleInstancesPolicy=IgnoreNew`, `DisallowStartIfOnBatteries=false`,
`StopIfGoingOnBatteries=false`, `StartWhenAvailable=true`, `ExecutionTimeLimit=PT3H`,
`Exec Command=<exe> Arguments=--sync WorkingDirectory=<exe dir>`. subprocess with
`CREATE_NO_WINDOW`, `encoding="oem", errors="replace"`. Status via `/Query /TN name /XML ONE`
(parse Command/Arguments) + `/Query /TN name /V /FO CSV /NH` (positional columns).
Pitfalls: never derive paths from argv[0]/cwd; windowed exe has `sys.stdout is None`.

## `core/jobs.py`, `cli.py`

```python
@dataclass(frozen=True) class JobReport: sync: SyncReport|None; indexed_files: int; exit_code: int
def run_sync_job(config, *, envs=None, force=False, dry_run=False, sink, cancel, http=None) -> JobReport
    # lock (held -> LogMessage + exit 0) -> SyncEngine.run -> IndexBuilder.update(envs) -> report
def run_index_job(config, *, envs=None, full_rebuild=False, sink, cancel) -> JobReport
```
CLI (`cli.main(argv) -> int`), first thing: if `sys.stdout is None` install devnull streams.
```
qtRequestory.exe                                   GUI
qtRequestory.exe --sync [--env X]... [--force] [--dry-run]     exit 0/1/2/3
qtRequestory.exe --index [--rebuild] [--env X]...              exit 0/1/3
qtRequestory.exe --find -e ENV (-f FDI | -k KEY | both) [--days N | --from D --to D] [--out PATH] [--no-open]
qtRequestory.exe --task install|remove|status|run
qtRequestory.exe --config PATH                     # every mode; only config.json moves, logs stay in the app dir
qtRequestory.exe --version
```
Every mode: `app_paths()` (+ `--config` -> `AppPaths.config_override`), `load_config`,
`configure_logging(paths, headless=<not GUI>, level=config.log_level)`. `--sync`/`--index`
call the jobs with `LoggingSink(sync_logger())` and a fresh `CancelToken` and return
`report.exit_code`; SIGINT sets the token, so the job unwinds and exits 3. `--find` is the
legacy `nginx/find-call.py` on top of the index (first hit of the newest matching day, the
"altre N entry" hint for the rest of that day, `pretty_json` + `write_temp_file`/`--out`,
editor unless `--no-open`, exit 1 when nothing matches). `--task status` exits 1 when no task
is registered. Qt is imported ONLY inside the GUI branch (`tests/test_cli.py` checks it in a
subprocess).

## Testing (pytest; fixtures are 100% synthetic — no real data ever)

`tests/conftest.py` fixtures: `synthetic_body(fdi, key, request_date=None, ndocs=2, noise=True)`
(includes `customData.templateKey` noise and `childDocuments`), `make_daily_file(root, env, day,
entries, crlf=True)`, `mirror(tmp_path)` (2 envs, 4 days, LF and CRLF files, one orphan body,
one header without body, one `correlationId_vuoto_` entry, one `-t15` entry, one non-JSON
body), `autoindex_html(entries, loose=0)`, `stub_server` (`ThreadingHTTPServer` on port 0, dict
routes, fault modes: status, truncate_after, hang), `fake_clock`, `events` (collecting sink).
`tests/test_no_qt_in_core.py` walks `core/` and asserts no `PySide6|PyQt|tkinter` import.
