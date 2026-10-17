"""Human-readable rendering of a RunSnapshotComparison (fake run -> live snapshot).

Every value line carries its unit in brackets, ``[no unit]`` for a dimensionless value (D26,
for this command).
"""

from datetime import datetime

from qci.domain.comparison import ParameterComparison, ResourceKind
from qci.domain.metric import Metric
from qci.domain.snapshot import (
    ErrorValueAtOne,
    MeasurementDateDifference,
    RunSnapshotComparison,
    UnitDifference,
)

FOOTPRINT_NOTE = (
    "  note: relevant hardware = calibration data for the physical resources of the run's "
    "footprint; it does not mean a parameter is known to affect workload performance"
)
ERROR_VALUE_NOTE = (
    "  note: values are stated as the provider reported them; QCI does not interpret them"
)
STATUS_GROUPS = (
    ("changed", "changed"),
    ("unchanged", "unchanged"),
    ("unavailable values", "unavailable"),
    ("not compared (units differ)", "not_comparable"),
)

Key = tuple[ResourceKind, str | None, tuple[int, ...], str]


def _date(value: datetime | None) -> str:
    return value.isoformat() if value else "unknown"


def _unit(unit: str | None) -> str:
    return f"[{unit}]" if unit else "[no unit]"


def _value(value: float | str | None) -> str:
    return "unavailable" if value is None else str(value)


def _resource(kind: ResourceKind, operation: str | None, qubits: tuple[int, ...]) -> str:
    if kind is ResourceKind.QUBIT:
        return f"qubit {qubits[0]}"
    return f"{operation}{list(qubits)}"


def _seconds(m: Metric | None) -> str:
    return "unavailable" if m is None else str(m.value)


def _parameter_line(p: ParameterComparison, units: dict[Key, UnitDifference]) -> str:
    name = f"{_resource(p.resource_kind, p.operation, p.qubits)} {p.parameter}"
    if p.status == "not_comparable":
        u = units[(p.resource_kind, p.operation, p.qubits, p.parameter)]
        return (
            f"    {name}: {_value(p.baseline)} {_unit(u.baseline_unit)} -> "
            f"{_value(p.candidate)} {_unit(u.candidate_unit)} (units differ; not compared)"
        )
    delta = f" (delta {p.delta:+g})" if p.delta is not None else ""
    return f"    {name} {_unit(p.unit)}: {_value(p.baseline)} -> {_value(p.candidate)}{delta}"


def _date_line(d: MeasurementDateDifference) -> str:
    return (
        f"    {_resource(d.resource_kind, d.operation, d.qubits)} {d.parameter}: "
        f"{_date(d.baseline_measured_at)} -> {_date(d.candidate_measured_at)}  "
        f"difference [s]: {_seconds(d.live_minus_fake)}"
    )


def _error_line(e: ErrorValueAtOne, unit: str | None) -> str:
    return (
        f"    {e.side:<9} {_resource(e.resource_kind, e.operation, e.qubits)} {e.parameter} "
        f"{_unit(unit)} = {e.value:g}  (measured {_date(e.measured_at)})"
    )


def render_run_snapshot_comparison(c: RunSnapshotComparison) -> str:
    b, k, fp, hw = c.baseline, c.candidate, c.footprint, c.hardware
    footprint = (
        f"qubits={fp.qubits} operations={len(fp.operations)}"
        if fp.status.value == "available"
        else f"{fp.status.value} ({fp.reason})"
    )
    mapping = (
        f"{c.device_mapping.fake} -> {c.device_mapping.device} ({c.device_mapping.source})"
        if c.device_mapping
        else "none"
    )
    source = b.snapshot_source.value if b.snapshot_source else "unknown"
    out = [
        f"Run-to-snapshot calibration comparison {c.run_snapshot_comparison_id}",
        f"  baseline:  run {b.run_id}  {b.provider or '-'}/{b.backend_name or '-'} "
        f"version={b.backend_version or '-'}  [{source}]",
        f"             calibrated {_date(b.calibrated_at)}  recorded device "
        f"{b.recorded_device or '-'} version={b.recorded_device_version or '-'}  "
        f"qiskit-ibm-runtime {b.qiskit_ibm_runtime_version or '-'}",
        f"  candidate: snapshot {k.snapshot_id}  {k.provider}/{k.backend_name} "
        f"version={k.backend_version or '-'}  [{k.source.value}]",
        f"             calibrated {_date(k.calibrated_at)}  captured {_date(k.captured_at)}  "
        f"content hash {k.content_hash}",
        f"  device mapping: {mapping}",
        f"  footprint: {footprint}",
        f"  status:    {c.status.value}",
        f"  method:    {c.method_version}",
        "  (baseline is the fake run, candidate the live snapshot; deltas and date differences "
        "are live minus fake)",
    ]

    out.append(
        f"Calibration (footprint-scoped): {hw.status.value}"
        + (f"  ({hw.reason})" if hw.reason else "")
    )
    out += [
        FOOTPRINT_NOTE,
        f"  global_snapshot_changed:   {hw.global_snapshot_changed}",
        f"  relevant_hardware_changed: {hw.relevant_hardware_changed}",
    ]
    params = hw.shared_resource_parameters
    units = {(u.resource_kind, u.operation, u.qubits, u.parameter): u for u in c.unit_differences}
    if params:
        count = {s: sum(p.status == s for p in params) for _, s in STATUS_GROUPS}
        out.append(
            f"  parameters of footprint resources: {len(params)}: {count['changed']} changed, "
            f"{count['unchanged']} unchanged, {count['unavailable']} unavailable, "
            f"{count['not_comparable']} not compared (units differ)"
        )
        for title, status in STATUS_GROUPS:
            items = [p for p in params if p.status == status]
            out.append(f"  {title}: {len(items)}")
            out += [_parameter_line(p, units) for p in items]
    out += [f"  excluded: {x}" for x in hw.excluded]

    out.append(f"Parameters reported by one side only: {len(c.parameters_on_one_side)}")
    out += [
        f"    {e.side:<9} {_resource(e.resource_kind, e.operation, e.qubits)} {e.parameter}"
        for e in c.parameters_on_one_side
    ]
    out.append(f"Unit differences: {len(c.unit_differences)}")
    out += [
        f"    {_resource(u.resource_kind, u.operation, u.qubits)} {u.parameter}: baseline "
        f"{_unit(u.baseline_unit)}, candidate {_unit(u.candidate_unit)}"
        for u in c.unit_differences
    ]

    if c.error_parameters:
        param_units = {
            (p.resource_kind, p.operation, p.qubits, p.parameter): p.unit for p in params
        }
        out.append(
            f"Error-type parameters equal to 1 ({', '.join(c.error_parameters)}): "
            f"{len(c.error_values_at_one)}"
        )
        out += [
            _error_line(e, param_units.get((e.resource_kind, e.operation, e.qubits, e.parameter)))
            for e in c.error_values_at_one
        ]
        out.append(ERROR_VALUE_NOTE)

    out += [
        "Measurement dates (fake -> live):",
        f"    calibrated_at: {_date(b.calibrated_at)} -> {_date(k.calibrated_at)}  "
        f"difference [s]: {_seconds(c.calibrated_at_difference)}",
    ]
    if c.measurement_dates:
        out.append(
            f"    live minus fake over {len(c.measurement_dates)} parameters [s]: "
            f"min {_seconds(c.live_minus_fake_min)}, max {_seconds(c.live_minus_fake_max)}"
        )
    out += [_date_line(d) for d in c.measurement_dates]

    out.append("Limitations:")
    out += [f"  - {line}" for line in c.limitations]
    return "\n".join(out)
