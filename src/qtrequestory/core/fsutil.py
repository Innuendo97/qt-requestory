"""Windows-safe file replace/remove helpers shared by ``state.py`` and ``sync.py``.

Windows can hold a short-lived exclusive handle on a file that was just
written or is about to be replaced — the Explorer/search indexer, a preview
pane, an antivirus scan. ``os.replace`` then raises ``PermissionError``
(WinError 5/32) even though nothing is actually wrong; the same handle is
almost always released within a few hundred milliseconds. Retrying a few
times with a short sleep turns a spurious failure into a silent success,
which matters here because the exe runs unattended (a scheduled task,
``console=False``): there is nobody around to retry it by hand.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)


def replace_with_retry(
    src: Path,
    dst: Path,
    *,
    attempts: int = 5,
    delay_s: float = 0.2,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """``os.replace(src, dst)``, retried only on ``PermissionError``.

    Any other ``OSError`` (e.g. the destination directory vanished) is not
    retried and raises immediately. After ``attempts`` failed tries the last
    ``PermissionError`` is re-raised, so the caller decides what "still
    failing" means (keep the old file, report the failure, etc.) rather than
    this helper swallowing it.
    """
    last_error: PermissionError | None = None
    for attempt in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError as e:
            last_error = e
            if attempt + 1 < attempts:
                sleep(delay_s)
    raise last_error  # type: ignore[misc]  # attempts >= 1 in every real caller


def remove_quietly(path: Path) -> None:
    """Best-effort ``path.unlink()``: a missing file is fine, anything else is logged."""
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError as e:  # pragma: no cover - best effort (e.g. antivirus holding the file)
        log.warning("impossibile rimuovere il file %s: %s", path, e)


def _norm(path: Path) -> str:
    """Absolute, normalised and — on Windows — case-folded, for comparisons."""
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def is_within(child: Path, parent: Path) -> bool:
    """True when ``child`` is ``parent`` or anything below it.

    Purely lexical (no symlink resolution) and component-wise: ``C:/logs-old``
    is NOT inside ``C:/logs``. Case-insensitive on Windows, like its file system.
    """
    c, p = _norm(child), _norm(parent)
    try:
        return os.path.commonpath([c, p]) == p
    except ValueError:  # different drives
        return False


def paths_overlap(a: Path, b: Path) -> bool:
    """``a`` and ``b`` are the same folder or one contains the other."""
    return is_within(a, b) or is_within(b, a)


def real_is_within(child: Path, parent: Path) -> bool:
    """:func:`is_within` after resolving both paths (``os.path.realpath``):
    a junction, a symlink, a ``subst`` drive or an 8.3 short name leading
    into ``parent`` still counts as inside it. Use it wherever "inside the
    archive" protects data."""
    return is_within(Path(os.path.realpath(child)), Path(os.path.realpath(parent)))


def same_file(a: Path, b: Path) -> bool:
    """``os.path.samefile`` that answers False when either side is missing."""
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False
