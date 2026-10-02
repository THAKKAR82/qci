"""IBM/Qiskit provider adapter (M0: local IBM fake backends only, no network)."""

import importlib.util
import inspect
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import qiskit
from qiskit import QuantumCircuit, transpile
from qiskit.primitives import BackendSamplerV2
from qiskit.providers import BackendV2
from qiskit_ibm_runtime import fake_provider
from qiskit_ibm_runtime.fake_provider.fake_backend import FakeBackendV2

from qci.adapters.qiskit_ibm.adapter_ids import PROVIDER_ID
from qci.adapters.qiskit_ibm.jsonable import to_jsonable
from qci.adapters.qiskit_ibm.summarize import summarize_circuit
from qci.core.errors import UnknownBackendError, WorkloadLoadError
from qci.core.hashing import hash_json, sha256_hex
from qci.core.ports import (
    CompiledCircuit,
    ExecutionOutput,
    LoadedWorkload,
    ResolvedBackend,
)
from qci.domain.backend import Backend, BackendSnapshot, SnapshotSource
from qci.domain.circuit import CompilationRecord, CompileConfig, CompilerInfo, Layout
from qci.domain.execution import ExecutionConfig, ExecutionResult
from qci.domain.provenance import WorkloadSource

# Qiskit core's backend sampler. The deprecated qiskit_ibm_runtime.SamplerV2 "local testing
# mode" delegates to exactly this class for fake backends; calling it directly avoids the
# deprecation and a bug where seed_simulator=0 is silently dropped. See docs/architecture.md.
PRIMITIVE_NAME = "qiskit.primitives.BackendSamplerV2"


def _native_circuit(handle: object) -> QuantumCircuit:
    if not isinstance(handle, QuantumCircuit):
        raise TypeError(f"expected a Qiskit QuantumCircuit handle, got {type(handle).__name__}")
    return handle


def _native_backend(handle: object) -> BackendV2:
    if not isinstance(handle, BackendV2):
        raise TypeError(f"expected a Qiskit BackendV2 handle, got {type(handle).__name__}")
    return handle


class QiskitWorkloadLoader:
    """Loads a Python file and calls ``entrypoint()``, which must return a QuantumCircuit."""

    def load(self, path: Path, entrypoint: str) -> LoadedWorkload:
        path = path.resolve()
        try:
            source = path.read_bytes()
        except OSError as exc:
            raise WorkloadLoadError(f"cannot read workload file {path}: {exc}") from exc
        digest = sha256_hex(source)

        module_name = f"qci_workload_{digest[:16]}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise WorkloadLoadError(f"cannot import workload file {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
            build = getattr(module, entrypoint, None)
            if not callable(build):
                raise WorkloadLoadError(f"{path} has no callable {entrypoint!r}")
            circuit = build()
        except WorkloadLoadError:
            raise
        except Exception as exc:
            raise WorkloadLoadError(
                f"workload {path}:{entrypoint} raised {type(exc).__name__}: {exc}"
            ) from exc
        finally:
            sys.modules.pop(module_name, None)

        if not isinstance(circuit, QuantumCircuit):
            raise WorkloadLoadError(
                f"{entrypoint}() must return a qiskit QuantumCircuit, got {type(circuit).__name__}"
            )
        return LoadedWorkload(
            source=WorkloadSource(
                source_path=str(path),
                source_sha256=digest,
                entrypoint=entrypoint,
                name=circuit.name or path.stem,
            ),
            logical=summarize_circuit(circuit),
            native=circuit,
        )


def fake_backend_classes() -> dict[str, type[FakeBackendV2]]:
    """Map fake backend names to classes without instantiating them.

    ``FakeProviderForBackendV2`` instantiates all ~68 fakes on lookup, which is slow and emits
    unrelated warnings from other backends' data; this instantiates only the one requested.
    """
    classes: dict[str, type[FakeBackendV2]] = {}
    for obj in vars(fake_provider).values():
        if inspect.isclass(obj) and issubclass(obj, FakeBackendV2) and obj is not FakeBackendV2:
            name = obj.__dict__.get("backend_name")
            if isinstance(name, str):
                classes[name] = obj
    return classes


class QiskitFakeBackendCatalog:
    """Resolves IBM fake backends (local simulators with frozen calibration data)."""

    def resolve(self, name: str) -> ResolvedBackend:
        backend_cls = fake_backend_classes().get(name)
        if backend_cls is None:
            raise UnknownBackendError(
                f"unknown backend {name!r}; M0 supports IBM fake backends such as 'fake_sherbrooke'"
            )
        native = backend_cls()
        backend = Backend(
            provider=PROVIDER_ID,
            name=native.name,
            version=str(native.backend_version) if native.backend_version else None,
            num_qubits=native.num_qubits,
            # Fake backends execute locally on a simulator, whatever hardware they mimic.
            is_simulator=True,
        )
        return ResolvedBackend(backend=backend, native=native)

    def snapshot(self, backend: ResolvedBackend) -> BackendSnapshot:
        native = _native_backend(backend.native)
        captured_at = datetime.now(UTC)
        properties = native.properties() if hasattr(native, "properties") else None
        configuration = native.configuration() if hasattr(native, "configuration") else None

        calibrated_at = None
        if properties is not None and properties.last_update_date is not None:
            calibrated_at = properties.last_update_date.astimezone(UTC)

        basis_gates: list[str]
        if configuration is not None and getattr(configuration, "basis_gates", None):
            basis_gates = list(configuration.basis_gates)
        else:
            basis_gates = sorted(native.target.operation_names)

        coupling = native.coupling_map
        edges = sorted((int(a), int(b)) for a, b in coupling.get_edges()) if coupling else []

        if isinstance(native, FakeBackendV2):
            source = SnapshotSource.STATIC_FAKE
        else:  # not reachable in M0; recorded honestly if another simulator is added
            source = SnapshotSource.SIMULATOR_IDEAL

        return BackendSnapshot(
            source=source,
            captured_at=captured_at,
            calibrated_at=calibrated_at,
            basis_gates=basis_gates,
            coupling_edges=edges,
            provider_raw={
                "properties": to_jsonable(properties.to_dict()) if properties else None,
                "configuration": to_jsonable(configuration.to_dict()) if configuration else None,
            },
        )


class QiskitTranspiler:
    def compile(
        self, workload: LoadedWorkload, backend: ResolvedBackend, config: CompileConfig
    ) -> CompiledCircuit:
        circuit = _native_circuit(workload.native)
        native_backend = _native_backend(backend.native)
        start = time.perf_counter()
        compiled = transpile(
            circuit,
            backend=native_backend,
            optimization_level=config.optimization_level,
            seed_transpiler=config.seed_transpiler,
        )
        duration_ms = (time.perf_counter() - start) * 1000

        layout = None
        if compiled.layout is not None:
            layout = Layout(
                initial=[
                    int(q) for q in compiled.layout.initial_index_layout(filter_ancillas=True)
                ],
                final=[int(q) for q in compiled.layout.final_index_layout()],
            )
        record = CompilationRecord(
            compiler=CompilerInfo(name="qiskit.transpile", version=qiskit.__version__),
            config=config,
            config_hash=hash_json(config),
            output=summarize_circuit(compiled),
            layout=layout,
            duration_ms=duration_ms,
        )
        return CompiledCircuit(record=record, native=compiled)


class QiskitSamplerExecutor:
    def execute(
        self, compiled: CompiledCircuit, backend: ResolvedBackend, config: ExecutionConfig
    ) -> ExecutionOutput:
        circuit = _native_circuit(compiled.native)
        options: dict[str, object] = {"default_shots": config.shots}
        if config.seed_simulator is not None:
            options["seed_simulator"] = config.seed_simulator
        sampler = BackendSamplerV2(backend=_native_backend(backend.native), options=options)
        job = sampler.run([circuit])
        primitive_result = job.result()
        pub_result = primitive_result[0]

        counts: dict[str, dict[str, int]] = {}
        for register, bit_array in pub_result.data.items():
            counts[register] = {bits: int(n) for bits, n in sorted(bit_array.get_counts().items())}
        total_shots = sum(next(iter(counts.values())).values()) if counts else 0

        return ExecutionOutput(
            result=ExecutionResult(
                counts=counts,
                total_shots=total_shots,
                provider_metadata={
                    "primitive_result": to_jsonable(dict(primitive_result.metadata)),
                    "pub_result": to_jsonable(dict(pub_result.metadata)),
                },
            ),
            primitive=PRIMITIVE_NAME,
            provider_job_id=str(job.job_id()),
        )


class QiskitIbmAdapter:
    """Bundles the Qiskit/IBM implementations of every port."""

    provider_id = PROVIDER_ID
    relevant_packages = ("qiskit", "qiskit-ibm-runtime", "qiskit-aer")

    def __init__(self) -> None:
        self.loader = QiskitWorkloadLoader()
        self.catalog = QiskitFakeBackendCatalog()
        self.compiler = QiskitTranspiler()
        self.executor = QiskitSamplerExecutor()
