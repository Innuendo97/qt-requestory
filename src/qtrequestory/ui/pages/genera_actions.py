"""The Genera setup pane's footer: pinned at the bottom of the pane, outside
what scrolls, so the one button that matters is always on screen — in every
mode, with the headers open, and on a 1366×768 laptop.

Top to bottom: a reminder that the headers differ from Impostazioni ("Header:
1 modificato  Mostra  Ripristina"), only while the Header step itself is
scrolled out of view (``GeneraSetup`` decides); the two options (email, zip);
**the** button, as wide as the pane, saying what it will do ("Genera 12
documenti"); the one-line problem under it while it cannot be pressed. During a run the button is [Interrompi];
the progress itself is at the top of the results pane (``genera_results``),
where the rows arrive. A hairline on top separates the footer from what
scrolls (``QFrame#generaActionBar`` in ``theme_qss_genera``).

**One click is one click.** A double click on the button arrives on
Windows as press, release, double-click, release: Qt makes TWO clicks of
it, and the second would hit [Interrompi] the instant the run started.
The double-click event is swallowed (:class:`_ButtonKeys`), so a double
click generates once, while a deliberate single click on [Interrompi] right
after the start still stops. **Enter** on the focused button presses it
(outside a dialog a push button takes only Space).
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import strings, theme

__all__ = ["BUTTON_HEIGHT", "GeneraActionBar"]

#: The button: taller than an ordinary one, it is the page's only action.
BUTTON_HEIGHT = 36

_ENTER = (Qt.Key.Key_Return, Qt.Key.Key_Enter)


class _ButtonKeys(QObject):
    """Event filter: no double click; Enter presses (module docstring)."""

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt naming
        if event.type() == QEvent.Type.MouseButtonDblClick:
            return True
        if (event.type() == QEvent.Type.KeyPress and event.key() in _ENTER
                and event.modifiers() == Qt.KeyboardModifier.NoModifier):
            if watched.isEnabled():
                watched.click()
            return True
        return False


class GeneraActionBar(QFrame):
    """Options, button and problem (module docstring)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("generaActionBar")
        self.zip_box = QCheckBox(strings.GENERA_ZIP)
        self.zip_box.setToolTip(strings.GENERA_ZIP_TIP)
        self.html_box = QCheckBox(strings.GENERA_HTML)
        self.html_box.setToolTip(strings.GENERA_HTML_TIP)
        self.headers_reminder = self._reminder()
        options = QHBoxLayout()
        options.setSpacing(theme.SPACE[4])
        options.addWidget(self.html_box)
        options.addWidget(self.zip_box)
        options.addStretch(1)

        self.start_button = QPushButton(strings.GENERA_START)
        theme.set_role(self.start_button, "primary")
        self.start_button.setToolTip(strings.GENERA_START_TIP)
        self.start_button.setMinimumHeight(BUTTON_HEIGHT)
        self.start_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._keys = _ButtonKeys(self)
        self.start_button.installEventFilter(self._keys)
        self.problem_label = QLabel()
        self.problem_label.setWordWrap(True)
        self.problem_label.setProperty("dot", "warn")
        theme.repolish(self.problem_label)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SPACE[3] + theme.SPACE[0], theme.SPACE[2] + theme.SPACE[0],
                                  theme.SPACE[3] + theme.SPACE[0], theme.SPACE[3])
        layout.setSpacing(theme.SPACE[2])
        layout.addWidget(self.headers_reminder)
        layout.addLayout(options)
        layout.addWidget(self.start_button)
        layout.addWidget(self.problem_label)
        self.problem_label.setVisible(False)

    def _reminder(self) -> QWidget:
        """"Header: 1 modificato   Mostra · Ripristina" (hidden until needed)."""
        self.headers_note = QLabel()
        self.headers_note.setProperty("pill", "warn")
        self.headers_note.setToolTip(strings.GENERA_HEADERS_MODIFIED_TIP)
        theme.repolish(self.headers_note)
        self.headers_show = QPushButton(strings.GENERA_HEADERS_SHOW)
        self.headers_show.setToolTip(strings.GENERA_HEADERS_SHOW_TIP)
        self.headers_reset = QPushButton(strings.GENERA_HEADERS_RESET)
        self.headers_reset.setToolTip(strings.GENERA_HEADERS_RESET_TIP)
        for link in (self.headers_show, self.headers_reset):
            theme.set_role(link, "link")
            link.setCursor(Qt.CursorShape.PointingHandCursor)
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(theme.SPACE[2])
        line.addWidget(self.headers_note)
        line.addStretch(1)
        line.addWidget(self.headers_show)
        line.addWidget(self.headers_reset)
        row.setVisible(False)
        return row

    def show_headers_reminder(self, modified: str) -> None:
        """``modified`` is the pill's text ("1 modificato"); "" hides the line."""
        self.headers_note.setText(strings.GENERA_HEADERS_REMINDER.format(modified=modified) if modified else "")
        self.headers_reminder.setVisible(bool(modified))

    def set_running(self, running: bool) -> None:
        """[Interrompi] while a run (or its lookup) goes; the primary [Genera] after."""
        for widget in (self.zip_box, self.html_box, self.headers_reminder):
            widget.setEnabled(not running)
        self.start_button.setProperty("running", running)
        if running:
            self.problem_label.setVisible(False)
            self.start_button.setText(strings.GENERA_STOP)
            self.start_button.setToolTip(strings.GENERA_STOP_TIP)
            self.start_button.setEnabled(True)
            theme.set_role(self.start_button, "")
        else:
            theme.set_role(self.start_button, "primary")
            self.start_button.setToolTip(strings.GENERA_START_TIP)

    def show_idle(self, text: str, problems: list[str]) -> None:
        """Not running: the button says what it will do, or the first problem why not."""
        self.start_button.setText(text)
        self.start_button.setEnabled(not problems)
        self.problem_label.setText(problems[0] if problems else "")
        self.problem_label.setVisible(bool(problems))
