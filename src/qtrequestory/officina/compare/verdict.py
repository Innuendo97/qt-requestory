"""Three-way verdict, tolerances, marks and summary (spec §5.1–5.3).

:func:`judge` combines TO-BE↔target and AS-IS↔target (``None``: two-way) with
the case's :class:`~qtrequestory.officina.model_review.Review`. Differences of
the two comparisons are matched by ``anchor`` equality (anchors are already
disambiguated by occurrence, ruling R19). For each TO-BE difference, the
first rule that applies:

1. an anchor in ``review.not_variables`` turns a ``variabile`` diff into
   ``testo`` (anchor unchanged, so "variabile di nuovo" still finds it; ruling
   R36), with the character spans of its two texts;
2. ``variabile`` / ``rumore`` → no verdict (``None``);
3. a class the profile does not count (``classify.counts``) → ``tollerata``;
4. a tolerance with the same anchor AND the same normalised generated text
   (:func:`generated_text`) → ``tollerata``, with its note;
5. two-way → ``da_fare``; else the same anchor in AS-IS↔target: same
   generated text → ``da_fare``, different → ``in_corso`` (``previous_text``
   = the AS-IS text); not in AS-IS → ``regressione``.

Then every counting AS-IS difference whose anchor is absent from TO-BE is a
``fatta``: the entry carries the AS-IS diff itself (its left side = the
target words, for the target-side underline).

Marks (ruling R7, PER MARK): a mark with ``mark.version < version`` is
verified and removed from the returned review — its difference gone →
resolved; still there with the same generated text → "non risolta": the
difference KEEPS its verdict (R31: a stuck ``regressione`` stays
``regressione``, an ``in_corso`` stays ``in_corso`` with the AS-IS
``previous_text``) and gets the ``unresolved`` flag, remembered in
``review.unresolved`` as ``(anchor, mark.version, generated text)`` (R10);
different text → ``in_corso`` with ``previous_text`` = the marked text. A mark
of the compared version (or a later one) is not verified: its open difference
is ``marked=True`` and keeps its verdict. A mark whose difference does not
count right now (``tollerata`` by profile or by hand, or no verdict) is
DORMANT (R32): not verified, not ``marked``, not in the verification, kept in
the review — live again when the difference counts again. A remembered "non
risolta" lasts while its difference is present with the same anchor and
generated text (flagged only while it counts) and is dropped when the
difference disappears or its generated text changes.

Anchors are unique within each comparison (the pipeline disambiguates them
by occurrence, ruling R19). Should a comparison still hold duplicates (it
would match the wrong partner), they are not an error (ruling R35: no
assertions on data): a warning is logged and that comparison's anchors go
through ``anchors.disambiguate`` again before judging.

A side without text (ruling R49): when the TO-BE comparison lacks text on
either side (the TO-BE or the target), nothing is judged — ``judged`` is
empty, no mark is verified, and the returned review is the given one
unchanged (its summary included); the summary returned is an empty one
(all zeros, ``avanzamento`` 0.0) that the caller does not save. When only
the AS-IS comparison lacks text, the verdict is two-way, as without an AS-IS.

Finally ``Diff.id`` is renumbered 1..n in judged order (R9). The summary
counts a marked difference both in its verdict and in ``da_verificare``
(R15); ``avanzamento`` = fatte / (fatte + da fare + in corso + regressioni),
1.0 when nothing counts.

The fake's verdict engine (``tests/fakes/fake_verdict.py``) implements the
same rules for the UI track; ``tests/officina/test_verdict.py`` pins that
both agree on scripted comparisons.

Pure: no I/O, no clock (the summary's ``when`` is passed in); stdlib only.
"""
from __future__ import annotations

import dataclasses
import logging
from collections.abc import Sequence

from qtrequestory.officina.compare.anchors import disambiguate
from qtrequestory.officina.compare.classify import counts
from qtrequestory.officina.compare.model import (
    Anchor,
    CaseSummary,
    Comparison,
    Diff,
    Judged,
    Profile,
    Verification,
)
from qtrequestory.officina.compare.normalise import normalise_token
from qtrequestory.officina.compare.worddiff import char_spans
from qtrequestory.officina.model_review import Mark, Review

__all__ = ["OPEN", "generated_text", "has_text", "inactive", "judge"]

log = logging.getLogger(__name__)

#: The verdicts a difference can be "segnata fatta" from.
OPEN: frozenset[str] = frozenset({"da_fare", "in_corso", "regressione"})


def generated_text(diff: Diff) -> str:
    """The normalised generated text of ``diff``: what tolerances and marks
    store (``generato``) and are matched on. Each word of ``right_text``
    through :func:`normalise_token`, joined by one space."""
    return " ".join(key for key in (normalise_token(w) for w in diff.right_text.split()) if key)


def judge(tobe: Comparison, asis: Comparison | None, review: Review, profile: Profile, version: int, *,
          when: str = "") -> tuple[tuple[Judged, ...], CaseSummary, Verification | None, Review]:
    """``(judged, summary, verification, updated review)`` for TO-BE
    ``version`` (see module doc). ``verification`` is None when no mark was
    verified (none due, or all dormant). ``review`` is not modified; the returned one has the verified marks
    removed, ``unresolved`` updated and ``summary`` set. A side without
    text: see the module doc (R49)."""
    if not has_text(tobe):
        empty = CaseSummary(version, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0.0, asis is None or not has_text(asis), when)
        return (), empty, None, _copy(review)
    if asis is not None and not has_text(asis):
        asis = None
    not_var = {a for a, _ in review.not_variables}

    def effective(d: Diff) -> Diff:
        if d.klass != "variabile" or d.anchor not in not_var:
            return d
        spans = char_spans(d.left_text, d.right_text)  # a counting testo diff shows its changed characters
        return dataclasses.replace(d, klass="testo", left_spans=spans[0], right_spans=spans[1])

    tobe_diffs = [effective(d) for d in tobe.diffs]
    asis_diffs = [effective(d) for d in asis.diffs] if asis is not None else []
    tobe_diffs, asis_diffs = _made_unique(tobe_diffs, "TO-BE"), _made_unique(asis_diffs, "AS-IS")
    asis_by = {d.anchor: d for d in asis_diffs}
    judged = [_judge_one(d, asis is None, asis_by, review, profile) for d in tobe_diffs]
    at = {d.anchor: i for i, d in enumerate(tobe_diffs)}          # TO-BE entries only, never "fatta"
    judged += [Judged(d, "fatta") for d in asis_diffs if d.anchor not in at and counts(d, profile)]

    due = [m for m in review.marks if m.version < version]
    unresolved = list(review.unresolved)
    verification: Verification | None = None
    dormant: list[Mark] = []
    if due:
        judged, verification, unresolved, dormant = _verify(judged, at, due, unresolved, version)
    kept = {id(m) for m in dormant}
    marks = [m for m in review.marks if m.version >= version or id(m) in kept]
    marked = {m.anchor for m in review.marks if m.version >= version}
    judged = [dataclasses.replace(j, marked=True) if j.verdict in OPEN and j.diff.anchor in marked else j
              for j in judged]
    # R31: "non risolta" lasts while the difference is there with the text it was verified with
    unresolved = _still_unresolved(unresolved, judged, at)
    flagged = {a for a, _, _ in unresolved}
    judged = [dataclasses.replace(j, unresolved=True) if j.verdict in OPEN and j.diff.anchor in flagged else j
              for j in judged]
    judged = [dataclasses.replace(j, diff=dataclasses.replace(j.diff, id=n)) for n, j in enumerate(judged, 1)]

    summary = _summary(judged, version, asis is None, when)
    updated = dataclasses.replace(review, tolerances=list(review.tolerances),
                                  not_variables=list(review.not_variables), marks=marks,
                                  unresolved=unresolved, noise_rules=list(review.noise_rules), summary=summary)
    return tuple(judged), summary, verification, updated


def has_text(comparison: Comparison) -> bool:
    """Both sides of ``comparison`` have extractable text (R49)."""
    return comparison.left_has_text and comparison.right_has_text


def _copy(review: Review) -> Review:
    return dataclasses.replace(review, tolerances=list(review.tolerances), not_variables=list(review.not_variables),
                               marks=list(review.marks), unresolved=list(review.unresolved),
                               noise_rules=list(review.noise_rules))


def _still_unresolved(unresolved: list[tuple[Anchor, int, str]], judged: list[Judged],
                      at: dict[Anchor, int]) -> list[tuple[Anchor, int, str]]:
    """The remembered "non risolte" whose difference is still there with the
    same generated text; "" (unknown: an older file) takes the current one."""
    out = []
    for anchor, made_in, text in unresolved:
        if anchor not in at:
            continue
        now = generated_text(judged[at[anchor]].diff)
        if text in ("", now):
            out.append((anchor, made_in, now))
    return out


def _made_unique(diffs: list[Diff], side: str) -> list[Diff]:
    """``diffs`` with unique anchors (R35): unchanged when they already are."""
    if len({d.anchor for d in diffs}) == len(diffs):
        return diffs
    log.warning("verdetto: ancore ripetute nel confronto %s, rinumerate", side)
    anchors = disambiguate([d.anchor for d in diffs])
    return [dataclasses.replace(d, anchor=a) for d, a in zip(diffs, anchors, strict=True)]


def inactive(review: Review, judged: Sequence[Judged]) -> int:
    """How many tolerances, "non è una variabile" entries and marks of
    ``review`` (the one :func:`judge` returned) do nothing in ``judged``: a
    tolerance whose anchor and generated text match no difference, a
    not-variable whose anchor matches none, a mark whose difference is not
    "da verificare" (gone, or dormant: R32). They stay in ``caso.json`` —
    e.g. after the target was replaced (Review Focus 4)."""
    anchors = {j.diff.anchor for j in judged}
    marked = {j.diff.anchor for j in judged if j.marked}
    texts = {(j.diff.anchor, generated_text(j.diff)) for j in judged}
    return (sum((t.anchor, t.generated) not in texts for t in review.tolerances)
            + sum(a not in anchors for a, _ in review.not_variables)
            + sum(m.anchor not in marked for m in review.marks))


def _judge_one(d: Diff, two_way: bool, asis_by: dict[Anchor, Diff], review: Review, profile: Profile) -> Judged:
    if d.klass in ("variabile", "rumore"):
        return Judged(d, None)
    if not counts(d, profile):
        return Judged(d, "tollerata")
    text = generated_text(d)
    for t in review.tolerances:
        if t.anchor == d.anchor and t.generated == text:
            return Judged(d, "tollerata", tolerated_note=t.note)
    if two_way:
        return Judged(d, "da_fare")
    before = asis_by.get(d.anchor)
    if before is None:
        return Judged(d, "regressione")
    if generated_text(before) == text:
        return Judged(d, "da_fare")
    return Judged(d, "in_corso", previous_text=before.right_text)


def _verify(judged: list[Judged], at: dict[Anchor, int], marks: list[Mark],
            unresolved: list[tuple[Anchor, int, str]], version: int
            ) -> tuple[list[Judged], Verification | None, list[tuple[Anchor, int, str]], list[Mark]]:
    judged = list(judged)
    resolved = stuck = changed = 0
    dormant: list[Mark] = []
    for mark in marks:
        i = at.get(mark.anchor)
        if i is None:
            resolved += 1
            continue
        j = judged[i]
        if j.verdict not in OPEN:          # R32: does not count right now
            dormant.append(mark)
            continue
        text = generated_text(j.diff)
        if text == mark.generated:         # R31: keeps its verdict, flagged "non risolta"
            stuck += 1
            unresolved = [e for e in unresolved if e[0] != mark.anchor] + [(mark.anchor, mark.version, text)]
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
