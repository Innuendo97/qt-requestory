"""The "Filtri del confronto" dialog (phase 2.5, U4: spec §3.8, decisions D3,
D4, D9, D14; rulings F3, F4, F5, F7, F13). It replaces the case's "Regole di
rumore…" dialog: the ONE entry point is "Filtri (n)" on the case bar::

    Filtri del confronto — MOD_TEST_A
    Calcolati dal documento. Quel che è messo da parte non conta…   [ ] Usa per tutta l'iniziativa
    ZONE · 7
      ▸ Header                   0  [x] Conta
      ▾ Footer                   2  [x] Conta
          p. 1, 2 · Acme-Servizi S.p.A. …
      ▸ Numero di pagina         2  [ ] Conta
      ▸ Testo invisibile         3  solo informativo
    VARIABILI RICONOSCIUTE · 4       (Segnaposto, Buchi, Celle, Sezioni, Esecuzione, Listino: [x] Variabile)
    DA DECIDERE · 9                  (Solo maiuscole, Solo punteggiatura: [ ] Tollera tutte)
    [Regole avanzate ▸]              (the regex rules' rows + the editor of the case's own rules)
    Riconoscimento esteso in corso…                                                  [Chiudi]

The "Zone" heading counts the zone differences that COUNT (the side
panel's number); each row shows its own n, set aside or informational.
"Ripristina predefiniti" drops every own choice of the case (undoable).
Closing with unsaved rules in "Regole avanzate" asks Salva / Scarta /
Annulla (leaving the case: Salva / Scarta).

MODELESS: a switch applies at once — the page queues it like a review action
(``officina_review``, R38), saves it with ``set_filters`` and judges the
version on screen again, so the case view behind re-filters live, without
regenerating; the page then hands the dialog the new panel
(:meth:`FiltersDialog.show_panel`). "Usa per tutta l'iniziativa" makes each
next choice the initiative's default too. A click on an occurrence shows it
in the case view (by anchor, F5). The control generation's state is a
discreet line at the bottom (never an error, D14), looked at again every
:data:`CONTROL_POLL_MS` while it runs.
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import ControlState, FilterGroup, FilterPanel
from qtrequestory.ui.pages import officina_dialogs as ask
from qtrequestory.ui.pages.officina_filters_rows import FilterRow, change_text
from qtrequestory.ui.pages.officina_noise_editor import NoiseRulesEditor

__all__ = ["CONTROL_POLL_MS", "FiltersDialog", "control_text"]

#: How often the control generation's state is asked again while it runs.
CONTROL_POLL_MS = 2000

_SECTIONS = (
    ("zone", strings.FILTRI_SECTION_ZONE, strings.FILTRI_NOTE_ZONE),
    ("variabili", strings.FILTRI_SECTION_VARIABILI, strings.FILTRI_NOTE_VARIABILI),
    ("decidere", strings.FILTRI_SECTION_DECIDERE, strings.FILTRI_NOTE_DECIDERE),
    ("avanzate", "", strings.FILTRI_NOTE_AVANZATE),  # its heading is the "Regole avanzate" button
)
_CONTROL = {
    "assente": strings.FILTRI_CONTROL_ASSENTE,
    "in_corso": strings.FILTRI_CONTROL_IN_CORSO,
    "pronta": strings.FILTRI_CONTROL_PRONTA,
    "non_disponibile": strings.FILTRI_CONTROL_NON_DISPONIBILE,
}


def control_text(state: ControlState) -> str:
    """The discreet line of the control generation: its own ``nota`` when it
    has one (e.g. "riconoscimento esteso non disponibile per questo caso"),
    else the sentence of its state."""
    if state.nota:
        return state.nota[:1].upper() + state.nota[1:]
    return _CONTROL.get(state.stato, "")


class _Section(QWidget):
    """A heading with its total, a short note and the rows of one ``gruppo``."""

    def __init__(self, gruppo: str, heading: str, note: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.gruppo, self._heading = gruppo, heading
        self.title = QLabel()
        theme.set_role(self.title, "diffTypeGroup")
        self.title.setVisible(bool(heading))
        self.note = QLabel(note)
        self.note.setWordWrap(True)
        theme.set_role(self.note, "muted")
        self.rows_box = QVBoxLayout()
        self.rows_box.setContentsMargins(theme.SPACE[1], 0, 0, 0)
        self.rows_box.setSpacing(theme.SPACE[0])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE[0])
        layout.addWidget(self.title)
        layout.addWidget(self.note)
        layout.addLayout(self.rows_box)

    def set_total(self, n: int) -> None:
        self.total = n
        self.title.setText(self._heading.format(n=n))


class FiltersDialog(QDialog):
    """The panel of one case; the page connects the three requests."""

    #: (choices ``{id: attivo}``, also the initiative's default, the toast's text)
    choices_requested = Signal(object, bool, str)
    #: (anchors, pages) of an occurrence to show in the case view
    occurrence_chosen = Signal(object, object)
    #: the case's own rules, from the editor in "Regole avanzate"
    rules_save_requested = Signal(object)
    #: "Ripristina predefiniti": every own choice of the case removed
    reset_requested = Signal()

    def __init__(self, title: str, panel: FilterPanel, case_id: str, *, editor: NoiseRulesEditor | None = None,
                 control_source: Callable[[], ControlState] | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(False)
        self.case_id = case_id
        self.panel = panel
        self.editor = editor
        self._control_source = control_source
        self.rows: dict[str, FilterRow] = {}
        self.help = QLabel(strings.FILTRI_HELP)
        self.help.setWordWrap(True)
        theme.set_role(self.help, "muted")
        self.scope = QCheckBox(strings.FILTRI_SCOPE)
        self.scope.setToolTip(strings.FILTRI_SCOPE_TIP)
        self.sections = {g: _Section(g, heading, note) for g, heading, note in _SECTIONS}
        self.advanced_button = QToolButton()
        self.advanced_button.setCheckable(True)
        self.advanced_button.setToolTip(strings.FILTRI_ADVANCED_TIP)
        theme.set_role(self.advanced_button, "stripButton")
        self.advanced = QWidget()
        self.save_rules_button = QPushButton(strings.FILTRI_RULES_SAVE)
        self.save_rules_button.setToolTip(strings.FILTRI_RULES_SAVE_TIP)
        self.panel_note = QLabel()
        self.panel_note.setWordWrap(True)
        theme.set_role(self.panel_note, "muted")
        self.control = QLabel()
        self.control.setWordWrap(True)
        self.control.setToolTip(strings.FILTRI_CONTROL_TIP)
        theme.set_role(self.control, "muted")
        self.close_button = QPushButton(strings.FILTRI_CLOSE)
        self.reset_button = QPushButton(strings.FILTRI_RESET)
        self.reset_button.setToolTip(strings.FILTRI_RESET_TIP)
        self.sections["zone"].title.setToolTip(strings.FILTRI_SECTION_ZONE_TIP)
        self.poll = QTimer(self, interval=CONTROL_POLL_MS)
        self._build()
        self.advanced_button.toggled.connect(self.set_advanced)
        self.save_rules_button.clicked.connect(self._on_save_rules)
        self.close_button.clicked.connect(self.close)
        self.reset_button.clicked.connect(self.reset_requested)
        self.poll.timeout.connect(self._poll_control)
        self.finished.connect(self._release)
        if editor is not None:
            editor.validity_changed.connect(self.save_rules_button.setEnabled)
            self.save_rules_button.setEnabled(editor.is_valid())
        self.set_advanced(False)
        self.show_panel(panel)
        self.resize(720, 640)

    def _build(self) -> None:
        content = QWidget()
        body = QVBoxLayout(content)
        body.setContentsMargins(0, 0, theme.SPACE[1], 0)
        body.setSpacing(theme.SPACE[2])
        for gruppo in ("zone", "variabili", "decidere"):
            body.addWidget(self.sections[gruppo])
        body.addWidget(self.advanced_button, 0, Qt.AlignmentFlag.AlignLeft)
        advanced = QVBoxLayout(self.advanced)
        advanced.setContentsMargins(0, 0, 0, 0)
        advanced.setSpacing(theme.SPACE[1])
        advanced.addWidget(self.sections["avanzate"])
        if self.editor is not None:
            advanced.addWidget(self.editor)
            advanced.addWidget(self.save_rules_button, 0, Qt.AlignmentFlag.AlignRight)
        body.addWidget(self.advanced)
        body.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(content)
        self.scroll = scroll
        head = QHBoxLayout()
        head.addWidget(self.help, 1)
        head.addWidget(self.scope, 0, Qt.AlignmentFlag.AlignTop)
        foot = QHBoxLayout()
        foot.addWidget(self.control, 1)
        foot.addWidget(self.reset_button)
        foot.addWidget(self.close_button)
        layout = QVBoxLayout(self)
        layout.setSpacing(theme.SPACE[1])
        layout.addLayout(head)
        layout.addWidget(self.panel_note)
        layout.addWidget(scroll, 1)
        layout.addLayout(foot)

    # -- public ------------------------------------------------------------------

    def show_panel(self, panel: FilterPanel) -> None:
        """The panel as it is now (after a switch, a comparison, a rules save):
        rows updated in place, expanded rows stay expanded."""
        self.panel = panel
        wanted = [g.id for g in panel.groups]
        if list(self.rows) != wanted:
            self._rebuild(panel.groups)
        else:
            for group in panel.groups:
                self.rows[group.id].update_group(group)
        for gruppo, section in self.sections.items():
            rows = panel.of(gruppo)
            if gruppo == "zone":  # what counts, as the side panel says (not arredo, not invisible)
                section.set_total(sum(g.n for g in rows if g.interruttore and not g.attivo))
            else:
                section.set_total(sum(g.n for g in rows))
            section.setVisible(bool(rows) or gruppo == "avanzate")
        self._label_advanced()
        self.panel_note.setText(panel.nota)
        self.panel_note.setVisible(bool(panel.nota))
        self.set_control(panel.controllo)

    def set_control(self, state: ControlState) -> None:
        """The control generation's line; polled again while it runs."""
        self.control.setText(control_text(state))
        self.control.setVisible(bool(self.control.text()))
        if state.stato == "in_corso" and self._control_source is not None:
            self.poll.start()
        else:
            self.poll.stop()

    def set_advanced(self, on: bool) -> None:
        """Open / close "Regole avanzate"."""
        if self.advanced_button.isChecked() != on:
            self.advanced_button.setChecked(on)
            return
        self.advanced.setVisible(on)
        self._label_advanced()
        if on:  # the rules come into view under their button (again once the layout settled)
            self._reveal_advanced()
            QTimer.singleShot(0, self, self._reveal_advanced)

    def set_own_choices(self, n: int) -> None:
        """How many own choices the case has ("Ripristina predefiniti")."""
        self.reset_button.setEnabled(n > 0)
        self.reset_button.setToolTip(strings.FILTRI_RESET_TIP_N.format(n=n) if n else strings.FILTRI_RESET_TIP)

    def reject(self) -> None:  # Chiudi, Esc, the window's ✕
        """Closed by the user: unsaved rules ask Salva / Scarta / Annulla first."""
        if self._settle_rules(cancellable=True):
            super().reject()

    def leave(self) -> None:
        """The case left the screen: unsaved rules ask Salva / Scarta, then it closes."""
        self._settle_rules(cancellable=False)
        super().reject()

    def ask_unsaved(self, *, valid: bool, cancellable: bool) -> str:
        """"save" | "discard" | "cancel" (a test answers instead)."""
        return ask.ask_unsaved_rules(self, valid=valid, cancellable=cancellable)

    def advanced_open(self) -> bool:
        return self.advanced.isVisibleTo(self)

    def row(self, filter_id: str) -> FilterRow | None:
        return self.rows.get(filter_id)

    def section_title(self, gruppo: str) -> str:
        """The heading of a section ("Regole avanzate": its button)."""
        if gruppo == "avanzate":
            return self.advanced_button.text()
        return self.sections[gruppo].title.text()

    def switch(self, filter_id: str, attivo: bool) -> None:
        """What a click on the row's box does (tests, keyboard helpers)."""
        row = self.rows[filter_id]
        row.switch.setChecked(not attivo if row.group.gruppo == "zone" else attivo)
        self._on_switched(filter_id, attivo)

    # -- internals ------------------------------------------------------------------

    def _reveal_advanced(self) -> None:
        """The "Regole avanzate" button at the top of the scrolled area."""
        self.scroll.widget().layout().activate()
        bar = self.scroll.verticalScrollBar()
        bar.setValue(min(bar.maximum(), self.advanced_button.y()))

    def _label_advanced(self) -> None:
        template = strings.FILTRI_ADVANCED_HIDE if self.advanced_button.isChecked() else strings.FILTRI_ADVANCED_SHOW
        self.advanced_button.setText(template.format(n=getattr(self.sections["avanzate"], "total", 0)))

    def _rebuild(self, groups: tuple[FilterGroup, ...]) -> None:
        expanded = {fid for fid, row in self.rows.items() if row.expander.isChecked()}
        for row in self.rows.values():
            row.setParent(None)
            row.deleteLater()
        self.rows = {}
        for group in groups:
            row = FilterRow(group)
            row.switched.connect(self._on_switched)
            row.occurrence_chosen.connect(self.occurrence_chosen)
            self.sections[group.gruppo].rows_box.addWidget(row)
            row.set_expanded(group.id in expanded)
            self.rows[group.id] = row

    def _on_switched(self, filter_id: str, attivo: bool) -> None:
        group = self.rows[filter_id].group
        initiative = self.scope.isChecked()
        self.choices_requested.emit({filter_id: attivo}, initiative,
                                    change_text(group, attivo, initiative=initiative))

    def _on_save_rules(self) -> None:
        if self.editor is not None and self.editor.is_valid():
            self.rules_save_requested.emit(self.editor.rules())

    def _settle_rules(self, *, cancellable: bool) -> bool:
        """False: stay open (the user chose Annulla)."""
        editor = self.editor
        if editor is None or not editor.is_dirty():
            return True
        answer = self.ask_unsaved(valid=editor.is_valid(), cancellable=cancellable)
        if answer == "cancel" and cancellable:
            self.set_advanced(True)
            return False
        if answer == "save" and editor.is_valid():
            self.rules_save_requested.emit(editor.rules())
        return True

    def _poll_control(self) -> None:
        if self._control_source is None:
            self.poll.stop()
            return
        self.set_control(self._control_source())

    def _release(self, _result: int = 0) -> None:
        """Closed: no more polling or counting (the page deletes the dialog)."""
        self.poll.stop()
        self._control_source = None
        if self.editor is not None:
            self.editor.release()
