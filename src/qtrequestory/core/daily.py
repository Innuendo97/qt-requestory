"""Entry-name parsing (STUB written by Task 4 — to be merged with Task 2's full module).

Only ``UUID_RE``, ``CALL_ID_RE``, ``EntryName`` and ``parse_entry_name`` live
here, exactly per the spec in ``docs/DESIGN-core.md`` §core/daily.py. The
scanner needs them; the day/file-name helpers belong to Task 2.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Canonical lowercase UUID: the FDI is the request correlation_id, never dossier.id.
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
# Trailing call id: 16 lowercase hex chars after the last underscore.
CALL_ID_RE = re.compile(r"_(?P<call_id>[0-9a-f]{16})$")

_VUOTO_PREFIX = "correlationId_vuoto_"


@dataclass(frozen=True)
class EntryName:
    raw: str
    fdi: str | None
    template_key: str
    call_id: str | None
    well_formed: bool


def parse_entry_name(raw: str) -> EntryName:
    """Split ``<fdi>_<TEMPLATE_KEY>_<call_id>`` deterministically; never raises.

    Rules: strip a trailing ``_[0-9a-f]{16}`` as ``call_id``; a remainder starting
    with ``correlationId_vuoto_`` has no FDI; otherwise split on the FIRST ``_``
    (template keys contain underscores, UUIDs never do). ``well_formed`` is true
    only for a canonical UUID FDI *and* a call id, so test shapes such as
    ``<uuid>-t15_...`` are kept but flagged.
    """
    rest = raw
    call_id: str | None = None
    m = CALL_ID_RE.search(rest)
    if m:
        call_id = m.group("call_id")
        rest = rest[: m.start()]

    fdi: str | None
    if rest.startswith(_VUOTO_PREFIX):
        fdi = None
        template_key = rest[len(_VUOTO_PREFIX):]
    elif "_" in rest:
        left, template_key = rest.split("_", 1)
        fdi = left.lower()
    else:
        fdi = None
        template_key = rest

    well_formed = fdi is not None and UUID_RE.match(fdi) is not None and call_id is not None
    return EntryName(raw=raw, fdi=fdi, template_key=template_key, call_id=call_id, well_formed=well_formed)
