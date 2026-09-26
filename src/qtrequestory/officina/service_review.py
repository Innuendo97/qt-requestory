"""The phase-2 half of ``OfficinaService`` (``officina.service``): the case
comparison with verdicts and the review actions (``ui.contracts.OfficinaApi``,
spec §5–§6). The inputs and the cached comparisons are ``officina.service_case``'s.

**compare_case** (run it in a worker): the target, the TO-BE asked for and
the AS-IS (when there is one: else the verdict is two-way) go through the
engine with the effective profile (case → initiative → "tollerante") and
the noise rules — the presets the initiative turned on, then the
initiative's own rules, then the case's; the user's own rules are matched
only in the noise guard's child process, on the exact texts the noise stage
sees (R46), and one that cannot be used there (out of time, R22) is dropped
with a note. The tracking preset also drops tracking keys from HTML URLs (R21).
``compare.verdict.judge`` gives the verdicts (``when`` = now, R30); the
review it returns (verified marks removed, "non risolte", summary) is saved —
the summary and the "non risolte" it prunes only for the latest TO-BE (R48).
When the TO-BE or the target has no text nothing is judged and nothing saved
(R49: the marks wait for a version with text); an AS-IS without text makes
the verdict two-way, with a note.
"Non è una variabile" is applied by ``judge`` (rule 1, ruling R36), so the
pipeline's ``disabled_slots`` is not used here: the anchor stays the slot's.

**Persisting** (rulings R8/R16): every write goes through
``Workspace.save_review`` (only the review keys of ``caso.json``), and starts
from the review ON DISK, not from the ``Case`` object in hand (``compare_case``
also JUDGES with the review on disk and leaves the result on the given
``Case``): a comparison run on a stale ``Case`` (the board's, while the case
view tolerated something) only removes the marks it verified and sets "non risolte" and the
summary; an action changes only its own entry. ``case.review`` is updated
after the save succeeded, so a refused save (``caso.json`` unreadable:
``ValueError``; for ``compare_case`` a ``CompareError``) changes nothing.
The one read-modify-write of the review, :meth:`ReviewMixin._commit`, holds
the case's write lock (``model_case.case_write_lock``, R16) from the read to
the save, and the read retries a Windows sharing violation
(``model_io.read_text_retrying``).

Actions are idempotent: tolerating, marking, "non è una variabile" twice
leave one entry (the last one's note and time). Stored texts are
``verdict.generated_text`` of the difference (R30).

Logs counts and action names only: never a text of a document, a note or a
rule.
"""
from __future__ import annotations

import dataclasses
import logging
import time
from collections.abc import Callable

from qtrequestory.officina.compare import noise, noise_guard
from qtrequestory.officina.compare.model import PROFILES, CaseComparison, Judged, Profile
from qtrequestory.officina.compare.verdict import generated_text, has_text, inactive, judge
from qtrequestory.officina.model import Case, Initiative, Version
from qtrequestory.officina.model_case import append_history, case_write_lock, read_caso_strict
from qtrequestory.officina.model_io import UnreadableJsonError
from qtrequestory.officina.model_review import DEFAULT_PROFILE, Mark, NoiseRule, Review, Tolerance, review_from_json
from qtrequestory.officina.service_case import CaseInputsMixin, noise_side
from qtrequestory.officina.service_compare import CompareError

__all__ = ["ReviewMixin"]

log = logging.getLogger("qtrequestory.officina.service")

#: Added to the TO-BE comparison's note when the AS-IS has no text (R49: two-way).
ASIS_WITHOUT_TEXT = "l'AS-IS non ha testo estraibile: verdetto a due vie"
#: The history line of a replaced target (ruling R29).
TARGET_REPLACED = ("target sostituito: segni «fatta», «non risolte» e riepilogo azzerati "
                   "(tolleranze e «non è una variabile» restano, attive se ancora combaciano)")


class ReviewMixin(CaseInputsMixin):
    """``compare_case`` and the review actions of ``OfficinaService``: needs
    ``_workspace()``, ``_clock()`` and ``CompareMixin``."""

    # ---------------------------------------------------------- compare_case ---

    def compare_case(self, ini: Initiative, case: Case, version: Version) -> CaseComparison:
        started = time.monotonic()
        target = case.target()
        if target is None:
            raise CompareError("manca il target del caso: caricarlo prima di confrontare")
        asis = case.asis()
        try:  # the review ON DISK: a stale Case must not judge with an old one
            review = self._fresh_review(case)
        except ValueError as exc:
            raise CompareError(f"confronto non fatto: {exc}") from None
        profile: Profile = review.profile or ini.profile or DEFAULT_PROFILE
        presets = [NoiseRule(p.name, p.pattern, True) for p in noise.PRESETS if p.name in ini.noise_presets]
        custom, clashes = _unique_rules(presets, [r for r in (*ini.noise_rules, *review.noise_rules) if r.enabled])
        target_in, tobe_in = self._input(target), self._input(version)
        asis_in = self._input(asis) if asis is not None else None
        others = [("TO-BE", tobe_in)] + ([("AS-IS", asis_in)] if asis_in is not None else [])
        tracking = noise.TRACKING_PRESET in ini.noise_presets
        made, dropped = self._compare_pairs(target_in, others, presets, custom, tracking)
        notes = [f"regola «{name}» ignorata: {message}" for name, message in dropped.items()
                 if message != noise_guard.UNAVAILABLE]
        notes += [f"regola «{name}» ignorata: nome già usato da un'altra regola" for name in clashes]
        unchecked = [name for name, message in dropped.items() if message == noise_guard.UNAVAILABLE]
        if unchecked:  # R37: dropped, never run in this process
            notes.append(f"{noise_guard.UNAVAILABLE} ({', '.join(f'«{n}»' for n in unchecked)})")
        tobe = self._noted(made[0], target_in, tobe_in, notes)
        asis_cmp = self._noted(made[1], target_in, asis_in, notes) if asis_in is not None else None

        if asis_cmp is not None and has_text(tobe) and not has_text(asis_cmp):
            tobe = dataclasses.replace(tobe, note="; ".join(n for n in (tobe.note, ASIS_WITHOUT_TEXT) if n))
        judged, summary, verification, updated = judge(tobe, asis_cmp, review, profile, version.number,
                                                       when=self._now())
        if has_text(tobe):  # R49: without text nothing is verified, nothing saved
            latest = case.latest_tobe()
            self._save_compared(case, review, updated, latest is None or version.number >= latest.number)
        result = CaseComparison(version.number, judged, summary, tobe, asis_cmp, verification, profile,
                                inactive(updated, judged))
        log.info("Officina: confronto del caso %s su v%d (%s%s): %d differenze, %d fatte, %d da fare, "
                 "%d in corso, %d regressioni, %d da verificare, %d tollerate, %d variabili, %d rumore%s (%d ms)",
                 case.id, version.number, profile, ", a due vie" if asis_cmp is None else "", len(judged),
                 summary.fatte, summary.da_fare, summary.in_corso, summary.regressioni, summary.da_verificare,
                 summary.tollerate, summary.variabili, summary.rumore,
                 "" if verification is None else f"; verificate {verification.checked} segnate "
                 f"({verification.resolved} risolte, {verification.unresolved} non risolte, "
                 f"{verification.changed} cambiate)", int((time.monotonic() - started) * 1000))
        return result

    def _save_compared(self, case: Case, before: Review, after: Review, latest: bool) -> None:
        """Save what the comparison changed onto the review on disk: the marks
        it verified go; for the ``latest`` TO-BE "non risolte" and the summary
        are its (see module doc). An older version (R48) only adds the "non
        risolte" its verification found: the summary and the other flags stay
        the latest's (a summary of a later version on disk is never replaced)."""
        verified = [m for m in before.marks if m not in after.marks]
        found = [e for e in after.unresolved if e not in before.unresolved]

        def change(fresh: Review) -> Review:
            newest = latest and (fresh.summary is None or fresh.summary.version <= after.summary.version)
            if newest:
                unresolved, summary = list(after.unresolved), after.summary
            else:
                again = {e[0] for e in found}
                unresolved = [e for e in fresh.unresolved if e[0] not in again] + found
                summary = fresh.summary
            return dataclasses.replace(fresh, marks=[m for m in fresh.marks if m not in verified],
                                       unresolved=unresolved, summary=summary)
        try:
            self._commit(case, change)
        except ValueError as exc:  # caso.json unreadable, or no Officina folder
            raise CompareError(f"confronto fatto ma non salvato: {exc}") from None

    # --------------------------------------------------------------- actions ---

    def tolerate(self, case: Case, judged: Judged, note: str = "") -> None:
        anchor, text, when = judged.diff.anchor, generated_text(judged.diff), self._now()
        self._act("tolleranza aggiunta", case, lambda r: dataclasses.replace(r, tolerances=[
            *(t for t in r.tolerances if t.anchor != anchor), Tolerance(anchor, text, note, when)]))

    def untolerate(self, case: Case, judged: Judged) -> None:
        anchor = judged.diff.anchor
        self._act("tolleranza tolta", case, lambda r: dataclasses.replace(
            r, tolerances=[t for t in r.tolerances if t.anchor != anchor]))

    def mark_done(self, case: Case, judged: Judged, version: int) -> None:
        anchor, text, when = judged.diff.anchor, generated_text(judged.diff), self._now()
        self._act("segnata fatta", case, lambda r: dataclasses.replace(r, marks=[
            *(m for m in r.marks if m.anchor != anchor), Mark(anchor, text, version, when)]))

    def unmark(self, case: Case, judged: Judged) -> None:
        anchor = judged.diff.anchor
        self._act("segno tolto", case, lambda r: dataclasses.replace(
            r, marks=[m for m in r.marks if m.anchor != anchor]))

    def unmark_all(self, case: Case) -> None:
        self._act("segni annullati", case, lambda r: dataclasses.replace(r, marks=[]))

    def not_variable(self, case: Case, judged: Judged) -> None:
        anchor, when = judged.diff.anchor, self._now()

        def change(r: Review) -> Review:
            if any(a == anchor for a, _ in r.not_variables):
                return r
            return dataclasses.replace(r, not_variables=[*r.not_variables, (anchor, when)])
        self._act("non è una variabile", case, change)

    def variable_again(self, case: Case, judged: Judged) -> None:
        anchor = judged.diff.anchor
        self._act("di nuovo variabile", case, lambda r: dataclasses.replace(
            r, not_variables=[(a, w) for a, w in r.not_variables if a != anchor]))

    def reset_tolerances(self, case: Case) -> None:
        self._act("tolleranze azzerate", case, lambda r: dataclasses.replace(r, tolerances=[], not_variables=[]))

    def set_profile(self, ini: Initiative, case: Case | None, profile: Profile | None) -> None:
        if profile is not None and profile not in PROFILES:
            raise ValueError(f"profilo non riconosciuto: «{profile}»")
        if case is None:
            self._save_initiative(ini, profile=profile or DEFAULT_PROFILE)
        else:
            self._act("profilo", case, lambda r: dataclasses.replace(r, profile=profile))

    def set_noise_rules(self, ini: Initiative, case: Case | None, rules: list[NoiseRule],
                        presets: list[str] | None = None) -> None:
        noise_guard.refuse_duplicates(rules)
        _refuse_name_clashes(ini, case, rules)
        copies = [dataclasses.replace(r) for r in rules]
        if case is not None:
            self._act("regole di rumore", case, lambda r: dataclasses.replace(r, noise_rules=copies))
        elif presets is not None:
            self._save_initiative(ini, noise_rules=copies, noise_presets=list(presets))
        else:
            self._save_initiative(ini, noise_rules=copies)

    def noise_presets(self) -> list[NoiseRule]:
        return noise.preset_rules()

    def count_noise_hits(self, case: Case, rules: list[NoiseRule]) -> dict[str, int | str]:
        """Per rule: its hits over the target and the latest TO-BE (a side
        that cannot be read counts nothing); the user's rules in the guard's
        child process (R22), the presets here."""
        noise_guard.refuse_duplicates(rules)
        inputs = []
        for version in (case.target(), case.latest_tobe()):
            if version is None:
                continue
            try:
                inputs.append(self._input(version))
            except CompareError:
                continue
        presets = {(p.name, p.pattern) for p in noise.PRESETS}
        trusted = [r for r in rules if (r.name, r.pattern) in presets]
        hits = {**noise_guard.count_trusted([noise_side(i) for i in inputs], trusted),
                **self._guarded_hits([r for r in rules if (r.name, r.pattern) not in presets], inputs)}
        return {r.name: hits[r.name] for r in rules}

    def dom_view(self, case: Case, version: Version) -> tuple[str, str]:
        target = case.target()
        if target is None or target.doc_type != "html" or version.doc_type != "html":
            return "", ""
        return self._pretty(target), self._pretty(version)

    # ---------------------------------------------------------- the target ---

    def _target_replaced(self, case: Case) -> None:
        """R29: a new target clears marks, "non risolte" and the summary (the
        old anchors are gone), keeps tolerances and not-variables (inactive
        if their anchors vanished), and says so in the history. A review that
        cannot be saved is left as it is (logged): the target is in already."""
        try:
            fresh = self._fresh_review(case)
            if not (fresh.marks or fresh.unresolved or fresh.summary is not None):
                return
            self._commit(case, lambda r: dataclasses.replace(r, marks=[], unresolved=[], summary=None))
            append_history(case.folder, TARGET_REPLACED)
        except (ValueError, OSError) as exc:
            log.warning("Officina: %s: revisione non azzerata dopo il nuovo target (%s)", case.id,
                        type(exc).__name__)
            return
        log.info("Officina: %s: nuovo target, segni e riepilogo azzerati", case.id)

    # -------------------------------------------------------------- helpers ---

    def _act(self, action: str, case: Case, change: Callable[[Review], Review]) -> None:
        self._commit(case, change)
        log.info("Officina: %s: %s", case.id, action)

    def _commit(self, case: Case, change: Callable[[Review], Review]) -> None:
        """Read the review on disk, apply ``change``, save it, THEN put it on
        ``case``, under the case's write lock (R16: another thread's write of
        this ``caso.json`` cannot land between the read and the save).
        ``ValueError`` (nothing written, ``case`` unchanged) when
        ``caso.json`` cannot be read."""
        with case_write_lock(case.folder):
            updated = change(self._fresh_review(case))
            self._workspace().save_review(dataclasses.replace(case, review=updated))  # type: ignore[attr-defined]
        case.review = updated

    @staticmethod
    def _fresh_review(case: Case) -> Review:
        if case.load_error:
            raise UnreadableJsonError(f"caso.json non è leggibile ({case.load_error}): la revisione non viene salvata")
        return review_from_json(read_caso_strict(case.folder), [])

    def _save_initiative(self, ini: Initiative, **changes) -> None:
        """Save a copy of ``ini`` with ``changes``, THEN update ``ini``."""
        self._workspace().save_initiative_settings(dataclasses.replace(ini, **changes))  # type: ignore[attr-defined]
        for name, value in changes.items():
            setattr(ini, name, value)
        log.info("Officina: iniziativa %s: impostazioni del confronto salvate", ini.id)

    def _now(self) -> str:
        now = self._clock()  # type: ignore[attr-defined]
        if now.tzinfo is not None:
            now = now.astimezone()
        return now.isoformat(timespec="seconds")


def _refuse_name_clashes(ini: Initiative, case: Case | None, rules: list[NoiseRule]) -> None:
    """Rule names are keys across levels too (the comparison applies the
    initiative's presets and rules and the case's together): a name of a
    preset, of an initiative rule (saving a case's) or of any case's rule
    (saving the initiative's) is refused with an Italian ``ValueError``."""
    taken = {p.name: "da un preset" for p in noise.PRESETS}
    if case is None:
        for other in ini.cases:
            for rule in other.review.noise_rules:
                taken.setdefault(rule.name, f"da una regola del caso {other.key}")
    else:
        for rule in ini.noise_rules:
            taken.setdefault(rule.name, "da una regola dell'iniziativa")
    for rule in rules:
        if rule.name in taken:
            raise ValueError(f"regola di rumore «{rule.name}»: nome già usato {taken[rule.name]}")


def _unique_rules(presets: list[NoiseRule], custom: list[NoiseRule]) -> tuple[list[NoiseRule], list[str]]:
    """``custom`` without the rules whose name a preset or an earlier rule
    already has (files saved before the check, or edited by hand), and those
    names: the comparison drops them with a note instead of failing."""
    seen = {p.name for p in presets}
    kept: list[NoiseRule] = []
    dropped: list[str] = []
    for rule in custom:
        if rule.name in seen:
            dropped.append(rule.name)
        else:
            seen.add(rule.name)
            kept.append(rule)
    return kept, dropped
