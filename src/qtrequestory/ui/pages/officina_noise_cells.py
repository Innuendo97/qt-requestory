"""Cells of the noise rules dialog (``officina_noise``): the count text
and the small table / item / label factories. Split for size."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QLabel, QTableWidget, QTableWidgetItem

from qtrequestory.ui import strings, theme

__all__ = ["hits_text", "make_item", "make_label", "make_table"]


def hits_text(value: int | str | None) -> str:
    if value is None:
        return strings.RUMORE_HITS_UNKNOWN
    if isinstance(value, str):
        return value
    if value == 0:
        return strings.RUMORE_HITS_NONE
    return strings.RUMORE_HITS_ONE if value == 1 else strings.RUMORE_HITS_MANY.format(n=value)


def make_table(columns: tuple[str, ...], editable: bool) -> QTableWidget:
    table = QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels(list(columns))
    table.verticalHeader().setVisible(False)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    if not editable:
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    header.setStretchLastSection(True)
    table.setColumnWidth(0, 190)
    if len(columns) == 3:
        table.setColumnWidth(1, 250)
    theme.set_table_look(table)
    return table


def make_item(text: str, *, editable: bool = False, check: bool | None = None) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
    if editable:
        flags |= Qt.ItemFlag.ItemIsEditable
    if check is not None:
        flags |= Qt.ItemFlag.ItemIsUserCheckable
        item.setCheckState(Qt.CheckState.Checked if check else Qt.CheckState.Unchecked)
    item.setFlags(flags)
    return item


def make_label(text: str, role: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    theme.set_role(label, role)
    return label
