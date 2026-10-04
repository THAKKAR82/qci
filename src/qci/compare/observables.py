"""Compare-time observables: bitstring-set probabilities with Wilson and Newcombe intervals.

Converting bitstring counts to (k, n) is the only bitstring-aware step. The statistics live in
``qci.compare.proportions`` and take integers only (ADR 0006). Observables reuse the
distribution comparability gate: when it fails, every observable reports the same reasons.
They also reuse the shared-seed rule: the Newcombe difference interval is withheld when the
TVD sampling floor would be, because both assume independent samples.
"""

from collections.abc import Iterable, Mapping, Sequence

from qci.compare.distribution import shared_simulator_seed
from qci.compare.proportions import WILSON_Z_95, newcombe_difference, wilson_interval
from qci.core.errors import InvalidObservableError
from qci.core.hashing import hash_json
from qci.domain.comparison import (
    ComparisonPolicy,
    ComparisonStatus,
    DistributionComparison,
    ObservableComparison,
    ObservableDifference,
    ObservableSide,
    ObservableSpec,
)
from qci.domain.metric import EvidenceKind, Metric
from qci.domain.run import Run

METHOD_VERSION = "1"
_WILSON = f"Wilson 95% score interval, z = {WILSON_Z_95!r}; assumes independent shots"
_NEWCOMBE = (
    "Newcombe hybrid score interval for candidate minus baseline, built from the two Wilson "
    f"95% intervals (z = {WILSON_Z_95!r}); assumes independent shots within and between runs"
)


def bitstring_set_counts(counts: Mapping[str, int], bitstrings: Iterable[str]) -> tuple[int, int]:
    """(k, n): shots whose counts key is in ``bitstrings``, and total shots.

    A bitstring never observed counts as 0.
    """
    return sum(counts.get(b, 0) for b in set(bitstrings)), sum(counts.values())


def canonical_observables(specs: Iterable[ObservableSpec]) -> list[ObservableSpec]:
    """The request in canonical order (by name). Names must be unique."""
    ordered = sorted(specs, key=lambda s: s.name)
    names = [s.name for s in ordered]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        raise InvalidObservableError(f"duplicate observable names: {', '.join(duplicates)}")
    return ordered


def observables_hash(specs: Iterable[ObservableSpec]) -> str:
    """Canonical hash of an observable request, part of the ``comparison_id`` derivation."""
    return hash_json([s.model_dump(mode="json") for s in canonical_observables(specs)])


def _metric(name: str, value: float, kind: EvidenceKind, method: str) -> Metric:
    return Metric(name=name, value=value, kind=kind, method=method, method_version=METHOD_VERSION)


def _side(k: int, n: int) -> ObservableSide:
    lower, upper = wilson_interval(k, n)
    return ObservableSide(
        k=k,
        n=n,
        estimate=_metric(
            "bitstring_set_probability",
            k / n,
            EvidenceKind.CALCULATED,
            "k / n: shots whose outcome is in the bitstring set over total shots",
        ),
        wilson_lower=_metric("wilson_95_lower", lower, EvidenceKind.STATISTICAL, _WILSON),
        wilson_upper=_metric("wilson_95_upper", upper, EvidenceKind.STATISTICAL, _WILSON),
    )


def _difference(kb: int, nb: int, kc: int, nc: int, *, interval: bool) -> ObservableDifference:
    delta = _metric(
        "bitstring_set_probability_delta",
        kc / nc - kb / nb,
        EvidenceKind.CALCULATED,
        "candidate estimate minus baseline estimate",
    )
    if not interval:
        return ObservableDifference(delta=delta)
    _, lower, upper = newcombe_difference(kb, nb, kc, nc)
    return ObservableDifference(
        delta=delta,
        newcombe_lower=_metric("newcombe_95_lower", lower, EvidenceKind.STATISTICAL, _NEWCOMBE),
        newcombe_upper=_metric("newcombe_95_upper", upper, EvidenceKind.STATISTICAL, _NEWCOMBE),
    )


def _counts_width(baseline: Run, candidate: Run, register: str | None) -> tuple[str, int] | None:
    """(register, key width) when both runs have counts and their keys share one width.

    ``register`` null means the single register both runs share. Returns None when there is
    nothing well defined to check against: a side has no result, the register is ambiguous or
    absent, no bitstring was recorded, or the widths differ (the gate reports that).
    """
    br, cr = baseline.result, candidate.result
    if br is None or cr is None:
        return None
    if register is None:
        if len(br.counts) != 1 or set(br.counts) != set(cr.counts):
            return None
        register = next(iter(br.counts))
    if register not in br.counts or register not in cr.counts:
        return None
    widths = {len(k) for k in (*br.counts[register], *cr.counts[register])}
    return (register, widths.pop()) if len(widths) == 1 else None


def _validate_width(spec: ObservableSpec, register: str, width: int) -> None:
    wrong = [b for b in spec.bitstrings if len(b) != width]
    if wrong:
        raise InvalidObservableError(
            f"observable {spec.name!r} has bitstrings of the wrong width {wrong}; the runs' "
            f"counts keys in register {register!r} have width {width}"
        )


def _gated(
    spec: ObservableSpec, baseline: Run, candidate: Run, distribution: DistributionComparison
) -> ObservableComparison:
    """The gate failed: report its status and reasons, after checking width where possible."""
    checkable = _counts_width(baseline, candidate, spec.classical_register)
    if checkable is not None:
        _validate_width(spec, *checkable)
    return ObservableComparison(
        spec=spec, status=distribution.status, reasons=list(distribution.reasons)
    )


def compare_observables(
    specs: Sequence[ObservableSpec],
    baseline: Run,
    candidate: Run,
    distribution: DistributionComparison,
    policy: ComparisonPolicy,
) -> list[ObservableComparison]:
    """One comparison per spec, in canonical order, behind the distribution gate.

    When both runs were simulated with the same simulator seed and the policy requires
    distinct seeds, each run's estimate and Wilson interval and the point difference are
    reported, but the Newcombe interval is withheld, because it assumes independent samples.

    Raises ``InvalidObservableError`` when a spec does not fit the runs' register or width.
    The width is checked whenever both runs have counts, even when the gate failed.
    """
    ordered = canonical_observables(specs)
    if distribution.status in (ComparisonStatus.UNAVAILABLE, ComparisonStatus.NOT_COMPARABLE):
        return [_gated(s, baseline, candidate, distribution) for s in ordered]
    register = distribution.classical_register
    assert register is not None and baseline.result is not None and candidate.result is not None
    b_counts, c_counts = baseline.result.counts[register], candidate.result.counts[register]
    checkable = _counts_width(baseline, candidate, register)
    shared_seed = shared_simulator_seed(baseline, candidate)
    withheld = (
        f"both samples were drawn with the same simulator seed ({shared_seed}), so they are "
        "not independent; the Newcombe interval assumes independent samples"
        if policy.sampling_floor_requires_distinct_simulator_seeds and shared_seed is not None
        else None
    )
    comparisons = []
    for spec in ordered:
        if spec.classical_register is not None and spec.classical_register != register:
            raise InvalidObservableError(
                f"observable {spec.name!r} names register {spec.classical_register!r}, but the "
                f"runs have register {register!r}"
            )
        if checkable is not None:
            _validate_width(spec, *checkable)
        kb, nb = bitstring_set_counts(b_counts, spec.bitstrings)
        kc, nc = bitstring_set_counts(c_counts, spec.bitstrings)
        empty = [side for side, n in (("baseline", nb), ("candidate", nc)) if n == 0]
        if empty:
            comparisons.append(
                ObservableComparison(
                    spec=spec,
                    status=ComparisonStatus.UNAVAILABLE,
                    reasons=[
                        f"{side} run has no counts in register {register!r}" for side in empty
                    ],
                    classical_register=register,
                )
            )
            continue
        comparisons.append(
            ObservableComparison(
                spec=spec,
                status=(
                    ComparisonStatus.CHANGED if kb * nc != kc * nb else ComparisonStatus.UNCHANGED
                ),
                classical_register=register,
                baseline=_side(kb, nb),
                candidate=_side(kc, nc),
                difference=_difference(kb, nb, kc, nc, interval=withheld is None),
                difference_unavailable_reason=withheld,
            )
        )
    return comparisons
