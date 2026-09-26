"""What a review action calls, what undoes it, and the per-case undo stack.

Spec §7.3: every action on a difference shows a toast with "Annulla" and
Ctrl+Z undoes the last one — one stack per case, in memory. Each action is
planned here as two lists of :data:`Step` (an ``OfficinaApi`` method name and
its arguments after the case): the forward calls and the calls that undo
them, computed from the review state BEFORE the action (the note of a
tolerance being removed, the version a mark being removed was made in):

====================  ==================  ==========================================
action                forward             undo
====================  ==================  ==========================================
F on an open diff     ``mark_done``       ``unmark``
F on a marked diff    ``unmark``          ``mark_done`` (in the mark's own version)
T / "Tollera…"        ``tolerate``        ``untolerate``
T on a hand-tolerated ``untolerate``      ``tolerate`` (with its old note)
V on a variable       ``not_variable``    ``variable_again``
V on a not-variable   ``variable_again``  ``not_variable``
"Annulla i segni"     ``unmark_all``      ``mark_done`` of every removed mark
====================  ==================  ==========================================

The API finds a difference by its ``anchor`` (and saves its generated text),
so a step keeps the :class:`Judged` it was planned on: after the refresh the
ids are renumbered, the anchors are not. A mark whose difference is not on
screen any more gets a stand-in :class:`Judged` built from the mark itself.
Qt-free: the page submits the steps to a worker (``officina_judge.act``).
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from qtrequestory.ui.contracts import Anchor, Diff, Judged, Mark, Review

__all__ = ["DEPTH", "Entry", "Intent", "Step", "UndoStack", "mark_steps", "stand_in",
           "tolerate_steps", "unmark_all_steps", "variable_steps"]

#: ``(OfficinaApi method, arguments after the case)``.
Step = tuple[str, tuple]
Plan = tuple[list[Step], list[Step]]
CaseKey = tuple[str, str]
#: Entries kept per case (the oldest go first).
DEPTH = 50


@dataclass(frozen=True, eq=False)
class Entry:
    """One undoable action: what its toast said, the TO-BE version it was
    made on, and the steps that undo it. Compared by identity: Ctrl+Z undoes
    the LAST entry; a toast's "Annulla" undoes ITS entry, even when later
    actions were pushed since (it may be pressed while another action saves),
    as long as it is still on the stack and the version on screen is the one
    it was made on."""

    text: str
    version: int
    undo: tuple[Step, ...]


@dataclass(frozen=True, eq=False)
class Intent:
    """What the user asked, queued until the case is free (R38). It names its
    difference by ``anchor`` — ids are renumbered by every re-judge — and is
    planned only when it reaches the head of the queue, against the review
    state the previous item left.

    ``kind``: "fatta" | "tollera" | "non_variabile" (a toggle each, on
    ``anchor``) | "tollera_nota" ("Tollera…": tolerate with ``note``, never
    a toggle: an earlier queued T on the same difference does not turn it
    into an untolerate, the note replaces) | "unmark_all" | "undo"
    (``entry``: that toast's action; None: the last one, Ctrl+Z). ``what``:
    the text the status line names if the difference is gone by then.
    ``version``: the TO-BE version on screen when the key was pressed; a
    queued "segna fatta" marks in THAT version even if another one is on
    screen by the time it runs (the difference is still found by anchor)."""

    kind: str
    anchor: Anchor | None = None
    note: str = ""
    entry: Entry | None = None
    what: str = ""
    version: int | None = None


def mark_steps(j: Judged, review: Review, version: int) -> Plan:
    """F: mark ``j`` done in ``version``, or remove its mark."""
    if j.marked:
        made = next((m.version for m in review.marks if m.anchor == j.diff.anchor), version)
        return [("unmark", (j,))], [("mark_done", (j, made))]
    return [("mark_done", (j, version))], [("unmark", (j,))]


def tolerate_steps(j: Judged, review: Review, note: str = "", *, toggle: bool = True) -> Plan:
    """T: tolerate ``j``, or stop tolerating a difference tolerated by hand
    (the undo puts its note back). ``toggle=False`` ("Tollera…"): always
    tolerate with ``note``; over an existing tolerance the undo restores its note."""
    by_hand = next((t for t in review.tolerances if t.anchor == j.diff.anchor), None)
    if toggle and j.verdict == "tollerata" and by_hand is not None:
        return [("untolerate", (j,))], [("tolerate", (j, by_hand.note))]
    if not toggle and by_hand is not None:
        return [("tolerate", (j, note))], [("tolerate", (j, by_hand.note))]
    return [("tolerate", (j, note))], [("untolerate", (j,))]


def variable_steps(j: Judged, review: Review) -> Plan:
    """V: "Non è una variabile", or back to a variable."""
    if any(anchor == j.diff.anchor for anchor, _when in review.not_variables):
        return [("variable_again", (j,))], [("not_variable", (j,))]
    return [("not_variable", (j,))], [("variable_again", (j,))]


def unmark_all_steps(review: Review, judged: Sequence[Judged]) -> Plan:
    """"Annulla i segni": undone by marking each removed mark again, in its version."""
    on_screen = {j.diff.anchor: j for j in judged}
    undo: list[Step] = [("mark_done", (on_screen.get(m.anchor) or stand_in(m), m.version))
                        for m in review.marks]
    return [("unmark_all", ())], undo


def stand_in(mark: Mark) -> Judged:
    """A :class:`Judged` carrying what the API reads of a marked difference:
    its anchor and its generated text."""
    a = mark.anchor
    diff = Diff(id=0, op=a.op, klass=a.klass, left=(), right=(), left_text=a.target_text,
                right_text=mark.generated, left_spans=(), right_spans=(), anchor=a)
    return Judged(diff, None, marked=True)


class UndoStack:
    """The last actions of each case, ``(initiative id, case id)`` → entries."""

    def __init__(self, depth: int = DEPTH) -> None:
        self._depth = depth
        self._stacks: dict[CaseKey, list[Entry]] = {}

    def push(self, key: CaseKey, entry: Entry) -> None:
        stack = self._stacks.setdefault(key, [])
        stack.append(entry)
        del stack[:-self._depth]

    def top(self, key: CaseKey, version: int) -> Entry | None:
        """The last action of the case, if it was made on ``version`` (the
        version on screen): undoing a v2 mark while v3 is compared would undo
        something the verification already used. Nothing is dropped: back on
        that version, Ctrl+Z works again."""
        entry = self.peek(key)
        return entry if entry is not None and entry.version == version else None

    def peek(self, key: CaseKey) -> Entry | None:
        stack = self._stacks.get(key)
        return stack[-1] if stack else None

    def holds(self, key: CaseKey, entry: Entry) -> bool:
        return entry in self._stacks.get(key, [])

    def discard(self, key: CaseKey, entry: Entry) -> None:
        """Forget ``entry`` (it was undone)."""
        stack = self._stacks.get(key, [])
        if entry in stack:
            stack.remove(entry)

    def __len__(self) -> int:
        return sum(len(s) for s in self._stacks.values())
