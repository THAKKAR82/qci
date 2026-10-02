# PLAN

**Current milestone: M1, compare two runs.**
**Status:** M0 is complete and committed. M1 is implemented and verified, and is awaiting
review before commit. M0.5 now follows M1 and has not started.

Milestones are strictly sequential. Do not build M1.x or M0.5 functionality while M1 is open.

---

## M0: Minimal instrumented run (DONE)

**Goal:** prove the full data path end to end with deliberately boring technology.

Success condition:

```bash
qci run examples/bell.py --backend fake_sherbrooke --seed 7   # creates a persisted Run
qci runs                                                      # lists it
qci show RUN_ID                                               # inspects it
```

### Scope

1. **Workload loading.** `examples/bell.py` defines `build() -> QuantumCircuit`, which is loaded
   from a file path with `importlib`. `--entrypoint` overrides the function name.
2. **Execution.** The circuit runs on `fake_sherbrooke` through Qiskit `SamplerV2`. `--seed`
   sets both `seed_transpiler` and `seed_simulator`. `--shots` defaults to 1000.
3. **Git provenance.** Commit, branch, dirty flag and remote with credentials stripped. Every
   field is null outside a git repository.
4. **Environment provenance.** Python version, platform and the versions of qci, qiskit,
   qiskit-ibm-runtime and qiskit-aer.
5. **Circuit summaries.** For both the logical and the transpiled circuit: qubit and clbit
   counts, depth, sorted op counts, two-qubit gate count, the two-qubit interaction edge list,
   OpenQASM 3 text where export succeeds, and exporter name and version. The transpiled
   circuit also records its layout when available.
6. **Backend.** Identity (provider, name, version, qubit count, simulator flag) and a snapshot
   with `source=static_fake`, capture time, calibration time, basis gates and coupling edges.
   The raw properties and configuration payloads are stored inline and verbatim.
7. **Execution record.** `ExecutionConfig` (shots, seeds, primitive, optimization level),
   start and finish times, and counts per classical register.
8. **Metrics.** Only `measured` values (shots, counts) and `calculated` values (circuit
   summaries), each labeled with an evidence kind, method and method version.
9. **Persistence.** An insert-only SQLite repository through SQLAlchemy 2 Core.
10. **CLI.** `qci run`, `qci runs`, `qci show RUN_ID [--json]`.
11. **Tests.** The six files listed under the file tree below.

### Explicitly excluded from M0

Blob store, QPY archival, ideal distributions, Hellinger fidelity, total variation distance
(TVD), golden fixtures, a contract-suite in-memory adapter, `compare`, project or organization
fields, Alembic, and `rich`.

### M0 file tree

```
src/qci/
  __init__.py
  domain/      run.py circuit.py backend.py execution.py metric.py provenance.py
  core/        ports.py hashing.py ids.py
  services/    run_service.py
  provenance/  git.py environment.py
  adapters/qiskit_ibm/  adapter.py summarize.py
  storage/     sqlite.py
  cli/         app.py
tests/
  test_hashing_ids.py   test_domain.py   test_storage.py
  test_architecture.py  test_run_service.py  test_cli_e2e.py
examples/bell.py
```

### M0 acceptance criteria

- [x] 1. `qci run examples/bell.py --backend fake_sherbrooke --seed 7` exits 0 and prints a run ID.
- [x] 2. `qci runs` lists the run with creation time, status, workload, backend and short git commit.
- [x] 3. `qci show RUN_ID` displays provenance, workload source hash, logical and transpiled
      summaries, compile config, the backend with snapshot source and calibration date,
      execution config, counts, and metrics with their evidence kind. `--json` emits the full record.
- [x] 4. Two runs with the same seed have identical counts, transpiled summaries, QASM text and
      config hashes. Only the run ID and timestamps differ.
- [x] 5. The stored record keeps the raw backend properties and configuration verbatim.
- [x] 6. The repository exposes no update or delete, and saving a duplicate run ID fails.
- [x] 7. An execution failure produces a persisted run with `status=failed` that `show` can display.
- [x] 8. `qci.domain` and `qci.core` import no qiskit, and a test enforces this.
- [x] 9. `ruff check`, `ruff format --check`, `mypy --strict src` and `pytest` pass offline,
      without IBM credentials.

### M0 implementation notes (2026-10-01)

- **Executor primitive.** The executor uses `qiskit.primitives.BackendSamplerV2` directly
  instead of `qiskit_ibm_runtime.SamplerV2`. The runtime class is deprecated as of
  qiskit-ibm-runtime 0.50. Its local testing mode delegates to `BackendSamplerV2` anyway, and
  the counts are identical. Its local mode also silently drops `seed_simulator=0`, which makes
  seed-0 runs non-deterministic. See D8.
- **Config field placement.** `optimization_level` lives in `CompileConfig`, not in
  `ExecutionConfig`. `primitive` lives in `ExecutionRecord` as what actually ran, not in
  `ExecutionConfig`, which holds only what was requested.
- **Raw payload encoding.** IBM payloads contain `datetime` and `complex` values. They are
  stored with explicit, lossless tags such as `{"$datetime": ...}` and `{"$complex": [re, im]}`.
  Unknown types raise an error and are never dropped.
- **Backend lookup.** Fake backends are looked up by class, so only the requested one is
  instantiated. `FakeProviderForBackendV2` instantiated all 68 and emitted unrelated warnings.
- **Record size.** A Bell run on `fake_sherbrooke` is about 560 KB, above the original 100 to
  300 KB estimate. Raw calibration data dominates the size. See D4.
- **Extra files beyond the planned tree.** `domain/base.py` holds the shared frozen base model.
  `core/errors.py` holds shared errors. `adapters/qiskit_ibm/jsonable.py` holds the payload
  encoder. `tests/conftest.py` holds Qiskit-free fixtures and the stub adapter.
- **Load failures.** A workload that fails to load records no run. The CLI exits with code 2.
  A failed run exits with code 1, and a successful run exits with code 0.

---

## M0.5: Archival and richer measurement (NEXT after M1, not started)

- A content-addressed blob store under `.qci/objects/`.
- Archival of raw QPY, QASM and provider payloads. Inline `provider_raw` moves to blob
  references, which requires a `schema_version` bump and an explicit upcast.
- Fuller provenance: complete installed-package list, diff hash and source snapshot.
- An ideal distribution by exact statevector for small circuits, plus Hellinger fidelity and
  TVD, all labeled `calculated` with method versions.
- Golden fixtures, serialization round-trip tests, and a provider contract suite run against
  both the Qiskit adapter and an in-memory adapter.

## M1: Compare two runs (CURRENT, implemented)

M1 answers "what changed between two immutable runs?" It does not answer whether anything
improved or regressed, or why it changed.

### Scope

1. **Directional command.** `qci compare BASELINE_RUN_ID CANDIDATE_RUN_ID [--json]`. Numeric
   deltas are always candidate minus baseline.
2. **Explicit semantic sections.** Source, environment, logical circuit, compilation,
   execution and backend identity are each compared over normalized fields. There is no
   generic JSON diff.
3. **Physical footprint per run.** It is derived from the stored transpiled OpenQASM 3. It
   holds the physical qubits, the measured qubits, the exact operations as name plus ordered
   physical qubits, and the initial and final layouts. See ADR 0004.
4. **Footprint comparison.** It lists common, baseline-only and candidate-only qubits and
   operations, and operation count changes.
5. **Hardware comparison.** The global snapshot change flag covers the whole raw payload.
   Calibration deltas are computed only for physical resources identical on both sides.
   `relevant_hardware_changed` is null whenever the footprints differ. "Relevant" means
   calibration of physical resources the workload actually used. It does not mean the
   parameter is known to affect performance, nor that a change caused a result change.
6. **Distribution comparison.** A `changed` status means the observed empirical distributions
   differ, not that the underlying distribution changed or that the difference is significant.
   TVD and Hellinger distance are computed as `calculated` point
   estimates, behind a conservative comparability gate.
7. **Policy and identity.** `ComparisonPolicy` is versioned as `qci.compare.v1`. The
   comparison ID is deterministic, and the output contains no generation timestamp.
8. **Read-only and unpersisted.** Comparisons are never written to the store.

### M1 acceptance criteria

- [x] 1. `qci compare A B` and `--json` work on existing M0 records without migration or mutation.
- [x] 2. Every user-facing name uses baseline and candidate. Deltas are candidate minus baseline.
- [x] 3. Same-seed Bell runs compare as `unchanged`, with TVD 0.
- [x] 4. Seed 7 versus seed 8 shows seed changes and an observed empirical distribution change
      with labeled TVD and Hellinger distance.
- [x] 5. A successful run compared with a failed run gives `partially_comparable` with
      unavailable sections and no crash.
- [x] 6. A calibration change on an unused qubit gives `global_snapshot_changed=true` and
      `relevant_hardware_changed=false`.
- [x] 7. A changed physical mapping gives `relevant_hardware_changed=null`. Only identical
      shared resources are compared, and different qubits are never compared as a temporal
      delta.
- [x] 8. Two `compare --json` invocations produce byte-identical output.
- [x] 9. The compare, core and domain code import no Qiskit, and a test enforces this.
- [x] 10. ruff, ruff format, `mypy --strict src tests` and offline pytest all pass.

### M1.x (deferred, not started)

Bootstrap TVD confidence intervals, chi-square and Monte Carlo tests, calibration coverage
summaries, FDR and multiple-register handling, role-aware highlighting of shared resources, and
run-time footprint capture.

## Beyond M1 (direction only, unplanned)

`qci test --baseline`, regression detection, evidence-based attribution, repeated executions
and experiment grouping, more providers, backend snapshot history, and research datasets.
See `docs/product.md`.

---

## Open decisions

None of these are settled. Each one should be resolved by an ADR when it becomes blocking.

| # | Question | Current position |
|---|---|---|
| D1 | What is the canonical identity of a circuit or workload? | Unresolved. M0 preserves the inputs and defines no identity. See `docs/data-model.md`. |
| D2 | Workload contract: `build()`, a decorator, or observe mode wrapping user code? | M0 uses `build()`. The rest is open. |
| D3 | What does "reproducible" mean? | A reconstructable record. Identical results are expected only for seeded simulators. |
| D4 | Should raw payloads stay inline or move to blobs? | Inline in M0, measured at about 560 KB per `fake_sherbrooke` run. Blobs in M0.5, where identical snapshots should also dedupe. |
| D5 | Project-local or user-global store? | Project-local `.qci/` with a `QCI_HOME` override. |
| D6 | Migration tooling? | Hand-rolled when the first migration exists. Alembic waits for hosted storage. |
| D7 | Multiple circuits, sweeps and repeated executions per run? | One circuit per run in M0. The modeling is open. |
| D8 | Why does `SamplerV2` warn on fake backends? | **Resolved.** It is a `DeprecationWarning` from qiskit-ibm-runtime 0.50. M0 uses `qiskit.primitives.BackendSamplerV2`. The client-side `executor_sampler.Sampler` targets IBM cloud execution and should be re-evaluated when live hardware is added. |
| D9 | Package manager? | pip and venv for now. uv may be adopted later. |
| D10 | How should backend snapshots be modeled over time, as history versus a point capture? | M0 stores a point capture per run. History modeling is open. |
| D11 | Should a workload that fails to load be recorded as a run? | M0 records nothing and exits with code 2. Open. |
| D12 | Transpiled summaries report all 127 device qubits. Should QCI also record the active qubit set? | **Resolved by M1.** The compare-time physical footprint lists exactly the referenced physical qubits. |
| D13 | Should the footprint be captured at run time from the native circuit? | Not in M1, which derives it from stored QASM3 per ADR 0004. Revisit with QPY in M0.5. |
| D14 | How should IBM `general` pairwise calibration (`jq_6272`, `zz_6272`) map to qubit pairs? | The key encoding is ambiguous, so the data is excluded from footprint scoping and reported as excluded. Open. |
| D15 | Should delay operations count as relevant hardware with unavailable calibration? | Yes in M1, conservatively. Delay has no provider calibration, so a footprint containing delays makes `relevant_hardware_changed` null. Open. |
| D16 | Should a numerical tolerance apply to calibration value equality? | No. M1 uses exact equality and reports raw deltas. Open. |
