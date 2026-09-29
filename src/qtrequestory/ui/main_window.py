"""The application shell: top app bar, stacked pages, status bar, toast.

The window itself owns no feature. It builds the pages listed in :data:`PAGES`,
switches between them and offers a few services to whichever page is showing:
:meth:`MainWindow.show_page`, :meth:`MainWindow.set_status` (transient hint in
the status bar), :meth:`MainWindow.show_toast` (confirmation over the content),
:meth:`MainWindow.set_context` (window title) and the sync-status chip
(:meth:`MainWindow.set_sync_state`, :meth:`MainWindow.set_sync_summary`).

Adding a page is one tuple in :data:`PAGES` plus one widget — that is the whole
extension mechanism (DESIGN-ui §Navigation: "future Replay / Statistiche / Diff
= one tuple + one widget"). A factory that cannot be imported yet degrades to a
placeholder label, so the shell always starts, whatever state the page modules
are in. The registry (:data:`PAGES`, :class:`PageSpec`, the navigation
shortcuts) and the optional hooks a page may expose are ``ui/page_registry``'s
(re-exported here).

Pages open the import dialog with ``window.open_import(sources)``, and
queue undoable deletions on ``window.deletions`` (``ui/pending_delete``: the
bar at the bottom, carried out when the window closes).
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from functools import partial

from PySide6.QtCore import QEvent, QSettings, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import actions, icons, strings
from qtrequestory.ui.app_bar import AppBar
from qtrequestory.ui.contracts import CoreServices
from qtrequestory.ui.import_state import ArchiveWatch
from qtrequestory.ui.main_window_actions import WindowActionsMixin
from qtrequestory.ui.page_registry import (  # noqa: F401 - the registry is re-exported
    PAGE_SHORTCUTS,
    PAGES,
    PAGES_PACKAGE,
    PageSpec,
    build_page,
    connect_page_hooks,
    nav_tooltip,
    page_factory,
)
from qtrequestory.ui.quit_dialog import (  # noqa: F401 - JOB_LABELS/build_quit_dialog re-exported
    JOB_LABELS,
    build_quit_dialog,
    confirm_quit_during_job,
    job_label,
    warn_failed_deletions,
)
from qtrequestory.ui.pending_bar import PendingBar
from qtrequestory.ui.pending_delete import PendingDeletions
from qtrequestory.ui.startup import StartupTasks
from qtrequestory.ui.sync_chip import SYNC_PANEL_SHORTCUT
from qtrequestory.ui.toast import DEFAULT_MS as TOAST_MS
from qtrequestory.ui.toast import Toast
from qtrequestory.ui.workers import OFFICINA_DELIVERY_JOB, OFFICINA_GENERATE_JOBS, JobRunner

log = logging.getLogger(__name__)

STATUS_TIMEOUT_MS = 4000
SYNC_NOW_SHORTCUT = "Ctrl+Shift+S"
#: Jobs after which every page's ``on_data_changed`` runs — and which closing
#: the window would interrupt, so it asks first.
DATA_JOBS = ("sync", "index", "import", "recycle")
#: Jobs closing the window would interrupt: the data jobs, and an Officina
#: generation (a document already on its way would not be saved). The three
#: generation lanes are asked about once. A delivery too (it stops between files).
QUIT_JOBS = (*DATA_JOBS, *OFFICINA_GENERATE_JOBS, OFFICINA_DELIVERY_JOB)
#: How often the pages' ``refresh_sync_state`` runs (the app-bar chip would
#: otherwise stay stale after a scheduled sync until the user opened
#: Sincronizzazione). Slow on purpose: it only re-reads a state file.
SYNC_STATE_REFRESH_MS = 60_000


class MainWindow(WindowActionsMixin, QMainWindow):
    """App bar + stack + status bar. Everything else is a page (the sync,
    import and wizard entry points: ``ui/main_window_actions``)."""

    def __init__(
        self,
        services: CoreServices,
        runner: JobRunner,
        pages: Sequence[PageSpec] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._services = services
        self._runner = runner
        self._specs = list(pages if pages is not None else PAGES)
        self._pages: dict[str, QWidget] = {}
        self.shortcuts: dict[str, QShortcut] = {}
        #: The header chip's dropdown, built on first use (see toggle_sync_panel).
        self.sync_panel: QWidget | None = None

        self.setWindowTitle(strings.WINDOW_TITLE)
        self.setWindowIcon(icons.app_icon())
        self.app_bar = AppBar()
        self.stack = QStackedWidget()

        self._build_layout()
        self.toast = Toast(self.centralWidget())
        #: Undoable deletions (D6), before the pages: they queue on it.
        self.deletions = PendingDeletions(self)
        self._build_pages()
        #: After the pages: its buttons come last in the Tab order.
        self.deletion_bar = PendingBar(self.deletions, self.centralWidget())
        self._build_shortcuts()
        self.app_bar.page_requested.connect(self.show_page)
        self.app_bar.sync_requested.connect(self.toggle_sync_panel)
        self._runner.busy.connect(self._on_job_refused)
        self._runner.job_finished.connect(self._on_job_finished)
        self._startup: StartupTasks | None = None
        self.sync_state_timer = QTimer(self)
        self.sync_state_timer.setInterval(SYNC_STATE_REFRESH_MS)
        self.sync_state_timer.timeout.connect(self.refresh_sync_state)
        self.sync_state_timer.start()
        self._restore_geometry()
        if self._pages:
            first = next(iter(self._pages))  # the first entry of PAGES
            self.show_page(first)
            focus = getattr(self._pages[first], "initial_focus", None)
            if callable(focus):
                focus()  # remembered by Qt and applied when the window activates

    # -- public API for the pages -----------------------------------------

    def show_page(self, key: str) -> None:
        """Switch to the page registered under ``key``; unknown keys are ignored."""
        page = self._pages.get(key)
        if page is None:
            log.debug("pagina sconosciuta: %s", key)
            return
        current = self.stack.currentWidget()
        leave = getattr(current, "can_leave", None)
        if current is not page and callable(leave) and not leave():
            # The bar already checked the clicked entry: put the check back.
            self.app_bar.set_current(self.current_page_key() or key)
            return
        self.stack.setCurrentWidget(page)
        self.app_bar.set_current(key)

    def set_status(self, text: str, ms: int = STATUS_TIMEOUT_MS) -> None:
        """Transient message in the left segment ("Copiato negli appunti…")."""
        self.statusBar().showMessage(text, ms)

    def show_toast(self, text: str, tone: str = "neutral", ms: int = TOAST_MS,
                   action: tuple[str, Callable[[], None]] | None = None, hint: str = "") -> None:
        """A confirmation over the content ("JSON copiato · 157 KB"); see ``ui/toast``.
        ``action`` = ``(button text, callback)`` adds a button ("Annulla")."""
        self.toast.show_message(text, tone, ms, action=action, hint=hint)

    def set_sync_state(self, items: Sequence[tuple]) -> None:
        """The app-bar chip: ``(env, tone, text[, note])`` per environment."""
        self.app_bar.status_chip.set_envs(list(items))

    def set_sync_summary(self, text: str) -> None:
        """The chip as one plain line — for a page that has no per-env state."""
        self.app_bar.status_chip.set_envs([("", "neutral", text)] if text else [])

    def set_context(self, text: str | None) -> None:
        """Window title "qtRequestory — coll · 1a2b3c4d", or just the name."""
        self.setWindowTitle(
            strings.WINDOW_TITLE_CONTEXT.format(context=text) if text else strings.WINDOW_TITLE
        )

    def current_page_key(self) -> str | None:
        current = self.stack.currentWidget()
        for key, page in self._pages.items():
            if page is current:
                return key
        return None

    def page(self, key: str) -> QWidget | None:
        return self._pages.get(key)

    def pages(self) -> list[str]:
        return list(self._pages)

    def refresh_sync_state(self) -> None:
        """Every page's ``refresh_sync_state`` hook (the chip follows)."""
        for page in self._pages.values():
            refresh = getattr(page, "refresh_sync_state", None)
            if callable(refresh):
                refresh()

    def startup_tasks(self) -> None:
        """Index what is pending, then a non-forced sync (see ``ui/startup``).

        ``run_gui`` calls this once the window is visible; nothing else does,
        so a window built by a test starts no background job by itself.
        """
        self._startup = StartupTasks(self._services, self._runner,
                                     self._start_background_sync, self)
        self._startup.run()

    # -- construction ------------------------------------------------------

    def _build_layout(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.app_bar)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self.statusBar()  # transient hints only; the sync state lives in the app bar

    def _build_pages(self) -> None:
        # The bar entries first: a widget joins the Tab chain when it enters the
        # window, so this puts the whole bar before every page.
        for spec in self._specs:
            if spec.placement == "hidden":
                continue
            if spec.placement == "icon":
                self.app_bar.add_icon_button(spec.key, spec.icon_name, nav_tooltip(spec))
            else:
                self.app_bar.add_tab(spec.key, spec.label, spec.icon_name, nav_tooltip(spec))
        chain = self.app_bar.focus_chain()
        for before, after in zip(chain, chain[1:]):
            QWidget.setTabOrder(before, after)  # the chip was created before the tabs
        for spec in self._specs:
            widget = build_page(spec, self._services, self._runner, self)
            self._pages[spec.key] = widget
            self.stack.addWidget(widget)
        connect_page_hooks(self._pages, self)
        for page in self._pages.values():  # now that someone listens (Important #9)
            emit = getattr(page, "emit_initial_state", None)
            if callable(emit):
                emit()

    def _build_shortcuts(self) -> None:
        bindings: list[tuple[str, Callable[[], None]]] = [
            (sequence, partial(self.show_page, key)) for key, sequence in PAGE_SHORTCUTS.items()
        ]
        bindings.append((SYNC_NOW_SHORTCUT, self.start_sync))
        bindings.append((SYNC_PANEL_SHORTCUT, self.toggle_sync_panel))
        for sequence, slot in bindings:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(slot)
            self.shortcuts[sequence] = shortcut

    # -- reactions ---------------------------------------------------------

    def _on_job_refused(self, name: str) -> None:
        self.set_status(strings.STATUS_BUSY.format(name=job_label(name)))

    def _on_job_finished(self, name: str, _ok: bool) -> None:
        """After a sync or an index — even a failed one, which may have written
        half the files — every page re-reads what it shows."""
        if name not in DATA_JOBS:
            return
        for page in self._pages.values():
            refresh = getattr(page, "on_data_changed", None)
            if callable(refresh):
                refresh()

    def _start_background_sync(self) -> None:
        """The startup sync: non-forced, and without leaving the current page."""
        starter = getattr(self._pages.get("sync"), "start_sync", None)
        if callable(starter):
            starter(force=False)

    def _broadcast_config(self, sender_key: str | None, cfg: object) -> None:
        """Impostazioni saved: let the OTHER pages reload.

        The sender is skipped on purpose: it already has the configuration it
        just saved, and a page that both emits ``config_changed`` and reloads on
        ``on_config_changed`` would otherwise re-enter itself.
        """
        for key, page in self._pages.items():
            if key == sender_key:
                continue
            handler = getattr(page, "on_config_changed", None)
            if callable(handler):
                handler(cfg)
        watch = ArchiveWatch.existing(self._runner)
        if watch is not None:  # new env names or a new folder: other strays
            watch.refresh()

    # -- window state ------------------------------------------------------

    def _job_detail(self, name: str) -> str:
        """"12 di 48 file" for a running sync, from the page's progress model."""
        counts = getattr(self._pages.get(name), "progress_counts", None)
        done_total = counts() if callable(counts) else None
        if not done_total:
            return ""
        done, total = done_total
        return strings.QUIT_PROGRESS.format(done=done, total=total)

    def settings(self) -> QSettings:
        """The user's store; see ``actions.user_settings`` for why not ``QSettings(org, app)``."""
        return actions.user_settings()

    def _restore_geometry(self) -> None:
        stored = self.settings()
        geometry = stored.value("window/geometry")
        state = stored.value("window/state")
        if geometry is not None:
            self.restoreGeometry(geometry)
        if state is not None:
            self.restoreState(state)

    def changeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        """Coming back to the window is when a stale chip would be noticed."""
        super().changeEvent(event)
        if event.type() == QEvent.Type.ActivationChange and self.isActiveWindow():
            self.refresh_sync_state()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        """Ask before abandoning a sync, an index or an Officina generation,
        carry out the pending deletions, then remember the geometry."""
        asked_officina = False
        for name in QUIT_JOBS:
            if not self._runner.is_running(name):
                continue
            if name in OFFICINA_GENERATE_JOBS:
                if asked_officina:
                    continue  # one question for the three lanes
                asked_officina = True
            # ``pending`` only when there is any: the question's older callers take three arguments
            extra = {"pending": len(self.deletions)} if len(self.deletions) else {}
            if not confirm_quit_during_job(self, name, self._job_detail(name), **extra):
                event.ignore()
                return
        for page in self._pages.values():
            quitting = getattr(page, "on_quit", None)
            if callable(quitting):
                quitting()  # e.g. the Officina drops the cases still waiting
        for name in QUIT_JOBS:
            self._runner.cancel(name)
        failed = self.deletions.flush()  # never lost, never postponed (D6)
        if failed:
            warn_failed_deletions(self, [f"{item.name}: {item.reason(exc)}" for item, exc in failed])
        stored = self.settings()
        stored.setValue("window/geometry", self.saveGeometry())
        stored.setValue("window/state", self.saveState())
        super().closeEvent(event)
