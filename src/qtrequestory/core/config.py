"""Application configuration: model, defaults, JSON persistence, validation.

Design choices (see docs/DESIGN-core.md §config):

* Loading is *lenient*: a missing file yields the defaults (without creating
  it — see ``load_config``), a corrupt one is set aside
  (``config.json.broken-<ts>``) instead of blocking the app, unknown keys are
  ignored and missing keys defaulted. The tool must always start.
* Writing is *atomic* (temp file + ``os.replace``) so a crash mid-save never
  leaves a truncated config behind.
* ``default_config()`` ships with NO environments: this repository is public and
  real hostnames are imported at runtime from ``environments.json`` next to the
  exe or entered in the wizard.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import os
import re
import shutil
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, time
from pathlib import Path
from typing import Any, TypeVar

from qtrequestory.core import paths
from qtrequestory.core.fsutil import is_within
from qtrequestory.core.logsetup import resolve_level

log = logging.getLogger(__name__)

CONFIG_VERSION = 1
#: ``{from_version: migrate(raw_dict) -> raw_dict}``; applied in order until CONFIG_VERSION.
MIGRATIONS: dict[int, Callable[[dict], dict]] = {}

ENV_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")
SIDECAR_NAME = "environments.json"
HIDDEN_DIR_NAME = ".qtrequestory"
TIME_FORMAT = "%H:%M"
#: ``folder_envs`` value meaning "the logs in this folder are not to be imported".
IGNORE_FOLDER = "__ignora__"

#: Hours between two attempts of the scheduled task, and how long it keeps
#: retrying. ``validate`` reports a value outside these; ``sanitised_schedule``
#: clamps to them. 12 and 23 keep the retry window inside its own day.
REPEAT_EVERY_RANGE = (1, 12)
REPEAT_FOR_RANGE = (0, 23)

T = TypeVar("T")


class ConfigError(Exception):
    """Unrecoverable configuration problem (e.g. no migration path)."""


class UnknownEnvironment(ValueError):
    """A name ``Config.environments`` does not contain.

    Raised by :meth:`Config.require_env` — used by ``SyncEngine.run`` and the
    CLI's ``--find`` — instead of the bare ``KeyError`` that :meth:`Config.env`
    still raises for callers that already have their own "unknown key"
    handling. The message names the typo AND what IS configured, so a
    misspelled ``-e colll`` is not confused with an environment that is
    correctly named but simply has not been synced yet.
    """

    def __init__(self, name: str, known: Iterable[str]) -> None:
        self.name = name
        self.known = sorted(known)
        super().__init__(f"ambiente sconosciuto: '{name}' (configurati: {', '.join(self.known)})")


# ------------------------------------------------------------------ model ---


@dataclass(frozen=True)
class Environment:
    name: str
    url: str
    enabled: bool = True


@dataclass
class SyncSettings:
    index_timeout_s: int = 15
    download_timeout_s: int = 60
    chunk_size: int = 1_048_576
    retries: int = 1


@dataclass
class IndexSettings:
    parse_json: bool = True


@dataclass(frozen=True)
class ScheduleSettings:
    """When the Windows scheduled task runs (Impostazioni § Sincronizzazione automatica).

    The defaults are not a taste decision: they are the schedule ``TaskSpec``
    used to hard-code (09:00, hourly for 9 h, plus a logon trigger), so an
    existing ``config.json`` — which has no ``schedule`` block at all — keeps
    behaving exactly as before.

    ``start_time`` stays a ``"HH:MM"`` *string* rather than a ``time``: the file
    may have been hand-edited, and a value the user can see in Impostazioni must
    be reported by ``validate`` instead of being silently swallowed while
    parsing. ``repeat_for_h == 0`` means "no repetition": a single daily run.
    """

    start_time: str = "09:00"
    repeat_every_h: int = 1
    repeat_for_h: int = 9
    run_at_logon: bool = True


@dataclass
class Config:
    schema_version: int
    mirror_root: Path
    environments: list[Environment]
    default_window_days: int
    editor_path: Path | None
    output_dir: Path | None
    output_retention_hours: int
    compaction_time: time
    sync: SyncSettings
    index: IndexSettings
    schedule: ScheduleSettings
    log_level: str
    #: Import: the environment the user chose for a folder whose logs name no
    #: configured env (``{folder: env name | IGNORE_FOLDER}``). A key is a
    #: folder path, relative to the scanned root or absolute (see
    #: ``core/archive.py``).
    folder_envs: dict[str, str] = field(default_factory=dict)

    @property
    def _hidden_dir(self) -> Path:
        return self.mirror_root / HIDDEN_DIR_NAME

    @property
    def index_path(self) -> Path:
        return self._hidden_dir / "index.sqlite"

    @property
    def state_path(self) -> Path:
        return self._hidden_dir / "sync-state.json"

    @property
    def lock_path(self) -> Path:
        return self._hidden_dir / "sync.lock"

    @property
    def resolved_output_dir(self) -> Path:
        return self.output_dir if self.output_dir is not None else paths.default_output_dir()

    def env(self, name: str) -> Environment:
        for e in self.environments:
            if e.name == name:
                return e
        raise KeyError(name)

    def require_env(self, name: str) -> Environment:
        """``env(name)``, but as :class:`UnknownEnvironment` instead of a bare
        ``KeyError`` — see its docstring for why the two need to differ."""
        try:
            return self.env(name)
        except KeyError:
            raise UnknownEnvironment(name, [e.name for e in self.environments]) from None

    def enabled_environments(self) -> list[Environment]:
        return [e for e in self.environments if e.enabled]


def default_config() -> Config:
    return Config(
        schema_version=CONFIG_VERSION,
        mirror_root=paths.default_mirror_root(),
        environments=[],
        default_window_days=30,
        editor_path=None,
        output_dir=None,
        output_retention_hours=24,
        compaction_time=time(18, 30),
        sync=SyncSettings(),
        index=IndexSettings(),
        schedule=ScheduleSettings(),
        log_level="INFO",
    )


# ----------------------------------------------------------- (de)serialise ---


def _to_raw(cfg: Config) -> dict[str, Any]:
    return {
        "schema_version": cfg.schema_version,
        "mirror_root": str(cfg.mirror_root),
        "environments": [dataclasses.asdict(e) for e in cfg.environments],
        "default_window_days": cfg.default_window_days,
        "editor_path": str(cfg.editor_path) if cfg.editor_path is not None else None,
        "output_dir": str(cfg.output_dir) if cfg.output_dir is not None else None,
        "output_retention_hours": cfg.output_retention_hours,
        "compaction_time": cfg.compaction_time.strftime(TIME_FORMAT),
        "sync": dataclasses.asdict(cfg.sync),
        "index": dataclasses.asdict(cfg.index),
        "schedule": dataclasses.asdict(cfg.schedule),
        "log_level": cfg.log_level,
        "folder_envs": dict(cfg.folder_envs),
    }


def _warn_unknown(raw: dict, known: Iterable[str], where: str) -> None:
    unknown = sorted(set(raw) - set(known))
    if unknown:
        log.warning("config: chiavi sconosciute ignorate in %s: %s", where, ", ".join(unknown))


def _optional_path(value: Any, key: str) -> Path | None:
    """``None``/empty -> None; a non-string (e.g. ``"mirror_root": 5``) is warned and dropped."""
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        log.warning("config: valore non valido per %s (%r), atteso un percorso", key, value)
        return None
    return Path(value)


def _mirror_root_from_raw(raw: dict, default: Path) -> Path:
    """Unlike :func:`_optional_path`, a *present but empty* string is kept, not
    replaced by the default.

    Silently falling back here is exactly Minor M3: a ``config.json`` hand-
    edited (or half-written by a crashed save) down to ``"mirror_root": ""``
    used to resolve straight to ``%USERPROFILE%\\qtRequestory\\logs`` without a
    word — which, once, was the live installed mirror. Keeping the empty value
    lets ``validate`` report it and the CLI's headless modes refuse to run
    against it instead. Only a missing key (the field was never written, e.g.
    a config from before this field existed) or the wrong JSON type still
    default: those are not "the user emptied it", they are "there was nothing
    here to begin with".
    """
    value = raw.get("mirror_root")
    if value is None:
        return default
    if not isinstance(value, str):
        log.warning("config: valore non valido per mirror_root (%r), atteso un percorso", value)
        return default
    return Path(value)


def parse_hhmm(value: str) -> time | None:
    """``"09:00"`` -> ``time(9, 0)``; ``None`` when it is not a wall clock time.

    Public because three places must agree on what a valid ``start_time`` is:
    ``validate`` (which reports it), the scheduler (which builds the trigger
    from it) and the UI (which shows the resulting schedule in words).
    """
    try:
        return datetime.strptime(str(value).strip(), TIME_FORMAT).time()
    except ValueError:
        return None


def _parse_time(value: Any, fallback: time) -> time:
    if value is None:
        return fallback
    try:
        return datetime.strptime(str(value), TIME_FORMAT).time()
    except ValueError:
        log.warning("config: compaction_time %r non valido (atteso HH:MM), uso %s", value, fallback.strftime(TIME_FORMAT))
        return fallback


def _coerce(value: Any, fallback: T, key: str) -> T:
    """Cast ``value`` to the type of ``fallback``; on failure warn and keep the default.

    A hand-edited ``"default_window_days": "abc"`` must not stop the app from
    starting: the wrong value is reported and the default used instead.
    """
    if value is None:
        return fallback
    kind = type(fallback)
    # bool is a subclass of int: never let `true` sneak into an int field or
    # `bool("false")` turn into True.
    if isinstance(value, kind) and not (kind is int and isinstance(value, bool)):
        return value
    # Only numeric fields get a cast: ``str(5)`` would silently accept a bad log_level.
    if kind is int:
        try:
            return kind(value)  # type: ignore[call-arg]
        # A hand-edited ``1e999`` (or the literal ``Infinity``) parses as
        # ``float("inf")`` — valid JSON as far as ``json.loads`` is concerned —
        # and ``int(inf)`` raises OverflowError, not ValueError: without this
        # the app never got past loading the file.
        except (TypeError, ValueError, OverflowError):
            pass
    log.warning("config: valore non valido per %s (%r), uso il predefinito %r", key, value, fallback)
    return fallback


def _settings_from_raw(cls: type[T], raw: Any, where: str) -> T:
    """Build a settings dataclass from a dict, defaulting missing/invalid fields."""
    defaults = cls()
    if not isinstance(raw, dict):
        return defaults
    names = [f.name for f in dataclasses.fields(cls)]
    _warn_unknown(raw, names, where)
    return cls(**{k: _coerce(raw.get(k), getattr(defaults, k), f"{where}.{k}") for k in names})


def _environments_from_raw(raw: Any) -> list[Environment]:
    """Lenient variant for config.json: a bad item is skipped, not fatal."""
    if not isinstance(raw, list):
        return []
    envs: list[Environment] = []
    for i, item in enumerate(raw):
        try:
            envs.append(_environment_from_item(item, i))
        except ValueError as exc:
            log.warning("config: ambiente ignorato: %s", exc)
    return envs


def _environment_from_item(item: Any, index: int) -> Environment:
    """Strict per-item parsing; shared by config loading and sidecar import."""
    if not isinstance(item, dict):
        raise ValueError(f"environments[{index}]: atteso un oggetto, trovato {type(item).__name__}")
    name, url = item.get("name"), item.get("url")
    if not isinstance(name, str) or not name:
        raise ValueError(f"environments[{index}]: campo 'name' mancante o non stringa")
    if not isinstance(url, str) or not url:
        raise ValueError(f"environments[{index}]: campo 'url' mancante o non stringa")
    enabled = item.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError(f"environments[{index}] ({name}): campo 'enabled' deve essere true/false")
    return Environment(name=name, url=url, enabled=enabled)


def _folder_envs_from_raw(raw: Any) -> dict[str, str]:
    """Lenient: a non-object is dropped, and so is every non-string pair."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        log.warning("config: valore non valido per folder_envs (%r), atteso un oggetto", raw)
        return {}
    good = {k: v for k, v in raw.items() if isinstance(k, str) and k and isinstance(v, str) and v}
    if len(good) != len(raw):
        log.warning("config: folder_envs: voci non valide ignorate: %s",
                    ", ".join(repr(k) for k in raw if k not in good))
    return good


def _from_raw(raw: dict[str, Any]) -> Config:
    d = default_config()
    _warn_unknown(raw, [f.name for f in dataclasses.fields(Config)], "config.json")
    return Config(
        schema_version=_coerce(raw.get("schema_version"), d.schema_version, "schema_version"),
        mirror_root=_mirror_root_from_raw(raw, d.mirror_root),
        environments=_environments_from_raw(raw.get("environments")),
        default_window_days=_coerce(raw.get("default_window_days"), d.default_window_days, "default_window_days"),
        editor_path=_optional_path(raw.get("editor_path"), "editor_path"),
        output_dir=_optional_path(raw.get("output_dir"), "output_dir"),
        output_retention_hours=_coerce(
            raw.get("output_retention_hours"), d.output_retention_hours, "output_retention_hours"
        ),
        compaction_time=_parse_time(raw.get("compaction_time"), d.compaction_time),
        sync=_settings_from_raw(SyncSettings, raw.get("sync"), "sync"),
        index=_settings_from_raw(IndexSettings, raw.get("index"), "index"),
        schedule=_settings_from_raw(ScheduleSettings, raw.get("schedule"), "schedule"),
        log_level=_coerce(raw.get("log_level"), d.log_level, "log_level"),
        folder_envs=_folder_envs_from_raw(raw.get("folder_envs")),
    )


# ------------------------------------------------------------------ files ---


def is_first_run(path: Path) -> bool:
    return not path.exists()


def save_config(cfg: Config, path: Path) -> None:
    _write_json(_to_raw(cfg), path)


def _write_json(data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    # newline="\n": keep LF on Windows too, so diffs/backups are byte-stable.
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def _set_aside_broken(path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    target = path.with_name(f"{path.name}.broken-{stamp}")
    n = 1
    while target.exists():  # two failures within the same second
        target = path.with_name(f"{path.name}.broken-{stamp}-{n}")
        n += 1
    os.replace(path, target)
    return target


def _write_defaults(path: Path) -> Config:
    """Defaults written back to disk; used only after a corrupt file was set aside.

    There the file DID exist, so the user has configured the tool before and the
    first-run wizard must not reappear: something has to take the broken file's
    place.
    """
    cfg = default_config()
    save_config(cfg, path)
    return cfg


def _file_schema_version(raw: dict[str, Any]) -> int:
    """Version the file claims; ``ValueError`` (-> corrupt path) if this app never wrote it."""
    version = _coerce(raw.get("schema_version"), CONFIG_VERSION, "schema_version")
    if version < 1:
        raise ValueError(f"schema_version {version} non valida")
    return version


def _migrate(raw: dict[str, Any], version: int, path: Path) -> dict[str, Any]:
    """Run MIGRATIONS from ``version`` up to CONFIG_VERSION, in order.

    The pre-migration file is kept as ``config.json.bak-v<N>`` so a downgrade of
    the app can recover it; the migrated dict is written back immediately.
    A gap in ``MIGRATIONS`` raises ``ConfigError``: every 1..CONFIG_VERSION-1 was
    once written by this app, so a gap is a developer error and must not
    silently discard the user's settings.
    """
    if version > CONFIG_VERSION:
        log.warning(
            "config: schema_version %d più recente di quella supportata (%d); il file viene letto così com'è",
            version, CONFIG_VERSION,
        )
    if version >= CONFIG_VERSION:
        return raw
    original = version
    while version < CONFIG_VERSION:
        step = MIGRATIONS.get(version)
        if step is None:
            raise ConfigError(
                f"config.json: nessuna migrazione da schema_version {version} a {CONFIG_VERSION}"
            )
        raw = step(raw)
        version += 1
        raw["schema_version"] = version
    shutil.copyfile(path, path.with_name(f"{path.name}.bak-v{original}"))
    _write_json(raw, path)
    log.info("config: migrato da schema_version %d a %d", original, version)
    return raw


def load_config(path: Path) -> Config:
    """The configuration at ``path``, or the defaults when it does not exist yet.

    A missing file is NOT created. ``is_first_run`` answers "has this user ever
    configured the tool", and the answer must survive everything that merely
    *reads* the configuration: a ``--sync`` fired by the scheduled task before
    the first launch, and above all a first-run wizard the user cancelled —
    writing defaults there would silently suppress the wizard forever. The file
    appears when something explicitly saves it (``save_config``), which is what
    the wizard and Impostazioni do.
    """
    if is_first_run(path):
        log.info("config: %s assente, uso i valori predefiniti", path)
        return default_config()
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(raw, dict):
            raise ValueError("il contenuto non è un oggetto JSON")
        version = _file_schema_version(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        broken = _set_aside_broken(path)
        log.warning("config: %s corrotto (%s); rinominato in %s e ripristinati i predefiniti", path, exc, broken.name)
        return _write_defaults(path)
    return _from_raw(_migrate(raw, version, path))


# ------------------------------------------------------------- validation ---


def mirror_root_errors(cfg: Config) -> list[str]:
    """Just the ``mirror_root`` problems, not the full :func:`validate`.

    For callers that only depend on this one field and must not refuse to run
    over something the current operation never touches — the CLI's pre-run
    gate for ``--sync``/``--index``/``--find``: those need a real mirror
    folder, but not a valid ``log_level`` or a well-formed schedule, which
    used to fall back silently and never stopped a sync before this task, and
    must still not (Important finding, fix round 1).
    """
    return _mirror_root_errors(cfg.mirror_root)


def validate(cfg: Config) -> list[str]:
    errors: list[str] = []
    errors.extend(mirror_root_errors(cfg))
    seen: set[str] = set()
    for e in cfg.environments:
        if not ENV_NAME_RE.match(e.name):
            errors.append(f"ambiente '{e.name}': il nome può contenere solo lettere, cifre, '-' e '_'")
        key = e.name.lower()
        if key in seen:
            errors.append(f"ambiente '{e.name}': nome duplicato (il confronto ignora maiuscole/minuscole)")
        seen.add(key)
        if not e.url.startswith(("http://", "https://")):
            errors.append(f"ambiente '{e.name}': l'URL '{e.url}' deve iniziare con http:// o https://")
        if not e.url.endswith("/"):
            errors.append(f"ambiente '{e.name}': l'URL '{e.url}' deve terminare con '/'")
    if not 1 <= cfg.default_window_days <= 3650:
        errors.append(f"default_window_days deve essere tra 1 e 3650 (trovato {cfg.default_window_days})")
    if cfg.output_retention_hours < 1:
        errors.append(f"output_retention_hours deve essere almeno 1 (trovato {cfg.output_retention_hours})")
    # Unchecked until now, and the one field whose typo used to stop the
    # windowed exe from starting at all (``configure_logging`` runs before any
    # window or log file exists). It now falls back to INFO there; this is
    # where the user is told why their level was ignored.
    _, bad_level = resolve_level(cfg.log_level)
    if bad_level is not None:
        errors.append(bad_level)
    errors.extend(_schedule_errors(cfg.schedule))
    errors.extend(output_dir_errors(cfg))
    return errors


def output_dir_errors(cfg: Config) -> list[str]:
    """F7: the output folder is pruned by age (``extract.housekeeping``), so it
    must never be the log folder, lie inside it, or contain it."""
    if _mirror_root_errors(cfg.mirror_root):
        return []  # already reported; a relative path would compare against the CWD
    out = cfg.resolved_output_dir
    if is_within(out, cfg.mirror_root) or is_within(cfg.mirror_root, out):
        return [
            f"La cartella dei file estratti ('{out}') non può coincidere con la cartella dei log, "
            "stare dentro di essa o contenerla: i file estratti vecchi vengono cancellati "
            "automaticamente"
        ]
    return []


def _mirror_root_errors(mirror_root: Path) -> list[str]:
    """Not this function's job to decide WHAT the folder should be — only that
    it is a real, absolute one. ``Path("")`` (an emptied field, see
    ``_mirror_root_from_raw``) normalises to ``Path(".")``, which is why both
    are treated as "not set" rather than "a relative path" — pathlib has
    already erased the difference by the time this runs.
    """
    if mirror_root.is_absolute():
        return []
    text = str(mirror_root)
    if text in ("", "."):
        return ["La cartella dei log non è impostata"]
    return [
        "La cartella dei log deve essere un percorso completo, per esempio "
        f"C:\\Users\\<utente>\\qtRequestory\\logs (trovato '{text}')"
    ]


def _schedule_errors(schedule: ScheduleSettings) -> list[str]:
    """The bounds Task Scheduler and a sensible retry window impose.

    ``repeat_every_h`` stops at 12 and ``repeat_for_h`` at 23 so that the window
    can never overlap the next day's run; ``repeat_for_h = 0`` is the legitimate
    "one run a day, no retries".
    """
    errors: list[str] = []
    if parse_hhmm(schedule.start_time) is None:
        errors.append(
            f"schedule.start_time '{schedule.start_time}' non è un orario valido (atteso HH:MM)"
        )
    every_low, every_high = REPEAT_EVERY_RANGE
    if not every_low <= schedule.repeat_every_h <= every_high:
        errors.append(
            f"schedule.repeat_every_h deve essere tra {every_low} e {every_high} "
            f"(trovato {schedule.repeat_every_h})"
        )
    for_low, for_high = REPEAT_FOR_RANGE
    if not for_low <= schedule.repeat_for_h <= for_high:
        errors.append(
            f"schedule.repeat_for_h deve essere tra {for_low} e {for_high} "
            f"(trovato {schedule.repeat_for_h})"
        )
    return errors


def sanitised_schedule(schedule: ScheduleSettings) -> ScheduleSettings:
    """The schedule as the scheduled task will really run it.

    ``validate`` *reports* a bad value; this *repairs* it, because the file can
    be hand-edited and the task must still be registered — a mirror that stops
    syncing loses every day the server purges before the next run. The start
    time falls back to the default (and is canonicalised, ``"7:30"`` ->
    ``"07:30"``) and the two
    counts are clamped into range, which also keeps XML ``schtasks`` refuses
    (``<Interval>PT0H</Interval>``) from ever being built.

    One function, so that what gets registered and what the UI says about it
    cannot diverge: ``scheduler.spec_from_config`` and the sentence the pages
    show both start here.
    """
    start = parse_hhmm(schedule.start_time) or parse_hhmm(ScheduleSettings().start_time)
    assert start is not None  # the dataclass default is always a valid HH:MM
    return ScheduleSettings(
        start_time=start.strftime(TIME_FORMAT),
        repeat_every_h=_clamp(schedule.repeat_every_h, *REPEAT_EVERY_RANGE),
        repeat_for_h=_clamp(schedule.repeat_for_h, *REPEAT_FOR_RANGE),
        run_at_logon=schedule.run_at_logon,
    )


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


# ------------------------------------------------- environments sidecar ---


def import_environments_file(path: Path) -> list[Environment]:
    """Parse ``[{"name","url","enabled"?}, ...]``; ValueError on anything malformed."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError(f"{path.name}: JSON non valido ({exc})") from exc
    if not isinstance(raw, list):
        raise ValueError(f"{path.name}: atteso un elenco JSON di ambienti")
    return [_environment_from_item(item, i) for i, item in enumerate(raw)]


def find_sidecar_environments(exe_dir: Path) -> Path | None:
    candidate = exe_dir / SIDECAR_NAME
    return candidate if candidate.is_file() else None


# ------------------------------------------------------------------ editor ---


def _default_editor_candidates() -> list[Path | None]:
    found: list[Path | None] = []
    for var in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(var)
        if base:
            found.append(Path(base) / "Notepad++" / "notepad++.exe")
    which = shutil.which("notepad++")
    found.append(Path(which) if which else None)
    return found


def detect_editor(candidates: Iterable[Path | None] | None = None) -> Path | None:
    """First existing candidate; ``candidates`` overrides the Notepad++ defaults for tests."""
    for c in _default_editor_candidates() if candidates is None else candidates:
        if c is not None and Path(c).is_file():
            return Path(c)
    return None
