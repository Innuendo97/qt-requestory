"""LOCAL-ONLY oracle of the comparison on a real case (task A3, spec §9).

Skipped unless the environment variable ``QTR_ORACLE`` names a JSON file
kept OUTSIDE the repository, which holds the pair to compare and what a
human verified on it (so no real path, name or text ever enters the public
repository; a failure message quotes counts and positions only)::

    {
      "target": "<path of the target PDF>",
      "generated": "<path of the generated PDF>",
      "max_counting": 40,                       # differences that count, at most
      "clean_changes": [["<old>", "<new>", 14]],  # at least n cambiato old -> new, each on its own
      "real": [["<left text>", "<right text>"]],  # each of these differences must still be there
      "zones": {"<zone>": 1}                    # at least n differences in that zone
    }

Checked on top of the file's expectations: no difference spans two pages on
one side, no counting difference lies in a zone set aside (page number,
watermark), every difference has a zone and a type of the contract.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from qtrequestory.officina.compare.extract_pdf import extract
from qtrequestory.officina.compare.model import ARREDO_ZONES, TIPI, ZONES
from qtrequestory.officina.compare.pipeline import compare_docs

_ORACLE = Path(os.environ.get("QTR_ORACLE", "")) if os.environ.get("QTR_ORACLE") else None

pytestmark = pytest.mark.skipif(_ORACLE is None or not _ORACLE.is_file(),
                                reason="QTR_ORACLE not set (local-only real-case oracle)")


@pytest.fixture(scope="module")
def oracle():
    spec = json.loads(_ORACLE.read_text(encoding="utf-8"))  # type: ignore[union-attr]
    target, generated = Path(spec["target"]), Path(spec["generated"])
    if not (target.is_file() and generated.is_file()):
        pytest.skip("the oracle's documents are not on this machine")
    return spec, compare_docs(extract(target), extract(generated))


def test_the_counting_differences_are_within_the_oracle(oracle):
    spec, result = oracle
    counting = result.counting()
    assert len(counting) <= spec["max_counting"], f"{len(counting)} counting differences"


def test_every_clean_change_is_visible_on_its_own(oracle):
    spec, result = oracle
    for old, new, least in spec.get("clean_changes", []):
        found = [d for d in result.counting() if d.op == "cambiato" and d.left_text.rstrip(",.;:") == old
                 and d.right_text.rstrip(",.;:") == new]
        assert len(found) >= least, f"clean change #{spec['clean_changes'].index([old, new, least])}: {len(found)}"


def test_no_real_difference_is_lost(oracle):
    spec, result = oracle
    for k, (left, right) in enumerate(spec.get("real", [])):
        assert any(left in d.left_text and right in d.right_text for d in result.counting()), f"real difference #{k}"


def test_zones_and_types(oracle):
    spec, result = oracle
    for zone, least in spec.get("zones", {}).items():
        assert sum(1 for d in result.diffs if d.zone == zone) >= least, zone
    for d in result.diffs:
        assert d.zone in ZONES and d.tipo in TIPI, d.id
        assert len({w.page for w in d.left}) <= 1 or "pagine" in d.detail, f"difference {d.id} spans pages"
        assert len({w.page for w in d.right}) <= 1 or "pagine" in d.detail, f"difference {d.id} spans pages"
        assert not (d.zone in ARREDO_ZONES and d in result.counting()), f"difference {d.id} counts in {d.zone}"
