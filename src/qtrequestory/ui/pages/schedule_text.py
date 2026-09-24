"""The automatic synchronisation schedule, in one Italian sentence.

Two pages describe the same four settings: the Impostazioni form shows what the
user is about to save, the Sincronizzazione page shows what is registered. If
each built its own wording they would drift apart the first time one of them
changed — and a status line that describes a schedule the task does not have is
worse than no status line at all: the user trusts what they read here, and
days the task never fetched are lost at the server's next manual purge.

Pure Python: no Qt, no core imports beyond the ``ScheduleSettings`` dataclass,
so the arithmetic (when does the retry window actually end?) is unit-tested
without a ``QApplication``.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import ScheduleSettings, parse_hhmm, sanitised_schedule

__all__ = ["schedule_sentence"]

TIME_FORMAT = "%H:%M"


def schedule_sentence(schedule: ScheduleSettings) -> str:
    """``"Ogni giorno alle 09:00, riprova ogni ora fino alle 18:00, e al login"``

    Without the final full stop: the Sincronizzazione status line puts the
    sentence between ``·`` separators, where a full stop mid-line reads like a
    mistake, while Impostazioni and the wizard close it themselves through
    their own string. Punctuation belongs to whoever frames the sentence.

    What is described is what the task will really do: the values go through
    ``config.sanitised_schedule`` first — the same repair ``spec_from_config``
    applies — so a hand-edited ``"repeat_every_h": 0`` reads as the hourly retry
    it will actually become, and no page goes blank over a bad character.
    """
    runnable = sanitised_schedule(schedule)
    start = parse_hhmm(runnable.start_time) or time(9, 0)
    parts = [strings.SYNC_SCHEDULE_DAILY.format(time=start.strftime(TIME_FORMAT))]
    if runnable.repeat_for_h > 0:
        template = (
            strings.SYNC_SCHEDULE_REPEAT_HOURLY if runnable.repeat_every_h == 1
            else strings.SYNC_SCHEDULE_REPEAT_EVERY
        )
        parts.append(template.format(n=runnable.repeat_every_h,
                                     end=_end_of_window(start, runnable.repeat_for_h)))
    if runnable.run_at_logon:
        parts.append(strings.SYNC_SCHEDULE_LOGON)
    return "".join(parts)


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
