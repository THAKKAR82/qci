# Architecture

QCI is a modular monolith: one Python package with enforced internal boundaries. Provider SDKs
appear only inside adapters. See [ADR 0001](adr/0001-modular-monolith.md) and
[ADR 0002](adr/0002-provider-abstraction.md). Execution is modeled as a stack of levels, with
only the physical level today, and new code must respect the constraints in
[ADR 0006](adr/0006-execution-levels.md).

## Layers

```
cli/            Typer commands: argument parsing and rendering only
  │
services/       Use-case orchestration (RunService, CompareService, SnapshotService)
  │  depends on ports, never on adapters directly
compare/        Pure comparison logic over stored runs: provider-neutral
  │
core/           ports.py (Protocols), hashing.py, ids.py: pure Python
domain/         Pydantic models: pure data, no I/O, no provider SDKs
  ▲
adapters/       Provider implementations of the ports (qiskit_ibm/ first)
storage/        Run and snapshot repository implementations (sqlite first)
provenance/     Git and environment collectors: plain Python
```

**Dependency rule:** the layers form a strict DAG: `domain` ← `core` ← `compare` ←
`services` ← `cli`. `domain` depends on nothing in QCI. `core` depends only on `domain`.
`compare` depends on `core` and `domain`. `services` depends on `compare`, `core`, `domain`
and `provenance`. Adapters, storage and provenance implement or supply `core` interfaces and
depend only on `core` and `domain`. The CLI wires concrete implementations together: it
imports `services` and `storage`, and imports adapters lazily inside the command that needs
them. The exception is `adapters/qiskit_ibm/live.py`, which the CLI imports at module level
for the default account name. That module imports `qiskit_ibm_runtime` only when it builds
the client, and `tests/test_architecture.py` checks that importing it loads no provider SDK.

`tests/test_architecture.py` enforces that `qci.domain` and `qci.core` never import a provider
SDK.

## Ports (M0)

All ports are `typing.Protocol` classes in `qci/core/ports.py`.

| Port | Responsibility |
|---|---|
| `WorkloadLoader` | Load a workload from a path and entrypoint. Returns a source description plus an opaque native circuit handle. |
| `Compiler` | Compile or transpile a native circuit for a backend under a `CompileConfig`. Returns a normalized `CompilationRecord` plus an opaque native handle. |
| `BackendCatalog` | Resolve a backend by name and capture a `BackendSnapshot`, keeping raw provider payloads. |
| `Executor` | Execute a compiled native circuit under an `ExecutionConfig`. Returns a normalized `ExecutionResult`. |
| `ProviderAdapter` | Bundles the four ports above for one provider, keyed by provider ID such as `qiskit_ibm`. |
| `RunRepository` | Insert-only persistence with `save`, `get` and `list`. It has no update or delete. |
| `CalibrationSource` (M1.3b) | Read a backend's published calibration once. Returns a `CapturedCalibration`: redacted raw payload, UTC-normalized dates, measurements and capture options. |
| `SnapshotRepository` (M1.3b) | Insert-only snapshot persistence with `save` (deduplicates by content hash and always adds a capture row), `get`, `get_by_hash`, `list_snapshots`, `measurements` and `captures`. It has no update or delete. |

### Why opaque handles

Compilation and execution need the provider's native objects, such as a Qiskit
`QuantumCircuit` and a `BackendV2`. The service passes these between ports of the *same*
adapter as `object`. The domain only ever sees normalized summaries plus raw payloads
serialized to JSON. This keeps SDK types out of the domain without forcing a premature
universal intermediate representation for circuits.

## M0 data flow

```
qci run PATH --backend NAME [--seed S] [--seed-transpiler T] [--seed-simulator U]
  1. provenance: collect git + environment             (never fails the run; nulls allowed)
  2. loader.load(PATH, entrypoint)                     → WorkloadSource + native circuit
  3. catalog.resolve(NAME); catalog.snapshot(handle)   → Backend + BackendSnapshot (raw kept)
  4. compiler.compile(native, handle, CompileConfig)   → CompilationRecord (+ native compiled)
  5. executor.execute(compiled, handle, ExecConfig)    → ExecutionResult (counts)
  6. metrics: label measured and calculated values     → [Metric]
  7. assemble the immutable Run (status=succeeded | failed) and insert it in one transaction
```

If any step from 3 onward raises, the service still persists a Run with `status=failed`. That
run records the failing stage, the error type and a sanitized message, and everything captured
before the failure. Sanitizing strips URL credentials, CRNs, bearer tokens and JWTs, and truncates to
2000 characters. The
failing stage is one of `resolve_backend`, `snapshot`, `compile`, `execute` or `metrics`. The
CLI prints the run ID and the error, then exits with code 1.

If the workload itself cannot be loaded in step 2, M0 reports the error, persists nothing and
exits with code 2. Whether load failures should also become runs is open as D11 in `PLAN.md`.

Provenance is collected after the workload loads. Git state is read from the directory that
contains the workload file, not from the current working directory.

### CLI exit codes

The exit codes are a contract.

| Command | Code | Meaning |
|---|---|---|
| `qci run` | 0 | The run succeeded and was persisted. |
| `qci run` | 1 | The run failed and **was persisted** with `status=failed` and the failing stage. |
| `qci run` | 2 | The workload could not be loaded. **Nothing was persisted.** |
| `qci show`, `qci compare` | 1 | A run ID was not found. |
| `qci compare` | 2 | An `--observable` argument is invalid. |
| `qci snapshot capture` | 0 | A snapshot was stored, or identical content was recorded as one more capture. |
| `qci snapshot capture` | 1 | Capture failed. **Nothing was persisted.** The message is sanitized. |
| `qci snapshot capture` | 2 | The backend is a fake (`fake_*` or a fake object) or a simulator. **Nothing was persisted.** |
| `qci snapshot show`, `qci snapshot export` | 1 | A snapshot ID was not found, the saved account could not be read for the export scan, or the export was unsafe. Export writes nothing. |
| any | 1 | Any other `QCIError` that reaches `main()`. |
| any | 2 | A usage error reported by Typer. |

`qci run` prints the run ID to stdout before the error, which goes to stderr. `qci snapshot
capture` prints the snapshot ID to stdout and its details to stderr.

## Qiskit/IBM adapter notes (M0)

- **Backend lookup.** Fake backends are looked up by their class's `backend_name`, so only the
  requested backend is instantiated.
- **Simulation.** QCI executes workloads on fake backends using the provider's local
  simulator and that backend's noise model; QCI does not construct noise models of its own.
- **Execution.** `qiskit.primitives.BackendSamplerV2` runs the circuit with `default_shots`
  and `seed_simulator`. `qiskit_ibm_runtime.SamplerV2` is deprecated as of 0.50. Its local
  testing mode wraps the same class, with identical counts, and it silently ignores
  `seed_simulator=0`.
- **Raw payloads.** `properties().to_dict()` and `configuration().to_dict()` contain `datetime`
  and `complex` values. `to_jsonable` encodes them with explicit tags and raises on unknown
  types.
- **Circuit summaries.** Summaries cover top-level instructions only. Control-flow bodies are
  not descended into in M0.
- **Edges versus operands.** `summarize.py` normalizes two-qubit edges to undirected
  `(min, max)` pairs for the circuit summary. `compare/footprint.py` keeps the ordered qubit
  operands of each operation. The order matters: IBM may calibrate `ecr(104,103)` and not
  `ecr(103,104)`, so calibration is looked up by exact ordered operands. The two
  representations serve different purposes and must stay separate.

## M1 compare flow

```
qci compare BASELINE CANDIDATE [--json]
  CompareService (read-only)
    repository.get(baseline), repository.get(candidate)          # unmodified schema-v1 records
    compare/sections.py   explicit semantic comparisons per section
    compare/footprint.py  physical footprint from stored transpiled OpenQASM 3   (ADR 0004)
    compare/hardware.py   footprint comparison + footprint-scoped calibration comparison
                          └─ CalibrationReader port, chosen by backend.provider
                             (adapters/qiskit_ibm/calibration.py: pure dict parsing, no Qiskit)
    compare/distribution.py  comparability gate, TVD and Hellinger distance metrics
    compare/divergence.py    pure TVD and Hellinger distance functions
    compare/sampling.py      TVD sampling floor, only after the gate passes: pooled-H0
                             multinomial resampling, seeded from the comparison_id; skipped
                             when both runs were simulated with the same simulator seed
    compare/observables.py   requested observables behind the same gate: bitstring counts
                             to (k, n), then compare/proportions.py (Wilson, Newcombe on
                             integer k and n only; ADR 0006); the Newcombe interval
                             is withheld under the same shared-seed rule as the floor
  → Comparison (deterministic comparison_id including the observable request, policy
    qci.compare.v3, engine qci.compare.engine.4, never persisted)
```

- **Provider neutrality.** The `compare` package, `domain/comparison.py` and
  `services/compare_service.py` import no provider SDK, and `tests/test_architecture.py`
  enforces it. `openqasm3` is the vendor-neutral OpenQASM reference parser, used only inside
  `compare/footprint.py`.
- **Lazy adapter import.** `qci.adapters.qiskit_ibm` imports `QiskitIbmAdapter` lazily, so
  `qci compare` never imports Qiskit. The package `__init__.py` uses a PEP 562 module
  `__getattr__`, with the real import behind `TYPE_CHECKING` for type checkers. Qiskit-free
  modules in the package, such as the calibration reader, can then be imported without
  Qiskit. A new adapter should copy this pattern.
- **Footprint-parity canary.** `tests/test_footprint_parity.py` transpiles real circuits at
  optimization levels 0, 1 and 3, plus a scheduled `delay`, and asserts that the
  QASM3-derived footprint equals the native circuit's operations. It is the canary for
  `openqasm3` and `qiskit` upgrades: under ADR 0004, an AST change must be absorbed in
  `compare/footprint.py` and pass this test.
- **New port.** `CalibrationReader.select(snapshot, qubits, operations)` returns calibration
  for exactly the requested physical resources. Missing data is returned as unavailable, never
  as zero.

## M1.3b snapshot capture flow

Read-only. QCI executes nothing on hardware. See [ADR 0005](adr/0005-live-calibration-snapshots.md).

```
qci snapshot capture --backend NAME [--account ACCOUNT]
  1. reject fake_* names                                → exit 2, no client built
  2. QiskitRuntimeService(name=ACCOUNT)                 → saved account only, never env vars
  3. service.backend(NAME, use_fractional_gates=False)  → reject fakes and simulators (exit 2)
  4. configuration(); properties(refresh=True)          → client logging disabled meanwhile
  5. datetimes → UTC; to_jsonable; redact_payload       → provider_raw + redaction paths
  6. extract_measurements(properties)                   → generic measurement rows
  7. open the store; SnapshotService.record             → hash, dedupe, insert in one transaction
```

Any error in steps 2 to 6 persists nothing, does not create the database, prints a sanitized
message without the account name, and exits 1. `qiskit_ibm_runtime` is imported lazily in
`adapters/qiskit_ibm/live.py`. The service factory is injectable, and tests never construct
the real client: a session guard in `tests/conftest.py` blocks `QiskitRuntimeService`,
`AccountManager.get` and network connections.

`qci snapshot export ID --fixture PATH [--account ACCOUNT]` is offline. It redacts again,
replaces local IDs with placeholders, writes sorted plain JSON, and aborts without writing if
the text contains the saved account's token, instance or URL verbatim, or if anything outside
the provider payload matches a redaction rule.

## Storage (M0)

- SQLite through SQLAlchemy 2 Core, at `./.qci/qci.db` or `$QCI_HOME/qci.db`.
- The `runs` table has indexed columns for listing (`run_id`, `created_at`, `status`,
  `workload`, `backend_name`, `git_commit`, `schema_version`) plus `record_json`, the complete
  serialized Run.
- The `schema_meta` table records the database schema version.
- Insert-only. See [ADR 0003](adr/0003-immutable-run-records.md).
- Calibration snapshots (M1.3b) live in the same file, in `calibration_snapshots`,
  `snapshot_captures` and `calibration_measurements`, owned by `SqliteSnapshotRepository`.
  They record `snapshot_db_schema = 1` in `schema_meta`. The `runs` table and
  `DB_SCHEMA_VERSION` are untouched. See [ADR 0005](adr/0005-live-calibration-snapshots.md).

The document-plus-index-columns design keeps the Run model free to evolve. Columns are added
only for things the CLI needs to filter or sort on.

## Extension points (designed for, not built)

| Future capability | Where it plugs in |
|---|---|
| More providers or simulators | A new `adapters/<provider>/` implementing the same ports |
| Other compilers | Another `Compiler` implementation. `CompilationRecord` records the compiler name and version. |
| Blob archival (M0.5) | A new `BlobStore` port and `ContentRef` model, plus a schema version bump |
| Compare (M1, built) | `CompareService` over two stored Runs plus a provider `CalibrationReader` |
| Hosted storage | Another `RunRepository` implementation |
| Probes, prediction, routing | New services consuming stored runs and snapshots. These are deliberately not designed yet. |
| New run metrics | Append to `compute_metrics` in `services/run_service.py`. Each metric carries an `EvidenceKind`, a `method` and a `method_version`. |
| New comparison rules | Change `ComparisonPolicy` and bump `ComparisonPolicy.version`. The field is typed as a `Literal` (currently `"qci.compare.v3"`), so a bump is a type change: `mypy --strict` then flags every equality check against the old version string as a non-overlapping comparison, and every `ComparisonPolicy(version=<old string>)` as an argument-type error, because `[tool.pydantic-mypy] init_typed = true` types model constructors. `tests/test_typed_init.py` proves the constructor case; pydantic also rejects the value at runtime. mypy cannot detect a rule change made without a bump; making the bump is the author's responsibility under `CLAUDE.md`. |

## Technology

Python 3.12+, Pydantic v2, Typer, SQLAlchemy 2, Qiskit 2.x, qiskit-ibm-runtime fake backends,
qiskit-aer, pytest, Ruff and mypy in strict mode. There are no servers, queues or containers.
