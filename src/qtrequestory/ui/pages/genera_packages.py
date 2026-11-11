"""The packages of the Elenco: tall rows with a check box and the key count.

One row per package of the Quadient list: the box, the package name and, at
the right, how many template keys it holds ("7 key", muted). A ticked row is
tinted with the selection colour, so what will be generated reads at a glance
in a long list.

**A click anywhere on the row ticks it** (not only on the 14 px box), Space
ticks the current row, and a double click ticks it once (its second release
is not a second click; the next press forgets that, so a second release that
slipped off the rows never swallows the next click). The box itself is styled by the theme for every item
view (``QListView::indicator`` in ``theme_qss``): unticked it has the muted
border, which Fusion alone drew in the invisible border colour on the dark
surface.

The list only shows and forwards: :attr:`PackageList.toggled` carries
``(package, ticked)``; :meth:`set_checked` puts the presenter's ticks back
without echoing them.
"""
from __future__ import annotations

from collections.abc import Collection, Sequence

from PySide6.QtCore import QEvent, QSignalBlocker, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QListWidget,
    QListWidgetItem,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
)

from qtrequestory.ui import strings, theme

__all__ = ["COUNT_ROLE", "PACKAGE_ROLE", "ROW_HEIGHT", "PackageList"]

PACKAGE_ROLE = Qt.ItemDataRole.UserRole
COUNT_ROLE = Qt.ItemDataRole.UserRole + 1
#: A row: room for the eye and the pointer (the old list packed 19 px rows).
ROW_HEIGHT = 30
#: Inner gap between the name and the count, and after the count.
_GAP = 12


class _PackageDelegate(QStyledItemDelegate):
    """Paints name + count; makes the whole row the click target."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._skip_release = False

    def sizeHint(self, option, index) -> QSize:  # noqa: N802 - Qt naming
        hint = super().sizeHint(option, index)
        return QSize(hint.width(), max(hint.height(), ROW_HEIGHT))

    def paint(self, painter, option, index) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        tokens = theme.tokens()
        ticked = index.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
        if ticked:
            painter.fillRect(opt.rect, QColor(tokens.selection))
        name, opt.text = opt.text, ""
        widget = opt.widget
        style = widget.style() if widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)
        text_rect = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, opt, widget)
        count = strings.GENERA_ELENCO_ROW_KEYS.format(n=index.data(COUNT_ROLE) or 0)
        metrics = QFontMetrics(opt.font)
        count_width = metrics.horizontalAdvance(count)
        right = opt.rect.right() - _GAP
        name_width = max(right - count_width - _GAP - text_rect.left(), 0)
        middle = int(Qt.AlignmentFlag.AlignVCenter)
        painter.save()
        painter.setFont(opt.font)
        painter.setPen(QColor(tokens.selection_text if ticked else tokens.text))
        painter.drawText(text_rect.left(), opt.rect.top(), name_width, opt.rect.height(),
                         middle | int(Qt.AlignmentFlag.AlignLeft),
                         metrics.elidedText(name, Qt.TextElideMode.ElideMiddle, name_width))
        painter.setPen(QColor(tokens.selection_text if ticked else tokens.muted))
        painter.drawText(right - count_width, opt.rect.top(), count_width, opt.rect.height(),
                         middle | int(Qt.AlignmentFlag.AlignRight), count)
        painter.restore()

    def editorEvent(self, event, model, option, index) -> bool:  # noqa: N802 - Qt naming
        flags = index.flags()
        if not (flags & Qt.ItemFlag.ItemIsUserCheckable and flags & Qt.ItemFlag.ItemIsEnabled):
            return super().editorEvent(event, model, option, index)
        kind = event.type()
        if kind == QEvent.Type.MouseButtonPress:
            # a new click: a double click whose second release landed off the rows
            # (never seen here) must not swallow this one's release
            self._skip_release = False
        if kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick,
                    QEvent.Type.MouseButtonRelease):
            if event.button() != Qt.MouseButton.LeftButton or not option.rect.contains(
                    event.position().toPoint()):
                return False
            if kind == QEvent.Type.MouseButtonDblClick:
                self._skip_release = True  # the double click's second release: one tick, not two
                return True
            if kind == QEvent.Type.MouseButtonPress:
                return True
            if self._skip_release:
                self._skip_release = False
                return True
            ticked = index.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
            state = Qt.CheckState.Unchecked if ticked else Qt.CheckState.Checked
            return model.setData(index, state.value, Qt.ItemDataRole.CheckStateRole)
        return super().editorEvent(event, model, option, index)  # Space: the base ticks


class PackageList(QListWidget):
    """The list of packages (module docstring)."""

    #: ``(package, ticked)`` after a user tick; never after :meth:`set_checked`.
    toggled = Signal(str, bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("generaPackages")
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setUniformItemSizes(True)
        self.setMouseTracking(True)  # the hover tint
        self._delegate = _PackageDelegate(self)
        self.setItemDelegate(self._delegate)
        self.setToolTip(strings.GENERA_ELENCO_ROW_TIP)
        self.itemChanged.connect(self._on_item_changed)

    def fill(self, packages: Sequence[tuple[str, int]]) -> None:
        """Replace the rows (unticked, as the presenter starts a list)."""
        with QSignalBlocker(self):
            self.clear()
            for package, n in packages:
                item = QListWidgetItem(package)
                item.setData(PACKAGE_ROLE, package)
                item.setData(COUNT_ROLE, n)
                item.setData(Qt.ItemDataRole.AccessibleTextRole,
                             strings.GENERA_ELENCO_ROW.format(package=package, n=n))
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Unchecked)
                self.addItem(item)
        if self.count():
            self.setCurrentRow(0)

    def set_checked(self, checked: Collection[str]) -> None:
        """The ticks as the presenter has them, silently."""
        with QSignalBlocker(self):
            for item in self._items():
                state = Qt.CheckState.Checked if item.data(PACKAGE_ROLE) in checked else Qt.CheckState.Unchecked
                if item.checkState() != state:
                    item.setCheckState(state)
        self.viewport().update()

    def apply_filter(self, text: str) -> None:
        wanted = text.strip().casefold()
        for item in self._items():
            item.setHidden(bool(wanted) and wanted not in str(item.data(PACKAGE_ROLE)).casefold())

    def shown(self) -> list[str]:
        """The packages the filter lets through, in order."""
        return [str(item.data(PACKAGE_ROLE)) for item in self._items() if not item.isHidden()]

    def texts(self) -> list[str]:
        """Every row as a screen reader reads it: "111_LUCE_FIX  (7)"."""
        return [str(item.data(Qt.ItemDataRole.AccessibleTextRole)) for item in self._items()]

    def _items(self) -> list[QListWidgetItem]:
        return [self.item(i) for i in range(self.count())]

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        self.toggled.emit(str(item.data(PACKAGE_ROLE)), item.checkState() == Qt.CheckState.Checked)
