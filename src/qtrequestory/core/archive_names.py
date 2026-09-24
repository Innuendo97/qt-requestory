"""What a log file's path says about it: its day and its environment.

Colleagues keep old logs in any layout (``svil/20260922.txt``,
``2026/09/coll/22.txt``, ``coll_22-09-2026.txt``...). The importer
(``core/archive.py``) reads the path elements nearest first — the file name,
then its folders up to the scanned root — and asks two questions here.

**Day.** Accepted tokens: ``YYYYMMDD``, ``YYYY-MM-DD`` and Italian
``DDMMYYYY`` / ``DD-MM-YYYY``, with ``-``, ``_`` or ``.`` as separator (the
same one twice), plus the ``YYYY/MM/DD.txt`` folder layout. No digit may be
glued to a token (``120260922`` is not a date), and only real dates between
2020-01-01 and tomorrow count, which is what makes the Italian reading safe:
an 8-digit run that reads as a valid date both ways cannot occur in that
range. An element holding two different dates is ambiguous and the file is
skipped rather than guessed.

**Environment.** A configured environment name, whatever it is, matched
case-insensitively as a whole word — nothing alphanumeric before it, no
letter after it (``prod2`` is ``prod``, ``production`` is not) — in an element
whose date tokens were removed first (``coll20260922`` is ``coll``). The
nearest element that names any environment decides; the longest name wins a
tie inside it; a tie between names of equal length is left to the user.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date, timedelta

DATE_MIN = date(2020, 1, 1)
NO_DATE = "nessuna data nel nome"
AMBIGUOUS = "data ambigua"

_SEP_YMD = re.compile(r"(?<!\d)(\d{4})([-_.])(\d{2})\2(\d{2})(?!\d)")
_SEP_DMY = re.compile(r"(?<!\d)(\d{2})([-_.])(\d{2})\2(\d{4})(?!\d)")
_EIGHT = re.compile(r"(?<!\d)(\d{8})(?!\d)")
_DAY_FILE = re.compile(r"^(\d{1,2})(\.[^.]*)?$")
_MONTH_DIR = re.compile(r"^\d{1,2}$")
_YEAR_DIR = re.compile(r"^\d{4}$")


def _real(year: int, month: int, day: int, today: date) -> date | None:
    try:
        d = date(year, month, day)
    except ValueError:
        return None
    return d if DATE_MIN <= d <= today + timedelta(days=1) else None


def element_dates(text: str, *, today: date) -> set[date]:
    """Every valid date one path element holds (each reading of each token)."""
    found: set[date] = set()
    for m in _SEP_YMD.finditer(text):
        found.add(_real(int(m[1]), int(m[3]), int(m[4]), today))
    for m in _SEP_DMY.finditer(text):
        found.add(_real(int(m[4]), int(m[3]), int(m[1]), today))
    for m in _EIGHT.finditer(text):
        t = m[1]
        found.add(_real(int(t[:4]), int(t[4:6]), int(t[6:]), today))  # YYYYMMDD
        found.add(_real(int(t[4:]), int(t[2:4]), int(t[:2]), today))  # DDMMYYYY
    found.discard(None)
    return found  # type: ignore[return-value]


def strip_dates(text: str) -> str:
    """``text`` with every date-shaped token replaced by one space."""
    for rx in (_SEP_YMD, _SEP_DMY, _EIGHT):
        text = rx.sub(" ", text)
    return text


def _year_month_day(parts: Sequence[str], today: date) -> date | None:
    """``.../YYYY/MM/DD.txt``: ``parts`` is file name, month dir, year dir, ..."""
    if len(parts) < 3:
        return None
    m = _DAY_FILE.match(parts[0])
    if m is None or not _MONTH_DIR.match(parts[1]) or not _YEAR_DIR.match(parts[2]):
        return None
    return _real(int(parts[2]), int(parts[1]), int(m[1]), today)


def day_from_parts(parts: Sequence[str], *, today: date) -> tuple[date | None, str | None]:
    """``(day, None)`` or ``(None, reason)``; ``parts`` is nearest first
    (file name, parent folder, ...).

    The first element holding a date decides; two different dates in it make
    the file ambiguous. The ``YYYY/MM/DD.txt`` layout is tried when the file
    name itself has no date token.
    """
    for i, part in enumerate(parts):
        dates = element_dates(part, today=today)
        if len(dates) > 1:
            return None, AMBIGUOUS
        if dates:
            return next(iter(dates)), None
        if i == 0:
            d = _year_month_day(parts, today)
            if d is not None:
                return d, None
    return None, NO_DATE


def _env_pattern(name: str) -> re.Pattern[str]:
    return re.compile(r"(?<![a-z0-9])" + re.escape(name.lower()) + r"(?![a-z])")


def env_from_parts(parts: Sequence[str], env_names: Sequence[str]) -> str | None:
    """The configured env the path names, or ``None`` (none, or a tie).

    ``parts`` is nearest first. Returns the name exactly as configured.
    """
    patterns = [(name, _env_pattern(name)) for name in env_names]
    for part in parts:
        text = strip_dates(part).lower()
        hits = {name for name, rx in patterns if rx.search(text)}
        if not hits:
            continue
        longest = max(len(n) for n in hits)
        best = [n for n in hits if len(n) == longest]
        return best[0] if len(best) == 1 else None
    return None
