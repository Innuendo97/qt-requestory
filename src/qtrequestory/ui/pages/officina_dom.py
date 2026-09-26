"""The "DOM" tab of an HTML case (spec §6): blocks and both sources.

    +- Blocchi del target -+- Sorgente del target -+- Sorgente generato -+
    | ▲ p[1] Per i dett…   |   <p>                 |   <p>               |
    |   table[1]           |     Per i dettagli    |     Per i dettagli  |
    |     tr[1]            |     <a href="…">      |     <a href="…">    |
    +----------------------+-----------------------+---------------------+

The tree lists the TARGET's block elements (``officina_dom_map.parse``), each
marked with the worst verdict of the differences inside it (the glyph and
the edge colour of ``officina_verdict_style.look_for``). The two
``QPlainTextEdit`` show the pretty sources, read-only, every located
difference's line tinted by its verdict (``ExtraSelection``) and the selected
one stronger; they scroll together.

Selection is shared with the list: :meth:`DomTab.select` (from the list, the
viewers, the strip) moves both sources to that difference's lines and the
tree to its block, without emitting; a click on a tinted line, or on a block
holding differences, emits :attr:`DomTab.difference_chosen`.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QTextCursor, QTextFormat
from PySide6.QtWidgets import (
    QLabel,
    QPlainTextEdit,
    QSplitter,
    QStackedLayout,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import Judged
from qtrequestory.ui.pages.officina_dom_map import Node, Source, locate, node_at, parse
from qtrequestory.ui.pages.officina_verdict_style import LOOKS, WORST_ORDER, look_for, state_of

__all__ = ["DomTab"]

#: Worst first: the marker a block shows when it holds several differences
#: (the board's order, then the states that do not count; "fatta" last: it is done).
_RANK = (*(s for s in WORST_ORDER if s != "fatta"), "nessuno", "tollerata", "variabile", "rumore", "fatta")


def _rank(state: str) -> int:
    """Position in :data:`_RANK`; a state it does not know yet sorts last."""
    return _RANK.index(state) if state in _RANK else len(_RANK)
_NODE = Qt.ItemDataRole.UserRole
#: Alpha of a tinted line (0-255): readable text in both themes.
_TINT = 90
#: Alpha of the selected difference's line: the accent, clearly stronger than a tint.
_CHOSEN = 110


def _editor() -> QPlainTextEdit:
    edit = QPlainTextEdit()
    edit.setReadOnly(True)
    edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
    edit.setFont(theme.mono_font())
    edit.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse
                                 | Qt.TextInteractionFlag.TextSelectableByKeyboard)
    return edit


def _column(title: str, widget: QWidget) -> QWidget:
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(theme.SPACE[0])
    label = QLabel(title)
    theme.set_role(label, "muted")
    layout.addWidget(label)
    layout.addWidget(widget, 1)
    return box


class DomTab(QWidget):
    """Tree of the target's blocks + the two sources, sharing the selection."""

    difference_chosen = Signal(int)   # Diff.id

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        #: What the sources on screen belong to (the case view's key), or None.
        self.key: object = None
        self._left = parse("")
        self._right = parse("")
        self._judged: list[Judged] = []
        self._lines: dict[int, tuple[int | None, int | None]] = {}
        self._current: int | None = None
        self._moving = False
        self._items: dict[int, QTreeWidgetItem] = {}
        self._labels: dict[int, str] = {}

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setUniformRowHeights(True)
        self.left = _editor()
        self.right = _editor()
        self.message = QLabel()
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message.setWordWrap(True)
        theme.set_role(self.message, "muted")
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(_column(strings.DOM_TREE, self.tree))
        self.splitter.addWidget(_column(strings.DOM_TARGET, self.left))
        self.splitter.addWidget(_column(strings.DOM_GENERATED, self.right))
        for index, share in enumerate((2, 3, 3)):
            self.splitter.setStretchFactor(index, share)
        self.stack = QStackedLayout(self)
        self.stack.addWidget(self.splitter)
        self.stack.addWidget(self.message)
        self.show_message(strings.DOM_LOADING)

        self.tree.itemClicked.connect(self._on_tree_clicked)
        self.left.cursorPositionChanged.connect(lambda: self._on_cursor("left"))
        self.right.cursorPositionChanged.connect(lambda: self._on_cursor("right"))
        self.left.verticalScrollBar().valueChanged.connect(lambda v: self._follow(self.left, self.right))
        self.right.verticalScrollBar().valueChanged.connect(lambda v: self._follow(self.right, self.left))
        theme.signals.changed.connect(self._relocate)  # the markers and tints use the tokens

    # -- content -------------------------------------------------------------------

    def show_message(self, text: str) -> None:
        self.message.setText(text)
        self.stack.setCurrentWidget(self.message)

    def forget(self) -> None:
        """The sources on screen no longer belong to what the case view shows."""
        self.key = None
        self.show_message(strings.DOM_LOADING)

    def show_sources(self, key: object, target: str, generated: str) -> None:
        """The two pretty sources of ``key`` (from ``dom_view``)."""
        self.key = key
        if not (target or generated):
            self.show_message(strings.DOM_EMPTY)
            return
        self._left, self._right = parse(target), parse(generated)
        self._moving = True
        self.left.setPlainText(target)
        self.right.setPlainText(generated)
        self._moving = False
        self.stack.setCurrentWidget(self.splitter)
        self._build_tree()
        self._relocate()

    def set_judged(self, judged: list[Judged]) -> None:
        """The differences on screen (the same list the viewers draw)."""
        self._judged = list(judged)
        self._relocate()

    def select(self, diff_id: int | None) -> None:
        """Both sources on ``diff_id``'s lines, the tree on its block; silent."""
        self._current = diff_id
        self._repaint()
        left, right = self._lines.get(diff_id, (None, None)) if diff_id is not None else (None, None)
        self._moving = True
        try:
            for edit, line in ((self.left, left), (self.right, right)):
                if line is not None:
                    self._goto(edit, line)
            node = node_at(self._left, left) if left is not None else None
            item = self._items.get(id(node)) if node is not None else None
            self.tree.setCurrentItem(item) if item is not None else self.tree.clearSelection()
        finally:
            self._moving = False

    def current_line(self, side: str) -> int:
        edit = self.left if side == "left" else self.right
        return edit.textCursor().blockNumber()

    def line_of(self, diff_id: int) -> tuple[int | None, int | None]:
        return self._lines.get(diff_id, (None, None))

    def item_of_line(self, line: int) -> QTreeWidgetItem | None:
        node = node_at(self._left, line)
        return self._items.get(id(node)) if node is not None else None

    # -- internals ------------------------------------------------------------------

    def _relocate(self) -> None:
        self._lines = locate([j.diff for j in self._judged], self._left, self._right)
        self._mark_tree()
        self.select(self._current if self._current in self._lines else None)

    def _states(self, src: Source, side: int) -> dict[int, str]:
        """``{node id: worst state}`` of the differences located inside each block."""
        worst: dict[int, str] = {}
        for j in self._judged:
            line = self._lines.get(j.diff.id, (None, None))[side]
            node = node_at(src, line) if line is not None else None
            if node is None:
                continue
            state = state_of(j)
            now = worst.get(id(node))
            if now is None or _rank(state) < _rank(now):
                worst[id(node)] = state
        return worst

    def _build_tree(self) -> None:
        """The target's blocks, once per source (a redraw only re-marks them,
        so the user's collapsed branches and the scroll stay)."""
        self.tree.clear()
        self._items = {}
        self._labels: dict[int, str] = {}
        body = next((n for n in self._left.nodes if n.tag == "body"), None)
        roots = body.children if body is not None else self._left.roots

        def add(node: Node, parent) -> None:
            label = f"{node.step}  {node.preview()}".rstrip()
            item = QTreeWidgetItem([label])
            item.setData(0, _NODE, node.line)
            item.setToolTip(0, node.path)
            (parent.addChild(item) if parent is not None else self.tree.addTopLevelItem(item))
            self._items[id(node)] = item
            self._labels[id(node)] = label
            for child in node.children:
                add(child, item)

        for node in roots:
            add(node, None)
        self.tree.expandAll()

    def _mark_tree(self) -> None:
        """Each block's glyph and colour: the worst state of the differences inside it."""
        worst = self._states(self._left, 0)
        t = theme.tokens()
        plain = self.tree.palette().text()
        for key, item in self._items.items():
            state = worst.get(key)
            look = LOOKS.get(state) if state else None
            item.setText(0, f"{look.icon} {self._labels[key]}" if look else self._labels[key])
            if look:
                item.setForeground(0, QColor(getattr(t, look.edge)))
            else:
                item.setForeground(0, plain)

    def _repaint(self) -> None:
        t = theme.tokens()
        for side, edit in ((0, self.left), (1, self.right)):
            selections = []
            for j in self._judged:
                line = self._lines.get(j.diff.id, (None, None))[side]
                if line is None:
                    continue
                look = look_for(j)
                chosen = j.diff.id == self._current
                colour = QColor(t.accent if chosen else getattr(t, look.fill or look.edge))
                colour.setAlpha(_CHOSEN if chosen else (_TINT if look.fill is None else 255))
                sel = QTextEdit.ExtraSelection()
                sel.format.setBackground(colour)
                sel.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
                if chosen:
                    sel.format.setFontWeight(700)
                cursor = QTextCursor(edit.document().findBlockByNumber(line))
                cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
                sel.cursor = cursor
                selections.append((chosen, sel))
            selections.sort(key=lambda pair: pair[0])  # the chosen one painted last, on top
            edit.setExtraSelections([s for _c, s in selections])

    @staticmethod
    def _goto(edit: QPlainTextEdit, line: int) -> None:
        block = edit.document().findBlockByNumber(line)
        if not block.isValid():
            return
        edit.setTextCursor(QTextCursor(block))
        edit.centerCursor()

    def _on_cursor(self, side: str) -> None:
        if self._moving:
            return
        line = self.current_line(side)
        index = 0 if side == "left" else 1
        hit = next((j.diff.id for j in self._judged
                    if self._lines.get(j.diff.id, (None, None))[index] == line), None)
        if hit is not None and hit != self._current:
            self.select(hit)
            self.difference_chosen.emit(hit)

    def _on_tree_clicked(self, item: QTreeWidgetItem) -> None:
        line = item.data(0, _NODE)
        node = node_at(self._left, line)
        inside = [j.diff.id for j in self._judged
                  if (at := self._lines.get(j.diff.id, (None, None))[0]) is not None
                  and node_at(self._left, at) is node]
        if inside:
            self.select(inside[0])
            self.difference_chosen.emit(inside[0])
            return
        self._moving = True
        try:
            self._goto(self.left, line)
            twin = next((n for n in self._right.nodes if n.path == node.path), None) if node else None
            if twin is not None:
                self._goto(self.right, twin.line)
        finally:
            self._moving = False

    def _follow(self, source: QPlainTextEdit, other: QPlainTextEdit) -> None:
        """Scroll the other source to the same share of its length."""
        if self._moving:
            return
        bar, twin = source.verticalScrollBar(), other.verticalScrollBar()
        self._moving = True
        try:
            share = bar.value() / bar.maximum() if bar.maximum() else 0.0
            twin.setValue(round(share * twin.maximum()))
        finally:
            self._moving = False
