"""What one environment "is" right now, in one word and one tone. No Qt here.

The card's badge and the app-bar chip's dot describe the same environment, so
they are computed by the same function: :func:`badge_for`. Before, the card
and the chip had their own rules and could disagree (a grey "Non
raggiungibile" pill next to an amber dot).

Three rules shape it:

* **What is happening beats what happened**, and what happened beats what the
  mirror looks like on disk: in corso > in attesa > non raggiungibile >
  errori > giorni persi > da scaricare > aggiornato / da aggiornare / mai
  sincronizzato. A mirror that is not fresh only because today had no calls
  (``EnvStatus.freshness == "empty_today"``) reads "aggiornato" too, with a
  tooltip saying tomorrow's sync confirms the day.
* **A hole beats a fresh mirror.** The server keeps its files until a manual
  purge: a day with calls that is still listed but not local (``pending``)
  is one sync away, a day purged before it was downloaded (``lost``) is gone.
  Neither may hide behind a green "aggiornato".
* **Red only for what is gone.** A lost day is the one ``bad`` badge. An
  unreachable endpoint is the normal state of this tool outside the office
  VPN; red there would turn "you are not on the VPN" into "something is
  broken". Every other tone is ``ok`` / ``warn`` / ``neutral``.

The header chip (D5) asks one more thing of the same badges: does anything
need the user? :func:`attention_level` says it per kind — red (``bad``) for
what is gone or failed (lost days, file errors), amber (``warn``) for what one
sync or the VPN fixes (to download, not reachable, stale, never synced),
nothing for the rest — and :func:`attention_for` folds the environments into
the one :class:`Attention` the chip and its panel show.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import EnvStatus

__all__ = [
    "Attention", "Badge", "EMPTY_TODAY", "ERRORS", "FRESH", "LOST", "NEVER", "PENDING", "QUEUED", "RUNNING", "STALE",
    "UNREACHABLE", "attention_for", "attention_level", "badge_for", "hint_for",
]

FRESH = "fresh"
EMPTY_TODAY = "empty_today"
STALE = "stale"
NEVER = "never"
RUNNING = "running"
QUEUED = "queued"
PENDING = "pending"
LOST = "lost"
UNREACHABLE = "unreachable"
ERRORS = "errors"

_TONES = {
    FRESH: "ok",
    EMPTY_TODAY: "ok",
    STALE: "warn",
    NEVER: "neutral",
    RUNNING: "neutral",
    QUEUED: "neutral",
    PENDING: "warn",
    LOST: "bad",
    UNREACHABLE: "warn",
    ERRORS: "warn",
}

_TEXTS = {
    FRESH: strings.SYNC_BADGE_FRESH,
    EMPTY_TODAY: strings.SYNC_BADGE_FRESH,
    STALE: strings.SYNC_BADGE_STALE,
    NEVER: strings.SYNC_BADGE_NEVER,
    RUNNING: strings.SYNC_BADGE_RUNNING,
    QUEUED: strings.SYNC_BADGE_QUEUED,
    UNREACHABLE: strings.SYNC_BADGE_UNREACHABLE,
    ERRORS: strings.SYNC_BADGE_ERRORS,
}

#: Header attention per kind; a kind not listed needs nothing from the user.
_ATTENTION = {
    LOST: "bad",
    ERRORS: "bad",
    PENDING: "warn",
    UNREACHABLE: "warn",
    STALE: "warn",
    NEVER: "warn",
}

_HINTS = {
    LOST: strings.SYNC_HINT_LOST,
    ERRORS: strings.SYNC_HINT_ERRORS,
    PENDING: strings.SYNC_HINT_PENDING,
    UNREACHABLE: strings.SYNC_HINT_UNREACHABLE,
    STALE: strings.SYNC_HINT_STALE,
    NEVER: strings.SYNC_HINT_NEVER,
}

#: Worst first.
_LEVELS = ("bad", "warn")


@dataclass(frozen=True)
class Badge:
    """``kind`` for code, ``tone`` for the theme (``pill``/``dot``), ``text`` for
    people, ``tooltip`` for the one badge that needs a word more (else "")."""

    kind: str
    tone: str
    text: str
    tooltip: str = ""


def badge_for(
    status: EnvStatus | None,
    *,
    running: bool = False,
    queued: bool = False,
    reachable: bool | None = None,
    failed: int = 0,
    pending: int = 0,
    lost: int = 0,
) -> Badge:
    """The single badge that describes an environment right now.

    ``reachable`` is None while nobody has asked (neither a probe nor a run);
    ``failed`` counts the files the last run could not download; ``pending``
    and ``lost`` the days of ``coverage_days()`` with those names.
    """
    kind = _kind(status, running=running, queued=queued, reachable=reachable,
                 failed=failed, pending=pending, lost=lost)
    if kind == LOST:
        text = strings.SYNC_BADGE_LOST_ONE if lost == 1 else strings.SYNC_BADGE_LOST.format(n=lost)
    elif kind == PENDING:
        text = strings.SYNC_BADGE_PENDING.format(n=pending)
    else:
        text = _TEXTS[kind]
    tooltip = strings.SYNC_BADGE_EMPTY_TODAY_TOOLTIP if kind == EMPTY_TODAY else ""
    return Badge(kind, _TONES[kind], text, tooltip)


def _kind(status: EnvStatus | None, *, running: bool, queued: bool, reachable: bool | None,
          failed: int, pending: int, lost: int) -> str:
    if running:
        return RUNNING
    if queued:
        return QUEUED
    if reachable is False:
        return UNREACHABLE
    if failed:
        return ERRORS
    if lost:
        return LOST
    if pending:
        return PENDING
    if status is None:
        return NEVER
    if status.fresh:
        return FRESH
    if status.freshness == "empty_today":
        return EMPTY_TODAY
    if status.never_synced:
        return NEVER
    return STALE


@dataclass(frozen=True)
class Attention:
    """What the header chip says about all the environments together.

    ``level`` is "" (nothing to do), ``"warn"`` or ``"bad"``; ``lines`` word
    each environment that needs attention ("svil: 1 giorno perso"); ``running``
    is True while a sync works on (or queues) any of them.
    """

    level: str = ""
    lines: tuple[str, ...] = ()
    running: bool = False

    @property
    def count(self) -> int:
        """How many environments need attention."""
        return len(self.lines)


def attention_level(kind: str) -> str:
    """"bad", "warn" or "" for one badge kind (see the module docstring)."""
    return _ATTENTION.get(kind, "")


def hint_for(kind: str) -> str:
    """One sentence on what the badge means for the user, or "" when nothing."""
    return _HINTS.get(kind, "")


def attention_for(badges: Mapping[str, Badge]) -> Attention:
    """Fold ``{env: badge}`` into the header's single :class:`Attention`."""
    levels = {attention_level(b.kind) for b in badges.values()}
    level = next((lv for lv in _LEVELS if lv in levels), "")
    lines = tuple(strings.SYNC_SUMMARY_ENTRY.format(env=env, when=b.text)
                  for env, b in badges.items() if attention_level(b.kind))
    running = any(b.kind in (RUNNING, QUEUED) for b in badges.values())
    return Attention(level, lines, running)
