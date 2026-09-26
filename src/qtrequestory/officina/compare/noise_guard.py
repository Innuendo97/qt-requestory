"""Custom noise rules evaluated in a killable child process (ruling R22).

A noise rule is a user's regular expression. ``noise.compile_rules`` refuses
the patterns known to backtrack catastrophically (ruling R17), but no static
check catches them all (``(a|a)*b`` passes), and CPython's ``re`` cannot be
interrupted: run in the application, such a rule would freeze it. So the
rules the USER wrote (never the built-in presets, which are tested) are run
here first, in a child process started with ``multiprocessing``'s *spawn*
method, each within :data:`BUDGET_S` seconds of matching:

* :func:`match_spans` gives, per rule name, the spans the rule matches on
  each given side (``noise.spans``): ``compare_case`` passes the EXACT keys
  and line ends the pipeline's noise stage sees and hands the spans to the
  pipeline (``noise.Found``), so a user's rule is never matched (executed) in
  the application process (ruling R46; the noise dialog only compiles it, to
  validate its syntax);
* :func:`count_hits` gives, per rule name, how many times the rule matches the
  given sides (the noise dialog's live counts), counted exactly as
  ``noise.apply`` counts it for that rule alone;
* either gives an Italian error instead: the ``compile_rules`` message for a
  rule that cannot be used (compiled in the child too; only
  ``noise.precheck``'s checks run here),
  :data:`~qtrequestory.officina.compare.noise.SLOW` for one that ran out of
  time — the child is then killed and a new one carries on with the rules
  after it.

The child's start-up (a new interpreter; a frozen exe unpacks) is not part of
the budget: it has :data:`START_S` to say it is ready. A child that cannot
be started, or never says it is ready, is logged and its rules are reported
as :data:`UNAVAILABLE` — NEVER run in this process (ruling R37: an
uninterruptible regex would hang the worker); the caller drops them with a
visible note. A child that never said it was ready latches the guard
"unavailable" for :data:`LATCH_S` seconds: meanwhile the rules are
:data:`UNAVAILABLE` at once, without starting a child or waiting
:data:`START_S` again on every comparison (a failed spawn costs nothing and
is retried at once).
The entry scripts call ``multiprocessing.freeze_support()`` so a child of
the frozen exe runs this module, not the application.

Stdlib only; no Qt, no pypdfium2. The child imports only this module and
``noise`` (light).
"""
from __future__ import annotations

import logging
import multiprocessing
import re
import threading
import time
from collections.abc import Sequence

from qtrequestory.officina.compare import noise
from qtrequestory.officina.model_review import NoiseRule

__all__ = ["BUDGET_S", "LATCH_S", "START_S", "UNAVAILABLE", "Side", "Spans", "count_hits", "count_trusted",
           "match_spans", "refuse_duplicates", "selftest"]

log = logging.getLogger(__name__)

#: Seconds one rule may take to match every side.
BUDGET_S = 2.0
#: Seconds a child may take to start and say it is ready.
START_S = 30.0
#: Seconds the guard stays "unavailable" after a child never said it was ready.
LATCH_S = 120.0
#: ``time.monotonic()`` until which no child is started (see :data:`LATCH_S`); the
#: noise dialog's counts and a comparison run in different workers: read and
#: written under :data:`_latch_lock`.
_unavailable_until = 0.0
_latch_lock = threading.Lock()
#: The message of a rule no child could evaluate (ruling R37).
UNAVAILABLE = "regole personalizzate non applicate: il controllo delle regole non si è avviato"

#: One text to match: its normalised keys and the indices of the keys a line ends after.
Side = tuple[list[str], list[int]]
#: A rule's matches on each side, in the order of the sides: ``(start, end)`` in that side's joined text.
Spans = tuple[tuple[tuple[int, int], ...], ...]
_READY = "ready"


def refuse_duplicates(rules: Sequence[NoiseRule]) -> None:
    """``ValueError`` (Italian) when two rules share a name: names are keys."""
    seen: set[str] = set()
    for rule in rules:
        if rule.name in seen:
            raise ValueError(f"due regole di rumore hanno lo stesso nome: «{rule.name}»")
        seen.add(rule.name)


def count_hits(sides: Sequence[Side], rules: Sequence[NoiseRule]) -> dict[str, int | str]:
    """Per rule name (enabled or not): its hits over ``sides``, or why it
    cannot be used (see module doc). ``ValueError`` for duplicate names."""
    return _guarded(sides, rules, "count")  # type: ignore[return-value]


def match_spans(sides: Sequence[Side], rules: Sequence[NoiseRule]) -> dict[str, Spans | str]:
    """Per rule name (enabled or not): its spans on each of ``sides`` (see
    :data:`Spans`), or why it cannot be used (see module doc).
    ``ValueError`` for duplicate names."""
    return _guarded(sides, rules, "spans")  # type: ignore[return-value]


def _guarded(sides: Sequence[Side], rules: Sequence[NoiseRule], mode: str) -> dict[str, object]:
    refuse_duplicates(rules)
    out: dict[str, object] = {}
    todo: list[tuple[str, str]] = []
    for rule in rules:
        problem = noise.precheck(rule.name, rule.pattern)
        if problem is not None:
            out[str(rule.name)] = problem
        else:
            todo.append((rule.name, rule.pattern))
    if todo:
        out.update(_evaluate([(list(keys), list(ends)) for keys, ends in sides], todo, mode))
    return {str(rule.name): out[str(rule.name)] for rule in rules}


def count_trusted(sides: Sequence[Side], rules: Sequence[NoiseRule]) -> dict[str, int | str]:
    """:func:`count_hits` in THIS process, for rules known to be safe (the
    built-in presets, which are tested): no child, no budget. Never for a
    user's rule (R46)."""
    refuse_duplicates(rules)
    out: dict[str, int | str] = {}
    for rule in rules:
        _, errors = noise.compile_rules([NoiseRule(rule.name, rule.pattern, True)])
        out[str(rule.name)] = next(iter(errors.values())) if errors else _count(sides, rule.name, rule.pattern)
    return out


# ------------------------------------------------------------ the child ---

def _count(sides: Sequence[Side], name: str, pattern: str) -> int:
    compiled = [(name, re.compile(pattern, re.MULTILINE))]
    return sum(len(noise.apply(keys, [()] * len(keys), compiled, set(ends))[2]) for keys, ends in sides)


def _work(sides: Sequence[Side], name: str, pattern: str, mode: str) -> object:
    """One rule's answer in the child: the check's error, or its count / spans."""
    compiled = noise.check(name, pattern)
    if isinstance(compiled, str):
        return compiled
    if mode == "count":
        return _count(sides, name, pattern)
    return tuple(tuple(noise.spans(keys, set(ends), compiled)) for keys, ends in sides)


def _child(conn, sides: list[Side], rules: list[tuple[str, str]], mode: str = "count") -> None:  # pragma: no cover
    """The child's work: say ready, then one ``(name, answer)`` per rule."""
    try:
        conn.send(_READY)
        for name, pattern in rules:
            conn.send((name, _work(sides, name, pattern, mode)))
    finally:
        conn.close()


def _start(sides: list[Side], rules: list[tuple[str, str]], mode: str = "count"):
    """A started child evaluating ``rules`` and the end of the pipe to read."""
    ctx = multiprocessing.get_context("spawn")
    receive, send = ctx.Pipe(duplex=False)
    process = ctx.Process(target=_child, args=(send, sides, rules, mode), daemon=True,
                          name="qtrequestory-noise-guard")
    process.start()
    send.close()
    return process, receive


def _evaluate(sides: list[Side], rules: list[tuple[str, str]], mode: str = "count") -> dict[str, object]:
    global _unavailable_until
    out: dict[str, object] = {}
    pending = list(rules)
    while pending:
        with _latch_lock:
            latched = time.monotonic() < _unavailable_until
        if latched:
            return {**out, **_here(sides, pending, "non pronto di recente", quiet=True)}
        try:
            process, receive = _start(sides, pending, mode)
        except (OSError, RuntimeError, ValueError) as exc:
            return {**out, **_here(sides, pending, f"non avviato ({type(exc).__name__})")}
        try:
            if not _ready(receive):
                with _latch_lock:
                    _unavailable_until = time.monotonic() + LATCH_S
                return {**out, **_here(sides, pending, "non pronto")}
            while pending:
                name, _ = pending.pop(0)
                try:
                    if not receive.poll(BUDGET_S):
                        raise TimeoutError
                    got_name, hits = receive.recv()
                except (TimeoutError, EOFError, OSError):
                    # out of time (or the child died on it): drop the rule, and
                    # a new child takes the rules after it
                    out[name] = noise.SLOW
                    log.info("regola di rumore scartata: oltre %.1f s", BUDGET_S)
                    break
                out[got_name] = hits
        finally:
            receive.close()
            if process.is_alive():
                process.kill()
            process.join(5)
    return out


def _ready(receive) -> bool:
    try:
        return bool(receive.poll(START_S)) and receive.recv() == _READY
    except (EOFError, OSError):
        return False


def _here(sides: list[Side], rules: list[tuple[str, str]], why: str, *,
          quiet: bool = False) -> dict[str, object]:
    """No child could run the rules: every one is :data:`UNAVAILABLE` (R37)."""
    (log.info if quiet else log.warning)("regole di rumore: processo di controllo %s, regole personalizzate non applicate", why)
    return {name: UNAVAILABLE for name, _ in rules}


def selftest() -> int:
    """One custom rule counted in a spawned child over a synthetic text:
    prints one line, exit code 0 when the count is right, else 1. The path a
    frozen exe must support through ``multiprocessing.freeze_support()`` in
    its entry script — the hidden CLI flag ``--selftest-noise-guard``, a dev
    check of a built exe. Keep it trivial: no file, no network, no config."""
    started = time.monotonic()
    hits = count_hits([(["prova", "uno", "prova", "due"], [3])], [NoiseRule("prova", "prova")])
    ok = hits == {"prova": 2}
    print(f"noise guard: {'ok' if ok else 'NON riuscito'} {hits} ({time.monotonic() - started:.2f} s)")
    return 0 if ok else 1
