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
