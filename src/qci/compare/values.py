"""Typed helpers for comparing normalized values. Deltas are candidate minus baseline."""

from collections.abc import Iterable, Mapping
from typing import Any, cast

from pydantic import JsonValue

from qci.domain.comparison import (
    ComparisonStatus,
    CounterComparison,
    CounterDelta,
    FieldStatus,
    KeyChange,
    MappingComparison,
    SetComparison,
    ValueComparison,
)


def _status(changed: bool) -> FieldStatus:
    return "changed" if changed else "unchanged"


def _json(value: Any) -> JsonValue:
    """Normalize tuples (e.g. edges) to lists so values serialize as JSON."""
    if isinstance(value, tuple | list):
        return [_json(v) for v in value]
    return cast(JsonValue, value)


def compare_value(baseline: Any, candidate: Any) -> ValueComparison:
    """Exact equality of two normalized values."""
    return ValueComparison(
        status=_status(baseline != candidate),
        baseline=_json(baseline),
        candidate=_json(candidate),
    )


def compare_number(baseline: int | float | None, candidate: int | float | None) -> ValueComparison:
    """Exact equality plus ``delta`` (candidate - baseline) when both sides are numbers."""
    delta = None
    if baseline is not None and candidate is not None:
        delta = candidate - baseline
    return ValueComparison(
        status=_status(baseline != candidate),
        baseline=baseline,
        candidate=candidate,
        delta=delta,
    )


def compare_set(baseline: Iterable[Any], candidate: Iterable[Any]) -> SetComparison:
    b, c = set(baseline), set(candidate)
    return SetComparison(
        status=_status(b != c),
        common=[_json(x) for x in sorted(b & c)],
        baseline_only=[_json(x) for x in sorted(b - c)],
        candidate_only=[_json(x) for x in sorted(c - b)],
    )


def compare_mapping(
    baseline: Mapping[str, JsonValue], candidate: Mapping[str, JsonValue]
) -> MappingComparison:
    changed = [
        KeyChange(key=key, baseline=baseline[key], candidate=candidate[key])
        for key in sorted(baseline.keys() & candidate.keys())
        if baseline[key] != candidate[key]
    ]
    baseline_only = sorted(baseline.keys() - candidate.keys())
    candidate_only = sorted(candidate.keys() - baseline.keys())
    return MappingComparison(
        status=_status(bool(changed or baseline_only or candidate_only)),
        baseline_only=baseline_only,
        candidate_only=candidate_only,
        changed=changed,
    )


def compare_counter(baseline: Mapping[str, int], candidate: Mapping[str, int]) -> CounterComparison:
    changed = []
    for key in sorted(baseline.keys() | candidate.keys()):
        b, c = baseline.get(key, 0), candidate.get(key, 0)
        if b != c:
            changed.append(CounterDelta(key=key, baseline=b, candidate=c, delta=c - b))
    return CounterComparison(status=_status(bool(changed)), changed=changed)


def fields_status(statuses: Iterable[FieldStatus]) -> ComparisonStatus:
    return (
        ComparisonStatus.CHANGED
        if any(s == "changed" for s in statuses)
        else ComparisonStatus.UNCHANGED
    )
