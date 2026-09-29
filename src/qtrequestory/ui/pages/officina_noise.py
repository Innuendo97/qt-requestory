"""The board's "Regole di rumore…" dialog (spec §4.2 step 5, §7.5; ruling
F14): the editor of the initiative's OWN regex rules
(``officina_noise_editor``: names and patterns, live counts), "Salva e
riconfronta" and "Annulla". No presets and no switches here: whether a
preset or a rule applies — for a case, or as the initiative's default — is
set in "Filtri del confronto" (``officina_filters``), whose "Regole
avanzate" hosts the same editor for the case's own rules.
"""
from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QHBoxLayout, QVBoxLayout, QWidget

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import NoiseRule
from qtrequestory.ui.pages.officina_noise_editor import DEBOUNCE_MS, SPINNER, Counter, NoiseRulesEditor, hits_text

__all__ = ["DEBOUNCE_MS", "SPINNER", "NoiseDialog", "hits_text"]


class NoiseDialog(QDialog):
    """The editor and its buttons; "Salva" is enabled while every rule can
    be saved. The editor's API (``rules``, ``own``, ``add_rule``,
    ``hits_shown``…) is reachable on the dialog itself."""

    def __init__(self, title: str, own: Sequence[NoiseRule], *, own_title: str,
                 presets: Sequence[NoiseRule] = (), inherited: Sequence[NoiseRule] = (),
                 reserved: dict[str, str] | None = None, counter: Counter | None = None,
                 counts_note: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.editor = NoiseRulesEditor(own, own_title=own_title, presets=presets, inherited=inherited,
                                       reserved=reserved, counter=counter, counts_note=counts_note)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                        | QDialogButtonBox.StandardButton.Cancel)
        self.ok_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_button.setText(strings.RUMORE_OK)
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(strings.BTN_CANCEL)
        layout = QVBoxLayout(self)
        layout.setSpacing(theme.SPACE[1])
        layout.addWidget(self.editor, 1)
        foot = QHBoxLayout()
        foot.addStretch(1)
        foot.addWidget(self.buttons)
        layout.addLayout(foot)
        self.ok_button.setEnabled(self.editor.is_valid())
        self.editor.validity_changed.connect(self.ok_button.setEnabled)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.finished.connect(self.editor.release)
        self.setMinimumSize(720, 460)

    def __getattr__(self, name: str):
        """The editor's attributes and methods, on the dialog (its tests and the page)."""
        editor = self.__dict__.get("editor")
        if editor is None:
            raise AttributeError(name)
        return getattr(editor, name)
