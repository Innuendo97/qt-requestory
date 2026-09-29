"""Commands of the case view (a mixin of ``CaseView``; spec §5.2, §7.1, ruling R45).

* **"⋯" → "Azzera tolleranze…"** in the case bar: emits
  ``reset_tolerances_requested``; the page asks (the manual tolerances and
  the «non è una variabile» corrections of this case go, no undo), calls
  ``OfficinaApi.reset_tolerances`` and judges the version again.
* **"⋯" → "Cambia chiamata…"** (task A1): emits ``change_call_requested``;
  the page opens "Aggiungi chiamata…" on this case (replacing is the default).
* **The call chip** (a strip before phase 2.5, U2): after "Cambia chiamata…"
  the AS-IS was made with the previous call (:func:`asis_predates_call`); a
  warn chip "AS-IS da rigenerare" in the bar says so (the whole sentence as
  its tooltip), and a click on it emits ``asis_after_call_requested``.
* **"Mostra fatte"**, a checkable toggle next to the list's tabs: the fatte
  are drawn on the target side (a thin ``ok`` underline, the viewer's
  ``set_show_done``) and in the minimap. Opening the *Fatte* tab turns it on.

Split from ``officina_case`` (size).
"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtWidgets import QToolButton

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import CALL_REPLACED_KIND, Case

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
    """Needs ``diffs``, ``left``, ``right``, the bar's ``change_call_action``,
    ``reset_tolerances_action`` and ``call_strip`` (a ``Chip``), and the
    signals ``reset_tolerances_requested``, ``change_call_requested`` and
    ``asis_after_call_requested``."""

    def _init_extras(self) -> None:
        self.change_call_action.triggered.connect(lambda _checked=False: self.change_call_requested.emit())
        self.reset_tolerances_action.triggered.connect(
            lambda _checked=False: self.reset_tolerances_requested.emit())
        self.call_strip.clicked.connect(lambda _checked=False: self.asis_after_call_requested.emit())

        self.done_button = QToolButton()
        self.done_button.setText(strings.ELENCO_SHOW_DONE)
        self.done_button.setToolTip(strings.ELENCO_SHOW_DONE_TIP)
        self.done_button.setCheckable(True)
        self.done_button.setAutoRaise(True)
        theme.set_role(self.done_button, "stripButton")
        self.done_button.toggled.connect(self._show_done)
        self.diffs.footer.add_tool(self.done_button)  # at the bottom of the panel, beside «?»
        self.diffs.tab_buttons["fatte"].clicked.connect(lambda _c=False: self.done_button.setChecked(True))

    def show_call_strip(self, case: Case | None) -> None:
        """The warn chip of an AS-IS older than the case's call (hidden otherwise)."""
        stale = asis_predates_call(case)
        self.call_strip.set_message(strings.CHIAMATA_STALE_ASIS if stale else "", strings.BARRA_STALE_ASIS)

    def _sync_extras(self, readable: bool, generating: bool) -> None:
        """``readable``: the case can be written; ``generating``: it can be sent."""
        self.change_call_action.setEnabled(readable)
        self.call_strip.setEnabled(generating)

    def _show_done(self, on: bool) -> None:
        self.done_button.setText(strings.ELENCO_SHOW_DONE_ON if on else strings.ELENCO_SHOW_DONE)
        for side in (self.left, self.right):
            side.view.set_show_done(on)
