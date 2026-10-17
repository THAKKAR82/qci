"""A fake backend's frozen calibration, as stored in one run, against one live snapshot of the
device the fake was built from (M1.4b, ADR 0007), scoped to the run's physical footprint.

Direction: the fake run is the baseline and the live snapshot the candidate, so every delta and
every date difference is live minus fake. The calibration logic is ``compare_calibration`` with
matching units required, unchanged. Additions made here only: parameters reported by one side
only, unit differences, measurement dates side by side with calculated differences, and listed
error-type values equal to 1. The run's ``captured_at`` is when QCI read the fake, not a
calibration date, and is never used.
"""

from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Literal

from qci.compare.footprint import footprint_for_run
from qci.compare.hardware import SnapshotFields, compare_calibration
from qci.compare.snapshots import error_values_at_one
from qci.core.hashing import hash_json
from qci.core.ports import RunSnapshotComparisonSupport
from qci.domain.backend import SnapshotSource
from qci.domain.comparison import (
    CalibrationValue,
    ComparisonStatus,
    FootprintCalibration,
    FootprintStatus,
    HardwareComparison,
    ResourceKind,
)
from qci.domain.metric import EvidenceKind, Metric
from qci.domain.run import Run
from qci.domain.snapshot import (
    RUN_SNAPSHOT_COMPARISON_METHOD_VERSION,
    CalibrationSnapshot,
    DeviceMapping,
    ErrorValueAtOne,
    FakeRunSide,
    LiveSnapshotSide,
    MeasurementDateDifference,
    ParameterOnOneSide,
    RunSnapshotComparison,
    UnitDifference,
)

LIMITATIONS = [
    "This comparison reports what differs between the calibration frozen into a fake backend, "
    "as stored in one run, and one live snapshot of the device the fake was built from, for the "
    "physical resources of that run's footprint. Deltas and date differences are live minus "
    "fake.",
    "The fake-to-device correspondence comes from an explicit list in the provider adapter and "
    "is checked against the device name recorded in the fake's own calibration payload. QCI "
    "cannot check that the fake's payload equals what the device published at that time.",
    "Both sides are reports about one device at different times. Qubit and gate indices are "
    "assumed to name the same physical resources on both sides. A device revision between the "
    "two dates (both backend versions are shown) could break this, and QCI cannot detect it.",
    "Values are provider-reported and compared exactly, with no tolerance. A parameter whose "
    "unit differs between the two sides is not compared, and no unit is converted.",
    "A changed value means only that the two reports give different values. This comparison "
    "does not say whether the fake's noise model suits the workload, and it does not predict "
    "how the workload would behave on the device. Nothing is simulated against the live "
    "snapshot.",
    "This compares calibration data: the values the fake backend was built from and the live "
    "device's reported values. It does not compare the noise model a simulator constructs from "
    "that data; a simulator may use only some of these parameters, in its own way.",
    "Measurement dates are provider timestamps, shown as given. Their differences are "
    "calculated. For virtual gates (such as rz) and configured durations (such as gate_length), "
    "the date can be the document timestamp rather than the time of a physical measurement.",
    "The run's captured_at is when QCI read the fake backend, not a calibration date, and is "
    "not used.",
    "Relevant hardware means calibration data for the physical resources of the footprint. It "
    "does not mean a parameter is known to affect workload performance.",
    "The raw payloads of a fake and a live device always differ, so global_snapshot_changed is "
    "true in practice and carries no further information here.",
    "Error-type parameters with a value of exactly 1 are listed as the provider reported them. "
    "QCI does not interpret them.",
    "Pairwise general parameters (D14) and measure gate entries (D22) are not compared.",
    "These comparisons are never stored.",
]

ResourceKey = tuple[ResourceKind, str | None, tuple[int, ...]]
Side = Literal["baseline", "candidate"]


def run_snapshot_comparison_id(run_id: str, snapshot_id: str) -> str:
    return hash_json(
        {
            "method_version": RUN_SNAPSHOT_COMPARISON_METHOD_VERSION,
            "run_id": run_id,
            "snapshot_id": snapshot_id,
        }
    )


def _sort_key(
    kind: ResourceKind, operation: str | None, qubits: tuple[int, ...], parameter: str
) -> tuple[str, str, tuple[int, ...], str]:
    return (kind.value, operation or "", qubits, parameter)


def _seconds(name: str, method: str, later: datetime, earlier: datetime) -> Metric:
    return Metric(
        name=name,
        value=(later - earlier).total_seconds(),
        unit="s",
        kind=EvidenceKind.CALCULATED,
        method=method,
        method_version="1",
    )


def _extreme(name: str, which: str, values: list[float]) -> Metric | None:
    if not values:
        return None
    return Metric(
        name=name,
        value=min(values) if which == "minimum" else max(values),
        unit="s",
        kind=EvidenceKind.CALCULATED,
        method=f"{which} of live_minus_fake over the compared parameters",
        method_version="1",
    )


def _by_resource(
    calibration: FootprintCalibration,
) -> dict[ResourceKey, dict[str, CalibrationValue]]:
    """Reported parameters per available resource."""
    out: dict[ResourceKey, dict[str, CalibrationValue]] = {}
    for q in calibration.qubits:
        if q.available:
            out[(ResourceKind.QUBIT, None, (q.qubit,))] = {p.name: p for p in q.parameters}
    for o in calibration.operations:
        if o.available:
            out[(ResourceKind.OPERATION, o.name, o.qubits)] = {p.name: p for p in o.parameters}
    return out


def parameters_on_one_side(
    baseline: FootprintCalibration, candidate: FootprintCalibration
) -> list[ParameterOnOneSide]:
    """Parameters one side reports and the other does not, for resources both sides have.

    Built from the reader selections, where a reported parameter has an entry even when its
    value is unrepresentable, and an unreported one has none."""
    b, c = _by_resource(baseline), _by_resource(candidate)
    found: list[ParameterOnOneSide] = []
    for key in b.keys() & c.keys():
        kind, operation, qubits = key
        sides: tuple[tuple[Side, set[str]], ...] = (
            ("baseline", set(b[key]) - set(c[key])),
            ("candidate", set(c[key]) - set(b[key])),
        )
        for side, names in sides:
            found += [
                ParameterOnOneSide(
                    side=side,
                    resource_kind=kind,
                    operation=operation,
                    qubits=qubits,
                    parameter=name,
                )
                for name in names
            ]
    return sorted(
        found,
        key=lambda e: (e.side, *_sort_key(e.resource_kind, e.operation, e.qubits, e.parameter)),
    )


def unit_differences(
    hardware: HardwareComparison, baseline: FootprintCalibration, candidate: FootprintCalibration
) -> list[UnitDifference]:
    """Both units of every parameter ``compare_calibration`` left uncompared for its units."""
    b, c = _by_resource(baseline), _by_resource(candidate)
    found = []
    for p in hardware.shared_resource_parameters:
        if p.status != "not_comparable":
            continue
        key = (p.resource_kind, p.operation, p.qubits)
        found.append(
            UnitDifference(
                resource_kind=p.resource_kind,
                operation=p.operation,
                qubits=p.qubits,
                parameter=p.parameter,
                baseline_unit=b[key][p.parameter].unit,
                candidate_unit=c[key][p.parameter].unit,
            )
        )
    return sorted(
        found, key=lambda u: _sort_key(u.resource_kind, u.operation, u.qubits, u.parameter)
    )


def measurement_dates(hardware: HardwareComparison) -> list[MeasurementDateDifference]:
    found = []
    for p in hardware.shared_resource_parameters:
        b, c = p.baseline_calibrated_at, p.candidate_calibrated_at
        found.append(
            MeasurementDateDifference(
                resource_kind=p.resource_kind,
                operation=p.operation,
                qubits=p.qubits,
                parameter=p.parameter,
                baseline_measured_at=b,
                candidate_measured_at=c,
                live_minus_fake=None
                if b is None or c is None
                else _seconds("live_minus_fake", "live measured_at minus fake measured_at", c, b),
            )
        )
    return sorted(
        found, key=lambda d: _sort_key(d.resource_kind, d.operation, d.qubits, d.parameter)
    )


def _sorted_at_one(items: Iterable[ErrorValueAtOne]) -> list[ErrorValueAtOne]:
    return sorted(
        items,
        key=lambda e: (e.side, *_sort_key(e.resource_kind, e.operation, e.qubits, e.parameter)),
    )


def compare_run_to_snapshot(
    run: Run,
    snapshot: CalibrationSnapshot,
    support_for: Callable[[str], RunSnapshotComparisonSupport | None],
) -> RunSnapshotComparison:
    footprint = footprint_for_run(run)
    bs, backend = run.backend_snapshot, run.backend
    support = support_for(snapshot.provider) if backend else None
    recorded = support.devices.recorded_device(bs) if support and bs else (None, None)
    package = support.fake_package if support else None

    candidate = LiveSnapshotSide(
        snapshot_id=snapshot.snapshot_id,
        provider=snapshot.provider,
        backend_name=snapshot.backend_name,
        backend_version=snapshot.backend_version,
        content_hash=snapshot.content_hash,
        source=snapshot.source,
        captured_at=snapshot.captured_at,
        calibrated_at=snapshot.calibrated_at,
    )
    baseline = FakeRunSide(
        run_id=run.run_id,
        provider=backend.provider if backend else None,
        backend_name=backend.name if backend else None,
        backend_version=backend.version if backend else None,
        snapshot_source=bs.source if bs else None,
        calibrated_at=bs.calibrated_at if bs else None,
        recorded_device=recorded[0],
        recorded_device_version=recorded[1],
        qiskit_ibm_runtime_version=run.provenance.environment.packages.get(package)
        if package
        else None,
    )
    calibrated_at_difference = (
        _seconds(
            "calibrated_at_difference",
            "live calibrated_at minus fake calibrated_at",
            snapshot.calibrated_at,
            bs.calibrated_at,
        )
        if bs and bs.calibrated_at and snapshot.calibrated_at
        else None
    )

    def result(
        hardware: HardwareComparison,
        mapping: DeviceMapping | None = None,
        error_parameters: tuple[str, ...] = (),
        *,
        one_side: list[ParameterOnOneSide] | None = None,
        units: list[UnitDifference] | None = None,
        at_one: list[ErrorValueAtOne] | None = None,
    ) -> RunSnapshotComparison:
        dates = measurement_dates(hardware)
        differences = [d.live_minus_fake.value for d in dates if d.live_minus_fake is not None]
        return RunSnapshotComparison(
            run_snapshot_comparison_id=run_snapshot_comparison_id(run.run_id, snapshot.snapshot_id),
            status=hardware.status,
            baseline=baseline,
            candidate=candidate,
            device_mapping=mapping,
            footprint=footprint,
            hardware=hardware,
            parameters_on_one_side=one_side or [],
            unit_differences=units or [],
            error_parameters=list(error_parameters),
            error_values_at_one=at_one or [],
            calibrated_at_difference=calibrated_at_difference,
            measurement_dates=dates,
            live_minus_fake_min=_extreme("live_minus_fake_min", "minimum", differences),
            live_minus_fake_max=_extreme("live_minus_fake_max", "maximum", differences),
            limitations=LIMITATIONS,
        )

    # 1. The run must carry a backend and its calibration.
    if bs is None or backend is None:
        return result(
            HardwareComparison(
                status=ComparisonStatus.UNAVAILABLE,
                reason=f"run {run.run_id} has no backend or no backend snapshot",
                baseline_snapshot_source=bs.source if bs else None,
                candidate_snapshot_source=snapshot.source,
            )
        )
    common: SnapshotFields = {
        "global_snapshot_changed": hash_json(bs.provider_raw) != hash_json(snapshot.provider_raw),
        "baseline_snapshot_source": bs.source,
        "candidate_snapshot_source": snapshot.source,
    }

    def stop(
        status: ComparisonStatus,
        reasons: list[str],
        mapping: DeviceMapping | None = None,
        error_parameters: tuple[str, ...] = (),
    ) -> RunSnapshotComparison:
        hardware = HardwareComparison(status=status, reason="; ".join(reasons), **common)
        return result(hardware, mapping, error_parameters)

    # 2-4. Sources and provider.
    if bs.source is not SnapshotSource.STATIC_FAKE:
        return stop(
            ComparisonStatus.NOT_COMPARABLE,
            [
                f"run snapshot source is {bs.source.value}, not static_fake; this comparison "
                "sets a fake backend's frozen calibration against a live snapshot"
            ],
        )
    if snapshot.source is not SnapshotSource.LIVE_CALIBRATION:
        return stop(
            ComparisonStatus.NOT_COMPARABLE,
            [
                f"snapshot {snapshot.snapshot_id} source is {snapshot.source.value}, "
                "not live_calibration"
            ],
        )
    if backend.provider != snapshot.provider:
        return stop(
            ComparisonStatus.NOT_COMPARABLE,
            [
                f"run provider {backend.provider} differs from snapshot provider "
                f"{snapshot.provider}; calibration from different providers is not compared"
            ],
        )

    # 5. Provider support.
    if support is None:
        return stop(
            ComparisonStatus.UNAVAILABLE,
            [f"no run-to-snapshot comparison support for provider {snapshot.provider!r}"],
        )
    error_parameters = support.snapshot.error_parameters

    # 6-8. The explicit fake-to-device mapping, checked against both sides.
    device = support.devices.device_for(backend.name)
    if device is None:
        return stop(
            ComparisonStatus.NOT_COMPARABLE,
            [
                f"{backend.name} has no entry in {support.mapping_source}; no device name is "
                "derived from a fake's name"
            ],
            error_parameters=error_parameters,
        )
    mapping = DeviceMapping(fake=backend.name, device=device, source=support.mapping_source)
    notes = [f"{backend.name} is the fake built from {device} calibration ({mapping.source})"]
    if snapshot.backend_name != device:
        return stop(
            ComparisonStatus.NOT_COMPARABLE,
            [
                *notes,
                f"snapshot {snapshot.snapshot_id} is of {snapshot.backend_name}, not the mapped "
                f"device {device}; calibration of different devices is not compared",
            ],
            mapping=mapping,
            error_parameters=error_parameters,
        )
    if recorded[0] != device:
        return stop(
            ComparisonStatus.NOT_COMPARABLE,
            [
                *notes,
                f"the run's recorded calibration names {recorded[0] or 'no device'}, not the "
                f"mapped device {device}",
            ],
            mapping=mapping,
            error_parameters=error_parameters,
        )

    # 9. The footprint.
    if footprint.status is not FootprintStatus.AVAILABLE:
        dynamic = footprint.status is FootprintStatus.UNSUPPORTED_DYNAMIC
        return stop(
            ComparisonStatus.NOT_COMPARABLE if dynamic else ComparisonStatus.UNAVAILABLE,
            [
                *notes,
                f"footprint of run {run.run_id} {footprint.status.value}: {footprint.reason}",
            ],
            mapping=mapping,
            error_parameters=error_parameters,
        )

    # 10. Every footprint resource must exist on both sides.
    qubits = list(footprint.qubits)
    operations = [(op.name, op.qubits) for op in footprint.operations]
    missing = [
        f"footprint resources missing from the {side}: {', '.join(labels)}"
        for side, labels in (
            (
                f"baseline (run {run.run_id} on {backend.name})",
                support.devices.missing_resources(bs, qubits, operations),
            ),
            (
                f"candidate (snapshot {snapshot.snapshot_id} of {snapshot.backend_name})",
                support.snapshot.resources.missing_resources(snapshot, qubits, operations),
            ),
        )
        if labels
    ]
    if missing:
        return stop(
            ComparisonStatus.NOT_COMPARABLE,
            [*notes, *missing],
            mapping=mapping,
            error_parameters=error_parameters,
        )

    # 11. The calibration comparison, unchanged, with the same footprint on both sides.
    reader = support.snapshot.reader
    live_view = support.snapshot.resources.backend_snapshot(snapshot)
    hardware = compare_calibration(
        bs, live_view, footprint, footprint, reader, notes, common, require_matching_units=True
    )
    shared_ops = sorted(set(operations))
    b_cal = reader.select(bs, sorted(set(qubits)), shared_ops)
    c_cal = reader.select(live_view, sorted(set(qubits)), shared_ops)
    at_one = [
        *error_values_at_one("baseline", b_cal, error_parameters),
        *error_values_at_one("candidate", c_cal, error_parameters),
    ]
    return result(
        hardware,
        mapping,
        error_parameters,
        one_side=parameters_on_one_side(b_cal, c_cal),
        units=unit_differences(hardware, b_cal, c_cal),
        at_one=_sorted_at_one(at_one),
    )
