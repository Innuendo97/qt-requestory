"""'Elimina iniziativa' (phase 2.5, D6): trash icon, right-click, Canc, the
undo window, the permanent deletion, failures, Ctrl+Z and the app close.

On the fake core (the real deletion on real folders under tmp); the queue's
clock is driven by hand, so nothing waits 5 real seconds.
"""
from __future__ import annotations

import pytest
from PySide6.QtGui import QKeySequence

from qtrequestory.ui import strings
from qtrequestory.ui.main_window import MainWindow
from qtrequestory.ui.pages.officina_page import OfficinaPage
from qtrequestory.ui.pending_delete import DELAY_MS


class FakeWindow:
    """What the page asks of the shell here: status and toasts (no ``deletions``:
    the page makes its own queue)."""

    def __init__(self) -> None:
        self.statuses: list[str] = []
        self.toasts: list[tuple[str, str]] = []

    def set_status(self, text: str) -> None:
        self.statuses.append(text)

    def show_toast(self, text: str, tone: str = "neutral", ms: int = 0, action=None, hint: str = "") -> None:
        self.toasts.append((text, tone))

    def show_page(self, key: str) -> None:
        pass


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def shell() -> FakeWindow:
    return FakeWindow()


@pytest.fixture
def page(qtbot, fake_core, runner, shell, clock) -> OfficinaPage:
    api = fake_core.officina
    for name in ("Alfa", "Beta", "Gamma"):
        api.create_initiative(name)
    widget = OfficinaPage(fake_core, runner, shell)
    widget.deletions.clock = clock
    qtbot.addWidget(widget)
    widget.resize(1200, 700)
    widget.show()
    widget.show_list()
    return widget


def _row(page, name: str) -> int:
    return page.list.names().index(name)


def _expire(page, clock) -> None:
    clock.now += DELAY_MS
    page.deletions.tick()


def test_the_trash_icon_hides_the_row_at_once_and_deletes_later(page, fake_core, clock):
    folder = fake_core.officina.load("Beta").folder
    page.list.delete_button(_row(page, "Beta")).click()

    assert "Beta" not in page.list.names()
    assert folder.is_dir() and fake_core.officina.deleted == [], "nothing deleted yet"
    assert [i.text for i in page.deletions.items()] == [strings.ELIMINA_INITIATIVE_DONE.format(name="Beta")]
    clock.now += DELAY_MS - 100
    page.deletions.tick()
    assert folder.is_dir()

    clock.now += 100
    page.deletions.tick()
    assert not folder.exists() and fake_core.officina.deleted == ["Beta"]
    assert "Beta" not in page.list.names()


def test_undo_brings_the_row_back_selected_and_touches_nothing(page, fake_core, clock):
    folder = fake_core.officina.load("Alfa").folder
    page.delete_initiative("Alfa")
    assert page.deletions.undo_last() is True
    assert "Alfa" in page.list.names() and page.list.selected_name() == "Alfa"
    _expire(page, clock)
    assert folder.is_dir() and fake_core.officina.deleted == []


def test_a_refresh_during_the_window_keeps_the_row_hidden(page):
    page.delete_initiative("Gamma")
    page.refresh()
    page.show_list()
    assert "Gamma" not in page.list.names()


def test_the_selection_moves_to_the_next_row(page):
    names = page.list.names()
    page.list.table.selectRow(0)
    page.delete_initiative(names[0])
    assert page.list.selected_name() == names[1]


def test_a_file_in_use_brings_the_row_back_with_a_message(page, fake_core, shell, clock):
    fake_core.officina.delete_error = "file in uso"
    page.delete_initiative("Beta")
    _expire(page, clock)

    assert "Beta" in page.list.names(), "back in the list"
    assert fake_core.officina.load("Beta").folder.is_dir()
    expected = strings.ELIMINA_FAILED.format(name="Beta", reason=strings.ELIMINA_REASON_LOCKED)
    assert (expected, "bad") in shell.toasts


def test_a_path_refusal_is_a_sentence_too(page, fake_core, shell, clock, monkeypatch):
    def refuse(_ini):
        raise ValueError("fuori dalla cartella")

    monkeypatch.setattr(fake_core.officina, "delete_initiative", refuse)
    page.delete_initiative("Beta")
    _expire(page, clock)
    expected = strings.ELIMINA_FAILED.format(name="Beta", reason=strings.ELIMINA_REASON_REFUSED)
    assert (expected, "bad") in shell.toasts and "Beta" in page.list.names()


def test_an_initiative_open_on_screen_is_closed_first(page):
    page.open_initiative("Alfa")
    assert page.view() == "board"
    page.delete_initiative("Alfa")
    assert page.view() == "list" and page.ini is None
    assert "Alfa" not in page.list.names()


def test_an_initiative_with_generations_under_way_is_not_deleted(page, shell, monkeypatch):
    monkeypatch.setattr(page.queue, "initiatives", lambda: {"Alfa"})
    page.delete_initiative("Alfa")
    assert len(page.deletions) == 0 and "Alfa" in page.list.names()
    assert (strings.ELIMINA_BUSY.format(name="Alfa"), "warn") in shell.toasts


def test_ctrl_z_in_the_list_undoes_the_latest(page):
    page.delete_initiative("Alfa")
    page.delete_initiative("Beta")
    assert page.list.undo_shortcut.key() == QKeySequence(QKeySequence.StandardKey.Undo)
    page.list.undo_shortcut.activated.emit()
    assert "Beta" in page.list.names() and "Alfa" not in page.list.names()


def test_canc_deletes_the_selected_row(page):
    page.list.table.selectRow(_row(page, "Gamma"))
    assert page.list.delete_shortcut.key() == QKeySequence(QKeySequence.StandardKey.Delete)
    page.list.delete_shortcut.activated.emit()
    assert page.deletions.is_pending(page.deletion_key(page.api.load("Gamma")))


def test_the_right_click_menu_offers_elimina_iniziativa(page):
    menu = page.list.context_menu("Beta")
    texts = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert strings.ELIMINA_INITIATIVE in texts
    next(a for a in menu.actions() if a.text() == strings.ELIMINA_INITIATIVE).trigger()
    assert "Beta" not in page.list.names()


def test_quick_deletions_group_in_the_queue(page):
    for name in ("Alfa", "Beta", "Gamma"):
        page.delete_initiative(name)
    assert len(page.deletions) == 3 and page.list.names() == []


# ------------------------------------------------------------------- window ---

@pytest.fixture
def window(qtbot, fake_core, runner):
    fake_core.officina.create_initiative("Delta")
    win = MainWindow(fake_core, runner)
    qtbot.addWidget(win)
    win.show()
    win.show_page("officina")
    return win


def test_the_page_uses_the_window_queue_and_its_bar(window):
    page = window.page("officina")
    assert page.deletions is window.deletions
    page.delete_initiative("Delta")
    assert window.deletion_bar.isVisible()
    assert window.deletion_bar.summary.text() == strings.ELIMINA_INITIATIVE_DONE.format(name="Delta")


def test_closing_the_window_carries_out_the_pending_deletions(window, fake_core):
    folder = fake_core.officina.load("Delta").folder
    window.page("officina").delete_initiative("Delta")
    assert window.close() is True
    assert not folder.exists() and fake_core.officina.deleted == ["Delta"]


def test_a_deletion_failing_at_close_is_reported(window, fake_core, monkeypatch):
    from qtrequestory.ui import main_window as mw

    reported: list[list[str]] = []
    monkeypatch.setattr(mw, "warn_failed_deletions", lambda parent, lines: reported.append(lines))
    fake_core.officina.delete_error = "file in uso"
    window.page("officina").delete_initiative("Delta")
    assert window.close() is True
    assert reported == [[f"Iniziativa «Delta»: {strings.ELIMINA_REASON_LOCKED}"]]
    assert fake_core.officina.load("Delta").folder.is_dir()


def test_the_quit_question_mentions_the_pending_deletions(qtbot, window):
    from qtrequestory.ui import main_window as mw

    box, _stop = mw.build_quit_dialog(window, "sync", "", pending=2)
    qtbot.addWidget(box)
    assert strings.QUIT_PENDING_DELETIONS.format(count=2) in box.informativeText()
    plain, _ = mw.build_quit_dialog(window, "sync")
    qtbot.addWidget(plain)
    assert "eliminazioni" not in plain.informativeText()


def test_the_quit_question_is_given_the_pending_count(window, runner, monkeypatch):
    import threading

    from qtrequestory.ui import main_window as mw

    asked: list[int] = []
    monkeypatch.setattr(mw, "confirm_quit_during_job",
                        lambda parent, name, detail="", pending=0: asked.append(pending) or False)
    window.page("officina").delete_initiative("Delta")
    gate = threading.Event()
    runner.submit("sync", lambda: gate.wait(5.0))
    try:
        assert window.close() is False
        assert asked == [1] and len(window.deletions) == 1, "still undoable: the window stays"
    finally:
        gate.set()


# ------------------------------------------------------ fix round 1 (review) ---

def test_a_new_initiative_during_the_window_keeps_the_pending_one_hidden(page, monkeypatch):
    from qtrequestory.ui.pages import officina_dialogs

    page.delete_initiative("Beta")
    monkeypatch.setattr(officina_dialogs, "ask_text", lambda *_a, **_k: "Nuova")
    page.new_initiative()
    assert "Nuova" in page.list.names() and "Beta" not in page.list.names()


def test_creating_the_name_of_a_pending_one_says_undo_or_wait(page, shell, monkeypatch):
    from qtrequestory.ui.pages import officina_dialogs

    page.delete_initiative("Beta")
    monkeypatch.setattr(officina_dialogs, "ask_text", lambda *_a, **_k: "beta")
    page.new_initiative()
    assert strings.OFFICINA_NEW_INITIATIVE_FAILED.format(
        reason=strings.ELIMINA_NAME_PENDING.format(name="beta")) in shell.statuses


def test_a_pending_initiative_cannot_be_opened(page, shell):
    page.delete_initiative("Beta")
    page.open_initiative("Beta")
    assert page.view() == "list" and page.ini is None
    assert strings.ELIMINA_PENDING_OPEN.format(name="Beta") in shell.statuses


def test_the_officina_choosers_leave_pending_initiatives_out(page, monkeypatch):
    from qtrequestory.ui.pages import officina_actions

    page.delete_initiative("Beta")
    assert {i.id for i in page.listed_initiatives()} == {"Alfa", "Gamma"}
    seen: list[list[str]] = []
    monkeypatch.setattr(officina_actions, "ask_add_case",
                        lambda _parent, choices, **_k: seen.append([c[0] for c in choices]))
    page.open_initiative("Alfa")
    page.add_from_file()
    assert seen and all("Beta" not in ids for ids in seen)


def test_ricerca_add_to_officina_leaves_pending_initiatives_out(window, monkeypatch):
    from types import SimpleNamespace

    from qtrequestory.ui.pages import officina_add

    window.page("officina").delete_initiative("Delta")
    seen: list = []
    monkeypatch.setattr(officina_add, "ask_add_case", lambda _p, choices, **_k: seen.append(list(choices)))
    officina_add.add_hit_to_officina(window.page("search"), window._services,
                                     SimpleNamespace(template_key="MOD_TEST_X"))
    assert seen == [[]], "Delta is the only initiative, and it is pending"


def test_ricerca_cannot_create_an_initiative_named_like_a_pending_one(window, monkeypatch):
    """I1 (D4 note): "Aggiungi all'Officina…" with a NEW initiative named like
    one waiting to be deleted says "annulla o attendi" and creates nothing."""
    from types import SimpleNamespace

    from qtrequestory.ui.pages import officina_add

    statuses: list[str] = []
    monkeypatch.setattr(window, "set_status", statuses.append, raising=False)
    window.page("officina").delete_initiative("Delta")
    monkeypatch.setattr(officina_add, "ask_add_case",
                        lambda *_a, **_k: officina_add.AddChoice("delta", True, ""))
    made = officina_add.add_hit_to_officina(window.page("search"), window._services,
                                            SimpleNamespace(template_key="MOD_TEST_X"))
    assert made is None
    assert strings.OFFICINA_ADD_FAILED.format(reason=strings.ELIMINA_NAME_PENDING.format(name="delta")) in statuses
    assert [i.id for i in window._services.officina.initiatives()] == ["Delta"]


def test_add_from_file_cannot_create_an_initiative_named_like_a_pending_one(page, shell, monkeypatch, tmp_path):
    from qtrequestory.ui.pages import officina_actions
    from qtrequestory.ui.pages.officina_add import AddChoice

    page.delete_initiative("Beta")
    page.open_initiative("Alfa")
    monkeypatch.setattr(officina_actions, "ask_add_case",
                        lambda *_a, **_k: AddChoice("Beta", True, "", "MOD_TEST_X",
                                                                     tmp_path / "x.pdf"))
    page.add_from_file()
    assert strings.OFFICINA_ADD_FAILED.format(reason=strings.ELIMINA_NAME_PENDING.format(name="Beta")) \
        in shell.statuses


@pytest.mark.parametrize("why", ["open", "queued", "officina-delivery", "officina-add", "officina-review",
                                 "officina-compare", "officina-noise", "officina-dom", "officina-generate-2"])
def test_the_commit_rechecks_and_restores_a_busy_initiative(page, fake_core, shell, clock, monkeypatch, why):
    page.delete_initiative("Beta")
    if why == "open":
        page.ini = fake_core.officina.load("Beta")  # reached some other way
    elif why == "queued":
        monkeypatch.setattr(page.queue, "initiatives", lambda: {"Beta"})
    else:  # a job that writes inside an initiative is still running
        monkeypatch.setattr(page.runner, "is_running", lambda name: name == why)
    _expire(page, clock)

    assert fake_core.officina.deleted == [] and fake_core.officina.load("Beta").folder.is_dir()
    expected = strings.ELIMINA_FAILED.format(name="Beta", reason=strings.ELIMINA_REASON_BUSY)
    assert (expected, "bad") in shell.toasts


def test_every_job_that_writes_in_an_initiative_is_checked():
    from qtrequestory.ui.pages.officina_delete import WRITER_JOBS
    from qtrequestory.ui.workers import JOB_NAMES

    officina = {name for name in JOB_NAMES if name.startswith("officina-")}
    assert officina - set(WRITER_JOBS) == {"officina-pick"}, "only the search of calls writes nothing"


def test_canc_does_not_auto_repeat(page):
    assert page.list.delete_shortcut.autoRepeat() is False


def test_a_second_trash_click_on_another_row_right_after_is_ignored(page):
    now = [10.0]
    page.list.clock = lambda: now[0]
    first = page.list.names()[0]
    page.list.delete_button(0).click()
    now[0] += 0.2
    page.list.delete_button(0).click()  # the neighbour slid under the pointer
    assert len(page.deletions) == 1 and page.deletions.items()[0].name.endswith(f"«{first}»")
    now[0] += 0.5
    page.list.delete_button(0).click()
    assert len(page.deletions) == 2


def test_a_root_changed_during_the_window_is_its_own_sentence(page, fake_core, shell, clock, monkeypatch,
                                                              tmp_path):
    from qtrequestory.officina.remove import RefusedDeletion

    def refuse(_ini):
        raise RefusedDeletion("C:\\percorso\\segreto non è direttamente nella cartella dell'Officina")

    page.delete_initiative("Beta")
    monkeypatch.setattr(fake_core.officina, "delete_initiative", refuse)
    monkeypatch.setattr(fake_core.officina, "workspace_root", lambda: tmp_path / "altra")
    _expire(page, clock)
    assert (strings.ELIMINA_FAILED_ROOT_CHANGED.format(name="Beta"), "bad") in shell.toasts
    assert not any("segreto" in text for text, _tone in shell.toasts)


def test_the_close_warning_uses_the_italian_reason(window, fake_core, monkeypatch):
    from qtrequestory.officina.remove import RefusedDeletion
    from qtrequestory.ui import main_window as mw

    def refuse(_ini):
        raise RefusedDeletion("C:\\percorso\\segreto non è un'iniziativa")

    reported: list[list[str]] = []
    monkeypatch.setattr(mw, "warn_failed_deletions", lambda parent, lines: reported.append(lines))
    monkeypatch.setattr(fake_core.officina, "delete_initiative", refuse)
    window.page("officina").delete_initiative("Delta")
    assert window.close() is True
    assert reported == [[f"Iniziativa «Delta»: {strings.ELIMINA_REASON_REFUSED}"]]


def test_a_just_viewed_case_does_not_hold_its_pdfs_open(qtbot, page, fake_core, clock, tmp_path):
    """The viewer's PDFium documents are closed after each page: deleting an
    initiative right after looking at its case must not fail as "in uso"."""
    import json

    from tests.fakes.fake_core import canned_pdf

    api = fake_core.officina
    ini = api.create_initiative("Vista")
    payload = tmp_path / "p.json"
    payload.write_text(json.dumps({"documents": [{"template": {"templateKey": "MOD_TEST_V"}}]}),
                       encoding="utf-8")
    case = api.case_from_file(ini, payload, "MOD_TEST_V")
    target = tmp_path / "cliente.pdf"
    target.write_bytes(canned_pdf("MOD_TEST cliente"))
    api.set_target(case, target)
    loaded = api.load("Vista")
    api.generate(loaded, loaded.cases[0], "tobe")
    page.refresh()
    page.open_initiative("Vista")
    page.open_case(case.id)
    qtbot.waitUntil(lambda: page.case_view.left.showing_document()
                    and page.case_view.right.showing_document(), timeout=10000)
    qtbot.wait(300)  # let the page renders finish
    page.show_list()
    page.delete_initiative("Vista")
    _expire(page, clock)
    assert api.deleted == ["Vista"] and not ini.folder.exists()
