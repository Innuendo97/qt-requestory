"""Two commands of the case view (a mixin of ``CaseView``; spec §5.2, §7.1, ruling R45).

* **"⋯" → "Azzera tolleranze…"** in the header: emits
  ``reset_tolerances_requested``; the page asks (the manual tolerances and
  the «non è una variabile» corrections of this case go, no undo), calls
  ``OfficinaApi.reset_tolerances`` and judges the version again.
* **"Mostra fatte"**, a checkable toggle next to the list's tabs: the fatte
  are drawn on the target side (a thin ``ok`` underline, the viewer's
  ``set_show_done``) and in the minimap. Opening the *Fatte* tab turns it on.

Split from ``officina_case`` (size).
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QToolButton

from qtrequestory.ui import strings, theme

__all__ = ["CaseExtrasMixin"]


class CaseExtrasMixin:
    """Needs ``diffs``, ``left``, ``right`` and ``reset_tolerances_requested``."""

    def _init_extras(self) -> None:
        self.more_button = QToolButton()
        self.more_button.setText(strings.CASO_MORE)
        self.more_button.setToolTip(strings.CASO_MORE_TIP)
        self.more_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        theme.set_role(self.more_button, "menuButton")
        menu = QMenu(self.more_button)
        self.reset_tolerances_action = QAction(strings.CASO_RESET_TOLERANCES, menu)
        self.reset_tolerances_action.setToolTip(strings.CASO_RESET_TOLERANCES_TIP)
        self.reset_tolerances_action.triggered.connect(
            lambda _checked=False: self.reset_tolerances_requested.emit())
        menu.addAction(self.reset_tolerances_action)
        self.more_button.setMenu(menu)

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

    def _show_done(self, on: bool) -> None:
        self.done_button.setText(strings.ELENCO_SHOW_DONE_ON if on else strings.ELENCO_SHOW_DONE)
        for side in (self.left, self.right):
            side.view.set_show_done(on)
