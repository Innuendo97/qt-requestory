"""The Info page: what this build is, where it keeps its files, what it logged.

It is the page a user is asked to open when something went wrong, so it is
laid out as four cards: "Versione", "Percorsi" (each path on one line, elided
in the middle rather than wrapped mid-word, with [Copia] — they end up pasted
into a chat — [Apri] for the text files and an [Apri cartella] icon), "Indice"
(what is indexed per environment) and "Log", beside the other three.

The log tail is read in a worker even though it is at most 1 MB: ``app.log``
lives in ``%LOCALAPPDATA%``, which can be a slow redirected folder, and a page
that blocks the GUI thread on a file read is a page that freezes on exactly the
machine where the log matters.
"""
from __future__ import annotations

import re
from collections import deque
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import CoreServices
from qtrequestory.ui.pages.settings_widgets import ElidedLabel, button, icon_button, muted
from qtrequestory.ui.workers import JobRunner

#: How much of ``app.log`` the viewer shows (DESIGN-ui §Info page).
MAX_LOG_LINES = 500
#: Job name: a second [Aggiorna] supersedes the first, it does not queue.
LOG_JOB = "about-log"

#: ``core.logsetup.APP_LOG_FORMAT`` is ``[<asctime>] <LEVELNAME> <message>``.
#: Only the level *field* is read — matching the word anywhere in the line
#: would turn a message that merely mentions an error into one.
LEVEL_RE = re.compile(r"^\[[^]]*\]\s+(?P<level>[A-Z]{4,8})\s")
#: What starts a record: the bracketed timestamp. Anything else — a traceback,
#: a multi-line message, a JSON fragment — continues the record above it.
RECORD_START_RE = re.compile(r"^\[\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}[^]]*\]")
#: Grid columns of a path row. [Apri] stays empty for the (binary) index, so
#: the buttons after it keep their column.
PATH_COL_LABEL, PATH_COL_VALUE, PATH_COL_COPY, PATH_COL_OPEN, PATH_COL_FOLDER = range(5)
#: The label column of the Percorsi and Indice cards.
LABEL_COLUMN_WIDTH = 130
#: The narrowest the column of cards may get; the log takes the rest.
CARDS_MIN_WIDTH = 460
DAY_FORMAT = "%d/%m/%Y"


def line_level(line: str) -> str | None:
    """The level a log line carries, or None for a line written without one.

    ``app.log`` only gained its level field in this version, so a mirror that
    has been in use for a while still holds level-less lines: they are not an
    error, they simply belong to no level filter.
    """
    match = LEVEL_RE.match(line)
    return match.group("level") if match is not None else None


def filter_records(lines: Sequence[str], levels: frozenset[str] | None) -> list[str]:
    """The lines of the records whose level is in ``levels`` (None: every line).

    A record is a line starting with a timestamp plus every following line
    that does not: a traceback belongs to the ERROR above it, and filtering it
    away would hide the one useful part. Continuation lines at the very top of
    the tail lost their record to the cut, so they carry no level and only the
    unfiltered view shows them.
    """
    if levels is None:
        return list(lines)
    kept: list[str] = []
    keep = False
    for line in lines:
        if RECORD_START_RE.match(line):
            keep = line_level(line) in levels
        if keep:
            kept.append(line)
    return kept


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
    """Version, paths, index and the tail of the application log."""

    FILTER_ALL = "all"
    FILTER_WARNINGS = "warn"
    FILTER_ERRORS = "error"
    #: Which ``logging`` level names each filter keeps. ``CRITICAL`` belongs
    #: with the errors: a user looking for what went wrong must not have to
    #: know that the worst failures are logged under a different name.
    LEVELS = {
        FILTER_WARNINGS: frozenset({"WARNING"}),
        FILTER_ERRORS: frozenset({"ERROR", "CRITICAL"}),
    }

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

        self.path_labels: dict[str, ElidedLabel] = {}
        self.copy_buttons: dict[str, QPushButton] = {}
        self.open_buttons: dict[str, QPushButton] = {}
        self.folder_buttons: dict[str, QPushButton] = {}
        self.index_labels: dict[str, QLabel] = {}
        self._build()
        self._refresh_paths()
        self._refresh_index()
        self.refresh()

    # -- construction ------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)  # as Sincronizzazione
        layout.setSpacing(theme.SPACE[2])
        self.title_label = QLabel(strings.ABOUT_TITLE)
        theme.set_role(self.title_label, "pageTitle")
        layout.addWidget(self.title_label)

        cards = QWidget()
        column = QVBoxLayout(cards)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(theme.SPACE[2])
        column.addWidget(self._version_card())
        column.addWidget(self._paths_card())
        column.addWidget(self._index_card())
        column.addStretch(1)
        scroll = QScrollArea()  # nothing is clipped on a 1366x768 laptop
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(cards)
        scroll.setMinimumWidth(CARDS_MIN_WIDTH)

        body = QHBoxLayout()
        body.setSpacing(theme.SPACE[3])
        body.addWidget(scroll, 5)
        body.addWidget(self._log_card(), 6)
        layout.addLayout(body, 1)

    @staticmethod
    def _card(title: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        theme.set_role(card, "card")
        inner = QVBoxLayout(card)
        inner.setContentsMargins(theme.SPACE[3], theme.SPACE[2], theme.SPACE[3], theme.SPACE[3])
        inner.setSpacing(theme.SPACE[2])
        heading = QLabel(title)
        theme.set_role(heading, "section")
        inner.addWidget(heading)
        return card, inner

    def _version_card(self) -> QFrame:
        card, inner = self._card(strings.ABOUT_VERSION_LABEL)
        self.name_label = QLabel(strings.APP_NAME)
        self.version_label = QLabel(
            strings.ABOUT_VERSION.format(version=self._services.version())
        )
        inner.addWidget(self.name_label)
        inner.addWidget(self.version_label)
        inner.addWidget(muted(strings.ABOUT_SUBTITLE, wrap=True))
        return card

    def _paths_card(self) -> QFrame:
        card, inner = self._card(strings.ABOUT_PATHS_LABEL)
        grid = self.paths_grid = QGridLayout()
        grid.setHorizontalSpacing(theme.SPACE[1])
        grid.setColumnMinimumWidth(PATH_COL_LABEL, LABEL_COLUMN_WIDTH)
        grid.setColumnStretch(PATH_COL_VALUE, 1)
        for row, (key, label, openable) in enumerate(self.PATH_ROWS):
            value = ElidedLabel()
            value.setFont(theme.mono_font())
            self.path_labels[key] = value
            grid.addWidget(muted(label), row, PATH_COL_LABEL)
            grid.addWidget(value, row, PATH_COL_VALUE)
            self.copy_buttons[key] = button(strings.BTN_COPY, lambda k=key: self._copy_path(k))
            grid.addWidget(self.copy_buttons[key], row, PATH_COL_COPY)
            if openable:
                self.open_buttons[key] = button(strings.BTN_OPEN, lambda k=key: self._open_file(k))
                grid.addWidget(self.open_buttons[key], row, PATH_COL_OPEN)
            self.folder_buttons[key] = icon_button(
                "folder-open", strings.BTN_OPEN_FOLDER, lambda k=key: self._open_folder(k))
            grid.addWidget(self.folder_buttons[key], row, PATH_COL_FOLDER)
        inner.addLayout(grid)
        return card

    def _index_card(self) -> QFrame:
        card, inner = self._card(strings.ABOUT_INDEX_LABEL)
        self._index_grid = QGridLayout()
        self._index_grid.setColumnMinimumWidth(0, LABEL_COLUMN_WIDTH)
        self._index_grid.setColumnStretch(1, 1)
        inner.addLayout(self._index_grid)
        self.index_settings_button = button(strings.ABOUT_BTN_INDEX_SETTINGS,
                                            self._open_index_settings)
        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(self.index_settings_button)
        inner.addLayout(actions)
        return card

    def _log_card(self) -> QFrame:
        card, inner = self._card(strings.ABOUT_LOG_LABEL)
        inner.addWidget(muted(strings.ABOUT_LOG_HINT))
        inner.addLayout(self._log_toolbar())
        inner.addWidget(self._log_view(), 1)
        return card

    def _log_toolbar(self) -> QHBoxLayout:
        self.filter_combo = QComboBox()
        for text, mode in (
            (strings.ABOUT_FILTER_ALL, self.FILTER_ALL),
            (strings.ABOUT_FILTER_WARNINGS, self.FILTER_WARNINGS),
            (strings.ABOUT_FILTER_ERRORS, self.FILTER_ERRORS),
        ):
            self.filter_combo.addItem(text, mode)
        self.filter_combo.currentIndexChanged.connect(self._render)
        self.refresh_button = button(strings.BTN_REFRESH, self.refresh)
        self.copy_button = button(strings.ABOUT_BTN_COPY_ALL, self._copy_all)

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
        self.log_view.setFont(theme.mono_font())
        return self.log_view

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
            self.path_labels[key].set_full_text(str(path))

    def on_config_changed(self, _cfg: object) -> None:
        """Impostazioni saved: the index lives under the mirror root, so a new
        mirror folder means a new database path to show."""
        self._refresh_paths()
        self._refresh_index()
        self.refresh()

    def on_data_changed(self) -> None:
        """A sync or an index job finished (``MainWindow`` hook)."""
        self._refresh_index()

    def _copy_path(self, key: str) -> None:
        QGuiApplication.clipboard().setText(str(self._paths()[key]))
        self._status(strings.ABOUT_PATH_COPIED)

    def _open_folder(self, key: str) -> None:
        self._services.extract.open_folder(self._paths()[key].parent)

    def _open_file(self, key: str) -> None:
        self._services.extract.open_in_editor([self._paths()[key]])

    # -- the index ---------------------------------------------------------

    def _refresh_index(self) -> None:
        """One line per enabled environment: files, requests, first and last day."""
        while self._index_grid.count():
            widget = self._index_grid.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()
        self.index_labels.clear()
        envs = [env.name for env in self._services.config.load().enabled_environments()]
        if not envs:
            self._index_grid.addWidget(muted(strings.ABOUT_INDEX_NO_ENVS), 0, 0, 1, 2)
            return
        for row, env in enumerate(envs):
            coverage = self._services.index.coverage(env)
            text = strings.ABOUT_INDEX_NONE if coverage is None else strings.ABOUT_INDEX_ENV.format(
                files=_count(coverage.n_files), entries=_count(coverage.n_entries),
                first=coverage.first_day.strftime(DAY_FORMAT),
                last=coverage.last_day.strftime(DAY_FORMAT),
            )
            self.index_labels[env] = QLabel(text)
            self._index_grid.addWidget(muted(env), row, 0)
            self._index_grid.addWidget(self.index_labels[env], row, 1)

    def _open_index_settings(self) -> None:
        """Rebuilding the index is an Impostazioni action: go there, on Archivio."""
        show = getattr(self._window, "show_page", None)
        if not callable(show):
            return
        show("settings")
        page = getattr(self._window, "page", None)
        section = getattr(page("settings") if callable(page) else None, "show_section", None)
        if callable(section):
            section("archive")

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

    def _render(self, *_args: object) -> None:
        shown = filter_records(self._lines, self.LEVELS.get(self.current_filter()))
        if shown:
            self.log_view.setPlainText("\n".join(shown))
        else:  # an empty log and an empty filter result are not the same thing
            self.log_view.setPlainText(
                strings.ABOUT_LOG_EMPTY if not self._lines else strings.ABOUT_LOG_NO_MATCH
            )

    def _copy_all(self) -> None:
        """Copia *tutto*: the whole tail, not the filtered view — the filter is
        there to read with, and pasting a placeholder into a chat helps nobody."""
        QGuiApplication.clipboard().setText("\n".join(self._lines))
        self._status(strings.ABOUT_LOG_COPIED)

    def _status(self, text: str) -> None:
        setter = getattr(self._window, "set_status", None)
        if callable(setter):
            setter(text)


def _count(n: int) -> str:
    """Thousands with the Italian dot: 3.412."""
    return f"{n:,}".replace(",", ".")
