"""The preview pane: the selected call's request body, and what to do with it.

Built by the Ricerca page itself (its ``preview_factory``), fed one hit at a
time through :meth:`PreviewPane.set_hit`. Layout (approved redesign)::

    20260901_1a2b3c4d-…_MOD_TEST_A_B.json                            <- mono, elided
    [Apri in Notepad++] [⧉] [💾] [📂]                    JSON | Dettagli
    +---------------------------------------------------------------+
    | the body (JSON tab) or the call's details (Dettagli tab)      |
    +---------------------------------------------------------------+

Three rules shape everything below.

**The body is sacred.** What Copia/Salva/Apri hand over is exactly
``extract.pretty_json(read_body(hit))`` — it starts with ``{\\n    "documents":
[``, it has no wrapper, no header, no comment, and the accents are intact. The
pane keeps that full text in :attr:`_text` and never edits it.

**The cap is a display device** (``preview_body``): every action and the find
bar use the full text.

**Reading happens on a worker**, under the superseding job name ``"preview"``:
clicking down a result list submits one job per row and only the last one
reports back.

Ctrl+S / Ctrl+O / Ctrl+Shift+O / Ctrl+C are the Ricerca page's shortcuts
(``search_actions``), never bound here: two bindings of one key in the same
focus chain are ambiguous and Qt fires neither.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QFont, QFontMetrics
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import actions, strings, theme
from qtrequestory.ui.contracts import CoreServices, SearchHit
from qtrequestory.ui.pages import sync_format
from qtrequestory.ui.pages.preview_body import MAX_LINES, BodyView
from qtrequestory.ui.pages.preview_details import PreviewDetails
from qtrequestory.ui.pages.search_icons import ThemedIcons
from qtrequestory.ui.workers import JobRunner

__all__ = ["MAX_LINES", "PREVIEW_JOB", "ElidedLabel", "PreviewPane", "editor_label"]

#: The job name: it supersedes, which is what makes arrow-key browsing cheap.
PREVIEW_JOB = "preview"
TAB_JSON, TAB_DETAILS = 0, 1


def editor_label(services: CoreServices) -> str:
    """"Apri in Notepad++" when that is what will open, else "Apri nell'editor"."""
    try:
        editor = services.config.load().editor_path or services.config.detect_editor()
    except Exception:  # noqa: BLE001 - a label must never break the pane
        editor = None
    if editor is not None and "notepad++" in Path(editor).name.lower():
        return strings.PREVIEW_BTN_OPEN_EDITOR
    return strings.PREVIEW_BTN_OPEN_DEFAULT


class ElidedLabel(QLabel):
    """A one-line label that elides in the middle and keeps the whole text.

    The file name is ``<day>_<fdi>_<key>.json``: both ends matter, so the
    middle goes. The whole name is in the tooltip and in :meth:`full_text`.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full = ""
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(40)

    def full_text(self) -> str:
        return self._full

    def set_full_text(self, text: str) -> None:
        self._full = text
        self._elide()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        width = max(self.contentsRect().width(), 0)
        self.setText(QFontMetrics(self.font()).elidedText(
            self._full, Qt.TextElideMode.ElideMiddle, width) if width else self._full)


class PreviewPane(QWidget):
    """Header + JSON/Dettagli for one :class:`SearchHit`.

    ``host`` is what the pane reports through — the Ricerca page:
    ``host.show_toast`` for what a copy or a save did, ``host.set_status`` for
    everything else, and the Dettagli tab's copy / search / folder requests.
    ``status`` (a plain callable) is the standalone alternative a test uses.
    """

    def __init__(self, services: CoreServices, runner: JobRunner, host: object | None = None,
                 parent: QWidget | None = None, *,
                 status: Callable[[str], None] | None = None) -> None:
        super().__init__(parent)
        self._services = services
        self._runner = runner
        self._host = host
        self._status = status
        self._hit: SearchHit | None = None
        self._text = ""
        self._build()
        self.set_hit(None)

    # -- public API the Ricerca page uses -----------------------------------

    def set_hit(self, hit: SearchHit | None) -> None:
        """Show the body of ``hit``; ``None`` clears the pane. Returns at once."""
        self._hit = hit
        self._text = ""
        self._set_actions_enabled(False)
        self.details.set_hit(hit)
        if hit is None:
            # No cancel: the read is one short disk call; _on_body drops it.
            self.body.clear()
            self.name_label.set_full_text("")
            self.name_label.setToolTip("")
            return
        name = self._services.extract.output_name(hit)
        self.name_label.set_full_text(name)
        self.name_label.setToolTip(strings.PREVIEW_NAME_TOOLTIP.format(name=name))
        self.body.clear(strings.PREVIEW_LOADING)
        job = self._runner.submit(PREVIEW_JOB, _read_body, self._services, hit)
        if job is None:  # the application is shutting down
            return
        job.signals.result.connect(self._on_body)
        job.signals.error.connect(self._on_error)

    def current_hit(self) -> SearchHit | None:
        return self._hit

    def body_text(self) -> str:
        """The FULL body, or ``""`` while there is none. What the actions use."""
        return self._text

    def open_label(self) -> str:
        return self.open_button.text()

    def refresh_editor_label(self) -> None:
        """Impostazioni may have changed the editor."""
        self.open_button.setText(editor_label(self._services))

    def on_config_changed(self, _cfg: object = None) -> None:
        self.refresh_editor_label()

    # -- the four actions ---------------------------------------------------

    def open_in_editor(self) -> None:
        """Write the full body to the output folder and open it."""
        if not self._ready():
            return
        kind = actions.open_hit_in_editor(self._services, self._hit, self._text)
        if kind != "editor":
            self._report(strings.PREVIEW_STATUS_OPENED_DEFAULT)
        elif editor_label(self._services) == strings.PREVIEW_BTN_OPEN_EDITOR:
            self._report(strings.PREVIEW_STATUS_OPENED_EDITOR)
        else:  # a configured editor that is not Notepad++: never name the wrong program
            self._report(strings.PREVIEW_STATUS_OPENED_OTHER)

    def save_as(self) -> Path | None:
        """Ask for a destination and write the full body there."""
        if not self._ready():
            return None
        path = actions.save_hit_as(self._services, self, self._hit, self._text)
        if path is not None:
            self._report(strings.PREVIEW_TOAST_SAVED.format(name=path.name), confirm=True)
        return path

    def copy_body(self) -> None:
        """Put the full body on the clipboard — never the capped preview."""
        if not self._ready():
            return
        actions.copy_text(self._text)
        size = sync_format.format_size(len(self._text.encode("utf-8")))
        self._report(strings.PREVIEW_TOAST_COPIED.format(size=size), confirm=True)

    def open_folder(self) -> None:
        """Show the folder of the extracted files, this body in it."""
        if not self._ready():
            return
        folder = actions.open_output_folder(self._services, self._hit, self._text)
        self._report(strings.PREVIEW_STATUS_FOLDER.format(path=folder))

    def copy_selection_or_body(self) -> None:
        """Ctrl+C in the body: the selection if there is one, else the body.

        In a read-only viewer Ctrl+C without a selection means "the body" —
        the tool's whole purpose; Qt's default would copy nothing.
        """
        if self.editor.textCursor().hasSelection():
            self.editor.copy()
        else:
            self.copy_body()

    def copy_file_name(self) -> None:
        name = self.name_label.full_text()
        if name:
            actions.copy_text(name)
            self._report(strings.PREVIEW_STATUS_COPIED_NAME, confirm=True)

    # -- find bar (the JSON tab's) ------------------------------------------

    def show_find(self) -> None:
        self.show_tab(TAB_JSON)
        self.body.show_find()

    def hide_find(self) -> None:
        self.body.hide_find()

    def find_next(self) -> bool:
        return self.body.find_next()

    def find_previous(self) -> bool:
        return self.body.find_previous()

    # -- tabs ---------------------------------------------------------------

    def show_tab(self, index: int) -> None:
        self.tabs.button(index).setChecked(True)
        self.stack.setCurrentIndex(index)

    def current_tab(self) -> int:
        return self.stack.currentIndex()

    # -- construction -------------------------------------------------------

    def _build(self) -> None:
        self.body = BodyView()
        self.editor = self.body.editor
        self.find_bar = self.body.find_bar
        self.find_edit = self.body.find_edit
        self.footer = self.body.footer
        self.highlighter = self.body.highlighter
        self.editor.copy_requested.connect(self.copy_selection_or_body)
        self.body.message.connect(self._report)
        self.details = PreviewDetails()
        self.details.copy_requested.connect(self._copy_value)
        self.details.search_requested.connect(self._search_only)
        self.details.log_folder_requested.connect(self._open_log_folder)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.body)      # TAB_JSON
        self.stack.addWidget(self.details)   # TAB_DETAILS

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self._build_name())
        layout.addLayout(self._build_actions())
        layout.addWidget(self.stack, 1)

    def _build_name(self) -> QLabel:
        self.name_label = ElidedLabel()
        font = theme.mono_font()
        font.setWeight(QFont.Weight.DemiBold)
        self.name_label.setFont(font)
        self.name_label.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        self.copy_name_action = QAction(strings.PREVIEW_MENU_COPY_NAME, self.name_label)
        self.copy_name_action.triggered.connect(lambda _checked=False: self.copy_file_name())
        self.name_label.addAction(self.copy_name_action)
        return self.name_label

    def _build_actions(self) -> QHBoxLayout:
        icons_ = ThemedIcons(self)
        self.open_button = QPushButton(editor_label(self._services))
        self.open_button.setToolTip(strings.PREVIEW_TOOLTIP_OPEN_EDITOR)
        self.open_button.setAutoDefault(False)
        theme.set_role(self.open_button, "primary")
        icons_.set(self.open_button, "document-arrow-right", "on_accent")
        self.open_button.clicked.connect(lambda _checked=False: self.open_in_editor())
        self.copy_button = self._icon_button(icons_, "copy", strings.PREVIEW_TOOLTIP_COPY,
                                             self.copy_body)
        self.save_button = self._icon_button(icons_, "save", strings.PREVIEW_TOOLTIP_SAVE_AS,
                                             self.save_as)
        self.folder_button = self._icon_button(icons_, "folder-open",
                                               strings.PREVIEW_TOOLTIP_FOLDER, self.open_folder)
        row = QHBoxLayout()
        row.setSpacing(4)
        row.addWidget(self.open_button)
        row.addSpacing(4)
        for button in (self.copy_button, self.save_button, self.folder_button):
            row.addWidget(button)
        row.addStretch(1)
        self.tabs = QButtonGroup(self)
        for index, label in ((TAB_JSON, strings.PREVIEW_TAB_JSON),
                             (TAB_DETAILS, strings.PREVIEW_TAB_DETAILS)):
            tab = QPushButton(label)
            tab.setProperty("tab", True)
            tab.setCheckable(True)
            tab.setAutoDefault(False)
            self.tabs.addButton(tab, index)
            row.addWidget(tab)
        self.tabs.button(TAB_JSON).setChecked(True)
        self.tabs.idClicked.connect(self.show_tab)
        return row

    @staticmethod
    def _icon_button(icons_: ThemedIcons, name: str, tooltip: str,
                     slot: Callable[[], object]) -> QPushButton:
        button = QPushButton()
        theme.set_role(button, "icon")
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setAutoDefault(False)
        button.setProperty("iconName", name)
        icons_.set(button, name)
        button.clicked.connect(lambda _checked=False: slot())
        return button

    # -- worker results -----------------------------------------------------

    def _on_body(self, text: str) -> None:
        """A live ``preview`` job finished (a superseded one never gets here).

        ``_hit is None`` still has to be checked: clearing the selection is not
        a new job, so the read already in flight would otherwise repopulate a
        pane the user just emptied.
        """
        if self._hit is None:
            return
        self._text = text
        self.body.set_text(text)
        self._set_actions_enabled(True)

    def _on_error(self, _kind: str, message: str) -> None:
        """Show the failure where the body would have been; actions stay off."""
        if self._hit is None:
            return
        text = strings.PREVIEW_ERROR.format(message=message)
        self.body.show_error(text)
        self._report(text)

    # -- the Dettagli tab's requests, forwarded to the page -------------------

    def _copy_value(self, text: str, message: str) -> None:
        copier = getattr(self._host, "copy_value", None)
        if callable(copier):
            copier(text, message)
        else:
            actions.copy_text(text)
            self._report(message, confirm=True)

    def _search_only(self, fdi: object, key: object) -> None:
        search = getattr(self._host, "search_only", None)
        if callable(search):
            search(fdi, key)

    def _open_log_folder(self) -> None:
        if self._hit is not None:
            self._services.extract.open_folder(self._hit.file_path.parent)

    # -- internals ----------------------------------------------------------

    def _ready(self) -> bool:
        return self._hit is not None and bool(self._text)

    def _set_actions_enabled(self, enabled: bool) -> None:
        for button in (self.open_button, self.copy_button, self.save_button, self.folder_button):
            button.setEnabled(enabled)

    def _report(self, message: str, *, confirm: bool = False) -> None:
        """``confirm``: the message says a copy or a save happened (a toast)."""
        if self._status is not None:
            self._status(message)
            return
        if confirm:
            toast = getattr(self._host, "show_toast", None)
            if callable(toast):
                toast(message, "ok")
                return
        report = getattr(self._host, "set_status", None)
        if callable(report):
            report(message)


def _read_body(services: CoreServices, hit: SearchHit) -> str:
    """Runs on the worker thread: touches the core only, never a widget."""
    return services.extract.pretty_json(services.index.read_body(hit))
