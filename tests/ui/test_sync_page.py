"""The Sincronizzazione page: cards, progress strip, registro, auto-sync, lock.

Everything runs against ``fake_core`` — the scripted sync of
``tests/fakes/fake_core.py`` — and never sleeps waiting for it: a test that
needs to act *during* a run hooks the job's ``progress`` signal and reacts to a
specific event, then waits for ``finished``. Assertions about the strip's
arithmetic feed the events in by hand through :meth:`SyncPage.handle_event`, so
they do not depend on how many ``FileProgress`` the throttle let through.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QToolButton

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import (
    EnvStarted,
    EnvStatus,
    FileProgress,
    FileStarted,
    IndexFileScanned,
    IndexStarted,
    RemoteIndexRead,
    SyncStarted,
)
from qtrequestory.ui.main_window import PAGES
from qtrequestory.ui.pages import env_card as ec
from qtrequestory.ui.pages.env_card import EnvCard
from qtrequestory.ui.pages.sync_page import SyncPage

MB = 1_048_576
TIMEOUT = 15_000


class FakeWindow:
    """What the page uses of ``MainWindow``: the transient status message.

    The sync summary is *not* here on purpose: the page emits
    ``summary_changed`` and the shell connects it, so the test listens to the
    signal instead of to a window method the page must not call.
    """

    def __init__(self) -> None:
        self.status: list[str] = []

    def set_status(self, text: str, ms: int = 4000) -> None:
        self.status.append(text)


@pytest.fixture
def window() -> FakeWindow:
    return FakeWindow()


@pytest.fixture
def page(qtbot, fake_core, runner, window) -> SyncPage:
    widget = SyncPage(fake_core, runner, window)
    qtbot.addWidget(widget)
    widget.show()
    widget.summaries = []
    widget.summary_changed.connect(widget.summaries.append)
    return widget


def run_to_completion(qtbot, page: SyncPage, **kw) -> None:
    page.start_sync(**kw)
    assert page.sync_job is not None
    with qtbot.waitSignal(page.sync_job.signals.finished, timeout=TIMEOUT):
        pass


# ------------------------------------------------------------ registration ---

def test_the_page_is_registered_in_the_shell_under_the_sync_key():
    spec = next(p for p in PAGES if p.key == "sync")
    assert spec.label == strings.NAV_SYNC


def test_the_page_offers_the_hooks_the_shell_looks_for(page):
    assert hasattr(page.summary_changed, "connect")
    assert callable(page.start_sync)
    assert callable(page.on_config_changed)


# ------------------------------------------------------------------- cards ---

def test_one_card_per_enabled_environment_prefilled_from_env_status(page, fake_core):
    assert [c.env_name for c in page.cards()] == [e.name for e in fake_core.config.load().environments]
    coll = page.card("coll")
    assert "39" in coll.local_label.text() and "41 MB" in coll.local_label.text()
    assert "18/09/2026" in coll.latest_label.text()
    assert coll.index_label.text() == strings.SYNC_CARD_INDEX_OK
    assert "example.invalid" in coll.url_label.toolTip()


def test_the_cards_are_rebuilt_when_the_configuration_changes(page, fake_core):
    import dataclasses

    from qtrequestory.ui.contracts import Environment

    cfg = dataclasses.replace(
        fake_core.config.load(),
        environments=[Environment("prod", "https://example.invalid/prod/"),
                      Environment("off", "https://example.invalid/off/", enabled=False)],
    )
    fake_core.config.save(cfg)  # Impostazioni saves, then broadcasts
    page.on_config_changed(cfg)
    assert [c.env_name for c in page.cards()] == ["prod"], "a disabled env has no card"
    assert [a.text() for a in page.sync_menu.actions() if not a.isSeparator()] == [
        strings.SYNC_MENU_ALL, strings.SYNC_MENU_ONLY.format(env="prod"),
        strings.SYNC_MENU_DRY_RUN,
    ], "the menu follows the same list"


@pytest.mark.parametrize(
    ("setup", "expected", "kind"),
    [
        (dict(fresh=True), strings.SYNC_PILL_FRESH, ec.PILL_FRESH),
        (dict(fresh=False, last_success=datetime(2026, 9, 21, 15, 48)),
         strings.SYNC_PILL_STALE, ec.PILL_STALE),
        (dict(fresh=False, last_success=None), strings.SYNC_PILL_NEVER, ec.PILL_NEVER),
    ],
)
def test_the_pill_reads_the_status_the_core_reported(qtbot, setup, expected, kind):
    card = EnvCard("coll", "https://example.invalid/coll/")
    qtbot.addWidget(card)
    base = dict(env="coll", last_success=datetime(2026, 9, 22, 11, 23), fresh=False,
                n_local_files=3, local_bytes=MB, latest_day=None, index_pending=0)
    card.set_status(EnvStatus(**{**base, **setup}))
    assert card.pill.text() == expected
    assert card.pill_kind == kind


def test_the_other_three_pill_states_are_running_unreachable_and_errors(qtbot):
    card = EnvCard("coll", "https://example.invalid/coll/")
    qtbot.addWidget(card)
    card.set_running(True)
    assert card.pill.text() == strings.SYNC_PILL_RUNNING and card.pill_kind == ec.PILL_RUNNING
    card.set_running(False)
    card.set_outcome("unreachable")
    assert card.pill.text() == strings.SYNC_PILL_UNREACHABLE
    assert card.pill_kind == ec.PILL_UNREACHABLE
    card.set_outcome("errors", failed=3)
    assert card.pill.text() == strings.SYNC_PILL_ERRORS.format(n=3)
    assert card.pill_kind == ec.PILL_ERRORS
    card.set_outcome("errors", failed=1)
    assert card.pill.text() == strings.SYNC_PILL_ERROR_ONE


def test_a_new_run_clears_the_previous_verdict(qtbot):
    card = EnvCard("coll", "https://example.invalid/coll/")
    qtbot.addWidget(card)
    card.set_outcome("unreachable")
    card.set_running(True)
    card.set_running(False)
    assert card.pill_kind != ec.PILL_UNREACHABLE, "the old outcome must not survive a new run"


def test_the_pill_colours_are_muted_and_never_red(qtbot, qapp):
    grey = ec.pill_color(ec.PILL_UNREACHABLE)
    amber = ec.pill_color(ec.PILL_ERRORS)
    assert amber.name().lower() in (ec.AMBER_LIGHT.lower(), ec.AMBER_DARK.lower())
    assert amber.red() > amber.blue(), "amber, not red: still much more green than blue"
    assert amber.green() > amber.blue()
    assert grey.red() == grey.green() == grey.blue() or grey != amber
    for kind in (ec.PILL_FRESH, ec.PILL_STALE, ec.PILL_NEVER, ec.PILL_RUNNING,
                 ec.PILL_UNREACHABLE, ec.PILL_ERRORS):
        colour = ec.pill_color(kind)
        assert not (colour.red() > 200 and colour.green() < 80 and colour.blue() < 80), kind


def test_the_index_backlog_is_shown_on_the_card(qtbot):
    card = EnvCard("coll", "https://example.invalid/coll/")
    qtbot.addWidget(card)
    card.set_status(EnvStatus(env="coll", last_success=None, fresh=False, n_local_files=0,
                              local_bytes=0, latest_day=None, index_pending=1))
    assert card.index_label.text() == strings.SYNC_CARD_INDEX_PENDING.format(n=1)


# ---------------------------------------------------------- progress strip ---

def test_the_strip_totals_come_from_remote_index_read(page):
    page.handle_event(SyncStarted(("coll",), False))
    page.handle_event(EnvStarted("coll"))
    page.handle_event(RemoteIndexRead("coll", n_daily=4, n_empty=1, n_loose=2,
                                      bytes_to_download=8 * MB))
    page.handle_event(FileStarted("coll", "20260918.txt", 8 * MB))
    page.handle_event(FileProgress("coll", "20260918.txt", 2 * MB, 8 * MB))

    assert "coll" in page.progress_label.text()
    assert "20260918.txt" in page.progress_label.text()
    assert "file 1 di 4" in page.totals_label.text()
    assert "2 MB/8 MB" in page.totals_label.text()
    assert page.progress_bar.value() == 25


def test_the_indexing_phase_takes_over_the_same_strip(page):
    page.handle_event(SyncStarted(("coll",), False))
    page.handle_event(IndexStarted(2))
    page.handle_event(IndexFileScanned(Path("mirror/20260918.txt"), 7, 1, 2))
    assert "20260918.txt" in page.progress_label.text()
    assert "file 1 di 2" in page.totals_label.text()
    assert page.rate_label.text() == "", "no MB/s while scanning files"


def test_a_sync_drives_the_strip_and_fills_the_registro(qtbot, page, fake_core):
    seen: list[str] = []
    page.start_sync()
    page.sync_job.signals.progress.connect(lambda ev: seen.append(page.progress_label.text()))
    with qtbot.waitSignal(page.sync_job.signals.finished, timeout=TIMEOUT):
        pass

    assert any("20260918.txt" in text for text in seen), "the current file must be shown"
    log = page.log_view.toPlainText()
    assert "scaricato 20260918.txt" in log
    assert "index letto" in log
    assert page.progress_bar.isHidden(), "the strip is put away when the run ends"
    assert fake_core.sync.runs[-1] == {"envs": ("coll", "svil"), "force": True, "dry_run": False}


def test_the_registro_starts_from_the_tail_of_sync_log(page, fake_core):
    assert fake_core.sync.log_lines[-1] in page.log_view.toPlainText()
    assert page.log_view.maximumBlockCount() == 2000
    assert page.log_view.isReadOnly()


def test_the_menu_offers_every_environment_and_the_dry_run(qtbot, page, fake_core):
    labels = [a.text() for a in page.sync_menu.actions() if not a.isSeparator()]
    assert labels[0] == strings.SYNC_MENU_ALL
    assert strings.SYNC_MENU_ONLY.format(env="coll") in labels
    assert labels[-1] == strings.SYNC_MENU_DRY_RUN

    dry = page.sync_menu.actions()[-1]
    dry.trigger()
    with qtbot.waitSignal(page.sync_job.signals.finished, timeout=TIMEOUT):
        pass
    assert fake_core.sync.runs[-1]["dry_run"] is True


def test_one_environment_only_runs_that_one(qtbot, page, fake_core):
    only = next(a for a in page.sync_menu.actions()
                if a.text() == strings.SYNC_MENU_ONLY.format(env="svil"))
    only.trigger()
    with qtbot.waitSignal(page.sync_job.signals.finished, timeout=TIMEOUT):
        pass
    assert fake_core.sync.runs[-1]["envs"] == ("svil",)


# ------------------------------------------------------------------ cancel ---

def test_cancel_stops_the_run_and_says_so(qtbot, page, fake_core):
    fake_core.sync.step_delay = 0.02
    during: list[str] = []
    page.start_sync()

    def on_event(ev) -> None:
        if isinstance(ev, FileStarted) and not page.sync_job.token.is_set():
            page.cancel()
            during.append(page.progress_label.text())

    page.sync_job.signals.progress.connect(on_event)
    with qtbot.waitSignal(page.sync_job.signals.finished, timeout=TIMEOUT):
        pass

    assert during == [strings.SYNC_PROGRESS_CANCELLING]
    assert page.outcome_label.text() == strings.SYNC_CANCELLED
    assert not page.cancel_button.isEnabled()
    assert page.sync_button.isEnabled()


def test_the_cancel_button_only_lives_while_a_run_does(qtbot, page):
    assert not page.cancel_button.isEnabled()
    page.start_sync()
    assert page.cancel_button.isEnabled()
    assert not page.sync_button.isEnabled()
    with qtbot.waitSignal(page.sync_job.signals.finished, timeout=TIMEOUT):
        pass
    assert not page.cancel_button.isEnabled()


# ------------------------------------------------------------- environments ---

def test_an_unreachable_environment_gets_a_grey_pill_and_calm_wording(qtbot, page, fake_core):
    fake_core.sync.set_unreachable("coll")
    run_to_completion(qtbot, page)

    card = page.card("coll")
    assert card.pill.text() == strings.SYNC_PILL_UNREACHABLE
    assert card.pill_kind == ec.PILL_UNREACHABLE
    assert ec.pill_color(ec.PILL_UNREACHABLE) != ec.pill_color(ec.PILL_ERRORS)
    assert "riprovo al prossimo giro" in page.log_view.toPlainText()
    assert page.card("svil").pill_kind != ec.PILL_UNREACHABLE


def test_a_failing_environment_shows_the_amber_pill(qtbot, page, fake_core):
    fake_core.sync.set_failing("coll", 2)
    run_to_completion(qtbot, page)
    assert page.card("coll").pill.text() == strings.SYNC_PILL_ERRORS.format(n=2)
    assert page.outcome_label.text() == strings.SYNC_DONE_ERRORS


def test_the_summary_names_every_environment(qtbot, page, fake_core):
    fake_core.sync.set_unreachable("coll")
    run_to_completion(qtbot, page)
    summary = page.summaries[-1]
    assert summary.startswith("coll: ") and "svil: " in summary
    assert strings.SYNC_WHEN_UNREACHABLE in summary


# --------------------------------------------------------------- auto sync ---

def test_ticking_the_checkbox_registers_the_task_in_a_worker(qtbot, page, fake_core):
    page.auto_check.setChecked(True)
    assert page.scheduler_job is not None
    with qtbot.waitSignal(page.scheduler_job.signals.finished, timeout=TIMEOUT):
        pass
    assert fake_core.scheduler.register_calls == 1
    assert strings.SYNC_AUTO_ON in page.auto_status.text()

    page.auto_check.setChecked(False)
    with qtbot.waitSignal(page.scheduler_job.signals.finished, timeout=TIMEOUT):
        pass
    assert fake_core.scheduler.unregister_calls == 1
    assert page.auto_status.text() == strings.SYNC_AUTO_OFF
    assert page.auto_check.isEnabled(), "the controls come back once schtasks answers"


def test_the_checkbox_is_locked_while_schtasks_is_running(qtbot, page, fake_core):
    """schtasks takes no cancel token: two calls in flight could land in either
    order, so a second change is not offered until the first one is back."""
    page.auto_check.setChecked(True)
    assert not page.auto_check.isEnabled()
    with qtbot.waitSignal(page.scheduler_job.signals.finished, timeout=TIMEOUT):
        pass
    assert page.auto_check.isEnabled()


def test_the_checkbox_starts_from_the_task_the_system_already_has(qtbot, fake_core, runner, window):
    fake_core.scheduler.set_status(registered=True, exe_matches=True, state="Pronto",
                                   next_run="domani 09:00")
    widget = SyncPage(fake_core, runner, window)
    qtbot.addWidget(widget)
    assert widget.auto_check.isChecked()
    assert "domani 09:00" in widget.auto_status.text()


def test_a_refused_schtasks_call_leaves_the_checkbox_telling_the_truth(qtbot, page, fake_core,
                                                                      runner):
    """``scheduler`` is exclusive (Impostazioni re-registers through the same
    name), and a refused submit runs nothing: the box must not stay ticked on a
    registration that never happened."""
    import threading

    from qtrequestory.ui.workers import SCHEDULER_JOB

    gate = threading.Event()
    busy = runner.submit(SCHEDULER_JOB, lambda: gate.wait(3.0))

    page.auto_check.setChecked(True)

    assert fake_core.scheduler.register_calls == 0
    assert not page.auto_check.isChecked()
    gate.set()
    with qtbot.waitSignal(busy.signals.finished, timeout=TIMEOUT):
        pass


def test_the_status_line_describes_the_schedule_that_is_configured(qtbot, page, fake_core):
    """Not the one that used to be compiled in: a user who moved the start to
    07:30 must read 07:30 here, or the line is worse than no line at all."""
    import dataclasses

    from qtrequestory.ui.contracts import ScheduleSettings

    fake_core.config.config = dataclasses.replace(
        fake_core.config.load(),
        schedule=ScheduleSettings(start_time="07:30", repeat_every_h=2, repeat_for_h=6,
                                  run_at_logon=False),
    )
    fake_core.scheduler.set_status(registered=True, exe_matches=True, state="Pronto")
    page.refresh_scheduler()

    line = page.auto_status.text()
    assert strings.SYNC_AUTO_ON in line
    assert "Ogni giorno alle 07:30, riprova ogni 2 ore fino alle 13:30" in line
    assert "login" not in line
    assert ". " not in line, "the sentence is framed by ' · ', not closed mid-line"


def test_saving_a_new_schedule_repaints_the_status_line(qtbot, page, fake_core):
    """Impostazioni broadcasts ``config_changed``; the line must follow it
    without waiting for the page to be rebuilt."""
    import dataclasses

    from qtrequestory.ui.contracts import ScheduleSettings

    fake_core.scheduler.set_status(registered=True, exe_matches=True, state="Pronto")
    page.refresh_scheduler()
    assert "09:00" in page.auto_status.text()

    fake_core.config.config = dataclasses.replace(
        fake_core.config.load(), schedule=ScheduleSettings(start_time="06:00", repeat_for_h=0)
    )
    page.on_config_changed(fake_core.config.load())
    assert "Ogni giorno alle 06:00, e al login" in page.auto_status.text()


def test_an_exe_mismatch_is_shown_with_a_way_out(qtbot, page, fake_core):
    fake_core.scheduler.exe = Path(r"C:\vecchio\qtRequestory.exe")
    fake_core.scheduler.set_status(registered=True, exe_matches=False,
                                   command=Path(r"C:\vecchio\qtRequestory.exe"))
    page.refresh_scheduler()
    assert not page.exe_warning.isHidden()
    assert "vecchio" in page.exe_warning.text()
    assert not page.exe_button.isHidden()

    page.exe_button.click()
    with qtbot.waitSignal(page.scheduler_job.signals.finished, timeout=TIMEOUT):
        pass
    assert fake_core.scheduler.register_calls == 1
    assert page.exe_warning.isHidden(), "a matching exe hides the warning again"


def test_an_unstable_location_is_explained_before_registering(qtbot, page, fake_core):
    fake_core.scheduler.unstable_reason = "L'eseguibile è in %TEMP%."
    box = page.build_unstable_dialog("L'eseguibile è in %TEMP%.")
    qtbot.addWidget(box)
    assert "%TEMP%" in box.text()
    assert box.windowTitle() == strings.SYNC_AUTO_UNSTABLE_TITLE


def test_refusing_the_unstable_warning_leaves_the_task_alone(qtbot, page, fake_core, monkeypatch):
    fake_core.scheduler.unstable_reason = "L'eseguibile è in %TEMP%."
    monkeypatch.setattr(page, "confirm_unstable", lambda reason: False)
    page.auto_check.setChecked(True)
    assert fake_core.scheduler.register_calls == 0
    assert not page.auto_check.isChecked(), "the checkbox goes back to where it was"
    assert page.scheduler_job is None


# -------------------------------------------------------------------- lock ---

def test_starting_a_sync_while_the_task_holds_the_lock_says_why(page, fake_core, window):
    fake_core.sync.set_lock_holder("attività pianificata (PID 4242)")
    page.start_sync()
    assert page.sync_job is None
    assert fake_core.sync.runs == []
    assert window.status[-1] == strings.SYNC_LOCK_HELD


def test_a_lock_held_by_the_scheduled_run_disables_the_button(page, fake_core):
    fake_core.sync.set_lock_holder("attività pianificata (PID 4242)")
    page.refresh_lock()
    assert not page.sync_button.isEnabled()
    assert page.lock_label.text() == strings.SYNC_LOCK_HELD
    assert not page.lock_label.isHidden()

    fake_core.sync.set_lock_holder(None)
    page.refresh_lock()
    assert page.sync_button.isEnabled()
    assert page.lock_label.isHidden()


def test_the_lock_is_polled_on_a_timer(page):
    assert page.lock_timer.isActive()
    assert page.lock_timer.interval() == SyncPage.LOCK_POLL_MS
    assert page.lock_timer.parent() is page, "the timer dies with the page"


def test_a_held_lock_never_fights_the_gui_job(qtbot, page, fake_core):
    """While we are the ones syncing, the lock text would be a lie."""
    page.start_sync()
    fake_core.sync.set_lock_holder("noi stessi")
    page.refresh_lock()
    assert page.lock_label.isHidden()
    with qtbot.waitSignal(page.sync_job.signals.finished, timeout=TIMEOUT):
        pass


# ------------------------------------------------------------------ errors ---

def test_a_failing_core_call_becomes_one_calm_line(qtbot, page, fake_core, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("disco pieno")

    monkeypatch.setattr(fake_core.sync, "run", boom)
    run_to_completion(qtbot, page)
    assert "disco pieno" in page.outcome_label.text()
    assert not page.cancel_button.isEnabled()
    assert page.sync_button.isEnabled()


def test_a_second_sync_is_refused_while_one_runs(qtbot, page, fake_core):
    page.start_sync()
    first = page.sync_job
    page.start_sync()
    assert page.sync_job is first, "the runner refuses the second one"
    with qtbot.waitSignal(first.signals.finished, timeout=TIMEOUT):
        pass
    assert len(fake_core.sync.runs) == 1


# ------------------------------------------------------------- the button ---

def test_the_button_syncs_on_click_and_opens_its_menu_on_the_arrow(page):
    """MenuButtonPopup: "Sincronizza ora" is one click, the variants are two."""
    assert page.sync_button.popupMode() == QToolButton.ToolButtonPopupMode.MenuButtonPopup
    assert page.sync_button.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextOnly
    assert page.sync_button.text() == strings.SYNC_BTN_NOW
    assert page.sync_button.menu() is page.sync_menu


# ------------------------------------------------------------------ theme ---

def test_a_theme_switch_re_tunes_every_pill(page):
    """The pill colour is the one thing the page paints itself."""
    for card in page.cards():
        card.pill.setStyleSheet("color: #ff0000;")
    page.retune()
    for card in page.cards():
        assert card.pill.styleSheet() == f"color: {ec.pill_color(card.pill_kind).name()};"
