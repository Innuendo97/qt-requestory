"""The initiative board: one row per case, and the batch actions.

Columns (approved mockup, "La vista Iniziativa", phase-1 subset): the key and
variant; the documents as small tiles — T(arget), A(S-IS), the latest TO-BE
version, "—" for a slot still empty; the "TO-BE contro target" pill, read
from the case's saved summary (worst state, count and percentage, spec §7.4:
``officina_board_pill``); the last generation, or why the last one failed;
the case status.

The board only displays and emits; ``OfficinaPage`` runs the generations and
hands the results back through :meth:`Board.show_initiative` and
:meth:`Board.refresh_run_states`. It runs no comparison.
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QStackedLayout,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import Case, Initiative, Version
from qtrequestory.ui.pages.officina_format import (
    accepted_count,
    elide,
    initiative_notice,
    last_run,
)
from qtrequestory.ui.pages.officina_board_pill import board_badge
from qtrequestory.ui.pages.officina_list import WarnBanner
from qtrequestory.ui.pages.officina_progress import glyph_html
from qtrequestory.ui.pages.officina_widgets import MiddleElidedLabel, cell as _cell, pill

__all__ = ["Board", "summary_pill"]

COLUMNS = (strings.OFFICINA_COL_CASE, strings.OFFICINA_COL_DOCUMENTS,
           strings.OFFICINA_COL_TOBE_VS_TARGET, strings.OFFICINA_COL_LAST_RUN,
           strings.OFFICINA_COL_STATUS)
COL_CASE, COL_DOCS, COL_PILL, COL_RUN, COL_STATUS = range(len(COLUMNS))
ROW_HEIGHT = 46


def _tile(text: str, version: Version | None, tip: str, tone: str) -> QLabel:
    if version is None:
        return pill(strings.OFFICINA_NONE, "neutral")
    if version.missing:
        return pill(text, "bad", strings.OFFICINA_THUMB_MISSING_TIP)
    return pill(text, tone, tip)


def summary_pill(case: Case) -> QLabel:
    """The "TO-BE contro target" cell of ``case``: a pill, or a muted label
    when nothing counts (``officina_board_pill.board_badge``). The plain text
    is the ``plain`` property (the label itself holds rich text)."""
    badge = board_badge(case)
    if badge.pill:
        label = pill("", badge.tone, badge.tooltip)
    else:
        label = QLabel()
        label.setToolTip(badge.tooltip)
        theme.set_role(label, "muted")
    label.setTextFormat(Qt.TextFormat.RichText)
    label.setText(glyph_html(badge.text))
    label.setProperty("plain", badge.text)
    return label


class Board(QWidget):
    """Toolbar, batch progress and the table of cases of one initiative."""

    back_requested = Signal()
    open_requested = Signal(str)            # case id
    add_from_search_requested = Signal()
    add_from_file_requested = Signal()
    generate_missing_requested = Signal()
    regenerate_requested = Signal(list)     # case ids
    cancel_requested = Signal()
    folder_requested = Signal()
    deliver_requested = Signal()
    noise_rules_requested = Signal()     # "Regole di rumore…" of the initiative

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ini: Initiative | None = None
        #: case id -> "queued" | "running" | None (from the generation queue)
        self.run_state: Callable[[str], str | None] = lambda _case_id: None
        #: case id -> the reason of its last failed generation, if any
        self.failure: Callable[[str], str | None] = lambda _case_id: None
        #: case id -> a neutral note on its last run (cancelled before sending)
        self.note: Callable[[str], str | None] = lambda _case_id: None

        self.back_button = QPushButton(strings.OFFICINA_BACK_TO_LIST)
        theme.set_role(self.back_button, "row")
        self.title = QLabel()
        theme.set_role(self.title, "pageTitle")
        self.accepted = pill("")
        self.add_search_button = QPushButton(strings.OFFICINA_ADD_FROM_SEARCH)
        self.add_file_button = QPushButton(strings.OFFICINA_ADD_FROM_FILE)
        self.missing_button = QPushButton(strings.OFFICINA_GENERATE_MISSING_ASIS)
        self.regenerate_button = QPushButton(strings.OFFICINA_REGENERATE_SELECTED)
        self.deliver_button = QPushButton(strings.OFFICINA_DELIVER)
        self.deliver_button.setToolTip(strings.OFFICINA_DELIVER_TIP)
        self.folder_button = QPushButton(strings.OFFICINA_OPEN_FOLDER)
        self.noise_button = QPushButton(strings.RUMORE_BUTTON)
        self.noise_button.setToolTip(strings.RUMORE_BUTTON_TIP)
        theme.set_role(self.regenerate_button, "primary")
        self.progress = QLabel()
        self.cancel_button = QPushButton(strings.OFFICINA_BATCH_CANCEL)
        self.progress_row = _cell(self.progress, self.cancel_button)
        self.progress_row.setVisible(False)
        #: An unreadable iniziativa.json (generation blocked) or what loading left out.
        self.notice = WarnBanner()

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(list(COLUMNS))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(COL_RUN, QHeaderView.ResizeMode.Stretch)
        theme.set_table_look(self.table)
        self.empty = QLabel(strings.OFFICINA_BOARD_EMPTY)
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        theme.set_role(self.empty, "muted")

        self._build()
        self._connect()
        theme.signals.changed.connect(self._fit_columns)  # a theme may change the font

    def _build(self) -> None:
        top = QHBoxLayout()
        top.addWidget(self.back_button)
        top.addWidget(self.title)
        top.addWidget(self.accepted)
        top.addStretch(1)
        top.addWidget(self.noise_button)
        top.addWidget(self.folder_button)
        actions = QHBoxLayout()
        for button in (self.add_search_button, self.add_file_button, self.missing_button,
                       self.regenerate_button):
            actions.addWidget(button)
        actions.addStretch(1)
        actions.addWidget(self.deliver_button)
        self.body = QStackedLayout()
        self.body.addWidget(self.table)
        self.body.addWidget(self.empty)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE[1])
        layout.addLayout(top)
        layout.addLayout(actions)
        layout.addWidget(self.notice)
        layout.addWidget(self.progress_row)
        layout.addLayout(self.body, 1)

    def _connect(self) -> None:
        self.back_button.clicked.connect(self.back_requested)
        self.add_search_button.clicked.connect(self.add_from_search_requested)
        self.add_file_button.clicked.connect(self.add_from_file_requested)
        self.missing_button.clicked.connect(self.generate_missing_requested)
        self.regenerate_button.clicked.connect(
            lambda: self.regenerate_requested.emit(self.selected_case_ids()))
        self.cancel_button.clicked.connect(self.cancel_requested)
        self.folder_button.clicked.connect(self.folder_requested)
        self.deliver_button.clicked.connect(self.deliver_requested)
        self.noise_button.clicked.connect(self.noise_rules_requested)
        self.table.doubleClicked.connect(self._open_row)
        enter = QShortcut(QKeySequence(Qt.Key.Key_Return), self.table)
        enter.setContext(Qt.ShortcutContext.WidgetShortcut)
        enter.activated.connect(lambda: self._open_row(self.table.currentIndex()))
        self.table.itemSelectionChanged.connect(self._sync_buttons)

    # -- content -----------------------------------------------------------

    def show_initiative(self, ini: Initiative) -> None:
        """Rebuild the rows; the selected cases stay selected."""
        same = self._ini is not None and self._ini.id == ini.id
        selected = set(self.selected_case_ids()) if same else set()
        self._ini = ini
        self.title.setText(ini.name)
        self.title.setToolTip(str(ini.folder))
        self.notice.set_text(initiative_notice(ini))
        self.accepted.setText(strings.OFFICINA_ACCEPTED_PILL.format(
            accepted=accepted_count(ini), total=len(ini.cases)))
        self._drop_cell_widgets()
        self.table.setRowCount(0)
        for case in ini.cases:
            self._add_row(case)
        self._fit_columns()
        self.table.clearSelection()
        mode = self.table.selectionMode()
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        for row, case in enumerate(ini.cases):
            if case.id in selected:
                self.table.selectRow(row)
        self.table.setSelectionMode(mode)
        self.body.setCurrentWidget(self.table if ini.cases else self.empty)
        self._sync_buttons()

    def refresh_run_states(self) -> None:
        """The "Ultima generazione" column: queued / running / failed / last run."""
        for row, case in enumerate(self._cases()):
            self._set_cell(row, COL_RUN, _cell(self._run_label(case)))
        self._sync_buttons()

    def set_progress(self, done: int, total: int) -> None:
        self.progress.setText(strings.OFFICINA_BATCH_PROGRESS.format(done=done, total=total))
        self.progress_row.setVisible(total > 0)

    def selected_case_ids(self) -> list[str]:
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        cases = self._cases()
        return [cases[r].id for r in rows if r < len(cases)]

    def select_cases(self, case_ids: list[str]) -> None:
        self.table.clearSelection()
        mode = self.table.selectionMode()
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        for row, case in enumerate(self._cases()):
            if case.id in case_ids:
                self.table.selectRow(row)
        self.table.setSelectionMode(mode)

    def row_texts(self, case_id: str) -> list[str]:
        """Every label of the row, column by column (what the user reads)."""
        for row, case in enumerate(self._cases()):
            if case.id == case_id:
                cells = [self.table.cellWidget(row, col) or QWidget()
                         for col in range(len(COLUMNS))]
                return [" ".join(label.property("plain") or label.text()
                                 for label in cell.findChildren(QLabel))
                        for cell in cells]
        return []

    # -- internals ---------------------------------------------------------

    def _cases(self) -> list[Case]:
        return self._ini.cases if self._ini is not None else []

    def _add_row(self, case: Case) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        key = MiddleElidedLabel(case.key)
        bold = QFont(key.font())
        bold.setWeight(QFont.Weight.DemiBold)
        key.setFont(bold)
        widgets: list[QWidget] = [key]
        if case.variant:
            variant = MiddleElidedLabel(case.variant)
            theme.set_role(variant, "muted")
            widgets.append(variant)
        cell = _cell(*widgets, vertical=True)
        cell.setToolTip(f"{case.key} · {case.variant}" if case.variant else case.key)
        self._set_cell(row, COL_CASE, cell)
        target, asis, tobe = case.target(), case.asis(), case.latest_tobe()
        tiles = (
            _tile(strings.OFFICINA_THUMB_TARGET, target, strings.OFFICINA_THUMB_TARGET_TIP.format(
                name=target.meta.get("original_name", "") if target else ""), "neutral"),
            _tile(strings.OFFICINA_THUMB_ASIS, asis, strings.OFFICINA_THUMB_ASIS_TIP, "neutral"),
            _tile(strings.OFFICINA_THUMB_TOBE.format(n=tobe.number) if tobe else "", tobe,
                  strings.OFFICINA_THUMB_TOBE_TIP.format(n=tobe.number) if tobe else "", "ok"),
        )
        self._set_cell(row, COL_DOCS, _cell(*tiles))
        self._set_cell(row, COL_PILL, _cell(summary_pill(case)))
        self._set_cell(row, COL_RUN, _cell(self._run_label(case)))
        if case.load_error:
            status = pill(strings.OFFICINA_STATUS_BROKEN, "bad", case.load_error)
        elif case.status == "accepted" and case.acceptance_is_current():
            status = pill(strings.OFFICINA_STATUS_ACCEPTED, "ok")
        elif case.status == "accepted":
            status = pill(strings.OFFICINA_STATUS_ACCEPTED, "warn", strings.OFFICINA_CASE_STALE)
        elif case.reopened:
            status = pill(strings.OFFICINA_STATUS_REOPENED, "warn", strings.OFFICINA_CASE_REOPENED)
        else:
            status = pill(strings.OFFICINA_STATUS_OPEN)
        self._set_cell(row, COL_STATUS, _cell(status))

    def _run_label(self, case: Case) -> QLabel:
        state = self.run_state(case.id)
        failure = self.failure(case.id)
        if state == "queued":
            label = QLabel(strings.OFFICINA_RUN_QUEUED)
            theme.set_role(label, "muted")
        elif state == "running":
            label = QLabel(strings.OFFICINA_GENERATING_ON.format(
                env=case.env or strings.OFFICINA_CASE_NO_ENV))
            theme.set_role(label, "muted")
        elif failure:
            label = QLabel(elide(failure, 110))
            label.setToolTip(failure)
            label.setProperty("dot", "bad")
            theme.repolish(label)
        else:
            label = QLabel(self.note(case.id) or last_run(case))
            theme.set_role(label, "muted")
        return label

    def _set_cell(self, row: int, column: int, widget: QWidget) -> None:
        """Replace a cell's widget; the old one is hidden at once (Qt only
        deletes it later, and until then it would still paint)."""
        old = self.table.cellWidget(row, column)
        if old is not None:
            old.hide()
        self.table.setCellWidget(row, column, widget)

    def _drop_cell_widgets(self) -> None:
        for row in range(self.table.rowCount()):
            for column in range(self.table.columnCount()):
                old = self.table.cellWidget(row, column)
                if old is not None:
                    old.hide()

    def _fit_columns(self) -> None:
        """Size the columns to their widgets (``ResizeToContents`` only
        measures items, and every cell here is a widget).

        Every label is polished first — its QSS font and padding apply only
        then, and an unpolished label measures too small at 125 % scaling —
        and the key column is measured from its text. Re-run on show and on a
        font, style or theme change (:meth:`changeEvent`, :meth:`showEvent`).
        """
        header = self.table.horizontalHeader()
        for column in (COL_CASE, COL_DOCS, COL_PILL, COL_STATUS):
            widths = [header.sectionSizeHint(column)]
            for row in range(self.table.rowCount()):
                cell = self.table.cellWidget(row, column)
                if cell is None:
                    continue
                for child in cell.findChildren(QWidget):
                    child.ensurePolished()
                cell.ensurePolished()
                cell.layout().invalidate()
                widths.append(cell.layout().sizeHint().width())
            self.table.setColumnWidth(column, max(widths) + theme.SPACE[2])

    def showEvent(self, event) -> None:  # noqa: D102, N802 - Qt naming
        super().showEvent(event)
        self._fit_columns()

    def changeEvent(self, event) -> None:  # noqa: D102, N802 - Qt naming
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange,
                            QEvent.Type.ScreenChangeInternal,
                            QEvent.Type.DevicePixelRatioChange):
            self._fit_columns()

    def _open_row(self, index) -> None:
        cases = self._cases()
        if 0 <= index.row() < len(cases):
            self.open_requested.emit(cases[index.row()].id)

    def _sync_buttons(self) -> None:
        """Generation needs readable settings: none while ``iniziativa.json``
        is unreadable, and not for a selection holding a broken ``caso.json``."""
        cases = self._cases()
        can_generate = self._ini is not None and not self._ini.load_error
        selected = set(self.selected_case_ids())
        broken = any(c.load_error for c in cases if c.id in selected)
        self.regenerate_button.setEnabled(can_generate and bool(selected) and not broken)
        self.missing_button.setEnabled(can_generate and bool(cases))
        self.deliver_button.setEnabled(bool(cases))
