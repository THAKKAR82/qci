"""Divergences between two probability distributions over outcome keys.

Pure functions on ``{outcome: probability}`` mappings. Missing outcomes have probability 0, and
outcomes are summed in sorted order so results are deterministic.
"""

import math


def total_variation_distance(p: dict[str, float], q: dict[str, float]) -> float:
    """TVD = 1/2 * sum_x |p(x) - q(x)|."""
    return 0.5 * sum(abs(p.get(k, 0.0) - q.get(k, 0.0)) for k in sorted(p.keys() | q.keys()))


def hellinger_distance(p: dict[str, float], q: dict[str, float]) -> float:
    """H = sqrt(1/2 * sum_x (sqrt p(x) - sqrt q(x))^2), in [0, 1]. Not Qiskit's
    ``hellinger_fidelity``."""
    total = sum(
        (math.sqrt(p.get(k, 0.0)) - math.sqrt(q.get(k, 0.0))) ** 2
        for k in sorted(p.keys() | q.keys())
    )
    return min(1.0, math.sqrt(0.5 * total))
