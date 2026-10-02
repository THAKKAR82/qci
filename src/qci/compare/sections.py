"""Explicit, semantic comparison of each normalized Run section (baseline -> candidate)."""

from qci.compare.values import (
    compare_counter,
    compare_mapping,
    compare_number,
    compare_set,
    compare_value,
    fields_status,
)
from qci.core.hashing import sha256_hex
from qci.domain.circuit import CircuitSummary
from qci.domain.comparison import (
    BackendComparison,
    CircuitStructureComparison,
    ComparisonStatus,
    CompilationComparison,
    EnvironmentComparison,
    ExecutionComparison,
    FieldStatus,
    LogicalCircuitComparison,
    SourceComparison,
)
from qci.domain.run import Run


def _qasm_sha256(summary: CircuitSummary) -> str | None:
    return sha256_hex(summary.qasm3.encode("utf-8")) if summary.qasm3 is not None else None


def _exporter(summary: CircuitSummary) -> str:
    return f"{summary.exporter.name} {summary.exporter.version}"


def _missing(side_b: object, side_c: object, what: str) -> str | None:
    if side_b is None and side_c is None:
        return f"neither run has {what}"
    if side_b is None:
        return f"baseline run has no {what}"
    if side_c is None:
        return f"candidate run has no {what}"
    return None


def compare_source(baseline: Run, candidate: Run) -> SourceComparison:
    b, c = baseline, candidate
    bg, cg = b.provenance.git, c.provenance.git
    fields = {
        "source_sha256": compare_value(b.workload.source_sha256, c.workload.source_sha256),
        "source_path": compare_value(b.workload.source_path, c.workload.source_path),
        "entrypoint": compare_value(b.workload.entrypoint, c.workload.entrypoint),
        "workload_name": compare_value(b.workload.name, c.workload.name),
        "git_commit": compare_value(bg.commit, cg.commit),
        "git_branch": compare_value(bg.branch, cg.branch),
        "git_dirty": compare_value(bg.dirty, cg.dirty),
        "git_remote": compare_value(bg.remote, cg.remote),
    }
    return SourceComparison(status=fields_status(f.status for f in fields.values()), **fields)


def compare_environment(baseline: Run, candidate: Run) -> EnvironmentComparison:
    be, ce = baseline.provenance.environment, candidate.provenance.environment
    python_version = compare_value(be.python_version, ce.python_version)
    implementation = compare_value(be.python_implementation, ce.python_implementation)
    platform = compare_value(be.platform, ce.platform)
    packages = compare_mapping(dict(be.packages), dict(ce.packages))
    env_hash = compare_value(be.config_hash, ce.config_hash)
    return EnvironmentComparison(
        status=fields_status(
            [python_version.status, implementation.status, platform.status, packages.status]
        ),
        python_version=python_version,
        python_implementation=implementation,
        platform=platform,
        packages=packages,
        environment_hash=env_hash,
    )


def compare_circuit_structure(b: CircuitSummary, c: CircuitSummary) -> CircuitStructureComparison:
    return CircuitStructureComparison(
        num_qubits=compare_number(b.num_qubits, c.num_qubits),
        num_clbits=compare_number(b.num_clbits, c.num_clbits),
        depth=compare_number(b.depth, c.depth),
        size=compare_number(b.size, c.size),
        two_qubit_gate_count=compare_number(b.two_qubit_gate_count, c.two_qubit_gate_count),
        op_counts=compare_counter(b.op_counts, c.op_counts),
        qasm3_sha256=compare_value(_qasm_sha256(b), _qasm_sha256(c)),
        qasm3_exporter=compare_value(_exporter(b), _exporter(c)),
    )


def _structure_status(s: CircuitStructureComparison) -> list[FieldStatus]:
    return [
        s.num_qubits.status,
        s.num_clbits.status,
        s.depth.status,
        s.size.status,
        s.two_qubit_gate_count.status,
        s.op_counts.status,
        s.qasm3_sha256.status,
        s.qasm3_exporter.status,
    ]


def compare_logical_circuit(baseline: Run, candidate: Run) -> LogicalCircuitComparison:
    b, c = baseline.logical_circuit, candidate.logical_circuit
    structure = compare_circuit_structure(b, c)
    edges = compare_set(b.two_qubit_edges, c.two_qubit_edges)
    statuses = [*_structure_status(structure), edges.status]
    return LogicalCircuitComparison(
        status=fields_status(statuses),
        structure=structure,
        two_qubit_edges=edges,
    )


def compare_compilation(baseline: Run, candidate: Run) -> CompilationComparison:
    b, c = baseline.compilation, candidate.compilation
    if b is None or c is None:
        return CompilationComparison(
            status=ComparisonStatus.UNAVAILABLE, note=_missing(b, c, "compilation record")
        )
    fields = {
        "compiler": compare_value(
            f"{b.compiler.name} {b.compiler.version}", f"{c.compiler.name} {c.compiler.version}"
        ),
        "optimization_level": compare_number(
            b.config.optimization_level, c.config.optimization_level
        ),
        "seed_transpiler": compare_value(b.config.seed_transpiler, c.config.seed_transpiler),
        "initial_layout": compare_value(
            b.layout.initial if b.layout else None, c.layout.initial if c.layout else None
        ),
        "final_layout": compare_value(
            b.layout.final if b.layout else None, c.layout.final if c.layout else None
        ),
    }
    transpiled = compare_circuit_structure(b.output, c.output)
    statuses = [f.status for f in fields.values()] + _structure_status(transpiled)
    return CompilationComparison(
        status=fields_status(statuses),
        transpiled=transpiled,
        **fields,
    )


def compare_execution(baseline: Run, candidate: Run) -> ExecutionComparison:
    b, c = baseline.execution, candidate.execution
    if b is None or c is None:
        return ExecutionComparison(
            status=ComparisonStatus.UNAVAILABLE, note=_missing(b, c, "execution record")
        )
    shots = compare_number(b.config.shots, c.config.shots)
    seed = compare_value(b.config.seed_simulator, c.config.seed_simulator)
    primitive = compare_value(b.primitive, c.primitive)
    return ExecutionComparison(
        status=fields_status([shots.status, seed.status, primitive.status]),
        shots=shots,
        seed_simulator=seed,
        primitive=primitive,
    )


def compare_backend(baseline: Run, candidate: Run) -> BackendComparison:
    b, c = baseline.backend, candidate.backend
    bs, cs = baseline.backend_snapshot, candidate.backend_snapshot
    if b is None or c is None or bs is None or cs is None:
        note = _missing(b, c, "backend") or _missing(bs, cs, "backend snapshot")
        return BackendComparison(status=ComparisonStatus.UNAVAILABLE, note=note)
    fields = {
        "provider": compare_value(b.provider, c.provider),
        "name": compare_value(b.name, c.name),
        "version": compare_value(b.version, c.version),
        "num_qubits": compare_number(b.num_qubits, c.num_qubits),
        "is_simulator": compare_value(b.is_simulator, c.is_simulator),
        "snapshot_source": compare_value(bs.source.value, cs.source.value),
        "calibrated_at": compare_value(
            bs.calibrated_at.isoformat() if bs.calibrated_at else None,
            cs.calibrated_at.isoformat() if cs.calibrated_at else None,
        ),
    }
    basis = compare_set(bs.basis_gates, cs.basis_gates)
    coupling = compare_set(bs.coupling_edges, cs.coupling_edges)
    statuses = [f.status for f in fields.values()] + [basis.status, coupling.status]
    return BackendComparison(
        status=fields_status(statuses),
        basis_gates=basis,
        coupling_edges=coupling,
        **fields,
    )
