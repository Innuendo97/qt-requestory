"""The control generation of the real ``OfficinaService`` (phase 2.5, spec
§3.4, decision D14; task A5; Review Focus 2).

Every call goes to a LOCAL fake generator (``controlgen.ControlServer``)
that renders the payload it receives, so the perturbed payload of a control
generation gives a different document. Never a real endpoint; synthetic data.
"""
from __future__ import annotations

import dataclasses
import json
import logging
from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from pathlib import Path

import pytest

from qtrequestory.core.config import Config, GeneratorEndpoint, OfficinaSettings, default_config
from qtrequestory.officina.compare.filter_model import CONTROL_UNAVAILABLE_NOTE, ControlState, control_sha
from qtrequestory.officina.model import Case, Initiative
from qtrequestory.officina.model_case import load_case
from qtrequestory.officina.service import OfficinaService

from .controlgen import Answer, ControlServer, payload, render, target

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def server() -> Iterator[ControlServer]:
    s = ControlServer()
    yield s
    s.close()


class Env:
    def __init__(self, tmp_path: Path, server: ControlServer, runner: Callable | None = None,
                 timeout_s: int = 10, generators: list[GeneratorEndpoint] | None = None,
                 default: str = "svil") -> None:
        settings = OfficinaSettings(root=tmp_path / "officina",
                                    generators=generators or [GeneratorEndpoint("svil", server.url)],
                                    default_generator=default, timeout_s=timeout_s)
        self.config: Config = dataclasses.replace(default_config(), mirror_root=tmp_path / "mirror",
                                                  officina=settings)
        self.jobs: list[Callable[[], None]] = []
        self.svc = OfficinaService(lambda: self.config, clock=lambda: NOW,
                                   control_runner=runner if runner is not None else self.jobs.append)
        self.tmp = tmp_path

    def case(self, body: dict | None = None, *, with_target: bool = True) -> tuple[Initiative, Case]:
        ini = self.svc.create_initiative(f"Controllo {len(self.svc.initiatives())}")
        src = self.tmp / "payload.json"
        src.write_text(json.dumps(body or payload()), encoding="utf-8")
        case = self.svc.case_from_file(ini, src, "MOD_TEST_A")
        if with_target:
            tgt = self.tmp / "atteso.pdf"
            tgt.write_bytes(target())
            self.svc.set_target(case, tgt)
        return ini, case

    def run_jobs(self) -> None:
        while self.jobs:
            self.jobs.pop(0)()


def sync(job: Callable[[], None]) -> None:
    job()


def _versions(case: Case) -> list[str]:
    return sorted(p.relative_to(case.folder).as_posix() for sub in ("asis", "tobe", "target")
                  for p in (case.folder / sub).rglob("*") if p.is_file())


def _record(case: Case):
    return load_case(case.folder).review.control


def _alfa(cc):
    return next(j for j in cc.judged if j.diff.right_text == "ALFA")


# ------------------------------------------------------------- the happy path ---

def test_a_control_after_the_first_generation_proves_esecuzione(tmp_path: Path, server: ControlServer):
    env = Env(tmp_path, server, sync)
    ini, case = env.case()

    v1, result = env.svc.generate(ini, case, "tobe")

    assert result.ok and v1 is not None
    assert len(server.requests) == 2                                   # the generation + one control
    (headers0, sent0), (headers1, sent1) = server.requests
    headers0, headers1 = ({k.lower(): v for k, v in h.items()} for h in (headers0, headers1))
    assert set(headers1) == set(headers0)                                  # the case's headers
    assert headers1["postman-token"] == headers0["postman-token"] != ""
    assert headers1["template_key"] == "MOD_TEST_A"
    # only the printed values changed, each in its own format; the plumbing is untouched
    assert sent1["documents"] == sent0["documents"] and sent1["cliente"]["clienteId"] == "CL-000001"
    assert sent1["offerta"]["tipoOfferta"] == "FISSA"
    nome, importo = sent1["cliente"]["nome"], sent1["offerta"]["importo"]
    assert nome != "Alfa" and len(nome) == 4 and nome[0].isupper() and nome[1:].islower()
    assert isinstance(importo, float) and importo != 12.5 and len(repr(importo)) == 4
    assert sent1["offerta"]["decorrenza"] != "2026-03-18" and len(sent1["offerta"]["decorrenza"]) == 10

    record = _record(case)
    sha = control_sha(v1.path.read_bytes(), payload())
    assert (record.sha, record.stato) == (sha, "pronta")
    assert (case.folder / "cache" / f"controllo-{sha}.pdf").read_bytes() == render(sent1)
    side = json.loads((case.folder / "cache" / f"controllo-{sha}.json").read_text(encoding="utf-8"))
    assert sorted(w[3] for w in side["parole"]) == ["12,50", "18/03/2026", "ALFA"]
    assert env.svc.control_state(case) == ControlState("pronta", "", record.quando)

    cc = env.svc.compare_case(ini, case, v1)
    alfa = _alfa(cc)
    assert (alfa.diff.klass, alfa.diff.prova, alfa.verdict) == ("variabile", "esecuzione", None)
    row = cc.filters.group("variabile.esecuzione")
    assert row.n == 1 and row.occorrenze[0].diff_ids == (alfa.diff.id,)
    assert cc.filters.controllo.stato == "pronta"


def test_without_a_control_the_same_value_counts(tmp_path: Path, server: ControlServer):
    env = Env(tmp_path, server)          # jobs queued, never run
    ini, case = env.case()
    v1, _ = env.svc.generate(ini, case, "tobe")

    alfa = _alfa(env.svc.compare_case(ini, case, v1))
    assert (alfa.diff.klass, alfa.verdict) == ("testo", "da_fare")
    assert env.svc.control_state(case).stato == "in_corso"   # queued = running, in memory only
    assert _record(case) is None


def test_the_proof_follows_the_value_into_a_later_version(tmp_path: Path, server: ControlServer):
    env = Env(tmp_path, server, sync)
    ini, case = env.case()
    env.svc.generate(ini, case, "asis")
    assert len(server.requests) == 2
    server.extra_top = True                                   # the template changed: everything moved down
    v1, _ = env.svc.generate(ini, case, "tobe")

    assert len(server.requests) == 3                          # the control of the same payload is reused
    alfa = _alfa(env.svc.compare_case(ini, case, v1))
    assert (alfa.diff.klass, alfa.diff.prova) == ("variabile", "esecuzione")


def test_a_new_payload_gets_a_new_control_at_its_first_generation(tmp_path: Path, server: ControlServer):
    env = Env(tmp_path, server, sync)
    ini, case = env.case()
    v1, _ = env.svc.generate(ini, case, "tobe")
    old = _record(case).sha
    env.svc.save_payload(case, payload(nome="Gamma"))          # what «Sostituisci la chiamata» does to it

    alfa_gone = env.svc.compare_case(ini, case, v1)           # the old control is not used for the new call
    assert all(j.diff.prova != "esecuzione" for j in alfa_gone.judged)
    assert env.svc.control_state(case) == ControlState("assente")    # never "pronta" for the old call
    env.svc.generate(ini, case, "tobe")

    assert len(server.requests) == 4 and _record(case).sha != old
    assert not (case.folder / "cache" / f"controllo-{old}.pdf").exists()   # the old files are replaced


# ------------------------------------------------------ Review Focus 2 ---

def test_control_never_becomes_a_version(tmp_path: Path, server: ControlServer):
    env = Env(tmp_path, server)          # manual runner: look before and after the control
    ini, case = env.case()
    history = list(case.history)
    v1, result = env.svc.generate(ini, case, "tobe")
    before = _files(case)

    env.run_jobs()

    assert result.ok and len(server.requests) == 2 and _record(case).stato == "pronta"
    added = sorted(n for n in set(_files(case)) - set(before) if not n.startswith("cache/extract-"))
    assert [n.split("/")[0] for n in added] == ["cache", "cache"]             # only the cache
    assert {n.rsplit(".", 1)[1] for n in added} == {"pdf", "json"} and all("/controllo-" in n for n in added)
    def kept(files: dict[str, str]) -> dict[str, str]:
        return {n: h for n, h in files.items() if not n.startswith("cache/") and n != "caso.json"}
    assert kept(_files(case)) == kept(before)
    assert [v.number for v in case.tobe_versions()] == [1] and case.asis() is None
    assert case.latest_tobe().path.read_bytes() == render(payload())           # the version is the real one
    assert case.history == history
    v2, _ = env.svc.generate(ini, case, "tobe")                                # numbering goes on
    assert v2.number == 2 and [v.number for v in case.tobe_versions()] == [1, 2]


def _files(case: Case) -> dict[str, str]:
    import hashlib

    return {p.relative_to(case.folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in case.folder.rglob("*") if p.is_file()}


@pytest.mark.parametrize("mode", ["http_error", "timeout", "html", "not_a_document", "network"])
def test_control_generation_failure_is_silent(tmp_path: Path, server: ControlServer, mode: str, caplog):
    answers = {
        "http_error": Answer(status=500, body=b"errore interno"),
        "timeout": Answer(delay_s=2.5),
        "html": Answer(body=b"<!doctype html><html><body>" + b"x" * 600 + b"</body></html>"),
        "not_a_document": Answer(body=b'{"errore": "validazione"}'),
    }
    server.answer = lambda n, body: Answer() if n == 0 else answers.get(mode, Answer())
    env = Env(tmp_path, server, sync, timeout_s=1 if mode == "timeout" else 10)
    ini, case = env.case()
    if mode == "network":
        from qtrequestory.officina.generator import _open

        def closed_after_first(request, timeout):
            if len(server.requests) >= 1:
                raise OSError("connessione rifiutata")
            return _open(request, timeout)
        env.svc._opener = closed_after_first

    with caplog.at_level(logging.INFO, logger="qtrequestory.officina.service"):
        v1, result = env.svc.generate(ini, case, "tobe")

    assert result.ok and v1 is not None and result.reason == ""     # the generation is not affected
    # no retry: a 5xx, a timeout, a network error stop at once (the refused connection never arrives)
    assert len(server.requests) == (1 if mode == "network" else 2)
    record = _record(case)
    assert record.stato == "non_disponibile"
    state = env.svc.control_state(case)
    assert state == ControlState("non_disponibile", CONTROL_UNAVAILABLE_NOTE, record.quando)
    assert [v.number for v in case.tobe_versions()] == [1] and case.asis() is None
    assert not list((case.folder / "cache").glob("controllo-*"))
    lines = [r for r in caplog.records if "controllo" in r.getMessage()]
    assert len(lines) == 1 and lines[0].levelno <= logging.WARNING
    assert "Alfa" not in caplog.text and "example.invalid/blob" not in caplog.text
    cc = env.svc.compare_case(ini, case, v1)                          # the comparison works as before
    assert _alfa(cc).diff.klass == "testo" and "controllo" not in cc.tobe.note
    assert cc.filters.controllo.nota == CONTROL_UNAVAILABLE_NOTE


def test_a_failed_control_is_retried_at_the_next_generation(tmp_path: Path, server: ControlServer):
    server.answer = lambda n, body: Answer(status=422) if n in (1, 2, 3) else Answer()
    env = Env(tmp_path, server, sync)
    ini, case = env.case()
    env.svc.generate(ini, case, "tobe")
    assert len(server.requests) == 4 and _record(case).stato == "non_disponibile"   # all, then each half

    env.svc.generate(ini, case, "tobe")
    assert len(server.requests) == 6 and _record(case).stato == "pronta"
    env.svc.generate(ini, case, "tobe")
    assert len(server.requests) == 7                                               # usable: no new control


def test_leaves_that_change_the_structure_are_left_out(tmp_path: Path, server: ControlServer):
    """«piano» is printed AND a condition (another plan adds a page): the
    first try (every leaf) changes the page count, the half without it is used."""
    server.answer = lambda n, sent: Answer(body=_with_plan(sent))
    env = Env(tmp_path, server, sync)
    ini, case = env.case(payload(piano="Base"))            # last leaf: in the second half

    env.svc.generate(ini, case, "tobe")

    assert _record(case).stato == "pronta"
    tries = [sent for _, sent in server.requests[1:]]
    assert len(tries) == 2
    assert tries[0]["offerta"]["piano"] != "Base"         # all the leaves: one more page
    assert tries[1]["offerta"]["piano"] == "Base"         # the half used leaves it alone
    assert tries[1]["cliente"]["nome"] != "Alfa"


def _with_plan(sent: dict) -> bytes:
    """The fake template with the plan printed first; a plan other than Base adds a page."""
    from .controlgen import LEFT, RUNNING, STEP, TOP, pdf

    plan = sent["offerta"]["piano"]
    nome = str(sent["cliente"]["nome"]).upper()
    importo = f"{float(sent['offerta']['importo']):.2f}".replace(".", ",")
    y, m, d = str(sent["offerta"]["decorrenza"])[:10].split("-")
    lines = [f"Piano {plan}", RUNNING[0], RUNNING[1], f"Quota vale {nome} euro al periodo",
             f"Importo {importo} euro", f"Decorrenza {d}/{m}/{y}", RUNNING[2], RUNNING[3]]
    first = [(LEFT, TOP + STEP * k, line) for k, line in enumerate(lines)]
    return pdf([first] if plan == "Base" else [first, [(LEFT, TOP, "Condizioni del piano")]])


def test_a_label_switched_by_a_value_is_never_proven(tmp_path: Path, server: ControlServer):
    """F18: the perturbed amount also switches a label's wording («Tariffa
    standard» → «variata»), without a page or a section: only the amount (and
    the other printed values) are proven, never the label's words."""
    server.answer = lambda n, sent: Answer(body=render(sent, label=True))
    env = Env(tmp_path, server, sync)
    ini, case = env.case()

    v1, _ = env.svc.generate(ini, case, "tobe")

    record = _record(case)
    assert record.stato == "pronta"
    assert "Tariffa variata applicata" in _text(case.folder / "cache" / f"controllo-{record.sha}.pdf")
    side = json.loads((case.folder / "cache" / f"controllo-{record.sha}.json").read_text(encoding="utf-8"))
    words = sorted(w[3] for w in side["parole"])
    assert words == ["12,50", "18/03/2026", "ALFA"] and "standard" not in words


def _text(path: Path) -> str:
    from qtrequestory.officina.compare.extract_pdf import extract

    return " ".join(w.text for w in extract(path).words)


def test_the_control_goes_to_svil_whatever_the_case_generator(tmp_path: Path, server: ControlServer):
    other = ControlServer()
    try:
        env = Env(tmp_path, server, sync, generators=[GeneratorEndpoint("coll", other.url),
                                                      GeneratorEndpoint("svil", server.url)], default="coll")
        ini, case = env.case()
        assert case.env == "coll"

        v1, result = env.svc.generate(ini, case, "tobe")

        assert result.ok and len(other.requests) == 1 and len(server.requests) == 1   # the control on svil
        assert _record(case).stato == "pronta"
    finally:
        other.close()


def test_without_svil_the_control_is_not_available(tmp_path: Path, server: ControlServer):
    env = Env(tmp_path, server, sync, generators=[GeneratorEndpoint("coll", server.url),
                                                  GeneratorEndpoint("svil", server.url, enabled=False)],
              default="coll")
    ini, case = env.case()

    v1, result = env.svc.generate(ini, case, "tobe")

    assert result.ok and len(server.requests) == 1
    assert env.svc.control_state(case).nota == CONTROL_UNAVAILABLE_NOTE


# ------------------------------------------------ one per case, cancelled ---

def test_a_regeneration_cancels_the_control_in_progress(tmp_path: Path, server: ControlServer):
    env = Env(tmp_path, server)          # manual runner: jobs wait in env.jobs
    ini, case = env.case()
    env.svc.generate(ini, case, "tobe")
    assert len(env.jobs) == 1 and env.svc.control_state(case).stato == "in_corso"

    env.svc.generate(ini, case, "tobe")  # Rigenera: the first control is cancelled, a new one queued
    assert len(env.jobs) == 2 and len(server.requests) == 2

    env.jobs.pop(0)()                    # the cancelled one sends nothing and writes nothing
    assert len(server.requests) == 2 and _record(case) is None
    assert env.svc.control_state(case).stato == "in_corso"
    env.jobs.pop(0)()
    assert len(server.requests) == 3 and _record(case).stato == "pronta"
    assert env.svc.control_state(case).stato == "pronta"


def test_a_regeneration_that_fails_still_cancels_the_control(tmp_path: Path, server: ControlServer):
    server.answer = lambda n, body: Answer(status=500) if n == 1 else Answer()
    env = Env(tmp_path, server)
    ini, case = env.case()
    env.svc.generate(ini, case, "tobe")
    version, result = env.svc.generate(ini, case, "tobe")     # Rigenera, refused by the generator
    assert version is None and not result.ok and len(env.jobs) == 1

    env.run_jobs()

    assert len(server.requests) == 2 and _record(case) is None
    assert env.svc.control_state(case).stato == "assente"


def test_in_corso_is_never_written_and_reads_back_as_assente(tmp_path: Path, server: ControlServer):
    env = Env(tmp_path, server)
    ini, case = env.case()
    env.svc.generate(ini, case, "tobe")
    raw = json.loads((case.folder / "caso.json").read_text(encoding="utf-8"))
    assert raw.get("controllo") is None
    fresh = OfficinaService(lambda: env.config, control_runner=None)
    assert fresh.control_state(case) == ControlState("assente")


def test_an_email_case_has_no_control(tmp_path: Path, server: ControlServer):
    server.answer = lambda n, body: Answer(body=b"<!doctype html><html><body>" + b"Alfa " * 200 + b"</body></html>")
    env = Env(tmp_path, server, sync)
    ini, case = env.case(with_target=False)

    v1, result = env.svc.generate(ini, case, "tobe")

    assert result.ok and v1.doc_type == "html" and len(server.requests) == 1
    assert env.svc.control_state(case) == ControlState("assente")


def test_the_real_app_runs_it_in_a_daemon_thread(tmp_path: Path, server: ControlServer):
    from qtrequestory.officina.service_control import start_thread

    env = Env(tmp_path, server, start_thread)
    ini, case = env.case()
    env.svc.generate(ini, case, "tobe")
    job = env.svc._control_jobs.get(next(iter(env.svc._control_jobs), ""))
    if job is not None:
        assert job.done.wait(30)
    assert _record(case).stato == "pronta" and len(server.requests) == 2


# ------------------------------------------ an initiative deleted meanwhile ---

def _tree(folder: Path) -> list[str]:
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*")) if folder.exists() else []


def test_an_answer_arriving_after_the_initiative_folder_is_gone_writes_nothing(tmp_path: Path,
                                                                                 server: ControlServer):
    import shutil

    env = Env(tmp_path, server, sync)
    ini, case = env.case()
    root, name, folder = ini.folder.parent, ini.name, ini.folder

    def gone_meanwhile(n: int, body: dict) -> Answer:
        if n == 1:                                   # the control call: the folder vanishes before its answer
            shutil.rmtree(folder)
        return Answer()
    server.answer = gone_meanwhile

    v1, result = env.svc.generate(ini, case, "tobe")

    assert result.ok and len(server.requests) == 2
    assert not folder.exists() and _tree(root) == []                  # no ghost folder
    again = env.svc.create_initiative(name)                           # the same name is free
    assert again.folder == folder


def test_deleting_an_initiative_cancels_its_control_in_progress(tmp_path: Path, server: ControlServer):
    env = Env(tmp_path, server)          # manual runner: the job waits in env.jobs
    ini, case = env.case()
    env.svc.generate(ini, case, "tobe")
    assert env.svc.control_state(case).stato == "in_corso"

    env.svc.delete_initiative(ini)
    env.run_jobs()

    assert len(server.requests) == 1 and not ini.folder.exists() and _tree(ini.folder.parent) == []
    assert env.svc.create_initiative(ini.name).folder == ini.folder


def test_deleting_an_initiative_during_the_control_call_drops_the_answer(tmp_path: Path, server: ControlServer):
    env = Env(tmp_path, server, sync)
    ini, case = env.case()

    def deleted_meanwhile(n: int, body: dict) -> Answer:
        if n == 1:
            env.svc.delete_initiative(ini)       # the user's deletion lands while svil answers
        return Answer()
    server.answer = deleted_meanwhile

    env.svc.generate(ini, case, "tobe")

    assert len(server.requests) == 2 and _tree(ini.folder.parent) == []
    assert env.svc.create_initiative(ini.name).folder == ini.folder


def test_deleting_an_initiative_forgets_what_its_cases_comparisons_found(tmp_path: Path, server: ControlServer):
    env = Env(tmp_path, server, sync)
    ini, case = env.case()
    v1, _ = env.svc.generate(ini, case, "tobe")
    env.svc.compare_case(ini, case, v1)
    assert any(g.n for g in env.svc.filters(ini, case).groups)

    env.svc.delete_initiative(ini)

    assert not any(g.n for g in env.svc.filters(ini, case).groups)
