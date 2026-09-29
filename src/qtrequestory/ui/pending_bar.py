"""The bar of the pending deletions, at the bottom of the window (D6).

Shows :class:`~qtrequestory.ui.pending_delete.PendingDeletions` (see that
module for the behaviour and how to reuse it):

* one deletion: its own sentence, the seconds left, **Annulla**, and a thin
  line running out in the ``danger`` colour;
* two or more: "N elementi eliminati", the seconds until the next one is
  carried out, **Annulla tutto**, and "Mostra quali" opening the list —
  one row per deletion with its own seconds and its own **Annulla**.

It floats over the bottom-left corner of its parent (the window's central
widget; the ordinary ``Toast`` keeps the bottom-right one), is hidden while
nothing is pending, and never takes the focus when it appears. Its buttons
are in the Tab order, and Ctrl+Z inside it undoes the latest deletion.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QEvent, QObject, QRectF, Qt
from PySide6.QtGui import QColor, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import icons, strings, theme
from qtrequestory.ui.pending_delete import PendingDeletion, PendingDeletions

__all__ = ["MARGIN", "MAX_WIDTH", "CountdownLine", "PendingBar"]

#: Distance from the parent's left and bottom edges (the toast's right one).
MARGIN = 16
MIN_WIDTH = 380
MAX_WIDTH = 520
#: Rows shown before the expanded list scrolls.
VISIBLE_ROWS = 5
ICON_PX = 18


def _seconds(ms: int) -> str:
    return strings.ELIMINA_SECONDS.format(seconds=math.ceil(ms / 1000))


class CountdownLine(QWidget):
    """A 3 px line: what is left of the window, in ``danger`` over ``border``."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.fraction = 1.0
        self.setFixedHeight(3)

    def set_fraction(self, value: float) -> None:
        self.fraction = max(0.0, min(1.0, value))
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt naming
        t = theme.tokens()
        painter = QPainter(self)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.fillRect(self.rect(), QColor(t.border))
        painter.fillRect(QRectF(0, 0, self.width() * self.fraction, self.height()), QColor(t.danger))


class _Row(QWidget):
    """One deletion of the expanded list."""

    def __init__(self, item: PendingDeletion, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.item = item
        self.label = QLabel(item.name)
        self.countdown = QLabel()
        self.countdown.setObjectName("pendingCountdown")
        self.undo_button = QPushButton(strings.ELIMINA_UNDO)
        self.undo_button.setObjectName("pendingUndo")
        self.undo_button.setAccessibleName(strings.ELIMINA_UNDO_ONE_A11Y.format(name=item.name))
        self.undo_button.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(ICON_PX + theme.SPACE[1], 0, 0, 0)
        layout.setSpacing(theme.SPACE[1])
        layout.addWidget(self.label, 1)
        layout.addWidget(self.countdown)
        layout.addWidget(self.undo_button)


class PendingBar(QFrame):
    """The deletions in their undo window, over the bottom-left of ``parent``."""

    def __init__(self, queue: PendingDeletions, parent: QWidget) -> None:
        super().__init__(parent)
        self.queue = queue
        self.setObjectName("pendingBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAccessibleName(strings.ELIMINA_BAR_A11Y)
        self._expanded = False

        self.mark = QLabel()
        self.mark.setFixedWidth(ICON_PX)
        self.summary = QLabel()
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.countdown = QLabel()
        self.countdown.setObjectName("pendingCountdown")
        self.countdown.setToolTip(strings.ELIMINA_COUNTDOWN_TIP)
        self.undo_button = QPushButton(strings.ELIMINA_UNDO)
        self.undo_button.setObjectName("pendingUndo")
        self.undo_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle = QToolButton()
        self.toggle.setObjectName("pendingToggle")
        self.toggle.setCheckable(True)
        self.toggle.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.line = CountdownLine()

        head = QHBoxLayout()
        head.setSpacing(theme.SPACE[1])
        head.addWidget(self.mark)
        head.addWidget(self.summary, 1)
        head.addWidget(self.countdown)
        head.addWidget(self.undo_button)
        head.addWidget(self.toggle)

        self._rows_host = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_host)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(2)
        self.list_box = QScrollArea()
        self.list_box.setObjectName("pendingList")
        self.list_box.setWidgetResizable(True)
        self.list_box.setFrameShape(QFrame.Shape.NoFrame)
        self.list_box.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SPACE[2], theme.SPACE[1] + 2, theme.SPACE[2], theme.SPACE[1] + 2)
        layout.setSpacing(theme.SPACE[1])
        layout.addLayout(head)
        layout.addWidget(self.list_box)
        layout.addWidget(self.line)
        self.list_box.setWidget(self._rows_host)
        self.list_box.setVisible(False)
        self._rows: list[_Row] = []

        self.undo_shortcut = QShortcut(QKeySequence(QKeySequence.StandardKey.Undo), self)
        self.undo_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.undo_shortcut.activated.connect(queue.undo_last)
        self.undo_button.clicked.connect(self._undo_head)
        self.toggle.toggled.connect(self.set_expanded)
        queue.changed.connect(self._rebuild)
        queue.ticked.connect(self._tick)
        parent.installEventFilter(self)
        self.hide()
        self._rebuild()

    # -- API ---------------------------------------------------------------------

    def rows(self) -> list[_Row]:
        return list(self._rows)

    def is_expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = bool(expanded)
        if self.toggle.isChecked() != self._expanded:
            self.toggle.setChecked(self._expanded)
        self._sync_toggle()
        self.list_box.setVisible(self._expanded and len(self.queue) > 1)
        self._place()

    # -- internals -------------------------------------------------------------------

    def _undo_head(self) -> None:
        if len(self.queue) > 1:
            self.queue.undo_all()
        else:
            self.queue.undo_last()

    def _sync_toggle(self) -> None:
        self.toggle.setText(f"{strings.ELIMINA_LIST} {'▴' if self._expanded else '▾'}")
        tip = strings.ELIMINA_HIDE_LIST if self._expanded else strings.ELIMINA_SHOW_LIST
        self.toggle.setToolTip(tip)
        self.toggle.setAccessibleName(tip)

    def _rebuild(self) -> None:
        items = self.queue.items()
        focused = next((i for i, r in enumerate(self._rows) if r.undo_button.hasFocus()), None)
        for row in self._rows:
            row.setParent(None)
            row.deleteLater()
        self._rows = []
        if not items:
            self._expanded = False
            self.toggle.setChecked(False)
            self.hide()
            return
        many = len(items) > 1
        self.summary.setText(strings.ELIMINA_MANY.format(count=len(items)) if many else items[0].text)
        self.undo_button.setText(strings.ELIMINA_UNDO_ALL if many else strings.ELIMINA_UNDO)
        self.undo_button.setToolTip(strings.ELIMINA_UNDO_ALL_TIP if many else strings.ELIMINA_UNDO_TIP)
        self.undo_button.setAccessibleName(self.undo_button.text())
        self.mark.setPixmap(icons.icon("delete", theme.tokens().danger).pixmap(ICON_PX, ICON_PX))
        self.toggle.setVisible(many)
        if many:
            for item in items:
                row = _Row(item, self._rows_host)
                row.undo_button.clicked.connect(lambda _checked=False, i=item: self.queue.undo(i))
                self._rows_layout.addWidget(row)
                self._rows.append(row)
            row_height = self._rows[0].sizeHint().height() + self._rows_layout.spacing()
            self.list_box.setFixedHeight(min(len(items), VISIBLE_ROWS) * row_height)
        else:
            self._expanded = False
            self.toggle.setChecked(False)
        self._sync_toggle()
        self.list_box.setVisible(self._expanded and many)
        if focused is not None:  # the keyboard goes on from the row that took its place
            (self._rows[min(focused, len(self._rows) - 1)].undo_button if self._rows
             else self.undo_button).setFocus()
        self._tick()
        if self.isHidden():
            self.show()  # never activates nor takes the focus: it is a child widget
        self.raise_()
        self._place()

    def _tick(self) -> None:
        items = self.queue.items()
        if not items:
            return
        soonest = min(items, key=lambda i: i.deadline)
        self.countdown.setText(_seconds(self.queue.remaining_ms(soonest)))
        self.line.set_fraction(self.queue.fraction(soonest))
        for row in self._rows:
            row.countdown.setText(_seconds(self.queue.remaining_ms(row.item)))

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt naming
        if watched is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self._place()
        return False

    def _place(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        width = max(0, min(MAX_WIDTH, max(MIN_WIDTH, self.sizeHint().width()), parent.width() - 2 * MARGIN))
        self.setFixedWidth(width)
        self.adjustSize()
        self.move(MARGIN, parent.height() - self.height() - MARGIN)
