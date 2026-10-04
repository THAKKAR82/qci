"""Compare-time observables: bitstring-set probabilities with Wilson and Newcombe intervals.

Converting bitstring counts to (k, n) is the only bitstring-aware step. The statistics live in
``qci.compare.proportions`` and take integers only (ADR 0006). Observables reuse the
distribution comparability gate: when it fails, every observable reports the same reasons.
"""

from collections.abc import Iterable, Mapping, Sequence

from qci.compare.proportions import WILSON_Z_95, newcombe_difference, wilson_interval
from qci.core.errors import InvalidObservableError
from qci.core.hashing import hash_json
from qci.domain.comparison import (
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


def _difference(kb: int, nb: int, kc: int, nc: int) -> ObservableDifference:
    d, lower, upper = newcombe_difference(kb, nb, kc, nc)
    return ObservableDifference(
        delta=_metric(
            "bitstring_set_probability_delta",
            d,
            EvidenceKind.CALCULATED,
            "candidate estimate minus baseline estimate",
        ),
        newcombe_lower=_metric("newcombe_95_lower", lower, EvidenceKind.STATISTICAL, _NEWCOMBE),
        newcombe_upper=_metric("newcombe_95_upper", upper, EvidenceKind.STATISTICAL, _NEWCOMBE),
    )


def _validate(spec: ObservableSpec, register: str, width: int) -> None:
    if spec.classical_register is not None and spec.classical_register != register:
        raise InvalidObservableError(
            f"observable {spec.name!r} names register {spec.classical_register!r}, but the "
            f"runs have register {register!r}"
        )
    wrong = [b for b in spec.bitstrings if len(b) != width]
    if wrong:
        raise InvalidObservableError(
            f"observable {spec.name!r} has bitstrings of the wrong width {wrong}; the runs' "
            f"counts keys have width {width}"
        )


def compare_observables(
    specs: Sequence[ObservableSpec],
    baseline: Run,
    candidate: Run,
    distribution: DistributionComparison,
) -> list[ObservableComparison]:
    """One comparison per spec, in canonical order, behind the distribution gate.

    Raises ``InvalidObservableError`` when a spec does not fit the runs' register or width.
    """
    ordered = canonical_observables(specs)
    if distribution.status in (ComparisonStatus.UNAVAILABLE, ComparisonStatus.NOT_COMPARABLE):
        return [
            ObservableComparison(
                spec=s, status=distribution.status, reasons=list(distribution.reasons)
            )
            for s in ordered
        ]
    register = distribution.classical_register
    assert register is not None and baseline.result is not None and candidate.result is not None
    b_counts, c_counts = baseline.result.counts[register], candidate.result.counts[register]
    width = len(next(iter({**b_counts, **c_counts})))
    comparisons = []
    for spec in ordered:
        _validate(spec, register, width)
        kb, nb = bitstring_set_counts(b_counts, spec.bitstrings)
        kc, nc = bitstring_set_counts(c_counts, spec.bitstrings)
        comparisons.append(
            ObservableComparison(
                spec=spec,
                status=(
                    ComparisonStatus.CHANGED if kb * nc != kc * nb else ComparisonStatus.UNCHANGED
                ),
                classical_register=register,
                baseline=_side(kb, nb),
                candidate=_side(kc, nc),
                difference=_difference(kb, nb, kc, nc),
            )
        )
    return comparisons
