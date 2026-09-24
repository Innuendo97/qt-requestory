"""Daily-file naming, local mirror listing and entry-name parsing.

The mirror keeps one file per environment and day at
``<root>/<env>/YYYY/MM/YYYYMMDD.txt``. Inside, every entry is announced by a
``### <name>.json`` header; ``parse_entry_name`` turns that ``<name>`` into
its parts (FDI, template key, call id). The parser is *total*: any string
yields an ``EntryName``, and ``well_formed`` records whether it had the
canonical ``UUID_KEY_ID`` shape. That way the index never drops an entry it
cannot fully understand — the user can still search it by template key.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

DAILY_NAME_RE = r"^(?P<day>\d{8})\.txt$"
# Canonical FDI (the request correlation_id). Applied AFTER lowercasing.
UUID_RE = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
# Trailing call id: 16 lowercase hex chars after the last underscore.
CALL_ID_RE = r"_([0-9a-f]{16})$"

_NO_FDI_PREFIX = "correlationId_vuoto_"

_daily_name = re.compile(DAILY_NAME_RE)
_uuid = re.compile(UUID_RE)
_call_id = re.compile(CALL_ID_RE)


# ------------------------------------------------------------- day / names ---

def day_from_name(name: str) -> date | None:
    """``'20260921.txt'`` -> ``date(2026, 9, 21)``; anything else (including
    ``.part`` files and impossible dates such as month 13) -> ``None``."""
    m = _daily_name.match(name)
    if m is None:
        return None
    try:
        return datetime.strptime(m.group("day"), "%Y%m%d").date()
    except ValueError:
        return None


def file_name(day: date) -> str:
    return f"{day:%Y%m%d}.txt"


def local_path(root: Path, env: str, day: date) -> Path:
    """``<root>/<env>/YYYY/MM/YYYYMMDD.txt``."""
    return Path(root) / env / f"{day:%Y}" / f"{day:%m}" / file_name(day)


def relative_path(env: str, day: date) -> str:
    """Same layout as ``local_path`` but as a portable string with forward
    slashes — this is what gets stored in the index (``files.rel_path``)."""
    return f"{env}/{day:%Y}/{day:%m}/{file_name(day)}"


# ----------------------------------------------------------- local listing ---

@dataclass(frozen=True)
class LocalDailyFile:
    env: str
    day: date
    path: Path
    size: int
    mtime_ns: int


def list_local_daily_files(root: Path, env: str) -> list[LocalDailyFile]:
    """All mirrored daily files of ``env``, newest first.

    Only ``YYYY/MM/YYYYMMDD.txt`` at the expected depth count; ``.part``
    leftovers and any other junk are ignored. A missing env (or root) folder
    simply yields ``[]`` — the mirror may not have been synced yet.
    """
    env_dir = Path(root) / env
    if not env_dir.is_dir():
        return []
    found: list[LocalDailyFile] = []
    for path in env_dir.glob("*/*/*.txt"):
        day = day_from_name(path.name)
        if day is None or not path.is_file():
            continue
        st = path.stat()
        found.append(LocalDailyFile(env, day, path, st.st_size, st.st_mtime_ns))
    found.sort(key=lambda f: f.day, reverse=True)
    return found


def count_local_files(root: Path) -> int:
    """Number of mirrored daily files across EVERY env folder under ``root``.

    Used by the first-run wizard to size the initial index build before the
    user has picked environments. Dot-folders (``.qtrequestory``, where the
    index itself lives) are skipped; a missing root counts as 0.
    """
    root = Path(root)
    if not root.is_dir():
        return 0
    return sum(
        len(list_local_daily_files(root, child.name))
        for child in root.iterdir()
        if child.is_dir() and not child.name.startswith(".")
    )


# -------------------------------------------------------------- coverage ---

@dataclass(frozen=True)
class CoverageDays:
    """What each day of one environment's coverage window is, as consumed by
    the search coverage warning and the sync-page coverage calendar.

    ``present`` is every local daily file with size > 0 (unfiltered);
    ``empty`` every local 0-byte file (a day the server published without
    traffic) that the server never listed non-empty. The three tuples only
    cover the window and days without a local file, or with a 0-byte one:

    * ``pending``: still listed non-empty by the server (can be downloaded,
      also over a 0-byte placeholder);
    * ``lost``: listed non-empty once, no longer listed (purged by the server
      before it was downloaded);
    * ``unknown``: a weekday on or after ``first_local`` that no listing ever
      showed non-empty (before the tracking began, nothing to say about it).

    ``first_local`` is the oldest local day (either kind), or ``None``.
    """
    present: frozenset[date]
    empty: frozenset[date] = frozenset()
    pending: tuple[date, ...] = ()
    lost: tuple[date, ...] = ()
    unknown: tuple[date, ...] = ()
    first_local: date | None = None

    @property
    def missing(self) -> tuple[date, ...]:
        """The days that need attention: ``pending`` plus ``lost``, ascending."""
        return tuple(sorted(self.pending + self.lost))


def classify_days(
    local_sizes: Mapping[date, int],
    listed_nonempty: Iterable[date],
    seen_nonempty: Iterable[date],
    days: int,
    today: date,
) -> CoverageDays:
    """Classify the ``days`` days before ``today`` for one environment.

    ``local_sizes`` maps every local daily file's day to its size;
    ``listed_nonempty`` / ``seen_nonempty`` come from the sync state. The
    window is ``[today - days + 1, today - 1]``: today's file is only
    complete after the evening compaction, so it is never judged. Weekends
    are classified like any other day: a weekend with traffic that is not
    local is ``pending`` or ``lost``. A local 0-byte day the server lists
    non-empty is ``pending`` (``lost`` once no longer listed). A day before
    ``first_local`` is only reported when the server listed it non-empty.
    """
    present = frozenset(d for d, size in local_sizes.items() if size > 0)
    first_local = min(local_sizes) if local_sizes else None
    listed = set(listed_nonempty)
    seen = set(seen_nonempty) | listed
    # A 0-byte placeholder the server lists (or listed) non-empty is not a
    # quiet day: it is pending (or lost), never "empty".
    empty = frozenset(d for d, size in local_sizes.items() if size == 0 and d not in seen)
    pending: list[date] = []
    lost: list[date] = []
    unknown: list[date] = []
    day = today - timedelta(days=days - 1)
    end = today - timedelta(days=1)
    while day <= end:
        if day not in present:
            if day in listed:
                pending.append(day)
            elif day in seen:
                lost.append(day)
            elif day in empty:
                pass
            elif first_local is not None and day >= first_local and day.weekday() < 5:
                unknown.append(day)
        day += timedelta(days=1)
    return CoverageDays(present=present, empty=empty, pending=tuple(pending), lost=tuple(lost),
                        unknown=tuple(unknown), first_local=first_local)


# -------------------------------------------------------- entry name parse ---

@dataclass(frozen=True)
class EntryName:
    raw: str
    fdi: str | None
    template_key: str
    call_id: str | None
    well_formed: bool


def parse_entry_name(raw: str) -> EntryName:
    """Split ``<fdi>_<TEMPLATE_KEY>_<call_id>`` deterministically.

    Rules (in this order):
    1. a trailing ``_<16 lowercase hex>`` is the ``call_id`` and is stripped;
    2. a remainder starting with ``correlationId_vuoto_`` has no FDI, the rest
       is the key;
    3. otherwise split on the FIRST underscore: left (lowercased) is the FDI,
       right is the key — template keys may contain underscores and even start
       with digits (``2_SOME_KEY_...``), the FDI token never contains one;
    4. no underscore at all: no FDI, the whole remainder is the key.

    ``well_formed`` is True only for a canonical UUID FDI plus a call id.
    Test-suffixed FDIs (``<uuid>-t15``) keep their token but are not canonical.
    """
    call_id: str | None = None
    remainder = raw
    m = _call_id.search(raw)
    if m is not None:
        call_id = m.group(1)
        remainder = raw[: m.start()]

    fdi: str | None
    if remainder.startswith(_NO_FDI_PREFIX):
        fdi = None
        template_key = remainder[len(_NO_FDI_PREFIX):]
    elif "_" in remainder:
        left, template_key = remainder.split("_", 1)
        fdi = left.lower()
    else:
        fdi = None
        template_key = remainder

    well_formed = fdi is not None and _uuid.match(fdi) is not None and call_id is not None
    return EntryName(raw=raw, fdi=fdi, template_key=template_key, call_id=call_id, well_formed=well_formed)
