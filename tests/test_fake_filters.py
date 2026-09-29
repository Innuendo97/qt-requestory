"""Phase 2.5 contract (T0 + fix round 1, rulings F3–F7):
``OfficinaApi.filters(ini, case)`` / ``set_filters`` / ``control_state`` on
the fake, its scripting API, and its fidelity to the real model (choices
are saved with the real ``Workspace``, so a reload through the real model
sees them). The shared panel scenario runs on the fake AND the real service
(A5 implemented it).

Synthetic data only (this repository is public).
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from qtrequestory.ui.contracts import (
    CONTROL_UNAVAILABLE_NOTE,
    FILTER_DEFAULTS,
    FILTER_IDS,
    INFORMATIONAL_IDS,
    ControlRecord,
    ControlState,
    CoreServices,
    FilterPanel,
    NoiseRule,
    OfficinaApi,
)
from tests.fakes.fake_core import build_fake_core, canned_pdf, fake_diff
from tests.fakes.fake_filters import fake_group, fake_occurrence
from tests.fakes.fake_verdict import FAKE_PRESETS

PRESET_ROWS = [f"avanzate.{p.name}" for p in FAKE_PRESETS]


@pytest.fixture
def fake(tmp_path: Path) -> CoreServices:
    return build_fake_core(tmp_path / "core")


def _real(fake):
    from qtrequestory.officina.service import OfficinaService

    return OfficinaService(lambda: fake.config.load(), control_runner=None)


def _case(fake, tmp_path: Path, api=None):
    api = api or fake.officina
    src = tmp_path / "p.json"
    src.write_text('{"documents": []}', encoding="utf-8")
    ini = api.create_initiative("Filtri")
    case = api.case_from_file(ini, src, "MOD_TEST_A")
    return api, ini, case


def _reloaded(api, ini, case):
    loaded = api.load(ini.id)
    return loaded, next(c for c in loaded.cases if c.id == case.id)


def test_the_new_methods_are_in_the_protocol_with_matching_signatures(fake):
    names = ("filters", "set_filters", "control_state")
    assert set(names) <= set(OfficinaApi.__protocol_attrs__)
    assert list(inspect.signature(OfficinaApi.filters).parameters) == ["self", "ini", "case"]  # F6
    for name in names:
        expected = inspect.signature(getattr(OfficinaApi, name)).parameters
        got = inspect.signature(getattr(fake.officina, name)).parameters
        assert [(p.name, p.kind, p.default) for p in got.values()] == \
               [(p.name, p.kind, p.default) for p in expected.values() if p.name != "self"], name


def test_the_real_service_answers_without_a_comparison(tmp_path: Path, fake):
    """A5: no stub left; before any comparison every row has 0 (never raises)."""
    real = _real(fake)
    api, ini, case = _case(fake, tmp_path, real)
    panel = real.filters(ini, case)
    assert [g.id for g in panel.groups][:len(FILTER_IDS)] == list(FILTER_IDS)
    assert all(g.n == 0 for g in panel.groups)
    assert real.control_state(case) == ControlState("assente")
    real.set_filters(ini, case, {"zona.header": True})
    assert real.filters(ini, case).group("zona.header").attivo is True


def test_default_panel_has_every_fixed_row_then_the_presets(fake, tmp_path: Path):
    api, ini, case = _case(fake, tmp_path)

    panel = api.filters(ini, case)

    assert isinstance(panel, FilterPanel)
    assert [g.id for g in panel.groups] == [*FILTER_IDS, *PRESET_ROWS]
    assert all(g.n == 0 and g.occorrenze == () for g in panel.groups)
    assert panel.choices() == {**{k: v for k, v in FILTER_DEFAULTS.items() if k not in INFORMATIONAL_IDS},
                               **dict.fromkeys(PRESET_ROWS, False)}
    invisible = panel.group("zona.invisibile")
    assert (invisible.interruttore, invisible.attivo) == (False, True)
    assert panel.controllo == ControlState("assente")
    assert len(panel.of("zone")) == 8


def test_advanced_rows_first_name_wins_and_filtri_owns_the_switch(fake, tmp_path: Path):
    api, ini, case = _case(fake, tmp_path)
    api.set_noise_rules(ini, None, [NoiseRule("iban", r"IT\d{2}", enabled=False)], None)
    api.set_noise_rules(ini, case, [NoiseRule("pratica", r"\d{6}")])
    case.review.noise_rules.append(NoiseRule("Data", "x", enabled=True))  # a hand-edited clash with a preset

    rows = api.filters(ini, case).of("avanzate")

    assert [(g.id, g.titolo, g.attivo) for g in rows][-2:] == [("avanzate.iban", "iban", False),
                                                               ("avanzate.pratica", "pratica", True)]
    assert [g.id for g in rows].count("avanzate.Data") == 1
    assert api.filters(ini, case).group("avanzate.Data").attivo is False  # the preset's default wins the name
    api.set_filters(ini, case, {"avanzate.iban": True, "avanzate.pratica": False})
    panel = api.filters(ini, case)
    assert (panel.group("avanzate.iban").attivo, panel.group("avanzate.pratica").attivo) == (True, False)


def test_scripted_rows_keep_counts_and_anchors_without_ids(fake, tmp_path: Path):
    api, ini, case = _case(fake, tmp_path)
    diff = fake_diff("cambiato", "zona", "Acme-Servizi S.p.A.", "Acme S.p.A.", zone="footer")
    occ = fake_occurrence("Acme-Servizi S.p.A.", pagine=(0, 1), anchors=(diff.anchor,), zona="footer")
    api.set_filter_groups(case.id, [fake_group("zona.footer", n=2, occorrenze=[occ]),
                                    fake_group("decidere.maiuscole", n=5)], nota="nota finta")

    panel = api.filters(ini, case)

    assert [(g.id, g.titolo, g.gruppo, g.n, g.attivo) for g in panel.groups] == [
        ("zona.footer", "Footer", "zone", 2, False), ("decidere.maiuscole", "Solo maiuscole", "decidere", 5, False)]
    assert panel.group("zona.footer").occorrenze == (occ,)
    assert panel.group("zona.footer").occorrenze[0].diff_ids == ()
    assert panel.nota == "nota finta"
    api.set_filters(ini, case, {"zona.footer": True})
    assert api.filters(ini, case).group("zona.footer").n == 2  # F7: n does not depend on the switch
    api.set_filter_groups(case.id, None)
    assert len(api.filters(ini, case).groups) == len(FILTER_IDS) + len(PRESET_ROWS)


def test_set_filters_case_then_initiative_precedence(fake, tmp_path: Path):
    """case choice → initiative default → built-in default; ``None`` removes a choice."""
    api, ini, case = _case(fake, tmp_path)

    api.set_filters(ini, None, {"zona.header": True, "zona.numero_pagina": False})
    api.set_filters(ini, case, {"zona.header": False, "decidere.maiuscole": True})
    panel = api.filters(ini, case)

    assert (panel.group("zona.header").attivo, panel.group("zona.header").predefinito) == (False, True)
    assert (panel.group("zona.numero_pagina").attivo, panel.group("zona.numero_pagina").predefinito) == (False, False)
    assert panel.group("decidere.maiuscole").attivo is True
    assert ini.filters == {"zona.header": True, "zona.numero_pagina": False}
    assert case.review.filters == {"zona.header": False, "decidere.maiuscole": True}
    loaded_ini, loaded_case = _reloaded(api, ini, case)  # saved with the real model
    assert loaded_ini.filters == ini.filters and loaded_case.review.filters == case.review.filters
    assert api.review_actions[-2:] == [("set_filters", None), ("set_filters", case.id)]

    api.set_filters(ini, case, {"zona.header": None})
    assert api.filters(ini, case).group("zona.header").attivo is True  # back to the initiative's
    assert case.review.filters == {"decidere.maiuscole": True}


def test_set_filters_prunes_the_keys_of_rules_that_are_gone(fake, tmp_path: Path):
    """F4: a renamed or removed rule's choice is ignored, then dropped at the next save."""
    api, ini, case = _case(fake, tmp_path)
    api.set_noise_rules(ini, case, [NoiseRule("pratica", r"\d{6}")])
    api.set_filters(ini, case, {"avanzate.pratica": False, "avanzate.Data": True})
    api.set_noise_rules(ini, case, [NoiseRule("pratica bis", r"\d{6}")])  # renamed

    assert api.filters(ini, case).group("avanzate.pratica") is None
    api.set_filters(ini, case, {"zona.header": True})
    assert case.review.filters == {"avanzate.Data": True, "zona.header": True}
    api.set_filters(ini, None, {"avanzate.fantasma": True})
    assert ini.filters == {}


@pytest.mark.parametrize("choices", [{"zona.boh": True}, {"zona.header": "sì"}, {"": True}, {"avanzate.": False},
                                     {"zona.invisibile": False}])
def test_set_filters_refuses_junk_and_changes_nothing(fake, tmp_path: Path, choices):
    api, ini, case = _case(fake, tmp_path)
    api.set_filters(ini, case, {"zona.header": True})

    for target in (case, None):
        with pytest.raises(ValueError):
            api.set_filters(ini, target, choices)
    assert case.review.filters == {"zona.header": True} and ini.filters == {}
    assert _reloaded(api, ini, case)[1].review.filters == {"zona.header": True}


def test_set_filters_on_an_unreadable_case_changes_nothing(fake, tmp_path: Path):
    api, ini, case = _case(fake, tmp_path)
    (case.folder / "caso.json").write_text("{rotto", encoding="utf-8")

    with pytest.raises(ValueError):
        api.set_filters(ini, case, {"zona.header": True})
    assert case.review.filters == {}


def test_preset_checkboxes_land_in_filtri_on_real_and_fake(fake, tmp_path: Path):
    """F4: the legacy ``presets`` argument (the 1.3.x noise page's checkboxes)
    is written into the initiative's filtri by BOTH services; there is no
    ``noise_presets`` view any more (A5)."""
    from qtrequestory.officina.compare import noise

    seen = []
    for name, api, presets in (("real", _real(fake), noise.PRESETS), ("fake", fake.officina, FAKE_PRESETS)):
        ini = api.create_initiative(f"Preset {name}")
        on = [presets[1].name]
        api.set_noise_rules(ini, None, [], on)
        loaded = api.load(ini.id)
        assert loaded.filters == ini.filters == {f"avanzate.{p.name}": p.name in on for p in presets}, name
        assert not hasattr(loaded, "noise_presets"), name
        api.set_noise_rules(ini, None, [], [])
        assert not any(api.load(ini.id).filters.values()), name
        seen.append(name)
    assert seen == ["real", "fake"]


def test_control_state_default_scripted_and_from_the_record(fake, tmp_path: Path):
    from qtrequestory.officina.model import Workspace

    api, ini, case = _case(fake, tmp_path)
    assert api.control_state(case) == ControlState("assente")

    api.set_control_state(case.id, ControlState("in_corso", quando="2026-09-28T10:00:00"))
    assert api.control_state(case).stato == "in_corso"
    assert api.filters(ini, case).controllo.stato == "in_corso"
    api.set_control_state(case.id, None)

    ws = Workspace(api.workspace_root())
    case.review.control = ControlRecord("ab" * 32, "non_disponibile", "2026-09-28T10:05:00")
    ws.save_review(case)  # what A5's background job writes
    assert api.control_state(case) == ControlState("non_disponibile", CONTROL_UNAVAILABLE_NOTE,
                                                   "2026-09-28T10:05:00")
    case.review.control = ControlRecord("ab" * 32, "pronta", "2026-09-28T10:06:00")
    ws.save_review(case)
    assert api.control_state(case) == ControlState("pronta", "", "2026-09-28T10:06:00")
    case.review.control = ControlRecord("ab" * 32, "in_corso", "2026-09-28T10:07:00")
    ws.save_review(case)  # a crash mid-run left it on disk
    assert api.control_state(case).stato == "assente"


def test_compare_case_carries_the_panel_with_the_judged_ids(fake, tmp_path: Path):
    api, ini, case = _case(fake, tmp_path)
    target = tmp_path / "atteso.pdf"
    target.write_bytes(canned_pdf("MOD_TEST atteso"))
    api.set_target(case, target)
    v1, result = api.generate(ini, case, "tobe")
    assert result.ok
    zona = fake_diff("cambiato", "zona", "Edizione 1", "Edizione 2", zone="spalla_sx", tipo="numeri")
    pagina = fake_diff("cambiato", "arredo", "Pag. 1 di 2", "Pag. 1 di 3", zone="numero_pagina", tipo="numeri")
    api.set_canned(case.id, 1, [zona, pagina])

    cc = api.compare_case(ini, case, v1)
    assert cc.filters is not None and all(g.n == 0 for g in cc.filters.groups)   # like the real service
    by = {j.diff.left_text: j for j in cc.judged}
    assert (by["Edizione 1"].diff.zone, by["Edizione 1"].diff.tipo, by["Edizione 1"].verdict) == (
        "spalla_sx", "numeri", "da_fare")
    assert by["Pag. 1 di 2"].verdict is None and cc.summary.arredo == 1 and cc.summary.tollerate == 0  # F3

    api.set_filter_groups(case.id, [
        fake_group("zona.numero_pagina", n=1, occorrenze=[fake_occurrence("Pag. 1 di 2", anchors=(pagina.anchor,))]),
        fake_group("zona.spalla_sx", n=1, occorrenze=[fake_occurrence("Edizione 1", anchors=(zona.anchor,))])])
    cc = api.compare_case(ini, case, v1)
    by = {j.diff.left_text: j for j in cc.judged}
    assert cc.filters.group("zona.numero_pagina").occorrenze[0].diff_ids == (by["Pag. 1 di 2"].diff.id,)
    assert cc.filters.group("zona.spalla_sx").occorrenze[0].diff_ids == (by["Edizione 1"].diff.id,)
    assert api.filters(ini, case).group("zona.spalla_sx").occorrenze[0].diff_ids == ()


def test_fake_diff_takes_the_new_fields():
    diff = fake_diff("cambiato", "arredo", "Pag. 1", "Pag. 2", zone="numero_pagina", tipo="numeri",
                     prova="segnaposto", nome="pagina")
    assert (diff.zone, diff.tipo, diff.prova, diff.nome) == ("numero_pagina", "numeri", "segnaposto", "pagina")
    plain = fake_diff("cambiato", "testo", "a", "b")
    assert (plain.zone, plain.tipo, plain.prova, plain.nome) == ("corpo", "altro", "", "")


# ------------------------------------------- M5: the same scenario, real and fake ---

@pytest.mark.parametrize("which", ["real", "fake"])
def test_panel_semantics_real_and_fake(fake, tmp_path: Path, which: str):
    """What A5 must make the real service do (the fake does it now): rows and
    order, defaults, precedence, informational row, rule ownership, pruning,
    anchors without ids, control state."""
    api = _real(fake) if which == "real" else fake.officina
    api, ini, case = _case(fake, tmp_path, api)
    api.set_noise_rules(ini, None, [NoiseRule("iban", r"IT\d{2}", enabled=False)], None)
    api.set_noise_rules(ini, case, [NoiseRule("pratica", r"\d{6}")])

    panel = api.filters(ini, case)
    ids = [g.id for g in panel.groups]
    assert ids[:len(FILTER_IDS)] == list(FILTER_IDS)
    assert ids[-2:] == ["avanzate.iban", "avanzate.pratica"] and len(ids) == len(set(ids))
    assert all(g.gruppo == "avanzate" for g in panel.groups[len(FILTER_IDS):])
    assert {g.id: g.attivo for g in panel.groups if g.id in FILTER_DEFAULTS} == FILTER_DEFAULTS
    assert panel.group("zona.invisibile").interruttore is False
    assert (panel.group("avanzate.iban").attivo, panel.group("avanzate.pratica").attivo) == (False, True)
    assert all(o.diff_ids == () for g in panel.groups for o in g.occorrenze)
    assert panel.controllo == api.control_state(case) == ControlState("assente")

    api.set_filters(ini, None, {"zona.header": True, "avanzate.iban": True})
    api.set_filters(ini, case, {"zona.header": False, "avanzate.pratica": False})
    panel = api.filters(ini, case)
    assert (panel.group("zona.header").attivo, panel.group("zona.header").predefinito) == (False, True)
    assert (panel.group("avanzate.iban").attivo, panel.group("avanzate.pratica").attivo) == (True, False)
    with pytest.raises(ValueError):
        api.set_filters(ini, case, {"zona.invisibile": False})

    api.set_noise_rules(ini, case, [])
    api.set_filters(ini, case, {"decidere.maiuscole": True})
    assert case.review.filters == {"zona.header": False, "decidere.maiuscole": True}
    assert _reloaded(api, ini, case)[1].review.filters == case.review.filters


def test_tollera_tutte_on_real_and_fake_gives_the_same_verdict(fake, tmp_path: Path):
    """M6 fidelity: the fake applies «Tollera tutte» like ``verdict.judge``
    (same verdict, same note, not a "fatta") and always carries the panel."""
    from qtrequestory.officina.compare.verdict import tipo_note

    api, ini, case = _case(fake, tmp_path)
    target = tmp_path / "atteso.pdf"
    target.write_bytes(canned_pdf("MOD_TEST atteso"))
    api.set_target(case, target)
    v1, result = api.generate(ini, case, "tobe")
    assert result.ok
    lower = fake_diff("cambiato", "testo", "Lorem", "LOREM", tipo="maiuscole")
    api.set_canned(case.id, 1, [lower])
    assert api.compare_case(ini, case, v1).judged[0].verdict == "da_fare"

    api.set_filters(ini, None, {"decidere.maiuscole": True})
    cc = api.compare_case(ini, case, v1)
    assert (cc.judged[0].verdict, cc.judged[0].tolerated_note) == ("tollerata", tipo_note("maiuscole"))
    assert cc.summary.tollerate == 1 and cc.filters is not None
