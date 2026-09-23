"""The Ricerca results: a model over ``list[SearchHit]``, flat or grouped by FDI.

Columns: Quando · Template key · FDI · Doc · Dim. (the view hides FDI while
grouped — the group row already names it, whole).

**Grouped** (the default, the user's decision): one top-level row per FDI,
``"<fdi completo> · dd/MM/yyyy HH:mm:ss · N chiamate"``, with its calls as
children. All the calls of a pratica arrive within the same second, so an FDI
repeated on eight rows was noise; the group says it once. A child shows only
its time, unless its group spans several days.

**Sorting** is done by the model itself (``sort()``), not by a proxy: a proxy
sorts each level on its own, and a group has to move with its best row. The
leaves are sorted on :data:`ResultsModel.SORT_ROLE` — a comparable Python key
per column, never the rendered text, so "10" does not sort before "2" — and
the groups follow the order in which their first leaf appears. Column ``-1``
is the order the core delivered: most recent first.

No widget is needed to exercise any of this: the rendering contract is
unit-tested, not eyeballed.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from PySide6.QtCore import QAbstractItemModel, QModelIndex, QObject, Qt
from PySide6.QtGui import QFont, QGuiApplication

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import SearchHit
from qtrequestory.ui.pages import sync_format

__all__ = ["ResultsModel", "format_day", "format_size", "format_time"]

_ALIGN_RIGHT = int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
_ALIGN_LEFT = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
#: ``internalId`` of a top-level row; a child of group ``g`` carries ``g + 1``.
_TOP = 0


# -------------------------------------------------------------- formatters ---

def format_day(day: date) -> str:
    return f"{day:%d/%m/%Y}"


def format_time(request_date: str | None) -> str:
    """``HH:MM:SS`` of an ISO timestamp, as it appears in the log.

    Shown in the timezone the log carries (UTC), not converted: the operator
    compares it with the caller's trace. A timestamp the parser cannot read is
    shown verbatim — an unexpected format is information, not an absence.
    """
    if not request_date:
        return strings.SEARCH_VALUE_MISSING
    try:
        stamp = datetime.fromisoformat(request_date.replace("Z", "+00:00"))
    except ValueError:
        return request_date
    return f"{stamp:%H:%M:%S}"


def format_size(n_bytes: int) -> str:
    """Whole kilobytes, rounded UP (the UI's one size formatter, whole-KB mode)."""
    return sync_format.format_size(n_bytes, whole_kb=True)


def _when(hit: SearchHit, *, with_date: bool) -> str:
    time = format_time(hit.request_date)
    return f"{hit.day:%d/%m} {time}" if with_date else time


def _time_key(hit: SearchHit) -> tuple:
    """The core's ORDER BY as a tuple: day, dated after undated, time, sequence."""
    return (hit.day.toordinal(), hit.request_date is not None, hit.request_date or "", hit.seq)


@dataclass
class _Group:
    fdi: str | None
    hits: list[SearchHit] = field(default_factory=list)

    def newest(self) -> SearchHit:
        return max(self.hits, key=_time_key)

    def label(self) -> str:
        newest = self.newest()
        when = format_day(newest.day)
        if newest.request_date:
            when += " " + format_time(newest.request_date)
        n = len(self.hits)
        calls = (strings.SEARCH_SUMMARY_CALLS_ONE if n == 1
                 else strings.SEARCH_SUMMARY_CALLS_MANY.format(n=n))
        return strings.SEARCH_GROUP_LABEL.format(
            fdi=self.fdi or strings.SEARCH_GROUP_NO_FDI, when=when, calls=calls)

    def one_day(self) -> bool:
        return len({h.day for h in self.hits}) == 1


# ------------------------------------------------------------------- model ---

class ResultsModel(QAbstractItemModel):
    """The rows of one search, flat or under their FDI."""

    COL_WHEN = 0
    COL_KEY = 1
    COL_FDI = 2
    COL_NDOCS = 3
    COL_SIZE = 4

    COLUMNS: tuple[str, ...] = (
        strings.SEARCH_COL_WHEN, strings.SEARCH_COL_KEY, strings.SEARCH_COL_FDI,
        strings.SEARCH_COL_NDOCS, strings.SEARCH_COL_SIZE,
    )
    NUMERIC_COLUMNS = (COL_NDOCS, COL_SIZE)
    #: A leaf answers this role with its ``SearchHit``; a group row with None.
    HIT_ROLE = Qt.ItemDataRole.UserRole
    #: The comparable key the sort uses.
    SORT_ROLE = Qt.ItemDataRole.UserRole + 1
    #: A group row answers this with its FDI ("" for the no-FDI group); leaves with None.
    GROUP_ROLE = Qt.ItemDataRole.UserRole + 2

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._hits: list[SearchHit] = []
        self._order: list[SearchHit] = []
        self._groups: list[_Group] = []
        self._grouped = True
        self._sort: tuple[int, Qt.SortOrder] = (-1, Qt.SortOrder.AscendingOrder)
        self._fonts: dict[str, QFont] = {}

    # -- contents ----------------------------------------------------------

    def set_hits(self, hits: Sequence[SearchHit]) -> None:
        """Replace every row (a search is always a full refresh)."""
        self.beginResetModel()
        self._hits = list(hits)
        self._fonts = {}
        self._rebuild()
        self.endResetModel()

    def hits(self) -> list[SearchHit]:
        return list(self._hits)

    def set_grouped(self, grouped: bool) -> None:
        if grouped == self._grouped:
            return
        self.beginResetModel()
        self._grouped = grouped
        self._rebuild()
        self.endResetModel()

    def grouped(self) -> bool:
        return self._grouped

    def sort_column(self) -> int:
        return self._sort[0]

    def sort_order(self) -> Qt.SortOrder:
        return self._sort[1]

    def hit_of(self, index: QModelIndex) -> SearchHit | None:
        """The hit of a leaf; None for a group row or an invalid index."""
        if not index.isValid():
            return None
        if not self._grouped:
            row = index.row()
            return self._order[row] if 0 <= row < len(self._order) else None
        group_id = index.internalId()
        if group_id == _TOP:
            return None
        hits = self._groups[group_id - 1].hits
        return hits[index.row()] if 0 <= index.row() < len(hits) else None

    def is_group(self, index: QModelIndex) -> bool:
        return self._grouped and index.isValid() and index.internalId() == _TOP

    def index_of(self, hit: SearchHit, column: int = 0) -> QModelIndex:
        """Where ``hit`` is now (inside its group when grouped); invalid if absent."""
        if not self._grouped:
            for row, candidate in enumerate(self._order):
                if candidate == hit:
                    return self.index(row, column)
            return QModelIndex()
        for group_row, group in enumerate(self._groups):
            for row, candidate in enumerate(group.hits):
                if candidate == hit:
                    return self.index(row, column, self.index(group_row, 0))
        return QModelIndex()

    def group_index(self, fdi: str | None) -> QModelIndex:
        for row, group in enumerate(self._groups):
            if group.fdi == fdi:
                return self.index(row, 0)
        return QModelIndex()

    # -- sorting -----------------------------------------------------------

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        """Re-order the leaves (and the groups after them); keeps persistent indexes."""
        self.layoutAboutToBeChanged.emit()
        old = self.persistentIndexList()
        anchors = [(self.hit_of(i), self._group_fdi(i), i.column()) for i in old]
        self._sort = (column, order)
        self._rebuild()
        new = []
        for hit, fdi, col in anchors:
            if hit is not None:
                new.append(self.index_of(hit, col))
            else:
                group = self.group_index(fdi) if self._grouped else QModelIndex()
                new.append(group.siblingAtColumn(col) if group.isValid() else QModelIndex())
        self.changePersistentIndexList(old, new)
        self.layoutChanged.emit()

    def _rebuild(self) -> None:
        column, order = self._sort
        if column < 0:
            self._order = list(self._hits)
        else:
            self._order = sorted(self._hits, key=lambda h: _sort_key(h, column),
                                 reverse=order == Qt.SortOrder.DescendingOrder)
        self._groups = []
        if self._grouped:
            by_fdi: dict[str | None, _Group] = {}
            for hit in self._order:
                group = by_fdi.get(hit.fdi)
                if group is None:
                    group = by_fdi[hit.fdi] = _Group(hit.fdi)
                    self._groups.append(group)
                group.hits.append(hit)

    def _group_fdi(self, index: QModelIndex) -> str | None:
        if self.is_group(index) and 0 <= index.row() < len(self._groups):
            return self._groups[index.row()].fdi
        return None

    # -- QAbstractItemModel ------------------------------------------------

    def index(self, row: int, column: int, parent: QModelIndex = QModelIndex()) -> QModelIndex:
        if not self.hasIndex(row, column, parent):
            return QModelIndex()
        if not parent.isValid():
            return self.createIndex(row, column, _TOP)
        return self.createIndex(row, column, parent.row() + 1)

    def parent(self, index: QModelIndex | None = None) -> Any:  # noqa: D102 - Qt override
        if index is None:  # QObject.parent()
            return super().parent()
        if not self._grouped or not index.isValid() or index.internalId() == _TOP:
            return QModelIndex()
        return self.createIndex(index.internalId() - 1, 0, _TOP)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if not parent.isValid():
            return len(self._groups) if self._grouped else len(self._order)
        if self.is_group(parent) and parent.column() == 0:
            return len(self._groups[parent.row()].hits)
        return 0

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return len(self.COLUMNS)

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        if self.is_group(index):
            return Qt.ItemFlag.ItemIsEnabled
        return (Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsDragEnabled)

    def headerData(self, section: int, orientation: Qt.Orientation,  # noqa: N802
                   role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if orientation != Qt.Orientation.Horizontal or not 0 <= section < len(self.COLUMNS):
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return self.COLUMNS[section]
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return _ALIGN_RIGHT if section in self.NUMERIC_COLUMNS else _ALIGN_LEFT
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        if self.is_group(index):
            return self._group_data(index, role)
        hit = self.hit_of(index)
        if hit is None:
            return None
        column = index.column()
        if role == self.HIT_ROLE:
            return hit
        if role == self.SORT_ROLE:
            return _sort_key(hit, column)
        if role == Qt.ItemDataRole.DisplayRole:
            return self._display(index, hit, column)
        if role == Qt.ItemDataRole.ToolTipRole:
            return _tooltip(hit, column)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return _ALIGN_RIGHT if column in self.NUMERIC_COLUMNS else _ALIGN_LEFT
        if role == Qt.ItemDataRole.FontRole:
            return self._font("mono" if column in (self.COL_KEY, self.COL_FDI) else "figures")
        return None

    def _group_data(self, index: QModelIndex, role: int) -> Any:
        group = self._groups[index.row()]
        if role == self.GROUP_ROLE:
            return group.fdi or ""
        if index.column() != 0:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return group.label()
        if role == Qt.ItemDataRole.ToolTipRole:
            return group.fdi
        return None

    def _display(self, index: QModelIndex, hit: SearchHit, column: int) -> str:
        if column == self.COL_WHEN:
            one_day = self._grouped and self._groups[index.internalId() - 1].one_day()
            return _when(hit, with_date=not one_day)
        if column == self.COL_KEY:
            return hit.template_key  # full text: the view's delegate elides it
        if column == self.COL_FDI:
            return hit.fdi or strings.SEARCH_VALUE_MISSING
        if column == self.COL_NDOCS:
            return strings.SEARCH_VALUE_UNKNOWN if hit.ndocs is None else str(hit.ndocs)
        return format_size(hit.body_len)

    def _font(self, kind: str) -> QFont:
        """Mono for identifiers; the UI font with tabular figures for numbers,
        so a column of times and sizes lines up digit under digit."""
        font = self._fonts.get(kind)
        if font is None:
            if kind == "mono":
                font = theme.mono_font()
            else:
                font = QFont(QGuiApplication.font())
                font.setFeature(QFont.Tag("tnum"), 1)
            self._fonts[kind] = font
        return font


def _tooltip(hit: SearchHit, column: int) -> str | None:
    """Only where the cell shows less than the log holds."""
    if column == ResultsModel.COL_WHEN:
        return f"{format_day(hit.day)} {hit.request_date or ''}".strip()
    if column == ResultsModel.COL_KEY:
        return hit.template_key
    if column == ResultsModel.COL_FDI:
        return hit.fdi
    return None


def _sort_key(hit: SearchHit, column: int) -> Any:
    if column == ResultsModel.COL_WHEN:
        return _time_key(hit)
    if column == ResultsModel.COL_KEY:
        return hit.template_key.lower()
    if column == ResultsModel.COL_FDI:
        return (hit.fdi or "").lower()
    if column == ResultsModel.COL_NDOCS:
        return -1 if hit.ndocs is None else int(hit.ndocs)
    return int(hit.body_len)

