"""Read IBM ``BackendProperties`` payloads (as stored by M0) for specific physical resources.

Pure dict parsing of the raw ``provider_raw["properties"]`` JSON. It does not import Qiskit.
The payload format is IBM-specific, so this lives in the IBM adapter.
"""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from qci.core.ports import RunSnapshotComparisonSupport, SnapshotComparisonSupport
from qci.domain.backend import BackendSnapshot
from qci.domain.comparison import (
    CalibrationValue,
    FootprintCalibration,
    OperationCalibration,
    QubitCalibration,
)
from qci.domain.snapshot import CalibrationSnapshot, Measurement

ERROR_PARAMETERS = ("gate_error", "readout_error", "init_error")
"""IBM parameters that snapshot comparison treats as error-type, as an explicit list. Names
are never matched by substring; an unlisted parameter is never reported as an error value."""

FAKE_DEVICE_SOURCES: Mapping[str, str] = {
    "fake_fez": "ibm_fez",
    "fake_kingston": "ibm_kingston",
    "fake_marrakesh": "ibm_marrakesh",
}
"""Fake backend name -> the real device whose calibration the fake was built from. Explicit
and exact. A fake not listed here is not compared with any live snapshot. Entries are added
only when verified (see the test below); device names are never derived from fake names."""

FAKE_DEVICE_SOURCES_NAME = "qiskit_ibm FAKE_DEVICE_SOURCES"
FAKE_PACKAGE = "qiskit-ibm-runtime"

PRESENCE_INSTRUCTIONS = ("measure", "reset", "delay")
"""Present on a device if listed in ``supported_instructions`` and all their qubits exist."""

EXTRACTION_METHOD = "qiskit_ibm.properties"
EXTRACTION_METHOD_VERSION = "1"

# Readout calibration is reported per qubit by IBM; measure has no gate entry.
_MEASURE_NOTE = "readout calibration is reported under the measured qubit"
_NO_CALIBRATION = {"delay": "the provider reports no calibration for delay"}
_GENERAL_EXCLUDED = (
    "general: pairwise/global parameters (e.g. jq_6272, zz_6272) use an ambiguous qubit-pair "
    "encoding and are not scoped to physical resources"
)


def _date(raw: Any) -> datetime | None:
    if isinstance(raw, Mapping) and isinstance(raw.get("$datetime"), str):
        parsed = datetime.fromisoformat(raw["$datetime"])
        return parsed.astimezone(UTC) if parsed.tzinfo else None
    return None


def _value(raw: Any) -> float | str | None:
    if isinstance(raw, bool):
        return str(raw)
    if isinstance(raw, int | float):
        return float(raw)
    if isinstance(raw, str):
        return raw
    return None  # missing, non-finite ({"$float": ...}) or complex: unavailable, never zero


def _parameters(entries: Any) -> list[CalibrationValue]:
    if not isinstance(entries, list):
        return []
    params = []
    for entry in entries:
        if isinstance(entry, Mapping) and isinstance(entry.get("name"), str):
            params.append(
                CalibrationValue(
                    name=entry["name"],
                    value=_value(entry.get("value")),
                    unit=entry.get("unit") or None,
                    calibrated_at=_date(entry.get("date")),
                )
            )
    return sorted(params, key=lambda p: p.name)


class IbmPropertiesCalibrationReader:
    def select(
        self,
        snapshot: BackendSnapshot,
        qubits: Sequence[int],
        operations: Sequence[tuple[str, tuple[int, ...]]],
    ) -> FootprintCalibration:
        properties: Any = snapshot.provider_raw.get("properties")
        if not isinstance(properties, Mapping):
            note = "snapshot has no IBM properties payload"
            return FootprintCalibration(
                qubits=[QubitCalibration(qubit=q, available=False) for q in qubits],
                operations=[
                    OperationCalibration(name=n, qubits=qa, available=False, note=note)
                    for n, qa in operations
                ],
            )

        raw_qubits = properties.get("qubits")
        qubit_entries = raw_qubits if isinstance(raw_qubits, list) else []
        selected_qubits = []
        for q in qubits:
            params = _parameters(qubit_entries[q]) if 0 <= q < len(qubit_entries) else []
            selected_qubits.append(
                QubitCalibration(qubit=q, available=bool(params), parameters=params)
            )

        gate_index: dict[tuple[str, tuple[int, ...]], list[Any]] = {}
        raw_gates = properties.get("gates")
        for gate in raw_gates if isinstance(raw_gates, list) else []:
            if not isinstance(gate, Mapping) or not isinstance(gate.get("gate"), str):
                continue
            gate_qubits = gate.get("qubits")
            if not isinstance(gate_qubits, list) or not all(
                isinstance(x, int) for x in gate_qubits
            ):
                continue
            gate_index.setdefault((gate["gate"], tuple(gate_qubits)), []).append(gate)

        selected_ops = []
        for name, qargs in operations:
            matches = gate_index.get((name, qargs), [])
            if name == "measure":
                selected_ops.append(
                    OperationCalibration(
                        name=name, qubits=qargs, available=True, note=_MEASURE_NOTE
                    )
                )
            elif len(matches) == 1:
                selected_ops.append(
                    OperationCalibration(
                        name=name,
                        qubits=qargs,
                        available=True,
                        parameters=_parameters(matches[0].get("parameters")),
                    )
                )
            else:
                note = (
                    "ambiguous: multiple calibration entries for these ordered qubits"
                    if matches
                    else _NO_CALIBRATION.get(
                        name, "no calibration entry for this operation on these ordered qubits"
                    )
                )
                selected_ops.append(
                    OperationCalibration(name=name, qubits=qargs, available=False, note=note)
                )

        excluded = [_GENERAL_EXCLUDED] if properties.get("general") else []
        return FootprintCalibration(
            qubits=selected_qubits, operations=selected_ops, excluded=excluded
        )


def gate_resource(name: str, qubits: Sequence[int]) -> str:
    return f"gate/{name}/{','.join(str(q) for q in qubits)}"


def _entry_measurements(kind: str, resource: str, entries: Any) -> list[Measurement]:
    """One row per reported parameter, in payload order. Duplicates are kept."""
    rows: list[Measurement] = []
    for entry in entries if isinstance(entries, list) else []:
        if isinstance(entry, Mapping) and isinstance(entry.get("name"), str):
            rows.append(
                Measurement(
                    resource_kind=kind,
                    resource=resource,
                    parameter=entry["name"],
                    value=_value(entry.get("value")),
                    unit=entry.get("unit") or None,
                    measured_at=_date(entry.get("date")),
                )
            )
    return rows


def extract_measurements(properties: Any) -> list[Measurement]:
    """Project a stored ``BackendProperties`` payload onto generic measurement rows.

    Uses the reader's own parsing helpers, so a selected value always equals its row. Entries
    the reader cannot address (no name, or non-integer qubits) produce no row; they stay in the
    raw payload. A parameter the provider did not report has no row. An unrepresentable value
    (non-finite, complex, redacted) has ``value=None``, never 0.
    """
    if not isinstance(properties, Mapping):
        return []
    rows: list[Measurement] = []
    raw_qubits = properties.get("qubits")
    for index, entries in enumerate(raw_qubits if isinstance(raw_qubits, list) else []):
        rows += _entry_measurements("qubit", f"qubit/{index}", entries)
    raw_gates = properties.get("gates")
    for gate in raw_gates if isinstance(raw_gates, list) else []:
        if not isinstance(gate, Mapping) or not isinstance(gate.get("gate"), str):
            continue
        gate_qubits = gate.get("qubits")
        if not isinstance(gate_qubits, list) or not all(isinstance(x, int) for x in gate_qubits):
            continue
        rows += _entry_measurements(
            "gate", gate_resource(gate["gate"], gate_qubits), gate.get("parameters")
        )
    rows += _entry_measurements("general", "general", properties.get("general"))
    return rows


def _label(name: str | None, qubits: Sequence[int]) -> str:
    if name is None:
        return f"qubit {qubits[0]}"
    return f"{name}({','.join(str(q) for q in qubits)})"


def _int_tuple(raw: Any) -> tuple[int, ...] | None:
    if isinstance(raw, list) and all(isinstance(x, int) and not isinstance(x, bool) for x in raw):
        return tuple(raw)
    return None


def missing_resources(
    provider_raw: Mapping[str, Any],
    qubits: Sequence[int],
    operations: Sequence[tuple[str, tuple[int, ...]]],
) -> list[str]:
    """Labels of the physical resources a stored IBM configuration does not have.

    A qubit is present if it is below ``n_qubits``. ``measure``, ``reset`` and ``delay`` are
    present if listed in ``supported_instructions`` and all their qubits are present. Another
    operation is present if its ``gates`` entry's ``coupling_map`` holds the exact ordered
    qubits. Anything else is missing, and so is every resource when there is no configuration.
    """
    config = provider_raw.get("configuration")
    if not isinstance(config, Mapping):
        return [_label(None, (q,)) for q in qubits] + [_label(n, qa) for n, qa in operations]
    raw_n = config.get("n_qubits")
    n_qubits = raw_n if isinstance(raw_n, int) and not isinstance(raw_n, bool) else 0
    raw_supported = config.get("supported_instructions")
    supported = set(raw_supported) if isinstance(raw_supported, list) else set()
    coupling: dict[str, set[tuple[int, ...]]] = {}
    raw_gates = config.get("gates")
    for gate in raw_gates if isinstance(raw_gates, list) else []:
        if not isinstance(gate, Mapping) or not isinstance(gate.get("name"), str):
            continue
        entries = gate.get("coupling_map")
        pairs = coupling.setdefault(gate["name"], set())
        for entry in entries if isinstance(entries, list) else []:
            ordered = _int_tuple(entry)
            if ordered is not None:
                pairs.add(ordered)

    def present(q: int) -> bool:
        return 0 <= q < n_qubits

    missing = [_label(None, (q,)) for q in qubits if not present(q)]
    for name, qargs in operations:
        if name in PRESENCE_INSTRUCTIONS:
            found = name in supported and all(present(q) for q in qargs)
        else:
            found = qargs in coupling.get(name, set())
        if not found:
            missing.append(_label(name, qargs))
    return missing


class IbmSnapshotResourceIndex:
    """``SnapshotResourceIndex`` for stored IBM snapshots."""

    def backend_snapshot(self, snapshot: CalibrationSnapshot) -> BackendSnapshot:
        config: Any = snapshot.provider_raw.get("configuration")
        config = config if isinstance(config, Mapping) else {}
        raw_basis = config.get("basis_gates")
        raw_coupling = config.get("coupling_map")
        edges = [
            (pair[0], pair[1])
            for pair in (_int_tuple(e) for e in (raw_coupling or []))
            if pair is not None and len(pair) == 2
        ]
        return BackendSnapshot(
            source=snapshot.source,
            captured_at=snapshot.captured_at,
            calibrated_at=snapshot.calibrated_at,
            basis_gates=[g for g in raw_basis if isinstance(g, str)]
            if isinstance(raw_basis, list)
            else [],
            coupling_edges=edges if isinstance(raw_coupling, list) else [],
            provider_raw=snapshot.provider_raw,
        )

    def missing_resources(
        self,
        snapshot: CalibrationSnapshot,
        qubits: Sequence[int],
        operations: Sequence[tuple[str, tuple[int, ...]]],
    ) -> list[str]:
        return missing_resources(snapshot.provider_raw, qubits, operations)


def snapshot_comparison_support() -> SnapshotComparisonSupport:
    return SnapshotComparisonSupport(
        reader=IbmPropertiesCalibrationReader(),
        resources=IbmSnapshotResourceIndex(),
        error_parameters=ERROR_PARAMETERS,
    )


class IbmFakeDeviceIndex:
    """``FakeDeviceIndex`` for IBM fake backends, from ``FAKE_DEVICE_SOURCES``."""

    def device_for(self, backend_name: str) -> str | None:
        return FAKE_DEVICE_SOURCES.get(backend_name)

    def recorded_device(self, snapshot: BackendSnapshot) -> tuple[str | None, str | None]:
        properties: Any = snapshot.provider_raw.get("properties")
        if not isinstance(properties, Mapping):
            return None, None
        name, version = properties.get("backend_name"), properties.get("backend_version")
        return (
            name if isinstance(name, str) else None,
            version if isinstance(version, str) else None,
        )

    def missing_resources(
        self,
        snapshot: BackendSnapshot,
        qubits: Sequence[int],
        operations: Sequence[tuple[str, tuple[int, ...]]],
    ) -> list[str]:
        return missing_resources(snapshot.provider_raw, qubits, operations)


def run_snapshot_comparison_support() -> RunSnapshotComparisonSupport:
    return RunSnapshotComparisonSupport(
        snapshot=snapshot_comparison_support(),
        devices=IbmFakeDeviceIndex(),
        mapping_source=FAKE_DEVICE_SOURCES_NAME,
        fake_package=FAKE_PACKAGE,
    )
