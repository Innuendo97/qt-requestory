"""Small widgets the Officina's screens share: pills, table cells and a
label that elides in the middle."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from qtrequestory.ui import theme

__all__ = ["MiddleElidedLabel", "cell", "pill"]


def pill(text: str, tone: str = "neutral", tooltip: str = "") -> QLabel:
    """A rounded status label (the ``pill`` QSS property)."""
    label = QLabel(text)
    label.setProperty("pill", tone)
    label.setToolTip(tooltip)
    theme.repolish(label)
    return label


class MiddleElidedLabel(QLabel):
    """A label that asks for its whole text and, when it gets less room,
    cuts the MIDDLE ("MOD_TEST_RICH…STA_B"), never the end: two keys that
    differ only in their last letters must never read the same."""

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        self.ensurePolished()
        hint = super().sizeHint()
        margins = self.contentsMargins()
        width = (self.fontMetrics().horizontalAdvance(self.text())
                 + margins.left() + margins.right() + 2)
        return QSize(max(hint.width(), width), hint.height())

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        hint = super().minimumSizeHint()
        return QSize(self.fontMetrics().horizontalAdvance("M…M"), hint.height())

    def is_elided(self) -> bool:
        return self.fontMetrics().horizontalAdvance(self.text()) > self.contentsRect().width()

    def paintEvent(self, event) -> None:  # noqa: D102, N802 - Qt naming
        if not self.is_elided():
            super().paintEvent(event)
            return
        painter = QPainter(self)
        rect = self.contentsRect()
        text = self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideMiddle,
                                             rect.width())
        self.style().drawItemText(painter, rect, int(self.alignment()), self.palette(),
                                  self.isEnabled(), text, self.foregroundRole())


def cell(*widgets: QWidget, vertical: bool = False) -> QWidget:
    holder = QWidget()
    layout = QVBoxLayout(holder) if vertical else QHBoxLayout(holder)
    layout.setContentsMargins(theme.SPACE[1], 2, theme.SPACE[1], 2)
    layout.setSpacing(0 if vertical else theme.SPACE[0])
    if vertical:
        layout.addStretch(1)
    for widget in widgets:
        layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)
    layout.addStretch(1)
    return holder
