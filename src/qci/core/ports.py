"""Ports: the provider-neutral interfaces the services depend on.

Native SDK objects (circuits, backends) cross these interfaces only as opaque ``native``
handles. A handle must only be passed back to ports of the adapter that produced it.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from pydantic import JsonValue

from qci.domain.backend import Backend, BackendSnapshot, SnapshotSource
from qci.domain.circuit import CircuitSummary, CompilationRecord, CompileConfig
from qci.domain.comparison import FootprintCalibration
from qci.domain.execution import ExecutionConfig, ExecutionResult
from qci.domain.provenance import WorkloadSource
from qci.domain.run import Run, RunListItem
from qci.domain.snapshot import (
    CalibrationSnapshot,
    Measurement,
    SnapshotCapture,
    SnapshotListItem,
)


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


class CalibrationReader(Protocol):
    """Selects provider calibration for specific physical resources from a stored snapshot.

    Implementations interpret one provider's raw payload format. Missing data must be returned
    as unavailable (value None), never as zero.
    """

    def select(
        self,
        snapshot: BackendSnapshot,
        qubits: Sequence[int],
        operations: Sequence[tuple[str, tuple[int, ...]]],
    ) -> FootprintCalibration: ...


@dataclass(frozen=True)
class CapturedCalibration:
    """What a calibration source read, already redacted, with datetimes normalized to UTC."""

    provider: str
    backend_name: str
    backend_version: str | None
    source: SnapshotSource
    captured_at: datetime
    calibrated_at: datetime | None
    capture_options: dict[str, JsonValue]
    provider_raw: dict[str, JsonValue]
    redactions: list[str]
    measurements: list[Measurement]
    extraction_method: str
    extraction_method_version: str
    environment: dict[str, str]


class CalibrationSource(Protocol):
    def capture(self, backend_name: str) -> CapturedCalibration:
        """Read published calibration once. Raises ``CaptureRejectedError`` for a fake or a
        simulator. Never retries or polls."""
        ...


class SnapshotRepository(Protocol):
    """Insert-only snapshot persistence. There is deliberately no update or delete."""

    def save(
        self,
        snapshot: CalibrationSnapshot,
        measurements: Sequence[Measurement],
        capture: SnapshotCapture,
    ) -> tuple[CalibrationSnapshot, bool]:
        """Record a capture. If a snapshot with the same content hash exists, only the capture
        row is inserted, pointing at it. Returns the stored snapshot and whether it is new."""
        ...

    def get(self, snapshot_id: str) -> CalibrationSnapshot:
        """Raises ``SnapshotNotFoundError`` if absent."""
        ...

    def get_by_hash(self, content_hash: str) -> CalibrationSnapshot | None: ...

    def list_snapshots(
        self, backend_name: str | None = None, limit: int | None = None
    ) -> list[SnapshotListItem]:
        """Newest first capture first."""
        ...

    def measurements(self, snapshot_id: str) -> list[Measurement]:
        """In extraction order."""
        ...

    def captures(self, snapshot_id: str) -> list[SnapshotCapture]:
        """Oldest first."""
        ...
