"""The preview pane's JSON tab: the body, capped on screen, and its find bar.

**The cap is a display device, nothing more.** A body of 80 000 lines would
make ``QPlainTextEdit`` crawl, so only the first :data:`MAX_LINES` are shown
and the footer says so. The pane's actions always use the FULL text.

**The find bar searches the full text too.** It looks in the body string, not
in the editor's document: a match inside the shown part is selected in the
editor; a match beyond the cap is reported — "trovato oltre la riga 4.000:
apri nell'editor" — instead of "not found", which is what searching only the
document used to claim.
"""
from __future__ import annotations

import re

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import strings, theme
from qtrequestory.ui.json_highlighter import JsonHighlighter

__all__ = ["MAX_LINES", "BodyView", "capped", "thousands"]

#: Lines shown in the editor; the rest is one click away in the editor.
MAX_LINES = 4000


def capped(text: str) -> tuple[str, int]:
    """``(what to display, how many lines the body really has)``.

    An uncapped body is returned untouched — including its trailing newline —
    so that "what you see is the file" holds for everything short enough.
    """
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if len(lines) <= MAX_LINES:
        return text, len(lines)
    return "\n".join(lines[:MAX_LINES]), len(lines)


def thousands(value: int) -> str:
    """``4000`` -> ``"4.000"`` (Italian grouping)."""
    return f"{value:,}".replace(",", ".")


def _last(pattern: re.Pattern[str], text: str) -> re.Match[str] | None:
    match = None
    for match in pattern.finditer(text):  # noqa: B007 - the last one is the point
        pass
    return match


def _utf16_len(text: str) -> int:
    """Length in ``QTextDocument`` positions (UTF-16 code units)."""
    return len(text.encode("utf-16-le")) // 2


class BodyEdit(QPlainTextEdit):
    """The body view, with Ctrl+C rebound to the pane.

    A subclass rather than a ``QShortcut``: a shortcut with
    ``WidgetWithChildrenShortcut`` context would also swallow Ctrl+C from the
    find field. Overriding the editor's own key handling scopes the override to
    exactly the widget whose default is wrong — and a real key press in a test
    can exercise it.
    """

    #: Ctrl+C was pressed in the body; the pane decides selection vs. body.
    copy_requested = Signal()

    def event(self, event) -> bool:  # noqa: D102 - Qt override
        """Claim Ctrl+C before any shortcut (the page's own Ctrl+C) sees it."""
        if event.type() == QEvent.Type.ShortcutOverride and event.matches(
                QKeySequence.StandardKey.Copy):
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.matches(QKeySequence.StandardKey.Copy):
            self.copy_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class BodyView(QWidget):
    """Editor + find bar + footer; knows the full text and what is shown of it."""

    #: A message for the host's status bar (a miss, a match beyond the cap).
    message = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._text = ""
        self._shown = ""
        self.editor = BodyEdit()
        self.editor.setReadOnly(True)
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.editor.setFont(theme.mono_font())
        self.editor.setPlaceholderText(strings.PREVIEW_EMPTY)
        # Parented to the editor's document, so it lives exactly as long.
        self.highlighter = JsonHighlighter(self.editor.document())
        self.footer = QLabel()
        self.footer.setWordWrap(True)
        theme.set_role(self.footer, "muted")
        self.footer.setVisible(False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self.editor, 1)
        layout.addWidget(self._build_find_bar())
        layout.addWidget(self.footer)
        find = QShortcut(QKeySequence(QKeySequence.StandardKey.Find), self)
        find.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        find.activated.connect(self.show_find)
        escape = QShortcut(QKeySequence(Qt.Key.Key_Escape), self.find_bar)
        escape.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        escape.activated.connect(self.hide_find)

    def _build_find_bar(self) -> QWidget:
        self.find_bar = QWidget()
        bar = QHBoxLayout(self.find_bar)
        bar.setContentsMargins(0, 0, 0, 0)
        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText(strings.PREVIEW_FIND_PLACEHOLDER)
        self.find_edit.returnPressed.connect(self.find_next)
        bar.addWidget(self.find_edit, 1)
        for text, tooltip, slot in (
            (strings.PREVIEW_FIND_PREVIOUS_GLYPH, strings.PREVIEW_FIND_PREVIOUS, self.find_previous),
            (strings.PREVIEW_FIND_NEXT_GLYPH, strings.PREVIEW_FIND_NEXT, self.find_next),
            (strings.PREVIEW_FIND_CLOSE_GLYPH, strings.PREVIEW_FIND_CLOSE, self.hide_find),
        ):
            button = QToolButton()
            button.setText(text)
            button.setToolTip(tooltip)
            button.clicked.connect(slot)
            bar.addWidget(button)
        self.find_bar.setVisible(False)
        return self.find_bar

    # -- content ---------------------------------------------------------------

    def clear(self, placeholder: str = strings.PREVIEW_EMPTY) -> None:
        self._text = self._shown = ""
        self.editor.clear()
        self.editor.setPlaceholderText(placeholder)
        self.footer.clear()
        self.footer.setVisible(False)

    def set_text(self, text: str) -> None:
        self._text = text
        self._shown, total = capped(text)
        self.editor.setPlainText(self._shown)
        self.editor.setPlaceholderText(strings.PREVIEW_EMPTY)
        if total > MAX_LINES:
            self.footer.setText(strings.PREVIEW_TRUNCATED.format(
                shown=thousands(MAX_LINES), total=thousands(total)))
            self.footer.setVisible(True)

    def show_error(self, text: str) -> None:
        self.editor.setPlaceholderText(strings.PREVIEW_EMPTY)
        self.footer.setText(text)
        self.footer.setVisible(True)

    # -- find bar ----------------------------------------------------------

    def show_find(self) -> None:
        """Ctrl+F: reveal the inline find bar with the field focused."""
        self.find_bar.setVisible(True)
        self.find_edit.selectAll()
        self.find_edit.setFocus()

    def hide_find(self) -> None:
        self.find_bar.setVisible(False)
        self.editor.setFocus()

    def find_next(self) -> bool:
        return self._find(backward=False)

    def find_previous(self) -> bool:
        return self._find(backward=True)

    def _find(self, *, backward: bool) -> bool:
        """Search the FULL body from the cursor, wrapping once (case-insensitive).

        A miss keeps the cursor where it was: a term that is not there must
        not scroll the reader away from the line they were reading.
        """
        term = self.find_edit.text()
        if not term:
            return False
        pattern = re.compile(re.escape(term), re.IGNORECASE)
        cursor = self.editor.textCursor()
        # Editor positions are UTF-16; the shown text is a prefix of the body,
        # so map the cursor back to a Python index through that prefix.
        start = self._python_index(cursor.selectionStart() if backward else cursor.selectionEnd())
        if backward:
            before = [m for m in pattern.finditer(self._text, 0, max(start + len(term) - 1, 0))
                      if m.start() < start]
            match = before[-1] if before else _last(pattern, self._text)
        else:
            match = pattern.search(self._text, start) or pattern.search(self._text)
        if match is None:
            self.message.emit(strings.PREVIEW_FIND_NOT_FOUND.format(text=term))
            return False
        found, end = match.start(), match.end()
        if end > len(self._shown):
            self.message.emit(strings.PREVIEW_FIND_BEYOND.format(shown=thousands(MAX_LINES)))
            return True
        begin = _utf16_len(self._shown[:found])
        select = QTextCursor(self.editor.document())
        select.setPosition(begin)
        select.setPosition(begin + _utf16_len(self._shown[found:end]),
                           QTextCursor.MoveMode.KeepAnchor)
        self.editor.setTextCursor(select)
        return True

    def _python_index(self, position: int) -> int:
        """The Python index of a document position within the shown text."""
        if self._shown.isascii():
            return min(position, len(self._shown))
        units = 0
        for index, char in enumerate(self._shown):
            if units >= position:
                return index
            units += 2 if ord(char) > 0xFFFF else 1
        return len(self._shown)
