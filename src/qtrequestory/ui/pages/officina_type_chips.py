"""The band of TYPE CHIPS of the side panel (phase 2.5, D8, draft
"f25-caso-v2")::

    (Aa) Parole 2   (▭) Zone 2   (#) Numeri 0   (A/a) Maiusc. 0 …

One :class:`TypeChip` per difference type (D9: every type counts): a
round badge with the type's icon, the short name, the number of rows of that
type in the current verdict tab. To keep the band short (U3 fix round 1)
only the chips with rows — and those that are on — show; the others wait
behind a trailing "+k altri" chip (its accessible name lists them) that
unfolds them inline, dimmed. A click (or Space on the focused chip — every
chip is reachable with Tab) toggles a chip; several can be on together;
none on = every type. :class:`TypeChips` emits :attr:`TypeChips.changed`
with the set that is on. The chips wrap onto as many lines as they need
(:class:`FlowLayout`): never cut.
"""
from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QLayout, QSizePolicy, QToolButton, QWidget, QWidgetItem

from qtrequestory.ui import strings, theme
from qtrequestory.ui.pages.officina_progress import GLYPH_FONT
from qtrequestory.ui.pages.officina_types import TYPE_ORDER, TYPES

__all__ = ["FlowLayout", "TypeChip", "TypeChips"]

#: The chip: height, badge diameter, inner gaps (logical px), text size (pt).
CHIP_H = 20
BADGE = 16
GAP = 3
CHIP_PT = 8.0
#: A chip with nothing in the tab.
ZERO_OPACITY = 0.45


class FlowLayout(QLayout):
    """Children left to right, wrapping to a new line when the width ends."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 3) -> None:
        super().__init__(parent)
        self._items: list = []
        self._gap = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:  # noqa: N802 - Qt naming
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802 - Qt naming
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):  # noqa: N802 - Qt naming
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientation:  # noqa: N802 - Qt naming
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - Qt naming
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - Qt naming
        return self._place(QRect(0, 0, width, 0), move=False)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802 - Qt naming
        super().setGeometry(rect)
        self._place(rect, move=True)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802 - Qt naming
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def _place(self, rect: QRect, *, move: bool) -> int:
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x, y, line = area.x(), area.y(), 0
        for item in self._items:
            if isinstance(item, QWidgetItem) and item.widget().isHidden():
                continue
            hint = item.sizeHint()
            if x > area.x() and x + hint.width() > area.right() + 1:
                x, y, line = area.x(), y + line + self._gap, 0
            if move:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._gap
            line = max(line, hint.height())
        return y + line - rect.y() + margins.bottom()


class TypeChip(QAbstractButton):
    """One type: badge with the icon, short name, number (painted, so the
    badge is a real circle); checkable; dimmed at zero."""

    def __init__(self, tipo: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.tipo = tipo
        self.info = TYPES[tipo]
        self.n = 0
        self.setCheckable(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        font = QFont(self.font())
        font.setPointSizeF(CHIP_PT)
        self.setFont(font)
        self.toggled.connect(lambda _on: self._describe())
        self.set_count(0)

    def set_count(self, n: int) -> None:
        self.n = n
        self.setText(f"{self.info.name} {n}")
        self._describe()
        self.updateGeometry()
        self.update()

    def _describe(self) -> None:
        self.setToolTip(f"{self.info.tip}\n{strings.PANNELLO_CHIP_HINT}")
        self.setAccessibleName(strings.PANNELLO_CHIP_NAME.format(name=self.info.name, n=self.n))
        self.setAccessibleDescription(self.info.tip)

    def _fonts(self) -> tuple[QFont, QFont]:
        text = QFont(self.font())
        glyph = QFont(text)
        glyph.setFamily(GLYPH_FONT)
        glyph.setPointSizeF(max(6.0, text.pointSizeF() * 0.8))
        return text, glyph

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        text, _glyph = self._fonts()
        width = 2 + BADGE + GAP + QFontMetrics(text).horizontalAdvance(self.text()) + 6
        return QSize(width, CHIP_H)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        return self.sizeHint()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt naming
        t = theme.tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.n and not self.isChecked():
            painter.setOpacity(ZERO_OPACITY)
        on = self.isChecked()
        body = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(QColor(t.accent if on or self.hasFocus() else t.border),
                            2.0 if self.hasFocus() else 1.0))
        painter.setBrush(QColor(t.selection if on else (t.surface2 if self.underMouse() else t.surface)))
        painter.drawRoundedRect(body, CHIP_H / 2, CHIP_H / 2)
        badge = QRectF(2, (CHIP_H - BADGE) / 2, BADGE, BADGE)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(t.accent if on else t.neutral_bg))
        painter.drawEllipse(badge)
        text_font, glyph_font = self._fonts()
        painter.setFont(glyph_font)
        painter.setPen(QColor(t.on_accent if on else t.text))
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, self.info.icon)
        painter.setFont(text_font)
        painter.setPen(QColor(t.selection_text if on else t.text))
        area = QRectF(badge.right() + GAP, 0, self.width() - badge.right() - GAP, CHIP_H)
        painter.drawText(area, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())
        painter.end()

    def enterEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().leaveEvent(event)
        self.update()


class TypeChips(QWidget):
    """All the chips, wrapping; ``changed`` carries the types that are on."""

    changed = Signal(frozenset)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("typeChips")
        self.setAccessibleName(strings.PANNELLO_CHIPS_NAME)
        layout = FlowLayout(self)
        layout.setContentsMargins(theme.SPACE[1], theme.SPACE[1], theme.SPACE[1], theme.SPACE[1])
        self.chips: dict[str, TypeChip] = {}
        for tipo in TYPE_ORDER:
            chip = TypeChip(tipo, self)
            chip.toggled.connect(self._on_toggled)
            layout.addWidget(chip)
            self.chips[tipo] = chip
        self.more = QToolButton(self)
        self.more.setCheckable(True)
        self.more.setProperty("chipMore", "true")
        # Pin the height: QToolButton.sizeHint() asks the QStyle
        # (Fusion's sizeFromContents), which is not as stable as the chips'
        # own hand-computed CHIP_H (it has been observed to answer 19-21 px
        # for the same font/text/state depending on unrelated Qt/style state
        # built up earlier in the process) — the row height FlowLayout
        # computes must stay deterministic, on the chips' own row height.
        self.more.setFixedHeight(CHIP_H)
        self.more.toggled.connect(lambda _on: self._show_chips())
        layout.addWidget(self.more)
        self._show_chips()
        policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        theme.signals.changed.connect(self.update)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - Qt naming
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - Qt naming
        return self.layout().heightForWidth(width)

    def set_counts(self, counts: Mapping[str, int]) -> None:
        for tipo, chip in self.chips.items():
            chip.set_count(counts.get(tipo, 0))
        self._show_chips()

    def hidden_types(self) -> list[str]:
        """The types behind "+k altri" (no rows in the tab, not on)."""
        return [t for t, chip in self.chips.items() if not chip.n and not chip.isChecked()]

    def _show_chips(self) -> None:
        hidden = self.hidden_types()
        unfolded = self.more.isChecked()
        for tipo, chip in self.chips.items():
            chip.setHidden(tipo in hidden and not unfolded)
        names = ", ".join(self.chips[t].info.name for t in hidden)
        k = len(hidden)
        more = strings.PANNELLO_CHIPS_MORE_ONE if k == 1 else strings.PANNELLO_CHIPS_MORE.format(k=k)
        self.more.setText(strings.PANNELLO_CHIPS_LESS if unfolded else more)
        tip = strings.PANNELLO_CHIPS_LESS_NAME if unfolded else strings.PANNELLO_CHIPS_MORE_NAME.format(names=names)
        self.more.setToolTip(tip)
        self.more.setAccessibleName(tip)
        self.more.setHidden(not hidden)
        self.layout().invalidate()
        self.updateGeometry()

    def _on_toggled(self, _on: bool) -> None:
        self._show_chips()
        self.changed.emit(self.selected())

    def selected(self) -> frozenset[str]:
        return frozenset(t for t, chip in self.chips.items() if chip.isChecked())

    def set_selected(self, types: frozenset[str] | set[str], *, emit: bool = True) -> None:
        """Turn exactly ``types`` on, emitting ``changed`` once (``emit``)."""
        self.blockSignals(True)
        for tipo, chip in self.chips.items():
            chip.setChecked(tipo in types)
        self.blockSignals(False)
        self._show_chips()
        if emit:
            self.changed.emit(self.selected())
