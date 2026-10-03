"""Footprint comparison and footprint-scoped hardware/calibration comparison.

"Relevant hardware" means calibration data associated with physical resources the workload
actually used. It does not mean a parameter is known to affect workload performance, nor that a
calibration change caused an observed result change.

Rules (unchanged since policy qci.compare.v1):
- The global snapshot flag covers the whole raw provider payload, including unused hardware.
- Calibration is only ever compared for a physical resource that is identical on both sides
  (same qubit, or same operation name on the same ordered qubits). Different physical resources
  are never presented as a temporal change of one resource.
- ``relevant_hardware_changed`` is only decided when both footprints use exactly the same
  physical resources; otherwise it is null and shared-resource evidence is still reported.
"""

from collections.abc import Callable

from qci.compare.values import compare_set, compare_value
from qci.core.hashing import hash_json
from qci.core.ports import CalibrationReader
from qci.domain.comparison import (
    CalibrationValue,
    ComparisonStatus,
    FootprintCalibration,
    FootprintComparison,
    FootprintStatus,
    HardwareComparison,
    OperationCountChange,
    OperationRef,
    ParameterComparison,
    PhysicalFootprint,
    ResourceKind,
)
from qci.domain.run import Run

OpKey = tuple[str, tuple[int, ...]]


def _op_counts(footprint: PhysicalFootprint) -> dict[OpKey, int]:
    return {(op.name, op.qubits): op.count for op in footprint.operations}


def _unusable_reason(baseline: PhysicalFootprint, candidate: PhysicalFootprint) -> str | None:
    reasons = []
    for side, fp in (("baseline", baseline), ("candidate", candidate)):
        if fp.status is not FootprintStatus.AVAILABLE:
            reasons.append(f"{side} footprint {fp.status.value}: {fp.reason}")
    return "; ".join(reasons) or None


def _unusable_status(baseline: PhysicalFootprint, candidate: PhysicalFootprint) -> ComparisonStatus:
    dynamic = FootprintStatus.UNSUPPORTED_DYNAMIC
    if dynamic in (baseline.status, candidate.status):
        return ComparisonStatus.NOT_COMPARABLE
    return ComparisonStatus.UNAVAILABLE


def resources_identical(baseline: PhysicalFootprint, candidate: PhysicalFootprint) -> bool:
    return set(baseline.qubits) == set(candidate.qubits) and set(_op_counts(baseline)) == set(
        _op_counts(candidate)
    )


def compare_footprints(
    baseline: PhysicalFootprint, candidate: PhysicalFootprint
) -> FootprintComparison:
    reason = _unusable_reason(baseline, candidate)
    if reason is not None:
        return FootprintComparison(status=_unusable_status(baseline, candidate), reason=reason)

    b_ops, c_ops = _op_counts(baseline), _op_counts(candidate)
    common = sorted(b_ops.keys() & c_ops.keys())
    count_changes = [
        OperationCountChange(
            name=name,
            qubits=q,
            baseline=b_ops[(name, q)],
            candidate=c_ops[(name, q)],
            delta=c_ops[(name, q)] - b_ops[(name, q)],
        )
        for name, q in common
        if b_ops[(name, q)] != c_ops[(name, q)]
    ]
    identical_resources = resources_identical(baseline, candidate)
    initial = compare_value(baseline.initial_layout, candidate.initial_layout)
    final = compare_value(baseline.final_layout, candidate.final_layout)
    unchanged = (
        identical_resources
        and not count_changes
        and initial.status == "unchanged"
        and final.status == "unchanged"
    )
    return FootprintComparison(
        status=ComparisonStatus.UNCHANGED if unchanged else ComparisonStatus.CHANGED,
        reason=None if identical_resources else "physical footprints use different resources",
        resources_identical=identical_resources,
        qubits=compare_set(baseline.qubits, candidate.qubits),
        measured_qubits=compare_set(baseline.measured_qubits, candidate.measured_qubits),
        common_operations=[OperationRef(name=n, qubits=q) for n, q in common],
        baseline_only_operations=[
            OperationRef(name=n, qubits=q) for n, q in sorted(b_ops.keys() - c_ops.keys())
        ],
        candidate_only_operations=[
            OperationRef(name=n, qubits=q) for n, q in sorted(c_ops.keys() - b_ops.keys())
        ],
        operation_count_changes=count_changes,
        initial_layout=initial,
        final_layout=final,
    )


def _resource_label(kind: ResourceKind, operation: str | None, qubits: tuple[int, ...]) -> str:
    if kind is ResourceKind.QUBIT:
        return f"qubit {qubits[0]}"
    return f"{operation}({','.join(str(q) for q in qubits)})"


def _compare_parameters(
    kind: ResourceKind,
    operation: str | None,
    qubits: tuple[int, ...],
    baseline: dict[str, CalibrationValue] | None,
    candidate: dict[str, CalibrationValue] | None,
    out: list[ParameterComparison],
    date_changes: list[str],
    unavailable: list[str],
) -> None:
    label = _resource_label(kind, operation, qubits)
    if baseline is None or candidate is None:
        side = "baseline" if baseline is None else "candidate"
        if baseline is None and candidate is None:
            side = "baseline and candidate"
        unavailable.append(f"{label}: no calibration in {side} snapshot")
        return
    for name in sorted(baseline.keys() | candidate.keys()):
        b, c = baseline.get(name), candidate.get(name)
        b_value = b.value if b else None
        c_value = c.value if c else None
        unit = (b.unit if b else None) or (c.unit if c else None)
        if b_value is None or c_value is None:
            status = "unavailable"
            unavailable.append(f"{label} {name}: unavailable")
        else:
            status = "changed" if b_value != c_value else "unchanged"
        delta = None
        if isinstance(b_value, float | int) and isinstance(c_value, float | int):
            delta = float(c_value - b_value)
        b_date = b.calibrated_at if b else None
        c_date = c.calibrated_at if c else None
        if status != "unavailable" and b_date != c_date:
            date_changes.append(f"{label} {name}: calibration date {b_date} -> {c_date}")
        out.append(
            ParameterComparison(
                resource_kind=kind,
                operation=operation,
                qubits=qubits,
                parameter=name,
                unit=unit,
                status=status,
                baseline=b_value,
                candidate=c_value,
                delta=delta,
                baseline_calibrated_at=b_date,
                candidate_calibrated_at=c_date,
            )
        )


def _index(
    calibration: FootprintCalibration,
) -> tuple[
    dict[int, dict[str, CalibrationValue] | None], dict[OpKey, dict[str, CalibrationValue] | None]
]:
    qubits = {
        q.qubit: ({p.name: p for p in q.parameters} if q.available else None)
        for q in calibration.qubits
    }
    ops: dict[OpKey, dict[str, CalibrationValue] | None] = {}
    for op in calibration.operations:
        ops[(op.name, op.qubits)] = {p.name: p for p in op.parameters} if op.available else None
    return qubits, ops


def compare_hardware(
    baseline: Run,
    candidate: Run,
    baseline_footprint: PhysicalFootprint,
    candidate_footprint: PhysicalFootprint,
    reader_for: Callable[[str], CalibrationReader | None],
) -> HardwareComparison:
    bs, cs = baseline.backend_snapshot, candidate.backend_snapshot
    if bs is None or cs is None or baseline.backend is None or candidate.backend is None:
        missing = "baseline" if bs is None or baseline.backend is None else "candidate"
        return HardwareComparison(
            status=ComparisonStatus.UNAVAILABLE,
            reason=f"{missing} run has no backend snapshot",
            baseline_snapshot_source=bs.source if bs else None,
            candidate_snapshot_source=cs.source if cs else None,
        )

    common = {
        "global_snapshot_changed": hash_json(bs.provider_raw) != hash_json(cs.provider_raw),
        "baseline_snapshot_source": bs.source,
        "candidate_snapshot_source": cs.source,
    }
    notes = []
    if bs.source != cs.source:
        notes.append(f"snapshot sources differ ({bs.source.value} vs {cs.source.value})")

    if baseline.backend.provider != candidate.backend.provider:
        return HardwareComparison(
            status=ComparisonStatus.NOT_COMPARABLE,
            reason="cross-provider hardware comparison is not supported",
            **common,
        )
    unusable = _unusable_reason(baseline_footprint, candidate_footprint)
    if unusable is not None:
        return HardwareComparison(
            status=_unusable_status(baseline_footprint, candidate_footprint),
            reason="; ".join([*notes, unusable]),
            **common,
        )
    reader = reader_for(baseline.backend.provider)
    if reader is None:
        return HardwareComparison(
            status=ComparisonStatus.UNAVAILABLE,
            reason=f"no calibration reader for provider {baseline.backend.provider!r}",
            **common,
        )

    shared_qubits = sorted(set(baseline_footprint.qubits) & set(candidate_footprint.qubits))
    shared_ops = sorted(set(_op_counts(baseline_footprint)) & set(_op_counts(candidate_footprint)))
    b_cal = reader.select(bs, shared_qubits, shared_ops)
    c_cal = reader.select(cs, shared_qubits, shared_ops)
    b_qubits, b_ops = _index(b_cal)
    c_qubits, c_ops = _index(c_cal)

    parameters: list[ParameterComparison] = []
    date_changes: list[str] = []
    unavailable: list[str] = []
    for q in shared_qubits:
        _compare_parameters(
            ResourceKind.QUBIT,
            None,
            (q,),
            b_qubits.get(q),
            c_qubits.get(q),
            parameters,
            date_changes,
            unavailable,
        )
    for name, qargs in shared_ops:
        _compare_parameters(
            ResourceKind.OPERATION,
            name,
            qargs,
            b_ops.get((name, qargs)),
            c_ops.get((name, qargs)),
            parameters,
            date_changes,
            unavailable,
        )
    excluded = sorted(set(b_cal.excluded) | set(c_cal.excluded))
    any_changed = any(p.status == "changed" for p in parameters)

    if not resources_identical(baseline_footprint, candidate_footprint):
        notes.append(
            "physical footprints differ: relevant_hardware_changed is undetermined; "
            "calibration is compared only for physical resources present on both sides"
        )
        relevant: bool | None = None
        status = ComparisonStatus.PARTIALLY_COMPARABLE
    elif any_changed:
        relevant, status = True, ComparisonStatus.CHANGED
    elif unavailable:
        notes.append("some relevant calibration data is unavailable")
        relevant, status = None, ComparisonStatus.PARTIALLY_COMPARABLE
    else:
        relevant, status = False, ComparisonStatus.UNCHANGED

    return HardwareComparison(
        status=status,
        reason="; ".join(notes) or None,
        relevant_hardware_changed=relevant,
        shared_resource_parameters=parameters,
        calibration_date_changes=date_changes,
        unavailable=unavailable,
        excluded=excluded,
        **common,
    )
