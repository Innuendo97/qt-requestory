"""The collapsible registro at the bottom of the Sincronizzazione page.

Collapsed by default: the page is about the state of the archive, and a wall
of log lines used to dominate it. The header says what the reader would open
it for — "Registro dell'ultima esecuzione · 11:24 · completata" — and the page
opens it by itself when a run ends badly, which is exactly when the lines are
worth reading.

The lines are ``sync.log``'s, in ``theme.mono_font()``: prefilled from the tail
of the file, then appended by the page from the core's own ``LoggingSink``
wording (``sync_format.log_line``), so the two never differ.
"""
from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPlainTextEdit, QSizePolicy, QToolButton, QVBoxLayout, QWidget

from qtrequestory.ui import theme
from qtrequestory.ui.pages.sync_format import log_header

__all__ = ["LOG_HEIGHT", "LOG_MAX_BLOCKS", "SyncLogPanel"]

#: Blocks the registro keeps (DESIGN-ui: "max 2000 righe").
LOG_MAX_BLOCKS = 2000
#: Height of the open registro: enough for a run, never the whole page.
LOG_HEIGHT = 200


class SyncLogPanel(QWidget):
    """A disclosure button over a read-only, monospaced ``QPlainTextEdit``."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE[0])

        self.toggle = QToolButton()
        self.toggle.setCheckable(True)
        self.toggle.setChecked(False)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.toggle.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        theme.set_role(self.toggle, "syncDisclosure")
        self.toggle.toggled.connect(self._on_toggled)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(LOG_MAX_BLOCKS)
        self.log_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.log_view.setFont(theme.mono_font())
        self.log_view.setFixedHeight(LOG_HEIGHT)
        self.log_view.hide()

        layout.addWidget(self.toggle)
        layout.addWidget(self.log_view)
        self.set_header(None, None)

    def set_header(self, when: str | None, outcome: str | None) -> None:
        self.toggle.setText(log_header(when, outcome))

    def header(self) -> str:
        return self.toggle.text()

    def is_expanded(self) -> bool:
        return self.toggle.isChecked()

    def expand(self, expanded: bool = True) -> None:
        self.toggle.setChecked(expanded)

    def set_lines(self, lines: Sequence[str]) -> None:
        self.log_view.setPlainText("\n".join(lines))

    def append(self, line: str) -> None:
        self.log_view.appendPlainText(line)

    def clear(self) -> None:
        self.log_view.clear()

    def text(self) -> str:
        return self.log_view.toPlainText()

    def _on_toggled(self, expanded: bool) -> None:
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.log_view.setVisible(expanded)
        if expanded:
            bar = self.log_view.verticalScrollBar()
            bar.setValue(bar.maximum())
