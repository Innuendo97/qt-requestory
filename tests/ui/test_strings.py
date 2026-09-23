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
        "STATUS_SYNC_SUMMARY_TOOLTIP", "NAV_TOOLTIP", "CHIP_SEPARATOR", "WINDOW_TITLE_CONTEXT",
        "QUIT_DURING_JOB_TITLE", "QUIT_DURING_JOB_TEXT", "QUIT_PROGRESS", "QUIT_STOP",
        "QUIT_CONTINUE", "QUIT_SYNC_INFO", "QUIT_INDEX_INFO",
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


# -- one vocabulary (the copy pass) -------------------------------------------

def _user_strings() -> dict[str, str]:
    return {name: value for name, value in vars(strings).items()
            if name.isupper() and isinstance(value, str)}


#: English words that crept into the Italian UI before ("index letto", "Ultimo
#: sync", "job … failed"). Whole words, case-insensitive.
ENGLISH_DENYLIST = ("index", "sync", "job", "failed", "error", "loading", "search",
                    "settings", "copy", "save", "open", "folder", "unknown")


def test_no_english_words_in_user_facing_strings():
    import re

    pattern = re.compile(r"\b(" + "|".join(ENGLISH_DENYLIST) + r")\b", re.IGNORECASE)
    offenders = {}
    for name, value in _user_strings().items():
        visible = re.sub(r"\{[^}]*\}", "", value)  # placeholders are not shown as such
        if pattern.search(visible):
            offenders[name] = value
    assert not offenders


def test_the_key_mode_reads_the_same_on_both_pages():
    assert strings.SETTINGS_KEY_MODE_EXACT == strings.SEARCH_KEY_MODE_EXACT == "esatta"
    assert strings.SETTINGS_KEY_MODE_CONTAINS == strings.SEARCH_KEY_MODE_CONTAINS == "contiene"


def test_the_reachability_note_reads_the_same_in_the_wizard_and_in_settings():
    assert strings.SETTINGS_CHECK_HINT == strings.WIZARD_P2_CHECK_NOTE


def test_no_module_formats_a_size_by_hand():
    """Every size goes through ``events.format_size`` (``sync_format.format_size``
    in the UI): "4.0 MB" next to "4 MB" is how the copy pass started."""
    import re
    from pathlib import Path

    src = Path(strings.__file__).resolve().parents[2]
    allowed = {src / "core" / "events.py", src / "ui" / "pages" / "sync_format.py"}
    hand_made = re.compile(r"(1024|1_048_576)[^\n]*\b[KMG]B\b|\b[KMG]B\b[^\n]*(1024|1_048_576)"
                           r"|/\s*(1024|1_048_576)\s*:")
    offenders = [f"{path.relative_to(src)}:{n}"
                 for path in src.rglob("*.py") if path not in allowed
                 for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
                 if hand_made.search(line)]
    assert not offenders
