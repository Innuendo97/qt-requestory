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

That one import is the documented exception to "the UI only sees
``ui/contracts.py``" (Task 11 brief: *"ok to import ``LoggingSink`` text style
but produce str"*); nothing else from ``core`` is touched here.

**The numbers.** Sizes, rates, ETAs and "oggi 11:23" — Italian, with a decimal
comma, and rounded the way DESIGN-ui shows them ("41 MB", "1,5 GB",
"8,2 MB/s", "circa 2 min rimanenti").
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime

from qtrequestory.core.events import LoggingSink  # see the module docstring
from qtrequestory.ui import strings
from qtrequestory.ui.contracts import Event, ScheduleSettings, TaskStatus
from qtrequestory.ui.pages.progress_model import PHASE_INDEX, ProgressSnapshot
from qtrequestory.ui.pages.schedule_text import schedule_sentence

__all__ = [
    "StripTexts", "format_eta", "format_rate", "format_size", "format_task_status",
    "format_when", "log_line", "message", "strip_texts",
]

KB = 1024
MB = 1024 * KB
GB = 1024 * MB

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
    """
    if whole_kb:
        kb = -(-int(max(0, n_bytes)) // 1024)  # ceil, so a small body is 1 KB
        return strings.SYNC_UNIT_KB.format(n=f"{kb:,}".replace(",", "."))
    n = max(0.0, float(n_bytes))
    if n < KB:
        return strings.SYNC_UNIT_B.format(n=int(n))
    if n < MB:
        return strings.SYNC_UNIT_KB.format(n=_decimal(n / KB))
    if n < GB:
        return strings.SYNC_UNIT_MB.format(n=_decimal(n / MB))
    return strings.SYNC_UNIT_GB.format(n=_decimal(n / GB))


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


def format_task_status(task: TaskStatus, schedule: ScheduleSettings) -> str:
    """The line under the auto-sync checkbox: active, schedule, next run, last outcome.

    ``schedule`` is the saved configuration rather than anything read back from
    the task: the same sentence is what Impostazioni shows, and describing a
    schedule the user did not choose would be worse than saying nothing.
    """
    if not task.registered:
        return strings.SYNC_AUTO_OFF
    parts = [strings.SYNC_AUTO_ON, schedule_sentence(schedule)]
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
        label = strings.SYNC_PROGRESS_FILE.format(
            env=snap.env, name=snap.name, size=format_size(snap.file_size))
    elif snap.env:
        label = strings.SYNC_PROGRESS_ENV.format(env=snap.env)
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
