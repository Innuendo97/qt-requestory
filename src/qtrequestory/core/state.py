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
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

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
                self._save()
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
        """True iff the env was synced after the most recent compaction moment.

        The server compacts loose files into the daily file once a day at
        ``compaction_time``; a sync completed after that moment already holds
        everything the server will ever publish for that day.
        """
        last_success = self.get(env).last_success
        if last_success is None:
            return False
        last_compaction = datetime.combine(now.date(), compaction_time)
        if now.time() < compaction_time:
            last_compaction -= timedelta(days=1)
        return last_success >= last_compaction

    # --------------------------------------------------------------- update ---

    def mark_success(self, env: str, when: datetime, *, last_remote_daily: int = 0, last_downloaded: int = 0) -> None:
        self._ensure_loaded()
        self._envs[env] = EnvSyncState(when, last_remote_daily, last_downloaded)
        self._save()

    def _save(self) -> None:
        payload = {
            "envs": {
                env: {
                    "last_success": s.last_success.isoformat() if s.last_success else None,
                    "last_remote_daily": s.last_remote_daily,
                    "last_downloaded": s.last_downloaded,
                }
                for env, s in sorted(self._envs.items())
            }
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)


def _parse_env(raw: object) -> EnvSyncState:
    if not isinstance(raw, dict):
        raise ValueError("env entry is not an object")
    ts = raw.get("last_success")
    return EnvSyncState(
        last_success=datetime.fromisoformat(ts) if ts is not None else None,
        last_remote_daily=int(raw.get("last_remote_daily", 0)),
        last_downloaded=int(raw.get("last_downloaded", 0)),
    )


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
