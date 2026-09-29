"""The pieces of the differences list (split from ``officina_diffs``, size):
:class:`DiffList` (rows that are widgets sized to the width; ↑/↓ over the
rows and the type-group headers — never onto the "DA VERIFICARE" header —,
Enter, Space, F / T / V), one row's widget, the group headers and the key
legend.

Phase 2.5 (U3): a row says its verdict (pill), its ZONE and page, and — only
for the classes that are not plain text — the class glyph; the type is the
row's group (``officina_types``). A type-group header is a row of its own
that the keyboard reaches: Enter or Space folds / unfolds it.
"""
from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import QEvent, QObject, QSize, Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QSizePolicy,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import Anchor, Judged
from qtrequestory.ui.pages.officina_progress import GLYPH_FONT, glyph_html
from qtrequestory.ui.pages.officina_rows import (
    REVIEW_KEYS,
    class_glyph,
    fit_context,
    notes_for,
    snippet_html,
    where_text,
)
from qtrequestory.ui.pages.officina_types import TypeGroup, where_zone
from qtrequestory.ui.pages.officina_verdict_style import LOOKS, look_for
from qtrequestory.ui.pages.officina_widgets import pill

__all__ = ["DIMMED_OPACITY", "DIFF_ID", "GROUP_KEY", "DiffList", "RowWidget", "group_header", "legend_html",
           "pill_column_width", "type_header"]

#: The item data of a difference row: its ``Diff.id`` (None on a header).
DIFF_ID = Qt.ItemDataRole.UserRole
#: The item data of a type-group header: its group key.
GROUP_KEY = Qt.ItemDataRole.UserRole + 1
#: Classes whose glyph a row still shows (the others read as text: the group says the type).
_GLYPH_CLASSES = frozenset({"composizione", "stile", "spaziatura", "variabile", "rumore", "link"})

#: The "DA VERIFICARE" rows under "Da guardare" are dimmed like the draft.
DIMMED_OPACITY = 0.6
#: Room around the pill's icon (the side panel's QSS pads it 2 px a side).
PILL_PADDING = 12
#: Row pills: one height (Qt drops a 9 px radius on a pill shorter than 18 px).
PILL_HEIGHT = 20
#: Room kept free at the end of a snippet line (rounding, the hair of kerning).
SNIPPET_SLACK = 6


class DiffList(QListWidget):
    """A list whose rows are widgets sized to the width, with the keys of §7.2."""

    enter_pressed = Signal()
    toggle_pressed = Signal()  # Space: fold / unfold the group header under the cursor
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
            if key == Qt.Key.Key_Space:
                self.toggle_pressed.emit()
                return
            if key in REVIEW_KEYS:
                self.key_action.emit(REVIEW_KEYS[key])
                return
            if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                self.step(-1 if key == Qt.Key.Key_Up else 1, headers=True)
                return
        super().keyPressEvent(event)

    def selectable_rows(self) -> list[int]:
        """The rows that are differences."""
        return [r for r in range(self.count())
                if self.item(r).flags() & Qt.ItemFlag.ItemIsSelectable and self.item(r).data(DIFF_ID) is not None]

    def navigable_rows(self) -> list[int]:
        """The differences and the type-group headers (not the "DA VERIFICARE" one)."""
        return [r for r in range(self.count()) if self.item(r).flags() & Qt.ItemFlag.ItemIsSelectable]

    def step(self, direction: int, *, headers: bool = False) -> None:
        """The next / previous difference (``headers``: or type-group header;
        never the "DA VERIFICARE" header)."""
        rows = self.navigable_rows() if headers else self.selectable_rows()
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
        """Each row widget as tall as its text at the list's width."""
        width = max(80, self.viewport().width())
        self._fitted_width = self.viewport().width()
        for row in range(self.count()):
            self.fit_row(self.item(row), width)

    def fit_row(self, item, width: int | None = None) -> None:
        """One row's height (e.g. after its secondary line was shown or hidden)."""
        width = width if width is not None else max(80, self.viewport().width())
        widget = self.itemWidget(item)
        if widget is None:
            return
        if isinstance(widget, RowWidget):
            widget.fit(width)
        if widget.layout() is not None:
            widget.layout().activate()
        height = (widget.heightForWidth(width) if widget.hasHeightForWidth()
                  else widget.sizeHint().height())
        item.setSizeHint(QSize(width, max(height, widget.minimumSizeHint().height())))

    def expand_current(self) -> None:
        """Only the current row shows its secondary line (U3 fix round 1)."""
        current = self.currentItem()
        for row in range(self.count()):
            item = self.item(row)
            widget = self.itemWidget(item)
            if isinstance(widget, RowWidget) and widget.set_expanded(item is current):
                self.fit_row(item)

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
    """One row, on ONE line (U3 fix round 1, draft f25-caso-v2): the verdict
    pill as its icon only (a fixed-width column; the word is its tooltip and
    accessible name), the snippet with as many context words as fit
    (:meth:`fit`, R33), the zone · page right-aligned (the operation in its
    tooltip). The secondary line — the class glyph when the class is not
    plain text, "Prima «…» → ora «…»", "Nell'AS-IS era uguale…", the non
    risolta reason, a link's href — shows only on the selected row
    (:meth:`set_expanded`); the item's tooltip carries it always."""

    def __init__(self, j: Judged, tokens: theme.Tokens, *, dim: bool, version: int,
                 since: Mapping[Anchor, int]) -> None:
        super().__init__()
        self.diff = j.diff
        self.tokens = tokens
        look = look_for(j)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        box = QVBoxLayout(self)
        box.setContentsMargins(theme.SPACE[1], 3, theme.SPACE[1], 3)
        box.setSpacing(2)
        head = QHBoxLayout()
        head.setSpacing(theme.SPACE[0])
        self.verdict = pill("", look.pill)
        self.verdict.setTextFormat(Qt.TextFormat.RichText)
        self.verdict.setText(glyph_html(look.icon))
        self.verdict.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.verdict.setToolTip(look.label)
        self.verdict.setAccessibleName(look.label)
        self.verdict.setFixedSize(pill_column_width(self.verdict), PILL_HEIGHT)
        self.snippet = QLabel(snippet_html(j.diff, tokens))
        self.snippet.setTextFormat(Qt.TextFormat.RichText)
        self.snippet.setWordWrap(False)
        self.snippet.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.where = QLabel(where_zone(j))
        self.where.setToolTip(where_text(j.diff))
        self.where.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)  # always whole
        theme.set_role(self.where, "muted")
        head.addWidget(self.verdict, 0, Qt.AlignmentFlag.AlignVCenter)
        head.addWidget(self.snippet, 1, Qt.AlignmentFlag.AlignVCenter)
        head.addWidget(self.where, 0, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        box.addLayout(head)
        self.more = QWidget()  # the secondary line: only on the selected row
        box.addWidget(self.more)  # parented before anything in it is shown: never a window (D7)
        more = QVBoxLayout(self.more)
        more.setContentsMargins(pill_column_width(self.verdict) + theme.SPACE[0], 0, 0, 0)
        more.setSpacing(1)
        glyph, name = class_glyph(j.diff)
        self.klass = QLabel(glyph_html(glyph) + "&nbsp;" + name)
        self.klass.setTextFormat(Qt.TextFormat.RichText)
        theme.set_role(self.klass, "muted")
        more.addWidget(self.klass)
        self.klass.setHidden(j.diff.klass not in _GLYPH_CLASSES and j.diff.op != "spostato")
        self.notes: list[str] = []
        for text, tone in notes_for(j, version, since):
            note = QLabel(text)
            note.setWordWrap(True)
            theme.set_role(note, "diffNoteBad" if tone == "bad" else "muted")
            more.addWidget(note)
            self.notes.append(text)
        self._has_more = bool(self.notes) or not self.klass.isHidden()
        self.more.setHidden(True)
        if dim:
            effect = QGraphicsOpacityEffect(self)
            effect.setOpacity(DIMMED_OPACITY)
            self.setGraphicsEffect(effect)

    def set_expanded(self, on: bool) -> bool:
        """Show the secondary line (``on``: the selected row); True when that changed."""
        show = on and self._has_more
        if self.more.isHidden() != show:
            return False
        self.more.setHidden(not show)
        return True

    def is_expanded(self) -> bool:
        return not self.more.isHidden()

    def fit(self, width: int) -> None:
        """As many context words as fit on the one line at ``width`` beside
        the pill and the zone · page, each piece measured in its own weight
        (the changed runs bold); what still does not fit is elided from the
        end with "…" (D5) — the trailing context first, so the change stays
        in sight — and the zone · page keeps its room (the whole texts are
        the tooltip)."""
        margins = self.layout().contentsMargins()
        spacing = self.layout().itemAt(0).layout().spacing()
        room = (width - margins.left() - margins.right() - self.verdict.width()
                - self.where.sizeHint().width() - 2 * spacing - SNIPPET_SLACK)
        self.snippet.ensurePolished()
        normal = QFontMetrics(self.snippet.font())
        font = QFont(self.snippet.font())
        font.setBold(True)
        bold = QFontMetrics(font)
        room = max(0, room)
        before, after = fit_context(self.diff, room, normal.horizontalAdvance, bold.horizontalAdvance)
        self.snippet.setText(snippet_html(self.diff, self.tokens, before=before, after=after,
                                          fit=(room, normal.horizontalAdvance, bold.horizontalAdvance)))


def pill_column_width(verdict: QLabel) -> int:
    """The width of the widest verdict icon (a flagged regressione's "▲!"
    included), so every row's pill is as wide."""
    verdict.ensurePolished()
    font = QFont(verdict.font())
    font.setBold(True)
    font.setFamily(GLYPH_FONT)
    metrics = QFontMetrics(font)
    icons = [look.icon for look in LOOKS.values()] + [strings.VERDETTO_ICON_REGRESSIONE + "!"]
    return max(metrics.horizontalAdvance(icon) for icon in icons) + PILL_PADDING


def group_header() -> QLabel:
    label = QLabel(strings.ELENCO_GROUP_VERIFICARE)
    theme.set_role(label, "diffGroup")
    return label


def type_header(group: TypeGroup) -> QLabel:
    """"▾ Aa Parole · 2" (▸ when folded): a type group of the list."""
    arrow = "▸" if group.folded else "▾"
    label = QLabel(glyph_html(f"{arrow} {group.icon}") + "&nbsp;&nbsp;" + group.text)
    label.setTextFormat(Qt.TextFormat.RichText)
    label.setToolTip(strings.PANNELLO_GROUP_TIP)
    label.setAccessibleName(group.text)
    theme.set_role(label, "diffTypeGroup")
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
