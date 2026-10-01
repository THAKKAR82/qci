# Data model

This document describes the **M0** run record. It also marks which concepts are deliberately
deferred and which questions are still open.

## Principles

- **Immutable.** A Run is written once. Corrections are new records, never edits.
- **Normalized plus raw.** QCI keeps the fields it understands *and* the provider's raw
  payload. Nothing is dropped because the normalized model ignores it.
- **Versioned.** Every record carries `schema_version`. Readers upcast older versions with
  explicit, tested functions.
- **Epistemically labeled.** Every metric states how it was obtained.
- **No speculative fields.** Fields are added when a real requirement exists, with an explicit
  migration. Tags are the exception because they are useful immediately.

## M0 Run record

All models are Pydantic v2 with `frozen=True` and `extra="forbid"`. Timestamps are UTC and
timezone-aware.

```
Run
├── run_id: str                      time-sortable, random (ULID-style)
├── schema_version: int = 1
├── qci_version: str
├── created_at: datetime
├── status: succeeded | failed
├── error: RunError | None           stage, error_type, message
├── tags: dict[str, str]
├── workload: WorkloadSource
│     source_path, source_sha256, entrypoint, name
├── provenance
│     git: GitProvenance             commit, branch, dirty, remote (credentials stripped); all nullable
│     environment: EnvironmentProvenance
│                                    python_version, platform, packages{name: version}, config_hash
├── logical_circuit: CircuitSummary | None
├── compilation: CompilationRecord | None
│     compiler{name, version}, config: CompileConfig, config_hash,
│     output: CircuitSummary, layout (initial/final index layout, nullable), duration_ms
├── backend: Backend | None
│     provider, name, version, num_qubits, is_simulator
├── backend_snapshot: BackendSnapshot | None
│     source: live_calibration | static_fake | simulator_ideal
│     captured_at, calibrated_at (nullable), basis_gates, coupling_edges,
│     provider_raw: {properties: JSON, configuration: JSON}   (verbatim)
├── execution: ExecutionRecord | None
│     config: ExecutionConfig        shots, seed_simulator, primitive, optimization_level
│     config_hash, started_at, finished_at, provider_job_id (nullable)
├── result: ExecutionResult | None
│     counts: dict[creg_name, dict[bitstring, int]], total_shots, provider_metadata: JSON
└── metrics: list[Metric]
      name, value, unit, kind: EvidenceKind, method, method_version, uncertainty (nullable)

CircuitSummary
  num_qubits, num_clbits, depth, op_counts (sorted), two_qubit_gate_count,
  two_qubit_edges (sorted list of qubit pairs), qasm3 (nullable), qasm3_error (nullable),
  exporter{name, version}
```

Fields after `provenance` are nullable so that a failed run can keep everything captured
before the failure.

### Backend snapshot semantics

`captured_at` is when QCI read the data. `calibrated_at` is when the provider says the
calibration was taken. For fake backends these differ greatly. `FakeSherbrooke` reports a
calibration date of 2025-02-26, frozen in the package. That is why `source=static_fake` is
explicit. A static fake snapshot must never be mistaken for live hardware state.

### EvidenceKind

| Kind | Meaning | First used |
|---|---|---|
| `measured` | Directly observed: counts, shots, timings | M0 |
| `calculated` | Deterministically derived from measured or recorded data: depth, gate counts, later fidelity against an ideal | M0 |
| `heuristic` | A rule of thumb without statistical guarantees | later |
| `statistical` | An estimate with stated uncertainty from a named test or estimator | M1 |
| `model_prediction` | The output of a learned or analytical predictive model | later |
| `causal_claim` | A claim that X caused Y, which requires explicit evidence and method | later |

## Identity and hashing (provisional)

**Circuit and workload identity is an unresolved research and architecture question.** M0
deliberately defines no canonical circuit ID or workload ID.

Why it is hard:
- OpenQASM 3 text is deterministic for a fixed Qiskit version, but the exporter can change
  between releases. It also encodes incidental choices such as register names and gate
  definitions.
- QPY is a faithful archival format, but its binary format is versioned per release (format
  17 in Qiskit 2.5), so its bytes are unstable across versions.
- The same logical intent can be expressed by different circuits. Whether two circuits that
  are equivalent up to qubit relabeling are "the same workload" depends on the question asked.
- Parameterized circuits and sweeps complicate identity further.

M0 therefore preserves the *inputs* to any future identity scheme:
- the workload source file SHA-256 and entrypoint
- OpenQASM 3 text for the logical and transpiled circuits, with exporter name and version
- the structural summary: counts, depth, op counts and two-qubit edges
- QPY archival, added in M0.5

M0 also computes **convenience hashes**: SHA-256 over canonical JSON for `CompileConfig`,
`ExecutionConfig` and the environment. These help spot "same config?" quickly. They are
explicitly *not* identities, and their canonicalization may change with a schema version.

Canonical JSON means sorted keys, UTF-8, no insignificant whitespace, and no NaN or Infinity.

**Run identity** is not content-based. A run is an event, so `run_id` is random and
time-sortable.

## Schema evolution

- `schema_version` starts at 1.
- A breaking change bumps the version and adds an upcast function from the previous version.
  Stored records are never rewritten.
- The first planned bump is M0.5, which moves `provider_raw` and QASM text to content-addressed
  blobs referenced by `ContentRef`.

## Deferred concepts (not modeled in M0)

These appear in the product vision. They will be modeled when a milestone needs them, with an
explicit migration.

| Concept | Expected milestone |
|---|---|
| `ContentRef` and blob store | M0.5 |
| Ideal distribution, Hellinger fidelity, TVD metrics | M0.5 |
| `Comparison` and per-dimension `Difference` | M1 |
| `Regression` and baselines | after M1 |
| `Attribution` and `Evidence` (method, version, confidence, uncertainty) | later |
| Experiment grouping and repeated executions | later |
| Organizations, projects and users | when hosted or multi-user becomes real |
| Cost, validation and routing decisions | later |
