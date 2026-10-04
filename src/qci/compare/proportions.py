"""Interval estimates for binomial proportions, on integer (k, n) arguments only.

These functions know nothing about bitstrings. Any observable that reduces to k events in n
trials (a bitstring-set probability today, a logical error rate later) reuses them unchanged
(ADR 0006).
"""

import math

WILSON_Z_95 = 1.959963984540054
"""Two-sided 95% standard normal quantile."""


def _check_counts(k: int, n: int) -> None:
    for name, value in (("k", k), ("n", n)):
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(f"{name} must be an int, got {type(value).__name__}")
    if n <= 0:
        raise ValueError(f"n must be positive, got {n}")
    if not 0 <= k <= n:
        raise ValueError(f"k must satisfy 0 <= k <= n, got k={k}, n={n}")


def wilson_interval(k: int, n: int, z: float = WILSON_Z_95) -> tuple[float, float]:
    """Wilson score interval for k successes in n trials: (lower, upper)."""
    _check_counts(k, n)
    z2 = z * z
    p = k / n
    denominator = n + z2
    center = (k + z2 / 2) / denominator
    half = z / denominator * math.sqrt(n * p * (1 - p) + z2 / 4)
    return max(0.0, center - half), min(1.0, center + half)


def newcombe_difference(
    k_baseline: int, n_baseline: int, k_candidate: int, n_candidate: int, z: float = WILSON_Z_95
) -> tuple[float, float, float]:
    """Candidate minus baseline proportion, with Newcombe's hybrid score interval.

    Returns (difference, lower, upper), built from the two Wilson intervals:
    lower = d - sqrt((p_c - l_c)^2 + (u_b - p_b)^2) and
    upper = d + sqrt((u_c - p_c)^2 + (p_b - l_b)^2).
    """
    _check_counts(k_baseline, n_baseline)
    _check_counts(k_candidate, n_candidate)
    p_b, p_c = k_baseline / n_baseline, k_candidate / n_candidate
    l_b, u_b = wilson_interval(k_baseline, n_baseline, z)
    l_c, u_c = wilson_interval(k_candidate, n_candidate, z)
    d = p_c - p_b
    lower = d - math.sqrt((p_c - l_c) ** 2 + (u_b - p_b) ** 2)
    upper = d + math.sqrt((u_c - p_c) ** 2 + (p_b - l_b) ** 2)
    return d, lower, upper
