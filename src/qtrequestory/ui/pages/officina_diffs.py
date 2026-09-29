"""The side panel of the case workbench: the differences (spec §5, §7.2;
phase 2.5 U3: D8, D9, D15, draft "f25-caso-v2")::

    [Da guardare 4] [ Verif. 1 ] [ Fatte 0 ]
    [   Toll. 0   ] [  Var. 1  ] [ Tutte 6 ]
    (Aa) Parole 2 (▭) Zone 2 (#) Numeri 1 (+8 altri)
    ▾ Aa Parole · 2
    ○  … da Acme ~~Pay~~**Services** …            corpo · pag. 1
    ◐  … vogri lino senrica**i** pelmo …           corpo · pag. 1
         Prima «prima» → ora «senricai»            (the selected row only)
    DA VERIFICARE
    ✓? … Acme S.p.A …                              Header · pag. 1   (dimmed)
    Header ✓ · Titolo ✓ · Spalla sx 1 · Footer 1 · pag. e filigrana ignorate
    ❯  ☐ Mostra fatte                              ?

292 px, collapsible to a 40 px rail for the session (``officina_side_panel``,
``officina_diffs_groups``). Short verdict tabs that wrap rather than being
cut (their whole names are the accessible names, :meth:`DiffPanel.tab_texts`);
TYPE CHIPS counting the tab's rows per type (the marked ones too: what the
chip filters), only those with rows shown, the rest behind "+k altri",
several on at once, filtering the tab (tab × types); the list GROUPED BY
TYPE (``officina_types``: a header per type — Enter, Space or a click folds
it); each row on ONE line — the verdict's icon, the context snippet
(R33/R34), zone · page — and the in corso / non risolta / href lines only on
the selected row (fix round 1: ≥ 10 rows at 1366 × 768). ``arredo`` (page number, watermark; F3) has no verdict
and never counts: only in "Tutte", in its own group. Zones summary and «?»
(``officina_panel_legend``) at the bottom.

Keyboard on the list: ↑/↓ over the rows and the type headers (never the "DA
VERIFICARE" one), Enter emits :attr:`DiffPanel.activated` (the case view
centres the difference in BOTH documents) or folds a header, F / T / V emit
:attr:`DiffPanel.action_requested` ("fatta" / "tollera" / "non_variabile")
when the action applies (F on a row that does not count:
``action_unavailable``; the viewers' F / T / V come through
:meth:`DiffPanel.trigger`). The selection is shared with the viewers both
ways; a difference outside the tab, a folded group or the chosen types
brings its place back. Refills keep the tab and the selection
(``officina_diffs_memory``: R40 walks, F8 pinned rows).

The AS-IS view speaks the same language (U2, U3): "da fare" rows in the same
tabs and groups, read-only (nothing to judge before the changes). A
comparison that could not be judged keeps the plain list
(:meth:`show_comparison`); a ``CompareError`` is a sentence (:meth:`show_message`).
"""
from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QListWidgetItem, QVBoxLayout, QWidget

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import Anchor, Comparison, Judged, Profile
from qtrequestory.ui.pages.officina_diffs_groups import PanelGroupsMixin
from qtrequestory.ui.pages.officina_diffs_memory import SelectionMemoryMixin
from qtrequestory.ui.pages.officina_difflist import (DIFF_ID, GROUP_KEY, DiffList, RowWidget, group_header,
                                                    legend_html, type_header)
from qtrequestory.ui.pages.officina_judged import count_line, difference_lines
from qtrequestory.ui.pages.officina_panel_legend import LegendPopover
from qtrequestory.ui.pages.officina_rows import TABS, actions_for, row_plain, tab_rows
from qtrequestory.ui.pages.officina_side_panel import SESSION, PanelFooter, PanelRail, build_tabs, tool
from qtrequestory.ui.pages.officina_type_chips import TypeChips
from qtrequestory.ui.pages.officina_types import TypeGroup, grouped, is_diff, type_counts
from qtrequestory.ui.pages.officina_verdict_style import look_for

__all__ = ["DiffList", "DiffPanel"]  # DiffList: officina_difflist

#: Seconds a second F is ignored on the last open row (after the refresh it would unmark).
REPEAT_GUARD_S = 1.0


class DiffPanel(PanelGroupsMixin, SelectionMemoryMixin, QWidget):
    """The differences between the TARGET and the document on the right."""

    difference_chosen = Signal(int)          # Diff.id — the selected row
    activated = Signal(int)                  # Enter on a row: go to it
    action_requested = Signal(int, str)      # (Diff.id, "fatta" | "tollera" | "non_variabile")
    action_unavailable = Signal(int, str)    # F on a difference that does not count (U4: a toast says why)
    collapsed_changed = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sidePanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._inactive = 0  # R30: the case's entries that match nothing (on "Tutte")
        self._held: tuple[Anchor, float] | None = None  # R42: the last F that could not move on
        self._followed: tuple[int, Anchor] | None = None  # (id, anchor) kept selected by refills
        self._pinned: int | None = None  # its id when kept in a tab it left (dimmed)
        self._types: frozenset[str] = frozenset()  # the chips that are on (none = every type)
        self._folded: set[str] = set()  # the folded type groups
        self._zones: tuple = ()  # the ZoneBox es of both documents
        self._read_only = False  # the AS-IS view: nothing to judge
        self.tabs, self.tab_buttons, self._group = build_tabs(self)
        for tab, button in self.tab_buttons.items():
            button.clicked.connect(lambda _c=False, t=tab: self._on_tab_clicked(t))
        self.collapse_button = tool(strings.PANNELLO_COLLAPSE, strings.PANNELLO_COLLAPSE_NAME, glyph=True)
        self.collapse_button.clicked.connect(lambda _c=False: self.set_collapsed(True))
        self.chips = TypeChips()
        self.chips.changed.connect(self._on_types)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.list = DiffList()
        self.list.setWordWrap(True)
        self.list.currentItemChanged.connect(self._on_current)
        self.list.itemClicked.connect(self._on_item_clicked)
        self.list.enter_pressed.connect(self._on_enter)
        self.list.toggle_pressed.connect(self._toggle_current_group)
        self.list.key_action.connect(self.trigger)
        self.footer = PanelFooter()
        self.popover = LegendPopover(legend_html(theme.tokens()), self)
        self.legend = self.popover.keys  # the key legend (inside the «?» popover)
        self.footer.legend_button.clicked.connect(lambda _c=False: self.popover.open_at(self.footer.legend_button))
        self.rail = PanelRail()
        self.rail.chosen.connect(self._on_rail)
        self.body = QWidget()
        self.footer.add_tool(self.collapse_button, first=True)  # out of the tab grid (U3 fix round 1)
        head = QHBoxLayout()
        head.setContentsMargins(theme.SPACE[0], theme.SPACE[1], theme.SPACE[0], 0)
        head.addWidget(self.tabs, 1)
        box = QVBoxLayout(self.body)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        box.addLayout(head)
        box.addWidget(self.chips)
        box.addWidget(self.summary)
        box.addWidget(self.list, 1)
        box.addWidget(self.footer)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self.body)
        outer.addWidget(self.rail)
        #: The judged differences on screen (None: the phase-1 list or a message).
        self._judged: list[Judged] | None = None
        self._version = 0
        self._since: dict[Anchor, int] = {}
        self._tab = "guardare"
        self._rows: list[Judged | TypeGroup | None] = []
        self._snippets: dict[int, QLabel] = {}
        #: (judged, action) -> True when the page will refuse it (T on a row the
        #: profile tolerates): the selection then stays where it is.
        self.refuses: Callable[[Judged, str], bool] = lambda _j, _action: False
        self._set_judged_chrome(False)
        self.set_collapsed(SESSION["collapsed"])
        theme.signals.changed.connect(self._retheme)

    # -- phase 1 / messages ----------------------------------------------------

    def show_message(self, text: str, tone: str = "") -> None:
        """A sentence instead of the list (no comparison, or it failed);
        ``tone`` "ok" / "warn" / "bad" colours it, "" leaves it muted."""
        self._judged = None
        self._tab = "guardare"
        self._clear()
        self._set_judged_chrome(False)
        self.list.setVisible(False)
        self._set_summary(text, tone)
        self._update_zones()

    def show_comparison(self, comparison: Comparison, profile: Profile = "tollerante") -> None:
        """Without verdicts (a comparison that could not be judged): what ``profile`` counts."""
        diffs = comparison.counting(profile)
        if comparison.equal_for(profile):
            self.show_message(strings.OFFICINA_DIFF_EQUAL, "ok")
            return
        if not diffs:
            self.show_message(comparison.note or strings.OFFICINA_DIFF_EQUAL, "warn")
            return
        self._judged = None
        self._clear()
        self._set_judged_chrome(False)
        self._set_summary(count_line(diffs), "warn")
        for diff in diffs:
            where, what = difference_lines(diff)
            item = QListWidgetItem(f"{where}\n{what}")
            item.setData(DIFF_ID, diff.id)
            item.setToolTip(what)
            self.list.addItem(item)
        self.list.setVisible(True)
        self._update_zones()

    # -- phase 2 -----------------------------------------------------------------

    def show_judged(self, judged: Sequence[Judged], version: int,
                    unresolved_since: Mapping[Anchor, int], inactive: int = 0, *,
                    read_only: bool = False) -> None:
        """The judged differences of TO-BE ``version`` in tabs and type groups;
        ``unresolved_since``: anchor → the version a "non risolta" was marked in;
        ``inactive``: the case's entries that match nothing (on "Tutte", R30);
        ``read_only``: the AS-IS view (F / T / V do nothing)."""
        keep = self._memory()
        self._inactive = inactive
        self._judged = list(judged)
        self._version = version
        self._since = dict(unresolved_since)
        self._read_only = read_only
        self._set_judged_chrome(True)
        self._fill(keep)

    def set_tab(self, tab: str) -> None:
        if self._judged is None or tab not in TABS:
            return
        self._tab = tab
        self._followed = None  # a tab change ends the pin
        self._fill(None)

    def select(self, diff_id: int) -> None:
        """Select ``diff_id`` without emitting (the viewers already focus it)."""
        if self._pinned is not None and diff_id != self._pinned:  # something else: unpin
            self._followed = None
            self._fill(None)
        if self._judged is not None and self._row_of(diff_id) is None:
            j = next((x for x in self._judged if x.diff.id == diff_id), None)
            if j is None:
                return
            self._tab = next((t for t in TABS[:-1] if j in tab_rows(t, [j])), "tutte")
            self._reveal(j)
            self._fill(None)
        row = self._row_of(diff_id)
        if row is not None:
            self._set_current_silently(row)

    # -- queries (tests, the case view) -----------------------------------------------

    def current_id(self) -> int | None:
        item = self.list.currentItem()
        if item is None or not item.flags() & Qt.ItemFlag.ItemIsSelectable or item.data(DIFF_ID) is None:
            return None
        return int(item.data(DIFF_ID))

    def current_tab(self) -> str:
        return self._tab

    def tabs_visible(self) -> bool:
        return not self.tabs.isHidden()

    def tab_texts(self) -> list[str]:
        """The tabs' whole names with their counts ("Da verificare 1"): their accessible names."""
        return [self.tab_buttons[t].accessibleName() for t in TABS]

    def tab_labels(self) -> list[str]:
        """What the tabs show (short: "Verif. 1")."""
        return [self.tab_buttons[t].text() for t in TABS]

    def list_row(self, diff_id: int) -> int | None:
        """The list row of ``diff_id`` (the type headers are rows too), or None."""
        return self._row_of(diff_id)

    def row_ids(self) -> list[int]:
        return [j.diff.id for j in self._rows if is_diff(j)]

    def snippet_html(self, diff_id: int) -> str:
        label = self._snippets.get(diff_id)
        return label.text() if label is not None else ""

    def texts(self) -> list[str]:
        if self._judged is None:
            return [self.list.item(r).text() for r in range(self.list.count())]
        return [row_plain(j, look_for(j).label, self._version, self._since)
                for j in self._rows if is_diff(j)]

    # -- internals ---------------------------------------------------------------

    def _set_judged_chrome(self, on: bool) -> None:
        self.tabs.setVisible(on)
        self.chips.setVisible(on)
        self.legend.setText(legend_html(theme.tokens()))

    def _set_summary(self, text: str, tone: str) -> None:
        self.summary.setText(text)
        self.summary.setVisible(bool(text))
        self.summary.setProperty("dot", tone or None)
        self.summary.setProperty("role", None if tone else "muted")
        theme.repolish(self.summary)

    def _clear(self) -> None:
        self.list.blockSignals(True)  # clear() walks the current row over the rows it removes:
        self.list.clear()             # no "chosen" (the viewers would jump there)
        self.list.blockSignals(False)
        self._rows = []
        self._snippets = {}

    def _fill(self, keep: tuple[Anchor, str, int] | None) -> None:
        judged = self._judged or []
        counts = self._set_tab_texts(judged)
        in_tab = tab_rows(self._tab, judged)
        self.chips.set_counts(type_counts(in_tab))  # every row the chips filter, marked ones too (M3)
        self._clear()
        self._rows = self._with_pin(grouped(in_tab, self._types, self._folded), judged, keep)
        tokens = theme.tokens()
        dim = False
        for entry in self._rows:
            item = QListWidgetItem()
            self.list.addItem(item)
            if entry is None:
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                self.list.setItemWidget(item, group_header())
                dim = True
                continue
            if isinstance(entry, TypeGroup):
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                item.setData(GROUP_KEY, entry.tipo)
                self.list.setItemWidget(item, type_header(entry))
                continue
            item.setData(DIFF_ID, entry.diff.id)
            widget = RowWidget(entry, tokens, dim=dim or entry.diff.id == self._pinned,
                               version=self._version, since=self._since)
            item.setToolTip("\n".join([strings.ELENCO_ROW_TIP.format(
                target=entry.diff.left_text, generated=entry.diff.right_text), *widget.notes]))
            self._snippets[entry.diff.id] = widget.snippet
            self.list.setItemWidget(item, widget)
        self.list.fit_rows()
        self.list.setVisible(True)  # even empty: it keeps the keyboard (F / T / Ctrl+Z) when a tab empties
        self._set_summary(self._empty_text(counts, bool(in_tab)), "")
        self._restore(keep)
        self.list.expand_current()
        self._update_zones()

    def _row_of(self, diff_id: int) -> int | None:
        if self._judged is not None:
            return next((r for r, j in enumerate(self._rows) if is_diff(j) and j.diff.id == diff_id), None)
        return next((r for r in range(self.list.count()) if self.list.item(r).data(DIFF_ID) == diff_id), None)

    def _set_current_silently(self, row: int) -> None:
        item = self.list.item(row)
        self.list.blockSignals(True)
        self.list.setCurrentItem(item)
        self.list.blockSignals(False)
        self.list.expand_current()
        self.list.scrollToItem(item)

    def _current_judged(self) -> Judged | None:
        diff_id = self.current_id()
        return next((j for j in self._rows if is_diff(j) and j.diff.id == diff_id), None)

    def _retheme(self) -> None:
        self.legend.setText(legend_html(theme.tokens()))
        if self._judged is not None:
            self._fill(self._memory())

    # -- slots ----------------------------------------------------------------------

    def _on_current(self, item: QListWidgetItem | None, _previous=None) -> None:
        self.list.expand_current()  # the secondary line follows the selection
        if item is not None and item.flags() & Qt.ItemFlag.ItemIsSelectable and item.data(DIFF_ID) is not None:
            self._followed = None  # the user moved on (arrows, a click, F in the list)
            if self._pinned is not None and int(item.data(DIFF_ID)) != self._pinned:
                QTimer.singleShot(0, self._unpin)  # not while the list is changing its row
            self.difference_chosen.emit(int(item.data(DIFF_ID)))

    def _on_tab_clicked(self, tab: str) -> None:
        """A tab chosen by the user: its first row is selected (the viewers
        follow) and the keyboard stays on the list, so ↓ / F / T / V work at once."""
        self.set_tab(tab)
        rows = self.list.selectable_rows()
        if rows:
            self.list.setCurrentRow(rows[0])
        self.list.setFocus(Qt.FocusReason.TabFocusReason)

    def _on_enter(self) -> None:
        if self._current_group():
            self._toggle_current_group()
            return
        diff_id = self.current_id()
        if diff_id is not None:
            self.activated.emit(diff_id)

    def trigger(self, action: str, *, advance: bool = True) -> None:
        """F / T / V on the selected difference: ``action_requested`` when it
        applies, then — from the list — the selection moves on to the next
        row AT ONCE, before the refresh (R40: F, F, F marks three rows); from
        a viewer (``advance=False``) it stays and follows the difference
        (spec §4.2). F on one that does not count emits ``action_unavailable``
        (T / V there stay silent). After an F that did not move on, F there is
        a no-op for :data:`REPEAT_GUARD_S` (R42). Nothing in the AS-IS view."""
        j = self._current_judged()
        held = self._held
        if self._read_only or j is None or (
                action == "fatta" and held is not None and held[0] == j.diff.anchor
                and time.monotonic() - held[1] < REPEAT_GUARD_S):
            return
        self._held = None
        if action in actions_for(j):
            if not advance:
                self.follow_current()
            self.action_requested.emit(j.diff.id, action)
            if not self.refuses(j, action):  # refused: the page says why, the row stays
                if not (advance and self.advance()) and action == "fatta":
                    self._held = (j.diff.anchor, time.monotonic())
        elif action == "fatta":
            self.action_unavailable.emit(j.diff.id, action)
