"""Convert Qiskit circuits into provider-neutral ``CircuitSummary`` records."""

import qiskit
from qiskit import QuantumCircuit, qasm3

from qci.domain.circuit import CircuitSummary, Exporter

QASM3_EXPORTER = Exporter(name="qiskit.qasm3", version=qiskit.__version__)


def summarize_circuit(circuit: QuantumCircuit) -> CircuitSummary:
    """Summarize top-level instructions. Control-flow bodies are not descended into (M0)."""
    two_qubit_count = 0
    edges: set[tuple[int, int]] = set()
    for instruction in circuit.data:
        operation = instruction.operation
        if getattr(operation, "_directive", False) or len(instruction.qubits) != 2:
            continue
        if operation.name in {"measure", "reset", "delay"}:
            continue
        a, b = (circuit.find_bit(q).index for q in instruction.qubits)
        two_qubit_count += 1
        edges.add((min(a, b), max(a, b)))

    qasm_text: str | None
    qasm_error: str | None = None
    try:
        qasm_text = qasm3.dumps(circuit)
    except Exception as exc:  # export failure is recorded, not fatal
        qasm_text = None
        qasm_error = f"{type(exc).__name__}: {exc}"

    return CircuitSummary(
        num_qubits=circuit.num_qubits,
        num_clbits=circuit.num_clbits,
        depth=circuit.depth(),
        size=circuit.size(),
        op_counts={name: int(n) for name, n in sorted(circuit.count_ops().items())},
        two_qubit_gate_count=two_qubit_count,
        two_qubit_edges=sorted(edges),
        qasm3=qasm_text,
        qasm3_error=qasm_error,
        exporter=QASM3_EXPORTER,
    )
