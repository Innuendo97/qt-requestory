"""A case's call replaced by another logged one (``OfficinaService.replace_call``).

Stdlib only. What changes: ``payload.json`` (the new call's body),
``source_fdi`` and one history line in ``caso.json``. What stays: the TARGET,
the AS-IS, every TO-BE and the review keys — the case keeps its work, only the
request it sends is new. The payload it replaces is kept next to it as
``payload.<YYYYMMDD-HHMMSS>.json``; ``payload.original.json`` stays the very
first payload the case had (written now if no edit ever wrote it).

The call the case already has (same FDI, same payload) changes nothing: no
backup, no history line, so no "AS-IS older than the call" strip either.

Ordered so a refusal writes nothing: ``caso.json`` is read (strict) before any
file moves, and the backups are written before the new payload.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from qtrequestory.officina.model_case import Case, case_write_lock, read_caso_strict
from qtrequestory.officina.model_io import (
    UnreadableJsonError,
    atomic_copy_text,
    read_json_object,
    write_json_atomic,
)

__all__ = ["HISTORY_KIND", "replace_payload"]

#: ``kind`` of the ``caso.json`` history entry a replacement writes (the case
#: view reads it to say that the AS-IS was made with the previous call).
HISTORY_KIND = "chiamata_sostituita"


def _backup_name(case_dir: Path, when: datetime) -> Path:
    stem = f"payload.{when:%Y%m%d-%H%M%S}"
    path, n = case_dir / f"{stem}.json", 1
    while path.exists():
        n += 1
        path = case_dir / f"{stem}-{n}.json"
    return path


def replace_payload(case: Case, payload: dict, fdi: str | None, when: datetime) -> Case:
    """Write ``payload`` as the case's payload and ``fdi`` as its source FDI,
    keeping the previous payload (see module doc). ``UnreadableJsonError``
    (a ``ValueError``) and nothing written for an unreadable ``caso.json``."""
    if case.load_error:
        raise UnreadableJsonError(
            f"caso.json non è leggibile ({case.load_error}): la chiamata non viene sostituita")
    case_dir = case.folder
    with case_write_lock(case_dir):
        raw = read_caso_strict(case_dir)  # refuse BEFORE anything moves
        current = case_dir / "payload.json"
        if fdi == case.source_fdi and read_json_object(current) == payload:
            return case  # the same call: nothing to replace
        if current.exists():
            original = case_dir / "payload.original.json"
            if not original.exists():
                atomic_copy_text(current, original)
            atomic_copy_text(current, _backup_name(case_dir, when))
        write_json_atomic(current, payload)
        old = case.source_fdi or "—"
        history = raw.get("history")
        if not isinstance(history, list):
            history = []
        history.append({"at": datetime.now().isoformat(), "kind": HISTORY_KIND,
                        "note": f"chiamata sostituita: {old} → {fdi or '—'}"})
        raw["history"] = history
        raw["source_fdi"] = fdi
        write_json_atomic(case_dir / "caso.json", raw)
    case.source_fdi = fdi
    return case
