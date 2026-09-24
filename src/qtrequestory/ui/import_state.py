"""What the import UI shares: job names, the worker calls, and the archive watch.

The Ricerca and Sincronizzazione banners and the Impostazioni › Archivio
summary all show the same thing — what ``ArchiveApi.report()`` finds in the
mirror folder outside ``<env>/YYYY/MM/YYYYMMDD.txt`` — so they share ONE
:class:`ArchiveWatch` per :class:`~qtrequestory.ui.workers.JobRunner`: one
scan in a worker, one result, three readers. It rescans by itself after
every sync, index or import (``JobRunner.job_finished``); ``MainWindow``
also asks it after a configuration change.
"""
from __future__ import annotations

import logging
from typing import NamedTuple

from PySide6.QtCore import QObject, QTimer, Signal

from qtrequestory.ui.contracts import (
    IMPORTABLE,
    NEEDS_ENV,
    ArchiveApi,
    ArchiveReport,
    CoreServices,
    ImportResult,
)
from qtrequestory.ui.workers import JobRunner

__all__ = [
    "ARCHIVE_REPORT_JOB", "IMPORT_JOB", "IMPORT_SCAN_JOB", "INDEX_JOB", "RECYCLE_JOB",
    "WIZARD_ARCHIVE_JOB", "ArchiveSnapshot", "ArchiveWatch", "ImportProgress", "import_call",
    "index_after_import", "stray_count",
]

log = logging.getLogger(__name__)

ARCHIVE_REPORT_JOB = "archive-report"
IMPORT_SCAN_JOB = "import-scan"
IMPORT_JOB = "import"
RECYCLE_JOB = "recycle"
INDEX_JOB = "index"
WIZARD_ARCHIVE_JOB = "wizard-archive-report"
#: The jobs after which the mirror may hold different files.
RESCAN_AFTER = frozenset({"sync", INDEX_JOB, IMPORT_JOB, RECYCLE_JOB})


class ArchiveSnapshot(NamedTuple):
    """The mirror report plus the number of daily files already in place."""

    report: ArchiveReport
    archived: int


class ImportProgress(NamedTuple):
    """``ArchiveApi.import_``'s progress callback, as a sink payload."""

    done: int
    total: int
    rel_path: str


def stray_count(report: ArchiveReport | None) -> int:
    """Logs a user can do something about: importable, or waiting for an env."""
    if report is None:
        return 0
    counts = report.counts()
    return counts[IMPORTABLE] + counts[NEEDS_ENV]


def take_snapshot(services: CoreServices) -> ArchiveSnapshot:
    """Worker thread: the mirror's report and its canonical file count."""
    return ArchiveSnapshot(services.archive.report(), services.index.count_local_files())


def import_call(archive: ArchiveApi, report: ArchiveReport, *, sink, cancel) -> ImportResult:
    """Worker thread: ``import_`` with its progress turned into sink events
    (the runner delivers them on the GUI thread as ``progress``)."""
    return archive.import_(report, cancel=cancel,
                           progress=lambda done, total, rel: sink(ImportProgress(done, total, rel)))


class ArchiveWatch(QObject):
    """The shared mirror report; ``changed`` after every scan (or failure)."""

    changed = Signal()

    def __init__(self, services: CoreServices, runner: JobRunner) -> None:
        super().__init__(runner)
        self._services = services
        self._runner = runner
        self.snapshot: ArchiveSnapshot | None = None
        #: Why there is no snapshot (the mirror folder is not usable), or None.
        self.problem: str | None = None
        self.loading = False
        runner.job_finished.connect(self._on_job_finished)

    @classmethod
    def shared(cls, services: CoreServices, runner: JobRunner) -> ArchiveWatch:
        """The runner's watch, created (and a first scan queued) on first use."""
        watch = cls.existing(runner)
        if watch is None:
            watch = cls(services, runner)
            runner._archive_watch = watch  # noqa: SLF001 - one per runner, by design
            QTimer.singleShot(0, watch, watch.refresh)
        return watch

    @staticmethod
    def existing(runner: JobRunner) -> ArchiveWatch | None:
        return getattr(runner, "_archive_watch", None)

    @property
    def report(self) -> ArchiveReport | None:
        return self.snapshot.report if self.snapshot is not None else None

    def refresh(self) -> None:
        """Rescan the mirror in a worker; an unusable folder is not scanned."""
        problems = self._services.config.mirror_root_errors(self._services.config.load())
        if problems:
            self.snapshot, self.problem, self.loading = None, problems[0], False
            self.changed.emit()
            return
        job = self._runner.submit(ARCHIVE_REPORT_JOB, take_snapshot, self._services)
        if job is None:
            return  # closing
        self.loading = True
        job.signals.result.connect(self._on_result)
        job.signals.error.connect(self._on_error)

    def _on_result(self, snapshot: ArchiveSnapshot) -> None:
        self.snapshot, self.problem, self.loading = snapshot, None, False
        self.changed.emit()

    def _on_error(self, _kind: str, message: str) -> None:
        log.info("controllo dell'archivio non riuscito: %s", message)
        self.snapshot, self.problem, self.loading = None, message, False
        self.changed.emit()

    def _on_job_finished(self, name: str, _ok: bool) -> None:
        if name in RESCAN_AFTER:
            self.refresh()


def index_after_import(services: CoreServices, runner: JobRunner, envs) -> bool:
    """Index ``envs`` now (True), or as soon as the running index ends (False).

    ``index`` is exclusive: while one runs (the startup index, a
    [Ricostruisci indice]) the submit is refused, and that run may have
    planned before the copy, so the imported days would stay unindexed. The
    envs then wait on the runner, merged with any already waiting, and are
    submitted when that index finishes, successfully or not. Owned by the
    runner, not by the dialog, so closing the dialog changes nothing.
    """
    envs = sorted(envs)
    if not envs:
        return True
    if runner.submit(INDEX_JOB, services.index.update, envs) is not None:
        return True
    if not runner.is_running(INDEX_JOB):
        return False  # the application is closing: the next start indexes
    waiting = getattr(runner, "_import_index_waiting", None)
    if waiting is None:
        waiting = _WaitingIndex(services, runner)
        runner._import_index_waiting = waiting  # noqa: SLF001 - one per runner
    waiting.envs.update(envs)
    return False


class _WaitingIndex(QObject):
    """Envs to index once the running ``index`` job is over."""

    def __init__(self, services: CoreServices, runner: JobRunner) -> None:
        super().__init__(runner)
        self._services = services
        self._runner = runner
        self.envs: set[str] = set()
        runner.job_finished.connect(self._on_job_finished)

    def _on_job_finished(self, name: str, _ok: bool) -> None:
        if name != INDEX_JOB or self._runner.is_running(INDEX_JOB):
            return
        envs, self.envs = self.envs, set()
        self._runner.job_finished.disconnect(self._on_job_finished)
        self._runner._import_index_waiting = None  # noqa: SLF001
        self.deleteLater()
        index_after_import(self._services, self._runner, envs)
