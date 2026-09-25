"""Small questions the Officina asks: a folder, a file, a name, a note.

Each one is a module-level function so a test can replace it (a modal dialog
cannot be answered from an offscreen test); the widgets call them through this
module, never through a local import of the function.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtWidgets import QCheckBox, QFileDialog, QInputDialog, QLineEdit, QMessageBox, QWidget

from qtrequestory.ui import strings

__all__ = ["ask_conflict", "ask_folder", "ask_note", "ask_open_file", "ask_text", "confirm",
           "in_onedrive", "on_network"]


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


def ask_text(parent: QWidget | None, title: str, label: str, text: str = "") -> str | None:
    """One line of text, stripped; None when cancelled or left empty."""
    value, ok = QInputDialog.getText(parent, title, label, QLineEdit.EchoMode.Normal, text)
    value = value.strip() if ok else ""
    return value or None


def ask_note(parent: QWidget | None, title: str, label: str) -> str | None:
    """A mandatory note (several lines allowed); None when cancelled or blank."""
    value, ok = QInputDialog.getMultiLineText(parent, title, label, "")
    value = value.strip() if ok else ""
    return value or None


def confirm(parent: QWidget | None, title: str, text: str) -> bool:
    """A yes/no question; "No" is the default."""
    answer = QMessageBox.question(parent, title, text,
                                  QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                  QMessageBox.StandardButton.No)
    return answer == QMessageBox.StandardButton.Yes


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
