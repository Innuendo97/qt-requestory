"""The Ricerca results model: flat rows or FDI groups, and how they sort.

Pure model tests: no view is created. A ``QAbstractItemModel`` answers
``data()`` on its own, so the whole rendering contract (formats, tooltips,
alignment, the hit behind a row, the grouping, the sort) is pinned down here —
a screenshot never tells you that "10" sorted before "2".
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from PySide6.QtCore import QModelIndex, QPersistentModelIndex, Qt

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import SearchHit
from qtrequestory.ui.pages import sync_format
from qtrequestory.ui.results_model import (
    ResultsModel,
    format_day,
    format_size,
    format_time,
)

FDI_1 = "aaaaaaaa-1111-4222-8333-444444444444"
FDI_2 = "bbbbbbbb-1111-4222-8333-444444444444"
KEY_A = "MOD_TEST_A"
KEY_B = "KEY_ALPHA"

W = ResultsModel.COL_WHEN
K = ResultsModel.COL_KEY
F = ResultsModel.COL_FDI
N = ResultsModel.COL_NDOCS
S = ResultsModel.COL_SIZE


def hit(entry_id: int = 1, *, day: date = date(2026, 9, 18), seq: int = 1,
        fdi: str | None = FDI_1, key: str = KEY_A,
        request_date: str | None = "2026-09-18T10:38:28.776Z",
        ndocs: int | None = 3, body_len: int = 4096) -> SearchHit:
    rel = f"coll/{day:%Y}/{day:%m}/{day:%Y%m%d}.txt"
    return SearchHit(
        entry_id=entry_id, env="coll", day=day, rel_path=rel, seq=seq,
        name=f"{fdi}_{key}_10b6016b0000003{entry_id % 10}", fdi=fdi, template_key=key,
        call_id=f"10b6016b0000003{entry_id % 10}", well_formed=True,
        request_date=request_date, ndocs=ndocs, dossier_number="DA00000001",
        header_offset=1024, header_len=64, body_offset=1088, body_len=body_len,
        json_ok=True, file_path=Path("mirror") / rel,
    )


def flat(hits) -> ResultsModel:
    model = ResultsModel()
    model.set_grouped(False)
    model.set_hits(hits)
    return model


def grouped(hits) -> ResultsModel:
    model = ResultsModel()
    model.set_hits(hits)
    return model


def cell(model, row, column, role=Qt.ItemDataRole.DisplayRole, parent=QModelIndex()):
    return model.data(model.index(row, column, parent), role)


def leaf_ids(model: ResultsModel) -> list[int]:
    """Every leaf's entry id, in display order (through the groups if any)."""
    ids = []
    for row in range(model.rowCount()):
        top = model.index(row, 0)
        if model.rowCount(top):
            ids += [model.index(r, 0, top).data(ResultsModel.HIT_ROLE).entry_id
                    for r in range(model.rowCount(top))]
        else:
            ids.append(top.data(ResultsModel.HIT_ROLE).entry_id)
    return ids


# ------------------------------------------------------------- formatters ---

def test_the_formatters_speak_the_page_s_language():
    assert format_day(date(2026, 9, 18)) == "18/09/2026"
    assert format_time("2026-09-18T10:38:28.776Z") == "10:38:28"
    assert format_time(None) == strings.SEARCH_VALUE_MISSING
    assert format_time("2026-08-03T07:26:09.78Z") == "07:26:09"
    assert format_time("non una data") == "non una data"


def test_sizes_are_whole_kilobytes_rounded_up():
    assert format_size(4096) == strings.SYNC_UNIT_KB.format(n="4")
    assert format_size(300) == strings.SYNC_UNIT_KB.format(n="1"), "a small body is 1 KB, not 0"
    assert format_size(2 * 1024 * 1024) == strings.SYNC_UNIT_KB.format(n="2.048")
    assert format_size(1024) == sync_format.format_size(1024, whole_kb=True)


# ------------------------------------------------------------------ shape ---

def test_grouping_by_fdi_is_on_by_default():
    assert ResultsModel().grouped() is True


def test_the_headers_are_quando_key_fdi_doc_dim():
    model = ResultsModel()
    headers = [model.headerData(c, Qt.Orientation.Horizontal) for c in range(model.columnCount())]
    assert headers == [strings.SEARCH_COL_WHEN, strings.SEARCH_COL_KEY, strings.SEARCH_COL_FDI,
                       strings.SEARCH_COL_NDOCS, strings.SEARCH_COL_SIZE]
    right = int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    left = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    align = Qt.ItemDataRole.TextAlignmentRole
    assert model.headerData(N, Qt.Orientation.Horizontal, align) == right
    assert model.headerData(S, Qt.Orientation.Horizontal, align) == right
    assert model.headerData(K, Qt.Orientation.Horizontal, align) == left


def test_flat_rows_show_date_and_time_the_whole_fdi_and_the_numbers():
    model = flat([hit(1, ndocs=3, body_len=4096)])
    assert model.rowCount() == 1
    assert cell(model, 0, W) == "18/09 10:38:28"
    assert cell(model, 0, K) == KEY_A
    assert cell(model, 0, F) == FDI_1, "the whole FDI, never cut to 8 characters"
    assert cell(model, 0, N) == "3"
    assert cell(model, 0, S) == strings.SYNC_UNIT_KB.format(n="4")


def test_groups_carry_the_full_fdi_the_newest_time_and_the_count():
    model = grouped([hit(1, request_date="2026-09-18T10:38:31.000Z"), hit(2),
                     hit(3, fdi=FDI_2, request_date="2026-09-18T09:00:00.000Z")])
    assert model.rowCount() == 2
    assert cell(model, 0, 0) == strings.SEARCH_GROUP_LABEL.format(
        fdi=FDI_1, when="18/09/2026 10:38:31",
        calls=strings.SEARCH_SUMMARY_CALLS_MANY.format(n=2))
    assert cell(model, 1, 0).endswith(strings.SEARCH_SUMMARY_CALLS_ONE)
    group = model.index(0, 0)
    assert model.rowCount(group) == 2
    assert model.data(group, ResultsModel.HIT_ROLE) is None
    assert model.data(group, ResultsModel.GROUP_ROLE) == FDI_1
    assert not model.flags(group) & Qt.ItemFlag.ItemIsSelectable
    child = model.index(0, W, group)
    assert child.data() == "10:38:31", "inside a one-day group, the time is enough"
    assert child.parent() == group
    assert model.flags(child) & Qt.ItemFlag.ItemIsDragEnabled


def test_a_group_spanning_several_days_keeps_the_date_on_each_row():
    model = grouped([hit(1), hit(2, day=date(2026, 9, 16), request_date="2026-09-16T08:15:00Z")])
    group = model.index(0, 0)
    assert model.index(1, W, group).data() == "16/09 08:15:00"


def test_calls_without_an_fdi_have_their_own_group():
    model = grouped([hit(1, fdi=None)])
    assert cell(model, 0, 0).startswith(strings.SEARCH_GROUP_NO_FDI)


def test_a_missing_time_and_an_unknown_document_count_have_their_own_glyphs():
    model = flat([hit(1, request_date=None, ndocs=None, fdi=None)])
    assert cell(model, 0, W) == "18/09 " + strings.SEARCH_VALUE_MISSING
    assert cell(model, 0, N) == strings.SEARCH_VALUE_UNKNOWN
    assert cell(model, 0, F) == strings.SEARCH_VALUE_MISSING


def test_the_tooltips_hold_what_the_cells_shorten():
    h = hit(1)
    model = flat([h])
    tip = Qt.ItemDataRole.ToolTipRole
    assert cell(model, 0, W, tip) == f"18/09/2026 {h.request_date}"
    assert cell(model, 0, K, tip) == KEY_A


def test_numbers_are_right_aligned_and_use_tabular_figures():
    model = flat([hit(1)])
    right = int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    for column in (N, S):
        assert cell(model, 0, column, Qt.ItemDataRole.TextAlignmentRole) == right
        font = cell(model, 0, column, Qt.ItemDataRole.FontRole)
        assert font.featureValue(font.Tag("tnum")) == 1
    key_font = cell(model, 0, K, Qt.ItemDataRole.FontRole)
    assert key_font.families()[:2] == ["Cascadia Mono", "Consolas"]


def test_index_of_finds_a_hit_inside_its_group():
    hits = [hit(1), hit(2, fdi=FDI_2), hit(3)]
    model = grouped(hits)
    index = model.index_of(hits[2])
    assert index.data(ResultsModel.HIT_ROLE) is hits[2]
    assert index.parent().data(ResultsModel.GROUP_ROLE) == FDI_1
    assert not model.index_of(hit(99)).isValid()


def test_switching_the_grouping_keeps_the_hits():
    hits = [hit(1), hit(2, fdi=FDI_2)]
    model = grouped(hits)
    model.set_grouped(False)
    assert model.rowCount() == 2 and leaf_ids(model) == [1, 2]
    assert model.hits() == hits


# ------------------------------------------------------------------- sort ---

def test_without_a_sort_column_the_core_order_is_kept():
    hits = [hit(3, day=date(2026, 9, 18)), hit(1, day=date(2026, 9, 15)),
            hit(2, day=date(2026, 9, 16))]
    model = flat(hits)
    model.sort(-1)
    assert leaf_ids(model) == [3, 1, 2]


def test_quando_sorts_by_day_then_time_then_sequence():
    hits = [
        hit(1, day=date(2026, 9, 15), request_date="2026-09-15T09:00:00.000Z"),
        hit(2, day=date(2026, 9, 18), request_date="2026-09-18T08:00:00.000Z"),
        hit(3, day=date(2026, 9, 18), request_date="2026-09-18T12:00:00.000Z"),
        hit(4, day=date(2026, 9, 18), request_date=None, seq=7),
        hit(5, day=date(2026, 9, 18), request_date=None, seq=9),
    ]
    model = flat(hits)
    model.sort(W, Qt.SortOrder.AscendingOrder)
    assert leaf_ids(model) == [1, 4, 5, 2, 3]
    model.sort(W, Qt.SortOrder.DescendingOrder)
    assert leaf_ids(model) == [3, 2, 5, 4, 1]


def test_doc_and_dim_sort_as_numbers_not_as_text():
    hits = [hit(1, ndocs=2, body_len=2048), hit(2, ndocs=10, body_len=10240),
            hit(3, ndocs=None, body_len=512)]
    model = flat(hits)
    model.sort(N)
    assert leaf_ids(model) == [3, 1, 2], "unknown first, then 2 < 10"
    model.sort(S)
    assert leaf_ids(model) == [3, 1, 2]


def test_text_columns_sort_case_insensitively():
    model = flat([hit(1, key="MOD_TEST_B", fdi=FDI_2), hit(2, key="mod_test_a", fdi=FDI_1.upper())])
    model.sort(K)
    assert leaf_ids(model) == [2, 1]
    model.sort(F)
    assert leaf_ids(model) == [2, 1]


def test_groups_follow_their_best_row_and_sort_inside():
    hits = [hit(1, key="MOD_TEST_C"), hit(2, fdi=FDI_2, key="MOD_TEST_A"), hit(3, key="MOD_TEST_B")]
    model = grouped(hits)
    model.sort(K)
    assert [model.index(r, 0).data(ResultsModel.GROUP_ROLE) for r in range(2)] == [FDI_2, FDI_1]
    assert leaf_ids(model) == [2, 3, 1]


def test_sorting_keeps_persistent_indexes_on_their_hit():
    hits = [hit(1, ndocs=5), hit(2, ndocs=1), hit(3, fdi=FDI_2, ndocs=3)]
    model = grouped(hits)
    kept = QPersistentModelIndex(model.index_of(hits[0]))
    model.sort(N)
    assert model.data(QModelIndex(kept), ResultsModel.HIT_ROLE) is hits[0]
