"""Distribution metrics and the conservative comparability gate."""

import math

import pytest

from conftest import LOGICAL_BELL_QASM, make_run, physical_bell_qasm, physical_run
from qci.compare.distribution import compare_distributions
from qci.compare.divergence import hellinger_distance, total_variation_distance
from qci.compare.footprint import footprint_for_run
from qci.compare.sampling import tvd_sampling_floor
from qci.domain.comparison import ComparisonPolicy, ComparisonStatus, DistributionComparison
from qci.domain.metric import EvidenceKind
from qci.domain.run import Run, RunError, RunStage, RunStatus

SEED = 12345


def dist(
    baseline: Run, candidate: Run, policy: ComparisonPolicy | None = None
) -> DistributionComparison:
    return compare_distributions(
        baseline,
        candidate,
        footprint_for_run(baseline),
        footprint_for_run(candidate),
        policy or ComparisonPolicy(),
        seed=SEED,
    )


def run(run_id: str, counts: dict[str, dict[str, int]], **kw: object) -> Run:
    return physical_run(run_id, qasm3=physical_bell_qasm(1, 0), counts=counts, **kw)  # type: ignore[arg-type]


def test_metric_values() -> None:
    p = {"00": 0.5, "11": 0.5}
    assert total_variation_distance(p, p) == 0.0 and hellinger_distance(p, p) == 0.0
    assert total_variation_distance({"0": 1.0}, {"1": 1.0}) == 1.0
    assert hellinger_distance({"0": 1.0}, {"1": 1.0}) == pytest.approx(1.0)
    q = {"00": 0.75, "11": 0.25}
    assert total_variation_distance(p, q) == pytest.approx(0.25)
    expected = math.sqrt(
        0.5 * ((math.sqrt(0.5) - math.sqrt(0.75)) ** 2 + (math.sqrt(0.5) - 0.5) ** 2)
    )
    assert hellinger_distance(p, q) == pytest.approx(expected)


def test_identical_counts_are_unchanged_and_metrics_are_labeled() -> None:
    d = dist(run("A", {"c": {"00": 50, "11": 50}}), run("B", {"c": {"00": 50, "11": 50}}))
    assert d.status is ComparisonStatus.UNCHANGED
    assert d.tvd is not None and d.tvd.value == 0.0
    assert d.tvd.kind is EvidenceKind.CALCULATED and d.tvd.method_version == "1"
    assert "no sampling uncertainty" in d.tvd.method
    assert d.hellinger_distance is not None and d.hellinger_distance.value == 0.0


def test_different_counts_and_shots_are_normalized() -> None:
    d = dist(run("A", {"c": {"00": 50, "11": 50}}), run("B", {"c": {"00": 150, "11": 50}}))
    assert d.status is ComparisonStatus.CHANGED
    assert d.tvd is not None and d.tvd.value == pytest.approx(0.25)
    assert (d.baseline_shots, d.candidate_shots) == (100, 200)
    assert any("normalized" in r for r in d.reasons)


GOOD = {"c": {"00": 50, "11": 50}}


@pytest.mark.parametrize(
    ("label", "candidate_kwargs", "reason_fragment"),
    [
        (
            "logical change",
            {"logical_qasm3": LOGICAL_BELL_QASM.replace("h q[0]", "x q[0]")},
            "logical circuit changed",
        ),
        ("logical unknown", {"logical_qasm3": None}, "logical artifact unknown"),
        ("provider", {"provider": "other"}, "providers differ"),
        ("register name", {"counts": {"meas": {"00": 50, "11": 50}}}, "classical registers differ"),
        ("width", {"counts": {"c": {"000": 50, "011": 50}}}, "bitstring widths differ"),
    ],
)
def test_gate_rules_make_distribution_not_comparable(
    label: str, candidate_kwargs: dict[str, object], reason_fragment: str
) -> None:
    kwargs = {"counts": GOOD, **candidate_kwargs}
    candidate = physical_run("B", qasm3=physical_bell_qasm(1, 0), **kwargs)  # type: ignore[arg-type]
    d = dist(run("A", GOOD), candidate)
    assert d.status is ComparisonStatus.NOT_COMPARABLE, label
    assert any(reason_fragment in r for r in d.reasons), d.reasons
    assert d.tvd is None and d.hellinger_distance is None


def test_multiple_registers_are_deferred() -> None:
    counts = {"a": {"0": 50, "1": 50}, "b": {"0": 100}}
    d = dist(run("A", counts), run("B", counts))
    assert d.status is ComparisonStatus.NOT_COMPARABLE
    assert any("multiple classical registers" in r for r in d.reasons)


def test_dynamic_circuit_is_not_comparable() -> None:
    dynamic_qasm = "OPENQASM 3.0;\nbit[2] c;\nc[0] = measure $0;\nif (c[0]) {\n  x $1;\n}\n"
    d = dist(run("A", GOOD), physical_run("B", qasm3=dynamic_qasm, counts=GOOD))
    assert d.status is ComparisonStatus.NOT_COMPARABLE
    assert any("dynamic" in r for r in d.reasons)


def test_failed_run_is_unavailable() -> None:
    failed = make_run(
        "F",
        status=RunStatus.FAILED,
        error=RunError(stage=RunStage.EXECUTE, error_type="E", message="m"),
        execution=None,
        result=None,
    )
    d = dist(run("A", GOOD), failed)
    assert d.status is ComparisonStatus.UNAVAILABLE
    assert d.reasons == ["candidate run has no successful result"]


# --- TVD sampling floor ------------------------------------------------------------------


def test_comparable_distributions_carry_a_statistical_sampling_floor() -> None:
    b, c = {"00": 50, "11": 50}, {"00": 150, "11": 50}
    d = dist(
        run("A", {"c": b}), run("B", {"c": c}), ComparisonPolicy(distribution_null_resamples=300)
    )
    f = d.sampling_floor
    assert f is not None
    assert (f.seed, f.resamples) == (SEED, 300)
    expected = tvd_sampling_floor(b, c, resamples=300, seed=SEED)
    metrics = (f.null_p50, f.null_p95, f.null_p99, f.p_value)
    values = (expected.null_p50, expected.null_p95, expected.null_p99, expected.p_value)
    assert [m.value for m in metrics] == list(values)
    for m in metrics:
        assert m.kind is EvidenceKind.STATISTICAL and m.method
    assert [m.method_version for m in metrics] == ["1", "1", "1", "2"]
    assert f"numpy {expected.numpy_version}" in f.rng
    assert len(f.caveats) == 4
    # The TVD point estimate itself is unchanged.
    assert d.tvd is not None and d.tvd.kind is EvidenceKind.CALCULATED


def test_p_value_uncertainty_is_its_monte_carlo_standard_error() -> None:
    b, c = {"00": 480, "11": 520}, {"00": 520, "11": 480}
    f = dist(run("A", {"c": b}), run("B", {"c": c})).sampling_floor
    assert f is not None
    p, n = f.p_value.value, f.resamples
    assert 0 < p < 1
    assert f.p_value.uncertainty == math.sqrt(p * (1 - p) / (n + 1))
    assert "sqrt(p * (1 - p) / (resamples + 1))" in f.p_value.method
    for quantile in (f.null_p50, f.null_p95, f.null_p99):
        assert quantile.uncertainty is None


def test_p_values_from_two_seeds_agree_within_four_standard_errors() -> None:
    b, c = {"c": {"00": 480, "11": 520}}, {"c": {"00": 520, "11": 480}}
    baseline, candidate = run("A", b), run("B", c)
    p_values = []
    for seed in (1, 2):
        d = compare_distributions(
            baseline,
            candidate,
            footprint_for_run(baseline),
            footprint_for_run(candidate),
            ComparisonPolicy(),
            seed=seed,
        )
        assert d.sampling_floor is not None
        p_values.append(d.sampling_floor.p_value)
    first, second = p_values
    assert first.uncertainty is not None and second.uncertainty is not None
    assert first.value != second.value  # the seeds really give different resamples
    # Standard error of the difference of two independent Monte Carlo estimates.
    se_difference = math.hypot(first.uncertainty, second.uncertainty)
    assert abs(first.value - second.value) <= 4 * se_difference


def test_identical_distributions_still_carry_a_sampling_floor() -> None:
    d = dist(run("A", GOOD), run("B", GOOD))
    assert d.status is ComparisonStatus.UNCHANGED
    assert d.sampling_floor is not None and d.sampling_floor.p_value.value == 1.0


@pytest.mark.parametrize(
    "candidate",
    [
        physical_run(
            "B",
            qasm3=physical_bell_qasm(1, 0),
            counts=GOOD,
            logical_qasm3=LOGICAL_BELL_QASM.replace("h q[0]", "x q[0]"),
        ),
        physical_run("B", qasm3=physical_bell_qasm(1, 0), counts=GOOD, provider="other"),
        physical_run("B", qasm3=physical_bell_qasm(1, 0), counts={"c": {"000": 50, "011": 50}}),
        physical_run(
            "B",
            qasm3="OPENQASM 3.0;\nbit[2] c;\nc[0] = measure $0;\nif (c[0]) {\n  x $1;\n}\n",
            counts=GOOD,
        ),
    ],
    ids=["logical", "provider", "width", "dynamic"],
)
def test_not_comparable_distribution_has_no_sampling_floor(candidate: Run) -> None:
    d = dist(run("A", GOOD), candidate)
    assert d.status is ComparisonStatus.NOT_COMPARABLE
    assert d.sampling_floor is None


def test_unavailable_distribution_has_no_sampling_floor() -> None:
    failed = make_run(
        "F",
        status=RunStatus.FAILED,
        error=RunError(stage=RunStage.EXECUTE, error_type="E", message="m"),
        execution=None,
        result=None,
    )
    d = dist(run("A", GOOD), failed)
    assert d.status is ComparisonStatus.UNAVAILABLE
    assert d.sampling_floor is None


def test_unsupported_reasons_name_the_policy_not_a_version() -> None:
    registers = {"a": {"0": 50, "1": 50}, "b": {"0": 100}}
    dynamic_qasm = "OPENQASM 3.0;\nbit[2] c;\nc[0] = measure $0;\nif (c[0]) {\n  x $1;\n}\n"
    reasons = [
        *dist(run("A", registers), run("B", registers)).reasons,
        *dist(run("A", GOOD), physical_run("B", qasm3=dynamic_qasm, counts=GOOD)).reasons,
    ]
    assert "multiple classical registers are not supported by this comparison policy" in reasons
    assert "dynamic circuits are not supported by this comparison policy" in reasons
    assert not any("v1" in r for r in reasons)


# --- Shared-seed guard (M1.1c) -----------------------------------------------------------

OTHER = {"c": {"00": 40, "11": 60}}


def seeded(run_id: str, seed: int | None, *, qasm3: str | None = None, **kw: object) -> Run:
    return physical_run(
        run_id,
        qasm3=qasm3 or physical_bell_qasm(1, 0),
        seed_simulator=seed,
        **kw,  # type: ignore[arg-type]
    )


def assert_floor_skipped_for_shared_seed(d: DistributionComparison, seed: int) -> None:
    assert d.sampling_floor is None
    assert d.sampling_floor_unavailable_reason == (
        f"both samples were drawn with the same simulator seed ({seed}), so they are not "
        "independent; the sampling floor assumes independent samples"
    )


def assert_floor_computed(d: DistributionComparison) -> None:
    assert d.sampling_floor is not None
    assert d.sampling_floor_unavailable_reason is None


def test_shared_seed_with_different_circuits_has_no_sampling_floor() -> None:
    baseline = seeded("A", 1, counts=GOOD)
    candidate = seeded("B", 1, qasm3=physical_bell_qasm(2, 3), layout=None, counts=OTHER)
    assert baseline.compilation is not None and candidate.compilation is not None
    assert baseline.compilation.output.qasm3 != candidate.compilation.output.qasm3
    d = dist(baseline, candidate)
    assert d.status is ComparisonStatus.CHANGED
    assert d.tvd is not None and d.hellinger_distance is not None
    assert_floor_skipped_for_shared_seed(d, 1)


def test_shared_seed_with_identical_circuits_is_unchanged_without_sampling_floor() -> None:
    d = dist(seeded("A", 7, counts=GOOD), seeded("B", 7, counts=GOOD))
    assert d.status is ComparisonStatus.UNCHANGED
    assert d.tvd is not None and d.tvd.value == 0.0
    assert_floor_skipped_for_shared_seed(d, 7)


def test_shared_seed_zero_is_a_real_seed() -> None:
    assert_floor_skipped_for_shared_seed(dist(seeded("A", 0), seeded("B", 0)), 0)


@pytest.mark.parametrize(
    ("baseline_seed", "candidate_seed"),
    [(1, 2), (None, None), (1, None), (None, 1)],
    ids=["different", "both-unseeded", "candidate-unseeded", "baseline-unseeded"],
)
def test_distinct_or_missing_seeds_keep_the_sampling_floor(
    baseline_seed: int | None, candidate_seed: int | None
) -> None:
    d = dist(seeded("A", baseline_seed, counts=GOOD), seeded("B", candidate_seed, counts=OTHER))
    assert d.status is ComparisonStatus.CHANGED
    assert_floor_computed(d)


def test_shared_seed_guard_can_be_disabled_by_policy() -> None:
    policy = ComparisonPolicy(sampling_floor_requires_distinct_simulator_seeds=False)
    assert_floor_computed(dist(seeded("A", 1, counts=GOOD), seeded("B", 1, counts=OTHER), policy))


@pytest.mark.parametrize(
    ("baseline_sim", "candidate_sim"),
    [(False, False), (True, False), (False, True)],
    ids=["neither", "baseline-only", "candidate-only"],
)
def test_shared_seed_applies_only_when_both_backends_are_simulators(
    baseline_sim: bool, candidate_sim: bool
) -> None:
    d = dist(
        seeded("A", 1, counts=GOOD, is_simulator=baseline_sim),
        seeded("B", 1, counts=OTHER, is_simulator=candidate_sim),
    )
    assert_floor_computed(d)


def test_failed_gate_with_shared_seed_has_no_unavailable_reason() -> None:
    candidate = seeded("B", 1, counts=GOOD, provider="other")
    d = dist(seeded("A", 1, counts=GOOD), candidate)
    assert d.status is ComparisonStatus.NOT_COMPARABLE
    assert d.sampling_floor is None and d.sampling_floor_unavailable_reason is None
