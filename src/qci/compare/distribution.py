"""Result distribution comparison behind a conservative comparability gate.

Compares observed empirical (sampled) distributions only. A nonzero TVD or Hellinger distance
means the observed distributions differ; it does not establish that the underlying probability
distribution changed, nor that the difference is statistically significant. When the gate
passes, TVD also carries a sampling floor (``qci.compare.sampling``): evidence about how large TVD
is expected to be from sampling alone at the observed shot counts, never a verdict.
"""

import math

from qci.domain.comparison import (
    ComparisonPolicy,
    ComparisonStatus,
    DistributionComparison,
    FootprintStatus,
    PhysicalFootprint,
    SamplingFloor,
)
from qci.domain.metric import EvidenceKind, Metric
from qci.domain.run import Run, RunStatus

METHOD_VERSION = "1"
_NO_UNCERTAINTY = "empirical point estimate; no sampling uncertainty or significance test"

SAMPLING_FLOOR_METHOD_VERSION = "1"
_H0 = (
    "H0: both runs sampled one shared distribution, estimated by the pooled plug-in estimate "
    "(merged counts over merged total)"
)
SAMPLING_FLOOR_CAVEATS = [
    "It tests only whether the two observed samples are consistent with one shared "
    "distribution at these shot counts. It makes no causal claim.",
    "The pooled plug-in estimate cannot resample outcomes never observed, so the floor is "
    "slightly underestimated for sparse distributions.",
    "It assumes shots within each run are independent and identically distributed. Drift "
    "within a job on real hardware violates this.",
    "No multiple-comparison correction is applied.",
]


def _probabilities(counts: dict[str, int]) -> dict[str, float]:
    total = sum(counts.values())
    return {k: v / total for k, v in counts.items()}


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


def compare_distributions(
    baseline: Run,
    candidate: Run,
    baseline_footprint: PhysicalFootprint,
    candidate_footprint: PhysicalFootprint,
    policy: ComparisonPolicy,
    *,
    seed: int,
) -> DistributionComparison:
    """Gate, then TVD, Hellinger distance and the TVD sampling floor (resampled with ``seed``)."""
    br, cr = baseline.result, candidate.result
    missing = []
    for side, run in (("baseline", baseline), ("candidate", candidate)):
        if run.status is not RunStatus.SUCCEEDED or run.result is None:
            missing.append(f"{side} run has no successful result")
    if missing or br is None or cr is None:
        return DistributionComparison(status=ComparisonStatus.UNAVAILABLE, reasons=missing)

    reasons: list[str] = []
    if br.total_shots == 0 or cr.total_shots == 0:
        reasons.append("a run has zero shots")
    b_qasm, c_qasm = baseline.logical_circuit.qasm3, candidate.logical_circuit.qasm3
    if policy.distribution_requires_identical_logical_qasm3:
        if b_qasm is None or c_qasm is None:
            reasons.append("logical circuit OpenQASM 3 unavailable; logical artifact unknown")
        elif b_qasm != c_qasm:
            reasons.append("logical circuit changed (OpenQASM 3 text differs)")
    if policy.distribution_requires_same_provider:
        bp = baseline.backend.provider if baseline.backend else None
        cp = candidate.backend.provider if candidate.backend else None
        if bp != cp:
            reasons.append(f"providers differ ({bp} vs {cp}); bit-order convention unverified")
    if set(br.counts) != set(cr.counts):
        reasons.append(f"classical registers differ ({sorted(br.counts)} vs {sorted(cr.counts)})")
    elif len(br.counts) > policy.distribution_max_classical_registers:
        reasons.append("multiple classical registers are not supported in compare v1")
    widths = {len(k) for counts in (*br.counts.values(), *cr.counts.values()) for k in counts}
    if len(widths) > 1:
        reasons.append(f"bitstring widths differ ({sorted(widths)})")
    if not policy.dynamic_circuits_supported and FootprintStatus.UNSUPPORTED_DYNAMIC in (
        baseline_footprint.status,
        candidate_footprint.status,
    ):
        reasons.append("dynamic circuits are not supported in compare v1")

    if reasons:
        return DistributionComparison(
            status=ComparisonStatus.NOT_COMPARABLE,
            reasons=reasons,
            baseline_shots=br.total_shots,
            candidate_shots=cr.total_shots,
        )

    register = next(iter(br.counts))
    p, q = _probabilities(br.counts[register]), _probabilities(cr.counts[register])
    tvd = total_variation_distance(p, q)
    hellinger = hellinger_distance(p, q)
    notes = []
    if br.total_shots != cr.total_shots:
        notes.append("shot counts differ; distributions were normalized")
    return DistributionComparison(
        status=ComparisonStatus.UNCHANGED if p == q else ComparisonStatus.CHANGED,
        reasons=notes,
        classical_register=register,
        baseline_shots=br.total_shots,
        candidate_shots=cr.total_shots,
        tvd=Metric(
            name="tvd",
            value=tvd,
            kind=EvidenceKind.CALCULATED,
            method=f"total variation distance between normalized counts; {_NO_UNCERTAINTY}",
            method_version=METHOD_VERSION,
        ),
        hellinger_distance=Metric(
            name="hellinger_distance",
            value=hellinger,
            kind=EvidenceKind.CALCULATED,
            method=f"Hellinger distance between normalized counts; {_NO_UNCERTAINTY}",
            method_version=METHOD_VERSION,
        ),
        sampling_floor=_sampling_floor(
            br.counts[register], cr.counts[register], policy.distribution_null_resamples, seed
        ),
    )


def _sampling_floor(
    baseline_counts: dict[str, int], candidate_counts: dict[str, int], resamples: int, seed: int
) -> SamplingFloor:
    # Deferred: qci.compare.sampling imports total_variation_distance from this module.
    from qci.compare.sampling import tvd_sampling_floor

    r = tvd_sampling_floor(baseline_counts, candidate_counts, resamples=resamples, seed=seed)
    resampling = f"{_H0}; {resamples} paired multinomial resamples at each run's own shot count"

    def metric(name: str, value: float, what: str) -> Metric:
        return Metric(
            name=name,
            value=value,
            kind=EvidenceKind.STATISTICAL,
            method=f"{what}; {resampling}",
            method_version=SAMPLING_FLOOR_METHOD_VERSION,
        )

    quantile = 'null TVD {} quantile, numpy.quantile(method="linear")'
    return SamplingFloor(
        method=f"Monte Carlo null distribution of TVD; {resampling}",
        method_version=SAMPLING_FLOOR_METHOD_VERSION,
        rng=f"numpy.random.Generator(numpy.random.PCG64(seed)); numpy {r.numpy_version}",
        seed=r.seed,
        resamples=r.resamples,
        null_p50=metric("tvd_null_p50", r.null_p50, quantile.format("0.50")),
        null_p95=metric("tvd_null_p95", r.null_p95, quantile.format("0.95")),
        null_p99=metric("tvd_null_p99", r.null_p99, quantile.format("0.99")),
        p_value=metric(
            "tvd_monte_carlo_p_value",
            r.p_value,
            "Monte Carlo p-value (1 + #{null_tvd >= observed_tvd - 1e-12}) / (resamples + 1)",
        ),
        caveats=SAMPLING_FLOOR_CAVEATS,
    )
