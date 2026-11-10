"""qtrequestory.officina.batch.elenco: reading the template key list.

Synthetic data only (this repository is public).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from qtrequestory.officina.batch.elenco import (
    NO_PACKAGE,
    Elenco,
    ElencoError,
    ElencoRow,
    load_elenco,
)

HEADER = "Template key;Nome Template ICM;Nome iniziativa;codice iniziativa ;package name"


def _write(tmp_path: Path, text: str, encoding: str = "cp1252") -> Path:
    path = tmp_path / "elenco.csv"
    path.write_bytes(text.encode(encoding))
    return path


def test_reads_cp1252_with_header(tmp_path):
    text = f"{HEADER}\r\nMOD_TEST_A;Modulo à;Iniziativa;1;111_PKG\r\nMOD_TEST_B;x;y;2;222_PKG\r\n"
    elenco = load_elenco(_write(tmp_path, text))
    assert elenco.rows == (
        ElencoRow("MOD_TEST_A", "111_PKG"),
        ElencoRow("MOD_TEST_B", "222_PKG"),
    )
    assert elenco.skipped == 0


def test_trailing_spaces_collapse_packages(tmp_path):
    text = f"{HEADER}\nMOD_TEST_A;;;;111_PKG\nMOD_TEST_B;;;;111_PKG   \n"
    elenco = load_elenco(_write(tmp_path, text))
    assert elenco.packages() == [("111_PKG", 2)]


def test_duplicate_key_same_package_kept_once(tmp_path):
    text = f"{HEADER}\nMOD_TEST_A;;;;111_PKG\nmod_test_a ;;;;111_PKG \n"
    elenco = load_elenco(_write(tmp_path, text))
    assert elenco.rows == (ElencoRow("MOD_TEST_A", "111_PKG"),)
    assert elenco.packages() == [("111_PKG", 1)]


def test_key_in_two_packages(tmp_path):
    text = f"{HEADER}\nMOD_TEST_A;;;;111_PKG\nMOD_TEST_A;;;;222_PKG\nMOD_TEST_B;;;;222_PKG\n"
    elenco = load_elenco(_write(tmp_path, text))
    assert elenco.packages_of("mod_test_a") == ("111_PKG", "222_PKG")
    assert elenco.packages_of("MOD_TEST_Z") == ()
    assert elenco.packages() == [("111_PKG", 1), ("222_PKG", 2)]
    assert elenco.keys_of(["222_PKG", "111_PKG"]) == ["MOD_TEST_A", "MOD_TEST_B"]
    assert elenco.keys_of({"222_PKG"}) == ["MOD_TEST_A", "MOD_TEST_B"]


def test_blank_key_skipped_and_counted(tmp_path):
    text = f"{HEADER}\n;;;;111_PKG\nMOD_TEST_A;;;;111_PKG\n   ;;;;222_PKG\n"
    elenco = load_elenco(_write(tmp_path, text))
    assert elenco.skipped == 2
    assert elenco.rows == (ElencoRow("MOD_TEST_A", "111_PKG"),)


def test_blank_package_is_no_package(tmp_path):
    text = f"{HEADER}\nMOD_TEST_A;;;;\nMOD_TEST_B;;;\n"
    elenco = load_elenco(_write(tmp_path, text))
    assert [r.package for r in elenco.rows] == [NO_PACKAGE, NO_PACKAGE]
    assert elenco.packages() == [(NO_PACKAGE, 2)]


def test_no_header_uses_columns_1_and_5(tmp_path):
    text = "MOD_TEST_A;a;b;c;111_PKG\nMOD_TEST_B;a;b;c;222_PKG\n"
    elenco = load_elenco(_write(tmp_path, text))
    assert elenco.rows == (
        ElencoRow("MOD_TEST_A", "111_PKG"),
        ElencoRow("MOD_TEST_B", "222_PKG"),
    )


def test_header_columns_found_by_name_in_any_order(tmp_path):
    text = " PACKAGE NAME ;x;template KEY\n111_PKG;a;MOD_TEST_A\n"
    elenco = load_elenco(_write(tmp_path, text))
    assert elenco.rows == (ElencoRow("MOD_TEST_A", "111_PKG"),)


def test_utf8_bom(tmp_path):
    text = f"{HEADER}\nMOD_TEST_A;Modulo à;;;111_PKG\n"
    elenco = load_elenco(_write(tmp_path, text, "utf-8-sig"))
    assert elenco.rows == (ElencoRow("MOD_TEST_A", "111_PKG"),)


def test_missing_file_and_too_few_columns_raise_elenco_error(tmp_path):
    with pytest.raises(ElencoError):
        load_elenco(tmp_path / "manca.csv")
    with pytest.raises(ElencoError):
        load_elenco(_write(tmp_path, "MOD_TEST_A;a\nMOD_TEST_B;b\n"))
    with pytest.raises(ElencoError):
        load_elenco(_write(tmp_path, "Template key;altro\nMOD_TEST_A;a\n"))


def test_empty_file_raises(tmp_path):
    with pytest.raises(ElencoError):
        load_elenco(_write(tmp_path, ""))
    with pytest.raises(ElencoError):
        load_elenco(_write(tmp_path, "\r\n\r\n"))


def test_directory_raises_elenco_error(tmp_path):
    with pytest.raises(ElencoError):
        load_elenco(tmp_path)


def test_unterminated_quote_past_the_field_limit_is_an_elenco_error(tmp_path):
    """Review item 4: ``csv.Error`` ("field larger than field limit") escaped."""
    text = f'{HEADER}\n"MOD_TEST_A;x;y;z;111_PKG\n' + "x" * 200_000
    with pytest.raises(ElencoError, match="virgoletta"):
        load_elenco(_write(tmp_path, text))


def test_unterminated_quote_swallowing_rows_is_an_elenco_error(tmp_path):
    """Review item 4: a small file with an open quote silently ate every row after it."""
    text = f'{HEADER}\nMOD_TEST_A;"aperta;;;111_PKG\nMOD_TEST_B;;;;111_PKG\nMOD_TEST_C;;;;222_PKG\n'
    with pytest.raises(ElencoError, match="virgoletta"):
        load_elenco(_write(tmp_path, text))
    text = f'{HEADER}\n"MOD_TEST_A;;;;111_PKG\nMOD_TEST_B;;;;111_PKG\n'
    with pytest.raises(ElencoError):
        load_elenco(_write(tmp_path, text))


def test_a_binary_file_is_not_a_list(tmp_path):
    """Review item 4: an .xlsx picked by mistake "loaded" as thousands of junk keys."""
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("xl/sharedStrings.xml", "MOD_TEST_A;;;;111_PKG\n" * 5000)
    path = tmp_path / "elenco.xlsx"
    path.write_bytes(buffer.getvalue())
    with pytest.raises(ElencoError, match="non sembra un elenco CSV"):
        load_elenco(path)


@pytest.mark.parametrize("cell", ["MOD_\x07TEST", "MOD\x1bTEST"])
def test_a_control_character_in_a_key_is_not_a_list(tmp_path, cell):
    with pytest.raises(ElencoError, match="non sembra un elenco CSV"):
        load_elenco(_write(tmp_path, f"{HEADER}\n{cell};;;;111_PKG\n", "utf-8"))


def test_a_line_break_in_a_key_cell_is_not_a_list(tmp_path):
    text = f'{HEADER}\n"MOD_TEST_A\nMOD_TEST_B";;;;111_PKG\n'
    with pytest.raises(ElencoError, match="non sembra un elenco CSV"):
        load_elenco(_write(tmp_path, text))


def test_a_multiline_description_cell_is_still_fine(tmp_path):
    text = f'{HEADER}\nMOD_TEST_A;"Modulo\r\nsu due righe";;;111_PKG\n'
    assert load_elenco(_write(tmp_path, text)).rows == (ElencoRow("MOD_TEST_A", "111_PKG"),)


def test_elenco_is_frozen_value():
    elenco = Elenco(rows=(ElencoRow("MOD_TEST_A", "111_PKG"),), skipped=0)
    assert elenco.packages_of("MOD_TEST_A") == ("111_PKG",)
