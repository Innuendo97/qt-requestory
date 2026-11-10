"""The Genera tab's remembered choices (``ui/prefs``, through
``actions.user_settings``). Reading or writing a preference never fails the
tab: a problem is logged and the choice is simply not remembered.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from qtrequestory.ui import actions, prefs

__all__ = ["Remembered", "read", "remember"]

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Remembered:
    """As stored; the presenter checks each value is still valid."""

    mode: str = ""
    generator: str = ""
    source_env: str = ""  # "" = follows the generator
    destination: str = ""
    elenco: str = ""
    make_zip: bool = False
    save_html: bool = False


def read() -> Remembered | None:
    """The stored choices, or None when the settings cannot be read."""
    try:
        stored = actions.user_settings()

        def text(key: str) -> str:
            return str(stored.value(key, "") or "")

        return Remembered(
            mode=text(prefs.GENERA_MODE_KEY), generator=text(prefs.GENERA_GENERATOR_KEY),
            source_env=text(prefs.GENERA_SOURCE_ENV_KEY), destination=text(prefs.GENERA_DESTINATION_KEY),
            elenco=text(prefs.GENERA_ELENCO_KEY),
            make_zip=bool(stored.value(prefs.GENERA_ZIP_KEY, False, type=bool)),
            save_html=bool(stored.value(prefs.GENERA_HTML_KEY, False, type=bool)))
    except Exception:  # noqa: BLE001 - a preference is never a reason to fail
        log.exception("preferenze di Genera non leggibili")
        return None


def remember(key: str, value: object) -> None:
    try:
        actions.user_settings().setValue(key, value)
    except Exception:  # noqa: BLE001 - a preference is never a reason to fail
        log.exception("preferenza %s non salvata", key)
