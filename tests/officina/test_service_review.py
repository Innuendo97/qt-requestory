"""qtrequestory.officina.service_review: compare_case and the review actions
(spec §5, §6, task E7) on the REAL service.

Every document comes from the local ``FakeServer`` generator (never a real
endpoint) as a hand-built ``canned_pdf`` (no Qt), or is an HTML printed by
a stub converter — or by the real Edge when it is installed (``find_edge``).
Synthetic data only.
"""
from __future__ import annotations

import dataclasses
import json
import logging
from pathlib import Path

import pytest

from qtrequestory.officina import service_compare as service_mod
from qtrequestory.officina.compare import noise, noise_guard
from qtrequestory.officina.compare.edge import find_edge
from qtrequestory.officina.compare.model import CaseComparison, Judged
from qtrequestory.officina.model_review import NoiseRule
from qtrequestory.officina.service import CompareError, OfficinaService
from tests.fakes.fake_core import canned_pdf

from .test_generator import FakeServer
from .test_service import SECRET_MARKER, Env

TARGET = ["Contratto di prova per Acme-Servizi", "Il prezzo resta fisso per dodici mesi",
          "La carta sarà abilitata agli acquisti online", "Pagamento con addebito mensile anticipato",
          "Firma del cliente in calce al modulo"]


def doc(*changes: tuple[str, str]) -> bytes:
    """The target's text with ``(old, new)`` word replacements."""
    lines = list(TARGET)
    for old, new in changes:
        lines = [line.replace(old, new) for line in lines]
    return canned_pdf("\n".join(lines))


ASIS = doc(("dodici", "ventiquattro"), ("abilitata", "abilitato"), ("mensile", "trimestrale"))
V1 = doc(("dodici", "ventiquattro"), ("abilitata", "abilitato"))           # fixes "mensile"
V2 = doc(("abilitata", "abilitato"))                                        # fixes "dodici" too


@pytest.fixture
def server():
    s = FakeServer()
    s.canned.body = ASIS
    yield s
    s.close()


@pytest.fixture
def env(tmp_path: Path, server: FakeServer) -> Env:
    return Env(tmp_path, server)


def _case(env: Env, tmp_path: Path, target: bytes = None, name: str = "atteso.pdf"):
    ini, case = env.case()
    src = tmp_path / name
    src.write_bytes(target if target is not None else canned_pdf("\n".join(TARGET)))
    env.svc.set_target(case, src)
    return ini, case


def _generate(env: Env, server: FakeServer, ini, case, kind: str, body: bytes):
    server.canned.status, server.canned.body = 200, body
    version, result = env.svc.generate(ini, case, kind)
    assert result.ok, result.reason
    return version


def _by_target(cc: CaseComparison) -> dict[str, Judged]:
    return {j.diff.left_text: j for j in cc.judged}


def _reload(env: Env, ini, case):
    fresh = env.svc.load(ini.id)
    return fresh, next(c for c in fresh.cases if c.id == case.id)


def _counts_agree(cc: CaseComparison) -> None:
    s, verdicts = cc.summary, [j.verdict for j in cc.judged]
    assert (s.fatte, s.da_fare, s.in_corso, s.regressioni, s.tollerate) == (
        verdicts.count("fatta"), verdicts.count("da_fare"), verdicts.count("in_corso"),
        verdicts.count("regressione"), verdicts.count("tollerata"))
    assert s.da_verificare == sum(j.marked for j in cc.judged)
    assert s.non_risolte == sum(j.unresolved for j in cc.judged)
    assert [j.diff.id for j in cc.judged] == list(range(1, len(cc.judged) + 1))


# ------------------------------------------------------------- the full cycle ---

def test_full_cycle_asis_v1_mark_two_v2_fixes_one(env: Env, server: FakeServer, tmp_path: Path):
    ini, case = _case(env, tmp_path)
    _generate(env, server, ini, case, "asis", ASIS)
    v1 = _generate(env, server, ini, case, "tobe", V1)

    first = env.svc.compare_case(ini, case, v1)
    by = _by_target(first)
    assert {t: j.verdict for t, j in by.items()} == {"dodici": "da_fare", "abilitata": "da_fare",
                                                     "mensile": "fatta"}
    assert first.asis is not None and not first.summary.two_way and first.version == 1
    assert first.profile == "tollerante" and first.verification is None and first.inactive == 0
    _counts_agree(first)

    env.svc.mark_done(case, by["dodici"], 1)
    env.svc.mark_done(case, by["abilitata"], 1)
    same = env.svc.compare_case(ini, case, v1)
    assert all(j.marked for j in same.judged if j.verdict == "da_fare") and same.verification is None
    assert same.summary.da_verificare == 2 and same.summary.da_fare == 2  # a promise, not a result

    v2 = _generate(env, server, ini, case, "tobe", V2)
    cc = env.svc.compare_case(ini, case, v2)

    assert cc.verification is not None
    assert (cc.verification.checked, cc.verification.resolved, cc.verification.unresolved,
            cc.verification.changed, cc.verification.version) == (2, 1, 1, 0, 2)
    by = _by_target(cc)
    assert by["abilitata"].verdict == "da_fare" and by["abilitata"].unresolved and not by["abilitata"].marked
    assert by["dodici"].verdict == "fatta" and by["mensile"].verdict == "fatta"
    _counts_agree(cc)
    _, reloaded = _reload(env, ini, case)
    assert reloaded.review.marks == []
    assert [(a.target_text, made_in, text) for a, made_in, text in reloaded.review.unresolved] == [
        ("abilitata", 1, "abilitato")]
    assert reloaded.review.summary == cc.summary
    raw = json.loads((case.folder / "caso.json").read_text(encoding="utf-8"))
    assert raw["riepilogo"]["versione"] == 2 and raw["riepilogo"]["non_risolte"] == 1
    # the flag is remembered on the next comparison of the same version
    assert _by_target(env.svc.compare_case(ini, case, v2))["abilitata"].unresolved


def test_failed_generation_keeps_marks(env: Env, server: FakeServer, tmp_path: Path):
    """Review Focus 3: a regeneration that fails (HTTP 502) while differences
    are "segnate" leaves every mark untouched; only a NEWER TO-BE verifies."""
    ini, case = _case(env, tmp_path)
    _generate(env, server, ini, case, "asis", ASIS)
    v1 = _generate(env, server, ini, case, "tobe", V1)
    for judged in env.svc.compare_case(ini, case, v1).judged:
        if judged.verdict == "da_fare":
            env.svc.mark_done(case, judged, 1)
    marks_before = list(case.review.marks)
    on_disk = json.loads((case.folder / "caso.json").read_text(encoding="utf-8"))["segnate"]
    assert len(marks_before) == 2

    server.canned.status, server.canned.body = 502, b"<html>Bad Gateway</html>"
    version, result = env.svc.generate(ini, case, "tobe")
    assert version is None and not result.ok

    _, reloaded = _reload(env, ini, case)
    assert reloaded.review.marks == marks_before
    assert json.loads((case.folder / "caso.json").read_text(encoding="utf-8"))["segnate"] == on_disk
    assert reloaded.latest_tobe().number == 1
    again = env.svc.compare_case(ini, case, reloaded.latest_tobe())
    assert again.verification is None
    assert sum(j.marked for j in again.judged) == 2
    assert _reload(env, ini, case)[1].review.marks == marks_before


def _marked_v1(env: Env, server: FakeServer, tmp_path: Path):
    """AS-IS, v1 compared (summary saved), its two "da fare" marked in v1."""
    ini, case = _case(env, tmp_path)
    _generate(env, server, ini, case, "asis", ASIS)
    v1 = _generate(env, server, ini, case, "tobe", V1)
    for judged in env.svc.compare_case(ini, case, v1).judged:
        if judged.verdict == "da_fare":
            env.svc.mark_done(case, judged, 1)
    assert len(case.review.marks) == 2
    return ini, case


def _unchanged_by_a_textless_compare(env: Env, ini, case, version, side: str) -> None:
    raw_before = json.loads((case.folder / "caso.json").read_text(encoding="utf-8"))
    cc = env.svc.compare_case(ini, case, version)
    assert cc.judged == () and cc.verification is None, "R49: no verdict without text"
    assert f"{side} non ha testo estraibile" in cc.tobe.note
    raw = json.loads((case.folder / "caso.json").read_text(encoding="utf-8"))
    for key in ("segnate", "non_risolte", "riepilogo"):
        assert raw.get(key) == raw_before.get(key), f"{key} changed by a comparison without text"
    assert raw["riepilogo"]["versione"] == 1
    assert len(_reload(env, ini, case)[1].review.marks) == 2


def test_tobe_without_text_keeps_marks_and_is_not_progress(env: Env, server: FakeServer, tmp_path: Path):
    """Final review C1 / R49: a blank regeneration is not "everything fixed"."""
    ini, case = _marked_v1(env, server, tmp_path)
    blank = _generate(env, server, ini, case, "tobe", canned_pdf(""))
    _unchanged_by_a_textless_compare(env, ini, case, blank, "TO-BE")


def test_target_without_text_keeps_marks(env: Env, server: FakeServer, tmp_path: Path):
    ini, case = _marked_v1(env, server, tmp_path)
    v2 = _generate(env, server, ini, case, "tobe", V2)
    case.target().path.write_bytes(canned_pdf(""))  # e.g. a scan put in place by hand
    _unchanged_by_a_textless_compare(env, ini, case, v2, "target")


def test_asis_without_text_is_two_way(env: Env, server: FakeServer, tmp_path: Path):
    """R49: an AS-IS without text judges two-way (never "regressione" for all)."""
    ini, case = _case(env, tmp_path)
    _generate(env, server, ini, case, "asis", canned_pdf(""))
    v1 = _generate(env, server, ini, case, "tobe", V1)
    cc = env.svc.compare_case(ini, case, v1)
    assert cc.summary.two_way and cc.asis is not None
    assert {j.verdict for j in cc.judged} == {"da_fare"} and len(cc.judged) == 2
    assert "l'AS-IS non ha testo estraibile" in cc.tobe.note
    _counts_agree(cc)


def test_comparing_an_older_version_never_overwrites_the_summary(env: Env, server: FakeServer,
                                                                   tmp_path: Path):
    """R48: only the latest TO-BE's comparison is the case's summary."""
    ini, case = _case(env, tmp_path)
    _generate(env, server, ini, case, "asis", ASIS)
    v1 = _generate(env, server, ini, case, "tobe", V1)
    v2 = _generate(env, server, ini, case, "tobe", V2)
    latest = env.svc.compare_case(ini, case, v2)
    older = env.svc.compare_case(ini, case, v1)
    assert older.summary.version == 1 and older.judged  # judged and shown all the same
    assert _reload(env, ini, case)[1].review.summary == latest.summary
    raw = json.loads((case.folder / "caso.json").read_text(encoding="utf-8"))
    assert raw["riepilogo"]["versione"] == 2


def test_comparing_an_older_version_keeps_the_non_risolte_of_the_latest(env: Env, server: FakeServer,
                                                                         tmp_path: Path):
    """R48 (final review M3): an older version does not prune "non risolte"."""
    ini, case = _case(env, tmp_path)
    _generate(env, server, ini, case, "asis", ASIS)
    v1 = _generate(env, server, ini, case, "tobe", doc())           # nothing left to do
    v2 = _generate(env, server, ini, case, "tobe", V2)
    for judged in env.svc.compare_case(ini, case, v2).judged:
        if judged.verdict == "da_fare":
            env.svc.mark_done(case, judged, 2)
    v3 = _generate(env, server, ini, case, "tobe", V2)             # the mark did not help
    env.svc.compare_case(ini, case, v3)
    before = _reload(env, ini, case)[1].review.unresolved
    assert len(before) == 1
    env.svc.compare_case(ini, case, v1)                             # the difference is not there
    assert _reload(env, ini, case)[1].review.unresolved == before


def test_tolerate_survives_a_reload_from_disk(env: Env, server: FakeServer, tmp_path: Path):
    ini, case = _case(env, tmp_path)
    v1 = _generate(env, server, ini, case, "tobe", V1)
    judged = _by_target(env.svc.compare_case(ini, case, v1))["abilitata"]
    assert judged.verdict == "da_fare" and env.svc.compare_case(ini, case, v1).summary.two_way

    env.svc.tolerate(case, judged, "va bene così")
    env.svc.tolerate(case, judged, "va bene così")               # idempotent

    ini2, case2 = _reload(env, ini, case)
    assert len(case2.review.tolerances) == 1
    assert case2.review.tolerances[0].generated == "abilitato"
    again = _by_target(env.svc.compare_case(ini2, case2, case2.latest_tobe()))["abilitata"]
    assert again.verdict == "tollerata" and again.tolerated_note == "va bene così"
    env.svc.untolerate(case2, again)
    assert _by_target(env.svc.compare_case(ini2, case2, case2.latest_tobe()))["abilitata"].verdict == "da_fare"


def test_a_profile_change_rejudges_without_regenerating(env: Env, server: FakeServer, tmp_path: Path,
                                                        monkeypatch: pytest.MonkeyPatch):
    split = doc(("abilitata", "abili tata"))                        # spaziatura: counts only in stretto
    ini, case = _case(env, tmp_path)
    v1 = _generate(env, server, ini, case, "tobe", split)
    judged = env.svc.compare_case(ini, case, v1).judged
    assert [(j.diff.klass, j.verdict) for j in judged] == [("spaziatura", "tollerata")]
    requests = len(server.requests)
    calls: list[Path] = []
    real_extract = service_mod.extract
    monkeypatch.setattr(service_mod, "extract", lambda path: calls.append(path) or real_extract(path))

    env.svc.set_profile(ini, case, "stretto")
    strict = env.svc.compare_case(ini, case, v1)
    assert strict.profile == "stretto" and [j.verdict for j in strict.judged] == ["da_fare"]
    env.svc.set_profile(ini, case, None)                               # "come l'iniziativa"
    env.svc.set_profile(ini, None, "solo_testo")
    assert env.svc.compare_case(ini, case, v1).profile == "solo_testo"
    assert len(server.requests) == requests and calls == []            # nothing regenerated or re-extracted
    ini2, case2 = _reload(env, ini, case)
    assert ini2.profile == "solo_testo" and case2.review.profile is None
    with pytest.raises(ValueError):
        env.svc.set_profile(ini, case, "boh")                          # type: ignore[arg-type]


# ------------------------------------------------------------------ actions ---

def test_marks_not_variables_and_resets_persist_and_are_idempotent(env: Env, server: FakeServer, tmp_path: Path):
    ini, case = _case(env, tmp_path)
    v1 = _generate(env, server, ini, case, "tobe", V1)
    first, second = [j for j in env.svc.compare_case(ini, case, v1).judged if j.verdict == "da_fare"]

    env.svc.mark_done(case, first, 1)
    env.svc.mark_done(case, first, 1)
    env.svc.mark_done(case, second, 1)
    assert [m.anchor for m in _reload(env, ini, case)[1].review.marks] == [first.diff.anchor, second.diff.anchor]
    env.svc.unmark(case, first)
    assert [m.anchor for m in _reload(env, ini, case)[1].review.marks] == [second.diff.anchor]
    env.svc.unmark_all(case)
    assert _reload(env, ini, case)[1].review.marks == []

    env.svc.not_variable(case, first)
    env.svc.not_variable(case, first)
    assert [a for a, _ in _reload(env, ini, case)[1].review.not_variables] == [first.diff.anchor]
    env.svc.variable_again(case, first)
    assert _reload(env, ini, case)[1].review.not_variables == []
    env.svc.not_variable(case, first)
    env.svc.tolerate(case, second)
    env.svc.reset_tolerances(case)
    reloaded = _reload(env, ini, case)[1]
    assert reloaded.review.tolerances == [] and reloaded.review.not_variables == []


def test_a_stale_case_object_never_wipes_a_newer_tolerance(env: Env, server: FakeServer, tmp_path: Path):
    """Two Case objects of one case (the board and the case view): an action
    saved through one survives a comparison run on the other (merge-write)."""
    ini, case = _case(env, tmp_path)
    v1 = _generate(env, server, ini, case, "tobe", V1)
    stale = _reload(env, ini, case)[1]
    judged = _by_target(env.svc.compare_case(ini, case, v1))["abilitata"]
    env.svc.tolerate(case, judged, "nota")

    cc = env.svc.compare_case(ini, stale, stale.latest_tobe())

    assert [t.note for t in _reload(env, ini, case)[1].review.tolerances] == ["nota"]
    assert [t.note for t in stale.review.tolerances] == ["nota"]
    # judged with the review on disk, not the stale one (fix round 1, Important 2)
    assert _by_target(cc)["abilitata"].verdict == "tollerata" and cc.summary.tollerate == 1
    assert _reload(env, ini, case)[1].review.summary.tollerate == 1


def test_compare_case_leaves_the_result_on_the_case_it_was_given(env: Env, server: FakeServer, tmp_path: Path):
    """The UI reads case.review.marks after a verification (banner counts)."""
    ini, case = _case(env, tmp_path)
    v1 = _generate(env, server, ini, case, "tobe", V1)
    other = _reload(env, ini, case)[1]
    env.svc.mark_done(other, _by_target(env.svc.compare_case(ini, other, v1))["dodici"], 1)
    v2 = _generate(env, server, ini, case, "tobe", V2)
    cc = env.svc.compare_case(ini, case, v2)          # ``case`` never saw the mark
    assert cc.verification is not None and cc.verification.resolved == 1
    assert case.review.marks == [] and case.review.summary == cc.summary


def test_a_new_target_clears_marks_and_summary_but_keeps_tolerances(env: Env, server: FakeServer,
                                                                    tmp_path: Path):
    """R29: replacing the target is a new start for marks, not for tolerances."""
    ini, case = _case(env, tmp_path)
    v1 = _generate(env, server, ini, case, "tobe", V1)
    first, second = [j for j in env.svc.compare_case(ini, case, v1).judged if j.verdict == "da_fare"]
    env.svc.mark_done(case, first, 1)
    env.svc.tolerate(case, second, "nota")
    history = len(case.history)

    src = tmp_path / "nuovo.pdf"
    src.write_bytes(doc(("Firma", "Sottoscrizione")))
    env.svc.set_target(case, src)

    reloaded = _reload(env, ini, case)[1]
    assert reloaded.review.marks == [] and reloaded.review.unresolved == [] and reloaded.review.summary is None
    assert [t.note for t in reloaded.review.tolerances] == ["nota"]
    assert case.review.marks == [] and len(case.history) == history + 1
    assert "target" in case.history[-1]["note"]
    cc = env.svc.compare_case(ini, case, v1)
    assert _by_target(cc)["abilitata"].verdict == "tollerata" and cc.inactive == 0  # its anchor still matches


def test_inactive_counts_entries_that_no_longer_match(env: Env, server: FakeServer, tmp_path: Path):
    ini, case = _case(env, tmp_path)
    v1 = _generate(env, server, ini, case, "tobe", V1)
    judged = _by_target(env.svc.compare_case(ini, case, v1))["abilitata"]
    env.svc.tolerate(case, judged)
    v2 = _generate(env, server, ini, case, "tobe", doc(("dodici", "ventiquattro"), ("abilitata", "abilitate")))
    cc = env.svc.compare_case(ini, case, v2)
    assert _by_target(cc)["abilitata"].verdict == "da_fare" and cc.inactive == 1


def test_compare_case_errors_are_compare_errors(env: Env, server: FakeServer, tmp_path: Path):
    ini, case = env.case()
    v1 = _generate(env, server, ini, case, "tobe", V1)
    with pytest.raises(CompareError, match="target"):
        env.svc.compare_case(ini, case, v1)
    src = tmp_path / "atteso.pdf"
    src.write_bytes(doc())
    env.svc.set_target(case, src)
    v1.path.unlink()
    with pytest.raises(CompareError, match="non esiste più"):
        env.svc.compare_case(ini, case, v1)


def test_an_unreadable_caso_json_refuses_actions_and_changes_nothing(env: Env, server: FakeServer,
                                                                    tmp_path: Path):
    ini, case = _case(env, tmp_path)
    v1 = _generate(env, server, ini, case, "tobe", V1)
    judged = env.svc.compare_case(ini, case, v1).judged[0]
    (case.folder / "caso.json").write_text("{rotto", encoding="utf-8")
    with pytest.raises(ValueError):
        env.svc.tolerate(case, judged)
    assert case.review.tolerances == []
    with pytest.raises(CompareError, match="caso.json"):
        env.svc.compare_case(ini, case, v1)


# -------------------------------------------------------------------- noise ---

def test_noise_presets_are_the_engine_presets_all_off(env: Env):
    presets = env.svc.noise_presets()
    assert [p.name for p in presets] == [p.name for p in noise.PRESETS]
    assert not any(p.enabled for p in presets)
    presets[0].enabled = True
    assert not env.svc.noise_presets()[0].enabled, "fresh copies"


def test_count_noise_hits_with_a_bad_and_a_slow_regex(env: Env, server: FakeServer, tmp_path: Path,
                                                    monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(noise_guard, "BUDGET_S", 1.0)
    ini, case = _case(env, tmp_path, canned_pdf("Emesso il 01/02/2026\n" + "a" * 40 + " fine"))
    _generate(env, server, ini, case, "tobe", canned_pdf("Emesso il 03/04/2026\naltro testo"))
    data = dataclasses.replace(noise.PRESETS[1], enabled=False)
    rules = [NoiseRule("anno", r"20\d\d"), NoiseRule("rotta", "("), NoiseRule("lenta", "(a|a)*b"), data]

    hits = env.svc.count_noise_hits(case, rules)

    assert hits["anno"] == 2 and hits["Data"] == 2
    assert isinstance(hits["rotta"], str) and hits["rotta"].startswith("espressione non valida")
    assert hits["lenta"] == noise.SLOW
    with pytest.raises(ValueError, match="stesso nome"):
        env.svc.count_noise_hits(case, [NoiseRule("a", "x"), NoiseRule("a", "y")])


def test_noise_rules_of_initiative_and_case_apply_and_a_slow_one_is_dropped(env: Env, server: FakeServer,
                                                                          tmp_path: Path,
                                                                          monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(noise_guard, "BUDGET_S", 1.0)
    ini, case = _case(env, tmp_path, canned_pdf("Emesso il 01/02/2026 a Roma\n" + "a" * 40))
    v1 = _generate(env, server, ini, case, "tobe", canned_pdf("Emesso il 3 marzo 2026 a Milano\n" + "a" * 40))
    assert [j.diff.klass for j in env.svc.compare_case(ini, case, v1).judged] == ["testo", "testo"]

    env.svc.set_noise_rules(ini, None, [], ["Data"])                                   # a preset
    env.svc.set_noise_rules(ini, case, [NoiseRule("citta", r"Roma|Milano"), NoiseRule("lenta", "(a|a)*b")])
    cc = env.svc.compare_case(ini, case, v1)

    assert [j.diff.klass for j in cc.judged] == ["rumore", "rumore"]
    assert "regola «lenta» ignorata: " + noise.SLOW in cc.tobe.note
    assert dict(cc.tobe.noise_hits) == {"Data": 2, "citta": 2}
    ini2, case2 = _reload(env, ini, case)
    assert ini2.noise_presets == ["Data"] and [r.name for r in case2.review.noise_rules] == ["citta", "lenta"]
    with pytest.raises(ValueError, match="stesso nome"):
        env.svc.set_noise_rules(ini, case, [NoiseRule("a", "x"), NoiseRule("a", "y")])


# ---------------------------------------------------------------- the cache ---

def test_extractions_are_cached_on_disk_across_services(env: Env, server: FakeServer, tmp_path: Path,
                                                        monkeypatch: pytest.MonkeyPatch):
    ini, case = _case(env, tmp_path)
    v1 = _generate(env, server, ini, case, "tobe", V1)
    env.svc.compare_case(ini, case, v1)
    assert len(list((case.folder / "cache").glob("extract-*.json"))) == 2
    calls: list[Path] = []
    monkeypatch.setattr(service_mod, "extract", lambda path: calls.append(path))

    fresh = OfficinaService(lambda: env.config, html_to_pdf=env._html_to_pdf)
    cc = fresh.compare_case(ini, case, v1)

    assert calls == [] and len(cc.judged) == 2
    for stored in (case.folder / "cache").glob("extract-*.json"):
        stored.write_text("{rotto", encoding="utf-8")                      # corrupt: silently redone
    monkeypatch.undo()
    assert len(OfficinaService(lambda: env.config).compare_case(ini, case, v1).judged) == 2


# --------------------------------------------------------------------- HTML ---

T_HTML = ('<html><body><table><tr><td><p>Gentile cliente, la sua offerta è attiva.</p>'
          '<p>Leggi le <a href="https://example.invalid/condizioni?id=1">condizioni</a> del servizio.</p>'
          '<p>Il prezzo resta fisso per dodici mesi.</p></td></tr></table>'
          + '<p>Questa email di prova è inviata da Acme-Servizi a un indirizzo example.invalid.</p>' * 8
          + '</body></html>')
G_HTML = (T_HTML.replace("dodici", "ventiquattro")
          .replace("condizioni?id=1", "condizioni?id=2"))


def _html_case(env: Env, server: FakeServer, tmp_path: Path, svc: OfficinaService | None = None):
    ini, case = _case(env, tmp_path, T_HTML.encode(), name="email.html")
    version = _generate(env, server, ini, case, "tobe", G_HTML.encode())
    return ini, case, version


def test_html_case_is_compared_through_its_dom_even_without_a_print(env: Env, server: FakeServer, tmp_path: Path):
    ini, case, v1 = _html_case(env, server, tmp_path)
    svc = OfficinaService(lambda: env.config, html_to_pdf=lambda *a, **k: "Edge non trovato")

    cc = svc.compare_case(ini, case, v1)

    got = [(j.diff.klass, j.diff.left_text, j.diff.right_text) for j in cc.judged]
    assert ("testo", "dodici", "ventiquattro") in got
    assert ("link", "https://example.invalid/condizioni?id=1", "https://example.invalid/condizioni?id=2") in got
    assert all(j.verdict == "da_fare" for j in cc.judged)
    assert "stampa" in cc.tobe.note and "Edge non trovato" in cc.tobe.note
    target_src, version_src = svc.dom_view(case, v1)
    assert "<p>" in target_src and "dodici" in target_src and "ventiquattro" in version_src


def test_dom_view_of_a_pdf_case_is_empty(env: Env, server: FakeServer, tmp_path: Path):
    ini, case = _case(env, tmp_path)
    v1 = _generate(env, server, ini, case, "tobe", V1)
    assert env.svc.dom_view(case, v1) == ("", "")


@pytest.mark.skipif(find_edge() is None, reason="Microsoft Edge non installato")
def test_html_case_end_to_end_with_edge(env: Env, server: FakeServer, tmp_path: Path):
    ini, case, v1 = _html_case(env, server, tmp_path)
    svc = OfficinaService(lambda: env.config)          # the real Edge print

    cc = svc.compare_case(ini, case, v1)

    changed = next(j for j in cc.judged if j.diff.klass == "testo")
    assert (changed.diff.left_text, changed.diff.right_text) == ("dodici", "ventiquattro")
    for word in (*changed.diff.left, *changed.diff.right):
        assert word.x1 > word.x0 > 0 and word.y1 > word.y0 > 0, "boxed from the Edge print"
    assert any(j.diff.klass == "link" for j in cc.judged)
    assert "stampa" not in cc.tobe.note


# ---------------------------------------------------------------------- log ---

def test_nothing_of_the_payload_or_the_documents_is_logged(env: Env, server: FakeServer, tmp_path: Path,
                                                         caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.DEBUG)
    ini, case = _case(env, tmp_path)
    _generate(env, server, ini, case, "asis", ASIS)
    v1 = _generate(env, server, ini, case, "tobe", V1)
    judged = env.svc.compare_case(ini, case, v1).judged
    env.svc.tolerate(case, judged[0], "nota riservata")
    env.svc.mark_done(case, judged[1], 1)
    env.svc.set_noise_rules(ini, case, [NoiseRule("regola", "segreta")])
    env.svc.count_noise_hits(case, [NoiseRule("regola", "segreta")])
    env.svc.compare_case(ini, case, v1)

    text = caplog.text
    assert "confronto del caso" in text, "compare_case logs its counts"
    for secret in (SECRET_MARKER, "abilitata", "abilitato", "ventiquattro", "Acme-Servizi", "nota riservata",
                   "segreta"):
        assert secret not in text, secret


def test_a_comparison_without_a_print_is_not_reused_once_the_print_works(env: Env, server: FakeServer,
                                                                        tmp_path: Path):
    """Fix round 1, Important 1: the boxless comparison made while Edge failed
    is never served again; its note stays while the print keeps failing."""
    import re as _re

    ini, case, v1 = _html_case(env, server, tmp_path)
    state = {"fail": True}

    def printer(html: Path, out_pdf: Path, timeout_s: int = 60) -> str | None:
        if state["fail"]:
            return "Edge non trovato"
        text = _re.sub(r"<[^>]+>", " ", Path(html).read_text(encoding="utf-8"))
        out_pdf.write_bytes(canned_pdf(" ".join(text.split())))
        return None

    svc = OfficinaService(lambda: env.config, html_to_pdf=printer)
    for _ in range(2):
        cc = svc.compare_case(ini, case, v1)
        assert "stampa dell'HTML non disponibile" in cc.tobe.note
    state["fail"] = False
    cc = svc.compare_case(ini, case, v1)
    assert "stampa" not in cc.tobe.note
    changed = next(j for j in cc.judged if j.diff.klass == "testo")
    assert all(w.x1 > w.x0 > 0 for w in (*changed.diff.left, *changed.diff.right)), "boxed from the new print"


def test_no_custom_regex_is_compiled_or_matched_in_the_application(env: Env, server: FakeServer, tmp_path: Path,
                                                                  monkeypatch: pytest.MonkeyPatch):
    """R46 (final review I2): the user's rules are matched in the guard's
    child on the pipeline's own texts; here they are never even compiled."""
    from .test_noise_guard import _refuse_compiling

    custom = r"Roma|Milano(?#R46)"
    ini, case = _case(env, tmp_path, canned_pdf("Emesso a Roma\nFirma"))
    _generate(env, server, ini, case, "asis", canned_pdf("Emesso a Torino\nFirma"))
    v1 = _generate(env, server, ini, case, "tobe", canned_pdf("Emesso a Milano\nFirma"))
    env.svc.set_noise_rules(ini, case, [NoiseRule("citta", custom), NoiseRule("rotta", "((?#R46)")])
    _refuse_compiling(monkeypatch, custom, "((?#R46)")
    cc = env.svc.compare_case(ini, case, v1)
    assert [(j.diff.klass, j.verdict) for j in cc.judged] == [("rumore", None), ("testo", "fatta")],         "applied through the child's spans (Torino is not a match: the AS-IS difference is fixed)"
    assert dict(cc.tobe.noise_hits) == {"citta": 2}
    assert "regola «rotta» ignorata: espressione non valida" in cc.tobe.note
    counts = env.svc.count_noise_hits(case, [NoiseRule("citta", custom), NoiseRule("rotta", "((?#R46)")])
    assert counts["citta"] == 2 and counts["rotta"].startswith("espressione non valida")


def test_a_rule_too_slow_on_the_pipelines_text_is_dropped_from_both_pairs(env: Env, server: FakeServer,
                                                                          tmp_path: Path,
                                                                          monkeypatch: pytest.MonkeyPatch):
    """R46: the budget is measured on what the noise stage really matches, and
    a rule dropped on one pair is dropped on the other too (one verdict)."""
    monkeypatch.setattr(noise_guard, "BUDGET_S", 1.0)
    ini, case = _case(env, tmp_path, canned_pdf("Emesso a Roma\n" + "a" * 40))
    _generate(env, server, ini, case, "asis", canned_pdf("Emesso a Torino\n" + "a" * 40))
    v1 = _generate(env, server, ini, case, "tobe", canned_pdf("Emesso a Milano\n" + "a" * 40))
    env.svc.set_noise_rules(ini, case, [NoiseRule("lenta", "(a|a)*b"), NoiseRule("citta", r"Roma|Milano|Torino")])
    cc = env.svc.compare_case(ini, case, v1)
    for comparison in (cc.tobe, cc.asis):
        assert "regola «lenta» ignorata: " + noise.SLOW in comparison.note
        assert dict(comparison.noise_hits) == {"citta": 2}


def test_custom_rules_are_dropped_with_a_note_when_no_child_can_check_them(env: Env, server: FakeServer,
                                                                          tmp_path: Path,
                                                                          monkeypatch: pytest.MonkeyPatch):
    """R37: a failed spawn never runs the user's regex in the application."""
    def broken(*_a, **_k):
        raise OSError("spawn non disponibile")

    monkeypatch.setattr(noise_guard, "_start", broken)
    ini, case = _case(env, tmp_path, canned_pdf("Emesso a Roma"))
    v1 = _generate(env, server, ini, case, "tobe", canned_pdf("Emesso a Milano"))
    env.svc.set_noise_rules(ini, case, [NoiseRule("citta", r"Roma|Milano")])
    cc = env.svc.compare_case(ini, case, v1)
    assert [j.diff.klass for j in cc.judged] == ["testo"], "the rule was not applied"
    assert noise_guard.UNAVAILABLE + " («citta»)" in cc.tobe.note
    assert env.svc.count_noise_hits(case, [NoiseRule("citta", r"Roma|Milano")]) == {
        "citta": noise_guard.UNAVAILABLE}
    monkeypatch.undo()
    assert [j.diff.klass for j in env.svc.compare_case(ini, case, v1).judged] == ["rumore"], "retried later"


def test_count_noise_hits_reuses_its_counts_for_the_same_texts(env: Env, server: FakeServer, tmp_path: Path,
                                                             monkeypatch: pytest.MonkeyPatch):
    ini, case = _case(env, tmp_path, canned_pdf("anno 2026 e 2027"))
    _generate(env, server, ini, case, "tobe", canned_pdf("anno 2028"))
    rules = [NoiseRule("anno", r"20\d\d")]
    assert env.svc.count_noise_hits(case, rules) == {"anno": 3}
    monkeypatch.setattr(noise_guard, "_start", lambda *a, **k: pytest.fail("a second child"))
    assert env.svc.count_noise_hits(case, rules) == {"anno": 3}


def test_spans_found_without_a_print_are_not_reused_once_the_print_works():
    """Re-review N1 (R50): the spans index the pre-noise text, which depends on
    the words' boxes; a print that fails once and then works must give what a
    fresh service gives (2 hits, in_piu '12345'), never cambiato 'Roma' -> '12345 Roma'."""
    from qtrequestory.officina.compare.extract_html import extract_html
    from qtrequestory.officina.service_case import CaseInput, CaseInputsMixin

    def blocks(html: str, boxed: bool):
        out = []
        for b, block in enumerate(extract_html(html.encode())[0]):
            if boxed:  # the first word alone on the block's first printed line
                block = dataclasses.replace(block, words=tuple(
                    dataclasses.replace(w, page=0, x0=10 + 40 * max(k - 1, 0), x1=40 + 40 * max(k - 1, 0),
                                        y0=100 * b + (0 if k == 0 else 20), y1=100 * b + (10 if k == 0 else 30))
                    for k, w in enumerate(block.words)))
            out.append(block)
        return tuple(out)

    class Service(CaseInputsMixin):
        pass

    left = "<p>Riferimento: Roma sede legale e amministrativa</p><p>Coda comune del documento</p>"
    right = "<p>Riferimento: 12345 Roma sede legale e amministrativa</p><p>Coda comune del documento</p>"
    rule = [NoiseRule("citta", "Roma")]

    def run(svc, boxed: bool, error: str):
        target = CaseInput("T", blocks(left, boxed), print_error=error)
        other = CaseInput("G", blocks(right, boxed), print_error=error)
        made = svc._compare_pairs(target, [("TO-BE", other)], [], rule, False)[0][0]
        return dict(made.noise_hits), [(d.op, d.klass, d.left_text, d.right_text) for d in made.diffs]

    svc = Service()
    svc._init_case()
    run(svc, False, "stampa non riuscita")
    again = run(svc, True, "")
    fresh = Service()
    fresh._init_case()
    assert again == run(fresh, True, "")
    assert again[0] == {"citta": 2} and again[1] == [("in_piu", "testo", "", "12345")]
