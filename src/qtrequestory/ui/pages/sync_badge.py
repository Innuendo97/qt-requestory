"""What one environment "is" right now, in one word and one tone. No Qt here.

The card's badge and the app-bar chip's dot describe the same environment, so
they are computed by the same function: :func:`badge_for`. Before, the card
and the chip had their own rules and could disagree (a grey "Non
raggiungibile" pill next to an amber dot).

Three rules shape it:

* **What is happening beats what happened**, and what happened beats what the
  mirror looks like on disk: in corso > in attesa > non raggiungibile >
  errori > giorni mancanti > aggiornato / da aggiornare / mai sincronizzato.
* **A lost day beats a fresh mirror.** The server keeps about one day of logs,
  so a missing weekday in the local archive is gone for good — it must not
  hide behind a green "aggiornato".
* **Never red.** An unreachable endpoint is the normal state of this tool
  outside the office VPN; red would turn "you are not on the VPN" into
  "something is broken". Tones are ``ok`` / ``warn`` / ``neutral``.
"""
from __future__ import annotations

from dataclasses import dataclass

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import EnvStatus

__all__ = [
    "Badge", "ERRORS", "FRESH", "MISSING", "NEVER", "QUEUED", "RUNNING", "STALE",
    "UNREACHABLE", "badge_for",
]

FRESH = "fresh"
STALE = "stale"
NEVER = "never"
RUNNING = "running"
QUEUED = "queued"
MISSING = "missing"
UNREACHABLE = "unreachable"
ERRORS = "errors"

_TONES = {
    FRESH: "ok",
    STALE: "warn",
    NEVER: "neutral",
    RUNNING: "neutral",
    QUEUED: "neutral",
    MISSING: "warn",
    UNREACHABLE: "warn",
    ERRORS: "warn",
}

_TEXTS = {
    FRESH: strings.SYNC_BADGE_FRESH,
    STALE: strings.SYNC_BADGE_STALE,
    NEVER: strings.SYNC_BADGE_NEVER,
    RUNNING: strings.SYNC_BADGE_RUNNING,
    QUEUED: strings.SYNC_BADGE_QUEUED,
    UNREACHABLE: strings.SYNC_BADGE_UNREACHABLE,
    ERRORS: strings.SYNC_BADGE_ERRORS,
}


@dataclass(frozen=True)
class Badge:
    """``kind`` for code, ``tone`` for the theme (``pill``/``dot``), ``text`` for people."""

    kind: str
    tone: str
    text: str


def badge_for(
    status: EnvStatus | None,
    *,
    running: bool = False,
    queued: bool = False,
    reachable: bool | None = None,
    failed: int = 0,
    missing: int = 0,
) -> Badge:
    """The single badge that describes an environment right now.

    ``reachable`` is None while nobody has asked (neither a probe nor a run);
    ``failed`` counts the files the last run could not download; ``missing``
    the weekdays absent from the local archive (``coverage_days().missing``).
    """
    kind = _kind(status, running=running, queued=queued, reachable=reachable,
                 failed=failed, missing=missing)
    if kind == MISSING:
        text = (strings.SYNC_BADGE_MISSING_ONE if missing == 1
                else strings.SYNC_BADGE_MISSING.format(n=missing))
    else:
        text = _TEXTS[kind]
    return Badge(kind, _TONES[kind], text)


def _kind(status: EnvStatus | None, *, running: bool, queued: bool, reachable: bool | None,
          failed: int, missing: int) -> str:
    if running:
        return RUNNING
    if queued:
        return QUEUED
    if reachable is False:
        return UNREACHABLE
    if failed:
        return ERRORS
    if missing:
        return MISSING
    if status is None:
        return NEVER
    if status.fresh:
        return FRESH
    if status.never_synced:
        return NEVER
    return STALE
