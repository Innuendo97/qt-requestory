"""Genera's header table: Impostazioni's ``HeaderTable``, plus "automatico".

The table is the whole set of headers a run sends (spec "Header"). An
automatic name (``AUTOMATIC_HEADERS``: ``template_key``, ``current_timestamp``,
``correlation_id``, ``Postman-Token``) with an empty value is computed per
call; the empty cell says so with a muted, italic "automatico" — drawn by a
delegate, never stored, so it is not sent and not counted as a change.

A subclass rather than a change to ``HeaderTable``: Impostazioni's profile
has no automatic rows and must keep showing an empty value as empty. This is
the only place in the tab where header VALUES are shown.

**Whole rows only.** The table is exactly as tall as its rows (header + rows
+ frame), up to :data:`MAX_ROWS`; beyond that it scrolls one row at a time
and its height stays a whole number of rows — the old fixed 200 px always cut
the last visible row in half. :meth:`GeneraHeaderTable.add_and_edit`
("Aggiungi") appends a row, brings it into view and opens its name cell for
typing; :meth:`GeneraHeaderTable.commit_editing` closes a cell still open, so
a run started from inside it sends what it shows.
"""
from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics
from PySide6.QtWidgets import (
    QAbstractItemDelegate,
    QAbstractItemView,
    QApplication,
    QLineEdit,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidgetItem,
)

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import AUTOMATIC_HEADERS
from qtrequestory.ui.pages.settings_officina_tables import HeaderTable

__all__ = ["GeneraHeaderTable", "headers_summary", "is_automatic", "modified_count"]

_AUTOMATIC = frozenset(name.casefold() for name in AUTOMATIC_HEADERS)
#: The most rows shown at once; more scroll, a whole row at a time.
MAX_ROWS = 8
#: The fewest: an empty table still reads as a table.
MIN_ROWS = 2


def is_automatic(name: str) -> bool:
    return name.strip().casefold() in _AUTOMATIC


def modified_count(defaults: Sequence[tuple[str, str]], rows: Sequence[tuple[str, str]]) -> int:
    """Rows added or changed, plus default rows removed (names compare
    case-insensitively, as HTTP does)."""
    known = set(defaults)
    current_names = {name.strip().casefold() for name, _v in rows}
    changed = sum(1 for row in rows if row not in known)
    removed = sum(1 for name, _v in defaults if name.strip().casefold() not in current_names)
    return changed + removed


def headers_summary(defaults: Sequence[tuple[str, str]], rows: Sequence[tuple[str, str]]) -> str:
    """The collapsed section: "Header · 7 inviati · 1 modificato" (no values)."""
    n = sum(1 for name, _v in rows if name.strip())
    m = modified_count(defaults, rows)
    if not m:
        return strings.GENERA_HEADERS_SUMMARY.format(n=n)
    if m == 1:
        return strings.GENERA_HEADERS_SUMMARY_MODIFIED_ONE.format(n=n)
    return strings.GENERA_HEADERS_SUMMARY_MODIFIED.format(n=n, m=m)


class _AutomaticValueDelegate(QStyledItemDelegate):
    """The value column: an empty value on an automatic name reads "automatico"."""

    def _placeholder(self, index) -> str:
        name = index.siblingAtColumn(HeaderTable.COL_NAME).data() or ""
        value = str(index.data() or "")
        return strings.GENERA_HEADER_AUTOMATIC if not value.strip() and is_automatic(str(name)) else ""

    def paint(self, painter, option, index) -> None:
        placeholder = self._placeholder(index)
        if not placeholder:
            super().paint(painter, option, index)
            return
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        widget = opt.widget
        style = widget.style() if widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)
        rect = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, opt, widget)
        font = QFont(opt.font)
        font.setItalic(True)
        painter.save()
        painter.setFont(font)
        painter.setPen(QColor(theme.tokens().muted))
        text = QFontMetrics(font).elidedText(placeholder, Qt.TextElideMode.ElideRight,
                                             max(rect.width() - 12, 0))
        painter.drawText(rect.adjusted(6, 0, -6, 0),
                         int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), text)
        painter.restore()

    def createEditor(self, parent, option, index):  # noqa: N802 - Qt naming
        editor = super().createEditor(parent, option, index)
        placeholder = self._placeholder(index)
        if placeholder and isinstance(editor, QLineEdit):
            editor.setPlaceholderText(placeholder)
        return editor


class GeneraHeaderTable(HeaderTable):
    """[Nome | Valore | Problema] with "automatico" and duplicate-safe loading."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._value_delegate = _AutomaticValueDelegate(self)
        self.setItemDelegateForColumn(self.COL_VALUE, self._value_delegate)
        self.setMinimumHeight(0)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerItem)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        # a rename in the name column changes how the value cell reads
        self.itemChanged.connect(lambda _item: self.viewport().update())
        model = self.model()
        model.rowsInserted.connect(lambda *_a: self.fit_height())
        model.rowsRemoved.connect(lambda *_a: self.fit_height())
        self.fit_height()

    def set_pairs(self, rows: Sequence[tuple[str, str]]) -> None:
        """Replace the rows, in order (a load: ``changed`` is not emitted).
        Unlike ``set_rows`` a list keeps two spellings of one name."""
        with QSignalBlocker(self):
            self.setRowCount(0)
        for name, value in rows:
            self._new_row([QTableWidgetItem(name), QTableWidgetItem(value)])
        self.show_problems({})

    # -- whole rows (module docstring) ----------------------------------------------------

    def fit_height(self) -> None:
        """As tall as the first :data:`MAX_ROWS` rows (at least :data:`MIN_ROWS`):
        never a row cut in half, never empty space under the last one."""
        heights = [self.rowHeight(r) for r in range(min(self.rowCount(), MAX_ROWS))]
        default = self.verticalHeader().defaultSectionSize()
        heights += [default] * max(MIN_ROWS - len(heights), 0)
        # isHidden, not isVisible: the table is fitted while its panel is still closed
        header = 0 if self.horizontalHeader().isHidden() else self.horizontalHeader().sizeHint().height()
        height = sum(heights) + header + 2 * self.frameWidth()
        if self.height() != height or self.minimumHeight() != height:
            self.setFixedHeight(height)

    def show_problems(self, by_row) -> None:
        super().show_problems(by_row)  # resizes the rows to their (wrapped) problems
        self.fit_height()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self.fit_height()

    def add_and_edit(self) -> int:
        """"Aggiungi": a new row, on screen, its name cell open for typing."""
        row = self.add_row()
        self.fit_height()
        item = self.item(row, self.COL_NAME)
        self.scrollToItem(item, QAbstractItemView.ScrollHint.PositionAtBottom)
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        self.setCurrentCell(row, self.COL_NAME)
        self.editItem(item)
        return row

    def commit_editing(self) -> bool:
        """The cell open in edit mode, if any, into the table now (``changed``
        follows, as for any edit), and closed: a run built right after sends
        what the cell shows (Ctrl+Invio from inside it, Riprova, Ricerca's
        calls) — the editor would commit only once it lost the focus."""
        if self.state() != QAbstractItemView.State.EditingState:
            return False
        editor = self.indexWidget(self.currentIndex())
        if editor is None:
            return False
        self.commitData(editor)
        self.closeEditor(editor, QAbstractItemDelegate.EndEditHint.NoHint)
        return True

    def shown_value(self, row: int) -> str:
        """What the value cell reads: the value, or "automatico"."""
        value = self.text(row, self.COL_VALUE)
        if not value.strip() and is_automatic(self.text(row, self.COL_NAME)):
            return strings.GENERA_HEADER_AUTOMATIC
        return value
