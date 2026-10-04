"""Wilson and Newcombe intervals: integer (k, n) arguments only, no bitstrings anywhere."""

import math

import numpy as np
import pytest

from qci.compare.proportions import WILSON_Z_95, newcombe_difference, wilson_interval


def _wilson_by_quadratic(k: int, n: int, z: float) -> tuple[float, float]:
    """Independent check: the roots in p of (p_hat - p)^2 = z^2 p (1 - p) / n."""
    p_hat = k / n
    a = 1 + z * z / n
    b = -(2 * p_hat + z * z / n)
    c = p_hat * p_hat
    root = math.sqrt(b * b - 4 * a * c)
    return (-b - root) / (2 * a), (-b + root) / (2 * a)


@pytest.mark.parametrize(("k", "n"), [(5, 10), (0, 10), (10, 10), (3, 17), (900, 1000)])
def test_wilson_matches_independent_quadratic_solution(k: int, n: int) -> None:
    lower, upper = wilson_interval(k, n)
    expected = _wilson_by_quadratic(k, n, WILSON_Z_95)
    assert lower == pytest.approx(max(0.0, expected[0]), abs=1e-12)
    assert upper == pytest.approx(min(1.0, expected[1]), abs=1e-12)


def test_wilson_reference_values() -> None:
    assert wilson_interval(5, 10) == pytest.approx((0.2366, 0.7634), abs=5e-5)
    lower, upper = wilson_interval(0, 10)
    assert lower == 0.0
    assert upper == pytest.approx(0.2775, abs=5e-5)


def test_z_is_the_two_sided_95_percent_normal_quantile() -> None:
    # Phi(z) = 0.975, checked with the standard library's error function.
    assert 0.5 * (1 + math.erf(WILSON_Z_95 / math.sqrt(2))) == pytest.approx(0.975, abs=1e-15)


def test_newcombe_reference_example() -> None:
    # Newcombe (1998), Statistics in Medicine 17:873-890, example 56/70 - 48/80, method 10:
    # difference 0.2000, interval 0.0524 to 0.3339.
    d, lower, upper = newcombe_difference(48, 80, 56, 70)
    assert d == pytest.approx(0.2)
    assert lower == pytest.approx(0.0524, abs=5e-5)
    assert upper == pytest.approx(0.3339, abs=5e-5)


def test_newcombe_is_directional() -> None:
    d, lower, upper = newcombe_difference(56, 70, 48, 80)
    assert (d, lower, upper) == pytest.approx((-0.2, -0.3339, -0.0524), abs=5e-5)


@pytest.mark.parametrize("bad", [5.0, True, np.int64(5), "5"])
def test_only_int_arguments_are_accepted(bad: object) -> None:
    with pytest.raises(TypeError):
        wilson_interval(bad, 10)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        wilson_interval(5, bad)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        newcombe_difference(5, 10, bad, 10)  # type: ignore[arg-type]


@pytest.mark.parametrize(("k", "n"), [(-1, 10), (11, 10), (0, 0), (0, -3)])
def test_out_of_range_counts_are_rejected(k: int, n: int) -> None:
    with pytest.raises(ValueError):
        wilson_interval(k, n)


def test_wilson_coverage_at_p_0_9_n_1000() -> None:
    rng = np.random.default_rng(20261004)
    p, n, trials = 0.9, 1000, 2000
    covered = 0
    for k in rng.binomial(n, p, size=trials):
        lower, upper = wilson_interval(int(k), n)
        covered += lower <= p <= upper
    assert 0.93 <= covered / trials <= 0.97


def test_newcombe_coverage() -> None:
    rng = np.random.default_rng(20261005)
    p_b, p_c, n, trials = 0.9, 0.85, 1000, 2000
    ks_b = rng.binomial(n, p_b, size=trials)
    ks_c = rng.binomial(n, p_c, size=trials)
    covered = 0
    for kb, kc in zip(ks_b, ks_c, strict=True):
        _, lower, upper = newcombe_difference(int(kb), n, int(kc), n)
        covered += lower <= p_c - p_b <= upper
    assert covered / trials >= 0.93
