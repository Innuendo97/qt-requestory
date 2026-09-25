"""How the Officina words times, versions and differences (pure functions)."""
from __future__ import annotations

import os
from collections.abc import Sequence
from datetime import date, datetime, timedelta

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import Case, DeliveryReport, Difference, Initiative, MissingSlot, Version

__all__ = ["accepted_count", "case_notice", "case_title", "delivery_summary", "difference_lines",
           "delivery_warning", "elide", "initiative_labels", "initiative_notice", "last_activity", "last_run",
           "latest_generated", "missing_text", "when"]

#: Longest text quoted in a difference line before it is cut with "…".
QUOTE_CHARS = 60


def when(moment: datetime | None, today: date | None = None) -> str:
    """"oggi 10:42", "ieri 17:20", "03/09/2026 09:15"; "—" for no moment."""
    if moment is None or moment == datetime.min:
        return strings.OFFICINA_NONE
    today = today or date.today()
    clock = moment.strftime("%H:%M")
    if moment.date() == today:
        return strings.OFFICINA_TODAY.format(time=clock)
    if moment.date() == today - timedelta(days=1):
        return strings.OFFICINA_YESTERDAY.format(time=clock)
    return strings.OFFICINA_ON_DAY.format(date=moment.strftime("%d/%m/%Y"), time=clock)


def case_title(case: Case) -> str:
    """"MOD_TEST_A · abilitato", or just the key."""
    return f"{case.key} · {case.variant}" if case.variant else case.key


def initiative_labels(initiatives: Sequence[Initiative]) -> dict[str, str]:
    """``{initiative id: what the user reads}``: the name, or "name (folder)"
    when two initiatives share the name (a folder copied in Explorer)."""
    counts: dict[str, int] = {}
    for ini in initiatives:
        counts[ini.name.casefold()] = counts.get(ini.name.casefold(), 0) + 1
    return {ini.id: (strings.OFFICINA_INITIATIVE_LABEL.format(name=ini.name, folder=ini.id)
                     if counts[ini.name.casefold()] > 1 else ini.name)
            for ini in initiatives}


def initiative_notice(ini: Initiative) -> str:
    """The board's banner: an unreadable ``iniziativa.json``, or what loading left out."""
    if ini.load_error:
        return strings.OFFICINA_INITIATIVE_BROKEN.format(reason=ini.load_error)
    return "\n".join(ini.load_notes)


def case_notice(case: Case) -> str:
    """The workbench's banner: an unreadable ``caso.json``, a case to check
    again after a new version, and what loading left out."""
    if case.load_error:
        return strings.OFFICINA_CASE_BROKEN.format(reason=case.load_error)
    lines = []
    if case.reopened and case.status != "accepted":
        lines.append(strings.OFFICINA_CASE_REOPENED)
    elif case.status == "accepted" and not case.acceptance_is_current():
        lines.append(strings.OFFICINA_CASE_STALE)
    return "\n".join(lines + list(case.load_notes))


def delivery_warning(chosen: Sequence[Case]) -> str:
    """The delivery dialog's warn line: the chosen cases not accepted, and
    those whose latest TO-BE is not the accepted one ("" when none)."""
    not_accepted = [c for c in chosen if c.status != "accepted"]
    stale = [c for c in chosen if c.status == "accepted" and not c.acceptance_is_current()]
    lines = []
    if not_accepted:
        names = ", ".join(case_title(c) for c in not_accepted)
        lines.append(strings.OFFICINA_DELIVERY_NOT_ACCEPTED_ONE.format(cases=names)
                     if len(not_accepted) == 1 else
                     strings.OFFICINA_DELIVERY_NOT_ACCEPTED.format(n=len(not_accepted), cases=names))
    if stale:
        lines.append(strings.OFFICINA_DELIVERY_STALE.format(
            cases=", ".join(case_title(c) for c in stale)))
    return " ".join(lines)


def _created(version: Version | None) -> datetime | None:
    if version is None or version.created == datetime.min:
        return None
    created = version.created
    return created.replace(tzinfo=None) if created.tzinfo else created


def latest_generated(case: Case) -> Version | None:
    """The newest AS-IS or TO-BE of ``case``."""
    versions = [v for v in (case.asis(), case.latest_tobe()) if _created(v) is not None]
    return max(versions, key=lambda v: _created(v)) if versions else None


def last_run(case: Case, today: date | None = None) -> str:
    """The board's "Ultima generazione": "oggi 11:05 · svil", "AS-IS ieri 16:02"."""
    version = latest_generated(case)
    if version is None:
        return strings.OFFICINA_NONE
    moment = when(_created(version), today)
    if version.kind == "asis":
        return strings.OFFICINA_LAST_RUN_ASIS.format(when=moment)
    env = str(version.meta.get("env") or case.env or "")
    return strings.OFFICINA_LAST_RUN.format(when=moment, env=env) if env else moment


def last_activity(ini: Initiative) -> datetime | None:
    """The newest document of any case (target, AS-IS or TO-BE)."""
    moments = [m for case in ini.cases
               for m in (_created(case.target()), _created(case.asis()),
                         _created(case.latest_tobe()))
               if m is not None]
    return max(moments) if moments else None


def accepted_count(ini: Initiative) -> int:
    return sum(1 for case in ini.cases if case.status == "accepted")


def elide(text: str, limit: int = QUOTE_CHARS) -> str:
    """``text`` on one line, cut to ``limit`` characters with "…"."""
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[:limit - 1].rstrip() + "…"


def difference_lines(diff: Difference) -> tuple[str, str]:
    """Where and what, for the differences list: ("pag. 1 · cambiato", "«a» → «b»")."""
    words = diff.left or diff.right
    page = (words[0].page + 1) if words else 1
    kind = {"added": strings.OFFICINA_KIND_ADDED, "removed": strings.OFFICINA_KIND_REMOVED,
            "changed": strings.OFFICINA_KIND_CHANGED}.get(diff.kind, diff.kind)
    if diff.kind == "changed":
        what = strings.OFFICINA_DIFF_CHANGE.format(left=elide(diff.left_text, QUOTE_CHARS // 2),
                                                   right=elide(diff.right_text, QUOTE_CHARS // 2))
    elif diff.kind == "removed":
        what = strings.OFFICINA_DIFF_ONLY_LEFT.format(text=elide(diff.left_text))
    else:
        what = strings.OFFICINA_DIFF_ONLY_RIGHT.format(text=elide(diff.right_text))
    return strings.OFFICINA_DIFF_WHERE.format(page=page, kind=kind), what


# -- delivery (ui/pages/officina_delivery.py) ------------------------------------

_MISSING = {"asis": strings.OFFICINA_DELIVERY_MISSING_ASIS, "tobe": strings.OFFICINA_DELIVERY_MISSING_TOBE,
            "target": strings.OFFICINA_DELIVERY_MISSING_TARGET}


def missing_text(slot: MissingSlot, *, with_key: bool = True) -> str:
    """"MOD_X · variante: manca il TO-BE (file non più su disco)"; without
    the key (the preview shows it under the key's folder): "variante: manca…"."""
    what = _MISSING[slot.slot]
    if slot.reason == "gone":
        what = strings.OFFICINA_DELIVERY_GONE.format(what=what)
    elif slot.reason == "outside":
        what = strings.OFFICINA_DELIVERY_OUTSIDE.format(what=what)
    elif slot.reason == "broken":
        what = strings.OFFICINA_DELIVERY_BROKEN.format(what=what)
    who = [slot.key] if with_key else []
    who += [slot.variant] if slot.variant else []
    return f"{' · '.join(who)}: {what}" if who else what


def delivery_summary(report: DeliveryReport, missing: Sequence[MissingSlot], *,
                     zip_asked: bool) -> tuple[str, str]:
    """``(title, body)`` of the delivery's summary: what was delivered, the
    zip, then the failed files (with their reason), the ones left as they
    were, and the slots skipped because missing."""
    if report.cancelled:
        title = strings.OFFICINA_DELIVERY_CANCELLED_TITLE
    elif report.failed:
        title = strings.OFFICINA_DELIVERY_PARTIAL_TITLE
    else:
        title = strings.OFFICINA_DELIVERY_DONE_TITLE
    files = [p for p in report.delivered if p != report.zip_path]
    lines = [strings.OFFICINA_DELIVERY_DELIVERED.format(n=len(files), folder=report.folder)]
    if report.zip_path is not None:
        lines.append(strings.OFFICINA_DELIVERY_ZIP_DONE.format(path=report.zip_path))
    elif zip_asked and (report.failed or report.cancelled):
        lines.append(strings.OFFICINA_DELIVERY_ZIP_NOT_MADE)
    if report.cancelled:
        lines.append(strings.OFFICINA_DELIVERY_CANCELLED)
    if report.remember_problem:
        lines.append(strings.OFFICINA_DELIVERY_NOT_REMEMBERED.format(reason=report.remember_problem))
    base = report.folder.parent
    sections = (
        (strings.OFFICINA_DELIVERY_FAILED, [f"{name}: {why}" for name, why in report.failed]),
        (strings.OFFICINA_DELIVERY_RENAMED, [
            strings.OFFICINA_DELIVERY_RENAMED_ENTRY.format(planned=planned, name=written.name)
            for planned, written in report.renamed]),
        (strings.OFFICINA_DELIVERY_SKIPPED, [os.path.relpath(p, base) for p in report.skipped]),
        (strings.OFFICINA_DELIVERY_ZIP_LEFT_OUT, [os.path.relpath(p, base) for p in report.zip_left_out]),
        (strings.OFFICINA_DELIVERY_MISSING, [missing_text(m) for m in missing]),
    )
    for heading, entries in sections:
        if entries:
            lines += ["", heading.format(n=len(entries)), *(f"  • {e}" for e in entries)]
    return title, "\n".join(lines)
