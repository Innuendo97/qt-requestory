"""The strings package is a contract: five page tasks each own one module.

These tests keep the layout honest — the shell strings live in ``common``, the
per-page modules exist even while empty, and everything is re-exported from the
package so widgets can do ``from qtrequestory.ui import strings`` and nothing
else.
"""
from __future__ import annotations

import importlib

import pytest

from qtrequestory.ui import strings

PAGE_MODULES = ("common", "search", "sync", "settings", "wizard", "about")


@pytest.mark.parametrize("name", PAGE_MODULES)
def test_every_page_module_exists(name: str):
    module = importlib.import_module(f"qtrequestory.ui.strings.{name}")
    assert module.__doc__, "each strings module documents who owns it"


@pytest.mark.parametrize(
    "name",
    [
        "APP_NAME", "ORG_NAME", "WINDOW_TITLE",
        "NAV_SEARCH", "NAV_SYNC", "NAV_SETTINGS", "NAV_ABOUT",
        "STATUS_SYNC_SUMMARY_EMPTY", "STATUS_SYNC_SUMMARY_TOOLTIP",
        "QUIT_DURING_SYNC_TITLE", "QUIT_DURING_SYNC_TEXT", "QUIT_STOP", "QUIT_CONTINUE",
        "BTN_CANCEL", "BTN_SAVE", "BTN_BROWSE", "BTN_OPEN", "BTN_OPEN_FOLDER",
        "BTN_ADD", "BTN_REMOVE", "BTN_IMPORT_FILE", "BTN_REFRESH",
        "ENV_COL_ENABLED", "ENV_COL_NAME", "ENV_COL_URL",
        "PAGE_UNAVAILABLE", "WIZARD_UNAVAILABLE", "STATUS_BUSY",
    ],
)
def test_shell_strings_are_re_exported_from_the_package(name: str):
    assert isinstance(getattr(strings, name), str)


def test_shell_strings_are_italian_and_not_empty():
    assert strings.NAV_SEARCH == "Ricerca"
    assert strings.NAV_SYNC == "Sincronizzazione"
    assert strings.NAV_SETTINGS == "Impostazioni"
    assert strings.NAV_ABOUT == "Info"
    assert strings.BTN_CANCEL == "Annulla"
    assert strings.QUIT_STOP and strings.QUIT_CONTINUE


def test_placeholders_format_with_their_documented_fields():
    assert "Ricerca" in strings.PAGE_UNAVAILABLE.format(label="Ricerca")
    assert "sync" in strings.STATUS_BUSY.format(name="sync")
