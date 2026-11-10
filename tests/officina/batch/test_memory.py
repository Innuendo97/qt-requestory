"""qtrequestory.officina.batch.memory: the template keys known to answer HTML.

Synthetic data only (this repository is public).
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from qtrequestory.officina.batch.memory import HtmlMemory


def test_record_html_then_pdf_forgets(tmp_path: Path):
    memory = HtmlMemory(tmp_path / "genera-html.json")
    assert not memory.is_html("MOD_TEST_A")
    memory.record("MOD_TEST_A", "html")
    assert memory.is_html("MOD_TEST_A")
    assert memory.is_html("mod_test_a ")  # case-insensitive, stripped
    memory.record("mod_test_a", "pdf")
    assert not memory.is_html("MOD_TEST_A")


def test_persists_across_instances(tmp_path: Path):
    path = tmp_path / "sub" / "genera-html.json"  # the folder does not exist yet
    first = HtmlMemory(path)
    first.record("MOD_TEST_A", "html")
    first.record("MOD_TEST_B", "html")
    first.record("MOD_TEST_B", "pdf")
    assert json.loads(path.read_text(encoding="utf-8")) == {"html_keys": ["MOD_TEST_A"]}
    second = HtmlMemory(path)
    assert second.is_html("mod_test_a") and not second.is_html("MOD_TEST_B")
    assert [p.name for p in path.parent.iterdir()] == ["genera-html.json"]  # no .part left


def test_corrupt_file_is_empty(tmp_path: Path):
    for content in (b"{not json", b'{"html_keys": "MOD_TEST_A"}', b"[1, 2]", b"\xff\xfe\x00",
                    b'{"html_keys": [1, null, " ", "MOD_TEST_A"]}'):
        path = tmp_path / "genera-html.json"
        path.write_bytes(content)
        memory = HtmlMemory(path)
        assert not memory.is_html("1")
    assert memory.is_html("MOD_TEST_A")  # the last one: the valid entry survives
    memory.record("MOD_TEST_B", "html")  # and the memory can be written again
    assert HtmlMemory(path).is_html("MOD_TEST_B")


def test_missing_file_is_empty(tmp_path: Path):
    assert not HtmlMemory(tmp_path / "assente.json").is_html("MOD_TEST_A")


def test_failed_save_keeps_the_change_in_memory(tmp_path: Path):
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    memory = HtmlMemory(blocker / "genera-html.json")  # its folder is a file: never writable
    memory.record("MOD_TEST_A", "html")  # does not raise
    assert memory.is_html("MOD_TEST_A")


def test_concurrent_records_are_all_kept(tmp_path: Path):
    path = tmp_path / "genera-html.json"
    memory = HtmlMemory(path)
    start = threading.Barrier(4)

    def lane(n: int) -> None:
        start.wait()
        for i in range(25):
            memory.record(f"MOD_TEST_{n}_{i}", "html")

    threads = [threading.Thread(target=lane, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(json.loads(path.read_text(encoding="utf-8"))["html_keys"]) == 100
    assert [p.name for p in tmp_path.iterdir()] == ["genera-html.json"]


def test_no_path_is_a_session_memory_never_written(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    memory = HtmlMemory(None)
    memory.record("MOD_TEST_A", "html")
    assert memory.is_html("mod_test_a")
    memory.record("MOD_TEST_A", "pdf")
    assert not memory.is_html("MOD_TEST_A")
    assert list(tmp_path.iterdir()) == []
