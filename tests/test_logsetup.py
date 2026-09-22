"""core/logsetup.py — the one thing that must work before anything else does.

``cli.main`` calls ``configure_logging`` before a window or a log file exists.
In the shipped exe (``console=False``) there is no console either, so anything
that raises here kills the process with no message at all: the user
double-clicks the icon and nothing happens, for ever. ``core/config.py`` opens
with the rule this protects — "the tool must always start".
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

from qtrequestory.core.logsetup import SYNC_LOGGER, configure_logging
from qtrequestory.core.paths import AppPaths


@pytest.fixture
def paths(tmp_path: Path) -> AppPaths:
    return AppPaths(tmp_path / "home").ensure()


@pytest.fixture(autouse=True)
def restore_logging():
    """``configure_logging`` reconfigures the GLOBAL root logger."""
    root, sync = logging.getLogger(), logging.getLogger(SYNC_LOGGER)
    saved = (root.level, list(root.handlers), list(sync.handlers), sync.propagate)
    yield
    root.setLevel(saved[0])
    root.handlers[:] = saved[1]
    sync.handlers[:] = saved[2]
    sync.propagate = saved[3]


@pytest.mark.parametrize("level,expected", [
    ("DEBUG", logging.DEBUG),
    ("debug", logging.DEBUG),
    ("WARNING", logging.WARNING),
    ("CRITICAL", logging.CRITICAL),
])
def test_a_known_level_name_is_applied(paths: AppPaths, level: str, expected: int):
    configure_logging(paths, headless=True, level=level)
    assert logging.getLogger().level == expected


@pytest.mark.parametrize("level", ["VERBOSE", "TRACE", "", "12", "INFOO"])
def test_an_unknown_level_falls_back_to_info_instead_of_killing_the_process(
    paths: AppPaths, level: str
):
    """``logging.getLevelName("VERBOSE")`` returns the *string* ``"Level
    VERBOSE"``, and ``root.setLevel`` then raises ``ValueError``.

    ``config.json`` is a plain file people hand-edit — that is how
    ``log_level`` gets a value nothing recognises. With ``console=False`` the
    traceback goes nowhere: the exe simply never opens a window.

    The warning is asserted in ``app.log`` rather than through ``caplog``
    because that is where it has to land: ``configure_logging`` replaces every
    root handler, so anything said before it finishes is said to nobody.
    """
    configure_logging(paths, headless=True, level=level)

    assert logging.getLogger().level == logging.INFO
    for handler in logging.getLogger().handlers:
        handler.flush()
    written = paths.app_log.read_text(encoding="utf-8")
    assert "log_level" in written
    assert level in written or not level


def test_logging_still_reaches_both_files_after_the_fallback(paths: AppPaths):
    """The fallback is not just "does not raise": the logs must work."""
    configure_logging(paths, headless=True, level="VERBOSE")

    logging.getLogger("qtrequestory.test").info("riga applicativa")
    logging.getLogger(SYNC_LOGGER).info("riga di sincronizzazione")
    for handler in (*logging.getLogger().handlers, *logging.getLogger(SYNC_LOGGER).handlers):
        handler.flush()

    assert "riga applicativa" in paths.app_log.read_text(encoding="utf-8")
    assert "riga di sincronizzazione" in paths.sync_log.read_text(encoding="utf-8")


def test_a_numeric_level_is_still_accepted(paths: AppPaths):
    """The parameter is typed ``str`` but the old code accepted an int too;
    nothing in the tree passes one, and nothing should start failing if it did."""
    configure_logging(paths, headless=True, level=logging.WARNING)
    assert logging.getLogger().level == logging.WARNING
