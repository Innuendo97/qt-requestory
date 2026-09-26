"""qtrequestory.officina.compare.cache: extraction cache on disk.

``<case>\\cache\\extract-<sha>.json``: a hit gives back exactly what was
stored; another format version, a corrupt or hand-edited file → None (the
caller extracts again and stores over it).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from qtrequestory.officina.compare import cache
from qtrequestory.officina.compare.extract_pdf import DocText, Word

SHA = "0123456789abcdef" * 4
WORDS = [
    Word("Acme-Servizi", 0, 40.0, 50.25, 110.5, 61.0, 11.04, True),
    Word("prezzo", 0, 115.0, 50.25, 150.125, 61.0, 11.04, False),
    Word("☐", 1, 40.0, 70.0, 48.0, 80.0),
]
SIZES = [(595.0, 842.0), (595.28, 841.89)]


def _file(case: Path) -> Path:
    return case / "cache" / f"extract-{SHA}.json"


def test_store_then_load_is_a_hit(tmp_path: Path):
    cache.store(tmp_path, SHA, WORDS, SIZES, True)
    assert _file(tmp_path).is_file()
    doc = cache.load(tmp_path, SHA)
    assert doc == DocText(WORDS, SIZES, True)
    assert [type(w) for w in doc.words] == [Word] * 3


def test_missing_file_is_a_miss(tmp_path: Path):
    assert cache.load(tmp_path, SHA) is None
    assert not (tmp_path / "cache").exists(), "a load never creates the folder"


def test_another_sha_is_a_miss(tmp_path: Path):
    cache.store(tmp_path, SHA, WORDS, SIZES, True)
    assert cache.load(tmp_path, "f" * 64) is None


def test_format_bump_is_a_miss(tmp_path: Path, monkeypatch):
    cache.store(tmp_path, SHA, WORDS, SIZES, True)
    monkeypatch.setattr(cache, "FORMAT", cache.FORMAT + 1)
    assert cache.load(tmp_path, SHA) is None
    cache.store(tmp_path, SHA, WORDS, SIZES, False)
    assert cache.load(tmp_path, SHA) == DocText(WORDS, SIZES, False)


@pytest.mark.parametrize("content", [
    b"", b"{not json", b"\xff\xfe\x00", b"[]", b'{"format": 1}',
    b'{"format": 1, "sha": "x", "has_text": true, "page_sizes": [], "words": []}',
])
def test_corrupt_file_is_a_miss_and_is_rewritten(tmp_path: Path, content: bytes):
    _file(tmp_path).parent.mkdir(parents=True)
    _file(tmp_path).write_bytes(content)
    assert cache.load(tmp_path, SHA) is None
    cache.store(tmp_path, SHA, WORDS, SIZES, True)
    assert cache.load(tmp_path, SHA) == DocText(WORDS, SIZES, True)


def _stored(tmp_path: Path) -> dict:
    cache.store(tmp_path, SHA, WORDS, SIZES, True)
    return json.loads(_file(tmp_path).read_text(encoding="utf-8"))


@pytest.mark.parametrize("junk", [
    lambda raw: raw["words"].append(["solo testo"]),
    lambda raw: raw["words"][0].__setitem__(1, "0"),
    lambda raw: raw["words"][0].__setitem__(7, 1),
    lambda raw: raw["words"][0].__setitem__(2, None),
    lambda raw: raw.__setitem__("has_text", "sì"),
    lambda raw: raw["page_sizes"].append([1.0]),
    lambda raw: raw.__setitem__("words", {}),
])
def test_hand_edited_junk_is_a_miss(tmp_path: Path, junk):
    raw = _stored(tmp_path)
    junk(raw)
    _file(tmp_path).write_text(json.dumps(raw), encoding="utf-8")
    assert cache.load(tmp_path, SHA) is None


def test_an_invalid_sha_is_refused(tmp_path: Path):
    with pytest.raises(ValueError):
        cache.store(tmp_path, "..\\evil", WORDS, SIZES, True)
    assert cache.load(tmp_path, "../evil") is None
    assert not (tmp_path / "cache").exists()


def test_store_leaves_no_temporary_file(tmp_path: Path):
    cache.store(tmp_path, SHA, WORDS, SIZES, True)
    cache.store(tmp_path, SHA, WORDS[:1], SIZES[:1], True)
    assert [p.name for p in (tmp_path / "cache").iterdir()] == [f"extract-{SHA}.json"]
    assert cache.load(tmp_path, SHA) == DocText(WORDS[:1], SIZES[:1], True)


@pytest.mark.parametrize("content", [b"[" * 200_000, b'{"a":' * 200_000], ids=["list", "object"])
def test_deeply_nested_json_is_a_miss(tmp_path: Path, content: bytes):
    _file(tmp_path).parent.mkdir(parents=True)
    _file(tmp_path).write_bytes(content)
    assert cache.load(tmp_path, SHA) is None


def test_store_is_best_effort(tmp_path: Path, caplog):
    _file(tmp_path).mkdir(parents=True)  # a folder where the file should go: cannot be replaced
    with caplog.at_level("DEBUG", logger="qtrequestory.officina.compare.cache"):
        assert cache.store(tmp_path, SHA, WORDS, SIZES, True) is False
    assert cache.load(tmp_path, SHA) is None
    assert "Acme-Servizi" not in caplog.text, "the log never carries document content"
    assert cache.store(tmp_path / "altro", SHA, WORDS, SIZES, True) is True
