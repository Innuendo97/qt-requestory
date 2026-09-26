"""The comparison jobs of the Officina tab (a mixin of ``OfficinaPage``).

The workbench's documents and judged comparison (``load_case_docs`` in the
``officina-compare`` job). The board has no job of its own: its pills read
``case.review.summary``, which the page keeps in step with the comparison it
was handed (:meth:`_on_docs`). While the compare job of
the case on screen runs, the case view knows (``CaseView.set_judging``): the
profile menu waits for it and the review actions queue behind it
(``officina_review``, R38), because the worker may be verifying the marks of
the same case. Split from
``officina_page`` (size); every method runs on the page.
"""
from __future__ import annotations

from functools import partial

from qtrequestory.ui import strings
from qtrequestory.ui.pages.officina_jobs import COMPARE_JOB, load_case_docs

__all__ = ["CompareJobsMixin"]


class CompareJobsMixin:
    """``_load_docs`` and its slots."""

    def _load_docs(self, key: str | None) -> None:
        case = self._case(self.case_id)
        if case is None:
            return
        self.case_view.show_loading()
        job = self.runner.submit(COMPARE_JOB, load_case_docs, self.services, case,
                                 self.case_view.version(key), self.ini)
        self._compare_job = job
        if job is not None:
            self.case_view.set_judging(True)
            job.signals.result.connect(self._on_docs)
            job.signals.error.connect(self._on_docs_error)
            job.signals.finished.connect(partial(self._on_docs_finished, job))

    def _on_docs_finished(self, job) -> None:
        """The compare job is over (a superseded one stays silent: the newer one reports)."""
        if job is getattr(self, "_compare_job", None):
            self._compare_job = None
            self.case_view.set_judging(False)
            self._pump_review()  # review requests wait for the compare, never refused (R38)

    def _on_docs(self, docs) -> None:
        self._keep_summary(docs)
        if self.view() == "case" and docs.case_id == self.case_id:
            self.case_view.show_docs(docs)

    def _keep_summary(self, docs) -> None:
        """The board reads ``case.review.summary``: the one ``compare_case``
        just saved is copied onto the case in memory, whatever the core did
        with the object it was given (the disk already has it)."""
        judged = docs.judged
        case = self._case(docs.case_id)
        if judged is not None and case is not None and judged.summary is not None:
            case.review.summary = judged.summary

    def _on_docs_error(self, _kind: str, message: str) -> None:
        """An unexpected failure preparing the documents: a sentence, not a
        workbench stuck on "Preparazione…" (the traceback is in app.log)."""
        if self.view() == "case":
            self.case_view.show_failure(strings.OFFICINA_DIFF_ERROR.format(reason=message))
