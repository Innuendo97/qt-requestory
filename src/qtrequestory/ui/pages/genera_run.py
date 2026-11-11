"""Starting, counting, stopping and following a Genera run: the
:class:`GeneraRun` mixin of :class:`~qtrequestory.ui.pages.genera_page.GeneraPage`
(see the page's docstring for the behaviour). It uses the page's widgets
(``action_bar``, ``results``, the cards) and its ``presenter``, ``runner``,
``services``; the page owns construction and rendering.

The flow: [Genera] → (FDIs: ``batch_count`` as job ``GENERA_JOB``, under
"Cerco le chiamate…" and [Interrompi]) → the question over
``CONFIRM_ABOVE`` calls → ``batch_run`` as job ``GENERA_JOB``. Both jobs have
the same exclusive name, so a count and a run never overlap, and the quit
question covers both. A stop, a refusal or the window closing during the
count ends it with nothing sent.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import BatchItemDone, BatchReport, BatchRequest, BatchStarted
from qtrequestory.ui.pages import officina_dialogs as ask
from qtrequestory.ui.pages.genera_outcomes import report_summary
from qtrequestory.ui.pages.genera_retry import RETRY_STATUSES
from qtrequestory.ui.workers import GENERA_JOB

__all__ = ["GeneraRun"]


class GeneraRun:
    """The run flow of the Genera page (module docstring)."""

    # -- starting ------------------------------------------------------------------------------

    def _on_button(self) -> None:
        if self._running:
            self.stop()
        else:
            self.generate()

    def _shortcut_generate(self) -> None:
        self._commit_edits()  # first: a header cell committed now may change the button
        if not self._running and self.start_button.isEnabled():
            self.generate()

    def _commit_edits(self) -> None:
        """A header cell still open in edit mode, into the table and the
        presenter, before any request is built (``GeneraHeaderTable.commit_editing``)."""
        if not self._running:
            self.header_table.commit_editing()

    def generate(self) -> None:
        """[Genera]: the request of the form as it is now."""
        self._commit_edits()
        if self._running or self.presenter.problems() or not self.presenter.has_generator():
            return
        self._begin(self.presenter.build_request())

    def retry(self) -> None:
        """[Riprova i non riusciti]: the unfinished rows of the last report, to
        the generator of now (exact calls: those very calls again)."""
        if self._running or self.report is None:
            return
        self._commit_edits()
        problems = self.presenter.problems()
        request = self.presenter.retry_request(self.report, self._last_request)
        # the source text may be empty now: only the "where" and header problems count
        blocking = [x for x in problems if x not in _SOURCE_PROBLEMS]
        if blocking:
            self.results.show_message(blocking[0])
        elif request.targets:
            self._begin(request)

    def _begin(self, request: BatchRequest) -> None:
        """Count first when FDIs make the number unknown; else confirm (over
        the threshold) and run."""
        if self.presenter.needs_count(request):
            self._count(request)
            return
        count = len(request.targets)
        if self.presenter.needs_confirmation(count) and not self._confirm(request, count):
            return
        self._run(request)

    def _confirm(self, request: BatchRequest, count: int) -> bool:
        """The question over ``CONFIRM_ABOVE`` calls, in Italian, its buttons
        saying what they do ("Genera 56 documenti" / "Annulla", the default)."""
        title, text = self.presenter.confirmation(request, count)
        return ask.confirm(self, title, text, yes=self.presenter.confirm_yes(count), no=strings.BTN_CANCEL)

    def _count(self, request: BatchRequest) -> None:
        job = self.runner.submit(GENERA_JOB, self.services.officina.batch_count, request)
        if job is None:
            self.results.show_message(strings.GENERA_ALREADY_RUNNING)
            return
        self._job, self._counted, self._run_env = job, None, request.source_env
        self._run_generator = request.generator
        self._set_running(True)
        job.signals.result.connect(self._on_counted)
        job.signals.error.connect(self._on_error)
        job.signals.finished.connect(lambda r=request, j=job: self._on_count_finished(r, j))

    def _on_counted(self, count: object) -> None:
        self._counted = int(count)

    def _on_count_finished(self, request: BatchRequest, job) -> None:
        self._job = None
        if self._stopping or job.token.is_set() or self._counted is None:  # stopped, refused, quitting
            self._set_running(False)
            return
        # out of the job's slot first: the question is a nested event loop
        QTimer.singleShot(0, lambda: self._after_count(request, self._counted))

    def _after_count(self, request: BatchRequest, count: int) -> None:
        if self._quitting or not self._running:
            self._set_running(False)
            return
        if self.presenter.needs_confirmation(count) and not self._confirm(request, count):
            self._set_running(False)
            return
        self._run(request)

    def _run(self, request: BatchRequest, notify=None) -> bool:
        """Submit the run; False when refused (one at a time). ``notify``
        (``genera_calls.CallsNotify``) hears how it ended, instead of the toast."""
        job = self.runner.submit(GENERA_JOB, self.services.officina.batch_run, request)
        if job is None:
            if self._running:
                self._set_running(False)
            self.results.show_message(strings.GENERA_ALREADY_RUNNING)
            return False
        self._job, self.report, self._run_env = job, None, request.source_env
        self._run_generator = request.generator
        self._last_request, self._notify = request, notify
        self.results.clear_for_run()
        if not self._running:
            self._set_running(True)
        job.signals.progress.connect(self._on_event)
        job.signals.result.connect(self._on_report)
        job.signals.error.connect(self._on_error)
        job.signals.finished.connect(self._on_finished)
        return True

    # -- running ---------------------------------------------------------------------------------

    def stop(self) -> None:
        """[Interrompi]: the calls already sent finish, the others are cancelled
        (during the count: nothing is sent at all)."""
        if self._job is None or self._stopping:
            return
        self._stopping = True
        self._job.cancel()
        self.start_button.setEnabled(False)
        self.results.progress_label.setText(strings.GENERA_STOPPING)
        self.results.progress_count.setText("")

    def _set_running(self, running: bool) -> None:
        self._running = running
        self._stopping = False
        for widget in (self.source, self.source.modes, self.setup.where, self.setup.headers):
            widget.setEnabled(not running)
        self.results.set_running(running, strings.GENERA_LOOKING_UP.format(env=self._run_env))
        self.action_bar.set_running(running)
        if not running:
            self.render()
        self.running_changed.emit(running)

    def _on_event(self, event: object) -> None:
        sending = strings.GENERA_SENDING.format(env=self._run_generator)
        if isinstance(event, BatchStarted):
            self.results.show_progress(sending, 0, event.total, label=not self._stopping)
        elif isinstance(event, BatchItemDone):
            self.results.add_live(event.outcome)
            self.results.show_progress(sending, event.done, event.total, label=not self._stopping)

    def _on_report(self, report: BatchReport) -> None:
        self.report = report
        self.results.show_report(report, self.presenter.retry_count(report))
        notify, self._notify = self._notify, None
        if notify is not None:  # a run of Ricerca's "Genera documento": Ricerca says how it went
            notify(report, "")
            return
        if self.isVisible():  # the results pane says it, where the eyes already are
            return
        unfinished = any(o.status in RETRY_STATUSES for o in report.outcomes)
        text = (strings.GENERA_TOAST_STOPPED if report.cancelled else strings.GENERA_TOAST_DONE).format(
            summary=report_summary(report, with_folder=False))
        toast = getattr(self._window, "show_toast", None)
        shower = getattr(self._window, "show_page", None)
        if callable(toast):
            actions = [(strings.GENERA_TOAST_SHOW, lambda: shower(GENERA_PAGE))] if callable(shower) else None
            toast(text, "warn" if unfinished else "ok", actions=actions)

    def _on_error(self, kind: str, message: str) -> None:
        if kind in _REFUSALS:
            self.results.show_message(strings.GENERA_REFUSED.format(reason=message))
        else:
            self.results.show_message(strings.GENERA_CRASHED)
        notify, self._notify = self._notify, None
        if notify is not None:
            notify(None, message if kind in _REFUSALS else strings.GENERA_CRASHED)

    def _on_finished(self) -> None:
        self._job, self._notify = None, None
        self._set_running(False)

    def _open_folder(self) -> None:
        """[Apri cartella]; a folder that is not there (never made, moved) is
        said inline, never an exception."""
        if self.report is None:
            return
        run_dir = self.report.run_dir
        try:
            if run_dir.is_dir():
                self.services.extract.open_folder(run_dir)
                return
        except OSError:
            pass
        self.results.show_message(strings.GENERA_FOLDER_MISSING.format(name=run_dir.name))

    def _open_document(self, path: Path) -> None:
        """A row's document, with the application Windows gives it."""
        try:
            self.services.extract.open_file(path)
        except OSError:
            self.results.show_message(strings.GENERA_OPEN_FAILED.format(name=path.name))

    def _open_document_folder(self, folder: Path) -> None:
        try:
            if folder.is_dir():
                self.services.extract.open_folder(folder)
                return
        except OSError:
            pass
        self.results.show_message(strings.GENERA_FOLDER_MISSING.format(name=folder.name))

    def _copy(self, text: str) -> None:
        QApplication.clipboard().setText(text)
        toast = getattr(self._window, "show_toast", None)
        if callable(toast):
            toast(strings.GENERA_ROW_COPIED, "ok")


#: The page key of the tab (the toast's [Vedi esiti]).
GENERA_PAGE = "genera"
#: The exception names whose message is the core's Italian refusal (the
#: contract: ``ValueError``; ``HeaderError`` is one). Anything else is a bug
#: and its text is not shown: it was never written for the user.
_REFUSALS = frozenset({"ValueError", "HeaderError"})
#: The problems of "Cosa generare": a retry has its own targets.
_SOURCE_PROBLEMS = frozenset({strings.GENERA_NEED_KEYS, strings.GENERA_NEED_ELENCO,
                              strings.GENERA_NEED_PACKAGE, strings.GENERA_NEED_FDI})
