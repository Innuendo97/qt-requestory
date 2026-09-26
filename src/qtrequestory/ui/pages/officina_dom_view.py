"""The DOM half of the case view (a mixin of ``CaseView``, spec §6): the
"Documenti | DOM" switch, the tab in the splitter in place of the two
viewers, its sources fetched once per (target, version) as they are on
disk — "Target…" replaces the target under the same case, maybe with the
same name — and the selection shared with the list. Split from
``officina_dom`` (size).
"""
from __future__ import annotations

from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QPushButton, QWidget

from qtrequestory.ui import strings, theme
from qtrequestory.ui.pages.officina_dom import DomTab

__all__ = ["DomViewMixin"]


def _identity(version) -> tuple | None:
    """A version's file as it is now: path, creation, size and modification time."""
    if version is None:
        return None
    try:
        stat = version.path.stat()
        on_disk = (stat.st_size, stat.st_mtime_ns)
    except OSError:
        on_disk = None
    return (str(version.path), version.created, on_disk)


class DomViewMixin:
    """The DOM half of ``CaseView``: the "Documenti | DOM" switch (only for
    an HTML target and an HTML version), the tab in the splitter in place of
    the two viewers, and the selection shared with the list. Needs
    ``splitter`` (TARGET, generated, [DOM], list), ``left``/``right``,
    ``diffs``, ``docs``, ``case``, ``dom_requested`` and
    ``_on_difference_clicked``."""

    def _init_dom_widgets(self) -> None:
        self.dom = DomTab()
        self.dom.setVisible(False)
        self.view_switch = QWidget()
        row = QHBoxLayout(self.view_switch)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self.docs_button = QPushButton(strings.DOM_VIEW_DOCS)
        self.dom_button = QPushButton(strings.DOM_VIEW_DOM)
        self.dom_button.setToolTip(strings.DOM_VIEW_TIP)
        group = QButtonGroup(self.view_switch)
        for button in (self.docs_button, self.dom_button):
            button.setCheckable(True)
            group.addButton(button)
            row.addWidget(button)
        theme.set_segmented([self.docs_button, self.dom_button])
        self.docs_button.setChecked(True)
        self.view_switch.setVisible(False)

    def _connect_dom(self) -> None:
        self.docs_button.clicked.connect(lambda: self.set_dom_mode(False))
        self.dom_button.clicked.connect(lambda: self.set_dom_mode(True))
        self.diffs.difference_chosen.connect(self.dom.select)
        self.dom.difference_chosen.connect(self._on_difference_clicked)
        self.dom.difference_chosen.connect(self._acted)  # R28, like a click in the list

    def dom_mode(self) -> bool:
        return self.dom.isVisibleTo(self)

    def dom_available(self) -> bool:
        docs = self.docs
        left = docs.left.version if docs is not None else None
        right = docs.right.version if docs is not None else None
        return left is not None and right is not None and left.doc_type == right.doc_type == "html"

    def set_dom_mode(self, on: bool) -> None:
        """The DOM tab in place of the two viewers (or back)."""
        on = on and self.dom_available()
        (self.dom_button if on else self.docs_button).setChecked(True)
        if on == self.dom_mode():
            return
        sizes = self.splitter.sizes()
        docs_w = sum(sizes[:3])
        self.left.setVisible(not on)
        self.right.setVisible(not on)
        self.dom.setVisible(on)
        if docs_w > 0:
            half = docs_w // 2
            self.splitter.setSizes([0, 0, docs_w, sizes[3]] if on else [half, docs_w - half, 0, sizes[3]])
        if on:
            self._request_dom()
            self.dom.select(self.diffs.current_id())

    def _dom_key(self) -> tuple | None:
        docs = self.docs
        if docs is None or docs.right.version is None or self.case is None:
            return None
        v, t = docs.right.version, docs.left.version
        # the TARGET too: "Target…" replaces it under the same case (maybe the same name)
        return (self.case.id, _identity(t), v.kind, v.number, _identity(v))

    def _request_dom(self) -> None:
        key = self._dom_key()
        if key is None or key == self.dom.key:
            return
        self.dom.forget()
        self.dom_requested.emit(key, self.case, self.docs.right.version)

    def _dom_follow(self) -> None:
        """After new documents: the switch only for HTML; the tab's sources
        follow. Without the Edge print (R45) the DOM tab is the main view."""
        available = self.dom_available()
        self.view_switch.setVisible(available)
        docs = self.docs
        if not available:
            self.set_dom_mode(False)
        elif docs is not None and (docs.left.no_print or docs.right.no_print):
            self.set_dom_mode(True)
            self._request_dom()
        elif self.dom_mode():
            self._request_dom()

    def show_dom(self, key: object, target: str, generated: str) -> None:
        if key == self._dom_key():
            self.dom.show_sources(key, target, generated)
            self.dom.select(self.diffs.current_id())

    def dom_failed(self, key: object, text: str) -> None:
        if key == self._dom_key():
            self.dom.show_message(text)
