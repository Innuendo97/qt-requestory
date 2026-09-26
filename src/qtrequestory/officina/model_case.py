"""The Officina case and its ``caso.json`` (``officina.model`` re-exports :class:`Case`).

Stdlib only. Loading is tolerant: an unreadable ``caso.json`` gives a
:class:`Case` with ``load_error`` set (and default values), a hand-edited
value that cannot be used is left out with a line in ``load_notes``. Every
WRITE of ``caso.json`` merges into what is on disk and therefore refuses an
unreadable file (:class:`~qtrequestory.officina.model_io.UnreadableJsonError`,
a ``ValueError``): a merge into ``{}`` would wipe env, headers and source FDI.

Every read-modify-write of one case's ``caso.json`` holds that case's
:func:`case_write_lock` (ruling R16): a worker saving the review and the main
thread saving the case never merge into each other's stale copy.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from qtrequestory.officina.model_io import (
    UnreadableJsonError,
    read_json_object,
    read_json_strict,
    write_json_atomic,
)
from qtrequestory.officina.model_review import Review, review_from_json, review_to_json
from qtrequestory.officina.model_versions import (
    Version,
    read_single_version,
    read_target,
    read_tobe_versions,
)

__all__ = ["Case"]

REOPENED_KEY = "reopened_after_acceptance"


@dataclass
class Case:
    id: str  # "<KEY>" or "<KEY>__<variant-slug>"
    key: str
    variant: str
    env: str
    headers: dict[str, str]  # case overrides (ordered)
    drop_postman_token: bool
    correlation: Literal["new", "source", "fixed"]
    correlation_value: str
    link_policy: Literal["remove", "keep_if_expired"]
    status: Literal["open", "accepted"]
    notes: str
    folder: Path
    load_error: str | None = None
    source_fdi: str | None = None
    #: The TO-BE number accepted ("Segna accettato"), None if none was.
    accepted_version: int | None = None
    #: A new AS-IS or TO-BE landed after the acceptance: the case went back
    #: to "open" and must be checked again (cleared by the next acceptance).
    reopened: bool = False
    #: What loading had to leave out of ``caso.json`` (e.g. a header whose
    #: value is null), for the user to see; the rest loaded normally.
    load_notes: list[str] = field(default_factory=list)
    #: Phase 2: profile, tolerances, marks, noise rules and the last summary
    #: (``model_review``). Written ONLY by ``Workspace.save_review`` (ruling R8):
    #: ``save_case`` never touches the review keys, so a stale instance saved
    #: by the editor cannot wipe newer marks or tolerances.
    review: Review = field(default_factory=Review)

    def target(self) -> Version | None:
        return read_target(self.folder)

    def asis(self) -> Version | None:
        return read_single_version(self.folder / "asis", "asis", kind="asis", number=0)

    def tobe_versions(self) -> list[Version]:
        return read_tobe_versions(self.folder / "tobe")

    def latest_tobe(self) -> Version | None:
        versions = self.tobe_versions()
        return versions[-1] if versions else None

    @property
    def history(self) -> list[dict]:
        """The ``caso.json`` ``history`` entries (e.g. AS-IS replace notes),
        read live from disk so callers never have to re-parse ``caso.json``
        themselves. Read-only: append via an AS-IS replace note, not here."""
        hist = read_json_object(self.folder / "caso.json").get("history", [])
        return hist if isinstance(hist, list) else []

    def mark_accepted(self) -> None:
        """Accepted AS OF the latest TO-BE (saved with ``Workspace.save_case``)."""
        latest = self.latest_tobe()
        self.status = "accepted"
        self.accepted_version = latest.number if latest is not None else None
        self.reopened = False

    def mark_open(self) -> None:
        self.status = "open"
        self.accepted_version = None
        self.reopened = False

    def acceptance_is_current(self) -> bool:
        """True when the case is accepted and the TO-BE accepted is still the latest."""
        if self.status != "accepted":
            return False
        latest = self.latest_tobe()
        return self.accepted_version == (latest.number if latest is not None else None)


def case_raw(case: Case) -> dict:
    return {
        "key": case.key, "variant": case.variant, "env": case.env,
        "headers": dict(case.headers),
        "drop_postman_token": case.drop_postman_token,
        "correlation": case.correlation, "correlation_value": case.correlation_value,
        "link_policy": case.link_policy,
        "status": case.status, "notes": case.notes,
        "source_fdi": case.source_fdi,
        "accepted_version": case.accepted_version,
        REOPENED_KEY: case.reopened,
    }


def headers_from(raw: object, where: str) -> tuple[dict[str, str], list[str]]:
    """``(headers, notes)`` from a JSON ``{name: value}``: a null value is
    left out with a note (never sent as the string "None")."""
    if not isinstance(raw, dict):
        return {}, []
    headers: dict[str, str] = {}
    notes: list[str] = []
    for name, value in raw.items():
        if value is None:
            notes.append(f"{where}: l'header «{name}» non ha valore (null) ed è stato ignorato")
        else:
            headers[str(name)] = str(value)
    return headers, notes


def load_case(case_dir: Path) -> Case:
    case_id = case_dir.name
    try:
        raw = read_json_strict(case_dir / "caso.json")
        headers, notes = headers_from(raw.get("headers"), "caso.json")
        source_fdi_raw = raw.get("source_fdi")
        accepted = raw.get("accepted_version")
        review = review_from_json(raw, notes)
        return Case(
            id=case_id,
            key=str(raw.get("key", case_id)),
            variant=str(raw.get("variant", "")),
            env=str(raw.get("env", "")),
            headers=headers,
            drop_postman_token=raw.get("drop_postman_token") is True,
            correlation=raw.get("correlation", "new"),
            correlation_value=str(raw.get("correlation_value", "")),
            link_policy=raw.get("link_policy", "remove"),
            status=raw.get("status", "open"),
            notes=str(raw.get("notes", "")),
            folder=case_dir,
            load_error=None,
            source_fdi=str(source_fdi_raw) if source_fdi_raw is not None else None,
            accepted_version=accepted if type(accepted) is int else None,
            reopened=raw.get(REOPENED_KEY) is True,
            load_notes=notes,
            review=review,
        )
    except (OSError, ValueError, KeyError, TypeError) as e:
        return Case(
            id=case_id, key=case_id, variant="", env="",
            headers={}, drop_postman_token=False,
            correlation="new", correlation_value="",
            link_policy="remove", status="open", notes="",
            folder=case_dir, load_error=str(e),
        )


log = logging.getLogger(__name__)

_write_locks: dict[str, threading.RLock] = {}
_write_locks_guard = threading.Lock()


def case_write_lock(case_dir: Path) -> threading.RLock:
    """The lock of one case folder (by resolved path), held around every
    read-modify-write of its ``caso.json`` in this process (R16)."""
    key = str(Path(case_dir).resolve()).lower()
    with _write_locks_guard:
        return _write_locks.setdefault(key, threading.RLock())


def read_caso_strict(case_dir: Path) -> dict:
    return read_json_strict(case_dir / "caso.json")


def append_history(case_dir: Path, note: str) -> None:
    with case_write_lock(case_dir):
        raw = read_caso_strict(case_dir)
        history = raw.get("history")
        if not isinstance(history, list):
            history = []
        history.append({"at": datetime.now().isoformat(), "note": note})
        raw["history"] = history
        write_json_atomic(case_dir / "caso.json", raw)


def write_review(case: Case) -> None:
    """Merge ONLY the review keys of ``case`` into its ``caso.json`` (the
    case fields, history and unknown keys stay as on disk). ``ValueError``
    and nothing written for a case with ``load_error`` or an unreadable file."""
    if case.load_error:
        raise UnreadableJsonError(
            f"caso.json non è leggibile ({case.load_error}): la revisione non viene salvata")
    with case_write_lock(case.folder):
        raw = read_caso_strict(case.folder)
        raw.update(review_to_json(case.review))
        write_json_atomic(case.folder / "caso.json", raw)


def reopen_if_accepted(case: Case) -> None:
    """A new AS-IS or TO-BE landed: an accepted case goes back to "open"
    with the "nuova versione dopo l'accettazione" notice. ``accepted_version``
    stays, for the record. A transient read error is retried (``model_io``);
    a ``caso.json`` that stays unreadable is left alone, with a warning in the
    log (never a silent skip: the case keeps showing "accettato")."""
    with case_write_lock(case.folder):
        try:
            raw = read_caso_strict(case.folder)
        except UnreadableJsonError as exc:
            log.warning("Officina: caso %s non riaperto dopo la nuova versione: %s", case.id, exc)
            return
        if raw.get("status") != "accepted":
            return
        raw["status"] = "open"
        raw[REOPENED_KEY] = True
        write_json_atomic(case.folder / "caso.json", raw)
    case.status = "open"
    case.reopened = True
