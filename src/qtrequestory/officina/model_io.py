"""JSON and file helpers of the Officina model (``officina.model``).

Stdlib only, like the model itself. Every write goes through a temporary file
with a UNIQUE name in the same folder, then ``fsutil.replace_with_retry``: two
writers of the same file (the board and a worker, two windows) never share a
temporary file, and a crash never leaves a half-written target behind.

Two ways to read a JSON object:

* :func:`read_json_object` is tolerant (``{}`` for missing, unreadable or not
  an object), for the readers that only display;
* :func:`read_json_strict` raises :class:`UnreadableJsonError` for a file that
  exists but cannot be parsed, for the writers that merge into it — a merge
  into ``{}`` would silently wipe everything the file held.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from qtrequestory.core.fsutil import remove_quietly, replace_with_retry

__all__ = [
    "UnreadableJsonError", "atomic_copy_text", "parse_dt", "read_json_object", "read_json_strict",
    "write_bytes_atomic", "write_json_atomic",
]


class UnreadableJsonError(ValueError):
    """A JSON file exists but cannot be read as an object; the message is Italian."""


def _unique_tmp(path: Path) -> Path:
    """A new, empty temporary file next to ``path`` (same folder, so the final
    rename never crosses a volume)."""
    fd, name = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(fd)
    return Path(name)


def write_bytes_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _unique_tmp(path)
    try:
        tmp.write_bytes(data)
        replace_with_retry(tmp, path)
    except BaseException:
        remove_quietly(tmp)
        raise


def write_json_atomic(path: Path, data: object) -> None:
    write_bytes_atomic(path, json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8"))


def atomic_copy_text(src: Path, dst: Path) -> None:
    write_bytes_atomic(dst, src.read_text(encoding="utf-8").encode("utf-8"))


def read_json_object(path: Path) -> dict:
    """The JSON object in ``path``; ``{}`` when missing, unreadable or not an object."""
    try:
        return read_json_strict(path)
    except UnreadableJsonError:
        return {}


def read_json_strict(path: Path) -> dict:
    """The JSON object in ``path``; ``{}`` when the file does not exist.
    :class:`UnreadableJsonError` when it exists but is not a readable object."""
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise UnreadableJsonError(f"{path.name} non è leggibile: {exc}") from None
    if not isinstance(raw, dict):
        raise UnreadableJsonError(f"{path.name} non è leggibile: non contiene un oggetto JSON")
    return raw


def parse_dt(raw: object) -> datetime:
    try:
        return datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return datetime.min
