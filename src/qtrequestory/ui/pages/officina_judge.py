"""The per-case worker locks, the generation under one, the judge and review jobs.

Split from ``officina_jobs`` (size). Two workers write a case's
``caso.json``: a generation (``OfficinaApi.generate``, an HTTP call that can
take minutes) and ``compare_case`` (it saves the summary and the outcome of
the marks' verification). They take turns on the case's lock, and a judge
never waits for a generation: the reload after the generation judges again.

A review action (U4: "segna fatta", "tollera", … and their undo) writes only
the review keys of ``caso.json`` (``Workspace.save_review`` merges under the
model's own per-case write lock, R16), as ``compare_case`` does: the two
take turns on a second, short lock per case — the REVIEW lock — so an action
never races the verification of the marks, and never waits for an HTTP call
(a generation does not touch the review keys). ``judge`` takes the case lock
then the review lock; ``act`` only the review lock: no cycle.

A case is known by ``(initiative id, case id)``: a case id is unique only
inside its initiative, so two initiatives holding the same key never share a
lock or a "being generated" count. The count is a counter, not a set: two
generations of one case (an AS-IS queued behind a TO-BE on another lane)
each add one and take it away, and the case stays "being generated" until
both are over.
"""
from __future__ import annotations

import logging
import threading
from collections import Counter
from collections.abc import Sequence

from qtrequestory.ui.contracts import (
    Case,
    CaseComparison,
    CompareError,
    CoreServices,
    Initiative,
    Version,
)

__all__ = ["act", "case_lock", "generate_locked", "is_generating", "judge", "review_lock"]

log = logging.getLogger(__name__)

CaseKey = tuple[str, str]

#: One lock per (initiative id, case id).
_case_locks: dict[CaseKey, threading.Lock] = {}
_case_locks_guard = threading.Lock()
#: One review lock per (initiative id, case id): compare_case and the review actions.
_review_locks: dict[CaseKey, threading.Lock] = {}
#: How many generations of each case are queued on its lock or running.
_generating: Counter[CaseKey] = Counter()
#: How often a judge waiting for another judge of the same case looks again, in seconds.
_JUDGE_POLL_S = 0.01


def _key(ini: Initiative, case: Case) -> CaseKey:
    return (ini.id, case.id)


def case_lock(initiative_id: str, case_id: str) -> threading.Lock:
    with _case_locks_guard:
        return _case_locks.setdefault((initiative_id, case_id), threading.Lock())


def review_lock(initiative_id: str, case_id: str) -> threading.Lock:
    with _case_locks_guard:
        return _review_locks.setdefault((initiative_id, case_id), threading.Lock())


def is_generating(initiative_id: str, case_id: str) -> bool:
    with _case_locks_guard:
        return _generating[(initiative_id, case_id)] > 0


def generate_locked(services: CoreServices, ini: Initiative, case: Case, kind, *,
                    replace_asis_note: str | None = None, cancel=None):
    """``OfficinaApi.generate`` under the case's lock (same signature, so the
    runner still injects the cancel token)."""
    key = _key(ini, case)
    with _case_locks_guard:
        _generating[key] += 1
    try:
        with case_lock(*key):
            return services.officina.generate(ini, case, kind, replace_asis_note=replace_asis_note,
                                              cancel=cancel)
    finally:
        with _case_locks_guard:
            _generating[key] -= 1
            if _generating[key] <= 0:
                del _generating[key]


def _take_for_judge(key: CaseKey) -> threading.Lock | None:
    """The case's lock, waiting only for another (short) judge of the same
    case; None as soon as a generation holds or waits for it."""
    lock = case_lock(*key)
    while not lock.acquire(timeout=_JUDGE_POLL_S):
        if is_generating(*key):
            return None
    if is_generating(*key):  # a generation is queued behind us: let it go first
        lock.release()
        return None
    return lock


def judge(services: CoreServices, ini: Initiative, case: Case, version: Version) -> CaseComparison | None:
    """``compare_case``, or None: the case is being generated right now
    (never wait for an HTTP call: the reload after the generation judges
    again), the core cannot judge yet (the real service until the engine
    lands) or it failed. The phase-1 comparison is shown then."""
    lock = _take_for_judge(_key(ini, case))
    if lock is None:
        return None
    try:
        with review_lock(*_key(ini, case)):
            return _compare_case(services, ini, case, version)
    finally:
        lock.release()


def _compare_case(services: CoreServices, ini: Initiative, case: Case,
                  version: Version) -> CaseComparison | None:
    try:
        return services.officina.compare_case(ini, case, version)
    except NotImplementedError:
        return None
    except (CompareError, OSError, ValueError) as exc:
        log.warning("confronto a tre vie non riuscito per %s: %s", case.key, exc)
        return None


def act(services: CoreServices, ini: Initiative, case: Case, version: Version | None,
        steps: Sequence[tuple[str, tuple]]) -> CaseComparison | None:
    """The review job: each ``(OfficinaApi method, arguments after the
    case)`` of ``steps`` in turn (``officina_undo``), then ``compare_case`` of
    ``version`` again, so the page redraws from the new verdicts without
    reloading the documents. None when ``version`` is not a TO-BE (the page
    reloads the case then) or the comparison failed. A refused save raises
    (``ValueError`` / ``OSError``): the job's error says why."""
    with review_lock(*_key(ini, case)):
        api = services.officina
        for method, args in steps:
            getattr(api, method)(case, *args)
        if version is None or version.kind != "tobe":
            return None
        return _compare_case(services, ini, case, version)
