"""Logging configuration for both the GUI and headless runs."""
from __future__ import annotations

import logging
import logging.handlers
import sys

from qtrequestory.core.paths import AppPaths

LOG_FORMAT = "[%(asctime)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
MAX_BYTES = 1_048_576
BACKUP_COUNT = 3

SYNC_LOGGER = "qtrequestory.sync"


def _rotating(path, level: int) -> logging.Handler:
    h = logging.handlers.RotatingFileHandler(
        path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    h.setLevel(level)
    h.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    return h


def configure_logging(paths: AppPaths, *, headless: bool, level: str = "INFO") -> None:
    """``app.log`` gets everything; ``sync.log`` gets only the sync logger.

    In a windowed (PyInstaller ``console=False``) exe ``sys.stderr`` is None,
    so a console handler is added only when a real stream exists.
    """
    paths.ensure()
    lvl = logging.getLevelName(level.upper()) if isinstance(level, str) else level
    root = logging.getLogger()
    root.setLevel(lvl)
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(_rotating(paths.app_log, lvl))
    if not headless and sys.stderr is not None:
        con = logging.StreamHandler(sys.stderr)
        con.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
        root.addHandler(con)

    sync_logger = logging.getLogger(SYNC_LOGGER)
    for h in list(sync_logger.handlers):
        sync_logger.removeHandler(h)
    sync_logger.addHandler(_rotating(paths.sync_log, logging.INFO))
    sync_logger.propagate = True


def sync_logger() -> logging.Logger:
    return logging.getLogger(SYNC_LOGGER)
