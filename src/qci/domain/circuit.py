"""Circuit summaries and compilation records.

Circuit identity is provisional (see docs/data-model.md). These models preserve the inputs a
future identity scheme may need, without defining one.
"""

from pydantic import NonNegativeFloat, NonNegativeInt

from qci.domain.base import DomainModel


class Exporter(DomainModel):
    """The software that produced a textual circuit representation."""

    name: str
    version: str


class CircuitSummary(DomainModel):
    """Structural summary of one circuit (logical or transpiled)."""

    num_qubits: NonNegativeInt
    num_clbits: NonNegativeInt
    depth: NonNegativeInt
    size: NonNegativeInt
    """Total number of instructions."""
    op_counts: dict[str, NonNegativeInt]
    two_qubit_gate_count: NonNegativeInt
    two_qubit_edges: list[tuple[int, int]]
    """Sorted, de-duplicated, undirected qubit pairs that share a two-qubit gate."""
    qasm3: str | None
    qasm3_error: str | None = None
    """Why OpenQASM 3 export failed, when it did."""
    exporter: Exporter


class CompileConfig(DomainModel):
    """Requested compilation settings."""

    optimization_level: int
    seed_transpiler: int | None = None


class CompilerInfo(DomainModel):
    name: str
    version: str


class Layout(DomainModel):
    """Qubit layout reported by the compiler. Indices are physical qubits."""

    initial: list[int] | None = None
    """Physical qubit assigned to each virtual (logical) qubit before routing."""
    final: list[int] | None = None
    """Physical qubit holding each virtual qubit at the end of the circuit."""


class CompilationRecord(DomainModel):
    compiler: CompilerInfo
    config: CompileConfig
    config_hash: str
    output: CircuitSummary
    layout: Layout | None = None
    duration_ms: NonNegativeFloat
