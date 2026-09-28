"""environments.json may also carry the Officina's generators (release 1.3.2).

The sidecar stays what it was — a JSON list of environments — or becomes an
object ``{"environments": [...], "generators": [...]}``. Generators are held
to the very rules Impostazioni applies (https only, no ``prod`` anywhere,
unique names): a bad one is dropped with a log line, never a crash, and the
log line never quotes its URL. Synthetic hosts only.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from qtrequestory.core.config import Environment, GeneratorEndpoint, import_environments_file
from qtrequestory.core.sidecar import import_generators_file, sidecar_generators

ENV_URL = "https://example.invalid/coll/"
GEN_URL = "https://example.invalid/rest/api/submit-job/documentGenerator"


def _write(tmp_path: Path, payload) -> Path:
    path = tmp_path / "environments.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_the_object_form_still_gives_the_environments(tmp_path: Path):
    path = _write(tmp_path, {"environments": [{"name": "coll", "url": ENV_URL}],
                             "generators": [{"name": "svil", "url": GEN_URL}]})
    assert import_environments_file(path) == [Environment("coll", ENV_URL, True)]


def test_importing_an_object_with_generators_only_is_refused(tmp_path: Path):
    """Importa would otherwise replace the environments table with nothing."""
    path = _write(tmp_path, {"generators": [{"name": "svil", "url": GEN_URL}]})
    with pytest.raises(ValueError, match="non contiene ambienti"):
        import_environments_file(path)


def test_the_generators_of_a_generators_only_file_are_still_read(tmp_path: Path):
    path = _write(tmp_path, {"generators": [{"name": "svil", "url": GEN_URL}]})
    assert import_generators_file(path) == [GeneratorEndpoint("svil", GEN_URL, True)]


def test_an_object_without_either_list_is_malformed(tmp_path: Path):
    path = _write(tmp_path, {"name": "coll", "url": ENV_URL})
    with pytest.raises(ValueError):
        import_environments_file(path)


def test_generators_are_read_with_their_flags(tmp_path: Path):
    path = _write(tmp_path, {"environments": [], "generators": [
        {"name": "svil", "url": GEN_URL},
        {"name": "coll", "url": GEN_URL + "?x=1", "enabled": False},
    ]})
    assert import_generators_file(path) == [
        GeneratorEndpoint("svil", GEN_URL, True),
        GeneratorEndpoint("coll", GEN_URL + "?x=1", False),
    ]


def test_the_list_form_has_no_generators(tmp_path: Path):
    path = _write(tmp_path, [{"name": "coll", "url": ENV_URL}])
    assert import_generators_file(path) == []


@pytest.mark.parametrize("bad, why", [
    ({"name": "svil", "url": "http://example.invalid/gen"}, "https"),
    ({"name": "prod", "url": GEN_URL}, "prod"),
    ({"name": "svil", "url": "https://prod.example.invalid/gen"}, "prod"),
    ({"name": "", "url": GEN_URL}, "name"),
    ({"name": "svil"}, "url"),
    ("svil", "oggetto"),
    ({"name": "svil", "url": GEN_URL, "enabled": "si"}, "enabled"),
])
def test_an_invalid_generator_is_ignored_with_a_log_line(tmp_path: Path, caplog, bad, why):
    good = {"name": "coll", "url": GEN_URL}
    path = _write(tmp_path, {"generators": [bad, good]})
    with caplog.at_level(logging.WARNING, logger="qtrequestory.core.sidecar"):
        assert import_generators_file(path) == [GeneratorEndpoint("coll", GEN_URL, True)]
    messages = [r.getMessage() for r in caplog.records]
    assert len(messages) == 1 and "ignorato" in messages[0]
    assert "example.invalid" not in messages[0]  # a URL is never quoted: it may carry a secret


def test_a_duplicate_name_is_ignored(tmp_path: Path, caplog):
    path = _write(tmp_path, {"generators": [{"name": "svil", "url": GEN_URL},
                                            {"name": "SVIL", "url": GEN_URL}]})
    with caplog.at_level(logging.WARNING, logger="qtrequestory.core.sidecar"):
        assert import_generators_file(path) == [GeneratorEndpoint("svil", GEN_URL, True)]
    assert "duplicat" in caplog.records[0].getMessage()


def test_generators_that_are_not_a_list_are_ignored(tmp_path: Path, caplog):
    path = _write(tmp_path, {"environments": [], "generators": {"name": "svil"}})
    with caplog.at_level(logging.WARNING, logger="qtrequestory.core.sidecar"):
        assert import_generators_file(path) == []
    assert caplog.records


def test_sidecar_generators_never_raises(tmp_path: Path, caplog):
    assert sidecar_generators(tmp_path) == []  # no file at all
    (tmp_path / "environments.json").write_text("nope", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="qtrequestory.core.sidecar"):
        assert sidecar_generators(tmp_path) == []
    assert caplog.records
    _write(tmp_path, {"generators": [{"name": "svil", "url": GEN_URL}]})
    assert sidecar_generators(tmp_path) == [GeneratorEndpoint("svil", GEN_URL, True)]
