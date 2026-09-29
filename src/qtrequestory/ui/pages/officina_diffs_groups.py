"""The side panel's tab texts and empty-tab wording, type groups, type
chips, zones summary and open / collapsed state (a mixin of ``officina_diffs.DiffPanel``, split for size;
spec §5, D8, D15). What the groups and the summary say is
``officina_types``; the widgets are ``officina_side_panel`` and
``officina_type_chips``.
"""
from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidgetItem

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import Judged
from qtrequestory.ui.pages.officina_difflist import GROUP_KEY
from qtrequestory.ui.pages.officina_rows import TABS, tab_counts, tab_rows
from qtrequestory.ui.pages.officina_side_panel import OPEN_WIDTH, RAIL_WIDTH, SESSION, TAB_TEXT
from qtrequestory.ui.pages.officina_types import (
    ARREDO_GROUP,
    TYPES,
    TypeGroup,
    is_arredo,
    is_diff,
    type_counts,
    zones_summary,
)

__all__ = ["PanelGroupsMixin"]

#: The tabs' whole names (their accessible names; the buttons show the short ones).
_FULL = {"guardare": strings.ELENCO_TAB_GUARDARE, "verificare": strings.ELENCO_TAB_VERIFICARE,
         "fatte": strings.ELENCO_TAB_FATTE, "tollerate": strings.ELENCO_TAB_TOLLERATE,
         "variabili": strings.ELENCO_TAB_VARIABILI, "tutte": strings.ELENCO_TAB_TUTTE}


class PanelGroupsMixin:
    """Needs from the panel: ``list``, ``chips``, ``footer``, ``rail``,
    ``body``, ``popover``, ``collapse_button``, ``_rows``, ``_judged``,
    ``_types``, ``_folded``, ``_zones``, ``_fill``, ``_memory``,
    ``_on_tab_clicked``, ``_set_current_silently``, ``current_id`` and the
    ``collapsed_changed`` signal."""

    # -- open / collapsed --------------------------------------------------------------

    def set_collapsed(self, on: bool) -> None:
        """The 40 px rail (``on``) or the 292 px panel; remembered for the session."""
        had_focus = self.body.isAncestorOf(self.focusWidget()) if self.focusWidget() else False
        SESSION["collapsed"] = self._collapsed = on
        self.body.setVisible(not on)
        self.rail.setVisible(on)
        self.setFixedWidth(RAIL_WIDTH if on else OPEN_WIDTH)
        if on and had_focus:
            self.rail.buttons["open"].setFocus(Qt.FocusReason.OtherFocusReason)
        self.collapsed_changed.emit(on)

    def is_collapsed(self) -> bool:
        return self._collapsed

    def _on_rail(self, what: str) -> None:
        if what == "legend":
            self.popover.open_at(self.rail.buttons["legend"])
            return
        self.set_collapsed(False)
        if what == "guardare" and self._judged is not None:
            self._on_tab_clicked("guardare")
        elif what == "types":
            shown = [c for c in self.chips.chips.values() if not c.isHidden()] or [self.chips.more]
            shown[0].setFocus(Qt.FocusReason.TabFocusReason)
        elif what == "zones":
            self.footer.legend_button.setFocus(Qt.FocusReason.TabFocusReason)
        else:
            self.collapse_button.setFocus(Qt.FocusReason.TabFocusReason)

    # -- groups, chips, zones ---------------------------------------------------------------

    def _current_group(self) -> str | None:
        item = self.list.currentItem()
        return item.data(GROUP_KEY) if item is not None else None

    def toggle_group(self, key: str) -> None:
        """Fold / unfold the type group ``key``; its header stays the current row."""
        self._folded.symmetric_difference_update({key})
        self._fill(self._memory())
        row = next((r for r, g in enumerate(self._rows) if isinstance(g, TypeGroup) and g.tipo == key), None)
        if row is not None and self.current_id() is None:
            self._set_current_silently(row)

    def _toggle_current_group(self) -> None:
        key = self._current_group()
        if key:
            self.toggle_group(key)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        key = item.data(GROUP_KEY)
        if key:
            self.toggle_group(key)

    def _on_types(self, types: frozenset) -> None:
        self._types = frozenset(types)
        if self._judged is not None:
            self._fill(self._memory())

    def _update_zones(self) -> None:
        text, known = zones_summary(self._judged or [], self._zones)
        self.footer.zones.setText(text)
        self.footer.zones.setVisible(known)
        judged = self._judged or []
        in_tab = tab_rows("guardare", judged)
        cut = next((i for i, j in enumerate(in_tab) if j is None), len(in_tab))
        counts = type_counts(judged)
        types_tip = " · ".join(f"{TYPES[t].name} {n}" for t, n in counts.items() if n)
        self.rail.set_state(cut, types_tip, text if known else "")

    def _reveal(self, j: Judged) -> None:
        """Unfold ``j``'s group and drop the type chips that would hide it."""
        key = ARREDO_GROUP if is_arredo(j) else (j.diff.tipo if j.diff.tipo in TYPES else "altro")
        self._folded.discard(key)
        if self._types and (is_arredo(j) or key not in self._types):
            self._types = frozenset()
            self.chips.set_selected(frozenset(), emit=False)

    def set_zones(self, zones: Sequence[object]) -> None:
        """The zone boxes of both documents, for the zones summary."""
        self._zones = tuple(zones)
        self._update_zones()

    def set_types(self, types: set[str] | frozenset[str]) -> None:
        """Turn exactly these type chips on (the list follows)."""
        self.chips.set_selected(frozenset(types))

    def groups(self) -> list[TypeGroup]:
        return [g for g in self._rows if isinstance(g, TypeGroup)]

    def zones_text(self) -> str:
        return self.footer.zones.text() if not self.footer.zones.isHidden() else ""

    # -- tab texts ---------------------------------------------------------------------

    def _set_tab_texts(self, judged: list[Judged]) -> dict[str, int]:
        counts = tab_counts(judged)
        arredo = sum(1 for j in judged if is_arredo(j))
        counts["tutte"] -= arredo  # never counted (F3)
        for tab in TABS:
            short, tip = TAB_TEXT[tab]
            button = self.tab_buttons[tab]
            button.setText(short.format(n=counts[tab]))
            button.setAccessibleName(_FULL[tab].format(n=counts[tab]))
            button.setToolTip(tip)
        tutte = self.tab_buttons["tutte"]
        tips = [TAB_TEXT["tutte"][1]]
        if k := self._inactive:  # R30: entries that match nothing now
            tutte.setText(strings.PANNELLO_TAB_TUTTE_INACTIVE.format(n=counts["tutte"], k=k))
            tutte.setAccessibleName(strings.ELENCO_TAB_TUTTE_INACTIVE.format(n=counts["tutte"], k=k))
            tips.append(strings.ELENCO_TAB_TUTTE_INACTIVE_TIP.format(k=k))
        if arredo:
            tips.append(strings.PANNELLO_TUTTE_ARREDO_TIP.format(n=arredo))
        tutte.setToolTip("\n".join(tips))
        self.tab_buttons[self._tab].setChecked(True)
        self.tabs.layout().invalidate()  # new counts, new widths: the grid measures again
        self.tabs.updateGeometry()
        return counts

    def _empty_text(self, counts: dict[str, int], any_in_tab: bool) -> str:
        if any_in_tab and not any(is_diff(j) for j in self._rows):
            return strings.PANNELLO_EMPTY_TYPES  # the chips leave nothing
        if self._tab != "guardare":
            return "" if any_in_tab else strings.ELENCO_EMPTY_TAB
        if counts["guardare"]:
            return ""
        if counts["verificare"]:
            return strings.ELENCO_ONLY_MARKED.format(n=counts["verificare"])
        if counts["fatte"]:
            return (strings.ELENCO_ALL_DONE_ONE if counts["tutte"] == 1
                    else strings.ELENCO_ALL_DONE.format(n=counts["fatte"]))
        return strings.ELENCO_NOTHING_TO_LOOK
