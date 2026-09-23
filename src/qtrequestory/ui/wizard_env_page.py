"""Page 2 of the first-run wizard: the environments table."""
from __future__ import annotations

import dataclasses
import logging
from pathlib import Path

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, Qt
from PySide6.QtGui import QPainter, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import Config, CoreServices, Environment
from qtrequestory.ui.env_table import EnvTable
from qtrequestory.ui.wizard_step import WizardStepPage, error_line, muted
from qtrequestory.ui.workers import Job, JobRunner

__all__ = ["REACHABILITY_JOB", "EnvironmentsPage", "PlaceholderDelegate"]

log = logging.getLogger(__name__)

#: Name of the reachability job in the shared runner. Not ``sync``/``index``
#: (those are exclusive), so a second click simply supersedes the first check.
REACHABILITY_JOB = "wizard-reachability"


class PlaceholderDelegate(QStyledItemDelegate):
    """Grey "nome" / "https://…" in the empty cells of a row.

    Painted only: the item's text stays empty, so a row the user never filled
    in is still ignored by ``EnvTable.environments()``. The cell editor carries
    the same text as its placeholder, so it does not vanish while typing.

    :meth:`paint` draws the text itself in ``PlaceholderText``: the theme's
    ``::item:selected`` rule sets the text colour of a selected row, and a
    freshly added row *is* the selected one.
    """

    def __init__(self, placeholders: dict[int, str], parent=None) -> None:
        super().__init__(parent)
        self._placeholders = placeholders

    def initStyleOption(self, option: QStyleOptionViewItem,
                        index: QModelIndex | QPersistentModelIndex) -> None:
        super().initStyleOption(option, index)
        placeholder = self._placeholders.get(index.column())
        if placeholder and not option.text:
            option.text = placeholder

    def paint(self, painter: QPainter, option: QStyleOptionViewItem,
              index: QModelIndex | QPersistentModelIndex) -> None:
        placeholder = self._placeholders.get(index.column())
        if not placeholder or index.data(Qt.ItemDataRole.DisplayRole):
            super().paint(painter, option, index)
            return
        opt = QStyleOptionViewItem(option)
        super().initStyleOption(opt, index)  # the empty cell: background, selection
        style = opt.widget.style() if opt.widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        rect = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, opt, opt.widget)
        # The same inner margin Qt leaves around an item's own text.
        margin = style.pixelMetric(QStyle.PixelMetric.PM_FocusFrameHMargin, None, opt.widget) + 1
        rect = rect.adjusted(margin, 0, -margin, 0)
        painter.save()
        painter.setPen(opt.palette.color(QPalette.ColorRole.PlaceholderText))
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                         placeholder)
        painter.restore()

    def createEditor(self, parent: QWidget, option: QStyleOptionViewItem,
                     index: QModelIndex | QPersistentModelIndex) -> QWidget:
        editor = super().createEditor(parent, option, index)
        placeholder = self._placeholders.get(index.column())
        if placeholder and isinstance(editor, QLineEdit):
            editor.setPlaceholderText(placeholder)
        return editor


class EnvironmentsPage(WizardStepPage):
    """The [abilitato | nome | URL] table, filled from the sidecar when there
    is one. Zero environments is allowed — the user can add them later — so the
    page warns instead of blocking."""

    def __init__(self, services: CoreServices, runner: JobRunner, parent=None) -> None:
        super().__init__(2, strings.WIZARD_P2_TITLE, strings.WIZARD_P2_SUBTITLE, parent)
        self._services = services
        self._runner = runner
        self._prefilled = False
        self._check_job: Job | None = None

        self.table = EnvTable()
        self.table.setItemDelegate(PlaceholderDelegate({
            EnvTable.COL_NAME: strings.WIZARD_P2_NAME_PLACEHOLDER,
            EnvTable.COL_URL: strings.WIZARD_P2_URL_PLACEHOLDER,
        }, self.table))
        self.hint_label = muted(strings.WIZARD_P2_HINT)
        self.error_label = error_line()
        self.error_label.setVisible(False)
        # Advisory, not an error, and it must be *seen*: it is shown and hidden
        # with its text while the page is open, not written at [Avanti] time
        # onto a page that is about to disappear.
        self.warning_label = muted()
        self.warning_label.setVisible(False)
        self.reachability_label = muted()
        self.reachability_label.setVisible(False)
        self.table.changed.connect(self._refresh_warning)

        self.add_button = QPushButton(strings.BTN_ADD)
        self.add_button.clicked.connect(self.add_environment)
        self.remove_button = QPushButton(strings.BTN_REMOVE)
        self.remove_button.clicked.connect(self.remove_selected)
        self.import_button = QPushButton(strings.BTN_IMPORT_FILE)
        self.import_button.clicked.connect(self.import_environments)

        buttons = QHBoxLayout()
        for button in (self.add_button, self.remove_button, self.import_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        self.check_button = QPushButton(strings.WIZARD_P2_BTN_CHECK)
        self.check_button.clicked.connect(self.check_reachability)
        buttons.addWidget(self.check_button)

        self.body.addWidget(self.hint_label)
        self.body.addWidget(self.table, 1)
        self.body.addLayout(buttons)
        self.body.addWidget(self.reachability_label)
        self.body.addWidget(muted(strings.WIZARD_P2_CHECK_NOTE))
        self.body.addWidget(self.warning_label)
        self.body.addWidget(self.error_label)

    def initializePage(self) -> None:
        """Pre-fill the table: what is already configured first, sidecar second.

        The wizard is not only a first run — Impostazioni re-runs it — and an
        empty table here would be written straight over the saved environments
        by [Fine]. So a configuration that already has some wins; the
        ``environments.json`` next to the executable is the *first-run* source,
        used when there is nothing to keep.

        A sidecar that cannot be parsed is *not* an error the user must deal
        with here: the page falls back to the hint, exactly as if there were no
        file, and the details go to the log.

        It happens once: [Indietro] then [Avanti] must not undo the edits the
        user made in between — including emptying the table on purpose.
        """
        if self._prefilled:
            return
        self._prefilled = True
        try:
            self._prefill()
        finally:
            self._refresh_warning()

    def _prefill(self) -> None:
        configured = self._services.config.load().environments
        if configured:
            self.table.set_environments(configured)
            self.hint_label.setText(strings.WIZARD_P2_CONFIGURED_LOADED)
            return
        sidecar = self._services.config.find_sidecar_environments()
        if sidecar is None:
            return
        try:
            self.table.set_environments(self._services.config.import_environments_file(sidecar))
        except ValueError as exc:
            log.warning("environments.json accanto all'eseguibile non leggibile: %s", exc)
            return
        self.hint_label.setText(strings.WIZARD_P2_SIDECAR_LOADED.format(path=sidecar))

    # -- what the wizard asks ----------------------------------------------

    def validatePage(self) -> bool:
        """``config.validate`` on the configuration this page would produce.

        Validating a whole ``Config`` rather than the rows by hand is what keeps
        the wizard and Impostazioni from drifting apart: there is one set of
        rules and it lives in the core.
        """
        errors = self._services.config.validate(self._candidate_config())
        self.error_label.setText("\n".join(errors))
        self.error_label.setVisible(bool(errors))
        self._refresh_warning()
        return not errors

    def cancel_jobs(self) -> None:
        """The wizard is closing: stop probing between environments."""
        if self._check_job is not None:
            self._check_job.cancel()

    # -- the answer ---------------------------------------------------------

    def environments(self) -> list[Environment]:
        return self.table.environments()

    # -- buttons ------------------------------------------------------------

    def add_environment(self) -> None:
        self.table.add_row()

    def remove_selected(self) -> None:
        self.table.remove_selected()

    def import_environments(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, strings.ENV_IMPORT_CAPTION, "", strings.ENV_IMPORT_FILTER
        )
        if not path:
            return
        try:
            self.table.import_from_file(Path(path), self._services.config.import_environments_file)
        except ValueError as exc:
            QMessageBox.warning(
                self,
                strings.ENV_IMPORT_ERROR_TITLE,
                strings.ENV_IMPORT_ERROR.format(error=exc),
            )
            return
        self.hint_label.setText(strings.WIZARD_P2_SIDECAR_LOADED.format(path=path))

    def check_reachability(self) -> Job | None:
        """One short HTTP GET per environment, in the shared runner.

        The rows are read here, on the GUI thread, and only the resulting
        frozen ``Environment`` dataclasses travel to the worker: the table is a
        widget and a worker never touches one. The URLs go with them — during
        the wizard nothing has been saved yet, so a probe by name alone would
        have no configuration to resolve against and would report every
        environment unreachable.
        """
        envs = [e for e in self.environments() if e.name]
        self.reachability_label.setVisible(True)
        if not envs:
            self.reachability_label.setText(strings.WIZARD_P2_CHECK_EMPTY)
            return None
        job = self._runner.submit(
            REACHABILITY_JOB, _probe_reachability, self._services.sync.check_reachable, envs
        )
        self._check_job = job
        if job is None:  # the application is shutting down
            return None
        self.reachability_label.setText(strings.WIZARD_P2_CHECK_RUNNING)
        job.signals.result.connect(self._show_reachability)
        return job

    # -- internals ----------------------------------------------------------

    def _refresh_warning(self) -> None:
        """Zero enabled environments is allowed, so this warns rather than
        blocks — live, on every edit of the table, while the page is on screen.
        """
        nothing_enabled = not any(e.enabled for e in self.environments())
        self.warning_label.setText(strings.WIZARD_P2_NO_ENVIRONMENTS if nothing_enabled else "")
        self.warning_label.setVisible(nothing_enabled)

    def _show_reachability(self, outcome: dict) -> None:
        self.reachability_label.setText(
            strings.WIZARD_P2_CHECK_SEPARATOR.join(
                strings.WIZARD_P2_CHECK_RESULT.format(
                    env=name,
                    state=(strings.WIZARD_P2_REACHABLE if reachable
                           else strings.WIZARD_P2_UNREACHABLE),
                )
                for name, reachable in outcome.items()
            )
        )

    def _candidate_config(self) -> Config:
        return dataclasses.replace(
            self._services.config.load(), environments=self.environments()
        )


def _probe_reachability(check, envs: list[Environment], *, cancel) -> dict[str, bool]:
    """Runs on a pool thread: plain data in, plain data out, no widgets.

    ``cancel`` is injected by the worker and checked between environments. Each
    probe is a blocking GET with a several-second timeout, so without this a
    wizard closed mid-check would keep the pool busy for one timeout *per*
    environment and outlive ``JobRunner.shutdown``'s wait.
    """
    outcome: dict[str, bool] = {}
    for env in envs:
        if cancel.is_set():
            break
        outcome[env.name] = check(env)
    return outcome
