"""qtrequestory.officina.batch.resolve: from what the user asked to the calls.

The lookups run against a REAL index (``IndexBuilder`` over synthetic daily
files, ``core.index.search.search``), so "newest hit" and the case-insensitive
key match are proven against the real ``ORDER BY`` and the NOCASE column. Only
the cancellation tests wrap that real index to cancel mid-way.

Synthetic data only (this repository is public).
"""
from __future__ import annotations

import dataclasses
from datetime import date
from pathlib import Path

import pytest

from qtrequestory.core.events import CancelToken, Cancelled, null_sink
from qtrequestory.core.index.builder import IndexBuilder
from qtrequestory.core.index.db import open_index
from qtrequestory.core.index.search import SearchHit, SearchQuery, search
from qtrequestory.officina.batch.elenco import NO_PACKAGE, Elenco, ElencoRow
from qtrequestory.officina.batch.model import Call, Target
from qtrequestory.officina.batch.resolve import (
    parse_keys,
    resolve,
    targets_from_fdis,
    targets_from_hits,
    targets_from_keys,
    targets_from_packages,
)
from tests.conftest import FDI_A, FDI_B, FDI_C, entry_name, make_daily_file, synthetic_body

KEY_A, KEY_B, KEY_C = "MOD_TEST_A", "MOD_TEST_B", "MOD_TEST_C"
OLD, NEW = date(2026, 11, 3), date(2026, 11, 9)
FDI_UNKNOWN = "dddddddd-1111-4222-8333-444444444444"


class RealIndex:
    """The two methods of ``IndexService`` that Genera uses, over a real DB."""

    def __init__(self, conn, root: Path) -> None:
        self.conn, self.root = conn, root
        self.queries: list[SearchQuery] = []

    def search(self, query: SearchQuery) -> list[SearchHit]:
        self.queries.append(query)
        return search(self.conn, self.root, query)


@pytest.fixture
def index(tmp_path):
    root = tmp_path / "mirror"
    make_daily_file(root, "coll", OLD, [
        (entry_name(FDI_A, KEY_A, "0a0a0a0a00000001"),
         synthetic_body(FDI_A, KEY_A, request_date="2026-11-03T08:00:00.000Z")),
        (entry_name(FDI_A, KEY_B, "0a0a0a0a00000002"),
         synthetic_body(FDI_A, KEY_B, request_date="2026-11-03T08:00:01.000Z")),
    ])
    make_daily_file(root, "coll", NEW, [
        # same day, the later request_date comes FIRST in the file: newest by date wins
        (entry_name(FDI_B, KEY_A, "0b0b0b0b00000002"),
         synthetic_body(FDI_B, KEY_A, request_date="2026-11-09T15:00:00.000Z")),
        (entry_name(FDI_C, KEY_A, "0b0b0b0b00000001"),
         synthetic_body(FDI_C, KEY_A, request_date="2026-11-09T09:00:00.000Z")),
        (entry_name(FDI_A, KEY_A, "0b0b0b0b00000003"),
         synthetic_body(FDI_A, KEY_A, request_date="2026-11-09T10:00:00.000Z")),
        # an FDI that only STARTS with FDI_A: a different pratica
        (f"{FDI_A}-t15_{KEY_C}_0b0b0b0b00000004", synthetic_body(FDI_A, KEY_C)),
    ])
    make_daily_file(root, "svil", NEW, [
        (entry_name(FDI_A, KEY_C, "0c0c0c0c00000001"), synthetic_body(FDI_A, KEY_C)),
    ])
    conn = open_index(":memory:")
    IndexBuilder(conn, root, null_sink).update(["coll", "svil"])
    yield RealIndex(conn, root)
    conn.close()


def _elenco(*rows: tuple[str, str]) -> Elenco:
    return Elenco(rows=tuple(ElencoRow(k, p) for k, p in rows), skipped=0)


# ---------------------------------------------------------------- parse_keys ---

def test_parse_keys_separators_and_duplicates():
    assert parse_keys("MOD_TEST_A, mod_test_a;\nMOD_TEST_B  ") == ["MOD_TEST_A", "MOD_TEST_B"]


def test_parse_keys_more_separators_and_blank():
    assert parse_keys(" ,;\r\n\t ") == []
    assert parse_keys("MOD_TEST_B,,;;MOD_TEST_A\r\nMOD_TEST_C\tmod_test_b") == [
        "MOD_TEST_B", "MOD_TEST_A", "MOD_TEST_C"]


# ------------------------------------------------------------------- targets ---

def test_keys_without_elenco_go_to_no_package():
    assert targets_from_keys(["MOD_TEST_A", " MOD_TEST_B "], None) == (
        Target("key", "MOD_TEST_A", (NO_PACKAGE,)),
        Target("key", "MOD_TEST_B", (NO_PACKAGE,)),
    )


def test_keys_not_in_elenco_go_to_no_package():
    elenco = _elenco((KEY_A, "111_PKG"))
    assert targets_from_keys(["mod_test_a", "MOD_TEST_Z"], elenco) == (
        Target("key", "mod_test_a", ("111_PKG",)),
        Target("key", "MOD_TEST_Z", (NO_PACKAGE,)),
    )


def test_targets_from_keys_drops_blanks_and_duplicates():
    assert targets_from_keys(["MOD_TEST_A", "", "  ", "mod_test_a"], None) == (
        Target("key", "MOD_TEST_A", (NO_PACKAGE,)),
    )


def test_targets_from_packages_only_selected_folders():
    elenco = _elenco((KEY_A, "111_PKG"), (KEY_B, "222_PKG"), (KEY_A, "222_PKG"), (KEY_C, "333_PKG"))
    assert targets_from_packages(elenco, ["222_PKG"]) == (
        Target("key", KEY_B, ("222_PKG",)),
        Target("key", KEY_A, ("222_PKG",)),
    )
    assert targets_from_packages(elenco, {"111_PKG", "222_PKG"}) == (
        Target("key", KEY_A, ("111_PKG", "222_PKG")),
        Target("key", KEY_B, ("222_PKG",)),
    )


def test_targets_from_fdis_strip_and_dedupe():
    assert targets_from_fdis([f" {FDI_A} ", FDI_A.upper(), "", FDI_B]) == (
        Target("fdi", FDI_A, ()),
        Target("fdi", FDI_B, ()),
    )


# ------------------------------------------------------------------- resolve ---

def test_key_takes_newest_hit(index):
    [call] = resolve(targets_from_keys([KEY_A], None), index=index, source_env="coll")
    assert call.hit is not None
    assert (call.hit.day, call.hit.fdi, call.hit.call_id) == (NEW, FDI_B, "0b0b0b0b00000002")
    assert call.key == KEY_A
    assert call.folders == (NO_PACKAGE,)
    assert index.queries == [SearchQuery("coll", template_key=KEY_A, key_mode="exact", limit=1)]


def test_key_lookup_ignores_case(index):
    [call] = resolve(targets_from_keys(["  mod_test_b "], None), index=index, source_env="coll")
    assert call.hit is not None and call.hit.template_key == KEY_B
    assert call.key == KEY_B  # the spelling of the logs: it becomes the template_key header


def test_key_lookup_uses_source_env(index):
    [call] = resolve(targets_from_keys([KEY_C], None), index=index, source_env="svil")
    assert call.hit is not None and call.hit.env == "svil"
    [missing] = resolve(targets_from_keys([KEY_B], None), index=index, source_env="svil")
    assert missing.hit is None


def test_missing_key_gives_call_without_hit(index):
    calls = resolve(targets_from_keys(["MOD_TEST_Z"], None), index=index, source_env="coll")
    assert calls == [Call(key="MOD_TEST_Z", folders=(NO_PACKAGE,), fdi=None, hit=None)]


def test_key_call_carries_the_fdi_of_its_source(index):
    [call] = resolve(targets_from_keys([KEY_B], None), index=index, source_env="coll")
    assert call.fdi == FDI_A


def test_key_in_two_packages_is_one_call_two_folders(index):
    elenco = _elenco((KEY_A, "111_PKG"), (KEY_B, "111_PKG"), (KEY_A, "222_PKG"))
    calls = resolve(targets_from_keys([KEY_A], elenco), index=index, source_env="coll")
    assert len(calls) == 1
    assert calls[0].folders == ("111_PKG", "222_PKG")
    assert calls[0].hit is not None


def test_calls_keep_target_order(index):
    calls = resolve(targets_from_keys(["MOD_TEST_Z", KEY_B, KEY_A], None), index=index,
                    source_env="coll")
    assert [c.key for c in calls] == ["MOD_TEST_Z", KEY_B, KEY_A]


def test_fdi_newest_hit_per_key_and_folder_is_fdi(index):
    calls = resolve(targets_from_fdis([FDI_A]), index=index, source_env="coll")
    by_key = {c.key: c for c in calls}
    assert set(by_key) == {KEY_A, KEY_B}  # the -t15 pratica (KEY_C) is another FDI
    assert len(calls) == 2
    assert by_key[KEY_A].hit is not None and by_key[KEY_A].hit.day == NEW
    assert by_key[KEY_A].hit.call_id == "0b0b0b0b00000003"
    assert by_key[KEY_B].hit is not None and by_key[KEY_B].hit.day == OLD
    for call in calls:
        assert call.folders == (FDI_A,)
        assert call.fdi == FDI_A
        assert call.hit.fdi == FDI_A
    assert index.queries == [SearchQuery("coll", fdi_prefix=FDI_A, limit=1000)]


def test_fdi_narrowed_to_keys_takes_that_fdis_call_only(index):
    """Review item 1: the retry of one key of an FDI takes THAT FDI's call,
    not the newest call of the key (FDI_B's KEY_A is newer than FDI_A's)."""
    target = Target("fdi", FDI_A, (), (KEY_A.lower(), "MOD_TEST_Z"))
    calls = resolve([target], index=index, source_env="coll")
    assert [(c.key, c.folders, c.fdi) for c in calls] == [
        (KEY_A, (FDI_A,), FDI_A), ("MOD_TEST_Z", (FDI_A,), FDI_A)]
    assert calls[0].hit is not None and calls[0].hit.fdi == FDI_A
    assert calls[0].hit.call_id == "0b0b0b0b00000003"
    assert calls[1].hit is None  # FDI_A has no such key: no call, never another FDI's
    assert index.queries == [SearchQuery("coll", fdi_prefix=FDI_A, limit=1000)]


def test_fdi_narrowed_to_keys_ignores_the_longer_pratica(index):
    (call,) = resolve([Target("fdi", FDI_A, (), (KEY_C,))], index=index, source_env="coll")
    assert call.hit is None  # KEY_C only exists in "<FDI_A>-t15", another FDI


def test_fdi_typed_in_upper_case_is_found(index):
    calls = resolve(targets_from_fdis([FDI_B.upper()]), index=index, source_env="coll")
    assert [(c.key, c.folders, c.fdi) for c in calls] == [(KEY_A, (FDI_B.upper(),), FDI_B.upper())]
    assert calls[0].hit is not None


def test_unknown_fdi_gives_single_call_without_hit(index):
    calls = resolve(targets_from_fdis([FDI_UNKNOWN]), index=index, source_env="coll")
    assert calls == [Call(key="", folders=(FDI_UNKNOWN,), fdi=FDI_UNKNOWN, hit=None)]


def test_fdi_prefix_alone_is_not_a_whole_fdi(index):
    calls = resolve(targets_from_fdis([FDI_A[:8]]), index=index, source_env="coll")
    assert calls == [Call(key="", folders=(FDI_A[:8],), fdi=FDI_A[:8], hit=None)]


def test_blank_targets_never_reach_the_index(index):
    calls = resolve((Target("key", "  ", ("111_PKG",)), Target("fdi", "", ())), index=index,
                    source_env="coll")
    assert [c.hit for c in calls] == [None, None]
    assert index.queries == []


def test_resolve_stops_on_cancel(index):
    token = CancelToken()
    real_search = index.search

    def search_then_cancel(query):
        token.cancel()
        return real_search(query)

    index.search = search_then_cancel
    with pytest.raises(Cancelled):
        resolve(targets_from_keys([KEY_A, KEY_B], None), index=index, source_env="coll", cancel=token)
    assert len(index.queries) == 1  # the second target never ran


def test_resolve_cancelled_before_start_runs_nothing(index):
    token = CancelToken()
    token.cancel()
    with pytest.raises(Cancelled):
        resolve(targets_from_fdis([FDI_A]), index=index, source_env="coll", cancel=token)
    assert index.queries == []


# ------------------------------------------------------------- exact calls ---

def _hits(index, fdi: str) -> list[SearchHit]:
    return index.search(SearchQuery("coll", fdi_prefix=fdi, limit=100))


def test_targets_from_hits_one_exact_target_per_call(index):
    older, newer = sorted((h for h in _hits(index, FDI_A) if h.template_key == KEY_A and h.fdi == FDI_A),
                          key=lambda h: h.day)
    no_fdi = dataclasses.replace(older, fdi=None)
    assert targets_from_hits([newer, older, newer, no_fdi]) == (
        Target("call", KEY_A, (FDI_A,), hit=newer),
        Target("call", KEY_A, (FDI_A,), hit=older),
        Target("call", KEY_A, (NO_PACKAGE,), hit=no_fdi),
    )


def test_exact_call_is_that_call_without_looking_anything_up(index):
    older = next(h for h in _hits(index, FDI_A) if h.template_key == KEY_A and h.day == OLD)
    (call,) = resolve(targets_from_hits([older]), index=index, source_env="svil")
    assert call == Call(key=KEY_A, folders=(FDI_A,), fdi=FDI_A, hit=older, exact=True)
    assert len(index.queries) == 1  # only the lookup of this test: resolve searched nothing


def test_exact_call_without_hit_is_refused(index):
    with pytest.raises(ValueError):
        resolve([Target("call", KEY_A, (FDI_A,))], index=index, source_env="coll")
