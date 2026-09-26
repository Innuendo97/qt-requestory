"""The fake's tiny verdict engine (spec §5.1–5.3) and builders for canned diffs.

Used by ``FakeOfficinaApi.compare_case`` (``tests/fakes/fake_core.py``). It
imports only the CONTRACT (``officina.compare.model``, ``officina.model_review``),
never the real engine: the UI track drives every verdict, mark and
verification state with hand-made :class:`Diff` lists, and the real engine
(``compare/verdict.py``) is pinned against the same spec by its own tests.

Rules, in order, for each TO-BE↔target difference:

1. an anchor in ``review.not_variables`` turns a ``variabile`` diff into
   ``testo`` (anchor unchanged, so ``variable_again`` finds it), with the
   character spans of its two texts (R36);
2. ``variabile`` / ``rumore`` → no verdict;
3. a class the profile does not count (``COUNTING``) → ``tollerata``;
4. a tolerance with the same anchor AND the same normalised generated text →
   ``tollerata`` (with its note);
5. without an AS-IS comparison (two-way) → ``da_fare``; else same anchor in
   AS-IS↔target: same generated text → ``da_fare``, different → ``in_corso``
   (``previous_text`` = the AS-IS text); not in AS-IS → ``regressione``.

Then every counted AS-IS difference whose anchor is gone from TO-BE is a
``fatta``. Marks (ruling R7, PER MARK): each mark with ``mark.version <
version`` is verified and removed — gone → resolved; same text as marked →
keeps its verdict + ``unresolved`` (R31), remembered in ``review.unresolved``
as ``(anchor, mark.version, text)`` (R10: the version the mark was MADE in);
different text → ``in_corso`` with ``previous_text`` = the marked text. A
mark whose difference does not count now (tollerata / no verdict) is dormant
(R32): not verified, kept. The other marks stay: their difference is
``marked=True`` and keeps its verdict. A remembered "non risolta" lasts while
the difference is there with the same text (flagged while it counts).
Finally every ``Diff.id`` in ``judged`` is renumbered 1..n in judged order
(R9: ids are unique within ``CaseComparison.judged``; the ``Comparison``
objects keep their own numbering).

A TO-BE comparison without text on either side judges nothing (R49):
``judged`` empty, no verification, the review returned as it is, an empty
summary; an AS-IS comparison without text judges two-way.

Deliberate shortcuts (E5 must make the same choice on purpose, or the fake
changes with it): a marked difference that is gone is "resolved", one that
is now ``tollerata`` is dormant (R32); a stuck ``regressione`` stays
``regressione`` + ``unresolved`` (R31); ``fatta`` entries never carry marks
or flags.
"""
from __future__ import annotations

import dataclasses
import difflib

from qtrequestory.officina.compare.model import (
    COUNTING,
    Anchor,
    CaseSummary,
    Comparison,
    Diff,
    Judged,
    Klass,
    Op,
    Profile,
    Verification,
)
from qtrequestory.officina.model_review import NoiseRule, Review

__all__ = ["FAKE_PRESETS", "fake_comparison", "fake_diff", "fake_inactive", "fake_judge", "norm"]

_OPEN = ("da_fare", "in_corso", "regressione")

#: The fake's built-in noise presets (names as the spec lists them; all off).
FAKE_PRESETS: tuple[NoiseRule, ...] = (
    NoiseRule("Numero di pagina", r"Pag\. \d+ di \d+", False),
    NoiseRule("Data", r"\b\d{2}/\d{2}/\d{4}\b", False),
    NoiseRule("IBAN", r"\bIT\d{2}[A-Z]\d{10}[0-9A-Z]{12}\b", False),
    NoiseRule("Codice fiscale", r"\b[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]\b", False),
    NoiseRule("CAP", r"\b\d{5}\b", False),
    NoiseRule("Importo", r"\b\d{1,3}(?:\.\d{3})*,\d{2} ?(?:€|euro)", False),
    NoiseRule("Marcatore di firma", r"`sig,[^`]*`", False),
    NoiseRule("Parametri di tracciamento", r"[?&]utm_[a-z]+=[^&\s]*", False),
)

_ids = iter(range(1, 1 << 30))


def norm(text: str) -> str:
    """The fake's normalised generated text: whitespace collapsed."""
    return " ".join(text.split())


def fake_diff(op: Op, klass: Klass, target_text: str, generated: str, *, context: str = "",
              detail: str = "", diff_id: int | None = None, before: str = "",
              after: str = "") -> Diff:
    """A canned difference without word boxes. The anchor is
    ``(op, klass, context, norm(target_text))``: two diffs with the same
    target text are the "same" difference across versions — give them a
    ``context`` to tell them apart. Spans cover the whole text. ``before`` /
    ``after`` are the display context (R33: ``Diff.context_before`` /
    ``context_after``, the target words around the change; never in the anchor)."""
    return Diff(
        id=diff_id if diff_id is not None else next(_ids), op=op, klass=klass, left=(), right=(),
        left_text=target_text, right_text=generated,
        left_spans=((0, len(target_text)),) if target_text else (),
        right_spans=((0, len(generated)),) if generated else (),
        anchor=Anchor(op, klass, context, norm(target_text)), detail=detail,
        context_before=before, context_after=after,
    )


def fake_comparison(diffs, **fields) -> Comparison:
    """A ``Comparison`` of ``diffs`` (a list or a ready ``Comparison``);
    ``fields`` override the defaults (both sides with text, 1 page each,
    ``slots_found`` = the ``variabile`` diffs, no note, no noise hits)."""
    if isinstance(diffs, Comparison):
        return dataclasses.replace(diffs, **fields) if fields else diffs
    diffs = tuple(diffs)
    values = dict(diffs=diffs, left_has_text=True, right_has_text=True, left_pages=1, right_pages=1,
                  note="", slots_found=sum(d.klass == "variabile" for d in diffs), noise_hits=())
    values.update(fields)
    return Comparison(**values)


def fake_judge(tobe: Comparison, asis: Comparison | None, review: Review, profile: Profile,
               version: int, when: str) -> tuple[tuple[Judged, ...], CaseSummary, Verification | None, Review]:
    """``(judged, summary, verification, updated review)`` — pure, no I/O."""
    if not (tobe.left_has_text and tobe.right_has_text):  # R49: nothing judged, the review as it is
        empty = CaseSummary(version, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0.0,
                            asis is None or not (asis.left_has_text and asis.right_has_text), when)
        return (), empty, None, dataclasses.replace(
            review, tolerances=list(review.tolerances), not_variables=list(review.not_variables),
            marks=list(review.marks), unresolved=list(review.unresolved), noise_rules=list(review.noise_rules))
    if asis is not None and not (asis.left_has_text and asis.right_has_text):
        asis = None  # R49: an AS-IS without text judges two-way
    counted = COUNTING[profile]
    not_var = {a for a, _ in review.not_variables}

    def effective(d: Diff) -> Diff:
        if d.klass != "variabile" or d.anchor not in not_var:
            return d
        left, right = _spans(d.left_text, d.right_text)
        return dataclasses.replace(d, klass="testo", left_spans=left, right_spans=right)

    tobe_diffs = [effective(d) for d in tobe.diffs]
    asis_by = {d.anchor: d for d in (effective(d) for d in asis.diffs)} if asis is not None else {}
    judged: list[Judged] = []
    for d in tobe_diffs:
        judged.append(_judge_one(d, asis, asis_by, review, counted))
    present = {d.anchor for d in tobe_diffs}
    for d in asis_by.values():
        if d.anchor not in present and d.klass in counted:
            judged.append(Judged(d, "fatta"))

    unresolved = list(review.unresolved)
    verification = None
    due = [m for m in review.marks if m.version < version]
    marked = {m.anchor for m in review.marks if m.version >= version}
    dormant: list = []
    if due:
        judged, verification, unresolved, dormant = _verify(judged, len(tobe_diffs), due, unresolved, version)
    marks = [m for m in review.marks if m.version >= version or any(m is d for d in dormant)]
    judged = [dataclasses.replace(j, marked=True) if j.verdict in _OPEN and j.diff.anchor in marked else j
              for j in judged]
    # R31: a remembered "non risolta" lasts while the difference is there with the same text
    now = {j.diff.anchor: norm(j.diff.right_text) for j in judged[:len(tobe_diffs)]}
    unresolved = [(a, v, now[a]) for a, v, g in unresolved if a in now and g in ("", now[a])]
    flagged = {a for a, _, _ in unresolved}
    judged = [dataclasses.replace(j, unresolved=True) if j.verdict in _OPEN and j.diff.anchor in flagged else j
              for j in judged]
    # R9: ids unique within judged ("fatta" entries come from the AS-IS comparison)
    judged = [dataclasses.replace(j, diff=dataclasses.replace(j.diff, id=n)) for n, j in enumerate(judged, 1)]

    summary = _summary(judged, version, asis is None, when)
    updated = dataclasses.replace(review, marks=marks, unresolved=unresolved, summary=summary)
    return tuple(judged), summary, verification, updated


def _spans(left: str, right: str):
    """Changed character ranges (the engine's rule: difflib by character,
    each whole text past 2000 characters)."""
    if len(left) > 2000 or len(right) > 2000:
        return (((0, len(left)),) if left else ()), (((0, len(right)),) if right else ())
    a, b = [], []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, left, right, autojunk=False).get_opcodes():
        if tag != "equal":
            if i2 > i1:
                a.append((i1, i2))
            if j2 > j1:
                b.append((j1, j2))
    return tuple(a), tuple(b)


def fake_inactive(review: Review, judged) -> int:
    """R30: the review entries that do nothing in ``judged`` — a tolerance
    matching no (anchor, text), a not-variable matching no anchor, a mark
    whose difference is not "da verificare" (same rule as the engine's)."""
    anchors = {j.diff.anchor for j in judged}
    marked = {j.diff.anchor for j in judged if j.marked}
    texts = {(j.diff.anchor, norm(j.diff.right_text)) for j in judged}
    return (sum((t.anchor, t.generated) not in texts for t in review.tolerances)
            + sum(a not in anchors for a, _ in review.not_variables)
            + sum(m.anchor not in marked for m in review.marks))


def _judge_one(d: Diff, asis: Comparison | None, asis_by: dict, review: Review, counted) -> Judged:
    if d.klass in ("variabile", "rumore"):
        return Judged(d, None)
    if d.klass not in counted:
        return Judged(d, "tollerata")
    for t in review.tolerances:
        if t.anchor == d.anchor and t.generated == norm(d.right_text):
            return Judged(d, "tollerata", tolerated_note=t.note)
    if asis is None:
        return Judged(d, "da_fare")
    before = asis_by.get(d.anchor)
    if before is None:
        return Judged(d, "regressione")
    if norm(before.right_text) == norm(d.right_text):
        return Judged(d, "da_fare")
    return Judged(d, "in_corso", previous_text=before.right_text)


def _verify(judged: list[Judged], n_tobe: int, marks, unresolved, version: int):
    by_anchor = {j.diff.anchor: i for i, j in enumerate(judged[:n_tobe])}
    resolved = stuck = changed = 0
    dormant = []
    judged = list(judged)
    for mark in marks:
        i = by_anchor.get(mark.anchor)
        if i is None:
            resolved += 1
            continue
        j = judged[i]
        if j.verdict not in _OPEN:          # R32: dormant while it does not count
            dormant.append(mark)
        elif norm(j.diff.right_text) == mark.generated:   # R31: keeps its verdict + the flag
            stuck += 1
            unresolved = [e for e in unresolved if e[0] != mark.anchor] + [
                (mark.anchor, mark.version, mark.generated)]
        else:
            changed += 1
            judged[i] = dataclasses.replace(j, verdict="in_corso", previous_text=mark.generated)
    checked = len(marks) - len(dormant)
    verification = Verification(checked, resolved, stuck, changed, version) if checked else None
    return judged, verification, unresolved, dormant


def _summary(judged: list[Judged], version: int, two_way: bool, when: str) -> CaseSummary:
    verdicts = [j.verdict for j in judged]
    fatte, da_fare = verdicts.count("fatta"), verdicts.count("da_fare")
    in_corso, regressioni = verdicts.count("in_corso"), verdicts.count("regressione")
    total = fatte + da_fare + in_corso + regressioni
    return CaseSummary(
        version=version, fatte=fatte, da_fare=da_fare, in_corso=in_corso, regressioni=regressioni,
        da_verificare=sum(j.marked for j in judged), non_risolte=sum(j.unresolved for j in judged),
        tollerate=verdicts.count("tollerata"),
        variabili=sum(j.diff.klass == "variabile" for j in judged),
        rumore=sum(j.diff.klass == "rumore" for j in judged),
        avanzamento=fatte / total if total else 1.0, two_way=two_way, when=when,
    )
