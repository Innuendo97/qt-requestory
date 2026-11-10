"""qtrequestory.officina.service_batch: Genera through ``OfficinaService``.

The end-to-end test runs the app's own wiring (``CoreServices.real`` over a
temp ``AppPaths``): a real index over a synthetic mirror, the loopback
``FakeServer`` as the only generator, the HTML memory next to the temp
``config.json``. Synthetic data only (public repo).
"""
from __future__ import annotations

import dataclasses
import json
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from qtrequestory.core.config import Environment, GeneratorEndpoint, default_config, save_config
from qtrequestory.core.events import CancelToken, null_sink
from qtrequestory.core.paths import AppPaths
from qtrequestory.officina.service import NO_GENERATOR, OfficinaService
from qtrequestory.officina.service_batch import NO_INDEX
from qtrequestory.ui.contracts import (
    AUTOMATIC_HEADERS,
    NO_PACKAGE,
    BatchItemDone,
    BatchRequest,
    BatchStarted,
    CoreServices,
    ElencoError,
    targets_from_keys,
)
from tests.conftest import FDI_A, entry_name, make_daily_file, synthetic_body
from tests.officina._server import HTML, PDF, Canned, FakeServer

KEY_A, KEY_H = "MOD_TEST_A", "MOD_TEST_H"
NOW = datetime(2026, 11, 10, 13, 30, 5, tzinfo=timezone.utc)


@pytest.fixture
def server():
    s = FakeServer()
    yield s
    s.close()


@pytest.fixture
def paths(tmp_path: Path) -> AppPaths:
    return AppPaths(tmp_path / "apphome").ensure()


def _config(tmp_path: Path, generator_url: str, **officina):
    base = default_config()
    return dataclasses.replace(
        base,
        mirror_root=tmp_path / "mirror",
        environments=[Environment("svil", "https://example.invalid/svil/"),
                      Environment("coll", "https://example.invalid/coll/")],
        output_dir=tmp_path / "out",
        officina=dataclasses.replace(base.officina, generators=[GeneratorEndpoint("svil", generator_url)],
                                     default_generator="svil", **officina),
    )


@pytest.fixture
def services(tmp_path: Path, paths: AppPaths, server: FakeServer) -> CoreServices:
    make_daily_file(tmp_path / "mirror", "coll", date(2026, 11, 9),
                    [(entry_name(FDI_A, KEY_A, "0a0a0a0a00000001"), synthetic_body(FDI_A, KEY_A)),
                     (entry_name(FDI_A, KEY_H, "0a0a0a0a00000002"), synthetic_body(FDI_A, KEY_H))])
    save_config(_config(tmp_path, server.url, header_profile={"office_id": "00001"}), paths.config_file)
    bundle = CoreServices.real(paths)
    bundle.index.update(["coll"], sink=null_sink, cancel=CancelToken())
    return bundle


def _request(services: CoreServices, destination: Path, *keys: str, **kw) -> BatchRequest:
    values = dict(generator="svil", source_env="coll", targets=targets_from_keys(list(keys), None),
                  header_rows=tuple(services.officina.batch_default_headers()),
                  destination=destination, save_html=False, make_zip=False)
    values.update(kw)
    return BatchRequest(**values)


def _route(headers: dict[str, str], body: bytes) -> Canned:
    key = next((v for k, v in headers.items() if k.casefold() == "template_key"), "")
    return Canned(body=HTML) if key == KEY_H else Canned()


# ------------------------------------------------------------------ batch_run ---

def test_batch_run_uses_configured_generator_and_index(services: CoreServices, server: FakeServer,
                                                       tmp_path: Path):
    events: list = []
    report = services.officina.batch_run(_request(services, tmp_path / "dest", KEY_A), sink=events.append)
    (outcome,) = report.outcomes
    pdf = report.run_dir / NO_PACKAGE / f"{KEY_A}.pdf"
    assert (outcome.status, outcome.files, outcome.fdi) == ("ok", (pdf,), FDI_A)
    assert pdf.read_bytes() == PDF and (report.run_dir / "esito.csv").is_file()
    assert report.run_dir.parent == tmp_path / "dest" and report.run_dir.name.startswith("svil_")
    (headers, body), = server.requests
    sent = {k.casefold(): v for k, v in headers.items()}
    assert sent["template_key"] == KEY_A and sent["office_id"] == "00001"
    assert json.loads(body)["documents"][0]["template"]["templateKey"] == KEY_A
    assert [type(e) for e in events] == [BatchStarted, BatchItemDone]


def test_html_memory_lives_next_to_config_and_is_one_per_service(services: CoreServices,
                                                                server: FakeServer, paths: AppPaths,
                                                                tmp_path: Path):
    server.route = _route
    officina = services.officina
    first = officina.batch_run(_request(services, tmp_path / "dest", KEY_H))
    assert first.outcomes[0].status == "html_skipped" and len(server.requests) == 1
    assert paths.genera_html_file == paths.config_file.with_name("genera-html.json")
    assert json.loads(paths.genera_html_file.read_text(encoding="utf-8")) == {"html_keys": [KEY_H]}
    # the same service remembers it: the key is not called again
    second = officina.batch_run(_request(services, tmp_path / "dest", KEY_H))
    assert second.outcomes[0].status == "html_skipped" and len(server.requests) == 1
    # a new service (next start of the app) reads it back from the file
    fresh = CoreServices.real(paths).officina
    assert fresh is not officina
    fresh.batch_run(_request(services, tmp_path / "dest", KEY_H))
    assert len(server.requests) == 1


def test_batch_count_reads_only(services: CoreServices, server: FakeServer, tmp_path: Path):
    """Review item 6: the real number of calls of an FDI, before anything is sent."""
    from qtrequestory.ui.contracts import targets_from_fdis

    request = _request(services, tmp_path / "dest", targets=targets_from_fdis([FDI_A]))
    assert services.officina.batch_count(request) == 2
    assert server.requests == [] and not (tmp_path / "dest").exists()
    no_index = OfficinaService(services.config.current, control_runner=None)
    with pytest.raises(ValueError, match="ricerca non disponibile"):
        no_index.batch_count(request)


def test_batch_run_reads_the_settings_again_for_every_row(services: CoreServices,
                                                          server: FakeServer, tmp_path: Path):
    """Review item 3b: the service passes a settings SOURCE, not a copy taken at start."""
    config = services.config.current()

    def disable_after_first(headers, body):
        services.config.save(dataclasses.replace(config, officina=dataclasses.replace(
            config.officina, generators=[dataclasses.replace(g, enabled=False)
                                         for g in config.officina.generators])))
        return Canned()

    server.route = disable_after_first
    request = _request(services, tmp_path / "dest", KEY_A, KEY_H, save_html=True)
    with patch("qtrequestory.officina.batch.runner.WORKERS", 1):  # one row after the other
        report = services.officina.batch_run(request)
    assert [o.status for o in report.outcomes] == ["ok", "failed"] and len(server.requests) == 1


def test_batch_run_without_index_is_an_italian_value_error(tmp_path: Path, server: FakeServer):
    config = _config(tmp_path, server.url)
    svc = OfficinaService(lambda: config, control_runner=None)
    request = BatchRequest("svil", "coll", targets_from_keys([KEY_A], None), (), tmp_path / "dest",
                           save_html=False, make_zip=False)
    with pytest.raises(ValueError, match="ricerca non disponibile") as caught:
        svc.batch_run(request)
    assert str(caught.value) == NO_INDEX
    assert not (tmp_path / "dest").exists() and server.requests == []


def test_batch_run_without_generator_is_an_italian_value_error(services: CoreServices,
                                                               tmp_path: Path, paths: AppPaths,
                                                               server: FakeServer):
    config = services.config.current()
    services.config.save(dataclasses.replace(config, officina=dataclasses.replace(
        config.officina, generators=[], default_generator="")))
    with pytest.raises(ValueError) as caught:
        services.officina.batch_run(_request(services, tmp_path / "dest", KEY_A))
    assert str(caught.value) == NO_GENERATOR
    assert not (tmp_path / "dest").exists() and server.requests == []


def test_service_without_memory_path_writes_no_memory_file(tmp_path: Path, server: FakeServer,
                                                          services: CoreServices, paths: AppPaths):
    server.route = _route
    svc = OfficinaService(services.config.current, index=services.index, control_runner=None,
                          clock=lambda: NOW)
    report = svc.batch_run(_request(services, tmp_path / "dest", KEY_H))
    assert report.outcomes[0].status == "html_skipped"
    assert report.run_dir.name == f"svil_{NOW.astimezone():%Y%m%d-%H%M%S}"  # the service's clock
    assert not paths.genera_html_file.exists()
    svc.batch_run(_request(services, tmp_path / "dest", KEY_H))
    assert len(server.requests) == 1  # remembered for the session all the same


# ------------------------------------------------------- headers and elenco ---

def test_batch_default_headers_from_profile(tmp_path: Path):
    config = _config(tmp_path, "https://example.invalid/svil",
                     header_profile={"office_id": "00001", "correlation_id": "fisso"})
    rows = OfficinaService(lambda: config, control_runner=None).batch_default_headers()
    assert rows == [("template_key", ""), ("current_timestamp", ""), ("correlation_id", "fisso"),
                    (AUTOMATIC_HEADERS[3], ""), ("office_id", "00001")]


def test_batch_load_elenco_raises_elenco_error(tmp_path: Path):
    svc = OfficinaService(lambda: default_config(), control_runner=None)
    with pytest.raises(ElencoError):
        svc.batch_load_elenco(tmp_path / "assente.csv")
    path = tmp_path / "elenco.csv"
    path.write_bytes("Template key;a;b;c;package name\r\nMOD_TEST_A;;;;111_PKG\r\n".encode("cp1252"))
    elenco = svc.batch_load_elenco(path)
    assert elenco.packages() == [("111_PKG", 1)]


def test_app_paths_put_the_memory_next_to_the_config(tmp_path: Path):
    assert AppPaths(tmp_path).genera_html_file == tmp_path / "genera-html.json"
    moved = AppPaths(tmp_path, config_override=tmp_path / "altrove" / "config.json")
    assert moved.genera_html_file == tmp_path / "altrove" / "genera-html.json"
