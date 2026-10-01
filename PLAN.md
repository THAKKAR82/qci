# PLAN

**Current milestone: M0, the minimal instrumented run.**
**Status:** Phase A (docs and scaffold) is complete. M0 implementation has not started and
needs approval.

Milestones are strictly sequential. Do not build M0.5 or M1 functionality while M0 is open.

---

## M0: Minimal instrumented run (CURRENT)

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

- [ ] 1. `qci run examples/bell.py --backend fake_sherbrooke --seed 7` exits 0 and prints a run ID.
- [ ] 2. `qci runs` lists the run with creation time, status, workload, backend and short git commit.
- [ ] 3. `qci show RUN_ID` displays provenance, workload source hash, logical and transpiled
      summaries, compile config, the backend with snapshot source and calibration date,
      execution config, counts, and metrics with their evidence kind. `--json` emits the full record.
- [ ] 4. Two runs with the same seed have identical counts, transpiled summaries, QASM text and
      config hashes. Only the run ID and timestamps differ.
- [ ] 5. The stored record keeps the raw backend properties and configuration verbatim.
- [ ] 6. The repository exposes no update or delete, and saving a duplicate run ID fails.
- [ ] 7. An execution failure produces a persisted run with `status=failed` that `show` can display.
- [ ] 8. `qci.domain` and `qci.core` import no qiskit, and a test enforces this.
- [ ] 9. `ruff check`, `ruff format --check`, `mypy --strict src` and `pytest` pass offline,
      without IBM credentials.

---

## M0.5: Archival and richer measurement (NEXT, not started)

- A content-addressed blob store under `.qci/objects/`.
- Archival of raw QPY, QASM and provider payloads. Inline `provider_raw` moves to blob
  references, which requires a `schema_version` bump and an explicit upcast.
- Fuller provenance: complete installed-package list, diff hash and source snapshot.
- An ideal distribution by exact statevector for small circuits, plus Hellinger fidelity and
  TVD, all labeled `calculated` with method versions.
- Golden fixtures, serialization round-trip tests, and a provider contract suite run against
  both the Qiskit adapter and an in-memory adapter.

## M1: Compare two runs (LATER, not started)

- `qci compare RUN_A RUN_B` produces a per-dimension diff covering source, environment, compile
  config, transpiled structure, backend snapshot, execution config and metrics.
- Statistical tests on counts, labeled `statistical` with method and uncertainty.
- No attribution claims. M1 reports differences and their statistical significance only.

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
| D4 | Should raw payloads stay inline or move to blobs? | Inline in M0 at an estimated 100 to 300 KB per run. Blobs in M0.5. |
| D5 | Project-local or user-global store? | Project-local `.qci/` with a `QCI_HOME` override. |
| D6 | Migration tooling? | Hand-rolled when the first migration exists. Alembic waits for hosted storage. |
| D7 | Multiple circuits, sweeps and repeated executions per run? | One circuit per run in M0. The modeling is open. |
| D8 | Why does `SamplerV2` warn on fake backends? | To be investigated and documented during M0. |
| D9 | Package manager? | pip and venv for now. uv may be adopted later. |
| D10 | How should backend snapshots be modeled over time, as history versus a point capture? | M0 stores a point capture per run. History modeling is open. |
