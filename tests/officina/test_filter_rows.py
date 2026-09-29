"""``compare.filter_rows``: the "Filtri del confronto" panel computed from
one comparison (phase 2.5, spec §3.8; task A5). Pure; synthetic data only."""
from __future__ import annotations

from qtrequestory.officina.compare.filter_model import FILTER_IDS, ControlState
from qtrequestory.officina.compare.filter_rows import found, panel, rule_rows, switches, with_ids
from qtrequestory.officina.compare.model import Anchor, Diff, Judged, Word
from qtrequestory.officina.model_review import NoiseRule

PRESETS = [NoiseRule("Data", r"\d+/\d+", False), NoiseRule("CAP", r"\d{5}", False)]


def _diff(n: int, klass: str, left: str, right: str, *, zone: str = "corpo", tipo: str = "parola",
          prova: str = "", detail: str = "", op: str = "cambiato", page: int = 0) -> Diff:
    words = (Word(left or right, page, 10, 10, 20, 20, zone=zone),)
    return Diff(n, op, klass, words if left else (), () if left else words, left, right, (), (),
                Anchor(op, klass, f"ctx{n}", left), detail, zone=zone, tipo=tipo, prova=prova)


DIFFS = (
    _diff(1, "zona", "Acme-Servizi", "Acme", zone="footer", detail="uguale su 2 pagine"),
    _diff(2, "arredo", "1 di 2", "1 di 3", zone="numero_pagina", tipo="numeri"),
    _diff(3, "stile", "Titolo", "Titolo", zone="titolo", tipo="altro"),
    _diff(4, "variabile", "", "12", zone="footer", prova="buco", op="in_piu"),     # a variable: not the zone's
    _diff(5, "testo", "Lorem", "LOREM", tipo="maiuscole"),
    _diff(6, "rumore", "01/02", "03/04", tipo="numeri"),
    _diff(7, "testo", "lorem,", "lorem", tipo="punteggiatura", page=1),
    _diff(8, "variabile", "", "Beta", prova="esecuzione", op="in_piu"),
    _diff(9, "arredo", "Rosa", "ROSA", zone="filigrana", tipo="maiuscole"),        # no verdict: not to decide
)
INVISIBLE = [("target", [Word("MOD_TEST", 0, 10, 700, 50, 708), Word("CODICE", 0, 52, 700, 80, 708),
                         Word("0001", 1, 10, 700, 30, 708)]),
             ("TO-BE", [Word("nascosto", 0, 10, 10, 40, 18)])]


def test_every_row_counts_what_the_comparison_found():
    rows = found(DIFFS, INVISIBLE, {"Data": 3, "mia": 0})
    n = {k: v[0] for k, v in rows.items()}
    assert (n["zona.footer"], n["zona.numero_pagina"], n["zona.titolo"], n["zona.header"]) == (1, 1, 1, 0)
    assert n["zona.filigrana"] == 1 and n["zona.invisibile"] == 3
    assert (n["variabile.buco"], n["variabile.esecuzione"], n["variabile.cella"]) == (1, 1, 0)
    assert (n["decidere.maiuscole"], n["decidere.punteggiatura"]) == (1, 1)
    assert (n["avanzate.Data"], n["avanzate.mia"]) == (3, 0)
    footer = rows["zona.footer"][1][0]
    assert (footer.testo, footer.anchors, footer.zona, footer.dettaglio) == (
        "Acme-Servizi", (DIFFS[0].anchor,), "footer", "uguale su 2 pagine")
    assert rows["decidere.punteggiatura"][1][0].pagine == (1,)
    lines = rows["zona.invisibile"][1]
    assert [(o.testo, o.pagine, o.anchors, o.dettaglio) for o in lines] == [
        ("MOD_TEST CODICE", (0,), (), "target"), ("0001", (1,), (), "target"), ("nascosto", (0,), (), "TO-BE")]


def test_rules_first_name_wins():
    rules = rule_rows(PRESETS, [NoiseRule("mia", "x"), NoiseRule("Data", "y")], [NoiseRule("mia", "z")])
    assert [(r.name, r.pattern) for r in rules] == [("Data", r"\d+/\d+"), ("CAP", r"\d{5}"), ("mia", "x")]


def test_switches_follow_case_then_initiative_then_defaults():
    rules = rule_rows(PRESETS, [NoiseRule("mia", "x", enabled=True), NoiseRule("spenta", "y", enabled=False)])
    default = switches({}, {}, rules)
    assert default.aside == {"numero_pagina", "filigrana"}
    assert default.proofs == {"segnaposto", "buco", "cella", "sezione", "esecuzione", "listino"}
    assert default.tolerated == frozenset() and default.rules_on == {"mia"}
    chosen = switches({"zona.footer": True, "zona.filigrana": False, "variabile.buco": False,
                       "avanzate.mia": False},
                      {"zona.footer": False, "decidere.maiuscole": True, "avanzate.Data": True,
                       "avanzate.spenta": True}, rules)
    assert chosen.aside == {"numero_pagina", "footer"}
    assert "buco" not in chosen.proofs and chosen.tolerated == {"maiuscole"}
    assert chosen.rules_on == {"Data", "spenta"}


def test_the_panel_lays_out_every_row_with_the_switches_in_hand():
    rules = rule_rows(PRESETS, [NoiseRule("mia", "x")])
    rows = found(DIFFS, INVISIBLE, {"Data": 3})
    made = panel(rows, rules, {"zona.footer": True}, {"decidere.maiuscole": True}, ControlState("pronta"))
    assert [g.id for g in made.groups] == [*FILTER_IDS, "avanzate.Data", "avanzate.CAP", "avanzate.mia"]
    footer = made.group("zona.footer")
    assert (footer.attivo, footer.predefinito, footer.n) == (True, False, 1)
    assert made.group("decidere.maiuscole").attivo is True and made.group("avanzate.mia").attivo is True
    assert made.group("avanzate.Data").n == 3 and made.group("avanzate.CAP").n == 0
    assert made.group("zona.invisibile").interruttore is False
    assert made.controllo == ControlState("pronta")
    # F7: the counts never depend on the switches
    other = panel(rows, rules, {"zona.footer": False}, {}, ControlState("assente"))
    assert [g.n for g in other.groups] == [g.n for g in made.groups]
    assert all(o.diff_ids == () for g in made.groups for o in g.occorrenze)
    empty = panel({}, rules, {}, {}, ControlState("assente"))
    assert all(g.n == 0 and g.occorrenze == () for g in empty.groups)


def test_with_ids_indexes_the_judged_list_by_anchor():
    rules = rule_rows(PRESETS)
    made = panel(found(DIFFS), rules, {}, {}, ControlState("assente"))
    judged = [Judged(DIFFS[0], "da_fare"), Judged(DIFFS[4], "da_fare")]
    judged = [Judged(Diff(**{**j.diff.__dict__, "id": n}), j.verdict) for n, j in enumerate(judged, 10)]
    ids = with_ids(made, judged)
    assert ids.group("zona.footer").occorrenze[0].diff_ids == (10,)
    assert ids.group("decidere.maiuscole").occorrenze[0].diff_ids == (11,)
    assert ids.group("zona.numero_pagina").occorrenze[0].diff_ids == ()
