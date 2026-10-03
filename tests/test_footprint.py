"""Footprint extraction from OpenQASM 3 text. No Qiskit."""

from conftest import GATE_DEFS, physical_bell_qasm
from qci.compare.footprint import extract_footprint
from qci.domain.circuit import Layout
from qci.domain.comparison import FootprintStatus, PhysicalFootprint

HEADER = 'OPENQASM 3.0;\ninclude "stdgates.inc";\n'


def ops(fp: PhysicalFootprint) -> list[tuple[str, tuple[int, ...], int]]:
    return [(o.name, o.qubits, o.count) for o in fp.operations]


def test_bell_footprint_preserves_ordered_qargs_and_does_not_inline_gate_definitions() -> None:
    fp = extract_footprint(
        physical_bell_qasm(104, 103), Layout(initial=[104, 103], final=[104, 103])
    )
    assert fp.status is FootprintStatus.AVAILABLE
    assert fp.qubits == [103, 104]
    assert fp.measured_qubits == [103, 104]
    assert ("ecr", (104, 103), 1) in ops(fp)
    assert all(name not in {"s", "cx"} for name, _, _ in ops(fp))  # definition body not inlined
    assert fp.initial_layout == [104, 103] and fp.final_layout == [104, 103]


def test_barrier_excluded_measure_reset_delay_make_qubits_relevant() -> None:
    text = HEADER + (
        "bit[1] c;\nx $1;\nbarrier $1, $5, $6;\nreset $2;\ndelay[160dt] $3;\n"
        "c[0] = measure $4;\nx $1;\n"
    )
    fp = extract_footprint(text, None)
    assert fp.status is FootprintStatus.AVAILABLE
    assert fp.qubits == [1, 2, 3, 4]  # barrier-only qubits 5 and 6 are not relevant
    assert fp.measured_qubits == [4]
    assert ops(fp) == [
        ("delay", (3,), 1),
        ("measure", (4,), 1),
        ("reset", (2,), 1),
        ("x", (1,), 2),
    ]
    assert fp.initial_layout is None and fp.final_layout is None


def test_direction_matters() -> None:
    a = extract_footprint(HEADER + GATE_DEFS + "ecr $1, $0;\n", None)
    b = extract_footprint(HEADER + GATE_DEFS + "ecr $0, $1;\n", None)
    assert ops(a) == [("ecr", (1, 0), 1)] and ops(b) == [("ecr", (0, 1), 1)]


def test_control_flow_is_unsupported_not_flattened() -> None:
    text = HEADER + "bit[1] c;\nc[0] = measure $0;\nif (c[0]) {\n  x $1;\n}\n"
    fp = extract_footprint(text, None)
    assert fp.status is FootprintStatus.UNSUPPORTED_DYNAMIC
    assert "BranchingStatement" in (fp.reason or "")
    assert fp.operations == [] and fp.qubits == []


def test_virtual_qubits_are_unavailable() -> None:
    text = HEADER + "qubit[2] q;\nh q[0];\n"
    fp = extract_footprint(text, None)
    assert fp.status is FootprintStatus.UNAVAILABLE
    assert "non-physical" in (fp.reason or "")


def test_unrecognized_or_modified_statements_fail_closed() -> None:
    for body in ("ctrl @ x $0, $1;\n", "#pragma foo\n", "@ann\nx $0;\n"):
        fp = extract_footprint(HEADER + body, None)
        assert fp.status is FootprintStatus.UNAVAILABLE, body


def test_missing_or_unparseable_qasm_is_unavailable() -> None:
    assert extract_footprint(None, None, missing_reason="export failed").reason == "export failed"
    fp = extract_footprint("this is not qasm", None)
    assert fp.status is FootprintStatus.UNAVAILABLE
    assert fp.reason and fp.reason.startswith("OpenQASM 3 parse failed")


def test_dynamic_reason_names_the_policy_not_a_version() -> None:
    text = HEADER + "bit[1] c;\nc[0] = measure $0;\nif (c[0]) {\n  x $1;\n}\n"
    reason = extract_footprint(text, None).reason
    assert reason == "control flow (BranchingStatement) is not supported by this comparison policy"
