"""RunService: orchestrates one instrumented run and persists the immutable record."""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from qci import __version__
from qci.core.hashing import hash_json
from qci.core.ids import new_run_id
from qci.core.ports import (
    CompiledCircuit,
    ExecutionOutput,
    ProviderAdapter,
    ResolvedBackend,
    RunRepository,
)
from qci.domain.backend import BackendSnapshot
from qci.domain.circuit import CompileConfig
from qci.domain.execution import ExecutionConfig, ExecutionRecord
from qci.domain.metric import EvidenceKind, Metric
from qci.domain.provenance import Provenance
from qci.domain.run import Run, RunError, RunStage, RunStatus
from qci.provenance.environment import collect_environment
from qci.provenance.git import collect_git

MAX_ERROR_MESSAGE = 2000
_URL_CREDENTIALS = re.compile(r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*://)[^/\s@]+@")
_CRN = re.compile(r"crn:[^\s\"',;)}\]]*", re.IGNORECASE)
_BEARER = re.compile(r"\b(bearer)\s+[^\s\"',;]+", re.IGNORECASE)
_JWT = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*")

METRICS_METHOD_VERSION = "1"


def sanitize_error_message(message: str) -> str:
    """Strip URL credentials, CRNs, bearer tokens and JWTs, then truncate.

    Error text may be shown and stored long-term.
    """
    cleaned = _URL_CREDENTIALS.sub(r"\g<scheme>", message)
    cleaned = _JWT.sub("[redacted jwt]", cleaned)
    cleaned = _BEARER.sub(r"\1 [redacted]", cleaned)
    cleaned = _CRN.sub("[redacted crn]", cleaned)
    if len(cleaned) > MAX_ERROR_MESSAGE:
        cleaned = cleaned[:MAX_ERROR_MESSAGE] + "... [truncated]"
    return cleaned


@dataclass(frozen=True)
class RunRequest:
    workload_path: Path
    backend_name: str
    compile_config: CompileConfig
    execution_config: ExecutionConfig
    entrypoint: str = "build"
    tags: dict[str, str] = field(default_factory=dict)


@dataclass
class _Captured:
    """Mutable scratch space while a run is in progress; frozen into a Run at the end."""

    resolved: ResolvedBackend | None = None
    snapshot: BackendSnapshot | None = None
    compiled: CompiledCircuit | None = None
    execution: ExecutionRecord | None = None
    output: ExecutionOutput | None = None
    metrics: list[Metric] = field(default_factory=list)


def compute_metrics(captured: _Captured, logical_depth: int) -> list[Metric]:
    """Label the values QCI reports. M0 emits only measured and calculated values."""
    metrics: list[Metric] = []
    if captured.output is not None:
        metrics.append(
            Metric(
                name="total_shots",
                value=captured.output.result.total_shots,
                unit="shots",
                kind=EvidenceKind.MEASURED,
                method="sum of counts in first classical register",
                method_version=METRICS_METHOD_VERSION,
            )
        )
    metrics.append(
        Metric(
            name="logical_depth",
            value=logical_depth,
            unit="layers",
            kind=EvidenceKind.CALCULATED,
            method="circuit depth of logical circuit",
            method_version=METRICS_METHOD_VERSION,
        )
    )
    if captured.compiled is not None:
        out = captured.compiled.record.output
        for name, value, unit in (
            ("transpiled_depth", out.depth, "layers"),
            ("transpiled_size", out.size, "instructions"),
            ("transpiled_two_qubit_gates", out.two_qubit_gate_count, "gates"),
        ):
            metrics.append(
                Metric(
                    name=name,
                    value=value,
                    unit=unit,
                    kind=EvidenceKind.CALCULATED,
                    method=f"{name} from transpiled circuit summary",
                    method_version=METRICS_METHOD_VERSION,
                )
            )
    return metrics


class RunService:
    def __init__(self, adapter: ProviderAdapter, repository: RunRepository) -> None:
        self._adapter = adapter
        self._repository = repository

    def run(self, request: RunRequest) -> Run:
        """Execute and persist one run.

        Workload load failures raise ``WorkloadLoadError`` and persist nothing (there is no
        workload to record). Any later failure is persisted as a failed run and returned.
        """
        workload = self._adapter.loader.load(request.workload_path, request.entrypoint)
        run_id = new_run_id()
        created_at = datetime.now(UTC)
        provenance = Provenance(
            git=collect_git(request.workload_path.resolve().parent),
            environment=collect_environment(self._adapter.relevant_packages),
        )

        captured = _Captured()
        error: RunError | None = None
        stage = RunStage.RESOLVE_BACKEND
        try:
            captured.resolved = self._adapter.catalog.resolve(request.backend_name)
            stage = RunStage.SNAPSHOT
            captured.snapshot = self._adapter.catalog.snapshot(captured.resolved)
            stage = RunStage.COMPILE
            captured.compiled = self._adapter.compiler.compile(
                workload, captured.resolved, request.compile_config
            )
            stage = RunStage.EXECUTE
            started_at = datetime.now(UTC)
            captured.output = self._adapter.executor.execute(
                captured.compiled, captured.resolved, request.execution_config
            )
            finished_at = datetime.now(UTC)
            captured.execution = ExecutionRecord(
                config=request.execution_config,
                config_hash=hash_json(request.execution_config),
                primitive=captured.output.primitive,
                started_at=started_at,
                finished_at=finished_at,
                provider_job_id=captured.output.provider_job_id,
            )
            stage = RunStage.METRICS
            captured.metrics = compute_metrics(captured, workload.logical.depth)
        except Exception as exc:
            error = RunError(
                stage=stage,
                error_type=f"{type(exc).__module__}.{type(exc).__qualname__}",
                message=sanitize_error_message(str(exc)),
            )

        fields: dict[str, Any] = {
            "run_id": run_id,
            "qci_version": __version__,
            "created_at": created_at,
            "status": RunStatus.FAILED if error else RunStatus.SUCCEEDED,
            "error": error,
            "tags": dict(request.tags),
            "workload": workload.source,
            "provenance": provenance,
            "logical_circuit": workload.logical,
            "backend": captured.resolved.backend if captured.resolved else None,
            "backend_snapshot": captured.snapshot,
            "compilation": captured.compiled.record if captured.compiled else None,
            "execution": captured.execution,
            "result": captured.output.result if captured.output else None,
            "metrics": captured.metrics,
        }
        run = Run.model_validate(fields)
        self._repository.save(run)
        return run
