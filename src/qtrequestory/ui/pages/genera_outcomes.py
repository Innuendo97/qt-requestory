"""The rows of the Genera results: one per document, and the words for them.

**Columns.** Template key (monospace, elided in the middle — both ends of a
key matter — full text as tooltip) · Esito · Cartella · Tipo · Durata ·
Motivo. An FDI with no call (or never looked up) has no key: its FDI is shown
instead. The outcome is a glyph AND a word, its colour only a third channel
(``ok`` green; failures and missing calls ``warn`` — DESIGN-ui keeps ``bad``
for loss; skipped e-mails and cancelled rows muted), re-tinted when the theme
changes.

**Opening.** Double click or Enter on a row whose document was saved opens it
(:attr:`OutcomeTable.activated_row`; the pane decides). A filter
(:meth:`OutcomeTable.set_filter`, from the chips) hides the other rows; a
current row it hides moves to the first row still shown (or to none), so
Enter never opens a row that is not on screen.

:func:`report_summary` is the one-line count of a report used by the toasts
of Genera and of Ricerca's "Genera documento".
"""
from __future__ import annotations

from collections.abc import Collection, Iterable

from PySide6.QtCore import QModelIndex, Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
)

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import BatchReport, Outcome

__all__ = ["CHIP_ORDER", "COLUMNS", "COL_FOLDER", "COL_KEY", "COL_REASON", "COL_STATUS",
           "STATUS_LOOK", "OutcomeTable", "outcome_cells", "report_summary", "status_counts"]

COL_KEY, COL_STATUS, COL_FOLDER, COL_TYPE, COL_DURATION, COL_REASON = range(6)
COLUMNS = (strings.GENERA_COL_KEY, strings.GENERA_COL_STATUS, strings.GENERA_COL_FOLDER,
           strings.GENERA_COL_TYPE, strings.GENERA_COL_DURATION, strings.GENERA_COL_REASON)
#: status -> (glyph, word, tone); tone is a ``Tokens`` field ("muted" for the quiet ones).
STATUS_LOOK = {
    "ok": (strings.GENERA_GLYPH_OK, strings.GENERA_STATUS_OK, "ok"),
    "html_skipped": (strings.GENERA_GLYPH_HTML, strings.GENERA_STATUS_HTML, "muted"),
    "no_call": (strings.GENERA_GLYPH_NO_CALL, strings.GENERA_STATUS_NO_CALL, "warn"),
    "failed": (strings.GENERA_GLYPH_FAILED, strings.GENERA_STATUS_FAILED, "warn"),
    "cancelled": (strings.GENERA_GLYPH_CANCELLED, strings.GENERA_STATUS_CANCELLED, "muted"),
}
#: The order of the chips (and of the summary's parts): what went well, then what to look at.
CHIP_ORDER = ("ok", "html_skipped", "no_call", "failed", "cancelled")
#: The status role of an outcome cell (for the re-tint).
STATUS_ROLE = Qt.ItemDataRole.UserRole + 1
#: A row: as tall as the package rows of the setup pane.
ROW_HEIGHT = 30


def _duration(outcome: Outcome) -> str:
    if not outcome.duration_ms and outcome.status not in ("ok", "failed"):
        return ""
    seconds = f"{outcome.duration_ms / 1000:.1f}".replace(".", ",")
    return strings.GENERA_DURATION.format(seconds=seconds)


def outcome_cells(outcome: Outcome) -> tuple[str, ...]:
    """The six texts of a row, as shown (in ``COLUMNS`` order)."""
    glyph, word, _tone = STATUS_LOOK.get(outcome.status, ("", outcome.status, "muted"))
    key = outcome.key or (outcome.fdi or "")
    return (key, strings.GENERA_STATUS_CELL.format(glyph=glyph, word=word),
            strings.GENERA_FOLDERS_SEPARATOR.join(outcome.folders),
            (outcome.doc_type or "").upper(), _duration(outcome), outcome.reason)


def status_counts(outcomes: Iterable[Outcome]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for outcome in outcomes:
        counts[outcome.status] = counts.get(outcome.status, 0) + 1
    return counts


def _part(n: int, one: str, many: str) -> str:
    return one if n == 1 else many.format(n=n)


#: status -> (one, many) of the summary's parts.
SUMMARY_WORDS = {
    "ok": (strings.GENERA_SUM_OK_ONE, strings.GENERA_SUM_OK),
    "failed": (strings.GENERA_SUM_FAILED_ONE, strings.GENERA_SUM_FAILED),
    "no_call": (strings.GENERA_SUM_NO_CALL_ONE, strings.GENERA_SUM_NO_CALL),
    "html_skipped": (strings.GENERA_SUM_HTML_ONE, strings.GENERA_SUM_HTML),
    "cancelled": (strings.GENERA_SUM_CANCELLED_ONE, strings.GENERA_SUM_CANCELLED),
}


def report_summary(report: BatchReport, *, with_folder: bool = True) -> str:
    """"3 generati · 1 non riuscito · 2 email saltate · in svil_…"."""
    if not report.outcomes:
        return strings.GENERA_SUM_NOTHING
    counts = status_counts(report.outcomes)
    parts = [_part(counts[status], *SUMMARY_WORDS[status])
             for status in ("ok", "failed", "no_call", "html_skipped", "cancelled") if counts.get(status)]
    if report.zips:
        parts.append(_part(len(report.zips), strings.GENERA_SUM_ZIP_ONE, strings.GENERA_SUM_ZIPS))
    if with_folder:
        parts.append(strings.GENERA_SUM_FOLDER.format(name=report.run_dir.name))
    return strings.GENERA_SUM_SEPARATOR.join(parts)


class _MiddleElide(QStyledItemDelegate):
    """A template key, an FDI or a folder: elided in the middle, not at the end."""

    def initStyleOption(self, option, index) -> None:  # noqa: N802 - Qt naming
        super().initStyleOption(option, index)
        option.textElideMode = Qt.TextElideMode.ElideMiddle


class OutcomeTable(QTableWidget):
    """The rows (module docstring); the outcomes themselves are the pane's."""

    #: A row was double-clicked or Enter was pressed on it.
    activated_row = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(0, len(COLUMNS), parent)
        self.setObjectName("generaResults")
        self.setHorizontalHeaderLabels(list(COLUMNS))
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setAlternatingRowColors(True)
        self.setWordWrap(False)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        theme.set_table_look(self)
        self._elide = _MiddleElide(self)
        for column in (COL_KEY, COL_FOLDER):
            self.setItemDelegateForColumn(column, self._elide)
        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(COL_REASON, QHeaderView.ResizeMode.Stretch)
        for column, width in ((COL_KEY, 300), (COL_STATUS, 150), (COL_FOLDER, 160),
                              (COL_TYPE, 56), (COL_DURATION, 70)):
            self.setColumnWidth(column, width)
        self._statuses: list[str] = []
        self._filter: str | None = None
        # explicit, not ``activated``: that one depends on the style's single-click hint
        self.doubleClicked.connect(lambda index: self.activated_row.emit(index.row()))
        theme.signals.changed.connect(self._tint)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if (event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and event.modifiers() in (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.KeypadModifier)):
            row = self.currentRow()
            if row >= 0 and not self.isRowHidden(row):  # never a row a chip has hidden
                self.activated_row.emit(row)
            event.accept()
            return
        super().keyPressEvent(event)

    def clear_rows(self) -> None:
        self._statuses = []
        self.setRowCount(0)

    def append(self, outcome: Outcome) -> None:
        row = self.rowCount()
        self.insertRow(row)
        self._statuses.append(outcome.status)
        for column, text in enumerate(outcome_cells(outcome)):
            item = QTableWidgetItem(text)
            item.setToolTip(f"{text}\n{strings.GENERA_ROW_TIP_OPEN}" if outcome.files else text)
            if column == COL_KEY:
                item.setFont(theme.mono_font())
            if column == COL_DURATION:
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if column == COL_STATUS:
                item.setData(STATUS_ROLE, outcome.status)
            self.setItem(row, column, item)
        self._tint_row(row)
        self.setRowHidden(row, self._hidden(outcome.status))

    def set_filter(self, statuses: Collection[str] | None) -> None:
        """Only the rows of ``statuses`` (None: every row). A current row the
        filter hides gives way to the first row still shown, or to none: Enter
        opens only what is on screen."""
        self._filter = frozenset(statuses) if statuses is not None else None
        for row, status_of_row in enumerate(self._statuses):
            self.setRowHidden(row, self._hidden(status_of_row))
        current = self.currentRow()
        if current >= 0 and self.isRowHidden(current):
            shown = next((r for r in range(self.rowCount()) if not self.isRowHidden(r)), None)
            if shown is None:
                self.clearSelection()
                self.setCurrentIndex(QModelIndex())
            else:
                self.setCurrentCell(shown, max(self.currentColumn(), 0))

    def row_texts(self) -> list[tuple[str, ...]]:
        return [tuple(self.item(r, c).text() for c in range(len(COLUMNS))) for r in range(self.rowCount())]

    def _hidden(self, status: str) -> bool:
        return self._filter is not None and status not in self._filter

    def _tint(self) -> None:
        for row in range(self.rowCount()):
            self._tint_row(row)

    def _tint_row(self, row: int) -> None:
        item = self.item(row, COL_STATUS)
        if item is None:
            return
        _g, _w, tone = STATUS_LOOK.get(item.data(STATUS_ROLE), ("", "", "muted"))
        item.setForeground(QBrush(QColor(getattr(theme.tokens(), tone))))
