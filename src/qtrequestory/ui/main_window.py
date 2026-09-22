"""The application shell: navigation rail, stacked pages, status bar.

The window itself owns no feature. It builds the pages listed in :data:`PAGES`,
switches between them and offers three services to whichever page is showing:
:meth:`MainWindow.show_page`, :meth:`MainWindow.set_status` and
:meth:`MainWindow.set_sync_summary`.

Adding a page is one tuple in :data:`PAGES` plus one widget — that is the whole
extension mechanism (DESIGN-ui §Navigation: "future Replay / Statistiche / Diff
= one tuple + one widget"). A factory that cannot be imported yet degrades to a
placeholder label, so the shell always starts, whatever state the page modules
are in.

Optional hooks a page may expose (all duck-typed, all optional):

``summary_changed``     ``Signal(str)`` → the right-hand status bar segment
``config_changed``      ``Signal(object)`` → broadcast to every other page's
                        ``on_config_changed(cfg)``
``on_config_changed``   receives that broadcast
``start_sync()``        called for Ctrl+Shift+S and after the first-run wizard
"""
from __future__ import annotations

import importlib
import logging
from collections.abc import Callable, Sequence
from typing import NamedTuple

from PySide6.QtCore import QSettings, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QKeySequence, QPalette, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QSizePolicy,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import icons, strings
from qtrequestory.ui.contracts import CoreServices
from qtrequestory.ui.workers import JobRunner

log = logging.getLogger(__name__)

RAIL_WIDTH = 200
STATUS_TIMEOUT_MS = 4000


class PageSpec(NamedTuple):
    """One entry of :data:`PAGES` — a plain ``(key, label, icon, factory, section)``.

    ``factory(services, runner, window) -> QWidget`` is called once, while the
    window is being built; ``section`` is ``"top"`` or ``"bottom"`` and decides
    which rail group the entry appears in.
    """

    key: str
    label: str
    icon_name: str
    factory: Callable[[CoreServices, JobRunner, "MainWindow"], QWidget]
    section: str


def page_factory(module: str, class_name: str) -> Callable[..., QWidget]:
    """A lazy factory for ``qtrequestory.ui.pages.<module>.<class_name>``.

    The import happens while the window is built, not at module import time, so
    the shell can be tested (and run) before the page modules exist.
    """

    def factory(services: CoreServices, runner: JobRunner, window: MainWindow) -> QWidget:
        page_module = importlib.import_module(f"qtrequestory.ui.pages.{module}")
        return getattr(page_module, class_name)(services, runner, window)

    factory.__name__ = f"make_{module}"
    return factory


#: The v1 pages, in rail order. No disabled placeholders: a page is here only
#: when it exists (DESIGN-ui §Navigation).
PAGES: list[PageSpec] = [
    PageSpec("search", strings.NAV_SEARCH, "search", page_factory("search_page", "SearchPage"), "top"),
    PageSpec("sync", strings.NAV_SYNC, "arrow-sync", page_factory("sync_page", "SyncPage"), "top"),
    PageSpec("settings", strings.NAV_SETTINGS, "settings",
             page_factory("settings_page", "SettingsPage"), "bottom"),
    PageSpec("about", strings.NAV_ABOUT, "info", page_factory("about_page", "AboutPage"), "bottom"),
]


class ClickableLabel(QLabel):
    """The status bar's sync summary: a label that can be clicked."""

    clicked = Signal()

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


def build_quit_dialog(parent: QWidget) -> tuple[QMessageBox, QPushButton]:
    """The "sincronizzazione in corso" question, without showing it.

    Split from :func:`confirm_quit_during_sync` so the wording can be tested
    without a modal event loop.
    """
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle(strings.QUIT_DURING_SYNC_TITLE)
    box.setText(strings.QUIT_DURING_SYNC_TEXT)
    stop = box.addButton(strings.QUIT_STOP, QMessageBox.ButtonRole.AcceptRole)
    keep = box.addButton(strings.QUIT_CONTINUE, QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(keep)
    box.setEscapeButton(keep)
    return box, stop


def confirm_quit_during_sync(parent: QWidget) -> bool:
    """True when the user chose "Interrompi ed esci"."""
    box, stop = build_quit_dialog(parent)
    box.exec()
    return box.clickedButton() is stop


class MainWindow(QMainWindow):
    """Rail + stack + status bar. Everything else is a page."""

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
        self.rail_top = self._make_rail()
        self.rail_bottom = self._make_rail()
        self.stack = QStackedWidget()
        self.sync_summary = ClickableLabel(strings.STATUS_SYNC_SUMMARY_EMPTY)
        self.sync_summary.setToolTip(strings.STATUS_SYNC_SUMMARY_TOOLTIP)

        self._build_layout()
        self._build_pages()
        self._build_shortcuts()
        self.sync_summary.clicked.connect(lambda: self.show_page("sync"))
        self._runner.busy.connect(self._on_job_refused)
        self._restore_geometry()
        if self._pages:
            self.show_page(next(iter(self._pages)))  # the first entry of PAGES

    # -- public API for the pages -----------------------------------------

    def show_page(self, key: str) -> None:
        """Switch to the page registered under ``key``; unknown keys are ignored."""
        page = self._pages.get(key)
        if page is None:
            log.debug("pagina sconosciuta: %s", key)
            return
        self.stack.setCurrentWidget(page)
        for rail in (self.rail_top, self.rail_bottom):
            row = _row_of(rail, key)
            with QSignalBlocker(rail):  # moving the selection must not re-enter
                rail.setCurrentRow(row)
                if row == -1:
                    rail.clearSelection()

    def set_status(self, text: str, ms: int = STATUS_TIMEOUT_MS) -> None:
        """Transient message in the left segment ("Copiato negli appunti…")."""
        self.statusBar().showMessage(text, ms)

    def set_sync_summary(self, text: str) -> None:
        """Permanent right segment ("svil: oggi 11:23 · coll: oggi 11:24")."""
        self.sync_summary.setText(text)

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
        starter = getattr(page, "start_sync", None)
        if callable(starter):
            starter()

    def rerun_wizard(self) -> object | None:
        """Impostazioni → "Riesegui configurazione iniziale"."""
        from qtrequestory.ui import app  # local: app imports this module

        if not app.wizard_available():
            self.set_status(strings.WIZARD_UNAVAILABLE)
            return None
        return app.show_first_run_wizard(self._services, self._runner, self)

    # -- construction ------------------------------------------------------

    def _make_rail(self) -> QListWidget:
        """One rail group: a borderless list that hugs its items.

        Painting it with the *Window* brush instead of the default *Base* one is
        what makes the two groups look like a single panel rather than two white
        boxes — palette-derived, so it follows light and dark on its own (no QSS,
        DESIGN-ui §Visual style).
        """
        rail = QListWidget()
        rail.setFixedWidth(RAIL_WIDTH)
        rail.setFrameShape(QListWidget.Shape.NoFrame)
        rail.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        rail.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        rail.setBackgroundRole(QPalette.ColorRole.Window)
        rail.viewport().setBackgroundRole(QPalette.ColorRole.Window)
        rail.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Maximum)
        rail.currentItemChanged.connect(self._on_rail_selection)
        return rail

    def _build_layout(self) -> None:
        rail_box = QWidget()
        rail_layout = QVBoxLayout(rail_box)
        rail_layout.setContentsMargins(0, 0, 0, 0)
        rail_layout.setSpacing(0)
        rail_layout.addWidget(self.rail_top)
        rail_layout.addStretch(1)
        rail_layout.addWidget(self.rail_bottom)
        rail_box.setFixedWidth(RAIL_WIDTH)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(rail_box)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.statusBar().addPermanentWidget(self.sync_summary)

    def _build_pages(self) -> None:
        for spec in self._specs:
            widget = self._build_page(spec)
            self._pages[spec.key] = widget
            self.stack.addWidget(widget)
            rail = self.rail_top if spec.section == "top" else self.rail_bottom
            item = QListWidgetItem(icons.icon(spec.icon_name), spec.label)
            item.setData(Qt.ItemDataRole.UserRole, spec.key)
            rail.addItem(item)
        self._connect_page_hooks()

    def _build_page(self, spec: PageSpec) -> QWidget:
        try:
            return spec.factory(self._services, self._runner, self)
        except ModuleNotFoundError as exc:  # a sibling task has not landed yet
            log.info("pagina %s non disponibile (%s)", spec.key, exc)
        except Exception:  # noqa: BLE001 - a broken page must not break the shell
            log.exception("pagina %s non disponibile", spec.key)
        placeholder = QLabel(strings.PAGE_UNAVAILABLE.format(label=spec.label))
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setWordWrap(True)
        return placeholder

    def _connect_page_hooks(self) -> None:
        for page in self._pages.values():
            summary = getattr(page, "summary_changed", None)
            if summary is not None and hasattr(summary, "connect"):
                summary.connect(self.set_sync_summary)
            changed = getattr(page, "config_changed", None)
            if changed is not None and hasattr(changed, "connect"):
                changed.connect(self._broadcast_config)

    def _build_shortcuts(self) -> None:
        bindings: list[tuple[str, Callable[[], None]]] = [
            ("Ctrl+1", lambda: self.show_page("search")),
            ("Ctrl+2", lambda: self.show_page("sync")),
            ("Ctrl+,", lambda: self.show_page("settings")),
            ("Ctrl+Shift+S", self.start_sync),
        ]
        for sequence, slot in bindings:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(slot)
            self.shortcuts[sequence] = shortcut

    # -- reactions ---------------------------------------------------------

    def _on_rail_selection(self, current: QListWidgetItem | None, _previous=None) -> None:
        if current is not None:
            self.show_page(current.data(Qt.ItemDataRole.UserRole))

    def _on_job_refused(self, name: str) -> None:
        self.set_status(strings.STATUS_BUSY.format(name=name))

    def _broadcast_config(self, cfg: object) -> None:
        """Impostazioni saved: let Ricerca and Sincronizzazione reload."""
        for page in self._pages.values():
            handler = getattr(page, "on_config_changed", None)
            if callable(handler):
                handler(cfg)

    # -- window state ------------------------------------------------------

    def settings(self) -> QSettings:
        return QSettings(strings.ORG_NAME, strings.APP_NAME)

    def _restore_geometry(self) -> None:
        stored = self.settings()
        geometry = stored.value("window/geometry")
        state = stored.value("window/state")
        if geometry is not None:
            self.restoreGeometry(geometry)
        if state is not None:
            self.restoreState(state)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        """Ask before abandoning a running sync, then remember the geometry."""
        if self._runner.is_running("sync") and not confirm_quit_during_sync(self):
            event.ignore()
            return
        self._runner.cancel("sync")
        stored = self.settings()
        stored.setValue("window/geometry", self.saveGeometry())
        stored.setValue("window/state", self.saveState())
        super().closeEvent(event)


def _row_of(rail: QListWidget, key: str) -> int:
    for row in range(rail.count()):
        if rail.item(row).data(Qt.ItemDataRole.UserRole) == key:
            return row
    return -1
