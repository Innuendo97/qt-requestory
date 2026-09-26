"""Classes and profiles (spec §4.2 step 10).

Every difference gets ONE class, by the first rule that applies:

1. ``variabile`` — what a target slot swallowed;
2. ``composizione`` — layout, not wording: ``sezione_assente``,
   ``sezione_in_piu``, ``spostato``, ``pagine``;
3. ``rumore`` — text a noise rule covers: every key holds a placeholder and
   the keys are the same on both sides (``01/02/2026.`` against
   ``1 febbraio 2026.``: both ``NOISE Data .``) or one side is empty;
4. ``stile`` — the keys are equal, the size (±0.5 pt) or the weight is not;
5. ``spaziatura`` — the keys differ only by where spaces and line breaks
   fall (``forni tura`` against ``fornitura``);
6. ``testo`` — everything else.

``link`` (a critical HTML attribute) is given by the HTML stage, not here.

A profile decides which classes count (:data:`~qtrequestory.officina.compare.model.COUNTING`);
``variabile`` and ``rumore`` never do.

Pure; stdlib only, no Qt, no pypdfium2.
"""
from __future__ import annotations

from collections.abc import Sequence

from qtrequestory.officina.compare.model import COUNTING, Diff, Klass, Op, Profile
from qtrequestory.officina.compare.noise import NOISE

__all__ = ["COMPOSITION_OPS", "classify", "counts", "is_noise"]

#: Operations that are about layout: always ``composizione``.
COMPOSITION_OPS: frozenset[str] = frozenset({"sezione_assente", "sezione_in_piu", "spostato", "pagine"})


def classify(op: Op, left_keys: Sequence[str], right_keys: Sequence[str], *,
             slot: bool = False, style: bool = False) -> Klass:
    """The class of a difference (rules in the module doc)."""
    if slot:
        return "variabile"
    if op in COMPOSITION_OPS:
        return "composizione"
    if is_noise(left_keys, right_keys):
        return "rumore"
    if style:
        return "stile"
    if op == "cambiato" and left_keys and right_keys and "".join(left_keys) == "".join(right_keys):
        return "spaziatura"
    return "testo"


def is_noise(left_keys: Sequence[str], right_keys: Sequence[str]) -> bool:
    """Whether a noise rule covers the difference: every key present holds a
    placeholder, and the two sides are the same keys (placeholders over
    different texts) or one side is empty (a covered text on one side only).
    A placeholder that differs by what surrounds it (``Data`` against
    ``Data.``), or another rule's, is not noise: it stays ``testo``."""
    keys = [*left_keys, *right_keys]
    if not keys or not all(NOISE in key for key in keys):
        return False
    return not left_keys or not right_keys or list(left_keys) == list(right_keys)


def counts(diff: Diff, profile: Profile) -> bool:
    """Whether ``diff`` counts in ``profile``."""
    return diff.klass in COUNTING[profile]
