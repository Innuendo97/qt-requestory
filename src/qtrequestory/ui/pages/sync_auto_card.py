"""The top card of the Sincronizzazione page: automatic sync and the commands.

It answers the page's first question — *is the automatic sync on?* — with a
switch, a title ("Sincronizzazione automatica attiva") and a muted line (the
schedule in words, the next run, the last one), and carries the page's
commands: [Modifica orari], the primary [Sincronizza ora] with its "Solo
<env>" menu, and [Annulla] only while a run is in flight.

**The task scheduler is never asked on the GUI thread** (BACKLOG item 1):
``scheduler.status()`` runs two ``schtasks`` processes, so it goes through the
runner under :data:`TASK_STATUS_JOB`. The answer is cached in :attr:`task`;
until it comes the card says "verifica in corso…" and the switch is disabled.
A failure — reading the status, registering, or a registration refused
because Impostazioni is updating the task at that very moment — is a
persistent warn banner with [Riprova], never a status-bar line that vanishes.
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QRectF, QSignalBlocker, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import CoreServices, TaskStatus
from qtrequestory.ui.pages import sync_format as fmt
from qtrequestory.ui.workers import SCHEDULER_JOB, Job, JobRunner

__all__ = ["AutoSyncCard", "SwitchButton", "TASK_STATUS_JOB"]

#: The runner name of ``scheduler.status()`` (not exclusive: a newer read
#: supersedes an older one).
TASK_STATUS_JOB = "sync-task-status"


class SwitchButton(QAbstractButton):
    """A checkable on/off switch painted from the theme tokens."""

    TRACK = QSize(34, 18)
    KNOB_MARGIN = 3

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        theme.signals.changed.connect(self.update)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        return self.TRACK + QSize(4, 4)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt naming
        t = theme.tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(2, 2, self.TRACK.width(), self.TRACK.height())
        on = self.isChecked()
        if not self.isEnabled():
            fill, knob = QColor(t.neutral_bg), QColor(t.surface)
        elif on:
            fill, knob = QColor(t.accent), QColor(t.on_accent)
        else:
            fill, knob = QColor(t.border), QColor(t.surface)
        painter.setPen(QColor(t.accent) if self.hasFocus() else Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        radius = track.height() / 2
        painter.drawRoundedRect(track, radius, radius)
        size = track.height() - 2 * self.KNOB_MARGIN
        x = (track.right() - self.KNOB_MARGIN - size) if on else (track.left() + self.KNOB_MARGIN)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(knob)
        painter.drawEllipse(QRectF(x, track.top() + self.KNOB_MARGIN, size, size))
        painter.end()


class AutoSyncCard(QFrame):
    """Switch + title + schedule line, the sync commands, and the task's banner."""

    #: ``(envs, dry_run)`` — ``envs`` is None for "every enabled environment".
    sync_requested = Signal(object, bool)
    cancel_requested = Signal()

    def __init__(self, services: CoreServices, runner: JobRunner,
                 window: object | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._services = services
        self._runner = runner
        self._window = window
        #: The last ``TaskStatus`` read, or None until the first answer.
        self.task: TaskStatus | None = None
        self.status_job: Job | None = None
        self.scheduler_job: Job | None = None
        self._retry: Callable[[], None] | None = None
        theme.set_role(self, "card")
        self._build()

    # -- construction ------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SPACE[3], theme.SPACE[2], theme.SPACE[3], theme.SPACE[2])
        layout.setSpacing(theme.SPACE[1])

        row = QHBoxLayout()
        row.setSpacing(theme.SPACE[2])
        self.switch = SwitchButton()
        self.switch.setAccessibleName(strings.SYNC_AUTO_TITLE)
        self.switch.toggled.connect(self._on_toggled)
        texts = QVBoxLayout()
        texts.setSpacing(0)
        self.title_label = QLabel(strings.SYNC_AUTO_TITLE)
        theme.set_role(self.title_label, "section")
        self.status_label = QLabel(strings.SYNC_AUTO_CHECKING)
        self.status_label.setWordWrap(True)
        theme.set_role(self.status_label, "muted")
        texts.addWidget(self.title_label)
        texts.addWidget(self.status_label)

        self.edit_button = QPushButton(strings.SYNC_AUTO_EDIT)
        self.edit_button.setToolTip(strings.SYNC_AUTO_EDIT_TOOLTIP)
        self.edit_button.clicked.connect(self.open_schedule_settings)

        self.sync_menu = QMenu(self)  # filled by rebuild_menu (it follows the config)
        self.sync_button = QToolButton()
        self.sync_button.setText(strings.SYNC_BTN_NOW)
        self.sync_button.setToolTip(strings.SYNC_BTN_NOW_TOOLTIP)
        self.sync_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.sync_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.sync_button.setMenu(self.sync_menu)
        theme.set_role(self.sync_button, "primary")
        self.sync_button.clicked.connect(lambda: self.sync_requested.emit(None, False))

        self.cancel_button = QPushButton(strings.BTN_CANCEL)
        self.cancel_button.clicked.connect(self.cancel_requested)
        self.cancel_button.hide()

        row.addWidget(self.switch, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addLayout(texts, 1)
        row.addWidget(self.edit_button, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.cancel_button, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.sync_button, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(row)

        self.exe_row = QWidget()
        exe = QHBoxLayout(self.exe_row)
        exe.setContentsMargins(0, 0, 0, 0)
        self.exe_warning = QLabel()
        self.exe_warning.setWordWrap(True)
        self.exe_button = QPushButton(strings.SYNC_AUTO_EXE_UPDATE)
        self.exe_button.clicked.connect(lambda: self._run_scheduler(True))
        exe.addWidget(self.exe_warning, 1)
        exe.addWidget(self.exe_button)
        self.exe_row.hide()
        layout.addWidget(self.exe_row)

        self.banner = QFrame()
        theme.set_role(self.banner, "syncBanner")
        banner = QHBoxLayout(self.banner)
        banner.setContentsMargins(theme.SPACE[2], theme.SPACE[1], theme.SPACE[1], theme.SPACE[1])
        self.banner_label = QLabel()
        self.banner_label.setWordWrap(True)
        self.retry_button = QPushButton(strings.SYNC_AUTO_RETRY)
        self.retry_button.clicked.connect(self._on_retry)
        banner.addWidget(self.banner_label, 1)
        banner.addWidget(self.retry_button)
        self.banner.hide()
        layout.addWidget(self.banner)
        self._paint_task()

    def rebuild_menu(self, environments: list[str]) -> None:
        self.sync_menu.clear()
        self.sync_menu.addAction(strings.SYNC_MENU_ALL).triggered.connect(
            lambda: self.sync_requested.emit(None, False))
        self.sync_menu.addSeparator()
        for name in environments:
            action = self.sync_menu.addAction(strings.SYNC_MENU_ONLY.format(env=name))
            action.triggered.connect(
                lambda _checked=False, env=name: self.sync_requested.emit([env], False))
        self.sync_menu.addSeparator()
        self.sync_menu.addAction(strings.SYNC_MENU_DRY_RUN).triggered.connect(
            lambda: self.sync_requested.emit(None, True))

    # -- the page drives these ---------------------------------------------

    def set_running(self, running: bool) -> None:
        """[Annulla] exists only while a run does; [Sincronizza ora] rests."""
        self.cancel_button.setVisible(running)
        self.cancel_button.setEnabled(running)

    def set_sync_enabled(self, enabled: bool) -> None:
        self.sync_button.setEnabled(enabled)

    def open_schedule_settings(self) -> None:
        """Impostazioni › Sincronizzazione automatica (wave-D contract)."""
        show_page = getattr(self._window, "show_page", None)
        if not callable(show_page):
            return
        show_page("settings")
        page = getattr(self._window, "page", None)
        settings = page("settings") if callable(page) else None
        show_section = getattr(settings, "show_section", None)
        if callable(show_section):
            show_section("automation")

    # -- the task's status, off the GUI thread -----------------------------

    def refresh_scheduler(self) -> None:
        """Ask for the task's status in a worker; the card repaints on the answer."""
        job = self._runner.submit(TASK_STATUS_JOB, self._services.scheduler.status)
        if job is None:  # the application is closing
            return
        self.status_job = job
        if self.task is None:
            self._paint_task()
        job.signals.result.connect(self._on_status)
        job.signals.error.connect(self._on_status_error)

    def _on_status(self, task: TaskStatus) -> None:
        self.task = task
        if self._retry == self.refresh_scheduler:
            self._hide_banner()
        self._paint_task()

    def _on_status_error(self, _kind: str, error: str) -> None:
        self._show_banner(strings.SYNC_AUTO_STATUS_FAILED.format(error=error),
                          self.refresh_scheduler)
        self._paint_task()

    def _paint_task(self) -> None:
        """Title, line, switch and exe warning from the cached status."""
        task = self.task
        busy = self._runner.is_running(SCHEDULER_JOB) and self.scheduler_job is not None
        self.title_label.setText(fmt.auto_title(task))
        with QSignalBlocker(self.switch):  # a repaint is not a user decision
            self.switch.setChecked(bool(task and task.registered))
        self.switch.setEnabled(task is not None and not busy)
        self.exe_button.setEnabled(not busy)
        if task is None:
            self.status_label.setText(strings.SYNC_AUTO_CHECKING)
            self.exe_row.hide()
            return
        self.status_label.setText(
            fmt.format_task_status(task, self._services.config.load().schedule))
        mismatch = task.registered and not task.exe_matches
        self.exe_warning.setText(
            strings.SYNC_AUTO_EXE_MISMATCH.format(path=task.command) if mismatch else "")
        self.exe_row.setVisible(mismatch)

    # -- registering and unregistering -------------------------------------

    def _on_toggled(self, checked: bool) -> None:
        reason = self._services.scheduler.unstable_location_reason() if checked else None
        if reason is not None and not self.confirm_unstable(reason):
            self._paint_task()
            return
        self._run_scheduler(checked)

    def _run_scheduler(self, register: bool) -> None:
        """``schtasks`` is a subprocess call: never on the GUI thread."""
        scheduler = self._services.scheduler
        job = self._runner.submit(SCHEDULER_JOB,
                                  scheduler.register if register else scheduler.unregister)
        if job is None:
            # Refused (Impostazioni is re-registering) or the application is
            # closing: nothing will run. The switch goes back to the truth and
            # the banner says why, with a way to try again.
            self._show_banner(strings.SYNC_AUTO_REFUSED, lambda: self._run_scheduler(register))
            self._paint_task()
            return
        self.scheduler_job = job
        self._hide_banner()
        self.switch.setEnabled(False)  # two schtasks calls could land in either order
        self.exe_button.setEnabled(False)
        job.signals.error.connect(
            lambda _kind, error: self._show_banner(
                strings.SYNC_AUTO_FAILED.format(error=error),
                lambda: self._run_scheduler(register)))
        job.signals.finished.connect(self._on_scheduler_finished)

    def _on_scheduler_finished(self) -> None:
        self.scheduler_job = None
        self._paint_task()
        self.refresh_scheduler()

    def confirm_unstable(self, reason: str) -> bool:
        """Show the "posizione poco stabile" question; True = register anyway."""
        box = self.build_unstable_dialog(reason)
        try:
            return box.exec() == QMessageBox.StandardButton.Yes
        finally:
            box.deleteLater()

    def build_unstable_dialog(self, reason: str) -> QMessageBox:
        """The dialog without showing it, so its wording can be tested."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(strings.SYNC_AUTO_UNSTABLE_TITLE)
        box.setText(strings.SYNC_AUTO_UNSTABLE_TEXT.format(reason=reason))
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        box.button(QMessageBox.StandardButton.Yes).setText(strings.SYNC_AUTO_UNSTABLE_OK)
        box.button(QMessageBox.StandardButton.No).setText(strings.BTN_CANCEL)
        return box

    # -- the banner --------------------------------------------------------

    def _show_banner(self, text: str, retry: Callable[[], None] | None) -> None:
        self.banner_label.setText(text)
        self._retry = retry
        self.retry_button.setVisible(retry is not None)
        self.banner.show()

    def _hide_banner(self) -> None:
        self._retry = None
        self.banner.hide()

    def _on_retry(self) -> None:
        retry = self._retry
        self._hide_banner()
        if retry is not None:
            retry()
