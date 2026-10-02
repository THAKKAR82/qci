"""Parity: footprint extracted from exported QASM3 == native transpiled circuit (uses Qiskit)."""

from collections import Counter

import pytest
from qiskit import QuantumCircuit, qasm3, transpile
from qiskit_ibm_runtime.fake_provider import FakeSherbrooke

from qci.compare.footprint import extract_footprint
from qci.domain.circuit import Layout
from qci.domain.comparison import FootprintStatus

BACKEND = FakeSherbrooke()


def native_footprint(circuit: QuantumCircuit) -> Counter[tuple[str, tuple[int, ...]]]:
    ops: Counter[tuple[str, tuple[int, ...]]] = Counter()
    for instruction in circuit.data:
        if instruction.operation.name == "barrier":
            continue
        qargs = tuple(circuit.find_bit(q).index for q in instruction.qubits)
        ops[(instruction.operation.name, qargs)] += 1
    return ops


def bell() -> QuantumCircuit:
    qc = QuantumCircuit(2, 2)
    qc.h(0)
    qc.cx(0, 1)
    qc.measure([0, 1], [0, 1])
    return qc


def routed_ghz(delay: bool = False) -> QuantumCircuit:
    qc = QuantumCircuit(5, 5)
    qc.h(0)
    for i in range(1, 5):
        qc.cx(0, i)  # star connectivity forces routing on heavy-hex
    qc.barrier()
    if delay:
        qc.delay(160, 1, unit="dt")
    qc.reset(2)
    qc.measure(range(5), range(5))
    return qc


CASES = [
    ("bell-l1", bell, {"optimization_level": 1}),
    ("ghz-l0", routed_ghz, {"optimization_level": 0}),
    ("ghz-l1", routed_ghz, {"optimization_level": 1}),
    ("ghz-l3", routed_ghz, {"optimization_level": 3}),
    (
        "ghz-delay-alap",
        lambda: routed_ghz(delay=True),
        {"optimization_level": 1, "scheduling_method": "alap"},
    ),
]


@pytest.mark.parametrize(("label", "build", "options"), CASES, ids=[c[0] for c in CASES])
def test_extracted_footprint_matches_native_transpiled_circuit(
    label: str, build: object, options: dict[str, object]
) -> None:
    compiled = transpile(build(), backend=BACKEND, seed_transpiler=7, **options)  # type: ignore[operator]
    layout = Layout(
        initial=list(compiled.layout.initial_index_layout(filter_ancillas=True)),
        final=list(compiled.layout.final_index_layout()),
    )
    fp = extract_footprint(qasm3.dumps(compiled), layout)
    assert fp.status is FootprintStatus.AVAILABLE, fp.reason
    extracted = Counter({(op.name, op.qubits): op.count for op in fp.operations})
    assert extracted == native_footprint(compiled)
    assert fp.qubits == sorted({q for (_, qargs) in extracted for q in qargs})
    assert fp.initial_layout == layout.initial and fp.final_layout == layout.final


def test_routing_makes_initial_and_final_layout_distinct() -> None:
    compiled = transpile(routed_ghz(), backend=BACKEND, seed_transpiler=7, optimization_level=0)
    assert compiled.layout.initial_index_layout(filter_ancillas=True) != (
        compiled.layout.final_index_layout()
    )


def test_control_flow_circuit_is_reported_unsupported() -> None:
    qc = QuantumCircuit(2, 2)
    qc.h(0)
    qc.measure(0, 0)
    with qc.if_test((qc.clbits[0], 1)):
        qc.x(1)
    qc.measure(1, 1)
    compiled = transpile(qc, backend=BACKEND, seed_transpiler=7, optimization_level=1)
    fp = extract_footprint(qasm3.dumps(compiled), None)
    assert fp.status is FootprintStatus.UNSUPPORTED_DYNAMIC
