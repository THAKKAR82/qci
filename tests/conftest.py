"""Shared, provider-free test fixtures. Nothing here imports Qiskit."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from qci.core.hashing import hash_json
from qci.core.ports import CompiledCircuit, ExecutionOutput, LoadedWorkload, ResolvedBackend
from qci.domain.backend import Backend, BackendSnapshot, SnapshotSource
from qci.domain.circuit import (
    CircuitSummary,
    CompilationRecord,
    CompileConfig,
    CompilerInfo,
    Exporter,
)
from qci.domain.execution import ExecutionConfig, ExecutionRecord, ExecutionResult
from qci.domain.metric import EvidenceKind, Metric
from qci.domain.provenance import EnvironmentProvenance, GitProvenance, Provenance, WorkloadSource
from qci.domain.run import Run, RunStatus
from qci.storage.sqlite import SqliteRunRepository

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

RAW_PROPERTIES: dict[str, Any] = {
    "backend_name": "stub",
    "last_update_date": {"$datetime": "2025-02-26T14:43:10-05:00"},
    "qubits": [[{"name": "T1", "value": 1.5e-4, "unit": "s"}]],
    "gates": [{"gate": "cx", "qubits": [0, 1], "parameters": []}],
    "provider_specific_unknown_field": {"nested": [1, 2.5, None, True]},
}


def circuit_summary(num_qubits: int = 2) -> CircuitSummary:
    return CircuitSummary(
        num_qubits=num_qubits,
        num_clbits=2,
        depth=3,
        size=4,
        op_counts={"cx": 1, "h": 1, "measure": 2},
        two_qubit_gate_count=1,
        two_qubit_edges=[(0, 1)],
        qasm3="OPENQASM 3.0;",
        exporter=Exporter(name="stub", version="0"),
    )


def make_run(run_id: str = "01TESTRUN00000000000000000", **overrides: Any) -> Run:
    compile_config = CompileConfig(optimization_level=1, seed_transpiler=7)
    exec_config = ExecutionConfig(shots=100, seed_simulator=7)
    fields: dict[str, Any] = {
        "run_id": run_id,
        "qci_version": "0.0.1",
        "created_at": T0,
        "status": RunStatus.SUCCEEDED,
        "tags": {"purpose": "test"},
        "workload": WorkloadSource(
            source_path="/tmp/bell.py", source_sha256="ab" * 32, entrypoint="build", name="bell"
        ),
        "provenance": Provenance(
            git=GitProvenance(commit="c0ffee", branch="main", dirty=False, remote=None),
            environment=EnvironmentProvenance(
                python_version="3.13.0",
                python_implementation="CPython",
                platform="test",
                packages={"qci": "0.0.1"},
                config_hash="sha256:" + "0" * 64,
            ),
        ),
        "logical_circuit": circuit_summary(),
        "backend": Backend(
            provider="stub", name="stub_backend", version="1", num_qubits=2, is_simulator=True
        ),
        "backend_snapshot": BackendSnapshot(
            source=SnapshotSource.STATIC_FAKE,
            captured_at=T0,
            calibrated_at=datetime(2025, 2, 26, tzinfo=UTC),
            basis_gates=["cx", "h"],
            coupling_edges=[(0, 1), (1, 0)],
            provider_raw={"properties": RAW_PROPERTIES, "configuration": None},
        ),
        "compilation": CompilationRecord(
            compiler=CompilerInfo(name="stub", version="0"),
            config=compile_config,
            config_hash=hash_json(compile_config),
            output=circuit_summary(),
            duration_ms=1.0,
        ),
        "execution": ExecutionRecord(
            config=exec_config,
            config_hash=hash_json(exec_config),
            primitive="stub.sampler",
            started_at=T0,
            finished_at=T0,
        ),
        "result": ExecutionResult(
            counts={"c": {"00": 52, "11": 48}}, total_shots=100, provider_metadata={}
        ),
        "metrics": [
            Metric(
                name="total_shots",
                value=100,
                kind=EvidenceKind.MEASURED,
                method="m",
                method_version="1",
            )
        ],
    }
    fields.update(overrides)
    return Run.model_validate(fields)


class StubLoader:
    def load(self, path: Path, entrypoint: str) -> LoadedWorkload:
        source = WorkloadSource(
            source_path=str(path), source_sha256="cd" * 32, entrypoint=entrypoint, name="stub"
        )
        return LoadedWorkload(source=source, logical=circuit_summary(), native=object())


class StubCatalog:
    def resolve(self, name: str) -> ResolvedBackend:
        return ResolvedBackend(
            backend=Backend(provider="stub", name=name, num_qubits=2, is_simulator=True),
            native=object(),
        )

    def snapshot(self, backend: ResolvedBackend) -> BackendSnapshot:
        return BackendSnapshot(
            source=SnapshotSource.SIMULATOR_IDEAL,
            captured_at=T0,
            basis_gates=["cx"],
            coupling_edges=[],
            provider_raw={"configuration": {"anything": 1}},
        )


class StubCompiler:
    def compile(
        self, workload: LoadedWorkload, backend: ResolvedBackend, config: CompileConfig
    ) -> CompiledCircuit:
        record = CompilationRecord(
            compiler=CompilerInfo(name="stub", version="0"),
            config=config,
            config_hash=hash_json(config),
            output=circuit_summary(),
            duration_ms=0.0,
        )
        return CompiledCircuit(record=record, native=object())


class StubExecutor:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    def execute(
        self, compiled: CompiledCircuit, backend: ResolvedBackend, config: ExecutionConfig
    ) -> ExecutionOutput:
        if self.error is not None:
            raise self.error
        return ExecutionOutput(
            result=ExecutionResult(
                counts={"c": {"00": config.shots}}, total_shots=config.shots, provider_metadata={}
            ),
            primitive="stub.sampler",
            provider_job_id=None,
        )


class StubAdapter:
    provider_id = "stub"
    relevant_packages: tuple[str, ...] = ()

    def __init__(self, executor_error: Exception | None = None) -> None:
        self.loader = StubLoader()
        self.catalog = StubCatalog()
        self.compiler = StubCompiler()
        self.executor = StubExecutor(executor_error)


@pytest.fixture
def repo(tmp_path: Path) -> Iterator[SqliteRunRepository]:
    repository = SqliteRunRepository(tmp_path / "qci.db")
    yield repository
    repository.close()


# --- physical-footprint fixtures for compare tests (still Qiskit-free) ------------------

GATE_DEFS = """gate ecr _gate_q_0, _gate_q_1 {
  s _gate_q_0;
  sx _gate_q_1;
  cx _gate_q_0, _gate_q_1;
  x _gate_q_0;
}
"""

LOGICAL_BELL_QASM = """OPENQASM 3.0;
include "stdgates.inc";
bit[2] c;
qubit[2] q;
h q[0];
cx q[0], q[1];
c[0] = measure q[0];
c[1] = measure q[1];
"""


def physical_bell_qasm(control: int, target: int) -> str:
    """Transpiled-style Bell circuit on physical qubits, as Qiskit's exporter writes it."""
    return (
        'OPENQASM 3.0;\ninclude "stdgates.inc";\n'
        + GATE_DEFS
        + f"bit[2] c;\nrz(pi/2) ${control};\nsx ${control};\necr ${control}, ${target};\n"
        + f"x ${control};\nc[0] = measure ${control};\nc[1] = measure ${target};\n"
    )


def ibm_properties(
    num_qubits: int = 4, *, t1: dict[int, float] | None = None, ecr_error: float = 0.005
) -> dict[str, Any]:
    """Synthetic IBM BackendProperties payload in M0's stored (tagged JSON) form."""
    date = {"$datetime": "2025-02-26T02:00:00-05:00"}
    t1 = t1 or {}
    qubits = [
        [
            {"name": "T1", "value": t1.get(q, 100.0), "unit": "us", "date": date},
            {"name": "readout_error", "value": 0.01, "unit": "", "date": date},
        ]
        for q in range(num_qubits)
    ]
    gates: list[dict[str, Any]] = []
    for q in range(num_qubits):
        for name in ("rz", "sx", "x"):
            gates.append(
                {
                    "gate": name,
                    "qubits": [q],
                    "parameters": [
                        {"name": "gate_error", "value": 0.0002, "unit": "", "date": date}
                    ],
                }
            )
    for a in range(num_qubits - 1):
        for control, target in ((a + 1, a), (a, a + 1)):
            gates.append(
                {
                    "gate": "ecr",
                    "qubits": [control, target],
                    "parameters": [
                        {"name": "gate_error", "value": ecr_error, "unit": "", "date": date}
                    ],
                }
            )
    general = [{"name": "jq_12", "value": 0.002, "unit": "GHz", "date": date}]
    return {"backend_name": "synthetic", "qubits": qubits, "gates": gates, "general": general}


def physical_run(
    run_id: str,
    *,
    qasm3: str | None,
    layout: tuple[list[int], list[int]] | None = ([1, 0], [1, 0]),
    properties: dict[str, Any] | None = None,
    counts: dict[str, dict[str, int]] | None = None,
    logical_qasm3: str | None = LOGICAL_BELL_QASM,
    provider: str = "qiskit_ibm",
    seed_simulator: int | None = None,
    is_simulator: bool = True,
) -> Run:
    """A run with a physical footprint. Unseeded by default, so the TVD sampling floor applies."""
    from qci.domain.circuit import Layout

    base = make_run(run_id)
    assert base.compilation is not None and base.backend is not None
    assert base.backend_snapshot is not None and base.result is not None
    assert base.execution is not None
    exec_config = base.execution.config.model_copy(update={"seed_simulator": seed_simulator})
    execution = base.execution.model_copy(
        update={"config": exec_config, "config_hash": hash_json(exec_config)}
    )
    output = base.compilation.output.model_copy(update={"qasm3": qasm3})
    compilation = base.compilation.model_copy(
        update={
            "output": output,
            "layout": Layout(initial=layout[0], final=layout[1]) if layout else None,
        }
    )
    snapshot = base.backend_snapshot.model_copy(
        update={
            "provider_raw": {"properties": properties or ibm_properties(), "configuration": None}
        }
    )
    counts = counts or {"c": {"00": 52, "11": 48}}
    result = base.result.model_copy(
        update={"counts": counts, "total_shots": sum(next(iter(counts.values())).values())}
    )
    return make_run(
        run_id,
        compilation=compilation,
        backend_snapshot=snapshot,
        backend=base.backend.model_copy(
            update={"provider": provider, "is_simulator": is_simulator}
        ),
        execution=execution,
        result=result,
        logical_circuit=base.logical_circuit.model_copy(update={"qasm3": logical_qasm3}),
    )
