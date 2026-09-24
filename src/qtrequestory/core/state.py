"""Per-environment sync state (``<mirror_root>/.qtrequestory/sync-state.json``).

The state answers one question for the scheduler and the UI: "did the last
successful sync of this environment happen after the last server-side
compaction?" — if so there is nothing new to fetch. It also remembers what
the last listing held (``oldest_listed``, ``listed_nonempty``) and every
non-empty day ever listed (``seen_nonempty``), so the coverage view can tell
a day still on the server ("da scaricare") from one the server purged before
it was downloaded. The server keeps its daily files until a manual purge
from the OCP terminal, which deletes them: the local mirror is the archive.
The counts are informational (shown in the UI).

The file is written atomically (temp file + ``os.replace``) so a crash or a
killed scheduled task can never leave a half-written JSON behind. Loading is
tolerant: a missing or corrupt file simply means "never synced", which at worst
costs one redundant sync.
"""
from __future__ import annotations

import dataclasses
import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

from qtrequestory.core.fsutil import replace_with_retry

log = logging.getLogger(__name__)

LEGACY_FILE_NAME = ".last-sync.json"
# The legacy PowerShell script only recorded the *day* of the last sync. We
# import it as noon of that day: noon is before the 18:30 compaction, so the
# first run after the migration is deliberately "not fresh" and re-syncs — the
# safe direction (a redundant sync costs seconds; a skipped one delays a day
# that a manual purge on the server could then delete before it is mirrored).
LEGACY_IMPORT_TIME = time(12, 0)

#: ``seen_nonempty`` only keeps the days this recent (relative to the listing).
SEEN_NONEMPTY_DAYS = 400


@dataclass
class EnvSyncState:
    last_success: datetime | None = None
    last_remote_daily: int = 0
    last_downloaded: int = 0
    #: The newest daily day, from the last listing read, that is now
    #: mirrored locally: present, shrunk, a successful download, or a
    #: COMPACTED 0-byte day whose local 0-byte file exists (created by the
    #: sync or already there). ``None`` when never synced or when read from a
    #: state file written before this field existed. See ``is_fresh``.
    newest_day: date | None = None
    #: The oldest day of the last listing read (the server's current horizon).
    oldest_listed: date | None = None
    #: The non-empty days of the last listing read, ascending.
    listed_nonempty: tuple[date, ...] = ()
    #: Every non-empty day ever listed, ascending, capped to the last
    #: ``SEEN_NONEMPTY_DAYS`` days before the latest listing.
    seen_nonempty: tuple[date, ...] = ()


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
           the newest daily file *seen in the remote listing* that is now
           mirrored locally must be at least the compacted day. A sync that
           read the listing before the server had compacted is NOT fresh even
           though it ran after ``compaction_time`` — this is what makes a
           late/slow compaction on the server retried on the next hourly run
           instead of silently skipped (a day left behind for long could be
           deleted by a manual purge on the server before it is mirrored). A
           0-byte day counts once it is compacted (listing time >= that day
           at ``compaction_time``) and its 0-byte local file exists: it is a
           day without traffic, so a quiet weekend is fresh like any other
           day. Today's 0-byte file before compaction never counts.
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
        """Record a successful sync; the listing memory is kept as it is."""
        self._ensure_loaded()
        self._envs[env] = dataclasses.replace(
            self._envs.get(env, EnvSyncState()),
            last_success=when, last_remote_daily=last_remote_daily,
            last_downloaded=last_downloaded, newest_day=newest_day,
        )
        self._save()

    def record_listing(
        self,
        env: str,
        when: datetime,
        *,
        oldest_listed: date | None,
        listed_nonempty: Iterable[date],
    ) -> None:
        """Remember what a listing read at ``when`` held, whatever the run's
        outcome: ``seen_nonempty`` grows by the listed non-empty days and
        forgets those older than ``SEEN_NONEMPTY_DAYS`` before ``when``.
        ``last_success`` and the counts are left alone."""
        self._ensure_loaded()
        listed = tuple(sorted(set(listed_nonempty)))
        current = self._envs.get(env, EnvSyncState())
        cutoff = when.date() - timedelta(days=SEEN_NONEMPTY_DAYS)
        seen = tuple(sorted(d for d in set(current.seen_nonempty) | set(listed) if d >= cutoff))
        self._envs[env] = dataclasses.replace(
            current, oldest_listed=oldest_listed, listed_nonempty=listed, seen_nonempty=seen)
        self._save()

    def _save(self) -> None:
        payload = {
            "envs": {
                env: {
                    "last_success": s.last_success.isoformat() if s.last_success else None,
                    "last_remote_daily": s.last_remote_daily,
                    "last_downloaded": s.last_downloaded,
                    "newest_day": s.newest_day.isoformat() if s.newest_day else None,
                    "oldest_listed": s.oldest_listed.isoformat() if s.oldest_listed else None,
                    "listed_nonempty": [d.isoformat() for d in s.listed_nonempty],
                    "seen_nonempty": [d.isoformat() for d in s.seen_nonempty],
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
        oldest_listed=_parse_newest_day(raw.get("oldest_listed")),
        listed_nonempty=_parse_days(raw.get("listed_nonempty")),
        seen_nonempty=_parse_days(raw.get("seen_nonempty")),
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


def _parse_days(raw: object) -> tuple[date, ...]:
    # Same tolerance as _parse_newest_day: a missing key (older file) or a
    # value that is not a list is (); invalid items are dropped one by one.
    if not isinstance(raw, list):
        return ()
    days: set[date] = set()
    for item in raw:
        if not isinstance(item, str):
            continue
        try:
            days.add(date.fromisoformat(item))
        except ValueError:
            continue
    return tuple(sorted(days))


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
