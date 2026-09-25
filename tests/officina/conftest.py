"""Fixtures for the Officina comparison tests (generated PDFs)."""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture
def pdfs(qapp, tmp_path: Path) -> Iterator[Path]:
    """A folder for generated PDFs, with a font registered for Qt meanwhile."""
    from tests.officina import pdfgen

    font_id = pdfgen.load_font()
    if font_id is None:
        pytest.skip("no system font to generate PDFs with")
    try:
        yield tmp_path
    finally:
        pdfgen.unload_font(font_id)
