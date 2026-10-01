# Architecture

QCI is a modular monolith: one Python package with enforced internal boundaries. Provider SDKs
appear only inside adapters. See [ADR 0001](adr/0001-modular-monolith.md) and
[ADR 0002](adr/0002-provider-abstraction.md).

## Layers

```
cli/            Typer commands: argument parsing and rendering only
  │
services/       Use-case orchestration (RunService; later CompareService)
  │  depends on ports, never on adapters directly
core/           ports.py (Protocols), hashing.py, ids.py: pure Python
domain/         Pydantic models: pure data, no I/O, no provider SDKs
  ▲
adapters/       Provider implementations of the ports (qiskit_ibm/ first)
storage/        RunRepository implementations (sqlite first)
provenance/     Git and environment collectors: plain Python
```

**Dependency rule:** `domain` depends on nothing in QCI. `core` depends only on `domain`.
`services` depends on `core` and `domain`. Adapters, storage and provenance implement or
supply `core` interfaces. The CLI wires concrete implementations together.

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

### Why opaque handles

Compilation and execution need the provider's native objects, such as a Qiskit
`QuantumCircuit` and a `BackendV2`. The service passes these between ports of the *same*
adapter as `object`. The domain only ever sees normalized summaries plus raw payloads
serialized to JSON. This keeps SDK types out of the domain without forcing a premature
universal intermediate representation for circuits.

## M0 data flow

```
qci run PATH --backend NAME --seed S
  1. provenance: collect git + environment             (never fails the run; nulls allowed)
  2. loader.load(PATH, entrypoint)                     → WorkloadSource + native circuit
  3. catalog.resolve(NAME); catalog.snapshot(handle)   → Backend + BackendSnapshot (raw kept)
  4. compiler.compile(native, handle, CompileConfig)   → CompilationRecord (+ native compiled)
  5. executor.execute(compiled, handle, ExecConfig)    → ExecutionResult (counts)
  6. metrics: label measured and calculated values     → [Metric]
  7. assemble the immutable Run (status=succeeded | failed) and insert it in one transaction
```

If any step from 3 onward raises, the service still persists a Run with `status=failed`. That
run records the failing stage, the error type and message, and everything captured before the
failure. If the workload itself cannot be loaded in step 2, M0 reports the error and persists
nothing. Whether load failures should also become runs is an open question.

## Storage (M0)

- SQLite through SQLAlchemy 2 Core, at `./.qci/qci.db` or `$QCI_HOME/qci.db`.
- The `runs` table has indexed columns for listing (`run_id`, `created_at`, `status`,
  `workload`, `backend_name`, `git_commit`, `schema_version`) plus `record_json`, the complete
  serialized Run.
- The `schema_meta` table records the database schema version.
- Insert-only. See [ADR 0003](adr/0003-immutable-run-records.md).

The document-plus-index-columns design keeps the Run model free to evolve. Columns are added
only for things the CLI needs to filter or sort on.

## Extension points (designed for, not built)

| Future capability | Where it plugs in |
|---|---|
| More providers or simulators | A new `adapters/<provider>/` implementing the same ports |
| Other compilers | Another `Compiler` implementation. `CompilationRecord` records the compiler name and version. |
| Blob archival (M0.5) | A new `BlobStore` port and `ContentRef` model, plus a schema version bump |
| Compare (M1) | `CompareService` over two stored Runs, which needs no adapter |
| Hosted storage | Another `RunRepository` implementation |
| Probes, prediction, routing | New services consuming stored runs and snapshots. These are deliberately not designed yet. |

## Technology

Python 3.12+, Pydantic v2, Typer, SQLAlchemy 2, Qiskit 2.x, qiskit-ibm-runtime fake backends,
qiskit-aer, pytest, Ruff and mypy in strict mode. There are no servers, queues or containers.
