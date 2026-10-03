"""Distribution metrics and the conservative comparability gate."""

import math

import pytest

from conftest import LOGICAL_BELL_QASM, make_run, physical_bell_qasm, physical_run
from qci.compare.distribution import (
    compare_distributions,
    hellinger_distance,
    total_variation_distance,
)
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
        assert m.kind is EvidenceKind.STATISTICAL and m.method and m.method_version == "1"
    assert f"numpy {expected.numpy_version}" in f.rng
    assert len(f.caveats) == 4
    # The TVD point estimate itself is unchanged.
    assert d.tvd is not None and d.tvd.kind is EvidenceKind.CALCULATED


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
