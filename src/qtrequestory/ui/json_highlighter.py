"""Syntax highlighting for the pretty-printed request bodies.

A request body is 4-space JSON that is mostly quoted text: without colours a
reader cannot tell a *key* from the string *value* next to it, which is exactly
the distinction they are scanning for ("where is `templateKey`?"). So four
token classes get four colours and the punctuation — braces, brackets, commas,
colons — is faded out instead: it carries no information and only adds noise at
4000 lines.

**Why one alternation instead of four passes.** The rules are mutually
exclusive and order matters (``12`` inside ``"a-12"`` is not a number), so a
single regex scanned left to right decides each token once: the string rule
consumes the quotes first, and nothing inside them can match again. Each
alternative is anchored and backtrack-free, so a block costs one linear scan —
the cap in the pane is 4000 lines and every one of them is rehighlighted on a
light/dark switch.

**Why the colours are half palette, half table.** A ``QPalette`` has no role
for "JSON string", so the four hues are two hand-picked sets (one for a light
Base, one for a dark one) chosen for contrast against it; what the palette
decides is *which* set, and the muted punctuation is literally the palette's
own ``Text`` colour at reduced alpha, so it follows a custom theme for free.
``QStyleHints.colorScheme`` is the tie-break when the palette says nothing, and
its ``colorSchemeChanged`` signal re-derives everything.
"""
from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QPalette,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextDocument,
)

__all__ = ["JsonHighlighter"]

#: One left-to-right pass: a string first (so nothing matches inside it), then
#: the scalars, then the structure. ``key`` is a string followed by a colon.
TOKENS = re.compile(
    r'(?P<key>"(?:[^"\\]|\\.)*"(?=\s*:))'
    r'|(?P<string>"(?:[^"\\]|\\.)*")'
    r'|(?P<literal>\b(?:true|false|null)\b)'
    r'|(?P<number>-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)'
    r'|(?P<punctuation>[{}\[\],:])'
)

#: Foregrounds per token class, for a light and for a dark ``Base``. Both sets
#: clear 4.5:1 against their background; ``punctuation`` is derived instead.
LIGHT = {
    "key": "#0B5394",
    "string": "#9C2C2C",
    "literal": "#1750C4",
    "number": "#116329",
}
DARK = {
    "key": "#9CDCFE",
    "string": "#CE9178",
    "literal": "#569CD6",
    "number": "#B5CEA8",
}

#: How much of the text colour is left for the structural characters.
PUNCTUATION_ALPHA = 130


class JsonHighlighter(QSyntaxHighlighter):
    """Colours a pretty-printed JSON document, following the current palette.

    Attach it to a document and forget it: it re-derives its colours whenever
    the system switches between light and dark, because the connection to
    ``colorSchemeChanged`` dies with the highlighter (it is a ``QObject`` and
    Qt drops the connection with the receiver).
    """

    def __init__(self, document: QTextDocument | None = None) -> None:
        super().__init__(document)
        self._formats: dict[str, QTextCharFormat] = {}
        self._build_formats()
        hints = QGuiApplication.styleHints()
        if hints is not None:  # pragma: no branch - always set under a QApplication
            hints.colorSchemeChanged.connect(self._on_color_scheme_changed)

    # -- public ------------------------------------------------------------

    def refresh_colors(self) -> None:
        """Re-derive the formats from the current palette and repaint.

        Called on ``colorSchemeChanged`` and by the pane after any other event
        that can swap the palette; safe with no document attached, which is the
        state of a pane that has never shown a body.
        """
        self._build_formats()
        if self.document() is not None:
            self.rehighlight()

    # -- QSyntaxHighlighter -------------------------------------------------

    def highlightBlock(self, text: str) -> None:  # noqa: N802 - Qt naming
        """One line. JSON never spans a line here (``json.dumps`` escapes every
        newline inside a string), so no block state is needed."""
        for match in TOKENS.finditer(text):
            kind = match.lastgroup
            char_format = self._formats.get(kind)
            if char_format is not None:
                self.setFormat(match.start(), match.end() - match.start(), char_format)

    # -- internals ----------------------------------------------------------

    def _on_color_scheme_changed(self, _scheme: object) -> None:
        self.refresh_colors()

    def _build_formats(self) -> None:
        palette = QGuiApplication.palette()
        colors = DARK if _is_dark(palette) else LIGHT
        formats = {kind: _foreground(QColor(value)) for kind, value in colors.items()}
        muted = QColor(palette.color(QPalette.ColorRole.Text))
        muted.setAlpha(PUNCTUATION_ALPHA)
        formats["punctuation"] = _foreground(muted)
        self._formats = formats


def _foreground(color: QColor) -> QTextCharFormat:
    char_format = QTextCharFormat()
    char_format.setForeground(color)
    return char_format


def _is_dark(palette: QPalette) -> bool:
    """True when the text view's background is darker than its text.

    The palette is asked first and the style hint only breaks a tie: a user who
    forces a dark palette on a light desktop (or a test) must get readable
    colours, and ``colorScheme`` reports the *desktop*, not this application.
    """
    base = palette.color(QPalette.ColorRole.Base).lightness()
    text = palette.color(QPalette.ColorRole.Text).lightness()
    if base != text:
        return base < text
    hints = QGuiApplication.styleHints()
    return hints is not None and hints.colorScheme() == Qt.ColorScheme.Dark
