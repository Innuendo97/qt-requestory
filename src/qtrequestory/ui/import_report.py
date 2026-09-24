"""Step 1 of the import dialog: what was found, and the folders needing an env.

Layout only, plus two signals: :class:`ReportView` shows an
:class:`~qtrequestory.ui.contracts.ArchiveReport` as a filterable table
(Percorso | Ambiente | Giorno | Dimensione | Stato) and, above it, one row per
folder whose environment the path does not tell — a combo with the
configured environment names and "Ignora". Picking one emits
``folder_env_chosen(folder, value)`` with the folder as an ABSOLUTE path
(``Config.folder_envs`` keys must be absolute: a relative ``svil`` would
apply to every scanned folder that has one); the dialog saves it and rescans.
"""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import (
    CONFLICT,
    DUPLICATE,
    IGNORE_FOLDER,
    IGNORED,
    IMPORTABLE,
    NEEDS_ENV,
    ArchiveReport,
    FoundLog,
)
from qtrequestory.ui.pages.sync_format import format_size

__all__ = ["COLUMNS", "FILTERS", "STATUS_LABELS", "FolderEnvPanel", "ReportTable", "ReportView",
           "folder_key"]

COLUMNS = (strings.IMPORT_COL_PATH, strings.IMPORT_COL_ENV, strings.IMPORT_COL_DAY,
           strings.IMPORT_COL_SIZE, strings.IMPORT_COL_STATUS)
STATUS_LABELS = {
    IMPORTABLE: strings.IMPORT_STATUS_IMPORTABLE,
    DUPLICATE: strings.IMPORT_STATUS_DUPLICATE,
    NEEDS_ENV: strings.IMPORT_STATUS_NEEDS_ENV,
    CONFLICT: strings.IMPORT_STATUS_CONFLICT,
    IGNORED: strings.IMPORT_STATUS_IGNORED,
}
#: ``(status or None for all, combo label)`` in combo order.
FILTERS = (
    (None, strings.IMPORT_FILTER_ALL),
    (IMPORTABLE, strings.IMPORT_FILTER_IMPORTABLE),
    (NEEDS_ENV, strings.IMPORT_FILTER_NEEDS_ENV),
    (DUPLICATE, strings.IMPORT_FILTER_DUPLICATE),
    (CONFLICT, strings.IMPORT_FILTER_CONFLICT),
    (IGNORED, strings.IMPORT_FILTER_IGNORED),
)
#: Status -> the theme token its cell is written in (None: the normal text).
STATUS_TONES = {IMPORTABLE: "ok", NEEDS_ENV: "warn", CONFLICT: "bad", IGNORED: "muted",
                DUPLICATE: "muted"}
#: Rows sort by status in this order, then by path: the work first.
STATUS_ORDER = {IMPORTABLE: 0, NEEDS_ENV: 1, CONFLICT: 2, DUPLICATE: 3, IGNORED: 4}


def folder_key(report: ArchiveReport, rel_dir: str) -> str:
    """The absolute folder a ``folder_envs`` entry is saved under."""
    return str(Path(report.root) / rel_dir) if rel_dir else str(Path(report.root))


class FolderEnvPanel(QFrame):
    """"Di che ambiente sono questi log?" — one combo per folder."""

    chosen = Signal(str, str)  # absolute folder, env name or IGNORE_FOLDER

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("banner", "warn")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.title = QLabel(strings.IMPORT_FOLDERS_TITLE)
        theme.set_role(self.title, "section")
        self.hint = QLabel(strings.IMPORT_FOLDERS_HINT)
        self.hint.setWordWrap(True)
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(theme.SPACE[2])
        self.grid.setVerticalSpacing(theme.SPACE[1])
        self.grid.setColumnStretch(0, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SPACE[3], theme.SPACE[2], theme.SPACE[3], theme.SPACE[2])
        layout.setSpacing(theme.SPACE[1])
        layout.addWidget(self.title)
        layout.addWidget(self.hint)
        layout.addLayout(self.grid)
        #: ``(absolute folder, combo)`` per row, for the dialog and the tests.
        self.combos: list[tuple[str, QComboBox]] = []
        self.setVisible(False)

    def set_report(self, report: ArchiveReport, env_names: Sequence[str]) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.combos = []
        waiting = report.of(NEEDS_ENV)
        for row, rel_dir in enumerate(report.needs_env_dirs()):
            n = sum(1 for f in waiting if f.rel_dir == rel_dir)
            label = QLabel(strings.IMPORT_FOLDER_ROW.format(
                folder=rel_dir or strings.IMPORT_FOLDER_ROOT, n=n))
            label.setToolTip(folder_key(report, rel_dir))
            combo = QComboBox()
            combo.addItem(strings.IMPORT_FOLDER_PICK, None)
            for name in env_names:
                combo.addItem(name, name)
            combo.addItem(strings.IMPORT_FOLDER_IGNORE, IGNORE_FOLDER)
            key = folder_key(report, rel_dir)
            combo.activated.connect(lambda index, c=combo, k=key: self._on_pick(k, c, index))
            self.grid.addWidget(label, row, 0)
            self.grid.addWidget(combo, row, 1)
            self.combos.append((key, combo))
        self.setVisible(bool(self.combos))

    def _on_pick(self, key: str, combo: QComboBox, index: int) -> None:
        value = combo.itemData(index)
        if value:
            self.chosen.emit(key, value)


class ReportTable(QTableWidget):
    """One row per found file; ``set_filter`` hides the other statuses."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(0, len(COLUMNS), parent)
        self.setHorizontalHeaderLabels(list(COLUMNS))
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(self.fontMetrics().height() + 10)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setWordWrap(False)
        self.setAlternatingRowColors(False)
        theme.set_table_look(self)
        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, len(COLUMNS) - 1):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(len(COLUMNS) - 1, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(len(COLUMNS) - 1, 320)
        self.items_shown: list[FoundLog] = []
        theme.signals.changed.connect(self.recolour)

    def set_report(self, report: ArchiveReport) -> None:
        found = sorted(report.items, key=lambda f: (STATUS_ORDER[f.status], f.rel_path.casefold()))
        self.items_shown = found
        self.setRowCount(len(found))
        for row, item in enumerate(found):
            cells = (
                item.rel_path,
                item.env or strings.IMPORT_NO_ENV,
                f"{item.day:%d/%m/%Y}" if item.day else strings.IMPORT_NO_ENV,
                format_size(item.size),
                status_text(item),
            )
            for column, text in enumerate(cells):
                cell = QTableWidgetItem(text)
                cell.setToolTip(str(item.path) if column == 0 else text)
                if column == 3:
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.setItem(row, column, cell)
        self.recolour()

    def recolour(self) -> None:
        """The status cells in the current theme's tones (also after a switch)."""
        tones = theme.tokens()
        for row, item in enumerate(self.items_shown):
            tone = STATUS_TONES.get(item.status)
            cell = self.item(row, len(COLUMNS) - 1)
            if tone and cell is not None:
                cell.setForeground(QColor(getattr(tones, tone)))

    def set_filter(self, status: str | None) -> None:
        for row, item in enumerate(self.items_shown):
            self.setRowHidden(row, status is not None and item.status != status)

    def visible_rows(self) -> list[FoundLog]:
        return [item for row, item in enumerate(self.items_shown) if not self.isRowHidden(row)]


class ReportView(QWidget):
    """Folder panel + filter + table + what [Importa] will do."""

    folder_env_chosen = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.folders = FolderEnvPanel()
        self.folders.chosen.connect(self.folder_env_chosen)
        self.filter = QComboBox()
        self.filter.currentIndexChanged.connect(self._apply_filter)
        self.table = ReportTable()
        self.plan_label = QLabel()
        self.plan_label.setWordWrap(True)
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel(strings.IMPORT_FILTER_LABEL))
        filter_row.addWidget(self.filter)
        filter_row.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE[2])
        layout.addWidget(self.folders)
        layout.addLayout(filter_row)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.plan_label)
        self.report: ArchiveReport | None = None

    def set_report(self, report: ArchiveReport, env_names: Sequence[str]) -> None:
        self.report = report
        self.folders.set_report(report, env_names)
        self.table.set_report(report)
        counts = report.counts()
        previous = self.filter.currentData()
        self.filter.blockSignals(True)
        self.filter.clear()
        for status, label in FILTERS:
            n = len(report.items) if status is None else counts[status]
            if status is None or n:
                self.filter.addItem(label.format(n=n), status)
        index = self.filter.findData(previous)
        self.filter.setCurrentIndex(max(index, 0))
        self.filter.blockSignals(False)
        self._apply_filter()
        self.plan_label.setText(plan_text(report))

    def _apply_filter(self, *_args: object) -> None:
        self.table.set_filter(self.filter.currentData())


def status_text(item: FoundLog) -> str:
    """"da importare: giorno mancante in archivio" — the reason once, not
    "già in archivio: già in archivio"."""
    label = STATUS_LABELS[item.status]
    if not item.reason or item.reason == label:
        return label
    return strings.IMPORT_STATUS_CELL.format(status=label, reason=item.reason)


def plan_text(report: ArchiveReport) -> str:
    counts = report.counts()
    if counts[IMPORTABLE]:
        text = strings.IMPORT_PLAN.format(n=counts[IMPORTABLE], dup=counts[DUPLICATE])
    else:
        text = strings.IMPORT_PLAN_NOTHING
    if counts[NEEDS_ENV]:
        text += strings.IMPORT_PLAN_WAITING.format(n=counts[NEEDS_ENV])
    return text
