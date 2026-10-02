"""QCI command-line interface (M0: run, runs, show)."""

import os
from pathlib import Path
from typing import Annotated

import typer

from qci.core.errors import QCIError, RunNotFoundError, WorkloadLoadError
from qci.domain.circuit import CircuitSummary, CompileConfig
from qci.domain.execution import ExecutionConfig
from qci.domain.run import Run, RunStatus
from qci.services.run_service import RunRequest, RunService
from qci.storage.sqlite import SqliteRunRepository

app = typer.Typer(
    help="QCI: instrumented, immutable records of quantum workload runs.",
    no_args_is_help=True,
    add_completion=False,
)

DB_FILENAME = "qci.db"


def store_dir() -> Path:
    """``$QCI_HOME`` if set, otherwise ``./.qci``."""
    home = os.environ.get("QCI_HOME")
    return Path(home) if home else Path.cwd() / ".qci"


def _repository() -> SqliteRunRepository:
    return SqliteRunRepository(store_dir() / DB_FILENAME)


def _parse_tags(values: list[str]) -> dict[str, str]:
    tags: dict[str, str] = {}
    for item in values:
        key, sep, value = item.partition("=")
        if not sep or not key:
            raise typer.BadParameter(f"tag {item!r} must look like key=value", param_hint="--tag")
        tags[key] = value
    return tags


@app.command()
def run(
    workload: Annotated[Path, typer.Argument(help="Python file defining the workload.")],
    backend: Annotated[str, typer.Option(help="Backend name, e.g. fake_sherbrooke.")],
    seed: Annotated[
        int | None, typer.Option(help="Seed for both transpiler and simulator.")
    ] = None,
    shots: Annotated[int, typer.Option(min=1, help="Number of shots.")] = 1000,
    optimization_level: Annotated[
        int, typer.Option(min=0, max=3, help="Transpiler optimization level.")
    ] = 2,
    entrypoint: Annotated[str, typer.Option(help="Function returning the circuit.")] = "build",
    tag: Annotated[list[str] | None, typer.Option(help="Tag as key=value; repeatable.")] = None,
) -> None:
    """Execute a workload, capture an immutable Run, persist it and print its ID."""
    # Imported here so that `qci runs` / `qci show` do not pay Qiskit's import cost.
    from qci.adapters.qiskit_ibm import QiskitIbmAdapter

    request = RunRequest(
        workload_path=workload,
        backend_name=backend,
        entrypoint=entrypoint,
        compile_config=CompileConfig(optimization_level=optimization_level, seed_transpiler=seed),
        execution_config=ExecutionConfig(shots=shots, seed_simulator=seed),
        tags=_parse_tags(tag or []),
    )
    repository = _repository()
    try:
        result = RunService(QiskitIbmAdapter(), repository).run(request)
    except WorkloadLoadError as exc:
        typer.echo(f"error: {exc}", err=True)
        typer.echo("No run was recorded because the workload could not be loaded.", err=True)
        raise typer.Exit(code=2) from exc
    finally:
        repository.close()

    typer.echo(result.run_id)
    if result.status is RunStatus.FAILED and result.error is not None:
        typer.echo(
            f"run failed at stage '{result.error.stage}': "
            f"{result.error.error_type}: {result.error.message}",
            err=True,
        )
        typer.echo(
            f"The failed run was recorded. Inspect it with: qci show {result.run_id}", err=True
        )
        raise typer.Exit(code=1)
    typer.echo(f"Run succeeded. Inspect it with: qci show {result.run_id}", err=True)


@app.command()
def runs(
    limit: Annotated[int, typer.Option(min=1, help="Maximum number of runs to list.")] = 20,
) -> None:
    """List persisted runs, newest first."""
    repository = _repository()
    try:
        items = repository.list_runs(limit=limit)
    finally:
        repository.close()
    if not items:
        typer.echo("No runs recorded yet.")
        return
    header = f"{'RUN ID':<26}  {'CREATED (UTC)':<19}  {'STATUS':<9}  {'WORKLOAD':<16}  "
    header += f"{'BACKEND':<18}  COMMIT"
    typer.echo(header)
    for item in items:
        typer.echo(
            f"{item.run_id:<26}  {item.created_at.strftime('%Y-%m-%d %H:%M:%S'):<19}  "
            f"{item.status.value:<9}  {item.workload_name[:16]:<16}  "
            f"{(item.backend_name or '-')[:18]:<18}  {(item.git_commit or '-')[:10]}"
        )


def _circuit_lines(label: str, summary: CircuitSummary) -> list[str]:
    ops = ", ".join(f"{name}={count}" for name, count in summary.op_counts.items())
    lines = [
        f"{label}:",
        f"  qubits={summary.num_qubits} clbits={summary.num_clbits} depth={summary.depth} "
        f"size={summary.size} two_qubit_gates={summary.two_qubit_gate_count}",
        f"  ops: {ops}",
        f"  two-qubit edges: {summary.two_qubit_edges}",
        f"  qasm3: {'captured' if summary.qasm3 else 'unavailable: ' + str(summary.qasm3_error)}"
        f" ({summary.exporter.name} {summary.exporter.version})",
    ]
    return lines


def render_run(r: Run) -> str:
    git = r.provenance.git
    env = r.provenance.environment
    lines = [
        f"Run {r.run_id}",
        f"  status:     {r.status.value}",
        f"  created:    {r.created_at.isoformat()}",
        f"  schema:     v{r.schema_version} (qci {r.qci_version})",
    ]
    if r.tags:
        lines.append(f"  tags:       {r.tags}")
    if r.error:
        lines += [
            "Error:",
            f"  stage: {r.error.stage.value}",
            f"  type:  {r.error.error_type}",
            f"  message: {r.error.message}",
        ]
    lines += [
        "Workload:",
        f"  name: {r.workload.name}  entrypoint: {r.workload.entrypoint}",
        f"  source: {r.workload.source_path}",
        f"  source sha256: {r.workload.source_sha256}",
        "Provenance:",
        f"  git: commit={git.commit or '-'} branch={git.branch or '-'} "
        f"dirty={'-' if git.dirty is None else git.dirty} remote={git.remote or '-'}",
        f"  python: {env.python_implementation} {env.python_version} on {env.platform}",
        "  packages: " + ", ".join(f"{k}={v or 'not installed'}" for k, v in env.packages.items()),
        f"  environment hash: {env.config_hash}",
    ]
    lines += _circuit_lines("Logical circuit", r.logical_circuit)
    if r.backend:
        b = r.backend
        lines += [
            "Backend:",
            f"  {b.provider}/{b.name} version={b.version or '-'} qubits={b.num_qubits} "
            f"simulator={b.is_simulator}",
        ]
    if r.backend_snapshot:
        s = r.backend_snapshot
        raw = ", ".join(k for k, v in s.provider_raw.items() if v is not None) or "none"
        lines += [
            "Backend snapshot:",
            f"  source: {s.source.value}"
            + (
                "  (frozen fake calibration data, NOT live hardware)"
                if s.source == "static_fake"
                else ""
            ),
            f"  calibrated at: {s.calibrated_at.isoformat() if s.calibrated_at else 'unknown'}",
            f"  captured at:   {s.captured_at.isoformat()}",
            f"  basis gates: {', '.join(s.basis_gates)}",
            f"  coupling edges: {len(s.coupling_edges)}",
            f"  raw provider payloads: {raw}",
        ]
    if r.compilation:
        c = r.compilation
        lines += [
            "Compilation:",
            f"  compiler: {c.compiler.name} {c.compiler.version}",
            f"  config: optimization_level={c.config.optimization_level} "
            f"seed_transpiler={c.config.seed_transpiler}",
            f"  config hash: {c.config_hash}",
            f"  layout: initial={c.layout.initial if c.layout else '-'} "
            f"final={c.layout.final if c.layout else '-'}",
            f"  duration: {c.duration_ms:.1f} ms",
        ]
        lines += _circuit_lines("Transpiled circuit", c.output)
    if r.execution:
        e = r.execution
        lines += [
            "Execution:",
            f"  primitive: {e.primitive}",
            f"  config: shots={e.config.shots} seed_simulator={e.config.seed_simulator}",
            f"  config hash: {e.config_hash}",
            f"  started: {e.started_at.isoformat()}  finished: {e.finished_at.isoformat()}",
            f"  provider job id: {e.provider_job_id or '-'}",
        ]
    if r.result:
        lines.append(f"Result (measured, total_shots={r.result.total_shots}):")
        for register, counts in r.result.counts.items():
            ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
            lines.append(f"  {register}: " + ", ".join(f"{k}={v}" for k, v in ordered))
    if r.metrics:
        lines.append("Metrics:")
        for m in r.metrics:
            unit = f" {m.unit}" if m.unit else ""
            lines.append(
                f"  {m.name} = {m.value}{unit}  [{m.kind.value}; {m.method} v{m.method_version}]"
            )
    return "\n".join(lines)


@app.command()
def show(
    run_id: Annotated[str, typer.Argument(help="Run ID.")],
    as_json: Annotated[bool, typer.Option("--json", help="Print the full record as JSON.")] = False,
) -> None:
    """Display a persisted run."""
    repository = _repository()
    try:
        record = repository.get(run_id)
    except RunNotFoundError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    finally:
        repository.close()
    typer.echo(record.model_dump_json(indent=2) if as_json else render_run(record))


def main() -> None:
    try:
        app()
    except QCIError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise SystemExit(1) from exc
