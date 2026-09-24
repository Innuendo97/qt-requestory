"""Importa log: copy logs kept in any folder layout into the archive.

Three steps in one dialog, every slow call in the :class:`JobRunner`:

1. **the report** (``import-scan``): ``ArchiveApi.report(folder)`` in a table
   (:mod:`~qtrequestory.ui.import_report`). A folder whose environment the
   path does not tell gets a combo; the choice is saved in
   ``Config.folder_envs`` under the folder's ABSOLUTE path and the folder is
   scanned again. Nothing waiting for an environment is ever copied.
2. **the copy** (``import``, exclusive, cancellable): ``ArchiveApi.import_``
   with a progress bar. ``ArchiveBusy`` (a sync holds the lock) sends the
   user back to step 1 with the reason.
3. **the result** (:mod:`~qtrequestory.ui.import_result`): the counts, then —
   only for verified originals outside the archive — "Vuoi cancellare gli
   originali?". A yes hands exactly those ``VerifiedOriginal`` records to
   ``ArchiveApi.recycle`` (again an ``import`` job). The touched environments
   are indexed right away (the ``index`` job), after which ``MainWindow``
   refreshes every page through ``on_data_changed``.

The dialog can be given several folders (the wizard queues the mirror's own
strays and a folder "altrove"): each is scanned only when its turn comes, so
its report already knows what the previous one copied.
"""
from __future__ import annotations

import dataclasses
import logging
from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import DUPLICATE, IMPORTABLE, ArchiveReport, CoreServices, ImportResult
from qtrequestory.ui.import_report import ReportView
from qtrequestory.ui.import_result import ResultView, deletable
from qtrequestory.ui.import_state import (
    IMPORT_JOB,
    IMPORT_SCAN_JOB,
    ArchiveWatch,
    ImportProgress,
    import_call,
)
from qtrequestory.ui.workers import Job, JobRunner

__all__ = ["INDEX_JOB", "ImportDialog", "open_import_dialog"]

log = logging.getLogger(__name__)

#: The index update after a copy: the same exclusive job as Impostazioni's.
INDEX_JOB = "index"
STEP_SCAN, STEP_REPORT, STEP_COPY, STEP_RESULT = range(4)


class ImportDialog(QDialog):
    """Report → copy → result, for one folder after another."""

    def __init__(self, services: CoreServices, runner: JobRunner,
                 sources: Sequence[Path | None] = (None,), parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._services = services
        self._runner = runner
        self._sources: list[Path | None] = list(sources) or [None]
        self._position = 0
        self.report: ArchiveReport | None = None
        self.result: ImportResult | None = None
        self.scan_job: Job | None = None
        self.import_job: Job | None = None
        self.recycle_job: Job | None = None
        self._recycling: list = []
        #: True once a folder's environment was saved (the caller may care).
        self.config_saved = False
        self.setWindowTitle(strings.IMPORT_TITLE)
        self.resize(960, 580)  # fits a 1366x768 screen with the taskbar
        self._build()
        self._scan()

    # -- construction ------------------------------------------------------

    def _build(self) -> None:
        self.title = QLabel(strings.IMPORT_TITLE)
        theme.set_role(self.title, "pageTitle")
        self.source_label = QLabel()
        theme.set_role(self.source_label, "muted")
        self.source_label.setWordWrap(True)
        self.intro = QLabel(strings.IMPORT_INTRO)
        self.intro.setWordWrap(True)
        self.error_banner = QFrame()
        self.error_banner.setProperty("banner", "warn")
        self.error_banner.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        QHBoxLayout(self.error_banner).addWidget(self.error_label)
        self.error_banner.hide()

        self.scanning_label = QLabel(strings.IMPORT_SCANNING)
        self.view = ReportView()
        self.view.folder_env_chosen.connect(self.save_folder_env)
        self.progress_label = QLabel(strings.IMPORT_COPYING)
        self.progress_label.setWordWrap(True)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        copy_page = QWidget()
        copy_layout = QVBoxLayout(copy_page)
        copy_layout.setContentsMargins(0, 0, 0, 0)
        copy_layout.addWidget(self.progress_label)
        copy_layout.addWidget(self.progress_bar)
        copy_layout.addStretch(1)
        self.result_view = ResultView()
        self.result_view.delete_requested.connect(self.delete_originals)
        self.result_view.keep_requested.connect(self.result_view.show_kept)
        self.stack = QStackedWidget()
        for widget in (self.scanning_label, self.view, copy_page, self.result_view):
            self.stack.addWidget(widget)

        self.close_button = QPushButton(strings.IMPORT_BTN_CLOSE)
        self.close_button.clicked.connect(self.reject)
        self.primary_button = QPushButton(strings.IMPORT_BTN_START)
        theme.set_role(self.primary_button, "primary")
        self.primary_button.clicked.connect(self._on_primary)
        footer = QHBoxLayout()
        footer.addStretch(1)
        footer.addWidget(self.close_button)
        footer.addWidget(self.primary_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SPACE[4], theme.SPACE[3], theme.SPACE[4], theme.SPACE[3])
        layout.setSpacing(theme.SPACE[2])
        for widget in (self.title, self.source_label, self.intro, self.error_banner):
            layout.addWidget(widget)
        layout.addWidget(self.stack, 1)
        layout.addLayout(footer)

    # -- state -------------------------------------------------------------

    def step(self) -> int:
        return self.stack.currentIndex()

    def source(self) -> Path | None:
        return self._sources[self._position]

    def has_next_source(self) -> bool:
        return self._position + 1 < len(self._sources)

    def _show_error(self, text: str) -> None:
        self.error_label.setText(text)
        self.error_banner.setVisible(bool(text))

    def _show_source(self) -> None:
        source = self.source()
        if source is None:
            text = strings.IMPORT_SOURCE_MIRROR.format(path=self._services.config.load().mirror_root)
        else:
            text = strings.IMPORT_SOURCE.format(path=source)
        if len(self._sources) > 1:
            text += strings.IMPORT_SOURCE_STEP.format(i=self._position + 1, n=len(self._sources))
        self.source_label.setText(text)

    # -- step 1: the report ------------------------------------------------

    def _scan(self) -> None:
        self._show_source()
        self._show_error("")
        self.stack.setCurrentIndex(STEP_SCAN)
        self.primary_button.setText(strings.IMPORT_BTN_START)
        self.primary_button.setEnabled(False)
        self.primary_button.show()
        self.scan_job = self._runner.submit(IMPORT_SCAN_JOB, self._services.archive.report,
                                            self.source())
        if self.scan_job is None:
            return  # closing
        self.scan_job.signals.result.connect(self._on_report)
        self.scan_job.signals.error.connect(self._on_scan_failed)

    def _on_report(self, report: ArchiveReport) -> None:
        self.report = report
        names = [e.name for e in self._services.config.load().environments]
        self.view.set_report(report, names)
        if not report.items:
            self.view.plan_label.setText(strings.IMPORT_EMPTY)
        self.stack.setCurrentIndex(STEP_REPORT)
        counts = report.counts()
        self.primary_button.setEnabled(bool(counts[IMPORTABLE] + counts[DUPLICATE]))

    def _on_scan_failed(self, _kind: str, message: str) -> None:
        self.scanning_label.setText(strings.IMPORT_SCAN_FAILED.format(error=message))

    def save_folder_env(self, folder: str, value: str) -> None:
        """A combo was set: remember it for that folder, then scan again."""
        cfg = self._services.config.load()
        folder_envs = {**cfg.folder_envs, folder: value}
        self._services.config.save(dataclasses.replace(cfg, folder_envs=folder_envs))
        self.config_saved = True
        self._scan()

    # -- step 2: the copy --------------------------------------------------

    def _on_primary(self) -> None:
        if self.step() == STEP_REPORT:
            self.start_import()
        elif self.step() == STEP_RESULT and self.has_next_source():
            self._position += 1
            self._scan()

    def start_import(self) -> None:
        if self.report is None:
            return
        problems = self._services.config.mirror_root_errors(self._services.config.load())
        if problems:
            self._show_error(strings.IMPORT_REFUSED.format(problem=problems[0]))
            return
        job = self._runner.submit(IMPORT_JOB, import_call, self._services.archive, self.report)
        if job is None:
            if self._runner.is_running(IMPORT_JOB):
                self._show_error(strings.STATUS_BUSY.format(name=strings.JOB_IMPORT))
            return
        self.import_job = job
        self._show_error("")
        self.progress_label.setText(strings.IMPORT_COPYING)
        self.progress_bar.setRange(0, 0)
        self.stack.setCurrentIndex(STEP_COPY)
        self.primary_button.hide()
        self.close_button.setText(strings.IMPORT_BTN_STOP)
        job.signals.progress.connect(self._on_progress)
        job.signals.result.connect(self._on_imported)
        job.signals.error.connect(self._on_import_failed)

    def _on_progress(self, event: object) -> None:
        if not isinstance(event, ImportProgress):
            return
        self.progress_bar.setRange(0, max(event.total, 1))
        self.progress_bar.setValue(event.done)
        if event.rel_path and not self.import_job.token.is_set():
            self.progress_label.setText(strings.IMPORT_PROGRESS.format(
                done=event.done, total=event.total, path=event.rel_path))

    def _on_import_failed(self, _kind: str, message: str) -> None:
        self.close_button.setText(strings.IMPORT_BTN_CLOSE)
        self.primary_button.show()
        self.stack.setCurrentIndex(STEP_REPORT)
        self._show_error(strings.IMPORT_FAILED.format(error=message))

    # -- step 3: the result ------------------------------------------------

    def _on_imported(self, result: ImportResult) -> None:
        self.result = result
        note = self._index(result)
        mirror = self._services.config.load().mirror_root
        self.result_view.set_result(result, deletable(result, mirror), note)
        self.stack.setCurrentIndex(STEP_RESULT)
        self.close_button.setText(strings.IMPORT_BTN_CLOSE)
        if self.has_next_source():
            self.primary_button.setText(strings.IMPORT_BTN_NEXT.format(
                path=self._sources[self._position + 1] or mirror))
            self.primary_button.setEnabled(True)
            self.primary_button.show()

    def _index(self, result: ImportResult) -> str:
        """Index what was copied; the line the result shows about it."""
        if not result.envs:
            return ""
        job = self._runner.submit(INDEX_JOB, self._services.index.update, sorted(result.envs))
        return strings.IMPORT_INDEXING if job is not None else strings.IMPORT_INDEX_BUSY

    def delete_originals(self) -> None:
        offered = list(self.result_view.offered)
        if not offered:
            return
        job = self._runner.submit(IMPORT_JOB, self._services.archive.recycle, offered)
        if job is None:
            return
        self.recycle_job = job
        self._recycling = offered
        self.result_view.set_busy(True)
        job.signals.result.connect(self._on_recycled)
        job.signals.error.connect(self._on_recycle_failed)
        job.signals.finished.connect(self._on_recycle_finished)

    def _on_recycled(self, failures: list) -> None:
        self.result_view.show_deleted(len(self._recycling) - len(failures), failures)

    def _on_recycle_failed(self, _kind: str, message: str) -> None:
        self.result_view.show_deleted(0, [(v.path, message) for v in self._recycling])

    def _on_recycle_finished(self) -> None:
        self.result_view.set_busy(False)

    # -- closing -----------------------------------------------------------

    def busy(self) -> bool:
        return any(job is not None and job.is_running()
                   for job in (self.import_job, self.recycle_job))

    def reject(self) -> None:
        """[Chiudi] / Esc / the close box. During the copy it means
        [Interrompi]: the job stops at its next file and step 3 shows what
        was copied; the dialog stays open until then."""
        if self.import_job is not None and self.import_job.is_running():
            self.import_job.cancel()
            self.progress_label.setText(strings.IMPORT_STOPPING)
            return
        if self.busy():
            return  # the Recycle Bin call: a few seconds at most
        if self.scan_job is not None:
            self.scan_job.cancel()
        super().reject()


def open_import_dialog(services: CoreServices, runner: JobRunner, parent: QWidget | None,
                       sources: Sequence[Path | None] = (None,),
                       on_closed: Callable[[], None] | None = None) -> ImportDialog | None:
    """Show the dialog (window-modal, deleted on close); ``None`` without a
    usable mirror folder — the 1.0.0 gate: nothing is ever copied into a
    relative or empty path. ``on_closed`` runs once the dialog is gone, and
    the shared :class:`ArchiveWatch` rescans then (a folder may have been
    assigned without copying anything)."""
    if services.config.mirror_root_errors(services.config.load()):
        return None
    dialog = ImportDialog(services, runner, sources, parent)
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

    def closed(_code: int) -> None:
        watch = ArchiveWatch.existing(runner)
        if watch is not None:
            watch.refresh()
        if on_closed is not None:
            on_closed()

    dialog.finished.connect(closed)
    dialog.open()
    return dialog
