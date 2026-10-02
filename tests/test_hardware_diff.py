"""Footprint-scoped hardware comparison rules."""

from conftest import ibm_properties, physical_bell_qasm, physical_run
from qci.adapters.qiskit_ibm.calibration import IbmPropertiesCalibrationReader
from qci.compare.footprint import footprint_for_run
from qci.compare.hardware import compare_footprints, compare_hardware
from qci.domain.comparison import ComparisonStatus, HardwareComparison
from qci.domain.run import Run

READERS = {"qiskit_ibm": IbmPropertiesCalibrationReader()}


def hardware(baseline: Run, candidate: Run) -> HardwareComparison:
    return compare_hardware(
        baseline, candidate, footprint_for_run(baseline), footprint_for_run(candidate), READERS.get
    )


def test_identical_snapshots_are_unchanged() -> None:
    a = physical_run("A", qasm3=physical_bell_qasm(1, 0))
    b = physical_run("B", qasm3=physical_bell_qasm(1, 0))
    hw = hardware(a, b)
    assert hw.status is ComparisonStatus.UNCHANGED
    assert hw.global_snapshot_changed is False and hw.relevant_hardware_changed is False


def test_unused_qubit_calibration_change_is_global_but_not_relevant() -> None:
    a = physical_run("A", qasm3=physical_bell_qasm(1, 0))
    b = physical_run("B", qasm3=physical_bell_qasm(1, 0), properties=ibm_properties(t1={3: 5.0}))
    hw = hardware(a, b)
    assert hw.global_snapshot_changed is True
    assert hw.relevant_hardware_changed is False
    assert hw.status is ComparisonStatus.UNCHANGED
    assert all(p.qubits != (3,) for p in hw.shared_resource_parameters)


def test_used_qubit_or_gate_change_is_relevant_with_candidate_minus_baseline_delta() -> None:
    a = physical_run("A", qasm3=physical_bell_qasm(1, 0))
    b = physical_run("B", qasm3=physical_bell_qasm(1, 0), properties=ibm_properties(t1={1: 80.0}))
    hw = hardware(a, b)
    assert hw.relevant_hardware_changed is True and hw.status is ComparisonStatus.CHANGED
    (change,) = [p for p in hw.shared_resource_parameters if p.status == "changed"]
    assert (change.qubits, change.parameter, change.delta) == ((1,), "T1", -20.0)

    c = physical_run(
        "C", qasm3=physical_bell_qasm(1, 0), properties=ibm_properties(ecr_error=0.009)
    )
    hw = hardware(a, c)
    assert hw.relevant_hardware_changed is True
    changed = [p for p in hw.shared_resource_parameters if p.status == "changed"]
    assert [(p.operation, p.qubits) for p in changed] == [("ecr", (1, 0))]


def test_date_only_change_is_reported_separately() -> None:
    props = ibm_properties()
    props["qubits"][1][0]["date"] = {"$datetime": "2025-03-01T00:00:00+00:00"}
    a = physical_run("A", qasm3=physical_bell_qasm(1, 0))
    b = physical_run("B", qasm3=physical_bell_qasm(1, 0), properties=props)
    hw = hardware(a, b)
    assert hw.relevant_hardware_changed is False
    assert any("qubit 1 T1" in d for d in hw.calibration_date_changes)


def test_changed_mapping_compares_only_identical_shared_resources() -> None:
    # Baseline uses qubits {1, 0}; candidate uses {2, 1}. Only qubit 1 is shared.
    a = physical_run("A", qasm3=physical_bell_qasm(1, 0), layout=([1, 0], [1, 0]))
    b = physical_run(
        "B",
        qasm3=physical_bell_qasm(2, 1),
        layout=([2, 1], [2, 1]),
        properties=ibm_properties(t1={0: 10.0, 1: 90.0, 2: 20.0}),
    )
    fp = compare_footprints(footprint_for_run(a), footprint_for_run(b))
    assert fp.resources_identical is False and fp.status is ComparisonStatus.CHANGED
    assert fp.qubits is not None
    assert (fp.qubits.common, fp.qubits.baseline_only, fp.qubits.candidate_only) == ([1], [0], [2])
    assert fp.initial_layout is not None and fp.initial_layout.status == "changed"

    hw = hardware(a, b)
    assert hw.relevant_hardware_changed is None
    assert hw.status is ComparisonStatus.PARTIALLY_COMPARABLE
    # Shared: qubit 1 and measure(1). measure has no own parameters (readout is per qubit).
    assert {
        (p.resource_kind.value, p.operation, p.qubits) for p in hw.shared_resource_parameters
    } == {("qubit", None, (1,))}
    # Qubit 1 is genuinely the same physical resource: its T1 change is valid evidence.
    t1 = [p for p in hw.shared_resource_parameters if p.parameter == "T1"]
    assert [(p.qubits, p.baseline, p.candidate) for p in t1] == [((1,), 100.0, 90.0)]
    # Never T1(q0) -> T1(q2): neither qubit 0 nor 2 appears in any comparison.
    assert all(0 not in p.qubits and 2 not in p.qubits for p in hw.shared_resource_parameters)


def test_missing_relevant_parameter_makes_relevance_undetermined_not_zero() -> None:
    props = ibm_properties()
    props["qubits"][0][0]["value"] = None
    a = physical_run("A", qasm3=physical_bell_qasm(1, 0))
    b = physical_run("B", qasm3=physical_bell_qasm(1, 0), properties=props)
    hw = hardware(a, b)
    assert hw.relevant_hardware_changed is None
    assert hw.status is ComparisonStatus.PARTIALLY_COMPARABLE
    (missing,) = [p for p in hw.shared_resource_parameters if p.status == "unavailable"]
    assert missing.candidate is None and missing.delta is None


def test_missing_snapshot_dynamic_footprint_and_unknown_provider() -> None:
    a = physical_run("A", qasm3=physical_bell_qasm(1, 0))
    no_snapshot = a.model_copy(update={"backend_snapshot": None})
    assert hardware(a, no_snapshot).global_snapshot_changed is None
    assert hardware(a, no_snapshot).status is ComparisonStatus.UNAVAILABLE

    dynamic = physical_run(
        "D", qasm3="OPENQASM 3.0;\nbit[1] c;\nc[0] = measure $0;\nif (c[0]) {\n  x $1;\n}\n"
    )
    hw = hardware(a, dynamic)
    assert hw.status is ComparisonStatus.NOT_COMPARABLE and hw.relevant_hardware_changed is None

    other = physical_run("O", qasm3=physical_bell_qasm(1, 0), provider="other")
    assert hardware(a, other).status is ComparisonStatus.NOT_COMPARABLE
    unknown = physical_run("U1", qasm3=physical_bell_qasm(1, 0), provider="unknown")
    unknown2 = physical_run("U2", qasm3=physical_bell_qasm(1, 0), provider="unknown")
    assert hardware(unknown, unknown2).status is ComparisonStatus.UNAVAILABLE
