"""The main window's entry points that open something (``ui/main_window``,
split for size): the sync (Ctrl+Shift+S, the header chip's panel), the
import dialog and the first-run wizard run again.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from functools import partial
from pathlib import Path

from PySide6.QtWidgets import QWidget

from qtrequestory.ui import strings
from qtrequestory.ui.app_bar import SYNC_PAGE_KEY

__all__ = ["WindowActionsMixin"]


class WindowActionsMixin:
    """``MainWindow``'s sync, import and wizard entry points. Needs
    ``_services``, ``_runner``, ``_pages``, ``stack``, ``app_bar``,
    ``sync_panel``, ``show_page``, ``set_status`` and ``_broadcast_config``."""

    def start_sync(self) -> None:
        """Ctrl+Shift+S, and the wizard's "avvia la prima sincronizzazione"."""
        self.show_page("sync")
        page = self._pages.get("sync")
        if page is not None and self.stack.currentWidget() is not page:
            return  # the page on screen refused to be left (unsaved changes)
        starter = getattr(page, "start_sync", None)
        if callable(starter):
            starter()

    def toggle_sync_panel(self) -> None:
        """The header chip and Ctrl+2: the sync panel under the chip (D5);
        without a real Sincronizzazione page, that page itself."""
        page = self._pages.get(SYNC_PAGE_KEY)
        if self.sync_panel is None and not hasattr(page, "presenter"):
            self.show_page(SYNC_PAGE_KEY)
            return
        if self.sync_panel is None:
            from qtrequestory.ui.pages.sync_panel import SyncPanel

            self.sync_panel = SyncPanel(self._services, page, self)
            self.sync_panel.open_page.connect(partial(self.show_page, SYNC_PAGE_KEY))
        self.sync_panel.toggle(self.app_bar.status_chip)

    def open_import(self, sources: Sequence[Path | None] | None = None,
                    on_closed: Callable[[], None] | None = None) -> QWidget | None:
        """The import dialog on ``sources`` (None: the mirror's own strays).

        The banners' [Importa], Impostazioni › Archivio and the wizard's offer
        all come here. Refused, with the reason in the status bar, while the
        log folder is not usable; ``on_closed`` then runs straight away.
        """
        from qtrequestory.ui.import_dialog import open_import_dialog

        dialog = open_import_dialog(self._services, self._runner, self,
                                    list(sources) if sources else [None], on_closed)
        if dialog is None:
            problems = self._services.config.mirror_root_errors(self._services.config.load())
            self.set_status(strings.IMPORT_REFUSED.format(
                problem=strings.lower_first(problems[0]) if problems else ""))
            if on_closed is not None:
                on_closed()
        return dialog

    def rerun_wizard(self) -> object | None:
        """Impostazioni → "Riesegui configurazione iniziale".

        The wizard saves the configuration itself, so every page is told, as
        after a save in Impostazioni; then the first sync it offers.
        """
        from qtrequestory.ui import app  # local: app imports this module

        if not app.wizard_available():
            self.set_status(strings.WIZARD_UNAVAILABLE)
            return None
        result = app.show_first_run_wizard(self._services, self._runner, self)
        if result is None:
            return None
        cfg = getattr(result, "config", None) or self._services.config.load()
        self._broadcast_config(None, cfg)
        then = self.start_sync if getattr(result, "start_sync", False) else None
        sources = getattr(result, "import_sources", ())
        if sources:
            self.open_import(sources, on_closed=then)  # the sync would hold the lock
        elif then is not None:
            then()
        return result
