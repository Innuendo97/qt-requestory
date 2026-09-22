"""The automatic synchronisation schedule, in one Italian sentence.

Two pages describe the same four settings: the Impostazioni form shows what the
user is about to save, the Sincronizzazione page shows what is registered. If
each built its own wording they would drift apart the first time one of them
changed — and a status line that describes a schedule the task does not have is
worse than no status line at all, because the server keeps only about a day of
logs and the user trusts what they read here.

Pure Python: no Qt, no core imports beyond the ``ScheduleSettings`` dataclass,
so the arithmetic (when does the retry window actually end?) is unit-tested
without a ``QApplication``.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import ScheduleSettings, parse_hhmm

__all__ = ["schedule_sentence"]

#: Shown when ``start_time`` cannot be parsed. The same value as
#: ``ScheduleSettings().start_time`` and ``scheduler.DEFAULT_START_TIME``: what
#: the task would actually run at.
FALLBACK_START = time(9, 0)
TIME_FORMAT = "%H:%M"


def schedule_sentence(schedule: ScheduleSettings) -> str:
    """``"Ogni giorno alle 09:00, riprova ogni ora fino alle 18:00, e al login."``

    An unparsable ``start_time`` (a hand-edited ``config.json``) falls back to
    the default instead of raising: ``config.validate`` is what reports it, and
    neither page may go blank over a bad character.
    """
    start = parse_hhmm(schedule.start_time) or FALLBACK_START
    parts = [strings.SYNC_SCHEDULE_DAILY.format(time=start.strftime(TIME_FORMAT))]
    if schedule.repeat_for_h > 0:
        template = (
            strings.SYNC_SCHEDULE_REPEAT_HOURLY if schedule.repeat_every_h == 1
            else strings.SYNC_SCHEDULE_REPEAT_EVERY
        )
        parts.append(template.format(n=schedule.repeat_every_h,
                                     end=_end_of_window(start, schedule.repeat_for_h)))
    if schedule.run_at_logon:
        parts.append(strings.SYNC_SCHEDULE_LOGON)
    return "".join(parts) + strings.SYNC_SCHEDULE_STOP


def _end_of_window(start: time, hours: int) -> str:
    """When the last attempt can still start, said in a way that cannot mislead.

    ``20:00`` plus nine hours is ``05:00`` — of the next day. Left as a bare
    time it reads as "this morning", i.e. a window that already closed.
    """
    end = datetime.combine(date.min, start) + timedelta(hours=hours)
    clock = end.strftime(TIME_FORMAT)
    if end.date() == date.min:
        return clock
    return strings.SYNC_SCHEDULE_END_NEXT_DAY.format(time=clock)
