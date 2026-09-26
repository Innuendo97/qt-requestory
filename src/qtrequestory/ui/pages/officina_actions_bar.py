"""The actions on a difference, from the documents (spec §7.3, D10; approved
draft "caso-fase2" v2):

* **clic** on a highlight: it is selected (list and both viewers) and a
  floating **mini-bar** opens under it — ``✓ Fatta F · ⊘ Tollera T · ⋯`` —
  always inside the viewer's viewport (above the highlight when there is no
  room below, pushed in from the page edge), following scroll and zoom;
* **doppio clic**: segna fatta / toglie il segno (nothing on a difference
  that does not count: a variable, noise, a tolerated or done one);
* **clic destro** (or ``⋯``): the menu Fatta · Tollera… · Non è una
  variabile · Copia testo del target · Copia testo generato;
* **F / T / V** in the viewer act on the selected difference like in the list;
* "Tollera…" asks an optional note (:class:`TolerateDialog`); T and the
  bar's "Tollera" tolerate without one.

No long press (D10). The case view only turns input into signals
(``review_action_requested``, ``copy_requested``, ``action_unavailable``,
``undo_requested``); the page saves in a worker and shows the toast with
"Annulla" (``officina_review``). The bar is UI chrome over the page: it
follows the theme (the highlights under it keep the paper colours, R13).
"""
from __future__ import annotations

from functools import partial

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QAction, QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import Judged
from qtrequestory.ui.pages.officina_progress import GLYPH_FONT
from qtrequestory.ui.pages.officina_rows import actions_for

__all__ = ["GAP", "ActionsBar", "ReviewInputMixin", "ReviewMenu", "TolerateDialog", "place_bar"]

#: Space between the highlight and the bar, in pixels.
GAP = 4
#: The bar's shadow: blur and downward offset (px); the colour is the
#: ``shadow`` token at this alpha — stronger on the dark chrome, where a light
#: one does not show.
SHADOW_BLUR, SHADOW_DY = 14, 4
SHADOW_ALPHA = {"light": 46, "dark": 120}


def place_bar(anchor: QRect, size: QSize, area: QRect, gap: int = GAP) -> QPoint:
    """Top-left of a ``size`` bar for a highlight at ``anchor``: under it,
    left edges aligned; above it when it would overflow ``area``'s bottom;
    then pushed back inside ``area`` on every side."""
    w, h = size.width(), size.height()
    y = anchor.bottom() + 1 + gap
    if y + h > area.bottom() + 1:
        above = anchor.top() - gap - h
        y = above if above >= area.top() else area.bottom() + 1 - h
    x = max(area.left(), min(anchor.left(), area.right() + 1 - w))
    y = max(area.top(), min(y, area.bottom() + 1 - h))
    return QPoint(x, y)


def with_glyph_font(widget: QWidget) -> None:
    """Plain-text buttons and menu entries cannot carry a glyph span: the
    symbol font goes after the UI font instead, so ⊘ ↺ ✓ come from it (the
    UI font draws ⊘ as a tiny ring)."""
    font = widget.font()
    font.setFamilies([*font.families(), GLYPH_FONT])
    widget.setFont(font)


def tolerated_by_profile(j: Judged, by_hand: bool) -> bool:
    """Tolerated because the profile does not count its class: T cannot undo that."""
    return j.verdict == "tollerata" and not by_hand


class ActionsBar(QFrame):
    """The floating bar of one viewer (a child of the ``DocView``)."""

    action_chosen = Signal(int, str)     # (Diff.id, "fatta" | "tollera")
    more_requested = Signal(int, QPoint)  # (Diff.id, global point for the menu)

    def __init__(self, view) -> None:  # view: DocView
        super().__init__(view)
        self.setObjectName("actionsBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._view = view
        self.diff_id: int | None = None
        self._wanted = False
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)
        self.done_button = self._button("fatta")
        self.tolerate_button = self._button("tollera")
        self.more_button = self._button("more")
        self.more_button.setText(strings.AZIONI_BAR_MORE)
        self.more_button.setToolTip(strings.AZIONI_BAR_MORE_TIP)
        for button in (self.done_button, self.tolerate_button, self.more_button):
            layout.addWidget(button)
        self.done_button.clicked.connect(lambda: self._chosen("fatta"))
        self.tolerate_button.clicked.connect(lambda: self._chosen("tollera"))
        self.more_button.clicked.connect(self._on_more)
        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(SHADOW_BLUR)
        self._shadow.setOffset(0, SHADOW_DY)
        self.setGraphicsEffect(self._shadow)
        self._recolour()
        theme.signals.changed.connect(self._recolour)
        for button in (self.done_button, self.tolerate_button, self.more_button):
            with_glyph_font(button)
        view.verticalScrollBar().valueChanged.connect(self.reposition)
        view.horizontalScrollBar().valueChanged.connect(self.reposition)
        view.zoom_changed.connect(self.reposition)
        self._viewport = view.viewport()
        self._viewport.installEventFilter(self)
        self.hide()

    def _recolour(self, *_args) -> None:
        tokens = theme.tokens()
        colour = QColor(tokens.shadow)
        colour.setAlpha(SHADOW_ALPHA["dark" if tokens == theme.DARK else "light"])
        self._shadow.setColor(colour)

    @staticmethod
    def _button(kind: str) -> QToolButton:
        button = QToolButton()
        button.setProperty("barAction", kind)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setAutoRaise(True)
        return button

    def show_for(self, j: Judged, *, tolerated_by_hand: bool) -> None:
        """Open under ``j``'s highlight with the actions that apply to it."""
        can = actions_for(j)
        self.diff_id = j.diff.id
        self.done_button.setVisible("fatta" in can)
        self.done_button.setText(strings.AZIONI_BAR_UNMARK if j.marked else strings.AZIONI_BAR_DONE)
        self.done_button.setToolTip(strings.AZIONI_BAR_UNMARK_TIP if j.marked
                                    else strings.AZIONI_BAR_DONE_TIP)
        tolerated = j.verdict == "tollerata"
        self.tolerate_button.setVisible("tollera" in can
                                        and not tolerated_by_profile(j, tolerated_by_hand))
        self.tolerate_button.setText(strings.AZIONI_BAR_UNTOLERATE if tolerated
                                     else strings.AZIONI_BAR_TOLERATE)
        self.tolerate_button.setToolTip(strings.AZIONI_BAR_UNTOLERATE_TIP if tolerated
                                        else strings.AZIONI_BAR_TOLERATE_TIP)
        self.layout().activate()
        self.resize(self.sizeHint())
        self._wanted = True
        self.reposition()

    def dismiss(self) -> None:
        self._wanted = False
        self.diff_id = None
        self.hide()

    def reposition(self, *_args) -> None:
        """Under the highlight, inside the viewport; hidden while the
        highlight is scrolled out of sight (back when it returns)."""
        if not self._wanted or self.diff_id is None:
            return
        rect = self._view.difference_rect(self.diff_id)
        viewport = self._view.viewport()
        area = viewport.geometry()
        anchor = self._view.mapFromScene(rect).boundingRect().translated(area.topLeft())
        if rect.isNull() or not anchor.intersects(area):
            self.hide()
            return
        self.move(place_bar(anchor, self.size(), area))
        self.show()
        self.raise_()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt naming
        if event.type() == QEvent.Type.Resize and watched is self._viewport:
            self.reposition()
        return False

    def _chosen(self, kind: str) -> None:
        if self.diff_id is not None:
            self.action_chosen.emit(self.diff_id, kind)

    def _on_more(self) -> None:
        if self.diff_id is not None:
            self.more_requested.emit(self.diff_id,
                                     self.more_button.mapToGlobal(self.more_button.rect().bottomLeft()))


class ReviewMenu(QMenu):
    """The right-click menu of one difference; entries that do not apply are disabled."""

    chosen = Signal(int, str)  # (Diff.id, "fatta" | "tollera" | "tollera_nota" | "non_variabile"
    #                            | "copia_target" | "copia_generato")

    def __init__(self, j: Judged, *, tolerated_by_hand: bool, not_variable: bool,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        with_glyph_font(self)
        can = actions_for(j)
        self._actions: dict[str, QAction] = {}
        self._add("fatta", strings.AZIONI_MENU_UNMARK if j.marked else strings.AZIONI_MENU_DONE,
                  j, "fatta" in can)
        untolerate = j.verdict == "tollerata" and tolerated_by_hand
        tolerate = self._add("tollera" if untolerate else "tollera_nota",
                             strings.AZIONI_MENU_UNTOLERATE if untolerate else strings.AZIONI_MENU_TOLERATE,
                             j, "tollera" in can and not tolerated_by_profile(j, tolerated_by_hand))
        self._actions["tollera_nota" if untolerate else "tollera"] = tolerate
        self._add("non_variabile", strings.AZIONI_MENU_VARIABLE_AGAIN if not_variable
                  else strings.AZIONI_MENU_NOT_VARIABLE, j, "non_variabile" in can)
        self.addSeparator()
        self._add("copia_target", strings.AZIONI_MENU_COPY_TARGET, j, bool(j.diff.left_text))
        self._add("copia_generato", strings.AZIONI_MENU_COPY_GENERATED, j, bool(j.diff.right_text))

    def _add(self, kind: str, text: str, j: Judged, enabled: bool) -> QAction:
        action = self.addAction(text)
        action.setEnabled(enabled)
        action.triggered.connect(partial(self.chosen.emit, j.diff.id, kind))
        self._actions[kind] = action
        return action

    def action_for(self, kind: str) -> QAction:
        return self._actions[kind]


class TolerateDialog(QDialog):
    """"Tollera…": the difference and an optional one-line note."""

    def __init__(self, what: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(strings.AZIONI_NOTE_TITLE)
        text = QLabel(strings.AZIONI_NOTE_TEXT.format(what=what))
        text.setWordWrap(True)
        label = QLabel(strings.AZIONI_NOTE_LABEL)
        theme.set_role(label, "muted")
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(strings.AZIONI_NOTE_PLACEHOLDER)
        label.setBuddy(self.edit)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(strings.AZIONI_NOTE_OK)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(strings.BTN_CANCEL)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.setSpacing(theme.SPACE[1])
        layout.addWidget(text)
        layout.addSpacing(theme.SPACE[0])
        layout.addWidget(label)
        layout.addWidget(self.edit)
        layout.addSpacing(theme.SPACE[1])
        layout.addWidget(buttons)
        self.setMinimumWidth(380)

    def note(self) -> str:
        return " ".join(self.edit.text().split())


class ReviewInputMixin:
    """The half of ``CaseView`` that turns clicks, keys and menus on the
    documents into review signals. Needs ``left``/``right`` (DocSide),
    ``diffs`` (DiffPanel), ``docs``, ``case`` and the signals
    ``review_action_requested``, ``copy_requested``, ``action_unavailable``,
    ``undo_requested``."""

    def _init_review_input(self) -> None:
        #: A review action of this case is being saved: the others wait.
        self.acting = False
        self.menu: ReviewMenu | None = None
        self.bars = {"left": ActionsBar(self.left.view), "right": ActionsBar(self.right.view)}
        self.undo_shortcut = QShortcut(QKeySequence(QKeySequence.StandardKey.Undo), self)
        self.undo_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.undo_shortcut.activated.connect(self.undo_requested)
        for name, side in (("left", self.left), ("right", self.right)):
            view, bar = side.view, self.bars[name]
            view.difference_clicked.connect(partial(self._show_bar, name))
            view.difference_double_clicked.connect(self._on_double_click)
            view.difference_menu.connect(self.open_review_menu)
            view.key_action.connect(self._on_viewer_key)
            view.blank_clicked.connect(self.hide_bars)
            bar.action_chosen.connect(self._on_bar_action)
            bar.more_requested.connect(self.open_review_menu)
        self.diffs.action_unavailable.connect(self.action_unavailable)
        self.diffs.refuses = lambda j, action: (
            action == "tollera" and tolerated_by_profile(j, self._by_hand(j)))

    def judged_by_id(self, diff_id: int) -> Judged | None:
        cc = self.docs.judged if self.docs is not None else None
        return next((j for j in cc.judged if j.diff.id == diff_id), None) if cc is not None else None

    def set_acting(self, acting: bool) -> None:
        """A review action of the case on screen is being saved / is over."""
        self.acting = acting
        self.refresh_run_state()

    def hide_bars(self) -> None:
        for bar in self.bars.values():
            bar.dismiss()

    def open_review_menu(self, diff_id: int, at: QPoint) -> None:
        j = self.judged_by_id(diff_id)
        if j is None:
            return
        if self.menu is not None:
            self.menu.hide()
            self.menu.deleteLater()
        self.menu = ReviewMenu(j, tolerated_by_hand=self._by_hand(j),
                               not_variable=self._not_variable(j), parent=self)
        self.menu.chosen.connect(self._on_menu_choice)
        self.menu.popup(at)

    def _show_bar(self, side: str, diff_id: int) -> None:
        for name, bar in self.bars.items():
            if name != side:
                bar.dismiss()
        j = self.judged_by_id(diff_id)
        if j is None:  # the AS-IS view or no verdict: nothing to act on
            self.bars[side].dismiss()
            return
        self.bars[side].show_for(j, tolerated_by_hand=self._by_hand(j))

    def _on_viewer_key(self, action: str) -> None:
        """F / T / V in a viewer: like the list's (the selection moves on, R40)."""
        self.hide_bars()
        self.diffs.trigger(action)

    def _on_bar_action(self, diff_id: int, kind: str) -> None:
        """The bar's Fatta / Tollera act like F / T: then the next row (R40)."""
        self.hide_bars()
        self.review_action_requested.emit(diff_id, kind)
        if self.diffs.current_id() == diff_id:
            self.diffs.advance()

    def _on_double_click(self, diff_id: int) -> None:
        """Segna fatta / toglie il segno; silent on a difference that does not count."""
        j = self.judged_by_id(diff_id)
        if j is not None and "fatta" in actions_for(j):
            self.review_action_requested.emit(diff_id, "fatta")

    def _on_menu_choice(self, diff_id: int, kind: str) -> None:
        if kind in ("copia_target", "copia_generato"):
            self.copy_requested.emit(diff_id, "left" if kind == "copia_target" else "right")
        else:
            self.review_action_requested.emit(diff_id, kind)

    def _by_hand(self, j: Judged) -> bool:
        review = self.case.review if self.case is not None else None
        return review is not None and any(t.anchor == j.diff.anchor for t in review.tolerances)

    def _not_variable(self, j: Judged) -> bool:
        review = self.case.review if self.case is not None else None
        return review is not None and any(a == j.diff.anchor for a, _w in review.not_variables)
