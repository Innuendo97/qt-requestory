"""The Hungarian algorithm, written here (spec §4.2 step 7): no scipy.

:func:`solve` finds the assignment of rows to distinct columns with the
minimum total cost. Rectangular matrices are allowed: with more rows than
columns some rows stay unassigned (``-1``); with more columns than rows every
row is assigned.

This is the shortest-augmenting-path form with row and column potentials
(Kuhn–Munkres as refined by Jonker–Volgenant), O(n²·m) for n ≤ m rows: each
row is added in turn and a Dijkstra-like search over reduced costs finds the
cheapest way to make room for it. It is deterministic — no randomness, no
set or dict ordering — so equal inputs give equal assignments, ties included.

Stdlib only; no Qt, no pypdfium2.
"""
from __future__ import annotations

import math
from collections.abc import Sequence

__all__ = ["solve", "solve_with_potentials"]


def solve(cost: Sequence[Sequence[float]]) -> list[int]:
    """For each row, the column assigned to it (``-1`` = unassigned).

    ``cost`` is a list of rows of equal length holding finite numbers;
    raises ``ValueError`` otherwise.
    """
    return solve_with_potentials(cost)[0]


def solve_with_potentials(cost: Sequence[Sequence[float]]) -> tuple[list[int], list[float], list[float]]:
    """:func:`solve`, plus the row potentials ``u`` and column potentials
    ``v`` that certify optimality (``u[i] + v[j] <= cost[i][j]``, equal on
    every assigned pair, ``v[j] <= 0`` and ``0`` on unassigned columns).

    For more rows than columns the problem is solved on the transpose; the
    potentials are then those of the transposed problem (rows ↔ columns).
    """
    rows = [list(map(float, row)) for row in cost]
    n = len(rows)
    if n == 0:
        return [], [], []
    m = len(rows[0])
    if any(len(row) != m for row in rows):
        raise ValueError("matrice dei costi non rettangolare")
    if any(not math.isfinite(c) for row in rows for c in row):
        raise ValueError("matrice dei costi con valori non finiti")
    if m == 0:
        return [-1] * n, [0.0] * n, []
    if n > m:
        transposed = [list(col) for col in zip(*rows, strict=True)]
        cols, u, v = _solve(transposed)
        assignment = [-1] * n
        for j, i in enumerate(cols):
            assignment[i] = j
        return assignment, u, v
    return _solve(rows)


def _solve(cost: list[list[float]]) -> tuple[list[int], list[float], list[float]]:
    """Rows ≤ columns. 1-based internally; column 0 is the virtual start."""
    n, m = len(cost), len(cost[0])
    inf = math.inf
    u = [0.0] * (n + 1)
    v = [0.0] * (m + 1)
    owner = [0] * (m + 1)   # owner[j] = row assigned to column j (0 = free)
    way = [0] * (m + 1)     # previous column on the augmenting path
    for i in range(1, n + 1):
        owner[0] = i
        j0 = 0
        minv = [inf] * (m + 1)
        used = [False] * (m + 1)
        while True:
            used[j0] = True
            i0 = owner[j0]
            row = cost[i0 - 1]
            ui0 = u[i0]
            delta, j1 = inf, 0
            for j in range(1, m + 1):
                if used[j]:
                    continue
                reduced = row[j - 1] - ui0 - v[j]
                if reduced < minv[j]:
                    minv[j] = reduced
                    way[j] = j0
                if minv[j] < delta:  # strict: the lowest column wins a tie
                    delta, j1 = minv[j], j
            for j in range(m + 1):
                if used[j]:
                    u[owner[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if owner[j0] == 0:
                break
        while j0:  # flip the augmenting path
            j1 = way[j0]
            owner[j0] = owner[j1]
            j0 = j1
    assignment = [-1] * n
    for j in range(1, m + 1):
        if owner[j]:
            assignment[owner[j] - 1] = j - 1
    return assignment, u[1:], v[1:]
