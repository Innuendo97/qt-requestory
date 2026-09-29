"""The variables in the real service (phase 2.5, task A4): ``compare_case``
gives the second pass the case's payload (names) and the initiative's
optional price-list dictionary (``dizionario.xlsx``); a dictionary that
cannot be read is a note, never an error. Synthetic data only."""
from __future__ import annotations

import json
import os
from pathlib import Path

from qtrequestory.officina.compare.values import DICTIONARY_NAME
from tests.fakes.fake_core import canned_pdf

from .test_generator import FakeServer
from .test_service import Env
from .test_service_review import env, server  # noqa: F401 - fixtures
from .test_variables import _xlsx

TARGET = ["Proposta di prova per Acme-Servizi", "Il periodo resta costante per [xx] mesi",
          "Pagamento con addebito anticipato"]
FILLED = ["Proposta di prova per Acme-Servizi", "Il periodo resta costante per 12 mesi",
          "Pagamento con addebito anticipato"]


def _compared(env: Env, server: FakeServer, tmp_path: Path, payload: dict):
    ini, case = env.case(body=payload)
    src = tmp_path / "atteso.pdf"
    src.write_bytes(canned_pdf("\n".join(TARGET)))
    env.svc.set_target(case, src)
    server.canned.status, server.canned.body = 200, canned_pdf("\n".join(FILLED))
    version, result = env.svc.generate(ini, case, "tobe")
    assert result.ok, result.reason
    return ini, case, version


def test_compare_case_names_a_variable_from_the_payload(env: Env, server: FakeServer, tmp_path: Path):
    ini, case, version = _compared(env, server, tmp_path, {"dossier": {"durata": "12"}})
    cc = env.svc.compare_case(ini, case, version)
    (judged,) = [j for j in cc.judged if j.diff.right_text == "12"]
    assert (judged.diff.klass, judged.diff.prova, judged.diff.nome, judged.verdict) == \
        ("variabile", "segnaposto", "dossier.durata", None)
    assert cc.summary.variabili == 1 and cc.summary.da_fare == 0


def test_a_dictionary_that_cannot_be_read_is_a_note(env: Env, server: FakeServer, tmp_path: Path):
    ini, case, version = _compared(env, server, tmp_path, {"dossier": {}})
    (ini.folder / DICTIONARY_NAME).write_bytes(b"not a workbook")
    cc = env.svc.compare_case(ini, case, version)
    assert "dizionario" in cc.tobe.note and "non letto" in cc.tobe.note
    assert [j.diff.klass for j in cc.judged] == ["variabile"]


def test_the_dictionary_is_read_once_per_file_state(env: Env, server: FakeServer, tmp_path: Path):
    ini, case, version = _compared(env, server, tmp_path, {"dossier": {}})
    path = _xlsx(ini.folder / DICTIONARY_NAME, [["Voce", "Valore"], ["Durata", 0.5]])
    _, dictionary, note = env.svc._values(ini, case)
    assert note == "" and dictionary.name("0,5") == "Listino: Durata"
    assert env.svc._values(ini, case)[1] is dictionary
    _xlsx(path, [["Voce", "Valore"], ["Durata", 0.75]])
    os.utime(path, ns=(path.stat().st_atime_ns, path.stat().st_mtime_ns + 10_000_000))
    assert env.svc._values(ini, case)[1].name("0,75") == "Listino: Durata"
    assert json.loads((case.folder / "payload.json").read_text(encoding="utf-8")) == {"dossier": {}}


def test_an_edited_payload_is_not_served_from_the_cache(env: Env, server: FakeServer, tmp_path: Path):
    ini, case, version = _compared(env, server, tmp_path, {"dossier": {"durata": "12"}})
    assert [j.diff.nome for j in env.svc.compare_case(ini, case, version).judged] == ["dossier.durata"]
    env.svc.save_payload(case, {"offerta": {"mesi": 12}})
    assert [j.diff.nome for j in env.svc.compare_case(ini, case, version).judged] == ["offerta.mesi"]
