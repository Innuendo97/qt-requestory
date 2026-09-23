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
# A daily row whose size column is human-readable (nginx's autoindex_exact_size
# off — "98K", "1.2M") instead of an exact byte count. DAILY_HREF_RE's \d+
# would silently match only the leading digits ("98K" -> 98), so every size
# comparison in sync.py would be wrong forever; this must be detected and
# refused instead of misread. Matched separately from DAILY_HREF_RE, which
# never matches these rows at all (the trailing letter is not \d).
ABBREVIATED_SIZE_RE = r'<a href="(?P<day>\d{8})\.txt">[^<]*</a>\s+\S+ \S+\s+(?P<size>\d+(?:\.\d+)?[KMGkmg])\b'

_daily_href = re.compile(DAILY_HREF_RE)
_loose_href = re.compile(LOOSE_HREF_RE)
_abbreviated_size = re.compile(ABBREVIATED_SIZE_RE)


class AutoindexFormatError(ValueError):
    """The server's autoindex shows human-readable sizes for at least one daily
    row (``autoindex_exact_size off`` in nginx) instead of exact byte counts.

    Every download decision in ``sync.py`` compares the remote size against
    what is on disk; deciding from a truncated size ("98K" read as 98) would
    corrupt the mirror silently and forever, so this must stop the sync of
    that environment rather than being read as a (wrong) number.
    """


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

    Raises ``AutoindexFormatError`` when any daily row's size column is
    abbreviated (``\\d+(\\.\\d+)?[KMGkmg]``) rather than an exact byte count —
    see ``ABBREVIATED_SIZE_RE``.
    """
    abbreviated = _abbreviated_size.search(html)
    if abbreviated is not None:
        raise AutoindexFormatError(
            f"dimensione abbreviata nell'autoindex: {abbreviated.group('day')}.txt = {abbreviated.group('size')}"
        )
    daily: list[RemoteDailyFile] = []
    for m in _daily_href.finditer(html):
        name = m.group("day") + ".txt"
        day = day_from_name(name)
        if day is None:
            continue
        daily.append(RemoteDailyFile(name, day, int(m.group("size"))))
    daily.sort(key=lambda f: f.day, reverse=True)
    return RemoteIndex(daily=tuple(daily), loose_count=len(_loose_href.findall(html)))
