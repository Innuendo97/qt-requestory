"""Parse the nginx autoindex page of one environment.

The page is plain HTML with one ``<a href="...">`` per file followed by the
modification time and the size in bytes, e.g.::

    <a href="20260921.txt">20260921.txt</a>   21-Sep-2026 18:30   64487564

We only need two things from it: the daily files (name, day, size — size 0
means "nothing that day", the sync skips it) and how many loose ``.json``
files are still waiting to be compacted (reported to the user, never
downloaded). Only the ``href`` is trusted: the visible text is truncated by
nginx (``..&gt;``) for long names.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from .daily import day_from_name

DAILY_HREF_RE = r'<a href="(?P<day>\d{8})\.txt">[^<]*</a>\s+(?P<date>\S+ \S+)\s+(?P<size>\d+)'
LOOSE_HREF_RE = r'<a href="[^"]+\.json">'

_daily_href = re.compile(DAILY_HREF_RE)
_loose_href = re.compile(LOOSE_HREF_RE)


@dataclass(frozen=True)
class RemoteDailyFile:
    name: str
    day: date
    size: int


@dataclass(frozen=True)
class RemoteIndex:
    daily: tuple[RemoteDailyFile, ...]   # newest first
    loose_count: int


def parse_autoindex(html: str) -> RemoteIndex:
    """Extract daily files (newest first) and the loose ``.json`` count.

    Anything that is not a ``\\d{8}.txt`` href is ignored (``../``, junk); a
    daily href whose digits are not a real date is skipped as well.
    """
    daily: list[RemoteDailyFile] = []
    for m in _daily_href.finditer(html):
        name = m.group("day") + ".txt"
        day = day_from_name(name)
        if day is None:
            continue
        daily.append(RemoteDailyFile(name, day, int(m.group("size"))))
    daily.sort(key=lambda f: f.day, reverse=True)
    return RemoteIndex(daily=tuple(daily), loose_count=len(_loose_href.findall(html)))
