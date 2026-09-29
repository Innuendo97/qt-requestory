"""'Elimina iniziativa' (phase 2.5, D6): the Officina's use of the undoable
deletion queue (``ui/pending_delete``).

The trash button of a row, its right-click menu and Canc all come to
:meth:`InitiativeDeletionMixin.delete_initiative`:

1. an initiative open on screen is closed first (the page goes to the list);
2. an initiative with cases waiting or being generated, or while a delivery
   or "Aggiungi chiamata…" writes, is not deleted (a message says why);
3. the row disappears at once and the window's bar counts 5 s down. A pending
   initiative is hidden EVERYWHERE (:meth:`listed_initiatives`: the list, the
   add choosers, Ricerca's "Aggiungi all'Officina…"), cannot be opened, and
   "Nuova iniziativa" with its name says to undo or wait;
4. at the deadline the checks of 2 are made AGAIN (it may have been reached
   another way): if busy it is restored with a message, else
   ``OfficinaApi.delete_initiative`` deletes the folder for good (path checks
   in ``officina.remove``); a folder already gone counts as deleted. The
   background control generations are not a reason to refuse: the deletion
   cancels them itself (they then write nothing);
5. "Annulla" (the bar, Ctrl+Z in the list or on the bar) puts the row back,
   selected; a failure (a file in use, a refused path) puts it back with a
   sentence in a toast.

The queue is the window's (``MainWindow.deletions``, flushed when the window
closes); a page built without a window (tests) makes its own.
"""
from __future__ import annotations

import os
from functools import partial

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import Initiative
from qtrequestory.ui.pending_delete import PendingDeletions, failure_reason
from qtrequestory.ui.workers import (
    OFFICINA_ADD_JOB,
    OFFICINA_COMPARE_JOB,
    OFFICINA_DELIVERY_JOB,
    OFFICINA_DOM_JOB,
    OFFICINA_GENERATE_JOBS,
    OFFICINA_NOISE_JOB,
    OFFICINA_REVIEW_JOB,
)

__all__ = ["FAILURE_TOAST_MS", "WRITER_JOBS", "DeletionBusy", "InitiativeDeletionMixin", "deletion_reason"]

#: Every job that writes inside an initiative folder (versions, caches,
#: review state, copies): while one runs no initiative is deleted — they run
#: for the initiative that was open, so the price is a rare "riprova".
#: Only "officina-pick" (the search of calls) writes nothing.
WRITER_JOBS = (*OFFICINA_GENERATE_JOBS, OFFICINA_COMPARE_JOB, OFFICINA_REVIEW_JOB, OFFICINA_NOISE_JOB,
               OFFICINA_DOM_JOB, OFFICINA_DELIVERY_JOB, OFFICINA_ADD_JOB)
#: A failure stays on screen long enough to be read.
FAILURE_TOAST_MS = 9000


class DeletionBusy(Exception):
    """The commit-time re-check found the initiative in use: restored, not deleted."""


def deletion_reason(exc: BaseException) -> str:
    """Why an initiative was not deleted, for the user (never a raw path)."""
    if isinstance(exc, DeletionBusy):
        return strings.ELIMINA_REASON_BUSY
    if isinstance(exc, ValueError):
        return strings.ELIMINA_REASON_REFUSED
    return failure_reason(exc)


class InitiativeDeletionMixin:
    """Mixed into ``OfficinaPage`` (needs ``list``, ``api``, ``queue``,
    ``runner``, ``ini``, ``case_id``, ``failures``, ``cancelled``, ``view()``,
    ``show_list()``, ``_notify()``)."""

    def _init_deletions(self, window: object | None) -> None:
        queue = getattr(window, "deletions", None)
        self.deletions = queue if isinstance(queue, PendingDeletions) else PendingDeletions(self)
        self.list.delete_requested.connect(self.delete_initiative)
        self.list.undo_requested.connect(self.deletions.undo_last)

    @staticmethod
    def deletion_key(ini: Initiative) -> str:
        """The queue key of ``ini``: its folder (another Officina folder's
        same-named initiative is another one)."""
        return "officina-iniziativa:" + os.path.normcase(str(ini.folder))

    def visible_initiatives(self, initiatives: list[Initiative]) -> list[Initiative]:
        """``initiatives`` without the ones waiting to be deleted."""
        return [ini for ini in initiatives if not self.deletions.is_pending(self.deletion_key(ini))]

    def listed_initiatives(self) -> list[Initiative]:
        """Every initiative the user may see or pick: the list, the add
        choosers, Ricerca's "Aggiungi all'Officina…" (never a pending one)."""
        return self.visible_initiatives(self.api.initiatives())

    def pending_initiative(self, initiative_id: str) -> Initiative | None:
        """The initiative ``initiative_id`` when it is waiting to be deleted."""
        return next((ini for ini in self.api.initiatives()
                     if ini.id == initiative_id and self.deletions.is_pending(self.deletion_key(ini))), None)

    def pending_named(self, name: str) -> bool:
        """True when an initiative waiting to be deleted has this name (or folder)."""
        wanted = name.strip().casefold()
        return any(wanted in (ini.name.casefold(), ini.id.casefold())
                   for ini in self.api.initiatives() if self.deletions.is_pending(self.deletion_key(ini)))

    def initiative_busy(self, initiative_id: str) -> bool:
        """Open on screen, cases waiting or being generated, or any job that
        writes inside an initiative running (:data:`WRITER_JOBS`): not now."""
        return (initiative_id in self.queue.initiatives()
                or (self.ini is not None and self.ini.id == initiative_id)
                or any(self.runner.is_running(name) for name in WRITER_JOBS))

    def delete_initiative(self, initiative_id: str) -> None:
        """Hide ``initiative_id`` now, delete it for good in 5 s unless undone."""
        if self.ini is not None and self.ini.id == initiative_id:
            self.ini, self.case_id = None, None  # an initiative on screen is closed first
        try:
            ini = self.api.load(initiative_id)
        except (FileNotFoundError, OSError, ValueError):
            self._notify(strings.OFFICINA_INITIATIVE_GONE.format(name=initiative_id))
            self.show_list()
            return
        if self.initiative_busy(initiative_id):
            self._say(strings.ELIMINA_BUSY.format(name=ini.name), "warn")
            return
        row = self.list.row_of(initiative_id)
        self.deletions.schedule(
            self.deletion_key(ini),
            strings.ELIMINA_INITIATIVE_DONE.format(name=ini.name),
            strings.ELIMINA_INITIATIVE_ROW.format(name=ini.name),
            partial(self._commit_deletion, ini),
            on_undo=partial(self._deletion_undone, ini.id),
            on_done=partial(self._deletion_done, ini.id),
            on_failed=partial(self._deletion_failed, ini),
            explain=partial(self._deletion_reason, ini),
        )
        self.show_list()
        self.list.select_near(row if row >= 0 else 0)
        if self.view() == "list":
            self.list.table.setFocus()

    # -- the queue's callbacks -----------------------------------------------------

    def _commit_deletion(self, ini: Initiative) -> None:
        """At the deadline: re-check (it may have been reached another way
        meanwhile), then delete for good."""
        if self.initiative_busy(ini.id):
            raise DeletionBusy(ini.id)
        try:
            self.api.delete_initiative(ini)
        except FileNotFoundError:
            pass  # already gone: what the user wanted

    def _deletion_undone(self, initiative_id: str) -> None:
        self._show_again(initiative_id)

    def _deletion_done(self, initiative_id: str) -> None:
        self.failures = {k: v for k, v in self.failures.items() if k[0] != initiative_id}
        self.cancelled = {k for k in self.cancelled if k[0] != initiative_id}

    def _root_changed(self, ini: Initiative) -> bool:
        root = self.api.workspace_root()
        return root is None or os.path.normcase(str(root)) != os.path.normcase(str(ini.folder.parent))

    def _deletion_reason(self, ini: Initiative, exc: BaseException) -> str:
        """The item's ``explain``: also used by the window's close warning."""
        if isinstance(exc, ValueError) and self._root_changed(ini):
            return strings.ELIMINA_REASON_ROOT_CHANGED
        return deletion_reason(exc)

    def _deletion_failed(self, ini: Initiative, exc: BaseException) -> None:
        if isinstance(exc, ValueError) and self._root_changed(ini):
            text = strings.ELIMINA_FAILED_ROOT_CHANGED.format(name=ini.name)  # not in this list
        else:
            text = strings.ELIMINA_FAILED.format(name=ini.name, reason=deletion_reason(exc))
        self._say(text, "bad", FAILURE_TOAST_MS)
        self._show_again(ini.id)

    def _show_again(self, initiative_id: str) -> None:
        """The row is back: on screen at once when the list is."""
        if self.view() != "list" or not self.isVisible():
            return
        self.show_list()
        row = self.list.row_of(initiative_id)
        if row >= 0:
            self.list.table.selectRow(row)

    def _say(self, text: str, tone: str, ms: int = FAILURE_TOAST_MS) -> None:
        toast = getattr(self._window, "show_toast", None)
        if callable(toast):
            toast(text, tone, ms)
        else:
            self._notify(text)
