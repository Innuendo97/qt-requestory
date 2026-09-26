"""The comparison contract of Officina phase 2 (spec §4.1, §5).

Every stage of the engine (``officina/compare/*``), the verdict, the service
and the UI (through ``ui/contracts.py``) speak these types. They are frozen
dataclasses holding tuples, so a result can be shared between threads and
cached without anyone mutating it.

Two of them are stored in ``caso.json`` and therefore have a JSON form:

* :class:`Anchor` — the stable key of a difference, taken on the TARGET side
  (never a page or block index), which is what tolerances, marks and
  "non è una variabile" are matched on across regenerations;
* :class:`CaseSummary` — the counts the board shows without running the engine.

``from_json`` never raises: anything that is not exactly the expected shape
(a hand-edited file) gives ``None``, and the caller drops it with a note.

Stdlib only; no Qt, no pypdfium2.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, get_args

__all__ = [
    "COUNTING", "KLASSES", "OPS", "PROFILES", "VERDICTS",
    "Anchor", "Block", "CaseComparison", "CaseSummary", "Comparison", "Diff", "Judged", "Klass", "Op",
    "Profile", "Verdict", "Verification", "Word",
]

Op = Literal["mancante", "in_piu", "cambiato", "spostato", "sezione_assente", "sezione_in_piu", "pagine"]
Klass = Literal["testo", "composizione", "stile", "spaziatura", "variabile", "rumore", "link"]
Verdict = Literal["fatta", "da_fare", "in_corso", "regressione", "tollerata"]
Profile = Literal["tollerante", "stretto", "solo_testo"]

OPS: tuple[str, ...] = get_args(Op)
KLASSES: tuple[str, ...] = get_args(Klass)
VERDICTS: tuple[str, ...] = get_args(Verdict)
PROFILES: tuple[str, ...] = get_args(Profile)

#: The classes each profile counts (spec §4.2 step 10); the others are
#: "tollerata" automatically. ``variabile`` and ``rumore`` never count: they
#: have no verdict at all.
COUNTING: dict[Profile, frozenset[Klass]] = {
    "tollerante": frozenset({"testo", "composizione", "link"}),
    "stretto": frozenset({"testo", "composizione", "link", "stile", "spaziatura"}),
    "solo_testo": frozenset({"testo"}),
}


@dataclass(frozen=True)
class Word:
    """One word with its box: PDF points, origin at the TOP-left of the page
    as displayed. ``size`` (points) and ``bold`` are sampled per word; 0.0 /
    False when unknown (HTML, or an extractor that does not sample them)."""

    text: str
    page: int
    x0: float
    y0: float
    x1: float
    y1: float
    size: float = 0.0
    bold: bool = False


@dataclass(frozen=True)
class Block:
    """A unit of layout: a paragraph, one row of a form, or an HTML block
    element. ``dom_path`` and ``attrs`` (normalised ``href``/``src``/``alt``,
    in a stable order) are for HTML only."""

    id: int
    words: tuple[Word, ...]
    page: int
    kind: Literal["paragrafo", "riga_modulo", "html"]
    dom_path: str = ""
    attrs: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Anchor:
    """The stable key of a difference, on the TARGET side: operation, class,
    normalised target context and normalised target text. For ``in_piu`` the
    context is the pair of target words around the insertion point."""

    op: Op
    klass: Klass
    context: str
    target_text: str

    def to_json(self) -> dict:
        return {"op": self.op, "klass": self.klass, "context": self.context, "target_text": self.target_text}

    @staticmethod
    def from_json(raw: object) -> Anchor | None:
        """The anchor in ``raw``; None for anything else (never raises)."""
        if not isinstance(raw, dict):
            return None
        op, klass = raw.get("op"), raw.get("klass")
        context, target_text = raw.get("context"), raw.get("target_text")
        if op not in OPS or klass not in KLASSES:
            return None
        if not isinstance(context, str) or not isinstance(target_text, str):
            return None
        return Anchor(op, klass, context, target_text)


@dataclass(frozen=True)
class Diff:
    """One difference of a comparison. ``left`` is the TARGET side; the
    spans are the changed character ranges inside ``left_text`` /
    ``right_text``; ``detail`` is a short extra (e.g. "href: a → b").

    ``id`` is unique within one ``Comparison.diffs`` and, after judging,
    within ``CaseComparison.judged`` (ruling R9: renumbered 1..n in judged
    order, since the "fatta" entries come from the AS-IS comparison). The UI
    keys selection and actions on the judged id; the stable key across
    regenerations is ``anchor``.

    ``context_before`` / ``context_after`` (ruling R33) are DISPLAY text only:
    up to 5 target words right before / after the change (for an insertion,
    around the insertion point), original glyphs, single-spaced, on the same
    line or block when possible; "" when there is none. The list's snippet
    shows them around the change; they are never part of ``anchor``."""

    id: int
    op: Op
    klass: Klass
    left: tuple[Word, ...]
    right: tuple[Word, ...]
    left_text: str
    right_text: str
    left_spans: tuple[tuple[int, int], ...]
    right_spans: tuple[tuple[int, int], ...]
    anchor: Anchor
    detail: str = ""
    context_before: str = ""
    context_after: str = ""


@dataclass(frozen=True)
class Comparison:
    """One side-by-side comparison: the target against one version.
    ``noise_hits`` is ``(rule name, hits)`` per noise rule applied."""

    diffs: tuple[Diff, ...]
    left_has_text: bool
    right_has_text: bool
    left_pages: int
    right_pages: int
    note: str
    slots_found: int
    noise_hits: tuple[tuple[str, int], ...]

    def counting(self, profile: Profile = "tollerante") -> tuple[Diff, ...]:
        """The differences ``profile`` counts (``COUNTING``): without a
        verdict (the AS-IS view) these are the ones shown; variables, noise
        and the classes the profile tolerates are left out."""
        return tuple(d for d in self.diffs if d.klass in COUNTING[profile])

    def equal_for(self, profile: Profile = "tollerante") -> bool:
        """Both sides have text and nothing ``profile`` counts differs."""
        return self.left_has_text and self.right_has_text and not self.counting(profile)

    @property
    def equal(self) -> bool:
        """:meth:`equal_for` the default profile (Tollerante)."""
        return self.equal_for()


@dataclass(frozen=True)
class Judged:
    """A difference of TO-BE↔target (or a "fatta" from AS-IS↔target) with
    its verdict; None for ``variabile`` and ``rumore``. ``marked`` is "da
    verificare", ``unresolved`` the "non risolta" flag; ``previous_text`` is
    the earlier generated text shown for "in corso"."""

    diff: Diff
    verdict: Verdict | None
    marked: bool = False
    unresolved: bool = False
    tolerated_note: str = ""
    previous_text: str = ""


_SUMMARY_COUNTS = (
    ("fatte", "fatte"), ("da_fare", "da_fare"), ("in_corso", "in_corso"), ("regressioni", "regressioni"),
    ("da_verificare", "da_verificare"), ("non_risolte", "non_risolte"), ("tollerate", "tollerate"),
    ("variabili", "variabili"), ("rumore", "rumore"),
)


@dataclass(frozen=True)
class CaseSummary:
    """The counts of one case comparison (``caso.json`` → ``riepilogo``).
    ``avanzamento`` is 0.0–1.0; ``when`` an ISO timestamp."""

    version: int
    fatte: int
    da_fare: int
    in_corso: int
    regressioni: int
    da_verificare: int
    non_risolte: int
    tollerate: int
    variabili: int
    rumore: int
    avanzamento: float
    two_way: bool
    when: str

    def to_json(self) -> dict:
        raw: dict = {"versione": self.version}
        for key, attr in _SUMMARY_COUNTS:
            raw[key] = getattr(self, attr)
        raw["avanzamento"] = self.avanzamento
        raw["quando"] = self.when
        raw["due_vie"] = self.two_way
        return raw

    @staticmethod
    def from_json(raw: object) -> CaseSummary | None:
        """The summary in ``raw``; None for anything else (never raises): a
        count that is not a non-negative int, an ``avanzamento`` that is not a
        finite number (``json`` reads ``NaN`` / ``Infinity``). A finite
        ``avanzamento`` outside 0–1 is clamped. A missing ``due_vie`` reads as three-way."""
        if not isinstance(raw, dict):
            return None
        values: dict = {}
        for key, attr in (("versione", "version"), *_SUMMARY_COUNTS):
            value = raw.get(key)
            if type(value) is not int or value < 0:
                return None
            values[attr] = value
        progress, when, two_way = raw.get("avanzamento"), raw.get("quando"), raw.get("due_vie", False)
        if type(progress) not in (int, float) or not isinstance(when, str) or type(two_way) is not bool:
            return None
        if not math.isfinite(progress):
            return None
        return CaseSummary(**values, avanzamento=min(1.0, max(0.0, float(progress))), two_way=two_way, when=when)


@dataclass(frozen=True)
class Verification:
    """Outcome of checking the marks ("segnate") against a newer TO-BE:
    ``resolved`` gone, ``unresolved`` still there with the same generated
    text, ``changed`` still there with a different one."""

    checked: int
    resolved: int
    unresolved: int
    changed: int
    version: int


@dataclass(frozen=True)
class CaseComparison:
    """Everything the case view shows for one TO-BE: the judged differences,
    the summary, both comparisons (``asis`` None without an AS-IS: two-way),
    the verification of the marks when this version verified some, and the
    profile that was applied.

    ``inactive`` (ruling R30) counts the entries of the case's review that do
    nothing in ``judged`` (``verdict.inactive``): a tolerance whose anchor and
    generated text match no difference, a "non è una variabile" whose anchor
    matches none, a mark that is not "da verificare" — e.g. after the target
    was replaced. They stay in ``caso.json``; the list's "Tutte" tab says how
    many."""

    version: int
    judged: tuple[Judged, ...]
    summary: CaseSummary
    tobe: Comparison
    asis: Comparison | None
    verification: Verification | None
    profile: Profile
    inactive: int = 0
