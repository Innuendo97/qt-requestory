"""The Genera tab: documents from template keys, the Quadient list or FDIs,
in one screen with one button (spec "Genera"; plan Task 5).

What scrolls, top to bottom:

1. the page title;
2. "Cosa generare" (``genera_source``): Template key · Elenco · FDI;
3. "Dove" (``genera_form``): the generator ("Genera su"), the logs the
   payloads come from ("Chiamate da", following the generator until
   changed) and the folder;
4. the headers (``genera_form``, ``genera_headers``), collapsed to one line
   ("Header · 6 inviati · 1 modificato"), the full table of what is sent;
5. the results (``genera_results``) — scrolled into view when a run starts
   and when it ends.

Pinned under it, always visible (``genera_actions``): the two options (zip,
HTML), **the** button, whose text says what it will do ("Genera 12
documenti"), the first problem in plain Italian right under it while it
cannot; during a run it is [Interrompi], next to the progress ("Cerco le
chiamate…" until the total is known, then "n di m").

The whole run is ONE exclusive job (``GENERA_JOB``): its events are a live
preview, its ``BatchReport`` the truth. Above ``CONFIRM_ABOVE`` CALLS the run
is confirmed first, naming the count and the environment; with FDIs the
count is known only from the logs, so a short job of the same name
(``batch_count``: reads only) looks them up first, under the same
"Cerco le chiamate…" and the same [Interrompi]. A ``ValueError`` from a job
is the core's Italian refusal and is said inline, never in a dialog.
Ctrl+Invio generates when the button can. The flow lives in ``genera_run``.

The form never gives way to the "Nessun generatore" state while a run goes
or while its results are on screen: a generator disabled in Impostazioni
meanwhile is a problem line under the button, and the engine stops sending.

Nothing of Genera touches the disk or builds the Officina service until the
tab is first shown (``GeneraPresenter.activate``).

No payload, header value or link reaches a status line or a toast here.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QFrame, QLabel, QScrollArea, QStackedWidget, QVBoxLayout, QWidget

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import BatchReport, CoreServices
from qtrequestory.ui.pages import officina_dialogs as ask
from qtrequestory.ui.pages.genera_actions import GeneraActionBar
from qtrequestory.ui.pages.genera_form import HeadersCard, WhereCard, fill_combo
from qtrequestory.ui.pages.genera_presenter import GeneraPresenter
from qtrequestory.ui.pages.genera_results import GeneraResults
from qtrequestory.ui.pages.genera_run import GeneraRun
from qtrequestory.ui.pages.genera_source import GeneraSource
from qtrequestory.ui.pages.mirror_banner import open_settings_section
from qtrequestory.ui.pages.search_states import EmptyState
from qtrequestory.ui.workers import JobRunner

__all__ = ["GENERATE_SHORTCUTS", "GeneraPage"]

GENERATE_SHORTCUTS = ("Ctrl+Return", "Ctrl+Enter")
#: The Impostazioni section with the generators.
OFFICINA_SECTION = "officina"


class GeneraPage(QWidget, GeneraRun):
    """See the module docstring; the run flow is :class:`GeneraRun` (``genera_run``)."""

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
        self._counted: int | None = None

        title = QLabel(strings.GENERA_TITLE)
        theme.set_role(title, "pageTitle")
        self.no_generator = EmptyState("settings")
        self.no_generator.set_text(strings.GENERA_NO_GENERATOR_TITLE, [strings.GENERA_NO_GENERATOR_HINT])
        self.no_generator.add_button(strings.GENERA_NO_GENERATOR_BTN,
                                     lambda: open_settings_section(self._window, OFFICINA_SECTION),
                                     primary=True)
        self.form = self._build_form()
        self.stack = QStackedWidget()
        self.stack.addWidget(self.no_generator)
        self.stack.addWidget(self.form)

        content = QWidget()
        column = QVBoxLayout(content)
        column.setContentsMargins(theme.SPACE[4], theme.SPACE[3], theme.SPACE[4], theme.SPACE[3])
        column.setSpacing(theme.SPACE[2])
        column.addWidget(title)
        column.addWidget(self.stack, 1)
        self._scroll = scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(scroll, 1)
        outer.addWidget(self.action_bar)

        self._wire()
        self._tab_order()
        for sequence in GENERATE_SHORTCUTS:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(self._shortcut_generate)
        self.render()

    # -- construction ------------------------------------------------------------------

    def _build_form(self) -> QWidget:
        self.source = GeneraSource(self.presenter)
        where = self._where_card()
        headers = self._headers_card()
        self.action_bar = bar = GeneraActionBar()
        self.zip_box, self.html_box, self.start_button = bar.zip_box, bar.html_box, bar.start_button
        self.progress_bar, self.progress_label = bar.progress_bar, bar.progress_label
        self.problem_label = bar.problem_label
        self.results = GeneraResults()

        form = QWidget()
        layout = QVBoxLayout(form)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE[2])
        layout.addWidget(self.source)
        layout.addWidget(where)
        layout.addWidget(headers)
        layout.addSpacing(theme.SPACE[2])
        layout.addWidget(self.results, 1)
        self._where, self._headers = where, headers
        return form

    def _where_card(self) -> WhereCard:
        card = WhereCard(self._browse_destination)
        self.generator_combo, self.source_combo = card.generator_combo, card.source_combo
        self.destination, self.browse_destination = card.destination, card.browse_destination
        return card

    def _headers_card(self) -> HeadersCard:
        card = HeadersCard(self._reset_headers)
        self.headers_toggle, self.headers_panel, self.header_table = card.toggle, card.panel, card.table
        self.add_header_button, self.remove_header_button = card.add_button, card.remove_button
        self.reset_headers_button = card.reset_button
        return card

    def _wire(self) -> None:
        p = self.presenter
        p.changed.connect(self.render)
        self.generator_combo.currentTextChanged.connect(lambda t: p.set_generator(t) if t else None)
        self.source_combo.currentTextChanged.connect(lambda t: p.set_source_env(t) if t else None)
        self.zip_box.toggled.connect(p.set_make_zip)
        self.html_box.toggled.connect(p.set_save_html)
        self.header_table.changed.connect(self._on_headers_edited)
        self.start_button.clicked.connect(lambda _c=False: self._on_button())
        self.results.retry_requested.connect(self.retry)
        self.results.open_requested.connect(self._open_folder)

    def _tab_order(self) -> None:
        s = self.source
        chain = [*s.mode_buttons.values(), s.keys_edit, s.elenco_path, s.browse_elenco_button,
                 s.filter_edit, s.all_button, s.none_button, s.package_list, s.fdi_edit,
                 self.generator_combo, self.source_combo, self.browse_destination,
                 self.headers_toggle, self.header_table, self.add_header_button,
                 self.remove_header_button, self.reset_headers_button, self.zip_box, self.html_box,
                 self.start_button, self.results.only_failed, self.results.retry_button,
                 self.results.open_folder_button, self.results.table]
        for before, after in zip(chain, chain[1:]):
            QWidget.setTabOrder(before, after)

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
        self.action_bar.setVisible(show_form)
        if not show_form:
            self._scroll.verticalScrollBar().setValue(0)  # the empty state starts at the title
        fill_combo(self.generator_combo, p.generators, p.generator)
        fill_combo(self.source_combo, p.envs, p.source_env)
        self.destination.setText(str(p.destination) if p.destination is not None else "")
        if self.header_table.rows() != p.header_rows:  # Ripristina, a new profile, the first show
            self.header_table.set_pairs(p.header_rows)
            self._show_header_problems()
        self.headers_toggle.setText(p.headers_summary())
        for box, on in ((self.zip_box, p.make_zip), (self.html_box, p.save_html)):
            if box.isChecked() != on:
                box.blockSignals(True)
                box.setChecked(on)
                box.blockSignals(False)
        self.source.render()
        if not self._running:
            self.action_bar.show_idle(p.start_text(), p.problems())

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

    def _browse_destination(self) -> None:
        chosen = ask.ask_folder(self, strings.GENERA_DESTINATION_PICK, self.presenter.destination)
        if chosen is not None:
            self.presenter.set_destination(chosen)
