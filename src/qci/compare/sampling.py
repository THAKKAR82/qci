"""Sampling floor for TVD: how large TVD is expected to be from multinomial sampling alone.

H0: both runs sampled one shared distribution. Under H0 the shared distribution is estimated by
the pooled plug-in estimate (merged counts over merged total), and each run is resampled from
it at its own shot count. The result is evidence about the observed samples at these shot
counts. It is not a verdict and makes no causal claim.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from qci.compare.distribution import total_variation_distance
from qci.core.hashing import HASH_PREFIX
from qci.domain.comparison import MIN_DISTRIBUTION_NULL_RESAMPLES

MIN_RESAMPLES = MIN_DISTRIBUTION_NULL_RESAMPLES
QUANTILES = (0.5, 0.95, 0.99)
# Absolute tolerance so that a null TVD equal to the observed TVD up to float rounding counts.
P_VALUE_TOLERANCE = 1e-12
# 53 bits: every seed is an exactly representable JSON number, even for float64 readers.
SEED_BITS = 53
_COMPARISON_ID = re.compile(re.escape(HASH_PREFIX) + r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class SamplingFloorResult:
    """Null TVD quantiles and Monte Carlo p-value. Internal; domain models come in M1.1b."""

    observed_tvd: float
    null_p50: float
    null_p95: float
    null_p99: float
    p_value: float
    resamples: int
    seed: int
    baseline_shots: int
    candidate_shots: int
    outcomes: int
    numpy_version: str


def seed_from_comparison_id(comparison_id: str) -> int:
    """Derive the resampling seed from a ``comparison_id``.

    ``comparison_id`` is ``qci.core.hashing.hash_json`` output: ``"sha256:"`` followed by 64
    lowercase hex digits. The seed is the leading 53 bits of that 256-bit digest read as an
    unsigned big-endian integer: ``int(hex_digest, 16) >> (256 - 53)``, in ``[0, 2**53)``.
    Pure and deterministic. Raises ``ValueError`` for any other format.
    """
    if not _COMPARISON_ID.fullmatch(comparison_id):
        raise ValueError(
            f"comparison_id must be {HASH_PREFIX!r} followed by 64 lowercase hex digits, "
            f"got {comparison_id!r}"
        )
    digest = int(comparison_id.removeprefix(HASH_PREFIX), 16)
    return digest >> (256 - SEED_BITS)


def _shots(side: str, counts: Mapping[str, int]) -> int:
    if not counts:
        raise ValueError(f"{side} counts are empty")
    if any(v < 0 for v in counts.values()):
        raise ValueError(f"{side} counts contain a negative count")
    total = sum(counts.values())
    if total == 0:
        raise ValueError(f"{side} counts have a zero total")
    return total


def _resample(
    rng: np.random.Generator, shots: int, pooled: NDArray[np.float64], resamples: int
) -> NDArray[np.int64]:
    """Draw ``resamples`` multinomial(shots, pooled) count vectors, one per row."""
    return rng.multinomial(shots, pooled, size=resamples)


def tvd_sampling_floor(
    baseline_counts: Mapping[str, int],
    candidate_counts: Mapping[str, int],
    *,
    resamples: int,
    seed: int,
) -> SamplingFloorResult:
    """Null distribution of TVD under H0 (one shared distribution) at the observed shot counts.

    Outcomes are ordered lexicographically. With ``numpy.random.Generator(PCG64(seed))``, all
    baseline resamples are drawn first (multinomial at the baseline shot count), then all
    candidate resamples (at the candidate shot count). Resample ``i`` pairs row ``i`` of each.
    Quantiles use ``numpy.quantile(method="linear")``. The Monte Carlo p-value is
    ``(1 + #{null_tvd >= observed_tvd - 1e-12}) / (resamples + 1)``.
    """
    if resamples < MIN_RESAMPLES:
        raise ValueError(f"resamples must be at least {MIN_RESAMPLES}, got {resamples}")
    if seed < 0:
        raise ValueError(f"seed must be non-negative, got {seed}")
    n_baseline = _shots("baseline", baseline_counts)
    n_candidate = _shots("candidate", candidate_counts)

    outcomes = sorted(baseline_counts.keys() | candidate_counts.keys())
    merged = np.array(
        [baseline_counts.get(k, 0) + candidate_counts.get(k, 0) for k in outcomes],
        dtype=np.float64,
    )
    pooled = merged / merged.sum()

    observed = total_variation_distance(
        {k: v / n_baseline for k, v in baseline_counts.items()},
        {k: v / n_candidate for k, v in candidate_counts.items()},
    )

    rng = np.random.Generator(np.random.PCG64(seed))
    b_draws = _resample(rng, n_baseline, pooled, resamples) / n_baseline
    c_draws = _resample(rng, n_candidate, pooled, resamples) / n_candidate
    null = np.array(
        [
            total_variation_distance(
                dict(zip(outcomes, b.tolist(), strict=True)),
                dict(zip(outcomes, c.tolist(), strict=True)),
            )
            for b, c in zip(b_draws, c_draws, strict=True)
        ],
        dtype=np.float64,
    )

    p50, p95, p99 = (float(x) for x in np.quantile(null, QUANTILES, method="linear"))
    exceed = int(np.count_nonzero(null >= observed - P_VALUE_TOLERANCE))
    return SamplingFloorResult(
        observed_tvd=observed,
        null_p50=p50,
        null_p95=p95,
        null_p99=p99,
        p_value=(1 + exceed) / (resamples + 1),
        resamples=resamples,
        seed=seed,
        baseline_shots=n_baseline,
        candidate_shots=n_candidate,
        outcomes=len(outcomes),
        numpy_version=np.__version__,
    )
