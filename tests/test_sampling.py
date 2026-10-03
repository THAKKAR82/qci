"""Sampling floor for TVD (M1.1a): the pure statistics core."""

from collections.abc import Mapping

import numpy as np
import pytest
from numpy.typing import NDArray

from qci.compare import sampling
from qci.compare.sampling import (
    SamplingFloorResult,
    seed_from_comparison_id,
    tvd_sampling_floor,
)
from qci.core.hashing import hash_json

B = 500


def floor(
    baseline: Mapping[str, int], candidate: Mapping[str, int], *, seed: int = 1, resamples: int = B
) -> SamplingFloorResult:
    return tvd_sampling_floor(baseline, candidate, resamples=resamples, seed=seed)


def sample_counts(
    rng: np.random.Generator, probs: Mapping[str, float], shots: int
) -> dict[str, int]:
    keys = sorted(probs)
    draws = rng.multinomial(shots, [probs[k] for k in keys])
    return {k: int(n) for k, n in zip(keys, draws, strict=True) if n > 0}


# --- seed derivation ---------------------------------------------------------------------------


def test_seed_is_leading_64_bits_of_the_comparison_digest() -> None:
    cid = hash_json({"baseline_run_id": "A", "candidate_run_id": "B"})
    seed = seed_from_comparison_id(cid)
    assert seed == int(cid.removeprefix("sha256:")[:16], 16)
    assert 0 <= seed < 2**64
    assert seed_from_comparison_id(cid) == seed
    assert seed_from_comparison_id(hash_json({"other": 1})) != seed


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "abc",
        "sha256:",
        "sha256:" + "a" * 63,
        "sha256:" + "A" * 64,
        "md5:" + "a" * 64,
        "sha256:" + "a" * 65,
        "sha256:" + "g" * 64,
    ],
)
def test_seed_derivation_rejects_malformed_ids(bad: str) -> None:
    with pytest.raises(ValueError, match="comparison_id"):
        seed_from_comparison_id(bad)


# --- input validation --------------------------------------------------------------------------


@pytest.mark.parametrize("resamples", [-1, 0, 99])
def test_too_few_resamples_rejected(resamples: int) -> None:
    with pytest.raises(ValueError, match="resamples must be at least 100"):
        floor({"0": 1}, {"0": 1}, resamples=resamples)


def test_minimum_resamples_accepted() -> None:
    assert floor({"0": 5, "1": 5}, {"0": 5, "1": 5}, resamples=100).resamples == 100


@pytest.mark.parametrize(
    ("baseline", "candidate", "message"),
    [
        ({}, {"0": 1}, "baseline counts are empty"),
        ({"0": 1}, {}, "candidate counts are empty"),
        ({"0": 0, "1": 0}, {"0": 1}, "baseline counts have a zero total"),
        ({"0": 1}, {"0": 0}, "candidate counts have a zero total"),
        ({"0": 2, "1": -1}, {"0": 1}, "baseline counts contain a negative count"),
    ],
)
def test_empty_zero_total_or_negative_counts_rejected(
    baseline: dict[str, int], candidate: dict[str, int], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        floor(baseline, candidate)


def test_negative_seed_rejected() -> None:
    with pytest.raises(ValueError, match="seed must be non-negative"):
        floor({"0": 1}, {"0": 1}, seed=-1)


# --- behaviour ---------------------------------------------------------------------------------


def test_identical_counts_give_p_value_one_and_nonzero_null_quantiles() -> None:
    counts = {"00": 480, "01": 20, "10": 25, "11": 475}
    r = floor(counts, dict(counts))
    assert r.observed_tvd == 0.0
    assert r.p_value == 1.0
    assert 0.0 < r.null_p50 <= r.null_p95 <= r.null_p99
    assert (r.baseline_shots, r.candidate_shots, r.outcomes) == (1000, 1000, 4)
    assert r.numpy_version == np.__version__


def test_strongly_different_large_samples_give_minimum_p_value() -> None:
    r = floor({"00": 9000, "11": 1000}, {"00": 1000, "11": 9000})
    assert r.observed_tvd == pytest.approx(0.8)
    assert r.p_value == 1 / (B + 1)
    assert r.null_p99 < r.observed_tvd


def test_unequal_shots_are_each_resampled_at_their_own_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, list[float], int]] = []
    real = sampling._resample

    def spy(
        rng: np.random.Generator, shots: int, pooled: NDArray[np.float64], resamples: int
    ) -> NDArray[np.int64]:
        draws = real(rng, shots, pooled, resamples)
        assert (draws.sum(axis=1) == shots).all()
        calls.append((shots, pooled.tolist(), resamples))
        return draws

    monkeypatch.setattr(sampling, "_resample", spy)
    r = floor({"0": 30, "1": 70}, {"0": 2500, "1": 2500, "2": 5000})
    # Baseline first at its own size, then candidate at its own size, from one pooled vector
    # over lexicographically ordered outcomes.
    pooled = [2530 / 10100, 2570 / 10100, 5000 / 10100]
    assert [(n, k) for n, _, k in calls] == [(100, B), (10000, B)]
    for _, p, _ in calls:
        assert p == pytest.approx(pooled)
    assert (r.baseline_shots, r.candidate_shots, r.outcomes) == (100, 10000, 3)


def test_unequal_shots_floor_is_dominated_by_the_smaller_run() -> None:
    counts = {"0": 50, "1": 50}
    small = floor(counts, counts)
    big = floor({"0": 5000, "1": 5000}, {"0": 5000, "1": 5000})
    mixed = floor(counts, {"0": 5000, "1": 5000})
    assert big.null_p95 < mixed.null_p95 < small.null_p95


def test_same_inputs_give_identical_output() -> None:
    b = {"00": 480, "01": 20, "10": 25, "11": 475}
    c = {"00": 450, "01": 30, "10": 10, "11": 510}
    first = floor(b, c, seed=12345)
    assert floor(b, c, seed=12345) == first
    # Input mapping order does not matter: outcomes are ordered lexicographically.
    assert floor(dict(reversed(b.items())), dict(reversed(c.items())), seed=12345) == first
    assert floor(b, c, seed=12346) != first


def test_seed_from_comparison_id_is_accepted_by_the_floor() -> None:
    seed = seed_from_comparison_id(hash_json({"x": 1}))
    r = floor({"0": 50, "1": 50}, {"0": 40, "1": 60}, seed=seed)
    assert r.seed == seed


# --- calibration and power ---------------------------------------------------------------------

# Noisy-GHZ-like: two dominant outcomes plus a sparse tail of 30 rare error outcomes.
_TAIL = [format(i, "05b") for i in range(1, 31)]
NULL_DIST = {"00000": 0.45, "11111": 0.45, **{k: 0.10 / 30 for k in _TAIL}}
CALIBRATION_PAIRS = 200
CALIBRATION_SHOTS = 1000

# Two-bit GHZ-like pair. True TVD between them is 0.08.
POWER_BASELINE = {"00": 0.48, "01": 0.02, "10": 0.02, "11": 0.48}
POWER_CANDIDATE = {"00": 0.40, "01": 0.02, "10": 0.02, "11": 0.56}
POWER_TRIALS = 100
POWER_SHOTS = 1000


def false_positive_rate() -> float:
    rng = np.random.Generator(np.random.PCG64(20261001))
    hits = 0
    for i in range(CALIBRATION_PAIRS):
        b = sample_counts(rng, NULL_DIST, CALIBRATION_SHOTS)
        c = sample_counts(rng, NULL_DIST, CALIBRATION_SHOTS)
        hits += floor(b, c, seed=i).p_value < 0.05
    return hits / CALIBRATION_PAIRS


def power() -> float:
    rng = np.random.Generator(np.random.PCG64(20261002))
    hits = 0
    for i in range(POWER_TRIALS):
        b = sample_counts(rng, POWER_BASELINE, POWER_SHOTS)
        c = sample_counts(rng, POWER_CANDIDATE, POWER_SHOTS)
        hits += floor(b, c, seed=i).p_value < 0.05
    return hits / POWER_TRIALS


def test_false_positive_calibration() -> None:
    """200 seeded pairs from one distribution, B=500: the fraction with p < 0.05 is in
    [0.01, 0.10]."""
    rate = false_positive_rate()
    assert 0.01 <= rate <= 0.10, f"false-positive rate {rate}"


def test_power_against_a_known_shift() -> None:
    """True TVD 0.08 at 1000 shots per side, B=500: p < 0.05 in at least 80% of 100 trials."""
    rate = power()
    assert rate >= 0.80, f"power {rate}"
