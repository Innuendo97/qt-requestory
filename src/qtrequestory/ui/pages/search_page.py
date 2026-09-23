"""The Ricerca page: filter bar, results, preview.

Layout (approved redesign, section 2)::

    [Ambiente ▾] [omnibox ……] [esatta|contiene] [7|30|90|📅] [Cerca]   <- full width
    12 chiamate · 1 FDI · … | log coll dal … al …   [Raggruppa per FDI] <- meta line
    mancano 3 giorni in coll · [Vai a Sincronizzazione]                 <- only if so
    +-------------------------------+------------------------------+
    | results (or an empty state)   | preview pane                 |
    +-------------------------------+------------------------------+

The bar is outside the splitter, so it no longer sets the page's minimum
width; while an empty state shows, the preview half is hidden. After a search
the row the user most likely wants is selected: for an FDI-only search the
entry with the most documents on the newest day (``pick_best``, as README
promises), otherwise the newest call.

Row actions, shortcuts and drag-out live in ``search_actions``; core calls in
``search_presenter``; the empty states in ``search_states``; the preview slot
in ``search_slot``.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

from PySide6.QtCore import QModelIndex, QSettings, Qt
from PySide6.QtGui import QAction, QGuiApplication
from PySide6.QtWidgets import QLabel, QMenu, QSplitter, QStackedLayout, QVBoxLayout, QWidget

from qtrequestory.ui import actions, prefs, strings, theme
from qtrequestory.ui.contracts import CoreServices, SearchHit, SearchQuery
from qtrequestory.ui.pages import search_actions
from qtrequestory.ui.pages.mirror_banner import MirrorRootBanner
from qtrequestory.ui.pages.preview_pane import PreviewPane
from qtrequestory.ui.pages.search_form import SearchForm
from qtrequestory.ui.pages.search_meta import (
    GapBanner,
    MetaLine,
    TitleContext,
    coverage_gap,
    summary_text,
)
from qtrequestory.ui.pages.search_presenter import SearchPresenter
from qtrequestory.ui.pages.search_recents import Recent, load_recents, remember
from qtrequestory.ui.pages.search_results import ResultsView, preselect, sort_tail
from qtrequestory.ui.pages.search_slot import PreviewSlot
from qtrequestory.ui.pages.search_states import WIDE_WINDOW_DAYS, SearchStates
from qtrequestory.ui.results_model import ResultsModel
from qtrequestory.ui.workers import JobRunner

__all__ = ["SearchPage", "SearchPresenter"]

#: ``QSettings`` key of the last used environment.
ENV_SETTING = "search/env"
#: The pages of the results stack, in stack order.
STATES = ("table", "start", "no_log", "no_results", "no_env")


class SearchPage(QWidget):
    """Bar + results + preview slot; the application's default page."""

    def __init__(self, services: CoreServices, runner: JobRunner, window: object | None = None,
                 parent: QWidget | None = None, *,
                 preview_factory: Callable[..., QWidget] | None = PreviewPane) -> None:
        """``preview_factory(services, runner, page)`` builds the preview pane."""
        super().__init__(parent)
        self.services = services
        self.runner = runner
        self._window = window
        self._preview: QWidget | None = None
        self._query: SearchQuery | None = None
        self._env = ""
        self.shortcuts: dict[str, object] = {}
        #: DESIGN-ui §Navigation: a future page may append its own row actions.
        self.context_menu_actions: list[QAction] = []

        self.presenter = SearchPresenter(services, runner, self)
        self.title = TitleContext(self, window)
        self.form = SearchForm()
        self.meta = MetaLine()
        self.gap_banner = GapBanner()
        self.mirror_banner = MirrorRootBanner(services, window)
        self.stale_banner = QLabel()
        self.model = ResultsModel(self)
        self.view = ResultsView(self.model)
        self.view.drag_provider = self.prepare_drag_file
        self.states = SearchStates(on_sync=lambda: self._show_page("sync"),
                                   on_widen=self._widen_window,
                                   on_settings=lambda: self._show_page("settings"))
        self.preview_slot = PreviewSlot()
        self.preview_placeholder = self.preview_slot.placeholder

        self._build()
        self._connect()
        if preview_factory is not None:
            self.set_preview_widget(preview_factory(services, runner, self))
        self.form.set_preset(self.presenter.default_window_days())
        self.set_grouped(bool(self._settings().value(
            prefs.GROUP_BY_FDI_KEY, prefs.GROUP_BY_FDI_DEFAULT, type=bool)), persist=False)
        self._set_state("start")
        self._load_config()

    # -- construction ------------------------------------------------------

    def _build(self) -> None:
        self.stale_banner.setVisible(False)
        self.stale_banner.setWordWrap(True)
        theme.set_role(self.stale_banner, "muted")

        self.results_stack = QStackedLayout()
        self.results_stack.addWidget(self.view)
        for name in STATES[1:]:
            self.results_stack.addWidget(self.states.widgets()[name])
        results = QWidget()
        results.setLayout(self.results_stack)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(results)
        self.splitter.addWidget(self.preview_slot)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(8)
        for widget in (self.mirror_banner, self.form, self.meta, self.gap_banner,
                       self.stale_banner):
            outer.addWidget(widget)
        outer.addWidget(self.splitter, 1)

    def _connect(self) -> None:
        self.form.search_requested.connect(self.run_search)
        self.form.env_changed.connect(self._on_env_changed)
        self.form.omnibox.recent_chosen.connect(self.apply_recent)
        self.gap_banner.go_sync.connect(lambda: self._show_page("sync"))
        self.meta.group_button.toggled.connect(self.set_grouped)
        self.presenter.results_ready.connect(self._on_results)
        self.presenter.status.connect(self._notify)
        self.presenter.busy.connect(self.form.set_busy)
        self.presenter.selection_changed.connect(self._deliver)
        self.presenter.selection_changed.connect(self._name_window)
        self.presenter.template_keys_ready.connect(self.form.set_template_keys)
        self.presenter.index_pending.connect(self._on_index_pending)
        self.view.open_requested.connect(self.open_selected)
        self.view.doubleClicked.connect(self._on_double_click)
        self.view.customContextMenuRequested.connect(
            lambda pos: search_actions.show_context_menu(self, pos))
        self.view.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self.view.header().sortIndicatorChanged.connect(lambda *_a: self._update_summary())
        self.shortcuts.update(search_actions.install_shortcuts(self))

    def _load_config(self) -> None:
        """Environments and the remembered choice, then the env load.

        The period is NOT touched here: it is set once, from the configured
        default, when the page is built. Saving Impostazioni must not throw
        away the window the user picked.
        """
        self.mirror_banner.refresh()
        envs = self.presenter.environments()
        self._show_recents(load_recents(self._settings()))
        remembered = self._settings().value(ENV_SETTING)
        current = remembered if remembered in envs else (envs[0] if envs else "")
        self.form.set_environments(envs, current)
        self.form.setEnabled(bool(envs))
        if not envs:
            self._env = ""
            self._clear_results()
            self.meta.coverage_label.clear()
            self.gap_banner.set_gap("", ())
            self._set_state("no_env")
            return
        if self.current_state() == "no_env":
            self._set_state("start")
        if current:
            self._on_env_changed(current)

    def on_config_changed(self, _cfg: object) -> None:
        """Impostazioni was saved: environments and Ricerca's preferences may
        have moved; the period and the results stay."""
        stored = self._settings()
        self.form.set_key_mode(str(stored.value(prefs.KEY_MODE_KEY, self.form.key_mode())),
                               persist=False)
        self.set_grouped(bool(stored.value(prefs.GROUP_BY_FDI_KEY, self.model.grouped(),
                                           type=bool)), persist=False)
        refresh = getattr(self._preview, "refresh_editor_label", None)
        if callable(refresh):
            refresh()  # the editor may have changed
        self._load_config()

    def on_data_changed(self) -> None:
        """A sync or an index job finished: coverage, keys and the stale banner
        may have moved. The results and the period stay."""
        if not self._env:
            return
        self.presenter.reload_template_keys(self._env)
        self.presenter.refresh_index_state(self._env)
        self._update_coverage(self._env)

    # -- public API --------------------------------------------------------

    def set_preview_widget(self, widget: QWidget | None) -> None:
        """Install (or remove, with None) the preview pane in the right half."""
        self._preview = widget
        self.preview_slot.install(widget)
        if widget is not None:
            self._deliver(self.selected_hit())  # a pane installed late is not empty

    def preview_widget(self) -> QWidget | None:
        return self._preview

    def initial_focus(self) -> None:
        """Shell hook at startup: typing an FDI right away lands in the omnibox."""
        self.form.omnibox.edit.setFocus(Qt.FocusReason.OtherFocusReason)

    def selected_hit(self) -> SearchHit | None:
        return self.view.selected_hit()

    def selected_entries(self) -> list[SearchHit]:
        """DESIGN-ui §Navigation: what a future page would act on."""
        hit = self.selected_hit()
        return [hit] if hit is not None else []

    def current_state(self) -> str:
        return STATES[self.results_stack.currentIndex()]

    def set_grouped(self, grouped: bool, *, persist: bool = True) -> None:
        """[Raggruppa per FDI]: regroup, keep the selected call selected."""
        selected = self.selected_hit()
        self.meta.group_button.blockSignals(True)
        self.meta.group_button.setChecked(grouped)
        self.meta.group_button.blockSignals(False)
        if persist:
            self._settings().setValue(prefs.GROUP_BY_FDI_KEY, grouped)
        if grouped != self.model.grouped():
            self.model.set_grouped(grouped)
            self.view.select_hit(selected)

    def run_search(self) -> None:
        """Build the query from the bar and submit it (F5, Enter, [Cerca])."""
        env = self.form.current_env()
        if not env or not self.form.can_search():
            return
        self.form.omnibox.commit()
        fdi, key, mode = self.form.fdi(), self.form.template_key(), self.form.key_mode()
        day_from, day_to = self.form.day_range()
        self._query = SearchQuery(env=env, fdi_prefix=fdi.lower() or None,
                                  template_key=key.upper() or None, key_mode=mode,
                                  day_from=day_from, day_to=day_to)
        self._show_recents(remember(self._settings(), Recent(env, fdi, key, mode)))
        self.presenter.search(self._query)

    def apply_recent(self, recent: Recent) -> None:
        """A recent search, run again as it was — in its own environment only."""
        if recent.env not in self.form.environments():
            self._notify(strings.SEARCH_RECENT_ENV_DISABLED.format(env=recent.env))
            return
        self.form.set_env(recent.env)
        self.form.set_fdi(recent.fdi)
        self.form.set_template_key(recent.key)
        self.form.set_key_mode(recent.mode, persist=False)
        self.run_search()

    def build_context_menu(self, hit: SearchHit) -> QMenu:
        """The row menu, built without showing it (so it can be tested)."""
        return search_actions.build_context_menu(self, hit)

    def prepare_drag_file(self, hit: SearchHit) -> Path | None:
        """The file a dragged row hands out (see ``search_actions``)."""
        return search_actions.prepare_drag_file(self, hit)

    # -- what the preview pane (and the row actions) report through -------

    def set_status(self, text: str) -> None:
        """A transient hint in the window's status bar."""
        self._notify(text)

    def show_toast(self, text: str, tone: str = "neutral") -> None:
        """A confirmation over the content; the status bar when there is no toast."""
        toast = getattr(self._window, "show_toast", None)
        if callable(toast):
            toast(text, tone)
        else:
            self._notify(text)

    def confirm(self, text: str) -> None:
        """"Copiato negli appunti…": what a copy or a save says it did."""
        self.show_toast(text, "ok")

    # -- row actions (search_actions, the pane's Dettagli tab) -------------

    def open_selected(self) -> None:
        self.delegate("open_in_editor")

    def delegate(self, method: str, *_args) -> None:
        """Apri / Salva / Copia JSON / cartella belong to whoever holds the body.

        Only for the SELECTED call: the pending selection is delivered first,
        and when the pane still shows another one (a group row was clicked,
        which selects nothing) the action is refused instead of acting on a
        call the user no longer has selected.
        """
        action = getattr(self._preview, method, None)
        if not callable(action):
            self._notify(strings.SEARCH_NO_PREVIEW_TOOLTIP)
            return
        self.presenter.flush_selection()
        selected = self.selected_hit()
        current = getattr(self._preview, "current_hit", None)
        if selected is None or (callable(current) and current() != selected):
            self._notify(strings.SEARCH_NOTHING_SELECTED)
            return
        action()

    def copy_value(self, text: str | None, message: str, *_args) -> None:
        QGuiApplication.clipboard().setText(text or "")
        self.confirm(message)

    def search_only(self, fdi: str | None, key: str | None, *_args) -> None:
        self.form.set_fdi(fdi or "")
        self.form.set_template_key(key or "")
        self.run_search()

    def open_day_folder(self, hit: SearchHit, *_args) -> None:
        self.services.extract.open_folder(hit.file_path.parent)

    # -- reactions ---------------------------------------------------------

    def _on_results(self, hits: list[SearchHit]) -> None:
        self.model.set_hits(hits)
        self._update_summary()
        if hits:
            self._set_state("table")
            self.view.select_hit(preselect(hits, self._query))
        else:
            self.states.describe_no_results(self._query, date.today())
            self._set_state("no_results")
        # Explicit: a model reset does not always emit selectionChanged, and the
        # pane must be told when there is nothing to show.
        self.presenter.select(self.selected_hit())

    def _update_summary(self) -> None:
        hits = self.model.hits()
        self.meta.set_summary(summary_text(hits, sort_tail(self.model)) if hits else "")

    def _on_selection_changed(self, _selected=None, _deselected=None) -> None:
        self.presenter.select(self.selected_hit())

    def _on_double_click(self, index: QModelIndex) -> None:
        if self.model.hit_of(index) is not None:  # a group row just folds
            self.open_selected()

    def _deliver(self, hit: SearchHit | None) -> None:
        """Hand the settled selection to the preview pane, if one is installed."""
        setter = getattr(self._preview, "set_hit", None)
        if callable(setter):
            setter(hit)

    def _name_window(self, hit: SearchHit | None) -> None:
        """Window title "qtRequestory — coll · 1a2b3c4d" for the selected call."""
        if hit is None:
            self.title.set(None)
        else:
            self.title.set(strings.SEARCH_WINDOW_CONTEXT.format(env=hit.env, fdi=hit.fdi[:8])
                           if hit.fdi else hit.env)

    def _on_env_changed(self, env: str) -> None:
        # Rows found in the PREVIOUS environment must go; a reload that does not
        # change the environment (Impostazioni saved) keeps them.
        if env != self._env:
            self._clear_results()
        self._env = env
        self._settings().setValue(ENV_SETTING, env)
        self.presenter.reload_template_keys(env)
        self.presenter.refresh_index_state(env)
        self._update_coverage(env)

    def _clear_results(self) -> None:
        """Drop the rows AND any state describing the search that made them."""
        self.model.set_hits([])
        self.meta.set_summary("")
        self._query = None
        if self.current_state() in ("table", "no_results", "no_log"):
            self._set_state("start")
        self.presenter.select(None)

    def _on_index_pending(self, pending: int) -> None:
        """Just display: the shell is what triggers the index job."""
        self.stale_banner.setText(strings.SEARCH_STALE_BANNER.format(n=pending))
        self.stale_banner.setVisible(pending > 0)

    def _update_coverage(self, env: str) -> None:
        coverage = self.presenter.coverage(env)
        days = self.presenter.coverage_days(env)
        self.meta.set_coverage(env, coverage)
        self.gap_banner.set_gap(env, coverage_gap(days, date.today()) if days else ())
        if coverage is None:
            self.states.describe_no_log(env, rebuilding=bool(days and days.present))
            self._set_state("no_log")
        elif self.current_state() == "no_log":
            self._set_state("start")  # this environment has logs after all

    def _widen_window(self) -> None:
        self.form.set_preset(WIDE_WINDOW_DAYS)
        self.run_search()

    def _show_recents(self, recents: list[Recent]) -> None:
        self.form.omnibox.set_recents(recents)
        self.states.set_recents(recents, self.apply_recent)

    # -- helpers -----------------------------------------------------------

    def _set_state(self, state: str) -> None:
        self.results_stack.setCurrentIndex(STATES.index(state))
        self.preview_slot.setVisible(state == "table")

    def _notify(self, text: str) -> None:
        setter = getattr(self._window, "set_status", None)
        if callable(setter):
            setter(text)

    def _show_page(self, key: str) -> None:
        shower = getattr(self._window, "show_page", None)
        if callable(shower):
            shower(key)

    def _settings(self) -> QSettings:
        """The user's store; see ``actions.user_settings`` for why not ``QSettings(org, app)``."""
        return actions.user_settings()

