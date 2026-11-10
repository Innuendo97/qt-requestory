"""qtrequestory.officina.batch.output: folders, names, esito.csv and zips.

Synthetic data only (this repository is public).
"""
from __future__ import annotations

import csv
import threading
import zipfile
from datetime import datetime
from pathlib import Path

import pytest

from qtrequestory.officina.batch import output
from qtrequestory.officina.batch.elenco import NO_PACKAGE
from qtrequestory.officina.batch.model import Outcome
from qtrequestory.officina.batch.output import Writer, run_dir_name, write_esito, zip_folders

PDF = b"%PDF-1.7\n" + b"0" * 100 + b"\n%%EOF\n"
FDI_A = "aaaaaaaa-1111-4222-8333-444444444444"


def _parts(root: Path) -> list[Path]:
    return [p for p in root.rglob("*") if p.name.endswith(".part")]


def _outcome(**kw) -> Outcome:
    values = dict(key="MOD_TEST_A", folders=("111_PKG",), fdi=None, status="ok", doc_type="pdf",
                  files=(), duration_ms=120, http_status=200, reason="")
    values.update(kw)
    return Outcome(**values)


def test_run_dir_name():
    assert run_dir_name("svil", datetime(2026, 11, 10, 14, 30, 5)) == "svil_20261110-143005"
    assert run_dir_name("a:b", datetime(2026, 11, 10, 14, 30, 5)) == "a_b_20261110-143005"


def test_write_into_two_folders(tmp_path: Path):
    writer = Writer(tmp_path / "run")
    files = writer.write(("111_PKG", "222_PKG"), "MOD_TEST_A", "pdf", PDF)
    assert files == (tmp_path / "run" / "111_PKG" / "MOD_TEST_A.pdf",
                     tmp_path / "run" / "222_PKG" / "MOD_TEST_A.pdf")
    assert all(f.read_bytes() == PDF for f in files)


def test_no_folders_means_no_package(tmp_path: Path):
    files = Writer(tmp_path).write((), "MOD_TEST_A", "pdf", PDF)
    assert files == (tmp_path / NO_PACKAGE / "MOD_TEST_A.pdf",)


def test_same_name_gets_suffix(tmp_path: Path):
    writer = Writer(tmp_path)
    first = writer.write((FDI_A,), "MOD_TEST_A", "pdf", b"%PDF-1")
    second = writer.write((FDI_A,), "mod_test_a", "pdf", b"%PDF-2")
    third = writer.write((FDI_A,), "MOD_TEST_A", "pdf", b"%PDF-3")
    assert [p[0].name for p in (first, second, third)] == [
        "MOD_TEST_A.pdf", "mod_test_a_2.pdf", "MOD_TEST_A_3.pdf"]
    assert [p[0].read_bytes() for p in (first, second, third)] == [b"%PDF-1", b"%PDF-2", b"%PDF-3"]


def test_names_differing_only_in_invalid_chars_do_not_overwrite(tmp_path: Path):
    writer = Writer(tmp_path)
    a = writer.write((NO_PACKAGE,), "A:B", "pdf", b"%PDF-colon")
    b = writer.write((NO_PACKAGE,), "A?B", "pdf", b"%PDF-question")
    assert a[0] != b[0]
    assert (a[0].name, b[0].name) == ("A_B.pdf", "A_B_2.pdf")
    assert (a[0].read_bytes(), b[0].read_bytes()) == (b"%PDF-colon", b"%PDF-question")


def test_folders_cleaning_to_the_same_name_are_written_once(tmp_path: Path):
    files = Writer(tmp_path).write(("PKG:1", "PKG?1", "pkg_1"), "MOD_TEST_A", "pdf", PDF)
    assert files == (tmp_path / "PKG_1" / "MOD_TEST_A.pdf",)


def test_suffix_survives_the_length_limit(tmp_path: Path):
    key = "MOD_TEST_" + "X" * 300
    writer = Writer(tmp_path)
    first = writer.write(("P",), key, "pdf", PDF)[0]
    second = writer.write(("P",), key, "pdf", PDF)[0]
    assert first != second and second.name.endswith("_2.pdf")
    assert len(first.name) <= output.MAX_COMPONENT and len(second.name) <= output.MAX_COMPONENT


def test_hostile_names_stay_inside_the_run(tmp_path: Path):
    run = tmp_path / "run"
    files = Writer(run).write(("..", "C:\\Windows", "CON"), "../../evil", "pdf", PDF)
    for f in files:
        assert run in f.parents and f.parent.parent == run
    assert {f.parent.name for f in files} == {"_", "C__Windows", "CON_"}


def test_concurrent_writes_get_distinct_names(tmp_path: Path):
    writer = Writer(tmp_path)
    start = threading.Barrier(6)
    results: list[Path] = []
    lock = threading.Lock()

    def lane(n: int) -> None:
        start.wait()
        path = writer.write(("P",), "MOD_TEST_A", "pdf", f"%PDF-{n}".encode())[0]
        with lock:
            results.append(path)

    threads = [threading.Thread(target=lane, args=(n,)) for n in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(set(results)) == 6
    assert sorted(p.read_bytes() for p in results) == sorted(f"%PDF-{n}".encode() for n in range(6))


def test_no_part_files_left(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    writer = Writer(tmp_path)
    writer.write(("111_PKG", "222_PKG"), "MOD_TEST_A", "pdf", PDF)
    assert _parts(tmp_path) == []

    real = output._write_bytes

    def disk_full(path: Path, content: bytes) -> None:
        real(path, content[:10])  # half a file on disk, then the disk is full
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(output, "_write_bytes", disk_full)
    with pytest.raises(OSError):
        writer.write(("111_PKG",), "MOD_TEST_B", "pdf", PDF)
    assert _parts(tmp_path) == []
    assert not (tmp_path / "111_PKG" / "MOD_TEST_B.pdf").exists()
    monkeypatch.setattr(output, "_write_bytes", real)
    # the name was released: a retry in the same run gets it, not "_2"
    assert writer.write(("111_PKG",), "MOD_TEST_B", "pdf", PDF)[0].name == "MOD_TEST_B.pdf"


def test_failure_in_the_second_folder_removes_the_first_copy(tmp_path: Path,
                                                             monkeypatch: pytest.MonkeyPatch):
    def no_copy(src, dst):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(output.shutil, "copyfile", no_copy)
    with pytest.raises(OSError):
        Writer(tmp_path).write(("111_PKG", "222_PKG"), "MOD_TEST_A", "pdf", PDF)
    assert [p for p in tmp_path.rglob("*") if p.is_file()] == []


def test_esito_columns_bom_and_semicolons(tmp_path: Path):
    run = tmp_path / "run"
    pdf_a = run / "111_PKG" / "MOD_TEST_A.pdf"
    pdf_b = run / "222_PKG" / "MOD_TEST_A.pdf"
    outcomes = [
        _outcome(folders=("111_PKG", "222_PKG"), files=(pdf_a, pdf_b), fdi=FDI_A),
        _outcome(key="MOD_TEST_B", status="html_skipped", doc_type="html", reason="HTML non richiesto"),
        _outcome(key="MOD_TEST_C", status="no_call", doc_type=None, http_status=None, duration_ms=0,
                 reason="nessuna chiamata nei log di coll"),
        _outcome(key="MOD_TEST_D", status="failed", doc_type=None, http_status=500,
                 reason="il generatore ha risposto HTTP 500; dettaglio"),
        _outcome(key="MOD_TEST_E", status="cancelled", doc_type=None, http_status=None,
                 duration_ms=0, reason="annullato prima dell'invio"),
    ]
    path = write_esito(run, outcomes)
    assert path == run / "esito.csv"
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(raw.decode("utf-8-sig").splitlines(), delimiter=";"))
    assert rows[0] == ["template_key", "cartella", "fdi", "esito", "tipo", "file", "durata_ms",
                       "stato_http", "motivo"]
    assert rows[1] == ["MOD_TEST_A", "111_PKG | 222_PKG", FDI_A, "ok", "pdf",
                       f"{Path('111_PKG') / 'MOD_TEST_A.pdf'} | {Path('222_PKG') / 'MOD_TEST_A.pdf'}",
                       "120", "200", ""]
    assert [r[3] for r in rows[1:]] == ["ok", "saltato: HTML", "nessuna chiamata nei log",
                                        "non riuscito", "annullato"]
    assert rows[3][7] == "" and rows[4][8] == "il generatore ha risposto HTTP 500; dettaglio"
    assert _parts(run) == []


def test_esito_never_contains_sas_signature(tmp_path: Path):
    reason = "errore: https://account.blob.example.invalid/c/doc.pdf?sv=2024&sig=abc123SECRET"
    path = write_esito(tmp_path, [_outcome(status="failed", reason=reason),
                                  _outcome(status="failed", reason="vedi ?sig=abc")])
    text = path.read_text(encoding="utf-8-sig")
    assert "abc123SECRET" not in text and "sig=abc" not in text
    assert "sig=***" in text


def test_zip_per_folder_keeps_folders(tmp_path: Path):
    run = tmp_path / "run"
    writer = Writer(run)
    writer.write(("111_PKG", "222_PKG"), "MOD_TEST_A", "pdf", PDF)
    writer.write(("111_PKG",), "MOD_TEST_B", "html", b"<html></html>")
    (run / "vuota").mkdir()
    write_esito(run, [])
    zips = zip_folders(run)
    assert zips == (run / "111_PKG.zip", run / "222_PKG.zip")
    with zipfile.ZipFile(zips[0]) as zf:
        assert sorted(zf.namelist()) == ["111_PKG/MOD_TEST_A.pdf", "111_PKG/MOD_TEST_B.html"]
        assert zf.read("111_PKG/MOD_TEST_A.pdf") == PDF
    with zipfile.ZipFile(zips[1]) as zf:
        assert zf.namelist() == ["222_PKG/MOD_TEST_A.pdf"]
    assert (run / "111_PKG" / "MOD_TEST_A.pdf").is_file()  # the folders stay
    assert not (run / "vuota.zip").exists()
    assert _parts(run) == []


def test_zip_failure_leaves_no_partial_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    run = tmp_path / "run"
    writer = Writer(run)
    writer.write(("111_PKG", "222_PKG"), "MOD_TEST_A", "pdf", PDF)
    real = output._write_zip
    calls = []

    def second_fails(folder, members, out):
        calls.append(out)
        if len(calls) == 2:
            raise OSError(28, "No space left on device")
        return real(folder, members, out)

    monkeypatch.setattr(output, "_write_zip", second_fails)
    with pytest.raises(OSError):
        zip_folders(run)
    assert list(run.glob("*.zip")) == [] and _parts(run) == []
