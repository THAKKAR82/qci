"""The Run: an immutable record of one attempted execution."""

from enum import StrEnum
from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from qci.domain.backend import Backend, BackendSnapshot
from qci.domain.base import DomainModel
from qci.domain.circuit import CircuitSummary, CompilationRecord
from qci.domain.execution import ExecutionRecord, ExecutionResult
from qci.domain.metric import Metric
from qci.domain.provenance import Provenance, WorkloadSource

SCHEMA_VERSION: Literal[1] = 1


class RunStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class RunStage(StrEnum):
    """Pipeline stages, in order. A failed run records the stage that raised."""

    RESOLVE_BACKEND = "resolve_backend"
    SNAPSHOT = "snapshot"
    COMPILE = "compile"
    EXECUTE = "execute"
    METRICS = "metrics"


class RunError(DomainModel):
    stage: RunStage
    error_type: str
    message: str
    """Sanitized and truncated error message."""


class Run(DomainModel):
    run_id: str
    schema_version: Literal[1] = SCHEMA_VERSION
    qci_version: str
    created_at: AwareDatetime
    status: RunStatus
    error: RunError | None = None
    tags: dict[str, str] = Field(default_factory=dict)
    workload: WorkloadSource
    provenance: Provenance
    logical_circuit: CircuitSummary
    backend: Backend | None = None
    backend_snapshot: BackendSnapshot | None = None
    compilation: CompilationRecord | None = None
    execution: ExecutionRecord | None = None
    result: ExecutionResult | None = None
    metrics: list[Metric] = Field(default_factory=list)

    @model_validator(mode="after")
    def _status_matches_error(self) -> Self:
        if self.status is RunStatus.FAILED and self.error is None:
            raise ValueError("a failed run must record an error")
        if self.status is RunStatus.SUCCEEDED:
            if self.error is not None:
                raise ValueError("a succeeded run must not record an error")
            missing = [
                name
                for name in ("backend", "backend_snapshot", "compilation", "execution", "result")
                if getattr(self, name) is None
            ]
            if missing:
                raise ValueError(f"a succeeded run is missing: {', '.join(missing)}")
        return self


class RunListItem(DomainModel):
    """Lightweight row for listing runs without loading full records."""

    run_id: str
    created_at: AwareDatetime
    status: RunStatus
    workload_name: str
    backend_name: str | None
    git_commit: str | None
