"""The pieces of the differences list (split from ``officina_diffs``, size):
:class:`DiffList` (rows that are widgets sized to the width; ↑/↓ over the
group header, Enter, F / T / V), one row's widget, the "DA VERIFICARE" group
header and the key legend."""
from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import QEvent, QObject, QSize, Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import Anchor, Judged
from qtrequestory.ui.pages.officina_progress import glyph_html
from qtrequestory.ui.pages.officina_rows import (
    REVIEW_KEYS,
    class_glyph,
    fit_context,
    notes_for,
    snippet_html,
    where_text,
)
from qtrequestory.ui.pages.officina_verdict_style import LOOKS, look_for, state_of
from qtrequestory.ui.pages.officina_widgets import pill

__all__ = ["DIMMED_OPACITY", "DiffList", "RowWidget", "group_header", "legend_html",
           "pill_column_width"]

#: The "DA VERIFICARE" rows under "Da guardare" are dimmed like the draft.
DIMMED_OPACITY = 0.6
#: The pill's QSS padding (8 px a side) plus room for the symbol-font glyphs.
PILL_PADDING = 24
#: Row pills: one height (Qt drops a 9 px radius on a pill shorter than 18 px).
PILL_HEIGHT = 20
#: Room kept free at the end of a snippet line (rounding, the hair of kerning).
SNIPPET_SLACK = 6


class DiffList(QListWidget):
    """A list whose rows are widgets sized to the width, with the keys of §7.2."""

    enter_pressed = Signal()
    key_action = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("diffList")
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        #: The viewport width the rows were last fitted to: the vertical scroll
        #: bar appearing narrows the viewport without resizing the list.
        self._fitted_width = -1
        self.viewport().installEventFilter(self)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        mods = event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
        key = event.key()
        if mods == Qt.KeyboardModifier.NoModifier:
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.enter_pressed.emit()
                return
            if key in REVIEW_KEYS:
                self.key_action.emit(REVIEW_KEYS[key])
                return
            if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                self.step(-1 if key == Qt.Key.Key_Up else 1)
                return
        super().keyPressEvent(event)

    def selectable_rows(self) -> list[int]:
        return [r for r in range(self.count())
                if self.item(r).flags() & Qt.ItemFlag.ItemIsSelectable]

    def step(self, direction: int) -> None:
        """The next / previous row that is a difference (never the group header)."""
        rows = self.selectable_rows()
        if not rows:
            return
        current = self.currentRow()
        if current not in rows:
            self.setCurrentRow(rows[0] if direction > 0 else rows[-1])
            return
        index = rows.index(current) + direction
        if 0 <= index < len(rows):
            self.setCurrentRow(rows[index])

    def fit_rows(self) -> None:
        """Each row widget as tall as its wrapped text at the list's width."""
        width = max(80, self.viewport().width())
        self._fitted_width = self.viewport().width()
        for row in range(self.count()):
            item = self.item(row)
            widget = self.itemWidget(item)
            if widget is None:
                continue
            if isinstance(widget, RowWidget):
                widget.fit(width)
            height = (widget.heightForWidth(width) if widget.hasHeightForWidth()
                      else widget.sizeHint().height())
            item.setSizeHint(QSize(width, max(height, widget.minimumSizeHint().height())))

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self.fit_rows()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt naming
        """The scroll bar came or went: fit the rows to the new viewport width
        (once per width, so the refit cannot bounce the scroll bar forever)."""
        if (event.type() == QEvent.Type.Resize and watched is self.viewport()
                and self.viewport().width() != self._fitted_width):
            self.fit_rows()
        return False


class RowWidget(QWidget):
    """One row: verdict pill (a fixed-width column, so the class chips line
    up), class glyph, page · op; the snippet; the notes. :meth:`fit` sets how
    many context words the snippet shows at the row's width (R33)."""

    def __init__(self, j: Judged, tokens: theme.Tokens, *, dim: bool, version: int,
                 since: Mapping[Anchor, int]) -> None:
        super().__init__()
        self.diff = j.diff
        self.tokens = tokens
        look = look_for(j)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        box = QVBoxLayout(self)
        box.setContentsMargins(theme.SPACE[1], 5, theme.SPACE[1], 6)
        box.setSpacing(2)
        head = QHBoxLayout()
        head.setSpacing(theme.SPACE[0])
        self.verdict = pill("", look.pill)
        self.verdict.setTextFormat(Qt.TextFormat.RichText)
        # the column is narrow: the state's own word; a flagged regressione's full label is the tooltip
        self.verdict.setText(glyph_html(f"{look.icon} {LOOKS[state_of(j)].label}"))
        self.verdict.setToolTip(look.label)
        self.verdict.setFixedSize(pill_column_width(self.verdict), PILL_HEIGHT)
        glyph, name = class_glyph(j.diff)
        self.klass = QLabel(glyph_html(glyph))
        self.klass.setToolTip(name)
        theme.set_role(self.klass, "diffGlyph")
        where = QLabel(where_text(j.diff))
        theme.set_role(where, "muted")
        for widget, stretch in ((self.verdict, 0), (self.klass, 0), (where, 1)):
            head.addWidget(widget, stretch, Qt.AlignmentFlag.AlignVCenter)
        box.addLayout(head)
        self.snippet = QLabel(snippet_html(j.diff, tokens))
        self.snippet.setTextFormat(Qt.TextFormat.RichText)
        self.snippet.setWordWrap(True)
        box.addWidget(self.snippet)
        for text, tone in notes_for(j, version, since):
            note = QLabel(text)
            note.setWordWrap(True)
            theme.set_role(note, "diffNoteBad" if tone == "bad" else "muted")
            box.addWidget(note)
        if dim:
            effect = QGraphicsOpacityEffect(self)
            effect.setOpacity(DIMMED_OPACITY)
            self.setGraphicsEffect(effect)

    def fit(self, width: int) -> None:
        """As many context words as fit on one line at ``width``, each piece
        measured in its own weight (the changed runs bold); the change itself
        may still wrap."""
        margins = self.layout().contentsMargins()
        room = width - margins.left() - margins.right() - SNIPPET_SLACK
        self.snippet.ensurePolished()
        normal = QFontMetrics(self.snippet.font())
        font = QFont(self.snippet.font())
        font.setBold(True)
        bold = QFontMetrics(font)
        before, after = fit_context(self.diff, room, normal.horizontalAdvance, bold.horizontalAdvance)
        self.snippet.setText(snippet_html(self.diff, self.tokens, before=before, after=after))


def pill_column_width(verdict: QLabel) -> int:
    """The width of the widest verdict pill, so every row's pill is as wide."""
    verdict.ensurePolished()
    font = QFont(verdict.font())
    font.setBold(True)
    metrics = QFontMetrics(font)
    widest = max(metrics.horizontalAdvance(f"{look.icon} {look.label}") for look in LOOKS.values())
    return widest + PILL_PADDING


def group_header() -> QLabel:
    label = QLabel(strings.ELENCO_GROUP_VERIFICARE)
    theme.set_role(label, "diffGroup")
    return label


def legend_html(t: theme.Tokens) -> str:
    """The key reminder; a group ("F fatta") never breaks across lines."""
    def key(text: str) -> str:
        return (f"<span style='background-color:{t.surface2};color:{t.text};font-weight:600'>"
                f"&nbsp;{text}&nbsp;</span>")

    def group(*parts: str) -> str:
        return "&nbsp;".join(p.replace(" ", "&nbsp;") if not p.startswith("<") else p
                             for p in parts)

    groups = [group(key("↑"), key("↓"), strings.ELENCO_KEY_MOVE),
              group(key(strings.ELENCO_KEY_ENTER), strings.ELENCO_KEY_GO),
              group(key("F"), strings.ELENCO_KEY_OR_DOUBLE_CLICK, strings.ELENCO_KEY_DONE),
              group(key("T"), strings.ELENCO_KEY_TOLERATE),
              group(key("V"), strings.ELENCO_KEY_NOT_VARIABLE),
              group(strings.ELENCO_KEY_RIGHT_CLICK, strings.ELENCO_KEY_MORE),
              group(key(strings.ELENCO_KEY_UNDO), strings.ELENCO_KEY_UNDO_WHAT)]
    return " · ".join(groups)
