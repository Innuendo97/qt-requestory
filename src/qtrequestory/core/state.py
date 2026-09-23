"""Per-environment sync state (``<mirror_root>/.qtrequestory/sync-state.json``).

The state answers one question for the scheduler and the UI: "did the last
successful sync of this environment happen after the last server-side
compaction?" — if so there is nothing new to fetch. Everything else stored
here is informational (counts shown in the UI).

The file is written atomically (temp file + ``os.replace``) so a crash or a
killed scheduled task can never leave a half-written JSON behind. Loading is
tolerant: a missing or corrupt file simply means "never synced", which at worst
costs one redundant sync.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

from qtrequestory.core.fsutil import replace_with_retry

log = logging.getLogger(__name__)

LEGACY_FILE_NAME = ".last-sync.json"
# The legacy PowerShell script only recorded the *day* of the last sync. We
# import it as noon of that day: noon is before the 18:30 compaction, so the
# first run after the migration is deliberately "not fresh" and re-syncs — the
# safe direction (a redundant sync costs seconds; a skipped one loses a day
# that the server drops after ~1 day of retention).
LEGACY_IMPORT_TIME = time(12, 0)


@dataclass
class EnvSyncState:
    last_success: datetime | None = None
    last_remote_daily: int = 0
    last_downloaded: int = 0
    #: The newest NON-EMPTY daily day, from the last listing read, that is
    #: now mirrored locally (present, shrunk, or a successful download); a
    #: 0-byte day never counts. ``None`` when never synced, when the listing
    #: held only 0-byte days, or when read from a state file written before
    #: this field existed. See ``is_fresh`` for how it drives freshness.
    newest_day: date | None = None


class SyncState:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._envs: dict[str, EnvSyncState] = {}
        self._loaded = False

    # ----------------------------------------------------------------- load ---

    def load(self) -> SyncState:
        """Read the state file; missing → empty, corrupt → empty + warning.

        When the new file does not exist yet but the legacy ``.last-sync.json``
        (next to the mirror root, i.e. ``path.parent.parent``) does, its days
        are imported and the new file is written immediately, so the import
        happens exactly once. The legacy file is never modified.
        """
        self._envs = {}
        self._loaded = True
        if self.path.exists():
            self._envs = self._read_current()
            return self
        legacy = self.path.parent.parent / LEGACY_FILE_NAME
        if legacy.exists():
            self._envs = _read_legacy(legacy)
            if self._envs:
                log.info("stato di sincronizzazione importato da %s", legacy)
                try:
                    self._save()
                except OSError as e:
                    # The import already happened in memory (self._envs is set):
                    # this run uses the imported values regardless. Only the
                    # write-back failed, so the same legacy import is retried
                    # on the next load() that manages to save successfully.
                    log.warning("stato di sincronizzazione non salvato dopo l'importazione legacy (%s): %s",
                               self.path.name, e)
        return self

    def _read_current(self) -> dict[str, EnvSyncState]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            envs_raw = data["envs"]
            if not isinstance(envs_raw, dict):
                raise ValueError("'envs' is not an object")
            return {str(env): _parse_env(raw) for env, raw in envs_raw.items()}
        except (OSError, ValueError, KeyError, TypeError) as e:
            log.warning("stato di sincronizzazione illeggibile (%s: %s): riparto da zero", self.path.name, e)
            return {}

    def _ensure_loaded(self) -> None:
        # A caller that forgets load() must not clobber other envs on save.
        if not self._loaded:
            self.load()

    # ---------------------------------------------------------------- query ---

    def get(self, env: str) -> EnvSyncState:
        self._ensure_loaded()
        return self._envs.get(env, EnvSyncState())

    def is_fresh(self, env: str, now: datetime, compaction_time: time) -> bool:
        """True iff the compacted day is confirmed mirrored, not just "synced recently".

        Fresh requires all of:

        1. ``last_success`` is not ``None`` and is not in the future. A
           timestamp in the future can never be trusted (clock skew, a bad
           write) so it is treated as not fresh, and logged.
        2. ``last_success >= last_compaction``, where the server compacts
           loose files into the daily file once a day at ``compaction_time``
           (``last_compaction`` is today at ``compaction_time`` if ``now`` is
           past it, otherwise yesterday's).
        3. ``newest_day is not None and newest_day >= last_compaction.date()``:
           the newest NON-EMPTY daily file *seen in the remote listing*
           that is now mirrored locally (present, shrunk, or a successful
           download) must be at least the compacted day. A sync that read the
           listing before the server had compacted is NOT fresh even though
           it ran after ``compaction_time`` — this is what makes a late/slow
           compaction on the server retried on the next hourly run instead of
           silently skipped (a skipped day is lost: the server keeps only ~1
           day). A 0-byte file never confirms a day: the server lists one
           before it compacts too. A quiet day (a weekend) therefore costs
           one cheap listing per hour until the next non-empty day is
           mirrored.
        4. A state loaded from a file written before ``newest_day`` existed
           (no such key) has ``newest_day is None`` and so is also not fresh —
           one extra sync after the upgrade is the safe direction.
        """
        state = self.get(env)
        last_success = state.last_success
        if last_success is None:
            return False
        if last_success > now:
            log.warning("stato di sincronizzazione di %s nel futuro (%s): ignorato", env, last_success.isoformat())
            return False
        last_compaction = datetime.combine(now.date(), compaction_time)
        if now.time() < compaction_time:
            last_compaction -= timedelta(days=1)
        if last_success < last_compaction:
            return False
        return state.newest_day is not None and state.newest_day >= last_compaction.date()

    # --------------------------------------------------------------- update ---

    def mark_success(
        self,
        env: str,
        when: datetime,
        *,
        last_remote_daily: int = 0,
        last_downloaded: int = 0,
        newest_day: date | None = None,
    ) -> None:
        self._ensure_loaded()
        self._envs[env] = EnvSyncState(when, last_remote_daily, last_downloaded, newest_day)
        self._save()

    def _save(self) -> None:
        payload = {
            "envs": {
                env: {
                    "last_success": s.last_success.isoformat() if s.last_success else None,
                    "last_remote_daily": s.last_remote_daily,
                    "last_downloaded": s.last_downloaded,
                    "newest_day": s.newest_day.isoformat() if s.newest_day else None,
                }
                for env, s in sorted(self._envs.items())
            }
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        replace_with_retry(tmp, self.path)


def _parse_env(raw: object) -> EnvSyncState:
    if not isinstance(raw, dict):
        raise ValueError("env entry is not an object")
    ts = raw.get("last_success")
    return EnvSyncState(
        last_success=datetime.fromisoformat(ts) if ts is not None else None,
        last_remote_daily=int(raw.get("last_remote_daily", 0)),
        last_downloaded=int(raw.get("last_downloaded", 0)),
        newest_day=_parse_newest_day(raw.get("newest_day")),
    )


def _parse_newest_day(raw: object) -> date | None:
    # Missing key (a file written before this field existed) or any invalid
    # value falls back to None, which is_fresh treats as "not fresh" — the
    # safe direction, never a crash on a state file written by an older build.
    if raw is None:
        return None
    try:
        return date.fromisoformat(str(raw))
    except ValueError:
        return None


def _read_legacy(legacy: Path) -> dict[str, EnvSyncState]:
    """``{"svil": "YYYY-MM-DD", ...}`` written by PowerShell with a UTF-8 BOM."""
    try:
        data = json.loads(legacy.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError("not an object")
    except (OSError, ValueError) as e:
        log.warning("file legacy %s illeggibile (%s): ignorato", legacy.name, e)
        return {}
    envs: dict[str, EnvSyncState] = {}
    for env, day in data.items():
        try:
            d = date.fromisoformat(str(day))
        except ValueError:
            log.warning("file legacy %s: valore non valido per %r (%r), ignorato", legacy.name, env, day)
            continue
        envs[str(env)] = EnvSyncState(last_success=datetime.combine(d, LEGACY_IMPORT_TIME))
    return envs
