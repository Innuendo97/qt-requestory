"""The compact case bar (phase 2.5, U2: spec §5, decision D15, draft "f25-caso-v2").

ONE bar of :data:`BAR_HEIGHT` px over the documents, in place of the title
row, the button row, the progress row and the strips of phase 2::

    ‹ MOD_TEST_A · abilitato  [AS-IS|v1|v2] (= AS-IS)  60% ▲1 ○3 ✓2 … (chips)   [Rigenera (F5)] [Filtri (6)] [⋯]

* ``‹`` back to the board (the initiative in its tooltip); the case's name
  (key · variant, elided in the middle; the generator in its tooltip);
  "accettato" when accepted;
* the version switch (``officina_docside.VersionSwitch``; the AS-IS segment
  explains "prima delle modifiche" in its tooltip) and the chip "= AS-IS"
  when the version shown has the same text as the AS-IS (:func:`same_as_asis`);
* the compact progress (``officina_progress.ProgressBar``);
* small chips instead of the strips — the verification outcome (in the
  progress), an AS-IS made with the previous call (click: "Rigenera AS-IS"),
  a failed generation, the case's loading notes — each with its whole
  message as tooltip; "Generazione su svil…" while a send runs;
* "Rigenera (F5)" (primary), "Filtri (n)" ("Filtri del confronto", U4: the
  case's noise rules live there now, under "Regole avanzate") and "⋯" with
  the rest: Rigenera / Genera AS-IS, Target…, Payload e header…, Cambia
  chiamata…, Profilo ▸, Azzera tolleranze…, Annulla i segni, Segna
  accettato / Riapri.

Every command stays reachable by keyboard: Tab reaches the buttons, the "⋯"
menu opens with Space/Enter, F5 regenerates. The bar owns its widgets; the
case view wires them to its signals.
"""
from __future__ import annotations

from collections import Counter

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QWidget,
)

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import CaseComparison
from qtrequestory.ui.pages.officina_banners import ProfileMenu
from qtrequestory.ui.pages.officina_progress import ProgressBar
from qtrequestory.ui.pages.officina_widgets import MiddleElidedLabel, pill

__all__ = ["BAR_HEIGHT", "CaseBar", "Chip", "filtered_count", "same_as_asis"]

#: The bar's height (spec §5), in logical px.
BAR_HEIGHT = 36


def same_as_asis(cc: CaseComparison | None) -> bool:
    """The TO-BE of ``cc`` reads as its AS-IS: both have text and they
    differ from the target in exactly the same counted places, with the same
    words (op, class, target text, generated text) — so nothing was
    published yet. Variables and noise are left out (a date may change
    between two generations). False without an AS-IS or without differences."""
    if cc is None or cc.asis is None:
        return False
    tobe, asis = cc.tobe, cc.asis
    if not (tobe.left_has_text and tobe.right_has_text and asis.left_has_text and asis.right_has_text):
        return False

    def words(comparison) -> Counter:
        return Counter((d.op, d.klass, d.left_text, d.right_text) for d in comparison.counting(cc.profile))

    counted = words(tobe)
    return bool(counted) and counted == words(asis) and tobe.right_pages == asis.right_pages


def filtered_count(cc: CaseComparison | None) -> int | None:
    """How many occurrences the active filters set aside in ``cc`` (None:
    no panel came with the comparison)."""
    panel = cc.filters if cc is not None else None
    if panel is None:
        return None
    return sum(g.n for g in panel.groups if g.attivo)


class Chip(QToolButton):
    """A small rounded chip of the bar (the ``barChip`` QSS tone): a short
    text, the whole message as tooltip, hidden without a message. A
    ``clickable`` chip takes the focus and emits ``clicked``."""

    def __init__(self, tone: str, *, clickable: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("barChip", tone)
        self.setProperty("clickable", clickable)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus if clickable else Qt.FocusPolicy.NoFocus)
        if clickable:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._message = ""
        theme.repolish(self)
        self.setVisible(False)

    def set_message(self, message: str, short: str, tone: str | None = None) -> None:
        """``message`` ("" hides the chip) shown as ``short``."""
        if tone is not None and tone != self.property("barChip"):
            self.setProperty("barChip", tone)
            theme.repolish(self)
        self._message = message
        self.setText(short)
        self.setToolTip(message)
        self.setAccessibleName(message)  # the short text alone says too little
        self.setVisible(bool(message))

    def message(self) -> str:
        """The whole message on show ("" while hidden)."""
        return self._message if not self.isHidden() else ""


class CaseBar(QFrame):
    """The widgets of the bar and the "⋯" menu; the case view connects them.
    ``switch`` and ``view_switch`` (Documenti | DOM) are the case view's."""

    def __init__(self, switch: QWidget, view_switch: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("caseBar")
        self.setFixedHeight(BAR_HEIGHT)
        self.back_button = QToolButton()
        self.back_button.setText("‹")
        theme.set_role(self.back_button, "barBack")
        self.title = MiddleElidedLabel()
        theme.set_role(self.title, "section")
        self.title.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.status = pill(strings.OFFICINA_STATUS_ACCEPTED, "ok")
        self.status.setVisible(False)
        self.switch = switch
        self.same_chip = Chip("warn")
        self.progress = ProgressBar()
        self.call_chip = Chip("warn", clickable=True)
        self.notice_chip = Chip("warn")
        self.failure_chip = Chip("bad")
        self.busy = QLabel()
        theme.set_role(self.busy, "muted")
        self.busy.setVisible(False)
        self.view_switch = view_switch
        self.regenerate_button = QPushButton(strings.BARRA_REGENERATE)
        theme.set_role(self.regenerate_button, "primary")
        self.filters_button = QPushButton(strings.BARRA_FILTERS)
        self.filters_button.setToolTip(strings.BARRA_FILTERS_TIP)
        self.filters_button.setAccessibleName(strings.BARRA_FILTERS)
        self.filters_button.setAccessibleDescription(strings.BARRA_FILTERS_TIP)
        self.more_button = QToolButton()
        self.more_button.setText(strings.CASO_MORE)
        self.more_button.setToolTip(strings.CASO_MORE_TIP)
        self.more_button.setAccessibleName(strings.BARRA_MORE_NAME)
        self.more_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        theme.set_role(self.more_button, "menuButton")
        self._build_menu()
        self._build()

    def _build_menu(self) -> None:
        menu = QMenu(self.more_button)
        menu.setToolTipsVisible(True)

        def add(text: str, tip: str = "") -> QAction:
            action = QAction(text, menu)
            action.setToolTip(tip or text)
            menu.addAction(action)
            return action

        self.asis_action = add(strings.OFFICINA_GENERATE_ASIS, strings.BARRA_ASIS_TIP)
        self.target_action = add(strings.OFFICINA_CHOOSE_TARGET)
        self.editor_action = add(strings.OFFICINA_PAYLOAD_HEADERS)
        self.change_call_action = add(strings.CHIAMATA_CHANGE, strings.CHIAMATA_CHANGE_TIP)
        menu.addSeparator()
        self.profile_menu = ProfileMenu(menu)
        menu.addMenu(self.profile_menu)
        self.reset_tolerances_action = add(strings.CASO_RESET_TOLERANCES, strings.CASO_RESET_TOLERANCES_TIP)
        self.unmark_action = add(strings.BARRA_UNMARK_ALL, strings.REVISIONE_UNMARK_ALL_TIP)
        menu.addSeparator()
        self.accept_action = add(strings.OFFICINA_MARK_ACCEPTED)
        self.more_button.setMenu(menu)

    def _build(self) -> None:
        row = QHBoxLayout(self)
        row.setContentsMargins(theme.SPACE[1], 0, theme.SPACE[1], 0)
        row.setSpacing(theme.SPACE[1])

        def add(widget: QWidget) -> None:
            row.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)  # never stretched to 36 px

        for widget in (self.back_button, self.title, self.status, self.switch, self.same_chip):
            add(widget)
        row.addSpacing(theme.SPACE[0])
        for widget in (self.progress, self.call_chip, self.notice_chip, self.failure_chip, self.busy):
            add(widget)
        row.addStretch(1)
        for widget in (self.view_switch, self.regenerate_button, self.filters_button, self.more_button):
            add(widget)

    def set_filters(self, n: int | None) -> None:
        """"Filtri (n)" — ``n`` occurrences set aside; None: just "Filtri"."""
        text = strings.BARRA_FILTERS if n is None else strings.BARRA_FILTERS_N.format(n=n)
        self.filters_button.setText(text)
        self.filters_button.setAccessibleName(text)

    def set_back(self, initiative: str) -> None:
        """The bare "‹": its tooltip and its accessible name name the initiative."""
        self.back_button.setToolTip(strings.BARRA_BACK_TIP.format(initiative=initiative))
        self.back_button.setAccessibleName(strings.BARRA_BACK_NAME.format(initiative=initiative))

    def set_same_as_asis(self, version: str | None, env: str) -> None:
        """The "= AS-IS" chip for ``version`` ("v1"), or hidden (None)."""
        if version is None:
            self.same_chip.set_message("", "")
            return
        tip = (strings.BARRA_SAME_AS_ASIS_TIP.format(version=version, env=env) if env
               else strings.BARRA_SAME_AS_ASIS_TIP_NO_ENV.format(version=version))
        self.same_chip.set_message(tip, strings.BARRA_SAME_AS_ASIS)
