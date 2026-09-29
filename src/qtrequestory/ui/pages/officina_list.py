"""The Officina's list of initiatives (and the one-line warn banner).

:class:`InitiativeList` is the table of initiatives (name, cases, accepted of
total, last activity) with "Nuova iniziativa", "Apri" and "Apri cartella";
it only displays and emits, ``OfficinaPage`` does the work. Phase 2.5 (D6):
each row ends with a trash button, the right-click menu has "Elimina
iniziativa", Canc deletes the selected row and Ctrl+Z inside the list undoes
the latest deletion (``officina_delete`` does the rest). While no folder
is chosen the page shows its setup card instead (``officina_setup``, release
1.3.2); while no generator is active, the same card sits over the table
(:meth:`InitiativeList.set_setup_card`).
"""
from __future__ import annotations

import time
from datetime import datetime

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QPushButton,
    QStackedLayout,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import icons, strings, theme
from qtrequestory.ui.contracts import Initiative
from qtrequestory.ui.pages.officina_format import (
    accepted_count,
    initiative_labels,
    last_activity,
    when,
)

__all__ = ["InitiativeList", "WarnBanner"]

COLUMNS = (strings.OFFICINA_COL_INITIATIVE, strings.OFFICINA_COL_CASES,
           strings.OFFICINA_COL_ACCEPTED, strings.OFFICINA_COL_ACTIVITY, "")
#: The last column: the row's trash button.
DELETE_COLUMN = len(COLUMNS) - 1
DELETE_WIDTH = 40
#: A trash click on ANOTHER row this soon after the last one is ignored: the
#: next row slides under the pointer, and a double click would delete two.
TRASH_GUARD_S = 0.5


class WarnBanner(QFrame):
    """A one-line warn (or bad) banner, hidden while it has no text."""

    def __init__(self, tone: str = "warn", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("banner", tone)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(theme.SPACE[2], theme.SPACE[1], theme.SPACE[2], theme.SPACE[1])
        layout.addWidget(self.label, 1)
        self.setVisible(False)

    def set_text(self, text: str) -> None:
        self.label.setText(text)
        self.setVisible(bool(text))

    def text(self) -> str:
        return self.label.text() if self.isVisible() else ""


class InitiativeList(QWidget):
    """Every initiative under the Officina folder."""

    open_requested = Signal(str)       # initiative id (its folder's name)
    new_requested = Signal()
    folder_requested = Signal()
    change_root_requested = Signal()
    delete_requested = Signal(str)     # initiative id (trash, menu, Canc)
    undo_requested = Signal()          # Ctrl+Z inside the list

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        title = QLabel(strings.OFFICINA_LIST_TITLE)
        theme.set_role(title, "pageTitle")
        self.root_label = QLabel()
        theme.set_role(self.root_label, "muted")
        self.new_button = QPushButton(strings.OFFICINA_NEW_INITIATIVE)
        theme.set_role(self.new_button, "positive")
        self.open_button = QPushButton(strings.OFFICINA_OPEN_INITIATIVE)
        self.folder_button = QPushButton(strings.OFFICINA_OPEN_FOLDER)
        self.change_button = QPushButton(strings.OFFICINA_CHANGE_ROOT)
        self.onedrive = WarnBanner()

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(list(COLUMNS))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        for column in range(1, len(COLUMNS)):
            self.table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(DELETE_COLUMN, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(DELETE_COLUMN, DELETE_WIDTH)
        theme.set_table_look(self.table)
        self.empty = QLabel(strings.OFFICINA_LIST_EMPTY)
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        theme.set_role(self.empty, "muted")

        bar = QHBoxLayout()
        bar.addWidget(title)
        bar.addSpacing(theme.SPACE[2])
        bar.addWidget(self.root_label, 1)
        for button in (self.new_button, self.open_button, self.folder_button, self.change_button):
            bar.addWidget(button)
        self.body = QStackedLayout()  # filled once it has a parent, below (D7)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE[1])
        layout.addLayout(bar)
        layout.addWidget(self.onedrive)
        layout.addLayout(self.body, 1)
        self.body.addWidget(self.table)  # addWidget shows the first page: never an orphan
        self.body.addWidget(self.empty)
        self._layout = layout

        self.new_button.clicked.connect(self.new_requested)
        self.folder_button.clicked.connect(self.folder_requested)
        self.change_button.clicked.connect(self.change_root_requested)
        self.open_button.clicked.connect(self._open_selected)
        self.table.doubleClicked.connect(lambda _index: self._open_selected())
        self.table.itemSelectionChanged.connect(self._sync_buttons)
        self.table.customContextMenuRequested.connect(self._on_menu)
        self.delete_shortcut = QShortcut(QKeySequence(QKeySequence.StandardKey.Delete), self.table)
        self.delete_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        self.delete_shortcut.setAutoRepeat(False)  # holding Canc must not empty the list
        self.delete_shortcut.activated.connect(self._delete_selected)
        self.undo_shortcut = QShortcut(QKeySequence(QKeySequence.StandardKey.Undo), self)
        self.undo_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.undo_shortcut.activated.connect(self.undo_requested)
        #: Seconds, monotonic (tests replace it); and the last trash click.
        self.clock = time.monotonic
        self._last_trash: tuple[str, float] | None = None
        self._sync_buttons()

    def set_setup_card(self, card: QWidget) -> None:
        """Put the page's setup card between the banner and the table (the
        page shows it while no generator is active)."""
        self._layout.insertWidget(self._layout.indexOf(self.onedrive) + 1, card)

    def show_initiatives(self, initiatives: list[Initiative], select: str | None = None) -> None:
        """Fill the table (newest activity first); keep or set the selection
        (``select`` is an initiative id). Each row carries its initiative's
        id; two rows with the same name show their folder too."""
        select = select or self.selected_name()
        labels = initiative_labels(initiatives)
        rows = sorted(sorted(initiatives, key=lambda i: (i.name.lower(), i.id.lower())),
                      key=lambda i: last_activity(i) or datetime.min, reverse=True)
        self.table.setRowCount(0)
        trash = _trash_icon()
        for ini in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            cells = (labels[ini.id], str(len(ini.cases)),
                     strings.OFFICINA_ACCEPTED_OF.format(accepted=accepted_count(ini),
                                                         total=len(ini.cases)),
                     when(last_activity(ini)))
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, ini.id)
                item.setToolTip(str(ini.folder))
                self.table.setItem(row, column, item)
            self.table.setCellWidget(row, DELETE_COLUMN, self._delete_button(ini.id, labels[ini.id], trash))
            if ini.id == select:
                self.table.selectRow(row)
        self.body.setCurrentWidget(self.table if rows else self.empty)
        self._sync_buttons()

    def delete_button(self, row: int) -> QToolButton:
        """The trash button of ``row``."""
        return self.table.cellWidget(row, DELETE_COLUMN)

    def select_near(self, row: int) -> None:
        """Select the row now at ``row`` (or the last): after a deletion the
        keyboard goes on from the neighbour."""
        if self.table.rowCount() and self.selected_name() is None:
            self.table.selectRow(min(max(row, 0), self.table.rowCount() - 1))

    def row_of(self, initiative_id: str) -> int:
        """The row showing ``initiative_id``, or -1."""
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).data(Qt.ItemDataRole.UserRole) == initiative_id:
                return row
        return -1

    def context_menu(self, initiative_id: str) -> QMenu:
        """The right-click menu of a row: Apri, Elimina iniziativa (Canc)."""
        menu = QMenu(self)
        menu.addAction(strings.ELIMINA_OPEN, lambda: self.open_requested.emit(initiative_id))
        menu.addSeparator()
        delete = menu.addAction(icons.icon("delete", theme.tokens().danger), strings.ELIMINA_INITIATIVE,
                                lambda: self.delete_requested.emit(initiative_id))
        delete.setShortcut(QKeySequence(QKeySequence.StandardKey.Delete))
        delete.setShortcutVisibleInContextMenu(True)
        return menu

    def names(self) -> list[str]:
        """What the rows show in the first column (names, disambiguated)."""
        return [self.table.item(r, 0).text() for r in range(self.table.rowCount())]

    def selected_name(self) -> str | None:
        """The selected initiative's id (its folder's name), or None."""
        items = self.table.selectedItems()
        return items[0].data(Qt.ItemDataRole.UserRole) if items else None

    def _open_selected(self) -> None:
        name = self.selected_name()
        if name:
            self.open_requested.emit(name)

    def _delete_button(self, initiative_id: str, label: str, trash: QIcon) -> QToolButton:
        button = QToolButton()
        button.setObjectName("rowDelete")
        button.setIcon(trash)
        button.setIconSize(QSize(18, 18))
        button.setFixedSize(30, 26)
        button.setAutoRaise(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # the keyboard has Canc and the menu key
        button.setToolTip(strings.ELIMINA_INITIATIVE_TIP)
        button.setAccessibleName(f"{strings.ELIMINA_INITIATIVE} {label}")
        button.clicked.connect(lambda: self._on_trash(initiative_id))
        return button

    def _on_trash(self, initiative_id: str) -> None:
        now = self.clock()
        last = self._last_trash
        if last is not None and last[0] != initiative_id and now - last[1] < TRASH_GUARD_S:
            return  # the neighbour slid under the pointer (double click)
        self._last_trash = (initiative_id, now)
        self.delete_requested.emit(initiative_id)

    def _on_menu(self, pos: QPoint) -> None:
        item = self.table.itemAt(pos)
        if item is None:
            return
        self.table.selectRow(item.row())
        menu = self.context_menu(item.data(Qt.ItemDataRole.UserRole))
        menu.exec(self.table.viewport().mapToGlobal(pos))
        menu.deleteLater()

    def _delete_selected(self) -> None:
        name = self.selected_name()
        if name:
            self.delete_requested.emit(name)

    def _sync_buttons(self) -> None:
        self.open_button.setEnabled(self.selected_name() is not None)


def _trash_icon() -> QIcon:
    """Muted at rest, ``danger`` under the mouse (the Active mode)."""
    t = theme.tokens()
    normal, hot = icons.icon("delete", t.muted), icons.icon("delete", t.danger)
    result = QIcon()
    for size in (16, 20, 32):
        result.addPixmap(normal.pixmap(size, size), QIcon.Mode.Normal)
        result.addPixmap(hot.pixmap(size, size), QIcon.Mode.Active)
    return result
