"""The replace-or-new question of "Aggiungi chiamata…" (decision U2).

A chosen call whose template key already has a case in the initiative:
"Sostituisci la chiamata di <case>" (one choice per such case — keeps target
and versions, keeps the old payload, the AS-IS is to be regenerated) or
"Crea un nuovo caso" with a variant. The window opened from inside a case
defaults to replacing that case; elsewhere the default is a new case. A call
whose key was already chosen for a new case in the same run is asked about
too (``taken``: the variants already planned), with the new case only.

:func:`ask_resolution` is the one entry point (the tests replace it: a modal
cannot be answered offscreen).
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import Case, SearchHit
from qtrequestory.ui.pages.officina_format import case_title

__all__ = ["ReplaceOrNewDialog", "Resolution", "ask_resolution", "free_variant"]


def free_variant(variant: str, hit: SearchHit, taken: set[str]) -> str:
    """``variant`` when free, else one made from the call's short FDI
    ("1a2b3c4d", "abilitato-1a2b3c4d", then "-2", "-3"…): "Crea un nuovo caso"
    is one Enter away (``taken`` holds casefolded variants)."""
    variant = variant.strip()
    if variant.casefold() not in taken:
        return variant
    short = (hit.fdi or "")[:8] or "nuovo"
    base = f"{variant}-{short}" if variant else short
    candidate, n = base, 1
    while candidate.casefold() in taken:
        n += 1
        candidate = f"{base}-{n}"
    return candidate


@dataclass(frozen=True)
class Resolution:
    """``replace`` = the id of the case whose call is replaced; None = a new
    case with ``variant``."""

    replace: str | None
    variant: str = ""


class ReplaceOrNewDialog(QDialog):
    """One radio per case of the key, then "Crea un nuovo caso" + variant."""

    def __init__(self, hit: SearchHit, cases: Sequence[Case], *, initiative: str,
                 default_replace: str | None = None, variant: str = "", taken: Sequence[str] = (),
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(strings.CHIAMATA_ASK_TITLE)
        self._cases = list(cases)
        self._taken = {v.strip().casefold() for v in (*taken, *(c.variant for c in self._cases))}
        wording = strings.CHIAMATA_ASK_TEXT if self._cases else strings.CHIAMATA_ASK_TEXT_SAME_RUN
        text = QLabel(wording.format(fdi=(hit.fdi or "")[:8] or "—", key=hit.template_key,
                                     initiative=initiative))
        text.setWordWrap(True)
        self.group = QButtonGroup(self)
        self.replace_buttons: dict[str, QRadioButton] = {}
        layout = QVBoxLayout(self)
        layout.addWidget(text)
        for case in self._cases:
            button = QRadioButton(strings.CHIAMATA_ASK_REPLACE.format(case=case_title(case)))
            self.group.addButton(button)
            self.replace_buttons[case.id] = button
            layout.addWidget(button)
        if self._cases:
            hint = QLabel(strings.CHIAMATA_ASK_REPLACE_HINT)
            hint.setWordWrap(True)
            theme.set_role(hint, "muted")
            layout.addWidget(hint)
        self.new_button = QRadioButton(strings.CHIAMATA_ASK_NEW)
        self.group.addButton(self.new_button)
        layout.addWidget(self.new_button)
        row = QHBoxLayout()
        row.addSpacing(theme.SPACE[3])
        row.addWidget(QLabel(strings.CHIAMATA_ASK_VARIANT))
        self.variant = QLineEdit(free_variant(variant, hit, self._taken))
        self.variant.setPlaceholderText(strings.OFFICINA_ADD_VARIANT_HINT)
        row.addWidget(self.variant, 1)
        layout.addLayout(row)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setProperty("dot", "bad")
        self.error.setVisible(False)
        layout.addWidget(self.error)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.button(QDialogButtonBox.StandardButton.Ok).setText(strings.CHIAMATA_ASK_CONTINUE)
        box.button(QDialogButtonBox.StandardButton.Cancel).setText(strings.BTN_CANCEL)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout.addWidget(box)
        self.setMinimumWidth(520)

        chosen = self.replace_buttons.get(default_replace or "", self.new_button)
        chosen.setChecked(True)
        self.group.buttonToggled.connect(lambda *_a: self._sync())
        self._sync()
        theme.repolish(self.error)

    def resolution(self) -> Resolution | None:
        """The answer, or None (the reason is shown in the dialog)."""
        problem = self.problem()
        self.error.setText(problem)
        self.error.setVisible(bool(problem))
        if problem:
            return None
        for case_id, button in self.replace_buttons.items():
            if button.isChecked():
                return Resolution(case_id)
        return Resolution(None, self.variant.text().strip())

    def problem(self) -> str:
        if not self.new_button.isChecked():
            return ""
        if self.variant.text().strip().casefold() in self._taken:
            return strings.CHIAMATA_ASK_NEED_VARIANT
        return ""

    def accept(self) -> None:  # noqa: D102 - validate before closing
        if self.resolution() is not None:
            super().accept()

    def _sync(self) -> None:
        creating = self.new_button.isChecked()
        self.variant.setEnabled(creating)
        if creating:
            self.variant.setFocus()


def ask_resolution(parent: QWidget | None, hit: SearchHit, cases: Sequence[Case], *,
                   initiative: str, default_replace: str | None = None,
                   variant: str = "", taken: Sequence[str] = ()) -> Resolution | None:
    """Show :class:`ReplaceOrNewDialog`; the answer, or None when cancelled."""
    dialog = ReplaceOrNewDialog(hit, cases, initiative=initiative, default_replace=default_replace,
                                variant=variant, taken=taken, parent=parent)
    try:
        return dialog.resolution() if dialog.exec() == QDialog.DialogCode.Accepted else None
    finally:
        dialog.deleteLater()
