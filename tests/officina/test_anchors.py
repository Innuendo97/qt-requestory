"""qtrequestory.officina.compare.anchors: occurrence numbering (ruling R19)."""
from __future__ import annotations

from qtrequestory.officina.compare.anchors import disambiguate
from qtrequestory.officina.compare.model import Anchor


def _a(context: str, text: str = "x") -> Anchor:
    return Anchor("cambiato", "testo", context, text)


def test_repeats_get_numbered_in_order():
    assert disambiguate([_a("c"), _a("d"), _a("c"), _a("c")]) == [_a("c"), _a("d"), _a("c #2"), _a("c #3")]


def test_an_empty_context_gets_just_the_number():
    assert disambiguate([_a(""), _a("")]) == [_a(""), _a("#2")]


def test_distinct_anchors_are_unchanged_and_only_identical_ones_count():
    anchors = [_a("c", "x"), _a("c", "y"), Anchor("mancante", "testo", "c", "x")]
    assert disambiguate(anchors) == anchors
    assert disambiguate([]) == []


def test_a_produced_anchor_never_collides_with_a_literal_one():
    """R35: "c #2" already in the list (a context that really ends in "#2") —
    the repeat of "c" must not become a second "c #2"."""
    out = disambiguate([_a("c"), _a("c"), _a("c #2")])
    assert len(set(out)) == 3
    assert out[0] == _a("c") and out[2] == _a("c #2")
    assert out[1].context.startswith("c #")


def test_every_output_is_unique_even_for_adversarial_lists():
    anchors = [_a("c"), _a("c #2"), _a("c"), _a("c #3"), _a("c"), _a("c #2")]
    out = disambiguate(anchors)
    assert len(set(out)) == len(out) == len(anchors)
    assert disambiguate(out) == out  # already unique: unchanged
