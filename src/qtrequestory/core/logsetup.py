"""Logging configuration for both the GUI and headless runs."""
from __future__ import annotations

import logging
import logging.handlers
import sys

from qtrequestory.core.paths import AppPaths

#: ``sync.log`` only. That file mirrors the legacy PowerShell log the user
#: reads every day, so its shape and wording must not change.
LOG_FORMAT = "[%(asctime)s] %(message)s"
#: ``app.log`` and the console: the same line plus the level, so the Info page
#: can offer its Tutti / Avvisi / Errori filter on something the application
#: really writes. Lines logged by older builds have no level; the viewer shows
#: them under "Tutti".
APP_LOG_FORMAT = "[%(asctime)s] %(levelname)s %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
MAX_BYTES = 1_048_576
BACKUP_COUNT = 3

SYNC_LOGGER = "qtrequestory.sync"

#: What an unreadable ``log_level`` falls back to. Same value as the default in
#: ``config.default_config()``: a misspelling must change nothing else.
DEFAULT_LEVEL = logging.INFO

#: The names ``log_level`` may hold, case-insensitively. Spelled out rather
#: than looked up with ``getattr(logging, name)``: that module also carries
#: integers and booleans under names nobody means as a level, and this list is
#: also what the error message offers the user.
LEVEL_NAMES = ("CRITICAL", "FATAL", "ERROR", "WARNING", "WARN", "INFO", "DEBUG", "NOTSET")
#: The subset worth suggesting (``FATAL``/``WARN`` are aliases, ``NOTSET`` is a
#: trap: on the root logger it means "everything").
SUGGESTED_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def resolve_level(level: str | int) -> tuple[int, str | None]:
    """``("debug", ...) -> (10, None)``; an unknown name -> ``(INFO, <reason>)``.

    ``logging.getLevelName("VERBOSE")`` does NOT raise and does NOT return
    None: it returns the *string* ``"Level VERBOSE"``, which ``setLevel`` then
    rejects with ``ValueError``. ``config.json`` is a plain file people
    hand-edit, so that value is one typo away — and ``cli.main`` configures
    logging before there is a window or a log file, in an exe built with
    ``console=False`` where the traceback goes nowhere. The user would just
    double-click the icon and watch nothing happen.

    The reason is returned rather than logged here so the caller can log it
    once the handlers are installed, i.e. into the file where it can be read.
    """
    if isinstance(level, int) and not isinstance(level, bool):
        return level, None  # nothing in the tree passes one, but it used to work
    name = str(level).strip().upper()
    if name in LEVEL_NAMES:
        return getattr(logging, name), None
    return DEFAULT_LEVEL, (
        f"log_level '{level}' non riconosciuto: uso "
        f"{logging.getLevelName(DEFAULT_LEVEL)}. Valori ammessi: "
        + ", ".join(SUGGESTED_LEVELS) + "."
    )


def _rotating(path, level: int, fmt: str = LOG_FORMAT) -> logging.Handler:
    h = logging.handlers.RotatingFileHandler(
        path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    h.setLevel(level)
    h.setFormatter(logging.Formatter(fmt, DATE_FORMAT))
    return h


def configure_logging(paths: AppPaths, *, headless: bool, level: str = "INFO") -> None:
    """``app.log`` gets everything; ``sync.log`` gets only the sync logger.

    The two files are formatted differently on purpose: ``app.log`` carries the
    level (the Info page filters on it), ``sync.log`` keeps the legacy
    ``[timestamp] message`` shape the user is used to reading.

    In a windowed (PyInstaller ``console=False``) exe ``sys.stderr`` is None,
    so a console handler is added only when a real stream exists.
    """
    paths.ensure()
    lvl, bad_level = resolve_level(level)
    root = logging.getLogger()
    root.setLevel(lvl)
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(_rotating(paths.app_log, lvl, APP_LOG_FORMAT))
    if not headless and sys.stderr is not None:
        con = logging.StreamHandler(sys.stderr)
        con.setFormatter(logging.Formatter(APP_LOG_FORMAT, DATE_FORMAT))
        root.addHandler(con)

    sync_logger = logging.getLogger(SYNC_LOGGER)
    for h in list(sync_logger.handlers):
        sync_logger.removeHandler(h)
    sync_logger.addHandler(_rotating(paths.sync_log, logging.INFO))
    sync_logger.propagate = True

    # Warned last, on purpose: now there is a file to warn INTO. Warning before
    # this point, in a windowed exe with no console, would say it to nobody.
    if bad_level is not None:
        logging.getLogger(__name__).warning("%s", bad_level)


def sync_logger() -> logging.Logger:
    return logging.getLogger(SYNC_LOGGER)
