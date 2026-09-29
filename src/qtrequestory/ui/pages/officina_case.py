"""The case workbench: TARGET on the left, AS-IS or a TO-BE on the right.

Phase 2.5 (U2, spec §5, D15, draft "f25-caso-v2"): ONE bar of 36 px over the
documents (``officina_case_bar``) holds the case, the version switch, the
"= AS-IS" chip, the compact progress, the chips that were strips, "Rigenera
(F5)", "Filtri (n)" and "⋯" with the other commands; the documents start
right under it (≤ 80 px from the top of the view at 1366x768)::

    ‹ MOD_TEST_A · abilitato [AS-IS|v1|v2] (= AS-IS) 60% ▲1 ○3 ✓2 …   [Rigenera (F5)] [Filtri (6)] [⋯]
    +-------- TARGET --------+---------- v2 ----------+-- Differenze --+
    | DocView                | DocView                | list           |
    +------------------------+------------------------+----------------+

The two viewers scroll and zoom together (``SyncController``); a click on a
difference, in the list or on a highlight, focuses it in both. Documents and
the comparison are prepared in the ``officina-compare`` job (an HTML goes
through Edge), so opening a case never blocks the window.

For a TO-BE the job also asks ``compare_case``; when it judged, the viewers
draw the differences by verdict (``officina_verdict_style``) and the list
shows them in tabs (``officina_diffs``). The AS-IS is drawn in the same
visual language: its differences from the target are the whole work, "da
fare" (``officina_case_docs``). The actions from the documents — mini-bar,
double click, right-click menu, F / T / V in the viewers, Ctrl+Z
(``officina_actions_bar``); after an action the page redraws the verdicts
with :meth:`CaseView.show_rejudged`, the documents stay. "Filtri (n)" opens
"Filtri del confronto" (U4, ``officina_filters_page``), whose occurrences
come back here (:meth:`CaseView.show_occurrence`); for an HTML case the
"Documenti | DOM" switch sits in the bar (``officina_dom``).

A case whose ``caso.json`` is unreadable can be looked at, not changed: the
editor, "Segna accettato" and the generations are disabled (saving it would
wipe what the file holds). The generations are disabled too while the
initiative's ``iniziativa.json`` is unreadable (``blocked``), and everything
that changes the case while it waits or runs.
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QSplitter, QVBoxLayout, QWidget

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import Case, Version
from qtrequestory.ui.pages.officina_actions_bar import ReviewInputMixin
from qtrequestory.ui.pages.officina_banners import ReviewBanners, live_marks
from qtrequestory.ui.pages.officina_case_bar import CaseBar
from qtrequestory.ui.pages.officina_case_docs import CaseDocsMixin
from qtrequestory.ui.pages.officina_case_extras import CaseExtrasMixin
from qtrequestory.ui.pages.officina_progress import remaining_text
from qtrequestory.ui.pages.officina_verdict_style import board_counts, pill_counts
from qtrequestory.ui.pages.officina_diffs import DiffPanel
from qtrequestory.ui.pages.officina_dom_view import DomViewMixin
from qtrequestory.ui.pages.officina_docside import DocSide, VersionSwitch, case_versions, version_key
from qtrequestory.ui.pages.officina_format import case_notice, case_title
from qtrequestory.ui.pages.officina_jobs import CaseDocs
from qtrequestory.ui.pages.officina_judged import unjudged
from qtrequestory.ui.pages.officina_viewer import SyncController

__all__ = ["CaseView", "REGENERATE_SHORTCUT", "notice_label"]

REGENERATE_SHORTCUT = "F5"
#: TARGET : generated document, as the splitter first opens; the side panel
#: has its own fixed width (292 px, or its 40 px rail: phase 2.5, U3).
SPLIT = (5, 5)
LEFT_DOC_ID = "officina-target"
RIGHT_DOC_ID = "officina-generated"


def notice_label(case: Case) -> str:
    """The short text of the notice chip (the whole notice is its tooltip)."""
    if case.load_error:
        return strings.OFFICINA_STATUS_BROKEN
    if (case.reopened and case.status != "accepted") or (
            case.status == "accepted" and not case.acceptance_is_current()):
        return strings.OFFICINA_STATUS_REOPENED
    return strings.BARRA_NOTICE


class CaseView(DomViewMixin, CaseExtrasMixin, ReviewInputMixin, CaseDocsMixin, QWidget):
    """One case: the two documents, the differences and the case actions."""

    back_requested = Signal()
    regenerate_requested = Signal()      # a new TO-BE
    asis_requested = Signal()            # the AS-IS (the page asks for a note if one exists)
    target_requested = Signal()
    editor_requested = Signal()
    status_toggle_requested = Signal()
    version_chosen = Signal(str)         # version_key
    unmark_all_requested = Signal()      # "Annulla i segni"
    profile_chosen = Signal(object)      # a Profile, or None = the initiative's
    #: (Diff.id, "fatta" | "tollera" | "tollera_nota" | "non_variabile"); "tollera_nota" = "Tollera…"
    review_action_requested = Signal(int, str)
    action_unavailable = Signal(int, str)  # F on a difference that does not count
    copy_requested = Signal(int, str)      # (Diff.id, "left" = target text | "right" = generated)
    undo_requested = Signal()              # Ctrl+Z
    filters_requested = Signal()           # "Filtri (n)": "Filtri del confronto" (U4)
    reset_tolerances_requested = Signal()  # "⋯" → "Azzera tolleranze…" (R45)
    change_call_requested = Signal()       # "⋯" → "Cambia chiamata…" (A1)
    asis_after_call_requested = Signal()   # the call strip's "Rigenera AS-IS" (A1)
    dom_requested = Signal(object, object, object)  # (key, Case, Version): the DOM tab's sources

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.case: Case | None = None
        self.docs: CaseDocs | None = None
        #: "queued" | "running" | None for the case on screen (the page's queue).
        self.run_state: Callable[[str], str | None] = lambda _case_id: None
        #: The initiative cannot generate (its iniziativa.json is unreadable).
        self.blocked = False
        #: A compare job of this case is running: the review writes wait (U2 fix).
        self.judging = False

        self.switch = VersionSwitch()
        self._init_dom_widgets()
        self.bar = CaseBar(self.switch, self.view_switch)
        bar = self.bar
        # the bar's widgets under the names the page and the tests use
        self.back_button, self.title, self.status = bar.back_button, bar.title, bar.status
        self.regenerate_button, self.busy, self.progress = bar.regenerate_button, bar.busy, bar.progress
        self.filters_button, self.more_button = bar.filters_button, bar.more_button
        self.asis_action, self.target_action, self.editor_action = (
            bar.asis_action, bar.target_action, bar.editor_action)
        self.accept_action, self.unmark_action = bar.accept_action, bar.unmark_action
        self.change_call_action = bar.change_call_action
        self.reset_tolerances_action = bar.reset_tolerances_action
        self.profile_menu = bar.profile_menu
        self.call_strip, self.notice, self.banner = bar.call_chip, bar.notice_chip, bar.failure_chip
        self.banners = ReviewBanners()

        self.left = DocSide(strings.OFFICINA_SIDE_TARGET, LEFT_DOC_ID)
        self.right = DocSide("", RIGHT_DOC_ID)
        self.right.slot.setVisible(False)
        self.diffs = DiffPanel()
        self.sync = SyncController(self.left.view, self.right.view)

        self.shortcut = QShortcut(QKeySequence(REGENERATE_SHORTCUT), self)
        self.shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._init_extras()
        self._build()
        self._connect()
        self._connect_dom()
        self._init_review_input()  # after _connect: a click selects, THEN the bar opens

    def _build(self) -> None:
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        for widget in (self.left, self.right, self.diffs):
            self.splitter.addWidget(widget)
        self.splitter.insertWidget(2, self.dom)  # hidden until "DOM" (HTML cases)
        for index, share in enumerate(SPLIT):
            self.splitter.setStretchFactor(index, share)
        self.splitter.setStretchFactor(2, SPLIT[0] + SPLIT[1])
        self.splitter.setStretchFactor(3, 0)
        self.diffs.collapsed_changed.connect(lambda _on: self._fit_panel())
        self._split_done = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE[0])
        layout.addWidget(self.bar)
        layout.addWidget(self.splitter, 1)

    def _connect(self) -> None:
        self.back_button.clicked.connect(self.back_requested)
        self.regenerate_button.clicked.connect(self.regenerate_requested)
        self.shortcut.activated.connect(self._on_f5)
        self.asis_action.triggered.connect(lambda _c=False: self.asis_requested.emit())
        self.target_action.triggered.connect(lambda _c=False: self.target_requested.emit())
        self.editor_action.triggered.connect(lambda _c=False: self.editor_requested.emit())
        self.accept_action.triggered.connect(lambda _c=False: self.status_toggle_requested.emit())
        self.unmark_action.triggered.connect(lambda _c=False: self.unmark_all_requested.emit())
        self.filters_button.clicked.connect(self.filters_requested)
        self.switch.chosen.connect(self.version_chosen)
        self.profile_menu.profile_chosen.connect(self.profile_chosen)
        self.diffs.action_requested.connect(self.review_action_requested)
        # Enter "porta alla differenza": centred in BOTH documents, even when on screen
        self.diffs.activated.connect(lambda diff_id: self.sync.focus_difference(diff_id, reveal=True))
        self.progress.asis_requested.connect(self._on_asis_from_bar)
        self.diffs.difference_chosen.connect(self.sync.focus_difference)
        for side in (self.left, self.right):
            side.view.difference_clicked.connect(self._on_difference_clicked)
            side.view.minimap_chosen.connect(self._on_difference_clicked)

    # -- content -----------------------------------------------------------

    def show_case(self, case: Case, initiative: str, current: str | None, *,
                  blocked: bool = False, initiative_profile: str | None = None) -> None:
        """The bar and the version switch; the documents follow in
        :meth:`show_docs` once the page's job has prepared them. ``blocked``:
        the initiative cannot generate (unreadable ``iniziativa.json``);
        ``initiative_profile``: what "Come l'iniziativa" means."""
        changed = self.case is None or self.case.id != case.id
        self.case = case
        self.hide_bars()
        self.blocked = blocked
        env = case.env or strings.OFFICINA_CASE_NO_ENV
        self.bar.set_back(initiative)
        self.title.setText(case_title(case))
        self.title.setToolTip(strings.BARRA_TITLE_TIP.format(title=case_title(case), env=env))
        self.regenerate_button.setToolTip(strings.BARRA_REGENERATE_TIP.format(env=env))
        accepted = case.status == "accepted"
        self.status.setVisible(accepted)
        self.accept_action.setText(strings.OFFICINA_REOPEN if accepted else strings.OFFICINA_MARK_ACCEPTED)
        self.asis_action.setText(strings.OFFICINA_REGENERATE_ASIS if case.asis() is not None
                                 else strings.OFFICINA_GENERATE_ASIS)
        self.notice.set_message(case_notice(case), notice_label(case))
        self.show_call_strip(case)
        self.switch.set_versions(self.versions(), current)
        self.profile_menu.set_profile(case.review.profile, initiative_profile)
        target = case.target()
        self.left.name.setText(target.meta.get("original_name", "") if target else "")
        if changed:
            self.docs = None
            self.set_dom_mode(False)
            self.view_switch.setVisible(False)
            self.dom.forget()
            self.left.show_message(strings.OFFICINA_LOADING)
            self.right.show_message(strings.OFFICINA_LOADING)
            self.right.slot.setVisible(False)
            self.diffs.show_message(strings.OFFICINA_LOADING)
            self.progress.show_summary(None, [])  # the page forgets the outcome (open_case)
            self.bar.set_same_as_asis(None, "")
            self.bar.set_filters(None)
        self.refresh_run_state()

    def versions(self) -> list[Version]:
        """The AS-IS (if any) then the TO-BE versions, ascending."""
        return case_versions(self.case) if self.case is not None else []

    def version(self, key: str | None) -> Version | None:
        return next((v for v in self.versions() if version_key(v) == key), None)

    def current_version_key(self) -> str | None:
        return self.switch.current()

    def show_loading(self) -> None:
        for side in (self.left, self.right):
            if not side.showing_document():
                side.show_message(strings.OFFICINA_LOADING)

    def set_failure(self, text: str) -> None:
        """The chip of a failed generation, the reason as its tooltip ("" hides it)."""
        self.banner.set_message(text, strings.BARRA_FAILED)

    def refresh_run_state(self) -> None:
        case = self.case
        running = case is not None and self.run_state(case.id) is not None
        self.busy.setText(strings.OFFICINA_GENERATING_ON.format(
            env=(case.env if case is not None else "") or strings.OFFICINA_CASE_NO_ENV))
        self.busy.setVisible(running)
        idle = case is not None and not running
        readable = idle and not case.load_error  # saving a broken caso.json would wipe it
        # the payload, headers, target and status must not change under a queued call
        self.target_action.setEnabled(idle)
        for action in (self.editor_action, self.accept_action):
            action.setEnabled(readable)
        # never write under a running compare, nor while an action is being saved
        reviewable = readable and not self.judging and not self.acting
        self.profile_menu.setEnabled(reviewable)
        self.reset_tolerances_action.setEnabled(reviewable)
        # the Filtri switches queue behind a compare or an action (R38): only a broken file stops them
        self.filters_button.setEnabled(readable)
        self.banners.show_marks(live_marks(case, self.docs), case.env if case is not None else "")
        self.progress.set_marks_tip(self.banners.marks_text())
        self.unmark_action.setEnabled(reviewable and bool(self.banners.marks_text()))
        generating = readable and not self.blocked
        self.regenerate_button.setEnabled(generating)
        self.asis_action.setEnabled(generating)
        self._sync_extras(readable, generating)

    def resizeEvent(self, event) -> None:  # noqa: D102, N802 - Qt naming
        super().resizeEvent(event)
        self._initial_split()

    def _initial_split(self) -> None:
        """The two documents share what the panel leaves, 5 : 5, the first
        time the workbench has a real width (stretch factors alone only share
        the space left over the size hints)."""
        width = self.splitter.width()
        if self._split_done or width < 200:
            return
        self._split_done = True
        docs = max(0, width - self.diffs.width() - 2 * self.splitter.handleWidth())
        left = docs * SPLIT[0] // sum(SPLIT)
        self.splitter.setSizes([left, docs - left, 0, self.diffs.width()])  # the DOM tab starts hidden

    def _fit_panel(self) -> None:
        """The panel opened / collapsed: the documents take (or give) the width."""
        sizes = self.splitter.sizes()
        if len(sizes) < 4 or not self._split_done:
            return
        free = sum(sizes) - self.diffs.width()
        shown = [i for i in range(3) if sizes[i] > 0] or [0, 1]
        total = sum(sizes[i] for i in shown) or len(shown)
        new = [0, 0, 0, self.diffs.width()]
        for i in shown:
            new[i] = free * (sizes[i] or 1) // total
        new[shown[-1]] += free - sum(new[:3])
        self.splitter.setSizes(new)

    def focus_default(self) -> None:
        """The keyboard focus inside the workbench, on the generated document."""
        self.right.view.setFocus(Qt.FocusReason.OtherFocusReason)

    def acceptance_warning(self) -> str:
        """What the "Segna accettato" confirmation says (spec §5.4: a
        warning, never a block), "" when there is nothing to warn about.
        Accepting stamps the LATEST TO-BE, so it is described: its judged
        comparison when on screen (a side without text is said), else its
        saved summary, else "not compared yet"; without any TO-BE, whether
        the documents on screen differ under the case's profile."""
        docs, case = self.docs, self.case
        latest = case.latest_tobe() if case is not None else None
        judged = docs.judged if docs is not None else None
        if judged is not None and latest is not None and judged.version == latest.number:
            if not (judged.tobe.left_has_text and judged.tobe.right_has_text):
                return strings.OFFICINA_ACCEPT_NO_TEXT.format(note=judged.tobe.note)
            return remaining_text(pill_counts(judged.judged))
        if latest is not None:
            summary = case.review.summary
            if summary is not None and summary.version == latest.number:
                return remaining_text(board_counts(summary))
            return strings.OFFICINA_ACCEPT_NOT_COMPARED.format(version=latest.number)
        comparison = docs.comparison if docs is not None else None
        if comparison is not None and not (comparison.left_has_text and comparison.right_has_text):
            return strings.OFFICINA_ACCEPT_NO_TEXT.format(note=comparison.note)
        if comparison is not None and comparison.equal_for(docs.profile):
            return ""
        return strings.OFFICINA_ACCEPT_WITH_DIFFS

    # -- internals ---------------------------------------------------------

    def _on_f5(self) -> None:
        if self.regenerate_button.isEnabled():
            self.regenerate_requested.emit()

    def set_judging(self, judging: bool) -> None:
        """A compare job of the case on screen started / ended."""
        self.judging = judging
        self.refresh_run_state()

    def _on_asis_from_bar(self) -> None:
        if self.asis_action.isEnabled():
            self.asis_requested.emit()

    def show_occurrence(self, anchors: tuple, pages: tuple) -> bool:
        """An occurrence of "Filtri del confronto" (F5): its difference
        selected in the list and ringed in both documents; without one on
        screen, the target at its first page. False when nothing was shown."""
        docs = self.docs
        if docs is None:
            return False
        diffs = (docs.judged.judged if docs.judged is not None else
                 [unjudged(d) for d in docs.comparison.diffs] if docs.comparison is not None else [])
        wanted = set(anchors)
        found = next((j.diff.id for j in diffs if j.diff.anchor in wanted), None)
        if found is not None:
            self.diffs.select(found)
            self.sync.focus_difference(found, reveal=True)
            self.dom.select(found)
            return True
        if pages and 0 <= pages[0] < self.left.view.page_count():
            self.left.view.scroll_to_position(pages[0], 0.0)
            return True
        return False

    def _on_difference_clicked(self, diff_id: int) -> None:
        self.sync.focus_difference(diff_id)
        self.diffs.select(diff_id)
        self.dom.select(diff_id)

    # -- U6: the DOM tab follows the documents and the verdicts ----------------------

    def show_docs(self, docs: CaseDocs) -> None:
        super().show_docs(docs)
        self._dom_follow()

    def _highlight(self, judged: list) -> None:
        super()._highlight(judged)
        self.dom.set_judged(judged)
        self.dom.select(self.diffs.current_id())  # the list's kept selection, after its refill
