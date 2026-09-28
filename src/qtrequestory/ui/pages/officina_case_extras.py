"""Two commands of the case view (a mixin of ``CaseView``; spec §5.2, §7.1, ruling R45).

* **"⋯" → "Azzera tolleranze…"** in the header: emits
  ``reset_tolerances_requested``; the page asks (the manual tolerances and
  the «non è una variabile» corrections of this case go, no undo), calls
  ``OfficinaApi.reset_tolerances`` and judges the version again.
* **"⋯" → "Cambia chiamata…"** (task A1): emits ``change_call_requested``;
  the page opens "Aggiungi chiamata…" on this case (replacing is the default).
* **The call strip**: after "Cambia chiamata…" the AS-IS was made with the
  previous call (:func:`asis_predates_call`); a warn strip says so, and its
  "Rigenera AS-IS" emits ``asis_after_call_requested``.
* **"Mostra fatte"**, a checkable toggle next to the list's tabs: the fatte
  are drawn on the target side (a thin ``ok`` underline, the viewer's
  ``set_show_done``) and in the minimap. Opening the *Fatte* tab turns it on.

Split from ``officina_case`` (size).
"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QToolButton

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import CALL_REPLACED_KIND, Case
from qtrequestory.ui.pages.officina_banners import Strip

__all__ = ["CaseExtrasMixin", "asis_predates_call"]


def asis_predates_call(case: Case | None) -> bool:
    """True when the case's AS-IS was generated before its call was last
    replaced (the latest ``caso.json`` history entry of that kind)."""
    asis = case.asis() if case is not None else None
    if asis is None or asis.missing:
        return False
    for entry in reversed(case.history):
        if isinstance(entry, dict) and entry.get("kind") == CALL_REPLACED_KIND:
            try:
                return datetime.fromisoformat(str(entry.get("at"))) > asis.created
            except (TypeError, ValueError):
                return False
    return False


class CaseExtrasMixin:
    """Needs ``diffs``, ``left``, ``right``, ``reset_tolerances_requested``,
    ``change_call_requested`` and ``asis_after_call_requested``."""

    def _init_extras(self) -> None:
        self.more_button = QToolButton()
        self.more_button.setText(strings.CASO_MORE)
        self.more_button.setToolTip(strings.CASO_MORE_TIP)
        self.more_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        theme.set_role(self.more_button, "menuButton")
        menu = QMenu(self.more_button)
        self.change_call_action = QAction(strings.CHIAMATA_CHANGE, menu)
        self.change_call_action.setToolTip(strings.CHIAMATA_CHANGE_TIP)
        self.change_call_action.triggered.connect(lambda _checked=False: self.change_call_requested.emit())
        menu.addAction(self.change_call_action)
        self.reset_tolerances_action = QAction(strings.CASO_RESET_TOLERANCES, menu)
        self.reset_tolerances_action.setToolTip(strings.CASO_RESET_TOLERANCES_TIP)
        self.reset_tolerances_action.triggered.connect(
            lambda _checked=False: self.reset_tolerances_requested.emit())
        menu.addAction(self.reset_tolerances_action)
        self.more_button.setMenu(menu)
        menu.setToolTipsVisible(True)
        self.call_strip = Strip("warn", strings.CHIAMATA_REGENERATE_ASIS)
        self.call_strip.button.clicked.connect(lambda _checked=False: self.asis_after_call_requested.emit())

        self.done_button = QToolButton()
        self.done_button.setText(strings.ELENCO_SHOW_DONE)
        self.done_button.setToolTip(strings.ELENCO_SHOW_DONE_TIP)
        self.done_button.setCheckable(True)
        self.done_button.setAutoRaise(True)
        theme.set_role(self.done_button, "stripButton")
        self.done_button.toggled.connect(self._show_done)
        grid = self.diffs.tabs.layout()  # a row of its own under the tabs: they keep their width
        grid.addWidget(self.done_button, grid.rowCount(), 0, 1, grid.columnCount(), Qt.AlignmentFlag.AlignLeft)
        self.diffs.tab_buttons["fatte"].clicked.connect(lambda _c=False: self.done_button.setChecked(True))

    def show_call_strip(self, case: Case | None) -> None:
        """The warn strip of an AS-IS older than the case's call ("" hides it)."""
        self.call_strip.set_text(strings.CHIAMATA_STALE_ASIS if asis_predates_call(case) else "")

    def _sync_extras(self, readable: bool, generating: bool) -> None:
        """``readable``: the case can be written; ``generating``: it can be sent."""
        self.change_call_action.setEnabled(readable)
        self.call_strip.button.setEnabled(generating)

    def _show_done(self, on: bool) -> None:
        self.done_button.setText(strings.ELENCO_SHOW_DONE_ON if on else strings.ELENCO_SHOW_DONE)
        for side in (self.left, self.right):
            side.view.set_show_done(on)
