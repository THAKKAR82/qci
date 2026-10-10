"""QCI command-line interface: run, runs, show, compare, and calibration snapshots."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from qci.adapters.qiskit_ibm import live as ibm_live
from qci.core.errors import (
    CaptureRejectedError,
    FixtureExportError,
    InvalidObservableError,
    QCIError,
    RunNotFoundError,
    SnapshotNotFoundError,
    WorkloadLoadError,
)
from qci.domain.circuit import CircuitSummary, CompileConfig
from qci.domain.comparison import ObservableSpec
from qci.domain.execution import ExecutionConfig
from qci.domain.run import Run, RunStatus
from qci.domain.snapshot import CalibrationSnapshot, SnapshotCapture
from qci.services.run_service import RunRequest, RunService, sanitize_error_message
from qci.services.snapshot_service import SnapshotService
from qci.storage.snapshots import SqliteSnapshotRepository
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


def _snapshot_repository() -> SqliteSnapshotRepository:
    return SqliteSnapshotRepository(store_dir() / DB_FILENAME)


snapshot_app = typer.Typer(
    help="Read-only calibration snapshots of live hardware. Nothing is executed.",
    no_args_is_help=True,
)
app.add_typer(snapshot_app, name="snapshot")


def _parse_observables(values: list[str]) -> list[ObservableSpec]:
    """Parse ``NAME=BITS[,BITS...]``. Bitstrings are provider counts keys, verbatim."""
    specs: list[ObservableSpec] = []
    for item in values:
        name, sep, bits = item.partition("=")
        if not sep or not name or not bits:
            raise typer.BadParameter(
                f"observable {item!r} must look like NAME=BITS[,BITS...]", param_hint="--observable"
            )
        try:
            specs.append(ObservableSpec(name=name, bitstrings=bits.split(",")))
        except ValidationError as exc:
            messages = "; ".join(e["msg"] for e in exc.errors())
            raise typer.BadParameter(
                f"observable {item!r}: {messages}", param_hint="--observable"
            ) from exc
    return specs


def _parse_tags(values: list[str]) -> dict[str, str]:
    tags: dict[str, str] = {}
    for item in values:
        key, sep, value = item.partition("=")
        if not sep or not key:
            raise typer.BadParameter(f"tag {item!r} must look like key=value", param_hint="--tag")
        tags[key] = value
    return tags


@dataclass(frozen=True)
class EffectiveSeeds:
    transpiler: int | None
    simulator: int | None


def resolve_seeds(
    seed: int | None, seed_transpiler: int | None, seed_simulator: int | None
) -> EffectiveSeeds:
    """Resolve per-stage seeds: the specific flag wins, then ``--seed``, then None (unseeded)."""
    return EffectiveSeeds(
        transpiler=seed_transpiler if seed_transpiler is not None else seed,
        simulator=seed_simulator if seed_simulator is not None else seed,
    )


@app.command()
def run(
    workload: Annotated[Path, typer.Argument(help="Python file defining the workload.")],
    backend: Annotated[str, typer.Option(help="Backend name, e.g. fake_sherbrooke.")],
    seed: Annotated[
        int | None,
        typer.Option(
            help="Shorthand seed for both transpiler and simulator. A specific "
            "--seed-transpiler or --seed-simulator overrides it for that stage."
        ),
    ] = None,
    seed_transpiler: Annotated[
        int | None,
        typer.Option(help="Transpiler seed. Overrides --seed for compilation only."),
    ] = None,
    seed_simulator: Annotated[
        int | None,
        typer.Option(help="Simulator (sampling) seed. Overrides --seed for execution only."),
    ] = None,
    shots: Annotated[int, typer.Option(min=1, help="Number of shots.")] = 1000,
    optimization_level: Annotated[
        int, typer.Option(min=0, max=3, help="Transpiler optimization level.")
    ] = 2,
    entrypoint: Annotated[str, typer.Option(help="Function returning the circuit.")] = "build",
    tag: Annotated[list[str] | None, typer.Option(help="Tag as key=value; repeatable.")] = None,
) -> None:
    """Execute a workload, capture an immutable Run, persist it and print its ID.

    Seed precedence, per stage: the specific flag, then --seed, then unseeded. An unseeded
    stage lets Qiskit choose its own randomness, so its output may differ between runs.
    """
    # Imported here so that `qci runs` / `qci show` do not pay Qiskit's import cost.
    from qci.adapters.qiskit_ibm import QiskitIbmAdapter

    seeds = resolve_seeds(seed, seed_transpiler, seed_simulator)
    request = RunRequest(
        workload_path=workload,
        backend_name=backend,
        entrypoint=entrypoint,
        compile_config=CompileConfig(
            optimization_level=optimization_level, seed_transpiler=seeds.transpiler
        ),
        execution_config=ExecutionConfig(shots=shots, seed_simulator=seeds.simulator),
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
def compare(
    baseline: Annotated[str, typer.Argument(help="Baseline run ID (the reference).")],
    candidate: Annotated[str, typer.Argument(help="Candidate run ID (compared against baseline).")],
    as_json: Annotated[
        bool, typer.Option("--json", help="Print the full comparison as JSON.")
    ] = False,
    observable: Annotated[
        list[str] | None,
        typer.Option(
            "--observable",
            help="NAME=BITS[,BITS...]: probability of the bitstring set, with Wilson and "
            "Newcombe intervals. Bitstrings are provider counts keys verbatim (Qiskit: "
            "classical bit 0 is the rightmost character). Repeatable.",
        ),
    ] = None,
) -> None:
    """Report what changed from BASELINE to CANDIDATE. Deltas are candidate minus baseline.

    Makes no better/worse, regression or causal claims.
    """
    specs = _parse_observables(observable or [])
    # Qiskit-free: the calibration reader parses stored JSON only.
    from qci.adapters.qiskit_ibm.adapter_ids import PROVIDER_ID
    from qci.adapters.qiskit_ibm.calibration import IbmPropertiesCalibrationReader
    from qci.cli.render_compare import render_comparison
    from qci.services.compare_service import CompareService

    repository = _repository()
    try:
        result = CompareService(
            repository, {PROVIDER_ID: IbmPropertiesCalibrationReader()}
        ).compare(baseline, candidate, specs)
    except RunNotFoundError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except InvalidObservableError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    finally:
        repository.close()
    typer.echo(result.model_dump_json(indent=2) if as_json else render_comparison(result))


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


AccountOption = Annotated[
    str,
    typer.Option(
        help="Name of an account saved with QiskitRuntimeService.save_account. QCI uses only "
        "saved accounts, never environment variables, and never stores or prints credentials."
    ),
]


def _safe_error(exc: BaseException, account: str) -> str:
    """Sanitized error text with the account name removed."""
    message = sanitize_error_message(str(exc))
    return message.replace(account, "[account]") if account else message


@snapshot_app.command("capture")
def snapshot_capture(
    backend: Annotated[str, typer.Option(help="Live IBM backend name, e.g. ibm_fez.")],
    account: AccountOption = ibm_live.DEFAULT_ACCOUNT,
) -> None:
    """Read the backend's published calibration once and store it as a snapshot.

    Uses the network. Runs once: no retries, polling or scheduling. Content identical to an
    existing snapshot adds only a capture record. On any error nothing is stored.
    """
    source = ibm_live.IbmLiveCalibrationSource(account=account)
    try:
        captured = source.capture(backend)
    except CaptureRejectedError as exc:
        typer.echo(f"error: {_safe_error(exc, account)}", err=True)
        raise typer.Exit(code=2) from exc
    except Exception as exc:
        typer.echo(
            f"error: capture failed: {type(exc).__name__}: {_safe_error(exc, account)}", err=True
        )
        typer.echo("Nothing was recorded.", err=True)
        raise typer.Exit(code=1) from exc

    repository = _snapshot_repository()
    try:
        outcome = SnapshotService(repository).record(captured)
    finally:
        repository.close()
    snap = outcome.snapshot
    typer.echo(snap.snapshot_id)
    typer.echo(
        "New snapshot."
        if outcome.created
        else "Content identical to this existing snapshot; recorded one more capture.",
        err=True,
    )
    calibrated = snap.calibrated_at.isoformat() if snap.calibrated_at else "unknown"
    typer.echo(f"calibrated at: {calibrated}", err=True)
    typer.echo(f"measurements: {outcome.measurement_count}", err=True)
    if snap.provider_raw.get("properties") is None:
        typer.echo("note: the provider returned no properties payload.", err=True)
    typer.echo(f"Inspect it with: qci snapshot show {snap.snapshot_id}", err=True)


@app.command()
def snapshots(
    backend: Annotated[str | None, typer.Option(help="Only this backend.")] = None,
    limit: Annotated[int, typer.Option(min=1, help="Maximum number of snapshots.")] = 20,
) -> None:
    """List calibration snapshots, newest first capture first."""
    repository = _snapshot_repository()
    try:
        items = repository.list_snapshots(backend_name=backend, limit=limit)
    finally:
        repository.close()
    if not items:
        typer.echo("No snapshots recorded yet.")
        return
    typer.echo(
        f"{'SNAPSHOT ID':<26}  {'BACKEND':<18}  {'CALIBRATED (UTC)':<19}  "
        f"{'FIRST CAPTURE (UTC)':<19}  {'LAST CAPTURE (UTC)':<19}  CAPTURES"
    )
    fmt = "%Y-%m-%d %H:%M:%S"
    for item in items:
        calibrated = item.calibrated_at.strftime(fmt) if item.calibrated_at else "-"
        typer.echo(
            f"{item.snapshot_id:<26}  {item.backend_name[:18]:<18}  {calibrated:<19}  "
            f"{item.first_captured_at.strftime(fmt):<19}  "
            f"{item.last_captured_at.strftime(fmt):<19}  {item.capture_count}"
        )


def render_snapshot(
    snap: CalibrationSnapshot, captures: list[SnapshotCapture], measurement_count: int
) -> str:
    raw = ", ".join(k for k, v in snap.provider_raw.items() if v is not None) or "none"
    lines = [
        f"Snapshot {snap.snapshot_id}",
        f"  backend:        {snap.provider}/{snap.backend_name} "
        f"version={snap.backend_version or '-'}",
        f"  source:         {snap.source.value}",
        f"  calibrated at:  {snap.calibrated_at.isoformat() if snap.calibrated_at else 'unknown'}",
        f"  first captured: {snap.captured_at.isoformat()}",
        f"  captures:       {len(captures)}"
        + (f" (last {captures[-1].captured_at.isoformat()})" if captures else ""),
        f"  content hash:   {snap.content_hash}",
        f"  capture options: {snap.capture_options}",
        f"  measurements:   {measurement_count} "
        f"[{snap.extraction_method} v{snap.extraction_method_version}]",
        f"  redacted paths: {len(snap.redactions)}",
        "  environment:    " + ", ".join(f"{k}={v}" for k, v in snap.environment.items()),
        f"  raw provider payloads: {raw}",
    ]
    return "\n".join(lines)


@snapshot_app.command("show")
def snapshot_show(
    snapshot_id: Annotated[str, typer.Argument(help="Snapshot ID.")],
    as_json: Annotated[bool, typer.Option("--json", help="Print the full record as JSON.")] = False,
) -> None:
    """Display a stored calibration snapshot."""
    repository = _snapshot_repository()
    try:
        snap = repository.get(snapshot_id)
        captures = repository.captures(snapshot_id)
        measurement_count = len(repository.measurements(snapshot_id))
    except SnapshotNotFoundError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    finally:
        repository.close()
    typer.echo(
        snap.model_dump_json(indent=2)
        if as_json
        else render_snapshot(snap, captures, measurement_count)
    )


@snapshot_app.command("export")
def snapshot_export(
    snapshot_id: Annotated[str, typer.Argument(help="Snapshot ID.")],
    fixture: Annotated[Path, typer.Option(help="Path of the fixture JSON file to write.")],
    account: AccountOption = ibm_live.DEFAULT_ACCOUNT,
) -> None:
    """Write a sanitized test fixture. Offline (developer use).

    Redacts again, replaces local IDs with placeholders, and aborts without writing if the
    output contains the saved account's token, instance or URL verbatim.
    """
    from qci.adapters.qiskit_ibm.redact import redact_payload

    try:
        secrets = ibm_live.load_account_secrets(account)
    except Exception as exc:
        typer.echo(
            f"error: cannot read the saved account for the export scan ({type(exc).__name__}). "
            "Nothing was written.",
            err=True,
        )
        raise typer.Exit(code=1) from exc
    repository = _snapshot_repository()
    try:
        text = SnapshotService(repository).export_fixture(
            snapshot_id, redact=redact_payload, secrets=secrets
        )
    except (SnapshotNotFoundError, FixtureExportError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    finally:
        repository.close()
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_text(text, encoding="utf-8")
    typer.echo(f"wrote {fixture}", err=True)


def main() -> None:
    try:
        app()
    except QCIError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise SystemExit(1) from exc
