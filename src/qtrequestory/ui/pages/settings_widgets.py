"""Small widgets of the Impostazioni page (and the Info page's paths).

* :class:`ElidedLabel` — one line of text elided *in the middle*, full text as
  tooltip: a path is informative at both ends (the drive and the last folder),
  and wrapping it mid-word, as a word-wrapped ``QLabel`` does, is unreadable.
* :class:`PathField` — an elided monospace path that looks like a field, plus
  its buttons ([Sfoglia…], the [Apri cartella] icon…). Paths are picked, not
  typed: the mockup shows them that way, and a hand-typed path is where the
  slash and trailing-space surprises came from.
* :func:`form_card` — a titled card whose rows are a ``QFormLayout`` with the
  labels on the left, muted.

No colour is written here: every look is a QSS role or object name defined in
``theme_qss`` (the "Impostazioni" block at the end).
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import icons, strings, theme

__all__ = [
    "ElidedLabel", "IconButton", "PathField", "button", "form_card", "form_label", "hours_spin",
    "icon_button", "muted", "row",
]

#: The narrowest an elided label lets itself be squeezed to.
MIN_ELIDED_WIDTH = 60
#: Width of the label column of every form card (the mockup's 170 px).
FORM_LABEL_WIDTH = 170


class ElidedLabel(QLabel):
    """A one-line label that elides its text in the middle to fit its width.

    ``text()`` is what is *shown*; :meth:`full_text` is what was set. The full
    text is always the tooltip, so nothing is ever out of reach.
    """

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full = ""
        self._placeholder = ""
        self.setWordWrap(False)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.set_full_text(text)

    def full_text(self) -> str:
        return self._full

    def set_full_text(self, text: str) -> None:
        self._full = text
        self.setToolTip(text)
        self._elide()

    def set_placeholder(self, text: str) -> None:
        """What an empty label shows instead (muted through the ``empty`` property)."""
        self._placeholder = text
        self._elide()

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        hint = super().sizeHint()
        wanted = self.fontMetrics().horizontalAdvance(self._full or self._placeholder)
        margins = self.contentsMargins()
        return QSize(wanted + margins.left() + margins.right() + 8, hint.height())

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        return QSize(MIN_ELIDED_WIDTH, super().minimumSizeHint().height())

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        empty = not self._full
        if bool(self.property("empty")) != empty:
            self.setProperty("empty", empty)
            theme.repolish(self)
        shown = self._placeholder if empty else self._full
        width = self.contentsRect().width() - 2
        if width > 0:
            shown = self.fontMetrics().elidedText(shown, Qt.TextElideMode.ElideMiddle, width)
        if shown != super().text():
            super().setText(shown)


class PathField(QWidget):
    """An elided monospace path with its buttons; ``changed`` on every new path."""

    changed = Signal(str)

    def __init__(self, placeholder: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._text = ""
        self.label = ElidedLabel()
        self.label.setObjectName("pathField")
        self.label.setFont(theme.mono_font())
        self.label.set_placeholder(placeholder)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(theme.SPACE[1])
        self._layout.addWidget(self.label, 1)

    def text(self) -> str:
        return self._text

    def setText(self, text: str) -> None:  # noqa: N802 - mirrors QLineEdit
        if text == self._text:
            return
        self._text = text
        self.label.set_full_text(text)
        self.changed.emit(text)

    def add(self, widget: QWidget) -> QWidget:
        self._layout.addWidget(widget)
        return widget


def button(text: str, slot: Callable[[], object]) -> QPushButton:
    """``clicked`` carries a ``checked`` flag no slot here wants."""
    result = QPushButton(text)
    result.clicked.connect(lambda _checked=False: slot())
    return result


class IconButton(QPushButton):
    """A square icon button that re-tints its glyph when the theme changes.

    The retint is a bound method, so the connection dies with the button.
    """

    def __init__(self, icon_name: str, tooltip: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._icon_name = icon_name
        theme.set_role(self, "icon")
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip)
        self.retint()
        theme.signals.changed.connect(self.retint)

    def retint(self) -> None:
        self.setIcon(icons.icon(self._icon_name))


def icon_button(icon_name: str, tooltip: str, slot: Callable[[], object]) -> IconButton:
    result = IconButton(icon_name, tooltip)
    result.clicked.connect(lambda _checked=False: slot())
    return result


def muted(text: str = "", *, wrap: bool = False) -> QLabel:
    label = QLabel(text)
    theme.set_role(label, "muted")
    label.setWordWrap(wrap)
    return label


def form_card(title: str) -> tuple[QFrame, QFormLayout]:
    """A card with a section heading and an empty form under it."""
    card = QFrame()
    theme.set_role(card, "card")
    outer = QVBoxLayout(card)
    outer.setContentsMargins(theme.SPACE[3], theme.SPACE[2], theme.SPACE[3], theme.SPACE[3])
    outer.setSpacing(theme.SPACE[2])
    heading = QLabel(title)
    theme.set_role(heading, "section")
    outer.addWidget(heading)
    form = QFormLayout()
    form.setContentsMargins(0, 0, 0, 0)
    form.setHorizontalSpacing(theme.SPACE[3])
    form.setVerticalSpacing(theme.SPACE[2])
    form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
    outer.addLayout(form)
    return card, form


def form_label(text: str) -> QLabel:
    """A form row's label: muted, and one width for every card of the page."""
    label = muted(text)
    label.setMinimumWidth(FORM_LABEL_WIDTH)
    return label


def row(*widgets: QWidget, stretch_at_end: bool = False, spacing: int | None = None) -> QWidget:
    """Widgets side by side, as one widget a form row can hold."""
    holder = QWidget()
    layout = QHBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(theme.SPACE[1] if spacing is None else spacing)
    for widget in widgets:
        layout.addWidget(widget)
    if stretch_at_end:
        layout.addStretch(1)
    return holder


def hours_spin(limits: tuple[int, int], *, special: str | None = None) -> QSpinBox:
    """A whole-hours box whose suffix follows the number ("1 ora", "2 ore").

    ``limits`` are the core's ``REPEAT_*_RANGE``; ``special`` is shown instead
    of the minimum value, which is how the retry window says "nessuna
    ripetizione" rather than a bare 0.
    """
    spin = QSpinBox()
    spin.setRange(*limits)
    if special is not None:
        spin.setSpecialValueText(special)

    def follow(value: int) -> None:
        spin.setSuffix(strings.SETTINGS_SCHEDULE_HOUR_ONE if value == 1
                       else strings.SETTINGS_SCHEDULE_HOURS)

    spin.valueChanged.connect(follow)
    follow(spin.value())
    return spin
