"""The "Filtri del confronto" of the real ``OfficinaService`` (phase 2.5,
spec §3.8, rulings F4–F7; task A5): ``compare_case`` applies the case's
switches (zones set aside, proofs, «Tollera tutte», regex rules and presets)
and carries the panel; ``filters`` / ``set_filters`` / ``set_noise_rules``.

Documents come from a LOCAL fake generator (``controlgen``); synthetic data.
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from qtrequestory.officina.compare import noise
from qtrequestory.officina.compare.filter_model import FILTER_IDS
from qtrequestory.officina.compare.verdict import tipo_note
from qtrequestory.officina.model import Case, Initiative
from qtrequestory.officina.model_review import NoiseRule

from .controlgen import RUNNING, Answer, ControlServer, pdf
from .test_service_control import Env, sync

HEAD_T = "Offerta di Acme-Servizi S.p.A. soggetta a direzione"
HEAD_G = "Offerta di Acme S.p.A. soggetta a direzione"
LINE_T = "Lorem Codice CL123456 del 01/02/2026 finale"
LINE_G = "LOREM Codice CL654321 del 03/04/2026 finale"


def _doc(head: str, line: str, *, invisible: bool = False) -> bytes:
    """Two pages with a text header (the brand), running lines, one line of
    values on page 1, the page number at the bottom; ``invisible``: a code
    written in render mode 3 on page 1."""
    pages = []
    for k in range(2):
        body = [(60, 100 + 14 * i, RUNNING[(i + k) % 4]) for i in range(12)]
        if k == 0:
            body.append((60, 100 + 14 * 12, line))
            if invisible:
                body.append((300, 500, "MOD_TEST_CODICE_0001", 3))
        pages.append([(60, 30, head), *body, (280, 800, f"Pagina {k + 1} di 2")])
    return pdf(pages)


@pytest.fixture
def server() -> Iterator[ControlServer]:
    s = ControlServer(answer=lambda n, body: Answer(body=_doc(HEAD_G, LINE_G)))
    yield s
    s.close()


def _case(env: Env, tmp_path: Path) -> tuple[Initiative, Case]:
    ini, case = env.case(with_target=False)
    tgt = tmp_path / "atteso.pdf"
    tgt.write_bytes(_doc(HEAD_T, LINE_T, invisible=True))
    env.svc.set_target(case, tgt)
    return ini, case


def _by(cc, left: str):
    return next(j for j in cc.judged if j.diff.left_text == left)


@pytest.fixture
def made(tmp_path: Path, server: ControlServer):
    env = Env(tmp_path, server)           # control jobs queued, never run
    ini, case = _case(env, tmp_path)
    v1, result = env.svc.generate(ini, case, "tobe")
    assert result.ok
    return env, ini, case, v1


def test_before_any_comparison_every_row_is_zero(made):
    env, ini, case, _ = made
    panel = env.svc.filters(ini, case)
    assert [g.id for g in panel.groups][:len(FILTER_IDS)] == list(FILTER_IDS)
    assert all(g.n == 0 and g.occorrenze == () for g in panel.groups)
    assert [g.id for g in panel.of("avanzate")] == [f"avanzate.{p.name}" for p in noise.PRESETS]


def test_compare_case_carries_the_panel_computed_from_the_documents(made):
    env, ini, case, v1 = made

    cc = env.svc.compare_case(ini, case, v1)

    panel = cc.filters
    header = panel.group("zona.header")
    brand = _by(cc, "Acme-Servizi")
    assert (brand.diff.klass, brand.diff.zone, brand.verdict) == ("zona", "header", "da_fare")
    assert (header.n, header.attivo) == (1, False)
    assert header.occorrenze[0].diff_ids == (brand.diff.id,) and header.occorrenze[0].pagine == (0, 1)
    assert panel.group("decidere.maiuscole").n == 1 and panel.group("decidere.maiuscole").attivo is False
    invisible = panel.group("zona.invisibile")
    assert (invisible.n, invisible.interruttore) == (1, False)
    assert invisible.occorrenze[0].testo == "MOD_TEST_CODICE_0001" and invisible.occorrenze[0].anchors == ()
    assert panel.group("avanzate.Data").n == 2          # the preset is off, its hits are counted (F7)
    # filters() gives the same rows without the ids of this judged list
    again = env.svc.filters(ini, case)
    assert [(g.id, g.n) for g in again.groups] == [(g.id, g.n) for g in panel.groups]
    assert all(o.diff_ids == () for g in again.groups for o in g.occorrenze)


def test_a_zone_set_aside_does_not_count_and_is_not_served_from_the_cache(made):
    env, ini, case, v1 = made
    assert _by(env.svc.compare_case(ini, case, v1), "Acme-Servizi").verdict == "da_fare"

    env.svc.set_filters(ini, case, {"zona.header": True})
    cc = env.svc.compare_case(ini, case, v1)

    brand = _by(cc, "Acme-Servizi")
    assert (brand.diff.klass, brand.verdict) == ("arredo", None)
    assert cc.filters.group("zona.header").n == 1 and cc.filters.group("zona.header").attivo is True
    env.svc.set_filters(ini, case, {"zona.header": None, "zona.numero_pagina": False})
    assert _by(env.svc.compare_case(ini, case, v1), "Acme-Servizi").verdict == "da_fare"


def test_tollera_tutte_tolerates_the_case_only_differences(made):
    env, ini, case, v1 = made
    before = env.svc.compare_case(ini, case, v1)
    assert _by(before, "Lorem").verdict == "da_fare"

    env.svc.set_filters(ini, None, {"decidere.maiuscole": True})     # the initiative's default
    cc = env.svc.compare_case(ini, case, v1)

    lorem = _by(cc, "Lorem")
    assert (lorem.verdict, lorem.tolerated_note) == ("tollerata", tipo_note("maiuscole"))
    assert cc.summary.tollerate == before.summary.tollerate + 1
    assert cc.summary.da_fare == before.summary.da_fare - 1
    assert cc.filters.group("decidere.maiuscole").n == 1


def test_the_filtri_map_owns_the_regex_rules_and_the_presets(made):
    env, ini, case, v1 = made
    env.svc.set_noise_rules(ini, case, [NoiseRule("codice", r"CL\d{6}", enabled=True)])
    cc = env.svc.compare_case(ini, case, v1)
    assert _by(cc, "CL123456").diff.klass == "rumore"                  # enabled: the default
    n = cc.filters.group("avanzate.codice").n
    assert n == 2

    env.svc.set_filters(ini, case, {"avanzate.codice": False})       # the switch wins over enabled (F4)
    cc = env.svc.compare_case(ini, case, v1)
    assert _by(cc, "CL123456").verdict == "da_fare"
    assert cc.filters.group("avanzate.codice").n == n and cc.filters.group("avanzate.codice").attivo is False

    assert _by(cc, "01/02/2026").verdict == "da_fare"
    env.svc.set_filters(ini, None, {"avanzate.Data": True})          # a preset switched on for the initiative
    assert _by(env.svc.compare_case(ini, case, v1), "01/02/2026").diff.klass == "rumore"


def test_a_proof_switched_off_leaves_its_values_counting(tmp_path: Path):
    from .controlgen import payload

    server = ControlServer()
    try:
        env = Env(tmp_path, server, sync)
        ini, case = env.case(payload())
        v1, _ = env.svc.generate(ini, case, "tobe")
        alfa = next(j for j in env.svc.compare_case(ini, case, v1).judged if j.diff.right_text == "ALFA")
        assert alfa.diff.klass == "variabile"

        env.svc.set_filters(ini, case, {"variabile.esecuzione": False})
        cc = env.svc.compare_case(ini, case, v1)
        alfa = next(j for j in cc.judged if j.diff.right_text == "ALFA")
        assert (alfa.diff.klass, alfa.diff.prova, alfa.verdict) == ("testo", "esecuzione", "da_fare")
        assert cc.filters.group("variabile.esecuzione").n == 1       # still found, now counting
    finally:
        server.close()


def test_saving_prunes_the_choices_of_rules_that_are_gone(made):
    env, ini, case, _ = made
    env.svc.set_noise_rules(ini, None, [NoiseRule("ini", "x")])
    env.svc.set_noise_rules(ini, case, [NoiseRule("mia", "y")])
    env.svc.set_filters(ini, case, {"avanzate.mia": False, "avanzate.ini": True, "avanzate.Data": True})
    env.svc.set_filters(ini, None, {"avanzate.ini": False, "avanzate.mia": True})

    env.svc.set_noise_rules(ini, case, [NoiseRule("mia bis", "y")])     # renamed: its old choice goes
    assert case.review.filters == {"avanzate.ini": True, "avanzate.Data": True}
    env.svc.set_noise_rules(ini, None, [])                              # the initiative's rule is gone
    assert ini.filters == {}                                            # «mia» is no case rule any more
    loaded = env.svc.load(ini.id)
    assert loaded.filters == {} and next(c for c in loaded.cases if c.id == case.id).review.filters == \
        case.review.filters


def test_the_renamed_preset_keeps_its_choices(made):
    env, ini, case, _ = made
    assert "Numero di pagina nel testo" in [p.name for p in noise.PRESETS]
    raw = json.loads((ini.folder / "iniziativa.json").read_text(encoding="utf-8"))
    raw["filtri"] = {"avanzate.Numero di pagina": True}
    (ini.folder / "iniziativa.json").write_text(json.dumps(raw), encoding="utf-8")

    loaded = env.svc.load(ini.id)
    assert loaded.filters == {"avanzate.Numero di pagina nel testo": True} and loaded.load_notes == []
    panel = env.svc.filters(loaded, next(c for c in loaded.cases if c.id == case.id))
    assert panel.group("avanzate.Numero di pagina nel testo").attivo is True
    with pytest.raises(ValueError, match="nome già usato"):          # the old name stays reserved
        env.svc.set_noise_rules(loaded, None, [NoiseRule("Numero di pagina", "x")])


def test_set_filters_refuses_junk_and_changes_nothing(made):
    env, ini, case, _ = made
    env.svc.set_filters(ini, case, {"zona.header": True})
    for choices in ({"zona.boh": True}, {"zona.invisibile": False}, {"zona.header": "sì"}):
        for where in (case, None):
            with pytest.raises(ValueError):
                env.svc.set_filters(ini, where, choices)
    assert case.review.filters == {"zona.header": True} and ini.filters == {}


def test_the_asis_view_counts_with_the_case_switches(made):
    """M5 / D15: ``compare`` (the AS-IS view) sets aside the zones the case
    sets aside, like its TO-BE view — and follows a change of the switch."""
    env, ini, case, _ = made
    asis, result = env.svc.generate(ini, case, "asis")
    assert result.ok
    target = case.target()

    def brand():
        return next(d for d in env.svc.compare(target, asis).diffs if d.left_text == "Acme-Servizi")

    assert brand().klass == "zona"
    env.svc.set_filters(ini, None, {"zona.header": True})            # the initiative's default
    assert brand().klass == "arredo"
    env.svc.set_filters(ini, case, {"zona.header": False})           # the case's own choice wins
    assert brand().klass == "zona"


def test_the_asis_view_applies_the_switched_regex_rules_and_presets(made):
    """I1 (A5 re-review): ``compare`` (the AS-IS view) applies the regex rules
    and presets the case switches on, like the case comparison — and follows
    the switch."""
    env, ini, case, _ = made
    asis, result = env.svc.generate(ini, case, "asis")
    assert result.ok
    target = case.target()

    def klass(left: str) -> str:
        return next(d for d in env.svc.compare(target, asis).diffs if d.left_text == left).klass

    assert klass("CL123456") != "rumore" and klass("01/02/2026") != "rumore"
    env.svc.set_noise_rules(ini, case, [NoiseRule("codice", r"CL\d{6}", enabled=True)])
    assert klass("CL123456") == "rumore"                                # the case's rule, on by default
    env.svc.set_filters(ini, case, {"avanzate.codice": False})         # switched off: it counts again
    assert klass("CL123456") != "rumore"
    env.svc.set_filters(ini, None, {"avanzate.Data": True})            # a preset on for the initiative
    assert klass("01/02/2026") == "rumore"
    env.svc.set_filters(ini, case, {"avanzate.Data": False})           # the case's own choice wins
    assert klass("01/02/2026") != "rumore"
