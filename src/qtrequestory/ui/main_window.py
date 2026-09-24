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
are in.

Optional hooks a page may expose (all duck-typed, all optional):

``state_changed``       ``Signal(list)`` of ``(env, tone, text[, note])`` -> the status chip
``summary_changed``     ``Signal(str)`` -> the status chip as one plain line (only
                        wired when the page has no ``state_changed``)
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
                        :data:`SYNC_STATE_REFRESH_MS` and on activation): a
                        scheduled ``--sync`` may have changed the state behind
                        the window's back; cheap reads only
``progress_counts()``   ``(done, total)`` files of the running sync, or None,
                        for the quit question
``can_leave()``         asked before switching away from the page; False keeps
                        it on screen (Impostazioni with unsaved changes)

Pages open the import dialog with ``window.open_import(sources)``.
"""
from __future__ import annotations

import importlib
import logging
from collections.abc import Callable, Sequence
from functools import partial
from pathlib import Path
from typing import Literal, NamedTuple

from PySide6.QtCore import QEvent, QSettings, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import actions, icons, strings
from qtrequestory.ui.app_bar import AppBar
from qtrequestory.ui.contracts import CoreServices
from qtrequestory.ui.import_state import ArchiveWatch
from qtrequestory.ui.quit_dialog import (  # noqa: F401 - JOB_LABELS/build_quit_dialog re-exported
    JOB_LABELS,
    build_quit_dialog,
    confirm_quit_during_job,
    job_label,
)
from qtrequestory.ui.startup import StartupTasks
from qtrequestory.ui.toast import DEFAULT_MS as TOAST_MS
from qtrequestory.ui.toast import Toast
from qtrequestory.ui.workers import JobRunner

log = logging.getLogger(__name__)

STATUS_TIMEOUT_MS = 4000
#: Page key -> its navigation shortcut; also shown in the tab/icon tooltip.
PAGE_SHORTCUTS = {"search": "Ctrl+1", "sync": "Ctrl+2", "settings": "Ctrl+,", "about": "F1"}
SYNC_NOW_SHORTCUT = "Ctrl+Shift+S"
#: Jobs after which every page's ``on_data_changed`` runs — and which closing
#: the window would interrupt, so it asks first.
DATA_JOBS = ("sync", "index", "import", "recycle")
#: How often the pages' ``refresh_sync_state`` runs (the app-bar chip would
#: otherwise stay stale after a scheduled sync until the user opened
#: Sincronizzazione). Slow on purpose: it only re-reads a state file.
SYNC_STATE_REFRESH_MS = 60_000


class PageSpec(NamedTuple):
    """One entry of :data:`PAGES` — a plain ``(key, label, icon, factory, placement)``.

    ``factory(services, runner, window) -> QWidget`` is called once, while the
    window is being built; ``placement`` decides how the app bar offers the
    page: a labelled ``"tab"`` on the left or an ``"icon"`` button (label as
    tooltip) on the right.
    """

    key: str
    label: str
    icon_name: str
    factory: Callable[[CoreServices, JobRunner, "MainWindow"], QWidget]
    placement: Literal["tab", "icon"]


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
    PageSpec("sync", strings.NAV_SYNC, "arrow-sync", page_factory("sync_page", "SyncPage"), "tab"),
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


class MainWindow(QMainWindow):
    """App bar + stack + status bar. Everything else is a page."""

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

        self.setWindowTitle(strings.WINDOW_TITLE)
        self.setWindowIcon(icons.app_icon())
        self.app_bar = AppBar()
        self.stack = QStackedWidget()

        self._build_layout()
        self.toast = Toast(self.centralWidget())
        self._build_pages()
        self._build_shortcuts()
        self.app_bar.page_requested.connect(self.show_page)
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

    def show_toast(self, text: str, tone: str = "neutral", ms: int = TOAST_MS) -> None:
        """A confirmation over the content ("JSON copiato · 157 KB"); see ``ui/toast``."""
        self.toast.show_message(text, tone, ms)

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

    def start_sync(self) -> None:
        """Ctrl+Shift+S, and the wizard's "avvia la prima sincronizzazione"."""
        self.show_page("sync")
        page = self._pages.get("sync")
        if page is not None and self.stack.currentWidget() is not page:
            return  # the page on screen refused to be left (unsaved changes)
        starter = getattr(page, "start_sync", None)
        if callable(starter):
            starter()

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
            if spec.placement == "icon":
                self.app_bar.add_icon_button(spec.key, spec.icon_name, nav_tooltip(spec))
            else:
                self.app_bar.add_tab(spec.key, spec.label, spec.icon_name, nav_tooltip(spec))
        chain = self.app_bar.focus_chain()
        for before, after in zip(chain, chain[1:]):
            QWidget.setTabOrder(before, after)  # the chip was created before the tabs
        for spec in self._specs:
            widget = self._build_page(spec)
            self._pages[spec.key] = widget
            self.stack.addWidget(widget)
        self._connect_page_hooks()
        self._emit_initial_states()

    def _build_page(self, spec: PageSpec) -> QWidget:
        try:
            return spec.factory(self._services, self._runner, self)
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

    def _connect_page_hooks(self) -> None:
        """Wire the optional hooks a page may expose (see the module docstring)."""
        for key, page in self._pages.items():
            state = getattr(page, "state_changed", None)
            summary = getattr(page, "summary_changed", None)
            if state is not None and hasattr(state, "connect"):
                state.connect(self.set_sync_state)
            elif summary is not None and hasattr(summary, "connect"):
                summary.connect(self.set_sync_summary)
            changed = getattr(page, "config_changed", None)
            if changed is not None and hasattr(changed, "connect"):
                # The key is bound here so the broadcast can skip its sender.
                changed.connect(partial(self._broadcast_config, key))

    def _emit_initial_states(self) -> None:
        """Ask each page for its state now that someone listens (Important #9)."""
        for page in self._pages.values():
            emit = getattr(page, "emit_initial_state", None)
            if callable(emit):
                emit()

    def _build_shortcuts(self) -> None:
        bindings: list[tuple[str, Callable[[], None]]] = [
            (sequence, partial(self.show_page, key)) for key, sequence in PAGE_SHORTCUTS.items()
        ]
        bindings.append((SYNC_NOW_SHORTCUT, self.start_sync))
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
        """Ask before abandoning a sync or an index job, then remember the geometry."""
        for name in DATA_JOBS:
            if self._runner.is_running(name) and not confirm_quit_during_job(
                    self, name, self._job_detail(name)):
                event.ignore()
                return
        for name in DATA_JOBS:
            self._runner.cancel(name)
        stored = self.settings()
        stored.setValue("window/geometry", self.saveGeometry())
        stored.setValue("window/state", self.saveState())
        super().closeEvent(event)
