"""Exact statistics of the M1.5d calibration-history experiment.

See docs/experiments/2026-10-calibration-history.md, "Exact statistics". Every function
returns a value only where the design defines it, otherwise ``Stat(None, reason)``. Nothing
here knows about stores, devices or parameters.
"""

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

TOO_FEW = "too_few_measurements"
NON_POSITIVE_MINIMUM = "non_positive_minimum"
NON_POSITIVE_MEAN = "non_positive_mean"
ALL_TIED = "all_values_tied"


@dataclass(frozen=True)
class Stat:
    """A statistic, or the reason it is undefined. Exactly one of the two is set."""

    value: float | None
    reason: str | None = None

    def to_json(self) -> float | str:
        return self.value if self.value is not None else f"undefined: {self.reason}"


def mean(xs: Sequence[float]) -> float:
    return math.fsum(xs) / len(xs)


def sample_sd(xs: Sequence[float]) -> Stat:
    """n - 1 convention. Defined for n >= 2."""
    n = len(xs)
    if n < 2:
        return Stat(None, TOO_FEW)
    m = mean(xs)
    return Stat(math.sqrt(math.fsum((x - m) ** 2 for x in xs) / (n - 1)))


def coefficient_of_variation(xs: Sequence[float]) -> Stat:
    """s / m. Defined for n >= 2 and m > 0."""
    s = sample_sd(xs)
    if s.value is None:
        return s
    m = mean(xs)
    if m <= 0:
        return Stat(None, NON_POSITIVE_MEAN)
    return Stat(s.value / m)


def max_min_ratio(xs: Sequence[float]) -> Stat:
    """max / min. Defined for n >= 2 and min > 0."""
    if len(xs) < 2:
        return Stat(None, TOO_FEW)
    low = min(xs)
    if low <= 0:
        return Stat(None, NON_POSITIVE_MINIMUM)
    return Stat(max(xs) / low)


def successive_spread(xs: Sequence[float]) -> Stat:
    """d / m, with d = sqrt(sum (x_{k+1} - x_k)^2 / (2 (n - 1))). Defined for n >= 3, m > 0."""
    n = len(xs)
    if n < 3:
        return Stat(None, TOO_FEW)
    m = mean(xs)
    if m <= 0:
        return Stat(None, NON_POSITIVE_MEAN)
    d = math.sqrt(math.fsum((xs[k + 1] - xs[k]) ** 2 for k in range(n - 1)) / (2 * (n - 1)))
    return Stat(d / m)


def median(xs: Sequence[float]) -> float | None:
    """The middle value, or the mean of the two middle values. None for an empty list."""
    if not xs:
        return None
    ordered = sorted(xs)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def quartiles(xs: Sequence[float]) -> tuple[float, float, float] | None:
    """Q1, Q2, Q3 by linear interpolation between order statistics (Hyndman-Fan type 7)."""
    if not xs:
        return None
    q = np.quantile(np.asarray(xs, dtype=float), [0.25, 0.5, 0.75], method="linear")
    return float(q[0]), float(q[1]), float(q[2])


def _tie_pairs(values: Sequence[float]) -> int:
    return sum(t * (t - 1) // 2 for t in Counter(values).values())


def kendall_tau_b(a: Sequence[float], b: Sequence[float]) -> Stat:
    """(n_c - n_d) / sqrt((n_0 - n_1) (n_0 - n_2)), equality being exact float equality.
    Defined for n >= 3 and a positive denominator."""
    if len(a) != len(b):
        raise ValueError("kendall_tau_b needs paired lists of equal length")
    n = len(a)
    if n < 3:
        return Stat(None, TOO_FEW)
    xa = np.asarray(a, dtype=float)
    xb = np.asarray(b, dtype=float)
    upper = np.triu_indices(n, k=1)
    product = (np.sign(xa[:, None] - xa[None, :]) * np.sign(xb[:, None] - xb[None, :]))[upper]
    n_c = int(np.count_nonzero(product > 0))
    n_d = int(np.count_nonzero(product < 0))
    n_0 = n * (n - 1) // 2
    denominator = (n_0 - _tie_pairs(a)) * (n_0 - _tie_pairs(b))
    if denominator <= 0:
        return Stat(None, ALL_TIED)
    return Stat((n_c - n_d) / math.sqrt(denominator))
