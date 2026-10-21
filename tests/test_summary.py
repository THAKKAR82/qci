"""Calibration magnitudes of the comparison summary (ADR 0009, section 6)."""

import math

from qci.compare.summary import METHOD, METHOD_VERSION, ParameterMagnitude, magnitudes
from qci.domain.comparison import ComparisonPolicy, ParameterComparison, ResourceKind
from qci.domain.metric import EvidenceKind
from qci.services.compare_service import ENGINE_VERSION


def qubit(
    q: int,
    baseline: float | str | None,
    candidate: float | str | None,
    *,
    parameter: str = "T1",
    unit: str | None = "us",
    status: str | None = None,
) -> ParameterComparison:
    if status is None:
        status = "unchanged" if baseline == candidate else "changed"
    return ParameterComparison.model_validate(
        {
            "resource_kind": ResourceKind.QUBIT,
            "operation": None,
            "qubits": (q,),
            "parameter": parameter,
            "unit": unit,
            "status": status,
            "baseline": baseline,
            "candidate": candidate,
        }
    )


def gate(
    name: str, qubits: tuple[int, ...], baseline: float, candidate: float
) -> ParameterComparison:
    return ParameterComparison.model_validate(
        {
            "resource_kind": ResourceKind.OPERATION,
            "operation": name,
            "qubits": qubits,
            "parameter": "gate_error",
            "unit": None,
            "status": "unchanged" if baseline == candidate else "changed",
            "baseline": baseline,
            "candidate": candidate,
        }
    )


def only(items: list[ParameterComparison]) -> ParameterMagnitude:
    (m,) = magnitudes(items)
    return m


def test_median_and_largest_absolute_and_relative_deltas_name_their_resource() -> None:
    m = only([qubit(0, 100.0, 90.0), qubit(1, 50.0, 60.0), qubit(2, 200.0, 200.0)])
    assert (m.resource_type, m.parameter, m.unit) == ("qubit", "T1", "us")
    assert (m.compared, m.changed) == (3, 2)
    assert m.median_absolute is not None and m.median_absolute.value == 10.0
    assert m.median_absolute.unit == "us"
    assert m.largest_absolute is not None
    assert (m.largest_absolute.metric.value, m.largest_absolute.resource) == (10.0, "qubit 0")
    assert m.median_relative is not None and m.median_relative.value == 0.1
    assert m.median_relative.unit is None
    assert m.largest_relative is not None
    assert (m.largest_relative.metric.value, m.largest_relative.resource) == (0.2, "qubit 1")


def test_every_figure_is_a_calculated_metric() -> None:
    m = only([qubit(0, 100.0, 90.0), qubit(1, 50.0, 60.0)])
    assert m.largest_absolute is not None and m.largest_relative is not None
    for metric in (
        m.median_absolute,
        m.largest_absolute.metric,
        m.median_relative,
        m.largest_relative.metric,
    ):
        assert metric is not None
        assert metric.kind is EvidenceKind.CALCULATED
        assert (metric.method, metric.method_version) == (METHOD, METHOD_VERSION)
        assert (METHOD, METHOD_VERSION) == ("qci.summary.magnitude", "1")


def test_a_baseline_of_zero_is_counted_and_has_no_relative_delta() -> None:
    m = only([qubit(0, 0.0, 0.5), qubit(1, 2.0, 3.0)])
    assert m.baseline_zero == 1
    assert m.largest_absolute is not None and m.largest_absolute.metric.value == 1.0
    assert m.largest_relative is not None and m.largest_relative.metric.value == 0.5
    assert m.largest_relative.resource == "qubit 1"
    every_zero = only([qubit(0, 0.0, 0.5)])
    assert every_zero.baseline_zero == 1
    assert every_zero.median_relative is None and every_zero.largest_relative is None
    for value in (every_zero.median_absolute, every_zero.largest_absolute):
        assert value is not None
    for metric in (m.median_relative, m.largest_relative.metric):
        assert metric is not None and math.isfinite(metric.value)


def test_unavailable_and_not_comparable_are_counted_never_entered_as_zero() -> None:
    items = [
        qubit(0, 100.0, None, status="unavailable"),
        qubit(1, 100.0, 130.0),
        qubit(2, 100.0, 4.0, unit=None, status="not_comparable"),
    ]
    found = magnitudes(items)
    assert [(m.unit, m.units_differ) for m in found] == [("us", False), (None, True)]
    with_unit, differ = found
    assert (with_unit.compared, with_unit.changed, with_unit.unavailable) == (2, 1, 1)
    assert with_unit.median_absolute is not None and with_unit.median_absolute.value == 30.0
    assert with_unit.largest_absolute is not None
    assert with_unit.largest_absolute.resource == "qubit 1"
    assert (differ.compared, differ.not_comparable) == (1, 1)
    assert differ.median_absolute is None and differ.largest_absolute is None
    assert differ.median_relative is None and differ.largest_relative is None
    only_unavailable = only([qubit(0, None, 5.0, status="unavailable")])
    assert only_unavailable.median_absolute is None and only_unavailable.unavailable == 1


def test_text_values_are_counted_as_not_numeric() -> None:
    m = only([qubit(0, "a", "b", status="changed"), qubit(1, 1.0, 2.0)])
    assert (m.not_numeric, m.compared, m.changed) == (1, 2, 2)
    assert m.largest_absolute is not None and m.largest_absolute.resource == "qubit 1"


def test_groups_by_resource_type_parameter_and_unit() -> None:
    found = magnitudes(
        [
            gate("sx", (1,), 1e-4, 2e-4),
            qubit(0, 1.0, 1.5, parameter="readout_error", unit=None),
            gate("cz", (0, 1), 0.01, 0.02),
            qubit(0, 100.0, 90.0),
            qubit(1, 1.0, 1.0, unit="ms"),
            gate("cz", (1, 2), 0.01, 0.01),
        ]
    )
    keys = [(m.resource_type, m.parameter, m.unit, m.compared) for m in found]
    assert keys == [
        ("qubit", "T1", "ms", 1),
        ("qubit", "T1", "us", 1),
        ("qubit", "readout_error", None, 1),
        ("cz", "gate_error", None, 2),
        ("sx", "gate_error", None, 1),
    ]
    (cz,) = [m for m in found if m.resource_type == "cz"]
    assert cz.largest_absolute is not None and cz.largest_absolute.resource == "cz[0, 1]"


def test_ties_name_the_first_resource() -> None:
    m = only([qubit(3, 1.0, 2.0), qubit(1, 1.0, 2.0)])
    assert m.largest_absolute is not None and m.largest_absolute.resource == "qubit 3"


def test_no_parameters_gives_no_groups() -> None:
    assert magnitudes([]) == []


def test_comparison_policy_and_engine_are_unchanged() -> None:
    assert ComparisonPolicy().version == "qci.compare.v3"
    assert ENGINE_VERSION == "qci.compare.engine.4"
