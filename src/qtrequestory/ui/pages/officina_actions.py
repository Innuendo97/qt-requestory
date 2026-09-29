"""The user actions of the Officina tab (a mixin of ``OfficinaPage``).

Changing the Officina folder (the first choice is the setup card's), creating an
initiative, adding a case from a file or from the logged calls ("Aggiungi chiamata…",
also "Cambia chiamata…" of a case: ``officina_pick_call``, carried out in the
``officina-add`` job),
the AS-IS (a replacement needs a note: spec §14 "a baseline can only be
changed with a note"), the TARGET, the payload and header editor,
accepting / reopening a case, and (phase 2) the case's profile — each saves
``caso.json`` and compares the same version again. The review actions
("segna fatta", "tollera", … with their undo) are ``officina_review``. Split from
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
from qtrequestory.ui.pages.officina_add_plan import PlanOutcome, outcome_text, run_plan
from qtrequestory.ui.pages.officina_banners import profile_name
from qtrequestory.ui.workers import OFFICINA_ADD_JOB

__all__ = ["CaseActionsMixin"]


class CaseActionsMixin:
    """What the list's buttons, the board's "+ Caso…" buttons and the
    workbench's toolbar do."""

    def _connect_case_view(self) -> None:
        case = self.case_view
        case.back_requested.connect(self.show_board)
        case.regenerate_requested.connect(lambda: self.regenerate_tobe([self.case_id]))
        case.asis_requested.connect(self.generate_asis)
        case.target_requested.connect(self.choose_target)
        case.editor_requested.connect(self.edit_payload)
        case.status_toggle_requested.connect(self.toggle_status)
        case.version_chosen.connect(self._load_docs)
        case.profile_chosen.connect(self.set_case_profile)
        case.reset_tolerances_requested.connect(self.reset_case_tolerances)
        case.change_call_requested.connect(self.change_call)
        case.asis_after_call_requested.connect(self.regenerate_asis_after_call)
        self._connect_review()  # officina_review: F / T / V, the mini-bar, the menu, undo

    def choose_root(self) -> None:
        """The list's "Cambia cartella…" (the first choice is the setup
        card's). The folder is checked like Impostazioni checks it (never
        inside the log mirror or the output folder) BEFORE anything is
        created or saved; a refusal is said in the status bar."""
        current = self.api.workspace_root()
        folder = ask.ask_folder(self, strings.OFFICINA_ROOT_TITLE, current)
        if folder is None:
            return
        cfg = self.services.config.load()
        cfg = dataclasses.replace(cfg, officina=dataclasses.replace(cfg.officina, root=folder))
        problems = officina_root_errors(cfg)
        if problems:
            self._notify(problems[0])
            return
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._notify(strings.OFFICINA_ROOT_FAILED.format(path=folder, reason=exc))
            return
        try:
            self.services.config.save(cfg)
        except (OSError, ValueError) as exc:
            self._notify(strings.OFFICINA_ROOT_SAVE_FAILED.format(reason=exc))
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
            reason = (strings.ELIMINA_NAME_PENDING if self.pending_named(name)
                      else strings.OFFICINA_INITIATIVE_EXISTS).format(name=name)
            self._notify(strings.OFFICINA_NEW_INITIATIVE_FAILED.format(reason=reason))
            return
        except (OSError, ValueError) as exc:
            self._notify(strings.OFFICINA_NEW_INITIATIVE_FAILED.format(reason=exc))
            return
        self.list.show_initiatives(self.listed_initiatives(), select=ini.id)

    def add_from_search(self) -> None:
        """The board's "Aggiungi chiamata…"."""
        self.pick_calls()

    def change_call(self) -> None:
        """"Cambia chiamata…" of the case on screen (its "⋯" menu, the editor's link)."""
        case = self._case(self.case_id)
        if case is None or case.load_error or self._run_state(case.id) is not None:
            return  # disabled meanwhile: a broken caso.json, a case on its way
        self.pick_calls(case)

    def pick_calls(self, case=None) -> None:
        """"Aggiungi chiamata…" (on ``case``: its call replaced by default)."""
        if self.ini is None:
            return
        if self.runner.is_running(OFFICINA_ADD_JOB):
            self._notify(strings.CHIAMATA_BUSY)
            return
        from qtrequestory.ui.pages.officina_pick_call import PickCallDialog

        dialog = PickCallDialog(self.services, self.runner, self.listed_initiatives(), current=self.ini.id,
                                case=case, busy=self.case_busy, parent=self)
        try:
            plan = dialog.plan() if dialog.exec() else None
        finally:
            dialog.deleteLater()
        if plan is not None:
            self.run_add_plan(*plan)

    def case_busy(self, initiative_id: str, case_id: str) -> bool:
        """True while case ``case_id`` of ``initiative_id`` waits or is sent:
        its call must not change under the queue (also asked by Ricerca)."""
        return self.queue.state(initiative_id, case_id) is not None

    def run_add_plan(self, target, items) -> None:
        """Every chosen call in ONE worker job, then one status line and one refresh.
        A case waiting for or being sent keeps its call (its payload must not
        change under the queue)."""
        if not target.create:
            busy = [i for i in items if i.replace is not None and self.case_busy(target.initiative, i.replace)]
            if busy:
                self._notify(strings.CHIAMATA_CASE_BUSY.format(case=busy[0].replace))
                return
        job = self.runner.submit(OFFICINA_ADD_JOB, run_plan, self.api, target, list(items))
        if job is None:
            self._notify(strings.CHIAMATA_BUSY)
            return
        self._notify(strings.CHIAMATA_ADDING)
        job.signals.result.connect(self._on_plan_done)
        job.signals.error.connect(
            lambda _kind, message: self._notify(strings.CHIAMATA_FAILED_ALL.format(reason=message)))

    def _on_plan_done(self, out: PlanOutcome) -> None:
        text = outcome_text(out)
        self._notify(text)
        self._toast(text, "warn" if out.error or out.failed else "ok")
        if out.initiative is None:
            return
        view = self.view()
        if view == "case" and self.ini is not None and self.ini.id == out.initiative.id:
            if self._reload_initiative() and self._case(self.case_id) is not None:
                self.open_case(self.case_id)  # the call strip says the AS-IS is older
        elif view == "board":
            self.ini = out.initiative  # the initiative chosen in the window
            if self._reload_initiative():
                self.show_board()
        elif view == "list":
            self.show_list()

    def regenerate_asis_after_call(self) -> None:
        """The call strip's "Rigenera AS-IS": the replacement's note is said for the user."""
        case = self._case(self.case_id)
        if case is None:
            return
        self._generate([case], "asis", strings.CHIAMATA_ASIS_NOTE if case.asis() is not None else None)

    def add_from_file(self) -> None:
        if self.ini is None:
            return
        choice = ask_add_case(self, initiative_choices(self.listed_initiatives()),
                              current=self.ini.id, from_file=True)
        if choice is None:
            return
        if choice.create and self.pending_named(choice.initiative):  # its folder is still there (D6)
            self._notify(strings.OFFICINA_ADD_FAILED.format(
                reason=strings.ELIMINA_NAME_PENDING.format(name=choice.initiative)))
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
        review = case.review
        clears = case.target() is not None and bool(review.marks or review.unresolved
                                                     or review.summary is not None)
        if clears and not ask.confirm(self, strings.OFFICINA_TARGET_REPLACE_TITLE,
                                      strings.OFFICINA_TARGET_REPLACE):
            return  # R29: a new target clears the marks and the summary
        try:
            self.api.set_target(case, path)
        except (OSError, ValueError) as exc:
            self._notify(strings.OFFICINA_TARGET_FAILED.format(reason=exc))
            return
        self._toast(strings.OFFICINA_TARGET_SET.format(name=path.name), "ok")
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
            change = dialog.wants_change_call
        finally:
            dialog.deleteLater()
        self._reload_initiative()
        self.open_case(case.id)
        if change:
            self.change_call()

    def toggle_status(self) -> None:
        case = self._case(self.case_id)
        if case is None:
            return
        if case.load_error or self._run_state(case.id) is not None:
            return  # the button is disabled: a broken file or a case on its way
        accepting = case.status != "accepted"
        warning = self.case_view.acceptance_warning() if accepting else ""
        if warning and not ask.confirm(self, strings.OFFICINA_MARK_ACCEPTED, warning):
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

    def set_case_profile(self, profile: str | None) -> None:
        """The header's profile menu: save it for the case (None = follow the
        initiative), then judge the version on screen again."""
        case = self._case(self.case_id)
        if case is None or self.ini is None:
            return
        if self.case_view.judging or self.case_view.acting:  # the menu is disabled meanwhile
            self._notify(strings.REVISIONE_WAIT_COMPARE)
            self.case_view.profile_menu.set_profile(case.review.profile, self.ini.profile)
            return
        try:
            self.api.set_profile(self.ini, case, profile)
        except (OSError, ValueError) as exc:
            self._notify(strings.PROFILO_FAILED.format(reason=exc))
            self.case_view.profile_menu.set_profile(case.review.profile, self.ini.profile)
            return
        self._toast(strings.PROFILO_SET.format(profile=profile_name(profile or self.ini.profile)))
        self._reload_initiative()
        self.open_case(case.id)  # the same version, compared again

    def reset_case_tolerances(self) -> None:
        """"Azzera tolleranze…" (spec §5.2, R45): after a question (no undo),
        the case's manual tolerances and «non è una variabile» go; the same
        version is judged again."""
        case = self._case(self.case_id)
        if case is None or self.ini is None:
            return
        queued = self.review_queue.get((self.ini.id, self.case_id))
        if self.case_view.judging or self.case_view.acting or queued:
            self._notify(strings.REVISIONE_WAIT_COMPARE)
            return
        if not ask.confirm(self, strings.CASO_RESET_TOLERANCES_TITLE,
                           strings.OFFICINA_RESET_TOLERANCES_CONFIRM):
            return
        try:
            self.api.reset_tolerances(case)
        except (OSError, ValueError) as exc:
            self._notify(strings.CASO_RESET_TOLERANCES_FAILED.format(reason=exc))
            return
        self._toast(strings.CASO_RESET_TOLERANCES_DONE, "ok")
        self._reload_initiative()
        self.open_case(case.id)  # the same version, compared again
