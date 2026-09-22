"""core/index/search.py: queries, byte-exact read_body, coverage and pickers."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from qtrequestory.core.events import null_sink
from qtrequestory.core.index.builder import IndexBuilder
from qtrequestory.core.index.db import open_index
from qtrequestory.core.index.search import (
    Coverage,
    IndexStale,
    SearchHit,
    SearchQuery,
    coverage,
    list_fdi_prefix,
    list_template_keys,
    output_name_for,
    output_name_with_id,
    pick_best,
    read_body,
    search,
)
from tests.conftest import FDI_A, FDI_B, FDI_C, KEY_CTE, KEY_EMAIL, KEY_NUMERIC, KEY_SINT, entry_name, make_daily_file, synthetic_body

D18, D16, D15, D03 = date(2026, 9, 18), date(2026, 9, 16), date(2026, 9, 15), date(2026, 8, 3)


@pytest.fixture
def indexed(mirror):
    conn = open_index(":memory:")
    IndexBuilder(conn, mirror.root, null_sink).update(["coll", "svil"])
    yield conn, mirror
    conn.close()


def _names(hits: list[SearchHit]) -> list[str]:
    return [h.name for h in hits]


# ------------------------------------------------------------- fdi prefix ---

def test_fdi_prefix_one_char(indexed):
    conn, mirror = indexed
    hits = search(conn, mirror.root, SearchQuery("coll", fdi_prefix="a"))
    assert {h.fdi for h in hits} == {FDI_A}
    assert len(hits) == 4  # 3 on 09-18 + 1 on 09-15; svil excluded
    assert all(h.env == "coll" for h in hits)


def test_fdi_prefix_eight_chars_and_full_uuid(indexed):
    conn, mirror = indexed
    assert len(search(conn, mirror.root, SearchQuery("coll", fdi_prefix=FDI_A[:8]))) == 4
    assert len(search(conn, mirror.root, SearchQuery("coll", fdi_prefix=FDI_A))) == 4
    # prefix is case-insensitive (stored lowercase)
    assert len(search(conn, mirror.root, SearchQuery("coll", fdi_prefix=FDI_A[:8].upper()))) == 4


def test_fdi_prefix_t15_variant(indexed):
    conn, mirror = indexed
    # the bare FDI_C prefix matches both the canonical entries and the -t15 test entry
    hits = search(conn, mirror.root, SearchQuery("coll", fdi_prefix=FDI_C))
    assert sorted(h.fdi for h in hits) == sorted([FDI_C, FDI_C, FDI_C + "-t15"])
    # the -t15 variant is found by its own full prefix and nothing else
    hits = search(conn, mirror.root, SearchQuery("coll", fdi_prefix=FDI_C + "-t15"))
    assert _names(hits) == [f"{FDI_C}-t15_{KEY_CTE}_1a2b3c0200000099"]
    assert hits[0].well_formed is False
    assert hits[0].call_id == "1a2b3c0200000099"


def test_fdi_ordering_across_and_within_days(indexed):
    conn, mirror = indexed
    hits = search(conn, mirror.root, SearchQuery("coll", fdi_prefix=FDI_A))
    assert [h.day for h in hits] == [D18, D18, D18, D15]
    # within 2026-09-18: request_date desc (ties -> seq desc), then the NULL request_date last
    assert _names(hits[:3]) == [
        entry_name(FDI_A, KEY_EMAIL, "1a2b3c0200000031"),  # seq 2, 10:38:28
        entry_name(FDI_A, KEY_SINT, "1a2b3c0200000033"),   # seq 0, 10:38:28
        entry_name(FDI_A, KEY_CTE, "1a2b3c0200000032"),    # seq 3, request_date NULL
    ]
    assert hits[2].request_date is None
    assert hits[3].name == entry_name(FDI_A, KEY_SINT, "1a2b3c0200000011")


def test_hit_fields(indexed):
    conn, mirror = indexed
    hit = search(conn, mirror.root, SearchQuery("coll", fdi_prefix=FDI_B, template_key=KEY_NUMERIC))[0]
    assert hit.env == "coll" and hit.day == D18
    assert hit.rel_path == "coll/2026/09/20260918.txt"
    assert hit.file_path == mirror.files[("coll", D18)]
    assert hit.file_path.is_absolute()
    assert hit.seq == 6
    assert hit.template_key == KEY_NUMERIC
    assert hit.json_ok is False and hit.ndocs is None
    assert hit.well_formed is True
    assert hit.dossier_number is None
    assert isinstance(hit.entry_id, int)
    assert hit.body_offset > hit.header_offset >= 0 and hit.body_len == len(b'{"documents": [ not json')


# ----------------------------------------------------------- template key ---

def test_template_key_exact_is_case_insensitive(indexed):
    conn, mirror = indexed
    lower = search(conn, mirror.root, SearchQuery("coll", template_key=KEY_SINT.lower()))
    upper = search(conn, mirror.root, SearchQuery("coll", template_key=KEY_SINT))
    assert _names(lower) == _names(upper)
    assert len(lower) == 3  # 2 on 09-18 + 1 on 09-15
    assert all(h.template_key == KEY_SINT for h in lower)


def test_template_key_exact_does_not_match_prefix(indexed):
    conn, mirror = indexed
    assert search(conn, mirror.root, SearchQuery("coll", template_key="MOD_TEST")) == []


def test_template_key_prefix_and_contains(indexed):
    conn, mirror = indexed
    prefix = search(conn, mirror.root, SearchQuery("coll", template_key="mod_test", key_mode="prefix"))
    assert {h.template_key for h in prefix} == {KEY_SINT, KEY_EMAIL}
    assert len(prefix) == 4
    contains = search(conn, mirror.root, SearchQuery("coll", template_key="plan", key_mode="contains"))
    assert {h.template_key for h in contains} == {KEY_SINT, KEY_CTE}
    assert search(conn, mirror.root, SearchQuery("coll", template_key="plan", key_mode="prefix")) == []


def test_like_metacharacters_are_literal(indexed):
    conn, mirror = indexed
    # "_" is a LIKE wildcard: "CTR_PLAN" as a prefix must NOT match "CTEXPLAN"; here we check the
    # inverse: a pattern with the wildcard chars replaced must not match anything.
    assert search(conn, mirror.root, SearchQuery("coll", template_key="CTE%PLAN", key_mode="prefix")) == []
    assert search(conn, mirror.root, SearchQuery("coll", template_key="CTR_PLAN", key_mode="prefix")) != []
    assert search(conn, mirror.root, SearchQuery("coll", template_key="MOD_TEST_R", key_mode="prefix")) != []
    assert search(conn, mirror.root, SearchQuery("coll", template_key="MOD%RIC_D", key_mode="contains")) == []
    assert search(conn, mirror.root, SearchQuery("coll", template_key="C_E_PLAN", key_mode="prefix")) == []
    assert search(conn, mirror.root, SearchQuery("coll", template_key="\\", key_mode="contains")) == []


def test_template_key_matches_principal_only(indexed):
    conn, mirror = indexed
    # attachments live in entry_documents, not in entries.template_key
    assert search(conn, mirror.root, SearchQuery("coll", template_key="ATTACH_1")) == []


# ------------------------------------------------------------- combined ---

def test_combined_fdi_and_key(indexed):
    conn, mirror = indexed
    hits = search(conn, mirror.root, SearchQuery("coll", fdi_prefix=FDI_A[:8], template_key=KEY_EMAIL))
    assert _names(hits) == [entry_name(FDI_A, KEY_EMAIL, "1a2b3c0200000031")]


def test_day_window_is_inclusive(indexed):
    conn, mirror = indexed
    hits = search(conn, mirror.root, SearchQuery("coll", template_key=KEY_CTE, day_from=D15, day_to=D15))
    assert [h.day for h in hits] == [D15]
    hits = search(conn, mirror.root, SearchQuery("coll", template_key=KEY_CTE, day_from=D15))
    assert [h.day for h in hits] == [D18, D18, D15]
    hits = search(conn, mirror.root, SearchQuery("coll", template_key=KEY_CTE, day_to=D15))
    assert [h.day for h in hits] == [D15, D03]
    hits = search(conn, mirror.root, SearchQuery("coll", template_key=KEY_CTE, day_from=D16, day_to=D16))
    assert hits == []


def test_limit(indexed):
    conn, mirror = indexed
    hits = search(conn, mirror.root, SearchQuery("coll", fdi_prefix=FDI_A, limit=2))
    assert len(hits) == 2 and [h.day for h in hits] == [D18, D18]


def test_env_isolation(indexed):
    conn, mirror = indexed
    hits = search(conn, mirror.root, SearchQuery("svil", fdi_prefix="a"))
    assert [h.env for h in hits] == ["svil"] and hits[0].day == D16
    assert search(conn, mirror.root, SearchQuery("prod", fdi_prefix="a")) == []


@pytest.mark.parametrize("q", [
    SearchQuery("coll"),
    SearchQuery("coll", fdi_prefix=""),
    SearchQuery("coll", template_key=""),
    SearchQuery("coll", fdi_prefix="  ", template_key=" "),
])
def test_requires_fdi_or_key(indexed, q):
    conn, mirror = indexed
    with pytest.raises(ValueError):
        search(conn, mirror.root, q)


# ------------------------------------------------------------- read_body ---

def test_read_body_is_byte_exact_for_every_hit(indexed):
    conn, mirror = indexed
    all_hits = []
    for env in ("coll", "svil"):
        all_hits += search(conn, mirror.root, SearchQuery(env, fdi_prefix="a"))
        all_hits += search(conn, mirror.root, SearchQuery(env, fdi_prefix="b"))
        all_hits += search(conn, mirror.root, SearchQuery(env, fdi_prefix="c"))
        all_hits += search(conn, mirror.root, SearchQuery(env, template_key="MOD_TEST_R"))
    assert len(all_hits) == 7 + 2 + 1 + 1
    for hit in all_hits:
        expected = dict(mirror.entries[(hit.env, hit.day)])[hit.name]
        assert read_body(hit) == expected


def test_read_body_detects_stale_index_and_recovers_after_rescan(indexed):
    conn, mirror = indexed
    hit = search(conn, mirror.root, SearchQuery("coll", fdi_prefix=FDI_B, template_key=KEY_SINT))[0]
    original = read_body(hit)
    path = mirror.files[("coll", D18)]
    path.write_bytes(b"### extra_ENTRY_0000000000000000.json\r\n{}\r\n" + path.read_bytes())

    with pytest.raises(IndexStale) as info:
        read_body(hit)
    assert (info.value.env, info.value.day) == ("coll", D18)

    IndexBuilder(conn, mirror.root, null_sink).rescan_file("coll", D18)
    hit2 = search(conn, mirror.root, SearchQuery("coll", fdi_prefix=FDI_B, template_key=KEY_SINT))[0]
    assert hit2.header_offset != hit.header_offset
    assert read_body(hit2) == original


def test_read_body_missing_file_is_stale_and_rescan_heals(indexed):
    conn, mirror = indexed
    hit = search(conn, mirror.root, SearchQuery("svil", fdi_prefix="a"))[0]
    hit.file_path.unlink()
    with pytest.raises(IndexStale) as info:
        read_body(hit)
    # the documented recovery loop must work for this trigger too: rescan drops the day
    assert IndexBuilder(conn, mirror.root, null_sink).rescan_file(info.value.env, info.value.day) == 0
    assert conn.in_transaction is False
    assert conn.execute("SELECT COUNT(*) FROM files WHERE env='svil'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM entries WHERE env='svil'").fetchone()[0] == 0
    assert search(conn, mirror.root, SearchQuery("svil", fdi_prefix="a")) == []
    assert coverage(conn, "svil") is None


def test_read_body_header_check_is_bounded(indexed, monkeypatch):
    """A stale offset landing inside a multi-MB body must not read the whole line."""
    conn, mirror = indexed
    hit = search(conn, mirror.root, SearchQuery("svil", fdi_prefix="a"))[0]
    path = mirror.files[("svil", D16)]
    path.write_bytes(b"### " + b"x" * 5_000_000 + b".json\n{}\n" + path.read_bytes())
    seen: list[int | None] = []
    real_open = Path.open

    def spy_open(self, *a, **kw):
        f = real_open(self, *a, **kw)
        real_readline = f.readline

        def readline(size=-1):
            seen.append(size)
            return real_readline(size)
        f.readline = readline
        return f

    monkeypatch.setattr(Path, "open", spy_open)
    with pytest.raises(IndexStale):
        read_body(hit)
    assert seen and all(0 < size < 1000 for size in seen)


def test_a_body_that_grew_under_the_index_is_stale_not_truncated(indexed):
    """``body_len`` was taken on trust: the header can still line up.

    Both other staleness tests shift the header, which the header check
    catches. This one keeps every offset valid and only makes the body longer —
    an entry edited in place, or a ``.part`` that was replaced while the index
    held the previous size. Without a check the read simply stops early and
    hands the UI a JSON document cut in half, which is worse than an error:
    ``pretty_json`` turns it into ``{"_parseError": ...}`` and the user has no
    idea the file on disk is fine.
    """
    conn, mirror = indexed
    hit = search(conn, mirror.root, SearchQuery("svil", fdi_prefix="a"))[0]
    raw = hit.file_path.read_bytes()
    cut = hit.body_offset + hit.body_len
    hit.file_path.write_bytes(raw[:cut] + b', "aggiunto": true' + raw[cut:])

    with pytest.raises(IndexStale) as info:
        read_body(hit)
    assert (info.value.env, info.value.day) == ("svil", D16)

    # the documented recovery loop heals it
    IndexBuilder(conn, mirror.root, null_sink).rescan_file("svil", D16)
    hit2 = search(conn, mirror.root, SearchQuery("svil", fdi_prefix="a"))[0]
    assert read_body(hit2).endswith(b', "aggiunto": true')


def test_a_body_at_the_very_end_of_the_file_is_not_stale(tmp_path):
    """The byte after the body may legitimately be nothing at all: a daily file
    whose last line has no trailing newline still reads."""
    conn = open_index(":memory:")
    root = tmp_path / "mirror"
    path = root / "coll" / "2026" / "09" / "20260918.txt"
    path.parent.mkdir(parents=True)
    body = synthetic_body(FDI_A, KEY_CTE, noise=False)
    path.write_bytes(f"### {entry_name(FDI_A, KEY_CTE)}.json\n".encode("utf-8") + body)

    IndexBuilder(conn, root, null_sink).update(["coll"])
    hit = search(conn, root, SearchQuery("coll", fdi_prefix=FDI_A))[0]
    assert read_body(hit) == body


# -------------------------------------------------------------- coverage ---

def test_coverage(indexed):
    conn, _ = indexed
    assert coverage(conn, "coll") == Coverage(first_day=D03, last_day=D18, n_files=3, n_entries=10)
    assert coverage(conn, "svil") == Coverage(first_day=D16, last_day=D16, n_files=1, n_entries=1)
    assert coverage(conn, "prod") is None


# ---------------------------------------------------------------- pickers ---

def test_list_template_keys_order_and_prefix(indexed):
    conn, mirror = indexed
    keys = list_template_keys(conn, "coll")
    # every key was last seen on 09-18 -> by count desc (CTE 4, SINT 3), then singles by key
    assert keys == [KEY_CTE, KEY_SINT, KEY_NUMERIC, KEY_EMAIL, "MOD_TEST_R"]
    assert list_template_keys(conn, "coll", prefix="MOD_TEST") == [KEY_SINT, KEY_EMAIL]
    assert list_template_keys(conn, "coll", prefix="mod_test_e") == [KEY_EMAIL]
    assert list_template_keys(conn, "coll", prefix="MOD%") == []
    assert list_template_keys(conn, "coll", prefix="  MOD_TEST ") == [KEY_SINT, KEY_EMAIL]
    assert list_template_keys(conn, "coll", prefix="   ") == list_template_keys(conn, "coll")
    assert list_template_keys(conn, "coll", limit=1) == [KEY_CTE]
    assert list_template_keys(conn, "prod") == []


def test_list_template_keys_most_recent_day_wins_over_count(indexed):
    conn, mirror = indexed
    make_daily_file(mirror.root, "svil", date(2026, 9, 10), [
        (entry_name(FDI_B, KEY_EMAIL, f"10b6016b000000{i:02x}"), synthetic_body(FDI_B, KEY_EMAIL)) for i in range(3)
    ])
    IndexBuilder(conn, mirror.root, null_sink).update(["svil"])
    # CTE: 1 entry on 09-16; EMAIL: 3 entries on 09-10 -> the more recent key comes first
    assert list_template_keys(conn, "svil") == [KEY_CTE, KEY_EMAIL]


def test_list_fdi_prefix(indexed):
    conn, _ = indexed
    assert list_fdi_prefix(conn, "coll", "c") == [FDI_C, FDI_C + "-t15"]
    assert list_fdi_prefix(conn, "coll", "C") == [FDI_C, FDI_C + "-t15"]
    assert list_fdi_prefix(conn, "coll", FDI_C + "-t") == [FDI_C + "-t15"]
    assert list_fdi_prefix(conn, "coll", "z") == []
    assert list_fdi_prefix(conn, "coll", "", limit=2) == [FDI_A, FDI_B]
    assert list_fdi_prefix(conn, "svil", "") == [FDI_A]
    assert list_fdi_prefix(conn, "svil", "  ") == [FDI_A]
    assert list_fdi_prefix(conn, "coll", " c ") == [FDI_C, FDI_C + "-t15"]


# ------------------------------------------------------------ output name ---

def test_output_name_for(indexed):
    conn, mirror = indexed
    hit = search(conn, mirror.root, SearchQuery("coll", fdi_prefix=FDI_A, template_key=KEY_SINT, day_from=D18))[0]
    assert output_name_for(hit) == f"20260918_{FDI_A}_{KEY_SINT}.json"
    assert output_name_with_id(hit) == f"20260918_{FDI_A}_{KEY_SINT}_1a2b3c0200000033.json"
    nofdi = search(conn, mirror.root, SearchQuery("coll", template_key="MOD_TEST_R"))[0]
    assert output_name_for(nofdi) == "20260918_nofdi_MOD_TEST_R.json"


# ------------------------------------------------------------- pick_best ---

def test_pick_best_keeps_the_newest_day_and_hands_back_the_rest_of_it(indexed):
    conn, mirror = indexed
    hits = search(conn, mirror.root, SearchQuery("coll", fdi_prefix=FDI_A))

    best, others = pick_best(hits)
    assert best is hits[0]
    assert _names(others) == _names(hits[1:3]), "only the same day is 'altre N entry'"
    assert all(o.day == best.day for o in others)


def test_pick_best_prefers_the_most_complete_body_of_the_day(indexed):
    """The legacy rule for an FDI-only search, and the reason --find exists.

    One pratica appears once per principal template key; the entry with the most
    ``documents`` is the one carrying the whole pratica, and that is what the
    user wants to replay. Without this, --find hands out whichever entry the
    file happened to end with.
    """
    conn, mirror = indexed
    hits = search(conn, mirror.root, SearchQuery("coll", fdi_prefix=FDI_A))
    assert [h.ndocs for h in hits[:3]] == [5, 3, 2]

    best, others = pick_best(hits, prefer_most_documents=True)
    assert best.template_key == KEY_EMAIL and best.ndocs == 5
    assert [o.ndocs for o in others] == [3, 2]


def test_pick_best_most_documents_keeps_the_query_order_on_a_tie(indexed):
    conn, mirror = indexed
    hits = search(conn, mirror.root, SearchQuery("coll", fdi_prefix=FDI_A))
    tied = [h for h in hits if h.day == D18]
    for h in tied:
        object.__setattr__(h, "ndocs", 4)

    best, others = pick_best(tied, prefer_most_documents=True)
    assert best is tied[0] and others == tied[1:]


def test_pick_best_ranks_an_unknown_ndocs_last(indexed):
    conn, mirror = indexed
    hits = search(conn, mirror.root, SearchQuery("coll", fdi_prefix=FDI_A))
    day = [h for h in hits if h.day == D18]
    object.__setattr__(day[0], "ndocs", None)  # a body that failed to parse

    best, _ = pick_best(day, prefer_most_documents=True)
    assert best is day[1]


def test_pick_best_of_nothing():
    assert pick_best([]) == (None, [])
