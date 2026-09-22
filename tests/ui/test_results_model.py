"""The results table's model: what each column shows and how it sorts.

Pure model tests: no widget is created, nothing is shown. A ``QAbstractTableModel``
answers ``data()`` on its own, so the whole rendering contract of the Ricerca
table (formats, tooltips, alignment, the hit behind a row, the sort keys) can be
pinned down here — which is also where a regression would actually be caught,
because a screenshot of a table view never tells you that "10" sorted before "2".
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from PySide6.QtCore import QModelIndex, Qt

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import SearchHit
from qtrequestory.ui.results_model import (
    ResultsModel,
    ResultsProxy,
    format_day,
    format_fdi,
    format_size,
    format_time,
)

FDI_1 = "aaaaaaaa-1111-4222-8333-444444444444"
FDI_2 = "bbbbbbbb-1111-4222-8333-444444444444"
KEY_LONG = "MOD_TEST_SUMMARY_PLAN_FIX_GAS"
KEY_SHORT = "CTR_PLAN_FIX_GAS"


def hit(
    entry_id: int = 1,
    *,
    day: date = date(2026, 9, 18),
    seq: int = 1,
    fdi: str | None = FDI_1,
    key: str = KEY_LONG,
    call_id: str | None = "1a2b3c0200000031",
    request_date: str | None = "2026-09-18T10:38:28.776Z",
    ndocs: int | None = 3,
    body_len: int = 4096,
) -> SearchHit:
    """A synthetic hit; every field the model reads is a keyword argument."""
    rel = f"coll/{day:%Y}/{day:%m}/{day:%Y%m%d}.txt"
    return SearchHit(
        entry_id=entry_id,
        env="coll",
        day=day,
        rel_path=rel,
        seq=seq,
        name=f"{fdi}_{key}_{call_id}",
        fdi=fdi,
        template_key=key,
        call_id=call_id,
        well_formed=True,
        request_date=request_date,
        ndocs=ndocs,
        dossier_number="DA00000001",
        header_offset=1024,
        body_offset=1088,
        body_len=body_len,
        json_ok=True,
        file_path=Path("mirror") / rel,
    )


@pytest.fixture
def model() -> ResultsModel:
    return ResultsModel()


def display(model: ResultsModel, row: int, column: int):
    return model.data(model.index(row, column), Qt.ItemDataRole.DisplayRole)


def tooltip(model: ResultsModel, row: int, column: int):
    return model.data(model.index(row, column), Qt.ItemDataRole.ToolTipRole)


# ------------------------------------------------------------- formatters ---

def test_the_formatters_speak_the_page_s_language():
    assert format_day(date(2026, 9, 18)) == "18/09/2026"
    assert format_time("2026-09-18T10:38:28.776Z") == "10:38:28"
    assert format_time(None) == strings.SEARCH_VALUE_MISSING
    # A two-digit fraction is what some real timestamps carry; it must not crash.
    assert format_time("2026-08-03T07:26:09.78Z") == "07:26:09"
    # Anything the parser cannot read is shown as-is rather than swallowed.
    assert format_time("non una data") == "non una data"
    assert format_fdi(FDI_1) == "aaaaaaaa" + strings.SEARCH_ELLIPSIS
    assert format_fdi(None) == strings.SEARCH_VALUE_MISSING
    assert format_fdi("abcd") == "abcd", "a short FDI is not decorated"


def test_sizes_are_whole_kilobytes_rounded_up():
    assert format_size(4096) == strings.SEARCH_SIZE_KB.format(n="4")
    assert format_size(300) == strings.SEARCH_SIZE_KB.format(n="1"), "a small body is 1 KB, not 0"
    assert format_size(0) == strings.SEARCH_SIZE_KB.format(n="0")
    assert format_size(2 * 1024 * 1024) == strings.SEARCH_SIZE_KB.format(n="2.048")


# ------------------------------------------------------------------ shape ---

def test_the_model_is_empty_until_hits_are_set(model):
    assert model.rowCount(QModelIndex()) == 0
    assert model.columnCount(QModelIndex()) == len(ResultsModel.COLUMNS)
    assert model.hit_at(0) is None


def test_the_headers_are_the_columns_design_ui_lists(model):
    headers = [
        model.headerData(c, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)
        for c in range(model.columnCount())
    ]
    assert headers == [
        strings.SEARCH_COL_DAY, strings.SEARCH_COL_TIME, strings.SEARCH_COL_KEY,
        strings.SEARCH_COL_FDI, strings.SEARCH_COL_NDOCS, strings.SEARCH_COL_SIZE,
        strings.SEARCH_COL_CALL_ID, strings.SEARCH_COL_FILE,
    ]
    assert ResultsModel.HIDDEN_COLUMNS == (ResultsModel.COL_CALL_ID, ResultsModel.COL_FILE)


def test_set_hits_replaces_the_rows_and_notifies(model, qtbot):
    with qtbot.waitSignal(model.modelReset):
        model.set_hits([hit(1), hit(2)])
    assert model.rowCount() == 2
    with qtbot.waitSignal(model.modelReset):
        model.set_hits([])
    assert model.rowCount() == 0


# -------------------------------------------------------------- rendering ---

def test_every_visible_column_renders_its_field(model):
    model.set_hits([hit(1, ndocs=3, body_len=4096)])
    assert display(model, 0, ResultsModel.COL_DAY) == "18/09/2026"
    assert display(model, 0, ResultsModel.COL_TIME) == "10:38:28"
    assert display(model, 0, ResultsModel.COL_KEY) == KEY_LONG, "full text; the delegate elides"
    assert display(model, 0, ResultsModel.COL_FDI) == "aaaaaaaa" + strings.SEARCH_ELLIPSIS
    assert display(model, 0, ResultsModel.COL_NDOCS) == "3"
    assert display(model, 0, ResultsModel.COL_SIZE) == strings.SEARCH_SIZE_KB.format(n="4")


def test_a_missing_time_and_an_unknown_document_count_have_their_own_glyphs(model):
    model.set_hits([hit(1, request_date=None, ndocs=None, fdi=None, call_id=None)])
    assert display(model, 0, ResultsModel.COL_TIME) == strings.SEARCH_VALUE_MISSING
    assert display(model, 0, ResultsModel.COL_NDOCS) == strings.SEARCH_VALUE_UNKNOWN
    assert display(model, 0, ResultsModel.COL_FDI) == strings.SEARCH_VALUE_MISSING
    assert display(model, 0, ResultsModel.COL_CALL_ID) == strings.SEARCH_VALUE_MISSING


def test_the_truncated_columns_keep_the_whole_value_in_the_tooltip(model):
    h = hit(1)
    model.set_hits([h])
    assert tooltip(model, 0, ResultsModel.COL_TIME) == h.request_date
    assert tooltip(model, 0, ResultsModel.COL_KEY) == KEY_LONG
    assert tooltip(model, 0, ResultsModel.COL_FDI) == FDI_1
    assert tooltip(model, 0, ResultsModel.COL_DAY) is None, "no tooltip where nothing is hidden"


def test_a_missing_time_has_no_tooltip(model):
    model.set_hits([hit(1, request_date=None, fdi=None)])
    assert tooltip(model, 0, ResultsModel.COL_TIME) is None
    assert tooltip(model, 0, ResultsModel.COL_FDI) is None


def test_the_numeric_columns_are_right_aligned(model):
    model.set_hits([hit(1)])
    right = int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    for column in (ResultsModel.COL_NDOCS, ResultsModel.COL_SIZE):
        assert model.data(model.index(0, column), Qt.ItemDataRole.TextAlignmentRole) == right
    left = model.data(model.index(0, ResultsModel.COL_KEY), Qt.ItemDataRole.TextAlignmentRole)
    assert left != right


def test_the_hidden_columns_carry_the_call_id_and_the_file(model):
    h = hit(1)
    model.set_hits([h])
    assert display(model, 0, ResultsModel.COL_CALL_ID) == h.call_id
    assert display(model, 0, ResultsModel.COL_FILE) == h.rel_path
    assert tooltip(model, 0, ResultsModel.COL_FILE) == str(h.file_path)


def test_every_cell_carries_the_hit_itself(model):
    hits = [hit(1), hit(2)]
    model.set_hits(hits)
    assert model.hit_at(1) is hits[1]
    assert model.hit_at(9) is None
    for column in range(model.columnCount()):
        assert model.data(model.index(1, column), ResultsModel.HIT_ROLE) is hits[1]
    assert model.hits() == hits


# ------------------------------------------------------------------- sort ---

def _sorted_ids(hits, column, order=Qt.SortOrder.AscendingOrder) -> list[int]:
    model = ResultsModel()
    model.set_hits(hits)
    proxy = ResultsProxy()
    proxy.setSourceModel(model)
    proxy.sort(column, order)
    return [
        proxy.data(proxy.index(row, 0), ResultsModel.HIT_ROLE).entry_id
        for row in range(proxy.rowCount())
    ]


def test_giorno_and_ora_sort_by_day_then_time_then_sequence():
    hits = [
        hit(1, day=date(2026, 9, 15), request_date="2026-09-15T09:00:00.000Z"),
        hit(2, day=date(2026, 9, 18), request_date="2026-09-18T08:00:00.000Z"),
        hit(3, day=date(2026, 9, 18), request_date="2026-09-18T12:00:00.000Z"),
        hit(4, day=date(2026, 9, 18), request_date=None, seq=7),
        hit(5, day=date(2026, 9, 18), request_date=None, seq=9),
    ]
    # Undated entries of a day come first ascending (they sort last descending,
    # exactly like the core's "ORDER BY day DESC, (request_date IS NULL), ...").
    assert _sorted_ids(hits, ResultsModel.COL_DAY) == [1, 4, 5, 2, 3]
    assert _sorted_ids(hits, ResultsModel.COL_TIME) == [1, 4, 5, 2, 3]
    assert _sorted_ids(hits, ResultsModel.COL_DAY, Qt.SortOrder.DescendingOrder) == [3, 2, 5, 4, 1]


def test_n_doc_and_dim_sort_as_numbers_not_as_text():
    hits = [hit(1, ndocs=2, body_len=2048), hit(2, ndocs=10, body_len=10240),
            hit(3, ndocs=None, body_len=512)]
    assert _sorted_ids(hits, ResultsModel.COL_NDOCS) == [3, 1, 2], "unknown first, then 2 < 10"
    assert _sorted_ids(hits, ResultsModel.COL_SIZE) == [3, 1, 2]


def test_text_columns_sort_case_insensitively():
    hits = [hit(1, key=KEY_LONG, fdi=FDI_2), hit(2, key=KEY_SHORT, fdi=FDI_1.upper())]
    assert _sorted_ids(hits, ResultsModel.COL_KEY) == [2, 1]
    assert _sorted_ids(hits, ResultsModel.COL_FDI) == [2, 1]


def test_without_a_sort_column_the_proxy_keeps_the_order_the_core_delivered():
    hits = [hit(3, day=date(2026, 9, 18)), hit(1, day=date(2026, 9, 15)),
            hit(2, day=date(2026, 9, 16))]
    assert _sorted_ids(hits, -1) == [3, 1, 2]
