"""Undoable deletions: delete at once on screen, for good only after 5 s (D6).

The pattern (Gmail's "Annulla", Todoist, Drive) instead of an "Are you
sure?" dialog: the item disappears from its list at once (optimistic), the
bar at the bottom of the window (:class:`~qtrequestory.ui.pending_bar.PendingBar`)
says "Iniziativa «X» eliminata · Annulla" with a visible countdown, and only
when the countdown ends is the deletion carried out — permanently, there is
no second level of recovery.

**The queue** (:class:`PendingDeletions`, one per window: ``MainWindow.deletions``):

* every deletion has its OWN deadline (``delay_ms`` after it was asked
  for): deleting A then B two seconds later leaves both undoable, A for 3 s
  more, B for 5 — nothing is ever pushed out by a later deletion, unlike the
  single ``Toast`` whose message the next one replaces;
* several deletions in their window are grouped by the bar ("3 elementi
  eliminati · Annulla tutto", with the list and a per-item "Annulla");
* ``undo_last()`` (Ctrl+Z on the bar or in the owner's list) takes the most
  recent one; ``undo(item)`` any one; ``undo_all()`` every one;
* at the deadline ``commit()`` runs on the GUI thread (a folder of PDFs is
  removed in well under a second); an exception there is a FAILURE: the
  item leaves the queue and ``on_failed(exc)`` lets the owner put it back
  on screen with a message;
* ``flush()`` carries out everything at once: the window calls it when it
  closes, so a deletion is never lost nor postponed to the next start (the
  quit question mentions them when it is asked anyway).

**Reusing it for another delicate deletion** (an environment in
Impostazioni, a generator, …)::

    queue = window.deletions                    # or PendingDeletions(self) without a window
    self.hidden.add(key)                        # 1. hide the item in YOUR list, now
    queue.schedule(
        key,                                    # unique for the thing ("env:coll")
        "Ambiente «coll» rimosso",              # the bar's sentence while it is alone
        "Ambiente «coll»",                      # its row in the grouped list
        commit=lambda: api.remove_env("coll"),  # 2. the real deletion; raise to fail
        on_undo=lambda: (self.hidden.discard(key), self.refresh()),
        on_done=lambda: self.hidden.discard(key),
        on_failed=lambda exc: (self.hidden.discard(key), self.refresh(), self.say(exc)),
        explain=lambda exc: "…",                # optional: your sentence for a failure
    )

``commit`` should also RE-CHECK that the deletion is still safe (the item may
have been reached another way during the 5 s) and raise to restore it.

and filter ``queue.is_pending(key)`` (or your own set) out of the list
every time you re-read it, so a refresh during the 5 s does not bring the
item back. Timers: :attr:`PendingDeletions.clock` (ms) and :meth:`tick`
let a test move time by hand.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal

from qtrequestory.ui import strings

__all__ = ["DELAY_MS", "TICK_MS", "PendingDeletion", "PendingDeletions", "failure_reason"]

log = logging.getLogger(__name__)

#: The undo window (D6: at most 5 s).
DELAY_MS = 5000
#: How often the countdown is refreshed and the deadlines checked.
TICK_MS = 100


def _monotonic_ms() -> float:
    return time.monotonic() * 1000.0


@dataclass(eq=False)
class PendingDeletion:
    """One deletion in its undo window. Compared by identity."""

    key: str
    #: The bar's sentence while it is the only one ("Iniziativa «X» eliminata").
    text: str
    #: Its row in the grouped list ("Iniziativa «X»").
    name: str
    commit: Callable[[], None]
    on_undo: Callable[[], None] | None
    on_done: Callable[[], None] | None
    on_failed: Callable[[BaseException], None] | None
    started: float
    deadline: float
    #: Why it failed, for the user (the close warning); default ``failure_reason``.
    explain: Callable[[BaseException], str] | None = None

    def reason(self, exc: BaseException) -> str:
        """The owner's sentence for ``exc``, else :func:`failure_reason`."""
        if self.explain is not None:
            try:
                return self.explain(exc)
            except Exception:  # noqa: BLE001
                log.exception("spiegazione dell'errore non riuscita")
        return failure_reason(exc)


class PendingDeletions(QObject):
    """The deletions waiting for their deadline (see the module docstring)."""

    #: An item was added or left (undone, carried out, failed).
    changed = Signal()
    #: The countdown moved (every :data:`TICK_MS`).
    ticked = Signal()
    undone = Signal(object)
    committed = Signal(object)
    #: ``(item, exception)``: the deletion failed; the owner restores the item.
    failed = Signal(object, object)

    def __init__(self, parent: QObject | None = None, *, delay_ms: int = DELAY_MS,
                 clock: Callable[[], float] | None = None) -> None:
        super().__init__(parent)
        self.delay_ms = delay_ms
        #: Milliseconds, monotonic. Replace it to drive the deadlines by hand.
        self.clock: Callable[[], float] = clock or _monotonic_ms
        self._items: list[PendingDeletion] = []
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self.tick)

    # -- API -----------------------------------------------------------------

    def schedule(self, key: str, text: str, name: str, commit: Callable[[], None], *,
                 on_undo: Callable[[], None] | None = None,
                 on_done: Callable[[], None] | None = None,
                 on_failed: Callable[[BaseException], None] | None = None,
                 explain: Callable[[BaseException], str] | None = None) -> PendingDeletion:
        """Start the undo window of ``key``; the same key twice is one deletion."""
        existing = self.find(key)
        if existing is not None:
            return existing
        now = self.clock()
        item = PendingDeletion(key, text, name, commit, on_undo, on_done, on_failed,
                               started=now, deadline=now + self.delay_ms, explain=explain)
        self._items.append(item)
        self._timer.start()
        self.changed.emit()
        return item

    def items(self) -> list[PendingDeletion]:
        """Oldest first."""
        return list(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def find(self, key: str) -> PendingDeletion | None:
        return next((item for item in self._items if item.key == key), None)

    def is_pending(self, key: str) -> bool:
        return self.find(key) is not None

    def remaining_ms(self, item: PendingDeletion) -> int:
        return max(0, round(item.deadline - self.clock()))

    def fraction(self, item: PendingDeletion) -> float:
        """What is left of its window, 1.0 → 0.0."""
        span = item.deadline - item.started
        return max(0.0, min(1.0, (item.deadline - self.clock()) / span)) if span > 0 else 0.0

    def undo(self, item: PendingDeletion) -> bool:
        """Cancel ``item``: False when it is not waiting any more."""
        if item not in self._items:
            return False
        self._items.remove(item)
        self._sync_timer()
        _call(item.on_undo)
        self.undone.emit(item)
        self.changed.emit()
        return True

    def undo_last(self) -> bool:
        """Ctrl+Z: the most recent one."""
        return self.undo(self._items[-1]) if self._items else False

    def undo_all(self) -> int:
        """Every one, oldest first; how many."""
        items = list(self._items)
        for item in items:
            self.undo(item)
        return len(items)

    def tick(self) -> None:
        """Carry out every deletion whose deadline passed; refresh the countdown."""
        now = self.clock()
        for item in [i for i in self._items if i.deadline <= now]:
            self._commit(item)
        if self._items:
            self.ticked.emit()

    def flush(self) -> list[tuple[PendingDeletion, BaseException]]:
        """Carry out everything now (the window is closing); the failures."""
        failures: list[tuple[PendingDeletion, BaseException]] = []
        for item in list(self._items):
            exc = self._commit(item)
            if exc is not None:
                failures.append((item, exc))
        return failures

    def stop(self) -> None:
        """Stop the timer (tests; nothing is carried out)."""
        self._timer.stop()

    # -- internals -------------------------------------------------------------

    def _commit(self, item: PendingDeletion) -> BaseException | None:
        if item not in self._items:
            return None
        self._items.remove(item)  # first: a slow commit must not run twice
        self._sync_timer()
        try:
            item.commit()
        except Exception as exc:  # noqa: BLE001 - any failure puts the item back
            log.warning("eliminazione non riuscita (%s): %s", item.key, exc)
            _call(item.on_failed, exc)
            self.failed.emit(item, exc)
            self.changed.emit()
            return exc
        _call(item.on_done)
        self.committed.emit(item)
        self.changed.emit()
        return None

    def _sync_timer(self) -> None:
        if not self._items:
            self._timer.stop()


def failure_reason(exc: BaseException) -> str:
    """Why a deletion failed, in Italian: a file in use / protected, or the
    system's words."""
    if isinstance(exc, PermissionError):
        return strings.ELIMINA_REASON_LOCKED
    if isinstance(exc, OSError):
        return strings.ELIMINA_REASON_OTHER.format(error=exc.strerror or exc)
    return str(exc) or type(exc).__name__


def _call(callback: Callable | None, *args: object) -> None:
    """An owner's callback; its bug must not stop the queue."""
    if callback is None:
        return
    try:
        callback(*args)
    except Exception:  # noqa: BLE001
        log.exception("callback di eliminazione non riuscito")
