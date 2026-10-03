# PLAN

**Current milestone: M1.1, sampling floor for TVD. Next sub-step: M1.1a.**
**Status:** M0 and M1 are complete and committed (`f722eb9`, `07856e0`). Independent seeds
(`80cfe02`) and the GHZ-star workload (`48638a5`) are committed.

Milestones and sub-steps are strictly sequential: M1.1a, M1.1b, M1.1v, M1.2, M1.3a, M1.3b,
M1.3c. Do not build a later step, or anything in the deferred backlog, while an earlier one is
open. Each step follows the step workflow in `CLAUDE.md`.

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
   sets both `seed_transpiler` and `seed_simulator`. `--shots` defaults to 1000. Independent
   per-stage seeds were added after M1. See "Experimental control: independent seeds".
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

## Experimental control: independent seeds (after M1, implemented)

This separates compilation variation from sampling variation. It is a CLI-only change, because
the Run schema already stores `CompileConfig.seed_transpiler` and `ExecutionConfig.seed_simulator`
separately.

- **New flags.** `--seed-transpiler N` and `--seed-simulator N`.
- **Shorthand kept.** `--seed N` still seeds both stages.
- **Precedence per stage.** The specific flag wins, then `--seed`, then unseeded. A seed of 0
  is a real seed.
- **Compare.** `qci compare` reports a transpiler-seed change under compilation and a
  simulator-seed change under execution.

## M1: Compare two runs (DONE)

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

## Pivot rationale (2026-10)

- **Fake backends cannot drift.** Their calibration is static, so they are QCI's offline test
  harness, not its first product environment.
- **Sampling variation is computed, not rerun.** On a fake backend, repeated runs differ only
  by multinomial sampling. Sampling variation is therefore computed from recorded counts.
  Repeated real-hardware runs are needed only for temporal (run-to-run) variation.
- **Full-distribution TVD is a weak primary metric.** It is dominated by rare error outcomes.
  M2 will need workload-specific observables.
- **First real-world evidence costs nothing.** It comes from read-only live calibration
  snapshots, at zero QPU cost, before any paid hardware execution.

## M1.1: Sampling floor for TVD (CURRENT)

**Goal:** report how large TVD is expected to be from sampling alone, at the observed shot
counts. It reports evidence. It does not decide whether a change is meaningful; that is M2.

### Scope

1. **Pure module `qci/compare/sampling.py`,** with no provider SDK imports.
   - **H0:** both runs sampled one shared distribution. The pooled estimate is the merged
     counts divided by the merged total. Outcomes are ordered lexicographically for
     determinism.
   - **Resampling:** for each of B resamples, draw multinomial(n_baseline, pooled) and
     multinomial(n_candidate, pooled), normalize, and compute TVD with the existing
     `total_variation_distance`.
   - **Outputs:** null quantiles p50, p95 and p99 using `numpy.quantile(method="linear")`, and
     the Monte Carlo p-value `(1 + #{null_tvd >= observed_tvd - 1e-12}) / (B + 1)`.
   - **RNG:** `numpy.random.Generator(numpy.random.PCG64(seed))`. The seed is derived
     deterministically from `comparison_id` by a documented function.
2. **Domain model.** A `SamplingFloor` model stored at `DistributionComparison.sampling_floor`.
   It is null whenever the existing comparability gate fails or the distribution comparison is
   unavailable. Every number is a `Metric` with `EvidenceKind.STATISTICAL`, a method and a
   method version. Fields: method, method_version, rng (including the installed numpy
   version), seed, resamples, null quantile metrics, p_value metric and caveats.
3. **Caveats, always emitted:**
   - (a) It tests only whether the two observed samples are consistent with one shared
     distribution at these shot counts. It makes no causal claim.
   - (b) The pooled plug-in estimate cannot resample outcomes never observed, so the floor is
     slightly underestimated for sparse distributions.
   - (c) It assumes shots within each run are independent and identically distributed. Drift
     within a job on real hardware violates this.
   - (d) No multiple-comparison correction is applied.
4. **Policy and engine version.** `ComparisonPolicy` version becomes `qci.compare.v2` and adds
   `distribution_null_resamples: int = 2000`, with a minimum of 100. `ENGINE_VERSION` becomes
   `qci.compare.engine.2`. Comparisons are not persisted, so no upcast is needed.
5. **Vocabulary.** The status vocabulary is unchanged. Output must never say significant,
   regression, improvement, better, worse, real change, PASS or FAIL. Update `LIMITATIONS` to
   say that TVD now has a sampling floor and that Hellinger distance still has none.
6. **CLI.** The text renderer shows the floor beside TVD.
7. **Dependency.** numpy becomes an explicit dependency in `pyproject.toml`.

**Out of scope:** a Hellinger floor, chi-square tests, thresholds or verdicts, and multiple
registers.

### M1.1 sub-steps

Each sub-step is reviewed and merged separately, in this order.

- **M1.1a, statistics core.** Branch: `feat/m1.1a-sampling-core`.
  - Scope items 1 and 7 only: the pure `qci/compare/sampling.py` module, the
    `comparison_id`-to-seed derivation function, and the explicit numpy dependency.
  - Every acceptance-criterion unit test that exercises the module directly: identical counts,
    strongly different samples, unequal shots, determinism, false-positive calibration and
    power.
  - No domain, policy, compare-service, CLI or renderer changes.
- **M1.1b, wiring.** Branch: `feat/m1.1b-sampling-floor`.
  - Scope items 2–6: the `SamplingFloor` domain model, policy `qci.compare.v2`, the engine
    version bump, `compare_distributions` integration, `LIMITATIONS` and the CLI renderer.
  - The remaining acceptance criteria: byte-identical `--json`, and `sampling_floor` null for
    not-comparable and unavailable comparisons.
  - Updating the `CLAUDE.md` policy-version convention to `qci.compare.v2`.

### M1.1 acceptance criteria

- [ ] (M1.1a) Unit tests: identical counts give p-value 1.0 and nonzero null quantiles; strongly
      different large samples give p-value 1/(B+1); unequal shot counts are each resampled at
      their own size; the same inputs give identical output.
- [ ] (M1.1a) False-positive calibration test: 200 seeded sample pairs drawn from one known
      distribution, with B=500. The fraction with p < 0.05 lies in [0.01, 0.10].
- [ ] (M1.1a) Power test: a known shifted distribution at a stated shot count is detected (p < 0.05)
      in at least 80% of 100 seeded trials.
- [ ] (M1.1b) `qci compare --json` is byte-identical across two invocations.
- [ ] (M1.1b) Not-comparable and unavailable comparisons have `sampling_floor` null.
- [ ] (M1.1a and M1.1b) All gates pass. The architecture test still passes.

## M1.1v: Sampling-floor validation experiment

**Goal:** test the M1.1 statistic against real draws from its own null, then re-score earlier
results. It is an experiment, not a product feature.

### Scope

1. **Location.** A scripts-only directory `experiments/repeated_sampling/` that uses the
   service API, not the CLI, and a separate store (`QCI_HOME=.qci-exp`, gitignored).
2. **Pre-registration.** Predictions are written and committed BEFORE running, in
   `docs/experiments/2026-10-repeated-sampling.md`, section "Pre-registered predictions".
3. **Groups.**
   - Group A: GHZ-star, `fake_sherbrooke`, optimization level 2, transpiler seed 7, simulator
     seeds 1–10, 1000 shots.
   - Group B: identical except transpiler seed 0.
4. **Analyses.**
   - All 45 within-group pairwise TVDs per group, against their sampling floors.
   - All 100 between-group pairs.
   - A re-score of the earlier compilation sweep (transpiler seeds 0–29, optimization levels
     1–3, fixed simulator seed), regenerated deterministically.
5. **Report.** It states results against the predictions and makes no claim about real
   hardware.

### M1.1v acceptance criteria

- [ ] The predictions commit precedes the results commit.
- [ ] The report includes raw tables plus the exact commands and seeds.
- [ ] No `src/` changes.

## M1.2: Compare-time observables

**Goal:** workload-specific figures of merit with uncertainty, without a run schema change.

### Scope

1. **Observable spec** (domain, provider-neutral):
   - name (identifier);
   - kind `bitstring_set_probability`;
   - bitstrings (unique, sorted);
   - register (optional; defaults to the single register);
   - bit_order `provider_counts_key`.

   The bitstrings must match provider counts keys verbatim. For Qiskit, classical bit 0 is the
   rightmost character. Document this.
2. **Per side:** k, n, the estimate k/n (`CALCULATED`), and a Wilson 95% score interval with
   z = 1.959963984540054 (`STATISTICAL`).
3. **Difference** (candidate minus baseline): a point estimate plus a Newcombe hybrid score
   interval built from the two Wilson intervals (`STATISTICAL`):
   ```
   lower = d - sqrt((p_c - l_c)^2 + (u_b - p_b)^2)
   upper = d + sqrt((u_c - p_c)^2 + (p_b - l_b)^2)
   ```
   where d = p_c - p_b, and (l, u) are the Wilson bounds.
4. **Gate and input rules.** Observables reuse the distribution comparability gate. If the gate
   fails, each observable is `not_comparable` with the same reasons. Bitstrings of the wrong
   width, or containing characters other than 0 and 1, are rejected at input. A bitstring never
   observed counts as 0.
5. **CLI:** `qci compare A B --observable NAME=BITS[,BITS...]`, repeatable.
6. **Identity.** Requested observables are part of the comparison request. Their canonical hash
   is included in the `comparison_id` derivation. `ENGINE_VERSION` becomes
   `qci.compare.engine.3`.
7. **Statistics on counts, not bitstrings.** The Wilson and Newcombe functions take integer
   arguments (k, n) and know nothing about bitstrings. Converting bitstring counts to (k, n) is
   a separate function. Rationale: a future logical-error-rate observable is also k failures in
   n trials and must reuse the same tested statistics (ADR 0006).

**Out of scope:** storing observables in the run record (needs schema v2; tracked as D18), and
parity and expectation-value observables.

### M1.2 acceptance criteria

- [ ] Wilson checks: k=5, n=10 gives about [0.2366, 0.7634]; k=0, n=10 gives an upper bound
      of about 0.2775. Both are verified independently in the test.
- [ ] Seeded coverage test: the Wilson interval covers the true p in 93–97% of 2000 trials at
      p=0.9, n=1000. The Newcombe interval covers the true difference in at least 93% of 2000
      trials.
- [ ] Different observable requests produce different `comparison_id`s. The same request
      produces an identical ID.
- [ ] The Wilson and Newcombe functions accept only integer (k, n) arguments and are tested
      without any bitstring input. The bitstring-counts-to-(k, n) conversion is a separate
      function with its own tests.
- [ ] Example in docs: `qci compare A B --observable ghz=00000,11111`.
- [ ] All gates pass.

## M1.3: Read-only live calibration snapshots

**Goal:** real drift evidence for a fixed footprint at zero QPU cost. No hardware execution.

Sub-steps, each reviewed separately:

- **M1.3a: design and ADR 0005 only, no code.** ADR number 0005 is reserved for this step;
  ADR 0006 was written earlier (2026-10) and is intentionally out of numeric order. Resolve:
  - snapshot storage: an insert-only standalone snapshot table, deduplicated by content hash,
    separate from runs;
  - the command surface;
  - credential handling: an IBM saved account, with tokens never stored, logged or put in
    tests;
  - whether historical calibration by datetime is supported by the INSTALLED
    qiskit-ibm-runtime, verified by reading the installed package source, not from memory;
  - how real-device calibration payloads differ from fakes;
  - snapshot storage designed as generic time-stamped measurements (adapter-defined resource
    identifier, parameter, value, unit and timestamp), with the raw provider payload kept
    alongside. The ADR must show how a non-qubit resource, such as a neutral-atom site or a
    logical error-correction patch, would be stored without a schema change (ADR 0006).
- **M1.3b: capture and storage,** with offline tests on sanitized recorded fixtures.
- **M1.3c: footprint-scoped snapshot-to-snapshot comparison,** reusing the existing hardware
  comparison logic. Existing compare outputs stay unchanged. Live capture is run manually by
  the user.

**Acceptance:** defined in ADR 0005 and approved before M1.3b starts.

## Deferred backlog (unplanned order)

None of these is scheduled. M0.5 follows M1.3, not M1. The rest have no planned order:

- M0.5: archival and richer measurement (details below).
- Estimated success probability as a labeled `MODEL_PREDICTION`.
- A Hellinger sampling floor.
- Chi-square tests.
- Multiple registers and FDR.
- Run-recorded observables (schema v2; D18).
- Probe runs as ordinary runs (research H3).
- Live hardware execution.
- The M2 meaningfulness policy.
- `qci test --baseline` and regression detection, built on the M2 meaningfulness policy.
- Evidence-based attribution.
- Repeated executions and experiment grouping (D7).
- More providers.
- Long-term backend snapshot history, beyond M1.3's standalone snapshots (D10, D19).
- Research datasets. See `docs/research.md` and `docs/product.md`.

### M0.5: Archival and richer measurement (deferred, not started)

- A content-addressed blob store under `.qci/objects/`.
- Archival of raw QPY, QASM and provider payloads. Inline `provider_raw` moves to blob
  references, which requires a `schema_version` bump and an explicit upcast.
- Fuller provenance: complete installed-package list, diff hash and source snapshot.
- An ideal distribution by exact statevector for small circuits, plus Hellinger fidelity and
  TVD, all labeled `calculated` with method versions.
- Golden fixtures, serialization round-trip tests, and a provider contract suite run against
  both the Qiskit adapter and an in-memory adapter.

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
| D17 | Who is the initial customer: HPC centers operating QPUs, or teams running error-mitigated experiments? | Unresolved. This is a product decision with no code impact yet. |
| D18 | Where are observables declared? | Compare-time now (M1.2). Workload-declared intent in the run record later, which requires schema v2. Open. |
| D19 | How should standalone calibration snapshots be stored, and how is their history kept? | To be resolved by ADR 0005 in M1.3a. |
