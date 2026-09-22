"""The Ricerca table: a model over ``list[SearchHit]`` and its sorting proxy.

The table shows six columns plus two hidden ones (DESIGN-ui §"Ricerca page").
Three of them are *shortened* — the time without its date, the template key
elided in the middle, the FDI cut after eight characters — so every one of those
keeps the whole value in ``Qt.ToolTipRole``: nothing the log carries may become
unreachable just because the column is narrow.

Sorting deserves a word. The header is clickable, so the proxy must compare the
*values*, not the rendered text: "10" would otherwise sort before "2" and
``18/09/2026`` before ``15/09/2026``. The model therefore answers a second role,
:data:`ResultsModel.SORT_ROLE`, with a comparable Python key per column, and
:class:`ResultsProxy` does nothing but compare those. The Giorno/Ora key is the
core's own ordering — ``day``, then "has a timestamp", then the timestamp, then
the sequence in the file — so clicking Giorno descending reproduces exactly the
order the core delivered.

No Qt widget is needed to exercise any of this, which is the point: the
rendering contract of the table is unit-tested, not eyeballed.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QSortFilterProxyModel, Qt
from PySide6.QtWidgets import QStyledItemDelegate

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import SearchHit

__all__ = [
    "ElideMiddleDelegate", "ResultsModel", "ResultsProxy",
    "format_day", "format_fdi", "format_size", "format_time",
]

#: How much of the FDI fits in its column before the ellipsis.
FDI_PREFIX_LEN = 8

_ALIGN_RIGHT = int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
_ALIGN_LEFT = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)


# -------------------------------------------------------------- formatters ---

def format_day(day: date) -> str:
    return f"{day:%d/%m/%Y}"


def format_time(request_date: str | None) -> str:
    """``HH:MM:SS`` of an ISO timestamp, as it appears in the log.

    The value is shown in the timezone the log carries (UTC), not converted:
    the operator compares it with what the caller's trace says, and a silent
    shift by two hours would make that comparison wrong. A timestamp the parser
    cannot read is shown verbatim rather than hidden behind an em dash — an
    unexpected format is information, not an absence.
    """
    if not request_date:
        return strings.SEARCH_VALUE_MISSING
    try:
        stamp = datetime.fromisoformat(request_date.replace("Z", "+00:00"))
    except ValueError:
        return request_date
    return f"{stamp:%H:%M:%S}"


def format_size(n_bytes: int) -> str:
    """Whole kilobytes, rounded UP so a small body never reads as ``0 KB``."""
    kb = -(-int(n_bytes) // 1024)
    return strings.SEARCH_SIZE_KB.format(n=f"{kb:,}".replace(",", "."))


def format_fdi(fdi: str | None) -> str:
    if not fdi:
        return strings.SEARCH_VALUE_MISSING
    if len(fdi) <= FDI_PREFIX_LEN:
        return fdi
    return fdi[:FDI_PREFIX_LEN] + strings.SEARCH_ELLIPSIS


# ------------------------------------------------------------------- model ---

class ResultsModel(QAbstractTableModel):
    """The rows of one search, exactly as the core delivered them."""

    COL_DAY = 0
    COL_TIME = 1
    COL_KEY = 2
    COL_FDI = 3
    COL_NDOCS = 4
    COL_SIZE = 5
    COL_CALL_ID = 6
    COL_FILE = 7

    COLUMNS: tuple[str, ...] = (
        strings.SEARCH_COL_DAY, strings.SEARCH_COL_TIME, strings.SEARCH_COL_KEY,
        strings.SEARCH_COL_FDI, strings.SEARCH_COL_NDOCS, strings.SEARCH_COL_SIZE,
        strings.SEARCH_COL_CALL_ID, strings.SEARCH_COL_FILE,
    )
    #: Present in the model (so the value can be sorted and copied) but hidden
    #: in the view: technical identifiers nobody reads at a glance.
    HIDDEN_COLUMNS: tuple[int, ...] = (COL_CALL_ID, COL_FILE)
    #: Every cell of a row answers this role with the ``SearchHit`` behind it,
    #: so a view (or the proxy) never has to map a row back to a list index.
    HIT_ROLE = Qt.ItemDataRole.UserRole
    #: The comparable key :class:`ResultsProxy` sorts on.
    SORT_ROLE = Qt.ItemDataRole.UserRole + 1

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._hits: list[SearchHit] = []

    # -- contents ----------------------------------------------------------

    def set_hits(self, hits: Sequence[SearchHit]) -> None:
        """Replace every row (a search is always a full refresh)."""
        self.beginResetModel()
        self._hits = list(hits)
        self.endResetModel()

    def hits(self) -> list[SearchHit]:
        return list(self._hits)

    def hit_at(self, row: int) -> SearchHit | None:
        """The hit of ``row``, or None — a stale row index must not raise."""
        if 0 <= row < len(self._hits):
            return self._hits[row]
        return None

    # -- QAbstractTableModel ----------------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._hits)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.COLUMNS)

    def headerData(self, section: int, orientation: Qt.Orientation,  # noqa: N802
                   role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if role != Qt.ItemDataRole.DisplayRole or orientation != Qt.Orientation.Horizontal:
            return None
        return self.COLUMNS[section] if 0 <= section < len(self.COLUMNS) else None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        hit = self.hit_at(index.row()) if index.isValid() else None
        if hit is None:
            return None
        column = index.column()
        if role == self.HIT_ROLE:
            return hit
        if role == self.SORT_ROLE:
            return _sort_key(hit, column)
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return _display(hit, column)
        if role == Qt.ItemDataRole.ToolTipRole:
            return _tooltip(hit, column)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return _ALIGN_RIGHT if column in (self.COL_NDOCS, self.COL_SIZE) else _ALIGN_LEFT
        return None


def _display(hit: SearchHit, column: int) -> str:
    if column == ResultsModel.COL_DAY:
        return format_day(hit.day)
    if column == ResultsModel.COL_TIME:
        return format_time(hit.request_date)
    if column == ResultsModel.COL_KEY:
        return hit.template_key  # full text: ElideMiddleDelegate shortens it
    if column == ResultsModel.COL_FDI:
        return format_fdi(hit.fdi)
    if column == ResultsModel.COL_NDOCS:
        return strings.SEARCH_VALUE_UNKNOWN if hit.ndocs is None else str(hit.ndocs)
    if column == ResultsModel.COL_SIZE:
        return format_size(hit.body_len)
    if column == ResultsModel.COL_CALL_ID:
        return hit.call_id or strings.SEARCH_VALUE_MISSING
    return hit.rel_path


def _tooltip(hit: SearchHit, column: int) -> str | None:
    """Only where the cell shows less than the log holds."""
    if column == ResultsModel.COL_TIME:
        return hit.request_date
    if column == ResultsModel.COL_KEY:
        return hit.template_key
    if column == ResultsModel.COL_FDI:
        return hit.fdi
    if column == ResultsModel.COL_FILE:
        return str(hit.file_path)
    return None


def _sort_key(hit: SearchHit, column: int) -> Any:
    if column in (ResultsModel.COL_DAY, ResultsModel.COL_TIME):
        # The core's ORDER BY, as a tuple: day, then entries WITH a timestamp
        # after those without one, then the timestamp, then the file sequence.
        return (hit.day.toordinal(), hit.request_date is not None, hit.request_date or "", hit.seq)
    if column == ResultsModel.COL_KEY:
        return hit.template_key.lower()
    if column == ResultsModel.COL_FDI:
        return (hit.fdi or "").lower()
    if column == ResultsModel.COL_NDOCS:
        return -1 if hit.ndocs is None else int(hit.ndocs)
    if column == ResultsModel.COL_SIZE:
        return int(hit.body_len)
    if column == ResultsModel.COL_CALL_ID:
        return hit.call_id or ""
    return hit.rel_path


# ------------------------------------------------------------------- proxy ---

class ResultsProxy(QSortFilterProxyModel):
    """Sorts on :data:`ResultsModel.SORT_ROLE`, filters nothing.

    There is no filter row on the page — narrowing a result set is what the form
    is for — so this exists purely to give the header a correct comparison.
    Sorted with column ``-1`` (the page's initial state) it passes the source
    order through untouched, which is "most recent first" from the core.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.setSortRole(ResultsModel.SORT_ROLE)
        self.setDynamicSortFilter(True)

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:  # noqa: N802
        """Compare the two Python keys; Qt's own QVariant order cannot.

        ``SORT_ROLE`` returns tuples, ints and strings — never a type Qt knows
        how to order — so without this every column would fall back to the
        rendered text.
        """
        a = left.data(ResultsModel.SORT_ROLE)
        b = right.data(ResultsModel.SORT_ROLE)
        try:
            return bool(a < b)
        except TypeError:  # mixed types (should not happen: keys are per column)
            return str(a) < str(b)


# ---------------------------------------------------------------- delegate ---

class ElideMiddleDelegate(QStyledItemDelegate):
    """Elides in the MIDDLE, for the template key column.

    Template keys differ at both ends (``MOD_TEST_SDS_…_GAS`` versus
    ``…_LUCE``): Qt's default right elision would cut off precisely the part
    that tells two of them apart.
    """

    def initStyleOption(self, option, index: QModelIndex) -> None:  # noqa: N802
        super().initStyleOption(option, index)
        option.textElideMode = Qt.TextElideMode.ElideMiddle
