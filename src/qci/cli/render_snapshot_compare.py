"""Human-readable rendering of a SnapshotComparison (baseline -> candidate)."""

from datetime import datetime

from qci.domain.comparison import ParameterComparison, ResourceKind
from qci.domain.snapshot import ErrorValueAtOne, SnapshotComparison, SnapshotSide, UnchangedValue

FOOTPRINT_NOTE = (
    "  note: relevant hardware = calibration data for the physical resources of the footprint "
    "run; it does not mean a parameter is known to affect workload performance"
)
NOT_RE_MEASURED_NOTE = (
    "  note: a value that was not re-measured has the same measurement date in both snapshots; "
    "it is one measurement reported twice, not evidence that the value held constant between "
    "the captures"
)
ERROR_VALUE_NOTE = (
    "  note: values are stated as the provider reported them; QCI does not interpret them"
)


def _date(value: datetime | None) -> str:
    return value.isoformat() if value else "unknown"


def _resource(kind: ResourceKind, operation: str | None, qubits: tuple[int, ...]) -> str:
    if kind is ResourceKind.QUBIT:
        return f"qubit {qubits[0]}"
    return f"{operation}{list(qubits)}"


def _side_line(label: str, s: SnapshotSide) -> str:
    return (
        f"  {label}: {s.snapshot_id}  {s.provider}/{s.backend_name}  "
        f"calibrated {_date(s.calibrated_at)}  captured {_date(s.captured_at)}  "
        f"[{s.source.value}]"
    )


def _parameter_line(p: ParameterComparison) -> str:
    name = f"{_resource(p.resource_kind, p.operation, p.qubits)} {p.parameter}"
    if p.status == "not_comparable":
        return (
            f"    {name}: baseline {p.baseline}, candidate {p.candidate} "
            "(units differ; not compared)"
        )
    unit = f" {p.unit}" if p.unit else ""
    delta = f" (delta {p.delta:+g})" if p.delta is not None else ""
    return f"    {name}: {p.baseline} -> {p.candidate}{unit}{delta}"


def _unchanged_line(u: UnchangedValue) -> str:
    dates = (
        _date(u.candidate_measured_at)
        if u.measurement == "not_re_measured"
        else f"{_date(u.baseline_measured_at)} -> {_date(u.candidate_measured_at)}"
    )
    resource = _resource(u.resource_kind, u.operation, u.qubits)
    return f"    {resource} {u.parameter} = {u.value}  (measured {dates})"


def _error_line(e: ErrorValueAtOne) -> str:
    return (
        f"    {e.side:<9} {_resource(e.resource_kind, e.operation, e.qubits)} {e.parameter} = "
        f"{e.value:g}  (measured {_date(e.measured_at)})"
    )


def render_snapshot_comparison(c: SnapshotComparison) -> str:
    fp = c.footprint
    footprint = (
        f"qubits={fp.qubits} operations={len(fp.operations)}"
        if fp.status.value == "available"
        else f"{fp.status.value} ({fp.reason})"
    )
    e = c.elapsed_between_captures
    out = [
        f"Snapshot comparison {c.snapshot_comparison_id}",
        _side_line("baseline ", c.baseline),
        _side_line("candidate", c.candidate),
        f"  elapsed between captures: {e.value:g} {e.unit}  [{e.kind.value}; v{e.method_version}]",
        f"  footprint run: {c.footprint_run_id} on {c.footprint_backend or 'unknown backend'}"
        f"  {footprint}",
        f"  allow_footprint_backend_mismatch: {c.allow_footprint_backend_mismatch}",
        f"  status:    {c.status.value}",
        f"  method:    {c.method_version}",
        "  (deltas are candidate minus baseline)",
    ]

    hw = c.hardware
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
    if params:
        count = {
            s: sum(p.status == s for p in params)
            for s in ("changed", "unchanged", "unavailable", "not_comparable")
        }
        out.append(
            f"  parameters of footprint resources: {len(params)}: {count['changed']} changed, "
            f"{count['unchanged']} unchanged, {count['unavailable']} unavailable, "
            f"{count['not_comparable']} not compared (units differ)"
        )
    out += [_parameter_line(p) for p in params if p.status in ("changed", "not_comparable")]
    out += [f"  unavailable: {u}" for u in hw.unavailable]
    out += [f"  measurement date changed: {d}" for d in hw.calibration_date_changes]
    out += [f"  excluded: {x}" for x in hw.excluded]

    if params:
        groups = (
            ("re-measured, same value", "re_measured_same_value"),
            ("not re-measured", "not_re_measured"),
            ("measurement date unavailable", "measurement_date_unavailable"),
        )
        out.append(f"Unchanged values: {len(c.unchanged_values)}")
        for title, key in groups:
            items = [u for u in c.unchanged_values if u.measurement == key]
            out.append(f"  {title}: {len(items)}")
            out += [_unchanged_line(u) for u in items]
        out.append(NOT_RE_MEASURED_NOTE)

    if c.error_parameters:
        out.append(
            f"Error-type parameters equal to 1 ({', '.join(c.error_parameters)}): "
            f"{len(c.error_values_at_one)}"
        )
        out += [_error_line(x) for x in c.error_values_at_one]
        out.append(ERROR_VALUE_NOTE)

    out.append("Limitations:")
    out += [f"  - {line}" for line in c.limitations]
    return "\n".join(out)
