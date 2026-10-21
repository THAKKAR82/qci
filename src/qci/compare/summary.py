"""Calibration magnitudes for the summary of a comparison (ADR 0009, section 6).

Under exact comparison nearly every re-measured continuous value counts as changed (M1.4c), so
a count of changed parameters says little. For each parameter of the footprint's resources,
grouped by resource type (qubit or operation name), parameter name and unit, this computes the
median and largest absolute delta ``|candidate - baseline|`` and relative delta
``|candidate - baseline| / |baseline|``. These are summary statistics of values the comparison
already holds: a view, never persisted and never part of ``--json``. ``ComparisonPolicy`` and
the comparison models are unchanged.

A baseline of exactly 0 has no relative delta: it is counted as "baseline 0". A parameter that
is unavailable, not numeric on both sides, or not compared (units differ) is counted and never
enters a figure.
"""

import statistics
from collections.abc import Iterable
from dataclasses import dataclass

from qci.domain.comparison import ParameterComparison, ResourceKind
from qci.domain.metric import EvidenceKind, Metric

METHOD = "qci.summary.magnitude"
METHOD_VERSION = "1"


def resource_name(p: ParameterComparison) -> str:
    if p.resource_kind is ResourceKind.QUBIT:
        return f"qubit {p.qubits[0]}"
    return f"{p.operation}{list(p.qubits)}"


@dataclass(frozen=True)
class Extreme:
    metric: Metric
    resource: str
    """The resource holding the largest value; the first in comparison order on a tie."""


@dataclass(frozen=True)
class ParameterMagnitude:
    resource_type: str
    """``qubit``, or the operation name (``cz``, ``sx``, ...)."""
    parameter: str
    unit: str | None
    units_differ: bool
    """The group of ``not_comparable`` parameters: the two sides report different units."""
    compared: int
    changed: int
    unavailable: int
    not_comparable: int
    not_numeric: int
    baseline_zero: int
    median_absolute: Metric | None
    largest_absolute: Extreme | None
    median_relative: Metric | None
    largest_relative: Extreme | None


def _metric(name: str, value: float, unit: str | None) -> Metric:
    return Metric(
        name=name,
        value=value,
        unit=unit,
        kind=EvidenceKind.CALCULATED,
        method=METHOD,
        method_version=METHOD_VERSION,
    )


def _numeric(value: float | str | None) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _largest(name: str, values: list[tuple[float, str]], unit: str | None) -> Extreme | None:
    if not values:
        return None
    value, resource = max(values, key=lambda pair: pair[0])  # max keeps the first on a tie
    return Extreme(_metric(name, value, unit), resource)


def _group(
    key: tuple[str, str, str | None, bool], items: list[ParameterComparison]
) -> ParameterMagnitude:
    resource_type, parameter, unit, units_differ = key
    absolute: list[tuple[float, str]] = []
    relative: list[tuple[float, str]] = []
    not_numeric = baseline_zero = 0
    for p in items:
        if p.status not in ("changed", "unchanged"):
            continue
        baseline, candidate = _numeric(p.baseline), _numeric(p.candidate)
        if baseline is None or candidate is None:
            not_numeric += 1
            continue
        difference = abs(candidate - baseline)
        absolute.append((difference, resource_name(p)))
        if baseline == 0:
            baseline_zero += 1
        else:
            relative.append((difference / abs(baseline), resource_name(p)))
    return ParameterMagnitude(
        resource_type=resource_type,
        parameter=parameter,
        unit=unit,
        units_differ=units_differ,
        compared=len(items),
        changed=sum(p.status == "changed" for p in items),
        unavailable=sum(p.status == "unavailable" for p in items),
        not_comparable=sum(p.status == "not_comparable" for p in items),
        not_numeric=not_numeric,
        baseline_zero=baseline_zero,
        median_absolute=(
            _metric("absolute_delta_median", statistics.median(v for v, _ in absolute), unit)
            if absolute
            else None
        ),
        largest_absolute=_largest("absolute_delta_largest", absolute, unit),
        median_relative=(
            _metric("relative_delta_median", statistics.median(v for v, _ in relative), None)
            if relative
            else None
        ),
        largest_relative=_largest("relative_delta_largest", relative, None),
    )


def magnitudes(parameters: Iterable[ParameterComparison]) -> list[ParameterMagnitude]:
    """One entry per resource type, parameter name and unit: qubit parameters first, then
    operations by name, each by parameter name. Parameters whose units differ form their own
    group, with no unit, after the group of their parameter."""
    groups: dict[tuple[str, str, str | None, bool], list[ParameterComparison]] = {}
    for p in parameters:
        resource_type = "qubit" if p.resource_kind is ResourceKind.QUBIT else str(p.operation)
        differ = p.status == "not_comparable"
        key = (resource_type, p.parameter, None if differ else p.unit, differ)
        groups.setdefault(key, []).append(p)
    ordered = sorted(
        groups.items(),
        key=lambda kv: (kv[0][0] != "qubit", kv[0][0], kv[0][1], kv[0][3], kv[0][2] or ""),
    )
    return [_group(key, items) for key, items in ordered]
