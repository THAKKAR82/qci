"""IBM properties reader: selection is scoped to exact physical resources."""

from datetime import UTC, datetime

from conftest import T0, ibm_properties
from qci.adapters.qiskit_ibm.calibration import IbmPropertiesCalibrationReader
from qci.domain.backend import BackendSnapshot, SnapshotSource


def snapshot(properties: object) -> BackendSnapshot:
    return BackendSnapshot(
        source=SnapshotSource.STATIC_FAKE,
        captured_at=T0,
        basis_gates=[],
        coupling_edges=[],
        provider_raw={"properties": properties, "configuration": None},
    )


READER = IbmPropertiesCalibrationReader()


def test_selects_only_requested_qubits_with_decoded_dates() -> None:
    cal = READER.select(snapshot(ibm_properties()), [1, 2], [])
    assert [q.qubit for q in cal.qubits] == [1, 2]
    t1 = next(p for p in cal.qubits[0].parameters if p.name == "T1")
    assert t1.value == 100.0 and t1.unit == "us"
    assert t1.calibrated_at == datetime(2025, 2, 26, 7, 0, tzinfo=UTC)


def test_ordered_qargs_matter_and_missing_operations_are_unavailable() -> None:
    props = ibm_properties()
    props["gates"] = [g for g in props["gates"] if g["qubits"] != [0, 1]]  # keep only ecr(1,0)
    cal = READER.select(snapshot(props), [], [("ecr", (1, 0)), ("ecr", (0, 1)), ("delay", (0,))])
    by_key = {(o.name, o.qubits): o for o in cal.operations}
    assert by_key[("ecr", (1, 0))].available
    assert by_key[("ecr", (1, 0))].parameters[0].value == 0.005
    assert not by_key[("ecr", (0, 1))].available
    assert not by_key[("delay", (0,))].available
    assert "delay" in (by_key[("delay", (0,))].note or "")


def test_missing_values_are_none_never_zero() -> None:
    props = ibm_properties()
    props["qubits"][1][0]["value"] = None
    props["qubits"][2][0]["value"] = {"$float": "nan"}
    cal = READER.select(snapshot(props), [1, 2, 99], [])
    assert cal.qubits[0].parameters[0].value is None
    assert cal.qubits[1].parameters[0].value is None
    assert not cal.qubits[2].available  # qubit not in payload


def test_measure_is_covered_by_qubit_readout_and_general_is_excluded() -> None:
    cal = READER.select(snapshot(ibm_properties()), [0], [("measure", (0,))])
    assert cal.operations[0].available and cal.operations[0].parameters == []
    assert any("general" in item for item in cal.excluded)


def test_snapshot_without_properties_is_unavailable() -> None:
    cal = READER.select(snapshot(None), [0], [("x", (0,))])
    assert not cal.qubits[0].available and not cal.operations[0].available


def test_reader_works_on_real_fake_sherbrooke_payload() -> None:
    from qiskit_ibm_runtime.fake_provider import FakeSherbrooke

    from qci.adapters.qiskit_ibm.jsonable import to_jsonable

    props = to_jsonable(FakeSherbrooke().properties().to_dict())
    cal = READER.select(snapshot(props), [103, 104], [("ecr", (104, 103)), ("ecr", (103, 104))])
    names = {p.name for p in cal.qubits[0].parameters}
    assert {"T1", "T2", "readout_error"} <= names
    ops = {(o.name, o.qubits): o for o in cal.operations}
    assert ops[("ecr", (104, 103))].available
    assert not ops[("ecr", (103, 104))].available
