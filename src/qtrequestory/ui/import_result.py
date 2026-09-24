"""Step 3 of the import dialog: the counts, and "Vuoi cancellare gli originali?".

Layout plus two signals. The question appears only when some VERIFIED
original lives OUTSIDE the archive: :func:`deletable` drops the ones inside
the mirror folder with ``real_is_within`` (a junction or a ``subst`` drive
leading into it still counts as inside), exactly as the CLI does, and the
Recycle Bin itself re-checks every record anyway.
"""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import ImportResult, VerifiedOriginal, real_is_within
from qtrequestory.ui.pages.sync_format import format_size

__all__ = ["ResultView", "deletable"]


def deletable(result: ImportResult, mirror_root: Path) -> list[VerifiedOriginal]:
    """The verified originals the user may send to the Recycle Bin."""
    return [v for v in result.verified if not real_is_within(v.path, mirror_root)]


class ResultView(QWidget):
    """Summary line, notes, errors, and the delete question."""

    delete_requested = Signal()
    keep_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.summary = QLabel()
        theme.set_role(self.summary, "section")
        self.summary.setWordWrap(True)
        self.notes = QLabel()
        self.notes.setWordWrap(True)
        self.errors = QPlainTextEdit()
        self.errors.setReadOnly(True)
        self.errors.setMaximumHeight(120)

        self.question = QFrame()
        self.question.setProperty("banner", "warn")
        self.question.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.question_label = QLabel(strings.IMPORT_DELETE_QUESTION)
        theme.set_role(self.question_label, "section")
        self.question_detail = QLabel()
        self.delete_button = QPushButton(strings.IMPORT_BTN_DELETE)
        self.keep_button = QPushButton(strings.IMPORT_BTN_KEEP)
        self.delete_button.clicked.connect(self.delete_requested)
        self.keep_button.clicked.connect(self.keep_requested)
        text = QVBoxLayout()
        text.setSpacing(theme.SPACE[0])
        text.addWidget(self.question_label)
        text.addWidget(self.question_detail)
        box = QHBoxLayout(self.question)
        box.setContentsMargins(theme.SPACE[3], theme.SPACE[2], theme.SPACE[2], theme.SPACE[2])
        box.addLayout(text, 1)
        box.addWidget(self.delete_button)
        box.addWidget(self.keep_button)

        self.outcome = QLabel()
        self.outcome.setWordWrap(True)
        self.outcome_details = QPlainTextEdit()
        self.outcome_details.setReadOnly(True)
        self.outcome_details.setMaximumHeight(120)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE[2])
        for widget in (self.summary, self.notes, self.errors, self.question, self.outcome,
                       self.outcome_details):
            layout.addWidget(widget)
        layout.addStretch(1)
        self.offered: list[VerifiedOriginal] = []

    def set_result(self, result: ImportResult, offered: Sequence[VerifiedOriginal],
                   index_note: str = "") -> None:
        self.summary.setText(strings.IMPORT_RESULT.format(
            copied=result.copied, skipped=result.skipped, conflicts=result.conflicts,
            errors=len(result.errors)))
        notes = []
        if result.cancelled:
            notes.append(strings.IMPORT_RESULT_CANCELLED)
        if result.conflicts:
            notes.append(strings.IMPORT_RESULT_CONFLICTS)
        if index_note:
            notes.append(index_note)
        self.notes.setText("\n".join(notes))
        self.notes.setVisible(bool(notes))
        self.errors.setPlainText("\n".join(
            strings.IMPORT_ERROR_LINE.format(path=path, reason=reason)
            for path, reason in result.errors))
        self.errors.setVisible(bool(result.errors))
        # After an interruption the question is not asked (as the CLI): the
        # user stopped the import, a deletion is not what they are after.
        self.offered = [] if result.cancelled else list(offered)
        if self.offered:
            size = format_size(sum(v.size for v in self.offered))
            n = len(self.offered)
            self.question_detail.setText(strings.IMPORT_DELETE_DETAIL_ONE.format(size=size) if n == 1
                                         else strings.IMPORT_DELETE_DETAIL.format(n=n, size=size))
        self.question.setVisible(bool(self.offered))
        self.set_outcome("")

    def set_busy(self, busy: bool) -> None:
        """While the Recycle Bin works: no second click."""
        self.delete_button.setEnabled(not busy)
        self.keep_button.setEnabled(not busy)
        if busy:
            self.set_outcome(strings.IMPORT_DELETING)

    def set_outcome(self, text: str, details: Sequence[str] = ()) -> None:
        self.outcome.setText(text)
        self.outcome.setVisible(bool(text))
        self.outcome_details.setPlainText("\n".join(details))
        self.outcome_details.setVisible(bool(details))

    def show_deleted(self, n_deleted: int, failures: Sequence[tuple[Path, str]]) -> None:
        self.question.setVisible(False)
        text = strings.IMPORT_DELETED.format(n=n_deleted)
        if failures:
            text += " " + strings.IMPORT_DELETE_REFUSED.format(n=len(failures))
        self.set_outcome(text, [strings.IMPORT_ERROR_LINE.format(path=p, reason=r)
                                for p, r in failures])

    def show_kept(self) -> None:
        self.question.setVisible(False)
        self.set_outcome(strings.IMPORT_KEPT)
