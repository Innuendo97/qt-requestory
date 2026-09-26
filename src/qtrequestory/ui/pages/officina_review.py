"""The review actions of the case on screen (a mixin of ``OfficinaPage``).

Spec §5.2, §5.3, §7.3: "segna fatta" (F, double click, mini-bar, menu),
"tollera" (T, mini-bar: no note; "Tollera…": a note), "non è una variabile"
(V, menu), "Annulla i segni" (the marks banner), their undo (Ctrl+Z, the
toast's "Annulla") and copying a difference's texts.

**Queued, never refused (R38).** Every request becomes an
:class:`~qtrequestory.ui.pages.officina_undo.Intent` on the case's FIFO queue
— undo requests too, so the entries come off the stack in order. The head of
the queue runs when the case is free: no compare of it running (it may be
verifying the marks) and no action being saved. Only then is it PLANNED
(``officina_undo``: the calls and the calls that undo them) against the
difference found by its anchor in the verdicts the previous item left — so
F on three rows marks three. F / T / V move the selection on to the next
row at once, before the refresh (R40), so F, F, F marks three consecutive
rows. A request keeps the version on screen when it was made (its undo
waits for that version, like Ctrl+Z); a "segna fatta" records the LATEST
TO-BE existing when it runs (R47), whatever version is on screen, so only a
newer generation verifies it.
A difference that is gone by then is skipped with a status line; a case left
with items waiting drops them, and says so.

The plan is saved in the ``officina-review`` worker (``officina_judge.act``:
under the case's review lock, then the same version judged again); the
verdicts on screen are redrawn from that comparison, the documents stay
where they are. The toast says what was done, with "Annulla"; the entry goes
on the undo stack only once the save succeeded, and is undone only on the
version it was made on (Ctrl+Z and the toast alike).
"""
from __future__ import annotations

from collections import deque
from functools import partial

from PySide6.QtWidgets import QApplication

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import CaseComparison, Judged
from qtrequestory.ui.pages import officina_dialogs as ask
from qtrequestory.ui.pages.officina_docside import version_key
from qtrequestory.ui.pages.officina_format import QUOTE_CHARS, elide
from qtrequestory.ui.pages.officina_judge import act
from qtrequestory.ui.pages.officina_rows import actions_for
from qtrequestory.ui.pages.officina_undo import (
    Entry,
    Intent,
    Step,
    mark_steps,
    tolerate_steps,
    unmark_all_steps,
    variable_steps,
)
from qtrequestory.ui.pages.officina_verdict_style import look_for
from qtrequestory.ui.workers import OFFICINA_REVIEW_JOB

__all__ = ["REVIEW_JOB", "ReviewActionsMixin"]

REVIEW_JOB = OFFICINA_REVIEW_JOB

Plan = tuple[list[Step], Entry, bool]  # (steps, entry, undoing)


def _what(j: Judged) -> str:
    return elide(j.diff.left_text or j.diff.right_text, QUOTE_CHARS // 2)


class ReviewActionsMixin:
    """``review_action``, ``unmark_all``, ``undo_review``, ``copy_difference``;
    the queue lives in ``self.review_queue`` ((initiative id, case id) → deque)."""

    def _connect_review(self) -> None:
        view = self.case_view
        view.review_action_requested.connect(self.review_action)
        view.unmark_all_requested.connect(self.unmark_all)
        view.undo_requested.connect(self.undo_review)
        view.action_unavailable.connect(self._explain_not_counting)
        view.copy_requested.connect(self.copy_difference)

    # -- requests (queued) ---------------------------------------------------------

    def review_action(self, diff_id: int, action: str) -> None:
        """"fatta" marks (or unmarks), "tollera" tolerates without a note (or
        stops tolerating), "tollera_nota" asks the note now (a dialog cannot
        wait in a queue), "non_variabile" turns a variable into text (or back)."""
        found = self._on_screen(diff_id)
        if found is None or action not in ("fatta", "tollera", "tollera_nota", "non_variabile"):
            return
        _case, cc, j = found
        note = ""
        if action == "tollera_nota":
            if j.verdict == "tollerata":
                action = "tollera"  # the menu said "Non tollerare più"
            else:
                note = ask.ask_tolerate_note(self, _what(j))
                if note is None:
                    return
        self._enqueue(Intent(action, j.diff.anchor, note, what=_what(j), version=cc.version))

    def unmark_all(self) -> None:
        """"Annulla i segni": every mark of the case goes (undoable: Ctrl+Z
        marks each one again, in its own version)."""
        if self._case(self.case_id) is not None:
            self._enqueue(Intent("unmark_all"))

    def undo_review(self) -> None:
        """Ctrl+Z: the last action of the case on screen, on the version on screen."""
        if self.ini is not None and self.case_id is not None and self.view() == "case":
            self._enqueue(Intent("undo"))

    def _undo_from_toast(self, key: tuple[str, str], entry: Entry) -> None:
        """The toast's "Annulla": that toast's action, if its case is still on screen."""
        if self.ini is not None and (self.ini.id, self.case_id) == key and self.view() == "case":
            self._enqueue(Intent("undo", entry=entry))

    def copy_difference(self, diff_id: int, side: str) -> None:
        found = self._on_screen(diff_id)
        if found is None:
            return
        diff = found[2].diff
        QApplication.clipboard().setText(diff.left_text if side == "left" else diff.right_text)
        self._toast(strings.AZIONI_COPIED_TARGET if side == "left" else strings.AZIONI_COPIED_GENERATED,
                    "ok")

    def _explain_not_counting(self, diff_id: int, _action: str) -> None:
        found = self._on_screen(diff_id)
        if found is not None:
            j = found[2]
            self._toast(strings.AZIONI_NOT_COUNTING.format(what=_what(j), state=look_for(j).label))

    # -- the queue ------------------------------------------------------------------

    def _enqueue(self, intent: Intent) -> None:
        self.review_queue.setdefault((self.ini.id, self.case_id), deque()).append(intent)
        self._pump_review()

    def _pump_review(self) -> None:
        """Start the head of the queue of the case on screen when it is free
        (called on every request, and when a review or compare job ends)."""
        here = (self.ini.id, self.case_id) if self.ini is not None and self.view() == "case" else None
        for key in [k for k in self.review_queue if k != here]:
            left = self.review_queue.pop(key)
            if left:
                self._notify(strings.AZIONI_DROPPED.format(n=len(left)))
        queue = self.review_queue.get(here) if here is not None else None
        while queue and not (self.case_view.judging or self.case_view.acting):
            plan = self._plan(queue.popleft())
            if plan is not None and self._submit(*plan):
                return  # the job's end pumps again

    def _plan(self, intent: Intent) -> Plan | None:
        """The calls of ``intent`` against the verdicts on screen now; None
        (with a status line when it helps) when there is nothing to do."""
        case = self._case(self.case_id)
        docs = self.case_view.docs
        cc = docs.judged if docs is not None else None
        if case is None:
            return None
        if intent.kind == "undo":
            return self._plan_undo(intent, cc)
        if intent.kind == "unmark_all":
            forward, undo = unmark_all_steps(case.review, cc.judged if cc is not None else ())
            text = strings.REVISIONE_UNMARKED.format(n=len(case.review.marks))
            return forward, Entry(text, cc.version if cc is not None else -1, tuple(undo)), False
        j = next((x for x in cc.judged if x.diff.anchor == intent.anchor), None) if cc else None
        if j is None:
            self._notify(strings.AZIONI_GONE.format(what=intent.what))
            return None
        what = _what(j)
        version = intent.version if intent.version is not None else cc.version
        if intent.kind == "fatta":
            if "fatta" not in actions_for(j):
                return None  # it stopped counting meanwhile (F explained it when it could)
            latest = case.latest_tobe()
            forward, undo = mark_steps(j, case.review, max(version, latest.number if latest else version))
            text = (strings.ELENCO_UNMARKED if j.marked else strings.ELENCO_MARKED).format(what=what)
        elif intent.kind in ("tollera", "tollera_nota"):
            by_hand = any(t.anchor == j.diff.anchor for t in case.review.tolerances)
            if j.verdict == "tollerata" and not by_hand:
                self._notify(strings.ELENCO_TOLERATED_BY_PROFILE.format(what=what))
                return None
            forward, undo = tolerate_steps(j, case.review, intent.note,
                                           toggle=intent.kind == "tollera")
            text = (strings.ELENCO_UNTOLERATED if forward[0][0] == "untolerate"
                    else strings.ELENCO_TOLERATED).format(what=what)
        elif intent.kind == "non_variabile":
            forward, undo = variable_steps(j, case.review)
            text = (strings.ELENCO_VARIABLE_AGAIN if forward[0][0] == "variable_again"
                    else strings.ELENCO_NOT_VARIABLE).format(what=what)
        else:
            return None
        return forward, Entry(text, version, tuple(undo)), False

    def _plan_undo(self, intent: Intent, cc: CaseComparison | None) -> Plan | None:
        """Ctrl+Z: the last entry, if made on the version on screen. The
        toast: its own entry, while it is still undoable on this version."""
        key = (self.ini.id, self.case_id)
        entry = intent.entry
        if entry is None:
            entry = self.undo.top(key, cc.version) if cc is not None else None
            if entry is None:
                self._notify(strings.AZIONI_NOTHING_TO_UNDO)
                return None
        elif cc is None or entry.version != cc.version or not self.undo.holds(key, entry):
            return None  # an old toast: another version on screen, or already undone
        return list(entry.undo), entry, True

    # -- the job ----------------------------------------------------------------

    def _on_screen(self, diff_id: int) -> tuple | None:
        """``(case, judged comparison, Judged)`` of a difference on screen."""
        case = self._case(self.case_id)
        docs = self.case_view.docs
        cc = docs.judged if docs is not None else None
        j = next((x for x in cc.judged if x.diff.id == diff_id), None) if cc is not None else None
        return None if case is None or j is None else (case, cc, j)

    def _submit(self, steps: list[Step], entry: Entry, undoing: bool) -> bool:
        case = self._case(self.case_id)
        docs = self.case_view.docs
        if case is None or self.ini is None:
            return False
        version = docs.right.version if docs is not None else None
        key = version_key(version) if version is not None else None
        job = self.runner.submit(REVIEW_JOB, act, self.services, self.ini, case,
                                 version if version is not None and version.kind == "tobe" else None,
                                 steps)
        if job is None:  # the application is closing
            return False
        self.case_view.set_acting(True)
        where = (self.ini.id, case.id)
        job.signals.result.connect(partial(self._on_review_saved, where, key, entry, undoing))
        job.signals.error.connect(partial(self._on_review_failed, where, undoing))
        job.signals.finished.connect(self._on_review_finished)
        return True

    def _on_review_finished(self) -> None:
        self.case_view.set_acting(False)
        self._pump_review()

    def _on_review_saved(self, where: tuple[str, str], key: str | None, entry: Entry, undoing: bool,
                         cc: CaseComparison | None) -> None:
        action = None
        if undoing:
            self.undo.discard(where, entry)
            message = strings.AZIONI_UNDONE.format(action=entry.text)
        else:
            self.undo.push(where, entry)
            message = entry.text
            action = (strings.AZIONI_UNDO, partial(self._undo_from_toast, where, entry))
        self._refresh_reviewed(where, key, cc)
        self._toast(message, "ok", action=action, hint=strings.AZIONI_UNDO_KEY if action else "")

    def _on_review_failed(self, where: tuple[str, str], undoing: bool, _kind: str, message: str) -> None:
        self._notify((strings.AZIONI_UNDO_FAILED if undoing else strings.ELENCO_ACTION_FAILED)
                     .format(reason=message))
        self._refresh_reviewed(where, None, None)

    def _refresh_reviewed(self, where: tuple[str, str], key: str | None,
                          cc: CaseComparison | None) -> None:
        """Re-read the initiative (the case's review changed on disk) and
        redraw the verdicts — or the whole case when there is no fresh
        comparison of the version still on screen."""
        ini_id, case_id = where
        if self.ini is None or self.ini.id != ini_id or not self._reload_initiative():
            return
        if self.view() != "case" or self.case_id != case_id:
            return
        view = self.case_view
        docs = view.docs
        if (cc is None or key is None or view.current_version_key() != key or docs is None
                or docs.judged is None or docs.judged.version != cc.version):
            self.open_case(case_id)
            return
        view.show_case(self._case(case_id), self.ini.name, key, blocked=bool(self.ini.load_error),
                       initiative_profile=self.ini.profile)
        view.show_rejudged(cc)
