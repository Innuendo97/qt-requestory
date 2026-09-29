"""qtrequestory.officina.compare.filter_model: the "Filtri del confronto" panel
and the control-generation state (phase 2.5, spec §3.4, §3.8).

Synthetic data only (this repository is public).
"""
from __future__ import annotations

import dataclasses

import pytest

from qtrequestory.officina.compare.filter_model import (
    CONTROL_STATES,
    CONTROL_UNAVAILABLE_NOTE,
    FILTER_DEFAULTS,
    FILTER_GRUPPI,
    FILTER_IDS,
    FILTER_TITLES,
    INFORMATIONAL_IDS,
    RENAMED_RULES,
    ControlState,
    FilterGroup,
    FilterOccurrence,
    FilterPanel,
    advanced_filter_id,
    advanced_rule_name,
    apply_choices,
    control_sha,
    current_rule_name,
    filter_gruppo,
    filter_switch,
    is_filter_id,
    legacy_preset_choices,
    prune_choices,
)
from qtrequestory.officina.compare.model import Anchor

_ANCHOR = Anchor("cambiato", "arredo", "", "Pag. 1 di 2")


def test_the_fixed_ids_cover_the_spec_rows():
    assert FILTER_IDS == (
        "zona.header", "zona.titolo", "zona.footer", "zona.spalla_sx", "zona.spalla_dx",
        "zona.numero_pagina", "zona.filigrana", "zona.invisibile",
        "variabile.segnaposto", "variabile.buco", "variabile.cella", "variabile.sezione",
        "variabile.esecuzione", "variabile.listino",
        "decidere.maiuscole", "decidere.punteggiatura",
    )
    assert FILTER_GRUPPI == ("zone", "variabili", "decidere", "avanzate")
    assert set(FILTER_TITLES) == set(FILTER_IDS) and all(FILTER_TITLES.values())


def test_defaults_follow_d4_and_d9():
    """ON = set aside. Page number, watermark and invisible text are set aside by
    default (D4); every other zone counts; recognised variables are variables;
    case-only and punctuation-only differences count (D9)."""
    on = {i for i, v in FILTER_DEFAULTS.items() if v}
    assert on == {"zona.numero_pagina", "zona.filigrana", "zona.invisibile", "variabile.segnaposto",
                  "variabile.buco", "variabile.cella", "variabile.sezione", "variabile.esecuzione",
                  "variabile.listino"}
    assert set(FILTER_DEFAULTS) == set(FILTER_IDS)


@pytest.mark.parametrize(("filter_id", "ok"), [
    ("zona.header", True), ("variabile.listino", True), ("decidere.maiuscole", True),
    ("avanzate.Data", True), ("avanzate.la mia regola", True),
    ("zona.corpo", False), ("zona.boh", False), ("avanzate.", False), ("avanzate.   ", False),
    ("header", False), ("", False), (5, False), (None, False),
])
def test_is_filter_id(filter_id, ok):
    assert is_filter_id(filter_id) is ok


def test_advanced_ids_and_gruppo():
    assert advanced_filter_id("Data") == "avanzate.Data"
    assert filter_gruppo("zona.footer") == "zone"
    assert filter_gruppo("variabile.buco") == "variabili"
    assert filter_gruppo("decidere.punteggiatura") == "decidere"
    assert filter_gruppo("avanzate.Data") == "avanzate"
    with pytest.raises(ValueError):
        filter_gruppo("zona.boh")


def test_group_conta_is_the_inverse_of_the_switch():
    occ = FilterOccurrence("Pag. 1 di 2", (0, 1), (_ANCHOR,), zona="numero_pagina")
    group = FilterGroup("zona.numero_pagina", "Numero di pagina", "zone", True, True, 2, (occ,))

    assert group.conta is False and group.interruttore is True
    assert dataclasses.replace(group, attivo=False).conta is True
    assert group.occorrenze[0].anchors == (_ANCHOR,) and group.occorrenze[0].pagine == (0, 1)
    assert group.occorrenze[0].diff_ids == ()  # F5: only on CaseComparison.filters
    blank = FilterOccurrence("x")
    assert (blank.pagine, blank.anchors, blank.diff_ids, blank.zona) == ((), (), (), "corpo")


def test_panel_lookups_keep_the_order():
    rows = (FilterGroup("zona.header", "Header", "zone", False, False, 1),
            FilterGroup("variabile.buco", "Buchi", "variabili", True, True, 3),
            FilterGroup("zona.footer", "Footer", "zone", False, False, 0),
            FilterGroup("zona.invisibile", "Testo invisibile", "zone", True, True, 7, interruttore=False))
    panel = FilterPanel(rows, ControlState("pronta", quando="2026-09-28T10:00:00"))

    assert panel.group("variabile.buco") is rows[1]
    assert panel.group("zona.titolo") is None
    assert panel.of("zone") == (rows[0], rows[2], rows[3])
    assert panel.of("avanzate") == ()
    assert panel.choices() == {"zona.header": False, "variabile.buco": True, "zona.footer": False}
    assert panel.nota == ""


def test_control_state():
    assert CONTROL_STATES == ("assente", "in_corso", "pronta", "non_disponibile")
    state = ControlState("non_disponibile", CONTROL_UNAVAILABLE_NOTE, "2026-09-28T10:00:00")
    assert state.nota == "riconoscimento esteso non disponibile per questo caso"
    assert ControlState("assente") == ControlState("assente", "", "")


def test_invisible_text_is_informational():
    """F7: no switch; always set aside; a choice for it is refused."""
    assert INFORMATIONAL_IDS == frozenset({"zona.invisibile"})
    assert filter_switch("zona.invisibile", {"zona.invisibile": False}, {"zona.invisibile": False}) == (True, True)
    with pytest.raises(ValueError, match="informativo"):
        apply_choices({}, {"zona.invisibile": False})


def test_filter_switch_precedence():
    assert filter_switch("zona.header", {}, {}) == (False, False)
    assert filter_switch("zona.header", {}, {"zona.header": True}) == (True, True)
    assert filter_switch("zona.header", {"zona.header": False}, {"zona.header": True}) == (False, True)
    # F4: a rule's ``enabled`` is only the default; filtri owns the state
    assert filter_switch("avanzate.iban", {}, {}, {"iban": True}) == (True, True)
    assert filter_switch("avanzate.iban", {}, {"avanzate.iban": False}, {"iban": True}) == (False, False)
    assert filter_switch("avanzate.sparita", {}, {}, {}) == (False, False)


def test_apply_choices_merges_removes_and_refuses_atomically():
    assert apply_choices({"zona.header": True}, {"zona.header": None, "zona.footer": True}) == {"zona.footer": True}
    for junk in ({"zona.boh": True}, {"zona.header": 1}, {"zona.footer": True, "": False}):
        with pytest.raises(ValueError):
            apply_choices({"zona.header": True}, junk)


def test_prune_drops_only_stale_rule_keys():
    choices = {"zona.header": True, "avanzate.Data": True, "avanzate.vecchia": False, "avanzate.nuova": True}
    assert prune_choices(choices, ["Data", "nuova"]) == {"zona.header": True, "avanzate.Data": True,
                                                         "avanzate.nuova": True}
    assert advanced_rule_name("avanzate.Data") == "Data" and advanced_rule_name("zona.header") is None


def test_legacy_presets_map_to_their_current_names():
    assert legacy_preset_choices(["Data", "IBAN", " "]) == {"avanzate.Data": True, "avanzate.IBAN": True}
    assert RENAMED_RULES == {"Numero di pagina": "Numero di pagina nel testo"}  # U4 M6
    assert current_rule_name("Numero di pagina") == "Numero di pagina nel testo"
    assert current_rule_name("Data") == "Data"
    assert legacy_preset_choices(["Numero di pagina"]) == {"avanzate.Numero di pagina nel testo": True}


def test_the_transition_bridges_are_gone():
    from qtrequestory.officina.compare import filter_model

    assert not hasattr(filter_model, "presets_on") and not hasattr(filter_model, "with_presets")


def test_control_sha_is_document_then_canonical_payload():
    import hashlib

    doc = b"%PDF-1.4 finto"
    expected = hashlib.sha256(doc + '{"a":[1,2],"b":"è"}'.encode("utf-8")).hexdigest()
    assert control_sha(doc, {"b": "è", "a": [1, 2]}) == expected
    assert control_sha(doc, {"a": [1, 2], "b": "è"}) == expected  # key order does not matter
    assert control_sha(doc + b" ", {"a": [1, 2], "b": "è"}) != expected
    assert control_sha(doc, {"a": [1, 3], "b": "è"}) != expected
