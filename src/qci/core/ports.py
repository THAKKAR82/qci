"""Ports: the provider-neutral interfaces the services depend on.

Native SDK objects (circuits, backends) cross these interfaces only as opaque ``native``
handles. A handle must only be passed back to ports of the adapter that produced it.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from qci.domain.backend import Backend, BackendSnapshot
from qci.domain.circuit import CircuitSummary, CompilationRecord, CompileConfig
from qci.domain.execution import ExecutionConfig, ExecutionResult
from qci.domain.provenance import WorkloadSource
from qci.domain.run import Run, RunListItem


@dataclass(frozen=True)
class LoadedWorkload:
    source: WorkloadSource
    logical: CircuitSummary
    native: object


@dataclass(frozen=True)
class ResolvedBackend:
    backend: Backend
    native: object


@dataclass(frozen=True)
class CompiledCircuit:
    record: CompilationRecord
    native: object


@dataclass(frozen=True)
class ExecutionOutput:
    result: ExecutionResult
    primitive: str
    provider_job_id: str | None


class WorkloadLoader(Protocol):
    def load(self, path: Path, entrypoint: str) -> LoadedWorkload:
        """Load a workload. Raises ``WorkloadLoadError`` on failure."""
        ...


class BackendCatalog(Protocol):
    def resolve(self, name: str) -> ResolvedBackend:
        """Resolve a backend by name. Raises ``UnknownBackendError`` if unavailable."""
        ...

    def snapshot(self, backend: ResolvedBackend) -> BackendSnapshot:
        """Capture what is currently known about the backend, keeping raw payloads."""
        ...


class Compiler(Protocol):
    def compile(
        self, workload: LoadedWorkload, backend: ResolvedBackend, config: CompileConfig
    ) -> CompiledCircuit: ...


class Executor(Protocol):
    def execute(
        self, compiled: CompiledCircuit, backend: ResolvedBackend, config: ExecutionConfig
    ) -> ExecutionOutput: ...


class ProviderAdapter(Protocol):
    """All ports for one provider."""

    @property
    def provider_id(self) -> str: ...

    @property
    def relevant_packages(self) -> tuple[str, ...]:
        """Distribution names whose versions belong in environment provenance."""
        ...

    @property
    def loader(self) -> WorkloadLoader: ...

    @property
    def catalog(self) -> BackendCatalog: ...

    @property
    def compiler(self) -> Compiler: ...

    @property
    def executor(self) -> Executor: ...


class RunRepository(Protocol):
    """Insert-only run persistence. There is deliberately no update or delete."""

    def save(self, run: Run) -> None:
        """Insert a run. Raises ``DuplicateRunError`` if the ID exists."""
        ...

    def get(self, run_id: str) -> Run:
        """Return a run. Raises ``RunNotFoundError`` if absent."""
        ...

    def list_runs(self, limit: int | None = None) -> list[RunListItem]:
        """Newest first."""
        ...
