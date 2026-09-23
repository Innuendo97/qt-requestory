"""The last searches, remembered across sessions (``search/recent``).

Ten entries, newest first, one per distinct ``(env, fdi, key, mode)``: running
the same search again moves it to the top instead of filling the list with
copies. Stored as a JSON list in the user's ``QSettings`` so the Impostazioni
page can clear it without importing anything from here.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass

from PySide6.QtCore import QSettings

from qtrequestory.ui import prefs, strings

__all__ = ["MAX_RECENTS", "Recent", "load_recents", "remember"]

log = logging.getLogger(__name__)

MAX_RECENTS = 10
#: How much of an FDI a recent-search label shows.
FDI_LABEL_LEN = 8


@dataclass(frozen=True)
class Recent:
    env: str
    fdi: str
    key: str
    mode: str

    def label(self) -> str:
        """"coll · 1a2b3c4d… · MOD_TEST_A · contiene"."""
        parts = [self.env]
        if self.fdi:
            short = self.fdi[:FDI_LABEL_LEN]
            parts.append(short + strings.SEARCH_ELLIPSIS if len(self.fdi) > FDI_LABEL_LEN else short)
        if self.key:
            parts.append(self.key)
        if self.key and self.mode == "contains":
            parts.append(strings.SEARCH_KEY_MODE_CONTAINS)
        return strings.SEARCH_RECENT_SEPARATOR.join(parts)


def load_recents(settings: QSettings) -> list[Recent]:
    """The stored list; anything unreadable is dropped, never raised."""
    raw = settings.value(prefs.RECENT_KEY, "")
    try:
        items = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        log.debug("ricerche recenti illeggibili: %r", raw)
        return []
    recents: list[Recent] = []
    for item in items if isinstance(items, list) else []:
        try:
            recents.append(Recent(str(item["env"]), str(item.get("fdi", "")),
                                  str(item.get("key", "")), str(item.get("mode", "exact"))))
        except (KeyError, TypeError, AttributeError):
            continue
    return recents[:MAX_RECENTS]


def remember(settings: QSettings, recent: Recent) -> list[Recent]:
    """Put ``recent`` on top (once) and store the list; returns it."""
    recents = [recent] + [r for r in load_recents(settings) if r != recent]
    recents = recents[:MAX_RECENTS]
    settings.setValue(prefs.RECENT_KEY, json.dumps([asdict(r) for r in recents]))
    return recents
