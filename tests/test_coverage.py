"""core/daily.py ``classify_days``: what each day of the coverage window is.

Rules (plan U1.4): a local file is ``present`` (size > 0) or ``empty``
(0 bytes: the server published "no traffic"); a day without a local file is
``pending`` while the server still lists it non-empty, ``lost`` once it was
seen non-empty but is no longer listed (purged before it was downloaded) and
``unknown`` when it is a weekday nobody ever saw (before tracking began).
Weekends are classified like any other day.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from qtrequestory.core.daily import CoverageDays, classify_days

TODAY = date(2026, 9, 23)  # a Wednesday; the 30-day window is [2026-08-25, 2026-09-22]


def _d(day: int, month: int = 9) -> date:
    return date(2026, month, day)


def test_present_and_empty_come_from_local_sizes():
    cov = classify_days({_d(21): 500, _d(20): 0, _d(19): 0}, listed_nonempty=(), seen_nonempty=(),
                        days=30, today=TODAY)
    assert cov.present == frozenset({_d(21)})
    assert cov.empty == frozenset({_d(20), _d(19)})
    assert cov.first_local == _d(19)


def test_a_day_still_listed_non_empty_is_pending_even_on_a_weekend():
    """F8: a weekend with traffic that is not local must be reported."""
    saturday = _d(19)
    assert saturday.weekday() == 5
    cov = classify_days({_d(18): 10}, listed_nonempty=(saturday, _d(22)), seen_nonempty=(saturday, _d(22)),
                        days=30, today=TODAY)
    assert cov.pending == (saturday, _d(22))
    assert cov.lost == ()
    assert cov.missing == (saturday, _d(22))


def test_a_day_seen_non_empty_but_no_longer_listed_is_lost():
    cov = classify_days({_d(10): 10, _d(22): 10}, listed_nonempty=(_d(22),),
                        seen_nonempty=(_d(15), _d(22)), days=30, today=TODAY)
    assert cov.lost == (_d(15),)
    assert cov.pending == ()
    assert cov.missing == (_d(15),)


def test_a_never_seen_weekday_after_the_archive_began_is_unknown_not_missing():
    cov = classify_days({_d(14): 10, _d(18): 10}, listed_nonempty=(), seen_nonempty=(), days=30, today=TODAY)
    # Weekdays in [first_local, today-1] without a file: 15, 16, 17, 21, 22.
    assert cov.unknown == (_d(15), _d(16), _d(17), _d(21), _d(22))
    assert _d(19) not in cov.unknown and _d(20) not in cov.unknown, "a never-seen weekend is not unknown"
    assert cov.missing == ()


def test_days_before_the_archive_began_are_only_flagged_when_the_server_saw_them():
    cov = classify_days({_d(18): 10}, listed_nonempty=(_d(1),), seen_nonempty=(_d(1), _d(2)),
                        days=30, today=TODAY)
    assert cov.pending == (_d(1),)
    assert cov.lost == (_d(2),)
    assert _d(3) not in cov.unknown, "a weekday before first_local is never unknown"
    assert cov.unknown == (_d(21), _d(22))


def test_local_files_win_over_every_server_list():
    cov = classify_days({_d(21): 10, _d(22): 0}, listed_nonempty=(_d(21), _d(22)),
                        seen_nonempty=(_d(21), _d(22)), days=30, today=TODAY)
    assert cov.pending == () and cov.lost == () and cov.unknown == ()


def test_the_window_excludes_today_and_days_older_than_it():
    old = TODAY - timedelta(days=30)  # just outside [today-29, today-1]
    cov = classify_days({_d(1, 8): 10}, listed_nonempty=(TODAY, old, TODAY - timedelta(days=29)),
                        seen_nonempty=(), days=30, today=TODAY)
    assert cov.pending == (TODAY - timedelta(days=29),)


def test_an_empty_mirror_with_no_server_knowledge_flags_nothing():
    cov = classify_days({}, listed_nonempty=(), seen_nonempty=(), days=30, today=TODAY)
    assert cov == CoverageDays(present=frozenset(), empty=frozenset(), pending=(), lost=(), unknown=(),
                               first_local=None)
    assert cov.missing == ()


def test_an_empty_mirror_still_reports_what_the_server_holds():
    cov = classify_days({}, listed_nonempty=(_d(21),), seen_nonempty=(_d(20),), days=30, today=TODAY)
    assert cov.pending == (_d(21),)
    assert cov.lost == (_d(20),)


def test_missing_is_pending_plus_lost_sorted():
    cov = CoverageDays(present=frozenset(), empty=frozenset(), pending=(_d(22), _d(3)), lost=(_d(10),),
                       unknown=(_d(11),), first_local=None)
    assert cov.missing == (_d(3), _d(10), _d(22))


def test_coverage_days_is_frozen():
    cov = classify_days({}, listed_nonempty=(), seen_nonempty=(), days=1, today=TODAY)
    with pytest.raises(AttributeError):
        cov.first_local = _d(1)  # type: ignore[misc]
