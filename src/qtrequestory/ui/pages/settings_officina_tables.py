"""The two tables of Impostazioni → Officina: generators and header profile.

Both show their problems *in the row*: a last "Problema" column, word-wrapped,
in the theme's bad colour, visible only while some row has a problem. The
rules themselves are the core's (``generator_problems``, ``header_problems``);
the section computes them and hands each table its rows' messages.

A row left completely blank is not a row: a freshly added line the user never
filled in is neither saved nor reported (as in the environments table).

The generators table never *shows* a URL query: it can carry a signature, so
the URL column is drawn through :func:`shown_url` (``…?***``). The full URL is only in the
cell's editor, where the user typed it. Nothing here logs anything.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from urllib.parse import urlsplit

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
)

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import GeneratorEndpoint

__all__ = ["GeneratorTable", "HeaderTable", "shown_url"]

#: Marks the name cell of the default generator (follows the row, not the name).
DEFAULT_ROLE = Qt.ItemDataRole.UserRole + 1
#: Marks the row that was the default until the user disabled it: ticking it
#: again makes it the default again.
DISABLED_DEFAULT_ROLE = Qt.ItemDataRole.UserRole + 2
#: Enough for a header and three rows; the page scrolls, the table grows.
MIN_TABLE_HEIGHT = 132


def shown_url(url: str) -> str:
    """``url`` as the table draws it: unchanged, unless it has a query, a
    fragment or credentials, which may hold a secret. Then only scheme, host
    and path are kept, and the rest becomes ``?***``."""
    if not any(mark in url for mark in ("?", "#", "@")):
        return url
    try:
        parts = urlsplit(url)
        host = parts.netloc.rsplit("@", 1)[-1]
    except ValueError:
        parts = None
    if parts is None or not parts.scheme or not host:  # not a URL: cut at the first mark
        return re.split(r"[?#@]", url, maxsplit=1)[0] + "?***"
    return f"{parts.scheme}://{host}{parts.path}?***"


class _MaskedUrlDelegate(QStyledItemDelegate):
    def displayText(self, value, locale) -> str:  # noqa: N802 - Qt naming
        return shown_url(str(value))


class _ProblemTable(QTableWidget):
    """An editable table whose last column holds each row's problems."""

    #: Every *user* edit (typing, ticking, adding, removing); never a load.
    changed = Signal()
    COL_PROBLEM = -1  # set by the subclasses

    def __init__(self, labels: Sequence[str], parent=None) -> None:
        super().__init__(0, len(labels), parent)
        self.setHorizontalHeaderLabels(list(labels))
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setAlternatingRowColors(True)
        self.setWordWrap(True)
        self.setMinimumHeight(MIN_TABLE_HEIGHT)
        theme.set_table_look(self)
        self._problems: dict[int, list[str]] = {}
        self.setColumnHidden(self.COL_PROBLEM, True)
        self.itemChanged.connect(lambda _item: self.changed.emit())
        theme.signals.changed.connect(self._paint_problems)

    # -- rows ----------------------------------------------------------------

    def remove_rows(self, rows: Iterable[int]) -> int:
        doomed = sorted(set(rows), reverse=True)
        if not doomed:
            return 0
        with QSignalBlocker(self):
            for row in doomed:
                self.removeRow(row)
        self.changed.emit()
        return len(doomed)

    def remove_selected(self) -> int:
        return self.remove_rows(index.row() for index in self.selectedIndexes())

    def _new_row(self, cells: Sequence[QTableWidgetItem]) -> int:
        row = self.rowCount()
        with QSignalBlocker(self):
            self.insertRow(row)
            for column, item in enumerate(cells):
                self.setItem(row, column, item)
            self.setItem(row, self.COL_PROBLEM, _readonly(""))
        return row

    def text(self, row: int, column: int) -> str:
        item = self.item(row, column)
        return item.text() if item is not None else ""

    # -- problems ------------------------------------------------------------

    def show_problems(self, by_row: dict[int, list[str]]) -> None:
        """Show each row's problems in its last cell (and nothing elsewhere)."""
        self._problems = {row: list(found) for row, found in by_row.items() if found}
        with QSignalBlocker(self):
            for row in range(self.rowCount()):
                self.setItem(row, self.COL_PROBLEM,
                             _readonly("\n".join(self._problems.get(row, []))))
        self._paint_problems()
        self.setColumnHidden(self.COL_PROBLEM, not self._problems)
        self.resizeRowsToContents()

    def problem_text(self, row: int) -> str:
        return "\n".join(self._problems.get(row, []))

    def _paint_problems(self) -> None:
        tokens = theme.tokens()
        with QSignalBlocker(self):
            for row in range(self.rowCount()):
                item = self.item(row, self.COL_PROBLEM)
                if item is None:
                    continue
                bad = row in self._problems
                item.setForeground(QBrush(QColor(tokens.bad)) if bad else QBrush())

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        if self._problems:
            self.resizeRowsToContents()  # the wrapped messages follow the width


class GeneratorTable(_ProblemTable):
    """[Attivo | Nome | URL | Problema]; one row may be marked as the default."""

    COL_ENABLED = 0
    COL_NAME = 1
    COL_URL = 2
    COL_PROBLEM = 3

    def __init__(self, parent=None) -> None:
        super().__init__([strings.ENV_COL_ENABLED, strings.ENV_COL_NAME, strings.ENV_COL_URL,
                          strings.SETTINGS_OFFICINA_COL_PROBLEM], parent)
        header = self.horizontalHeader()
        header.setSectionResizeMode(self.COL_ENABLED, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.COL_NAME, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(self.COL_URL, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(self.COL_PROBLEM, QHeaderView.ResizeMode.Stretch)
        self.setColumnWidth(self.COL_NAME, 140)
        self._url_delegate = _MaskedUrlDelegate(self)
        self.setItemDelegateForColumn(self.COL_URL, self._url_delegate)

    def set_generators(self, generators: Sequence[GeneratorEndpoint], default: str) -> None:
        """Replace the rows (silently: a load, not an edit); the first enabled
        row named ``default`` becomes the default."""
        with QSignalBlocker(self):
            self.setRowCount(0)
        for g in generators:
            self._append(g)
        match = next((row for row, g in self.entries() if g.enabled and g.name == default), None)
        self.set_default_row(match)
        self.show_problems({})

    def add_row(self, generator: GeneratorEndpoint | None = None) -> int:
        row = self._append(generator or GeneratorEndpoint("", "", True))
        self.setCurrentCell(row, self.COL_NAME)
        self.changed.emit()
        return row

    def entries(self) -> list[tuple[int, GeneratorEndpoint]]:
        """``(row, generator)`` for every row that is not blank, trimmed."""
        found: list[tuple[int, GeneratorEndpoint]] = []
        for row in range(self.rowCount()):
            name = self.text(row, self.COL_NAME).strip()
            url = self.text(row, self.COL_URL).strip()
            if name or url:
                found.append((row, GeneratorEndpoint(name, url, self.is_enabled(row))))
        return found

    def generators(self) -> list[GeneratorEndpoint]:
        return [g for _row, g in self.entries()]

    def is_enabled(self, row: int) -> bool:
        item = self.item(row, self.COL_ENABLED)
        return item is not None and item.checkState() == Qt.CheckState.Checked

    def default_row(self) -> int | None:
        return self._marked(DEFAULT_ROLE)

    def set_default_row(self, row: int | None) -> None:
        self._mark(DEFAULT_ROLE, row)

    def disabled_default_row(self) -> int | None:
        return self._marked(DISABLED_DEFAULT_ROLE)

    def set_disabled_default_row(self, row: int | None) -> None:
        self._mark(DISABLED_DEFAULT_ROLE, row)

    def _marked(self, role: int) -> int | None:
        for row in range(self.rowCount()):
            item = self.item(row, self.COL_NAME)
            if item is not None and item.data(role):
                return row
        return None

    def _mark(self, role: int, row: int | None) -> None:
        with QSignalBlocker(self):
            for r in range(self.rowCount()):
                item = self.item(r, self.COL_NAME)
                if item is not None:
                    item.setData(role, r == row)

    def _append(self, g: GeneratorEndpoint) -> int:
        check = QTableWidgetItem()
        check.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                       | Qt.ItemFlag.ItemIsUserCheckable)
        check.setCheckState(Qt.CheckState.Checked if g.enabled else Qt.CheckState.Unchecked)
        return self._new_row([check, QTableWidgetItem(g.name), QTableWidgetItem(g.url)])


class HeaderTable(_ProblemTable):
    """[Nome | Valore | Problema]: the header profile, in its saved order."""

    COL_NAME = 0
    COL_VALUE = 1
    COL_PROBLEM = 2

    def __init__(self, parent=None) -> None:
        super().__init__([strings.SETTINGS_OFFICINA_COL_HEADER, strings.SETTINGS_OFFICINA_COL_VALUE,
                          strings.SETTINGS_OFFICINA_COL_PROBLEM], parent)
        header = self.horizontalHeader()
        for column in (self.COL_NAME, self.COL_VALUE, self.COL_PROBLEM):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)

    def set_rows(self, profile: dict[str, str]) -> None:
        with QSignalBlocker(self):
            self.setRowCount(0)
        for name, value in profile.items():
            self._new_row([QTableWidgetItem(name), QTableWidgetItem(value)])
        self.show_problems({})

    def add_row(self, name: str = "", value: str = "") -> int:
        row = self._new_row([QTableWidgetItem(name), QTableWidgetItem(value)])
        self.setCurrentCell(row, self.COL_NAME)
        self.changed.emit()
        return row

    def entries(self) -> list[tuple[int, tuple[str, str]]]:
        """``(row, (name, value))`` for every row that is not blank; the name
        is trimmed, the value kept as typed (the generator trims it)."""
        found: list[tuple[int, tuple[str, str]]] = []
        for row in range(self.rowCount()):
            name = self.text(row, self.COL_NAME).strip()
            value = self.text(row, self.COL_VALUE)
            if name or value.strip():
                found.append((row, (name, value)))
        return found

    def rows(self) -> list[tuple[str, str]]:
        return [pair for _row, pair in self.entries()]


def _readonly(text: str) -> QTableWidgetItem:
    """A problem cell: not editable, and not selectable either, so a selected
    row keeps its message in the bad colour instead of the selection's."""
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled)
    return item
