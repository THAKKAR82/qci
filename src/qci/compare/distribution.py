"""Result distribution comparison behind a conservative comparability gate.

Compares observed empirical (sampled) distributions only. A nonzero TVD or Hellinger distance
means the observed distributions differ; it does not establish that the underlying probability
distribution changed, nor that the difference is statistically significant. When the gate
passes, TVD also carries a sampling floor (``qci.compare.sampling``): evidence about how large TVD
is expected to be from sampling alone at the observed shot counts, never a verdict. The floor is
skipped when both runs were simulated with the same simulator seed, because their samples are
then not independent.
"""

import math

from qci.compare.divergence import hellinger_distance, total_variation_distance
from qci.compare.sampling import tvd_sampling_floor
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
P_VALUE_METHOD_VERSION = "2"
"""v2 adds the Monte Carlo standard error of the p-value as the metric's ``uncertainty``."""
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


def shared_simulator_seed(baseline: Run, candidate: Run) -> int | None:
    """The simulator seed both runs share, if both ran on simulators with one non-null seed."""
    seeds = []
    for run in (baseline, candidate):
        if run.backend is None or not run.backend.is_simulator or run.execution is None:
            return None
        seeds.append(run.execution.config.seed_simulator)
    return seeds[0] if seeds[0] == seeds[1] else None


def _probabilities(counts: dict[str, int]) -> dict[str, float]:
    total = sum(counts.values())
    return {k: v / total for k, v in counts.items()}


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
        reasons.append("multiple classical registers are not supported by this comparison policy")
    widths = {len(k) for counts in (*br.counts.values(), *cr.counts.values()) for k in counts}
    if len(widths) > 1:
        reasons.append(f"bitstring widths differ ({sorted(widths)})")
    if not policy.dynamic_circuits_supported and FootprintStatus.UNSUPPORTED_DYNAMIC in (
        baseline_footprint.status,
        candidate_footprint.status,
    ):
        reasons.append("dynamic circuits are not supported by this comparison policy")

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
    floor: SamplingFloor | None = None
    floor_unavailable: str | None = None
    shared_seed = shared_simulator_seed(baseline, candidate)
    if policy.sampling_floor_requires_distinct_simulator_seeds and shared_seed is not None:
        floor_unavailable = (
            f"both samples were drawn with the same simulator seed ({shared_seed}), so they are "
            "not independent; the sampling floor assumes independent samples"
        )
    else:
        floor = _sampling_floor(
            br.counts[register], cr.counts[register], policy.distribution_null_resamples, seed
        )
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
        sampling_floor=floor,
        sampling_floor_unavailable_reason=floor_unavailable,
    )


def p_value_standard_error(p_value: float, resamples: int) -> float:
    """Monte Carlo standard error of a resampling p-value: sqrt(p * (1 - p) / (B + 1))."""
    return math.sqrt(p_value * (1 - p_value) / (resamples + 1))


def _sampling_floor(
    baseline_counts: dict[str, int], candidate_counts: dict[str, int], resamples: int, seed: int
) -> SamplingFloor:
    r = tvd_sampling_floor(baseline_counts, candidate_counts, resamples=resamples, seed=seed)
    resampling = f"{_H0}; {resamples} paired multinomial resamples at each run's own shot count"

    def metric(
        name: str,
        value: float,
        what: str,
        version: str = SAMPLING_FLOOR_METHOD_VERSION,
        uncertainty: float | None = None,
    ) -> Metric:
        return Metric(
            name=name,
            value=value,
            kind=EvidenceKind.STATISTICAL,
            method=f"{what}; {resampling}",
            method_version=version,
            uncertainty=uncertainty,
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
            "Monte Carlo p-value (1 + #{null_tvd >= observed_tvd - 1e-12}) / (resamples + 1); "
            "uncertainty is its Monte Carlo standard error sqrt(p * (1 - p) / (resamples + 1))",
            version=P_VALUE_METHOD_VERSION,
            uncertainty=p_value_standard_error(r.p_value, r.resamples),
        ),
        caveats=SAMPLING_FLOOR_CAVEATS,
    )
