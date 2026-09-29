"""The Officina tab: setup → initiatives → board → case workbench.

One ``QStackedWidget`` with four screens (see ``officina_setup``,
``officina_list``, ``officina_board``, ``officina_case``). While no folder is
chosen the first screen is the "Configura l'Officina" card (folder and
generator, release 1.3.2); while the folder is there but no generator is
active, the same card sits over the initiatives. This module is the controller: it
reads the Officina through ``services.officina``, runs every generation
through one :class:`~qtrequestory.ui.pages.officina_jobs.GenerationQueue`
(at most three cases at once, a failed case never stops the others) and every
comparison in a ``JobRunner`` job, and keeps the reason of each case's last
failed generation in memory (the model stores only successful runs).

Nothing heavy is imported here: PDFium is only reached inside the workers.
The page reads the disk when it is shown, not when the window is built.
"""
from __future__ import annotations

from collections import deque
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import Case, CoreServices, Initiative
from qtrequestory.ui.pages import officina_dialogs as ask
from qtrequestory.ui.pages.officina_actions import CaseActionsMixin
from qtrequestory.ui.pages.officina_board import Board
from qtrequestory.ui.pages.officina_compare_jobs import CompareJobsMixin
from qtrequestory.ui.pages.officina_delete import InitiativeDeletionMixin
from qtrequestory.ui.pages.officina_case import CaseView
from qtrequestory.ui.pages.officina_docside import case_versions, version_key
from qtrequestory.ui.pages.officina_filters_page import FiltersMixin
from qtrequestory.ui.pages.officina_generation import GenerationMixin
from qtrequestory.ui.pages.officina_jobs import GenerationQueue
from qtrequestory.ui.pages.mirror_banner import open_settings_section
from qtrequestory.ui.pages.officina_list import InitiativeList
from qtrequestory.ui.pages.officina_noise_page import NoiseRulesMixin
from qtrequestory.ui.pages.officina_review import ReviewActionsMixin
from qtrequestory.ui.pages.officina_setup import SetupCard
from qtrequestory.ui.pages.officina_undo import UndoStack
from qtrequestory.ui.workers import OFFICINA_ADD_JOB, OFFICINA_DELIVERY_JOB, JobRunner

__all__ = ["OfficinaPage"]

VIEWS = ("setup", "list", "board", "case")
#: The setup card standing in for the initiatives: wide enough for the URL.
SETUP_WIDTH = 760


class OfficinaPage(CaseActionsMixin, ReviewActionsMixin, FiltersMixin, NoiseRulesMixin, CompareJobsMixin,
                   GenerationMixin, InitiativeDeletionMixin, QWidget):
    """The Officina tab (``PAGES`` key ``officina``, Ctrl+3)."""

    #: The folder chosen here was saved: the shell tells the other pages.
    config_changed = Signal(object)

    def __init__(self, services: CoreServices, runner: JobRunner, window: object | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self.runner = runner
        self._window = window
        self.ini: Initiative | None = None
        self.case_id: str | None = None
        #: (initiative id, case id) -> why its last generation failed (masked),
        #: until one succeeds. The model stores only successful runs.
        self.failures: dict[tuple[str, str], str] = {}
        #: (initiative id, case id) of the cases "Annulla" stopped before sending.
        self.cancelled: set[tuple[str, str]] = set()
        #: The review actions each case can undo (Ctrl+Z, the toast's "Annulla"), in memory.
        self.undo = UndoStack()
        #: (initiative id, case id) -> the review requests waiting their turn (R38).
        self.review_queue: dict[tuple[str, str], deque] = {}
        self._loaded = False
        #: The folder the screens on show were read from (see on_config_changed).
        self._root: Path | None = None
        #: The setup card was filled since it came on screen (see _show_setup).
        self._setup_loaded = False
        #: The card over the list must be refilled when next synced.
        self._list_setup_stale = False

        self.queue = GenerationQueue(services, runner, parent=self)
        #: "Configura l'Officina": instead of the initiatives (no folder) …
        self.setup_card = SetupCard(services, require_generator=False, writing=self.is_writing)
        self.setup = _centered(self.setup_card, SETUP_WIDTH)
        #: … and over them (a folder, but no active generator).
        self.list_setup = SetupCard(services, require_generator=True, writing=self.is_writing)
        self.list_setup.hide()
        self.list = InitiativeList()
        self.list.set_setup_card(self.list_setup)
        self.board = Board()
        self.case_view = CaseView()
        self.board.run_state = self._run_state
        self.board.failure = self._failure
        self.board.note = self._note
        self.case_view.run_state = self._run_state
        self.stack = QStackedWidget()
        for widget in (self.setup, self.list, self.board, self.case_view):
            self.stack.addWidget(widget)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SPACE[3], theme.SPACE[2], theme.SPACE[3], theme.SPACE[2])
        layout.addWidget(self.stack)
        self._init_deletions(window)  # officina_delete: "Elimina iniziativa" (D6)
        self._connect()

    def _connect(self) -> None:
        for card in (self.setup_card, self.list_setup):
            card.saved.connect(self._on_setup_saved)
            card.settings_requested.connect(
                lambda: open_settings_section(self._window, "officina"))
        self.list.change_root_requested.connect(self.choose_root)
        self.list.new_requested.connect(self.new_initiative)
        self.list.open_requested.connect(self.open_initiative)
        self.list.folder_requested.connect(lambda: self._open_folder(self.api.workspace_root()))
        board = self.board
        board.back_requested.connect(self.show_list)
        board.open_requested.connect(self.open_case)
        board.add_from_search_requested.connect(self.add_from_search)
        board.add_from_file_requested.connect(self.add_from_file)
        board.generate_missing_requested.connect(self.generate_missing_asis)
        board.regenerate_requested.connect(self.regenerate_tobe)
        board.cancel_requested.connect(self.queue.cancel)
        board.deliver_requested.connect(self.deliver)
        board.folder_requested.connect(
            lambda: self._open_folder(self.ini.folder if self.ini else None))
        self._connect_case_view()
        self._connect_noise()  # officina_noise_page: "Regole di rumore…", the DOM sources
        self._connect_filters()  # officina_filters_page: "Filtri del confronto" (U4)
        self.queue.state_changed.connect(self._on_run_state)
        self.queue.case_finished.connect(self._on_case_finished)
        self.queue.progress.connect(self._show_progress)
        self.queue.batch_finished.connect(self._on_batch_finished)

    @property
    def api(self):
        return self.services.officina

    # -- navigation --------------------------------------------------------

    def view(self) -> str:
        return VIEWS[self.stack.currentIndex()]

    def refresh(self) -> None:
        """Re-read the disk and show the screen the user was on."""
        self._loaded = True
        self._root = self.api.workspace_root()
        if self._root is None:
            self.ini, self.case_id = None, None
            self._show_setup()
            return
        if self.ini is not None and self._reload_initiative():
            if self.case_id is not None and self._case(self.case_id) is not None:
                self.open_case(self.case_id)
            else:
                self.show_board()
            return
        self.show_list()

    def show_list(self) -> None:
        root = self.api.workspace_root()
        if root is None:
            self._show_setup()
            return
        self._sync_list_setup()
        self.list.root_label.setText(strings.OFFICINA_ROOT_LABEL.format(path=root))
        self.list.onedrive.set_text(strings.OFFICINA_ROOT_ONEDRIVE.format(path=root)
                                    if ask.in_onedrive(root) else "")
        self.list.show_initiatives(self.listed_initiatives(),
                                   select=self.ini.id if self.ini else None)
        self._close_filters()  # before the initiative goes: unsaved rules may be saved
        self.ini, self.case_id = None, None
        self.stack.setCurrentWidget(self.list)

    def open_initiative(self, initiative_id: str) -> None:
        """Open the initiative in folder ``initiative_id`` (``Initiative.id``);
        never one waiting to be deleted."""
        pending = self.pending_initiative(initiative_id)
        if pending is not None:
            self._notify(strings.ELIMINA_PENDING_OPEN.format(name=pending.name))
            self.ini = None
            self.show_list()
            return
        try:
            self.ini = self.api.load(initiative_id)
        except (FileNotFoundError, OSError, ValueError):
            self._notify(strings.OFFICINA_INITIATIVE_GONE.format(name=initiative_id))
            self.ini = None
            self.show_list()
            return
        self.show_board()

    def show_board(self) -> None:
        if self.ini is None:
            self.show_list()
            return
        self.case_id = None
        self._close_filters()
        self.board.show_initiative(self.ini)
        self.board.refresh_run_states()
        self._show_progress(*self.queue.counts())
        self.stack.setCurrentWidget(self.board)

    def open_case(self, case_id: str, version: str | None = None) -> None:
        case = self._case(case_id)
        if case is None or self.ini is None:
            return
        same = self.case_id == case_id and self.view() == "case"
        self.case_id = case_id
        if not same:  # a verification outcome belongs to the visit that saw it
            self.case_view.banners.forget()
        current = version or (self.case_view.current_version_key() if same else None)
        if current not in {version_key(v) for v in case_versions(case)}:
            current = self._default_version(case)
        self.case_view.show_case(case, self.ini.name, current, blocked=bool(self.ini.load_error),
                                 initiative_profile=self.ini.profile)
        self.case_view.set_failure(self._failure(case_id) or "")
        self.stack.setCurrentWidget(self.case_view)
        if not same:
            self.case_view.focus_default()  # F5 works at once, arrows scroll the document
        self._sync_filters()  # another case closes the Filtri dialog; the same one refreshes it
        self._load_docs(current)

    def current_initiative_id(self) -> str | None:
        """The id (folder) of the initiative on screen, for "Aggiungi all'Officina…"."""
        return self.ini.id if self.ini else None

    # -- shell hooks ---------------------------------------------------------

    def showEvent(self, event) -> None:  # noqa: N802 - Qt naming
        """The disk is read when the tab is shown, not while the window is built."""
        super().showEvent(event)
        self.refresh()

    def on_config_changed(self, _cfg: object) -> None:
        """Impostazioni saved: the folder or the generators may have changed.

        A new folder goes quietly to its list: the initiative on screen is not
        "gone" (it is in the old folder), and a same-named one in the new
        folder is another initiative, never swapped in."""
        if not self._loaded:
            return
        if self.api.workspace_root() != self._root:
            self.ini, self.case_id = None, None
        self._reload_setup_cards()
        self.refresh()

    def is_writing(self) -> bool:
        """True while cases wait or run, a delivery copies files or calls
        become cases ("Aggiungi chiamata…"): the
        folder must not change under them (Impostazioni asks)."""
        return self.queue.is_busy() or any(self.runner.is_running(name)
                                           for name in (OFFICINA_DELIVERY_JOB, OFFICINA_ADD_JOB))

    def on_quit(self) -> None:
        """The window is closing (the user already agreed): nothing more is
        sent. The waiting cases are dropped, the running ones stopped before
        they send."""
        self.queue.cancel()

    def on_case_added(self, _ini_id: str, _case_id: str) -> None:
        """Ricerca added a case. The tab re-reads the disk whenever it is
        shown, so only a tab already on screen needs telling."""
        if self._loaded and self.isVisible():
            self.refresh()

    # -- setup (release 1.3.2) -------------------------------------------------

    def _show_setup(self) -> None:
        """The card instead of the initiatives; filled from the configuration
        when it comes on screen (never over what the user is typing)."""
        if self.stack.currentWidget() is not self.setup or not self._setup_loaded:
            self.setup_card.load()
            self._setup_loaded = True
        self.stack.setCurrentWidget(self.setup)

    def _sync_list_setup(self) -> None:
        """The card over the initiatives, while no generator is active."""
        needed = not self.services.config.load().officina.enabled_generators()
        if needed and (self.list_setup.isHidden() or self._list_setup_stale):
            self.list_setup.load()
            self._list_setup_stale = False
        self.list_setup.setVisible(needed)

    def _reload_setup_cards(self) -> None:
        """The configuration was saved elsewhere (Impostazioni, the other
        card): a card must show it, or its [Salva] would write back the old
        folder and generators over that save. What was saved wins over a
        half-typed card."""
        self._setup_loaded = False
        self._list_setup_stale = True

    def _on_setup_saved(self, cfg) -> None:
        """A card saved: tell the other pages, and go on without a restart."""
        self.config_changed.emit(cfg)
        if self.api.workspace_root() != self._root:
            self.ini, self.case_id = None, None
        self.refresh()
        root = cfg.officina.root
        if root is not None and ask.in_onedrive(root):
            self._toast(strings.OFFICINA_ROOT_ONEDRIVE.format(path=root), "warn")
        else:
            self._toast(strings.OFFICINA_SETUP_SAVED, "ok")

    # -- helpers -----------------------------------------------------------

    def _reload_initiative(self) -> bool:
        if self.ini is None:
            return False
        try:
            self.ini = self.api.load(self.ini.id)
        except (FileNotFoundError, OSError, ValueError):
            self._notify(strings.OFFICINA_INITIATIVE_GONE.format(name=self.ini.name))
            self.ini, self.case_id = None, None
            self.show_list()
            return False
        return True

    def _case(self, case_id: str | None) -> Case | None:
        if self.ini is None or case_id is None:
            return None
        return next((c for c in self.ini.cases if c.id == case_id), None)

    @staticmethod
    def _default_version(case: Case) -> str | None:
        latest = case.latest_tobe()
        if latest is not None:
            return version_key(latest)
        return "asis" if case.asis() is not None else None

    def _run_state(self, case_id: str) -> str | None:
        return self.queue.state(self.ini.id, case_id) if self.ini is not None else None

    def _note(self, case_id: str) -> str | None:
        key = (self.ini.id, case_id) if self.ini is not None else None
        return strings.OFFICINA_RUN_CANCELLED if key in self.cancelled else None

    def _failure(self, case_id: str) -> str | None:
        return self.failures.get((self.ini.id, case_id)) if self.ini is not None else None

    def _open_folder(self, path: Path | None) -> None:
        if path is not None:
            self.services.extract.open_folder(path)

    def _notify(self, text: str) -> None:
        setter = getattr(self._window, "set_status", None)
        if callable(setter):
            setter(text)

    def _toast(self, text: str, tone: str = "neutral", action=None, hint: str = "") -> None:
        """A toast (the status bar without a window); ``action`` = ``(button
        text, callback)`` adds a button, ``hint`` follows it ("(Ctrl+Z)")."""
        toast = getattr(self._window, "show_toast", None)
        if callable(toast) and action is not None:
            toast(text, tone, action=action, hint=hint)
        elif callable(toast):
            toast(text, tone)
        else:
            self._notify(text)


def _centered(widget: QWidget, width: int) -> QWidget:
    """``widget`` at a fixed width, centred, a little above the middle."""
    widget.setFixedWidth(width)  # a fixed width lets the wrapped text claim its height
    screen = QWidget()
    # Stretches rather than an alignment flag: an aligned item loses
    # height-for-width, and the wrapped sentences would be clipped.
    row = QHBoxLayout()
    row.addStretch(1)
    row.addWidget(widget)
    row.addStretch(1)
    outer = QVBoxLayout(screen)
    outer.addStretch(1)
    outer.addLayout(row)
    outer.addStretch(2)
    return screen
