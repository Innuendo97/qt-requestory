"""The home-grown Hungarian algorithm (spec §4.2 step 7, no scipy)."""
from __future__ import annotations

import itertools
import math
import random

import pytest

from qtrequestory.officina.compare import hungarian
from qtrequestory.officina.compare.hungarian import solve


def _total(cost: list[list[float]], assignment: list[int]) -> float:
    return sum(cost[i][j] for i, j in enumerate(assignment) if j >= 0)


def _brute_force(cost: list[list[float]]) -> float:
    """Minimum total over every way of assigning min(n, m) rows to distinct columns."""
    n, m = len(cost), len(cost[0])
    best = math.inf
    if n <= m:
        for cols in itertools.permutations(range(m), n):
            best = min(best, sum(cost[i][c] for i, c in enumerate(cols)))
    else:
        for rows in itertools.permutations(range(n), m):
            best = min(best, sum(cost[r][j] for j, r in enumerate(rows)))
    return best


def _valid(assignment: list[int], n: int, m: int) -> None:
    assert len(assignment) == n
    used = [j for j in assignment if j >= 0]
    assert len(used) == len(set(used)) == min(n, m)
    assert all(-1 <= j < m for j in assignment)


def test_known_three_by_three():
    cost = [[4, 1, 3], [2, 0, 5], [3, 2, 2]]
    assert solve(cost) == [1, 0, 2]


def test_known_four_by_two_leaves_rows_unassigned():
    cost = [[5, 9], [1, 8], [7, 2], [6, 6]]
    assert solve(cost) == [-1, 0, 1, -1]


def test_known_two_by_four():
    cost = [[3, 1, 4, 1.5], [2, 7, 1, 8]]
    assert solve(cost) == [1, 2]


def test_negative_costs_are_fine():
    cost = [[-0.5, 0.0], [0.0, -0.2]]
    assert solve(cost) == [0, 1]


def test_empty_inputs():
    assert solve([]) == []
    assert solve([[], []]) == [-1, -1]


@pytest.mark.parametrize("cost", [[[1, 2], [3]], [[1, math.nan]], [[math.inf, 1]]])
def test_malformed_matrices_are_refused(cost):
    with pytest.raises(ValueError):
        solve(cost)


def test_matches_brute_force_on_small_random_matrices():
    rng = random.Random(20260925)
    for _ in range(300):
        n, m = rng.randint(1, 6), rng.randint(1, 6)
        if rng.random() < 0.5:
            cost = [[rng.randint(-3, 9) for _ in range(m)] for _ in range(n)]  # many ties
        else:
            cost = [[rng.uniform(-1, 1) for _ in range(m)] for _ in range(n)]
        assignment = solve(cost)
        _valid(assignment, n, m)
        assert _total(cost, assignment) == pytest.approx(_brute_force(cost), abs=1e-9)


@pytest.mark.parametrize(("n", "m"), [(30, 30), (20, 30)])
def test_random_thirty_is_optimal_by_duality(n: int, m: int):
    """Too big to brute-force: the potentials prove optimality (LP duality)."""
    rng = random.Random(n * 1000 + m)
    cost = [[rng.uniform(0, 100) for _ in range(m)] for _ in range(n)]
    assignment, u, v = hungarian.solve_with_potentials(cost)
    _valid(assignment, n, m)
    eps = 1e-7
    for i in range(n):
        for j in range(m):
            assert u[i] + v[j] <= cost[i][j] + eps  # dual feasible
        assert u[i] + v[assignment[i]] == pytest.approx(cost[i][assignment[i]], abs=eps)  # tight
    assigned = set(assignment)
    for j in range(m):
        assert v[j] <= eps
        if j not in assigned:
            assert v[j] == pytest.approx(0.0, abs=eps)
    assert sum(u) + sum(v) == pytest.approx(_total(cost, assignment), abs=1e-6)


def test_deterministic_on_ties():
    cost = [[1.0] * 5 for _ in range(5)]
    first = solve(cost)
    assert all(solve(cost) == first for _ in range(3))
