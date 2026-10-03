"""Routing-sensitive workload: a 5-qubit GHZ state built with star connectivity.

Every CX shares logical qubit 0, so qubit 0 must interact with four others. FakeSherbrooke's
heavy-hex coupling map gives no qubit more than three neighbours, so the transpiler must insert
routing (SWAPs, executed as native ECR sequences). The chosen physical layout and routing
depend on the transpiler seed and optimization level, which makes this workload useful for
observing compilation-induced physical changes. The ideal output is 00000 or 11111.
"""

from qiskit import QuantumCircuit


def build() -> QuantumCircuit:
    qc = QuantumCircuit(5, 5, name="ghz_star_5")
    qc.h(0)
    for target in range(1, 5):
        qc.cx(0, target)
    qc.measure(range(5), range(5))
    return qc
