"""Result distribution comparison behind a conservative comparability gate.

Compares observed empirical (sampled) distributions only. A nonzero TVD or Hellinger distance
means the observed distributions differ; it does not establish that the underlying probability
distribution changed, nor that the difference is statistically significant.
"""

import math

from qci.domain.comparison import (
    ComparisonPolicy,
    ComparisonStatus,
    DistributionComparison,
    FootprintStatus,
    PhysicalFootprint,
)
from qci.domain.metric import EvidenceKind, Metric
from qci.domain.run import Run, RunStatus

METHOD_VERSION = "1"
_NO_UNCERTAINTY = "empirical point estimate; no sampling uncertainty or significance test"


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
) -> DistributionComparison:
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
    )
