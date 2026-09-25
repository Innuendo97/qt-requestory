"""The user actions of the Officina tab (a mixin of ``OfficinaPage``).

Choosing the Officina folder, creating an initiative, adding a case from a
file, the AS-IS (a replacement needs a note: spec §14 "a baseline can only be
changed with a note"), the TARGET, the payload and header editor, and
accepting / reopening a case. Split from
``officina_page`` only to keep each module readable; every method runs on the
page and uses its helpers (``_case``, ``_reload_initiative``, ``open_case``,
``_generate``, ``_notify``, ``_toast``).
"""
from __future__ import annotations

import dataclasses

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import officina_root_errors
from qtrequestory.ui.pages import officina_dialogs as ask
from qtrequestory.ui.pages.officina_add import ask_add_case, create_case, initiative_choices

__all__ = ["CaseActionsMixin"]


class CaseActionsMixin:
    """What the folder chooser, the list's buttons, the board's "+ Caso…"
    buttons and the workbench's toolbar do."""

    def choose_root(self) -> None:
        """The folder is checked like Impostazioni checks it (never inside the
        log mirror or the output folder) BEFORE anything is created or saved."""
        current = self.api.workspace_root()
        folder = ask.ask_folder(self, strings.OFFICINA_ROOT_TITLE, current)
        if folder is None:
            return
        cfg = self.services.config.load()
        cfg = dataclasses.replace(cfg, officina=dataclasses.replace(cfg.officina, root=folder))
        problems = officina_root_errors(cfg)
        if problems:
            self.chooser.error.set_text(problems[0])
            self._notify(problems[0])
            return
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.chooser.error.set_text(
                strings.OFFICINA_ROOT_FAILED.format(path=folder, reason=exc))
            return
        self.chooser.error.set_text("")
        try:
            self.services.config.save(cfg)
        except (OSError, ValueError) as exc:
            message = strings.OFFICINA_ROOT_SAVE_FAILED.format(reason=exc)
            self.chooser.error.set_text(message)
            self._notify(message)
            return
        self.config_changed.emit(cfg)
        self.ini, self.case_id = None, None
        self.show_list()
        if ask.in_onedrive(folder):
            self._toast(strings.OFFICINA_ROOT_ONEDRIVE.format(path=folder), "warn")

    def new_initiative(self) -> None:
        name = ask.ask_text(self, strings.OFFICINA_NEW_INITIATIVE,
                            strings.OFFICINA_NEW_INITIATIVE_LABEL)
        if not name:
            return
        try:
            ini = self.api.create_initiative(name)
        except FileExistsError:
            self._notify(strings.OFFICINA_NEW_INITIATIVE_FAILED.format(
                reason=strings.OFFICINA_INITIATIVE_EXISTS.format(name=name)))
            return
        except (OSError, ValueError) as exc:
            self._notify(strings.OFFICINA_NEW_INITIATIVE_FAILED.format(reason=exc))
            return
        self.list.show_initiatives(self.api.initiatives(), select=ini.id)

    def add_from_search(self) -> None:
        """Ricerca, with a hint: the context menu there adds the case here."""
        shower = getattr(self._window, "show_page", None)
        if callable(shower):
            shower("search")
        self._toast(strings.OFFICINA_SEARCH_HINT)

    def add_from_file(self) -> None:
        if self.ini is None:
            return
        choice = ask_add_case(self, initiative_choices(self.api.initiatives()),
                              current=self.ini.id, from_file=True)
        if choice is None:
            return
        try:
            ini, case = create_case(self.services, choice)
        except ValueError as exc:
            self._notify(strings.OFFICINA_ADD_FAILED.format(reason=exc))
            return
        self._toast(strings.OFFICINA_ADDED.format(key=case.key, initiative=ini.name), "ok")
        self.ini = ini
        self._reload_initiative()
        self.show_board()

    def generate_asis(self) -> None:
        """The workbench's AS-IS button: a replacement needs a note (spec §14)."""
        case = self._case(self.case_id)
        if case is None:
            return
        note = None
        if case.asis() is not None:
            note = ask.ask_note(self, strings.OFFICINA_ASIS_NOTE_TITLE,
                                strings.OFFICINA_ASIS_NOTE_LABEL)
            if not note:
                self._notify(strings.OFFICINA_ASIS_NOTE_REQUIRED)
                return
        self._generate([case], "asis", note)

    def choose_target(self) -> None:
        case = self._case(self.case_id)
        if case is None:
            return
        path = ask.ask_open_file(self, strings.OFFICINA_TARGET_TITLE,
                                 strings.OFFICINA_TARGET_FILTER)
        if path is None:
            return
        try:
            self.api.set_target(case, path)
        except (OSError, ValueError) as exc:
            self._notify(strings.OFFICINA_TARGET_FAILED.format(reason=exc))
            return
        self._toast(strings.OFFICINA_TARGET_SET.format(name=path.name), "ok")
        self.board.forget_summary(case.id)
        self._reload_initiative()
        self.open_case(case.id)

    def edit_payload(self) -> None:
        case = self._case(self.case_id)
        if case is None:
            return
        from qtrequestory.ui.pages.officina_editor import PayloadHeaderDialog

        dialog = PayloadHeaderDialog(self.services, case, self)
        try:
            if dialog.exec():
                self._toast(strings.OFFICINA_EDITOR_SAVED, "ok")
        finally:
            dialog.deleteLater()
        self._reload_initiative()
        self.open_case(case.id)

    def toggle_status(self) -> None:
        case = self._case(self.case_id)
        if case is None:
            return
        if case.load_error or self._run_state(case.id) is not None:
            return  # the button is disabled: a broken file or a case on its way
        accepting = case.status != "accepted"
        if accepting and not self.case_view.comparison_is_equal() and not ask.confirm(
                self, strings.OFFICINA_MARK_ACCEPTED, strings.OFFICINA_ACCEPT_WITH_DIFFS):
            return
        if accepting:
            case.mark_accepted()  # as of the latest TO-BE: a newer one reopens it
        else:
            case.mark_open()
        try:
            self.api.save_case(case)
        except (OSError, ValueError) as exc:
            self._notify(strings.OFFICINA_EDITOR_SAVE_FAILED.format(reason=exc))
            self._reload_initiative()
            self.open_case(case.id)
            return
        self._toast(strings.OFFICINA_ACCEPTED if accepting else strings.OFFICINA_REOPENED, "ok")
        self._reload_initiative()
        self.open_case(case.id)
