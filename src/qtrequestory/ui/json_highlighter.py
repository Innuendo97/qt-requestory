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

**Where the colours come from.** The four hues are the theme's ``code_*``
tokens and the muted punctuation is the theme's ``text`` at reduced alpha, so
the highlighter needs no colour of its own. ``theme.signals.changed`` fires
after every theme switch (including the desktop going dark in "Sistema" mode)
and re-derives everything.
"""
from __future__ import annotations

import re

from PySide6.QtGui import QColor, QSyntaxHighlighter, QTextCharFormat, QTextDocument

from qtrequestory.ui import theme

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

#: How much of the text colour is left for the structural characters.
PUNCTUATION_ALPHA = 130


class JsonHighlighter(QSyntaxHighlighter):
    """Colours a pretty-printed JSON document with the current theme's tokens.

    Attach it to a document and forget it: it re-derives its colours on every
    theme switch, and the connection to ``theme.signals.changed`` dies with the
    highlighter (it is a ``QObject`` and Qt drops the connection with the
    receiver).
    """

    def __init__(self, document: QTextDocument | None = None) -> None:
        super().__init__(document)
        self._formats: dict[str, QTextCharFormat] = {}
        self._build_formats()
        theme.signals.changed.connect(self.refresh_colors)

    # -- public ------------------------------------------------------------

    def refresh_colors(self) -> None:
        """Re-derive the formats from the current theme and repaint.

        Called on ``theme.signals.changed``; safe with no document attached,
        which is the state of a pane that has never shown a body.
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

    def _build_formats(self) -> None:
        tokens = theme.tokens()
        colors = {
            "key": tokens.code_key,
            "string": tokens.code_string,
            "literal": tokens.code_literal,
            "number": tokens.code_number,
        }
        formats = {kind: _foreground(QColor(value)) for kind, value in colors.items()}
        muted = QColor(tokens.text)
        muted.setAlpha(PUNCTUATION_ALPHA)
        formats["punctuation"] = _foreground(muted)
        self._formats = formats


def _foreground(color: QColor) -> QTextCharFormat:
    char_format = QTextCharFormat()
    char_format.setForeground(color)
    return char_format

