"""The Ricerca results view: a tree of FDI groups (or a flat list) of calls.

* **Group rows** span every column and are painted by :class:`ResultsDelegate`
  — the FDI in mono, the time and count muted. They cannot be selected: the
  arrow keys jump over them (:meth:`ResultsView.moveCursor`), so walking down
  the list always lands on a call and the preview always has something to show.
* **Columns:** Quando, Doc and Dim. size to their contents, the numbers
  right-aligned side by side at the right edge (headers too, see
  :class:`ResultsHeader`); the template key takes the rest, elided in the
  middle when short of room (keys differ at both ends: ``…_LUCE`` /
  ``…_GAS``); the FDI column (flat mode only) is as wide as a whole uuid, at
  most :data:`FDI_MAX_WIDTH`, elided in the middle below that — so the flat
  list fits a 1366 px screen without a horizontal scroll bar.
* **Enter** on a call opens it (the page opens a double-clicked call too).
* **Drag out:** dragging a call hands the file manager (or Notepad++, or an
  e-mail) a real ``.json`` file — written on drag start by ``drag_provider``.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtCore import QMimeData, QModelIndex, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDrag, QFont, QFontMetrics
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionHeader,
    QStyleOptionViewItem,
    QTreeView,
    QWidget,
)

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import SearchHit, SearchQuery, pick_best
from qtrequestory.ui.results_model import ResultsModel

__all__ = ["FDI_MAX_WIDTH", "KEY_MIN_WIDTH", "ResultsDelegate", "ResultsHeader", "ResultsView", "mime_for_file", "preselect", "sort_tail"]

#: The template key column is never narrower than this.
KEY_MIN_WIDTH = 160
#: The FDI column (flat mode) fits a whole uuid, but never more than this.
FDI_MAX_WIDTH = 320
#: Horizontal padding of a header label (the stylesheet's ``padding: 5px 8px``).
HEADER_PADDING = 8
#: Room kept for the sort arrow at the right of a sorted numeric header.
SORT_ARROW_ROOM = 14
#: Indentation of the calls under their group.
INDENT = 14
_FORWARD = (QAbstractItemView.CursorAction.MoveDown, QAbstractItemView.CursorAction.MovePageDown,
            QAbstractItemView.CursorAction.MoveHome, QAbstractItemView.CursorAction.MoveNext)


def mime_for_file(path: Path) -> QMimeData:
    """What a drag carries: the file itself, as a local URL."""
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    return mime


def preselect(hits: Sequence[SearchHit], query: SearchQuery | None) -> SearchHit:
    """The row to select after a search (``hits`` newest first, never empty).

    For an FDI-only search: the entry carrying the most documents on the newest
    day — ``pick_best(prefer_most_documents=True)``, the pratica's whole body,
    what README promises. Otherwise the newest call.
    """
    if query is not None and query.fdi_prefix and not query.template_key:
        best, _rest = pick_best(list(hits), prefer_most_documents=True)
        if best is not None:
            return best
    return hits[0]


def sort_tail(model: ResultsModel) -> str:
    """The summary's tail: "ordinate dalla più recente" only when that is true."""
    column, order = model.sort_column(), model.sort_order()
    if column < 0 or (column == ResultsModel.COL_WHEN and order == Qt.SortOrder.DescendingOrder):
        return strings.SEARCH_SUMMARY_TAIL
    return strings.SEARCH_SUMMARY_TAIL_COLUMN.format(column=ResultsModel.COLUMNS[column])


class ResultsDelegate(QStyledItemDelegate):
    """Group rows: FDI (mono) + muted details. Template keys: elided in the middle."""

    def initStyleOption(self, option: QStyleOptionViewItem, index: QModelIndex) -> None:  # noqa: N802
        super().initStyleOption(option, index)
        if index.column() in (ResultsModel.COL_KEY, ResultsModel.COL_FDI):
            option.textElideMode = Qt.TextElideMode.ElideMiddle

    def paint(self, painter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        model = index.model()
        if not (isinstance(model, ResultsModel) and model.is_group(index)):
            super().paint(painter, option, index)
            return
        tokens = theme.tokens()
        painter.save()
        painter.fillRect(option.rect, QColor(tokens.surface2))
        fdi = model.data(index, ResultsModel.GROUP_ROLE) or strings.SEARCH_GROUP_NO_FDI
        label = model.data(index, Qt.ItemDataRole.DisplayRole) or ""
        rest = label[len(fdi):] if label.startswith(fdi) else ""
        rect = option.rect.adjusted(6, 0, -6, 0)
        mono = theme.mono_font()
        mono.setWeight(QFont.Weight.Medium)
        painter.setFont(mono)
        painter.setPen(QColor(tokens.text))
        align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        painter.drawText(rect, align, fdi)
        rect.setLeft(rect.left() + QFontMetrics(mono).horizontalAdvance(fdi))
        painter.setFont(option.font)
        painter.setPen(QColor(tokens.muted))
        painter.drawText(rect, align, QFontMetrics(option.font).elidedText(
            rest, Qt.TextElideMode.ElideRight, rect.width()))
        painter.restore()


class ResultsHeader(QHeaderView):
    """A header whose numeric sections are right-aligned, over their numbers.

    The application stylesheet sets ``text-align: left`` on every header
    section, and a stylesheet wins over the model's alignment; so the numeric
    sections draw their background with the style and their label here.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)

    def paintSection(self, painter, rect, index: int) -> None:  # noqa: N802 - Qt naming
        if index not in ResultsModel.NUMERIC_COLUMNS:
            super().paintSection(painter, rect, index)
            return
        painter.save()
        option = QStyleOptionHeader()
        self.initStyleOptionForIndex(option, index)
        option.rect = rect
        label = option.text
        option.text = ""
        self.style().drawControl(QStyle.ControlElement.CE_Header, option, painter, self)
        painter.restore()
        painter.save()
        font = QFont(self.font())
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor(theme.tokens().muted))
        right = HEADER_PADDING
        if self.isSortIndicatorShown() and self.sortIndicatorSection() == index:
            right += SORT_ARROW_ROOM
        painter.drawText(rect.adjusted(HEADER_PADDING, 0, -right, 0),
                         int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), label)
        painter.restore()


class ResultsView(QTreeView):
    """The results, with the behaviours the page relies on."""

    open_requested = Signal()

    def __init__(self, model: ResultsModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.results = model
        self.setObjectName("results")  # its own row padding in the stylesheet
        #: ``hit -> path`` of the file a drag hands out; None disables drag-out.
        self.drag_provider: Callable[[SearchHit], Path | None] | None = None
        self.setModel(model)
        self.setItemDelegate(ResultsDelegate(self))
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setAlternatingRowColors(True)
        self.setUniformRowHeights(True)
        self.setAllColumnsShowFocus(True)
        self.setIndentation(INDENT)
        self.setWordWrap(False)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header = ResultsHeader(self)
        self.setHeader(header)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setHighlightSections(False)
        header.setSectionsClickable(True)
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(40)
        for column in (ResultsModel.COL_WHEN, ResultsModel.COL_NDOCS, ResultsModel.COL_SIZE):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(ResultsModel.COL_KEY, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(ResultsModel.COL_FDI, QHeaderView.ResizeMode.Interactive)
        # Sorted by NOTHING to start with: the core's order, most recent first.
        header.setSortIndicator(-1, Qt.SortOrder.DescendingOrder)
        self.setSortingEnabled(True)
        model.modelReset.connect(self._after_reset)
        model.layoutChanged.connect(self._span_groups)
        self._after_reset()

    # -- selection ---------------------------------------------------------

    def selected_hit(self) -> SearchHit | None:
        rows = self.selectionModel().selectedRows()
        return self.results.hit_of(rows[0]) if rows else None

    def select_hit(self, hit: SearchHit | None) -> None:
        index = self.results.index_of(hit) if hit is not None else QModelIndex()
        if not index.isValid():
            self.clearSelection()
            return
        self.setCurrentIndex(index)
        self.scrollTo(index)

    def is_group(self, index: QModelIndex) -> bool:
        return self.results.is_group(index)

    # -- layout ------------------------------------------------------------

    def fit_fdi_column(self) -> None:
        wanted = max(self.sizeHintForColumn(ResultsModel.COL_FDI),
                     self.header().sectionSizeHint(ResultsModel.COL_FDI))
        self.header().resizeSection(ResultsModel.COL_FDI, min(wanted, FDI_MAX_WIDTH))

    def _after_reset(self) -> None:
        grouped = self.results.grouped()
        self.setRootIsDecorated(grouped)
        self.setColumnHidden(ResultsModel.COL_FDI, grouped)
        self._span_groups()
        self.expandAll()
        self.fit_fdi_column()

    def _span_groups(self) -> None:
        root = QModelIndex()
        for row in range(self.results.rowCount()):
            self.setFirstColumnSpanned(row, root, self.results.is_group(self.results.index(row, 0)))

    # -- keys, mouse, drag -------------------------------------------------

    def moveCursor(self, action, modifiers) -> QModelIndex:  # noqa: N802 - Qt naming
        """Never stop on a group row: step past it in the direction of travel."""
        index = super().moveCursor(action, modifiers)
        forward = action in _FORWARD
        while index.isValid() and self.is_group(index):
            index = self.indexBelow(index) if forward else self.indexAbove(index)
        return index if index.isValid() else self.currentIndex()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.selected_hit():
            self.open_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def startDrag(self, supported) -> None:  # noqa: N802 - Qt naming
        hit = self.selected_hit()
        if hit is None or self.drag_provider is None:
            return
        path = self.drag_provider(hit)
        if path is None:
            return
        drag = QDrag(self)
        drag.setMimeData(mime_for_file(path))
        drag.exec(Qt.DropAction.CopyAction)
