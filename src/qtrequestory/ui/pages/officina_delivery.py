""""Consegna…": the testers' delivery folder (spec §8), one dialog.

1. **The form.** The cases (preselected: the ones accepted AS OF their latest
   TO-BE; choosing one that is not accepted, or whose latest TO-BE is not the
   accepted one, shows a warning line, it is allowed), the destination (the
   initiative's last one, remembered in ``iniziativa.json``), "Crea anche lo
   zip", and a preview of the tree that will be written — with the slots that
   will be skipped because they are missing.
2. **The check** (``officina-delivery`` job): which files are already at the
   destination. Each one is asked about on the GUI thread (Sostituisci /
   Mantieni entrambi / Salta, "Applica a tutti") BEFORE anything is copied.
3. **The copy** (the same job, cancellable between files): the answers are
   handed to ``OfficinaApi.deliver`` as its ``on_conflict``. A file that
   turns up only during the copy was never asked about and is kept next to
   the new one ("Mantieni entrambi"): nothing is overwritten without a click.
4. **The summary**: delivered, left as they were, missing, failed (with the
   reason; the rest is still delivered), the zip, and "Apri cartella".

The destination is often a OneDrive/SharePoint folder (the testers'
convention): allowed, no warning here — what goes there is meant to be shared.
"""
from __future__ import annotations

import os
from collections.abc import Sequence
from functools import partial
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import (
    CoreServices,
    DeliveryPlan,
    DeliveryReport,
    Initiative,
    delivery_folder,
    safe_component,
    zip_destination,
)
from qtrequestory.ui.pages import officina_dialogs as ask
from qtrequestory.ui.pages.officina_format import (
    case_title,
    delivery_summary,
    delivery_warning,
    missing_text,
)
from qtrequestory.ui.workers import OFFICINA_DELIVERY_JOB, JobRunner

__all__ = ["DELIVERY_JOB", "DeliveryDialog", "open_delivery_dialog"]

DELIVERY_JOB = OFFICINA_DELIVERY_JOB


def _norm(path: Path) -> str:
    return os.path.normcase(os.path.abspath(path))


def _decide(decisions: dict[str, str], path: Path) -> str:
    """``on_conflict`` for the worker: the user's answer; a file nobody was
    asked about (it appeared during the copy) is kept, never overwritten."""
    return decisions.get(_norm(path), "keep_both")


class DeliveryDialog(QDialog):
    """Form → check → copy → summary (module docstring)."""

    def __init__(self, services: CoreServices, runner: JobRunner, ini: Initiative,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services, self.runner, self.ini = services, runner, ini
        self.setWindowTitle(strings.OFFICINA_DELIVERY_TITLE.format(initiative=ini.name))
        self._plan = DeliveryPlan([], [])
        self._report: DeliveryReport | None = None
        self._job = None
        self._busy = False

        self.cases = QListWidget()
        for case in ini.cases:
            current = case.acceptance_is_current()
            if current:
                state = strings.OFFICINA_DELIVERY_CASE_ACCEPTED
            elif case.status == "accepted":
                state = strings.OFFICINA_DELIVERY_CASE_STALE
            else:
                state = strings.OFFICINA_DELIVERY_CASE_OPEN
            item = QListWidgetItem(f"{case_title(case)}  —  {state}")
            item.setData(Qt.ItemDataRole.UserRole, case.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if current else Qt.CheckState.Unchecked)
            self.cases.addItem(item)
        self.warning = QLabel()
        self.warning.setWordWrap(True)
        self.warning.setProperty("dot", "warn")
        self.dest_edit = QLineEdit()
        self.dest_edit.setReadOnly(True)
        self.dest_edit.setPlaceholderText(strings.OFFICINA_DELIVERY_DESTINATION_HINT)
        self.browse = QPushButton(strings.BTN_BROWSE)
        self.zip_box = QCheckBox(strings.OFFICINA_DELIVERY_ZIP)
        self.preview = QTreeWidget()
        self.preview.setHeaderHidden(True)
        self.preview.setRootIsDecorated(True)
        self.preview.setTextElideMode(Qt.TextElideMode.ElideLeft)  # the initiative stays readable
        self.nothing = QLabel(strings.OFFICINA_DELIVERY_NOTHING)
        theme.set_role(self.nothing, "muted")
        self.status = QLabel()
        theme.set_role(self.status, "muted")
        self.deliver_button = QPushButton(strings.OFFICINA_DELIVERY_START)
        theme.set_role(self.deliver_button, "primary")
        self.cancel_button = QPushButton(strings.BTN_CANCEL)

        self.summary_title = QLabel()
        theme.set_role(self.summary_title, "section")
        self.summary_body = QPlainTextEdit()
        self.summary_body.setReadOnly(True)
        self.open_folder_button = QPushButton(strings.BTN_OPEN_FOLDER)
        self.close_button = QPushButton(strings.BTN_CLOSE)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._form_page())
        self.pages.addWidget(self._summary_page())
        layout = QVBoxLayout(self)
        layout.addWidget(self.pages)
        self.resize(940, 580)

        self.cases.itemChanged.connect(lambda _item: self._refresh())
        self.zip_box.toggled.connect(lambda _on: self._refresh())
        self.browse.clicked.connect(self._browse)
        self.deliver_button.clicked.connect(self.start)
        self.cancel_button.clicked.connect(self._cancel_clicked)
        self.open_folder_button.clicked.connect(self._open_folder)
        self.close_button.clicked.connect(self.accept)
        theme.repolish(self.warning)
        last = services.officina.last_delivery_destination(ini)
        self.dest_edit.setText(str(last) if last is not None else "")
        self._refresh()

    # -- layout --------------------------------------------------------------

    def _form_page(self) -> QWidget:
        left = QVBoxLayout()
        heading = QLabel(strings.OFFICINA_DELIVERY_CASES)
        theme.set_role(heading, "section")
        left.addWidget(heading)
        left.addWidget(self.cases, 1)
        left.addWidget(self.warning)
        dest_row = QHBoxLayout()
        dest_row.addWidget(self.dest_edit, 1)
        dest_row.addWidget(self.browse)
        right = QVBoxLayout()
        dest_label = QLabel(strings.OFFICINA_DELIVERY_DESTINATION)
        theme.set_role(dest_label, "section")
        right.addWidget(dest_label)
        right.addLayout(dest_row)
        right.addWidget(self.zip_box)
        preview_label = QLabel(strings.OFFICINA_DELIVERY_PREVIEW)
        theme.set_role(preview_label, "section")
        right.addWidget(preview_label)
        right.addWidget(self.preview, 1)
        right.addWidget(self.nothing)
        columns = QHBoxLayout()
        columns.addLayout(left, 2)
        columns.addSpacing(theme.SPACE[3])
        columns.addLayout(right, 3)
        buttons = QHBoxLayout()
        buttons.addWidget(self.status, 1)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.deliver_button)
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(columns, 1)
        layout.addLayout(buttons)
        return page

    def _summary_page(self) -> QWidget:
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.open_folder_button)
        buttons.addWidget(self.close_button)
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.summary_title)
        layout.addWidget(self.summary_body, 1)
        layout.addLayout(buttons)
        return page

    # -- form state ------------------------------------------------------------

    def checked_case_ids(self) -> list[str]:
        return [self.cases.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.cases.count())
                if self.cases.item(i).checkState() == Qt.CheckState.Checked]

    def set_checked(self, case_id: str, checked: bool) -> None:
        for i in range(self.cases.count()):
            item = self.cases.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == case_id:
                item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

    def destination(self) -> Path | None:
        text = self.dest_edit.text().strip()
        return Path(text) if text and Path(text).is_absolute() else None

    def set_destination(self, path: Path) -> None:
        self.dest_edit.setText(str(path))
        self._refresh()

    def _browse(self) -> None:
        chosen = ask.ask_folder(self, strings.OFFICINA_DELIVERY_PICK, self.destination())
        if chosen is not None:
            self.set_destination(chosen)

    def _refresh(self) -> None:
        chosen = self.checked_case_ids()
        self._plan = self.services.officina.delivery_plan(self.ini, chosen)
        warning = delivery_warning([c for c in self.ini.cases if c.id in chosen])
        self.warning.setText(warning)
        self.warning.setVisible(bool(warning))
        self._fill_preview()
        self.nothing.setVisible(bool(chosen) and not self._plan.items)
        self.deliver_button.setEnabled(not self._busy and bool(self._plan.items)
                                       and self.destination() is not None)

    def _fill_preview(self) -> None:
        self.preview.clear()
        dest = self.destination()
        root_text = (str(delivery_folder(dest, self.ini.id)) if dest is not None
                     else f"{strings.OFFICINA_DELIVERY_NO_DESTINATION}\\{safe_component(self.ini.id)}")
        root = QTreeWidgetItem([root_text])
        root.setToolTip(0, root_text)
        self.preview.addTopLevelItem(root)
        folders: dict[str, QTreeWidgetItem] = {}

        def folder(name: str) -> QTreeWidgetItem:
            if name.casefold() not in folders:
                folders[name.casefold()] = QTreeWidgetItem(root, [name])
            return folders[name.casefold()]

        for item in self._plan.items:
            head, _sep, name = item.dest_rel.partition("/")
            QTreeWidgetItem(folder(head), [name])
        muted = self.palette().color(QPalette.ColorRole.PlaceholderText)
        for slot in self._plan.missing:
            line = QTreeWidgetItem(folder(safe_component(slot.key)),
                                   [missing_text(slot, with_key=False)])
            line.setForeground(0, muted)
        if self.zip_box.isChecked():
            archive = zip_destination(dest or Path("."), self.ini.id).name
            self.preview.addTopLevelItem(QTreeWidgetItem([archive]))
        self.preview.expandAll()

    def preview_lines(self) -> list[str]:
        """The preview as text, two spaces per level (what the user reads)."""
        lines: list[str] = []

        def walk(item: QTreeWidgetItem, depth: int) -> None:
            lines.append("  " * depth + item.text(0))
            for i in range(item.childCount()):
                walk(item.child(i), depth + 1)

        for i in range(self.preview.topLevelItemCount()):
            walk(self.preview.topLevelItem(i), 0)
        return lines

    # -- running -----------------------------------------------------------------

    def start(self) -> None:
        """Check the destination for existing files (in the worker)."""
        dest = self.destination()
        if dest is None or not self._plan.items or self._busy:
            return
        self._set_busy(strings.OFFICINA_DELIVERY_CHECKING, stoppable=False)
        job = self.runner.submit(DELIVERY_JOB, self.services.officina.delivery_conflicts, self.ini,
                                 list(self._plan.items), dest, make_zip=self.zip_box.isChecked())
        if job is None:
            self._set_idle()
            return
        found: dict[str, Sequence[Path]] = {}
        job.signals.result.connect(partial(found.__setitem__, "conflicts"))
        job.signals.error.connect(self._on_error)
        # The copy is submitted under the same (exclusive) name, so only once
        # this job's `finished` is delivered: at `result` it may still count
        # as running, and the submit would be refused.
        job.signals.finished.connect(partial(self._ask_then_copy, dest, found))

    def _ask_then_copy(self, dest: Path, found: dict[str, Sequence[Path]]) -> None:
        if "conflicts" not in found:
            return  # the check failed: _on_error already shows why
        conflicts = found["conflicts"]
        decisions: dict[str, str] = {}
        for i, path in enumerate(conflicts):
            if _norm(path) in decisions:
                continue
            choice, apply_all = ask.ask_conflict(self, path, len(conflicts) - i)
            for other in conflicts[i:] if apply_all else [path]:
                decisions.setdefault(_norm(other), choice)
        self._set_busy(strings.OFFICINA_DELIVERY_COPYING, stoppable=True)
        self._job = self.runner.submit(
            DELIVERY_JOB, self.services.officina.deliver, self.ini, list(self._plan.items), dest,
            on_conflict=partial(_decide, decisions), make_zip=self.zip_box.isChecked())
        if self._job is None:
            self._set_idle()
            return
        self._job.signals.result.connect(self._show_summary)
        self._job.signals.error.connect(self._on_error)

    def _set_busy(self, text: str, *, stoppable: bool) -> None:
        self._busy = True
        self.status.setText(text)
        for widget in (self.cases, self.browse, self.zip_box, self.deliver_button):
            widget.setEnabled(False)
        self.cancel_button.setText(strings.OFFICINA_DELIVERY_STOP if stoppable else strings.BTN_CANCEL)
        self.cancel_button.setEnabled(stoppable)

    def _set_idle(self) -> None:
        self._busy = False
        self.status.setText("")
        for widget in (self.cases, self.browse, self.zip_box):
            widget.setEnabled(True)
        self.cancel_button.setText(strings.BTN_CANCEL)
        self.cancel_button.setEnabled(True)
        self._refresh()

    def _cancel_clicked(self) -> None:
        if self._busy:
            if self._job is not None:
                self._job.cancel()
                self.cancel_button.setEnabled(False)
            return
        self.reject()

    def _on_error(self, _kind: str, message: str) -> None:
        self._busy = False
        self._report = None
        self.summary_title.setText(strings.OFFICINA_DELIVERY_PARTIAL_TITLE)
        self.summary_body.setPlainText(strings.OFFICINA_DELIVERY_ERROR.format(reason=message))
        self.open_folder_button.setEnabled(False)
        self.pages.setCurrentIndex(1)

    # -- summary -------------------------------------------------------------------

    def _show_summary(self, report: DeliveryReport) -> None:
        self._busy = False
        self._report = report
        title, body = delivery_summary(report, self._plan.missing, zip_asked=self.zip_box.isChecked())
        self.summary_title.setText(title)
        self.summary_body.setPlainText(body)
        self.open_folder_button.setEnabled(report.folder_exists)  # stat'ed in the worker
        self.pages.setCurrentIndex(1)

    def showing_summary(self) -> bool:
        return self.pages.currentIndex() == 1

    def summary_text(self) -> str:
        return f"{self.summary_title.text()}\n{self.summary_body.toPlainText()}"

    def _open_folder(self) -> None:
        if self._report is not None:
            self.services.extract.open_folder(self._report.folder)

    # -- closing ---------------------------------------------------------------------

    def reject(self) -> None:  # noqa: D102 - never while the copy runs
        if not self._busy:
            super().reject()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if self._busy:
            event.ignore()
            return
        super().closeEvent(event)


def open_delivery_dialog(parent: QWidget | None, services: CoreServices, runner: JobRunner,
                         ini: Initiative) -> None:
    """The board's "Consegna…" (tests replace this function)."""
    dialog = DeliveryDialog(services, runner, ini, parent)
    try:
        dialog.exec()
    finally:
        dialog.deleteLater()
