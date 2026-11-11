"""The Genera tab's setup pane: the steps in the order they are taken.

::

    +-- Cosa generare ------------------+  pinned: the segments never scroll away
    | [Template key | Elenco | FDI]      |
    +-----------------------------------+
    | the current source (takes the     |  scrolls only when it must
    | height that is left)              |  (the headers opened, a short window)
    | ───────────────────────────────── |
    | Dove                              |
    |  Genera su      Chiamate dai log  |
    |  [svil ▾]       [coll ▾]          |
    |  (note when the logs differ)      |
    |  Salva in [path…] [Sfoglia…]      |
    | ───────────────────────────────── |
    | ▸ Header  7 inviati [1 modificato] Ripristina |
    +-----------------------------------+
    | (Header: 1 modificato  Mostra Ripristina)  only while the line above is out of view
    | [ ] Salva anche le email  [ ] zip |  pinned: options, THE button, its problem
    | [      Genera 16 documenti      ] |
    +-----------------------------------+

On a wide window the pane is a column on the left; on a narrow one it is on
top (:meth:`GeneraSetup.set_stacked`, the page decides). Only widgets: the
page wires them to the presenter.
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import QFrame, QScrollArea, QVBoxLayout, QWidget

from qtrequestory.ui import theme
from qtrequestory.ui.pages.genera_actions import GeneraActionBar
from qtrequestory.ui.pages.genera_form import HeadersStep, WhereStep
from qtrequestory.ui.pages.genera_presenter import GeneraPresenter
from qtrequestory.ui.pages.genera_source import GeneraSource

__all__ = ["GeneraSetup"]

#: The pane's side margins, and the air around the rule between two steps.
MARGIN = theme.SPACE[3] + theme.SPACE[0]
STEP_GAP = theme.SPACE[3]


def _rule() -> QFrame:
    rule = QFrame()
    theme.set_role(rule, "hrule")
    return rule


class GeneraSetup(QFrame):
    """The setup pane (module docstring)."""

    def __init__(self, presenter: GeneraPresenter, *, browse_destination: Callable[[], None],
                 follow_generator: Callable[[], None], reset_headers: Callable[[], None],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("generaSetup")
        self.source = GeneraSource(presenter)
        self.where = WhereStep(browse_destination, follow_generator)
        self.headers = HeadersStep(reset_headers)
        self.actions = GeneraActionBar()

        top = QWidget()
        head = QVBoxLayout(top)
        head.setContentsMargins(MARGIN, MARGIN - theme.SPACE[0], MARGIN, theme.SPACE[2])
        head.addWidget(self.source.modes)

        content = QWidget()
        column = QVBoxLayout(content)
        column.setContentsMargins(MARGIN, 0, MARGIN, MARGIN)
        column.setSpacing(0)
        column.addWidget(self.source, 1)
        for step in (self.where, self.headers):
            column.addSpacing(STEP_GAP)
            column.addWidget(_rule())
            column.addSpacing(STEP_GAP)
            column.addWidget(step)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidget(content)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(top)
        layout.addWidget(self.scroll, 1)
        layout.addWidget(self.actions)

        self.actions.headers_show.clicked.connect(lambda _c=False: self.open_headers())
        self.actions.headers_reset.clicked.connect(lambda _c=False: reset_headers())
        bar = self.scroll.verticalScrollBar()
        bar.valueChanged.connect(lambda _v: self._sync_reminder())
        bar.rangeChanged.connect(lambda _lo, _hi: self._sync_reminder())

    # -- the headers' reminder over the button ---------------------------------------------

    def show_headers_state(self, sent: str, modified: str) -> None:
        """The Header step's line, and its reminder in the footer when that
        line is out of view (``genera_actions``)."""
        self.headers.show_state(sent, modified)
        self._sync_reminder()

    def headers_in_view(self) -> bool:
        line = self.headers.toggle
        viewport = self.scroll.viewport()
        top = line.mapTo(viewport, QPoint(0, 0))
        return viewport.rect().contains(QRect(top, line.size()))

    def open_headers(self) -> None:
        """[Mostra]: the table open, scrolled into view."""
        self.headers.toggle.setChecked(True)
        self.scroll.widget().layout().activate()
        self.reveal(self.headers)

    def _sync_reminder(self) -> None:
        modified = self.headers.modified_pill.text() if not self.headers.modified_pill.isHidden() else ""
        self.actions.show_headers_reminder("" if self.headers_in_view() else modified)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._sync_reminder()

    def set_stacked(self, stacked: bool) -> None:
        """On top of the results (narrow window) rather than beside them."""
        if bool(self.property("stacked")) != stacked:
            self.setProperty("stacked", stacked)
            theme.repolish(self)

    def reveal(self, widget: QWidget, rect: QRect | None = None) -> None:
        """Scroll so ``rect`` of ``widget`` (all of it by default) is in view."""
        content = self.scroll.widget()
        area = rect if rect is not None else widget.rect()
        top_left = widget.mapTo(content, area.topLeft())
        centre = QPoint(top_left.x() + area.width() // 2, top_left.y() + area.height() // 2)
        self.scroll.ensureVisible(centre.x(), centre.y(), area.width() // 2 + theme.SPACE[1],
                                  area.height() // 2 + theme.SPACE[2])
