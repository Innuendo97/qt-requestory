"""core/archive_names.py: the day and the environment a log's path names."""
from __future__ import annotations

from datetime import date

import pytest

from qtrequestory.core.archive_names import (
    AMBIGUOUS,
    NO_DATE,
    day_from_parts,
    element_dates,
    env_from_parts,
    strip_dates,
)

TODAY = date(2026, 9, 24)
D = date(2026, 9, 22)


# ------------------------------------------------------------------ dates ---

@pytest.mark.parametrize("text", [
    "20260922", "20260922.txt", "coll_20260922.txt", "2026-09-22", "2026_09_22.log",
    "2026.09.22", "22092026", "22-09-2026.txt", "22_09_2026", "22.09.2026",
    "svil-20260922-copia.txt", "log 2026-09-22 (1).txt",
])
def test_every_accepted_date_shape(text):
    assert element_dates(text, today=TODAY) == {D}


@pytest.mark.parametrize("text", [
    "120260922", "202609221", "12026-09-22", "22-09-20261",   # digits glued to the token
    "2026-09_22", "22-09_2026",                                  # inconsistent separators
    "20261340", "31022026", "2026-02-30",                        # not real dates
    "20191231", "31122019",                                      # before 2020
    "20260926",                                                  # after tomorrow
    "2026-9-22", "260922", "notes", "",
])
def test_rejected_shapes(text):
    assert element_dates(text, today=TODAY) == set()


def test_tomorrow_still_counts():
    assert element_dates("20260925", today=TODAY) == {date(2026, 9, 25)}


def test_two_different_dates_in_one_element_are_both_returned():
    assert element_dates("20260921_20260922", today=TODAY) == {date(2026, 9, 21), D}
    assert element_dates("20260922 copia 22-09-2026", today=TODAY) == {D}


def test_strip_dates_removes_every_token():
    assert strip_dates("coll20260922") == "coll "
    assert strip_dates("2026-09-22_svil") == " _svil"
    assert strip_dates("svil2") == "svil2"


def test_day_from_the_file_name_first():
    assert day_from_parts(["20260922.txt", "20260101", "x"], today=TODAY) == (D, None)


def test_day_from_the_nearest_dir_when_the_name_has_none():
    assert day_from_parts(["access.txt", "22-09-2026", "20260101"], today=TODAY) == (D, None)


def test_year_month_day_layout():
    assert day_from_parts(["22.txt", "09", "2026", "coll"], today=TODAY) == (D, None)
    assert day_from_parts(["22.txt", "9", "2026"], today=TODAY) == (D, None)
    assert day_from_parts(["31.txt", "02", "2026"], today=TODAY) == (None, NO_DATE)


def test_no_date_anywhere():
    assert day_from_parts(["notes.txt", "coll"], today=TODAY) == (None, NO_DATE)


def test_an_element_with_two_dates_is_ambiguous():
    assert day_from_parts(["20260921_20260922.txt"], today=TODAY) == (None, AMBIGUOUS)
    assert day_from_parts(["access.txt", "20260921-20260922"], today=TODAY) == (None, AMBIGUOUS)


# -------------------------------------------------------------------- env ---

ENVS = ("svil", "coll", "prod", "collaudo")


@pytest.mark.parametrize("parts, expected", [
    (["20260922.txt", "coll"], "coll"),
    (["coll_20260922.txt"], "coll"),
    (["coll20260922.txt"], "coll"),               # the date token is removed first
    (["20260922.txt", "2026", "SVIL"], "svil"),   # case-insensitive, returns the configured name
    (["svil-20260922.txt", "coll"], "svil"),      # file name before dirs
    (["20260922.txt", "coll", "svil"], "coll"),   # nearest dir wins
    (["20260922.txt", "collaudo"], "collaudo"),   # "coll" is followed by a letter: no match
    (["20260922.txt", "prod2"], "prod"),          # a digit after the name is allowed
    (["20260922.txt", "production"], None),       # a letter after is not
    (["20260922.txt", "xprod"], None),            # nor a letter before
    (["20260922.txt", "3prod"], None),            # nor a digit before
    (["20260922.txt", "svil e coll"], None),      # still tied: ask the user
    (["20260922.txt", "logs"], None),
])
def test_env_from_parts(parts, expected):
    assert env_from_parts(parts, ENVS) == expected


def test_the_longest_name_wins_a_tie_in_the_same_element():
    assert env_from_parts(["a.txt", "coll2"], ("coll", "coll2")) == "coll2"


def test_env_names_with_regex_metacharacters_are_literal():
    assert env_from_parts(["a.txt", "svil-2"], ("svil-2", "svil")) == "svil-2"
    assert env_from_parts(["a.txt", "x"], ("a.b",)) is None
