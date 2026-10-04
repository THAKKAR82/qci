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
├── error: RunError | None           stage (resolve_backend|snapshot|compile|execute|metrics),
│                                    error_type (qualified), message (sanitized, truncated)
├── tags: dict[str, str]
├── workload: WorkloadSource
│     source_path, source_sha256, entrypoint, name
├── provenance
│     git: GitProvenance             commit, branch, dirty, remote (credentials stripped); all nullable
│     environment: EnvironmentProvenance
│                                    python_version, python_implementation, platform,
│                                    packages{name: version | None}, config_hash
├── logical_circuit: CircuitSummary  (always present: load failures are not recorded)
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
│     config: ExecutionConfig        shots, seed_simulator           (what was requested)
│     primitive, config_hash, started_at, finished_at, provider_job_id (what actually ran)
├── result: ExecutionResult | None
│     counts: dict[creg_name, dict[bitstring, int]], total_shots, provider_metadata: JSON
└── metrics: list[Metric]
      name, value, unit, kind: EvidenceKind, method, method_version, uncertainty (nullable)

CircuitSummary
  num_qubits, num_clbits, depth, size, op_counts (sorted), two_qubit_gate_count,
  two_qubit_edges (sorted list of qubit pairs), qasm3 (nullable), qasm3_error (nullable),
  exporter{name, version}
```

Fields after `logical_circuit` are nullable so that a failed run can keep everything captured
before the failure. A succeeded run must have all of them, which the model validates.

`CompileConfig` holds `optimization_level` and `seed_transpiler`. `ExecutionConfig` holds only
what was requested. The primitive that actually ran is recorded on `ExecutionRecord`.

For a transpiled circuit, `num_qubits` is the whole device, 127 for `fake_sherbrooke`. The
qubits actually used are visible through `layout` and `two_qubit_edges`, which use physical
indices. Logical-circuit edges use virtual indices.

### Raw payload encoding

Provider payloads are converted to JSON losslessly. Types JSON cannot represent are tagged:

| Python value | Stored as |
|---|---|
| `datetime` | `{"$datetime": "<ISO-8601 with offset>"}` |
| `complex` | `{"$complex": [real, imag]}` |
| non-finite float | `{"$float": "nan" \| "inf" \| "-inf"}` |
| tuple | list |

Any other non-JSON type raises an error and is never stringified or dropped. A Bell run on
`fake_sherbrooke` produces a record of about 560 KB, dominated by raw calibration data. This
motivates the M0.5 move to deduplicated blobs.

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
| `Comparison` (see below) | M1, built |
| `Regression` and baselines | after M1 |
| `Attribution` and `Evidence` (method, version, confidence, uncertainty) | later |
| Experiment grouping and repeated executions | later |
| Organizations, projects and users | when hosted or multi-user becomes real |
| Cost, validation and routing decisions | later |

## M1 Comparison (computed, never persisted)

Comparisons are directional: **baseline → candidate**. Every `delta` is candidate minus
baseline. All models live in `qci/domain/comparison.py`.

```
Comparison
├── schema_version: 1
├── comparison_id      hash_json({baseline_run_id, candidate_run_id, engine_version,
│                      observables_hash, policy_hash})
├── engine_version     "qci.compare.engine.4"
├── policy: ComparisonPolicy (version "qci.compare.v3", gate rules,
│                      distribution_null_resamples,
│                      sampling_floor_requires_distinct_simulator_seeds), policy_hash
├── baseline_run_id, candidate_run_id
├── status             overall ComparisonStatus
├── source / environment / logical_circuit / compilation / execution / backend
│                      explicit per-section models built from typed helpers:
│                      ValueComparison (exact, optional numeric delta), SetComparison,
│                      MappingComparison, CounterComparison
├── baseline_footprint, candidate_footprint: PhysicalFootprint
├── footprint: FootprintComparison
├── hardware: HardwareComparison
├── baseline_counts, candidate_counts    raw results, always shown when present
├── distribution: DistributionComparison (TVD, Hellinger distance as calculated Metrics;
│                      sampling_floor: SamplingFloor | null for TVD;
│                      sampling_floor_unavailable_reason: str | null)
├── observables: list[ObservableComparison], sorted by name; [] when none requested
│                      spec: ObservableSpec (name, kind "bitstring_set_probability",
│                        bitstrings sorted and unique, classical_register | null,
│                        bit_order "provider_counts_key")
│                      baseline / candidate: ObservableSide (k, n, estimate k/n calculated,
│                        Wilson 95% bounds statistical)
│                      difference: ObservableDifference (delta candidate minus baseline
│                        calculated, Newcombe 95% bounds statistical | null)
│                      difference_unavailable_reason: str | null
└── limitations        fixed text: no regression, improvement or causal claims
```

`observables_hash` is the canonical hash of the requested observables, sorted by name, so the
same request always gives the same `comparison_id` and a different request a different one.
Bitstrings are provider counts keys verbatim. For Qiskit, classical bit 0 is the rightmost
character. The Wilson and Newcombe functions in `qci/compare/proportions.py` take integer
(k, n) arguments only. Converting bitstring counts to (k, n) is a separate function in
`qci/compare/observables.py` (ADR 0006).

Observables follow the same shared-seed rule as the TVD sampling floor, under the same policy
flag. When both runs were simulated with the same non-null simulator seed, each run's estimate
and Wilson interval and the point delta are still reported, but the Newcombe bounds are null
and `difference_unavailable_reason` says why. The reason is null when the interval is computed
and when the gate failed. If a run has no counts in the register, the observable is
`unavailable`.

The output contains no generation timestamp, so the same two runs always produce byte-identical
JSON.

### Status vocabulary

| Status | Meaning |
|---|---|
| `unchanged` | Compared, and no difference found |
| `changed` | Compared, and a difference found. This is an observation, not a judgment. For result distributions it means the observed empirical distributions differ, not that the underlying probability distribution changed or that the difference is statistically significant. |
| `partially_comparable` | Some evidence compared, some not, for example when footprints differ |
| `not_comparable` | Both sides exist, but comparing them would be invalid, for example a dynamic circuit or a changed logical circuit |
| `unavailable` | Required evidence is missing on at least one side |

The words better, worse, regression and improvement are never used.

### PhysicalFootprint semantics

The footprint is extracted from the final transpiled OpenQASM 3, scanning top-level statements
only. See ADR 0004.

- `operations` lists each distinct (name, ordered physical qubits) with its count. Barriers are
  excluded. Measure, reset and delay are included.
- `qubits` is every physical qubit referenced by a non-barrier instruction. `measured_qubits` is
  the subset that is measured.
- `initial_layout[v]` is the physical qubit assigned to logical qubit v before routing.
  `final_layout[v]` is the physical qubit holding v's state at the end. The initial mapping,
  the executed operations and the final mapping are three distinct things.
- `status` is `unsupported_dynamic` for control flow, which is never flattened. It is
  `unavailable` when QASM3 is missing, unparseable or contains unsupported constructs.

### Hardware comparison rules

- `global_snapshot_changed` compares hashes of the whole raw provider payload, including unused
  hardware.
- Calibration is compared only for physical resources present on **both** sides: the same
  qubit, or the same operation name on the same ordered qubits. A value on one physical qubit is
  never compared with a value on a different qubit.
- **Definition.** "Relevant hardware" means calibration data associated with physical
  resources the workload actually used. It does not mean a parameter is known to affect
  workload performance, and a relevant calibration change is not a claim that it caused an
  observed result change.
- `relevant_hardware_changed` takes one of three values:
  - **true** if any shared, available parameter value differs.
  - **false** if the footprints are identical and every relevant value is available and equal.
  - **null** if the footprints differ, or if some relevant value is unavailable.
- Calibration date changes are listed separately from value changes.
- IBM `general` pairwise data uses ambiguous key encodings and is listed as excluded.

### Distribution comparability gate

TVD and Hellinger distance are computed only when all of these hold:
- Both runs succeeded with results.
- The logical OpenQASM 3 text is present and identical on both sides.
- The provider is the same.
- There is exactly one classical register, with the same name on both sides.
- Bitstring widths are equal.
- Neither circuit is dynamic.

Otherwise the status is `not_comparable` with every failing reason listed, or `unavailable` if a
result is missing, and the raw counts are still shown.

The metrics are defined as follows:
- `tvd = ½ Σ |p − q|`
- `hellinger_distance = sqrt(½ Σ (√p − √q)²)`. This is not Qiskit's `hellinger_fidelity`.

Both are empirical point estimates. Hellinger distance has no sampling floor.

When the gate passes, `sampling_floor` reports how large TVD is expected to be from sampling
alone, at the observed shot counts (`qci/compare/sampling.py`). H0 is that both runs sampled one
shared distribution, estimated by the pooled plug-in estimate. Each of B resamples
(`policy.distribution_null_resamples`, default 2000, minimum 100) draws each run at its own shot
count. The null TVD quantiles p50, p95 and p99 and the Monte Carlo p-value `(1 + #{null_tvd >=
observed_tvd - 1e-12}) / (B + 1)` are `statistical` Metrics. The p-value is itself a Monte Carlo
estimate: its `uncertainty` is the standard error `sqrt(p(1 − p) / (B + 1))` (p-value method
version 2). The seed is the leading 53 bits of the `comparison_id` digest, stored as a JSON
integer, and `rng` records the installed numpy version. `sampling_floor` is null for
`not_comparable` and `unavailable` distributions. It is also null when both runs executed on
simulator backends with the same non-null `seed_simulator` (policy
`sampling_floor_requires_distinct_simulator_seeds`, default true): the two samples are then
not independent, and the floor assumes independent samples. This holds whether or not the
compiled circuits differ. `sampling_floor_unavailable_reason` then says so. It is null whenever
the floor is computed and when the gate failed, since `reasons` already explains that case. The
floor is evidence, not a verdict, and always carries four caveats: it makes no causal claim;
the plug-in estimate cannot resample unobserved outcomes, so sparse floors are slightly
underestimated; it assumes i.i.d. shots within a run; and no multiple-comparison correction is
applied.

A `changed` distribution status, meaning a nonzero TVD or Hellinger distance, says only that
the **observed empirical** result distributions differ. It does not establish that the
underlying probability distribution changed, nor that the difference is statistically
significant. Seeded or repeated runs can differ by sampling noise alone.
