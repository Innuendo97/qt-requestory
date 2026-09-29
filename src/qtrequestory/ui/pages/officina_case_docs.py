"""Filling the case workbench with a prepared comparison (a mixin of
``CaseView``): both documents, the case bar (progress, "= AS-IS", filters,
verification outcome), the differences list — with tabs for a judged TO-BE
(U3), the phase-1 list for the AS-IS view or a core that cannot judge — and
the highlights, the viewers following the list's kept selection.

The AS-IS view speaks the same visual language as a TO-BE (phase 2.5, U2,
U3, spec §5, D15): its counted differences from the target are drawn as "da
fare" — the whole work before the changes — and the bar shows their number
in the "da fare" pill; every other row of its list (tolerated by the
profile, variable, noise, page number / watermark) is drawn in its own look,
so selecting any row rings it on both pages. A TO-BE that could not be
judged stays neutral (its differences may be anything). After a review action only the verdicts
change: :meth:`show_rejudged` redraws them on the documents already on screen
(no reload, no jump to the top). Split from ``officina_case`` (size).
"""
from __future__ import annotations

import dataclasses

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from qtrequestory.ui.contracts import COUNTING, NO_VERDICT, CaseComparison, Comparison, Judged, Profile

from qtrequestory.ui import strings
from qtrequestory.ui.pages.officina_case_bar import filtered_count, same_as_asis
from qtrequestory.ui.pages.officina_docside import DocSide, version_label
from qtrequestory.ui.pages.officina_format import when
from qtrequestory.ui.pages.officina_jobs import CaseDocs
from qtrequestory.ui.pages.officina_judged import unjudged

__all__ = ["CaseDocsMixin", "asis_rows"]


def asis_rows(comparison: Comparison, profile: Profile) -> list[Judged]:
    """The AS-IS view's list in the TO-BE's language (U3): what ``profile``
    counts is "da fare" (the whole work), variables / noise / page number and
    watermark have no verdict, the rest is tolerated by the profile."""
    counted = COUNTING[profile]
    return [Judged(d, "da_fare") if d.klass in counted else Judged(d, None if d.klass in NO_VERDICT else "tollerata")
            for d in comparison.diffs]


class CaseDocsMixin:
    """``show_docs`` / ``show_failure`` of :class:`CaseView`."""

    def show_docs(self, docs: CaseDocs) -> None:
        """The prepared documents and their comparison (from ``load_case_docs``)."""
        self._show_docs(docs)

    def show_rejudged(self, cc: CaseComparison) -> None:
        """The same version judged again after a review action: new verdicts,
        list and highlights on the documents already shown."""
        if self.docs is None:
            return
        before = QApplication.focusWidget()
        self.docs = dataclasses.replace(self.docs, judged=cc)
        self._show_judgement(self.docs)
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
        self.hold_view = False  # new documents: the viewers go to the selection again
        self._show_side(self.left, docs.left.version, docs.left.path, docs.left.sizes,
                        docs.left.error, strings.OFFICINA_NO_TARGET)
        self._show_side(self.right, docs.right.version, docs.right.path, docs.right.sizes,
                        docs.right.error, strings.OFFICINA_NO_VERSION)
        right = docs.right.version
        self.right.info.setText(strings.OFFICINA_VERSION_INFO.format(
            env=right.meta.get("env", ""), when=when(right.created)) if right else "")
        self.right.slot.setText(version_label(right) if right else "")
        self.right.slot.setVisible(right is not None)
        self._show_judgement(docs)

    def _show_judgement(self, docs: CaseDocs) -> None:
        self.hide_bars()  # the difference under a bar may have changed state
        right = docs.right.version
        cc = docs.judged
        textless = cc is not None and not (cc.tobe.left_has_text and cc.tobe.right_has_text)
        # R49: a side without text has no verdict, so no bar either (only the note below)
        self.progress.show_summary(cc.summary if cc and not textless else None, cc.judged if cc else (),
                                   can_generate_asis=self.asis_action.isEnabled())
        two_way = (strings.REVISIONE_TWO_WAY_NO_TEXT if cc is not None and cc.asis is not None
                   and not (cc.asis.left_has_text and cc.asis.right_has_text) else strings.REVISIONE_TWO_WAY)
        self.progress.two_way.setToolTip(two_way)
        self.progress.two_way.setAccessibleName(two_way)
        self.banners.show_judged(self.case.folder if self.case else None, cc,
                                 right.number if right is not None and right.kind == "tobe" else None)
        self.progress.set_outcome(self.banners.outcome())
        env = self.case.env if self.case is not None else ""
        self.bar.set_same_as_asis(version_label(right) if right is not None and same_as_asis(cc) else None, env)
        self.bar.set_filters(filtered_count(cc))
        shown = cc.tobe if cc is not None else docs.comparison
        self._show_zones(shown)
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
            counted = docs.comparison.counting(docs.profile)
            if right is not None and right.kind == "asis":  # the whole work, drawn as "da fare"
                both = docs.comparison.left_has_text and docs.comparison.right_has_text
                if both and counted:  # the same tabs and groups, read-only (U3); every row
                    rows = asis_rows(docs.comparison, docs.profile)  # drawn in its own look (D15)
                    self.diffs.show_judged(rows, 0, {}, read_only=True)
                    self._highlight(rows)
                else:
                    self.diffs.show_comparison(docs.comparison, docs.profile)
                    self._highlight([Judged(d, "da_fare") for d in counted])
                if both:
                    self.progress.show_total(len(counted))
            else:
                self.diffs.show_comparison(docs.comparison, docs.profile)
                self._highlight([unjudged(d) for d in counted])
        else:
            self.left.view.set_highlights([])
            self.right.view.set_highlights([])
            if docs.compare_error:
                self.diffs.show_message(strings.OFFICINA_DIFF_ERROR.format(
                    reason=docs.compare_error), "bad")
            else:
                self.diffs.show_message(strings.OFFICINA_DIFF_NEED_BOTH)
        self.refresh_run_state()  # a verification may have used the marks up

    def _show_zones(self, comparison: Comparison | None) -> None:
        """The zone rails on both pages and the panel's zones summary (U3)."""
        left = tuple(comparison.left_zones) if comparison is not None else ()   # contract fields (M7)
        right = tuple(comparison.right_zones) if comparison is not None else ()
        self.left.view.set_zones(left)
        self.right.view.set_zones(right)
        self.diffs.set_zones(left + right)

    def _highlight(self, judged: list) -> None:
        self.left.view.set_highlights([(j, "left") for j in judged])
        self.right.view.set_highlights([(j, "right") for j in judged])
        current = self.diffs.current_id()  # a refill kept the selection: the viewers follow
        if current is not None:  # after an action from the page only the rings move (§4.2)
            self.sync.focus_difference(current, scroll=not self.hold_view)

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
