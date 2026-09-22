"""core/autoindex.py: parse the nginx autoindex page of one environment."""
from __future__ import annotations

import re
from datetime import date

from qtrequestory.core.autoindex import (
    DAILY_HREF_RE,
    LOOSE_HREF_RE,
    RemoteDailyFile,
    RemoteIndex,
    parse_autoindex,
)
from tests.conftest import autoindex_html

THREE_DAYS = [
    ("20260919.txt", "19-Sep-2026 18:30", 12345),
    ("20260921.txt", "21-Sep-2026 18:30", 64487564),
    ("20260920.txt", "20-Sep-2026 18:30", 0),      # weekend: empty file
]


def test_parse_three_daily_and_two_loose():
    idx = parse_autoindex(autoindex_html(THREE_DAYS, loose=2))
    assert isinstance(idx, RemoteIndex)
    assert idx.loose_count == 2
    assert idx.daily == (
        RemoteDailyFile("20260921.txt", date(2026, 9, 21), 64487564),
        RemoteDailyFile("20260920.txt", date(2026, 9, 20), 0),
        RemoteDailyFile("20260919.txt", date(2026, 9, 19), 12345),
    )
    for f in idx.daily:
        assert isinstance(f.size, int)
        assert isinstance(f.day, date)


def test_empty_page_and_parent_link_only():
    assert parse_autoindex("") == RemoteIndex(daily=(), loose_count=0)
    idx = parse_autoindex(autoindex_html([]))
    assert idx.daily == () and idx.loose_count == 0


def test_invalid_date_href_is_skipped():
    html = autoindex_html([("20261340.txt", "21-Sep-2026 18:30", 10), ("20260921.txt", "21-Sep-2026 18:30", 20)])
    idx = parse_autoindex(html)
    assert [f.name for f in idx.daily] == ["20260921.txt"]


def test_non_daily_names_are_ignored():
    html = autoindex_html([
        ("notes.txt", "21-Sep-2026 18:30", 10),
        ("2026092.txt", "21-Sep-2026 18:30", 10),
        ("20260921.txt.part", "21-Sep-2026 18:30", 10),
        ("20260921.txt", "21-Sep-2026 18:30", 20),
    ])
    idx = parse_autoindex(html)
    assert [f.name for f in idx.daily] == ["20260921.txt"]
    assert idx.loose_count == 0


def test_only_href_matters_not_visible_name():
    html = autoindex_html([("20260921.txt", "21-Sep-2026 18:30", 42)], loose=1)
    assert "..&gt;" in html
    # mangle the visible text of the daily link too: the href must still win
    html = html.replace('">20260921.txt</a>', '">2026..&gt;</a>')
    idx = parse_autoindex(html)
    assert idx.daily == (RemoteDailyFile("20260921.txt", date(2026, 9, 21), 42),)
    assert idx.loose_count == 1


def test_exported_regexes_match_spec_line_shape():
    line = '<a href="20260921.txt">20260921.txt</a>   21-Sep-2026 18:30   64487564'
    m = re.search(DAILY_HREF_RE, line)
    assert m and m.group("day") == "20260921" and m.group("size") == "64487564"
    assert m.group("date") == "21-Sep-2026 18:30"
    assert re.search(LOOSE_HREF_RE, '<a href="abc_KEY_0123456789abcdef.json">abc..&gt;</a>')
    assert not re.search(LOOSE_HREF_RE, line)
