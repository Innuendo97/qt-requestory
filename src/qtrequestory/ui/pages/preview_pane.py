"""The preview pane: the selected call's request body, and what to do with it.

Hosted by the Ricerca page (``SearchPage.set_preview_widget``), fed one hit at
a time through :meth:`PreviewPane.set_hit`, and driving the four actions the
page also offers in its context menu.

Three rules shape everything below.

**The body is sacred.** What Copia/Salva/Apri hand over is exactly
``extract.pretty_json(read_body(hit))`` — it starts with ``{\\n    "documents":
[``, it has no wrapper, no header, no comment, and the accents are intact. The
pane keeps that full text in :attr:`_text` and never edits it.

**The cap is a display device, nothing more.** A body of 80 000 lines would
make ``QPlainTextEdit`` crawl, so only the first :data:`MAX_LINES` are shown
and the footer says so. Every action still uses the full text — that asymmetry
is the point, and the tests assert it.

**Reading happens on a worker.** ``read_body`` hits the disk, so the load goes
through the shared :class:`JobRunner` under the name ``"preview"``. That name
supersedes: clicking down a result list submits one job per row and the runner
guarantees the older ones stay silent, so the pane needs no request ids of its
own and the last selection always wins.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QFontDatabase, QKeySequence, QShortcut, QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import actions, strings
from qtrequestory.ui.contracts import CoreServices, SearchHit
from qtrequestory.ui.json_highlighter import JsonHighlighter
from qtrequestory.ui.workers import JobRunner

__all__ = ["MAX_LINES", "PREVIEW_JOB", "PreviewPane"]

#: Lines shown in the editor; the rest is one click away in Notepad++.
MAX_LINES = 4000
#: The job name: it supersedes, which is what makes arrow-key browsing cheap.
PREVIEW_JOB = "preview"
#: Monospace, in order of preference (DESIGN-ui §Visual style).
MONO_FAMILIES = ("Cascadia Mono", "Consolas")


class PreviewPane(QWidget):
    """Header + body + footer for one :class:`SearchHit`.

    ``status`` is the shell's ``MainWindow.set_status``; without it the pane
    simply stays quiet, which is what a standalone test wants.
    """

    def __init__(
        self,
        services: CoreServices,
        runner: JobRunner,
        status: Callable[[str], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._services = services
        self._runner = runner
        self._status = status
        self._hit: SearchHit | None = None
        self._text = ""
        self._build()
        self.set_hit(None)

    # -- public API the Ricerca page uses -----------------------------------

    def set_hit(self, hit: SearchHit | None) -> None:
        """Show the body of ``hit``; ``None`` clears the pane.

        Returns immediately: the read runs on a worker and the result arrives
        in :meth:`_on_body`, unless a newer ``set_hit`` superseded it first.
        """
        self._hit = hit
        self._text = ""
        self._set_actions_enabled(False)
        self.editor.clear()
        self.footer.clear()
        self.footer.setVisible(False)
        if hit is None:
            # No cancel: the read is one short disk call with no check point,
            # so the job is let finish and _on_body drops it instead.
            self.name_label.clear()
            self.name_label.setToolTip("")
            return

        name = self._services.extract.output_name(hit)
        self.name_label.setText(name)
        self.name_label.setToolTip(strings.PREVIEW_NAME_TOOLTIP.format(name=name))
        self.editor.setPlaceholderText(strings.PREVIEW_LOADING)
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

    # -- the four actions ---------------------------------------------------

    def open_in_editor(self) -> None:
        """Write the full body to the output folder and open it in Notepad++."""
        if not self._ready():
            return
        kind = actions.open_hit_in_editor(self._services, self._hit, self._text)
        self._report(strings.PREVIEW_STATUS_OPENED_EDITOR if kind == "editor"
                     else strings.PREVIEW_STATUS_OPENED_DEFAULT)

    def save_as(self) -> Path | None:
        """Ask for a destination and write the full body there."""
        if not self._ready():
            return None
        path = actions.save_hit_as(self._services, self, self._hit, self._text)
        if path is not None:
            self._report(strings.PREVIEW_STATUS_SAVED.format(path=path))
        return path

    def copy_body(self) -> None:
        """Put the full body on the clipboard — never the capped preview."""
        if not self._ready():
            return
        actions.copy_text(self._text)
        size = _human_size(len(self._text.encode("utf-8")))
        self._report(strings.PREVIEW_STATUS_COPIED.format(size=size))

    def open_folder(self) -> None:
        """Show the folder the extracted files are written into."""
        if not self._ready():
            return
        folder = actions.open_output_folder(self._services, self._hit, self._text)
        self._report(strings.PREVIEW_STATUS_FOLDER.format(path=folder))

    def copy_selection_or_body(self) -> None:
        """Ctrl+C in the body: the selection if there is one, else the body.

        Overriding the default copy is deliberate. In a read-only viewer the
        user who presses Ctrl+C without selecting anything wants the body —
        that is the tool's whole purpose — and Qt's default would hand them an
        empty clipboard.

        It reaches here from :class:`_BodyEdit`, so only a key press *in the
        body* can trigger it: the find field keeps its own Ctrl+C, and there is
        no way for the search term to come out of this.
        """
        if self.editor.textCursor().hasSelection():
            self.editor.copy()
        else:
            self.copy_body()

    # -- find bar -----------------------------------------------------------

    def show_find(self) -> None:
        """Ctrl+F: reveal the inline find bar with the field focused."""
        self.find_bar.setVisible(True)
        self.find_edit.selectAll()
        self.find_edit.setFocus()

    def hide_find(self) -> None:
        self.find_bar.setVisible(False)
        self.editor.setFocus()

    def find_next(self) -> bool:
        return self._find(QTextDocument.FindFlag(0))

    def find_previous(self) -> bool:
        return self._find(QTextDocument.FindFlag.FindBackward)

    # -- construction -------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addLayout(self._build_header())
        layout.addWidget(self._build_editor(), 1)
        layout.addWidget(self._build_find_bar())
        self.footer = QLabel()
        self.footer.setWordWrap(True)
        self.footer.setVisible(False)
        layout.addWidget(self.footer)
        self._build_shortcuts()

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        self.name_label = QLabel()
        self.name_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.name_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        header.addWidget(self.name_label, 1)

        self.open_button = _button(strings.PREVIEW_BTN_OPEN_EDITOR,
                                   strings.PREVIEW_TOOLTIP_OPEN_EDITOR, self.open_in_editor)
        self.open_button.setDefault(True)  # the primary action of the pane
        self.save_button = _button(strings.BTN_SAVE_AS, strings.PREVIEW_TOOLTIP_SAVE_AS,
                                   self.save_as)
        self.copy_button = _button(strings.PREVIEW_BTN_COPY, strings.PREVIEW_TOOLTIP_COPY,
                                   self.copy_body)
        self.folder_button = _button(strings.BTN_OPEN_FOLDER, strings.PREVIEW_TOOLTIP_FOLDER,
                                     self.open_folder)
        for button in self._buttons():
            header.addWidget(button)
        return header

    def _build_editor(self) -> QPlainTextEdit:
        self.editor = _BodyEdit()
        self.editor.copy_requested.connect(self.copy_selection_or_body)
        self.editor.setReadOnly(True)
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.editor.setFont(_mono_font())
        self.editor.setPlaceholderText(strings.PREVIEW_EMPTY)
        # Parented to the editor's document, so it lives exactly as long.
        self.highlighter = JsonHighlighter(self.editor.document())
        return self.editor

    def _build_find_bar(self) -> QWidget:
        self.find_bar = QWidget()
        bar = QHBoxLayout(self.find_bar)
        bar.setContentsMargins(0, 0, 0, 0)
        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText(strings.PREVIEW_FIND_PLACEHOLDER)
        self.find_edit.returnPressed.connect(self.find_next)
        bar.addWidget(self.find_edit, 1)
        for text, tooltip, slot in (
            (strings.PREVIEW_FIND_PREVIOUS_GLYPH, strings.PREVIEW_FIND_PREVIOUS, self.find_previous),
            (strings.PREVIEW_FIND_NEXT_GLYPH, strings.PREVIEW_FIND_NEXT, self.find_next),
            (strings.PREVIEW_FIND_CLOSE_GLYPH, strings.PREVIEW_FIND_CLOSE, self.hide_find),
        ):
            button = QToolButton()
            button.setText(text)
            button.setToolTip(tooltip)
            button.clicked.connect(slot)
            bar.addWidget(button)
        self.find_bar.setVisible(False)
        return self.find_bar

    def _build_shortcuts(self) -> None:
        """Active while anything in the pane has the focus.

        Ctrl+C is deliberately NOT here: it belongs to :class:`_BodyEdit`, see
        that class for why.
        """
        for sequence, slot in (
            (QKeySequence.StandardKey.Save, self.save_as),
            (QKeySequence.StandardKey.Open, self.open_in_editor),
            (QKeySequence("Ctrl+Shift+O"), self.open_folder),
            (QKeySequence.StandardKey.Find, self.show_find),
        ):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(slot)
        escape = QShortcut(QKeySequence(Qt.Key.Key_Escape), self.find_bar)
        escape.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        escape.activated.connect(self.hide_find)

    # -- worker results -----------------------------------------------------

    def _on_body(self, text: str) -> None:
        """A live ``preview`` job finished: a superseded one never gets here.

        ``_hit is None`` still has to be checked: clearing the selection is not
        a new job, so the runner has nothing to supersede and the read already
        in flight would otherwise repopulate a pane the user just emptied.
        """
        if self._hit is None:
            return
        self._text = text
        shown, total = _capped(text)
        self.editor.setPlainText(shown)
        self.editor.setPlaceholderText(strings.PREVIEW_EMPTY)
        if total > MAX_LINES:
            self.footer.setText(strings.PREVIEW_TRUNCATED.format(
                shown=_thousands(MAX_LINES), total=_thousands(total)))
            self.footer.setVisible(True)
        self._set_actions_enabled(True)

    def _on_error(self, _kind: str, message: str) -> None:
        """Show the failure where the body would have been, and keep the
        actions disabled: there is nothing to copy, save or open."""
        if self._hit is None:  # the selection was cleared while it was reading
            return
        text = strings.PREVIEW_ERROR.format(message=message)
        self.editor.setPlaceholderText(strings.PREVIEW_EMPTY)
        self.footer.setText(text)
        self.footer.setVisible(True)
        self._report(text)

    # -- internals ----------------------------------------------------------

    def _ready(self) -> bool:
        return self._hit is not None and bool(self._text)

    def _buttons(self) -> tuple[QPushButton, ...]:
        return (self.open_button, self.save_button, self.copy_button, self.folder_button)

    def _set_actions_enabled(self, enabled: bool) -> None:
        for button in self._buttons():
            button.setEnabled(enabled)

    def _report(self, message: str) -> None:
        if self._status is not None:
            self._status(message)

    def _find(self, flags: QTextDocument.FindFlag) -> bool:
        """Search from the cursor, then once more from the far end (wrap).

        A miss puts the cursor back where it was: wrapping is a *search*
        strategy, and a term that is simply not in the body must not scroll the
        reader away from the line they were looking at.
        """
        needle = self.find_edit.text()
        if not needle:
            return False
        if self.editor.find(needle, flags):
            return True
        original = self.editor.textCursor()
        cursor = QTextCursor(original)
        backward = bool(flags & QTextDocument.FindFlag.FindBackward)
        cursor.movePosition(QTextCursor.MoveOperation.End if backward
                            else QTextCursor.MoveOperation.Start)
        self.editor.setTextCursor(cursor)
        if self.editor.find(needle, flags):
            return True
        self.editor.setTextCursor(original)
        self._report(strings.PREVIEW_FIND_NOT_FOUND.format(text=needle))
        return False


class _BodyEdit(QPlainTextEdit):
    """The body view, with Ctrl+C rebound to the pane.

    Why a subclass instead of a ``QShortcut`` on the pane, like the other four
    bindings: a shortcut with ``WidgetWithChildrenShortcut`` context would also
    swallow Ctrl+C from the find field, so the pane would have to guess when
    the user meant the search term and when they meant the body. Overriding the
    editor's own key handling scopes the override to exactly the widget whose
    default is wrong — and it is the only version that can be *tested* with a
    real key press, because Qt matches shortcuts from window-system events,
    which a synthetic ``keyClick`` is not.
    """

    #: Ctrl+C was pressed in the body; the pane decides selection vs. body.
    copy_requested = Signal()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.matches(QKeySequence.StandardKey.Copy):
            self.copy_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


# --------------------------------------------------------------- helpers ---

def _read_body(services: CoreServices, hit: SearchHit) -> str:
    """Runs on the worker thread: touches the core only, never a widget."""
    return services.extract.pretty_json(services.index.read_body(hit))


def _capped(text: str) -> tuple[str, int]:
    """``(what to display, how many lines the body really has)``.

    An uncapped body is returned untouched — including its trailing newline —
    so that "what you see is the file" holds for everything short enough.
    """
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if len(lines) <= MAX_LINES:
        return text, len(lines)
    return "\n".join(lines[:MAX_LINES]), len(lines)


def _thousands(value: int) -> str:
    """``4000`` -> ``"4.000"`` (Italian grouping)."""
    return f"{value:,}".replace(",", ".")


def _human_size(n_bytes: int) -> str:
    """Rounded size for the status bar ("312 KB", "1,4 MB")."""
    if n_bytes < 1024:
        return strings.PREVIEW_SIZE_BYTES.format(value=n_bytes)
    if n_bytes < 1024 * 1024:
        return strings.PREVIEW_SIZE_KB.format(value=round(n_bytes / 1024))
    megabytes = f"{n_bytes / (1024 * 1024):.1f}".replace(".", ",")
    return strings.PREVIEW_SIZE_MB.format(value=megabytes)


def _mono_font() -> QFont:
    """Cascadia Mono, else Consolas, else whatever this system calls fixed.

    The families are set as a *list* rather than probed against
    ``QFontDatabase.families()``: Qt then falls through them itself, which also
    works where the database is empty (a headless test run).
    """
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    font.setFamilies([*MONO_FAMILIES, font.family()])
    font.setStyleHint(QFont.StyleHint.TypeWriter)
    return font


def _button(text: str, tooltip: str, slot: Callable[[], object]) -> QPushButton:
    button = QPushButton(text)
    button.setToolTip(tooltip)
    button.clicked.connect(lambda: slot())
    button.setAutoDefault(False)
    return button
