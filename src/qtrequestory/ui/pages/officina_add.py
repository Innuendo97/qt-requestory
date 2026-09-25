"""Adding a case to the Officina: from a Ricerca hit, or from a JSON file.

Ricerca's context menu "Aggiungi all'Officina…" and the board's "+ Caso da
file…" share one dialog (:class:`AddCaseDialog`): which initiative (or a new
one), the variant, and — for a file — the file and its template key, which is
prefilled from the payload's first document when it has one. The case itself
is made by ``OfficinaApi.case_from_hit`` / ``case_from_file``; every refusal
they raise becomes a sentence in the status bar, never a traceback.
"""
from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import Case, CoreServices, Initiative, SearchHit
from qtrequestory.ui.pages import officina_dialogs as ask
from qtrequestory.ui.pages.officina_format import initiative_labels

__all__ = ["AddCaseDialog", "AddChoice", "add_hit_to_officina", "ask_add_case", "create_case",
           "initiative_choices", "key_from_payload"]


@dataclass(frozen=True)
class AddChoice:
    """What the user chose: an initiative — its id (folder), or with
    ``create`` the name of a new one — the variant, and for a file its path
    and key."""

    initiative: str
    create: bool
    variant: str
    key: str = ""
    path: Path | None = None


def key_from_payload(path: Path) -> str:
    """``documents[0].template.templateKey`` of a payload file, or ""."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        return str(data["documents"][0]["template"]["templateKey"]).strip()
    except (OSError, ValueError, LookupError, TypeError):
        return ""


class AddCaseDialog(QDialog):
    """Initiative (existing or new), variant; file and key when ``from_file``.

    ``initiatives`` are ``(id, label)`` pairs (see ``initiative_choices``) or
    plain ids shown as they are; ``current`` is an id."""

    def __init__(self, initiatives: Sequence[str | tuple[str, str]], *, current: str | None = None,
                 key: str = "", from_file: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(strings.OFFICINA_ADD_TITLE)
        self._from_file = from_file
        self.initiative = QComboBox()
        pairs = [item if isinstance(item, tuple) else (item, item) for item in initiatives]
        for ini_id, label in pairs:
            self.initiative.addItem(label, userData=ini_id)
        self.initiative.addItem(strings.OFFICINA_ADD_NEW_INITIATIVE, userData="__new__")
        ids = [ini_id for ini_id, _label in pairs]
        if current in ids:
            self.initiative.setCurrentIndex(ids.index(current))
        self.new_name = QLineEdit()
        self.new_name_label = QLabel(strings.OFFICINA_ADD_NEW_NAME)
        self.path = QLineEdit()
        self.path.setReadOnly(True)
        self.browse = QPushButton(strings.BTN_BROWSE)
        self.key = QLineEdit(key)
        self.key.setReadOnly(not from_file)
        self.variant = QLineEdit()
        self.variant.setPlaceholderText(strings.OFFICINA_ADD_VARIANT_HINT)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setProperty("dot", "bad")
        self.error.setVisible(False)

        form = QFormLayout()
        form.addRow(strings.OFFICINA_ADD_INITIATIVE, self.initiative)
        form.addRow(self.new_name_label, self.new_name)
        if from_file:
            row = QHBoxLayout()
            row.addWidget(self.path, 1)
            row.addWidget(self.browse)
            form.addRow(strings.OFFICINA_ADD_FILE, row)
        form.addRow(strings.OFFICINA_ADD_KEY, self.key)
        form.addRow(strings.OFFICINA_ADD_VARIANT, self.variant)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(strings.OFFICINA_ADD_BUTTON)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(strings.BTN_CANCEL)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.error)
        layout.addWidget(buttons)
        self.setMinimumWidth(460)

        self.initiative.currentIndexChanged.connect(self._sync_new_name)
        self.browse.clicked.connect(self._browse)
        self._sync_new_name()
        theme.repolish(self.error)

    def set_file(self, path: Path) -> None:
        """Use ``path`` as the payload; the key comes from it when blank."""
        self.path.setText(str(path))
        if not self.key.text().strip():
            self.key.setText(key_from_payload(path))

    def choice(self) -> AddChoice | None:
        """The validated answer, or None (the reason is shown in the dialog)."""
        problem = self.problem()
        self.error.setText(problem)
        self.error.setVisible(bool(problem))
        if problem:
            return None
        creating = self.initiative.currentData() == "__new__"
        name = self.new_name.text().strip() if creating else self.initiative.currentData()
        return AddChoice(name, creating, self.variant.text().strip(), self.key.text().strip(),
                         Path(self.path.text()) if self._from_file else None)

    def problem(self) -> str:
        if self.initiative.currentData() == "__new__" and not self.new_name.text().strip():
            return strings.OFFICINA_ADD_NEED_NAME
        if self._from_file and not self.path.text().strip():
            return strings.OFFICINA_ADD_NEED_FILE
        if not self.key.text().strip():
            return strings.OFFICINA_ADD_NEED_KEY
        return ""

    def accept(self) -> None:  # noqa: D102 - validate before closing
        if self.choice() is not None:
            super().accept()

    def _sync_new_name(self) -> None:
        creating = self.initiative.currentData() == "__new__"
        self.new_name.setVisible(creating)
        self.new_name_label.setVisible(creating)
        if creating:
            self.new_name.setFocus()

    def _browse(self) -> None:
        chosen = ask.ask_open_file(self, strings.OFFICINA_ADD_PICK_FILE,
                                   strings.OFFICINA_JSON_FILTER)
        if chosen is not None:
            self.set_file(chosen)


def initiative_choices(initiatives: Sequence[Initiative]) -> list[tuple[str, str]]:
    """``(id, label)`` of every initiative, for :class:`AddCaseDialog`."""
    labels = initiative_labels(initiatives)
    return [(ini.id, labels[ini.id]) for ini in initiatives]


def ask_add_case(parent: QWidget | None, initiatives: Sequence[str | tuple[str, str]], *,
                 current: str | None = None, key: str = "",
                 from_file: bool = False) -> AddChoice | None:
    """Show :class:`AddCaseDialog`; the choice, or None when cancelled."""
    dialog = AddCaseDialog(initiatives, current=current, key=key, from_file=from_file,
                           parent=parent)
    try:
        if from_file:
            dialog._browse()  # the file first: it prefills the key
        return dialog.choice() if dialog.exec() == QDialog.DialogCode.Accepted else None
    finally:
        dialog.deleteLater()


def create_case(services: CoreServices, choice: AddChoice,
                hit: SearchHit | None = None) -> tuple[Initiative, Case]:
    """Make the case ``choice`` describes (and its initiative, if new).

    Raises ``ValueError`` with an Italian sentence for every refusal.
    """
    api = services.officina
    try:
        if choice.create:
            ini = api.create_initiative(choice.initiative)
        else:
            ini = api.load(choice.initiative)
    except FileExistsError as exc:
        raise ValueError(strings.OFFICINA_INITIATIVE_EXISTS.format(name=choice.initiative)) from exc
    except FileNotFoundError as exc:
        raise ValueError(strings.OFFICINA_INITIATIVE_GONE.format(name=choice.initiative)) from exc
    try:
        if hit is not None:
            case = api.case_from_hit(ini, hit, choice.variant)
        else:
            case = api.case_from_file(ini, choice.path or Path(), choice.key, choice.variant)
    except FileExistsError as exc:
        raise ValueError(strings.OFFICINA_ADD_DUPLICATE) from exc
    except OSError as exc:
        raise ValueError(str(exc)) from exc
    return ini, case


def add_hit_to_officina(parent: QWidget, services: CoreServices, hit: SearchHit) -> Case | None:
    """Ricerca › "Aggiungi all'Officina…": ask, create, tell the Officina tab."""
    window = parent.window()
    notify = getattr(window, "set_status", None) or (lambda _text: None)
    api = services.officina
    if api.workspace_root() is None:
        notify(strings.OFFICINA_ADD_NO_ROOT)
        return None
    officina = window.page("officina") if callable(getattr(window, "page", None)) else None
    current = getattr(officina, "current_initiative_id", lambda: None)()
    choice = ask_add_case(parent, initiative_choices(api.initiatives()), current=current,
                          key=hit.template_key)
    if choice is None:
        return None
    QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)
    try:
        ini, case = create_case(services, choice, hit)
    except ValueError as exc:
        notify(strings.OFFICINA_ADD_FAILED.format(reason=exc))
        return None
    finally:
        QApplication.restoreOverrideCursor()
    toast = getattr(window, "show_toast", None)
    message = strings.OFFICINA_ADDED.format(key=case.key, initiative=ini.name)
    if callable(toast):
        toast(message, "ok")
    else:
        notify(message)
    added = getattr(officina, "on_case_added", None)
    if callable(added):
        added(ini.id, case.id)
    return case
