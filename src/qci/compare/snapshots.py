"""Footprint-scoped comparison of two calibration snapshots (M1.3c, ADR 0005 section 7).

A stored run supplies the physical footprint: it only selects which physical resources are
read, and it is never compared with either snapshot. The calibration logic is the one run
comparison uses (``compare_calibration``), with one difference: units must match, so a
parameter whose unit differs between the snapshots is ``not_comparable`` and never converted.

Additions over run comparison, made here only:
- an unchanged value is labeled by its measurement dates: re-measured with the same value, not
  re-measured (one measurement reported twice), or date unavailable;
- listed error-type parameters of footprint resources with a provider value of exactly 1 are
  listed, as given.
"""

from collections.abc import Callable
from typing import Literal

from qci.compare.footprint import footprint_for_run
from qci.compare.hardware import SnapshotFields, compare_calibration
from qci.core.hashing import hash_json
from qci.core.ports import SnapshotComparisonSupport
from qci.domain.comparison import (
    ComparisonStatus,
    FootprintCalibration,
    FootprintStatus,
    HardwareComparison,
    ParameterComparison,
    ResourceKind,
)
from qci.domain.metric import EvidenceKind, Metric
from qci.domain.run import Run
from qci.domain.snapshot import (
    SNAPSHOT_COMPARISON_METHOD_VERSION,
    CalibrationSnapshot,
    ErrorValueAtOne,
    MeasurementDates,
    SnapshotComparison,
    SnapshotSide,
    UnchangedValue,
)

LIMITATIONS = [
    "This comparison reports what differs between two calibration snapshots of one backend, "
    "for the physical resources of one run's footprint. Deltas are candidate minus baseline.",
    "The footprint run only selects which physical resources are read. The run is not "
    "compared with either snapshot.",
    "Values are provider-reported and compared exactly, with no tolerance. A parameter whose "
    "unit differs between the snapshots is not compared, and no unit is converted.",
    "Relevant hardware means calibration data for the physical resources of the footprint. It "
    "does not mean a parameter is known to affect workload performance.",
    "An unchanged value that was not re-measured (the same measurement date in both "
    "snapshots) is one measurement reported twice. It is not evidence that the parameter held "
    "constant between the captures.",
    "A changed measurement date is the provider's timestamp. For virtual gates (such as rz) "
    "and configured durations (such as gate_length), the provider can update the date without "
    "a physical measurement, so 're-measured' may not mean physically re-measured.",
    "Error-type parameters with a value of exactly 1 are listed as the provider reported them. "
    "QCI does not interpret them.",
    "Pairwise general parameters (D14) and measure gate entries (D22) are not compared.",
    "Snapshot comparisons are never stored.",
]


def snapshot_comparison_id(
    baseline_id: str, candidate_id: str, footprint_run_id: str, allow_mismatch: bool
) -> str:
    return hash_json(
        {
            "allow_footprint_backend_mismatch": allow_mismatch,
            "baseline_snapshot_id": baseline_id,
            "candidate_snapshot_id": candidate_id,
            "footprint_run_id": footprint_run_id,
            "method_version": SNAPSHOT_COMPARISON_METHOD_VERSION,
        }
    )


def _side(snapshot: CalibrationSnapshot) -> SnapshotSide:
    return SnapshotSide(
        snapshot_id=snapshot.snapshot_id,
        provider=snapshot.provider,
        backend_name=snapshot.backend_name,
        content_hash=snapshot.content_hash,
        source=snapshot.source,
        captured_at=snapshot.captured_at,
        calibrated_at=snapshot.calibrated_at,
    )


def _measurement(p: ParameterComparison) -> MeasurementDates:
    b, c = p.baseline_calibrated_at, p.candidate_calibrated_at
    if b is None or c is None:
        return "measurement_date_unavailable"
    return "not_re_measured" if b == c else "re_measured_same_value"


def unchanged_values(hardware: HardwareComparison) -> list[UnchangedValue]:
    out = []
    for p in hardware.shared_resource_parameters:
        if p.status != "unchanged" or p.baseline is None:
            continue
        out.append(
            UnchangedValue(
                resource_kind=p.resource_kind,
                operation=p.operation,
                qubits=p.qubits,
                parameter=p.parameter,
                value=p.baseline,
                measurement=_measurement(p),
                baseline_measured_at=p.baseline_calibrated_at,
                candidate_measured_at=p.candidate_calibrated_at,
            )
        )
    return out


def error_values_at_one(
    side: Literal["baseline", "candidate"],
    calibration: FootprintCalibration,
    error_parameters: tuple[str, ...],
) -> list[ErrorValueAtOne]:
    """Listed error parameters whose value is exactly 1. Names are matched exactly."""
    found: list[ErrorValueAtOne] = []
    resources = [
        (ResourceKind.QUBIT, None, (q.qubit,), q.parameters) for q in calibration.qubits
    ] + [(ResourceKind.OPERATION, o.name, o.qubits, o.parameters) for o in calibration.operations]
    for kind, operation, qubits, parameters in resources:
        for p in parameters:
            if p.name in error_parameters and isinstance(p.value, float) and p.value == 1.0:
                found.append(
                    ErrorValueAtOne(
                        side=side,
                        resource_kind=kind,
                        operation=operation,
                        qubits=qubits,
                        parameter=p.name,
                        value=p.value,
                        measured_at=p.calibrated_at,
                    )
                )
    return found


def compare_snapshots(
    baseline: CalibrationSnapshot,
    candidate: CalibrationSnapshot,
    footprint_run: Run,
    support_for: Callable[[str], SnapshotComparisonSupport | None],
    *,
    allow_footprint_backend_mismatch: bool = False,
) -> SnapshotComparison:
    footprint = footprint_for_run(footprint_run)
    footprint_backend = footprint_run.backend.name if footprint_run.backend else None
    elapsed = (candidate.captured_at - baseline.captured_at).total_seconds()

    def result(
        hardware: HardwareComparison,
        unchanged: list[UnchangedValue] | None = None,
        at_one: list[ErrorValueAtOne] | None = None,
        error_parameters: tuple[str, ...] = (),
    ) -> SnapshotComparison:
        return SnapshotComparison(
            snapshot_comparison_id=snapshot_comparison_id(
                baseline.snapshot_id,
                candidate.snapshot_id,
                footprint_run.run_id,
                allow_footprint_backend_mismatch,
            ),
            status=hardware.status,
            baseline=_side(baseline),
            candidate=_side(candidate),
            elapsed_between_captures=Metric(
                name="elapsed_between_captures",
                value=elapsed,
                unit="s",
                kind=EvidenceKind.CALCULATED,
                method="candidate captured_at minus baseline captured_at",
                method_version="1",
            ),
            footprint_run_id=footprint_run.run_id,
            footprint_backend=footprint_backend,
            allow_footprint_backend_mismatch=allow_footprint_backend_mismatch,
            footprint=footprint,
            hardware=hardware,
            unchanged_values=unchanged or [],
            error_parameters=list(error_parameters),
            error_values_at_one=at_one or [],
            limitations=LIMITATIONS,
        )

    b_device = f"{baseline.provider}/{baseline.backend_name}"
    c_device = f"{candidate.provider}/{candidate.backend_name}"
    if b_device != c_device:
        return result(
            HardwareComparison(
                status=ComparisonStatus.NOT_COMPARABLE,
                reason=f"snapshots are of different backends (baseline {b_device}, candidate "
                f"{c_device}); calibration of different devices is not compared",
            )
        )

    common: SnapshotFields = {
        "global_snapshot_changed": baseline.content_hash != candidate.content_hash,
        "baseline_snapshot_source": baseline.source,
        "candidate_snapshot_source": candidate.source,
    }
    notes: list[str] = []
    if baseline.source != candidate.source:
        notes.append(
            f"snapshot sources differ ({baseline.source.value} vs {candidate.source.value})"
        )

    if footprint.status is not FootprintStatus.AVAILABLE:
        dynamic = footprint.status is FootprintStatus.UNSUPPORTED_DYNAMIC
        return result(
            HardwareComparison(
                status=ComparisonStatus.NOT_COMPARABLE if dynamic else ComparisonStatus.UNAVAILABLE,
                reason="; ".join(
                    [
                        *notes,
                        f"footprint of run {footprint_run.run_id} {footprint.status.value}: "
                        f"{footprint.reason}",
                    ]
                ),
                **common,
            )
        )

    mismatch = footprint_backend != baseline.backend_name
    backends = (
        f"footprint taken from run {footprint_run.run_id} on {footprint_backend}; "
        f"snapshots are of {baseline.backend_name}"
    )
    if mismatch and not allow_footprint_backend_mismatch:
        return result(
            HardwareComparison(
                status=ComparisonStatus.NOT_COMPARABLE,
                reason="; ".join(
                    [
                        *notes,
                        f"{backends}; a footprint from another backend is used only when "
                        "allow_footprint_backend_mismatch is set",
                    ]
                ),
                **common,
            )
        )

    support = support_for(baseline.provider)
    if support is None:
        return result(
            HardwareComparison(
                status=ComparisonStatus.UNAVAILABLE,
                reason=f"no snapshot comparison support for provider {baseline.provider!r}",
                **common,
            )
        )

    qubits = list(footprint.qubits)
    operations = [(op.name, op.qubits) for op in footprint.operations]
    if mismatch:
        notes.append(backends)
        missing = [
            f"footprint resources missing from the {side} snapshot: {', '.join(labels)}"
            for side, snapshot in (("baseline", baseline), ("candidate", candidate))
            if (labels := support.resources.missing_resources(snapshot, qubits, operations))
        ]
        if missing:
            return result(
                HardwareComparison(
                    status=ComparisonStatus.NOT_COMPARABLE,
                    reason="; ".join([*notes, *missing]),
                    **common,
                ),
                error_parameters=support.error_parameters,
            )

    b_view = support.resources.backend_snapshot(baseline)
    c_view = support.resources.backend_snapshot(candidate)
    hardware = compare_calibration(
        b_view,
        c_view,
        footprint,
        footprint,
        support.reader,
        notes,
        common,
        require_matching_units=True,
    )
    at_one = [
        *error_values_at_one(
            "baseline",
            support.reader.select(b_view, qubits, operations),
            support.error_parameters,
        ),
        *error_values_at_one(
            "candidate",
            support.reader.select(c_view, qubits, operations),
            support.error_parameters,
        ),
    ]
    return result(hardware, unchanged_values(hardware), at_one, support.error_parameters)
