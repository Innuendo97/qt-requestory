"""The [Attivo | Nome | URL] environments table.

Two places edit the same list of environments — the first-run wizard and the
Impostazioni page — and they must behave identically, so the widget lives here
and both import it.

It deliberately knows nothing about ``CoreServices``: importing a file takes the
*importer callable* as an argument (``services.config.import_environments_file``)
instead of the services bundle, which keeps the widget testable with a two-line
stub and keeps the error dialog in the page that owns the window.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import Environment

EnvironmentImporter = Callable[[Path], list[Environment]]


class EnvTable(QTableWidget):
    """Editable list of environments with a checkbox for ``enabled``.

    ``changed`` fires on every *user* edit (typing, toggling, adding, removing,
    importing) and never on :meth:`set_environments`, because the pages use it
    to enable their [Salva] button: filling the form programmatically is not a
    change the user made.
    """

    COL_ENABLED = 0
    COL_NAME = 1
    COL_URL = 2

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(0, 3, parent)
        self.setHorizontalHeaderLabels(
            [strings.ENV_COL_ENABLED, strings.ENV_COL_NAME, strings.ENV_COL_URL]
        )
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setAlternatingRowColors(True)
        theme.set_table_look(self)
        header = self.horizontalHeader()
        header.setSectionResizeMode(self.COL_ENABLED, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.COL_NAME, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.COL_URL, QHeaderView.ResizeMode.Stretch)
        self.itemChanged.connect(self._on_item_changed)

    # -- contents ----------------------------------------------------------

    def set_environments(self, envs: Sequence[Environment]) -> None:
        """Replace the contents. Silent: this is a load, not an edit."""
        with QSignalBlocker(self):
            self.setRowCount(0)
            for env in envs:
                self._append(env)

    def environments(self) -> list[Environment]:
        """The rows, trimmed. Rows left completely blank are ignored — a freshly
        added row the user never filled in is not an environment, and passing it
        to ``config.validate`` would produce a confusing error."""
        result: list[Environment] = []
        for row in range(self.rowCount()):
            name = self._text(row, self.COL_NAME)
            url = self._text(row, self.COL_URL)
            if not name and not url:
                continue
            enabled = self.item(row, self.COL_ENABLED).checkState() == Qt.CheckState.Checked
            result.append(Environment(name=name, url=url, enabled=enabled))
        return result

    def add_row(self, env: Environment | None = None) -> int:
        """Append a row (empty and enabled by default) and focus its name cell."""
        with QSignalBlocker(self):
            row = self._append(env if env is not None else Environment("", "", True))
        self.setCurrentCell(row, self.COL_NAME)
        self.changed.emit()
        return row

    def remove_selected(self) -> int:
        """Remove every selected row; returns how many were removed."""
        rows = sorted({index.row() for index in self.selectedIndexes()}, reverse=True)
        if not rows:
            return 0
        with QSignalBlocker(self):
            for row in rows:
                self.removeRow(row)
        self.changed.emit()
        return len(rows)

    def import_from_file(self, path: Path, importer: EnvironmentImporter) -> list[Environment]:
        """Replace the rows with the contents of ``path``.

        ``importer`` is ``services.config.import_environments_file``; its
        ``ValueError`` propagates untouched (and the table is left as it was) so
        the calling page can show the file name in the message.
        """
        envs = importer(path)
        self.set_environments(envs)
        self.changed.emit()
        return envs

    # -- internals ---------------------------------------------------------

    def _append(self, env: Environment) -> int:
        row = self.rowCount()
        self.insertRow(row)
        check = QTableWidgetItem()
        check.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsUserCheckable
        )
        check.setCheckState(Qt.CheckState.Checked if env.enabled else Qt.CheckState.Unchecked)
        self.setItem(row, self.COL_ENABLED, check)
        self.setItem(row, self.COL_NAME, QTableWidgetItem(env.name))
        self.setItem(row, self.COL_URL, QTableWidgetItem(env.url))
        return row

    def _text(self, row: int, column: int) -> str:
        item = self.item(row, column)
        return item.text().strip() if item is not None else ""

    def _on_item_changed(self, _item: QTableWidgetItem) -> None:
        self.changed.emit()
