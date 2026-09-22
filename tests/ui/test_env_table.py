"""The environments table, shared by the first-run wizard and Impostazioni.

Both callers do the same three things — load a list, let the user edit it, read
it back — so the contract tested here is the roundtrip plus the ``changed``
signal their dirty tracking depends on.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import Environment
from qtrequestory.ui.env_table import EnvTable

ENVS = [
    Environment("coll", "https://example.invalid/coll/", True),
    Environment("svil", "https://example.invalid/svil/", False),
]


@pytest.fixture
def table(qtbot):
    widget = EnvTable()
    qtbot.addWidget(widget)
    return widget


def test_headers_are_the_italian_column_names(table):
    labels = [table.horizontalHeaderItem(i).text() for i in range(table.columnCount())]
    assert labels == [strings.ENV_COL_ENABLED, strings.ENV_COL_NAME, strings.ENV_COL_URL]


def test_environments_roundtrip_including_the_enabled_flag(table):
    table.set_environments(ENVS)
    assert table.rowCount() == 2
    assert table.environments() == ENVS


def test_loading_environments_does_not_look_like_a_user_edit(table, qtbot):
    """Impostazioni enables [Salva] on ``changed``: filling the form must not."""
    seen: list[int] = []
    table.changed.connect(lambda: seen.append(1))
    table.set_environments(ENVS)
    assert seen == []


def test_editing_a_cell_reports_a_change(table):
    table.set_environments(ENVS)
    seen: list[int] = []
    table.changed.connect(lambda: seen.append(1))

    table.item(0, EnvTable.COL_NAME).setText("prod")

    assert seen == [1]
    assert table.environments()[0].name == "prod"


def test_unchecking_the_box_disables_that_environment(table):
    table.set_environments(ENVS)
    seen: list[int] = []
    table.changed.connect(lambda: seen.append(1))

    table.item(0, EnvTable.COL_ENABLED).setCheckState(Qt.CheckState.Unchecked)

    assert seen == [1]
    assert table.environments()[0].enabled is False


def test_add_row_appends_an_empty_enabled_row_and_reports_a_change(table):
    table.set_environments(ENVS)
    seen: list[int] = []
    table.changed.connect(lambda: seen.append(1))

    row = table.add_row()

    assert row == 2 and table.rowCount() == 3
    assert seen == [1]
    assert table.environments() == ENVS, "a blank row is not an environment yet"

    table.item(row, EnvTable.COL_NAME).setText("prod")
    table.item(row, EnvTable.COL_URL).setText("https://example.invalid/prod/")
    assert table.environments()[-1] == Environment("prod", "https://example.invalid/prod/", True)


def test_add_row_can_be_given_an_environment(table):
    table.add_row(Environment("prod", "https://example.invalid/prod/", False))
    assert table.environments() == [Environment("prod", "https://example.invalid/prod/", False)]


def test_remove_selected_drops_the_selected_rows(table):
    table.set_environments(ENVS)
    seen: list[int] = []
    table.changed.connect(lambda: seen.append(1))

    table.selectRow(0)
    removed = table.remove_selected()

    assert removed == 1
    assert [e.name for e in table.environments()] == ["svil"]
    assert seen == [1]


def test_remove_selected_without_a_selection_changes_nothing(table):
    table.set_environments(ENVS)
    seen: list[int] = []
    table.changed.connect(lambda: seen.append(1))

    assert table.remove_selected() == 0
    assert table.environments() == ENVS
    assert seen == []


def test_values_are_trimmed(table):
    table.add_row()
    table.item(0, EnvTable.COL_NAME).setText("  coll  ")
    table.item(0, EnvTable.COL_URL).setText(" https://example.invalid/coll/ ")
    assert table.environments() == [Environment("coll", "https://example.invalid/coll/", True)]


def test_import_from_file_replaces_the_rows_through_the_importer(table, tmp_path: Path):
    table.set_environments(ENVS)
    seen: list[int] = []
    table.changed.connect(lambda: seen.append(1))
    imported = [Environment("prod", "https://example.invalid/prod/", True)]
    calls: list[Path] = []

    def importer(path: Path) -> list[Environment]:
        calls.append(path)
        return imported

    result = table.import_from_file(tmp_path / "environments.json", importer)

    assert calls == [tmp_path / "environments.json"]
    assert result == imported
    assert table.environments() == imported
    assert seen == [1], "an import is one change, whatever the row count"


def test_a_malformed_file_leaves_the_table_untouched(table, tmp_path: Path):
    table.set_environments(ENVS)

    def importer(path: Path) -> list[Environment]:
        raise ValueError("environments.json non valido")

    with pytest.raises(ValueError):
        table.import_from_file(tmp_path / "bad.json", importer)

    assert table.environments() == ENVS
