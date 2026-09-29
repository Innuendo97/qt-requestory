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

Phase 2.5 (spec §3.2–§3.5, §7) adds, all defaulted so every 1.3.x call site
and file keeps its meaning: the page zone of a word and of a difference
(``ZONES``, default ``"corpo"``), the difference type (``TIPI``, default
``"altro"``), the variable's proof and name, the classes ``zona`` (a
difference in a zone other than the body: it counts) and ``arredo`` (one in a
zone set aside, page number and watermark by default: it does not count),
and the optional filter panel on :class:`CaseComparison` (``filter_model``).

``from_json`` never raises: anything that is not exactly the expected shape
(a hand-edited file) gives ``None``, and the caller drops it with a note.

Stdlib only; no Qt, no pypdfium2.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, get_args

from qtrequestory.officina.compare.filter_model import FilterPanel

__all__ = [
    "ARREDO_ZONES", "COUNTING", "KLASSES", "NO_VERDICT", "OPS", "PROFILES", "PROVE", "TIPI", "VERDICTS", "ZONES",
    "Anchor", "Block", "CaseComparison", "CaseSummary", "Comparison", "Diff", "Judged", "Klass", "Op",
    "Profile", "Prova", "Tipo", "Verdict", "Verification", "Word", "Zone", "ZoneBox",
]

Op = Literal["mancante", "in_piu", "cambiato", "spostato", "sezione_assente", "sezione_in_piu", "pagine"]
Klass = Literal["testo", "composizione", "stile", "spaziatura", "variabile", "rumore", "link", "zona", "arredo"]
Verdict = Literal["fatta", "da_fare", "in_corso", "regressione", "tollerata"]
Profile = Literal["tollerante", "stretto", "solo_testo"]
#: The page zones (spec §3.2). ``corpo`` is the body (with the title it flows
#: across pages); the others are recognised on both sides together.
Zone = Literal["header", "titolo", "footer", "spalla_sx", "spalla_dx", "numero_pagina", "filigrana", "corpo"]
#: The difference types (spec §3.5, D8): orthogonal to the verdict; ALL count (D9).
Tipo = Literal["maiuscole", "punteggiatura", "spazi", "numeri", "parola", "frase", "sezione", "spostamento",
               "zona", "link", "altro"]
#: The position proof of a variable (spec §3.3; "listino" = a price-list dictionary match, F7); "" = none.
Prova = Literal["segnaposto", "buco", "cella", "sezione", "esecuzione", "listino", ""]

OPS: tuple[str, ...] = get_args(Op)
KLASSES: tuple[str, ...] = get_args(Klass)
VERDICTS: tuple[str, ...] = get_args(Verdict)
PROFILES: tuple[str, ...] = get_args(Profile)
ZONES: tuple[str, ...] = get_args(Zone)
TIPI: tuple[str, ...] = get_args(Tipo)
#: The proofs, without the empty "no proof".
PROVE: tuple[str, ...] = tuple(p for p in get_args(Prova) if p)
#: The zones whose differences are ``arredo`` (do not count) by default (D4):
#: the panel can turn them back on ("zona.numero_pagina", "zona.filigrana").
ARREDO_ZONES: frozenset[str] = frozenset({"numero_pagina", "filigrana"})

#: The classes each profile counts (spec §4.2 step 10); the others are
#: "tollerata" automatically. ``variabile`` and ``rumore`` never count: they
#: have no verdict at all. Phase 2.5: ``zona`` counts in every profile (D4:
#: header/footer text is compared: only TEXT changes in a zone are ``zona``;
#: style/spacing keep their class, and ``tipo`` stays separate from the zone);
#: ``arredo`` never counts and, like ``variabile`` and ``rumore``, has NO
#: verdict (ruling F3: never in "Tollerate"; its own ``CaseSummary.arredo``).
COUNTING: dict[Profile, frozenset[Klass]] = {
    "tollerante": frozenset({"testo", "composizione", "link", "zona"}),
    "stretto": frozenset({"testo", "composizione", "link", "stile", "spaziatura", "zona"}),
    "solo_testo": frozenset({"testo", "zona"}),
}
#: The classes judged without a verdict (``Judged.verdict`` None), in every profile.
NO_VERDICT: frozenset[str] = frozenset({"variabile", "rumore", "arredo"})


@dataclass(frozen=True)
class Word:
    """One word with its box: PDF points, origin at the TOP-left of the page
    as displayed. ``size`` (points) and ``bold`` are sampled per word; 0.0 /
    False when unknown (HTML, or an extractor that does not sample them).
    ``zone`` (``ZONES``) is set by the zone stage; ``"corpo"`` until then."""

    text: str
    page: int
    x0: float
    y0: float
    x1: float
    y1: float
    size: float = 0.0
    bold: bool = False
    zone: Zone = "corpo"


@dataclass(frozen=True)
class ZoneBox:
    """Where one zone lies on one page (phase 2.5, for the viewer's margin
    rails): the union of the zone's word boxes and of its graphics (logo,
    divider, watermark path), in the same space as :class:`Word` boxes. The
    zone stage (``compare.zones``) gives one per page and zone, never for
    ``corpo``."""

    page: int
    zone: Zone
    x0: float
    y0: float
    x1: float
    y1: float


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
    shows them around the change; they are never part of ``anchor``.

    Phase 2.5, never part of ``anchor`` either: ``zone`` (``ZONES``) where
    the difference is (target side; the generated side when the target has
    none); ``tipo`` (``TIPI``) what kind of change it is; for a
    ``variabile``, ``prova`` (``PROVE``: the proof that made it one) and
    ``nome`` (payload leaf, dictionary entry or the placeholder itself; ``""``
    when unknown). A difference whose proof the case switched off
    (``variabile.<proof>`` filter) keeps counting with its ``prova`` and
    ``nome`` still set, so the filter panel counts it (task A4,
    ``compare.variables``); ``prova`` is ``""`` on every other difference.

    ``empty_at`` (phase 2.5, task A3) is, for a difference with words on ONE
    side only (``mancante``, ``in_piu``, a section), where it sits on the
    OTHER side: ``(page, x0, y0, x1, y1)`` of the word right before the
    insertion point there (else right after it), for the viewer to align the
    empty side; None when both sides have words or the other side has none."""

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
    zone: Zone = "corpo"
    tipo: Tipo = "altro"
    prova: Prova = ""
    nome: str = ""
    empty_at: tuple[int, float, float, float, float] | None = None


@dataclass(frozen=True)
class Comparison:
    """One side-by-side comparison: the target against one version.
    ``noise_hits`` is ``(rule name, hits)`` per noise rule applied.
    ``left_zones`` / ``right_zones`` (phase 2.5) are each side's
    zone boxes (:class:`ZoneBox`), for the viewer's margin rails; empty when the zone
    stage did not run (HTML, no text)."""

    diffs: tuple[Diff, ...]
    left_has_text: bool
    right_has_text: bool
    left_pages: int
    right_pages: int
    note: str
    slots_found: int
    noise_hits: tuple[tuple[str, int], ...]
    left_zones: tuple[ZoneBox, ...] = ()
    right_zones: tuple[ZoneBox, ...] = ()

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
    its verdict; None for ``NO_VERDICT`` (variabile, rumore, arredo). ``marked`` is "da
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
    ``avanzamento`` is 0.0–1.0; ``when`` an ISO timestamp. ``arredo``
    (phase 2.5, F3) counts the verdict-less differences of the zones set
    aside (page number, watermark); 0 in a summary written before it."""

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
    arredo: int = 0

    def to_json(self) -> dict:
        raw: dict = {"versione": self.version}
        for key, attr in _SUMMARY_COUNTS:
            raw[key] = getattr(self, attr)
        raw["avanzamento"] = self.avanzamento
        raw["quando"] = self.when
        raw["due_vie"] = self.two_way
        raw["arredo"] = self.arredo
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
        arredo = raw.get("arredo", 0)
        if type(arredo) is not int or arredo < 0:
            return None
        return CaseSummary(**values, avanzamento=min(1.0, max(0.0, float(progress))), two_way=two_way, when=when,
                           arredo=arredo)


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
    many.

    ``filters`` (phase 2.5) is the "Filtri del confronto" panel computed with
    this comparison, or None when the service did not compute one (then
    ``OfficinaApi.filters`` gives it)."""

    version: int
    judged: tuple[Judged, ...]
    summary: CaseSummary
    tobe: Comparison
    asis: Comparison | None
    verification: Verification | None
    profile: Profile
    inactive: int = 0
    filters: FilterPanel | None = None
