"""The documents of an Officina case: TARGET, AS-IS and the TO-BE versions.

Part of the model (``officina.model`` re-exports :class:`Version`). Stdlib only.
Reading is tolerant by design: a version file deleted from disk, or a
``*.meta.json`` damaged by hand, never raises — the caller gets a
:class:`Version` that says what is wrong (``missing``, ``broken``) instead.

A meta file is never trusted to build a path: the TARGET's ``original_name``
must be ONE safe file name (else the target is ``broken``), and a
``doc_type`` other than ``pdf``/``html`` is ignored in favour of the content
file actually on disk (``asis.pdf``, ``v001.html``...).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from qtrequestory.officina.model_io import (
    UnreadableJsonError,
    parse_dt,
    read_json_strict,
    write_bytes_atomic,
    write_json_atomic,
)

__all__ = ["DOC_TYPES", "SlotKind", "Version", "is_safe_component"]

SlotKind = Literal["target", "asis", "tobe"]
DOC_TYPES = ("pdf", "html")

_TOBE_RE = re.compile(r"^v(\d{3})\.meta\.json$")
_TOBE_CONTENT_RE = re.compile(r"^v(\d{3})\.(pdf|html)$")
#: What a single file name may not contain on Windows (plus control characters).
_UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


@dataclass(frozen=True)
class Version:
    """One generated or supplied document (a TARGET, the AS-IS, or one TO-BE)."""

    kind: SlotKind
    number: int  # 0 for target/asis, 1.. for tobe
    path: Path  # absolute file path
    doc_type: Literal["pdf", "html"]
    created: datetime
    meta: dict  # generation metadata, or {"original_name": ...} for target
    missing: bool  # True when the file is gone from disk
    #: Why the metadata cannot be used (a hand edit), "" when fine. A broken
    #: version is also ``missing``, and its ``path`` is its slot's folder.
    broken: str = ""


def is_safe_component(name: object) -> bool:
    """True for ONE usable file name: no separator, drive, reserved or
    control character, not empty, ``.`` or ``..``."""
    return (isinstance(name, str) and name.strip() not in ("", ".", "..")
            and not _UNSAFE.search(name))


def _meta(meta_path: Path) -> dict | None:
    try:
        return read_json_strict(meta_path)
    except UnreadableJsonError:
        return None


def sniff_doc_type_by_name(name: str) -> Literal["pdf", "html"]:
    ext = Path(name).suffix.lower()
    return "html" if ext in (".html", ".htm") else "pdf"


def write_version(
    dir_: Path, base: str, *, kind: SlotKind, number: int, content: bytes, doc_type: str, meta: dict,
) -> Version:
    dir_.mkdir(parents=True, exist_ok=True)
    dest = dir_ / f"{base}.{doc_type}"
    write_bytes_atomic(dest, content)
    created = datetime.now()
    write_json_atomic(dir_ / f"{base}.meta.json", {
        "doc_type": doc_type, "created": created.isoformat(), "meta": meta,
    })
    return Version(kind=kind, number=number, path=dest, doc_type=doc_type, created=created,
                   meta=dict(meta), missing=False)


def read_target(case_dir: Path) -> Version | None:
    target_dir = case_dir / "target"
    meta_path = target_dir / "target.meta.json"
    if not meta_path.exists():
        return None
    raw = _meta(meta_path)
    if raw is None:
        return None
    created = parse_dt(raw.get("created"))
    original_name = raw.get("original_name", "")
    if not is_safe_component(original_name):
        return _broken("target", 0, target_dir, created,
                       f"target.meta.json non valido: nome del file {original_name!r} non ammesso")
    doc_type = raw.get("doc_type")
    if doc_type not in DOC_TYPES:
        doc_type = sniff_doc_type_by_name(original_name)
    path = target_dir / original_name
    return Version(
        kind="target", number=0, path=path, doc_type=doc_type, created=created,
        meta={"original_name": original_name}, missing=not path.exists(),
    )


def _broken(kind: SlotKind, number: int, folder: Path, created: datetime, reason: str) -> Version:
    return Version(kind=kind, number=number, path=folder, doc_type="pdf", created=created,
                   meta={}, missing=True, broken=reason)


def read_single_version(dir_: Path, base: str, *, kind: SlotKind, number: int) -> Version | None:
    meta_path = dir_ / f"{base}.meta.json"
    if not meta_path.exists():
        return None
    raw = _meta(meta_path)
    if raw is None:
        return None
    created = parse_dt(raw.get("created"))
    meta = raw.get("meta", {})
    if not isinstance(meta, dict):
        meta = {}
    doc_type = raw.get("doc_type", "pdf")
    if doc_type not in DOC_TYPES:
        doc_type = content_type_on_disk(dir_, base)
        if doc_type is None:
            return _broken(kind, number, dir_, created,
                           f"{meta_path.name} non valido: tipo di documento non ammesso")
    path = dir_ / f"{base}.{doc_type}"
    return Version(
        kind=kind, number=number, path=path, doc_type=doc_type,
        created=created, meta=meta, missing=not path.exists(),
    )


def content_type_on_disk(dir_: Path, base: str) -> str | None:
    """``pdf`` or ``html`` for the ``<base>.pdf`` / ``<base>.html`` in ``dir_``, else None."""
    return next((ext for ext in DOC_TYPES if (dir_ / f"{base}.{ext}").is_file()), None)


def existing_tobe_numbers(tobe_dir: Path) -> set[int]:
    """Every TO-BE version number with a file on disk, meta *or* content —
    so a version whose meta went missing/corrupt is never renumbered over."""
    numbers: set[int] = set()
    for p in tobe_dir.iterdir():
        m = _TOBE_RE.match(p.name) or _TOBE_CONTENT_RE.match(p.name)
        if m:
            numbers.add(int(m.group(1)))
    return numbers


def _read_tobe_version(tobe_dir: Path, number: int) -> Version | None:
    base = f"v{number:03d}"
    meta_path = tobe_dir / f"{base}.meta.json"
    if meta_path.exists():
        v = read_single_version(tobe_dir, base, kind="tobe", number=number)
        if v is not None:
            return v
        # meta.json exists but is corrupt (or not an object): fall through
        # to the content-file fallback below rather than dropping the
        # version silently.
    for ext in ("pdf", "html"):
        content_path = tobe_dir / f"{base}.{ext}"
        if content_path.exists():
            try:
                created = datetime.fromtimestamp(content_path.stat().st_mtime)
            except OSError:
                created = datetime.min
            return Version(kind="tobe", number=number, path=content_path, doc_type=ext,
                           created=created, meta={}, missing=False)
    return None


def read_tobe_versions(tobe_dir: Path) -> list[Version]:
    if not tobe_dir.exists():
        return []
    versions: list[Version] = []
    for number in sorted(existing_tobe_numbers(tobe_dir)):
        v = _read_tobe_version(tobe_dir, number)
        if v is not None:
            versions.append(v)
    return versions
