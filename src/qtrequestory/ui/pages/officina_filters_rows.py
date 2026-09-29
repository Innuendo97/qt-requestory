"""The rows of "Filtri del confronto" (phase 2.5, U4: spec §3.8, rulings F4, F5, F7).

One :class:`FilterRow` per ``FilterGroup``::

    ▸ Footer                                   2   [x] Conta
      p. 1, 2 · Acme-Servizi S.p.A. · …                         (expanded)
    ▸ Testo invisibile                         3   solo informativo

The switch reads as its section says (:func:`switch_label`): a zone "Conta"
(checked = its differences count, the inverse of ``attivo``), a proof
"Variabile", a "Da decidere" row "Tollera tutte", a rule "Applica" (all
three checked = ``attivo``). ``zona.invisibile`` has no switch (F7). A row
with ``n == 0`` stays, dimmed. Each occurrence is a flat button: a click
asks the case view to show it (by anchor, F5); an occurrence without anchors
(invisible text) is not a difference and is disabled.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton, QToolButton, QVBoxLayout, QWidget

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import FilterGroup, FilterOccurrence
from qtrequestory.ui.pages.officina_format import elide
from qtrequestory.ui.pages.officina_widgets import pill

__all__ = ["MAX_OCCURRENCES", "FilterRow", "change_text", "checked_for", "display_title", "occurrence_text",
           "switch_label"]

#: Occurrences listed under a row; the rest are summed up in one line.
MAX_OCCURRENCES = 40
#: Characters of an occurrence's text before "…".
OCCURRENCE_CHARS = 70

_SWITCH = {
    "zone": (strings.FILTRI_SWITCH_ZONE, strings.FILTRI_SWITCH_ZONE_TIP),
    "variabili": (strings.FILTRI_SWITCH_VARIABILI, strings.FILTRI_SWITCH_VARIABILI_TIP),
    "decidere": (strings.FILTRI_SWITCH_DECIDERE, strings.FILTRI_SWITCH_DECIDERE_TIP),
    "avanzate": (strings.FILTRI_SWITCH_AVANZATE, strings.FILTRI_SWITCH_AVANZATE_TIP),
}
_STATE = {
    "zone": (strings.FILTRI_STATE_ZONE_ON, strings.FILTRI_STATE_ZONE_OFF),
    "variabili": (strings.FILTRI_STATE_VARIABILI_ON, strings.FILTRI_STATE_VARIABILI_OFF),
    "decidere": (strings.FILTRI_STATE_DECIDERE_ON, strings.FILTRI_STATE_DECIDERE_OFF),
    "avanzate": (strings.FILTRI_STATE_AVANZATE_ON, strings.FILTRI_STATE_AVANZATE_OFF),
}


#: Rows whose stored name reads ambiguously in the panel: (title, tooltip).
_TITLES = {
    "avanzate.Numero di pagina nel testo": (strings.FILTRI_PRESET_PAGE_NUMBER, strings.FILTRI_PRESET_PAGE_NUMBER_TIP),
    # the 2.4 stored name (an alias of the renamed preset, filter_model.RENAMED_RULES)
    "avanzate.Numero di pagina": (strings.FILTRI_PRESET_PAGE_NUMBER, strings.FILTRI_PRESET_PAGE_NUMBER_TIP),
}


def display_title(group: FilterGroup) -> str:
    """The row's title on screen: the regex preset named like the zone
    reads "Numero di pagina nel testo" and says why in its tooltip."""
    return _TITLES.get(group.id, (group.titolo, ""))[0]


def switch_label(gruppo: str) -> str:
    """What the switch of a row of ``gruppo`` says."""
    return _SWITCH[gruppo][0]


def checked_for(gruppo: str, attivo: bool) -> bool:
    """The box of a row: a zone is checked when it COUNTS (not ``attivo``)."""
    return not attivo if gruppo == "zone" else attivo


def change_text(group: FilterGroup, attivo: bool, *, initiative: bool = False) -> str:
    """The toast of switching ``group`` to ``attivo``."""
    on, off = _STATE[group.gruppo]
    template = strings.FILTRI_CHANGED_INITIATIVE if initiative else strings.FILTRI_CHANGED
    return template.format(name=display_title(group), state=on if attivo else off)


def occurrence_text(o: FilterOccurrence) -> str:
    """``p. 1, 2 · text · detail`` (1-based pages; the text elided)."""
    pages = ", ".join(str(p + 1) for p in o.pagine) or "–"
    text = elide(" ".join(o.testo.split()), OCCURRENCE_CHARS) or strings.FILTRI_OCCURRENCE_EMPTY
    if o.dettaglio:
        return strings.FILTRI_OCCURRENCE_DETAIL.format(pages=pages, text=text,
                                                       detail=elide(o.dettaglio, OCCURRENCE_CHARS // 2))
    return strings.FILTRI_OCCURRENCE.format(pages=pages, text=text)


def _count_tip(n: int) -> str:
    if n == 0:
        return strings.FILTRI_COUNT_TIP_NONE
    return strings.FILTRI_COUNT_TIP_ONE if n == 1 else strings.FILTRI_COUNT_TIP_MANY.format(n=n)


class FilterRow(QFrame):
    """One row: expander, title, count, switch; its occurrences below."""

    #: (filter id, attivo): the user turned the switch.
    switched = Signal(str, bool)
    #: (anchors, pages) of the occurrence clicked.
    occurrence_chosen = Signal(object, object)

    def __init__(self, group: FilterGroup, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.group = group
        self.expander = QToolButton()
        theme.set_role(self.expander, "panelTool")
        self.expander.setCheckable(True)
        self.expander.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.title = QLabel()
        self.count = pill("", "neutral")
        self.switch = QCheckBox(switch_label(group.gruppo))
        self.informative = QLabel(strings.FILTRI_INFORMATIVE)
        theme.set_role(self.informative, "muted")
        self.informative.setToolTip(strings.FILTRI_INFORMATIVE_TIP)
        self.occurrences = QWidget()
        self._list = QVBoxLayout(self.occurrences)
        self._list.setContentsMargins(theme.SPACE[4], 0, 0, theme.SPACE[0])
        self._list.setSpacing(0)
        self.occurrences.setVisible(False)
        self._build()
        self.expander.toggled.connect(self.set_expanded)
        self.switch.clicked.connect(self._on_clicked)
        self.update_group(group)

    def _build(self) -> None:
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(theme.SPACE[1])
        top.addWidget(self.expander)
        top.addWidget(self.title, 1)
        top.addWidget(self.count)
        top.addSpacing(theme.SPACE[1])
        top.addWidget(self.switch)
        top.addWidget(self.informative)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(top)
        layout.addWidget(self.occurrences)

    # -- public ------------------------------------------------------------------

    def update_group(self, group: FilterGroup) -> None:
        """New counts, occurrences and switch (the expansion stays)."""
        self.group = group
        self.title.setText(display_title(group))
        self.title.setToolTip(_TITLES.get(group.id, ("", ""))[1])
        theme.set_role(self.title, "" if group.n else "muted")
        theme.repolish(self.title)
        self.count.setText(str(group.n))
        self.count.setToolTip(_count_tip(group.n))
        self.count.setAccessibleName(_count_tip(group.n))
        self.switch.setVisible(group.interruttore)
        self.informative.setVisible(not group.interruttore)
        self.switch.setChecked(checked_for(group.gruppo, group.attivo))
        default = strings.FILTRI_ON if checked_for(group.gruppo, group.predefinito) else strings.FILTRI_OFF
        tip = f"{_SWITCH[group.gruppo][1]}\n{strings.FILTRI_DEFAULT_TIP.format(state=default)}"
        self.switch.setToolTip(tip)
        self.switch.setAccessibleName(f"{switch_label(group.gruppo)}: {display_title(group)}")
        has = bool(group.occorrenze)
        self.expander.setEnabled(has)
        name = strings.FILTRI_EXPAND_NAME.format(name=display_title(group))
        self.expander.setAccessibleName(name)
        self.expander.setToolTip(name if has else "")
        self._fill()
        self.set_expanded(self.expander.isChecked() and has)

    def is_expanded(self) -> bool:
        return self.occurrences.isVisibleTo(self)

    def set_expanded(self, on: bool) -> None:
        on = on and bool(self.group.occorrenze)
        if self.expander.isChecked() != on:
            self.expander.setChecked(on)  # toggled comes back here once
            return
        self.expander.setText("▾" if on else "▸")
        self.occurrences.setVisible(on)

    def occurrence_buttons(self) -> list[QPushButton]:
        return [self._list.itemAt(i).widget() for i in range(self._list.count())
                if isinstance(self._list.itemAt(i).widget(), QPushButton)]

    # -- internals ------------------------------------------------------------------

    def _fill(self) -> None:
        while self._list.count():
            widget = self._list.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()
        shown = self.group.occorrenze[:MAX_OCCURRENCES]
        for occurrence in shown:
            button = QPushButton(occurrence_text(occurrence))
            theme.set_role(button, "row")
            button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            button.setToolTip(strings.FILTRI_OCCURRENCE_TIP if occurrence.anchors
                              else strings.FILTRI_OCCURRENCE_NO_DIFF)
            button.setEnabled(bool(occurrence.anchors))
            button.clicked.connect(lambda _c=False, o=occurrence: self.occurrence_chosen.emit(o.anchors, o.pagine))
            self._list.addWidget(button)
        rest = len(self.group.occorrenze) - len(shown)
        if rest > 0:
            more = QLabel(strings.FILTRI_MORE_OCCURRENCES.format(n=rest))
            theme.set_role(more, "muted")
            self._list.addWidget(more)

    def _on_clicked(self, checked: bool) -> None:
        attivo = not checked if self.group.gruppo == "zone" else checked
        self.switched.emit(self.group.id, attivo)
