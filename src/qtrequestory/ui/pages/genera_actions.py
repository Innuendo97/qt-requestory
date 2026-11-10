"""The Genera tab's action bar: pinned at the bottom of the tab, outside the
scrolling part, so the one button that matters is always on screen — in
every mode and on a 1366×768 laptop (the Elenco list used to push it below
the fold).

Top to bottom: the two options (zip, HTML); **the** button with, during a
run, the progress next to it; the one-line problem under it while it cannot
be pressed. A hairline on top separates it from what scrolls
(``QFrame#generaActionBar`` in ``theme_qss``).

**One click is one click.** A double click on the button arrives on
Windows as press, release, double-click, release: Qt makes TWO clicks of
it, and the second would hit [Interrompi] the instant the run started.
The double-click event is swallowed (:class:`_NoDoubleClick`), so a double
click generates once, while a deliberate single click on [Interrompi] right
after the start still stops.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import strings, theme
from qtrequestory.ui.pages.settings_widgets import muted

__all__ = ["GeneraActionBar"]


class _NoDoubleClick(QObject):
    """Event filter: the button never sees a double click (module docstring)."""

    def eventFilter(self, _watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt naming
        return event.type() == QEvent.Type.MouseButtonDblClick


class GeneraActionBar(QFrame):
    """Options, button, progress and problem (module docstring)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("generaActionBar")
        self.zip_box = QCheckBox(strings.GENERA_ZIP)
        self.html_box = QCheckBox(strings.GENERA_HTML)
        self.html_box.setToolTip(strings.GENERA_HTML_TIP)
        options = QHBoxLayout()
        options.setSpacing(theme.SPACE[4])
        options.addWidget(self.zip_box)
        options.addWidget(self.html_box)
        options.addStretch(1)

        self.start_button = QPushButton(strings.GENERA_START)
        theme.set_role(self.start_button, "primary")
        self.start_button.setToolTip(strings.GENERA_START_TIP)
        self.start_button.setMinimumWidth(220)
        # its own width, not the row's: a full-width bar does not read as a button
        self.start_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._no_double_click = _NoDoubleClick(self)
        self.start_button.installEventFilter(self._no_double_click)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setMaximumWidth(320)
        self.progress_label = muted()
        action = QHBoxLayout()
        action.setSpacing(theme.SPACE[3])
        action.addWidget(self.start_button)
        action.addWidget(self.progress_bar, 1)
        action.addWidget(self.progress_label)
        action.addStretch(1)
        self.problem_label = QLabel()
        self.problem_label.setWordWrap(True)
        self.problem_label.setProperty("dot", "warn")
        theme.repolish(self.problem_label)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SPACE[4], theme.SPACE[2], theme.SPACE[4], theme.SPACE[2])
        layout.setSpacing(theme.SPACE[2])
        layout.addLayout(options)
        layout.addLayout(action)
        layout.addWidget(self.problem_label)
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)

    def set_running(self, running: bool, status: str = "") -> None:
        """[Interrompi] + an indeterminate bar and ``status`` while a run (or
        its lookup) goes; the primary [Genera] again after."""
        for box in (self.zip_box, self.html_box):
            box.setEnabled(not running)
        self.progress_bar.setVisible(running)
        self.progress_label.setVisible(running)
        if running:
            self.problem_label.setVisible(False)
            self.start_button.setText(strings.GENERA_STOP)
            self.start_button.setToolTip(strings.GENERA_STOP_TIP)
            self.start_button.setEnabled(True)
            theme.set_role(self.start_button, "")
            self.progress_bar.setRange(0, 0)  # indeterminate until BatchStarted
            self.progress_label.setText(status)
        else:
            theme.set_role(self.start_button, "primary")
            self.start_button.setToolTip(strings.GENERA_START_TIP)

    def show_progress(self, done: int, total: int, *, label: bool = True) -> None:
        self.progress_bar.setRange(0, max(total, 1))
        self.progress_bar.setValue(done)
        if label:
            self.progress_label.setText(strings.GENERA_PROGRESS.format(done=done, total=total))

    def show_idle(self, text: str, problems: list[str]) -> None:
        """Not running: the button says what it will do, or the first problem why not."""
        self.start_button.setText(text)
        self.start_button.setEnabled(not problems)
        self.problem_label.setText(problems[0] if problems else "")
        self.problem_label.setVisible(bool(problems))
