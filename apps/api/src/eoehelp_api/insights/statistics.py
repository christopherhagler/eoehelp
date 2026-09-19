"""The statistics behind food patterns: small, exact, and standard library only.

A *block* is one 28-day stretch of analyzable days, in date order, as two
parallel 0/1 sequences: `exposure` (the food was in the lag window) and
`outcome` (a symptom day). Blocks let slow changes, such as a new treatment or
a flare, be absorbed rather than credited to a food. See
docs/plans/2026-09-19-insights-food-patterns.md, "Method".
"""

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

Block = tuple[Sequence[int], Sequence[int]]

# One-sided 95%.
Z_95 = 1.6448536269514722


def _aligned(exposure: Sequence[int], outcome: Sequence[int]) -> int:
    return sum(e * y for e, y in zip(exposure, outcome, strict=True))


def shift_distribution(exposure: Sequence[int], outcome: Sequence[int]) -> dict[int, float]:
    """Exposed symptom days under every circular shift of `exposure`, equally weighted.

    Every offset from 0 to n - 1 is included, the unshifted one too. That is
    what makes the shifts a group and the test a valid randomization test;
    dropping the short shifts was measured to flag 40% of trigger-free patients.
    """
    n = len(exposure)
    counts: dict[int, int] = defaultdict(int)
    for shift in range(n):
        counts[sum(exposure[(i + shift) % n] * outcome[i] for i in range(n))] += 1
    return {value: count / n for value, count in counts.items()}


def shift_test(blocks: Sequence[Block]) -> float:
    """One-sided p that exposure lines up with symptom days more than chance.

    The null shifts each block's exposure independently, which keeps the runs
    in both series (a meal feeds a three-day window; a flare lasts a week) and
    breaks only their alignment. The distribution of the total is the exact
    convolution of the blocks' distributions: no random draws.
    """
    distribution: dict[int, float] = {0: 1.0}
    observed = 0
    for exposure, outcome in blocks:
        observed += _aligned(exposure, outcome)
        block = shift_distribution(exposure, outcome) if exposure else {0: 1.0}
        combined: dict[int, float] = defaultdict(float)
        for total, p_total in distribution.items():
            for value, p_value in block.items():
                combined[total + value] += p_total * p_value
        distribution = combined
    return min(1.0, sum(p for total, p in distribution.items() if total >= observed))


@dataclass(frozen=True)
class RiskDifference:
    """Mantel-Haenszel risk difference over informative blocks, with Sato's variance."""

    estimate: float
    variance: float
    # Days in blocks that hold both exposed and unexposed days. Blocks that are
    # all one or the other say nothing about the difference, so they do not
    # count toward the minimums either.
    exposed_days: int
    unexposed_days: int

    def upper_bound(self, inflation: float) -> float:
        return self.estimate + Z_95 * math.sqrt(self.variance) * inflation


def mantel_haenszel_rd(blocks: Sequence[Block]) -> RiskDifference | None:
    weight = numerator = p_term = q_term = 0.0
    exposed_total = unexposed_total = 0
    for exposure, outcome in blocks:
        n1 = sum(exposure)
        n0 = len(exposure) - n1
        if n1 == 0 or n0 == 0:
            continue
        n = n1 + n0
        a = sum(1 for e, y in zip(exposure, outcome, strict=True) if e and y)
        c = sum(1 for e, y in zip(exposure, outcome, strict=True) if not e and y)
        weight += n1 * n0 / n
        numerator += (a * n0 - c * n1) / n
        p_term += (n1 * n1 * c - n0 * n0 * a + n1 * n0 * (n0 - n1) / 2) / (n * n)
        q_term += (a * (n0 - c) + c * (n1 - a)) / (2 * n)
        exposed_total += n1
        unexposed_total += n0
    if weight == 0:
        return None
    estimate = numerator / weight
    # Sato (1989). Clamped: with very few days the formula can dip below zero.
    variance = max((estimate * p_term + q_term) / (weight * weight), 0.0)
    return RiskDifference(estimate, variance, exposed_total, unexposed_total)


def benjamini_hochberg(p_values: Sequence[float]) -> list[float]:
    """q-values for a family of tests, in the order given."""
    m = len(p_values)
    order = sorted(range(m), key=lambda i: p_values[i])
    q_values = [0.0] * m
    running = 1.0
    for rank in range(m, 0, -1):
        index = order[rank - 1]
        running = min(running, p_values[index] * m / rank)
        q_values[index] = running
    return q_values
