"""Turning sync events and numbers into the text the page shows. No Qt in here.

Two jobs, both pure functions, both testable without a ``QApplication``:

**The registro.** It must read exactly like ``sync.log``, because the panel is
prefilled with the tail of that very file: two wordings for the same event
would look like two different things happening. The only way to guarantee that
is to let the core's own :class:`~qtrequestory.core.events.LoggingSink` produce
the line — it is fed a private, non-propagating logger whose single handler
keeps the formatted message instead of writing it anywhere. So the page copies
no format string from the core, and a change to the core's wording reaches the
window without anybody editing the UI.

That import — and ``events.format_size``, the size wording the ``LoggingSink``
itself uses — is the documented exception to "the UI only sees
``ui/contracts.py``" (Task 11 brief: *"ok to import ``LoggingSink`` text style
but produce str"*); nothing else from ``core`` is touched here.

**The numbers.** Sizes, rates, ETAs and "oggi 11:23" — Italian, with a decimal
comma, and rounded the way DESIGN-ui shows them ("41 MB", "1,5 GB",
"8,2 MB/s", "circa 2 min rimanenti").

**The page's sentences.** The auto-sync line, the pending/lost banners, the
final message of a run and the registro header: small rules ("completata"
only when every environment is fine) that deserve tests without a widget.
"""
from __future__ import annotations

import logging
import re
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime

from qtrequestory.core.events import LoggingSink  # see the module docstring
from qtrequestory.core.events import format_size as core_format_size  # ditto
from qtrequestory.ui import strings
from qtrequestory.ui.contracts import Event, ScheduleSettings, TaskStatus
from qtrequestory.ui.pages.progress_model import PHASE_INDEX, ProgressSnapshot
from qtrequestory.ui.pages.schedule_text import schedule_sentence

__all__ = [
    "RunOutcome", "StripTexts", "auto_title", "format_days", "format_eta", "format_rate",
    "format_size", "format_task_status", "format_when", "last_log_time", "log_header",
    "log_line", "lost_days_text", "message", "pending_days_text", "run_outcome", "status_text",
    "strip_texts",
]

KB = 1024

#: Mirrors ``core.logsetup.DATE_FORMAT`` so an appended line and a line read
#: back from ``sync.log`` are indistinguishable.
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


# ------------------------------------------------------------ event -> text ---

class _Capture(logging.Handler):
    """Keeps the formatted message of the last record instead of emitting it."""

    def __init__(self) -> None:
        super().__init__(logging.NOTSET)
        self.line: str | None = None

    def emit(self, record: logging.LogRecord) -> None:
        self.line = record.getMessage()


def _build_sink() -> tuple[LoggingSink, _Capture]:
    """A ``LoggingSink`` writing into a logger that reaches nothing else.

    ``logging.Logger(...)`` is built directly rather than through
    ``getLogger``: the object stays out of the global hierarchy, so it has no
    parent to propagate to and ``app.log`` never receives a copy of the lines
    the registro shows.
    """
    logger = logging.Logger("qtrequestory.ui.sync_format", logging.DEBUG)
    logger.propagate = False
    handler = _Capture()
    logger.addHandler(handler)
    return LoggingSink(logger), handler


_SINK, _CAPTURE = _build_sink()
#: The sink and its handler are shared state; rendering is serialised so two
#: threads cannot read each other's line. In practice only the GUI thread
#: renders, but a silent cross-thread mix-up would be very hard to see.
_LOCK = threading.Lock()


def message(ev: Event) -> str | None:
    """The ``sync.log`` wording of ``ev``, or None when it is not logged.

    ``FileStarted``/``FileProgress``/``FileSkipped``/``SyncStarted``/
    ``SyncFinished`` deliberately produce nothing: the core considers them too
    chatty for a log file, and the registro is that log file.
    """
    with _LOCK:
        _CAPTURE.line = None
        _SINK(ev)
        return _CAPTURE.line


def log_line(ev: Event) -> str | None:
    """:func:`message` with the ``[YYYY-MM-DD HH:MM:SS]`` prefix of ``sync.log``."""
    text = message(ev)
    if text is None:
        return None
    stamp = datetime.fromtimestamp(ev.ts).strftime(TIMESTAMP_FORMAT)
    return f"[{stamp}] {text}"


def status_text(snap: ProgressSnapshot) -> str | None:
    """The status-bar line of a running sync, or None when there is none yet.

    "Sincronizzazione coll 3/48…" while downloading, "Indicizzazione 2/5…"
    while indexing. Nothing before the first file: "0/48" says nothing the
    strip does not already say better.
    """
    if snap.file_index <= 0 or snap.n_files <= 0:
        return None
    if snap.phase == PHASE_INDEX:
        return strings.SYNC_STATUS_INDEXING.format(i=snap.file_index, n=snap.n_files)
    if snap.env:
        return strings.SYNC_STATUS_PROGRESS.format(env=snap.env, i=snap.file_index,
                                                   n=snap.n_files)
    return None


# ----------------------------------------------------------------- numbers ---

def _decimal(value: float) -> str:
    """One decimal, Italian comma, and no pointless ",0" ("41", "1,5")."""
    text = f"{value:.1f}".replace(".", ",")
    return text[:-2] if text.endswith(",0") else text


def format_size(n_bytes: float, *, whole_kb: bool = False) -> str:
    """"512 B" / "2,5 KB" / "80,4 MB" / "1,5 GB" (DESIGN-ui wording).

    **The only size formatter in the UI.** There used to be three, with three
    different roundings, so one click showed the same body as "1.434 KB" in the
    Ricerca table and "1,4 MB" in the status bar — the user has no way to know
    those are the same number.

    ``whole_kb`` is what the results table needs and nothing else does: whole
    kilobytes all the way up, rounded UP so a 300-byte body never reads "0 KB",
    with the Italian thousands separator. One unit down the whole column is
    what makes rows comparable at a glance; the sort is on the raw byte count
    either way.

    The readable unit is the core's :func:`~qtrequestory.core.events.format_size`
    — the same function ``sync.log`` is written with — so a registro line and
    a card never disagree about the same file.
    """
    if whole_kb:
        kb = -(-int(max(0, n_bytes)) // KB)  # ceil, so a small body is 1 KB
        return strings.SYNC_UNIT_KB.format(n=f"{kb:,}".replace(",", "."))
    return core_format_size(n_bytes)


def format_rate(bytes_per_second: float | None) -> str:
    """"8,2 MB/s"; an unknown rate is shown as nothing at all."""
    if bytes_per_second is None:
        return ""
    return strings.SYNC_UNIT_RATE.format(size=format_size(bytes_per_second))


def format_eta(seconds: float | None) -> str:
    """"circa 2 min rimanenti", rounded so it never looks like a measurement.

    Below a minute it is rounded to five seconds (and never to zero: "circa
    0 s" would be a countdown, and this is an estimate).
    """
    if seconds is None or seconds < 0:
        return ""
    if seconds < 60:
        return strings.SYNC_ETA_SECONDS.format(n=max(5, round(seconds / 5) * 5))
    if seconds < 3600:
        return strings.SYNC_ETA_MINUTES.format(n=max(1, round(seconds / 60)))
    return strings.SYNC_ETA_HOURS.format(n=_decimal(seconds / 3600))


def format_when(moment: datetime | None, *, now: datetime | None = None) -> str:
    """"oggi 11:23" / "ieri 15:48" / "03/09/2026 08:05" / "mai".

    ``now`` is injectable so the wording can be asserted without waiting for
    midnight.
    """
    if moment is None:
        return strings.SYNC_WHEN_NEVER
    reference = now if now is not None else datetime.now()
    days = (reference.date() - moment.date()).days
    clock = moment.strftime("%H:%M")
    if days == 0:
        return strings.SYNC_WHEN_TODAY.format(time=clock)
    if days == 1:
        return strings.SYNC_WHEN_YESTERDAY.format(time=clock)
    return strings.SYNC_WHEN_OLDER.format(date=moment.strftime("%d/%m/%Y"), time=clock)


def format_days(n: int) -> str:
    """"1 giorno" / "68 giorni"."""
    return strings.SYNC_DAYS_ONE if n == 1 else strings.SYNC_DAYS.format(n=n)


def auto_title(task: TaskStatus | None) -> str:
    """The auto-sync card's title; ``None`` = status not known yet."""
    if task is None:
        return strings.SYNC_AUTO_TITLE
    return strings.SYNC_AUTO_TITLE_ON if task.registered else strings.SYNC_AUTO_TITLE_OFF


def format_task_status(task: TaskStatus, schedule: ScheduleSettings) -> str:
    """The muted line under the auto-sync title: schedule, next run, last outcome.

    ``schedule`` is the saved configuration rather than anything read back from
    the task (``TaskStatus`` carries no trigger): the same sentence is what
    Impostazioni shows, and describing a schedule the user did not choose would
    be worse than saying nothing. The next run and the last one are the task's.
    """
    if not task.registered:
        return strings.SYNC_AUTO_OFF_HINT
    parts = [schedule_sentence(schedule)]
    if task.next_run:
        parts.append(strings.SYNC_AUTO_NEXT.format(next=task.next_run))
    if task.last_run:
        result = task.last_result if task.last_result is not None else "—"
        parts.append(strings.SYNC_AUTO_LAST.format(last=task.last_run, result=result))
    else:
        parts.append(strings.SYNC_AUTO_LAST_NONE)
    return strings.SYNC_AUTO_SEP.join(parts)


# ------------------------------------------------------------ the strip ---

@dataclass(frozen=True)
class StripTexts:
    """The four values the progress strip paints, derived in one place.

    Computing them here rather than in the widget keeps the wording, the
    rounding and the "hide the ETA when it is a guess" rule under test without
    a ``QApplication``. ``label`` is empty when the snapshot has nothing new to
    say about *what* is running — the page then leaves whatever it was showing
    ("Avvio…", "Annullamento…") alone.
    """

    label: str
    totals: str
    rate: str
    percent: int


def strip_texts(snap: ProgressSnapshot) -> StripTexts:
    """Snapshot -> the four strings/numbers of the progress strip."""
    if snap.phase == PHASE_INDEX:
        return StripTexts(
            label=(strings.SYNC_PROGRESS_INDEXING_FILE.format(name=snap.name) if snap.name
                   else strings.SYNC_PROGRESS_INDEXING),
            totals=strings.SYNC_PROGRESS_COUNT.format(i=snap.file_index, n=snap.n_files),
            rate="",  # scanning files has no byte totals to measure against
            percent=0,
        )
    if snap.name:
        label = strings.SYNC_PROGRESS_FILE.format(name=snap.name, size=format_size(snap.file_size))
    elif snap.env:
        label = strings.SYNC_PROGRESS_ENV
    else:
        label = ""
    return StripTexts(
        label=label,
        totals=strings.SYNC_PROGRESS_TOTALS.format(
            i=snap.file_index, n=snap.n_files,
            done=format_size(snap.bytes_done), total=format_size(snap.bytes_total)),
        rate=_rate_text(snap),
        percent=snap.file_percent,
    )


def _rate_text(snap: ProgressSnapshot) -> str:
    """"8,2 MB/s · circa 2 min rimanenti", or just the rate, or nothing."""
    rate = format_rate(snap.rate_bps)
    if not rate:
        return ""
    eta = format_eta(snap.eta_s)
    if not eta:
        return strings.SYNC_PROGRESS_RATE.format(rate=rate)
    return strings.SYNC_PROGRESS_RATE_ETA.format(rate=rate, eta=eta)


# ------------------------------------------------------- page sentences ---

#: Dates listed by name in a coverage banner before "e altri N".
MISSING_LISTED = 5


def pending_days_text(pending: Mapping[str, Sequence[date]]) -> str:
    """The warn banner: days with calls still on the server but not local.

    One sentence per environment, naming the dates; "" when there is none.
    The next sync downloads them (the banner carries the button).
    """
    return _days_text(pending, strings.SYNC_PENDING_ONE, strings.SYNC_PENDING_MANY)


def lost_days_text(lost: Mapping[str, Sequence[date]]) -> str:
    """The bad banner: days the server purged before they were downloaded."""
    return _days_text(lost, strings.SYNC_LOST_ONE, strings.SYNC_LOST_MANY)


def _days_text(by_env: Mapping[str, Sequence[date]], one: str, many: str) -> str:
    lines = []
    for env, days in by_env.items():
        if not days:
            continue
        listed = [d.strftime("%d/%m/%Y") for d in sorted(days)[:MISSING_LISTED]]
        dates = strings.SYNC_MISSING_DATES_SEP.join(listed)
        if len(days) > MISSING_LISTED:
            dates += strings.SYNC_MISSING_MORE.format(n=len(days) - MISSING_LISTED)
        lines.append(one.format(env=env, dates=dates) if len(days) == 1
                     else many.format(env=env, n=len(days), dates=dates))
    return " ".join(lines)


@dataclass(frozen=True)
class RunOutcome:
    """How a run ended: the message, its tone, and the word for the registro header."""

    text: str
    tone: str
    log: str

    @property
    def expand_log(self) -> bool:
        """The run itself failed: open the registro so the user sees why.

        Failed files open it as they happen (the page watches ``FileFailed``);
        an unreachable environment does not — off the VPN that is the normal
        state, and the final message already names it.
        """
        return self.log == strings.SYNC_LOG_FAILED


def run_outcome(exit_code: int, results: Mapping[str, tuple[str, int]], *,
                dry_run: bool = False, skipped: bool = False,
                importing: bool = False) -> RunOutcome:
    """"Sincronizzazione completata" only when every environment is ok/fresh.

    ``results`` maps each environment of the run to ``(EnvResult.status,
    failed)``. Anything else is named: "Completata · svil non raggiungibile",
    in warn tone — the old "completata" next to an unreachable environment read
    as if everything had been fetched. ``skipped``: the core found the lock
    held and ran nothing (``JobReport.sync is None``) — the scheduled task's,
    or, with ``importing``, this window's own import (which copies under it).
    """
    if skipped:
        if importing:
            return RunOutcome(strings.SYNC_SKIPPED_IMPORT, "neutral", strings.SYNC_LOG_SKIPPED)
        return RunOutcome(strings.SYNC_LOCK_HELD, "neutral", strings.SYNC_LOG_SKIPPED)
    if exit_code == 3:
        return RunOutcome(strings.SYNC_CANCELLED, "neutral", strings.SYNC_LOG_CANCELLED)
    if exit_code == 2:
        return RunOutcome(strings.SYNC_DONE_UNREACHABLE, "warn", strings.SYNC_LOG_WARNINGS)
    details = []
    for env, (status, failed) in results.items():
        if status == "unreachable":
            details.append(strings.SYNC_DETAIL_UNREACHABLE.format(env=env))
        elif failed == 1:
            details.append(strings.SYNC_DETAIL_ERROR_ONE.format(env=env))
        elif failed:
            details.append(strings.SYNC_DETAIL_ERRORS.format(env=env, n=failed))
    if details:
        text = strings.SYNC_DONE_PARTIAL.format(details=strings.SYNC_DETAIL_SEP.join(details))
        return RunOutcome(text, "warn", strings.SYNC_LOG_WARNINGS)
    text = strings.SYNC_DONE_DRY_RUN if dry_run else strings.SYNC_DONE
    return RunOutcome(text, "ok", strings.SYNC_LOG_DONE)


def log_header(when: str | None, outcome: str | None) -> str:
    """"Registro dell'ultima esecuzione · 11:24 · completata"; parts may be missing."""
    text = strings.SYNC_LOG_HEADER
    for part in (when, outcome):
        if part:
            text += strings.SYNC_LOG_HEADER_PART.format(part=part)
    return text


_STAMP_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]")


def last_log_time(lines: Sequence[str], *, now: datetime | None = None) -> str | None:
    """"oggi 09:03" from the last timestamped line of ``sync.log``, or None."""
    for line in reversed(lines):
        match = _STAMP_RE.match(line)
        if match:
            moment = datetime.strptime(match.group(1), TIMESTAMP_FORMAT)
            return format_when(moment, now=now)
    return None
