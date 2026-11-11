"""What "Riprova i non riusciti" calls again, from a finished run's report.

The rows that did not end well (failed, no call, cancelled) become targets
again, de-duplicated, in the report's order:

* a row of an exact call (``Outcome.exact_hit``: Ricerca's "Genera
  documento") → that very call again (``Target("call", …)``), into the same
  folder — never the newest call of its key;
* a row of an FDI target (its only folder is the FDI) with a key → that key
  OF THAT FDI (``Target("fdi", fdi, (), keys)``, one target per FDI holding
  all its keys to retry): the FDI's own call, into the FDI's folder — never
  the whole FDI again, never the newest call of the key from another FDI;
* a row of an FDI without a key (it had no call, or was never looked up) →
  the whole FDI;
* any other row → its key, into the same folders.

:func:`retry_count` is the number of calls the retry will make, which is
what the button says: one per key or exact call, one per whole FDI (an FDI that had no
call is one row, and stays one row unless calls appeared since).

The choices of NOW (generator, logs, folder, headers) are the presenter's to add.
"""
from __future__ import annotations

import dataclasses

from qtrequestory.ui.contracts import NO_PACKAGE, BatchReport, SearchHit, Target

__all__ = ["RETRY_STATUSES", "retry_count", "retry_targets"]

#: What "Riprova i non riusciti" calls again.
RETRY_STATUSES = frozenset({"failed", "no_call", "cancelled"})


def retry_targets(report: BatchReport) -> tuple[Target, ...]:
    """The targets to call again (module docstring)."""
    targets: list[Target] = []
    fdi_at: dict[str, int] = {}   # folded FDI -> index of its target in ``targets``
    keys_seen: set[str] = set()
    hits_seen: set[SearchHit] = set()
    for outcome in report.outcomes:
        if outcome.status not in RETRY_STATUSES:
            continue
        fdi, key = (outcome.fdi or "").strip(), outcome.key.strip()
        hit = outcome.exact_hit
        if hit is not None:
            if hit not in hits_seen:
                hits_seen.add(hit)
                folders = tuple(outcome.folders) or (hit.fdi or NO_PACKAGE,)
                targets.append(Target("call", hit.template_key, folders, hit=hit))
        elif fdi and tuple(outcome.folders) == (fdi,):
            folded = fdi.casefold()
            if folded not in fdi_at:
                fdi_at[folded] = len(targets)
                targets.append(Target("fdi", fdi, (), (key,) if key else ()))
                continue
            current = targets[fdi_at[folded]]
            if key and current.keys and key.casefold() not in {k.casefold() for k in current.keys}:
                targets[fdi_at[folded]] = dataclasses.replace(current, keys=(*current.keys, key))
        elif key and key.casefold() not in keys_seen:
            keys_seen.add(key.casefold())
            targets.append(Target("key", outcome.key, tuple(outcome.folders) or (NO_PACKAGE,)))
    return tuple(targets)


def retry_count(report: BatchReport) -> int:
    """The calls the retry makes: one per key or exact call, one per whole FDI."""
    return sum(len(t.keys) if t.kind == "fdi" and t.keys else 1 for t in retry_targets(report))
