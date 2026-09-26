"""Integration (task I1) checks of the real ``OfficinaService`` review state:
the per-case write lock around the review's read-modify-write (R16), noise
rule names across levels, and a file with clashing names still compared.
Local ``FakeServer`` generator only; synthetic data only."""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from qtrequestory.officina.model_case import case_write_lock
from qtrequestory.officina.model_review import NoiseRule
from tests.fakes.fake_core import canned_pdf

from .test_generator import FakeServer
from .test_service import Env
from .test_service_review import TARGET, _case, _generate, doc


@pytest.fixture
def server():
    s = FakeServer()
    yield s
    s.close()


@pytest.fixture
def env(tmp_path: Path, server: FakeServer) -> Env:
    return Env(tmp_path, server)


def test_a_review_action_holds_the_case_write_lock_from_read_to_save(env: Env, server: FakeServer,
                                                                     tmp_path: Path,
                                                                     monkeypatch: pytest.MonkeyPatch):
    """R16 (I1): ``ReviewMixin._commit`` reads the review on disk and saves it
    under ``case_write_lock``: another thread cannot take the lock (and
    write ``caso.json``) between the read and the save."""
    ini, case = _case(env, tmp_path)
    v1 = _generate(env, server, ini, case, "tobe", doc(("abilitata", "abilitato")))
    judged = env.svc.compare_case(ini, case, v1).judged[0]
    workspace = env.svc._workspace()
    seen: list[bool] = []
    save = type(workspace).save_review

    def spying(self, c):
        other: list[bool] = []

        def try_lock() -> None:
            lock = case_write_lock(c.folder)
            got = lock.acquire(blocking=False)
            if got:
                lock.release()  # never leave it held by a finished thread
            other.append(got)

        probe = threading.Thread(target=try_lock)
        probe.start()
        probe.join()
        seen.append(other[0])
        return save(self, c)

    monkeypatch.setattr(type(workspace), "save_review", spying)
    env.svc.tolerate(case, judged, "nota")
    assert seen == [False], "another thread took the case's lock while the review was being written"


def test_noise_rule_names_are_unique_across_the_initiative_and_its_cases(env: Env, tmp_path: Path):
    """E7 deferred minor (I1): ``set_noise_rules`` refuses a name already used
    on the other level or by a preset, with an Italian message; nothing saved."""
    ini, case = _case(env, tmp_path)
    env.svc.set_noise_rules(ini, None, [NoiseRule("codice", r"X-\d+")])
    with pytest.raises(ValueError, match="nome già usato da una regola dell'iniziativa"):
        env.svc.set_noise_rules(ini, case, [NoiseRule("codice", "altro")])
    with pytest.raises(ValueError, match="nome già usato da un preset"):
        env.svc.set_noise_rules(ini, case, [NoiseRule("Data", "altro")])
    env.svc.set_noise_rules(ini, case, [NoiseRule("pratica", r"P-\d+")])
    with pytest.raises(ValueError, match="nome già usato da una regola del caso"):
        env.svc.set_noise_rules(ini, None, [NoiseRule("pratica", "x")])
    fresh = env.svc.load(ini.id)
    assert [r.name for r in fresh.noise_rules] == ["codice"]
    assert [r.name for r in fresh.cases[0].review.noise_rules] == ["pratica"]


def test_a_file_with_clashing_rule_names_is_still_compared_with_a_note(env: Env, server: FakeServer,
                                                                        tmp_path: Path):
    """Names saved before the check (or edited by hand): the later rule is
    dropped with a note, the comparison never fails on it."""
    ini, case = _case(env, tmp_path, canned_pdf("\n".join([*TARGET, "Codice X-1"])))
    v1 = _generate(env, server, ini, case, "tobe", canned_pdf("\n".join([*TARGET, "Codice X-2"])))
    env.svc.set_noise_rules(ini, None, [NoiseRule("codice", r"X-\d")])
    caso = case.folder / "caso.json"
    raw = json.loads(caso.read_text(encoding="utf-8"))
    raw["regole_rumore"] = [{"name": "codice", "pattern": "Codice", "enabled": True}]
    caso.write_text(json.dumps(raw), encoding="utf-8")
    fresh = next(c for c in env.svc.load(ini.id).cases if c.id == case.id)

    cc = env.svc.compare_case(env.svc.load(ini.id), fresh, v1)

    assert "regola «codice» ignorata: nome già usato" in cc.tobe.note
    assert [j.diff.klass for j in cc.judged] == ["rumore"], "the initiative's rule applied"
