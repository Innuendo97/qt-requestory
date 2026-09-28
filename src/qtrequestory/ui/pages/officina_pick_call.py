""""Aggiungi chiamata…": one window to add cases from the logged calls, or to
replace a case's call (decision U2).

* the environment of the logs (default: the one Ricerca last used, else the
  first enabled one);
* one field for a template key or an FDI — the rules of Ricerca's omnibox
  (``search_paste``: an entry name pasted gives both, a token is an FDI when
  it reads like the start of one, else an EXACT key) — searched as you type,
  :data:`DEBOUNCE_MS` after the last keystroke, in the ``officina-pick`` job
  (``IndexApi.search``, most recent first, at most :data:`PICK_LIMIT` rows);
* the calls found (date and time, FDI, key); several can be chosen, a double
  click takes one at once;
* the initiative (the open one; "Nuova iniziativa…" as in ``AddCaseDialog``)
  and the variant of the new cases.

A chosen call whose key already has a case in that initiative is asked about
(``officina_pick_question``: replace that case's call, or a new case).
Opened from a case (``case=``), the field starts on the case's key, one
call is chosen and replacing that case is the default answer.

The window only decides: :meth:`PickCallDialog.plan` is carried out by the
page in a worker (``officina_add_plan.run_plan``). Every problem — no
environment, a log folder that cannot be used, nothing indexed yet, a query
refused — is a sentence in the window, never a traceback.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Sequence

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from qtrequestory.ui import actions, strings, theme
from qtrequestory.ui.contracts import Case, CoreServices, Initiative, SearchHit, SearchQuery
from qtrequestory.ui.pages import officina_pick_question as question
from qtrequestory.ui.pages.officina_add_plan import AddTarget, PlanItem, cases_of_key
from qtrequestory.ui.pages.officina_format import case_title, initiative_labels
from qtrequestory.ui.pages.search_paste import classify_token, parse_pasted_entry
from qtrequestory.ui.results_model import format_day, format_time
from qtrequestory.ui.workers import OFFICINA_PICK_JOB, JobRunner

__all__ = ["DEBOUNCE_MS", "PICK_LIMIT", "PickCallDialog", "parse_query"]

log = logging.getLogger(__name__)

DEBOUNCE_MS = 300
PICK_LIMIT = 200
#: Ricerca's remembered environment (``search_page.ENV_SETTING``).
SEARCH_ENV_SETTING = "search/env"
NEW = "__new__"
COL_WHEN, COL_FDI, COL_KEY = range(3)


def parse_query(text: str) -> tuple[str | None, str | None] | None:
    """``(fdi prefix, exact key)`` of what was typed or pasted, else None."""
    pasted = parse_pasted_entry(text)
    if pasted is not None:
        return pasted
    token = classify_token(text)
    if token is None:
        return None
    kind, value = token
    return (value, None) if kind == "fdi" else (None, value)


class PickCallDialog(QDialog):
    """See module doc. ``initiatives`` are read from disk by the caller."""

    def __init__(self, services: CoreServices, runner: JobRunner, initiatives: Sequence[Initiative], *,
                 current: str | None = None, case: Case | None = None,
                 busy: Callable[[str, str], bool] | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._services = services
        self._runner = runner
        self._initiatives = {ini.id: ini for ini in initiatives}
        self._case = case
        self._hits: list[SearchHit] = []
        self._plan: tuple[AddTarget, list[PlanItem]] | None = None
        self._closed = False
        #: (initiative id, case id) -> the case waits or is sent: its call cannot change now.
        self._busy = busy or (lambda _ini, _case: False)
        #: Bumped by every search: an answer to an older one is dropped.
        self._seq = 0
        self.setWindowTitle(strings.CHIAMATA_TITLE_CASE.format(case=case_title(case)) if case
                            else strings.CHIAMATA_TITLE)

        self.env = QComboBox()
        self.query = QLineEdit(case.key if case is not None else "")
        self.query.setPlaceholderText(strings.CHIAMATA_QUERY_HINT)
        self.query.setClearButtonEnabled(True)
        self.note = QLabel(strings.CHIAMATA_START)
        self.note.setWordWrap(True)
        theme.set_role(self.note, "muted")
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([strings.CHIAMATA_COL_WHEN, strings.CHIAMATA_COL_FDI,
                                              strings.CHIAMATA_COL_KEY])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection if case
                                    else QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_KEY, QHeaderView.ResizeMode.Stretch)
        theme.set_table_look(self.table)
        self.initiative = QComboBox()
        labels = initiative_labels(initiatives)
        for ini in initiatives:
            self.initiative.addItem(labels[ini.id], userData=ini.id)
        self.initiative.addItem(strings.OFFICINA_ADD_NEW_INITIATIVE, userData=NEW)
        if current in self._initiatives:
            self.initiative.setCurrentIndex(self.initiative.findData(current))
        self.new_name = QLineEdit()
        self.new_name_label = QLabel(strings.OFFICINA_ADD_NEW_NAME)
        self.variant = QLineEdit()
        self.variant.setPlaceholderText(strings.OFFICINA_ADD_VARIANT_HINT)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setProperty("dot", "bad")
        self.error.setVisible(False)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(DEBOUNCE_MS)

        self._build()
        self._fill_envs()
        self.initiative.currentIndexChanged.connect(self._sync_new_name)
        self.query.textChanged.connect(lambda _t: self.timer.start())
        self.env.currentIndexChanged.connect(lambda _i: self.timer.start())
        self.timer.timeout.connect(self.search_now)
        self.table.doubleClicked.connect(self._take_row)
        self._sync_new_name()
        theme.repolish(self.error)
        self.resize(760, 560)
        if self.query.text():
            self.timer.start()
            self.query.selectAll()
        self.query.setFocus()  # type straight away

    def _build(self) -> None:
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.add_button = box.button(QDialogButtonBox.StandardButton.Ok)
        self.add_button.setText(strings.CHIAMATA_ADD_CASE if self._case else strings.CHIAMATA_ADD)
        box.button(QDialogButtonBox.StandardButton.Cancel).setText(strings.BTN_CANCEL)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        self.variant_label = QLabel(strings.CHIAMATA_VARIANT)
        # ONE grid: every label in the same column, so the fields line up
        grid = QGridLayout(self)
        rows = [(QLabel(strings.CHIAMATA_ENV), self.env), (QLabel(strings.CHIAMATA_QUERY), self.query),
                (None, self.note), (None, self.table),
                (QLabel(strings.CHIAMATA_INITIATIVE), self.initiative),
                (self.new_name_label, self.new_name), (self.variant_label, self.variant),
                (None, self.error), (None, box)]
        for row, (label, field) in enumerate(rows):
            if label is None:
                grid.addWidget(field, row, 0, 1, 2)
            else:
                grid.addWidget(label, row, 0)
                grid.addWidget(field, row, 1)
        grid.setRowStretch(3, 1)
        grid.setColumnStretch(1, 1)
        if self._case is not None:  # the case's initiative, and no new case to name
            self.initiative.setEnabled(False)
            for widget in (self.variant_label, self.variant):
                widget.setVisible(False)

    def _fill_envs(self) -> None:
        envs = [env.name for env in self._services.config.load().enabled_environments()]
        try:
            remembered = actions.user_settings().value(SEARCH_ENV_SETTING)
        except Exception:  # noqa: BLE001 - a preference, never a reason to fail
            remembered = None
        self.env.addItems(envs)
        if remembered in envs:
            self.env.setCurrentIndex(envs.index(remembered))
        self.env.setEnabled(bool(envs))
        if not envs:
            self._say(strings.CHIAMATA_NO_ENV)

    # -- the search --------------------------------------------------------

    def hits(self) -> list[SearchHit]:
        """The calls listed (at most :data:`PICK_LIMIT`)."""
        return list(self._hits)

    def search_now(self) -> None:
        """Search what the field holds now (the debounce's end)."""
        self.timer.stop()
        self._seq += 1  # whatever an earlier search answers now is dropped
        env = self.env.currentText()
        text = self.query.text().strip()
        if not env:
            self._show([], strings.CHIAMATA_NO_ENV)
            return
        if not text:
            self._show([], strings.CHIAMATA_START)
            return
        parsed = parse_query(text)
        if parsed is None:
            self._show([], strings.CHIAMATA_NOT_A_QUERY)
            return
        config = self._services.config
        problems = config.mirror_root_errors(config.load())
        if problems:
            self._show([], strings.CHIAMATA_FAILED.format(reason=strings.lower_first(problems[0])))
            return
        try:
            covered = self._services.index.coverage(env)
        except Exception:  # noqa: BLE001 - a broken index reads as "nothing indexed"
            log.exception("periodo coperto di %s non disponibile", env)
            covered = None
        if covered is None:
            self._show([], strings.CHIAMATA_NO_INDEX.format(env=env))
            return
        fdi, key = parsed
        query = SearchQuery(env, fdi_prefix=fdi or None, template_key=key or None, key_mode="exact",
                            limit=PICK_LIMIT + 1)
        job = self._runner.submit(OFFICINA_PICK_JOB, self._services.index.search, query)
        if job is None:
            return
        self.note.setText(strings.CHIAMATA_SEARCHING)
        seq = self._seq
        job.signals.result.connect(lambda hits, e=env: self._on_hits(e, hits, seq))
        job.signals.error.connect(lambda _kind, message: self._on_error(message, seq))

    def done(self, result: int) -> None:  # noqa: D102 - a late answer finds nobody
        self._closed = True
        self.timer.stop()
        super().done(result)

    def _on_error(self, message: str, seq: int) -> None:
        if not self._closed and seq == self._seq:
            self._show([], strings.CHIAMATA_FAILED.format(reason=message))

    def _on_hits(self, env: str, hits: list[SearchHit], seq: int) -> None:
        if self._closed or seq != self._seq:
            return  # closed, or an older search (the field or the environment changed since)
        found = list(hits)
        if not found:
            note = strings.CHIAMATA_NONE.format(env=env)
        elif len(found) > PICK_LIMIT:
            note = strings.CHIAMATA_CAPPED.format(n=PICK_LIMIT)
        elif len(found) == 1:
            note = strings.CHIAMATA_FOUND_ONE
        else:
            note = strings.CHIAMATA_FOUND.format(n=len(found))
        self._show(found[:PICK_LIMIT], note)
        if len(self._hits) == 1:
            self.table.selectRow(0)

    def _show(self, hits: list[SearchHit], note: str) -> None:
        self._hits = hits
        self.table.setRowCount(0)
        for row, hit in enumerate(hits):
            self.table.insertRow(row)
            when = f"{format_day(hit.day)} {format_time(hit.request_date)}"
            current = self._is_current(hit)
            fdi = strings.CHIAMATA_CURRENT.format(fdi=hit.fdi) if current else (hit.fdi or "—")
            for col, text in ((COL_WHEN, when), (COL_FDI, fdi), (COL_KEY, hit.template_key)):
                item = QTableWidgetItem(text)
                if current:
                    item.setToolTip(strings.CHIAMATA_CURRENT_TIP)
                if col == COL_FDI:
                    item.setFont(theme.mono_font())
                if not hit.json_ok:  # its body cannot become a payload
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled & ~Qt.ItemFlag.ItemIsSelectable)
                    item.setToolTip(strings.CHIAMATA_NOT_JSON_TIP)
                self.table.setItem(row, col, item)
        self._say(note)

    def _is_current(self, hit: SearchHit) -> bool:
        """The row of the FDI and key the case was made from ("(attuale)": a label
        only — the payload may have been edited since)."""
        case = self._case
        return (case is not None and bool(hit.fdi) and hit.fdi == case.source_fdi
                and hit.template_key == case.key)

    def _say(self, note: str) -> None:
        self.note.setText(note)

    # -- choosing ------------------------------------------------------------

    def selected_hits(self) -> list[SearchHit]:
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        return [self._hits[row] for row in rows if row < len(self._hits) and self._hits[row].json_ok]

    def plan(self) -> tuple[AddTarget, list[PlanItem]] | None:
        """What to do, once the window was accepted."""
        return self._plan

    def accept(self) -> None:  # noqa: D102 - decide (and ask) before closing
        # "(attuale)" is only a label: the same FDI may come with a payload edited
        # since, so the core decides (replace_call compares FDI AND payload)
        plan = self._decide()
        if plan is not None:
            self._plan = plan
            super().accept()

    def _decide(self) -> tuple[AddTarget, list[PlanItem]] | None:
        hits = self.selected_hits()
        problem = ""
        creating = self.initiative.currentData() == NEW
        if not hits:
            problem = strings.CHIAMATA_NEED_SELECTION
        elif self._case is not None and hits[0].template_key != self._case.key:
            problem = strings.CHIAMATA_OTHER_KEY.format(key=self._case.key)
        elif creating and not self.new_name.text().strip():
            problem = strings.OFFICINA_ADD_NEED_NAME
        self.error.setText(problem)
        self.error.setVisible(bool(problem))
        if problem:
            return None
        ini = None if creating else self._initiatives.get(self.initiative.currentData())
        name = self.new_name.text().strip() if creating else (ini.name if ini else "")
        # a case on its way cannot have its call changed: said BEFORE any question
        busy = next((c for h in hits for c in cases_of_key(ini, h.template_key)
                     if ini is not None and self._busy(ini.id, c.id)), None)
        if busy is not None:
            self.error.setText(strings.CHIAMATA_CASE_BUSY.format(case=busy.id))
            self.error.setVisible(True)
            return None
        variant = self.variant.text().strip()
        items: list[PlanItem] = []
        taken: set[str] = set()  # a case replaced once in this run is not offered again
        planned: dict[str, list[str]] = {}  # key -> the variants of its new cases in this run
        for hit in hits:
            key = hit.template_key
            cases = [c for c in cases_of_key(ini, key) if c.id not in taken]
            same_run = planned.get(key, [])
            if not cases and variant.casefold() not in {v.casefold() for v in same_run}:
                items.append(PlanItem(hit, None, variant))
                planned.setdefault(key, []).append(variant)
                continue
            own = self._case.id if self._case is not None and any(c.id == self._case.id for c in cases)                 else None
            answer = question.ask_resolution(self, hit, cases, initiative=name,
                                             default_replace=own, variant=variant, taken=list(same_run))
            if answer is None:
                return None  # the question was cancelled: back to the window
            if answer.replace is not None:
                taken.add(answer.replace)
            else:
                planned.setdefault(key, []).append(answer.variant)
            items.append(PlanItem(hit, answer.replace, answer.variant))
        target = AddTarget(name, True) if creating else AddTarget(self.initiative.currentData())
        return target, items

    def _take_row(self, index) -> None:
        if index.isValid() and index.row() < len(self._hits) and self._hits[index.row()].json_ok:
            self.table.selectRow(index.row())
            self.accept()

    def _sync_new_name(self) -> None:
        creating = self.initiative.currentData() == NEW and self._case is None
        self.new_name.setVisible(creating)
        self.new_name_label.setVisible(creating)
