"""Read IBM ``BackendProperties`` payloads (as stored by M0) for specific physical resources.

Pure dict parsing of the raw ``provider_raw["properties"]`` JSON. It does not import Qiskit.
The payload format is IBM-specific, so this lives in the IBM adapter.
"""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from qci.domain.backend import BackendSnapshot
from qci.domain.comparison import (
    CalibrationValue,
    FootprintCalibration,
    OperationCalibration,
    QubitCalibration,
)

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
