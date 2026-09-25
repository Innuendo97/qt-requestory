"""Pieces of the case workbench: the version switch, one document side, and
the differences list.

* :class:`VersionSwitch` — AS-IS, v1 … vn as a segmented control (the newest
  versions; older ones in a "…" menu), like the approved mockup.
* :class:`DocSide` — a header (slot pill, name, info) over a ``DocView``, or a
  sentence when there is nothing to show (no target yet, a file gone, a
  document still being prepared).
* :class:`DiffPanel` — the count and the list of text differences with their
  kind and "…"-elided text; a ``CompareError`` is shown as a sentence here.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QStackedLayout,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import Case, TextComparison, Version
from qtrequestory.ui.pages.officina_widgets import pill
from qtrequestory.ui.pages.officina_format import difference_lines
from qtrequestory.ui.pages.officina_viewer import DocView

__all__ = ["DiffPanel", "DocSide", "VersionSwitch", "case_versions", "version_key"]

#: How many TO-BE versions get their own segment; older ones go in the menu.
VISIBLE_VERSIONS = 5
#: Height of a side's header row (the version switch is the tallest thing in it).
HEADER_HEIGHT = 36


def version_key(version: Version) -> str:
    """"asis", or "v3" for TO-BE 3."""
    return "asis" if version.kind == "asis" else f"v{version.number}"


def case_versions(case: Case) -> list[Version]:
    """The AS-IS (if any) then the TO-BE versions, ascending."""
    asis = case.asis()
    return ([asis] if asis is not None else []) + case.tobe_versions()


def _label(version: Version) -> str:
    return (strings.OFFICINA_VERSION_ASIS if version.kind == "asis"
            else strings.OFFICINA_VERSION_TOBE.format(n=version.number))


class VersionSwitch(QWidget):
    """AS-IS | v1 | v2 | … — which generated document the right side shows."""

    chosen = Signal(str)  # version_key

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self.buttons: dict[str, QPushButton] = {}
        self.more = QToolButton()
        self.more.setText("…")
        self.more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._older: list[Version] = []

    def set_versions(self, versions: list[Version], current: str | None) -> None:
        """``versions``: the AS-IS (if any) then the TO-BEs, ascending."""
        for button in list(self.buttons.values()):
            self._group.removeButton(button)
            button.deleteLater()
        self.buttons.clear()
        while self._layout.count():
            self._layout.takeAt(0)
        asis = [v for v in versions if v.kind == "asis"]
        tobe = [v for v in versions if v.kind == "tobe"]
        self._older = tobe[:-VISIBLE_VERSIONS] if len(tobe) > VISIBLE_VERSIONS else []
        shown = asis + tobe[-VISIBLE_VERSIONS:]
        if current is not None and current not in {version_key(v) for v in shown}:
            shown = asis + [v for v in tobe if version_key(v) == current] + tobe[-VISIBLE_VERSIONS:]
        for version in shown:
            key = version_key(version)
            button = QPushButton(_label(version))
            button.setCheckable(True)
            if version.missing:
                button.setToolTip(strings.OFFICINA_THUMB_MISSING_TIP)
            button.clicked.connect(lambda _c=False, k=key: self.chosen.emit(k))
            self._group.addButton(button)
            self._layout.addWidget(button)
            self.buttons[key] = button
        if self.buttons:
            theme.set_segmented(list(self.buttons.values()))
        if self._older:
            menu = QMenu(self.more)
            for version in self._older:
                key = version_key(version)
                menu.addAction(_label(version), lambda k=key: self.chosen.emit(k))
            self.more.setMenu(menu)
            self._layout.addSpacing(theme.SPACE[0])
            self._layout.addWidget(self.more)
        self.more.setVisible(bool(self._older))
        if current in self.buttons:
            self.buttons[current].setChecked(True)

    def current(self) -> str | None:
        checked = self._group.checkedButton()
        for key, button in self.buttons.items():
            if button is checked:
                return key
        return None


class DocSide(QWidget):
    """Header + viewer, or a sentence in place of the viewer."""

    def __init__(self, slot: str, doc_id: str, switch: QWidget | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.doc_id = doc_id
        self.slot = pill(slot, "neutral")
        self.name = QLabel()
        self.name.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.info = QLabel()
        theme.set_role(self.info, "muted")
        self.view = DocView()
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        theme.set_role(self.message, "muted")
        head = QWidget()
        head.setFixedHeight(HEADER_HEIGHT)  # both sides alike, switch or not: pages line up
        header = QHBoxLayout(head)
        header.setContentsMargins(0, 0, theme.SPACE[1], 0)
        header.addWidget(self.slot, 0, Qt.AlignmentFlag.AlignVCenter)
        if switch is not None:
            header.addWidget(switch)
        header.addWidget(self.name, 1)
        header.addWidget(self.info)
        self.stack = QStackedLayout()
        self.stack.addWidget(self.view)
        self.stack.addWidget(self.message)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE[0])
        layout.addWidget(head)
        layout.addLayout(self.stack, 1)
        self.show_message(strings.OFFICINA_LOADING)

    def show_message(self, text: str) -> None:
        self.message.setText(text)
        self.stack.setCurrentWidget(self.message)

    def show_document(self, path, sizes) -> None:
        self.view.load(self.doc_id, path, sizes)
        self.view.set_zoom("fit_width")
        self.stack.setCurrentWidget(self.view)

    def showing_document(self) -> bool:
        return self.stack.currentWidget() is self.view

    def message_text(self) -> str:
        return "" if self.showing_document() else self.message.text()


class DiffPanel(QWidget):
    """The differences between the TARGET and the document on the right."""

    difference_chosen = Signal(int)  # Difference.id

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        title = QLabel(strings.OFFICINA_DIFF_TITLE)
        theme.set_role(title, "section")
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.list = QListWidget()
        self.list.setWordWrap(True)
        self.list.setSpacing(3)
        self.list.currentItemChanged.connect(self._on_current)
        self.list.itemActivated.connect(self._on_activated)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SPACE[1], 0, 0, 0)  # air after the version info
        layout.setSpacing(theme.SPACE[1])
        title.setFixedHeight(HEADER_HEIGHT)  # the list starts where the pages start
        layout.addWidget(title)
        layout.addWidget(self.summary)
        layout.addWidget(self.list, 1)
        self.setMinimumWidth(240)

    def show_message(self, text: str, tone: str = "") -> None:
        """A sentence instead of the list (no comparison, or it failed);
        ``tone`` "ok" / "warn" / "bad" colours it, "" leaves it muted."""
        self.list.clear()
        self.list.setVisible(False)
        self._set_summary(text, tone)

    def _set_summary(self, text: str, tone: str) -> None:
        self.summary.setText(text)
        self.summary.setProperty("dot", tone or None)
        self.summary.setProperty("role", None if tone else "muted")
        theme.repolish(self.summary)

    def show_comparison(self, comparison: TextComparison) -> None:
        self.list.clear()
        diffs = comparison.differences
        if comparison.equal:
            self.show_message(strings.OFFICINA_DIFF_EQUAL, "ok")
            return
        if not diffs:
            self.show_message(comparison.note or strings.OFFICINA_DIFF_EQUAL, "warn")
            return
        self._set_summary(strings.OFFICINA_DIFF_COUNT_ONE if len(diffs) == 1
                          else strings.OFFICINA_DIFF_COUNT.format(n=len(diffs)), "warn")
        for diff in diffs:
            where, what = difference_lines(diff)
            item = QListWidgetItem(f"{where}\n{what}")
            item.setData(Qt.ItemDataRole.UserRole, diff.id)
            item.setToolTip(what)
            self.list.addItem(item)
        self.list.setVisible(True)

    def select(self, diff_id: int) -> None:
        for row in range(self.list.count()):
            item = self.list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == diff_id:
                self.list.blockSignals(True)
                self.list.setCurrentItem(item)
                self.list.blockSignals(False)
                self.list.scrollToItem(item)
                return

    def texts(self) -> list[str]:
        return [self.list.item(r).text() for r in range(self.list.count())]

    def _on_current(self, item: QListWidgetItem | None, _previous=None) -> None:
        if item is not None:
            self.difference_chosen.emit(int(item.data(Qt.ItemDataRole.UserRole)))

    def _on_activated(self, item: QListWidgetItem) -> None:
        self._on_current(item)
