"""What "Aggiungi chiamata…" does once the calls are chosen: Qt-free, run in a worker.

The window (``officina_pick_call``) and Ricerca's "Aggiungi all'Officina…"
(``officina_add``) both end with a list of :class:`PlanItem` — a call and
what to do with it: a new case (with its variant) or the replacement of an
existing case's call — for one initiative (:class:`AddTarget`, existing or
new). :func:`run_plan` carries it out through ``OfficinaApi`` and never
raises: every refusal becomes a line of :class:`PlanOutcome`, and
:func:`outcome_text` makes the one status line the page shows.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import Case, Initiative, OfficinaApi, SearchHit

__all__ = ["AddTarget", "PlanItem", "PlanOutcome", "cases_of_key", "hit_label", "outcome_text",
           "run_plan"]


@dataclass(frozen=True)
class AddTarget:
    """The initiative: its id (folder), or with ``create`` a new one's name."""

    initiative: str
    create: bool = False


@dataclass(frozen=True)
class PlanItem:
    """One chosen call: ``replace`` = the id of the case whose call it
    replaces, None = a new case with ``variant``."""

    hit: SearchHit
    replace: str | None = None
    variant: str = ""


@dataclass
class PlanOutcome:
    initiative: Initiative | None = None
    added: list[Case] = field(default_factory=list)
    replaced: list[Case] = field(default_factory=list)
    #: Cases given the call they already had: nothing was written.
    unchanged: list[Case] = field(default_factory=list)
    #: ``(key and short FDI of the call, why it failed)``
    failed: list[tuple[str, str]] = field(default_factory=list)
    #: The initiative itself could not be used: nothing was done.
    error: str = ""


def hit_label(hit: SearchHit) -> str:
    """``KEY (1a2b3c4d)``: how a call is named in a message."""
    return f"{hit.template_key} ({hit.fdi[:8]})" if hit.fdi else hit.template_key


def cases_of_key(ini: Initiative | None, key: str) -> list[Case]:
    """The cases of ``ini`` with template key ``key`` (what a call may replace)."""
    if ini is None:
        return []
    return [c for c in ini.cases if c.key.strip() == key.strip()]


def _initiative(api: OfficinaApi, target: AddTarget) -> Initiative:
    try:
        return api.create_initiative(target.initiative) if target.create else api.load(target.initiative)
    except FileExistsError as exc:
        raise ValueError(strings.OFFICINA_INITIATIVE_EXISTS.format(name=target.initiative)) from exc
    except FileNotFoundError as exc:
        raise ValueError(strings.OFFICINA_INITIATIVE_GONE.format(name=target.initiative)) from exc


def run_plan(api: OfficinaApi, target: AddTarget, items: Sequence[PlanItem]) -> PlanOutcome:
    """Every item, in order; a failed one never stops the others."""
    out = PlanOutcome()
    try:
        ini = _initiative(api, target)
    except (OSError, ValueError) as exc:
        out.error = str(exc)
        return out
    out.initiative = ini
    for item in items:
        try:
            if item.replace is not None:
                case = next((c for c in ini.cases if c.id == item.replace), None)
                if case is None:
                    raise ValueError(strings.CHIAMATA_CASE_GONE)
                before = len(case.history)
                got = api.replace_call(case, item.hit)
                (out.replaced if len(got.history) > before else out.unchanged).append(got)
            else:
                out.added.append(api.case_from_hit(ini, item.hit, item.variant))
        except FileExistsError:
            out.failed.append((hit_label(item.hit), strings.OFFICINA_ADD_DUPLICATE))
        except (OSError, ValueError) as exc:
            out.failed.append((hit_label(item.hit), str(exc)))
    return out


def outcome_text(out: PlanOutcome) -> str:
    """The one status line of a run."""
    if out.error:
        return strings.CHIAMATA_FAILED_ALL.format(reason=out.error)
    parts = []
    if out.added:
        n = len(out.added)
        parts.append(strings.CHIAMATA_DONE_ADDED_ONE if n == 1 else strings.CHIAMATA_DONE_ADDED.format(n=n))
    if out.replaced:
        n = len(out.replaced)
        parts.append(strings.CHIAMATA_DONE_REPLACED_ONE if n == 1
                     else strings.CHIAMATA_DONE_REPLACED.format(n=n))
    if out.unchanged:
        n = len(out.unchanged)
        parts.append(strings.CHIAMATA_DONE_UNCHANGED_ONE if n == 1
                     else strings.CHIAMATA_DONE_UNCHANGED.format(n=n))
    if out.failed:
        reasons = "; ".join(strings.CHIAMATA_ITEM_FAILED.format(what=w, reason=r) for w, r in out.failed)
        parts.append(strings.CHIAMATA_DONE_FAILED.format(n=len(out.failed), reasons=reasons))
    name = out.initiative.name if out.initiative is not None else ""
    return strings.CHIAMATA_DONE.format(initiative=name, parts=", ".join(parts))
