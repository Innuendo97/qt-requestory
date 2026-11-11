"""Small questions the Officina asks: a folder, a file, a name, a note, a
tolerance's optional note.

Each one is a module-level function so a test can replace it (a modal dialog
cannot be answered from an offscreen test); the widgets call them through this
module, never through a local import of the function.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QInputDialog,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QWidget,
)

from qtrequestory.ui import strings

__all__ = ["ask_conflict", "ask_folder", "ask_note", "ask_open_file", "ask_text",
           "ask_tolerate_note", "ask_unsaved_rules", "confirm", "confirm_box",
           "in_onedrive", "input_box", "on_network"]


def ask_folder(parent: QWidget | None, title: str, start: Path | None = None) -> Path | None:
    """A folder chosen by the user, or None."""
    chosen = QFileDialog.getExistingDirectory(parent, title, str(start or Path.home()))
    return Path(chosen) if chosen else None


def ask_open_file(parent: QWidget | None, title: str, filters: str,
                  start: Path | None = None) -> Path | None:
    """A file chosen by the user, or None."""
    chosen, _filter = QFileDialog.getOpenFileName(parent, title, str(start or Path.home()),
                                                  filters)
    return Path(chosen) if chosen else None


def input_box(parent: QWidget | None, title: str, label: str, text: str = "", *,
              multiline: bool = False) -> QInputDialog:
    """The box of :func:`ask_text` / :func:`ask_note`, not shown. Qt's static
    ``getText`` has English buttons (the app loads no Qt translation), so the
    dialog is built here with ours."""
    box = QInputDialog(parent)
    box.setWindowTitle(title)
    box.setLabelText(label)
    box.setInputMode(QInputDialog.InputMode.TextInput)
    if multiline:
        box.setOption(QInputDialog.InputDialogOption.UsePlainTextEditForTextInput, True)
    else:
        box.setTextEchoMode(QLineEdit.EchoMode.Normal)
    box.setTextValue(text)
    box.setOkButtonText(strings.BTN_OK)
    box.setCancelButtonText(strings.BTN_CANCEL)
    return box


def _ask_input(box: QInputDialog) -> str | None:
    try:
        value = box.textValue().strip() if box.exec() else ""
        return value or None
    finally:
        box.deleteLater()


def ask_text(parent: QWidget | None, title: str, label: str, text: str = "") -> str | None:
    """One line of text, stripped; None when cancelled or left empty."""
    return _ask_input(input_box(parent, title, label, text))


def ask_note(parent: QWidget | None, title: str, label: str) -> str | None:
    """A mandatory note (several lines allowed); None when cancelled or blank."""
    return _ask_input(input_box(parent, title, label, multiline=True))


def ask_tolerate_note(parent: QWidget | None, what: str) -> str | None:
    """"Tollera…": the optional note ("" = none); None when cancelled."""
    from qtrequestory.ui.pages.officina_actions_bar import TolerateDialog

    dialog = TolerateDialog(what, parent)
    try:
        return dialog.note() if dialog.exec() else None
    finally:
        dialog.deleteLater()


def confirm_box(parent: QWidget | None, title: str, text: str, *, yes: str | None = None,
                no: str | None = None) -> tuple[QMessageBox, QPushButton]:
    """The box of :func:`confirm`, not shown: ``(box, the yes button)``.

    Qt's standard Yes/No are English (the app loads no Qt translation), so the
    buttons are always ours: what they do ("Genera 56 documenti" / "Annulla")
    when the caller says it, else "Sì" / "No". The safe answer is both the
    default (Enter) and the escape button."""
    box = QMessageBox(QMessageBox.Icon.Question, title, text, parent=parent)
    accept = box.addButton(yes or strings.BTN_YES, QMessageBox.ButtonRole.AcceptRole)
    reject = box.addButton(no or strings.BTN_NO, QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(reject)
    box.setEscapeButton(reject)
    return box, accept


def confirm(parent: QWidget | None, title: str, text: str, *, yes: str | None = None,
            no: str | None = None) -> bool:
    """A yes/no question in Italian; the "no" button is the default
    (:func:`confirm_box`)."""
    box, accept = confirm_box(parent, title, text, yes=yes, no=no)
    try:
        box.exec()
        return box.clickedButton() is accept
    finally:
        box.deleteLater()


def ask_unsaved_rules(parent: QWidget | None, *, valid: bool, cancellable: bool) -> str:
    """Closing "Filtri del confronto" with unsaved rules: "save" | "discard" |
    "cancel". Without ``cancellable`` (the case is being left) there is no
    "Annulla"; with rules that cannot be saved (``valid`` False) no "Salva"."""
    box = QMessageBox(QMessageBox.Icon.Question, strings.FILTRI_UNSAVED_TITLE,
                      strings.FILTRI_UNSAVED_TEXT if valid else strings.FILTRI_UNSAVED_INVALID, parent=parent)
    buttons = {}
    if valid:
        buttons["save"] = box.addButton(strings.FILTRI_UNSAVED_SAVE, QMessageBox.ButtonRole.AcceptRole)
    buttons["discard"] = box.addButton(strings.FILTRI_UNSAVED_DISCARD, QMessageBox.ButtonRole.DestructiveRole)
    if cancellable:
        buttons["cancel"] = box.addButton(strings.FILTRI_UNSAVED_CANCEL, QMessageBox.ButtonRole.RejectRole)
        box.setEscapeButton(buttons["cancel"])
    box.setDefaultButton(buttons.get("save") or buttons.get("cancel") or buttons["discard"])
    box.exec()
    clicked = box.clickedButton()
    return next((k for k, b in buttons.items() if b is clicked), "cancel" if cancellable else "discard")


def ask_conflict(parent: QWidget | None, path: Path, remaining: int) -> tuple[str, bool]:
    """A file of the delivery is already there: ``("replace" | "keep_both" |
    "skip", apply_to_all)``. ``remaining`` counts the undecided files, this one
    included; "Applica a tutti" is offered when there is more than one. Esc
    and closing the box mean "Salta": nothing is overwritten without a click."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle(strings.OFFICINA_CONFLICT_TITLE)
    box.setText(strings.OFFICINA_CONFLICT_TEXT.format(name=path.name))
    box.setInformativeText(str(path.parent))
    replace = box.addButton(strings.OFFICINA_CONFLICT_REPLACE, QMessageBox.ButtonRole.DestructiveRole)
    keep = box.addButton(strings.OFFICINA_CONFLICT_KEEP_BOTH, QMessageBox.ButtonRole.AcceptRole)
    skip = box.addButton(strings.OFFICINA_CONFLICT_SKIP, QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(keep)
    box.setEscapeButton(skip)
    apply_all = QCheckBox(strings.OFFICINA_CONFLICT_APPLY_ALL.format(n=remaining))
    if remaining > 1:
        box.setCheckBox(apply_all)
    try:
        box.exec()
        clicked = box.clickedButton()
        choice = "replace" if clicked is replace else "keep_both" if clicked is keep else "skip"
        return choice, remaining > 1 and apply_all.isChecked()
    finally:
        box.deleteLater()


def in_onedrive(path: Path) -> bool:
    """True when ``path`` is inside a OneDrive folder (spec §9: allowed, but
    the user is told — the payloads hold real customer data).

    The OneDrive variables name the synced roots (personal and business); a
    folder named ``OneDrive…`` anywhere in the path counts too, as
    ``scheduler.location_problem`` does for the exe.
    """
    resolved = os.path.normcase(os.path.abspath(path))
    for var in ("OneDrive", "OneDriveCommercial", "OneDriveConsumer"):
        base = os.environ.get(var)
        if base:
            root = os.path.normcase(os.path.abspath(base))
            if resolved == root or resolved.startswith(root.rstrip("\\/") + os.sep):
                return True
    return any(part.lower().startswith("onedrive") for part in Path(path).parts)


#: ``GetDriveTypeW`` answer for a mapped network drive.
_DRIVE_REMOTE = 4


def on_network(path: Path) -> bool:
    r"""True when ``path`` is a UNC path (``\\server\share``) or on a mapped
    network drive: allowed, but the payloads hold real customer data and a
    dropped connection fails the generations."""
    text = str(path)
    if text.startswith(("\\\\", "//")):
        return True
    drive = os.path.splitdrive(text)[0]
    if sys.platform != "win32" or len(drive) != 2 or drive[1] != ":":
        return False
    import ctypes

    try:
        return ctypes.windll.kernel32.GetDriveTypeW(drive + "\\") == _DRIVE_REMOTE
    except (AttributeError, OSError):
        return False
