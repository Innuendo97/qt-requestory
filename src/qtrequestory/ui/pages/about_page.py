"""The Info page: what this build is, where it keeps its files, what it logged.

It is the page a user is asked to open when something went wrong, so the four
paths are selectable text (they end up pasted into a chat) and each one can be
revealed in Explorer; the text files can also be opened in the editor.

The log tail is read in a worker even though it is at most 1 MB: ``app.log``
lives in ``%LOCALAPPDATA%``, which can be a slow redirected folder, and a page
that blocks the GUI thread on a file read is a page that freezes on exactly the
machine where the log matters.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import CoreServices
from qtrequestory.ui.workers import JobRunner

#: How much of ``app.log`` the viewer shows (DESIGN-ui §Info page).
MAX_LOG_LINES = 500
#: Job name: a second [Aggiorna] supersedes the first, it does not queue.
LOG_JOB = "about-log"
MONOSPACE_FAMILIES = ("Cascadia Mono", "Consolas")


def tail_lines(path: Path, n: int) -> list[str]:
    """The last ``n`` lines of ``path``; a missing or unreadable file is empty.

    A deque over the open file keeps the memory bounded by ``n`` and never
    seeks, which is what makes it safe on a UTF-8 file: cutting a rotating log
    by byte offset would land in the middle of a multi-byte character.
    """
    try:
        with Path(path).open("r", encoding="utf-8", errors="replace") as handle:
            return [line.rstrip("\n") for line in deque(handle, maxlen=n)]
    except OSError:
        return []


class AboutPage(QWidget):
    """Version, paths and the tail of the application log."""

    FILTER_ALL = "all"
    FILTER_WARNINGS = "warn"
    FILTER_ERRORS = "error"
    #: Uppercase tokens that mark a line. ``logsetup`` writes ``[ts] message``
    #: without a level field, so the level of a line that matters shows up as
    #: the uppercase word the message itself carries; the match is
    #: case-sensitive on purpose, so an Italian "errore" is not an ERROR.
    TOKENS = {FILTER_WARNINGS: ("WARN",), FILTER_ERRORS: ("ERROR",)}

    #: ``(key, label, can_open_as_text)`` — the index database is binary, so it
    #: only offers its folder.
    PATH_ROWS = (
        ("config", strings.ABOUT_PATH_CONFIG, True),
        ("index", strings.ABOUT_PATH_INDEX, False),
        ("app_log", strings.ABOUT_PATH_APP_LOG, True),
        ("sync_log", strings.ABOUT_PATH_SYNC_LOG, True),
    )

    def __init__(
        self,
        services: CoreServices,
        runner: JobRunner,
        window: object | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._services = services
        self._runner = runner
        self._window = window
        self._lines: list[str] = []
        #: False while the log job is in flight; the tests wait on it.
        self.log_loaded = False

        self.path_labels: dict[str, QLabel] = {}
        self.folder_buttons: dict[str, QPushButton] = {}
        self.open_buttons: dict[str, QPushButton] = {}
        self._build()
        self._refresh_paths()
        self.refresh()

    # -- construction ------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        self.title_label = QLabel(strings.APP_NAME)
        title_font = self.title_label.font()
        title_font.setPointSize(title_font.pointSize() + 4)
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        self.version_label = QLabel(
            strings.ABOUT_VERSION.format(version=self._services.version())
        )
        layout.addWidget(self.title_label)
        layout.addWidget(QLabel(strings.ABOUT_SUBTITLE))
        layout.addWidget(self.version_label)
        layout.addWidget(self._paths_box())
        layout.addWidget(QLabel(strings.ABOUT_LOG_LABEL))
        layout.addLayout(self._log_toolbar())
        layout.addWidget(self._log_view(), 1)

    def _paths_box(self) -> QFrame:
        box = QFrame()
        box.setFrameShape(QFrame.Shape.StyledPanel)
        grid = QGridLayout(box)
        for row, (key, label, openable) in enumerate(self.PATH_ROWS):
            value = QLabel()
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
            value.setWordWrap(True)
            self.path_labels[key] = value
            grid.addWidget(QLabel(label), row, 0)
            grid.addWidget(value, row, 1)
            if openable:
                self.open_buttons[key] = self._button(
                    strings.BTN_OPEN, lambda k=key: self._open_file(k)
                )
                grid.addWidget(self.open_buttons[key], row, 2)
            self.folder_buttons[key] = self._button(
                strings.BTN_OPEN_FOLDER, lambda k=key: self._open_folder(k)
            )
            grid.addWidget(self.folder_buttons[key], row, 3)
        grid.setColumnStretch(1, 1)
        return box

    def _log_toolbar(self) -> QHBoxLayout:
        self.filter_combo = QComboBox()
        for text, mode in (
            (strings.ABOUT_FILTER_ALL, self.FILTER_ALL),
            (strings.ABOUT_FILTER_WARNINGS, self.FILTER_WARNINGS),
            (strings.ABOUT_FILTER_ERRORS, self.FILTER_ERRORS),
        ):
            self.filter_combo.addItem(text, mode)
        self.filter_combo.currentIndexChanged.connect(lambda _index: self._render())
        self.refresh_button = self._button(strings.BTN_REFRESH, self.refresh)
        self.copy_button = self._button(strings.ABOUT_BTN_COPY_ALL, self._copy_all)

        row = QHBoxLayout()
        row.addWidget(self.filter_combo)
        row.addStretch(1)
        row.addWidget(self.refresh_button)
        row.addWidget(self.copy_button)
        return row

    def _log_view(self) -> QPlainTextEdit:
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        font = QFont(MONOSPACE_FAMILIES[0])
        font.setFamilies(list(MONOSPACE_FAMILIES))
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.log_view.setFont(font)
        return self.log_view

    def _button(self, text: str, slot: Callable[[], None]) -> QPushButton:
        button = QPushButton(text)
        button.clicked.connect(lambda _checked=False: slot())
        return button

    # -- paths -------------------------------------------------------------

    def _paths(self) -> dict[str, Path]:
        return {
            "config": self._services.config.config_path(),
            "index": self._services.index_db_path(),
            "app_log": self._services.app_log_path(),
            "sync_log": self._services.sync_log_path(),
        }

    def _refresh_paths(self) -> None:
        for key, path in self._paths().items():
            self.path_labels[key].setText(str(path))

    def on_config_changed(self, _cfg: object) -> None:
        """Impostazioni saved: the index lives under the mirror root, so a new
        mirror folder means a new database path to show."""
        self._refresh_paths()
        self.refresh()

    def _open_folder(self, key: str) -> None:
        self._services.extract.open_folder(self._paths()[key].parent)

    def _open_file(self, key: str) -> None:
        self._services.extract.open_in_editor([self._paths()[key]])

    # -- the log -----------------------------------------------------------

    def refresh(self) -> None:
        """Re-read the tail of ``app.log`` in a worker."""
        self.log_loaded = False
        self.log_view.setPlainText(strings.ABOUT_LOG_LOADING)
        job = self._runner.submit(LOG_JOB, tail_lines, self._services.app_log_path(),
                                  MAX_LOG_LINES)
        if job is None:  # shutting down
            self.log_loaded = True
            return
        job.signals.result.connect(self._on_lines)
        job.signals.error.connect(self._on_error)

    def _on_lines(self, lines: object) -> None:
        self._lines = list(lines or [])
        self.log_loaded = True
        self._render()

    def _on_error(self, _kind: str, message: str) -> None:
        self._lines = []
        self.log_loaded = True
        self.log_view.setPlainText(strings.ABOUT_LOG_FAILED.format(message=message))

    def set_filter(self, mode: str) -> None:
        """Select Tutti / Avvisi / Errori by its mode token."""
        index = self.filter_combo.findData(mode)
        if index >= 0:
            self.filter_combo.setCurrentIndex(index)

    def current_filter(self) -> str:
        return self.filter_combo.currentData()

    def _render(self) -> None:
        mode = self.current_filter()
        tokens = self.TOKENS.get(mode)
        shown = self._lines if tokens is None else [
            line for line in self._lines if any(token in line for token in tokens)
        ]
        self.log_view.setPlainText("\n".join(shown) if shown else strings.ABOUT_LOG_EMPTY)

    def _copy_all(self) -> None:
        QGuiApplication.clipboard().setText(self.log_view.toPlainText())
        self._status(strings.ABOUT_LOG_COPIED)

    def _status(self, text: str) -> None:
        setter = getattr(self._window, "set_status", None)
        if callable(setter):
            setter(text)
