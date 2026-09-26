"""The "Regole di rumore…" dialog (spec §4.2 step 5, §7.5).

Opened from the board (the initiative's rules and presets) and from the case
header (the case's own rules; the initiative's rules are listed read-only
because they add up; the presets are the initiative's in both)::

    Le regole cercano nel testo normalizzato (…)
    Preset                          Valgono per tutta l'iniziativa.
    [ ] Numero di pagina                          3 occorrenze
    [ ] Data                                      ◐
    Regole di questo caso                       [+ Regola] [Rimuovi]
    [x] Codice pratica   PR-\\d{6}                 2 occorrenze
    [x] Rotta            (a+                      espressione non valida: …
                                          [Salva e riconfronta] [Annulla]

Every rule shows how often it matches the target and the latest TO-BE of the
case (``count_noise_hits``) BEFORE saving. The counts run in a worker the
page provides (``counter``), debounced: a user rule may take up to ~2 s in
the service's guarded child process (ruling R22), so each row shows a small
spinner meanwhile and the window never waits. A row with an error — no name,
no pattern, a regex that does not compile, a name already used at any level
(the engine refuses it too), or an error the service reported (ruling R17:
"espressione potenzialmente troppo lenta: semplificala") — shows it in red on
that row and keeps "Salva" disabled; the other rows are unaffected.
"""
from __future__ import annotations

import dataclasses
import re
from collections.abc import Callable
from functools import partial

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import NoiseRule
from qtrequestory.ui.pages.officina_noise_cells import hits_text
from qtrequestory.ui.pages.officina_noise_cells import make_item as _item
from qtrequestory.ui.pages.officina_noise_cells import make_label as _label
from qtrequestory.ui.pages.officina_noise_cells import make_table as _table

__all__ = ["DEBOUNCE_MS", "NoiseDialog", "hits_text"]

#: Quiet time after the last edit before the counts are asked again.
DEBOUNCE_MS = 400
SPIN_MS = 120
SPINNER = "◐◓◑◒"
NAME, PATTERN, HITS = range(3)
Counter = Callable[[list[NoiseRule]], object]   # rules -> a Job (or None: nothing to count on)


class NoiseDialog(QDialog):
    """Presets, the rules of the level being edited and their live counts.

    ``own``: the rules this dialog edits (the initiative's, or the case's);
    ``inherited``: the initiative's rules shown read-only for a case;
    ``reserved``: other names in use (name -> "where" phrase, e.g. another
    case's rules); ``counter``: submits ``count_noise_hits`` in a worker and
    returns the job, None when there is no case to count on (``counts_note``
    says which case the counts are about, or why there are none)."""

    def __init__(self, title: str, presets: list[NoiseRule], active: set[str], own: list[NoiseRule],
                 *, own_title: str, inherited: list[NoiseRule] | None = None,
                 reserved: dict[str, str] | None = None, counter: Counter | None = None,
                 counts_note: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self._counter = counter
        self._presets = [dataclasses.replace(p) for p in presets]
        self._inherited = [dataclasses.replace(r) for r in inherited or []]
        self._reserved = dict(reserved or {})
        #: rule name -> the last count (or the service's error) for that name
        self._hits: dict[str, int | str] = {}
        #: (name, pattern) -> the service's error for exactly that rule (it blocks "Salva")
        self._service_errors: dict[tuple[str, str], str] = {}
        self._pending: set[str] = set()
        self._serial = 0
        self._frame = 0
        self._filling = False

        self.presets = _table((strings.RUMORE_COL_NAME, strings.RUMORE_COL_HITS), editable=False)
        self.inherited = _table((strings.RUMORE_COL_NAME, strings.RUMORE_COL_PATTERN,
                                 strings.RUMORE_COL_HITS), editable=False)
        self.own = _table((strings.RUMORE_COL_NAME, strings.RUMORE_COL_PATTERN,
                           strings.RUMORE_COL_HITS), editable=True)
        self.add_button = QPushButton(strings.RUMORE_ADD)
        self.remove_button = QPushButton(strings.RUMORE_REMOVE)
        self.blocked = _label(strings.RUMORE_BLOCKED, "diffNoteBad")
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                        | QDialogButtonBox.StandardButton.Cancel)
        self.ok_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_button.setText(strings.RUMORE_OK)
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(strings.BTN_CANCEL)
        self.debounce = QTimer(self, singleShot=True, interval=DEBOUNCE_MS)
        self.spinner = QTimer(self, interval=SPIN_MS)
        self._build(own_title, counts_note)
        self._fill(active, own)
        self._connect()
        self.setMinimumSize(780, 620)
        self._check()
        self.schedule_counts()

    def _build(self, own_title: str, counts_note: str) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(theme.SPACE[1])
        layout.addWidget(_label(strings.RUMORE_HELP, "muted"))
        if counts_note:
            layout.addWidget(_label(counts_note, "muted"))
        layout.addWidget(self._heading(strings.RUMORE_PRESETS, strings.RUMORE_PRESETS_NOTE))
        layout.addWidget(self.presets, 5)
        if self._inherited:
            layout.addWidget(self._heading(strings.RUMORE_INHERITED, strings.RUMORE_INHERITED_NOTE))
            layout.addWidget(self.inherited, 1)
        self.inherited.setVisible(bool(self._inherited))
        head = QHBoxLayout()
        head.addWidget(_label(own_title, "section"), 1)
        head.addWidget(self.add_button)
        head.addWidget(self.remove_button)
        layout.addLayout(head)
        layout.addWidget(self.own, 3)
        foot = QHBoxLayout()
        foot.addWidget(self.blocked, 1)
        foot.addWidget(self.buttons)
        layout.addLayout(foot)

    @staticmethod
    def _heading(text: str, note: str) -> QWidget:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, theme.SPACE[1], 0, 0)
        row.addWidget(_label(text, "section"))
        row.addWidget(_label(note, "muted"), 1)
        return box

    def _fill(self, active: set[str], own: list[NoiseRule]) -> None:
        self._filling = True
        for rule in self._presets:
            row = self.presets.rowCount()
            self.presets.insertRow(row)
            name = _item(rule.name, check=rule.name in active)
            name.setToolTip(rule.pattern)
            self.presets.setItem(row, 0, name)
            self.presets.setItem(row, 1, _item(""))
        for rule in self._inherited:
            row = self.inherited.rowCount()
            self.inherited.insertRow(row)
            self.inherited.setItem(row, NAME, _item(rule.name, check=rule.enabled))
            self.inherited.item(row, NAME).setFlags(Qt.ItemFlag.ItemIsEnabled)  # read-only box
            self.inherited.setItem(row, PATTERN, _item(rule.pattern))
            self.inherited.setItem(row, HITS, _item(""))
        for rule in own:
            self._append(rule)
        self._filling = False

    def _append(self, rule: NoiseRule) -> int:
        row = self.own.rowCount()
        self.own.insertRow(row)
        name = _item(rule.name, editable=True, check=rule.enabled)
        name.setToolTip(strings.RUMORE_ENABLED_TIP)
        self.own.setItem(row, NAME, name)
        self.own.setItem(row, PATTERN, _item(rule.pattern, editable=True))
        self.own.setItem(row, HITS, _item(""))
        return row

    def _connect(self) -> None:
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.add_button.clicked.connect(self._on_add)
        self.remove_button.clicked.connect(self._on_remove)
        self.own.itemChanged.connect(self._on_edited)
        self.debounce.timeout.connect(self._count_now)
        self.spinner.timeout.connect(self._spin)
        theme.signals.changed.connect(self._paint)
        self.finished.connect(self._release)

    def _release(self, _result: int = 0) -> None:
        """Closed: no more counts, spinner or repaints (the page deletes the dialog)."""
        self.debounce.stop()
        self.spinner.stop()
        self._counter = None
        self._serial += 1  # an answer still on its way finds a stale serial and does nothing
        try:
            theme.signals.changed.disconnect(self._paint)
        except (RuntimeError, TypeError):
            pass

    # -- public ------------------------------------------------------------------

    def rules(self) -> list[NoiseRule]:
        """The edited level's rules, in table order."""
        return [NoiseRule(self._name(r), self._pattern(r), self._enabled(r))
                for r in range(self.own.rowCount())]

    def active_presets(self) -> list[str]:
        return [self.presets.item(r, 0).text() for r in range(self.presets.rowCount())
                if self.presets.item(r, 0).checkState() == Qt.CheckState.Checked]

    def add_rule(self, name: str = "", pattern: str = "", enabled: bool = True) -> int:
        """A new row (the "+ Regola" button without a name gives "Regola N")."""
        self._filling = True
        row = self._append(NoiseRule(name, pattern, enabled))
        self._filling = False
        self._on_edited()
        return row

    def set_pattern(self, row: int, pattern: str) -> None:
        self.own.item(row, PATTERN).setText(pattern)   # itemChanged → debounced counts

    def own_row(self, name: str) -> int:
        return next(r for r in range(self.own.rowCount()) if self._name(r) == name)

    def hits_shown(self, table: QTableWidget, row: int) -> str:
        return table.item(row, table.columnCount() - 1).text()

    def row_error(self, row: int) -> str:
        """Why own row ``row`` cannot be saved ("" when it can)."""
        name, pattern = self._name(row), self._pattern(row)
        if not name:
            return strings.RUMORE_ERR_NAME_EMPTY
        if not pattern:
            return strings.RUMORE_ERR_PATTERN_EMPTY
        try:  # a syntax check only: the rule is never matched here (R46)
            re.compile(pattern)
        except (re.error, OverflowError, RecursionError, ValueError) as exc:
            return strings.RUMORE_ERR_REGEX.format(reason=exc)
        where = self._used_elsewhere(row, name)
        if where:
            return strings.RUMORE_ERR_DUPLICATE.format(where=where)
        return self._service_errors.get((name, pattern), "")

    def is_counting(self) -> bool:
        return bool(self._pending) or self.debounce.isActive()

    def schedule_counts(self) -> None:
        if self._counter is not None:
            self.debounce.start()

    # -- internals ------------------------------------------------------------------

    def _name(self, row: int) -> str:
        return " ".join(self.own.item(row, NAME).text().split())

    def _pattern(self, row: int) -> str:
        return self.own.item(row, PATTERN).text()

    def _enabled(self, row: int) -> bool:
        return self.own.item(row, NAME).checkState() == Qt.CheckState.Checked

    def _used_elsewhere(self, row: int, name: str) -> str:
        if any(self._name(r) == name for r in range(self.own.rowCount()) if r != row):
            return strings.RUMORE_WHERE_HERE
        if any(p.name == name for p in self._presets):
            return strings.RUMORE_WHERE_PRESET
        if any(r.name == name for r in self._inherited):
            return strings.RUMORE_WHERE_INITIATIVE
        return self._reserved.get(name, "")

    def _on_add(self) -> None:
        taken = {self._name(r) for r in range(self.own.rowCount())}
        n = self.own.rowCount() + 1
        while strings.RUMORE_NEW_NAME.format(n=n) in taken:
            n += 1
        row = self.add_rule(strings.RUMORE_NEW_NAME.format(n=n))
        self.own.setCurrentCell(row, PATTERN)
        self.own.editItem(self.own.item(row, PATTERN))

    def _on_remove(self) -> None:
        row = self.own.currentRow()
        if row >= 0:
            self.own.removeRow(row)
            self._on_edited()

    def _on_edited(self, item: QTableWidgetItem | None = None) -> None:
        if self._filling or (item is not None and item.column() == HITS):
            return
        self._check()
        self.schedule_counts()

    def _requested(self) -> list[NoiseRule]:
        """What to count: every preset and inherited rule, and the own rows
        without a local error — all switched on (a count is "what it would
        catch"), names unique by construction."""
        own = [NoiseRule(self._name(r), self._pattern(r), True) for r in range(self.own.rowCount())
               if not self._local_error(r)]
        inherited = [r for i, r in enumerate(self._inherited) if not self.inherited_error(i)]
        return [dataclasses.replace(p, enabled=True) for p in (*self._presets, *inherited)] + own

    def inherited_error(self, index: int) -> str:
        """An initiative rule named like a preset or like an earlier one (an
        old or hand-edited file): shown on its row and left out of the counts
        (the service would refuse the whole request). Fixed from the board."""
        name = self._inherited[index].name
        if any(p.name == name for p in self._presets):
            return strings.RUMORE_ERR_DUPLICATE.format(where=strings.RUMORE_WHERE_PRESET)
        if any(r.name == name for r in self._inherited[:index]):
            return strings.RUMORE_ERR_DUPLICATE.format(where=strings.RUMORE_WHERE_HERE)
        return ""

    def _local_error(self, row: int) -> bool:
        name, pattern = self._name(row), self._pattern(row)
        return bool(self.row_error(row)) and (name, pattern) not in self._service_errors

    def _count_now(self) -> None:
        if self._counter is None:
            return
        rules = self._requested()
        self._serial += 1
        job = self._counter(rules)
        if job is None:
            self._pending.clear()
            self._paint()
            return
        self._pending = {r.name for r in rules}
        keys = {r.name: r.pattern for r in rules}
        job.signals.result.connect(partial(self._on_hits, self._serial, keys))
        job.signals.error.connect(partial(self._on_count_failed, self._serial))
        self.spinner.start()
        self._paint()

    def _on_hits(self, serial: int, keys: dict[str, str], hits: dict) -> None:
        if serial != self._serial:
            return
        for name, pattern in keys.items():
            value = hits.get(name)
            self._hits[name] = value
            self._service_errors.pop((name, pattern), None)
            if isinstance(value, str) and name not in {p.name for p in self._presets}:
                self._service_errors[(name, pattern)] = value
        self._stop_spinner()
        self._check()

    def _on_count_failed(self, serial: int, _kind: str, _message: str) -> None:
        if serial != self._serial:
            return
        for name in self._pending:
            self._hits[name] = strings.RUMORE_HITS_FAILED
        self._stop_spinner()
        self._paint()

    def _stop_spinner(self) -> None:
        self._pending.clear()
        self.spinner.stop()

    def _spin(self) -> None:
        self._frame = (self._frame + 1) % len(SPINNER)
        self._paint()

    def _check(self) -> None:
        errors = [self.row_error(r) for r in range(self.own.rowCount())]
        blocked = any(errors)
        self.ok_button.setEnabled(not blocked)
        self.blocked.setVisible(blocked)
        self._paint()

    def _paint(self) -> None:
        t = theme.tokens()
        self._filling = True
        try:
            for row in range(self.presets.rowCount()):
                self._paint_hits(self.presets, row, self.presets.item(row, 0).text(), "", t)
            for row in range(self.inherited.rowCount()):
                self._paint_hits(self.inherited, row, self._inherited[row].name, self.inherited_error(row), t)
            for row in range(self.own.rowCount()):
                self._paint_hits(self.own, row, self._name(row), self.row_error(row), t)
        finally:
            self._filling = False

    def _paint_hits(self, table: QTableWidget, row: int, name: str, error: str, t) -> None:
        item = table.item(row, table.columnCount() - 1)
        value = self._hits.get(name)
        if error:
            text, colour = error, t.bad
        elif name in self._pending:
            text, colour = SPINNER[self._frame], t.muted
        elif self._counter is None:
            text, colour = strings.RUMORE_HITS_UNKNOWN, t.muted
        else:
            text = hits_text(value)
            colour = t.bad if isinstance(value, str) else (t.text if value else t.muted)
        item.setText(text)
        item.setToolTip(text)
        item.setForeground(QColor(colour))
