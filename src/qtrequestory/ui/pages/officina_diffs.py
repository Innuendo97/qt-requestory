"""The differences list of the case workbench (spec §7.2, approved drafts
"caso-fase2" v1/v2)::

    Differenze con il target
    [Da guardare 3] [Da verificare 1] [Fatte 6]
    [Tollerate 3]   [Variabili 14]    [Tutte 27]
    ┌──────────────────────────────────────────┐
    │ ○ da fare  Aa  pag. 1 · cambiato          │
    │ sarà abilitat~~a~~**o** agli acquisti     │
    │ ◐ in corso  Aa  pag. 1 · cambiato         │
    │ verrà addebitat~~o~~**e** in un'unica      │
    │ Prima «addebitati» → ora «addebitate»     │
    │ DA VERIFICARE                             │
    │ ✓? da verificare  Aa  pag. 1 · cambiato   │  (dimmed)
    └──────────────────────────────────────────┘
    ↑ ↓ scorri · Invio vai · F fatta · T tollera · V non è una variabile

What each row says is ``officina_rows``. Keyboard on the list: ↑/↓ move
(over the group header), Enter emits :attr:`DiffPanel.activated` (the case
view centres the difference in BOTH documents, even when it is on screen),
F / T / V emit :attr:`DiffPanel.action_requested` with "fatta" / "tollera" /
"non_variabile" when the action applies to the selected row (F on a row that
does not count emits ``action_unavailable``; the viewers' F / T / V come
through :meth:`DiffPanel.trigger` too). The selection is shared with the
viewers both ways: a row emits ``difference_chosen``; the case
view calls :meth:`DiffPanel.select` for a click on a highlight or on the
verdict strip, and a difference outside the current tab switches to the tab
that holds it. A refill (the same case compared again after an action) keeps
the tab and the selected difference, or — when that one changed state (just
marked, tolerated) — the row at the same place, so F, F, F walks down the list.

The AS-IS view ("cos'altro ho cambiato") has no verdicts: it keeps the phase-1
list (:meth:`show_comparison`), without tabs or keys. A ``CompareError`` is a
sentence here (:meth:`show_message`).
"""
from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QGridLayout,
    QLabel,
    QListWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import Anchor, Comparison, Judged, Profile
from qtrequestory.ui.pages.officina_docside import HEADER_HEIGHT
from qtrequestory.ui.pages.officina_difflist import DiffList, RowWidget, group_header, legend_html
from qtrequestory.ui.pages.officina_judged import count_line, difference_lines
from qtrequestory.ui.pages.officina_rows import TABS, actions_for, row_plain, tab_counts, tab_rows
from qtrequestory.ui.pages.officina_verdict_style import look_for, state_of

__all__ = ["DiffList", "DiffPanel"]  # DiffList: officina_difflist

_TAB_TEXT = {"guardare": (strings.ELENCO_TAB_GUARDARE, strings.ELENCO_TAB_GUARDARE_TIP),
             "verificare": (strings.ELENCO_TAB_VERIFICARE, strings.ELENCO_TAB_VERIFICARE_TIP),
             "fatte": (strings.ELENCO_TAB_FATTE, strings.ELENCO_TAB_FATTE_TIP),
             "tollerate": (strings.ELENCO_TAB_TOLLERATE, strings.ELENCO_TAB_TOLLERATE_TIP),
             "variabili": (strings.ELENCO_TAB_VARIABILI, strings.ELENCO_TAB_VARIABILI_TIP),
             "tutte": (strings.ELENCO_TAB_TUTTE, strings.ELENCO_TAB_TUTTE_TIP)}
TAB_COLUMNS = 3
_ID = Qt.ItemDataRole.UserRole
#: Seconds a second F is ignored on the last open row (after the refresh it would unmark).
REPEAT_GUARD_S = 1.0


class DiffPanel(QWidget):
    """The differences between the TARGET and the document on the right."""

    difference_chosen = Signal(int)          # Diff.id — the selected row
    activated = Signal(int)                  # Enter on a row: go to it
    action_requested = Signal(int, str)      # (Diff.id, "fatta" | "tollera" | "non_variabile")
    action_unavailable = Signal(int, str)    # F on a difference that does not count (U4: a toast says why)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._inactive = 0  # R30: the case's entries that match nothing (on "Tutte")
        self._held: tuple[Anchor, float] | None = None  # R42: the last F that could not move on
        title = QLabel(strings.OFFICINA_DIFF_TITLE)
        theme.set_role(title, "section")
        self.tabs = QWidget()
        grid = QGridLayout(self.tabs)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self.tab_buttons: dict[str, QToolButton] = {}
        for index, tab in enumerate(TABS):
            button = QToolButton()
            button.setCheckable(True)
            button.setProperty("diffTab", "true")
            button.setToolTip(_TAB_TEXT[tab][1])
            button.clicked.connect(lambda _c=False, t=tab: self._on_tab_clicked(t))
            self._group.addButton(button)
            grid.addWidget(button, index // TAB_COLUMNS, index % TAB_COLUMNS)
            self.tab_buttons[tab] = button
        grid.setColumnStretch(TAB_COLUMNS, 1)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.list = DiffList()
        self.list.setWordWrap(True)
        self.list.currentItemChanged.connect(self._on_current)
        self.list.enter_pressed.connect(self._on_enter)
        self.list.key_action.connect(self.trigger)
        self.legend = QLabel()
        self.legend.setWordWrap(True)
        theme.set_role(self.legend, "diffLegend")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SPACE[1], 0, 0, 0)  # air after the version info
        layout.setSpacing(theme.SPACE[1])
        title.setFixedHeight(HEADER_HEIGHT)  # the list starts where the pages start
        layout.addWidget(title)
        layout.addWidget(self.tabs)
        layout.addWidget(self.summary)
        layout.addWidget(self.list, 1)
        layout.addWidget(self.legend)
        self.setMinimumWidth(240)
        #: The judged differences on screen (None: the phase-1 list or a message).
        self._judged: list[Judged] | None = None
        self._version = 0
        self._since: dict[Anchor, int] = {}
        self._tab = "guardare"
        self._rows: list[Judged | None] = []
        self._snippets: dict[int, QLabel] = {}
        #: (judged, action) -> True when the page will refuse it (T on a row the
        #: profile tolerates): the selection then stays where it is.
        self.refuses: Callable[[Judged, str], bool] = lambda _j, _action: False
        self._set_judged_chrome(False)
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

    def show_comparison(self, comparison: Comparison, profile: Profile = "tollerante") -> None:
        """Without verdicts (AS-IS view, judge fallback): what ``profile`` counts."""
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
            item.setData(_ID, diff.id)
            item.setToolTip(what)
            self.list.addItem(item)
        self.list.setVisible(True)

    # -- phase 2 -----------------------------------------------------------------

    def show_judged(self, judged: Sequence[Judged], version: int,
                    unresolved_since: Mapping[Anchor, int], inactive: int = 0) -> None:
        """The judged differences of TO-BE ``version`` in tabs;
        ``unresolved_since``: anchor → the version a "non risolta" was marked in;
        ``inactive``: the case's entries that match nothing (on "Tutte", R30)."""
        keep = self._memory()
        self._inactive = inactive
        self._judged = list(judged)
        self._version = version
        self._since = dict(unresolved_since)
        self._set_judged_chrome(True)
        self._fill(keep)

    def set_tab(self, tab: str) -> None:
        if self._judged is None or tab not in TABS:
            return
        self._tab = tab
        self._fill(None)

    def select(self, diff_id: int) -> None:
        """Select ``diff_id`` without emitting (the viewers already focus it)."""
        if self._judged is not None and self._row_of(diff_id) is None:
            j = next((x for x in self._judged if x.diff.id == diff_id), None)
            if j is None:
                return
            self._tab = next((t for t in TABS[:-1] if j in tab_rows(t, [j])), "tutte")
            self._fill(None)
        row = self._row_of(diff_id)
        if row is not None:
            self._set_current_silently(row)

    # -- queries (tests, the case view) -----------------------------------------------

    def current_id(self) -> int | None:
        item = self.list.currentItem()
        if item is None or not item.flags() & Qt.ItemFlag.ItemIsSelectable:
            return None
        return int(item.data(_ID))

    def current_tab(self) -> str:
        return self._tab

    def tabs_visible(self) -> bool:
        return not self.tabs.isHidden()

    def tab_texts(self) -> list[str]:
        return [self.tab_buttons[t].text() for t in TABS]

    def row_ids(self) -> list[int]:
        return [j.diff.id for j in self._rows if j is not None]

    def snippet_html(self, diff_id: int) -> str:
        label = self._snippets.get(diff_id)
        return label.text() if label is not None else ""

    def texts(self) -> list[str]:
        if self._judged is None:
            return [self.list.item(r).text() for r in range(self.list.count())]
        return [row_plain(j, look_for(j).label, self._version, self._since)
                for j in self._rows if j is not None]

    # -- internals ---------------------------------------------------------------

    def _set_judged_chrome(self, on: bool) -> None:
        self.tabs.setVisible(on)
        self.legend.setVisible(on)
        if on:
            self.legend.setText(legend_html(theme.tokens()))

    def _set_summary(self, text: str, tone: str) -> None:
        self.summary.setText(text)
        self.summary.setVisible(bool(text))
        self.summary.setProperty("dot", tone or None)
        self.summary.setProperty("role", None if tone else "muted")
        theme.repolish(self.summary)

    def _clear(self) -> None:
        self.list.clear()
        self._rows = []
        self._snippets = {}

    def _memory(self) -> tuple[Anchor, str, int] | None:
        """(anchor, state, index among the rows) of the selected difference."""
        if self._judged is None:
            return None
        diff_id = self.current_id()
        j = next((x for x in self._rows if x is not None and x.diff.id == diff_id), None)
        if j is None:
            return None
        rows = self.list.selectable_rows()
        return j.diff.anchor, state_of(j), rows.index(self.list.currentRow())

    def _fill(self, keep: tuple[Anchor, str, int] | None) -> None:
        judged = self._judged or []
        counts = tab_counts(judged)
        for tab in TABS:
            self.tab_buttons[tab].setText(_TAB_TEXT[tab][0].format(n=counts[tab]))
        if k := self._inactive:  # R30: entries that match nothing now
            self.tab_buttons["tutte"].setText(strings.ELENCO_TAB_TUTTE_INACTIVE.format(n=counts["tutte"], k=k))
        self.tab_buttons["tutte"].setToolTip(_TAB_TEXT["tutte"][1] + (
            "\n" + strings.ELENCO_TAB_TUTTE_INACTIVE_TIP.format(k=k) if k else ""))
        self.tab_buttons[self._tab].setChecked(True)
        self._clear()
        self._rows = tab_rows(self._tab, judged)
        tokens = theme.tokens()
        dim = False
        for j in self._rows:
            item = QListWidgetItem()
            self.list.addItem(item)
            if j is None:
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                self.list.setItemWidget(item, group_header())
                dim = True
                continue
            item.setData(_ID, j.diff.id)
            item.setToolTip(strings.ELENCO_ROW_TIP.format(target=j.diff.left_text,
                                                          generated=j.diff.right_text))
            widget = RowWidget(j, tokens, dim=dim, version=self._version, since=self._since)
            self._snippets[j.diff.id] = widget.snippet
            self.list.setItemWidget(item, widget)
        self.list.fit_rows()
        self.list.setVisible(bool(self._rows))
        self._set_summary(self._empty_text(counts), "")
        self._restore(keep)

    def _empty_text(self, counts: dict[str, int]) -> str:
        if self._tab != "guardare":
            return "" if counts[self._tab] else strings.ELENCO_EMPTY_TAB
        if counts["guardare"]:
            return ""
        if counts["verificare"]:
            return strings.ELENCO_ONLY_MARKED.format(n=counts["verificare"])
        if counts["fatte"]:
            return (strings.ELENCO_ALL_DONE_ONE if counts["tutte"] == 1
                    else strings.ELENCO_ALL_DONE.format(n=counts["fatte"]))
        return strings.ELENCO_NOTHING_TO_LOOK

    def _restore(self, keep: tuple[Anchor, str, int] | None) -> None:
        rows = self.list.selectable_rows()
        if keep is None or not rows:
            return
        anchor, state, index = keep
        for row, j in enumerate(self._rows):
            if j is not None and j.diff.anchor == anchor and state_of(j) == state:
                self._set_current_silently(row)
                return
        open_rows = self._open_rows()  # just marked: stay among the open rows, if any
        rows = open_rows or rows
        self._set_current_silently(rows[min(index, len(rows) - 1)])

    def _open_rows(self) -> list[int]:
        """The selectable rows above the "DA VERIFICARE" header of *Da guardare*
        (every row in another tab)."""
        header = next((r for r, j in enumerate(self._rows) if j is None), len(self._rows))
        return [r for r in self.list.selectable_rows() if r < header]

    def _row_of(self, diff_id: int) -> int | None:
        return next((r for r, j in enumerate(self._rows) if j is not None and j.diff.id == diff_id),
                    None) if self._judged is not None else next(
            (r for r in range(self.list.count()) if self.list.item(r).data(_ID) == diff_id), None)

    def _set_current_silently(self, row: int) -> None:
        item = self.list.item(row)
        self.list.blockSignals(True)
        self.list.setCurrentItem(item)
        self.list.blockSignals(False)
        self.list.scrollToItem(item)

    def _current_judged(self) -> Judged | None:
        diff_id = self.current_id()
        return next((j for j in self._rows if j is not None and j.diff.id == diff_id), None)

    def _retheme(self) -> None:
        if self._judged is not None:
            self._set_judged_chrome(True)
            self._fill(self._memory())

    # -- slots ----------------------------------------------------------------------

    def _on_current(self, item: QListWidgetItem | None, _previous=None) -> None:
        if item is not None and item.flags() & Qt.ItemFlag.ItemIsSelectable:
            self.difference_chosen.emit(int(item.data(_ID)))

    def _on_tab_clicked(self, tab: str) -> None:
        """A tab chosen by the user: its first row is selected (the viewers
        follow) and the keyboard stays on the list, so ↓ / F / T / V work at once."""
        self.set_tab(tab)
        rows = self.list.selectable_rows()
        if rows:
            self.list.setCurrentRow(rows[0])
        self.list.setFocus(Qt.FocusReason.TabFocusReason)

    def advance(self) -> bool:
        """The next row of the tab becomes the selection (the viewers follow)
        — but never from the last open row of *Da guardare* into the dimmed
        "DA VERIFICARE" group (the next F there would take a mark away).
        False when the selection stayed where it was."""
        open_rows = self._open_rows()
        if open_rows and self.list.currentRow() == open_rows[-1]:
            return False
        self.list.step(1)
        return True

    def _on_enter(self) -> None:
        diff_id = self.current_id()
        if diff_id is not None:
            self.activated.emit(diff_id)

    def trigger(self, action: str) -> None:
        """F / T / V on the selected difference (from the list or a viewer):
        ``action_requested`` when it applies, then the selection moves on to
        the next row AT ONCE, before the refresh (R40: F, F, F marks three
        rows); F on one that does not count emits ``action_unavailable``
        instead (T / V there stay silent). After an F that could not move on
        (the last open row), F there is a no-op for :data:`REPEAT_GUARD_S` (R42)."""
        j = self._current_judged()
        held = self._held
        if j is None or (action == "fatta" and held is not None and held[0] == j.diff.anchor
                         and time.monotonic() - held[1] < REPEAT_GUARD_S):
            return
        self._held = None
        if action in actions_for(j):
            self.action_requested.emit(j.diff.id, action)
            if not self.refuses(j, action):  # refused: the page says why, the row stays
                if not self.advance() and action == "fatta":
                    self._held = (j.diff.anchor, time.monotonic())
        elif action == "fatta":
            self.action_unavailable.emit(j.diff.id, action)
