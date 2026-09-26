"""qtrequestory.officina.compare.noise_guard: custom noise rules in a killable
child process with a time budget (ruling R22). Synthetic data only."""
from __future__ import annotations

import re
import time
from pathlib import Path

import pytest

from qtrequestory.officina.compare import noise, noise_guard
from qtrequestory.officina.model_review import NoiseRule

ROOT = Path(__file__).resolve().parents[2]

#: ``(a|a)*b`` passes the static heuristic (ruling R17) and backtracks
#: exponentially on a run of "a" with no "b": the case the guard exists for.
EXPONENTIAL = "(a|a)*b"


def _side(text: str) -> tuple[list[str], list[int]]:
    keys = text.split()
    return keys, []


def _in_process(sides, rule: NoiseRule) -> int:
    usable, errors = noise.compile_rules([rule])
    assert not errors
    return sum(len(noise.apply(keys, [()] * len(keys), usable, ends)[2]) for keys, ends in sides)


def test_counts_agree_with_the_engine_and_bad_rules_say_why():
    sides = [_side("Emesso il 01/02/2026 e il 03/04/2026"), _side("Emesso il 05/06/2027")]
    rules = [NoiseRule("anno", r"20\d\d"), NoiseRule("rotta", "("), NoiseRule("vuota", "")]
    hits = noise_guard.count_hits(sides, rules)
    assert hits["anno"] == _in_process(sides, rules[0]) == 3
    assert isinstance(hits["rotta"], str) and hits["rotta"].startswith("espressione non valida")
    assert hits["vuota"] == "espressione vuota"


def test_a_disabled_rule_is_counted_too():
    """The dialog counts every rule it shows, switched on or not."""
    hits = noise_guard.count_hits([_side("uno due uno")], [NoiseRule("uno", "uno", enabled=False)])
    assert hits == {"uno": 2}


def test_a_catastrophic_rule_is_stopped_and_the_next_one_still_counted(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(noise_guard, "BUDGET_S", 1.0)
    sides = [_side("a" * 40 + " fine riga 2026")]
    rules = [NoiseRule("lenta", EXPONENTIAL), NoiseRule("anno", r"20\d\d")]
    started = time.monotonic()
    hits = noise_guard.count_hits(sides, rules)
    elapsed = time.monotonic() - started
    assert hits == {"lenta": noise.SLOW, "anno": 1}
    assert elapsed < 30, f"the child must be killed at the budget, took {elapsed:.1f} s"


def test_nothing_to_evaluate_starts_no_process(monkeypatch: pytest.MonkeyPatch):
    def refuse(*_a, **_k):
        raise AssertionError("no child process for rules unusable before compiling")

    monkeypatch.setattr(noise_guard, "_start", refuse)
    assert noise_guard.count_hits([_side("x")], [NoiseRule("vuota", ""), NoiseRule(" ", "x")]) == {
        "vuota": "espressione vuota", " ": "nome vuoto"}
    assert noise_guard.count_hits([_side("x")], []) == {}
    assert noise_guard.match_spans([_side("x")], [NoiseRule("vuota", "")]) == {"vuota": "espressione vuota"}


def _refuse_compiling(monkeypatch: pytest.MonkeyPatch, *patterns: str) -> None:
    """R46: fail if THIS process compiles (or parses) one of ``patterns``."""
    real_compile, real_parse = re._compile, noise._sre_parse.parse  # type: ignore[attr-defined]

    def compile_(pattern, flags):
        if pattern in patterns:
            pytest.fail(f"a custom pattern was compiled in the application: {pattern!r}")
        return real_compile(pattern, flags)

    def parse(pattern, *args, **kwargs):
        if pattern in patterns:
            pytest.fail(f"a custom pattern was parsed in the application: {pattern!r}")
        return real_parse(pattern, *args, **kwargs)

    monkeypatch.setattr(re, "_compile", compile_)
    monkeypatch.setattr(noise._sre_parse, "parse", parse)


def test_a_rule_that_does_not_compile_is_checked_in_the_child(monkeypatch: pytest.MonkeyPatch):
    _refuse_compiling(monkeypatch, "(", r"20\d\d")
    hits = noise_guard.count_hits([_side("anno 2026")], [NoiseRule("rotta", "("), NoiseRule("anno", r"20\d\d")])
    assert hits["rotta"].startswith("espressione non valida") and hits["anno"] == 1


def test_spans_are_found_in_the_child_and_apply_as_the_rule_would(monkeypatch: pytest.MonkeyPatch):
    """The spans the child finds, applied through noise.Found, give exactly
    what applying the compiled rule here gives (keys, members, hits)."""
    sides = [(["Emesso", "il", "01/02/2026", "a", "Roma"], [2]), (["Roma", "e", "Roma"], [])]
    rule = NoiseRule("citta", r"Roma|Milano")
    compiled, _ = noise.compile_rules([rule])  # the reference, compiled BEFORE the guard below
    _refuse_compiling(monkeypatch, rule.pattern)
    found = noise_guard.match_spans(sides, [rule, NoiseRule("rotta", "(")])
    assert found["rotta"].startswith("espressione non valida")
    for (keys, ends), side_spans in zip(sides, found["citta"], strict=True):
        members = [(k,) for k in keys]
        assert noise.apply(keys, members, [("citta", noise.Found(side_spans))], set(ends)) == \
            noise.apply(keys, members, compiled, set(ends))
    assert [len(s) for s in found["citta"]] == [1, 2]


def test_a_child_that_cannot_start_never_runs_the_rules_here(monkeypatch: pytest.MonkeyPatch):
    """R37: a failed spawn drops the user's rules, it never runs them in-process."""
    def broken(*_a, **_k):
        raise OSError("spawn non disponibile")

    monkeypatch.setattr(noise_guard, "_start", broken)
    monkeypatch.setattr(noise_guard, "_count", lambda *a: pytest.fail("evaluated in-process"))
    assert noise_guard.count_hits([_side("uno due uno")], [NoiseRule("uno", "uno")]) == {
        "uno": noise_guard.UNAVAILABLE}


def test_a_child_that_never_gets_ready_is_killed_and_the_rules_dropped(monkeypatch: pytest.MonkeyPatch):
    class Mute:
        def poll(self, timeout):
            return False

        def close(self):
            pass

    class Process:
        killed = False

        def is_alive(self):
            return not self.killed

        def kill(self):
            self.killed = True

        def join(self, timeout):
            pass

    started = Process()
    monkeypatch.setattr(noise_guard, "_unavailable_until", 0.0)  # restored after the test
    monkeypatch.setattr(noise_guard, "_start", lambda *a: (started, Mute()))
    monkeypatch.setattr(noise_guard, "_count", lambda *a: pytest.fail("evaluated in-process"))
    assert noise_guard.count_hits([_side("x")], [NoiseRule("a", "x"), NoiseRule("b", "y")]) == {
        "a": noise_guard.UNAVAILABLE, "b": noise_guard.UNAVAILABLE}
    assert started.killed


def test_a_child_that_never_got_ready_is_not_waited_for_again_for_a_while(monkeypatch: pytest.MonkeyPatch):
    """E7 deferred minor (I1): a child that never says ready costs START_S once;
    for LATCH_S afterwards the user's rules are UNAVAILABLE at once (no child,
    no wait), then a child is tried again."""
    class Mute:
        def poll(self, timeout):
            return False

        def close(self):
            pass

    class Process:
        def is_alive(self):
            return False

        def join(self, timeout):
            pass

    clock = [1000.0]
    starts: list[int] = []
    monkeypatch.setattr(noise_guard, "_unavailable_until", 0.0)
    monkeypatch.setattr(noise_guard.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(noise_guard, "_start", lambda *a: (starts.append(1), (Process(), Mute()))[1])
    rules = [NoiseRule("a", "x")]
    assert noise_guard.count_hits([_side("x")], rules) == {"a": noise_guard.UNAVAILABLE}
    assert len(starts) == 1
    clock[0] += noise_guard.LATCH_S - 1
    assert noise_guard.count_hits([_side("x")], rules) == {"a": noise_guard.UNAVAILABLE}
    assert len(starts) == 1, "inside the latch no child is started (and nothing waits START_S)"
    clock[0] += 2
    noise_guard.count_hits([_side("x")], rules)
    assert len(starts) == 2, "after the latch a child is tried again"


def test_a_child_that_cannot_start_is_retried_at_once(monkeypatch: pytest.MonkeyPatch):
    """A failed spawn costs nothing: no latch, the next call tries again."""
    calls: list[int] = []

    def broken(*_a, **_k):
        calls.append(1)
        raise OSError("spawn non disponibile")

    monkeypatch.setattr(noise_guard, "_unavailable_until", 0.0)
    monkeypatch.setattr(noise_guard, "_start", broken)
    for _ in range(2):
        assert noise_guard.count_hits([_side("x")], [NoiseRule("a", "x")]) == {"a": noise_guard.UNAVAILABLE}
    assert len(calls) == 2


def test_duplicate_names_are_refused():
    with pytest.raises(ValueError, match="stesso nome"):
        noise_guard.count_hits([_side("x")], [NoiseRule("a", "x"), NoiseRule("a", "y")])


@pytest.mark.parametrize("script", ["scripts/entrypoint.py", "src/qtrequestory/__main__.py"])
def test_the_entry_scripts_support_frozen_child_processes(script: str):
    """A spawned child of the frozen exe re-runs the entry script: it must
    call ``multiprocessing.freeze_support()`` first, under a main guard."""
    text = (ROOT / script).read_text(encoding="utf-8")
    guard = text.index('if __name__ == "__main__":')
    support = text.index("multiprocessing.freeze_support()")
    assert guard < support < text.index("main()", support)
    assert not re.search(r"^raise SystemExit", text, re.MULTILINE), "nothing may run at import time"
