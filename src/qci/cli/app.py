"""QCI command-line interface: run, runs, show, compare, and calibration snapshots."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from qci.adapters.qiskit_ibm import live as ibm_live
from qci.adapters.qiskit_ibm.extra import EXTRA_MESSAGE, missing_sdk_modules
from qci.core.errors import (
    BackfillRejectedError,
    CaptureRejectedError,
    DamagedStoreError,
    FixtureExportError,
    InvalidObservableError,
    LookupRejectedError,
    QCIError,
    RunNotFoundError,
    SchemaVersionError,
    SnapshotNotFoundError,
    TooManyRequestsError,
    WorkloadLoadError,
)
from qci.core.selectors import (
    Entry,
    Kind,
    SelectorAmbiguousError,
    SelectorNotFoundError,
    SelectorUsageError,
    resolve,
)
from qci.domain.circuit import CircuitSummary, CompileConfig
from qci.domain.comparison import ObservableSpec
from qci.domain.execution import ExecutionConfig
from qci.domain.run import Run, RunStatus
from qci.domain.snapshot import CalibrationSnapshot, SnapshotCapture
from qci.services.run_service import RunRequest, RunService, sanitize_error_message
from qci.services.snapshot_service import SnapshotService
from qci.storage.location import (
    DB_FILENAME,
    create_store_directory,
    legacy_note,
    legacy_store,
    store_location,
)
from qci.storage.snapshots import SqliteSnapshotRepository
from qci.storage.sqlite import SqliteRunRepository

app = typer.Typer(
    help="QCI: instrumented, immutable records of quantum workload runs.",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def _legacy_store_note() -> None:
    # Every command opens a store or reports on it (where, doctor), so the note about a
    # ./.qci store from before R1 is printed once per invocation, on stderr (ADR 0009,
    # section 3). It only checks that the file exists.
    legacy = legacy_store(Path.cwd())
    if legacy is not None:
        typer.echo(legacy_note(legacy, store_location()), err=True)


def store_dir() -> Path:
    """``$QCI_HOME`` if set and non-empty, otherwise the per-user store directory."""
    return store_location().directory


def _open[T](open_store: Callable[[], T]) -> T:
    """Open a repository, turning a damaged or unsupported store into an error and exit 1."""
    try:
        return open_store()
    except (DamagedStoreError, SchemaVersionError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


def _store_db(*, read_only: bool) -> Path:
    directory = store_dir()
    if not read_only:
        create_store_directory(directory)
    return directory / DB_FILENAME


def _repository(*, read_only: bool = False) -> SqliteRunRepository:
    return _open(lambda: SqliteRunRepository(_store_db(read_only=read_only), read_only=read_only))


def _snapshot_repository(*, read_only: bool = False) -> SqliteSnapshotRepository:
    """``read_only`` for commands that only read: they never create or write the store."""
    return _open(
        lambda: SqliteSnapshotRepository(_store_db(read_only=read_only), read_only=read_only)
    )


def _require_ibm_extra() -> None:
    """Exit 2 without the provider SDKs, before any store is opened or workload loaded."""
    if missing_sdk_modules():
        typer.echo(f"error: {EXTRA_MESSAGE}", err=True)
        raise typer.Exit(code=2)


def _calibration_stamp(value: datetime | None) -> str | None:
    """A fixed-width UTC string, so stamps order as text in the same order as in time."""
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") if value else None


def _run_entries(repository: SqliteRunRepository) -> list[Entry]:
    return [(item.run_id, item.backend_name, item.run_id) for item in repository.list_runs()]


def _snapshot_entries(repository: SqliteSnapshotRepository) -> list[Entry]:
    return [
        (item.snapshot_id, item.backend_name, _calibration_stamp(item.calibrated_at))
        for item in repository.list_snapshots()
    ]


def _select(selector: str, entries: list[Entry], kind: Kind, role: str) -> str:
    """Resolve a selector (ADR 0009, section 5). Prints ``role: selector -> ID`` on stderr
    when the argument was not the ID itself; stdout is never touched."""
    try:
        chosen = resolve(selector, entries, kind)
    except SelectorUsageError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    except (SelectorNotFoundError, SelectorAmbiguousError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if chosen != selector:
        typer.echo(f"{role}: {selector} -> {chosen}", err=True)
    return chosen


def _select_run(repository: SqliteRunRepository, selector: str, role: str) -> str:
    return _select(selector, _run_entries(repository), "run", role)


def _select_snapshot(repository: SqliteSnapshotRepository, selector: str, role: str) -> str:
    return _select(selector, _snapshot_entries(repository), "snapshot", role)


RUN_SELECTOR = (
    "a run ID, a unique ID prefix of 8 or more characters, or [BACKEND:]latest[~N] "
    "(latest is the newest run, latest~1 the one before)"
)
SNAPSHOT_SELECTOR = (
    "a snapshot ID, a unique ID prefix of 8 or more characters, or BACKEND:latest[~N] "
    "(by calibrated_at: the newest calibration, then the one before)"
)


snapshot_app = typer.Typer(
    help="Read-only calibration snapshots of live hardware, captured now or looked up for "
    "past times. Nothing is executed.",
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
    _require_ibm_extra()
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
    # Opening checks the store first: a damaged or other-version store exits 1 here, before
    # the workload is loaded and before any run record, succeeded or failed, exists.
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
    repository = _repository(read_only=True)
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
    baseline: Annotated[str, typer.Argument(help=f"Baseline run (the reference): {RUN_SELECTOR}.")],
    candidate: Annotated[
        str,
        typer.Argument(help="Candidate run (compared against baseline), selected the same way."),
    ],
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

    repository = _repository(read_only=True)
    try:
        baseline = _select_run(repository, baseline, "baseline")
        candidate = _select_run(repository, candidate, "candidate")
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
    run_id: Annotated[str, typer.Argument(help=f"The run: {RUN_SELECTOR}.")],
    as_json: Annotated[bool, typer.Option("--json", help="Print the full record as JSON.")] = False,
) -> None:
    """Display a persisted run."""
    repository = _repository(read_only=True)
    try:
        record = repository.get(_select_run(repository, run_id, "run"))
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
    _require_ibm_extra()
    # Check the store before the network read: a damaged or other-version store exits 1
    # with no client built. Read-only, so an absent store is not created here.
    _snapshot_repository(read_only=True).close()
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


BACKFILL_STAMP_NOTE = (
    "Backfilled history is documents by provider stamp time, not what a user would have seen "
    "at a given time: a document stamped before a requested time can have been published after "
    "it."
)


BACKFILL_HELP = "\n\n".join(
    [
        "Look up past calibration of a live device and store each returned document as a "
        "historical_lookup snapshot.",
        "Uses the network. One properties request per pending grid time: one UTC midnight per "
        "day (or every --step-hours hours), newest first, going back --days days, capped at the "
        "device's verified lookup depth (365 days for ibm_fez, ibm_kingston and "
        "ibm_marrakesh). Requested times are sent as UTC with a zero offset. A lookup stores "
        "no configuration: the provider keeps no configuration history.",
        BACKFILL_STAMP_NOTE,
        "Each invocation is bounded: at most --max-requests requests (default 30, at most "
        "100), with --pause seconds before each one (default 10, minimum 2). QCI retries "
        "nothing and stops at the first error, including the first too-many-requests response "
        "(HTTP 429 or IBM error code 1202). The IBM client's own HTTP session may still retry "
        "some 5xx responses (up to 5 times, with backoff); that is outside QCI's control. "
        "Every lookup stored before an error is kept. Grid times already stored are skipped "
        "without a request, so re-running the same command continues where the last one "
        "stopped.",
        "A returned document without a date, or dated after its requested time, stores "
        "nothing and stops with exit 1. Backfilled data stays in the local store: qci snapshot "
        "export refuses it.",
    ]
)


@snapshot_app.command("backfill", help=BACKFILL_HELP)
def snapshot_backfill(
    backend: Annotated[str, typer.Option(help="Live IBM device name, e.g. ibm_fez.")],
    days: Annotated[
        int, typer.Option(min=1, help="How many days back, at most the verified depth.")
    ],
    step_hours: Annotated[
        int, typer.Option(min=1, help="Hours between grid times (24: UTC midnights).")
    ] = 24,
    max_requests: Annotated[
        int, typer.Option(min=1, max=100, help="Most requests in this invocation.")
    ] = 30,
    pause: Annotated[
        float, typer.Option(min=2.0, help="Seconds to wait before each request.")
    ] = 10.0,
    account: AccountOption = ibm_live.DEFAULT_ACCOUNT,
) -> None:
    _require_ibm_extra()
    from qci.adapters.qiskit_ibm.historical import IbmHistoricalCalibrationSource
    from qci.services.backfill_service import BackfillService, LookupResult

    service = BackfillService(IbmHistoricalCalibrationSource(account=account))
    # Check the store and plan before any request. Read-only, so nothing is created or
    # upcast when nothing is requested.
    reader = _snapshot_repository(read_only=True)
    try:
        plan = service.plan(reader, backend, days, step_hours)
    except BackfillRejectedError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    finally:
        reader.close()
    typer.echo(
        f"grid times: {len(plan.grid)}; already stored: {plan.already_stored}; "
        f"pending: {len(plan.pending)}",
        err=True,
    )
    if not plan.pending:
        typer.echo("Nothing to request.", err=True)
        return

    try:
        lookup = service.open(plan)
    except BackfillRejectedError as exc:
        typer.echo(f"error: {_safe_error(exc, account)}", err=True)
        raise typer.Exit(code=2) from exc
    except Exception as exc:
        typer.echo(
            f"error: backfill failed: {type(exc).__name__}: {_safe_error(exc, account)}",
            err=True,
        )
        typer.echo("Nothing was recorded.", err=True)
        raise typer.Exit(code=1) from exc

    stored: list[LookupResult] = []

    def show(result: LookupResult) -> None:
        stored.append(result)
        snap = result.outcome.snapshot
        calibrated = snap.calibrated_at.isoformat() if snap.calibrated_at else "unknown"
        typer.echo(
            f"{result.requested_before.isoformat()}  {snap.snapshot_id}  "
            f"calibrated_at={calibrated}  {'new' if result.outcome.created else 'existing'}"
        )

    repository = _snapshot_repository()
    try:
        report = service.run(
            repository,
            lookup,
            plan,
            max_requests=max_requests,
            pause_seconds=pause,
            on_result=show,
        )
    except TooManyRequestsError as exc:
        typer.echo(f"error: stopped: {exc}. Nothing was retried.", err=True)
        typer.echo(f"Lookups stored before it are kept: {len(stored)}.", err=True)
        raise typer.Exit(code=1) from exc
    except LookupRejectedError as exc:
        typer.echo(f"error: {exc}", err=True)
        typer.echo(f"Lookups stored before it are kept: {len(stored)}.", err=True)
        raise typer.Exit(code=1) from exc
    except Exception as exc:
        typer.echo(
            f"error: backfill failed: {type(exc).__name__}: {_safe_error(exc, account)}",
            err=True,
        )
        typer.echo(f"Lookups stored before it are kept: {len(stored)}.", err=True)
        raise typer.Exit(code=1) from exc
    finally:
        repository.close()
    typer.echo(f"requested: {report.requested}; remaining: {report.remaining}", err=True)
    if report.remaining:
        typer.echo("Re-run the same command to continue.", err=True)
    typer.echo(f"note: {BACKFILL_STAMP_NOTE}", err=True)


@app.command()
def snapshots(
    backend: Annotated[str | None, typer.Option(help="Only this backend.")] = None,
    limit: Annotated[int, typer.Option(min=1, help="Maximum number of snapshots.")] = 20,
) -> None:
    """List calibration snapshots, newest first capture first."""
    repository = _snapshot_repository(read_only=True)
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
    lookups = [c for c in captures if c.requested_before is not None]
    if lookups:
        lines.append(f"  historical lookups: {len(lookups)}")
        lines += [
            f"    {c.capture_id}  requested_before={c.requested_before.isoformat()}  "
            f"requested_at={c.captured_at.isoformat()}"
            for c in lookups
            if c.requested_before is not None
        ]
    return "\n".join(lines)


@snapshot_app.command("show")
def snapshot_show(
    snapshot_id: Annotated[str, typer.Argument(help=f"The snapshot: {SNAPSHOT_SELECTOR}.")],
    as_json: Annotated[bool, typer.Option("--json", help="Print the full record as JSON.")] = False,
) -> None:
    """Display a stored calibration snapshot."""
    repository = _snapshot_repository(read_only=True)
    try:
        snapshot_id = _select_snapshot(repository, snapshot_id, "snapshot")
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
    snapshot_id: Annotated[str, typer.Argument(help=f"The snapshot: {SNAPSHOT_SELECTOR}.")],
    fixture: Annotated[Path, typer.Option(help="Path of the fixture JSON file to write.")],
    account: AccountOption = ibm_live.DEFAULT_ACCOUNT,
) -> None:
    """Write a sanitized test fixture. Offline (developer use).

    Redacts again, replaces local IDs with placeholders, and aborts without writing if the
    output contains the saved account's token, instance or URL verbatim.
    """
    _require_ibm_extra()
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
    repository = _snapshot_repository(read_only=True)
    try:
        snapshot_id = _select_snapshot(repository, snapshot_id, "snapshot")
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


@snapshot_app.command("compare")
def snapshot_compare(
    baseline: Annotated[
        str, typer.Argument(help=f"Baseline snapshot (the reference): {SNAPSHOT_SELECTOR}.")
    ],
    candidate: Annotated[str, typer.Argument(help="Candidate snapshot, selected the same way.")],
    footprint_run: Annotated[
        str,
        typer.Option(
            help="Run whose physical footprint selects the resources to compare. The run is "
            f"not compared with either snapshot. {RUN_SELECTOR[0].upper()}{RUN_SELECTOR[1:]}."
        ),
    ],
    allow_footprint_backend_mismatch: Annotated[
        bool,
        typer.Option(
            "--allow-footprint-backend-mismatch",
            help="Use a footprint run from another backend, such as fake_fez for ibm_fez "
            "snapshots. Every footprint resource must then exist in both snapshots.",
        ),
    ] = False,
    as_json: Annotated[
        bool, typer.Option("--json", help="Print the full comparison as JSON.")
    ] = False,
) -> None:
    """Report what differs from BASELINE to CANDIDATE snapshot, for one run's footprint.

    Offline and read-only; nothing is stored. Deltas are candidate minus baseline.
    """
    from qci.adapters.qiskit_ibm.adapter_ids import PROVIDER_ID
    from qci.adapters.qiskit_ibm.calibration import snapshot_comparison_support
    from qci.cli.render_snapshot_compare import render_snapshot_comparison
    from qci.services.snapshot_compare_service import SnapshotCompareService

    runs = _repository(read_only=True)
    try:
        snapshots_repo = _snapshot_repository(read_only=True)
    except typer.Exit:
        runs.close()
        raise
    try:
        baseline = _select_snapshot(snapshots_repo, baseline, "baseline")
        candidate = _select_snapshot(snapshots_repo, candidate, "candidate")
        footprint_run = _select_run(runs, footprint_run, "footprint run")
        result = SnapshotCompareService(
            runs, snapshots_repo, {PROVIDER_ID: snapshot_comparison_support()}
        ).compare(
            baseline,
            candidate,
            footprint_run,
            allow_footprint_backend_mismatch=allow_footprint_backend_mismatch,
        )
    except (SnapshotNotFoundError, RunNotFoundError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    finally:
        snapshots_repo.close()
        runs.close()
    typer.echo(result.model_dump_json(indent=2) if as_json else render_snapshot_comparison(result))


@snapshot_app.command("compare-run")
def snapshot_compare_run(
    run_id: Annotated[
        str,
        typer.Argument(
            help=f"Baseline: a stored run on a fake backend (the reference); {RUN_SELECTOR}."
        ),
    ],
    snapshot_id: Annotated[
        str,
        typer.Argument(
            help="Candidate: a stored live snapshot of the device the fake was built from; "
            f"{SNAPSHOT_SELECTOR}."
        ),
    ],
    as_json: Annotated[
        bool, typer.Option("--json", help="Print the full comparison as JSON.")
    ] = False,
) -> None:
    """Report what differs from the calibration stored in RUN_ID's fake backend to SNAPSHOT_ID,
    for the run's footprint.

    The fake-to-device pairing comes from an explicit list in the provider adapter. Offline and
    read-only; nothing is stored. Deltas and date differences are live minus fake.
    """
    from qci.adapters.qiskit_ibm.adapter_ids import PROVIDER_ID
    from qci.adapters.qiskit_ibm.calibration import run_snapshot_comparison_support
    from qci.cli.render_run_snapshot_compare import render_run_snapshot_comparison
    from qci.services.run_snapshot_compare_service import RunSnapshotCompareService

    runs = _repository(read_only=True)
    try:
        snapshots_repo = _snapshot_repository(read_only=True)
    except typer.Exit:
        runs.close()
        raise
    try:
        run_id = _select_run(runs, run_id, "run")
        snapshot_id = _select_snapshot(snapshots_repo, snapshot_id, "snapshot")
        result = RunSnapshotCompareService(
            runs, snapshots_repo, {PROVIDER_ID: run_snapshot_comparison_support()}
        ).compare(run_id, snapshot_id)
    except (SnapshotNotFoundError, RunNotFoundError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    finally:
        snapshots_repo.close()
        runs.close()
    typer.echo(
        result.model_dump_json(indent=2) if as_json else render_run_snapshot_comparison(result)
    )


@app.command()
def where() -> None:
    """Print the path of the qci.db file that commands use. Opens nothing.

    stdout is the path alone, so that shasum -a 256 "$(qci where)" works. stderr says where
    the path came from and whether the file exists.
    """
    location = store_location()
    typer.echo(str(location.db))
    typer.echo(f"source: {location.source}", err=True)
    typer.echo(
        "file: exists"
        if location.db.is_file()
        else "file: does not exist yet (the first command that writes creates it)",
        err=True,
    )


@app.command()
def doctor() -> None:
    """Check the installation, the saved IBM account and the store, one line per check.

    Local and read-only: no network, no IBM client, nothing written. Exit 0 when no check
    reports a problem (notes allowed), 1 otherwise.
    """
    from qci.cli import doctor as checks

    results = checks.run_checks(checks.default_inputs())
    for check in results:
        typer.echo(check.line())
    if any(check.outcome == "problem" for check in results):
        raise typer.Exit(code=1)


def main() -> None:
    try:
        app()
    except QCIError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise SystemExit(1) from exc
