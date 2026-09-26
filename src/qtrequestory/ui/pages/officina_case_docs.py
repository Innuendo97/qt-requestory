"""Filling the case workbench with a prepared comparison (a mixin of
``CaseView``): both documents, the progress bar and the banners, the
differences list — with tabs for a judged TO-BE (U3), the phase-1 list for the
AS-IS view or a core that cannot judge — and the highlights, the viewers
following the list's kept selection. After a review action only the
verdicts change: :meth:`show_rejudged` redraws them on the documents already
on screen (no reload, no jump to the top). Split from ``officina_case`` (size).
"""
from __future__ import annotations

import dataclasses

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from qtrequestory.ui.contracts import CaseComparison

from qtrequestory.ui import strings
from qtrequestory.ui.pages.officina_docside import DocSide
from qtrequestory.ui.pages.officina_format import when
from qtrequestory.ui.pages.officina_jobs import CaseDocs
from qtrequestory.ui.pages.officina_judged import unjudged

__all__ = ["CaseDocsMixin"]


class CaseDocsMixin:
    """``show_docs`` / ``show_failure`` of :class:`CaseView`."""

    def show_docs(self, docs: CaseDocs) -> None:
        """The prepared documents and their comparison (from ``load_case_docs``)."""
        self._filling = True
        try:
            self._show_docs(docs)
        finally:
            self._filling = False

    def show_rejudged(self, cc: CaseComparison) -> None:
        """The same version judged again after a review action: new verdicts,
        list and highlights on the documents already shown."""
        if self.docs is None:
            return
        before = QApplication.focusWidget()
        self._filling = True
        try:
            self.docs = dataclasses.replace(self.docs, judged=cc)
            self._show_judgement(self.docs)
        finally:
            self._filling = False
        if (before is not None and self.isAncestorOf(before)
                and QApplication.focusWidget() is not before):
            # e.g. the tab emptied and the list hid: Qt passed the focus to
            # the next button; F, T and Ctrl+Z must keep working
            if before.isVisible():
                before.setFocus(Qt.FocusReason.OtherFocusReason)
            else:
                self.focus_default()

    def _show_docs(self, docs: CaseDocs) -> None:
        self.docs = docs
        self._show_side(self.left, docs.left.version, docs.left.path, docs.left.sizes,
                        docs.left.error, strings.OFFICINA_NO_TARGET)
        self._show_side(self.right, docs.right.version, docs.right.path, docs.right.sizes,
                        docs.right.error, strings.OFFICINA_NO_VERSION)
        right = docs.right.version
        self.right.info.setText(strings.OFFICINA_VERSION_INFO.format(
            env=right.meta.get("env", ""), when=when(right.created)) if right else "")
        self._show_judgement(docs)

    def _show_judgement(self, docs: CaseDocs) -> None:
        self.hide_bars()  # the difference under a bar may have changed state
        right = docs.right.version
        cc = docs.judged
        textless = cc is not None and not (cc.tobe.left_has_text and cc.tobe.right_has_text)
        # R49: a side without text has no verdict, so no bar either (only the note below)
        self.progress.show_summary(cc.summary if cc and not textless else None, cc.judged if cc else (),
                                   can_generate_asis=self.asis_button.isEnabled())
        self.progress.two_way.setToolTip(
            strings.REVISIONE_TWO_WAY_NO_TEXT if cc is not None and cc.asis is not None
            and not (cc.asis.left_has_text and cc.asis.right_has_text) else strings.REVISIONE_TWO_WAY)
        self.banners.show_judged(self.case.folder if self.case else None, cc,
                                 right.number if right is not None and right.kind == "tobe" else None)
        self.progress.set_outcome(self.banners.collapsed_outcome())
        if cc is not None:  # a judged TO-BE: the list with tabs (U3)
            if textless:
                self.diffs.show_message(cc.tobe.note, "warn")  # a side without text: not "uguale"
            elif cc.judged:
                since = {a: v for a, v, _text in self.case.review.unresolved} if self.case else {}
                self.diffs.show_judged(cc.judged, cc.version, since, cc.inactive)
            else:
                self.diffs.show_message(strings.OFFICINA_DIFF_EQUAL, "ok")
            self._highlight(list(cc.judged))
        elif docs.comparison is not None:  # the AS-IS, or a core that cannot judge: no verdicts,
            # only what the case's profile counts
            self.diffs.show_comparison(docs.comparison, docs.profile)
            self._highlight([unjudged(d) for d in docs.comparison.counting(docs.profile)])
        else:
            self.left.view.set_highlights([])
            self.right.view.set_highlights([])
            if docs.compare_error:
                self.diffs.show_message(strings.OFFICINA_DIFF_ERROR.format(
                    reason=docs.compare_error), "bad")
            else:
                self.diffs.show_message(strings.OFFICINA_DIFF_NEED_BOTH)
        self.refresh_run_state()  # a verification may have used the marks up

    def _highlight(self, judged: list) -> None:
        self.left.view.set_highlights([(j, "left") for j in judged])
        self.right.view.set_highlights([(j, "right") for j in judged])
        current = self.diffs.current_id()  # a refill kept the selection: the viewers follow
        if current is not None:
            self.sync.focus_difference(current)

    def show_failure(self, text: str) -> None:
        """The documents could not be prepared at all."""
        for side in (self.left, self.right):
            if not side.showing_document():
                side.show_message(text)
        self.diffs.show_message(text, "bad")
        self.progress.show_summary(None, [])

    @staticmethod
    def _show_side(side: DocSide, version, path, sizes, error: str, empty: str) -> None:
        if version is None:
            side.show_message(empty)
        elif error or path is None:
            side.show_message(error)
        else:
            side.show_document(path, sizes)
