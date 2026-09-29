"""The undoable-deletion queue and its bar (phase 2.5, D6): ``ui/pending_delete``.

Timers run on a fake clock (``PendingDeletions.clock``) and ``tick()``, so
nothing waits 5 real seconds; one test lets the real ``QTimer`` fire on a
short delay.
"""
from __future__ import annotations

import pytest
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QWidget

from qtrequestory.ui import strings
from qtrequestory.ui.pending_bar import PendingBar
from qtrequestory.ui.pending_delete import DELAY_MS, PendingDeletions


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Owner:
    """What a page does with the callbacks: record them."""

    def __init__(self) -> None:
        self.log: list[tuple[str, str]] = []
        self.fail: dict[str, BaseException] = {}

    def schedule(self, queue: PendingDeletions, key: str):
        def commit() -> None:
            if key in self.fail:
                raise self.fail[key]
            self.log.append(("commit", key))

        return queue.schedule(key, f"Iniziativa «{key}» eliminata", f"Iniziativa «{key}»", commit,
                              on_undo=lambda: self.log.append(("undo", key)),
                              on_done=lambda: self.log.append(("done", key)),
                              on_failed=lambda exc: self.log.append(("failed", f"{key}:{exc}")))


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def queue(qapp, clock) -> PendingDeletions:
    q = PendingDeletions(clock=clock)
    yield q
    q.stop()


def test_the_default_window_is_five_seconds():
    assert DELAY_MS == 5000


def test_nothing_is_deleted_before_the_window_ends(queue, clock):
    owner = Owner()
    owner.schedule(queue, "A")
    clock.now += DELAY_MS - 1
    queue.tick()
    assert owner.log == [] and queue.is_pending("A")
    clock.now += 1
    queue.tick()
    assert owner.log == [("commit", "A"), ("done", "A")]
    assert not queue.is_pending("A") and len(queue) == 0


def test_every_deletion_has_its_own_timer(queue, clock):
    owner = Owner()
    owner.schedule(queue, "A")
    clock.now += 3000
    owner.schedule(queue, "B")
    clock.now += 2000  # A's 5 s are over, B has 3 s left
    queue.tick()
    assert owner.log == [("commit", "A"), ("done", "A")]
    assert queue.is_pending("B") and queue.remaining_ms(queue.items()[0]) == 3000
    clock.now += 3000
    queue.tick()
    assert owner.log[-2:] == [("commit", "B"), ("done", "B")]


def test_undo_one_keeps_the_others_running(queue, clock):
    owner = Owner()
    a = owner.schedule(queue, "A")
    owner.schedule(queue, "B")
    assert queue.undo(a) is True
    clock.now += DELAY_MS
    queue.tick()
    assert owner.log == [("undo", "A"), ("commit", "B"), ("done", "B")]
    assert queue.undo(a) is False, "an item undone once is gone"


def test_undo_last_takes_the_latest_and_undo_all_the_rest(queue):
    owner = Owner()
    for key in "ABC":
        owner.schedule(queue, key)
    assert queue.undo_last() is True
    assert owner.log == [("undo", "C")]
    assert queue.undo_all() == 2
    assert owner.log == [("undo", "C"), ("undo", "A"), ("undo", "B")]
    assert queue.undo_last() is False and len(queue) == 0


def test_the_same_key_is_not_queued_twice(queue):
    owner = Owner()
    first = owner.schedule(queue, "A")
    assert owner.schedule(queue, "A") is first and len(queue) == 1


def test_a_failed_deletion_calls_back_and_leaves_the_queue(queue, clock):
    owner = Owner()
    owner.fail["A"] = PermissionError(13, "in uso")
    failures = []
    queue.failed.connect(lambda item, exc: failures.append((item.key, type(exc))))
    owner.schedule(queue, "A")
    clock.now += DELAY_MS
    queue.tick()
    assert owner.log == [("failed", "A:[Errno 13] in uso")]
    assert failures == [("A", PermissionError)] and len(queue) == 0


def test_flush_deletes_everything_now_and_returns_the_failures(queue):
    owner = Owner()
    owner.fail["B"] = OSError("bloccato")
    for key in "ABC":
        owner.schedule(queue, key)
    failures = queue.flush()
    assert [(item.key, str(exc)) for item, exc in failures] == [("B", "bloccato")]
    assert [e for e in owner.log if e[0] == "commit"] == [("commit", "A"), ("commit", "C")]
    assert len(queue) == 0


def test_the_real_timer_deletes_on_its_own(qtbot):
    owner = Owner()
    q = PendingDeletions(delay_ms=150)
    owner.schedule(q, "A")
    qtbot.waitUntil(lambda: ("commit", "A") in owner.log, timeout=3000)
    assert not q.is_pending("A")


# ----------------------------------------------------------------------- bar ---

@pytest.fixture
def bar(qtbot, queue) -> PendingBar:
    host = QWidget()
    qtbot.addWidget(host)
    host.resize(1000, 600)
    widget = PendingBar(queue, host)
    host.show()
    yield widget  # the fixture keeps ``host`` (the bar's parent) alive
    host.close()


def test_the_bar_is_hidden_while_nothing_is_pending(bar, queue):
    assert bar.isHidden()
    Owner().schedule(queue, "A")
    assert bar.isVisible()
    queue.undo_last()
    assert bar.isHidden()


def test_one_deletion_reads_as_a_sentence_with_a_countdown(bar, queue, clock):
    Owner().schedule(queue, "Banco")
    assert bar.summary.text() == "Iniziativa «Banco» eliminata"
    assert bar.undo_button.text() == strings.ELIMINA_UNDO
    assert bar.countdown.text() == strings.ELIMINA_SECONDS.format(seconds=5)
    assert bar.toggle.isHidden()
    clock.now += 2100
    queue.tick()
    assert bar.countdown.text() == strings.ELIMINA_SECONDS.format(seconds=3)
    assert 0.5 < bar.line.fraction < 0.6


def test_quick_deletions_are_grouped_with_undo_all(bar, queue):
    owner = Owner()
    for key in "ABC":
        owner.schedule(queue, key)
    assert bar.summary.text() == strings.ELIMINA_MANY.format(count=3)
    assert bar.undo_button.text() == strings.ELIMINA_UNDO_ALL
    assert bar.toggle.isVisible() and not bar.is_expanded()
    bar.undo_button.click()
    assert len(queue) == 0 and [e for e in owner.log if e[0] == "undo"] == [("undo", k) for k in "ABC"]


def test_the_expanded_list_undoes_one_item(bar, queue, clock):
    owner = Owner()
    owner.schedule(queue, "A")
    clock.now += 1000
    owner.schedule(queue, "B")
    owner.schedule(queue, "C")
    bar.toggle.click()
    assert bar.is_expanded()
    rows = bar.rows()
    assert [r.label.text() for r in rows] == ["Iniziativa «A»", "Iniziativa «B»", "Iniziativa «C»"]
    assert rows[0].countdown.text() == strings.ELIMINA_SECONDS.format(seconds=4)
    assert rows[1].countdown.text() == strings.ELIMINA_SECONDS.format(seconds=5)
    rows[1].undo_button.click()
    assert owner.log == [("undo", "B")]
    assert [item.key for item in queue.items()] == ["A", "C"]
    assert [r.label.text() for r in bar.rows()] == ["Iniziativa «A»", "Iniziativa «C»"]


def test_back_to_one_item_the_bar_reads_as_one_again(bar, queue):
    owner = Owner()
    owner.schedule(queue, "A")
    owner.schedule(queue, "B")
    bar.toggle.click()
    queue.undo_last()
    assert bar.summary.text() == "Iniziativa «A» eliminata"
    assert bar.toggle.isHidden() and not bar.list_box.isVisible()


def test_ctrl_z_on_the_bar_undoes_the_latest(bar, queue):
    owner = Owner()
    owner.schedule(queue, "A")
    owner.schedule(queue, "B")
    assert bar.undo_shortcut.key() == QKeySequence(QKeySequence.StandardKey.Undo)
    bar.undo_shortcut.activated.emit()
    assert owner.log == [("undo", "B")]


def test_the_bar_is_keyboard_reachable_and_named(bar, queue):
    from PySide6.QtCore import Qt

    owner = Owner()
    owner.schedule(queue, "A")
    owner.schedule(queue, "B")
    bar.toggle.click()
    assert bar.undo_button.focusPolicy() & Qt.FocusPolicy.TabFocus
    assert bar.toggle.focusPolicy() & Qt.FocusPolicy.TabFocus
    assert bar.accessibleName() == strings.ELIMINA_BAR_A11Y
    assert bar.rows()[0].undo_button.accessibleName() == \
        strings.ELIMINA_UNDO_ONE_A11Y.format(name="Iniziativa «A»")


def test_the_bar_sits_at_the_bottom_of_its_parent(bar, queue):
    Owner().schedule(queue, "A")
    host = bar.parentWidget()
    assert bar.geometry().bottom() < host.height()
    assert host.height() - bar.geometry().bottom() <= 32


def test_focus_stays_on_the_next_rows_annulla(qtbot, bar, queue):
    owner = Owner()
    for key in "ABC":
        owner.schedule(queue, key)
    bar.set_expanded(True)
    host = bar.parentWidget()
    host.activateWindow()
    qtbot.waitUntil(host.isActiveWindow, timeout=2000)
    bar.rows()[1].undo_button.setFocus()
    qtbot.waitUntil(lambda: bar.rows()[1].undo_button.hasFocus(), timeout=2000)
    bar.rows()[1].undo_button.click()
    assert [r.item.key for r in bar.rows()] == ["A", "C"]
    assert bar.rows()[1].undo_button.hasFocus(), "the focus moves to the row that took its place"


def test_an_item_can_explain_its_failure(queue):
    item = queue.schedule("A", "a", "Elemento «A»", lambda: None, explain=lambda exc: "spiegato")
    assert item.explain(ValueError("x")) == "spiegato"
