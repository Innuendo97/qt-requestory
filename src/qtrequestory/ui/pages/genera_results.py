"""The Genera tab's results: one row per document, a summary, what to do next.

**Rows.** Template key (monospace, elided in the middle — both ends of a key
matter — full text as tooltip) · Cartella · Esito · Tipo · Durata · Motivo.
An FDI with no call (or never looked up) has no key: its FDI is shown
instead. The outcome is a glyph AND a word, its colour only a third channel
(``ok`` green; failures and missing calls ``warn`` — DESIGN-ui keeps ``bad``
for loss; skipped and cancelled muted), re-tinted when the theme changes.

**Live, then the truth.** While a run goes, rows arrive in completion order
(:meth:`GeneraResults.add_live`); the final ``BatchReport`` replaces them in
call order (:meth:`GeneraResults.show_report`) — also when no event came at
all (a run stopped while the calls were looked up).

**After.** "12 generati · 1 non riuscito · in svil_20261110-143005",
[Riprova i N non riusciti] (only when there is one), [Apri cartella], and the
"Solo non riusciti" filter. A refusal before anything started is the same
line in the ``warn`` tone (:meth:`GeneraResults.show_message`).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QStackedWidget,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import BatchReport, Outcome
from qtrequestory.ui.pages.genera_retry import RETRY_STATUSES

__all__ = ["COLUMNS", "STATUS_LOOK", "GeneraResults", "outcome_cells", "report_summary"]

COL_KEY, COL_FOLDER, COL_STATUS, COL_TYPE, COL_DURATION, COL_REASON = range(6)
COLUMNS = (strings.GENERA_COL_KEY, strings.GENERA_COL_FOLDER, strings.GENERA_COL_STATUS,
           strings.GENERA_COL_TYPE, strings.GENERA_COL_DURATION, strings.GENERA_COL_REASON)
#: status -> (glyph, word, tone); tone is a ``Tokens`` field ("muted" for the quiet ones).
STATUS_LOOK = {
    "ok": (strings.GENERA_GLYPH_OK, strings.GENERA_STATUS_OK, "ok"),
    "html_skipped": (strings.GENERA_GLYPH_HTML, strings.GENERA_STATUS_HTML, "muted"),
    "no_call": (strings.GENERA_GLYPH_NO_CALL, strings.GENERA_STATUS_NO_CALL, "warn"),
    "failed": (strings.GENERA_GLYPH_FAILED, strings.GENERA_STATUS_FAILED, "warn"),
    "cancelled": (strings.GENERA_GLYPH_CANCELLED, strings.GENERA_STATUS_CANCELLED, "muted"),
}
#: The status role of an outcome cell (for the re-tint).
STATUS_ROLE = Qt.ItemDataRole.UserRole + 1
#: Enough for a few rows before the page has to scroll.
MIN_TABLE_HEIGHT = 168


def _duration(outcome: Outcome) -> str:
    if not outcome.duration_ms and outcome.status not in ("ok", "failed"):
        return ""
    seconds = f"{outcome.duration_ms / 1000:.1f}".replace(".", ",")
    return strings.GENERA_DURATION.format(seconds=seconds)


def outcome_cells(outcome: Outcome) -> tuple[str, ...]:
    """The six texts of a row, as shown."""
    glyph, word, _tone = STATUS_LOOK.get(outcome.status, ("", outcome.status, "muted"))
    key = outcome.key or (outcome.fdi or "")
    return (key, strings.GENERA_FOLDERS_SEPARATOR.join(outcome.folders),
            strings.GENERA_STATUS_CELL.format(glyph=glyph, word=word),
            (outcome.doc_type or "").upper(), _duration(outcome), outcome.reason)


def _part(n: int, one: str, many: str) -> str:
    return one if n == 1 else many.format(n=n)


def report_summary(report: BatchReport, *, with_folder: bool = True) -> str:
    """"3 generati · 1 non riuscito · 2 saltati (HTML) · in svil_…"."""
    counts: dict[str, int] = {}
    for outcome in report.outcomes:
        counts[outcome.status] = counts.get(outcome.status, 0) + 1
    if not report.outcomes:
        return strings.GENERA_SUM_NOTHING
    parts = [_part(counts[status], one, many) for status, one, many in (
        ("ok", strings.GENERA_SUM_OK_ONE, strings.GENERA_SUM_OK),
        ("failed", strings.GENERA_SUM_FAILED_ONE, strings.GENERA_SUM_FAILED),
        ("no_call", strings.GENERA_SUM_NO_CALL_ONE, strings.GENERA_SUM_NO_CALL),
        ("html_skipped", strings.GENERA_SUM_HTML_ONE, strings.GENERA_SUM_HTML),
        ("cancelled", strings.GENERA_SUM_CANCELLED_ONE, strings.GENERA_SUM_CANCELLED),
    ) if counts.get(status)]
    if report.zips:
        parts.append(_part(len(report.zips), strings.GENERA_SUM_ZIP_ONE, strings.GENERA_SUM_ZIPS))
    if with_folder:
        parts.append(strings.GENERA_SUM_FOLDER.format(name=report.run_dir.name))
    return strings.GENERA_SUM_SEPARATOR.join(parts)


class _MiddleElide(QStyledItemDelegate):
    """A template key or an FDI: elided in the middle, not at the end."""

    def initStyleOption(self, option, index) -> None:  # noqa: N802 - Qt naming
        super().initStyleOption(option, index)
        option.textElideMode = Qt.TextElideMode.ElideMiddle


class GeneraResults(QWidget):
    """Summary + actions over the results table (module docstring)."""

    retry_requested = Signal()
    open_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._outcomes: list[Outcome] = []
        self._actions: tuple[int, bool] = (0, False)  # (retry count, folder) of the report shown
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.only_failed = QCheckBox(strings.GENERA_ONLY_FAILED)
        self.retry_button = QPushButton(strings.GENERA_RETRY_ONE)
        self.retry_button.setToolTip(strings.GENERA_RETRY_TIP)
        self.open_folder_button = QPushButton(strings.BTN_OPEN_FOLDER)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(list(COLUMNS))
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.setMinimumHeight(MIN_TABLE_HEIGHT)
        theme.set_table_look(self.table)
        self._elide = _MiddleElide(self.table)
        self.table.setItemDelegateForColumn(COL_KEY, self._elide)
        self.table.setItemDelegateForColumn(COL_FOLDER, self._elide)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(COL_REASON, QHeaderView.ResizeMode.Stretch)
        for column, width in ((COL_KEY, 300), (COL_FOLDER, 170), (COL_STATUS, 150),
                              (COL_TYPE, 56), (COL_DURATION, 72)):
            self.table.setColumnWidth(column, width)
        self.empty = QLabel(strings.GENERA_RESULTS_EMPTY)
        # right under the button, not centred far below it where a short window cuts it off
        self.empty.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        theme.set_role(self.empty, "muted")
        self.stack = QStackedWidget()
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.table)

        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(theme.SPACE[2])
        bar.addWidget(self.summary, 1)
        bar.addWidget(self.only_failed)
        bar.addWidget(self.retry_button)
        bar.addWidget(self.open_folder_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE[1])
        layout.addLayout(bar)
        layout.addWidget(self.stack, 1)
        self.stack.setMinimumHeight(MIN_TABLE_HEIGHT)

        self.only_failed.toggled.connect(lambda _on: self._apply_filter())
        self.retry_button.clicked.connect(lambda _c=False: self.retry_requested.emit())
        self.open_folder_button.clicked.connect(lambda _c=False: self.open_requested.emit())
        theme.signals.changed.connect(self._tint)
        self._set_actions(retry=0, folder=False)
        self.only_failed.setVisible(False)
        self._say("")

    # -- a run -----------------------------------------------------------------------

    def clear_for_run(self) -> None:
        """A new run: no rows, no summary, no actions (the filter stays)."""
        self._outcomes = []
        self._actions = (0, False)
        self.table.setRowCount(0)
        self.stack.setCurrentWidget(self.empty)
        self.only_failed.setVisible(False)
        self._say("")
        self._set_actions(retry=0, folder=False)

    def add_live(self, outcome: Outcome) -> None:
        self._outcomes.append(outcome)
        self._append(outcome)

    def show_report(self, report: BatchReport, retry: int) -> None:
        """The truth: every outcome in call order, the summary, the actions."""
        self._outcomes = list(report.outcomes)
        self.table.setRowCount(0)
        for outcome in self._outcomes:
            self._append(outcome)
        self.stack.setCurrentWidget(self.table if self._outcomes else self.empty)
        self.only_failed.setVisible(bool(self._outcomes))
        self._say(report_summary(report))
        self.summary.setToolTip(str(report.run_dir))
        self._actions = (retry, True)
        self._set_actions(retry=retry, folder=True)
        self.open_folder_button.setToolTip(str(report.run_dir))

    def show_message(self, text: str) -> None:
        """A run that did not start: the reason, in the warn tone."""
        self._say(text, tone="warn")

    # -- reading back ------------------------------------------------------------------

    def row_texts(self) -> list[tuple[str, ...]]:
        return [tuple(self.table.item(r, c).text() for c in range(len(COLUMNS)))
                for r in range(self.table.rowCount())]

    def visible_rows(self) -> list[tuple[str, ...]]:
        rows = self.row_texts()
        return [row for r, row in enumerate(rows) if not self.table.isRowHidden(r)]

    def outcomes(self) -> list[Outcome]:
        return list(self._outcomes)

    # -- internals ------------------------------------------------------------------------

    def _append(self, outcome: Outcome) -> None:
        self.stack.setCurrentWidget(self.table)
        self.only_failed.setVisible(True)  # a filter over nothing is noise
        row = self.table.rowCount()
        self.table.insertRow(row)
        texts = outcome_cells(outcome)
        for column, text in enumerate(texts):
            item = QTableWidgetItem(text)
            item.setToolTip(text)
            if column == COL_KEY:
                item.setFont(theme.mono_font())
            if column == COL_DURATION:
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if column == COL_STATUS:
                item.setData(STATUS_ROLE, outcome.status)
            self.table.setItem(row, column, item)
        self._tint_row(row)
        self.table.setRowHidden(row, self._hidden(outcome))

    def _hidden(self, outcome: Outcome) -> bool:
        return self.only_failed.isChecked() and outcome.status not in RETRY_STATUSES

    def _apply_filter(self) -> None:
        for row, outcome in enumerate(self._outcomes[: self.table.rowCount()]):
            self.table.setRowHidden(row, self._hidden(outcome))

    def _tint(self) -> None:
        for row in range(self.table.rowCount()):
            self._tint_row(row)

    def _tint_row(self, row: int) -> None:
        item = self.table.item(row, COL_STATUS)
        if item is None:
            return
        _g, _w, tone = STATUS_LOOK.get(item.data(STATUS_ROLE), ("", "", "muted"))
        item.setForeground(QBrush(QColor(getattr(theme.tokens(), tone))))

    def _say(self, text: str, tone: str = "") -> None:
        self.summary.setText(text)
        self.summary.setVisible(bool(text))
        if (self.summary.property("dot") or "") != tone:
            self.summary.setProperty("dot", tone or None)
            theme.repolish(self.summary)

    def _set_actions(self, *, retry: int, folder: bool) -> None:
        self.retry_button.setText(strings.GENERA_RETRY_ONE if retry == 1
                                  else strings.GENERA_RETRY.format(n=retry))
        self.retry_button.setVisible(retry > 0)
        self.open_folder_button.setVisible(folder)

    def set_running(self, running: bool) -> None:
        """While a run (or its count) goes the actions of the previous one are
        hidden; they come back when it ends without a new report (the count
        stopped, a refusal)."""
        retry, folder = (0, False) if running else self._actions
        self._set_actions(retry=retry, folder=folder)
