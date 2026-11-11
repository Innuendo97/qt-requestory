"""The Genera tab: documents from template keys, the Quadient list or FDIs,
in one screen with one button (spec "Genera"; redesign of 1.5.0).

**Two panes.** On a window at least :data:`WIDE_MIN` px wide::

    +-- setup (``genera_setup``) --+-- results (``genera_results``) --------------+
    | Cosa generare  [TK|Elenco|FDI]| Esiti  Generazione finita · svil_…  [Riprova] |
    |  the current source           | (progress while running)                      |
    |  ───────                      | (Tutti 5) (✓ 3 generati) (✕ 2 non riusciti)   |
    |  Dove                         | +-------------------------------------------+ |
    |  ───────                      | | rows, or what will happen before a run     | |
    |  ▸ Header  7 inviati          | |                                           | |
    | [x] email  [ ] zip            | |                                           | |
    | [   Genera 16 documenti   ]   | +-------------------------------------------+ |
    +-------------------------------+-----------------------------------------------+

The setup pane has a comfortable fixed width (:func:`setup_width`); the
results take the rest and are always on screen, so pressing Genera never
needs a scroll to see what happens. Narrower than :data:`WIDE_MIN` the panes
stack (setup on top, results under it) and the button stays pinned at the
bottom of the setup pane. Nothing scrolls the page itself.

**The flow** (``genera_run``): the whole run is ONE exclusive job
(``GENERA_JOB``): its events are a live preview, its ``BatchReport`` the
truth. Above ``CONFIRM_ABOVE`` CALLS the run is confirmed first, in Italian,
the buttons saying what they do; with FDIs the count is known only from the
logs, so a short job of the same name (``batch_count``: reads only) looks
them up first. A ``ValueError`` from a job is the core's Italian refusal and
is said inline, never in a dialog. Ctrl+Invio generates when the button can;
Enter does too on the focused button.

The two panes never give way to the "Nessun generatore" state while a run
goes or while its results are on screen: a generator disabled in Impostazioni
meanwhile is a problem line under the button, and the engine stops sending.

Nothing of Genera touches the disk or builds the Officina service until the
tab is first shown (``GeneraPresenter.activate``) — or until Ricerca's
"Genera documento" sends its calls through this page (``genera_calls``:
the same run, rows and retry; :attr:`GeneraPage.running_changed` tells
Ricerca when a run starts and ends).

No payload, header value or link reaches a status line or a toast here.
"""
from __future__ import annotations

from PySide6.QtCore import QModelIndex, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QBoxLayout, QLayout, QStackedWidget, QVBoxLayout, QWidget

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import BatchReport, CoreServices
from qtrequestory.ui.pages import officina_dialogs as ask
from qtrequestory.ui.pages.genera_calls import GeneraCalls
from qtrequestory.ui.pages.genera_form import fill_combo
from qtrequestory.ui.pages.genera_presenter import GeneraPresenter
from qtrequestory.ui.pages.genera_results import GeneraResults
from qtrequestory.ui.pages.genera_run import GeneraRun
from qtrequestory.ui.pages.genera_setup import GeneraSetup
from qtrequestory.ui.pages.mirror_banner import open_settings_section
from qtrequestory.ui.pages.search_states import EmptyState
from qtrequestory.ui.workers import JobRunner

__all__ = ["GENERATE_SHORTCUTS", "WIDE_MIN", "GeneraPage", "setup_width"]

GENERATE_SHORTCUTS = ("Ctrl+Return", "Ctrl+Enter")
#: The Impostazioni section with the generators.
OFFICINA_SECTION = "officina"
#: Below this page width the panes stack.
WIDE_MIN = 1000
#: The setup pane's width: about a third of the page, within these bounds.
SETUP_MIN, SETUP_MAX = 400, 480
#: Stacked: how the height is shared between setup and results.
STACKED_STRETCH = (3, 2)
_UNBOUNDED = 16_777_215  # QWIDGETSIZE_MAX


def setup_width(page_width: int) -> int:
    return max(SETUP_MIN, min(SETUP_MAX, round(page_width * 0.32)))


class GeneraPage(QWidget, GeneraRun, GeneraCalls):
    """See the module docstring; the run flow is :class:`GeneraRun` (``genera_run``),
    the exact calls of Ricerca :class:`GeneraCalls` (``genera_calls``)."""

    #: True when a run (or the lookup of its count) starts, False when it ends.
    running_changed = Signal(bool)

    def __init__(self, services: CoreServices, runner: JobRunner, window=None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services, self.runner, self._window = services, runner, window
        self.presenter = GeneraPresenter(services, self)
        #: The last run's report (None before any, or after a refusal).
        self.report: BatchReport | None = None
        self._job = None
        self._running = False   # a run, or the lookup of its count, is going
        self._stopping = False
        self._quitting = False
        self._run_env = ""
        self._run_generator = ""
        self._counted: int | None = None
        self._last_request = None   # the request of ``report`` (an exact-call retry keeps its logs, HTML)
        self._notify = None         # the caller told how the current run ends (genera_calls)
        self._wide: bool | None = None

        self.no_generator = EmptyState("settings")
        self.no_generator.set_text(strings.GENERA_NO_GENERATOR_TITLE, [strings.GENERA_NO_GENERATOR_HINT])
        self.no_generator.add_button(strings.GENERA_NO_GENERATOR_BTN,
                                     lambda: open_settings_section(self._window, OFFICINA_SECTION),
                                     primary=True)
        self.setup = GeneraSetup(self.presenter, browse_destination=self._browse_destination,
                                 follow_generator=self._follow_generator, reset_headers=self._reset_headers)
        self.results = GeneraResults()
        self._aliases()
        self.form = QWidget()  # the two panes
        self._panes = QBoxLayout(QBoxLayout.Direction.LeftToRight, self.form)
        self._panes.setContentsMargins(0, 0, 0, 0)
        self._panes.setSpacing(0)
        self._panes.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)  # see _arrange
        self._panes.addWidget(self.setup)
        self._panes.addWidget(self.results, 1)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.no_generator)
        self.stack.addWidget(self.form)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.stack)

        self._wire()
        self._tab_order()
        for sequence in GENERATE_SHORTCUTS:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(self._shortcut_generate)
        self._arrange(self.width())
        self.render()

    # -- construction ------------------------------------------------------------------

    def _aliases(self) -> None:
        """The widgets the run flow, Ricerca and the tests reach by name."""
        s = self.setup
        self.source = s.source
        self.action_bar = bar = s.actions
        self.zip_box, self.html_box, self.start_button = bar.zip_box, bar.html_box, bar.start_button
        self.problem_label = bar.problem_label
        self.progress_bar, self.progress_label = self.results.progress_bar, self.results.progress_label
        self.generator_combo, self.source_combo = s.where.generator_combo, s.where.source_combo
        self.destination, self.browse_destination = s.where.destination, s.where.browse_destination
        h = s.headers
        self.headers_toggle, self.headers_panel, self.header_table = h.toggle, h.panel, h.table
        self.add_header_button, self.remove_header_button = h.add_button, h.remove_button
        self.reset_headers_button = h.reset_button

    def _wire(self) -> None:
        p = self.presenter
        p.changed.connect(self.render)
        self.generator_combo.currentTextChanged.connect(lambda t: p.set_generator(t) if t else None)
        self.source_combo.currentTextChanged.connect(lambda t: p.set_source_env(t) if t else None)
        self.zip_box.toggled.connect(p.set_make_zip)
        self.html_box.toggled.connect(p.set_save_html)
        self.header_table.changed.connect(self._on_headers_edited)
        self.add_header_button.clicked.connect(lambda _c=False: self._reveal_current_header())
        self.headers_toggle.toggled.connect(lambda on: on and QTimer.singleShot(0, self._reveal_headers))
        self.start_button.clicked.connect(lambda _c=False: self._on_button())
        r = self.results
        r.retry_requested.connect(self.retry)
        r.open_requested.connect(self._open_folder)
        r.open_file_requested.connect(self._open_document)
        r.open_folder_requested.connect(self._open_document_folder)
        r.copy_requested.connect(self._copy)

    def _tab_order(self) -> None:
        s, w, r = self.source, self.setup.where, self.results
        chain = [*s.mode_buttons.values(), s.keys_edit, s.browse_elenco_button, s.filter_edit,
                 s.all_button, s.none_button, s.package_list, s.fdi_edit,
                 self.generator_combo, self.source_combo, w.follow_button, self.browse_destination,
                 self.headers_toggle, self.reset_headers_button, self.header_table,
                 self.add_header_button, self.remove_header_button, self.html_box, self.zip_box,
                 self.start_button, r.retry_button, r.open_folder_button,
                 *(r.chips.chip(k) for k in r.chips._chips), r.table]
        for before, after in zip(chain, chain[1:]):
            QWidget.setTabOrder(before, after)

    # -- layout: two panes or stacked -------------------------------------------------------

    def is_wide(self) -> bool:
        return bool(self._wide)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._arrange(event.size().width())

    def _arrange(self, width: int) -> None:
        """Side by side when both panes fit at ``width``, else stacked. The panes'
        layout never sets the page's minimum width (``SetNoConstraint``): the
        sum of the two panes must not stop the window from getting narrow
        enough to stack them; stacked, the wider pane's minimum is the page's."""
        setup_w = setup_width(width)
        needed = setup_w + self.results.minimumSizeHint().width()
        wide = width >= max(WIDE_MIN, needed)
        self.form.setMinimumWidth(max(self.setup.minimumSizeHint().width(),
                                      self.results.minimumSizeHint().width()))
        if wide:
            self.setup.setFixedWidth(setup_w)
        if wide == self._wide:
            return
        self._wide = wide
        if wide:
            self._panes.setDirection(QBoxLayout.Direction.LeftToRight)
            self._panes.setStretchFactor(self.setup, 0)
            self._panes.setStretchFactor(self.results, 1)
        else:
            self.setup.setMinimumWidth(0)
            self.setup.setMaximumWidth(_UNBOUNDED)
            self._panes.setDirection(QBoxLayout.Direction.TopToBottom)
            self._panes.setStretchFactor(self.setup, STACKED_STRETCH[0])
            self._panes.setStretchFactor(self.results, STACKED_STRETCH[1])
        self.setup.set_stacked(not wide)

    # -- shell hooks -----------------------------------------------------------------------

    def initial_focus(self) -> QWidget:
        """Where typing goes: the current source's field."""
        target = self.source.first_field()
        target.setFocus(Qt.FocusReason.OtherFocusReason)
        return target

    def on_config_changed(self, _cfg) -> None:
        """Impostazioni saved: generators, environments and (if untouched) headers."""
        self.presenter.reload_config()

    def on_quit(self) -> None:
        """The window is closing: no run starts any more (after a count, say)."""
        self._quitting = True

    def is_running(self) -> bool:
        return self._running

    def showEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().showEvent(event)
        if not self.presenter.activated:  # the first time: the disk and the service, now
            self.presenter.activate()
        QTimer.singleShot(0, self._focus_if_outside)

    def _focus_if_outside(self) -> None:
        focus = self.focusWidget()
        if self.isVisible() and not self._running and (focus is None or not self.isAncestorOf(focus)):
            self.source.first_field().setFocus(Qt.FocusReason.OtherFocusReason)

    # -- rendering -----------------------------------------------------------------------------

    def render(self) -> None:
        p = self.presenter
        # a run, or its results, stay on screen even if the generator went away meanwhile
        show_form = p.has_generator() or self._running or self.report is not None
        self.stack.setCurrentWidget(self.form if show_form else self.no_generator)
        fill_combo(self.generator_combo, p.generators, p.generator)
        fill_combo(self.source_combo, p.envs, p.source_env)
        note, can_follow = p.source_note()
        self.setup.where.show_source_note(note, p.generator if can_follow else "")
        self.destination.setText(str(p.destination) if p.destination is not None else "")
        if self.header_table.rows() != p.header_rows:  # Ripristina, a new profile, the first show
            self.header_table.set_pairs(p.header_rows)
            self._show_header_problems()
        self.setup.show_headers_state(p.headers_sent_text(), p.headers_modified_text())
        for box, on in ((self.zip_box, p.make_zip), (self.html_box, p.save_html)):
            if box.isChecked() != on:
                box.blockSignals(True)
                box.setChecked(on)
                box.blockSignals(False)
        self.source.render()
        self.results.show_plan(p.plan_lines())
        if not self._running:
            self.action_bar.show_idle(p.start_text(), p.problems())
        self._arrange(self.width())  # a run's buttons may have widened the results' minimum

    def _show_header_problems(self) -> None:
        entries = self.header_table.entries()
        problems = self.presenter.header_row_problems()
        self.header_table.show_problems({row: found for (row, _pair), found in zip(entries, problems)})

    def _on_headers_edited(self) -> None:
        self.presenter.set_header_rows(self.header_table.rows())
        self._show_header_problems()

    def _reset_headers(self) -> None:
        self.presenter.reset_headers()
        self.header_table.set_pairs(self.presenter.header_rows)
        self._show_header_problems()
        self.render()

    def _reveal_headers(self) -> None:
        self.setup.scroll.widget().layout().activate()
        self.setup.reveal(self.setup.headers)

    def _reveal_current_header(self) -> None:
        """After "Aggiungi": the setup pane scrolls to the new row, whose name
        cell is already open for typing (``GeneraHeaderTable.add_and_edit``)."""
        table = self.header_table
        self.setup.scroll.widget().layout().activate()
        index: QModelIndex = table.currentIndex()
        rect = table.visualRect(index) if index.isValid() else table.viewport().rect()
        self.setup.reveal(table.viewport(), rect)

    def _follow_generator(self) -> None:
        """[Usa i log di svil]: the payloads from the generator's own logs again."""
        self.presenter.set_source_env(self.presenter.generator)

    def _browse_destination(self) -> None:
        chosen = ask.ask_folder(self, strings.GENERA_DESTINATION_PICK, self.presenter.destination)
        if chosen is not None:
            self.presenter.set_destination(chosen)
