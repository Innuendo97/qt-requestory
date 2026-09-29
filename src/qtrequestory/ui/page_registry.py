"""The pages of the main window (``ui/main_window``): what the app bar
offers and how each page is built, and the navigation shortcuts.

Adding a page is one tuple in :data:`PAGES` plus one widget. The factories
import their page module while the window is built, not at import time.

Optional hooks a page may expose (all duck-typed, all optional):

``state_changed``       ``Signal(list)`` of ``(env, tone, text[, note])`` -> the status chip
``summary_changed``     ``Signal(str)`` -> the status chip as one plain line (only
                        wired when the page has no ``state_changed``)
``attention_changed``   ``Signal(Attention)`` -> the chip's colour, dot and spin (D5)
``emit_initial_state()`` called once, after every hook above is connected: a
                        page that computes its state in ``__init__`` has no
                        listener yet at that point
``config_changed``      ``Signal(object)`` -> broadcast to every other page's
                        ``on_config_changed(cfg)``
``on_config_changed``   receives that broadcast
``start_sync()``        called for Ctrl+Shift+S and after the first-run wizard;
                        the Sincronizzazione page also takes ``force=False``
                        for the startup sync
``initial_focus()``     the first page puts the keyboard focus where typing
                        should go at startup (Ricerca: the FDI field)
``on_data_changed()``   a sync or an index job finished: coverage, keys and
                        counts may have moved (``JobRunner.job_finished``)
``refresh_sync_state()`` the window's slow refresh (every
                        ``main_window.SYNC_STATE_REFRESH_MS`` and on activation): a
                        scheduled ``--sync`` may have changed the state behind
                        the window's back; cheap reads only
``progress_counts()``   ``(done, total)`` files of the running sync, or None,
                        for the quit question
``can_leave()``         asked before switching away from the page; False keeps
                        it on screen (Impostazioni with unsaved changes)
``on_quit()``           the window is closing (after the quit question): stop
                        starting new work (the Officina's waiting cases)
"""
from __future__ import annotations

import importlib
import logging
from collections.abc import Callable, Mapping
from functools import partial
from typing import TYPE_CHECKING, Literal, NamedTuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QWidget

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import CoreServices

if TYPE_CHECKING:
    from qtrequestory.ui.main_window import MainWindow
    from qtrequestory.ui.workers import JobRunner

__all__ = ["PAGES", "PAGES_PACKAGE", "PAGE_SHORTCUTS", "PageSpec", "build_page", "connect_page_hooks",
           "nav_tooltip", "page_factory"]

log = logging.getLogger(__name__)

#: Page key -> its navigation shortcut; also shown in the tab/icon tooltip.
#: Ctrl+2 (the old Sincronizzazione tab) opens the header's sync panel instead.
PAGE_SHORTCUTS = {"search": "Ctrl+1", "officina": "Ctrl+3", "settings": "Ctrl+,", "about": "F1"}


class PageSpec(NamedTuple):
    """One entry of :data:`PAGES` — a plain ``(key, label, icon, factory, placement)``.

    ``factory(services, runner, window) -> QWidget`` is called once, while the
    window is being built; ``placement`` decides how the app bar offers the
    page: a labelled ``"tab"`` on the left or an ``"icon"`` button (label as
    tooltip) on the right, or ``"hidden"``: no entry, reached another way
    (Sincronizzazione, from the header chip's panel since D5).
    """

    key: str
    label: str
    icon_name: str
    factory: Callable[[CoreServices, JobRunner, MainWindow], QWidget]
    placement: Literal["tab", "icon", "hidden"]


#: Where the page modules live; a ModuleNotFoundError about anything else is a
#: real import error in a page, not a task that has not landed yet.
PAGES_PACKAGE = "qtrequestory.ui.pages"


def page_factory(module: str, class_name: str) -> Callable[..., QWidget]:
    """A lazy factory for ``qtrequestory.ui.pages.<module>.<class_name>``.

    The import happens while the window is built, not at module import time, so
    the shell can be tested (and run) before the page modules exist.
    """

    def factory(services: CoreServices, runner: JobRunner, window: MainWindow) -> QWidget:
        page_module = importlib.import_module(f"{PAGES_PACKAGE}.{module}")
        return getattr(page_module, class_name)(services, runner, window)

    factory.__name__ = f"make_{module}"
    return factory


#: The v1 pages, in app-bar order. No disabled placeholders: a page is here
#: only when it exists (DESIGN-ui §Navigation).
PAGES: list[PageSpec] = [
    PageSpec("search", strings.NAV_SEARCH, "search",
             page_factory("search_page", "SearchPage"), "tab"),
    PageSpec("sync", strings.NAV_SYNC, "arrow-sync", page_factory("sync_page", "SyncPage"), "hidden"),
    PageSpec("officina", strings.OFFICINA_NAV, "wrench",
             page_factory("officina_page", "OfficinaPage"), "tab"),
    PageSpec("settings", strings.NAV_SETTINGS, "settings",
             page_factory("settings_page", "SettingsPage"), "icon"),
    PageSpec("about", strings.NAV_ABOUT, "info", page_factory("about_page", "AboutPage"), "icon"),
]


def nav_tooltip(spec: PageSpec) -> str:
    """"Impostazioni (Ctrl+,)": the label, plus the shortcut when there is one."""
    shortcut = PAGE_SHORTCUTS.get(spec.key)
    if not shortcut:
        return spec.label
    return strings.NAV_TOOLTIP.format(label=spec.label, shortcut=shortcut)


def build_page(spec: PageSpec, services: CoreServices, runner: JobRunner, window: MainWindow) -> QWidget:
    """``spec``'s page, or a placeholder label when it cannot be built: a
    page module not written yet is an info line, any other failure an error
    (a broken page must not break the shell)."""
    try:
        return spec.factory(services, runner, window)
    except ModuleNotFoundError as exc:
        if (exc.name or "").startswith(PAGES_PACKAGE):
            log.info("pagina %s non disponibile (%s)", spec.key, exc)  # not written yet
        else:
            # The page exists but one of ITS imports is missing: a real bug.
            log.exception("pagina %s non disponibile", spec.key)
    except Exception:  # noqa: BLE001 - a broken page must not break the shell
        log.exception("pagina %s non disponibile", spec.key)
    placeholder = QLabel(strings.PAGE_UNAVAILABLE.format(label=spec.label))
    placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
    placeholder.setWordWrap(True)
    return placeholder


def connect_page_hooks(pages: Mapping[str, QWidget], window: MainWindow) -> None:
    """Wire the optional hooks the ``pages`` expose (module docstring) to ``window``."""
    for key, page in pages.items():
        state = getattr(page, "state_changed", None)
        summary = getattr(page, "summary_changed", None)
        if state is not None and hasattr(state, "connect"):
            state.connect(window.set_sync_state)
        elif summary is not None and hasattr(summary, "connect"):
            summary.connect(window.set_sync_summary)
        attention = getattr(page, "attention_changed", None)
        if attention is not None and hasattr(attention, "connect"):
            attention.connect(window.app_bar.status_chip.set_attention)
        changed = getattr(page, "config_changed", None)
        if changed is not None and hasattr(changed, "connect"):
            # The key is bound here so the broadcast can skip its sender.
            changed.connect(partial(window._broadcast_config, key))  # noqa: SLF001 - the window's own slot
