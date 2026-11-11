"""The Genera tab's results pane: always on screen, the thing the user waits for.

::

    Esiti   Generazione finita · svil_20261110-143005   [Riprova i 3 non riusciti] [Apri cartella]
    ( Generazione non partita: … )                       <- a refusal, warn banner
    ( Genero su svil…                         12 di 56 ) <- while running, with the bar
    (Tutti 22) (✓ 15 generati) (○ 3 senza chiamata) (✕ 4 non riusciti)
    +--------------------------------------------------------------------+
    | Template key | Esito | Cartella | Tipo | Durata | Motivo           |
    +--------------------------------------------------------------------+

**Before the first run** the table's place holds what will happen (an icon,
"Gli esiti compaiono qui…", the plan: what, from which logs, where the files
go — ``GeneraViews.plan_lines``). **Live, then the truth**: while a run goes
the rows arrive in completion order (:meth:`GeneraResults.add_live`) and the
chips count them; the final ``BatchReport`` replaces them in call order
(:meth:`GeneraResults.show_report`), also when no event came at all.

**Rows** (``genera_outcomes``): double click or Enter opens a saved document;
the row menu (:meth:`GeneraResults.menu_for_row`) opens the document or its
folder and copies the key or the reason. The pane emits what was asked; the
page does it through ``ExtractApi``.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import BatchReport, Outcome
from qtrequestory.ui.pages.genera_chips import OutcomeChips, statuses_of
from qtrequestory.ui.pages.genera_outcomes import COLUMNS, OutcomeTable, status_counts
from qtrequestory.ui.pages.search_icons import ThemedIcons
from qtrequestory.ui.pages.search_states import EmptyState

__all__ = ["COLUMNS", "GeneraResults"]

MARGIN = theme.SPACE[3] + theme.SPACE[0]


def _banner(kind: str) -> tuple[QFrame, QLabel]:
    frame = QFrame()
    frame.setProperty("banner", kind)
    label = QLabel()
    label.setWordWrap(True)
    layout = QHBoxLayout(frame)
    layout.setContentsMargins(theme.SPACE[2] + theme.SPACE[0], theme.SPACE[1] + theme.SPACE[0],
                              theme.SPACE[2] + theme.SPACE[0], theme.SPACE[1] + theme.SPACE[0])
    layout.addWidget(label, 1)
    frame.setVisible(False)
    return frame, label


class GeneraResults(QWidget):
    """The results pane (module docstring)."""

    retry_requested = Signal()
    #: [Apri cartella]: the run's folder.
    open_requested = Signal()
    open_file_requested = Signal(Path)
    open_folder_requested = Signal(Path)
    #: A row's text to copy (key or reason).
    copy_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._outcomes: list[Outcome] = []
        self._actions: tuple[int, bool] = (0, False)  # (retry count, folder) of the report shown
        icons = ThemedIcons(self)

        title = QLabel(strings.GENERA_RESULTS)
        theme.set_role(title, "section")
        self.summary = QLabel()
        theme.set_role(self.summary, "muted")
        # clipped on a narrow pane rather than widening the window (its tooltip is the folder)
        self.summary.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.retry_button = QPushButton(strings.GENERA_RETRY_ONE)
        self.retry_button.setToolTip(strings.GENERA_RETRY_TIP)
        icons.set(self.retry_button, "arrow-sync")
        self.open_folder_button = QPushButton(strings.BTN_OPEN_FOLDER)
        icons.set(self.open_folder_button, "folder-open")
        head = QHBoxLayout()
        head.setSpacing(theme.SPACE[2])
        head.addWidget(title)
        head.addWidget(self.summary, 1)
        head.addWidget(self.retry_button)
        head.addWidget(self.open_folder_button)

        self.message_banner, self.message = _banner("warn")
        self.progress = self._progress_strip()
        self.chips = OutcomeChips()

        self.empty = EmptyState("document-multiple")
        self.empty.set_text(strings.GENERA_RESULTS_EMPTY_TITLE, [strings.GENERA_PLAN_NOT_READY])
        self.waiting = EmptyState()
        self.waiting.set_text(strings.GENERA_RESULTS_WAITING)
        self.table = OutcomeTable()
        self.stack = QStackedWidget()
        for widget in (self.empty, self.waiting, self.table):
            self.stack.addWidget(widget)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(MARGIN, MARGIN - theme.SPACE[0], MARGIN, MARGIN)
        layout.setSpacing(theme.SPACE[2])
        layout.addLayout(head)
        layout.addWidget(self.message_banner)
        layout.addWidget(self.progress)
        layout.addWidget(self.chips)
        layout.addWidget(self.stack, 1)

        self.chips.changed.connect(self._on_chip)
        self.table.activated_row.connect(self._activated)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.retry_button.clicked.connect(lambda _c=False: self.retry_requested.emit())
        self.open_folder_button.clicked.connect(lambda _c=False: self.open_requested.emit())
        self._set_actions(retry=0, folder=False)
        self.chips.setVisible(False)
        self._say("")

    def _progress_strip(self) -> QFrame:
        """"Genero su svil…  12 di 56" over a thin bar, in the progress tone."""
        strip = QFrame()
        strip.setProperty("banner", "progress")
        self.progress_label = QLabel()
        self.progress_count = QLabel()
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        line = QHBoxLayout()
        line.setSpacing(theme.SPACE[2])
        line.addWidget(self.progress_label, 1)
        line.addWidget(self.progress_count)
        column = QVBoxLayout(strip)
        column.setContentsMargins(theme.SPACE[2] + theme.SPACE[0], theme.SPACE[1] + theme.SPACE[0],
                                  theme.SPACE[2] + theme.SPACE[0], theme.SPACE[2])
        column.setSpacing(theme.SPACE[1] + theme.SPACE[0])
        column.addLayout(line)
        column.addWidget(self.progress_bar)
        strip.setVisible(False)
        return strip

    # -- before any run ---------------------------------------------------------------

    def show_plan(self, lines: list[str]) -> None:
        """What the empty pane says (``GeneraViews.plan_lines``)."""
        self.empty.set_text(strings.GENERA_RESULTS_EMPTY_TITLE, lines)

    # -- a run -----------------------------------------------------------------------

    def clear_for_run(self) -> None:
        """A new run: no rows, no summary, no actions; every row is shown as it
        arrives, and the filter chosen comes back with the report if the new
        rows still have some for it (``genera_chips``)."""
        self._outcomes = []
        self._actions = (0, False)
        self.table.clear_rows()
        self.chips.begin_run()
        self.chips.set_counts({})
        self.chips.setVisible(False)
        self.stack.setCurrentWidget(self.waiting)
        self.message_banner.setVisible(False)
        self._say("")
        self._set_actions(retry=0, folder=False)

    def add_live(self, outcome: Outcome) -> None:
        self._outcomes.append(outcome)
        self._show_rows()
        self.table.append(outcome)

    def show_report(self, report: BatchReport, retry: int) -> None:
        """The truth: every outcome in call order, the heading, the actions."""
        self._outcomes = list(report.outcomes)
        self.table.clear_rows()
        for outcome in self._outcomes:
            self.table.append(outcome)
        self._show_rows(final=True)
        if not self._outcomes:
            self.stack.setCurrentWidget(self.empty)
        title = strings.GENERA_STOPPED_TITLE if report.cancelled else strings.GENERA_DONE_TITLE
        self._say(strings.GENERA_DONE_LINE.format(title=title, name=report.run_dir.name))
        self.summary.setToolTip(str(report.run_dir))
        self._actions = (retry, True)
        self._set_actions(retry=retry, folder=True)
        self.open_folder_button.setToolTip(str(report.run_dir))

    def show_message(self, text: str) -> None:
        """A run that did not start, a folder that is gone: the reason, warn banner."""
        self.message.setText(text)
        self.message_banner.setVisible(bool(text))

    def set_running(self, running: bool, status: str = "") -> None:
        """The progress strip (``status`` while the total is unknown); the actions
        of the previous run hide meanwhile and come back when it ends without a
        new report (the count stopped, a refusal)."""
        self.progress.setVisible(running)
        if running:
            self.message_banner.setVisible(False)
            self.progress_bar.setRange(0, 0)  # indeterminate until BatchStarted
            self.progress_label.setText(status)
            self.progress_count.setText("")
        retry, folder = (0, False) if running else self._actions
        self._set_actions(retry=retry, folder=folder)

    def show_progress(self, status: str, done: int, total: int, *, label: bool = True) -> None:
        self.progress_bar.setRange(0, max(total, 1))
        self.progress_bar.setValue(done)
        if label:
            self.progress_label.setText(status)
            self.progress_count.setText(strings.GENERA_PROGRESS.format(done=done, total=total))

    # -- reading back ------------------------------------------------------------------

    def row_texts(self) -> list[tuple[str, ...]]:
        return self.table.row_texts()

    def visible_rows(self) -> list[tuple[str, ...]]:
        return [row for r, row in enumerate(self.row_texts()) if not self.table.isRowHidden(r)]

    def outcomes(self) -> list[Outcome]:
        return list(self._outcomes)

    # -- rows ---------------------------------------------------------------------------

    def menu_for_row(self, row: int) -> QMenu:
        """The row menu, built and not shown (the right click shows it)."""
        outcome = self._outcomes[row]
        document = outcome.files[0] if outcome.files else None
        menu = QMenu(self)
        open_ = menu.addAction(strings.GENERA_ROW_OPEN)
        open_.setShortcut(QKeySequence(Qt.Key.Key_Return))
        open_.setShortcutVisibleInContextMenu(True)
        open_.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)  # display only
        folder = menu.addAction(strings.GENERA_ROW_FOLDER)
        menu.addSeparator()
        key = menu.addAction(strings.GENERA_ROW_COPY_KEY)
        reason = menu.addAction(strings.GENERA_ROW_COPY_REASON)
        open_.setEnabled(document is not None)
        folder.setEnabled(document is not None)
        reason.setEnabled(bool(outcome.reason))
        if document is not None:
            open_.triggered.connect(lambda _c=False: self.open_file_requested.emit(document))
            folder.triggered.connect(lambda _c=False: self.open_folder_requested.emit(document.parent))
        key.triggered.connect(lambda _c=False: self.copy_requested.emit(outcome.key or outcome.fdi or ""))
        reason.triggered.connect(lambda _c=False: self.copy_requested.emit(outcome.reason))
        return menu

    def _context_menu(self, pos: QPoint) -> None:
        index = self.table.indexAt(pos)
        if not index.isValid() or index.row() >= len(self._outcomes):
            return
        self.table.selectRow(index.row())
        menu = self.menu_for_row(index.row())
        menu.exec(self.table.viewport().mapToGlobal(pos))
        menu.deleteLater()

    def _activated(self, row: int) -> None:
        if 0 <= row < len(self._outcomes) and self._outcomes[row].files:
            self.open_file_requested.emit(self._outcomes[row].files[0])

    # -- internals ------------------------------------------------------------------------

    def _show_rows(self, *, final: bool = False) -> None:
        self.stack.setCurrentWidget(self.table)
        self.chips.set_counts(status_counts(self._outcomes), final=final)
        self.chips.setVisible(bool(self._outcomes))

    def _on_chip(self, key: str | None) -> None:
        self.table.set_filter(statuses_of(key))

    def _say(self, text: str) -> None:
        self.summary.setText(text)
        self.summary.setVisible(bool(text))

    def _set_actions(self, *, retry: int, folder: bool) -> None:
        self.retry_button.setText(strings.GENERA_RETRY_ONE if retry == 1
                                  else strings.GENERA_RETRY.format(n=retry))
        self.retry_button.setVisible(retry > 0)
        self.open_folder_button.setVisible(folder)
