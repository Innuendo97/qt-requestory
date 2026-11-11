"""Ricerca's "Genera documento": the document (PDF, or the HTML of an e-mail)
of the calls selected in the results, generated from THOSE calls as logged.

**Entry points.** A button in the results' action line (before [Raggruppa
per FDI]), an entry of the row menu (and the only entry of an FDI group
row's menu) and ``Ctrl+G``. "Genera documento", "Genera 3 documenti" when
several calls are selected; an FDI group row (clicked: nothing selected)
means every call of that group on screen. With more than one enabled
generator the user picks one from a small menu ("su coll", "su svil"): first
the environment the calls come from when it is a generator, else the Genera
tab's generator (``genera_calls.generator_order``); ``Ctrl+G`` pops that
menu up. With one generator there is no menu; with none (or no Genera tab)
the button is hidden and the menu entry disabled, its tooltip says why.

**The run is the Genera tab's.** :meth:`SearchGenerate.generate` hands the
calls to ``GeneraPage.generate_calls`` (the tab's headers and folder, its
confirmation above 20 calls, its exclusive job): the tab shows the progress,
the rows and "Riprova i non riusciti". While a Genera run goes the entry
points are disabled, with a tooltip saying so.

**How it ended**, in a toast (never a dialog):

* one document → opened with its default application
  (``ExtractApi.open_file``), "Salvato <file> in <cartella>" · [Apri cartella];
* several calls → the counts · [Apri cartella] · [Vedi esiti] (the Genera tab);
* nothing generated → the reason · [Vedi esiti].

Opening goes through ``ExtractApi`` (the fake records it in tests: nothing is
ever launched). No payload, header or link reaches a toast or the status bar.
"""
from __future__ import annotations

from collections.abc import Sequence
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QObject, Qt, Slot
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QMenu, QPushButton

from qtrequestory.ui import icons, strings
from qtrequestory.ui.contracts import BatchReport, SearchHit
from qtrequestory.ui.pages.genera_outcomes import STATUS_LOOK, report_summary
from qtrequestory.ui.pages.genera_retry import RETRY_STATUSES
from qtrequestory.ui.pages.search_icons import ThemedIcons
from qtrequestory.ui.workers import GENERA_JOB

if TYPE_CHECKING:
    from qtrequestory.ui.pages.search_page import SearchPage

__all__ = ["GENERATE_SHORTCUT", "ICON", "SearchGenerate"]

GENERATE_SHORTCUT = "Ctrl+G"
#: The Genera tab's own icon: this is a Genera run.
ICON = "document-multiple"
GENERA_PAGE = "genera"


class SearchGenerate(QObject):
    """The entry points and the toasts (module docstring); owned by the page."""

    def __init__(self, page: SearchPage) -> None:
        super().__init__(page)
        self._page = page
        self._connected: object | None = None  # the Genera page whose running_changed we follow
        self.button = QPushButton(strings.GENERA_CALLS_ACTION_ONE)
        ThemedIcons(self.button).set(self.button, ICON, "muted")
        self.button.clicked.connect(lambda _c=False: self._on_button())
        self.menu = QMenu(self.button)
        self.menu.setToolTipsVisible(True)
        self.menu.aboutToShow.connect(self.refresh_menu)
        page.meta.add_action(self.button)

        selection = page.view.selectionModel()
        selection.selectionChanged.connect(lambda *_a: self.refresh())
        selection.currentChanged.connect(lambda *_a: self.refresh())  # a group row: no selection
        page.model.modelReset.connect(self.refresh)
        page.model.layoutChanged.connect(lambda *_a: self.refresh())
        # bound methods of this QObject, never lambdas: the runner and the Genera page
        # outlive this page, and Qt drops these connections when it is deleted
        page.runner.job_finished.connect(self._on_job_finished)
        page.installEventFilter(self)  # shown again: Impostazioni may have changed the generators
        self.shortcut = QShortcut(QKeySequence(GENERATE_SHORTCUT), page)
        self.shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.shortcut.activated.connect(self._on_shortcut)
        self.refresh()

    # -- what it acts on ---------------------------------------------------------------------

    def hits(self) -> list[SearchHit]:
        """The selected calls; with none, the calls of the current FDI group row."""
        view = self._page.view
        return view.selected_hits() or view.group_hits(view.currentIndex())

    def generators(self, hits: Sequence[SearchHit]) -> list[str]:
        """The enabled generators, the default first ([] without the Genera tab)."""
        genera = self._genera()
        return list(genera.calls_generators(hits)) if genera is not None else []

    def state(self, hits: Sequence[SearchHit], generators: Sequence[str]) -> tuple[bool, str]:
        """``(enabled, tooltip)`` of the entry points for ``hits``."""
        genera = self._genera()
        if genera is None:
            return False, strings.GENERA_CALLS_UNAVAILABLE
        if not generators:
            return False, strings.GENERA_CALLS_TIP_NO_GENERATOR
        if genera.is_running():
            return False, strings.GENERA_CALLS_TIP_RUNNING
        if not hits:
            return False, strings.GENERA_CALLS_TIP_NOTHING
        tip = strings.GENERA_CALLS_TIP.format(shortcut=GENERATE_SHORTCUT)
        note = genera.headers_note() if callable(getattr(genera, "headers_note", None)) else ""
        return True, f"{tip}\n{note}" if note else tip

    @staticmethod
    def label(n: int) -> str:
        return strings.GENERA_CALLS_ACTION_ONE if n <= 1 else strings.GENERA_CALLS_ACTION_N.format(n=n)

    # -- the entry points ------------------------------------------------------------------------

    def refresh(self) -> None:
        """The button after a selection, a run, a new configuration."""
        hits = self.hits()
        generators = self.generators(hits)
        enabled, tip = self.state(hits, generators)
        self.button.setVisible(bool(generators))
        self.button.setEnabled(enabled)
        self.button.setToolTip(tip)
        self.button.setText(self.label(len(hits)))
        wanted = self.menu if len(generators) > 1 else None
        if self.button.menu() is not wanted:
            self.button.setMenu(wanted)

    def refresh_menu(self) -> None:
        """The button's menu: one entry per generator, for the calls of now."""
        hits = self.hits()
        self.menu.clear()
        self._fill(self.menu, hits, self.generators(hits))

    def add_entry(self, menu: QMenu, hits: Sequence[SearchHit]):
        """The "Genera documento" entry of a row (or group row) menu."""
        hits = list(hits)
        generators = self.generators(hits)
        enabled, tip = self.state(hits, generators)
        label = self.label(len(hits))
        if enabled and len(generators) > 1:
            sub = menu.addMenu(label)
            sub.setToolTipsVisible(True)
            self._fill(sub, hits, generators)
            action = sub.menuAction()
        else:
            action = menu.addAction(label)
            if generators:
                action.triggered.connect(lambda _c=False: self.generate(generators[0], hits))
        action.setEnabled(enabled)
        action.setToolTip(tip)
        action.setIcon(icons.icon(ICON))
        action.setProperty("iconName", ICON)
        if len(generators) <= 1:
            action.setShortcut(QKeySequence(GENERATE_SHORTCUT))
            action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)  # display only
            action.setShortcutVisibleInContextMenu(True)
        return action

    def group_menu(self, group) -> QMenu:
        """The menu of an FDI group row: generate its calls."""
        menu = QMenu(self._page)
        menu.setToolTipsVisible(True)
        self.add_entry(menu, self._page.view.group_hits(group))
        return menu

    def _fill(self, menu: QMenu, hits: list[SearchHit], generators: Sequence[str]) -> None:
        for name in generators:
            action = menu.addAction(strings.GENERA_CALLS_ON_ENV.format(env=name))
            action.triggered.connect(lambda _c=False, name=name: self.generate(name, hits))
        if menu.actions():
            menu.setActiveAction(menu.actions()[0])

    def _on_button(self) -> None:
        # with a menu Qt opens it on press; without, one generator: go
        hits = self.hits()
        generators = self.generators(hits)
        if self.state(hits, generators)[0] and len(generators) == 1:
            self.generate(generators[0], hits)

    def _on_shortcut(self) -> None:
        hits = self.hits()
        generators = self.generators(hits)
        enabled, tip = self.state(hits, generators)
        if not enabled:
            self._page.set_status(tip)
        elif len(generators) == 1:
            self.generate(generators[0], hits)
        else:
            self._popup()

    def _popup(self) -> None:
        """Ctrl+G with several generators: the menu under the button, the default active."""
        self.refresh_menu()
        self.menu.popup(self.button.mapToGlobal(self.button.rect().bottomLeft()))
        if self.menu.actions():
            self.menu.setActiveAction(self.menu.actions()[0])

    # -- the run ------------------------------------------------------------------------------------

    def generate(self, generator: str, hits: Sequence[SearchHit] | None = None) -> None:
        """Send ``hits`` (default: :meth:`hits`) as logged to ``generator``."""
        hits = list(hits) if hits is not None else self.hits()
        genera = self._genera()
        if genera is None:
            self._toast(strings.GENERA_CALLS_UNAVAILABLE, "warn")
            return
        started, reason = genera.generate_calls(hits, generator, parent=self._page,
                                                notify=self._on_done)
        if started:
            n = len(set(hits))
            text = (strings.GENERA_CALLS_STARTED_ONE.format(env=generator) if n == 1
                    else strings.GENERA_CALLS_STARTED.format(n=n, env=generator))
            self._toast(text, "neutral")
        elif reason:
            self._toast(reason, "warn", [(strings.GENERA_CALLS_OPEN_GENERA, self._show_genera)])
        self.refresh()

    def _on_done(self, report: BatchReport | None, problem: str) -> None:
        """How the run ended (module docstring)."""
        see = (strings.GENERA_CALLS_SEE_RESULTS, self._show_genera)
        if report is None:
            self._toast(strings.GENERA_REFUSED.format(reason=problem), "warn", [see])
            return
        outcomes = report.outcomes
        saved = [o for o in outcomes if o.status == "ok" and o.files]
        if not saved:
            first = next((o for o in outcomes if o.status != "ok"), None)
            reason = (first.reason or STATUS_LOOK.get(first.status, ("", first.status, ""))[1]
                      ) if first is not None else strings.GENERA_SUM_NOTHING
            text = (strings.GENERA_CALLS_NOTHING.format(reason=reason) if len(outcomes) <= 1 else
                    strings.GENERA_CALLS_NOTHING_MANY.format(
                        summary=report_summary(report, with_folder=False), reason=reason))
            self._toast(text, "warn", [see])
        elif len(outcomes) == 1:
            document = saved[0].files[0]
            text = (strings.GENERA_CALLS_SAVED.format(name=document.name, folder=document.parent.name)
                    if self._open_file(document)
                    else strings.GENERA_CALLS_SAVED_NOT_OPENED.format(name=document.name))
            self._toast(text, "ok", [(strings.BTN_OPEN_FOLDER, partial(self._open_folder, document.parent))])
        else:
            words = strings.GENERA_TOAST_STOPPED if report.cancelled else strings.GENERA_TOAST_DONE
            unfinished = any(o.status in RETRY_STATUSES for o in outcomes)
            self._toast(words.format(summary=report_summary(report, with_folder=False)),
                        "warn" if unfinished else "ok",
                        [(strings.BTN_OPEN_FOLDER, partial(self._open_folder, report.run_dir)), see])

    # -- the window ---------------------------------------------------------------------------------

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt naming
        if watched is self._page and event.type() == QEvent.Type.Show:
            self.refresh()
        return False

    def _genera(self):
        """The Genera page, when the window has one that takes exact calls."""
        getter = getattr(self._page._window, "page", None)  # noqa: SLF001 - the page's window
        genera = getter(GENERA_PAGE) if callable(getter) else None
        if genera is None or not callable(getattr(genera, "generate_calls", None)):
            return None
        if self._connected is not genera:
            self._connected = genera
            genera.running_changed.connect(self._on_genera_running)  # bound: see __init__
        return genera

    @Slot(str, bool)
    def _on_job_finished(self, name: str, _ok: bool) -> None:
        if name == GENERA_JOB:
            self.refresh()

    @Slot(bool)
    def _on_genera_running(self, _running: bool) -> None:
        self.refresh()

    def _toast(self, text: str, tone: str, actions: list | None = None) -> None:
        toast = getattr(self._page._window, "show_toast", None)  # noqa: SLF001
        if actions and callable(toast):
            toast(text, tone, actions=actions)
        else:
            self._page.show_toast(text, tone)

    def _show_genera(self) -> None:
        shower = getattr(self._page._window, "show_page", None)  # noqa: SLF001
        if callable(shower):
            shower(GENERA_PAGE)

    def _open_file(self, path: Path) -> bool:
        try:
            self._page.services.extract.open_file(path)
        except OSError:
            return False
        return True

    def _open_folder(self, path: Path) -> None:
        try:
            if path.is_dir():
                self._page.services.extract.open_folder(path)
                return
        except OSError:
            pass
        self._page.set_status(strings.GENERA_FOLDER_MISSING.format(name=path.name))
