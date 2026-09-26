"""The generations of the Officina tab (a mixin of ``OfficinaPage``): the
board's and the workbench's "Rigenera"/"Genera AS-IS mancanti", the delivery
dialog, and the slots of the page's ``GenerationQueue`` (run state, a case
finished, the batch progress). Split from ``officina_page`` (size); every
method runs on the page and uses its helpers (``_case``, ``_run_state``,
``_reload_initiative``, ``open_case``, ``_notify``, ``_toast``).
"""
from __future__ import annotations

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import Case, SendResult, Version
from qtrequestory.ui.pages.officina_docside import version_key

__all__ = ["GenerationMixin"]


class GenerationMixin:
    """Generation requests and the queue's slots."""

    # -- actions: generation ------------------------------------------------

    def regenerate_tobe(self, case_ids: list[str | None]) -> None:
        cases = [c for c in (self._case(i) for i in case_ids if i) if c is not None]
        if not cases:
            self._notify(strings.OFFICINA_NOTHING_SELECTED)
            return
        self._generate(cases, "tobe")

    def generate_missing_asis(self) -> None:
        cases = [c for c in (self.ini.cases if self.ini else [])
                 if c.asis() is None and not c.load_error]
        if not cases:
            self._notify(strings.OFFICINA_NO_MISSING_ASIS)
            return
        self._generate(cases, "asis")

    def deliver(self) -> None:
        """The board's "Consegna…": the dialog runs the delivery itself."""
        if self.ini is None or not self._reload_initiative():
            return
        from qtrequestory.ui.pages import officina_delivery

        officina_delivery.open_delivery_dialog(self, self.services, self.runner, self.ini)

    # -- jobs ------------------------------------------------------------------

    def _generate(self, cases: list[Case], kind: str, note: str | None = None) -> None:
        if self.ini is None:
            return
        waiting = {c.id for c in cases if self._run_state(c.id) is not None}
        for case in cases:
            if case.id not in waiting:
                self.failures.pop((self.ini.id, case.id), None)
                self.cancelled.discard((self.ini.id, case.id))
        skipped = self.queue.enqueue(self.ini, cases, kind, note)
        if skipped:
            self._notify(strings.OFFICINA_ALREADY_QUEUED.format(
                cases=", ".join(c.id for c in skipped)))
        self._on_run_state()

    def _on_run_state(self, *_ids: str) -> None:
        self.board.refresh_run_states()
        self.case_view.refresh_run_state()

    def _on_case_finished(self, initiative: str, case_id: str, _kind: str,
                          version: Version | None, result: SendResult,
                          cancelled: bool = False) -> None:
        if cancelled:
            self.cancelled.add((initiative, case_id))  # neutral: nothing went wrong
        elif version is None:
            status = (strings.OFFICINA_HTTP_STATUS.format(status=result.status)
                      if result.status else "")
            self.failures[(initiative, case_id)] = strings.OFFICINA_GENERATION_FAILED.format(
                status=status, reason=result.reason)
        else:
            self.failures.pop((initiative, case_id), None)
        if self.ini is None or self.ini.id != initiative:
            return  # another initiative is on screen: it reads the disk when shown
        if self.view() == "case" and self.case_id == case_id and version is None:
            self.case_view.set_failure(self._failure(case_id) or "")
            self.case_view.refresh_run_state()
            return
        if not self._reload_initiative():
            return
        if self.view() == "board":
            self.board.show_initiative(self.ini)
            self.board.refresh_run_states()  # a new TO-BE: its pill says «da riconfrontare»
        elif self.view() == "case" and self.case_id == case_id:
            self.open_case(case_id, version_key(version))

    def _show_progress(self, done: int, total: int) -> None:
        """The batch line belongs to the initiative whose cases are running."""
        mine = self.ini is not None and self.ini.id in self.queue.initiatives()
        self.board.set_progress(done, total if mine else 0)

    def _on_batch_finished(self, ok: int, failed: int) -> None:
        self.board.set_progress(0, 0)
        if ok + failed > 1:
            self._toast(strings.OFFICINA_BATCH_DONE.format(ok=ok, failed=failed),
                        "ok" if not failed else "warn")
