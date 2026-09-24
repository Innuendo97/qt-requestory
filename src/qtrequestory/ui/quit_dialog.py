"""Operation names for the user, and the question asked before closing.

``JobRunner`` job names are identifiers chosen by the pages; :func:`job_label`
is how they are ever shown. The quit question names whichever long job — a
sync, an index or an import — closing the window would interrupt.
"""
from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QPushButton, QWidget

from qtrequestory.ui import strings

__all__ = ["JOB_LABELS", "QUIT_INFO", "build_quit_dialog", "confirm_quit_during_job", "job_label"]

#: What the quit question adds under the main text, per job.
QUIT_INFO = {"sync": strings.QUIT_SYNC_INFO, "index": strings.QUIT_INDEX_INFO,
             "import": strings.QUIT_IMPORT_INFO}

#: ``JobRunner`` name -> what to call that operation in front of the user. The
#: names are identifiers chosen by the pages ("check-envs", "search_plan",
#: "about-log"); only ``EXCLUSIVE`` ones can currently be refused, but the map
#: covers every name in ``workers.JOB_NAMES`` — a test pins the two together —
#: so a new exclusive one is never a surprise in the status bar.
JOB_LABELS = {
    "sync": strings.JOB_SYNC,
    "sync-task-status": strings.JOB_SYNC_TASK_STATUS,
    "sync-reachability": strings.JOB_SYNC_REACHABILITY,
    "index": strings.JOB_INDEX,
    "scheduler": strings.JOB_SCHEDULER,
    "search": strings.JOB_SEARCH,
    "search_keys": strings.JOB_SEARCH_KEYS,
    "search_plan": strings.JOB_SEARCH_PLAN,
    "preview": strings.JOB_PREVIEW,
    "check-envs": strings.JOB_CHECK_ENVS,
    "about-log": strings.JOB_ABOUT_LOG,
    "wizard-reachability": strings.JOB_WIZARD_REACHABILITY,
    "wizard-task-status": strings.JOB_WIZARD_TASK_STATUS,
    "wizard-count-files": strings.JOB_WIZARD_COUNT_FILES,
    "wizard-archive-report": strings.JOB_WIZARD_ARCHIVE,
    "archive-report": strings.JOB_ARCHIVE_REPORT,
    "import-scan": strings.JOB_IMPORT_SCAN,
    "import": strings.JOB_IMPORT,
}


def job_label(name: str) -> str:
    """The Italian name of an operation; the raw job name if it has none.

    Falling back to the name is deliberate: a message naming something the user
    does not recognise is poor, but saying nothing at all about a refused
    operation is worse.
    """
    return JOB_LABELS.get(name, name)


def build_quit_dialog(parent: QWidget, name: str,
                      detail: str = "") -> tuple[QMessageBox, QPushButton]:
    """The "<operazione> in corso" question, without showing it.

    ``name`` is the running job ("sync", "index"), ``detail`` what it has done
    so far ("12 di 48 file"), or empty. Split from
    :func:`confirm_quit_during_job` so the wording can be tested without a
    modal event loop.
    """
    label = job_label(name)
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle(strings.QUIT_DURING_JOB_TITLE.format(label=label))
    box.setText(strings.QUIT_DURING_JOB_TEXT.format(
        label=label, progress=f": {detail}" if detail else ""))
    info = QUIT_INFO.get(name)
    if info:
        box.setInformativeText(info)
    stop = box.addButton(strings.QUIT_STOP, QMessageBox.ButtonRole.AcceptRole)
    keep = box.addButton(strings.QUIT_CONTINUE, QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(keep)
    box.setEscapeButton(keep)
    return box, stop


def confirm_quit_during_job(parent: QWidget, name: str, detail: str = "") -> bool:
    """True when the user chose "Interrompi ed esci".

    The box is destroyed afterwards: answering "Continua" keeps the window open,
    and without this every refused close would leave a dialog parented to it.
    """
    box, stop = build_quit_dialog(parent, name, detail)
    try:
        box.exec()
        return box.clickedButton() is stop
    finally:
        box.deleteLater()
