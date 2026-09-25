"""The Officina tab: folder chooser → initiatives → board → case workbench.

One ``QStackedWidget`` with four screens (see ``officina_list``,
``officina_board``, ``officina_case``); this module is the controller: it
reads the Officina through ``services.officina``, runs every generation
through one :class:`~qtrequestory.ui.pages.officina_jobs.GenerationQueue`
(at most three cases at once, a failed case never stops the others) and every
comparison in a ``JobRunner`` job, and keeps the reason of each case's last
failed generation in memory (the model stores only successful runs).

Nothing heavy is imported here: PDFium is only reached inside the workers.
The page reads the disk when it is shown, not when the window is built.
"""
from __future__ import annotations

from functools import partial
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QStackedWidget, QVBoxLayout, QWidget

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import Case, CoreServices, Initiative, SendResult, Version
from qtrequestory.ui.pages import officina_dialogs as ask
from qtrequestory.ui.pages.officina_actions import CaseActionsMixin
from qtrequestory.ui.pages.officina_board import Board
from qtrequestory.ui.pages.officina_case import CaseView
from qtrequestory.ui.pages.officina_diffs import case_versions, version_key
from qtrequestory.ui.pages.officina_jobs import (
    COMPARE_JOB,
    SUMMARY_JOB,
    GenerationQueue,
    load_case_docs,
    summarise,
)
from qtrequestory.ui.pages.officina_list import InitiativeList, RootChooser
from qtrequestory.ui.workers import OFFICINA_DELIVERY_JOB, JobRunner

__all__ = ["OfficinaPage"]

VIEWS = ("chooser", "list", "board", "case")


class OfficinaPage(CaseActionsMixin, QWidget):
    """The Officina tab (``PAGES`` key ``officina``, Ctrl+3)."""

    #: The folder chosen here was saved: the shell tells the other pages.
    config_changed = Signal(object)

    def __init__(self, services: CoreServices, runner: JobRunner, window: object | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self.runner = runner
        self._window = window
        self.ini: Initiative | None = None
        self.case_id: str | None = None
        #: (initiative id, case id) -> why its last generation failed (masked),
        #: until one succeeds. The model stores only successful runs.
        self.failures: dict[tuple[str, str], str] = {}
        #: (initiative id, case id) of the cases "Annulla" stopped before sending.
        self.cancelled: set[tuple[str, str]] = set()
        self._loaded = False
        #: The folder the screens on show were read from (see on_config_changed).
        self._root: Path | None = None

        self.queue = GenerationQueue(services, runner, parent=self)
        self.chooser = RootChooser()
        self.list = InitiativeList()
        self.board = Board()
        self.case_view = CaseView()
        self.board.run_state = self._run_state
        self.board.failure = self._failure
        self.board.note = self._note
        self.case_view.run_state = self._run_state
        self.stack = QStackedWidget()
        for widget in (self.chooser, self.list, self.board, self.case_view):
            self.stack.addWidget(widget)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SPACE[3], theme.SPACE[2], theme.SPACE[3], theme.SPACE[2])
        layout.addWidget(self.stack)
        self._connect()

    def _connect(self) -> None:
        self.chooser.choose_requested.connect(self.choose_root)
        self.list.change_root_requested.connect(self.choose_root)
        self.list.new_requested.connect(self.new_initiative)
        self.list.open_requested.connect(self.open_initiative)
        self.list.folder_requested.connect(lambda: self._open_folder(self.api.workspace_root()))
        board = self.board
        board.back_requested.connect(self.show_list)
        board.open_requested.connect(self.open_case)
        board.add_from_search_requested.connect(self.add_from_search)
        board.add_from_file_requested.connect(self.add_from_file)
        board.generate_missing_requested.connect(self.generate_missing_asis)
        board.regenerate_requested.connect(self.regenerate_tobe)
        board.cancel_requested.connect(self.queue.cancel)
        board.deliver_requested.connect(self.deliver)
        board.folder_requested.connect(
            lambda: self._open_folder(self.ini.folder if self.ini else None))
        case = self.case_view
        case.back_requested.connect(self.show_board)
        case.regenerate_requested.connect(lambda: self.regenerate_tobe([self.case_id]))
        case.asis_requested.connect(self.generate_asis)
        case.target_requested.connect(self.choose_target)
        case.editor_requested.connect(self.edit_payload)
        case.status_toggle_requested.connect(self.toggle_status)
        case.version_chosen.connect(self._load_docs)
        self.queue.state_changed.connect(self._on_run_state)
        self.queue.case_finished.connect(self._on_case_finished)
        self.queue.progress.connect(self._show_progress)
        self.queue.batch_finished.connect(self._on_batch_finished)

    @property
    def api(self):
        return self.services.officina

    # -- navigation --------------------------------------------------------

    def view(self) -> str:
        return VIEWS[self.stack.currentIndex()]

    def refresh(self) -> None:
        """Re-read the disk and show the screen the user was on."""
        self._loaded = True
        self._root = self.api.workspace_root()
        if self._root is None:
            self.ini, self.case_id = None, None
            self.stack.setCurrentWidget(self.chooser)
            return
        if self.ini is not None and self._reload_initiative():
            if self.case_id is not None and self._case(self.case_id) is not None:
                self.open_case(self.case_id)
            else:
                self.show_board()
            return
        self.show_list()

    def show_list(self) -> None:
        root = self.api.workspace_root()
        if root is None:
            self.stack.setCurrentWidget(self.chooser)
            return
        self.list.root_label.setText(strings.OFFICINA_ROOT_LABEL.format(path=root))
        self.list.onedrive.set_text(strings.OFFICINA_ROOT_ONEDRIVE.format(path=root)
                                    if ask.in_onedrive(root) else "")
        self.runner.cancel(SUMMARY_JOB)  # the board's comparisons are no longer on show
        self.list.show_initiatives(self.api.initiatives(),
                                   select=self.ini.id if self.ini else None)
        self.ini, self.case_id = None, None
        self.stack.setCurrentWidget(self.list)

    def open_initiative(self, initiative_id: str) -> None:
        """Open the initiative in folder ``initiative_id`` (``Initiative.id``)."""
        try:
            self.ini = self.api.load(initiative_id)
        except (FileNotFoundError, OSError, ValueError):
            self._notify(strings.OFFICINA_INITIATIVE_GONE.format(name=initiative_id))
            self.ini = None
            self.show_list()
            return
        self.show_board()

    def show_board(self) -> None:
        if self.ini is None:
            self.show_list()
            return
        self.case_id = None
        self.board.show_initiative(self.ini)
        self.board.refresh_run_states()
        self._show_progress(*self.queue.counts())
        self.stack.setCurrentWidget(self.board)
        self._request_summaries()

    def open_case(self, case_id: str, version: str | None = None) -> None:
        case = self._case(case_id)
        if case is None or self.ini is None:
            return
        same = self.case_id == case_id and self.view() == "case"
        self.runner.cancel(SUMMARY_JOB)  # the board's comparisons would compete with this one
        self.case_id = case_id
        current = version or (self.case_view.current_version_key() if same else None)
        if current not in {version_key(v) for v in case_versions(case)}:
            current = self._default_version(case)
        self.case_view.show_case(case, self.ini.name, current,
                                 blocked=bool(self.ini.load_error))
        self.case_view.set_failure(self._failure(case_id) or "")
        self.stack.setCurrentWidget(self.case_view)
        if not same:
            self.case_view.focus_default()  # F5 works at once, arrows scroll the document
        self._load_docs(current)

    def current_initiative_id(self) -> str | None:
        """The id (folder) of the initiative on screen, for "Aggiungi all'Officina…"."""
        return self.ini.id if self.ini else None

    # -- shell hooks ---------------------------------------------------------

    def showEvent(self, event) -> None:  # noqa: N802 - Qt naming
        """The disk is read when the tab is shown, not while the window is built."""
        super().showEvent(event)
        self.refresh()

    def on_config_changed(self, _cfg: object) -> None:
        """Impostazioni saved: the folder or the generators may have changed.

        A new folder goes quietly to its list: the initiative on screen is not
        "gone" (it is in the old folder), and a same-named one in the new
        folder is another initiative, never swapped in."""
        if not self._loaded:
            return
        if self.api.workspace_root() != self._root:
            self.ini, self.case_id = None, None
        self.refresh()

    def is_writing(self) -> bool:
        """True while cases wait or run, or a delivery copies files: the
        folder must not change under them (Impostazioni asks)."""
        return self.queue.is_busy() or self.runner.is_running(OFFICINA_DELIVERY_JOB)

    def on_quit(self) -> None:
        """The window is closing (the user already agreed): nothing more is
        sent. The waiting cases are dropped, the running ones stopped before
        they send."""
        self.queue.cancel()

    def on_case_added(self, _ini_id: str, _case_id: str) -> None:
        """Ricerca added a case. The tab re-reads the disk whenever it is
        shown, so only a tab already on screen needs telling."""
        if self._loaded and self.isVisible():
            self.refresh()

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
        if version is not None:
            self.board.forget_summary(case_id)
        if self.view() == "case" and self.case_id == case_id and version is None:
            self.case_view.set_failure(self._failure(case_id) or "")
            self.case_view.refresh_run_state()
            return
        if not self._reload_initiative():
            return
        if self.view() == "board":
            self.board.show_initiative(self.ini)
            self.board.refresh_run_states()
            if version is not None:
                self._request_summaries()
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

    def _load_docs(self, key: str | None) -> None:
        case = self._case(self.case_id)
        if case is None:
            return
        self.case_view.show_loading()
        job = self.runner.submit(COMPARE_JOB, load_case_docs, self.services, case,
                                 self.case_view.version(key))
        if job is not None:
            job.signals.result.connect(self._on_docs)
            job.signals.error.connect(self._on_docs_error)

    def _on_docs(self, docs) -> None:
        if self.view() == "case" and docs.case_id == self.case_id:
            self.case_view.show_docs(docs)

    def _on_docs_error(self, _kind: str, message: str) -> None:
        """An unexpected failure preparing the documents: a sentence, not a
        workbench stuck on "Preparazione…" (the traceback is in app.log)."""
        if self.view() == "case":
            self.case_view.show_failure(strings.OFFICINA_DIFF_ERROR.format(reason=message))

    def _request_summaries(self) -> None:
        if self.ini is None:
            return
        job = self.runner.submit(SUMMARY_JOB, summarise, self.services, list(self.ini.cases))
        if job is not None:
            job.signals.result.connect(partial(self._on_summaries, self.ini.id))

    def _on_summaries(self, initiative_id: str, summaries: dict) -> None:
        if self.ini is not None and self.ini.id == initiative_id:
            self.board.set_summaries(summaries)

    # -- helpers -----------------------------------------------------------

    def _reload_initiative(self) -> bool:
        if self.ini is None:
            return False
        try:
            self.ini = self.api.load(self.ini.id)
        except (FileNotFoundError, OSError, ValueError):
            self._notify(strings.OFFICINA_INITIATIVE_GONE.format(name=self.ini.name))
            self.ini, self.case_id = None, None
            self.show_list()
            return False
        return True

    def _case(self, case_id: str | None) -> Case | None:
        if self.ini is None or case_id is None:
            return None
        return next((c for c in self.ini.cases if c.id == case_id), None)

    @staticmethod
    def _default_version(case: Case) -> str | None:
        latest = case.latest_tobe()
        if latest is not None:
            return version_key(latest)
        return "asis" if case.asis() is not None else None

    def _run_state(self, case_id: str) -> str | None:
        return self.queue.state(self.ini.id, case_id) if self.ini is not None else None

    def _note(self, case_id: str) -> str | None:
        key = (self.ini.id, case_id) if self.ini is not None else None
        return strings.OFFICINA_RUN_CANCELLED if key in self.cancelled else None

    def _failure(self, case_id: str) -> str | None:
        return self.failures.get((self.ini.id, case_id)) if self.ini is not None else None

    def _open_folder(self, path: Path | None) -> None:
        if path is not None:
            self.services.extract.open_folder(path)

    def _notify(self, text: str) -> None:
        setter = getattr(self._window, "set_status", None)
        if callable(setter):
            setter(text)

    def _toast(self, text: str, tone: str = "neutral") -> None:
        toast = getattr(self._window, "show_toast", None)
        if callable(toast):
            toast(text, tone)
        else:
            self._notify(text)
