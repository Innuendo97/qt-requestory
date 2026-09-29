"""How the differences list keeps its selection across refills (a mixin of
``DiffPanel``, split from ``officina_diffs`` for size).

A refill (the same case compared again after an action) keeps the selected
difference; when that one changed state (just marked, tolerated) the row at
the same place instead, so F, F, F walks down the list — never from the last
open row of *Da guardare* into the dimmed "DA VERIFICARE" group. After an
action from the page (:meth:`SelectionMemoryMixin.follow_current`: the
mini-bar, the menu, a double click, F / T / V in a viewer) the SAME
difference stays selected in its new state, so the viewers do not move
(spec §4.2). When its new state takes it out of the tab (e.g. «Togli il
segno» in *Da verificare*) it stays there anyway as a *pinned* row, under its
own type header and dimmed, until the user selects something else or changes tab; then
the tab is recomputed normally (controller ruling, U1 fix round 1). The tab
counts are always the real ones. The followed difference is found by its
pre-action ``Diff.id`` first (stable across in-place actions; only a
regeneration renumbers), then by its full anchor, and only then by
:func:`same_place` — never an untouched twin with the same text (fix round 2).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from qtrequestory.ui.pages.officina_types import insert_in_group, is_diff
from qtrequestory.ui.pages.officina_verdict_style import state_of

if TYPE_CHECKING:
    from qtrequestory.ui.contracts import Anchor, Judged


def same_place(a: Anchor, b: Anchor) -> bool:
    """The same difference for following it: the class may change with the
    action ("Non è una variabile" turns a variable into text)."""
    return a == b or (a.op, a.context, a.target_text) == (b.op, b.context, b.target_text)


def find_followed(followed: tuple[int, Anchor], rows) -> int | None:
    """Index in ``rows`` (Judged, a group header or None) of the followed ``(id, anchor)``:
    the same id still at the same place, else the same anchor, else the same
    place with another class (the action changed it)."""
    diff_id, anchor = followed
    tests = (lambda d: d.id == diff_id and same_place(d.anchor, anchor),
             lambda d: d.anchor == anchor,
             lambda d: same_place(d.anchor, anchor))
    for test in tests:
        hit = next((i for i, j in enumerate(rows) if is_diff(j) and test(j.diff)), None)
        if hit is not None:
            return hit
    return None

__all__ = ["SelectionMemoryMixin"]


class SelectionMemoryMixin:
    """Needs from the panel: ``list`` (DiffList), ``_rows``, ``_judged``,
    ``current_id``, ``_current_judged``, ``_set_current_silently`` and
    ``_followed`` ((id, anchor)) / ``_pinned`` (None in ``__init__``)."""

    def _with_pin(self, rows: list, judged: list[Judged],
                  keep: tuple[Anchor, str, int] | None) -> list:
        """``rows`` plus the followed difference at its old place when its new
        state took it out of the tab (``_pinned``: its id, drawn dimmed)."""
        self._pinned = None
        followed = self._followed
        if (followed is None or keep is None or not same_place(keep[0], followed[1])
                or find_followed(followed, rows) is not None):
            return rows
        hit = find_followed(followed, judged)
        if hit is None:  # gone altogether (e.g. regenerated): nothing to keep
            return rows
        j = judged[hit]
        self._pinned = j.diff.id
        return insert_in_group(rows, j)  # under its own type header (U3 fix round 1, M1)

    def _unpin(self) -> None:
        """The user moved on: the tab without the pinned row."""
        if self._pinned is not None and self._followed is None and self._judged is not None:
            self._fill(self._memory())

    def _memory(self) -> tuple[Anchor, str, int] | None:
        """(anchor, state, index among the rows) of the selected difference."""
        if self._judged is None:
            return None
        diff_id = self.current_id()
        j = next((x for x in self._rows if is_diff(x) and x.diff.id == diff_id), None)
        if j is None:
            return None
        rows = self.list.selectable_rows()
        return j.diff.anchor, state_of(j), rows.index(self.list.currentRow())

    def _restore(self, keep: tuple[Anchor, str, int] | None) -> None:
        rows = self.list.selectable_rows()
        if keep is None or not rows:
            return
        anchor, state, index = keep
        if self._followed is not None and same_place(anchor, self._followed[1]):
            row = find_followed(self._followed, self._rows)
            if row is not None:
                self._set_current_silently(row)
                return
        for row, j in enumerate(self._rows):
            if is_diff(j) and j.diff.anchor == anchor and state_of(j) == state:
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

    def follow_current(self) -> None:
        """An action on the selected difference came from the page: the next
        refills keep it selected in its new state (no move on, no fallback),
        until the selection moves."""
        j = self._current_judged()
        self._followed = (j.diff.id, j.diff.anchor) if j is not None else None

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

