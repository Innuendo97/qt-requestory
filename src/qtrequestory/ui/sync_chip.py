"""The sync chip in the header: "⟳ svil oggi 09:00 · coll 2 da scaricare".

Officina 2.5 (D5) moved the Sincronizzazione tab into this chip. It says the
environments' state in words and, when something needs the user, says so on
three channels (never colour alone, WCAG 1.4.1):

* **colour** — the sync glyph turns the icon's amber (``identity``) or the
  header's red (``header_bad``);
* **shape** — a small amber dot, or a larger red disc with "!";
* **text** — the chip itself, its tooltip (one line per environment in
  trouble) and its accessible name ("Sincronizzazione: 1 ambiente da
  controllare").

No dot when all is fine. While a sync runs the glyph turns (unless the app
asks for reduced motion). The chip decides nothing: the level comes ready-made
from :func:`~.pages.sync_badge.attention_for`, the same badges the cards show.
A click, Enter or Space asks for the dropdown panel (``clicked``).
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import NamedTuple

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget

from qtrequestory.ui import icons, strings, theme
from qtrequestory.ui.pages.sync_badge import Attention
from qtrequestory.ui.toast import Toast

__all__ = ["SYNC_PANEL_SHORTCUT", "StatusChip", "SyncGlyph"]

#: Opens the panel (it opened the Sincronizzazione tab before D5).
SYNC_PANEL_SHORTCUT = "Ctrl+2"
GLYPH_PX = 16


class DotShape(NamedTuple):
    """The attention mark: its radius in px and the glyph drawn inside it."""

    radius: float
    mark: str


_SHAPES = {"warn": DotShape(3.5, ""), "bad": DotShape(5.5, "!")}


class SyncGlyph(QWidget):
    """The ⟳ glyph with its attention dot, painted (a tinted, turning icon)."""

    #: Frame interval of the turning glyph, and degrees per frame.
    SPIN_MS = 40
    SPIN_STEP = 12

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(GLYPH_PX + 8, GLYPH_PX + 4)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._level = ""
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(self.SPIN_MS)
        self._timer.timeout.connect(self._turn)
        theme.signals.changed.connect(self.update)

    def level(self) -> str:
        return self._level

    def angle(self) -> int:
        return self._angle

    def is_spinning(self) -> bool:
        return self._timer.isActive()

    def set_level(self, level: str) -> None:
        self._level = level if level in _SHAPES else ""
        self.update()

    def set_spinning(self, on: bool) -> None:
        if on and Toast.animations_enabled():
            if not self._timer.isActive():
                self._timer.start()
            return
        self._timer.stop()
        self._angle = 0
        self.update()

    def ink(self) -> str:
        """The glyph's colour: white at rest, amber or red when it asks for attention."""
        t = theme.tokens()
        return {"warn": t.identity, "bad": t.header_bad}.get(self._level, t.on_header)

    def dot_shape(self) -> DotShape | None:
        return _SHAPES.get(self._level)

    def _turn(self) -> None:
        self._angle = (self._angle + self.SPIN_STEP) % 360
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        centre = QPointF(GLYPH_PX / 2 + 1, self.height() / 2)
        painter.save()
        painter.translate(centre)
        painter.rotate(self._angle)
        pixmap = icons.icon("arrow-sync", self.ink()).pixmap(GLYPH_PX, GLYPH_PX)
        painter.drawPixmap(QRectF(-GLYPH_PX / 2, -GLYPH_PX / 2, GLYPH_PX, GLYPH_PX), pixmap,
                           QRectF(pixmap.rect()))
        painter.restore()
        shape = self.dot_shape()
        if shape is not None:
            self._paint_dot(painter, shape)
        painter.end()

    def _paint_dot(self, painter: QPainter, shape: DotShape) -> None:
        """Top right, ringed in the chip's own blue so it reads off the glyph."""
        t = theme.tokens()
        r = shape.radius
        c = QPointF(self.width() - r - 0.5, r + 0.5)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(t.header_raise))
        painter.drawEllipse(c, r + 1.5, r + 1.5)
        painter.setBrush(QColor(self.ink()))
        painter.drawEllipse(c, r, r)
        if shape.mark:
            font = QFont(self.font())
            font.setBold(True)
            font.setPixelSize(int(r * 2 - 2))
            painter.setFont(font)
            painter.setPen(QColor(t.header_end))
            painter.drawText(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r),
                             Qt.AlignmentFlag.AlignCenter, shape.mark)


class StatusChip(QPushButton):
    """The header's sync chip: glyph + "svil oggi 09:00 · coll 2 da scaricare"."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("statusChip")
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)  # a click must not steal the focus
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setProperty("current", False)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 10, 0)
        layout.setSpacing(4)
        self.glyph = SyncGlyph(self)
        self.text_label = QLabel(self)
        self.text_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self.glyph)
        layout.addWidget(self.text_label)
        self._layout = layout
        self._summary = ""
        self._notes: list[str] = []
        self._attention = Attention()
        self.hide()

    def set_envs(self, items: Sequence[tuple]) -> None:
        """``(env, tone, text)`` or ``(env, tone, text, note)`` per environment;
        an empty list hides the chip. A note goes into the tooltip as "env: note".

        ``env`` may be empty: :meth:`MainWindow.set_sync_summary` passes one
        plain line that way. The tone is not drawn: the attention dot says
        what matters for all the environments together (:meth:`set_attention`).
        """
        parts: list[str] = []
        self._notes = []
        for env, _tone, text, *note in items:
            parts.append(f"{env} {text}".strip())
            if note and note[0]:
                self._notes.append(f"{env}: {note[0]}" if env else note[0])
        self._summary = strings.CHIP_SEPARATOR.join(parts)
        self.text_label.setText(self._summary)
        self._describe()
        self.setVisible(bool(parts))
        self.updateGeometry()

    def set_attention(self, attention: Attention) -> None:
        """Colour, dot and words for what needs the user; spin while running."""
        self._attention = attention
        self.glyph.set_level(attention.level)
        self.glyph.set_spinning(attention.running)
        self._describe()

    def attention(self) -> Attention:
        return self._attention

    def summary(self) -> str:
        """The chip as plain text ("coll oggi 11:24 · svil ieri 18:40")."""
        return self._summary

    @staticmethod
    def accessible_name(attention: Attention, summary: str) -> str:
        if attention.count:
            head = (strings.SYNC_CHIP_A11Y_ATTENTION_ONE if attention.count == 1
                    else strings.SYNC_CHIP_A11Y_ATTENTION.format(n=attention.count))
        elif attention.running:
            head = strings.SYNC_CHIP_A11Y_RUNNING
        else:
            head = strings.SYNC_CHIP_A11Y_OK
        return strings.SYNC_CHIP_A11Y_SEP.join(p for p in (head, summary) if p)

    def _describe(self) -> None:
        head = strings.SYNC_CHIP_TOOLTIP.format(shortcut=SYNC_PANEL_SHORTCUT)
        self.setToolTip("\n".join([head, *self._attention.lines, *self._notes]))
        self.setAccessibleName(self.accessible_name(self._attention, self._summary))
        self.setAccessibleDescription("\n".join(self._attention.lines))

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        """Enter opens the panel like Space (a QPushButton outside a dialog ignores it)."""
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not event.isAutoRepeat():
            self.click()
            return
        super().keyPressEvent(event)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        """The children's size: ``QPushButton`` only measures its own text."""
        hint = self._layout.sizeHint()
        return QSize(hint.width(), max(hint.height(), 24))

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        return self.sizeHint()

