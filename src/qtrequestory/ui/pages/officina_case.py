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
from qtrequestory.ui.pages.officina_widgets import pill
from qtrequestory.ui.pages.officina_diffs import (
    DiffPanel,
    DocSide,
    VersionSwitch,
    case_versions,
    version_key,
)
from qtrequestory.ui.pages.officina_format import case_notice, case_title, when
from qtrequestory.ui.pages.officina_jobs import CaseDocs
from qtrequestory.ui.pages.officina_list import WarnBanner
from qtrequestory.ui.pages.officina_viewer import SyncController

__all__ = ["CaseView", "REGENERATE_SHORTCUT"]

REGENERATE_SHORTCUT = "F5"
#: TARGET : generated document : differences, as the splitter first opens.
SPLIT = (5, 5, 2)
LEFT_DOC_ID = "officina-target"
RIGHT_DOC_ID = "officina-generated"


class CaseView(QWidget):
    """One case: the two documents, the differences and the case actions."""

    back_requested = Signal()
    regenerate_requested = Signal()      # a new TO-BE
    asis_requested = Signal()            # the AS-IS (the page asks for a note if one exists)
    target_requested = Signal()
    editor_requested = Signal()
    status_toggle_requested = Signal()
    version_chosen = Signal(str)         # version_key

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.case: Case | None = None
        self.docs: CaseDocs | None = None
        #: "queued" | "running" | None for the case on screen (the page's queue).
        self.run_state: Callable[[str], str | None] = lambda _case_id: None
        #: The initiative cannot generate (its iniziativa.json is unreadable).
        self.blocked = False

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
        self.notice = WarnBanner()  # a damaged caso.json, a case to check again

        self.switch = VersionSwitch()
        self.left = DocSide(strings.OFFICINA_SIDE_TARGET, LEFT_DOC_ID)
        self.right = DocSide("", RIGHT_DOC_ID, self.switch)
        self.right.slot.setVisible(False)
        self.diffs = DiffPanel()
        self.sync = SyncController(self.left.view, self.right.view)

        self.shortcut = QShortcut(QKeySequence(REGENERATE_SHORTCUT), self)
        self.shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._build()
        self._connect()

    def _build(self) -> None:
        top = QHBoxLayout()
        top.addWidget(self.back_button)
        top.addWidget(self.title)
        top.addWidget(self.status)
        top.addSpacing(theme.SPACE[2])
        top.addWidget(self.env_label)
        top.addStretch(1)
        actions = QHBoxLayout()
        for button in (self.regenerate_button, self.asis_button, self.target_button,
                       self.editor_button):
            actions.addWidget(button)
        actions.addWidget(self.busy)
        actions.addStretch(1)
        actions.addWidget(self.accept_button)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        for widget in (self.left, self.right, self.diffs):
            self.splitter.addWidget(widget)
        for index, share in enumerate(SPLIT):
            self.splitter.setStretchFactor(index, share)
        self._split_done = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE[1])
        layout.addLayout(top)
        layout.addLayout(actions)
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
        self.diffs.difference_chosen.connect(self.sync.focus_difference)
        for side in (self.left, self.right):
            side.view.difference_clicked.connect(self._on_difference_clicked)

    # -- content -----------------------------------------------------------

    def show_case(self, case: Case, initiative: str, current: str | None, *,
                  blocked: bool = False) -> None:
        """Header, buttons and the version switch; the documents follow in
        :meth:`show_docs` once the page's job has prepared them. ``blocked``:
        the initiative cannot generate (unreadable ``iniziativa.json``)."""
        changed = self.case is None or self.case.id != case.id
        self.case = case
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
        target = case.target()
        self.left.name.setText(target.meta.get("original_name", "") if target else "")
        if changed:
            self.docs = None
            self.left.show_message(strings.OFFICINA_LOADING)
            self.right.show_message(strings.OFFICINA_LOADING)
            self.diffs.show_message(strings.OFFICINA_LOADING)
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

    def show_docs(self, docs: CaseDocs) -> None:
        """The prepared documents and their comparison (from ``load_case_docs``)."""
        self.docs = docs
        self._show_side(self.left, docs.left.version, docs.left.path, docs.left.sizes,
                        docs.left.error, strings.OFFICINA_NO_TARGET)
        self._show_side(self.right, docs.right.version, docs.right.path, docs.right.sizes,
                        docs.right.error, strings.OFFICINA_NO_VERSION)
        right = docs.right.version
        self.right.info.setText(strings.OFFICINA_VERSION_INFO.format(
            env=right.meta.get("env", ""), when=when(right.created)) if right else "")
        if docs.comparison is not None:
            comparison = docs.comparison
            self.diffs.show_comparison(comparison)
            self.left.view.set_highlights([(d.id, d.kind, d.left) for d in comparison.differences])
            self.right.view.set_highlights([(d.id, d.kind, d.right)
                                            for d in comparison.differences])
        else:
            self.left.view.set_highlights([])
            self.right.view.set_highlights([])
            if docs.compare_error:
                self.diffs.show_message(strings.OFFICINA_DIFF_ERROR.format(
                    reason=docs.compare_error), "bad")
            else:
                self.diffs.show_message(strings.OFFICINA_DIFF_NEED_BOTH)

    def show_failure(self, text: str) -> None:
        """The documents could not be prepared at all."""
        for side in (self.left, self.right):
            if not side.showing_document():
                side.show_message(text)
        self.diffs.show_message(text, "bad")

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
        self.splitter.setSizes([width * share // total for share in SPLIT])

    def focus_default(self) -> None:
        """The keyboard focus inside the workbench, on the generated document."""
        self.right.view.setFocus(Qt.FocusReason.OtherFocusReason)

    def comparison_is_equal(self) -> bool:
        """True when the documents on screen have no text difference."""
        return bool(self.docs and self.docs.comparison and self.docs.comparison.equal)

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _show_side(side: DocSide, version, path, sizes, error: str, empty: str) -> None:
        if version is None:
            side.show_message(empty)
        elif error or path is None:
            side.show_message(error)
        else:
            side.show_document(path, sizes)

    def _on_f5(self) -> None:
        if self.regenerate_button.isEnabled():
            self.regenerate_requested.emit()

    def _on_difference_clicked(self, diff_id: int) -> None:
        self.sync.focus_difference(diff_id)
        self.diffs.select(diff_id)
