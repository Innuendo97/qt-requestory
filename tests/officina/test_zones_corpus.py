"""LOCAL-ONLY check of the zone stage on real documents.

Skipped unless the environment variable ``QTR_ZONES_CORPUS`` lists folders
(``os.pathsep``-separated) holding PDFs. Real documents are only READ where
they are: nothing is copied into the repository, and a failure message names
the file and the page, never its text. Invariants checked on every document:

* the stage keeps the words (order, boxes) and is deterministic;
* rotated text in the far left margin is ``spalla_sx``;
* the zones never swallow the page: at most 40 % of a page's words are
  outside the body and the title;
* a page number holds a digit; a watermark word is at least twice the body size.
"""
from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

from qtrequestory.officina.compare.extract_pdf import extract
from qtrequestory.officina.compare.zones import zone_document

_FOLDERS = [Path(p) for p in os.environ.get("QTR_ZONES_CORPUS", "").split(os.pathsep) if p.strip()]
_PDFS = sorted({p for folder in _FOLDERS if folder.is_dir() for p in folder.rglob("*.pdf")})

pytestmark = pytest.mark.skipif(not _PDFS, reason="QTR_ZONES_CORPUS not set (local-only real-corpus check)")


@pytest.mark.parametrize("path", _PDFS, ids=[f"doc{k}" for k in range(len(_PDFS))])
def test_zones_on_a_real_document(path: Path):
    doc = extract(path)
    zoned = zone_document(doc)
    assert zone_document(doc) == zoned, path.name
    assert [replace(w, zone="corpo") for w in zoned.doc.words] == [replace(w, zone="corpo") for w in doc.words]
    body = zoned.body_size
    for page in range(len(doc.page_sizes)):
        words = [(i, w) for i, w in enumerate(zoned.doc.words) if w.page == page]
        for i, word in words:
            if doc.angle(i) in (90, 270) and word.x1 < 25:
                assert word.zone == "spalla_sx", (path.name, page)
            if word.zone == "filigrana":
                assert word.size >= 2 * body, (path.name, page)
        number = " ".join(w.text for _, w in words if w.zone == "numero_pagina")
        assert not number or any(ch.isdigit() for ch in number), (path.name, page)
        outside = sum(w.zone not in ("corpo", "titolo") for _, w in words)
        assert outside <= max(0.4 * len(words), 40), (path.name, page, outside, len(words))
