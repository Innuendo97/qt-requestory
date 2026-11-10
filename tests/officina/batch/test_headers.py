"""qtrequestory.officina.batch.headers: the header table of a Genera run.

Synthetic data only (this repository is public).
"""
from __future__ import annotations

import pytest

from qtrequestory.core.config import OfficinaSettings
from qtrequestory.officina.batch.headers import AUTOMATIC, build_headers, default_rows
from qtrequestory.officina.generator import POSTMAN_TOKEN, HeaderError


def _uuids():
    n = 0

    def new_uuid() -> str:
        nonlocal n
        n += 1
        return f"uuid-{n}"

    return new_uuid


def _build(rows, **kw):
    args = {"key": "MOD_TEST_A", "now_ms": 1700000000000, "new_uuid": _uuids(),
            "postman_token": "token-test"}
    args.update(kw)
    return build_headers(rows, **args)


def _automatic_rows():
    return [(name, "") for name in AUTOMATIC]


def test_default_rows_list_automatic_then_profile():
    settings = OfficinaSettings(header_profile={"office_id": "OFF_TEST", "service_number": "SN_TEST"})
    assert default_rows(settings) == [
        ("template_key", ""), ("current_timestamp", ""), ("correlation_id", ""), (POSTMAN_TOKEN, ""),
        ("office_id", "OFF_TEST"), ("service_number", "SN_TEST"),
    ]


def test_default_rows_profile_wins_on_same_name():
    settings = OfficinaSettings(header_profile={"postman-token": "dal-profilo", "IMEL": "active"})
    assert default_rows(settings) == [
        ("template_key", ""), ("current_timestamp", ""), ("correlation_id", ""),
        ("postman-token", "dal-profilo"), ("IMEL", "active"),
    ]


def test_blank_automatic_values_are_computed():
    headers = _build(_automatic_rows())
    assert headers == {
        "template_key": "MOD_TEST_A",
        "current_timestamp": "1700000000000",
        "correlation_id": "uuid-1",
        POSTMAN_TOKEN: "token-test",
    }


def test_new_uuid_called_only_when_needed():
    def boom() -> str:
        raise AssertionError("new_uuid must not be called")

    headers = _build([("correlation_id", "fisso")], new_uuid=boom)
    assert headers == {"correlation_id": "fisso"}


def test_blank_postman_token_falls_back_to_default():
    headers = _build([(POSTMAN_TOKEN, "")], postman_token="  ")
    assert headers == {POSTMAN_TOKEN: OfficinaSettings().postman_token}


def test_explicit_value_overrides_automatic():
    rows = [("template_key", "MOD_TEST_ALTRO"), ("current_timestamp", "123"),
            ("correlation_id", "corr-test"), (POSTMAN_TOKEN, "mio")]
    assert _build(rows) == {"template_key": "MOD_TEST_ALTRO", "current_timestamp": "123",
                            "correlation_id": "corr-test", POSTMAN_TOKEN: "mio"}


def test_removed_row_is_not_sent():
    rows = [row for row in _automatic_rows() if row[0] != POSTMAN_TOKEN]
    headers = _build(rows)
    assert not any(name.casefold() == POSTMAN_TOKEN.casefold() for name in headers)
    assert set(headers) == {"template_key", "current_timestamp", "correlation_id"}


def test_added_row_is_sent():
    headers = _build([*_automatic_rows(), ("IMEL", "active")])
    assert headers["IMEL"] == "active"


def test_non_automatic_blank_value_is_sent_blank():
    assert _build([("office_id", "")]) == {"office_id": ""}


def test_last_duplicate_wins():
    rows = [("office_id", "PRIMO"), ("template_key", ""), ("OFFICE_ID", "SECONDO")]
    headers = _build(rows)
    assert headers == {"OFFICE_ID": "SECONDO", "template_key": "MOD_TEST_A"}


def test_last_duplicate_of_automatic_wins_even_when_blank():
    headers = _build([("correlation_id", "fisso"), ("Correlation_Id", "")])
    assert headers == {"Correlation_Id": "uuid-1"}


def test_names_and_values_are_stripped():
    assert _build([("  IMEL ", " active  ")]) == {"IMEL": "active"}


def test_newline_in_value_raises_header_error():
    with pytest.raises(HeaderError, match="non può andare a capo"):
        _build([("IMEL", "act\nive")])


def test_invalid_name_raises_header_error():
    with pytest.raises(HeaderError, match="non è un nome di intestazione valido"):
        _build([("nome con spazi", "x")])
    with pytest.raises(HeaderError, match="gestita dal client HTTP"):
        _build([("Host", "x")])


def test_blank_name_row_ignored():
    headers = _build([("", "valore"), ("   ", "altro"), ("IMEL", "active")])
    assert headers == {"IMEL": "active"}
