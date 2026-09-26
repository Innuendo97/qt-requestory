# qtRequestory — core design (v1)

The core is the UI-agnostic engine: sync, index, search, extract, scheduler, config.
**Rule: `qtrequestory.core` imports only the standard library** (a test enforces it).
Everything here is callable from the CLI (`--sync`, `--index`, `--find`, `--task`,
`--archivio`, `--import`) and from the PySide6 UI through the same functions.
The Officina engine (`qtrequestory.officina`, §Officina) sits beside the core: it is Qt-free
too, may use `pypdfium2` (only through `officina/pdf.py`, loaded lazily), and imports the
core — never the other way round (`tests/test_no_qt_in_core.py` checks both).

## Domain facts (measured on real data; fixtures must reproduce them synthetically)

- Server exposes an nginx autoindex page per environment
  (`https://<host>/AutoDeploy/Input/`). Entries: `YYYYMMDD.txt` (one per day; **0 bytes**
  on weekends/holidays), plus loose `<uuid>_<TEMPLATE_KEY>_<id16hex>.json` files for the
  current day (compacted into the daily file at ~18:30). **The server keeps its daily
  files until a manual purge from the OCP terminal, which deletes them**; a day without
  traffic is published as a 0-byte file, so a 0-byte file always means "no traffic".
  The local mirror is the only lasting archive: what the purge deletes before a sync
  downloaded it is gone, while a day that is still listed can always be fetched later.
  A first sync therefore downloads the whole history since the last purge.
- Colleagues keep old logs in arbitrary layouts (flat folders, `env/YYYYMMDD.txt`,
  `YYYY/MM/env/…`, Italian dates, extracted zips). They are never indexed in place: they are
  COPIED into the canonical tree (§Archive import).
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
├── cli.py                 argparse; --sync/--index/--find/--task/--archivio/--import; imports ui lazily
├── cli_archive.py         --archivio / --import (kept apart from cli.py for size)
├── core/
│   ├── paths.py           AppPaths
│   ├── config.py          Config, Environment, load/save/validate, UnknownEnvironment, import_environments_file, detect_editor, IGNORE_FOLDER
│   ├── logsetup.py        configure_logging(paths, headless, level), resolve_level
│   ├── events.py          Event dataclasses, EventSink, LoggingSink, CancelToken, Cancelled, format_size
│   ├── daily.py           day/file-name helpers, list_local_daily_files, count_local_files, parse_entry_name,
│   │                      CoverageDays, classify_days
│   ├── archive_names.py   day and env from the elements of a path (any layout, Italian dates)
│   ├── archive.py         discover(root, env_names, folder_envs) -> ArchiveReport; compare_files
│   ├── importer.py        run_import -> ImportResult; VerifiedOriginal; send_to_recycle_bin, check_original
│   ├── autoindex.py       parse_autoindex(html) -> RemoteIndex, AutoindexFormatError
│   ├── http.py            HttpClient Protocol + UrllibHttpClient
│   ├── fsutil.py          replace_with_retry, remove_quietly, is_within, paths_overlap, real_is_within, same_file
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
│   └── facade.py          Config/Sync/Scheduler/Index/Extract/ArchiveService, ArchiveBusy: what the UI calls
├── officina/              the Officina tab's engine (§Officina); Qt-free, never imported by core or cli
│   ├── __init__.py        empty: importing the package loads nothing heavy
│   ├── model.py           Workspace, Initiative (+ re-exports Case, Version): initiatives and cases on disk
│   ├── model_case.py      Case and its caso.json (load, save merge, reopen), case_write_lock, write_review
│   ├── model_review.py    Review, Tolerance, Mark, NoiseRule: the review keys of caso.json / iniziativa.json
│   ├── model_versions.py  Version: reading/writing TARGET, AS-IS and TO-BE files and metas
│   ├── model_io.py        atomic writes (unique temp file), tolerant / strict JSON reads, read_text_retrying
│   ├── links.py           upload links (SAS): find_links, remove_links, signed_links, mask, mask_text
│   ├── generator.py       resolve_headers, prepare_payload, send, sniff, SendResult, HeaderError
│   ├── service.py         OfficinaService (behind ui/contracts.OfficinaApi): workspace, generate, delivery
│   ├── service_compare.py CompareMixin (compare without verdict, render_path, Edge print cache), CompareError
│   ├── service_case.py    CaseInputsMixin: engine inputs per version, cached pairs, custom rules via the guard
│   ├── service_review.py  ReviewMixin: compare_case, the review actions, profile, noise rules, dom_view
│   ├── delivery.py        build_plan/plan_delivery, deliver/run_delivery, safe_component
│   ├── pdf.py             THE ONLY pypdfium2 importer: read_chars (+ fonts), page_sizes, page_count, render_page, TextSearch
│   └── compare/           the staged comparison engine (§Comparison engine); pure, stdlib only
│       ├── model.py       THE CONTRACT: Word, Block, Anchor, Diff, Comparison, Judged, CaseSummary,
│       │                  Verification, CaseComparison, COUNTING
│       ├── extract_pdf.py Word, DocText, extract (pypdfium2 loaded inside extract())
│       ├── extract_html.py extract_html (html.parser) -> Blocks + pretty source; attr_diffs, locate
│       ├── html_boxes.py  boxes for HTML words from Edge's print
│       ├── cache.py       the extraction cache on disk (extract-<sha>.json)
│       ├── normalise.py   normalise_token, units (comb fields, checkboxes, dehyphenation, punctuation)
│       ├── slots.py       variable slots of the target, absorb, slot_anchor
│       ├── noise.py       PRESETS, compile_rules (risky-pattern check), apply (placeholders)
│       ├── noise_guard.py custom noise rules in a killable child process (2 s budget): counts, spans
│       ├── sides.py       prepare: both sides up to the noise stage (Prepared.noise_sides), noise_stage
│       ├── blocks.py      lines, columns, paragraphs, form rows -> Blocks
│       ├── hungarian.py   assignment solver (no scipy)
│       ├── align.py       block alignment: exact matches, weighted score, Hungarian
│       ├── worddiff.py    word diff over the whole sequence (patience cuts), char_spans
│       ├── bounds.py      unmatched blocks as hard boundaries of the word diff
│       ├── moves.py       reading order, out-of-order pairs, text moves
│       ├── classify.py    one class per difference; counts(profile, klass)
│       ├── anchor_keys.py the target keys an Anchor is taken on
│       ├── anchors.py     disambiguate: "#n" on repeated anchors
│       ├── display.py     context_before / context_after of a difference
│       ├── linkdiff.py    the link differences of an HTML pair
│       ├── urls.py        URL normalisation, TRACKING_KEYS / tracking_drop
│       ├── pipeline.py    compare_docs = sides.prepare + finish: every stage, composed
│       ├── verdict.py     judge: three-way verdict, tolerances, marks, summary; generated_text, inactive
│       ├── sanitise.py    sanitise_html (allow-list) + CSP
│       └── edge.py        find_edge, html_to_pdf (Microsoft Edge headless)
├── THIRD-PARTY-NOTICES.md licences of the bundled third-party components (§Packaging)
└── ui/                    the only package allowed to import PySide6
```

Dependency direction: `ui -> jobs/search/config/scheduler/extract -> core internals`, and
`ui -> officina.service -> officina.* -> core.config/fsutil/index.search`.
`cli.py` is the only module that knows both core and ui; it never imports `officina` itself.

## Locations

- App dir: `%LOCALAPPDATA%\qtRequestory\` (override with env `QTREQUESTORY_HOME`):
  `config.json`, `logs\app.log`, `logs\sync.log` (RotatingFileHandler 1 MB × 3).
  `--config PATH` moves only `config.json`.
- UI preferences (window geometry, last environment, theme mode, search options, recent
  searches) are not files: they live in `QSettings` (`HKCU\Software\qtRequestory\qtRequestory`),
  opened only through `ui/actions.user_settings()`.
- Mirror: `<mirror_root>\<env>\YYYY\MM\YYYYMMDD.txt` (a 0-byte file is a day the server
  listed empty, see §`core/sync.py` step 4; only this exact path counts, see §`core/daily.py`),
  plus the occasional
  `YYYYMMDD.txt.remote-<size>` (a server copy smaller than the local day, see §`core/sync.py`)
  and a `.part` while a download runs; `<mirror_root>\.qtrequestory\` holds
  `sync-state.json`, `sync.lock`, `index.sqlite` (+ `-wal`/`-shm`, and up to 3
  `index.sqlite.broken-*`).
- Output dir default: `%TEMP%\qtrequestory-calls\`. It is pruned by age, so it may never
  overlap the mirror (§`core/config.py`, §`core/extract.py`).

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
  "log_level": "INFO",
  "folder_envs": {"D:\\old-logs\\misc": "coll", "D:\\old-logs\\junk": "__ignora__"},
  "officina": {
    "root": "C:\\Users\\<u>\\Officina",
    "generators": [ {"name": "svil", "url": "https://<host>/<path>/documentGenerator", "enabled": true} ],
    "default_generator": "svil",
    "postman_token": "qtRequestory",
    "header_profile": {"service_number": "service_number", "office_id": "office_id", "branch_id": "branch_id"},
    "timeout_s": 120
  }
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
                                     # log_level: a name logging knows (via logsetup.resolve_level);
                                     # + output_dir_errors
def output_dir_errors(cfg) -> list[str]   # resolved_output_dir == mirror_root, inside it, or containing it
IGNORE_FOLDER = "__ignora__"              # folder_envs value: "do not import this folder"
def mirror_root_errors(cfg) -> list[str]  # only the mirror_root part of validate (the CLI gate)
class UnknownEnvironment(ValueError)      # "ambiente sconosciuto: 'x' (configurati: coll, svil)"
Config.require_env(name) -> Environment   # env(name), but UnknownEnvironment instead of KeyError
def import_environments_file(path) -> list[Environment]   # JSON list [{"name","url","enabled"?}] — used by wizard / auto-import of environments.json next to the exe
def find_sidecar_environments(exe_dir) -> Path | None     # environments.json next to the exe
def detect_editor() -> Path | None   # Notepad++ in ProgramFiles / ProgramFiles(x86) / PATH
CONFIG_VERSION = 1; MIGRATIONS: dict[int, Callable[[dict], dict]] = {}

# the Officina block (generators are NOT the log environments: those are only read)
@dataclass class GeneratorEndpoint: name: str; url: str; enabled: bool = True
@dataclass class OfficinaSettings:
    root: Path | None = None                 # None = not chosen yet (the tab shows its chooser)
    generators: list[GeneratorEndpoint] = [] # ships empty: no hostname in the repo
    default_generator: str = "svil"
    postman_token: str = "qtRequestory"      # non-empty: keeps test calls out of the nginx logs
    header_profile: dict[str, str] = {"service_number": ..., "office_id": ..., "branch_id": ...}  # placeholders
    timeout_s: int = 120                     # OFFICINA_TIMEOUT_RANGE = (1, 600)
    def generator(self, name) -> GeneratorEndpoint        # KeyError when unknown
    def enabled_generators(self) -> list[GeneratorEndpoint]
Config.officina: OfficinaSettings                          # the last field; a missing block = defaults
# shared validators: validate(), Impostazioni (inline, per row) and the generator client use the SAME functions
def is_prod_like(text) -> bool                           # "prod", or "prd" as a token, after NFKC + casefold, raw and percent-decoded
def generator_url_problem(url, *, allow_loopback_http=False) -> str | None   # prod, non-ASCII, unreadable host/port,
                                                         # no host, not https (http only to loopback, for tests)
def generator_problems(generators) -> list[list[str]]    # per row: empty/prod-like name, URL problem, duplicate name (casefold)
def default_generator_problem(o) -> str | None           # generators configured but the default is not an enabled one
def postman_token_problem(token) -> str | None           # empty or blank
HTTP_CLIENT_HEADERS: frozenset[str]                      # Host, Content-Length, Transfer-Encoding, Connection, …
def header_name_problem(name) / header_value_problem(name, value) -> str | None   # RFC token, not a client header; no CR/LF, latin-1
def header_problems(rows) -> list[list[str]]             # per row + case-insensitive duplicates
def officina_root_errors(cfg) -> list[str]               # absolute; not the mirror / output folder, not inside, not containing
def officina_errors(cfg) -> list[str]                    # all of the above, Italian; part of validate()
```
The Officina block is parsed with the file's usual leniency (a non-object block, bad
generator items, non-string profile pairs, wrong scalar types: warned and defaulted;
unknown keys warned). `officina_errors` never quotes a generator URL (it could carry a
signature, and the messages reach the error list); the generator name identifies the row.
`officina_root_errors` keeps payloads out of the log mirror (nothing from the Officina ever
goes there) and out of the output folder, which `extract.housekeeping` prunes by age.

`mirror_root`: a *missing* key defaults to `%USERPROFILE%\qtRequestory\logs`, but a key that
is present and empty is **kept empty**, never silently defaulted (that once pointed a
hand-edited config at the live mirror). `validate` then reports "La cartella dei log non è
impostata"; a relative path is "La cartella dei log deve essere un percorso completo…".
Numbers are coerced tolerantly: `1e999` / `Infinity` (`OverflowError`) fall back to the
default like any other bad value, with a warning.

`folder_envs: dict[str, str]` (default `{}`, persisted, parsed leniently: a non-object or
non-string items are dropped with a warning) holds the environment the user chose for a
folder whose paths name none: `{folder: env name | IGNORE_FOLDER}`. A key is a folder
**absolute** or relative to the scanned root; the UI always saves absolute paths, because a
relative `svil` would apply to every scanned folder that has one (§Archive import).
`--import --env-for` merges its pairs into a copy for that run only.

**Output folder overlap (F7).** `extract.housekeeping` deletes files older than
`output_retention_hours` in the output folder, so `output_dir_errors` rejects an output
folder that is the mirror, lies inside it or contains it. The comparison is
`fsutil.is_within` in both directions: absolute, `normcase`d (case-insensitive on Windows)
and component-wise (`C:\logs-old` is not inside `C:\logs`). It is skipped while
`mirror_root` itself is invalid (already reported; a relative path would compare against the
CWD).

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
def list_local_daily_files(root, env) -> list[LocalDailyFile]   # newest first; ONLY files at local_path(root, env, day)
def count_local_files(root) -> int                          # every env folder under root (the wizard, the archive summary)
@dataclass(frozen=True) class EntryName: raw; fdi: str|None; template_key: str; call_id: str|None; well_formed: bool
def parse_entry_name(raw) -> EntryName
@dataclass(frozen=True) class CoverageDays: present: frozenset[date]; empty: frozenset[date]
    pending: tuple[date,...]; lost: tuple[date,...]; unknown: tuple[date,...]; first_local: date|None
    missing -> tuple[date,...]            # property: sorted(pending + lost)
def classify_days(local_sizes: Mapping[date,int], listed_nonempty, seen_nonempty, days, today) -> CoverageDays
```
`list_local_daily_files` accepts a file only when its path **is** `local_path(root, env,
day)` (F4): `env/2026/8/…` (unpadded month) or a day filed under the wrong month is
ignored, because the index keeps one file per day and two candidates made it flip between
them forever (rescans, `IndexStale`, duplicate downloads). Such files are the archive
importer's business: `discover` reports them and the import copies them to the right place.
Both counts include 0-byte days; `facade.SyncService.env_status` drops them (below).

`classify_days` looks at the window `[today - days + 1, today - 1]` (today is excluded:
its file is complete only after the evening compaction). `present` is every local file
with size > 0, `empty` every 0-byte local file the server never showed non-empty. A
0-byte local file whose day the last listing shows non-empty is `pending`; one an earlier
listing showed non-empty and the last one no longer does is `lost` (the placeholder is not
the day's content). A window day without a non-empty local file is `pending` when the
last listing still shows it non-empty, `lost` when an earlier listing showed it non-empty
and the last one no longer does (purged before it was downloaded), `unknown` when it is a
weekday on or after `first_local` that no listing ever showed non-empty. Weekends are
classified like any other day. A day before `first_local` is only reported when the
server listed it. `IndexService.coverage_days(env, days=30, today=None)` feeds it the
local file listing (not the index) and the listing memory of the sync state (on a
legacy-only mirror `SyncState.load()` may write `sync-state.json` once). Consumers:
the Ricerca coverage warning and the Sincronizzazione calendar, banners and badge.
`EnvSyncState.oldest_listed` is persisted but not used by the classification.

`facade.SyncService.env_status` counts only days with calls: 0-byte files are dropped
before `n_local_files`, `local_bytes` and `latest_day` are computed (a 0-byte file is "no
traffic", not archive content).
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
                               oldest_listed: date|None; listed_nonempty: tuple[date,...]; seen_nonempty: tuple[date,...]
                               listed_empty: tuple[date,...]   # 0-byte days of the last listing (1.1.1; () from older files)
class SyncState(path):
    load()                       # tolerant; imports legacy <root>/.last-sync.json (utf-8-sig, {"svil":"YYYY-MM-DD"}) once
    get(env) -> EnvSyncState
    mark_success(env, when, *, last_remote_daily=0, last_downloaded=0, newest_day=None)     # atomic save, keeps the listing memory
    record_listing(env, when, *, oldest_listed, listed_nonempty, listed_empty=())   # every real run's listing; seen_nonempty = union, last 400 days
    is_fresh(env, now, compaction_time) -> bool
        # fresh iff ALL of:
        #  1. last_success is not None and <= now (a future timestamp is never fresh, and logs a warning)
        #  2. last_success >= last_compaction_moment, where
        #     last_compaction_moment = today@compaction_time if now >= that else yesterday@compaction_time
        #  3. newest_day is not None and newest_day >= last_compaction_moment.date()
        #     newest_day = the newest daily day seen in the *listing that produced this state* which is
        #     now mirrored locally (present, shrunk, a successful download, or a 0-byte day listed on a
        #     later calendar day whose 0-byte local file exists) — so a run whose listing was read before the
        #     server compacted is NOT fresh even if last_success is already past compaction_time; the next
        #     hourly run retries instead of leaving the day behind until a manual purge deletes it. Today's
        #     0-byte file never counts, even after compaction_time (late compaction); Sunday does on Monday.
        #  4. a state loaded from a file written before newest_day existed (rule 3's key missing) -> not fresh
    freshness(env, now, compaction_time) -> Literal["fresh", "empty_today", "stale"]   # display only (1.1.1)
        # "fresh" iff is_fresh; "empty_today" iff not fresh BUT now is past today's compaction,
        # last_compaction <= last_success <= now, today in listed_empty and newest_day >= today - 1 day
        # (the only unconfirmed day is today, listed at 0 bytes); else "stale". Exposed as
        # SyncService.freshness / EnvStatus.freshness: the card and the chip read "aggiornato" with a tooltip,
        # while is_fresh stays False so the next scheduled run re-lists and confirms or downloads the day.
class ProcessLock(path): acquire(blocking=False) -> bool; release(); holder_info(); context manager   # msvcrt.locking
def peek_holder(path) -> str | None     # "<pid> <ISO time>" of a LIVE holder, else None; never takes the lock
```
**Freshness** is the rule above, not "synced recently": `mark_success` receives the clock
reading taken right before the listing GET and the newest listed day that ended up
mirrored (present, downloaded, shrunk, or a 0-byte day listed on a later day — see below). A listing read at 18:29, before the
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
def count_crlf(path) -> int   # streamed b"\r\n" count; a pair split across chunks counts once
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
4. Not a dry run → `state.record_listing` (oldest listed day, non-empty listed days),
   whatever the outcome of the downloads. Plan every listed daily, newest first, and emit
   `RemoteIndexRead` with `bytes_to_download` over the `download` plans. Per remote file:
   size 0 → `empty`; local size == remote → `present`; local larger than remote with
   `local - count(b"\r\n") == remote` (a copy imported with CRLF line endings) → `present`
   plus one `LogMessage(INFO)`, no sidecar, the day mirrored (this is exact: a CRLF copy
   with even one extra byte is `shrunk`); **otherwise local larger than remote →
   `shrunk`**; missing or smaller locally → `download`.
   `empty` (real run only): only when listed on a later calendar day (`day < listing_at.date()`;
   on the day itself a late compaction may still be pending) a missing local file is created as 0 bytes (exclusive create, never over an existing
   file) and the day counts as mirrored; an existing local file of any size also counts.
   A creation failure is a `LogMessage(WARNING)` and confirms nothing. If the server later
   lists that day non-empty, the normal `download` replaces the 0-byte file.
5. `shrunk` — **never shrink the archive**: `dest` is not touched. The remote copy is
   fetched into `YYYYMMDD.txt.remote-<size>` (skipped if already there with that size; the
   name never matches `DAILY_NAME_RE`, so the indexer ignores it), then `FileSkipped(…,
   "shrunk")` and, only when the sidecar is fetched in this run, one warning "… sul server è
   più piccolo della copia locale (L contro R): tenuta la copia locale, quella remota salvata
   come …" (or "impossibile salvare la copia remota (…)" when the sidecar failed). A sidecar
   already there is not reported again. The day counts as mirrored, the status stays `ok`.
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
8. `failed > 0` → status `errors`, no `mark_success` (only the listing is remembered). Otherwise `mark_success(env,
   listing_at, newest_day=max(mirrored))`; a failed state write is a warning, not an error
   (see §state).

Never delete local files. Cancel → `.part` removed, status `cancelled`, no `mark_success`,
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
F6: a UTF-8 BOM at offset 0 is skipped (the first `header_offset` is then 3), and a line of
blanks only (`BLANKS = b" \t\r\n"`) is neither a body nor an orphan, so a blank line between
a header and its body no longer produces an empty body plus an orphan.
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
                                           # on both sides; only blank bytes [ \t\r\n] may sit between
                                           # the end of that line and body_offset (the scanner skips them);
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
def write_temp_file(out_dir, name, text, *, retention_hours=24, alt_name=None, protected=None) -> Path
                                            # housekeeping (delete files older than N h, best effort: a listing
                                            # or unlink error is skipped) then write; when `name` already
                                            # exists and `alt_name` (the call-id variant) is given, that one is used instead
def housekeeping(out_dir, retention_hours, *, protected=None) -> int
                                            # protected = mirror_root: when paths_overlap(out_dir, protected)
                                            # NOTHING is deleted (one warning) — defence in depth behind validate
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

## Archive import (`core/archive_names.py`, `core/archive.py`, `core/importer.py`)

Logs kept in any other layout are **copied** into `<mirror_root>/<env>/YYYY/MM/YYYYMMDD.txt`,
never indexed in place. The three modules are stdlib-only and have no UI knowledge.

```python
# archive_names.py — what a path says (parts are nearest first: file name, parent, ..., scanned root's name)
def element_dates(text, *, today) -> set[date]      # every valid reading of every date token in one element
def strip_dates(text) -> str
def day_from_parts(parts, *, today) -> tuple[date|None, reason|None]    # reasons: NO_DATE, AMBIGUOUS
def env_from_parts(parts, env_names) -> str | None                      # None: no name, or a tie
# archive.py — read-only
IMPORTABLE, DUPLICATE ("duplicate_same"), NEEDS_ENV, CONFLICT, IGNORED; STATUSES
@dataclass(frozen=True) class FoundLog: rel_path; path; size; mtime_ns; env|None; day|None; status; reason; dest|None
    rel_dir -> str                                  # "" for the scanned root
@dataclass(frozen=True) class ArchiveReport: root; canonical_root|None; items: tuple[FoundLog,...]
    of(status); counts() -> dict[str,int]; needs_env_dirs() -> list[str]
def discover(root, env_names, folder_envs, *, canonical_root=None, today=None) -> ArchiveReport
def compare_files(a, b) -> "same" | "a_prefix" | "b_prefix" | "diverge"    # streamed bytes; a_prefix = STRICT prefix
def looks_like_log(head: bytes) -> bool
# importer.py
@dataclass(frozen=True) class VerifiedOriginal: path; size; mtime_ns; dest
@dataclass class ImportResult: copied; skipped; conflicts; errors: list[(Path, reason)];
    verified: list[VerifiedOriginal]; envs: set[str]; cancelled: bool;  verified_paths -> list[Path]
def run_import(report, canonical_root, *, cancel=None, progress=None) -> ImportResult
def send_to_recycle_bin(originals: Sequence[VerifiedOriginal], *, canonical_root) -> list[(Path, reason)]
def check_original(rec, canonical_root) -> str | None   # why this record may not be recycled now
```

**Walk.** `os.scandir` with an explicit stack. Never follows symlinks or junctions
(`DirEntry.is_junction`), never enters dot-folders, `$RECYCLE.BIN` or `System Volume
Information`. The app's own `.part` / `.remote-<n>` files, and every file already at its
canonical path under `canonical_root` (compared **resolved**, so the mirror reached through a
junction, a `subst` drive or an 8.3 name is still recognised), are skipped silently.

**Day.** From the file name, else from the parent folders, nearest first, and last from the
scanned root's own name. Accepted tokens: `YYYYMMDD`, `YYYY-MM-DD` / `_` / `.` (the same
separator twice), Italian `DDMMYYYY` / `DD-MM-YYYY`, plus the `YYYY/MM/DD.txt` folder
layout when the file name has no date token. No digit may be glued to a token, and only real
dates in `2020-01-01 … tomorrow` count, which is what makes the Italian reading safe. The
first element holding a date decides; two different dates in it, or a file name with a
digit run of 6+ that is no valid date (an epoch, a typo), give `ignored` "data ambigua" —
never a fallback to a folder's date.

**Content.** Compressed files (`.zip .gz .7z .rar .tgz`) are never opened: `ignored`
"archivio compresso: estrailo nella cartella". Otherwise at most 64 KiB are read; after a
BOM the first non-blank line must match `scanner.HEADER_RE`, else "non è un log di
chiamate". A 0-byte file is an empty day only when the date is in its own name and the
extension is `.txt` or none; otherwise it is ignored with that explanation.

**Environment.** First `folder_envs`: the deepest ancestor folder with a key (relative to the
scanned root or absolute) whose value is a configured env name or `IGNORE_FOLDER` ("cartella
da ignorare"); a value naming an env no longer configured is not trusted and the lookup
moves up. Then the path tokens: a configured env name, case-insensitive, as a whole word
(`(?<![a-z0-9])name(?![a-z])` on the element with its date tokens removed, so `prod2` is
`prod` and `coll20260922` is `coll`); file name before folders, the nearest element that
names any env decides, the longest name wins a tie inside it, an equal-length tie is left
to the user. Then, with exactly one env configured, that env. Otherwise `needs_env`.

**Verdict** (per env+day group, then against the canonical file at `dest`). The largest copy
of a group is the candidate; every other one must be a prefix of it (else the whole group is
`conflict`) and becomes `duplicate_same`. Candidate vs archive: no file → `importable`
("giorno mancante in archivio" / "giorno senza chiamate"); identical → `duplicate_same`;
archive a strict prefix of it → `importable` "più completo della copia in archivio"; it a
strict prefix of the archive → `duplicate_same` "l'archivio ha già una copia più
completa"; anything else (including a smaller file that is not a prefix) → `conflict`
"copie diverse dello stesso giorno", for every member. Byte equality is strict on purpose:
the index reads bodies by offset, so a copy equal only modulo CRLF is a conflict unless the
archive lacks the day.

**Copy.** `run_import` holds no lock itself (the facade does, below). Per `importable` item:
re-check what the archive holds (replacing is allowed only in the strict-prefix case), and
that the source still has the scanned size and mtime; copy to `dest.part` (parents
created), flush + fsync, read back and compare size + sha256 with the source, re-stat the
source (changed during the copy → error, nothing renamed), re-check the archive, then
`fsutil.replace_with_retry(part, dest)`. The `.part` is removed on every exit path; cancel is
checked between files and between chunks. A source that IS the canonical file under
another spelling (`fsutil.same_file`) is skipped silently and never verified. `verified` =
the copies that passed, plus the `duplicate_same` sources re-checked at import time against
the canonical file (a prefix whose larger twin failed to copy is not verified). `envs` =
the environments that received a copy; indexing them is the caller's job.

**Recycle Bin.** `send_to_recycle_bin` accepts only `VerifiedOriginal` records (a bare path
is refused "non verificato da un'importazione") and runs `check_original` right before each
shell call: an absolute path that does NOT resolve inside `canonical_root` (the whole mirror
folder, not only canonical paths) and a `dest` that does; a regular file, not the same file
as `dest`; unchanged size and mtime; `dest` still a file and `compare_files(path, dest)` in
`("same", "a_prefix")`. Then Windows only, and only on `DRIVE_FIXED` drives (on network or
removable drives `FOF_ALLOWUNDO` silently deletes for good). One `SHFileOperationW` call per
path with `FO_DELETE | FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI`.
Returns the refused/failed paths with the reason; never deletes anything else. Files
misplaced inside the mirror are therefore imported but never recycled: they stay as harmless
leftovers (ignored by the index, `duplicate_same` in the mirror's report).

**Facade.** `facade.ArchiveService(config_source)`:
- `report(path=None, *, canonical_root=None) -> ArchiveReport` — `path` defaults to the
  mirror, `canonical_root` to the mirror (the wizard passes the folder about to become the
  mirror). Raises `ValueError` while `mirror_root` is unusable, so a relative root never
  scans the CWD. It reads every candidate file (a sniff, plus a full compare against an
  existing canonical day): callers run it in a worker.
- `import_(report, *, cancel=None, progress=None) -> ImportResult` — takes the sync
  `ProcessLock` (the sync writes the same `.part` names); held → `ArchiveBusy`
  ("sincronizzazione in corso (…): importa al termine"). Does not index.
- `recycle(originals) -> list[(Path, reason)]` — `send_to_recycle_bin` with
  `canonical_root = mirror_root`.

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
   terminal used to print nothing. For `--sync/--index/--find/--task/--version/--archivio/--import/--selftest-noise-guard` (decided on
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
qtRequestory.exe --archivio [PATH]                 # read-only report; default PATH = the mirror
qtRequestory.exe --import PATH [--env-for DIR=ENV]... [--delete-originals]
qtRequestory.exe --config PATH                     # every mode; only config.json moves, logs stay in the app dir
qtRequestory.exe --version
qtRequestory.exe --selftest-noise-guard            # hidden (argparse.SUPPRESS): dev/diagnostic check of the noise guard, see §Packaging
```

Exit codes:

| code | `--sync` | `--index` | `--find` | `--task` | `--archivio` | `--import` |
|---|---|---|---|---|---|---|
| 0 | ok, nothing to do, or lock held by another run | ok | extracted | ok | nothing needs an env, no conflict | all done |
| 1 | file errors, or an unexpected exception (logged with traceback to `sync.log`) | index failure / unexpected exception | nothing found | `status`: no task registered; scheduler error | some file `needs_env` or `conflict` | copy errors, conflicts, files still `needs_env`, a refused recycle, the index job's failure, or `ArchiveBusy` (a sync holds the lock) |
| 2 | **no environment reachable**, *or* a config error: unknown `-e`, `mirror_root` empty/relative | config error (unknown `-e`, `mirror_root`) | config error (unknown `-e`, `mirror_root`) | — | `mirror_root`; PATH missing or not a folder | `mirror_root`; PATH empty/missing/not a folder; `--env-for` with an unknown env |
| 3 | cancelled (Ctrl+C) | cancelled | — | — | — | cancelled (no recycle then) |

`--archivio` prints one line per file (`[stato] rel_path (env day, size) — reason`), the
counts, and the folders that need `--env-for`. `--import` prints the same report, copies,
then runs `run_index_job` on `result.envs`; `--env-for DIR=ENV` (repeatable; DIR relative to
PATH or absolute; `ignora`/`__ignora__` = skip) is merged into a copy of `folder_envs` for
that run only, never saved. Originals go to the Recycle Bin only with `--delete-originals`,
only `ImportResult.verified` records outside the mirror (`real_is_within`), and never after
a cancel; without the flag it prints how many could go. `--env-for` / `--delete-originals`
without `--import` are argparse errors.

`EXIT_CONFIG_ERROR = 2` deliberately shares the number with the engine's "nothing
reachable": both mean "nothing was synced, look at the setup/network", but they are
distinguishable only by the printed message (config errors print "Errore…"/"Errore di
configurazione: …" before any job starts). A script that must tell them apart has to read
the output.

The pre-run gate for `--sync/--index/--find/--archivio/--import` checks **only** `mirror_root`
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

## Officina (`qtrequestory.officina`) — phases 1 and 2

The engine of the Officina tab (README §Officina, DESIGN-ui §Officina): initiatives and
cases on disk, generation against a document generator with safe headers and upload links,
the staged comparison of a generated document with the customer's TARGET (phase 2, release
1.3.0: variables, noise rules, block alignment, moves and sections, a three-way verdict,
tolerances, "segna fatta" verified on regeneration, HTML through its DOM), and the testers'
delivery folder. What is still to come (images, tables cell by cell, the PDF summary…) is
in BACKLOG §Officina. Qt-free throughout: the UI turns the rendered bytes into `QImage`s
and reaches everything through `ui/contracts.OfficinaApi`.

### Lazy boundary and PDFium (`officina/pdf.py`)

- `officina/pdf.py` is the **only** module that imports `pypdfium2`; `officina/__init__.py`
  is empty; `compare/extract_pdf.extract()` and the viewer's render job import
  `officina.pdf` inside the function. So `import qtrequestory.cli` (the hourly `--sync`),
  `import qtrequestory.officina`, `officina.service`, `ui.contracts`, `officina_viewer` and
  `officina_page` never load pypdfium2 (`tests/test_officina_boundary.py` and subprocess
  tests in the officina/UI test files). `CoreServices.officina` is built on first access
  (`officina_factory`), and the UI reaches `officina_page` only through the page factory.
- Functions: `read_chars(path) -> list[PageChars]` (per page: displayed size, image count,
  characters with a `text_box` in the text's own unrotated space — used to group words and
  lines — and a `display_box` in the displayed page, top-left origin, CropBox and /Rotate
  applied through `FPDF_PageToDevice`; PDFium's line-end hyphen U+0002 becomes `-`, a glyph
  without Unicode U+FFFD); `page_sizes`, `page_count`; `render_page(path, page, scale) ->
  RenderedPage` (BGRx bytes, displayed orientation, white fill). A /Rotate 180 page is read
  with its rotation set to 0 **in memory** (PDFium reads upside-down text right-to-left) and
  restored in `finally`; the file is never saved. `PdfReadError(ValueError)` wraps
  PDFium's errors in Italian; a missing file stays `FileNotFoundError`. Phase 2 adds, per
  character run, the font size and weight (`PageChars.fonts`, read through
  `pypdfium2.raw`; a weight of −1 is guessed from the font name; bold = weight ≥ 600 or a
  bold font name) and `TextSearch`, a text search over a PDF used to box HTML blocks on
  Edge's print.
- **One process-wide `RLock` around every PDFium call** (render, extraction, sizes): PDFium
  is not thread-safe, and the viewer's render threads could otherwise meet an extraction
  running in a worker. Rendering is therefore never parallel; the pools only keep the UI
  responsive.

### Model (`officina/model.py`)

```
<Officina root>\
  <Iniziativa>\                      folder-safe name; the display name is in iniziativa.json
    iniziativa.json                  name, created, header_defaults, delivery {last_destination, last_at}, notes,
                                     profilo, regole_rumore, preset_rumore
    casi\<case-id>\                  case-id = <KEY> or <KEY>__<variant-slug>
      caso.json                      key, variant, env, headers, drop_postman_token, correlation(+value),
                                     link_policy, status, notes, source_fdi, history [{at, note}],
                                     + the review keys (below)
      payload.json                   (payload.original.json written on the first edit)
      target\<original name>         + target.meta.json {original_name, …}
      asis\asis.pdf|html + asis.meta.json      (asis.previous-<n>.* kept on replace)
      tobe\v001.pdf|html + v001.meta.json, v002…
      cache\                         html-<sha>.pdf Edge prints, extract-<sha>.json extractions,
                                     temporary copies (all safe to delete)
```
- `Workspace(root)`: `initiatives()`, `create_initiative(name)` (refuses duplicates),
  `load(initiative_id)`, `add_case(ini, key, variant, payload, *, env, source_fdi)`, `save_case`,
  `payload` / `save_payload`, `set_target(case, src)` (copy, original name kept; a second
  call replaces), `add_version(case, "asis"|"tobe", content, doc_type, meta, *,
  replace_asis_note=None)`, `last_delivery_destination` / `remember_delivery_destination`.
- **An initiative is its folder**: `Initiative.id` is the folder's name and the only thing
  `load()` takes (one plain folder name; never looked up by display name). `name` (from
  `iniziativa.json`, else the folder) is display only: a folder copied in Explorer keeps
  the original's name and is still another initiative. The UI keys everything on the id
  (list rows, queue, failures, delivery folder).
- `Case` (`id, key, variant, env, headers, drop_postman_token, correlation: new|source|fixed,
  correlation_value, link_policy: remove|keep_if_expired, status: open|accepted, notes,
  folder, source_fdi, load_error, accepted_version, reopened, load_notes`) reads its slots
  from disk on every call: `target()`, `asis()`, `tobe_versions()` (ascending),
  `latest_tobe()`, `history`. A new case has `link_policy="remove"`, `correlation="new"`,
  `status="open"`. `Version(kind, number, path, doc_type, created, meta, missing, broken)`:
  number 0 for target/AS-IS, 1… for TO-BE.
- **Acceptance is of a version**: `mark_accepted()` records `accepted_version` (the latest
  TO-BE's number); `add_version` of a new AS-IS or TO-BE on an accepted case sets it back to
  `open` with `reopened_after_acceptance: true` (`Case.reopened`; `accepted_version` kept for
  the record); `acceptance_is_current()` is what delivery preselects on.
- Every write is atomic (temp file + `fsutil.replace_with_retry`), including the copy of a
  target (committed before its meta). Names: `\ / : * ? " < > |` replaced, trailing dots
  and spaces stripped, Windows device names (`CON`, `COM1`…) escaped, for initiatives and
  case ids alike; accents and spaces stay readable.
- The AS-IS is a baseline: `add_version("asis")` raises `AsisAlreadyExistsError` when one
  exists and no note is given; with a note the old one becomes `asis.previous-<n>.*` and the
  note is appended to `caso.json` `history`. Nothing ever deletes a TO-BE version.
- Loading never raises for what the user can do in Explorer: a corrupt `caso.json` gives a
  case with defaults and `load_error`, a corrupt `iniziativa.json` an initiative with
  `load_error` (header defaults unknown: generation is refused); a version file deleted on
  disk gives `Version.missing=True` (Review Focus 4). Hand-edited metadata is never trusted
  to build a path: a target `original_name` that is not one safe file name gives
  `Version.broken` (also refused by `render_path`, `compare` and delivery), a `doc_type`
  other than pdf/html falls back to the content file on disk, a null header value is dropped
  with a line in `load_notes`, and `drop_postman_token` is only the JSON `true`.
- **Writing never merges into what it cannot read**: `save_case`, the AS-IS history note, the
  reopen and `remember_delivery_destination` raise `ValueError` (nothing written) for an
  unreadable `caso.json` / `iniziativa.json` — a merge into `{}` would wipe env, headers,
  source FDI, name or header defaults. Every write goes through a unique temporary file in
  the same folder (`tempfile.mkstemp`), so two writers never share one.
- Initiative header defaults exist in the model (`header_defaults`) but have no editor in the
  UI yet.

**Review state** (`officina/model_review.py`, phase 2). `Case.review` is a `Review` read from
the `caso.json` keys below; `Initiative.profile`, `.noise_rules`, `.noise_presets` from
`iniziativa.json`. Everything is backward compatible: a missing key is the empty value, so a
1.2.0 file loads as `Review()`; a value that cannot be used (hand-edited junk, an unknown
profile, an anchor of the wrong shape) is dropped with an Italian line in `load_notes`,
never a crash. Anchors are stored as `{op, klass, context, target_text}`.

```
caso.json
  "profilo":       null | "tollerante" | "stretto" | "solo_testo"      null = as the initiative
  "tolleranze":    [{"anchor", "generato", "nota", "quando"}]
  "non_variabili": [{"anchor", "quando"}]
  "segnate":       [{"anchor", "generato", "versione", "quando"}]      versione = TO-BE the mark was made in
  "non_risolte":   [{"anchor", "versione", "generato"}]                versione = the mark's (R10)
  "regole_rumore": [{"name", "pattern", "enabled"}]                    the case's own; they add up
  "riepilogo":     {"versione", "fatte", "da_fare", "in_corso", "regressioni", "da_verificare",
                    "non_risolte", "tollerate", "variabili", "rumore", "avanzamento", "quando", "due_vie"}
iniziativa.json
  "profilo" (default "tollerante"), "regole_rumore", "preset_rumore" (names of the presets on)
```
The legacy `noise_rules` of an `iniziativa.json` (unused in phase 1) is read once as the
initiative's own rules when `regole_rumore` is absent, and disappears at the next
`save_initiative_settings`. Nothing is ever inherited by a case from another case or
initiative: a new case starts with an empty review.

- **One writer per part of `caso.json`** (R8): `save_case` merges the case's own fields and
  keeps the review keys; `Workspace.save_review(case)` merges ONLY the review keys. Both
  refuse an unreadable file like every other merge.
- **Per-case write lock** (R16): every read-modify-write of one case's `caso.json` holds
  `model_case.case_write_lock(case_dir)` (a process-wide `RLock` per folder), so a worker
  saving the review and the GUI thread saving the case never merge into each other's stale
  copy. The lock is per process (the app is single-instance).
- **Retrying reads** (R16): on Windows, opening a file while another thread `os.replace`s
  it fails with a sharing violation for a few milliseconds. `model_io.read_text_retrying`
  retries errors 32/33 (`TRANSIENT_TRIES` = 10, 20 ms apart); `read_json_strict` has no
  separate existence check: it relies on the read's own `FileNotFoundError` inside the retry,
  so a racing replace is never read as "missing".
- **Replacing the target** (R29) on a case with review state clears `segnate`,
  `non_risolte` and `riepilogo` and appends a history line; tolerances and
  `non_variabili` stay (they are inactive where their anchors no longer match).

### Upload links (`officina/links.py`)

A payload carries `{"key": "attachmentId"}` / `{"key": "attachmentUrl", "value": <SAS URL>}`
attributes in `documents[].attributes[]` and in nested
`dossierItems[].childItems[].documents[].attributes[]`. The SAS URL is a **write**
permission on a real customer's blob, so replaying a still-valid one would overwrite a real
document.
- `find_links(payload)` finds every such attribute at any depth (key compared
  case-insensitively) with its JSON path, expiry (`se=`) and write permission (`sp=`).
  A missing, unreadable or **repeated** `se` means "not expired"; a repeated `sp` means
  writable; a malformed URL is treated as valid (so refused). A link counts as expired only
  when `expires + CLOCK_SKEW (5 min) <= now`. `UploadLink.url` is out of `repr`;
  `.masked` is the safe form.
- `remove_links(payload)` returns a deep copy without the `attachmentUrl`/`attachmentId`
  attributes (policy **Rimuovi**, the default: the probe showed the generator still returns
  the document in the body).
- `signed_links(payload)` scans **every string** of the payload (decoded up to four rounds:
  HTML entities, JSON `\uXXXX` / `\/`, percent-encoding) for `sig=`, protocol-relative and
  scheme-less forms included — the defence in depth behind both policies.
- `mask(url)` keeps scheme, host, port and path and turns any query into `sig=***` (userinfo
  and fragment dropped; an unreadable URL becomes `<url non leggibile>`, never an
  exception); `mask_text` / `mask_bytes` mask every URL in free text and then any `sig`
  followed by `=`, `%3D`, `&#61;`, `&#x3d;` or `&equals;`.

### Generator client (`officina/generator.py`)

- `resolve_headers(case, ini, settings, *, now_ms, new_uuid, source_fdi)`. **Precedence,
  the later layer winning: automatic < profile (Impostazioni) < initiative defaults < case
  overrides.** Automatic: `current_timestamp` (now, epoch ms), `template_key` (the case
  key), `correlation_id` (a new uuid4 — `new_uuid` is called only in this mode —, the source
  FDI, or the fixed value), `Postman-Token` (the configured default). The case winning over
  the automatic values is deliberate: headers are fully editable (e.g. a fixed
  `current_timestamp`). Names merge case-insensitively; a header whose final value is empty
  is not sent, except `Postman-Token`, which is put back with its canonical name unless
  `case.drop_postman_token` — the only way to drop it. A missing `correlation_id` (mode
  "source" without an FDI, "fixed" without a value, and no layer setting it) and a bad name
  or value (the shared `header_name_problem` / `header_value_problem`: RFC token, not one of
  `HTTP_CLIENT_HEADERS`, no CR/LF, latin-1) raise `HeaderError`, whose message names the
  layer ("intestazioni (caso): …").
- `prepare_payload(payload, policy, *, now) -> (payload | None, reason)`: `remove` →
  `remove_links`; `keep_if_expired` → unchanged only if every link is provably expired; any
  other policy is refused. Then, whatever the policy, a still-valid signed URL anywhere in the
  payload (`signed_links`) refuses the send; the reason names the JSON path and the masked
  URL. The input is never mutated.
- `send(url, payload, headers, *, timeout_s, opener=None) -> SendResult(ok, status, doc_type,
  content, duration_ms, reason, headers_sent)`. Never raises. Before any call the URL goes
  through `generator_url_problem(url, allow_loopback_http=True)` (plain http only to
  127.0.0.1/localhost/::1, for the tests' fake server). The default opener **refuses
  redirects** (a 3xx is a failed run). The body is read against an overall deadline (the
  socket timeout shrinks to the time left, so a trickling server cannot stretch it) and a
  200 MB cap. The type is **sniffed** from the bytes — the server sends no Content-Type:
  `%PDF-` at the start (at most 8 BOM/whitespace bytes before it) → pdf; a body starting
  with `<` whose first KB holds `<!doctype html` or `<html` → html. Failed runs: HTTP ≥ 400,
  not a document ("la risposta non è un PDF né un HTML"), HTML under 512 bytes ("risposta
  HTML sospetta: troppo corta") — with the first 4 KB of the body, masked, as `content` —
  and timeout / network error / refused URL with empty content. `reason` is always masked;
  `headers_sent` is `shown_headers(headers)`: credential headers `***`, URLs masked.
- urllib sends header names title-cased (`Template_Key`); HTTP names are case-insensitive
  and the probe went out the same way.

### Service (`officina/service.py`, behind `ui/contracts.OfficinaApi`)

`OfficinaService(config_source, *, index=None, opener=None, clock, new_uuid,
html_to_pdf)` reads `Config.officina` through the callable on **every** call, so a save in
Impostazioni is seen at once. `workspace_root()` is None when `root` is unset, blank or
relative; then `initiatives()` is empty and writes raise `ValueError`.
- `case_from_hit(ini, hit, variant)`: the body from `IndexApi.read_body(hit)` (must be a JSON
  object), key and `source_fdi` from the hit, env = the default generator; a call no longer
  in the local log is `ValueError("…ripetere la ricerca")`. `case_from_file(ini, path, key,
  variant)`: a JSON object file (BOM allowed), non-blank key, no source FDI.
- `generate(ini, case, kind, *, replace_asis_note=None, cancel=None) -> (Version | None,
  SendResult)` refuses as early as possible, in this order, so nothing leaves the machine
  when it should not: no root → the case env must be a configured, **enabled**, not
  prod-like generator with a usable URL → an existing AS-IS without a note →
  `resolve_headers` → an empty payload → `prepare_payload` → the cancel token → `send` →
  the **expected type** (the target's type, else the AS-IS's — for a new AS-IS only the
  target's; with neither, pdf or html): an HTML answer for a PDF case is almost always a
  gateway error page → only then `Workspace.add_version`, with meta `env`, `generator`
  (masked URL), `status`, `duration_ms`, `bytes`, `sent_at`, `headers_sent`,
  `link_policy`, `links_removed` — never the payload. Every refusal or failure is
  `(None, SendResult(ok=False, reason=<masked Italian>))` and writes nothing; a save error
  after a good answer is "documento ricevuto ma non salvato: …". A call already on the wire
  cannot be interrupted: `cancel` is checked just before sending.
- Logging carries only case id, slot, env name, status, duration, version number, doc type
  and the reason with every link reduced to its host (`links.mask_text_for_log`) — never the
  payload, the document, the headers or a link's path (a caplog test checks it). The reason
  returned to the UI keeps the masked link (`…?sig=***`) so the user sees which one.
- `generate` also refuses an initiative with `load_error` and a case with `load_error`.
- `compare(left, right) -> Comparison`: the engine's `compare_docs` without noise rules,
  verdicts or a review (the AS-IS view, "cos'altro ho cambiato"). Each file is read once
  and hashed; a PDF is extracted from a private copy of exactly those bytes (in `cache\`),
  an HTML side is first printed by Edge. PDF extractions are cached **on disk**
  (§Comparison engine, `compare/cache.py`) and in memory (LRU 16), results in memory
  (LRU 64, keyed by both hashes and labels), so an identical regenerated TO-BE costs two
  reads and two hashes, and a restart costs no re-extraction. `left_label` / `right_label`
  name the sides in the "non ha testo estraibile" note. A comparison that cannot be made
  (file gone, unreadable PDF, Edge missing or failing, no cache folder) raises
  `CompareError` (Italian): not a note, because a note would be cached and read like a
  result, while these problems are fixable and must be retried. A side without a text
  layer IS a result (Review Focus 2).
- `render_path(case, version) -> Path`: the PDF the viewer shows — the file itself, or the
  cached Edge print of an HTML.
- **HTML print cache**: `<case>\cache\html-<sha256[:32]>.pdf`. The hashed bytes are copied to
  a private file, printed to a private name, checked (`%PDF-`, over 1 KB, `%%EOF` in the last
  KB) and renamed atomically; a lock per final name serialises check-and-convert (the board
  and the case view convert the same HTML once); a cached file that fails the check is
  printed again. Nothing derived is ever written into `target\`, `asis\` or `tobe\`.
- `delivery_plan`, `delivery_conflicts`, `deliver` (the delivery folder is named after
  `Initiative.id`; remembers the destination in `iniziativa.json`, or says why not in
  `DeliveryReport.remember_problem`; logs counts only, never file names — a target name may
  be a customer's)
  and `last_delivery_destination` wrap `officina/delivery.py`.

**Phase 2: the case comparison and the review** (`service_case.py`, `service_review.py`):
- `compare_case(ini, case, version) -> CaseComparison` (in a worker): TO-BE `version` ↔
  target and, when there is an AS-IS, AS-IS ↔ target, both through `compare_docs` with the
  noise rules (the presets the initiative turned on, then the initiative's rules, then the
  case's); then `verdict.judge` with the effective profile (case → initiative →
  `tollerante`), the review **read from disk** (never the `Case` in hand, which may be the
  board's stale copy) and `when` = now. The returned review (verified marks
  removed, `non_risolte`, `riepilogo`) is saved; `case.review` is updated only after the
  save succeeded. Only the LATEST TO-BE's comparison writes `riepilogo` and prunes
  `non_risolte` (R48): an older version adds the "non risolte" its verification found and
  leaves the rest. When the TO-BE or the target has no extractable text nothing is judged,
  no mark is verified and nothing is saved (R49: `judged` empty, the note shows); an AS-IS
  without text makes the verdict two-way, with a note. An unreadable `caso.json` is a
  `CompareError`.
- Inputs (`CaseInputsMixin._input`): a PDF as its words (disk + memory cache); an HTML as
  its DOM blocks (`extract_html`, every URL key kept so the cache does not depend on the
  tracking preset), boxed from the Edge print (`html_boxes`). Without Edge, the service still
  compares an HTML through its DOM (`print_error` says why; the words keep zero boxes);
  the case view uses it for a TO-BE (R45, DESIGN-ui §Officina: "Stampa dell'HTML non
  disponibile", the DOM tab as the main view). Pairs are
  cached in memory by content hashes, rules and tracking flag: re-judging after a profile or
  tolerance change costs no engine run. The user's rules never run in the application
  (R46): `sides.prepare` builds each pair's pre-noise sides, ONE `noise_guard.match_spans`
  child matches the rules on `Prepared.noise_sides()` (the exact keys and line ends the
  noise stage sees) for every pair, and `pipeline.finish` applies the returned spans
  (`noise.Found`) after the presets. A rule unusable on any pair (does not compile, out of
  time, no child) is dropped from all of them with a note; spans are cached per pair and
  pattern.
- Actions: `tolerate(case, judged, note)`, `untolerate`, `mark_done(case, judged,
  version)`, `unmark`, `unmark_all`, `not_variable`, `variable_again`, `reset_tolerances`
  (clears `tolleranze` and `non_variabili`), `set_profile(ini, case | None, profile)`,
  `set_noise_rules(ini, case | None, rules, presets)`, `noise_presets()`,
  `count_noise_hits(case, rules)` (the dialog's live counts, through the noise guard),
  `dom_view(case, version) -> (target source, generated source)` (pretty sources). Every
  action is idempotent (twice = one entry), finds its difference by `anchor`, stores
  `verdict.generated_text(diff)` (R30), and goes through `ReviewMixin._commit`: under the
  case write lock, read the review from disk, change only its own entry, `save_review`.
  `mark_done` also accepts a stand-in `Judged` built from a mark (the undo of "Annulla i
  segni" when the difference is not on screen).
- Rule names are unique across presets, the initiative and every case: `set_noise_rules`
  refuses a clash ("regola di rumore «X»: nome già usato da un preset / da una regola
  dell'iniziativa / da una regola del caso KEY"); `compare_case` tolerates a clash already
  in a hand-edited file (the later rule dropped with a note).
- Logs carry counts and action names only — never a document's text, a note or a rule.

### Comparison engine (`officina/compare/`)

Phase 2 replaced phase 1's single-sequence text diff: every comparison, with or without a
verdict, goes through `pipeline.compare_docs`. Every stage is a small module (≲ 400 lines),
**pure** (input → output, no global state), stdlib only, and **deterministic** (stable
orders everywhere, no set or dict order reaches a result; tests run it twice).

**Contract** (`compare/model.py`, frozen dataclasses of tuples, shared between threads):
- `Word(text, page, x0, y0, x1, y1, size, bold)` — PDF points of the displayed page, origin
  top-left; `size`/`bold` sampled per word (0.0/False for HTML).
- `Block(id, words, page, kind: paragrafo | riga_modulo | html, dom_path, attrs)`.
- `Diff(id, op, klass, left, right, left_text, right_text, left_spans, right_spans, anchor,
  detail, context_before, context_after)` — `left` is the TARGET; `op` ∈ mancante, in_piu,
  cambiato, spostato, sezione_assente, sezione_in_piu, pagine; `klass` ∈ testo,
  composizione, stile, spaziatura, variabile, rumore, link; spans = changed character
  ranges; `context_*` = up to 5 target words around the change, display only (R33).
- `Anchor(op, klass, context, target_text)` — the stable key of a difference across
  regenerations, taken on the **target** side, never a page or block index.
- `Comparison(diffs, left_has_text, right_has_text, left_pages, right_pages, note,
  slots_found, noise_hits)`; `.counting(profile)` = the diffs whose class the profile counts
  (what the verdict-less AS-IS view lists), `.equal_for(profile)` = both sides have text and
  nothing counted differs, `.equal` = `equal_for("tollerante")`.
- `Judged(diff, verdict, marked, unresolved, tolerated_note, previous_text)`,
  `CaseSummary` (the `riepilogo`), `Verification(checked, resolved, unresolved, changed,
  version)`, `CaseComparison(version, judged, summary, tobe, asis, verification, profile,
  inactive)`.
- `COUNTING[profile]`: tollerante = testo, composizione, link; stretto = + stile,
  spaziatura; solo_testo = testo. `variabile` and `rumore` never count.

**Stages** (`pipeline.compare_docs(left, right, *, rules, custom_hits, disabled_slots,
left_label, right_label, link_drop) -> Comparison` = `pipeline.finish(sides.prepare(...))`:
stages up to slots in `prepare`, noise onwards in `finish`; left = TARGET, each side a `DocText` or an HTML
`Block` list; the profile is applied later, by the verdict):
1. **extract** — `extract_pdf.extract(path) -> DocText(words, page_sizes, has_text)`
   (characters → words on whitespace, a gap over 0.25 × glyph height, a line change or a
   jump left; lines by vertical centre; off-page characters dropped; `has_text` False with
   no word, or for a "scan": every page under 5 words and one page with an image), or
   `extract_html` (§HTML through the DOM).
2. **blocks** (`blocks.py`) — lines by baseline (± half a line height), columns at empty
   vertical corridors (≥ 3 median character widths on ≥ 3 consecutive lines), paragraphs by
   line pitch (> 1.5 ×), indent and font-size changes; a line with a leader or a checkbox is
   its own `riga_modulo` block. HTML blocks come from the extractor.
3. **align** (`align.py`, `hungarian.py`) — exact matches first (identical normalised text
   occurring the same number of times on both sides, paired in order); then, per candidate
   pair, 0.70·content (Jaccard on 3-key shingles; `SequenceMatcher` ratio under 8 keys) +
   0.20·position (relative order, convex penalty so equal rows never cross) + 0.10·structure
   (kind, lines, font size), solved by a home-made Hungarian algorithm (Jonker–Volgenant
   form) on pairs scoring ≥ 0.35, per connected group; a group over 300 blocks a side is
   cut into windows of 30 target pages; a key shared by many blocks yields only its 48
   nearest candidates.
4. **reading order** (`moves.reading_order`, R20/R26) — alignment only ORDERS the generated
   side: a STRONG pair (content ratio ≥ 0.85) out of order is read at its partner's place
   and reported as a move; weak and unpaired generated blocks stay where they are.
5. **normalise** (`normalise.py`) — per token NFKC (ligatures, NBSP), invisible characters
   dropped, quotes and dashes unified, checkbox glyphs (Wingdings/PUA, `❏`, `☐`, `□`, `[ ]`,
   a lone `q` opening a line) → `☐`, (`☒`, `☑`, `[x]`, `[X]`) → `☒`; across tokens:
   **comb fields** (≥ 4 one-character letters/digits on a line with a regular pitch, ±25%)
   → one unit, dehyphenation at line ends, punctuation stuck to its neighbour. Only the
   comparison KEY changes: a unit keeps its original `Word`s, so highlights use the
   original boxes. Case is kept.
6. **slots** (`slots.py`, target only) — *sicuro*: a leader, a run of ≥ 4 `.`/`_` (`…` is
   three dots after NFKC), split out of its label's key; *probabile*: a label followed by
   a line end or another label, where the label ends with `:`, is a known form label (N°,
   CAP, Provincia, Località, Data) or is a word ending with `,` alone on its line («Città,
   »). A slot is a wildcard key: in the word diff it absorbs, for a sure slot, the generated
   keys up to the next word matching the target (one line at most), for a probable one at
   most 6 words on one line; beyond that it stays a normal difference. Line ends are the
   words' boxes and, for an HTML side, also its block boundaries (HTML words may have no
   boxes: no Edge print, or a block the print could not place). What it absorbs is a
   `variabile` diff, anchored by `slot_anchor` — the ONE place a slot's anchor is made
   (R2), taken before noise.
7. **noise** (`noise.py`) — the enabled valid rules, in order, on both sides' NORMALISED
   keys (keys joined by spaces, newlines at line ends, `re.MULTILINE`; each rule runs line
   by line on at most 2,000 characters). A match becomes ONE unit holding the placeholder
   `NOISE:<name>` (R18: `01/02/2026.` and `1 febbraio 2026.` both become one `NOISE Data .`
   key). `compile_rules` names and leaves out every unusable rule — a regex that does not
   compile, an empty name or pattern, a duplicate name, or a **risky** pattern (a repeat
   whose body holds an unbounded repeat, a backreference inside a repeat; found by walking
   the `re` parser tree, R17: "espressione potenzialmente troppo lenta: semplificala"); a
   bad rule is never half-applied. Presets (all off by default): Numero di pagina, Data
   (numeric and Italian textual), IBAN, Codice fiscale, CAP, Importo, Marcatore di firma
   (`` `sig,…` ``), Parametri di tracciamento (URL keys from `urls.TRACKING_KEYS`, R21 —
   also dropped from HTML URL attributes when on).
8. **worddiff** (`worddiff.py`, `bounds.py`) — `difflib.SequenceMatcher(autojunk=False)`
   over the WHOLE unit sequence in target order (reflow onto another page, or blocks cut
   differently, cost nothing), fixed on the aligned blocks with identical keys; a stretch
   over 1,000 keys is cut at *patience anchors* (keys unique on both sides) or, where none
   exist, at aligned block-pair starts (R23: otherwise a 2,400-row form never finishes).
   Target blocks the alignment left unmatched that could be a section are hard boundaries
   (R27), so a missing clause next to an edited word is one section plus one small change.
   Each non-equal part is refined and split around slots → `cambiato` / `mancante` /
   `in_piu`; a second `SequenceMatcher` on characters gives the spans of a `cambiato`.
   Equal runs whose placeholders cover different texts are `rumore` changes; equal runs
   whose words differ in size (> 0.5 pt) or weight are `stile` changes.
9. **moves and sections** (`moves.py`) — out-of-order strong pairs (the pairs outside a
   longest increasing subsequence; a consecutive run = one move), and a `mancante` plus an
   `in_piu` with the same text (≥ 3 keys, ratio ≥ 0.85), become ONE `spostato`. A deletion
   (insertion) covering whole unmatched blocks holding ≥ 2 lines together (an HTML block
   counts as one line, R24) is ONE `sezione_assente` (`sezione_in_piu`, detail "N righe").
   Different page counts (PDF only) give one `pagine` diff, first in the list.
10. **classify** (`classify.py`) — the first rule that applies: `variabile`; `composizione`
    (sections, moves, pages); `rumore`; `stile` (keys equal, size or weight not);
    `spaziatura` (keys differ only by where spaces and line breaks fall); `testo`. `link`
    comes from the HTML stage.

**Anchors** (`anchor_keys.py`, `anchors.py`): `context` = the 3 target keys before and after
the difference (for an insertion, the one key before and the one after; keys without a
letter or digit are never context), `target_text` = the target keys of the difference (a
slot as its leader), both taken on the target's slotted keys BEFORE noise, so switching a
rule on does not move them. A form with ten identical rows would give ten identical
anchors, so `disambiguate` appends `" #n"` (n ≥ 2, target order) to repeats (R19), always
producing unused anchors (R35). Differences are then numbered 1..n in target order.
Accepted cost: an edit that shifts identical rows can move a tolerance or a mark onto the
neighbouring row; replacing the target is a fresh start for anchors.

**Verdict** (`verdict.judge(tobe, asis | None, review, profile, version, when)`): TO-BE and
AS-IS differences are matched by anchor equality. For each TO-BE difference, the first rule
that applies:
1. an anchor in `review.not_variables` turns a `variabile` diff into `testo` under the same
   anchor (R36: the slot keeps absorbing, the spot becomes one counting diff "leader →
   value", so undo and tolerances stay keyed to it; the pipeline's `disabled_slots` is not
   used by the service);
2. `variabile` / `rumore` → no verdict;
3. a class the profile does not count → `tollerata`;
4. a tolerance with the same anchor AND the same normalised generated text
   (`generated_text`) → `tollerata` with its note (a changed text makes it count again; the
   tolerance stays in the file, inactive);
5. two-way (no AS-IS) → `da_fare`; else the anchor in AS-IS↔target: same generated text →
   `da_fare`, different → `in_corso` (`previous_text` = the AS-IS text); absent →
   `regressione`.
Then each counting AS-IS difference whose anchor is gone from TO-BE is a `fatta` (it carries
the AS-IS diff, for the target-side underline).

Marks are verified **per mark** (R7): a mark with `mark.version < version` is removed from
the returned review — difference gone → resolved; still there with the same generated text
→ **"non risolta"**: the difference KEEPS its verdict (R31: a stuck `regressione` stays a
`regressione`, an `in_corso` stays `in_corso`) and gets the `unresolved` flag, remembered in
`non_risolte` while the difference is present with the same anchor and text; different text
→ `in_corso` with `previous_text` = the marked text. A mark of the compared version or later
is `marked=True` ("da verificare") and keeps its verdict. A mark on a difference that does
not count right now is **dormant** (R32): not verified, not "da verificare", kept, live
again when the difference counts again. `inactive(review, judged)` counts the review entries
that match nothing (shown on the "Tutte" tab). Duplicate anchors are never an assertion
(R35): a warning, then `disambiguate` again. Ids are renumbered 1..n in judged order (R9).
Summary: a marked difference counts in its verdict AND in `da_verificare` (R15);
`avanzamento` = fatte / (fatte + da fare + in corso + regressioni), 1.0 when nothing counts.
A "non risolta" count covers every flagged difference, whatever its verdict (R44).

**Noise guard** (`noise_guard.py`, R22/R37). CPython's `re` cannot be interrupted and no
static check catches every catastrophic pattern (`(a|a)*b` passes R17), so the rules the
USER wrote — never the tested presets — run first in a child process (`multiprocessing`
*spawn*), each within `BUDGET_S` = 2 s of matching: `count_hits` gives per rule the number
of hits or an Italian error; a rule out of time kills the child and a new one carries on
with the next rule. The engine compiles them only in the child (`noise.check`; in the
application only `noise.precheck`, which compiles nothing; the noise dialog compiles a
pattern only to validate its syntax, catching `re.error`, `OverflowError` and
`RecursionError`). `compare_case` does not probe and then apply: it
sends the pipeline's exact pre-noise sides to `match_spans` and applies the spans found
(`noise.Found`), so no user regex is ever matched (executed) in the application process
(R46); spans are cached per pair, pattern and print state, never for a side without a
print (R50: they index a text without boxes); a rule
out of time is dropped with a note. The dialog's counts (`count_hits`) take the same path. The child's start-up is not
part of the budget (`START_S` = 30 s to say "ready"). A child that cannot start, or never
gets ready, makes its rules `UNAVAILABLE` — dropped from that comparison with the note
"regole personalizzate non applicate: …", **never** run in-process; a child that never got
ready latches the guard "unavailable" for `LATCH_S` = 120 s (a failed spawn is retried at
once). A timed-out rule stays refused for those texts until restart (accepted, R43). The
entry scripts (`scripts/entrypoint.py`, `__main__.py`) call
`multiprocessing.freeze_support()` so a child of the frozen exe runs the guard, not the
application; `--selftest-noise-guard` checks exactly that (§Packaging).

**Disk cache** (`cache.py`, spec §4.3; closes a phase-1 limit):
`<case>\cache\extract-<sha256>.json` per extracted PDF — words with boxes, size and bold,
page sizes, `has_text`, the sha and `FORMAT` (1). A missing file, another format, another sha, or anything not exactly
the expected shape is a miss (never an error): the caller extracts again and `store`
overwrites it atomically. Writing is best-effort (logged at debug, path and error only).

**Timings** (idle development laptop, measured at integration): two 10-page PDFs (~6,700
words each) 1.8–1.9 s end to end (extraction 1.6 s, `compare_docs` 0.25 s; spec budget
3 s); two 60-page PDFs (~40,500 words each) ~12 s the first time (extraction ~10 s, the
comparison ~2 s), then ~2 s from the disk cache; a synthetic 60-page pair with 1,030
differences compares in ~1.3 s (the patience cuts, R23). Everything runs in workers.

### HTML through the DOM (`compare/extract_html.py`, `html_boxes.py`, `linkdiff.py`, `urls.py`)

- `extract_html` (stdlib `html.parser`, no lxml/inscriptis/xmldiff — decision D4) returns
  the `Block` list stages 3–10 work on, plus a pretty source (one tag or text run per line,
  two spaces per depth) for the DOM tab. One block per block element with text (`p`, `td`,
  `th`, `li`, `h1`–`h6`); other text belongs to the innermost `div`, else the top-level
  element holding it, else `body` (inline text straight in `body` is ONE block); text
  around a nested block is split around it, in reading order. Invisible content is
  skipped: `head`, `script`, `style`, `template`, Office's `<xml>` and `o:`/`v:`/`w:` tags,
  every comment (MSO conditionals included; an unterminated one hides the rest, as in a
  browser), and any element with `display:none` or `hidden`, with its subtree.
  `dom_path` counts same-tag siblings below `body` (`table[2]/tr[3]/td[1]`).
- **Critical attributes** — `href` (`a`/`area`, `mailto:`/`tel:` included), `src` and `alt`
  (`img`), compared EXACTLY after `urls.normalise` (scheme and host lower-cased, query keys
  sorted, the tracking keys dropped when the "Parametri di tracciamento" preset is on; path,
  fragment and values as written; a key nobody recognises is always kept). A difference is
  one `cambiato` of class `link` per attribute, detail `"href: a → b"`, anchored like a change
  of its target block; it counts like text.
- **Boxes** (`html_boxes.py`) — the viewer shows the Edge print, so the DOM words take their
  boxes from it: matched against the print's words with one `SequenceMatcher`; a leftover
  word placed after its matched neighbour; a block none of whose words matched searched as
  text in the print (`pdf` search); otherwise zero boxes — the difference is only in the
  list and the DOM tab. Sizes and weights are not taken from the print.

### HTML → PDF with Edge, sandboxed (`officina/compare/sanitise.py`, `edge.py`)

An HTML case (an email body) is compared through its DOM (§HTML through the DOM), and
shown — its words boxed — through its PDF print by the Microsoft Edge installed on Windows
(`find_edge()`: Program Files (x86), Program Files, LOCALAPPDATA, then the App Paths
registry key, read-only). Rendering must be offline and deterministic,
and a customer HTML must not be able to reach the network, so there are three layers:
1. **Sanitiser (an allow-list)**: `sanitise_html(bytes)` writes a sanitised copy next to the
   output, and Edge renders that copy, never the original. A reference survives only when it
   is relative (no scheme, no leading `/` or `\`), `data:` (not in frames/plugins), a
   fragment or empty; everything else — http(s), `//host`, `cid:`, `javascript:`,
   `file://host`, UNC `\\host\share` (SMB would leak NTLM credentials) — is blanked (`href`
   on `a`/`area` becomes `#`). Values are tested after HTML-entity decoding and CSS
   unescaping. `<script>`, `on*` handlers, `srcdoc`, `<base>`, `http-equiv` metas other than
   content-type/content-language/x-ua-compatible and CSS `@import` are removed; CSS
   `url(…)` / `image-set(…)` are checked in `<style>` and `style=""`; a `srcset` with one bad
   candidate is blanked. The document's own encoding (BOM, `<meta charset>`, else UTF-8,
   cp1252, latin-1) is kept.
2. **CSP**: a `<meta http-equiv="Content-Security-Policy">` first in `<head>` (after the
   doctype when there is no head): `default-src 'none'; img-src data:; style-src
   'unsafe-inline'; font-src data:; script-src 'none'; object-src 'none'; frame-src 'none';
   worker-src 'none'; base-uri 'none'; form-action 'none'`. It blocks every fetch even if the
   sanitiser missed a reference, and switches JavaScript off — the
   `--blink-settings=scriptEnabled=false` switch makes `--print-to-pdf` write nothing
   (verified), so it is deliberately not passed (a test checks it). Relative references do
   not load either: harmless, the copy lives in `cache\`, away from the original's files.
3. **Edge itself**: a throw-away `--user-data-dir` per run (`qtr-edge-*` in the temp folder;
   ones older than a day, left by a crash, are swept), a dead proxy
   (`--proxy-server=http://127.0.0.1:9`) and a resolver that resolves nothing
   (`--host-resolver-rules=MAP * ~NOTFOUND`), extensions, sync, background networking and
   component updates off, no print header/footer. The proxy does not cover SMB — layers 1
   and 2 do.

The exit code is not trusted (a known regression makes `--headless=new` exit 0 without a
valid PDF): any stale output is deleted first, the output must start with `%PDF-` and exceed
1 KB, and one retry runs with `--headless=old`; on timeout only our own process tree is
killed (`taskkill /T`); on failure no output file is left. A fresh profile costs about
3.5 s per print; the service allows 60 s (`EDGE_TIMEOUT_S`).

### Delivery (`officina/delivery.py`)

- `build_plan(ini, case_ids) -> DeliveryPlan(items, missing)`; `plan_delivery` returns the
  items. Layout under `<destination>\<Iniziativa>\`: `<KEY>\<KEY>_ASIS.<ext>`,
  `<KEY>\<KEY>_TOBE.<ext>` (the latest TO-BE) and `<KEY>\<target original name>`. Several
  **chosen** cases with one key share the folder as `<KEY>_<variant>_ASIS/TOBE.<ext>`; their
  targets keep their names, and equal names get ` (<variant>)` (variant capped at 40
  characters) before the extension; any remaining collision (case-insensitive) gets ` (2)`.
  A missing slot is listed as `MissingSlot` with reason `absent`, `gone` (deleted on disk) or
  `outside` (the meta points outside the case folder) — never invented.
- Path safety: keys, variants, target names and the initiative name each become exactly
  ONE component through `safe_component` (invalid and control characters → `_`, trailing
  dots/spaces stripped, `.`/`..`/empty → `_`, device names escaped, at most 120 characters
  with the extension kept); every destination is re-checked to lie inside
  `<destination>\<Iniziativa>` (lexically, and with `real_is_within` after `mkdir`); a
  source must lie inside its case folder.
- `deliver(items, destination, ini_name, *, on_conflict, make_zip, cancel) ->
  DeliveryReport(delivered, skipped, failed, renamed, zip_path, zip_left_out, cancelled,
  folder_exists)` never raises for a single file; `run_delivery` wraps it (returns the
  written paths, raises `DeliveryError(report)`). All sources are checked before the first
  copy. Each file is copied to `.<name>.<12hex>.part` in its final folder and committed with
  `os.rename` (which on Windows refuses to overwrite) or, only after "replace",
  `replace_with_retry`; "keep_both" → ` (2)`, ` (3)`…; "skip" drops the temp file. A file
  that appears between the check and the rename is asked about again. A failure in the
  middle is recorded per file and the others continue; `cancel` is checked before each file.
  `find_conflicts` lists the existing files (zip included) for the UI to ask first.
- **Zip** (optional): `<destination>\<Iniziativa>.zip`, ZIP_DEFLATED, entries relative to
  `<Iniziativa>` with forward slashes, holding exactly **this** delivery (the files written
  plus the existing files kept with "Salta") — never an earlier delivery's leftovers. A
  symlink, or a file reached through one, is never read (listed in `zip_left_out`). It is
  written through a temp file like the documents, and only when every document was
  delivered: a zip of an incomplete delivery would travel on its own.

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

**The Officina and pypdfium2.** `qtrequestory.officina` is collected with
`collect_submodules("qtrequestory.officina")` (its UI page is reached through the same
dynamic page factory as the others), and `collect_all("pypdfium2")` brings pypdfium2's data
files, hidden imports and its `pypdfium2-<version>.dist-info` folder — which holds the
licence texts. `pdfium.dll` (about 5.4 MB) lives in the separate `pypdfium2_raw` package
and is collected by pyinstaller-hooks-contrib's `hook-pypdfium2_raw`.
`tests/test_packaging.py` checks the spec text for both collections. Measured with the
Officina: **34.17 MB** (1.2.0), **34.51 MB** after phase 2 (+0.34 MB for the whole staged
engine: stdlib only, no new dependency).

**Multiprocessing in the frozen exe.** The noise guard starts a *spawn* child; in a onefile
exe that child is the exe itself, so `scripts/entrypoint.py` (and `__main__.py`) call
`multiprocessing.freeze_support()` first thing.

**`--selftest-noise-guard`** (hidden: `argparse.SUPPRESS`, not in `--help`; for development
and diagnostics only, never for users) runs `noise_guard.selftest()`: one synthetic custom
rule counted in a spawned child, one printed line `noise guard: ok {…} (… s)`, exit 0 — or
`NON riuscito`, exit 1. It is a headless flag (the parent console is attached, like
`--version`) and returns before any config, path or logging setup, with no file or network
I/O: keep it that way. Run it on a new build (with `QTREQUESTORY_HOME` pointing at a temp
folder) whenever the packaging or the guard changes: it is the only check of the frozen
child path short of the UI.

**Third-party licences.** `src/qtrequestory/THIRD-PARTY-NOTICES.md` names every bundled
third-party component and its licence: pypdfium2 (`Apache-2.0 OR BSD-3-Clause`), PDFium
(`(Apache-2.0 OR BSD-3-Clause) AND LicenseRef-PdfiumThirdParty`: libpng, LibTIFF, AGG,
FreeType, Little CMS, OpenJPEG, zlib, libjpeg-turbo, ICU), PySide6/Qt (LGPL-3.0, unmodified
DLLs), the Fluent UI icons (MIT, `ui/icons/LICENSE.md`), CPython and its OpenSSL. It is
bundled as `qtrequestory/THIRD-PARTY-NOTICES.md` (spec `datas`) and declared as package
data in `pyproject.toml`; the full pypdfium2/PDFium texts ship in the bundled dist-info.
`tests/test_packaging.py` checks the notice's content and the spec entry. Only permissive
PDF libraries are allowed: no PyMuPDF (AGPL), no Ghostscript-based tools (AGPL), no GPL
layout tools.

Measured (before the Officina): 39.81 MB before the two binary filters, **30.18 MB** after. Qt DLLs shipped:
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

Archive import tests build every layout synthetically in `tmp_path` (`tests/test_archive_names.py`,
`test_archive.py`, `test_importer.py`, `test_archive_service.py`, `test_cli_archive.py`);
`tests/test_import_safety.py` uses a real `mklink /J` junction in a temp folder with the
shell delete mocked. The real Recycle Bin is never called by the suite.

`tests/test_no_qt_in_core.py` walks `core/` and asserts no `PySide6|PyQt|tkinter` import;
it also walks `officina/` for GUI imports and `core/` for any `qtrequestory.officina` import.
`tests/fakes/fake_core.py` implements the facade in memory for the UI tests;
`tests/test_fake_core.py` runs the same calls against the real facade on temp paths and the
fake (`run(None)` skips disabled envs, unknown env raises, `register` without an exe
fails, ordering of `list_template_keys`, `plan(envs)`, retention, `coverage_days` on a disk
mirror with empty files and a real state file, the five archive verdicts on one synthetic
tree…) so the two cannot drift. `FakeArchiveApi` runs the real `discover`/`run_import` on
its temp tree and simulates the Recycle Bin (it unlinks only files under its own root).

**Officina tests** (`tests/officina/`, `tests/ui/test_officina_*.py`, `tests/ui/test_settings_officina.py`),
synthetic only (`MOD_TEST_*` keys, `example.invalid` URLs, made-up signatures):
- `tests/officina/pdfgen.py` builds PDFs with `QPdfWriter` + `QTextDocument` from HTML
  snippets (controlled differences, reflow, hyphenation, image-only "scans"); rotated and
  cropped pages are made with pypdfium2 in the test itself. Three traps it works around: the
  offscreen platform has **no fonts** (the `pdfs` fixture registers Arial for the test and
  removes it afterwards), `QTextDocument.print_()` adds page numbers (pages are drawn by
  hand), and writer margins let the next page's lines bleed into the text layer (zero writer
  margins, root-frame margins instead).
- The generator and the service are tested against a local `ThreadingHTTPServer` on
  127.0.0.1 that sends no Content-Type and can answer PDF, HTML, JSON, 3xx, 500, slowly,
  half a body or a trickle. No test ever contacts a real endpoint.
- The real-Edge test is skipped when Edge is missing; a fake `msedge.cmd` covers the
  failure and retry path.
- `FakeOfficinaApi` (`tests/fakes/fake_officina.py`, re-exported by `fake_core.py`) wraps the
  **real** `OfficinaService` on real files for generation, the model and delivery, and
  replaces only the outside world: an in-process HTTP opener (`canned_pdf(text)`, a
  hand-built one-page PDF; per-case scripting with `set_response_for` / `set_responder`)
  and a canned Edge print. Its comparisons and verdicts are scripted: `compare` /
  `compare_case` return canned `Diff` lists (`fake_diff`) judged by
  `tests/fakes/fake_verdict.py`, a small re-implementation of the verdict rules that imports
  only the contract, so the UI tests drive every state by hand. `tests/test_fake_core.py`
  compares real and fake on generation, refusals, file layout, headers sent and delivery,
  and runs one scripted review scenario (tolerate, mark, verify, "non è una variabile",
  "Annulla i segni" and its undo, duplicate rule names…) on both, step by step.
- **Engine tests** (`tests/officina/test_{normalise,slots,noise,noise_guard,blocks,hungarian,
  align,worddiff,moves,classify,anchors,pipeline,verdict,cache,extract_html,html_boxes,
  compare_docs_basics,service_review,service_integration}.py`) build their PDFs with
  `pdfgen` (a changed letter, sure and probable slots and a value too long for one,
  Wingdings boxes against `[x]`, spaced comb fields, a block in another reading order,
  sections missing and extra, moved blocks, an extra page, style and spacing in the three
  profiles) and synthetic HTML emails (nested tables, MSO comments, hidden elements,
  tracking parameters, a changed `src`). Properties: determinism (two runs), time budgets
  (10 pages; 60 pages), the disk cache (hit, other format, corrupt file), 1.2.0
  `caso.json` / `iniziativa.json` loading unchanged. The noise-guard tests use a fake clock
  and a slow pattern like `(a|a)*b`.
- **End to end** (`tests/ui/test_officina_e2e_real.py`): the Officina page on the REAL
  service and the local fake generator — target, AS-IS, v1, F on two rows, v2 fixing one:
  the outcome strip reads "v2: verificate 2 modifiche segnate — 1 risolta, 1 non risolta"
  and `caso.json` holds the non risolta and the v2 summary; the HTML variant (real Edge,
  skipped without it) checks the DOM tab.
