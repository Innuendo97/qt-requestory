"""The JSON syntax highlighter of the preview pane.

What is worth testing here is not "which hue" — that is taste — but the three
things a reader depends on: the four token classes are told apart, a key and
the string *value* next to it do not look the same (the whole point of a
highlighter in a file full of quoted text), and a light/dark switch re-derives
the colours instead of leaving grey on grey.

Formats are read back through the public text layout: ``QSyntaxHighlighter``
pushes its ``setFormat`` calls into ``QTextBlock.layout().formats()``, which
only exists on a document that has a layout — hence a real ``QPlainTextEdit``
rather than a bare ``QTextDocument``.
"""
from __future__ import annotations

import time

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette, QTextDocument
from PySide6.QtWidgets import QPlainTextEdit

from qtrequestory.ui.json_highlighter import JsonHighlighter

SAMPLE = (
    '{\n'
    '    "documents": [\n'
    '        {\n'
    '            "attachmentId": "a-1",\n'
    '            "ndocs": 12,\n'
    '            "isFlag": true,\n'
    '            "dossier": null\n'
    '        }\n'
    '    ]\n'
    '}\n'
)


@pytest.fixture
def editor(qtbot) -> QPlainTextEdit:
    widget = QPlainTextEdit()
    qtbot.addWidget(widget)
    return widget


@pytest.fixture
def highlighter(editor) -> JsonHighlighter:
    """A highlighter on ``SAMPLE``; its document is ``highlighter.document()``."""
    instance = JsonHighlighter(editor.document())
    editor.setPlainText(SAMPLE)
    return instance


@pytest.fixture
def app_palette(qapp):
    """Restore the application palette afterwards: it is process-wide state."""
    original = qapp.palette()
    yield
    qapp.setPalette(original)


def span_of(document: QTextDocument, fragment: str) -> tuple[int, int, QColor]:
    """``(start, length, foreground)`` of the format covering ``fragment``."""
    for number in range(document.blockCount()):
        block = document.findBlockByNumber(number)
        start = block.text().find(fragment)
        if start < 0:
            continue
        for span in block.layout().formats():
            if span.start <= start < span.start + span.length:
                return span.start, span.length, span.format.foreground().color()
        raise AssertionError(f"{fragment!r} is in the document but carries no format")
    raise AssertionError(f"{fragment!r} is not in the document")


def color_of(document: QTextDocument, fragment: str) -> QColor:
    return span_of(document, fragment)[2]


def dark_palette() -> QPalette:
    palette = QPalette()
    for role in (QPalette.ColorRole.Base, QPalette.ColorRole.Window):
        palette.setColor(role, QColor("#1f1f1f"))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText):
        palette.setColor(role, QColor("#e6e6e6"))
    return palette


# ------------------------------------------------------------------ tokens ---

def test_the_four_token_classes_get_four_different_colors(highlighter):
    document = highlighter.document()
    names = {
        "key": color_of(document, '"documents"').name(),
        "string": color_of(document, '"a-1"').name(),
        "number": color_of(document, "12").name(),
        "literal": color_of(document, "true").name(),
    }
    assert len(set(names.values())) == 4, names


def test_a_key_and_the_string_value_beside_it_are_told_apart(highlighter):
    """``"attachmentId": "a-1"`` — same shape, different meaning."""
    document = highlighter.document()
    assert color_of(document, '"attachmentId"') != color_of(document, '"a-1"')


def test_null_is_a_literal_and_not_a_string(highlighter):
    document = highlighter.document()
    assert color_of(document, "null") == color_of(document, "true")
    assert color_of(document, "null") != color_of(document, '"a-1"')


def test_punctuation_is_the_body_text_faded(highlighter, qapp):
    """Braces carry no information: they must not compete with the values."""
    punctuation = color_of(highlighter.document(), "{")
    text = qapp.palette().color(QPalette.ColorRole.Text)

    assert punctuation.alpha() < 255, "punctuation must be muted"
    assert (punctuation.red(), punctuation.green(), punctuation.blue()) == (
        text.red(), text.green(), text.blue()
    ), "muted punctuation is the palette's own text colour, not a third hue"


def test_a_digit_inside_a_string_stays_a_string(editor):
    """The number rule must not reach inside ``"12345"`` or every id would glow."""
    JsonHighlighter(editor.document())
    editor.setPlainText('{\n    "codice": "12345",\n    "n": 7\n}\n')
    document = editor.document()

    start, length, color = span_of(document, '"12345"')
    assert length == len('"12345"'), "the whole quoted value is one span"
    assert color != color_of(document, "7")


def test_a_key_whose_value_is_on_the_same_line_does_not_swallow_the_colon(highlighter):
    start, length, _ = span_of(highlighter.document(), '"ndocs"')
    assert length == len('"ndocs"')


# ------------------------------------------------------------ palette change ---

def test_refresh_colors_re_derives_the_palette_and_rehighlights(highlighter, qapp, app_palette):
    document = highlighter.document()
    before = color_of(document, '"documents"')

    qapp.setPalette(dark_palette())
    highlighter.refresh_colors()

    after = color_of(document, '"documents"')
    assert after != before, "a dark window must not keep the light-theme hues"
    assert after.lightness() > 110, "keys must stay readable on a dark background"


def test_a_light_dark_switch_refreshes_the_colors_by_itself(highlighter, qapp, app_palette):
    """The pane never calls ``refresh_colors``: the highlighter listens itself."""
    document = highlighter.document()
    before = color_of(document, '"documents"')

    qapp.setPalette(dark_palette())
    qapp.styleHints().colorSchemeChanged.emit(Qt.ColorScheme.Dark)

    assert color_of(document, '"documents"') != before


def test_refresh_colors_without_a_document_does_not_crash(qapp):
    """The pane refreshes on every ``colorSchemeChanged``, even with no body yet."""
    JsonHighlighter(None).refresh_colors()


# -------------------------------------------------------------------- speed ---

def test_four_thousand_lines_highlight_without_pathological_backtracking(editor):
    body = '{\n    "documents": [\n' + '        {"id": "a-1", "n": 12, "ok": true},\n' * 4000 + "    ]\n}\n"
    JsonHighlighter(editor.document())

    started = time.perf_counter()
    editor.setPlainText(body)
    elapsed = time.perf_counter() - started

    assert elapsed < 1.0, f"highlighting 4000 lines took {elapsed:.2f}s"
    assert color_of(editor.document(), "true").isValid()
