"""core/index/scanner.py: byte-exact offsets, orphan rules, JSON vs regex extraction."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from qtrequestory.core.events import CancelToken, Cancelled
from qtrequestory.core.index.scanner import HEADER_RE, REQDATE_RE, ScannedEntry, ScanStats, scan_daily_file
from tests.conftest import FDI_A, FDI_B, FDI_C, KEY_CTE, KEY_EMAIL, KEY_NUMERIC, KEY_SINT, entry_name, make_daily_file, synthetic_body

CRLF_DAY = ("coll", date(2026, 9, 18))
LF_DAY = ("coll", date(2026, 9, 15))


def _read_at(path: Path, offset: int, length: int) -> bytes:
    with path.open("rb") as f:
        f.seek(offset)
        return f.read(length)


def _by_name(entries: list[ScannedEntry]) -> dict[str, ScannedEntry]:
    return {e.name.raw: e for e in entries}


def _assert_round_trip(path: Path, scanned: list[ScannedEntry], original: list[tuple[str, bytes | None]]) -> None:
    """Every scanned entry must point at exactly the bytes the fixture wrote."""
    expected = {name: body for name, body in original if body is not None}
    assert [e.name.raw for e in scanned] == list(expected)
    for e in scanned:
        assert _read_at(path, e.body_offset, e.body_len) == expected[e.name.raw]
        header = _read_at(path, e.header_offset, len(e.name.raw) + 9)
        assert header == b"### " + e.name.raw.encode() + b".json"
        assert e.body_offset > e.header_offset


# --------------------------------------------------------------- structure ---

def test_crlf_file_offsets_round_trip(mirror):
    path = mirror.files[CRLF_DAY]
    entries, stats = scan_daily_file(path)
    assert isinstance(stats, ScanStats)
    assert stats == ScanStats(n_entries=7, n_orphans=0)
    assert len(entries) == 7
    assert [e.seq for e in entries] == list(range(7))
    _assert_round_trip(path, entries, mirror.entries[CRLF_DAY])
    # body_len excludes the CRLF terminator
    first = entries[0]
    assert _read_at(path, first.body_offset + first.body_len, 2) == b"\r\n"


def test_lf_file_counts_orphans_and_round_trips(mirror):
    path = mirror.files[LF_DAY]
    entries, stats = scan_daily_file(path)
    assert stats == ScanStats(n_entries=2, n_orphans=2)  # one orphan body + one header without body
    assert [e.seq for e in entries] == [0, 1]
    _assert_round_trip(path, entries, mirror.entries[LF_DAY])
    first = entries[0]
    assert _read_at(path, first.body_offset + first.body_len, 1) == b"\n"


def test_header_without_body_at_eof_is_orphan(tmp_path: Path):
    path = make_daily_file(tmp_path, "x", date(2026, 1, 5), [
        (entry_name(FDI_A, KEY_CTE), synthetic_body(FDI_A, KEY_CTE)),
        (entry_name(FDI_B, KEY_CTE, "1a2b3c0200000002"), None),
    ])
    entries, stats = scan_daily_file(path)
    assert stats == ScanStats(n_entries=1, n_orphans=1)
    assert entries[0].name.raw == entry_name(FDI_A, KEY_CTE)


def test_last_body_without_trailing_newline(tmp_path: Path):
    path = tmp_path / "d.txt"
    body = synthetic_body(FDI_A, KEY_CTE)
    path.write_bytes(b"### " + entry_name(FDI_A, KEY_CTE).encode() + b".json\n" + body)
    entries, stats = scan_daily_file(path)
    assert stats == ScanStats(1, 0)
    assert _read_at(path, entries[0].body_offset, entries[0].body_len) == body


def test_empty_file(tmp_path: Path):
    path = tmp_path / "empty.txt"
    path.write_bytes(b"")
    assert scan_daily_file(path) == ([], ScanStats(0, 0))


def test_header_regex_shapes():
    assert HEADER_RE.match(b"### abc_KEY_0123456789abcdef.json\r\n").group("name") == b"abc_KEY_0123456789abcdef"
    assert HEADER_RE.match(b"### abc.json\n").group("name") == b"abc"
    assert HEADER_RE.match(b"### abc.json").group("name") == b"abc"
    assert HEADER_RE.match(b"### abc.json \t\r\n").group("name") == b"abc"
    assert HEADER_RE.match(b'{"documents":[]}\r\n') is None
    assert HEADER_RE.match(b"###abc.json\n") is None
    assert REQDATE_RE.search(b'{"dossier":{"requestDate":"2026-01-01T00:00:00Z"}}').group(1) == b"2026-01-01T00:00:00Z"


# ----------------------------------------------------------------- content ---

def test_ndocs_is_exact_despite_noise(mirror):
    entries, _ = scan_daily_file(mirror.files[CRLF_DAY])
    by = _by_name(entries)
    e3 = by[entry_name(FDI_A, KEY_SINT, "1a2b3c0200000033")]
    e5 = by[entry_name(FDI_A, KEY_EMAIL, "1a2b3c0200000031")]
    assert e3.ndocs == 3 and e3.json_ok is True
    assert e5.ndocs == 5 and e5.json_ok is True
    assert e3.doc_keys[0] == KEY_SINT and len(e3.doc_keys) == 3
    assert e5.doc_keys == (KEY_EMAIL, "ATTACH_1", "ATTACH_2", "ATTACH_3", "ATTACH_4")
    assert e3.dossier_id == "dossier-" + FDI_A[:8]
    assert e3.dossier_number == "DA00000001"
    assert e3.request_date == "2026-09-18T10:38:28.776Z"
    assert e3.name.fdi == FDI_A and e3.name.template_key == KEY_SINT
    assert e3.name.call_id == "1a2b3c0200000033" and e3.name.well_formed is True


def test_non_json_body_falls_back(mirror, tmp_path: Path):
    entries, _ = scan_daily_file(mirror.files[CRLF_DAY])
    bad = _by_name(entries)[entry_name(FDI_B, KEY_NUMERIC, "1a2b3c0100000041")]
    assert bad.json_ok is False
    assert bad.ndocs is None
    assert bad.request_date is None
    assert bad.doc_keys == ()
    assert bad.dossier_id is None and bad.dossier_number is None
    # invalid JSON that still carries a requestDate: the regex fallback finds it
    path = make_daily_file(tmp_path, "x", date(2026, 1, 5), [
        (entry_name(FDI_A, KEY_CTE), b'{"dossier":{"requestDate":"X"}, broken'),
    ])
    (e,), stats = scan_daily_file(path)
    assert stats.n_entries == 1
    assert e.json_ok is False and e.ndocs is None and e.request_date == "X"


def test_missing_request_date_is_none_with_json_ok(mirror):
    entries, _ = scan_daily_file(mirror.files[CRLF_DAY])
    e = _by_name(entries)[entry_name(FDI_A, KEY_CTE, "1a2b3c0200000032")]
    assert e.json_ok is True
    assert e.request_date is None
    assert e.ndocs == 2


def test_tolerates_missing_documents_and_dossier(tmp_path: Path):
    path = make_daily_file(tmp_path, "x", date(2026, 1, 5), [
        (entry_name(FDI_A, KEY_CTE), b'{}'),
        (entry_name(FDI_B, KEY_CTE, "1a2b3c0200000002"), b'{"documents":[{"template":{}},{"x":1},{"template":{"templateKey":"K"}}],"dossier":null}'),
        (entry_name(FDI_C, KEY_CTE, "1a2b3c0200000003"), b'[1,2,3]'),
    ])
    (a, b, c), stats = scan_daily_file(path)
    assert stats == ScanStats(3, 0)
    assert a.json_ok is True and a.ndocs == 0 and a.doc_keys == () and a.request_date is None
    assert b.json_ok is True and b.ndocs == 3 and b.doc_keys == ("K",) and b.dossier_id is None
    assert c.json_ok is False and c.ndocs is None  # valid JSON but not an object: unusable


def test_awkward_names(mirror):
    entries, _ = scan_daily_file(mirror.files[CRLF_DAY])
    by = _by_name(entries)
    vuoto = by["correlationId_vuoto_MOD_TEST_R_1a2b3c0300000000"]
    assert vuoto.name.fdi is None
    assert vuoto.name.template_key == "MOD_TEST_R"
    assert vuoto.name.call_id == "1a2b3c0300000000"
    assert vuoto.name.well_formed is False
    assert vuoto.json_ok is True  # the body itself is fine
    t15 = by[f"{FDI_C}-t15_{KEY_CTE}_1a2b3c0200000099"]
    assert t15.name.well_formed is False
    assert t15.name.template_key == KEY_CTE
    assert t15.name.fdi == f"{FDI_C}-t15"


def test_parse_json_false_uses_regex_only(mirror):
    entries, stats = scan_daily_file(mirror.files[CRLF_DAY], parse_json=False)
    assert stats.n_entries == 7
    for e in entries:
        assert e.ndocs is None
        assert e.doc_keys == ()
        assert e.dossier_id is None and e.dossier_number is None
    by = _by_name(entries)
    assert by[entry_name(FDI_A, KEY_SINT, "1a2b3c0200000033")].request_date == "2026-09-18T10:38:28.776Z"
    assert by[entry_name(FDI_A, KEY_CTE, "1a2b3c0200000032")].request_date is None
    # offsets are identical regardless of the parse mode
    full, _ = scan_daily_file(mirror.files[CRLF_DAY])
    assert [(e.header_offset, e.body_offset, e.body_len) for e in entries] == \
        [(e.header_offset, e.body_offset, e.body_len) for e in full]


# ------------------------------------------------------------------ cancel ---

def test_cancel_before_loop(mirror):
    token = CancelToken()
    token.cancel()
    with pytest.raises(Cancelled):
        scan_daily_file(mirror.files[CRLF_DAY], cancel=token)


def test_cancel_checked_every_50_entries(tmp_path: Path):
    entries = [(entry_name(FDI_A, KEY_CTE, f"10b6016b{i:08x}"), synthetic_body(FDI_A, KEY_CTE, noise=False)) for i in range(120)]
    path = make_daily_file(tmp_path, "x", date(2026, 1, 5), entries)

    class CountingToken(CancelToken):
        def __init__(self, fail_at: int) -> None:
            super().__init__()
            self.calls = 0
            self.fail_at = fail_at

        def check(self) -> None:
            self.calls += 1
            if self.calls == self.fail_at:
                self.cancel()
            super().check()

    ok = CountingToken(fail_at=0)
    scan_daily_file(path, cancel=ok)
    assert ok.calls == 1 + 120 // 50  # start + after entries 50 and 100

    tok = CountingToken(fail_at=2)  # second check == after the 50th entry
    with pytest.raises(Cancelled):
        scan_daily_file(path, cancel=tok)


def test_documents_not_a_list_is_tolerated(tmp_path: Path):
    path = make_daily_file(tmp_path, "x", date(2026, 1, 5), [
        (entry_name(FDI_A, KEY_CTE), b'{"documents": 7, "dossier": {"requestDate": "R"}}'),
    ])
    (e,), _ = scan_daily_file(str(path))
    assert e.json_ok is True and e.ndocs == 0 and e.doc_keys == () and e.request_date == "R"
