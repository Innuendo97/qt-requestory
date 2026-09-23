"""Transient in-window notifications ("JSON copiato · 157 KB").

A confirmation in the status bar sits at the very bottom edge, in small grey
text, and is easy to miss; a toast shows up over the content, in the corner the
eyes pass by, and goes away on its own. One toast per window: a new message
replaces the current one and restarts its timer, so a burst of copies never
stacks up.

The toast is a child of the window's central widget, anchored bottom-right
``MARGIN`` px from its edges; an event filter on that parent moves it on every
resize. It is never wider than the parent minus both margins: a longer message
("Salvato: <full path>") is elided in the middle, where a path is least useful.
It ignores the mouse, so it never covers a click meant for the table
underneath. It fades in and out unless motion is reduced — the application
property ``reduce_motion`` or the system's own animation switch.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QWidget,
)

from qtrequestory.ui import theme

__all__ = ["DEFAULT_MS", "MARGIN", "Toast"]

#: Distance from the parent's right and bottom edges.
MARGIN = 16
DEFAULT_MS = 2500
FADE_MS = 150
TONES = ("ok", "warn", "bad", "neutral")
#: The leading mark per tone; tinted by the theme (``QLabel#toastMark``).
MARKS = {"ok": "✓", "warn": "!", "bad": "✕", "neutral": "•"}


class Toast(QFrame):
    """One transient message over the bottom-right corner of ``parent``."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("toast")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 7, 12, 7)
        layout.setSpacing(8)
        self._mark = QLabel()
        self._mark.setObjectName("toastMark")
        self._label = QLabel()
        self._text = ""
        layout.addWidget(self._mark)
        layout.addWidget(self._label)

        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(1.0)
        self.setGraphicsEffect(self._effect)
        self._fade = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade.setDuration(FADE_MS)
        self._fade.finished.connect(self._on_fade_finished)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)

        parent.installEventFilter(self)
        self.hide()

    # -- API ---------------------------------------------------------------

    def show_message(self, text: str, tone: str = "neutral", ms: int = DEFAULT_MS) -> None:
        """Show ``text`` for ``ms`` milliseconds, replacing whatever is up."""
        tone = tone if tone in TONES else "neutral"
        self._text = text
        self._mark.setText(MARKS[tone])
        self.setProperty("tone", tone)
        theme.repolish(self)
        theme.repolish(self._mark)
        self._place()
        self._fade.stop()
        self.show()
        self.raise_()
        if self.animations_enabled():
            self._fade.setStartValue(self._effect.opacity())
            self._fade.setEndValue(1.0)
            self._fade.start()
        else:
            self._effect.setOpacity(1.0)
        self._timer.start(max(0, ms))

    def text(self) -> str:
        """The whole message, even when the label shows it elided."""
        return self._text

    def dismiss(self) -> None:
        """Hide now (fading out when motion is allowed)."""
        self._timer.stop()
        if not self.isVisible():
            return
        if self.animations_enabled():
            self._fade.stop()
            self._fade.setStartValue(self._effect.opacity())
            self._fade.setEndValue(0.0)
            self._fade.start()
        else:
            self.hide()

    @staticmethod
    def animations_enabled() -> bool:
        """False when the app asks for reduced motion or the system turned effects off."""
        app = QApplication.instance()
        if app is None or bool(app.property("reduce_motion")):
            return False
        return QApplication.isEffectEnabled(Qt.UIEffect.UI_General)

    # -- internals ---------------------------------------------------------

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt naming
        if watched is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self._place()
        return False

    def _place(self) -> None:
        """Fit the text to the parent's width, then anchor bottom-right."""
        parent = self.parentWidget()
        if parent is None:
            return
        room = max(0, parent.width() - 2 * MARGIN)
        self.setMaximumWidth(room)
        margins = self.layout().contentsMargins()
        chrome = (margins.left() + margins.right() + self.layout().spacing()
                  + self._mark.sizeHint().width())
        self._label.setText(QFontMetrics(self._label.font()).elidedText(
            self._text, Qt.TextElideMode.ElideMiddle, max(0, room - chrome)))
        self.adjustSize()
        self.move(parent.width() - self.width() - MARGIN,
                  parent.height() - self.height() - MARGIN)

    def _on_fade_finished(self) -> None:
        if self._effect.opacity() <= 0.0:
            self.hide()
            self._effect.setOpacity(1.0)
