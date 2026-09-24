"""The Sincronizzazione page: auto-sync card, env cards, coverage, registro, lock.

Everything runs against ``fake_core`` — the scripted sync of
``tests/fakes/fake_core.py`` — and never sleeps waiting for it: a test that
needs to act *during* a run hooks the job's ``progress`` signal and reacts to a
specific event, then waits for ``finished``. Assertions about progress
arithmetic feed the events in by hand through :meth:`SyncPage.handle_event`.

The scheduler is always the fake one: the user's real scheduled tasks are live
on this machine and no test may touch them.
"""
from __future__ import annotations

import logging
import threading
from datetime import date, datetime, timedelta
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
from qtrequestory.ui.pages import coverage_strip as cs
from qtrequestory.ui.pages import sync_badge as sb
from qtrequestory.ui.pages.env_card import EnvCard
from qtrequestory.ui.pages.sync_page import SyncPage

MB = 1_048_576
TIMEOUT = 15_000


class FakeSettingsPage:
    def __init__(self) -> None:
        self.sections: list[str] = []

    def show_section(self, key: str) -> None:
        self.sections.append(key)


class FakeWindow:
    """What the page uses of ``MainWindow``: status line, toast, page switch."""

    def __init__(self) -> None:
        self.status: list[str] = []
        self.toasts: list[tuple[str, str]] = []
        self.shown: list[str] = []
        self.settings = FakeSettingsPage()

    def set_status(self, text: str, ms: int = 4000) -> None:
        self.status.append(text)

    def show_toast(self, text: str, tone: str = "neutral", ms: int = 0) -> None:
        self.toasts.append((text, tone))

    def show_page(self, key: str) -> None:
        self.shown.append(key)

    def page(self, key: str):
        return self.settings if key == "settings" else None


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def weekdays_back(n: int, skip: tuple[date, ...] = ()) -> set[date]:
    """Every weekday of the last ``n`` days before today, minus ``skip``."""
    today = date.today()
    days = {today - timedelta(days=i) for i in range(1, n + 1)}
    return {d for d in days if d.weekday() < 5 and d not in skip}


@pytest.fixture
def window() -> FakeWindow:
    return FakeWindow()


@pytest.fixture
def complete_mirror(fake_core):
    """No gaps in either env, so no banner and no "da scaricare" by default."""
    for env in ("coll", "svil"):
        fake_core.index.set_local_days(env, weekdays_back(40))


def wait_status(qtbot, page: SyncPage) -> None:
    job = page.auto_card.status_job
    if job is not None and job.is_running():
        with qtbot.waitSignal(job.signals.finished, timeout=TIMEOUT):
            pass
    qtbot.waitUntil(lambda: page.auto_card.task is not None, timeout=TIMEOUT)


def wait_probe(qtbot, page: SyncPage) -> None:
    if page.reach_job is not None:
        qtbot.waitUntil(lambda: not page.reach_job.is_running(), timeout=TIMEOUT)
        qtbot.wait(20)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def page(qtbot, fake_core, runner, window, complete_mirror, clock) -> SyncPage:
    widget = SyncPage(fake_core, runner, window, clock=clock)
    qtbot.addWidget(widget)
    widget.resize(1100, 800)
    widget.show()
    widget.summaries = []
    widget.summary_changed.connect(widget.summaries.append)
    wait_status(qtbot, widget)
    wait_probe(qtbot, widget)
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
    assert hasattr(page.state_changed, "connect")
    assert callable(page.emit_initial_state)
    assert callable(page.start_sync)
    assert callable(page.on_config_changed)
    assert callable(page.progress_counts)


# ------------------------------------------------------------------- cards ---

def test_one_card_per_enabled_environment_with_labelled_rows(page, fake_core):
    assert [c.env_name for c in page.cards()] == [e.name for e in fake_core.config.load().environments]
    coll = page.card("coll")
    assert [label.text() for label in coll.row_labels[:2]] == [
        "Ultima sincronizzazione", "Archivio locale"]
    first = min(weekdays_back(40)).strftime("%d/%m/%Y")
    assert coll.archive_value.text() == f"39 giorni · 41 MB · dal {first}"
    assert coll.last_value.text().endswith("· 2 file scaricati")
    assert coll.index_value.isHidden(), "no backlog, no row"
    assert "example.invalid" in coll.host_label.toolTip()
    assert coll.property("role") == "card"
    assert coll.name_label.property("role") == "section"


def test_the_index_backlog_gets_its_own_row(qtbot):
    card = EnvCard("coll", "https://example.invalid/coll/")
    qtbot.addWidget(card)
    card.set_status(EnvStatus(env="coll", last_success=None, fresh=False, n_local_files=0,
                              local_bytes=0, latest_day=None, index_pending=3), None)
    assert card.index_value.text() == strings.SYNC_CARD_INDEX_PENDING.format(n=3)
    assert not card.index_value.isHidden()
    assert card.archive_value.text() == strings.SYNC_CARD_ARCHIVE_EMPTY


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


def test_the_cards_sit_in_two_columns_and_stack_when_narrow(qtbot, page):
    assert page.columns() == 2
    page.resize(500, 800)
    qtbot.waitUntil(lambda: page.columns() == 1, timeout=TIMEOUT)
    page.resize(1200, 800)
    qtbot.waitUntil(lambda: page.columns() == 2, timeout=TIMEOUT)


def test_a_badge_is_a_theme_pill_with_a_readable_text(qtbot):
    card = EnvCard("coll", "https://example.invalid/coll/")
    qtbot.addWidget(card)
    card.set_badge(sb.badge_for(None, pending=2))
    assert card.pill.text() == "2 da scaricare"
    assert card.pill.property("pill") == "warn"
    assert card.pill.styleSheet() == "", "colours come from the theme stylesheet"
    card.set_badge(sb.badge_for(None))
    assert (card.pill.text(), card.pill.property("pill")) == ("mai sincronizzato", "neutral")


def test_the_pills_paint_nothing_themselves(page):
    for card in page.cards():
        assert card.pill.styleSheet() == ""
        assert card.pill.property("pill") in ("ok", "warn", "neutral")


# --------------------------------------------------------------- coverage ---

def test_each_card_shows_thirty_days_of_coverage(page):
    strip = page.card("coll").strip
    kinds = strip.kinds()
    assert len(kinds) == 30
    assert kinds[-1] == (date.today(), cs.TODAY)
    assert not {cs.PENDING, cs.LOST} & {k for _d, k in kinds}
    assert strip.tooltip_at(29) == f"{date.today():%d/%m/%Y}: oggi (arriva domani)"
    assert page.legend.shown() == [
        "log presente", "weekend", "oggi (arriva domani)"], "only what a card draws"


def test_the_legend_explains_the_outline_only_when_a_card_shows_it(page, fake_core):
    """svil has no archive before 40 days ago: the oldest squares of a young
    archive are empty outlines, and the legend must say what they mean."""
    fake_core.index.set_local_days("svil", weekdays_back(10))
    page.refresh_cards()
    visible = page.legend.shown()
    assert visible[-1] == strings.SYNC_LEGEND_BEFORE
    fake_core.index.set_local_days("svil", weekdays_back(40))
    page.refresh_cards()
    assert strings.SYNC_LEGEND_BEFORE not in page.legend.shown()


def test_a_pending_day_is_amber_on_the_strip_named_in_a_banner_and_on_the_badge(
        qtbot, page, fake_core):
    gap = max(weekdays_back(10))  # the most recent weekday before today
    fake_core.index.set_local_days("svil", weekdays_back(40, skip=(gap,)))
    fake_core.index.set_server_days("svil", listed={gap})  # still on the server: pending
    fake_core.sync.set_env_status("svil", last_success=datetime.now(), n_local_files=28,
                                  local_bytes=MB)
    assert page.banners.isHidden()
    page.refresh_cards()

    svil = page.card("svil")
    assert dict(svil.strip.kinds())[gap] == cs.PENDING
    assert svil.pill.text() == "1 da scaricare" and svil.pill.property("pill") == "warn"
    assert not page.banners.pending_banner.isHidden() and page.banners.lost_banner.isHidden()
    text = page.banners.pending_label.text()
    assert "svil" in text and gap.strftime("%d/%m/%Y") in text and "ancora sul server" in text
    assert "coll" not in text
    assert strings.SYNC_LEGEND_PENDING in page.legend.shown()


def test_the_pending_banner_syncs_only_the_envs_concerned(qtbot, page, fake_core):
    gap = max(weekdays_back(10))
    fake_core.index.set_local_days("svil", weekdays_back(40, skip=(gap,)))
    fake_core.index.set_server_days("svil", listed={gap})
    page.refresh_cards()
    page.banners.sync_button.click()
    assert page.sync_job is not None
    assert not page.banners.sync_button.isEnabled(), "one run at a time"
    with qtbot.waitSignal(page.sync_job.signals.finished, timeout=TIMEOUT):
        pass
    assert fake_core.sync.runs[-1]["envs"] == ("svil",)


def test_a_lost_day_is_red_everywhere_and_says_it_cannot_be_recovered(qtbot, page, fake_core):
    gap = max(weekdays_back(10))
    fake_core.index.set_local_days("svil", weekdays_back(40, skip=(gap,)))
    fake_core.index.set_server_days("svil", listed=(), seen={gap})  # purged before download
    page.refresh_cards()
    svil = page.card("svil")
    assert dict(svil.strip.kinds())[gap] == cs.LOST
    assert (svil.pill.text(), svil.pill.property("pill")) == ("1 giorno perso", "bad")
    assert page.banners.pending_banner.isHidden()
    assert "non recuperabile" in page.banners.lost_label.text()
    assert page.banners.lost_banner.property("role") == "syncBannerBad"
    assert ("svil", "bad", "1 giorno perso") in page.presenter.state(), "the chip agrees"


def test_a_quiet_day_is_grey_and_raises_nothing(qtbot, page, fake_core):
    quiet = max(weekdays_back(10))
    fake_core.index.set_local_days("svil", weekdays_back(40, skip=(quiet,)), empty={quiet})
    page.refresh_cards()
    assert dict(page.card("svil").strip.kinds())[quiet] == cs.EMPTY
    assert page.banners.isHidden()
    assert strings.SYNC_LEGEND_EMPTY in page.legend.shown()


# ------------------------------------------------------------ during a run ---

def test_the_running_env_has_the_progress_and_the_other_one_waits(qtbot, page, fake_core):
    fake_core.sync.step_delay = 0.02
    seen: list[tuple] = []
    page.start_sync()

    def on_event(ev) -> None:
        if isinstance(ev, FileStarted) and ev.env == "coll" and not seen:
            coll, svil = page.card("coll"), page.card("svil")
            seen.append((coll.pill_kind, svil.pill_kind, coll.progress_box.isHidden(),
                         svil.progress_box.isHidden(), coll.progress_label.text()))

    page.sync_job.signals.progress.connect(on_event)
    with qtbot.waitSignal(page.sync_job.signals.finished, timeout=TIMEOUT):
        pass
    [(coll_kind, svil_kind, coll_hidden, svil_hidden, label)] = seen
    assert (coll_kind, svil_kind) == (sb.RUNNING, sb.QUEUED)
    assert not coll_hidden and svil_hidden, "only the running card shows progress"
    assert "20260918.txt" in label
    assert all(c.progress_box.isHidden() for c in page.cards()), "put away at the end"


def test_the_card_progress_comes_from_remote_index_read(page):
    page.presenter.begin_run(["coll"])
    page.handle_event(SyncStarted(("coll",), False))
    page.handle_event(EnvStarted("coll"))
    page.handle_event(RemoteIndexRead("coll", n_daily=4, n_empty=1, n_loose=2,
                                      bytes_to_download=8 * MB))
    page.handle_event(FileStarted("coll", "20260918.txt", 8 * MB))
    page.handle_event(FileProgress("coll", "20260918.txt", 2 * MB, 8 * MB))

    card = page.card("coll")
    assert card.progress_label.text() == "20260918.txt (8 MB)"
    assert "file 1 di 4" in card.totals_label.text()
    assert "2 MB/8 MB" in card.totals_label.text()
    assert card.progress_bar.value() == 25


def test_the_indexing_phase_is_told_under_the_cards(page):
    page.handle_event(SyncStarted(("coll",), False))
    page.handle_event(IndexStarted(2))
    page.handle_event(IndexFileScanned(Path("mirror/20260918.txt"), 7, 1, 2))
    assert "20260918.txt" in page.run_label.text()
    assert "file 1 di 2" in page.run_label.text()


def test_the_chip_says_in_corso_and_in_attesa_during_a_run(qtbot, page, fake_core):
    states: list[list] = []
    page.state_changed.connect(states.append)
    page.start_sync()
    queued = dict((env, (tone, text)) for env, tone, text in states[-1])
    assert queued["coll"] == ("neutral", strings.SYNC_CHIP_QUEUED)
    assert queued["svil"] == ("neutral", strings.SYNC_CHIP_QUEUED)
    with qtbot.waitSignal(page.sync_job.signals.finished, timeout=TIMEOUT):
        pass
    assert any(dict((e, t) for e, _tone, t in s).get("coll") == strings.SYNC_CHIP_RUNNING
               for s in states)
    after = dict((env, text) for env, _tone, text in states[-1])
    assert strings.SYNC_CHIP_RUNNING not in after.values()
    assert strings.SYNC_CHIP_QUEUED not in after.values()


def _gap_in_coll(page, fake_core):
    gap = max(weekdays_back(10))
    fake_core.index.set_local_days("coll", weekdays_back(40, skip=(gap,)))
    fake_core.index.set_server_days("coll", listed={gap})  # still on the server: pending


def _lost_in_coll(page, fake_core):
    gap = max(weekdays_back(10))
    fake_core.index.set_local_days("coll", weekdays_back(40, skip=(gap,)))
    fake_core.index.set_server_days("coll", listed=(), seen={gap})  # purged first


BADGE_SETUPS = {
    sb.FRESH: lambda page, fc: fc.sync.set_env_status("coll", fresh=True),
    sb.STALE: lambda page, fc: fc.sync.set_env_status(
        "coll", fresh=False, last_success=datetime.now() - timedelta(days=1)),
    sb.NEVER: lambda page, fc: fc.sync.set_env_status("coll", fresh=False, last_success=None),
    sb.RUNNING: lambda page, fc: setattr(page.presenter, "running", "coll"),
    sb.QUEUED: lambda page, fc: page.presenter.queued.add("coll"),
    sb.PENDING: _gap_in_coll,
    sb.LOST: _lost_in_coll,
    sb.UNREACHABLE: lambda page, fc: page.presenter.reachable.__setitem__("coll", False),
    sb.ERRORS: lambda page, fc: (page.presenter.outcomes.__setitem__("coll", "errors"),
                                 page.presenter.failures.__setitem__("coll", 2)),
}


@pytest.mark.parametrize("kind", sorted(BADGE_SETUPS))
def test_the_chip_dot_agrees_with_the_card_badge_for_every_kind(page, fake_core, kind):
    BADGE_SETUPS[kind](page, fake_core)
    page.refresh_cards()
    card = page.card("coll")
    assert card.pill_kind == kind
    tones = dict((env, tone) for env, tone, _ in page.presenter.state())
    assert tones["coll"] == card.pill.property("pill")
    assert (tones["coll"] == "bad") == (kind == sb.LOST), "red only for a lost day"


def test_the_chip_tone_always_agrees_with_the_card_badge(qtbot, page, fake_core):
    fake_core.sync.set_unreachable("svil")
    fake_core.sync.set_env_status("coll", fresh=True, last_success=datetime.now())
    run_to_completion(qtbot, page)
    tones = dict((env, tone) for env, tone, _ in page.presenter.state())
    for card in page.cards():
        assert tones[card.env_name] == card.pill.property("pill"), card.env_name


# ----------------------------------------------------------- final message ---

def test_completata_only_when_everything_went_fine(qtbot, page, window):
    run_to_completion(qtbot, page)
    assert page.run_label.text() == "Sincronizzazione completata"
    assert window.toasts[-1] == ("Sincronizzazione completata", "ok")
    assert page.log_panel.header().endswith("· completata")
    assert not page.log_panel.is_expanded()


def test_an_unreachable_env_is_named_in_the_final_message(qtbot, page, fake_core, window):
    fake_core.sync.set_unreachable("svil")
    run_to_completion(qtbot, page)
    assert page.run_label.text() == "Completata · svil non raggiungibile"
    assert window.toasts[-1] == ("Completata · svil non raggiungibile", "warn")
    card = page.card("svil")
    assert card.pill.text() == "non raggiungibile" and card.pill.property("pill") == "warn"
    assert page.card("coll").pill_kind != sb.UNREACHABLE
    assert "riprovo al prossimo giro" in page.log_panel.text()
    assert not page.log_panel.is_expanded(), "off the VPN is not an error worth opening"


def test_failed_files_are_named_and_open_the_registro(qtbot, page, fake_core):
    fake_core.sync.set_failing("coll", 2)
    run_to_completion(qtbot, page)
    assert page.run_label.text() == "Completata · coll con 2 errori"
    assert page.card("coll").pill.text() == "errori"
    assert page.card("coll").pill.property("pill") == "warn", "amber, never red"
    assert page.log_panel.is_expanded(), "the registro opens by itself on errors"


def test_a_failing_core_call_becomes_one_calm_line(qtbot, page, fake_core, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("disco pieno")

    monkeypatch.setattr(fake_core.sync, "run", boom)
    run_to_completion(qtbot, page)
    assert "disco pieno" in page.run_label.text()
    assert page.log_panel.is_expanded()
    assert page.cancel_button.isHidden()
    assert page.sync_button.isEnabled()


# ------------------------------------------------------------------ registro ---

def test_the_registro_is_collapsed_mono_and_starts_from_sync_log(page, fake_core):
    panel = page.log_panel
    assert not panel.is_expanded() and panel.log_view.isHidden()
    assert panel.header().startswith("Registro dell'ultima esecuzione")
    assert fake_core.sync.log_lines[-1] in panel.text()
    assert panel.log_view.maximumBlockCount() == 2000
    assert panel.log_view.isReadOnly()
    from qtrequestory.ui import theme
    assert panel.log_view.font().families() == theme.mono_font().families()
    panel.toggle.click()
    assert panel.is_expanded() and not panel.log_view.isHidden()


def test_a_run_writes_its_lines_in_the_registro(qtbot, page):
    run_to_completion(qtbot, page)
    log = page.log_panel.text()
    assert "scaricato 20260918.txt (4 MB)" in log
    assert "elenco del server letto" in log and "index letto" not in log


# ---------------------------------------------------------------- the menu ---

def test_the_menu_offers_every_environment_and_the_dry_run(qtbot, page, fake_core):
    labels = [a.text() for a in page.sync_menu.actions() if not a.isSeparator()]
    assert labels[0] == strings.SYNC_MENU_ALL
    assert strings.SYNC_MENU_ONLY.format(env="coll") in labels
    assert labels[-1] == strings.SYNC_MENU_DRY_RUN

    page.sync_menu.actions()[-1].trigger()
    with qtbot.waitSignal(page.sync_job.signals.finished, timeout=TIMEOUT):
        pass
    assert fake_core.sync.runs[-1]["dry_run"] is True


def test_one_environment_only_runs_that_one(qtbot, page, fake_core):
    only = next(a for a in page.sync_menu.actions()
                if a.text() == strings.SYNC_MENU_ONLY.format(env="svil"))
    only.trigger()
    assert page.card("coll").pill_kind not in (sb.QUEUED, sb.RUNNING)
    with qtbot.waitSignal(page.sync_job.signals.finished, timeout=TIMEOUT):
        pass
    assert fake_core.sync.runs[-1]["envs"] == ("svil",)


def test_sincronizza_ora_is_the_primary_split_button(page):
    button = page.sync_button
    assert button.popupMode() == QToolButton.ToolButtonPopupMode.MenuButtonPopup
    assert button.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextOnly
    assert button.text() == strings.SYNC_BTN_NOW
    assert button.menu() is page.sync_menu
    assert button.property("role") == "primary"


def test_a_click_syncs_every_enabled_environment_with_force(qtbot, page, fake_core):
    page.sync_button.click()
    with qtbot.waitSignal(page.sync_job.signals.finished, timeout=TIMEOUT):
        pass
    assert fake_core.sync.runs[-1] == {"envs": ("coll", "svil"), "force": True, "dry_run": False}


# ------------------------------------------------------------------ cancel ---

def test_annulla_exists_only_while_a_run_does(qtbot, page):
    assert page.cancel_button.isHidden()
    page.start_sync()
    assert not page.cancel_button.isHidden()
    assert not page.sync_button.isEnabled()
    with qtbot.waitSignal(page.sync_job.signals.finished, timeout=TIMEOUT):
        pass
    assert page.cancel_button.isHidden()
    assert page.sync_button.isEnabled()


def test_cancel_stops_the_run_and_says_so(qtbot, page, fake_core):
    fake_core.sync.step_delay = 0.02
    during: list[str] = []
    page.start_sync()

    def on_event(ev) -> None:
        if isinstance(ev, FileStarted) and not page.sync_job.token.is_set():
            page.cancel()
            during.append(page.run_label.text())

    page.sync_job.signals.progress.connect(on_event)
    with qtbot.waitSignal(page.sync_job.signals.finished, timeout=TIMEOUT):
        pass
    assert during == [strings.SYNC_PROGRESS_CANCELLING]
    assert page.run_label.text() == strings.SYNC_CANCELLED
    assert page.log_panel.header().endswith("· annullata")


def test_a_second_sync_is_refused_while_one_runs(qtbot, page, fake_core):
    page.start_sync()
    first = page.sync_job
    page.start_sync()
    assert page.sync_job is first, "the runner refuses the second one"
    with qtbot.waitSignal(first.signals.finished, timeout=TIMEOUT):
        pass
    assert len(fake_core.sync.runs) == 1


def test_start_sync_can_run_without_forcing(qtbot, page, fake_core):
    """The startup sync skips environments that are already fresh."""
    run_to_completion(qtbot, page, force=False)
    assert fake_core.sync.runs[-1]["force"] is False


# ----------------------------------------------------- reachability at rest ---

def test_an_unreachable_env_says_so_without_any_run(qtbot, fake_core, runner, window,
                                                     complete_mirror, clock):
    fake_core.sync.set_unreachable("svil")
    widget = SyncPage(fake_core, runner, window, clock=clock)
    qtbot.addWidget(widget)
    assert widget.reach_job is None, "nothing is probed before the page is shown"
    widget.show()
    wait_probe(qtbot, widget)
    qtbot.waitUntil(lambda: widget.card("svil").pill_kind == sb.UNREACHABLE, timeout=TIMEOUT)
    assert fake_core.sync.runs == []
    assert widget.card("coll").pill_kind != sb.UNREACHABLE


def test_the_probe_runs_at_most_every_five_minutes(qtbot, page, clock):
    first = page.reach_job
    assert first is not None
    page.hide()
    page.show()
    assert page.reach_job is first, "shown again within five minutes: no new probe"
    clock.now += SyncPage.REACHABILITY_INTERVAL_S + 1
    page.hide()
    page.show()
    assert page.reach_job is not first
    wait_probe(qtbot, page)


# ---------------------------------------------------- status bar and chip ---

def test_the_initial_state_is_one_toned_entry_per_environment(page, fake_core):
    fake_core.sync.set_env_status("coll", fresh=True,
                                  last_success=datetime.now().replace(second=0))
    states: list[list] = []
    page.state_changed.connect(states.append)
    page.emit_initial_state()
    [(coll, svil)] = [tuple(s) for s in states]
    assert coll[0] == "coll" and coll[1] == "ok" and coll[2].startswith("oggi ")
    assert svil == ("svil", "neutral", strings.SYNC_WHEN_NEVER)


def test_an_older_mirror_is_amber_never_red(page, fake_core):
    fake_core.sync.set_env_status("coll", last_success=datetime.now() - timedelta(days=1))
    page.refresh_cards()
    assert page.card("coll").pill_kind == sb.STALE
    assert dict((e, t) for e, t, _ in page.presenter.state())["coll"] == "warn"


def test_the_summary_names_every_environment(qtbot, page, fake_core):
    fake_core.sync.set_unreachable("coll")
    run_to_completion(qtbot, page)
    summary = page.summaries[-1]
    assert summary.startswith("coll: ") and "svil: " in summary
    assert strings.SYNC_WHEN_UNREACHABLE in summary


def test_the_status_bar_counts_the_files_during_a_sync(page, window):
    for ev in (SyncStarted(("coll",), False),
               RemoteIndexRead("coll", n_daily=48, n_empty=0, n_loose=0, bytes_to_download=MB)):
        page.handle_event(ev)
    for i in range(1, 4):
        page.handle_event(FileStarted("coll", f"2026010{i}.txt", MB))
    assert window.status[-1] == strings.SYNC_STATUS_PROGRESS.format(env="coll", i=3, n=48)


def test_the_status_bar_follows_the_index_phase(page, window):
    page.handle_event(IndexStarted(5))
    page.handle_event(IndexFileScanned(Path("x.txt"), 1, 2, 5))
    assert window.status[-1] == strings.SYNC_STATUS_INDEXING.format(i=2, n=5)


# --------------------------------------------------------------- auto sync ---

def test_the_task_status_is_read_off_the_gui_thread_and_cached(qtbot, fake_core, runner, window,
                                                                complete_mirror, monkeypatch):
    threads: list[int] = []
    real = fake_core.scheduler.status

    def status():
        threads.append(threading.get_ident())
        return real()

    monkeypatch.setattr(fake_core.scheduler, "status", status)
    widget = SyncPage(fake_core, runner, window)
    qtbot.addWidget(widget)
    card = widget.auto_card
    assert card.task is None
    assert card.status_label.text() == strings.SYNC_AUTO_CHECKING
    assert not card.switch.isEnabled()
    wait_status(qtbot, widget)
    assert threads and threading.get_ident() not in threads
    assert card.title_label.text() == strings.SYNC_AUTO_TITLE_OFF
    assert card.switch.isEnabled()


def test_the_card_starts_from_the_task_the_system_already_has(qtbot, fake_core, runner, window,
                                                               complete_mirror):
    fake_core.scheduler.set_status(registered=True, exe_matches=True, state="Pronto",
                                   next_run="24/09/2026 09:00")
    widget = SyncPage(fake_core, runner, window)
    qtbot.addWidget(widget)
    wait_status(qtbot, widget)
    card = widget.auto_card
    assert card.switch.isChecked()
    assert card.title_label.text() == strings.SYNC_AUTO_TITLE_ON
    assert "24/09/2026 09:00" in card.status_label.text()
    assert "Ogni giorno alle 09:00" in card.status_label.text()


def test_a_failing_status_read_is_a_banner_with_a_retry(qtbot, fake_core, runner, window,
                                                        complete_mirror, monkeypatch):
    from qtrequestory.ui.contracts import SchedulerError

    def broken():
        raise SchedulerError("schtasks non risponde")

    monkeypatch.setattr(fake_core.scheduler, "status", broken)
    widget = SyncPage(fake_core, runner, window)
    qtbot.addWidget(widget)
    card = widget.auto_card
    qtbot.waitUntil(lambda: not card.banner.isHidden(), timeout=TIMEOUT)
    assert "schtasks non risponde" in card.banner_label.text()
    monkeypatch.undo()
    card.retry_button.click()
    wait_status(qtbot, widget)
    assert card.banner.isHidden()


def test_the_switch_registers_the_task_in_a_worker(qtbot, page, fake_core):
    card = page.auto_card
    card.switch.click()
    assert card.scheduler_job is not None
    assert not card.switch.isEnabled(), "locked while schtasks runs"
    with qtbot.waitSignal(card.scheduler_job.signals.finished, timeout=TIMEOUT):
        pass
    wait_status(qtbot, page)
    qtbot.waitUntil(lambda: card.title_label.text() == strings.SYNC_AUTO_TITLE_ON, timeout=TIMEOUT)
    assert fake_core.scheduler.register_calls == 1
    assert card.switch.isChecked() and card.switch.isEnabled()

    card.switch.click()
    with qtbot.waitSignal(card.scheduler_job.signals.finished, timeout=TIMEOUT):
        pass
    qtbot.waitUntil(lambda: card.title_label.text() == strings.SYNC_AUTO_TITLE_OFF, timeout=TIMEOUT)
    assert fake_core.scheduler.unregister_calls == 1
    assert card.status_label.text() == strings.SYNC_AUTO_OFF_HINT


def test_a_refused_registration_is_not_lost(qtbot, page, fake_core, runner):
    """Impostazioni is re-registering: the switch goes back and the banner says
    why, with [Riprova] that really registers once the other call is over."""
    from qtrequestory.ui.workers import SCHEDULER_JOB

    gate = threading.Event()
    busy = runner.submit(SCHEDULER_JOB, lambda: gate.wait(3.0))
    card = page.auto_card
    card.switch.click()

    assert fake_core.scheduler.register_calls == 0
    assert not card.switch.isChecked()
    assert not card.banner.isHidden()
    assert card.banner_label.text() == strings.SYNC_AUTO_REFUSED
    gate.set()
    with qtbot.waitSignal(busy.signals.finished, timeout=TIMEOUT):
        pass
    card.retry_button.click()
    with qtbot.waitSignal(card.scheduler_job.signals.finished, timeout=TIMEOUT):
        pass
    assert fake_core.scheduler.register_calls == 1
    assert card.banner.isHidden()


def test_a_failed_registration_stays_on_screen(qtbot, page, fake_core):
    fake_core.scheduler.exe = None  # running from source: register refuses
    card = page.auto_card
    card.switch.click()
    with qtbot.waitSignal(card.scheduler_job.signals.finished, timeout=TIMEOUT):
        pass
    assert not card.banner.isHidden()
    assert card.banner_label.text().startswith("Impossibile aggiornare l'attività pianificata")


def test_the_status_line_describes_the_schedule_that_is_configured(qtbot, page, fake_core):
    import dataclasses

    from qtrequestory.ui.contracts import ScheduleSettings

    fake_core.config.config = dataclasses.replace(
        fake_core.config.load(),
        schedule=ScheduleSettings(start_time="07:30", repeat_every_h=2, repeat_for_h=6,
                                  run_at_logon=False),
    )
    fake_core.scheduler.set_status(registered=True, exe_matches=True, state="Pronto")
    page.on_config_changed(fake_core.config.load())
    wait_status(qtbot, page)
    qtbot.waitUntil(lambda: "07:30" in page.auto_card.status_label.text(), timeout=TIMEOUT)
    line = page.auto_card.status_label.text()
    assert "Ogni giorno alle 07:30, riprova ogni 2 ore fino alle 13:30" in line
    assert "login" not in line
    assert ". " not in line, "the sentence is framed by ' · ', not closed mid-line"


def test_an_exe_mismatch_is_shown_with_a_way_out(qtbot, page, fake_core):
    fake_core.scheduler.exe = Path(r"C:\vecchio\qtRequestory.exe")
    fake_core.scheduler.set_status(registered=True, exe_matches=False,
                                   command=Path(r"C:\vecchio\qtRequestory.exe"))
    card = page.auto_card
    card.refresh_scheduler()
    qtbot.waitUntil(lambda: not card.exe_row.isHidden(), timeout=TIMEOUT)
    assert "vecchio" in card.exe_warning.text()

    card.exe_button.click()
    with qtbot.waitSignal(card.scheduler_job.signals.finished, timeout=TIMEOUT):
        pass
    qtbot.waitUntil(lambda: card.exe_row.isHidden(), timeout=TIMEOUT)
    assert fake_core.scheduler.register_calls == 1


def test_an_unstable_location_is_explained_before_registering(qtbot, page):
    box = page.auto_card.build_unstable_dialog("L'eseguibile è in %TEMP%.")
    qtbot.addWidget(box)
    assert "%TEMP%" in box.text()
    assert box.windowTitle() == strings.SYNC_AUTO_UNSTABLE_TITLE


def test_refusing_the_unstable_warning_leaves_the_task_alone(page, fake_core, monkeypatch):
    fake_core.scheduler.unstable_reason = "L'eseguibile è in %TEMP%."
    card = page.auto_card
    monkeypatch.setattr(card, "confirm_unstable", lambda reason: False)
    card.switch.click()
    assert fake_core.scheduler.register_calls == 0
    assert not card.switch.isChecked(), "the switch goes back to where it was"
    assert card.scheduler_job is None


def test_modifica_orari_opens_the_automation_section_of_impostazioni(page, window):
    page.auto_card.edit_button.click()
    assert window.shown == ["settings"]
    assert window.settings.sections == ["automation"]


# -------------------------------------------------------------------- lock ---

def test_the_peek_never_blocks_a_sync_the_core_decides(qtbot, page, fake_core, window):
    """A stale or misread holder line must not lock the user out: the core
    takes the real lock and, if it is held, runs nothing and says so."""
    fake_core.sync.set_lock_holder("4242 2026-09-23T09:00:00")
    run_to_completion(qtbot, page)
    assert len(fake_core.sync.runs) == 1, "start_sync asked the core"
    assert page.run_label.text() == strings.SYNC_LOCK_HELD
    assert window.toasts[-1] == (strings.SYNC_LOCK_HELD, "neutral")
    assert "Sincronizzazione completata" not in page.run_label.text()


def test_a_lock_held_by_the_scheduled_run_disables_the_button(page, fake_core):
    fake_core.sync.set_lock_holder("4242 2026-09-23T09:00:00")
    page.refresh_lock()
    assert not page.sync_button.isEnabled()
    assert not page.lock_label.isHidden()
    fake_core.sync.set_lock_holder(None)
    page.refresh_lock()
    assert page.sync_button.isEnabled()
    assert page.lock_label.isHidden()


def test_the_lock_is_polled_only_while_the_page_is_visible(page):
    assert page.lock_timer.isActive()
    assert page.lock_timer.interval() == SyncPage.LOCK_POLL_MS
    assert page.lock_timer.parent() is page, "the timer dies with the page"
    page.hide()
    assert not page.lock_timer.isActive()
    page.show()
    assert page.lock_timer.isActive()


def test_a_held_lock_never_fights_the_gui_job(qtbot, page, fake_core):
    """While we are the ones syncing, the lock text would be a lie."""
    page.start_sync()
    fake_core.sync.set_lock_holder("noi stessi")
    page.refresh_lock()
    assert page.lock_label.isHidden()
    with qtbot.waitSignal(page.sync_job.signals.finished, timeout=TIMEOUT):
        pass


@pytest.fixture
def importing(qtbot, runner):
    """A GUI import in flight: it holds the sync lock (``ArchiveService.import_``)."""
    gate = threading.Event()
    job = runner.submit("import", lambda: gate.wait(TIMEOUT / 1000))
    qtbot.waitUntil(lambda: runner.is_running("import"), timeout=TIMEOUT)
    yield job
    gate.set()
    with qtbot.waitSignal(job.signals.finished, timeout=TIMEOUT):
        pass


def test_a_gui_import_is_not_blamed_on_the_scheduled_task(page, fake_core, importing):
    """Final review M2: the lock is ours during an import, and says so."""
    fake_core.sync.set_lock_holder("4242 importazione")
    page.refresh_lock()
    assert not page.lock_label.isHidden()
    assert page.lock_label.text() == strings.SYNC_LOCK_IMPORT
    assert not page.sync_button.isEnabled()


def test_a_sync_refused_by_a_gui_import_says_importazione(qtbot, page, fake_core, window, importing):
    fake_core.sync.set_lock_holder("4242 importazione")
    run_to_completion(qtbot, page)
    assert page.run_label.text() == strings.SYNC_SKIPPED_IMPORT
    assert strings.SYNC_LOCK_HELD not in page.run_label.text()


# ------------------------------------------------ GUI runs reach sync.log ---

class _Records(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


@pytest.fixture
def sync_log():
    """What reaches the ``sync.log`` logger during the test."""
    from qtrequestory.core.logsetup import SYNC_LOGGER

    logger = logging.getLogger(SYNC_LOGGER)
    handler = _Records()
    previous = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    yield handler.lines
    logger.removeHandler(handler)
    logger.setLevel(previous)


def test_a_sync_run_from_the_window_is_written_to_sync_log(qtbot, page, sync_log):
    """Same lines the headless ``--sync`` writes, from the same LoggingSink."""
    run_to_completion(qtbot, page)
    assert any(line.startswith("coll: 1 scaricati") for line in sync_log), sync_log
    assert any(line.startswith("indice:") for line in sync_log), sync_log


def test_the_registro_still_gets_every_line(qtbot, page, sync_log):
    run_to_completion(qtbot, page)
    shown = page.log_panel.text()
    assert all(line in shown for line in sync_log if "scaricati" in line)


# ------------------------------------------------- invalid log folder ------

@pytest.fixture
def no_mirror(fake_core):
    """config.json with ``"mirror_root": ""`` — what the CLI refuses (exit 2)."""
    import dataclasses

    fake_core.config.config = dataclasses.replace(fake_core.config.config, mirror_root=Path(""))


def test_an_invalid_log_folder_refuses_the_sync_and_says_why(qtbot, no_mirror, page, fake_core, runner):
    """Final review #1: never sync into the process CWD."""
    page.start_sync()
    qtbot.wait(100)

    assert page.sync_job is None and runner.job("sync") is None
    assert fake_core.sync.runs == []
    assert page.run_label.isVisible()
    assert "cartella dei log" in page.run_label.text()


def test_an_invalid_log_folder_shows_a_banner_to_impostazioni_archivio(no_mirror, page, window):
    banner = page.mirror_banner
    assert banner.isVisible()
    assert "cartella dei log" in banner.label.text().lower()

    banner.button.click()

    assert window.shown == ["settings"]
    assert window.settings.sections == ["archive"]


def test_a_valid_log_folder_shows_no_banner(page):
    assert not page.mirror_banner.isVisible()


def test_fixing_the_folder_in_impostazioni_hides_the_banner(no_mirror, page, fake_core, tmp_path):
    import dataclasses

    fake_core.config.config = dataclasses.replace(fake_core.config.config, mirror_root=tmp_path / "logs")
    page.on_config_changed(fake_core.config.load())

    assert not page.mirror_banner.isVisible()
