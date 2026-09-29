"""``OfficinaService.replace_call``: a case's call swapped for another logged one.

Real service on a tmp Officina root, real index on the synthetic ``mirror``
of ``tests/conftest.py``; the generator is a local ``FakeServer`` (never a
real endpoint). Synthetic data only.
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from qtrequestory.core.config import Environment, default_config
from qtrequestory.core.events import CancelToken, CollectingSink
from qtrequestory.core.facade import IndexService
from qtrequestory.core.index.search import SearchQuery
from qtrequestory.officina.compare.model import Anchor
from qtrequestory.officina.model_case import write_review
from qtrequestory.officina.model_review import Mark
from qtrequestory.officina.service import OfficinaService
from tests.conftest import FDI_A, FDI_B, KEY_CTE, KEY_SINT

from .test_service import NOW, Env, env, server  # noqa: F401 - fixtures


@pytest.fixture
def indexed(env: Env, mirror):  # noqa: F811 - the fixture above
    cfg = dataclasses.replace(default_config(), mirror_root=mirror.root,
                              environments=[Environment("coll", "https://example.invalid/coll/")])
    index = IndexService(lambda: cfg)
    index.update(["coll"], full_rebuild=True, sink=CollectingSink(), cancel=CancelToken())
    svc = OfficinaService(lambda: env.config, control_runner=None, index=index, clock=lambda: NOW)
    return svc, index


def _hit(index, fdi: str, key: str = KEY_SINT):
    return index.search(SearchQuery("coll", fdi_prefix=fdi, template_key=key))[0]


def test_replace_call_swaps_the_payload_and_keeps_everything_else(env: Env, indexed, tmp_path: Path):  # noqa: F811
    svc, index = indexed
    old, new = _hit(index, FDI_A), _hit(index, FDI_B)
    ini = svc.create_initiative("Sostituzioni")
    case = svc.case_from_hit(ini, old)
    target = tmp_path / "atteso.pdf"
    target.write_bytes(b"%PDF-1.4 target di prova")
    svc.set_target(case, target)
    (case.folder / "asis").mkdir()
    (case.folder / "asis" / "asis.pdf").write_bytes(b"%PDF asis")
    (case.folder / "asis" / "asis.meta.json").write_text(
        json.dumps({"doc_type": "pdf", "created": "2026-09-20T10:00:00", "meta": {}}), encoding="utf-8")
    case.review = dataclasses.replace(case.review, profile="stretto",
                                      marks=[Mark(Anchor("cambiato", "testo", "il prezzo | al mese", "12,00"), "11,00", 1, "2026-09-20T10:00:00")])
    write_review(case)
    before = {p.name: p.read_bytes() for p in (case.folder / "target").iterdir()}
    first_payload = svc.payload(case)

    got = svc.replace_call(case, new)

    assert got.source_fdi == FDI_B
    assert svc.payload(got) == json.loads(index.read_body(new))
    backups = sorted(p.name for p in case.folder.glob("payload.*.json"))
    assert "payload.original.json" in backups
    stamped = [n for n in backups if n != "payload.original.json"]
    assert stamped == [f"payload.{NOW.astimezone():%Y%m%d-%H%M%S}.json"]
    assert json.loads((case.folder / stamped[0]).read_text(encoding="utf-8")) == first_payload
    assert json.loads((case.folder / "payload.original.json").read_text(encoding="utf-8")) == first_payload
    reloaded = next(c for c in svc.load(ini.id).cases if c.id == case.id)
    assert reloaded.source_fdi == FDI_B
    assert reloaded.review.profile == "stretto" and len(reloaded.review.marks) == 1
    assert {p.name: p.read_bytes() for p in (case.folder / "target").iterdir()} == before
    assert reloaded.asis() is not None and reloaded.target() is not None
    last = reloaded.history[-1]
    assert last["note"] == f"chiamata sostituita: {FDI_A} → {FDI_B}"
    assert last["kind"] == "chiamata_sostituita"


def test_a_second_replace_keeps_the_very_first_original(env: Env, indexed):  # noqa: F811
    svc, index = indexed
    a, b, c = _hit(index, FDI_A), _hit(index, FDI_B), index.search(
        SearchQuery("coll", fdi_prefix=FDI_A, template_key=KEY_SINT))[-1]
    ini = svc.create_initiative("Due volte")
    case = svc.case_from_hit(ini, a)
    first = svc.payload(case)
    svc.replace_call(case, b)
    svc.replace_call(case, c)
    assert json.loads((case.folder / "payload.original.json").read_text(encoding="utf-8")) == first
    stamped = sorted(p.name for p in case.folder.glob("payload.2*.json"))
    assert len(stamped) == 2, "the same second twice: two backups, none overwritten"
    assert svc.payload(case) == json.loads(index.read_body(c))
    notes = [h["note"] for h in case.history if h.get("kind") == "chiamata_sostituita"]
    assert len(notes) == 2


def test_replace_call_refuses_another_key_and_a_vanished_call(env: Env, indexed):  # noqa: F811
    svc, index = indexed
    ini = svc.create_initiative("Rifiuti")
    case = svc.case_from_hit(ini, _hit(index, FDI_A))
    before = svc.payload(case)
    with pytest.raises(ValueError, match="template key"):
        svc.replace_call(case, _hit(index, FDI_A, KEY_CTE))
    gone = _hit(index, FDI_B)
    gone.file_path.unlink()
    with pytest.raises(ValueError, match="la chiamata non è più nel log locale"):
        svc.replace_call(case, gone)
    assert svc.payload(case) == before
    assert not list(case.folder.glob("payload.2*.json"))
    assert case.source_fdi == FDI_A


def test_replace_call_refuses_an_unreadable_caso_json(env: Env, indexed):  # noqa: F811
    svc, index = indexed
    ini = svc.create_initiative("Rotto")
    case = svc.case_from_hit(ini, _hit(index, FDI_A))
    before = svc.payload(case)
    (case.folder / "caso.json").write_text("{ rotto", encoding="utf-8")
    with pytest.raises(ValueError):
        svc.replace_call(case, _hit(index, FDI_B))
    assert svc.payload(case) == before


def test_the_fake_replaces_like_the_real_service(tmp_path: Path):
    """Fidelity: the fake core's ``replace_call`` is the shipped behaviour."""
    from tests.conftest import FDI_C
    from tests.fakes.fake_core import build_fake_core

    core = build_fake_core(tmp_path / "core")
    hits = [h for h in core.index.hits if h.template_key == KEY_SINT]
    first = next(h for h in hits if h.fdi == FDI_A)
    second = next(h for h in hits if h.fdi == FDI_C)
    ini = core.officina.create_initiative("Finto")
    case = core.officina.case_from_hit(ini, first)
    got = core.officina.replace_call(case, second)
    assert got.source_fdi == FDI_C
    assert core.officina.payload(got) == json.loads(core.index.read_body(second))
    assert case.history[-1]["kind"] == "chiamata_sostituita"
    core.index.set_missing(first)
    with pytest.raises(ValueError, match="ripetere la ricerca"):
        core.officina.replace_call(case, first)


def test_replacing_with_the_same_call_writes_nothing(env: Env, indexed):  # noqa: F811
    svc, index = indexed
    ini = svc.create_initiative("Stessa chiamata")
    hit = _hit(index, FDI_A)
    case = svc.case_from_hit(ini, hit)
    caso = (case.folder / "caso.json").read_bytes()
    got = svc.replace_call(case, hit)
    assert got is case and got.source_fdi == FDI_A
    assert (case.folder / "caso.json").read_bytes() == caso
    assert sorted(p.name for p in case.folder.glob("payload*.json")) == ["payload.json"]
