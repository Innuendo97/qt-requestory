"""The two document sides of the case workbench (split from ``officina_diffs``).

* :class:`VersionSwitch` — AS-IS, v1 … vn as a segmented control (the newest
  versions; older ones in a "…" menu), like the approved mockup.
* :class:`DocSide` — a header (slot pill, name, info) over a ``DocView``, or a
  sentence when there is nothing to show (no target yet, a file gone, a
  document still being prepared).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QStackedLayout,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import Case, Version
from qtrequestory.ui.pages.officina_viewer import DocView
from qtrequestory.ui.pages.officina_widgets import pill

__all__ = ["HEADER_HEIGHT", "DocSide", "VersionSwitch", "case_versions", "version_key"]

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
