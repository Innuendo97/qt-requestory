"""Phase 2.5 on disk: the panel choices (``filtri``) of a case and of an
initiative, and the control generation's record (``controllo``) of a case
(spec §7). 1.3.x files load unchanged and without notes; junk is dropped
with a load note.

Synthetic data only (this repository is public).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from qtrequestory.officina.model import Workspace
from qtrequestory.officina.model_review import ControlRecord, Review, review_to_json


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    return Workspace(tmp_path / "officina-root")


def _payload() -> dict:
    return {"documents": [{"template": {"templateKey": "MOD_TEST_A"}}]}


def _case(ws: Workspace):
    ini = ws.create_initiative("Alpha")
    return ini, ws.add_case(ini, "MOD_TEST_A", "", _payload(), env="svil", source_fdi=None)


def _caso_13x() -> dict:
    """``caso.json`` as 1.3.2 writes it: the phase-2 keys, no ``filtri``/``controllo``."""
    return {
        "key": "MOD_TEST_A", "variant": "", "env": "svil", "headers": {}, "drop_postman_token": False,
        "correlation": "new", "correlation_value": "", "status": "open", "notes": "", "source_fdi": None,
        "accepted_version": None, "reopened_after_acceptance": False, "history": [],
        "profilo": None, "tolleranze": [], "non_variabili": [], "segnate": [], "non_risolte": [],
        "regole_rumore": [], "riepilogo": None,
    }


def _write(path: Path, raw: dict) -> None:
    path.write_text(json.dumps(raw), encoding="utf-8")


def _reload(ws: Workspace, case):
    return next(c for c in ws.load("Alpha").cases if c.id == case.id)


def test_review_defaults_are_empty():
    review = Review()
    assert review.filters == {} and review.control is None


def test_review_json_writes_filtri_and_controllo_last():
    raw = review_to_json(Review(filters={"zona.header": True},
                                control=ControlRecord("ab12", "pronta", "2026-09-28T10:00:00")))
    assert list(raw)[-2:] == ["filtri", "controllo"]
    assert raw["filtri"] == {"zona.header": True}
    assert raw["controllo"] == {"sha": "ab12", "stato": "pronta", "quando": "2026-09-28T10:00:00"}
    assert review_to_json(Review())["controllo"] is None and review_to_json(Review())["filtri"] == {}


def test_a_13x_case_loads_unchanged_and_without_notes(ws: Workspace):
    _, case = _case(ws)
    _write(case.folder / "caso.json", _caso_13x())

    loaded = _reload(ws, case)

    assert loaded.load_error is None and loaded.load_notes == []
    assert loaded.review == Review()


def test_case_filters_and_control_round_trip(ws: Workspace):
    _, case = _case(ws)
    case.review.filters = {"zona.header": True, "decidere.maiuscole": True, "avanzate.Data": False}
    case.review.control = ControlRecord("0f" * 32, "non_disponibile", "2026-09-28T10:00:00")

    ws.save_review(case)
    loaded = _reload(ws, case)

    assert loaded.load_notes == []
    assert loaded.review.filters == case.review.filters
    assert loaded.review.control == case.review.control


@pytest.mark.parametrize(("filtri", "kept", "n_notes"), [
    ("tutti", {}, 1),
    ([["zona.header", True]], {}, 1),
    ({"zona.header": "sì", "zona.footer": True}, {"zona.footer": True}, 1),
    ({"zona.boh": True, "avanzate.": False, "decidere.maiuscole": False}, {"decidere.maiuscole": False}, 2),
    ({"zona.header": 1}, {}, 1),
    ({"zona.invisibile": False, "avanzate.sparita": True}, {"avanzate.sparita": True}, 1),  # F7; stale kept (F4)
])
def test_junk_filters_are_dropped_with_a_note(ws: Workspace, filtri, kept, n_notes):
    _, case = _case(ws)
    _write(case.folder / "caso.json", {**_caso_13x(), "filtri": filtri})

    loaded = _reload(ws, case)

    assert loaded.load_error is None
    assert loaded.review.filters == kept
    assert len(loaded.load_notes) == n_notes and all("filtri" in n for n in loaded.load_notes)


@pytest.mark.parametrize("controllo", [
    "pronta", [], {"sha": "ab", "stato": "boh", "quando": ""}, {"sha": 5, "stato": "pronta", "quando": ""},
    {"stato": "pronta", "quando": ""}, {"sha": "ab", "stato": "pronta", "quando": None},
])
def test_junk_control_is_dropped_with_a_note(ws: Workspace, controllo):
    _, case = _case(ws)
    _write(case.folder / "caso.json", {**_caso_13x(), "controllo": controllo})

    loaded = _reload(ws, case)

    assert loaded.load_error is None and loaded.review.control is None
    assert len(loaded.load_notes) == 1 and "controllo" in loaded.load_notes[0]


def test_a_null_control_is_no_control_and_no_note(ws: Workspace):
    _, case = _case(ws)
    _write(case.folder / "caso.json", {**_caso_13x(), "controllo": None, "filtri": None})

    loaded = _reload(ws, case)

    assert loaded.review.control is None and loaded.review.filters == {} and loaded.load_notes == []


def test_save_case_never_touches_the_filters(ws: Workspace):
    """R8 still holds: only ``save_review`` writes the review keys."""
    _, case = _case(ws)
    case.review.filters = {"zona.header": True}
    ws.save_review(case)
    stale = _reload(ws, case)
    stale.review.filters = {}
    stale.notes = "altro"

    ws.save_case(stale)

    assert _reload(ws, case).review.filters == {"zona.header": True}


# ----------------------------------------------------------- iniziativa.json ---

def test_a_13x_initiative_has_no_filters_and_no_notes(ws: Workspace):
    folder = ws.root / "Vecchia"
    (folder / "casi").mkdir(parents=True)
    _write(folder / "iniziativa.json", {"name": "Vecchia", "header_defaults": {}, "profilo": "tollerante",
                                        "regole_rumore": [], "preset_rumore": []})

    ini = ws.load("Vecchia")

    assert ini.filters == {} and ini.load_notes == []
    assert ws.create_initiative("Nuova").filters == {}


def test_initiative_filters_round_trip(ws: Workspace):
    ini = ws.create_initiative("Alpha")
    ini.filters = {"zona.numero_pagina": False, "variabile.buco": True}

    ws.save_initiative_settings(ini)

    loaded = ws.load("Alpha")
    assert loaded.filters == {"zona.numero_pagina": False, "variabile.buco": True}
    raw = json.loads((ini.folder / "iniziativa.json").read_text(encoding="utf-8"))
    assert raw["filtri"] == loaded.filters and raw["name"] == "Alpha"


def test_initiative_junk_filters_are_a_load_note(ws: Workspace):
    folder = ws.root / "Junk"
    (folder / "casi").mkdir(parents=True)
    _write(folder / "iniziativa.json", {"name": "Junk", "header_defaults": {},
                                        "filtri": {"zona.header": True, "boh": True}})

    ini = ws.load("Junk")

    assert ini.filters == {"zona.header": True}
    assert len(ini.load_notes) == 1 and "iniziativa.json" in ini.load_notes[0]


def test_a_control_left_in_corso_reads_as_assente(ws: Workspace):
    """F7: ``in_corso`` lives in memory; on disk it can only be a crash mid-run."""
    _, case = _case(ws)
    _write(case.folder / "caso.json", {**_caso_13x(), "controllo": {"sha": "ab", "stato": "in_corso",
                                                                    "quando": "2026-09-28T10:00:00"}})

    loaded = _reload(ws, case)

    assert loaded.load_notes == []
    assert loaded.review.control == ControlRecord("ab", "assente", "2026-09-28T10:00:00")
    assert loaded.review.control.state().stato == "assente"


def test_legacy_preset_rumore_is_mapped_once_into_filtri(ws: Workspace):
    """F4: the presets turned on become ON advanced rows; a choice already in
    filtri wins; the next save drops preset_rumore for good."""
    folder = ws.root / "Legacy"
    (folder / "casi").mkdir(parents=True)
    _write(folder / "iniziativa.json", {"name": "Legacy", "header_defaults": {}, "preset_rumore": ["Data", "CAP"],
                                        "filtri": {"avanzate.CAP": False, "zona.header": True}})

    ini = ws.load("Legacy")

    assert ini.filters == {"avanzate.CAP": False, "zona.header": True, "avanzate.Data": True}
    assert ini.load_notes == [] and not hasattr(ini, "noise_presets")
    ws.save_initiative_settings(ini)
    raw = json.loads((folder / "iniziativa.json").read_text(encoding="utf-8"))
    assert "preset_rumore" not in raw and raw["filtri"] == ini.filters
    assert ws.load("Legacy").filters == ini.filters


def test_a_mark_saved_by_1_3_reads_as_engine_1_and_a_new_one_round_trips_as_engine_2():
    """Final review M4: marks of 1.3.x (no «motore») are known as such."""
    from qtrequestory.officina.compare.model import Anchor
    from qtrequestory.officina.model_review import Mark, Review, review_from_json, review_to_json

    anchor = Anchor("cambiato", "testo", "prima dopo", "uno")
    legacy = {"segnate": [{"anchor": anchor.to_json(), "generato": "one", "versione": 2, "quando": "x"}]}
    notes: list[str] = []
    [old] = review_from_json(legacy, notes).marks
    assert old.engine == 1 and notes == []
    saved = review_to_json(Review(marks=[old, Mark(anchor, "one", 3, "y")]))
    assert [m.get("motore") for m in saved["segnate"]] == [1, 2]
    assert [m.engine for m in review_from_json(saved, []).marks] == [1, 2]
