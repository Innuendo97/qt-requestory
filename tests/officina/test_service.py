"""qtrequestory.officina.service: the OfficinaApi the UI talks to.

Every generation goes to a local ``http.server`` (``FakeServer`` of the
generator tests) — never to a real endpoint. PDFs are the hand-built
``canned_pdf`` of the fake core (no Qt needed). Synthetic data only.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import threading
import time
from collections.abc import Iterator
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from qtrequestory.core.config import Config, Environment, GeneratorEndpoint, OfficinaSettings, default_config
from qtrequestory.core.events import CancelToken, CollectingSink
from qtrequestory.core.facade import IndexService
from qtrequestory.core.index.search import SearchQuery
from qtrequestory.officina import service_compare as service_mod
from qtrequestory.officina.generator import SendResult
from qtrequestory.officina.model import Case, Initiative, Version
from qtrequestory.officina.service import CompareError, OfficinaService
from qtrequestory.ui.contracts import OfficinaApi
from tests.conftest import FDI_B, KEY_SINT
from tests.fakes.fake_core import canned_pdf

from .test_generator import HTML, FakeServer
from .test_links import SIG, sas

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
VALID = "2026-12-31T23%3A59%3A59Z"
PDF = canned_pdf("MOD_TEST documento generato\nseconda riga del documento")
KEY = "MOD_TEST_A"
#: A marker that must never reach a log line: it sits in the payload.
SECRET_MARKER = "SEGRETO-DEL-PAYLOAD-0123"


def payload() -> dict:
    return {
        "documents": [{
            "template": {"templateKey": KEY},
            "attributes": [
                {"key": "attachmentId", "value": "att-0"},
                {"key": "attachmentUrl", "value": sas(VALID)},
            ],
        }],
        "customers": [{"name": SECRET_MARKER}],
    }


# ------------------------------------------------------------------ fixtures ---

@pytest.fixture
def server() -> Iterator[FakeServer]:
    s = FakeServer()
    s.canned.body = PDF
    yield s
    s.close()


class Env:
    """A real OfficinaService on a tmp Officina root, generator = local server."""

    def __init__(self, tmp_path: Path, server: FakeServer | None, **officina) -> None:
        url = server.url if server is not None else "https://example.invalid/svil/documentGenerator"
        settings = OfficinaSettings(
            root=tmp_path / "officina",
            generators=[GeneratorEndpoint("svil", url), GeneratorEndpoint("coll", url, enabled=False)],
            default_generator="svil",
            timeout_s=10,
        )
        settings = dataclasses.replace(settings, **officina)
        self.config: Config = dataclasses.replace(default_config(), mirror_root=tmp_path / "mirror",
                                                  officina=settings)
        self.uuid_n = 0
        self.conversions: list[tuple[Path, Path]] = []
        self.svc = OfficinaService(lambda: self.config, clock=lambda: NOW, new_uuid=self._uuid,
                                   html_to_pdf=self._html_to_pdf)

    def _uuid(self) -> str:
        self.uuid_n += 1
        return f"00000000-0000-4000-8000-{self.uuid_n:012d}"

    def _html_to_pdf(self, html: Path, out_pdf: Path, timeout_s: int = 60) -> str | None:
        self.conversions.append((Path(html), Path(out_pdf)))
        out_pdf.with_name(out_pdf.stem + ".sanitised.html").write_bytes(Path(html).read_bytes())
        out_pdf.write_bytes(canned_pdf("MOD_TEST corpo email"))
        return None

    def case(self, name: str = "Iniziativa di prova", *, key: str = KEY, variant: str = "",
             body: dict | None = None) -> tuple[Initiative, Case]:
        try:
            ini = self.svc.load(name)
        except FileNotFoundError:
            ini = self.svc.create_initiative(name)
        src = self.config.officina.root.parent / f"payload-{key}-{variant or 'base'}.json"
        src.write_text(json.dumps(body if body is not None else payload()), encoding="utf-8")
        return ini, self.svc.case_from_file(ini, src, key, variant)


@pytest.fixture
def env(tmp_path: Path, server: FakeServer) -> Env:
    return Env(tmp_path, server)


def files_under(folder: Path) -> list[str]:
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()) if folder.exists() else []


# -------------------------------------------------------------- workspace ---

def test_service_satisfies_the_protocol(env: Env):
    assert isinstance(env.svc, OfficinaApi)


def test_workspace_root_and_initiatives(env: Env, tmp_path: Path):
    assert env.svc.workspace_root() == tmp_path / "officina"
    assert env.svc.initiatives() == []
    ini = env.svc.create_initiative("Offerte 2026")
    assert [i.name for i in env.svc.initiatives()] == ["Offerte 2026"]
    assert env.svc.load("Offerte 2026").folder == ini.folder


def test_without_a_root_nothing_is_written(tmp_path: Path):
    e = Env(tmp_path, None, root=None)
    assert e.svc.workspace_root() is None
    assert e.svc.initiatives() == []
    with pytest.raises(ValueError, match="cartella"):
        e.svc.create_initiative("X")
    assert list(tmp_path.iterdir()) == []


def test_generate_without_a_root_is_a_refusal_not_an_exception(tmp_path: Path, server: FakeServer):
    e = Env(tmp_path, server)
    ini, case = e.case()
    e.config = dataclasses.replace(e.config, officina=dataclasses.replace(e.config.officina, root=None))
    version, result = e.svc.generate(ini, case, "tobe")
    assert version is None and not result.ok and "cartella" in result.reason
    assert server.requests == []


def test_a_relative_root_is_refused(tmp_path: Path):
    e = Env(tmp_path, None, root=Path("relativa"))
    assert e.svc.workspace_root() is None
    with pytest.raises(ValueError):
        e.svc.create_initiative("X")


def test_case_from_file(env: Env):
    ini, case = env.case(variant="Abilitato")
    assert (case.key, case.variant, case.id, case.env, case.source_fdi) == (KEY, "Abilitato", f"{KEY}__abilitato", "svil", None)
    assert env.svc.payload(case) == payload()
    assert [c.id for c in env.svc.load(ini.name).cases] == [case.id]


@pytest.mark.parametrize("content", [b"[1, 2]", b"{ non json", b""])
def test_case_from_file_refuses_a_non_object(env: Env, tmp_path: Path, content: bytes):
    ini = env.svc.create_initiative("I")
    src = tmp_path / "bad.json"
    src.write_bytes(content)
    with pytest.raises(ValueError):
        env.svc.case_from_file(ini, src, KEY)
    assert env.svc.load("I").cases == []


def test_case_from_file_needs_a_key(env: Env, tmp_path: Path):
    ini = env.svc.create_initiative("I")
    src = tmp_path / "p.json"
    src.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="template"):
        env.svc.case_from_file(ini, src, "  ")


def test_case_from_file_accepts_a_bom(env: Env, tmp_path: Path):
    ini = env.svc.create_initiative("I")
    src = tmp_path / "p.json"
    src.write_bytes(b"\xef\xbb\xbf" + json.dumps({"documents": []}).encode())
    assert env.svc.payload(env.svc.case_from_file(ini, src, KEY)) == {"documents": []}


def test_case_from_hit_uses_the_real_index(env: Env, mirror, tmp_path: Path):
    cfg = dataclasses.replace(default_config(), mirror_root=mirror.root,
                              environments=[Environment("coll", "https://example.invalid/coll/")])
    index = IndexService(lambda: cfg)
    index.update(["coll"], full_rebuild=True, sink=CollectingSink(), cancel=CancelToken())
    hit = index.search(SearchQuery("coll", fdi_prefix=FDI_B, template_key=KEY_SINT))[0]
    svc = OfficinaService(lambda: env.config, index=index, clock=lambda: NOW)
    ini = svc.create_initiative("Da ricerca")

    case = svc.case_from_hit(ini, hit, "variante")

    assert (case.key, case.variant, case.source_fdi, case.env) == (KEY_SINT, "variante", FDI_B, "svil")
    assert svc.payload(case) == json.loads(index.read_body(hit))


def test_case_from_hit_refuses_a_non_json_body(env: Env, mirror):
    cfg = dataclasses.replace(default_config(), mirror_root=mirror.root,
                              environments=[Environment("coll", "https://example.invalid/coll/")])
    index = IndexService(lambda: cfg)
    index.update(["coll"], full_rebuild=True, sink=CollectingSink(), cancel=CancelToken())
    hit = next(h for h in index.search(SearchQuery("coll", fdi_prefix="bbbb")) if not h.json_ok)
    svc = OfficinaService(lambda: env.config, index=index)
    ini = svc.create_initiative("I")
    with pytest.raises(ValueError, match="JSON"):
        svc.case_from_hit(ini, hit)
    assert svc.load("I").cases == []


def test_save_case_payload_and_target_delegate_to_the_workspace(env: Env, tmp_path: Path):
    ini, case = env.case()
    case.notes = "nota"
    env.svc.save_case(case)
    env.svc.save_payload(case, {"documents": [], "x": 1})
    src = tmp_path / "Modulo cliente.pdf"
    src.write_bytes(PDF)
    target = env.svc.set_target(case, src)
    again = env.svc.load(ini.name).cases[0]
    assert again.notes == "nota"
    assert env.svc.payload(again) == {"documents": [], "x": 1}
    assert target.kind == "target" and again.target().path.name == "Modulo cliente.pdf"


# ---------------------------------------------------------------- generate ---

def test_generate_asis_then_tobe_twice(env: Env, server: FakeServer):
    ini, case = env.case()

    asis, r0 = env.svc.generate(ini, case, "asis")
    tobe1, r1 = env.svc.generate(ini, case, "tobe")
    tobe2, r2 = env.svc.generate(ini, case, "tobe")

    assert all(isinstance(r, SendResult) and r.ok for r in (r0, r1, r2))
    assert [v.number for v in (asis, tobe1, tobe2)] == [0, 1, 2]
    assert [v.kind for v in (asis, tobe1, tobe2)] == ["asis", "tobe", "tobe"]
    assert asis.path.read_bytes() == PDF and asis.doc_type == "pdf"
    assert [v.number for v in case.tobe_versions()] == [1, 2]
    # what went out: automatic headers, and the upload link removed (policy "remove")
    headers, body = server.requests[0]
    low = {k.lower(): v for k, v in headers.items()}
    assert low["template_key"] == KEY
    assert low["postman-token"] == "qtRequestory"
    assert low["correlation_id"] == "00000000-0000-4000-8000-000000000001"
    assert low["current_timestamp"] == str(int(NOW.timestamp() * 1000))
    sent = json.loads(body)
    assert "attachmentUrl" not in json.dumps(sent) and "attachmentId" not in json.dumps(sent)
    # the version's meta: no payload, masked headers, the env
    meta = tobe2.meta
    assert meta["env"] == "svil" and meta["status"] == 200 and meta["links_removed"] == 1
    assert meta["headers_sent"]["template_key"] == KEY
    assert SECRET_MARKER not in json.dumps(meta)
    assert SIG not in json.dumps(meta)


def test_a_failed_send_writes_no_file(env: Env, server: FakeServer):
    ini, case = env.case()
    before = files_under(case.folder)
    server.canned.status = 500
    server.canned.body = b"errore interno"

    version, result = env.svc.generate(ini, case, "tobe")

    assert version is None and not result.ok and result.status == 500
    assert "500" in result.reason
    assert files_under(case.folder) == before
    assert case.tobe_versions() == []


def test_a_timeout_writes_no_file(tmp_path: Path, server: FakeServer):
    e = Env(tmp_path, server, timeout_s=1)
    ini, case = e.case()
    server.canned.delay_s = 3
    version, result = e.svc.generate(ini, case, "asis")
    assert version is None and not result.ok and "tempo scaduto" in result.reason
    assert case.asis() is None and not (case.folder / "asis").exists()


@pytest.mark.parametrize("env_name, why", [("coll", "non è attivo"), ("ignoto", "non è configurato"),
                                           ("", "nessun generatore")])
def test_an_env_that_is_not_an_enabled_generator_is_refused(env: Env, server: FakeServer, env_name: str, why: str):
    ini, case = env.case()
    case.env = env_name

    version, result = env.svc.generate(ini, case, "tobe")

    assert version is None and not result.ok and result.status is None
    assert why in result.reason
    assert server.requests == []
    assert case.tobe_versions() == []


def test_a_prod_generator_is_refused_even_if_the_config_slipped_through(tmp_path: Path, server: FakeServer):
    e = Env(tmp_path, server, generators=[GeneratorEndpoint("PRODUZIONE", server.url)],
            default_generator="PRODUZIONE")
    ini, case = e.case()
    version, result = e.svc.generate(ini, case, "tobe")
    assert version is None and "prod" in result.reason.lower()
    assert server.requests == []


def test_a_still_valid_link_is_refused_with_keep_if_expired(env: Env, server: FakeServer):
    ini, case = env.case()
    case.link_policy = "keep_if_expired"
    version, result = env.svc.generate(ini, case, "tobe")
    assert version is None and "ancora valido" in result.reason
    assert "sig=***" in result.reason and SIG not in result.reason
    assert server.requests == []


def test_a_header_problem_is_refused(env: Env, server: FakeServer):
    ini, case = env.case()
    case.correlation = "source"  # no source FDI: a case from a file
    version, result = env.svc.generate(ini, case, "tobe")
    assert version is None and "correlation_id" in result.reason
    assert server.requests == []


def test_an_empty_payload_is_refused(env: Env, server: FakeServer):
    ini, case = env.case(body={})
    version, result = env.svc.generate(ini, case, "tobe")
    assert version is None and "payload" in result.reason
    assert server.requests == []


def test_correlation_source_uses_the_case_source_fdi(env: Env, server: FakeServer):
    ini, case = env.case()
    case.source_fdi = FDI_B
    case.correlation = "source"
    env.svc.generate(ini, case, "tobe")
    low = {k.lower(): v for k, v in server.requests[0][0].items()}
    assert low["correlation_id"] == FDI_B


def test_asis_twice_needs_a_note_and_is_refused_before_sending(env: Env, server: FakeServer):
    ini, case = env.case()
    env.svc.generate(ini, case, "asis")
    version, result = env.svc.generate(ini, case, "asis")
    assert version is None and "nota" in result.reason
    assert len(server.requests) == 1

    server.canned.body = canned_pdf("MOD_TEST nuovo AS-IS")
    version, result = env.svc.generate(ini, case, "asis", replace_asis_note="template ripubblicato")
    assert result.ok and version.path.read_bytes() == server.canned.body
    assert case.history[-1]["note"] == "template ripubblicato"


def test_an_html_answer_for_a_pdf_case_is_a_failed_run(env: Env, server: FakeServer, tmp_path: Path):
    ini, case = env.case()
    src = tmp_path / "atteso.pdf"
    src.write_bytes(PDF)
    env.svc.set_target(case, src)
    server.canned.body = HTML

    version, result = env.svc.generate(ini, case, "tobe")

    assert version is None and not result.ok
    assert result.reason == "risposta HTML per un caso PDF: probabilmente una pagina d'errore del gateway"
    assert len(result.content) <= 4096
    assert case.tobe_versions() == []


def test_a_pdf_answer_for_an_html_case_is_a_failed_run(env: Env, server: FakeServer, tmp_path: Path):
    ini, case = env.case()
    src = tmp_path / "email.html"
    src.write_bytes(HTML)
    env.svc.set_target(case, src)

    version, result = env.svc.generate(ini, case, "tobe")

    assert version is None and not result.ok and "risposta PDF per un caso HTML" in result.reason
    assert case.tobe_versions() == []


def test_the_asis_type_is_the_expectation_when_there_is_no_target(env: Env, server: FakeServer):
    ini, case = env.case()
    server.canned.body = HTML
    asis, r = env.svc.generate(ini, case, "asis")  # nothing known yet: html accepted
    assert r.ok and asis.doc_type == "html"
    server.canned.body = PDF
    version, result = env.svc.generate(ini, case, "tobe")
    assert version is None and "risposta PDF per un caso HTML" in result.reason
    # the expectation came from the AS-IS, not a target: the reason says so
    assert "atteso HTML come l'AS-IS" in result.reason
    assert "se l'AS-IS è sbagliato rigeneralo con una nota" in result.reason


def test_a_wrong_asis_can_be_replaced_by_one_of_another_type(env: Env, server: FakeServer):
    """The old AS-IS is not the expectation of its own replacement: otherwise
    an AS-IS of the wrong type could never be fixed."""
    ini, case = env.case()
    server.canned.body = HTML
    env.svc.generate(ini, case, "asis")
    server.canned.body = PDF
    version, result = env.svc.generate(ini, case, "asis", replace_asis_note="era la pagina d'errore")
    assert result.ok and version.doc_type == "pdf" and case.asis().doc_type == "pdf"


def test_cancel_before_sending(env: Env, server: FakeServer):
    ini, case = env.case()
    cancel = CancelToken()
    cancel.cancel()
    version, result = env.svc.generate(ini, case, "tobe", cancel=cancel)
    assert version is None and not result.ok and "annullat" in result.reason
    assert server.requests == []


def test_nothing_from_the_payload_or_the_document_is_logged(env: Env, server: FakeServer,
                                                           caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.DEBUG)
    ini, case = env.case()
    case.link_policy = "keep_if_expired"
    env.svc.generate(ini, case, "tobe")          # refused: valid link
    case.link_policy = "remove"
    env.svc.generate(ini, case, "tobe")          # ok
    server.canned.status = 500
    server.canned.body = SECRET_MARKER.encode()
    env.svc.generate(ini, case, "tobe")          # failed, the body echoes the marker
    text = caplog.text
    assert caplog.records, "the service logs its outcomes"
    assert SECRET_MARKER not in text
    assert "MOD_TEST documento" not in text
    assert SIG not in text and "se=" not in text


# ----------------------------------------------------------------- compare ---

def _versions(env: Env, tmp_path: Path, target: bytes, generated: bytes, *, name: str = "atteso.pdf",
              kind: str = "tobe") -> tuple[Case, Version, Version]:
    ini, case = env.case()
    src = tmp_path / name
    src.write_bytes(target)
    tgt = env.svc.set_target(case, src)
    from qtrequestory.officina.model import Workspace
    other = Workspace(env.svc.workspace_root()).add_version(case, kind, generated, "pdf", {})
    return case, tgt, other


def test_compare_finds_the_changed_word(env: Env, tmp_path: Path):
    _, tgt, tobe = _versions(env, tmp_path, canned_pdf("prezzo fisso per dodici mesi"),
                             canned_pdf("prezzo fisso per ventiquattro mesi"))
    result = env.svc.compare(tgt, tobe)
    assert [(d.kind, d.left_text, d.right_text) for d in result.differences] == [("changed", "dodici", "ventiquattro")]


def test_compare_cache_hits_on_the_second_call(env: Env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    calls: list[Path] = []
    real_extract = service_mod.extract

    def counting(path: Path):
        calls.append(Path(path))
        return real_extract(path)

    monkeypatch.setattr(service_mod, "extract", counting)
    _, tgt, tobe = _versions(env, tmp_path, canned_pdf("uno due tre"), canned_pdf("uno due quattro"))

    first = env.svc.compare(tgt, tobe)
    second = env.svc.compare(tgt, tobe)

    assert len(calls) == 2
    assert second is first
    # the same content under another version (a regenerated identical TO-BE) hits too
    same = dataclasses.replace(tobe, number=9)
    assert env.svc.compare(tgt, same) is first and len(calls) == 2


def test_compare_notices_a_changed_file(env: Env, tmp_path: Path):
    _, tgt, tobe = _versions(env, tmp_path, canned_pdf("uno due tre"), canned_pdf("uno due tre"))
    assert env.svc.compare(tgt, tobe).equal
    tobe.path.write_bytes(canned_pdf("uno due cinque"))
    assert not env.svc.compare(tgt, tobe).equal


def test_target_without_text_is_reported_not_diffed(env: Env, tmp_path: Path):
    _, tgt, tobe = _versions(env, tmp_path, canned_pdf(""), canned_pdf("testo del documento generato"))
    result = env.svc.compare(tgt, tobe)
    assert result.differences == [] and not result.equal
    assert result.note == "il target non ha testo estraibile"


def test_the_asis_is_named_as_such(env: Env, tmp_path: Path):
    _, tgt, asis = _versions(env, tmp_path, canned_pdf("testo del target"), canned_pdf(""), kind="asis")
    assert env.svc.compare(tgt, asis).note == "l'AS-IS non ha testo estraibile"


def test_asis_vs_tobe_names_both_sides(env: Env, tmp_path: Path):
    ini, case = env.case()
    from qtrequestory.officina.model import Workspace
    ws = Workspace(env.svc.workspace_root())
    asis = ws.add_version(case, "asis", canned_pdf(""), "pdf", {})
    tobe = ws.add_version(case, "tobe", canned_pdf("testo"), "pdf", {})
    assert env.svc.compare(asis, tobe).note == "l'AS-IS non ha testo estraibile"


def test_html_is_converted_under_the_case_cache(env: Env, tmp_path: Path):
    case, tgt, _ = _versions(env, tmp_path, HTML, PDF, name="email.html")
    from qtrequestory.officina.model import Workspace
    tobe = Workspace(env.svc.workspace_root()).add_version(case, "tobe", HTML, "html", {})

    result = env.svc.compare(tgt, tobe)

    assert result.equal
    assert len(env.conversions) == 1  # same content: converted once
    html_src, out_pdf = env.conversions[0]
    # Edge printed a private copy in cache\ (its sanitised copy went next to
    # the output, in cache\ too); both are temporary: only the final PDF stays
    assert out_pdf.parent == case.folder / "cache" and html_src.parent == case.folder / "cache"
    # nothing derived lands in the slots
    assert files_under(case.folder / "target") == ["email.html", "target.meta.json"]
    assert files_under(case.folder / "tobe") == ["v001.meta.json", "v001.pdf", "v002.html", "v002.meta.json"]
    cached = files_under(case.folder / "cache")
    assert len(cached) == 1 and cached[0].endswith(".pdf")

    # a new service (app restarted) reuses the converted PDF on disk
    again = OfficinaService(lambda: env.config, html_to_pdf=env._html_to_pdf)
    again.compare(tgt, tobe)
    assert len(env.conversions) == 1


def test_an_edge_failure_is_a_compare_error(env: Env, tmp_path: Path):
    case, tgt, _ = _versions(env, tmp_path, HTML, PDF, name="email.html")
    from qtrequestory.officina.model import Workspace
    tobe = Workspace(env.svc.workspace_root()).add_version(case, "tobe", HTML, "html", {})
    svc = OfficinaService(lambda: env.config, html_to_pdf=lambda *a, **k: "Microsoft Edge non trovato")
    with pytest.raises(CompareError, match="Edge non trovato"):
        svc.compare(tgt, tobe)
    assert not any((case.folder / "cache").glob("*.pdf"))


def test_an_unreadable_pdf_is_a_compare_error(env: Env, tmp_path: Path):
    _, tgt, tobe = _versions(env, tmp_path, b"%PDF-1.4\nnon un vero pdf", PDF)
    with pytest.raises(CompareError, match="target"):
        env.svc.compare(tgt, tobe)


def test_a_missing_file_is_a_compare_error(env: Env, tmp_path: Path):
    _, tgt, tobe = _versions(env, tmp_path, PDF, PDF)
    tobe.path.unlink()
    with pytest.raises(CompareError, match="non esiste"):
        env.svc.compare(tgt, tobe)


# ------------------------------------------------------------ core wiring ---

def test_core_services_build_the_service_lazily_and_once(tmp_path: Path):
    from qtrequestory.core.paths import AppPaths
    from qtrequestory.ui.contracts import CoreServices

    services = CoreServices.real(AppPaths(tmp_path / "apphome").ensure())
    first = services.officina
    assert isinstance(first, OfficinaApi) and services.officina is first


def test_importing_the_contracts_never_loads_pypdfium2():
    from tests.test_officina_boundary import _imported_after

    mods = _imported_after("import qtrequestory.ui.contracts, qtrequestory.core.facade")
    assert not any(m.startswith("pypdfium2") for m in mods)
    assert "qtrequestory.officina.pdf" not in mods


# ------------------------------------------------------ fix round 1 (review) ---

class SlowConverter:
    """A stub Edge: slow, records every call, writes a canned PDF (and the
    sanitised copy next to it, like the real one). It first writes half the
    PDF, so a reader that does not wait would see a truncated file."""

    def __init__(self, delay_s: float = 0.0, fail: str | None = None) -> None:
        self.delay_s = delay_s
        self.fail = fail
        self.calls: list[tuple[Path, Path, bytes]] = []
        self._lock = threading.Lock()

    def __call__(self, html: Path, out_pdf: Path, timeout_s: int = 60) -> str | None:
        data = Path(html).read_bytes()
        with self._lock:
            self.calls.append((Path(html), Path(out_pdf), data))
        out_pdf.with_name(out_pdf.stem + ".sanitised.html").write_bytes(data)
        pdf = canned_pdf("MOD_TEST corpo email")
        out_pdf.write_bytes(pdf[: len(pdf) // 2])
        time.sleep(self.delay_s)
        if self.fail:
            return self.fail
        out_pdf.write_bytes(pdf)
        return None


def _html_case(env: Env, tmp_path: Path, html: bytes = HTML):
    from qtrequestory.officina.model import Workspace

    ini, case = env.case()
    src = tmp_path / "email.html"
    src.write_bytes(html)
    tgt = env.svc.set_target(case, src)
    tobe = Workspace(env.svc.workspace_root()).add_version(case, "tobe", html, "html", {})
    return case, tgt, tobe


def test_concurrent_compares_of_the_same_html_convert_once(env: Env, tmp_path: Path):
    case, tgt, tobe = _html_case(env, tmp_path)
    slow = SlowConverter(delay_s=0.4)
    svc = OfficinaService(lambda: env.config, html_to_pdf=slow)
    results, errors = [], []

    def run() -> None:
        try:
            results.append(svc.compare(tgt, tobe))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert errors == [] and len(results) == 2 and all(r.equal for r in results)
    assert len(slow.calls) == 1
    # Edge printed a private copy to a private name; only the final PDF stays
    html_in, out_tmp, _ = slow.calls[0]
    assert out_tmp.parent == case.folder / "cache" and html_in.parent == case.folder / "cache"
    cached = files_under(case.folder / "cache")
    assert len(cached) == 1 and cached[0].endswith(".pdf")
    assert case.folder / "cache" / cached[0] != out_tmp


def test_a_truncated_cached_pdf_is_reconverted(env: Env, tmp_path: Path):
    case, tgt, tobe = _html_case(env, tmp_path)
    slow = SlowConverter()
    OfficinaService(lambda: env.config, html_to_pdf=slow).compare(tgt, tobe)
    (final,) = (case.folder / "cache").glob("*.pdf")
    whole = final.read_bytes()
    assert len(whole) > 1024
    final.write_bytes(whole[:1100])  # a crash mid-write: header and size, no %%EOF

    again = OfficinaService(lambda: env.config, html_to_pdf=slow)
    assert again.compare(tgt, tobe).equal
    assert len(slow.calls) == 2 and final.read_bytes() == whole


def test_a_failed_conversion_leaves_nothing_behind(env: Env, tmp_path: Path):
    case, tgt, tobe = _html_case(env, tmp_path)
    slow = SlowConverter(fail="Edge si è chiuso")
    with pytest.raises(CompareError, match="Edge si è chiuso"):
        OfficinaService(lambda: env.config, html_to_pdf=slow).compare(tgt, tobe)
    assert files_under(case.folder / "cache") == []


def test_the_html_converted_is_the_html_hashed(env: Env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The cached PDF is named by the hash of the bytes Edge printed (a copy
    of exactly those bytes), not of a live file that changed meanwhile."""
    case, tgt, tobe = _html_case(env, tmp_path)
    slow = SlowConverter()
    real_read = service_mod._read_version

    def read_then_edit(version, label):
        data = real_read(version, label)
        if version.kind == "tobe":  # the file changes right after it was read
            version.path.write_bytes(HTML.replace(b"corpo", b"testo"))
        return data

    monkeypatch.setattr(service_mod, "_read_version", read_then_edit)
    OfficinaService(lambda: env.config, html_to_pdf=slow).compare(tgt, tobe)
    assert slow.calls and all(html_in.parent == case.folder / "cache" for html_in, _, _ in slow.calls)
    printed = {hashlib.sha256(data).hexdigest()[:32] for _, _, data in slow.calls}
    names = {p.stem.removeprefix("html-") for p in (case.folder / "cache").glob("*.pdf")}
    assert names and names <= printed


def test_a_pdf_changed_during_extraction_is_not_cached(env: Env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The words cached under a hash are the words OF those bytes: the TO-BE
    is hashed as A, then rewritten to B while extraction runs (and back to
    A — a re-hash afterwards could not tell). Extraction reads a private copy
    of A, so the result is A's, and nothing of B is ever cached under A."""
    calls: list[Path] = []
    real_extract = service_mod.extract
    content_a, content_b = canned_pdf("uno due quattro"), canned_pdf("uno due tre")
    case, tgt, tobe = _versions(env, tmp_path, canned_pdf("uno due tre"), content_a)

    def extract_while_rewritten(path: Path):
        calls.append(Path(path))
        tobe.path.write_bytes(content_b)
        try:
            return real_extract(path)
        finally:
            tobe.path.write_bytes(content_a)

    monkeypatch.setattr(service_mod, "extract", extract_while_rewritten)
    first = env.svc.compare(tgt, tobe)
    assert not first.equal  # A's words ("quattro"), not B's
    assert env.svc.compare(tgt, tobe) is first
    assert calls and all(p.parent == case.folder / "cache" for p in calls)
    assert files_under(case.folder / "cache") == []  # the private copies are gone


def test_case_from_hit_of_a_vanished_call_is_a_readable_error(tmp_path: Path):
    from tests.fakes.fake_core import build_fake_core

    core = build_fake_core(tmp_path / "core")
    hit = core.index.hits[0]
    core.index.set_missing(hit)
    ini = core.officina.create_initiative("I")
    with pytest.raises(ValueError, match="la chiamata non è più nel log locale: ripetere la ricerca"):
        core.officina.case_from_hit(ini, hit)
    assert core.officina.load("I").cases == []


def test_case_from_hit_of_a_deleted_daily_file_is_a_readable_error(env: Env, mirror):
    cfg = dataclasses.replace(default_config(), mirror_root=mirror.root,
                              environments=[Environment("coll", "https://example.invalid/coll/")])
    index = IndexService(lambda: cfg)
    index.update(["coll"], full_rebuild=True, sink=CollectingSink(), cancel=CancelToken())
    hit = index.search(SearchQuery("coll", fdi_prefix=FDI_B, template_key=KEY_SINT))[0]
    hit.file_path.unlink()
    svc = OfficinaService(lambda: env.config, index=index)
    ini = svc.create_initiative("I")
    with pytest.raises(ValueError, match="la chiamata non è più nel log locale"):
        svc.case_from_hit(ini, hit)
    assert svc.load("I").cases == []


def test_render_path_of_a_pdf_is_the_version_itself(env: Env, tmp_path: Path):
    case, tgt, tobe = _versions(env, tmp_path, PDF, PDF)
    assert env.svc.render_path(case, tobe) == tobe.path
    assert env.svc.render_path(case, tgt) == tgt.path


def test_render_path_of_an_html_is_the_cached_edge_pdf(env: Env, tmp_path: Path):
    case, tgt, tobe = _html_case(env, tmp_path)
    slow = SlowConverter()
    svc = OfficinaService(lambda: env.config, html_to_pdf=slow)
    first = svc.render_path(case, tobe)
    assert first.parent == case.folder / "cache" and first.read_bytes().startswith(b"%PDF-")
    assert svc.render_path(case, tgt) == first  # same content, same PDF
    svc.compare(tgt, tobe)
    assert len(slow.calls) == 1


def test_render_path_of_a_missing_file_is_a_compare_error(env: Env, tmp_path: Path):
    case, tgt, tobe = _versions(env, tmp_path, PDF, PDF)
    tobe.path.unlink()
    with pytest.raises(CompareError, match="non esiste"):
        env.svc.render_path(case, tobe)


def test_a_replaced_bundle_builds_its_own_officina(tmp_path: Path):
    from tests.fakes.fake_core import build_fake_core

    built: list[object] = []

    def factory() -> object:
        built.append(object())
        return built[-1]

    core = build_fake_core(tmp_path / "core")
    first = core.officina
    core2 = dataclasses.replace(core, officina_factory=factory)
    assert core2.officina is built[0] and core2.officina is not first and len(built) == 1
