"""The case workbench: TARGET on the left, AS-IS or a TO-BE on the right.

Approved mockup "La vista Caso", phase-1 subset (text differences only; the
three-way verdict and the progress come in phase 2):

    ‹ Iniziativa   MOD_TEST_A · abilitato   [aperto]   Generatore: svil
    [Rigenera TO-BE (F5)] [Genera AS-IS] [Target…] [Payload e header…]   [Segna accettato]
    (notice: caso.json unreadable / new version after the acceptance)
    (warn banner: the last generation failed, with the masked reason)
    +-------- TARGET --------+---- [AS-IS|v1|v2] ----+-- Differenze --+
    | DocView                | DocView               | list           |
    +------------------------+-----------------------+----------------+

The two viewers scroll and zoom together (``SyncController``); a click on a
difference, in the list or on a highlight, focuses it in both. Documents and
the comparison are prepared in the ``officina-compare`` job (an HTML goes
through Edge), so opening a case never blocks the window.

Phase 2 (U1): for a TO-BE the job also asks ``compare_case``; when it judged,
the viewers draw the differences by verdict (``officina_verdict_style``) and
the list shows them in tabs (U3, ``officina_diffs``); otherwise (the AS-IS, or a core that cannot
judge yet) the phase-1 comparison is drawn without verdict. U2: the header's
profile menu, the progress bar with its verdict strip (``officina_progress``)
and the review banners (``officina_banners``) under the toolbar. U4: the
actions from the documents — mini-bar, double click, right-click menu, F / T /
V in the viewers, Ctrl+Z (``officina_actions_bar``); after an action the page
redraws the verdicts with :meth:`CaseView.show_rejudged`, the documents stay.
U6: "Regole di rumore…" in the header (``officina_noise_page``) and, for an
HTML case, the "Documenti | DOM" switch with the DOM tab (``officina_dom``).

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
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import Case, Version
from qtrequestory.ui.pages.officina_actions_bar import ReviewInputMixin
from qtrequestory.ui.pages.officina_banners import ProfileButton, ReviewBanners, live_marks
from qtrequestory.ui.pages.officina_case_docs import CaseDocsMixin
from qtrequestory.ui.pages.officina_case_extras import CaseExtrasMixin
from qtrequestory.ui.pages.officina_progress import ProgressBar, remaining_text
from qtrequestory.ui.pages.officina_verdict_style import board_counts, pill_counts
from qtrequestory.ui.pages.officina_widgets import pill
from qtrequestory.ui.pages.officina_diffs import DiffPanel
from qtrequestory.ui.pages.officina_dom_view import DomViewMixin
from qtrequestory.ui.pages.officina_docside import DocSide, VersionSwitch, case_versions, version_key
from qtrequestory.ui.pages.officina_format import case_notice, case_title
from qtrequestory.ui.pages.officina_jobs import CaseDocs
from qtrequestory.ui.pages.officina_list import WarnBanner
from qtrequestory.ui.pages.officina_viewer import SyncController

__all__ = ["CaseView", "REGENERATE_SHORTCUT"]

REGENERATE_SHORTCUT = "F5"
#: TARGET : generated document : differences, as the splitter first opens (the
#: list's snippets need ~300 px at 1366: U3).
SPLIT = (5, 5, 3)
LEFT_DOC_ID = "officina-target"
RIGHT_DOC_ID = "officina-generated"


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
    noise_rules_requested = Signal()       # "Regole di rumore…"
    reset_tolerances_requested = Signal()  # "⋯" → "Azzera tolleranze…" (R45)
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
        #: show_docs is filling the view: a list selection it causes is not a user action.
        self._filling = False

        self.back_button = QPushButton()
        theme.set_role(self.back_button, "row")
        self.title = QLabel()
        theme.set_role(self.title, "pageTitle")
        self.status = pill("")
        self.env_label = QLabel()  # the generator every send of this case goes to
        theme.set_role(self.env_label, "muted")
        self.regenerate_button = QPushButton(strings.OFFICINA_REGENERATE_TOBE)
        theme.set_role(self.regenerate_button, "primary")
        self.asis_button = QPushButton(strings.OFFICINA_GENERATE_ASIS)
        self.target_button = QPushButton(strings.OFFICINA_CHOOSE_TARGET)
        self.editor_button = QPushButton(strings.OFFICINA_PAYLOAD_HEADERS)
        self.accept_button = QPushButton(strings.OFFICINA_MARK_ACCEPTED)
        self.busy = QLabel()
        theme.set_role(self.busy, "muted")
        self.busy.setVisible(False)
        self.banner = WarnBanner()
        self.profile_button = ProfileButton()
        self.noise_button = QPushButton(strings.RUMORE_BUTTON)
        self.noise_button.setToolTip(strings.RUMORE_BUTTON_TIP)
        self.progress = ProgressBar()
        self.banners = ReviewBanners()
        self.notice = WarnBanner()  # a damaged caso.json, a case to check again

        self.switch = VersionSwitch()
        self.left = DocSide(strings.OFFICINA_SIDE_TARGET, LEFT_DOC_ID)
        self.right = DocSide("", RIGHT_DOC_ID, self.switch)
        self.right.slot.setVisible(False)
        self.diffs = DiffPanel()
        self.sync = SyncController(self.left.view, self.right.view)

        self.shortcut = QShortcut(QKeySequence(REGENERATE_SHORTCUT), self)
        self.shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._init_dom_widgets()
        self._init_extras()
        self._build()
        self._connect()
        self._connect_dom()
        self._init_review_input()  # after _connect: a click selects, THEN the bar opens

    def _build(self) -> None:
        top = QHBoxLayout()
        top.addWidget(self.back_button)
        top.addWidget(self.title)
        top.addWidget(self.status)
        top.addSpacing(theme.SPACE[2])
        top.addWidget(self.env_label)
        top.addStretch(1)
        top.addWidget(self.noise_button)
        top.addWidget(self.profile_button)
        top.addWidget(self.more_button)
        actions = QHBoxLayout()
        for button in (self.regenerate_button, self.asis_button, self.target_button,
                       self.editor_button):
            actions.addWidget(button)
        actions.addWidget(self.busy)
        actions.addStretch(1)
        actions.addWidget(self.view_switch)
        actions.addSpacing(theme.SPACE[2])
        actions.addWidget(self.accept_button)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        for widget in (self.left, self.right, self.diffs):
            self.splitter.addWidget(widget)
        self.splitter.insertWidget(2, self.dom)  # hidden until "DOM" (HTML cases)
        for index, share in enumerate(SPLIT):
            self.splitter.setStretchFactor(index if index < 2 else index + 1, share)
        self.splitter.setStretchFactor(2, SPLIT[0] + SPLIT[1])
        self._split_done = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE[1])
        layout.addLayout(top)
        layout.addLayout(actions)
        layout.addWidget(self.progress)
        layout.addWidget(self.banners)
        layout.addWidget(self.notice)
        layout.addWidget(self.banner)
        layout.addWidget(self.splitter, 1)

    def _connect(self) -> None:
        self.back_button.clicked.connect(self.back_requested)
        self.regenerate_button.clicked.connect(self.regenerate_requested)
        self.shortcut.activated.connect(self._on_f5)
        self.asis_button.clicked.connect(self.asis_requested)
        self.target_button.clicked.connect(self.target_requested)
        self.editor_button.clicked.connect(self.editor_requested)
        self.accept_button.clicked.connect(self.status_toggle_requested)
        self.switch.chosen.connect(self.version_chosen)
        self.profile_button.profile_chosen.connect(self.profile_chosen)
        self.noise_button.clicked.connect(self.noise_rules_requested)
        self.diffs.action_requested.connect(self.review_action_requested)
        # Enter "porta alla differenza": centred in BOTH documents, even when on screen
        self.diffs.activated.connect(lambda diff_id: self.sync.focus_difference(diff_id, reveal=True))
        self.banners.unmark_all_requested.connect(self.unmark_all_requested)
        self.progress.diff_selected.connect(self._on_difference_clicked)
        self.progress.asis_requested.connect(self._on_asis_from_bar)
        # R28: the user's next action folds the verification outcome into the bar
        for signal in (self.regenerate_requested, self.asis_requested, self.target_requested,
                       self.editor_requested, self.status_toggle_requested, self.version_chosen,
                       self.profile_chosen, self.unmark_all_requested, self.review_action_requested,
                       self.diffs.difference_chosen, self.progress.diff_selected,
                       self.left.view.difference_clicked, self.right.view.difference_clicked,
                       self.left.view.minimap_chosen, self.right.view.minimap_chosen):
            signal.connect(self._acted)
        self.diffs.difference_chosen.connect(self.sync.focus_difference)
        for side in (self.left, self.right):
            side.view.difference_clicked.connect(self._on_difference_clicked)
            side.view.minimap_chosen.connect(self._on_difference_clicked)

    # -- content -----------------------------------------------------------

    def show_case(self, case: Case, initiative: str, current: str | None, *,
                  blocked: bool = False, initiative_profile: str | None = None) -> None:
        """Header, buttons and the version switch; the documents follow in
        :meth:`show_docs` once the page's job has prepared them. ``blocked``:
        the initiative cannot generate (unreadable ``iniziativa.json``);
        ``initiative_profile``: what "Come l'iniziativa" means."""
        changed = self.case is None or self.case.id != case.id
        self.case = case
        self.hide_bars()
        self.blocked = blocked
        self.back_button.setText(strings.OFFICINA_BACK_TO_BOARD.format(initiative=initiative))
        self.title.setText(case_title(case))
        self.env_label.setText(strings.OFFICINA_CASE_ENV.format(
            env=case.env or strings.OFFICINA_CASE_NO_ENV))
        accepted = case.status == "accepted"
        self.status.setText(strings.OFFICINA_STATUS_ACCEPTED if accepted
                            else strings.OFFICINA_STATUS_OPEN)
        self.status.setProperty("pill", "ok" if accepted else "neutral")
        theme.repolish(self.status)
        self.accept_button.setText(strings.OFFICINA_REOPEN if accepted
                                   else strings.OFFICINA_MARK_ACCEPTED)
        self.asis_button.setText(strings.OFFICINA_REGENERATE_ASIS if case.asis() is not None
                                 else strings.OFFICINA_GENERATE_ASIS)
        self.notice.set_text(case_notice(case))
        self.switch.set_versions(self.versions(), current)
        self.profile_button.set_profile(case.review.profile, initiative_profile)
        target = case.target()
        self.left.name.setText(target.meta.get("original_name", "") if target else "")
        if changed:
            self.docs = None
            self.set_dom_mode(False)
            self.view_switch.setVisible(False)
            self.dom.forget()
            self.left.show_message(strings.OFFICINA_LOADING)
            self.right.show_message(strings.OFFICINA_LOADING)
            self.diffs.show_message(strings.OFFICINA_LOADING)
            self.progress.show_summary(None, [])  # the page forgets the outcome (open_case)
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
        """The warn banner of a failed generation ("" hides it)."""
        self.banner.set_text(text)

    def refresh_run_state(self) -> None:
        case = self.case
        running = case is not None and self.run_state(case.id) is not None
        self.busy.setText(strings.OFFICINA_GENERATING_ON.format(
            env=(case.env if case is not None else "") or strings.OFFICINA_CASE_NO_ENV))
        self.busy.setVisible(running)
        idle = case is not None and not running
        readable = idle and not case.load_error  # saving a broken caso.json would wipe it
        # the payload, headers, target and status must not change under a queued call
        self.target_button.setEnabled(idle)
        for button in (self.editor_button, self.accept_button):
            button.setEnabled(readable)
        # never write under a running compare, nor while an action is being saved
        reviewable = readable and not self.judging and not self.acting
        self.profile_button.setEnabled(reviewable)
        self.noise_button.setEnabled(reviewable)
        self.reset_tolerances_action.setEnabled(reviewable)
        self.banners.show_marks(live_marks(case, self.docs), case.env if case is not None else "",
                                enabled=reviewable)
        for button in (self.regenerate_button, self.asis_button):
            button.setEnabled(readable and not self.blocked)

    def resizeEvent(self, event) -> None:  # noqa: D102, N802 - Qt naming
        super().resizeEvent(event)
        self._initial_split()

    def _initial_split(self) -> None:
        """5 : 5 : 2 the first time the workbench has a real width (stretch
        factors alone only share the space left over the size hints)."""
        width = self.splitter.width()
        if self._split_done or width < 200:
            return
        self._split_done = True
        total = sum(SPLIT)
        sizes = [width * share // total for share in SPLIT]
        self.splitter.setSizes([*sizes[:2], 0, sizes[2]])  # the DOM tab (index 2) starts hidden

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

    def _acted(self, *_args) -> None:
        if self._filling:
            return
        self.banners.collapse()
        self.progress.set_outcome(self.banners.collapsed_outcome())

    def _on_asis_from_bar(self) -> None:
        if self.asis_button.isEnabled():
            self.asis_requested.emit()

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
