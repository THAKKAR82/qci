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
services/       Use-case orchestration (RunService, CompareService, SnapshotService,
                SnapshotCompareService, RunSnapshotCompareService, BackfillService)
  │  depends on ports, never on adapters directly
compare/        Pure comparison logic over stored runs: provider-neutral; summary.py
  │             computes the calibration magnitudes of the text summary (R1)
core/           ports.py (Protocols), hashing.py, ids.py, selectors.py: pure Python
domain/         Pydantic models: pure data, no I/O, no provider SDKs
  ▲
adapters/       Provider implementations of the ports (qiskit_ibm/ first)
storage/        Run and snapshot repository implementations (sqlite first), and
                location.py: where the store lives (R1)
provenance/     Git and environment collectors: plain Python
```

**Dependency rule:** the layers form a strict DAG: `domain` ← `core` ← `compare` ←
`services` ← `cli`. `domain` depends on nothing in QCI. `core` depends only on `domain`.
`compare` depends on `core` and `domain`. `services` depends on `compare`, `core`, `domain`
and `provenance`. Adapters, storage and provenance implement or supply `core` interfaces and
depend only on `core` and `domain`. The CLI wires concrete implementations together: it
imports `services` and `storage`, and imports adapters lazily inside the command that needs
them. The exception is `adapters/qiskit_ibm/live.py`, which the CLI imports at module level
for the default account name, and `adapters/qiskit_ibm/extra.py`, which checks for the `ibm`
extra with `importlib.util.find_spec` (R1). Neither imports a provider SDK at module level:
`live.py` imports `qiskit_ibm_runtime` only when it builds the client or lists saved account
names, and `tests/test_architecture.py` checks that importing either loads no provider SDK.

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
| `SnapshotResourceIndex` (M1.3c) | For one provider's stored snapshots: build a `BackendSnapshot` view from the stored configuration, and list the footprint resources a snapshot's device does not have. |
| `SnapshotComparisonSupport` (M1.3c) | A dataclass bundling one provider's `CalibrationReader`, `SnapshotResourceIndex` and explicit error-type parameter list. |
| `FakeDeviceIndex` (M1.4b) | For one provider's fake backends: the device a fake was built from, from an explicit list (IBM: `FAKE_DEVICE_SOURCES`), never derived from the fake's name; the device name and version a run's stored payload records; and the footprint resources a run's stored configuration does not have. |
| `RunSnapshotComparisonSupport` (M1.4b) | A dataclass bundling one provider's `SnapshotComparisonSupport`, its `FakeDeviceIndex`, the name of the mapping list, and the package whose fakes hold the frozen calibration. |
| `SnapshotRepository` (M1.3b) | Insert-only snapshot persistence with `save` (deduplicates by content hash and always adds a capture row), `get`, `get_by_hash`, `list_snapshots`, `measurements`, `captures` and `lookup_times` (M1.5c: the `requested_before` of every stored historical lookup of a backend). It has no update or delete. |
| `HistoricalCalibrationSource`, `HistoricalLookup` (M1.5c) | One provider's historical lookups: an explicit list of verified lookup depths per device, and `open(NAME)`, which resolves the device and rejects fakes and simulators. `lookup(requested_before)` makes one request, never retries, and raises `TooManyRequestsError` at the first too-many-requests response. |

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
| `qci run`, `qci snapshot capture`, `qci snapshot backfill`, `qci snapshot export` | 2 | The `ibm` extra is missing (`this command needs the ibm extra: pip install 'bloq-qci[ibm]'`). Checked first: no store is opened or created and no workload is loaded. |
| `qci show`, `qci compare` | 1 | A run ID or selector matches nothing, or a selector is ambiguous (candidates listed). |
| `qci show`, `qci compare`, `qci snapshot show`, `qci snapshot export`, `qci snapshot compare`, `qci snapshot compare-run` | 2 | A selector is malformed: text that is not a stored ID and is shorter than 8 characters, `~` without an integer of 1 or more, a snapshot `latest` without `BACKEND:`, or anything else that fits no form. |
| `qci compare` | 2 | An `--observable` argument is invalid. |
| `qci snapshot capture` | 0 | A snapshot was stored, or identical content was recorded as one more capture. |
| `qci snapshot capture` | 1 | Capture failed. **Nothing was persisted.** The message is sanitized. |
| `qci snapshot capture` | 2 | The backend is a fake (`fake_*` or a fake object) or a simulator. **Nothing was persisted.** |
| `qci snapshot backfill` | 0 | Every requested lookup was stored, or nothing was pending. Grid times left by `--max-requests` are printed as remaining. |
| `qci snapshot backfill` | 1 | A request failed, including the first too-many-requests response, or a returned document has no date or is dated after its requested time. Nothing is retried; lookups stored before the error are kept. |
| `qci snapshot backfill` | 2 | The backend is a fake or a simulator, has no verified lookup depth, or `--days` exceeds it; or an option is out of range. **Nothing was requested.** |
| `qci snapshot compare` | 1 | A snapshot or the footprint run matches nothing, or a selector is ambiguous. Nothing is stored. |
| `qci snapshot compare-run` | 1 | The run or the snapshot matches nothing, or a selector is ambiguous. Nothing is stored. |
| `qci snapshot show`, `qci snapshot export` | 1 | A snapshot matches nothing or a selector is ambiguous, the saved account could not be read for the export scan, or the export was unsafe or holds historical lookup data. Export writes nothing. |
| `qci where` | 0 | Always. It prints the path and opens nothing. |
| `qci doctor` | 0 | No check reports `problem`; notes are allowed. Nothing is written. |
| `qci doctor` | 1 | At least one check reports `problem`. Nothing is written. |
| `qci runs`, `qci show`, `qci compare`, `qci snapshots`, `qci snapshot show`, `qci snapshot export`, `qci snapshot compare`, `qci snapshot compare-run` | 1 | The store is damaged (`DamagedStoreError`) or has another schema version. Nothing is written. (`qci doctor` reports these as a `problem` line instead.) |
| any | 1 | Any other `QCIError` that reaches `main()`. |
| any | 2 | A usage error reported by Typer. |

A selector that is not the full ID is echoed on stderr as `<role>: <selector> -> <ID>`, and
the `./.qci` note (below) goes to stderr too, so stdout and exit codes never depend on either.
`qci run` prints the run ID to stdout before the error, which goes to stderr. `qci snapshot
capture` prints the snapshot ID to stdout and its details to stderr. `qci snapshot backfill`
prints one line per stored lookup to stdout (requested time, snapshot ID, returned stamp, new
or existing) and its counts and errors to stderr.

## R1: store location, extras, selectors and the summary

Designed in [ADR 0009](adr/0009-packaging-and-first-run.md). Packaging, store location and
presentation only: comparison rules, record schemas and JSON output are unchanged.

- **Distribution and extras.** The distribution is `bloq-qci`; the import package and the
  command stay `qci`. The core install (`pydantic`, `typer`, `sqlalchemy`, `numpy`,
  `openqasm3[parser]`) lists, shows and compares stored runs and snapshots, and runs
  `qci where` and `qci doctor`. The `ibm` extra (`qiskit`, `qiskit-ibm-runtime` below 0.51,
  `qiskit-aer`) is needed by `qci run`, `qci snapshot capture`, `qci snapshot backfill` and
  `qci snapshot export`, which check for it first (`adapters/qiskit_ibm/extra.py`) and exit 2
  without it. `tests/test_ibm_extra.py` runs every command in a subprocess with the three SDKs
  blocked.
- **Store location** (`storage/location.py`). `$QCI_HOME/qci.db` when `QCI_HOME` is set and
  non-empty; otherwise a per-user directory: `~/Library/Application Support/qci` on macOS,
  `%LOCALAPPDATA%\qci` (or `~\AppData\Local\qci`) on Windows, and `$XDG_DATA_HOME/qci` (only
  when absolute) or `~/.local/share/qci` elsewhere. Standard library only. Write commands
  create the directory, with mode `0o700` on POSIX; read-only commands never create it.
- **`qci where`** prints the absolute `qci.db` path alone on stdout, and on stderr its source
  (`QCI_HOME` or the per-user default) and whether the file exists. It opens nothing.
- **The `./.qci` note.** When `QCI_HOME` is unset and `./.qci/qci.db` is a file in the
  current directory (never a parent), every command prints a note on stderr, once, from the
  Typer callback, with the exact `export QCI_HOME=...` line. The path is double-quoted, or
  `shlex.quote`d when it contains a character a shell expands inside double quotes. Only
  `Path.is_file` touches that file; QCI never moves, copies, links or merges a store.
- **`qci doctor`** (`cli/doctor.py`) reports one `ok`, `note` or `problem` line per check:
  Python version, `bloq-qci` version against `qci.__version__`, core dependencies, the `ibm`
  extra, the saved account (by name only), and the health of the store `qci where` names, for
  runs and snapshots separately, plus a legacy `./.qci` store as a note. Stores are summarized
  read-only (`run_store_summary`, `snapshot_store_summary`, SQLite `mode=ro`). The account
  check calls `AccountManager.list()` only when the account file exists, because `list()`
  creates an empty file when there is none; it uses only the returned names, and on an error
  prints only the exception type. All inputs are injected (`DoctorInputs`).
- **Selectors** (`core/selectors.py`). `ID | PREFIX | [BACKEND:]latest[~N]`, resolved by a pure
  function over the `(id, backend, sort_key)` lists that `list_runs` and `list_snapshots`
  return: no SQL, no provider import (`tests/test_architecture.py`). An argument equal to a
  stored ID selects it, whatever its length. Runs are ordered by `run_id` descending (creation
  order; every status); snapshots by `calibrated_at` descending, with `BACKEND:` required and
  undated snapshots never selected. Two runs in one millisecond, or two snapshots with one
  `calibrated_at`, at the selected position are ambiguous: exit 1 with the candidates (at most
  10, then a count). The CLI resolves selectors on the read-only repositories before calling
  any service.
- **Summary-first text.** `qci compare`, `qci snapshot compare` and `qci snapshot compare-run`
  print `cli/render_summary.py`'s summary by default; `--verbose` prints the summary, a blank
  line, then the full text of the existing renderers unchanged; `--json` is unaffected by
  `--verbose`. The calibration magnitudes come from `compare/summary.py`: per resource type,
  parameter name and unit, counts compared and changed, median and largest `|delta|`, median
  and largest relative delta (`|delta| / |baseline|`), each a `CALCULATED` `Metric`
  (`qci.summary.magnitude`, version 1), computed on the text path only and never persisted. A
  baseline of 0, an unavailable value, a text value and a unit difference are counted, never
  entered as 0. `tests/golden/cli/` pins the JSON, the summary and the full text of each case.

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
qci compare BASELINE CANDIDATE [--json] [--verbose] [--observable NAME=BITS,...]
  CLI: resolve both selectors on the read-only repository (R1)
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
  0. check the snapshot store read-only                 → exit 1 if damaged or another version
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
`AccountManager.get`, `AccountManager.list` and network connections, and every test runs with
a fresh empty `HOME`.

`qci snapshot export ID --fixture PATH [--account ACCOUNT]` is offline. It redacts again,
replaces local IDs with placeholders, writes sorted plain JSON, and aborts without writing if
the text contains the saved account's token, instance or URL verbatim, or if anything outside
the provider payload matches a redaction rule. It also refuses a snapshot whose source or any
capture is a historical lookup: backfilled data stays in the local store (ADR 0008, D29).

## M1.5c historical backfill flow

Read-only on hardware. The only networked command besides `qci snapshot capture`. See
[ADR 0008](adr/0008-historical-backfill.md).

```
qci snapshot backfill --backend NAME --days N [--step-hours H] [--max-requests M] [--pause S]
                      [--account ACCOUNT]
  0. open the snapshot store read-only                  → exit 1 if damaged or another version
  1. fake_* name, no verified depth, or N > depth       → exit 2, no client built
  2. grid: multiples of H hours since the epoch (UTC), from the latest midnight back to at most
     N days before now, newest first; drop times already stored as lookups
  3. nothing pending                                    → exit 0, no client built
  4. QiskitRuntimeService(name=ACCOUNT); service.backend → reject fakes and simulators (exit 2)
  5. open the store for writing                         → upcast a version 1 store to version 2
  6. per pending time, at most M: pause S seconds; properties(datetime=<UTC, zero offset>)
     → stamp missing or after the requested time: store nothing, exit 1
     → too-many-requests (HTTP 429 or IBM code 1202): stop, exit 1, nothing retried
     → else SnapshotService.record in its own transaction (configuration: null)
  7. print requested and remaining counts
```

Backfilled history is documents by provider stamp time, not what a user would have seen at a
given time: a document stamped before a requested time can have been published after it
(ADR 0008 Findings). The grid recovers neither documents superseded between grid times nor
any configuration history. The IBM client's own HTTP session retries some 5xx responses (up
to 5 times, with backoff); QCI adds no retries. The verified depths are an explicit list in
`adapters/qiskit_ibm/historical.py` (365 days for `ibm_fez`, `ibm_kingston` and
`ibm_marrakesh`).

## M1.3c snapshot comparison flow

Offline and read-only. See ADR 0005, section 7.

```
qci snapshot compare BASE CAND --footprint-run RUN [--allow-footprint-backend-mismatch]
                     [--json] [--verbose]
  0. resolve the three selectors (R1)                    → exit 1 no match or ambiguous, 2 malformed
  1. load both snapshots and the run                     → exit 1 if an ID is unknown
  2. different provider or backend                       → not_comparable, no parameters
  3. footprint_for_run(RUN) not available                → not_comparable (dynamic) or unavailable
  4. run backend != snapshot backend, no flag            → not_comparable, both backends named
  5. with the flag: SnapshotResourceIndex.missing_resources on each snapshot
                                                         → not_comparable if anything is missing
  6. compare_calibration(..., require_matching_units=True)
  7. label unchanged values by measurement date; list error-type values equal to 1
```

`compare_calibration` is the calibration core shared with run comparison. `compare_hardware`
calls it without `require_matching_units`, so run comparison output is unchanged, which the
golden files in `tests/golden/compare/` pin byte for byte.

## M1.4b run-to-snapshot comparison flow

Offline and read-only. See ADR 0007. The baseline is a stored run on a fake backend, and its
stored `BackendSnapshot` is the baseline calibration. The candidate is a stored live snapshot.

```
qci snapshot compare-run RUN SNAPSHOT [--json] [--verbose]
  0. resolve both selectors (R1)                         → exit 1 no match or ambiguous, 2 malformed
  1. load the run and the snapshot                       → exit 1 if an ID is unknown
  2. ordered exits, none with parameter comparisons:
     run has no backend or backend snapshot              → unavailable
     run snapshot source not static_fake                 → not_comparable
     snapshot source not live_calibration                → not_comparable
     providers differ                                    → not_comparable
     no RunSnapshotComparisonSupport for the provider    → unavailable
     FakeDeviceIndex.device_for(run backend) is None     → not_comparable (no name is derived)
     snapshot backend != mapped device                   → not_comparable
     run's recorded payload device != mapped device      → not_comparable
     footprint_for_run(RUN) not available                → not_comparable (dynamic) or unavailable
     footprint resource missing on either side           → not_comparable, listed per side
  3. compare_calibration(run snapshot, snapshot view, footprint, footprint,
                         require_matching_units=True)
  4. parameters on one side, unit differences, error-type values equal to 1, and
     measurement dates with live-minus-fake differences (calculated)
```

`compare_calibration`, `missing_resources` and `error_values_at_one` are reused unchanged, so
`qci compare` and `qci snapshot compare` output is unchanged. The run's
`backend_snapshot.captured_at` is when QCI read the fake, not a calibration date, and is never
used.

## Storage (M0)

- SQLite through SQLAlchemy 2 Core, at `$QCI_HOME/qci.db` or the per-user default (R1,
  above; before R1 the default was `./.qci/qci.db`).
- The `runs` table has indexed columns for listing (`run_id`, `created_at`, `status`,
  `workload`, `backend_name`, `git_commit`, `schema_version`) plus `record_json`, the complete
  serialized Run.
- The `schema_meta` table records the database schema version.
- Insert-only. See [ADR 0003](adr/0003-immutable-run-records.md).
- Calibration snapshots (M1.3b) live in the same file, in `calibration_snapshots`,
  `snapshot_captures` and `calibration_measurements`, owned by `SqliteSnapshotRepository`.
  They record `snapshot_db_schema` in `schema_meta`. The `runs` table and
  `DB_SCHEMA_VERSION` are untouched. See [ADR 0005](adr/0005-live-calibration-snapshots.md).
- Snapshot DB schema 2 (M1.5c, [ADR 0008](adr/0008-historical-backfill.md) section 3) adds
  `snapshot_lookups` (`capture_id`, `requested_before`, `method_version`): one row per
  historical lookup capture; a capture without a row is a live capture. Opening a version 1
  store for writing upcasts it in one transaction, creating the table and recording version 2
  and changing no other row. A read-only command on a version 1 store reads every capture as
  live and writes nothing. Store checks accept exactly the version 1 table set (three tables)
  with version 1 and the version 2 set (four) with version 2; any other set is
  `DamagedStoreError`.
- Commands that only read (`qci runs`, `qci show`, `qci compare`, `qci snapshots`,
  `qci snapshot show`, `qci snapshot export`, `qci snapshot compare`,
  `qci snapshot compare-run` and `qci doctor`) open their stores with `read_only=True`, and
  `qci where` opens nothing. SQLite then opens the file with `mode=ro`, so these
  commands never create the file, a table or a `schema_meta` row. A missing file, or a file
  with none of a store's tables, reads as an empty store, so the result is "No runs recorded
  yet.", "No snapshots recorded yet." or an unknown-ID error. A damaged store is an error,
  never empty: some but not all of a store's tables, or its tables without the `schema_meta`
  table or its version row (`db_schema` for runs, `snapshot_db_schema` for snapshots), raise
  `DamagedStoreError` naming what is missing, and the command exits 1. Detection only reads.
- Write commands use the same check before writing anything. Opening a writable repository
  first inspects the store read-only: an empty store gets its tables and version row as
  before, while a damaged or other-version store raises with nothing written. `qci run` opens
  its repository before `RunService.run`, so the check precedes loading the workload and
  creating any run record, succeeded or failed. `qci snapshot capture` and `qci snapshot
  backfill` check the snapshot store read-only before building the client, and again when
  they open the store to save.
  The check is per store: damage to the snapshot store does not block `qci run`, and damage
  to the run store does not block capture. A write through a read-only repository
  raises `ReadOnlyStoreError`.

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
