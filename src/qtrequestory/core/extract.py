"""Turn a raw request body into a file the user can open.

Output contract (non-negotiable): the written file is the PURE request body,
pretty-printed with 4 spaces, key order preserved, accents intact, UTF-8
without BOM, LF line endings, ending with a single newline. No wrapper, no
header, no comments — the user pastes this straight into Postman.
"""
from __future__ import annotations

import json
import os
import time
from datetime import date
from pathlib import Path

ENCODING = "utf-8"  # never "utf-8-sig": a BOM would break the "starts with {" contract
NO_FDI = "nofdi"


def pretty_json(raw: bytes) -> str:
    """Pretty-print a JSON body; on decode/parse failure wrap the text so the
    user still gets a readable file instead of an exception.

    ``ensure_ascii=False`` keeps ``Màrio``/``città`` verbatim; ``json.loads``
    preserves key order, so ``documents`` stays first exactly as in the log.
    """
    try:
        obj = json.loads(raw.decode(ENCODING))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        obj = {"_parseError": str(e), "raw": raw.decode(ENCODING, "replace")}
    return json.dumps(obj, ensure_ascii=False, indent=4) + "\n"


def output_name(day: date, fdi: str | None, template_key: str, call_id: str | None = None) -> str:
    """``<YYYYMMDD>_<fdi|nofdi>_<TEMPLATE_KEY>[_<call_id>].json``.

    ``call_id`` is only appended to disambiguate a name collision (same
    pratica, same template, same day — e.g. a retry).
    """
    stem = f"{day:%Y%m%d}_{fdi or NO_FDI}_{template_key}"
    if call_id:
        stem += f"_{call_id}"
    return stem + ".json"


def housekeeping(out_dir: Path, retention_hours: float) -> int:
    """Delete regular files in ``out_dir`` older than ``retention_hours`` (mtime).

    Only the top level is touched and subdirectories are left alone: the
    output dir defaults to a %TEMP% subfolder, but the user may point it at
    something they also use for other things.
    """
    out_dir = Path(out_dir)
    if not out_dir.is_dir():
        return 0
    cutoff = time.time() - retention_hours * 3600
    removed = 0
    for entry in out_dir.iterdir():
        try:
            if entry.is_file() and entry.stat().st_mtime < cutoff:
                entry.unlink()
                removed += 1
        except OSError:
            # A file open in the editor or already gone: not our problem, move on.
            continue
    return removed


def _write_text(path: Path, text: str) -> None:
    """UTF-8 without BOM, LF only (``newline="\\n"`` stops Windows from writing CRLF)."""
    with open(path, "w", encoding=ENCODING, newline="\n") as f:
        f.write(text)


def write_temp_file(
    out_dir: Path,
    name: str,
    text: str,
    *,
    retention_hours: float = 24,
    alt_name: str | None = None,
) -> Path:
    """Write ``text`` to ``out_dir/name`` after pruning stale outputs.

    If ``name`` already exists and ``alt_name`` is given (the caller passes the
    call-id variant), the alternative name is used so an earlier extraction
    the user may still have open is not overwritten. Without ``alt_name`` the
    file is simply overwritten.
    """
    out_dir = Path(out_dir)
    housekeeping(out_dir, retention_hours)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / name
    if alt_name and path.exists():
        path = out_dir / alt_name
    _write_text(path, text)
    return path


def save_as(path: Path, text: str) -> None:
    """Save to a user-chosen location, creating parent folders."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_text(path, text)
