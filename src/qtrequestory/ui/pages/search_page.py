"""The Ricerca page: filter bar, results table, preview slot.

Layout (DESIGN-ui §"Ricerca page"): a horizontal splitter whose left half holds
the form, the coverage line, the stale-index banner, the summary line and the
results table, and whose right half is a *slot* — the preview pane is a separate
widget that the shell installs with :meth:`SearchPage.set_preview_widget`. Until
one is installed the slot shows a placeholder and the three body actions of the
context menu are disabled, so the page is complete on its own.

What the page owns:

* the query (built from the form, never from the core's internals),
* the table's states — rows, "nessun log per questo ambiente", "nessuna
  chiamata trovata" — swapped in a ``QStackedLayout`` rather than by hiding
  widgets, so exactly one of them can ever be on screen,
* the row actions, three of which it delegates to the preview pane because the
  pane is what holds the body.

What it does NOT own: the search itself. :class:`SearchPresenter` submits every
core call to the :class:`~qtrequestory.ui.workers.JobRunner` under the name
``"search"``, which supersedes: a slow first query is silenced the moment a
second one starts, so this page needs no request ids of its own.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date
from functools import partial

from PySide6.QtCore import QEvent, QObject, QSettings, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedLayout,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import actions, strings
from qtrequestory.ui.contracts import Coverage, CoreServices, SearchHit, SearchQuery
from qtrequestory.ui.pages.search_form import FULL_FDI_LEN, SearchForm
from qtrequestory.ui.results_model import ElideMiddleDelegate, ResultsModel, ResultsProxy, format_day
from qtrequestory.ui.workers import JobRunner

log = logging.getLogger(__name__)

__all__ = ["SearchPage", "SearchPresenter"]

#: A selection settles before the preview is asked for a body (DESIGN-ui).
SELECTION_DEBOUNCE_MS = 150
#: The window the "nessun risultato" state offers to widen to.
WIDE_WINDOW_DAYS = 90
#: ``QSettings`` key of the last used environment.
ENV_SETTING = "search/env"
#: The three pages of the results stack.
STATE_TABLE, STATE_NO_LOG, STATE_NO_RESULTS = 0, 1, 2
_STATE_NAMES = {STATE_TABLE: "table", STATE_NO_LOG: "no_log", STATE_NO_RESULTS: "no_results"}


def summary_text(hits: Sequence[SearchHit]) -> str:
    """"12 chiamate · 1 FDI · 4 giorni · ordinate dalla più recente"."""
    return strings.SEARCH_SUMMARY.format(
        calls=_count(len(hits), strings.SEARCH_SUMMARY_CALLS_ONE, strings.SEARCH_SUMMARY_CALLS_MANY),
        fdis=_count(len({h.fdi for h in hits}), strings.SEARCH_SUMMARY_FDIS_ONE,
                    strings.SEARCH_SUMMARY_FDIS_MANY),
        days=_count(len({h.day for h in hits}), strings.SEARCH_SUMMARY_DAYS_ONE,
                    strings.SEARCH_SUMMARY_DAYS_MANY),
    )


def _count(n: int, one: str, many: str) -> str:
    return one if n == 1 else many.format(n=n)


# ------------------------------------------------------------ empty state ---

class EmptyState(QWidget):
    """Centred title + hints + one optional button (never a modal)."""

    def __init__(self, button_text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.title = QLabel()
        self.hint = QLabel()
        self.button = QPushButton(button_text)
        self.button.setVisible(bool(button_text))
        layout = QVBoxLayout(self)
        layout.addStretch(1)
        for widget in (self.title, self.hint):
            widget.setWordWrap(True)
            widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(widget)
        layout.addSpacing(8)
        layout.addWidget(self.button, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addStretch(1)

    def set_text(self, title: str, hints: Sequence[str] = ()) -> None:
        self.title.setText(title)
        self.hint.setText("\n".join(hints))

    def text(self) -> str:
        """Everything the state says, for tests and for accessibility tools."""
        return f"{self.title.text()}\n{self.hint.text()}"


# --------------------------------------------------------------- presenter ---

class SearchPresenter(QObject):
    """Every core call the page makes, off the GUI thread, plus the debounce.

    A plain object with signals (DESIGN-ui §Testability): it holds the last
    result set and knows nothing about widgets, so the page stays a renderer.
    """

    results_ready = Signal(list)
    selection_changed = Signal(object)  # SearchHit or None
    status = Signal(str)
    template_keys_ready = Signal(list)
    index_pending = Signal(int)

    def __init__(self, services: CoreServices, runner: JobRunner,
                 parent: QObject | None = None,
                 debounce_ms: int = SELECTION_DEBOUNCE_MS) -> None:
        super().__init__(parent)
        self._services = services
        self._runner = runner
        self._hits: list[SearchHit] = []
        self._selected: SearchHit | None = None
        # A restartable single-shot timer, not a chain of QTimer.singleShot:
        # dragging the cursor down the table must produce ONE preview request,
        # not one per row passed over.
        self.selection_timer = QTimer(self)
        self.selection_timer.setSingleShot(True)
        self.selection_timer.setInterval(debounce_ms)
        self.selection_timer.timeout.connect(self._emit_selection)

    # -- synchronous, cheap ------------------------------------------------

    def environments(self) -> list[str]:
        return [env.name for env in self._services.config.load().enabled_environments()]

    def default_window_days(self) -> int:
        return self._services.config.load().default_window_days

    def coverage(self, env: str) -> Coverage | None:
        """One indexed aggregate over ``files``; cheap enough for the GUI thread."""
        try:
            return self._services.index.coverage(env)
        except Exception:  # noqa: BLE001 - a missing index must not break the page
            log.exception("coverage di %s non disponibile", env)
            return None

    def hits(self) -> list[SearchHit]:
        return list(self._hits)

    # -- jobs --------------------------------------------------------------

    def search(self, query: SearchQuery) -> None:
        self.status.emit(strings.SEARCH_RUNNING)
        job = self._runner.submit("search", self._services.index.search, query)
        if job is None:  # shutting down
            return
        job.signals.result.connect(self._on_hits)
        job.signals.error.connect(self._on_error)

    def reload_template_keys(self, env: str) -> None:
        job = self._runner.submit("search_keys", self._services.index.list_template_keys, env)
        if job is not None:
            job.signals.result.connect(lambda keys: self.template_keys_ready.emit(list(keys)))

    def refresh_index_state(self, env: str) -> None:
        """How many local files the index has not scanned yet (stale banner)."""
        job = self._runner.submit("search_plan", self._services.index.plan, [env])
        if job is not None:
            job.signals.result.connect(lambda plan: self.index_pending.emit(len(plan.to_scan)))

    # -- selection ---------------------------------------------------------

    def select(self, hit: SearchHit | None) -> None:
        self._selected = hit
        self.selection_timer.start()

    def _emit_selection(self) -> None:
        self.selection_changed.emit(self._selected)

    def _on_hits(self, hits: list[SearchHit]) -> None:
        self._hits = list(hits)
        self.results_ready.emit(self._hits)

    def _on_error(self, _kind: str, message: str) -> None:
        self.status.emit(strings.SEARCH_FAILED.format(error=message))


# -------------------------------------------------------------------- page ---

class SearchPage(QWidget):
    """Form + table + preview slot; the application's default page."""

    def __init__(self, services: CoreServices, runner: JobRunner, window: object | None = None,
                 parent: QWidget | None = None) -> None:
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
        self.form = SearchForm()
        self.model = ResultsModel(self)
        self.proxy = ResultsProxy(self)
        self.proxy.setSourceModel(self.model)
        self.table = QTableView()
        self.coverage_label = QLabel()
        self.stale_banner = QLabel()
        self.summary_label = QLabel()
        self.empty_no_log = EmptyState(strings.SEARCH_EMPTY_NO_LOG_BTN)
        self.empty_no_results = EmptyState(strings.SEARCH_EMPTY_WIDEN_BTN)
        self.preview_placeholder = QLabel(strings.SEARCH_PREVIEW_PLACEHOLDER)

        self._build()
        self._connect()
        self._load_config()

    # -- construction ------------------------------------------------------

    def _build(self) -> None:
        self._build_table()
        self.stale_banner.setVisible(False)
        self.stale_banner.setWordWrap(True)
        self.coverage_label.setWordWrap(True)

        self.results_stack = QStackedLayout()
        self.results_stack.addWidget(self.table)          # STATE_TABLE
        self.results_stack.addWidget(self.empty_no_log)   # STATE_NO_LOG
        self.results_stack.addWidget(self.empty_no_results)  # STATE_NO_RESULTS
        results = QWidget()
        results.setLayout(self.results_stack)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        for widget in (self.form, self.coverage_label, self.stale_banner, self.summary_label):
            left_layout.addWidget(widget)
        left_layout.addWidget(results, 1)

        self.preview_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_placeholder.setWordWrap(True)
        preview_slot = QWidget()
        self._preview_layout = QVBoxLayout(preview_slot)
        self._preview_layout.setContentsMargins(0, 0, 0, 0)
        self._preview_layout.addWidget(self.preview_placeholder)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(left)
        self.splitter.addWidget(preview_slot)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        outer = QVBoxLayout(self)
        outer.addWidget(self.splitter)

    def _build_table(self) -> None:
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setVisible(False)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.table.setSortingEnabled(True)
        # ...but sorted by NOTHING to start with, so the rows keep the order the
        # core delivered them in (most recent first) until a header is clicked.
        self.table.sortByColumn(-1, Qt.SortOrder.AscendingOrder)
        self.table.setItemDelegateForColumn(ResultsModel.COL_KEY, ElideMiddleDelegate(self))
        for column in ResultsModel.HIDDEN_COLUMNS:
            self.table.setColumnHidden(column, True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(ResultsModel.COL_KEY, QHeaderView.ResizeMode.Stretch)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.installEventFilter(self)

    def _connect(self) -> None:
        self.form.search_requested.connect(self.run_search)
        self.form.env_changed.connect(self._on_env_changed)
        self.presenter.results_ready.connect(self._on_results)
        self.presenter.status.connect(self._notify)
        self.presenter.selection_changed.connect(self._deliver)
        self.presenter.template_keys_ready.connect(self.form.set_template_keys)
        self.presenter.index_pending.connect(self._on_index_pending)
        self.table.doubleClicked.connect(lambda _index: self._open_selected())
        self.table.customContextMenuRequested.connect(self._on_context_menu)
        self.table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self.empty_no_log.button.clicked.connect(lambda: self._show_page("sync"))
        self.empty_no_results.button.clicked.connect(self._widen_window)
        for sequence, slot in (("F5", self.run_search), ("Ctrl+L", self.form.focus_fdi),
                               ("Ctrl+K", self.form.focus_key)):
            self.shortcuts[sequence] = _shortcut(self, sequence, slot)

    def _load_config(self) -> None:
        """Environments, remembered choice and default period, then the env load."""
        envs = self.presenter.environments()
        remembered = self._settings().value(ENV_SETTING)
        current = remembered if remembered in envs else (envs[0] if envs else "")
        self.form.set_environments(envs, current)
        self.form.set_preset(self.presenter.default_window_days())
        if current:
            self._on_env_changed(current)

    def on_config_changed(self, _cfg: object) -> None:
        """Impostazioni was saved: environments and default period may have moved."""
        self._load_config()

    # -- public API --------------------------------------------------------

    def set_preview_widget(self, widget: QWidget | None) -> None:
        """Install (or remove) the preview pane in the right half of the splitter.

        The pane is a separate deliverable, so the page must work without one:
        passing None puts the placeholder back and disables the body actions.
        """
        if self._preview is not None:
            self._preview_layout.removeWidget(self._preview)
            self._preview.setParent(None)
        self._preview = widget
        self.preview_placeholder.setVisible(widget is None)
        if widget is not None:
            self._preview_layout.addWidget(widget)
            widget.setVisible(True)
            self._deliver(self.selected_hit())  # a pane installed late is not empty

    def preview_widget(self) -> QWidget | None:
        return self._preview

    def selected_hit(self) -> SearchHit | None:
        rows = self.table.selectionModel().selectedRows()
        return rows[0].data(ResultsModel.HIT_ROLE) if rows else None

    def selected_entries(self) -> list[SearchHit]:
        """DESIGN-ui §Navigation: what a future page would act on."""
        hit = self.selected_hit()
        return [hit] if hit is not None else []

    def current_state(self) -> str:
        return _STATE_NAMES[self.results_stack.currentIndex()]

    def run_search(self) -> None:
        """Build the query from the form and submit it (F5, Enter, [Cerca])."""
        env = self.form.current_env()
        if not env or not self.form.can_search():
            return
        day_from, day_to = self.form.day_range()
        self._query = SearchQuery(
            env=env,
            fdi_prefix=self.form.fdi().lower() or None,
            template_key=self.form.template_key().upper() or None,
            day_from=day_from,
            day_to=day_to,
        )
        self.presenter.search(self._query)

    def build_context_menu(self, hit: SearchHit) -> QMenu:
        """The row menu, built without showing it (so it can be tested)."""
        menu = QMenu(self)
        for label, method in ((strings.SEARCH_MENU_OPEN, "open_in_editor"),
                              (strings.BTN_SAVE_AS, "save_as"),
                              (strings.SEARCH_MENU_COPY_JSON, "copy_body")):
            action = menu.addAction(label)
            action.setEnabled(self._preview is not None)
            if self._preview is None:
                action.setToolTip(strings.SEARCH_NO_PREVIEW_TOOLTIP)
            action.triggered.connect(partial(self._delegate, method))
        menu.addSeparator()
        _add(menu, strings.SEARCH_MENU_COPY_FDI, partial(self._copy, hit.fdi,
             strings.SEARCH_STATUS_COPIED_FDI), enabled=bool(hit.fdi))
        _add(menu, strings.SEARCH_MENU_COPY_KEY, partial(self._copy, hit.template_key,
             strings.SEARCH_STATUS_COPIED_KEY))
        _add(menu, strings.SEARCH_MENU_ONLY_FDI, partial(self._search_only, hit.fdi, None),
             enabled=bool(hit.fdi))
        _add(menu, strings.SEARCH_MENU_ONLY_KEY, partial(self._search_only, None,
             hit.template_key))
        menu.addSeparator()
        _add(menu, strings.SEARCH_MENU_OPEN_DAY_FOLDER, partial(self._open_day_folder, hit))
        for extra in self.context_menu_actions:
            menu.addAction(extra)
        return menu

    # -- reactions ---------------------------------------------------------

    def _on_results(self, hits: list[SearchHit]) -> None:
        self.model.set_hits(hits)
        if hits:
            self.summary_label.setText(summary_text(hits))
            self._set_state(STATE_TABLE)
            self.table.selectRow(0)  # the newest call is what people want first
        else:
            self.summary_label.setText("")
            self._show_no_results()
        # Explicit: a model reset does not always emit selectionChanged, and the
        # pane must be told that there is nothing to show.
        self.presenter.select(self.selected_hit())

    def _on_selection_changed(self, _selected=None, _deselected=None) -> None:
        self.presenter.select(self.selected_hit())

    def _deliver(self, hit: SearchHit | None) -> None:
        """Hand the settled selection to the preview pane, if one is installed."""
        setter = getattr(self._preview, "set_hit", None)
        if callable(setter):
            setter(hit)

    def _on_env_changed(self, env: str) -> None:
        # Rows found in the PREVIOUS environment must go: keeping them while the
        # coverage line already names the new one would be a lie. A reload that
        # does not actually change the environment (Impostazioni was saved) keeps
        # them, because there the user did not ask to look somewhere else.
        if env != self._env:
            self._clear_results()
        self._env = env
        self._settings().setValue(ENV_SETTING, env)
        self.presenter.reload_template_keys(env)
        self.presenter.refresh_index_state(env)
        self._update_coverage(env)

    def _clear_results(self) -> None:
        """Drop the rows AND any empty state describing the search that made them.

        "Nessuna chiamata trovata" is about a query that ran against the
        previous environment; leaving it up while switching to one that does
        have logs claims there is nothing there before anything was searched.
        The caller (``_on_env_changed``) then asks ``_update_coverage`` to put
        the "no log" state back if this environment really has none.
        """
        self.model.set_hits([])
        self.summary_label.setText("")
        self._query = None
        self._set_state(STATE_TABLE)
        self.presenter.select(None)

    def _on_index_pending(self, pending: int) -> None:
        """Just display: the shell is what triggers the index job."""
        self.stale_banner.setText(strings.SEARCH_STALE_BANNER.format(n=pending))
        self.stale_banner.setVisible(pending > 0)

    def _update_coverage(self, env: str) -> None:
        coverage = self.presenter.coverage(env)
        if coverage is None:
            self.coverage_label.setText(strings.SEARCH_COVERAGE_NONE.format(env=env))
            self.empty_no_log.set_text(strings.SEARCH_EMPTY_NO_LOG_TITLE.format(env=env),
                                       [strings.SEARCH_EMPTY_NO_LOG_HINT])
            self._set_state(STATE_NO_LOG)
            return
        self.coverage_label.setText(strings.SEARCH_COVERAGE.format(
            env=env, first=format_day(coverage.first_day), last=format_day(coverage.last_day)))
        if self.results_stack.currentIndex() == STATE_NO_LOG:
            self._set_state(STATE_TABLE)  # this environment has logs after all

    def _show_no_results(self) -> None:
        """The hints describe the query that just ran, not the form as it is now."""
        today = date.today()
        query = self._query
        day_from = query.day_from if query and query.day_from else today
        day_to = query.day_to if query and query.day_to else today
        fdi = (query.fdi_prefix or "") if query else ""
        hints = [strings.SEARCH_EMPTY_NO_RESULTS_HINT]
        if day_to == today:
            hints.append(strings.SEARCH_EMPTY_HINT_TODAY.format(file=f"{day_to:%Y%m%d}.txt"))
        if 0 < len(fdi) < FULL_FDI_LEN:
            hints.append(strings.SEARCH_EMPTY_HINT_SHORT_FDI)
        self.empty_no_results.set_text(strings.SEARCH_EMPTY_NO_RESULTS_TITLE, hints)
        self.empty_no_results.button.setVisible((day_to - day_from).days + 1 < WIDE_WINDOW_DAYS)
        self._set_state(STATE_NO_RESULTS)

    def _widen_window(self) -> None:
        self.form.set_preset(WIDE_WINDOW_DAYS)
        self.run_search()

    def _on_context_menu(self, pos) -> None:
        index = self.table.indexAt(pos)
        if not index.isValid():
            return
        self.table.selectRow(index.row())
        menu = self.build_context_menu(index.data(ResultsModel.HIT_ROLE))
        menu.exec(self.table.viewport().mapToGlobal(pos))
        menu.deleteLater()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt naming
        """Enter on a row opens it, exactly like a double click."""
        if (obj is self.table and event.type() == QEvent.Type.KeyPress
                and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)):
            self._open_selected()
            return True
        return super().eventFilter(obj, event)

    # -- row actions -------------------------------------------------------

    def _open_selected(self) -> None:
        self._delegate("open_in_editor")

    def _delegate(self, method: str, *_args) -> None:
        """Apri / Salva / Copia JSON belong to whoever holds the body."""
        action = getattr(self._preview, method, None)
        if callable(action):
            action()
        else:
            self._notify(strings.SEARCH_NO_PREVIEW_TOOLTIP)

    def _copy(self, text: str | None, message: str, *_args) -> None:
        QGuiApplication.clipboard().setText(text or "")
        self._notify(message)

    def _search_only(self, fdi: str | None, key: str | None, *_args) -> None:
        self.form.set_fdi(fdi or "")
        self.form.set_template_key(key or "")
        self.run_search()

    def _open_day_folder(self, hit: SearchHit, *_args) -> None:
        self.services.extract.open_folder(hit.file_path.parent)

    # -- helpers -----------------------------------------------------------

    def _set_state(self, state: int) -> None:
        self.results_stack.setCurrentIndex(state)

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


def _add(menu: QMenu, label: str, slot, *, enabled: bool = True) -> QAction:
    action = menu.addAction(label)
    action.setEnabled(enabled)
    action.triggered.connect(slot)
    return action


def _shortcut(parent: QWidget, sequence: str, slot) -> QShortcut:
    """A shortcut that only fires while this page (or a child) has the focus."""
    shortcut = QShortcut(QKeySequence(sequence), parent)
    shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
    shortcut.activated.connect(slot)
    return shortcut
