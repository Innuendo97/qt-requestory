"""1.1.0: the coverage states the core now tells apart, and truthful texts.

The server keeps its daily files until a manual purge and publishes a quiet
day as a 0-byte file. So a day absent from the local archive is either still
on the server (``pending``: sync it), purged before anybody downloaded it
(``lost``: gone), or unknown (before the listing memory began). A 0-byte local
day is not a hole at all: nobody called that day (``empty``).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import CoverageDays, EnvStatus
from qtrequestory.ui.pages import coverage_strip as cs
from qtrequestory.ui.pages import sync_badge as sb
from qtrequestory.ui.pages import sync_format as fmt

TODAY = date(2026, 9, 23)  # a Wednesday
MON, TUE = date(2026, 9, 21), date(2026, 9, 22)
SAT, SUN = date(2026, 9, 19), date(2026, 9, 20)
FRI, THU = date(2026, 9, 18), date(2026, 9, 17)


def _status(**kw) -> EnvStatus:
    base = dict(env="svil", last_success=datetime(2026, 9, 22, 11, 23), fresh=True,
                n_local_files=3, local_bytes=1, latest_day=None, index_pending=0)
    return EnvStatus(**{**base, **kw})


# -------------------------------------------------------------- the strip ---

def test_every_state_of_the_core_has_its_own_square():
    cov = CoverageDays(present=frozenset({FRI}), empty=frozenset({SAT}), pending=(MON,),
                       lost=(TUE,), unknown=(THU,), first_local=date(2026, 9, 16))
    kinds = dict(cs.day_kinds(cov, TODAY, days=30))
    assert kinds[TODAY] == cs.TODAY
    assert kinds[TUE] == cs.LOST
    assert kinds[MON] == cs.PENDING
    assert kinds[SUN] == cs.WEEKEND, "a weekend nobody knows anything about"
    assert kinds[SAT] == cs.EMPTY
    assert kinds[FRI] == cs.PRESENT
    assert kinds[THU] == cs.UNKNOWN
    assert kinds[date(2026, 9, 15)] == cs.BEFORE


def test_a_weekend_with_traffic_that_is_missing_is_pending_not_weekend():
    cov = CoverageDays(present=frozenset({FRI}), pending=(SAT,), lost=(SUN,),
                       first_local=FRI)
    kinds = dict(cs.day_kinds(cov, TODAY, days=30))
    assert (kinds[SAT], kinds[SUN]) == (cs.PENDING, cs.LOST)


def test_each_square_says_what_it_is():
    assert cs.tooltip(SAT, cs.EMPTY) == "19/09/2026: nessuna chiamata"
    assert cs.tooltip(MON, cs.PENDING) == "21/09/2026: sul server: da scaricare"
    assert cs.tooltip(TUE, cs.LOST) == (
        "22/09/2026: ripulito dal server prima di essere scaricato")
    assert cs.tooltip(THU, cs.UNKNOWN) == "17/09/2026: non verificabile"


def test_the_legend_shows_only_the_kinds_on_screen(qtbot):
    legend = cs.CoverageLegend()
    qtbot.addWidget(legend)
    legend.set_kinds({cs.PRESENT, cs.TODAY, cs.PENDING})
    visible = legend.shown()
    assert visible == [strings.SYNC_LEGEND_PRESENT, strings.SYNC_LEGEND_PENDING,
                       strings.SYNC_LEGEND_TODAY]
    legend.set_kinds({cs.EMPTY, cs.LOST, cs.UNKNOWN, cs.BEFORE})
    visible = legend.shown()
    assert visible == [strings.SYNC_LEGEND_EMPTY, strings.SYNC_LEGEND_LOST,
                       strings.SYNC_LEGEND_UNKNOWN, strings.SYNC_LEGEND_BEFORE]


# -------------------------------------------------------------- the badge ---

def test_a_lost_day_is_red_and_beats_a_pending_one():
    badge = sb.badge_for(_status(), pending=2, lost=1)
    assert (badge.kind, badge.tone, badge.text) == (sb.LOST, "bad", "1 giorno perso")
    assert sb.badge_for(_status(), lost=3).text == "3 giorni persi"


def test_a_pending_day_is_amber_and_says_how_many_to_download():
    badge = sb.badge_for(_status(), pending=2)
    assert (badge.kind, badge.tone, badge.text) == (sb.PENDING, "warn", "2 da scaricare")
    assert sb.badge_for(_status(), pending=1).text == "1 da scaricare"


def test_what_is_happening_still_beats_a_hole():
    assert sb.badge_for(_status(), running=True, lost=1).kind == sb.RUNNING
    assert sb.badge_for(_status(), reachable=False, lost=1).kind == sb.UNREACHABLE
    assert sb.badge_for(_status(), failed=1, pending=1).kind == sb.ERRORS


def test_only_a_lost_day_is_red():
    for kw in (dict(reachable=False), dict(failed=5), dict(pending=9), {}):
        assert sb.badge_for(_status(), **kw).tone in ("ok", "warn", "neutral")


# ------------------------------------------------------------ the banners ---

def test_the_pending_banner_names_the_env_the_count_and_the_dates():
    text = fmt.pending_days_text({"svil": (MON, TUE), "coll": ()})
    assert text == ("svil: 2 giorni (21/09/2026, 22/09/2026) sono ancora sul server "
                    "ma non sono stati scaricati.")
    assert fmt.pending_days_text({"svil": (MON,)}) == (
        "svil: 1 giorno (21/09/2026) è ancora sul server ma non è stato scaricato.")
    assert fmt.pending_days_text({"svil": ()}) == ""


def test_the_lost_banner_says_they_cannot_be_recovered():
    text = fmt.lost_days_text({"svil": (MON, TUE)})
    assert text == ("svil: 2 giorni (21/09/2026, 22/09/2026) sono stati ripuliti dal server "
                    "prima di essere scaricati: non recuperabili.")
    assert fmt.lost_days_text({"svil": (MON,)}).endswith(
        "è stato ripulito dal server prima di essere scaricato: non recuperabile.")


def test_a_long_list_of_dates_is_cut():
    days = tuple(date(2026, 9, d) for d in range(1, 10))
    assert "e altri 4" in fmt.pending_days_text({"svil": days})


def test_no_text_anywhere_claims_the_server_keeps_about_a_day():
    values = [v for k, v in vars(strings).items() if k.isupper() and isinstance(v, str)]
    assert not [v for v in values if "circa un giorno" in v or "un giorno di log" in v]


# ------------------------------------------------------------- search gap ---

def test_the_search_warning_counts_pending_and_lost_only(qtbot):
    from qtrequestory.ui.pages.search_meta import GapBanner

    banner = GapBanner()
    qtbot.addWidget(banner)
    banner.set_gap("coll", pending=(MON,), lost=())
    assert not banner.isHidden()
    assert banner.label.text() == "1 giorno da scaricare in coll"
    assert banner.property("banner") == "warn"
    banner.set_gap("coll", pending=(MON, TUE), lost=(THU,))
    assert banner.label.text() == (
        "2 giorni da scaricare in coll · 1 giorno non recuperabile")
    assert banner.property("banner") == "bad"
    assert "17/09" in banner.toolTip() and "21/09" in banner.toolTip()
    banner.set_gap("coll", pending=(), lost=())
    assert banner.isHidden()


# ------------------------------------------------------------- the wizard ---

def test_the_wizard_warns_that_the_first_sync_downloads_the_whole_history():
    assert "storico" in strings.WIZARD_P3_FIRST_SYNC_NOTE
    assert "GB" in strings.WIZARD_P3_FIRST_SYNC_NOTE


@pytest.mark.parametrize("name", ["SETTINGS_SCHEDULE_LOGON_HINT"])
def test_the_logon_hint_tells_the_real_retention(name):
    text = getattr(strings, name)
    assert "pulizia" in text and "circa" not in text


def test_the_card_counts_only_days_with_calls(qtbot):
    """A 0-byte placeholder is "no traffic", not archive content."""
    from qtrequestory.ui.pages.env_card import EnvCard

    card = EnvCard("svil", "https://example.invalid/svil/")
    qtbot.addWidget(card)
    cov = CoverageDays(present=frozenset({FRI}), empty=frozenset({SAT, SUN}),
                       first_local=FRI - timedelta(days=1))
    card.set_status(_status(n_local_files=1, local_bytes=1_048_576), cov, TODAY)
    assert card.archive_value.text().startswith("1 giorno · ")
