"""The Officina's first two screens: the folder chooser and the initiatives.

:class:`RootChooser` is the empty state while ``officina.root`` is not set:
one sentence on why the folder matters and [Scegli cartella…].
:class:`InitiativeList` is the table of initiatives (name, cases, accepted of
total, last activity) with "Nuova iniziativa", "Apri" and "Apri cartella".
Both only display and emit; ``OfficinaPage`` does the work.
"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QStackedLayout,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import Initiative
from qtrequestory.ui.pages.officina_format import (
    accepted_count,
    initiative_labels,
    last_activity,
    when,
)

__all__ = ["InitiativeList", "RootChooser", "WarnBanner"]

COLUMNS = (strings.OFFICINA_COL_INITIATIVE, strings.OFFICINA_COL_CASES,
           strings.OFFICINA_COL_ACCEPTED, strings.OFFICINA_COL_ACTIVITY)


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


class RootChooser(QWidget):
    """The empty state: no Officina folder yet."""

    choose_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        title = QLabel(strings.OFFICINA_ROOT_TITLE)
        theme.set_role(title, "pageTitle")
        text = QLabel(strings.OFFICINA_ROOT_TEXT)
        text.setWordWrap(True)
        theme.set_role(text, "muted")
        self.button = QPushButton(strings.OFFICINA_ROOT_BUTTON)
        theme.set_role(self.button, "primary")
        self.button.clicked.connect(self.choose_requested)
        self.error = WarnBanner("bad")
        column = QVBoxLayout()
        column.setSpacing(theme.SPACE[2])
        column.addWidget(title)
        column.addWidget(text)
        column.addWidget(self.error)
        column.addWidget(self.button, 0, Qt.AlignmentFlag.AlignLeft)
        box = QWidget()
        box.setLayout(column)
        box.setFixedWidth(560)  # a fixed width lets the wrapped text claim its height
        # Stretches rather than an alignment flag: an aligned item loses
        # height-for-width, and the wrapped sentence would be clipped.
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(box)
        row.addStretch(1)
        outer = QVBoxLayout(self)
        outer.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(2)


class InitiativeList(QWidget):
    """Every initiative under the Officina folder."""

    open_requested = Signal(str)       # initiative id (its folder's name)
    new_requested = Signal()
    folder_requested = Signal()
    change_root_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        title = QLabel(strings.OFFICINA_LIST_TITLE)
        theme.set_role(title, "pageTitle")
        self.root_label = QLabel()
        theme.set_role(self.root_label, "muted")
        self.new_button = QPushButton(strings.OFFICINA_NEW_INITIATIVE)
        theme.set_role(self.new_button, "primary")
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
        for column in range(1, len(COLUMNS)):
            self.table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents)
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
        self.body = QStackedLayout()
        self.body.addWidget(self.table)
        self.body.addWidget(self.empty)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE[1])
        layout.addLayout(bar)
        layout.addWidget(self.onedrive)
        layout.addLayout(self.body, 1)

        self.new_button.clicked.connect(self.new_requested)
        self.folder_button.clicked.connect(self.folder_requested)
        self.change_button.clicked.connect(self.change_root_requested)
        self.open_button.clicked.connect(self._open_selected)
        self.table.doubleClicked.connect(lambda _index: self._open_selected())
        self.table.itemSelectionChanged.connect(self._sync_buttons)
        self._sync_buttons()

    def show_initiatives(self, initiatives: list[Initiative], select: str | None = None) -> None:
        """Fill the table (newest activity first); keep or set the selection
        (``select`` is an initiative id). Each row carries its initiative's
        id; two rows with the same name show their folder too."""
        select = select or self.selected_name()
        labels = initiative_labels(initiatives)
        rows = sorted(sorted(initiatives, key=lambda i: (i.name.lower(), i.id.lower())),
                      key=lambda i: last_activity(i) or datetime.min, reverse=True)
        self.table.setRowCount(0)
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
            if ini.id == select:
                self.table.selectRow(row)
        self.body.setCurrentWidget(self.table if rows else self.empty)
        self._sync_buttons()

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

    def _sync_buttons(self) -> None:
        self.open_button.setEnabled(self.selected_name() is not None)
