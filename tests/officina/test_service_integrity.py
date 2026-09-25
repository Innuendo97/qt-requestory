"""OfficinaService, final fix wave: unreadable files, folder identity, logs.

A real service on a tmp Officina root with a local fake generator (see
``test_service.Env``). Synthetic data only.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from qtrequestory.officina.model import Workspace
from qtrequestory.officina.service import CompareError

from .test_links import sas
from .test_service import PDF, Env, FakeServer, env, server  # noqa: F401 - fixtures

VALID = "2026-12-31T23%3A59%3A59Z"


def _break(path: Path) -> None:
    path.write_text("{ rotto", encoding="utf-8")


# ------------------------------------------------ unreadable iniziativa.json ---

def test_generation_is_refused_while_iniziativa_json_is_unreadable(env: Env, server: FakeServer):
    ini, case = env.case()
    _break(ini.folder / "iniziativa.json")
    ini = env.svc.load(ini.id)
    assert ini.load_error

    version, result = env.svc.generate(ini, ini.cases[0], "tobe")

    assert version is None and not result.ok
    assert "iniziativa.json" in result.reason and "rifiutat" in result.reason
    assert server.requests == []


def test_generation_is_refused_for_a_case_whose_caso_json_is_unreadable(env: Env,
                                                                        server: FakeServer):
    ini, case = env.case()
    _break(case.folder / "caso.json")
    broken = env.svc.load(ini.id).cases[0]

    version, result = env.svc.generate(env.svc.load(ini.id), broken, "tobe")

    assert version is None and not result.ok and "caso.json" in result.reason
    assert server.requests == []


def test_delivery_says_the_destination_was_not_remembered(env: Env, tmp_path: Path):
    ini, case = env.case()
    env.svc.generate(ini, case, "tobe")
    _break(ini.folder / "iniziativa.json")
    ini = env.svc.load(ini.id)
    plan = env.svc.delivery_plan(ini, [case.id])

    report = env.svc.deliver(ini, plan.items, tmp_path / "consegna", on_conflict=lambda _p: "replace",
                             make_zip=False)

    assert report.delivered
    assert "iniziativa.json" in report.remember_problem
    assert (ini.folder / "iniziativa.json").read_text(encoding="utf-8") == "{ rotto"


# ------------------------------------------------------- identity: the folder ---

def test_two_folders_with_one_name_deliver_to_their_own_folder(env: Env, tmp_path: Path):
    ini, case = env.case("Banco")
    env.svc.generate(ini, case, "tobe")
    copy = ini.folder.with_name("Banco - Copia")
    import shutil
    shutil.copytree(ini.folder, copy)
    assert json.loads((copy / "iniziativa.json").read_text(encoding="utf-8"))["name"] == "Banco"

    twin = env.svc.load("Banco - Copia")
    assert twin.folder == copy and twin.name == "Banco"
    plan = env.svc.delivery_plan(twin, [c.id for c in twin.cases])
    report = env.svc.deliver(twin, plan.items, tmp_path / "consegna",
                             on_conflict=lambda _p: "replace", make_zip=False)

    assert report.folder == tmp_path / "consegna" / "Banco - Copia"
    assert env.svc.delivery_conflicts(twin, plan.items, tmp_path / "consegna", make_zip=False)
    assert env.svc.delivery_conflicts(env.svc.load("Banco"), plan.items, tmp_path / "consegna",
                                      make_zip=False) == []


# ------------------------------------------------------ acceptance and versions ---

def test_generating_after_acceptance_reopens_the_case(env: Env):
    ini, case = env.case()
    env.svc.generate(ini, case, "tobe")
    env.svc.generate(ini, case, "tobe")
    case.mark_accepted()
    env.svc.save_case(case)

    version, result = env.svc.generate(ini, case, "tobe")

    assert result.ok and version.number == 3
    reloaded = env.svc.load(ini.id).cases[0]
    assert reloaded.status == "open" and reloaded.reopened and reloaded.accepted_version == 2


# ------------------------------------------------------- broken metadata ---

def test_render_path_and_compare_refuse_a_broken_target(env: Env, tmp_path: Path):
    ini, case = env.case()
    src = tmp_path / "cliente.pdf"
    src.write_bytes(PDF)
    env.svc.set_target(case, src)
    (tmp_path / "officina" / "fuori.pdf").write_bytes(PDF)
    meta = case.folder / "target" / "target.meta.json"
    raw = json.loads(meta.read_text(encoding="utf-8"))
    raw["original_name"] = "../../../fuori.pdf"
    meta.write_text(json.dumps(raw), encoding="utf-8")
    tobe = Workspace(env.svc.workspace_root()).add_version(case, "tobe", PDF, "pdf", {})

    target = case.target()
    with pytest.raises(CompareError, match="target.meta.json"):
        env.svc.render_path(case, target)
    with pytest.raises(CompareError, match="target.meta.json"):
        env.svc.compare(target, tobe)


# ------------------------------------------------------------------ logs ---

def test_a_refused_link_is_logged_with_its_host_only(env: Env, server: FakeServer,
                                                     caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.DEBUG)
    body = {"documents": [{"template": {"templateKey": "MOD_TEST_A"}, "attributes": [
        {"key": "attachmentUrl", "value": sas(VALID, name="cartella-cliente/PRATICA-0042.pdf")}]}]}
    ini, case = env.case(body=body)
    case.link_policy = "keep_if_expired"

    version, result = env.svc.generate(ini, case, "tobe")

    assert version is None and "PRATICA-0042" in result.reason, "the user still sees which link"
    assert "example.invalid" in caplog.text
    assert "PRATICA-0042" not in caplog.text and "cartella-cliente" not in caplog.text
