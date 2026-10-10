# PLAN

**Current milestone: M1.3, read-only live calibration snapshots. Current sub-step: M1.3c.
M1.3b is done (capture and storage, branch `feat/m1.3b-snapshot-capture`). M1.3a is done
(ADR 0005 accepted 2026-10-09). M1.1 (including M1.1v-addendum) and M1.2 are complete.**
**Status:** M0 and M1 are complete and committed (`f722eb9`, `07856e0`). Independent seeds
(`80cfe02`) and the GHZ-star workload (`48638a5`) are committed. M1.1a, M1.1b and M1.1v are
complete (`82ccd2e`). M1.1c is complete (`6e5ebe7`).
M1.1v-addendum is complete (predictions `b7f9ae6`). M1.2 is complete (`aec0e3d`, `c564c13`).

Milestones and sub-steps are strictly sequential: M1.1a, M1.1b, M1.1v, M1.1c,
M1.1v-addendum, M1.2, M1.3a, M1.3b, M1.3c. Do not build a later step, or anything in the
deferred backlog, while an earlier one is open. Each step follows the step workflow in
`CLAUDE.md`.

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

## M1.1: Sampling floor for TVD (DONE)

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
     deterministically from `comparison_id` by a documented function: the leading 53 bits
     of its SHA-256 digest, so the seed is an exact JSON number for float64 readers.
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

- [x] (M1.1a) Unit tests: identical counts give p-value 1.0 and nonzero null quantiles; strongly
      different large samples give p-value 1/(B+1); unequal shot counts are each resampled at
      their own size; the same inputs give identical output.
- [x] (M1.1a) False-positive calibration test: 200 seeded sample pairs drawn from one known
      distribution, with B=500. The fraction with p < 0.05 lies in [0.01, 0.10].
- [x] (M1.1a) Power test: a known shifted distribution at a stated shot count is detected (p < 0.05)
      in at least 80% of 100 seeded trials.
- [x] (M1.1b) `qci compare --json` is byte-identical across two invocations.
- [x] (M1.1b) Not-comparable and unavailable comparisons have `sampling_floor` null.
- [x] (M1.1a and M1.1b) All gates pass. The architecture test still passes.

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

- [x] The predictions commit precedes the results commit.
- [x] The report includes raw tables plus the exact commands and seeds.
- [x] No `src/` changes.

## M1.1c: Shared-seed guard

**Goal:** stop reporting a sampling floor when its independence assumption is known to fail.
M1.1v found that runs sharing a simulator seed produce correlated samples, so the floor gives
misleadingly high p-values for them (0.62–0.99 for different compilations; see
`docs/experiments/2026-10-repeated-sampling.md`, "Findings beyond the marked predictions").
Branch: `feat/m1.1c-shared-seed-guard`.

### Scope

1. **Guard.** When both runs executed on simulator backends and both have the same non-null
   `seed_simulator`, the distribution comparison does not compute the sampling floor.
   `sampling_floor` is null, and a new field `sampling_floor_unavailable_reason` states that
   the two samples were drawn with the same simulator seed, so they are not independent, and
   the floor assumes independent samples. This applies whether or not the compiled circuits
   differ.
2. **Unaffected runs.** Runs with different seeds, or where either seed is null (unseeded),
   are unaffected.
3. **Policy and engine version.** `ComparisonPolicy` version becomes `qci.compare.v3` and adds
   `sampling_floor_requires_distinct_simulator_seeds: bool = True`. Bump `ENGINE_VERSION`.
   Update the `CLAUDE.md` policy-version convention.
4. **Limitations and CLI.** `LIMITATIONS` gains one line on this rule. The text renderer
   shows the unavailable reason where the floor would appear.
5. **Reason scope.** `sampling_floor_unavailable_reason` is null whenever the floor is
   computed, and also when the comparability gate failed, because those reasons are already
   reported elsewhere.

### M1.1c acceptance criteria

- [x] Shared seed, different circuits: `sampling_floor` null, reason set.
- [x] Shared seed, identical circuits: status unchanged, `sampling_floor` null, reason set.
- [x] Different seeds: floor present.
- [x] Both unseeded: floor present.
- [x] One seeded and one unseeded: floor present.
- [x] With `sampling_floor_requires_distinct_simulator_seeds=False`, a shared-seed simulator
      pair gets a computed floor and no unavailable reason.
- [x] Equal non-null `seed_simulator` values where the backends are not both simulators: floor
      present.
- [x] `qci compare --json` is byte-identical across two invocations.
- [x] All gates pass.

## M1.1v-addendum: Compilation sweep with distinct simulator seeds

**Goal:** answer the question M1.1v's sweep re-score could not: are the output differences
between compilations larger than sampling alone produces? M1.1v's re-score was invalid
because every sweep run shared simulator seed 7 (see
`docs/experiments/2026-10-repeated-sampling.md`, "Findings beyond the marked predictions").
This reruns the sweep with a distinct simulator seed per run. It is an experiment, not a
product feature. Branch: `exp/m1.1v-addendum-sweep`.

### Design

1. **Runs.** GHZ-star, `fake_sherbrooke`, 1000 shots, transpiler seeds 0–29 at optimization
   levels 1, 2 and 3 (90 runs). Simulator seed = 1000 + 100 × level + transpiler seed, so
   every run has a distinct simulator seed.
2. **Store and scripts.** Scripts under `experiments/repeated_sampling/` use `RunService` and
   `CompareService`, not the CLI, and write to a fresh store `QCI_HOME=.qci-exp-addendum`
   (gitignored). The run script refuses to run if the working tree is dirty.
3. **Comparisons.** Each run is compared against the transpiler-seed-0 run of its level
   (29 pairs per level, 87 in total). Pairs with identical transpiled circuits (same
   transpiled qasm3 hash) are flagged.
4. **GHZ population.** P(00000) + P(11111) per run, with binomial standard error, computed in
   the experiment script only.
5. **Order.** Plan, scripts and pre-registered predictions are committed before any run is
   generated. Results and discussion are appended to the existing experiment document in a
   section "Addendum: sweep with distinct simulator seeds".

### M1.1v-addendum acceptance criteria

- [x] Predictions are committed before any run is generated.
- [x] All runs record git provenance with `dirty=false`.
- [x] Results are appended, with each prediction marked matched, not matched or inconclusive.
- [x] No `src/` changes.
- [x] All gates pass.

## M1.2: Compare-time observables (DONE)

**Goal:** workload-specific figures of merit with uncertainty, without a run schema change.

### Scope

1. **Observable spec** (domain, provider-neutral):
   - name (identifier);
   - kind `bitstring_set_probability`;
   - bitstrings (unique, sorted);
   - register (optional; defaults to the single register). Implemented as
     `classical_register`, because a field named `register` shadows `ABCMeta.register` on
     pydantic models;
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
   is included in the `comparison_id` derivation. Bump `ENGINE_VERSION`.
7. **Statistics on counts, not bitstrings.** The Wilson and Newcombe functions take integer
   arguments (k, n) and know nothing about bitstrings. Converting bitstring counts to (k, n) is
   a separate function. Rationale: a future logical-error-rate observable is also k failures in
   n trials and must reuse the same tested statistics (ADR 0006).
8. **Shared-seed rule.** When the shared-seed guard applies (same rule and policy flag as the
   TVD sampling floor), each run's estimate and Wilson interval are still reported, but the
   Newcombe difference interval is not computed; `difference_unavailable_reason` states why.
   The point difference (calculated) is still reported, as TVD is when the floor is withheld.

**Out of scope:** storing observables in the run record (needs schema v2; tracked as D18), and
parity and expectation-value observables.

### M1.2 acceptance criteria

- [x] Wilson checks: k=5, n=10 gives about [0.2366, 0.7634]; k=0, n=10 gives an upper bound
      of about 0.2775. Both are verified independently in the test.
- [x] Seeded coverage test: the Wilson interval covers the true p in 93–97% of 2000 trials at
      p=0.9, n=1000. The Newcombe interval covers the true difference in at least 93% of 2000
      trials.
- [x] Different observable requests produce different `comparison_id`s. The same request
      produces an identical ID.
- [x] The Wilson and Newcombe functions accept only integer (k, n) arguments and are tested
      without any bitstring input. The bitstring-counts-to-(k, n) conversion is a separate
      function with its own tests.
- [x] Example in docs: `qci compare A B --observable ghz=00000,11111`.
- [x] A shared-seed simulator pair has per-run estimates and Wilson intervals, no Newcombe
      difference interval, and `difference_unavailable_reason` set.
- [x] With `sampling_floor_requires_distinct_simulator_seeds=False`, the same pair gets a
      Newcombe difference interval and no unavailable reason.
- [x] All gates pass.

## M1.3: Read-only live calibration snapshots (CURRENT: M1.3c)

**Goal:** real drift evidence for a fixed footprint at zero QPU cost. No hardware execution.

Sub-steps, each reviewed separately:

- **M1.3a: design and ADR 0005 only, no code (DONE: ADR 0005 accepted).** ADR number 0005
  is reserved for this step; ADR 0006 was written earlier (2026-10) and is intentionally out
  of numeric order. Resolve:
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
- **M1.3b: capture and storage (DONE),** with offline tests on sanitized recorded fixtures.
- **M1.3c: footprint-scoped snapshot-to-snapshot comparison,** reusing the existing hardware
  comparison logic. Existing compare outputs stay unchanged. Live capture is run manually by
  the user.

**Acceptance:** defined in ADR 0005, approved on 2026-10-09 with amendments, and copied here.
Two M1.3c criteria (error parameters equal to 1, and re-measured versus not re-measured
parameters) were added at the M1.3b review on 2026-10-10.

M1.3a findings that shape these criteria: the installed qiskit-ibm-runtime 0.50.0 forwards a
`datetime` to the server, but its own docstrings say this is not implemented, so capture is
forward-only. QCI always passes `name=` to `QiskitRuntimeService`, so only a saved account is
used, never environment variables.

### M1.3b acceptance criteria (approved)

- [x] `qci/domain/snapshot.py` defines `Measurement` and `CalibrationSnapshot` as in ADR 0005
      section 2: frozen, `extra="forbid"`, with no provider SDK import (the architecture test
      covers the module).
- [x] `CalibrationSource` port in `qci/core/ports.py`. `SqliteSnapshotRepository` with the
      three tables in ADR 0005 section 1 and `snapshot_db_schema = 1`. It has `save`, `get`,
      `get_by_hash`, `list` and `measurements`, and no update or delete method. A test
      asserts that the class has no attribute named `update*` or `delete*`.
- [x] An existing M0/M1 database opens unchanged. The `runs` table and `DB_SCHEMA_VERSION`
      are untouched, and the snapshot tables are created beside them.
- [x] Capturing identical content twice creates one snapshot and two capture rows. Changed
      content creates a second snapshot. Content hashes do not depend on the local timezone:
      a test captures the same stub payload under two `TZ` settings and gets one snapshot.
- [x] Measurements: one row per reported (resource, parameter). A non-finite or complex value
      is stored with both value columns null. An unreported parameter has no row. No
      unavailable value is stored as 0.
- [x] A test stores rows with `resource_kind` values `site` and `logical_patch` through the
      repository, reads them back unchanged, and runs no migration.
- [x] `qci snapshot capture --backend NAME [--account ACCOUNT]` constructs the client only as
      `QiskitRuntimeService(name=ACCOUNT)`. A test asserts the exact keyword arguments
      through the injected factory. It rejects `fake_*` names and simulators with exit code 2,
      and on any error persists nothing and exits 1.
- [x] `qci snapshots`, `qci snapshot show ID [--json]` and
      `qci snapshot export ID --fixture PATH` work offline. `--json` output
      validates as `CalibrationSnapshot`.
- [x] `redact_payload` and the six sanitization tests in ADR 0005 section 5 exist and pass.
      `sanitize_error_message` redacts CRNs, bearer tokens and JWTs.
- [x] One real sanitized capture is committed under `tests/fixtures/snapshots/` as plain
      JSON with sorted keys and 2-space indentation, not gzip, checked by
      `test_fixture_is_plain_sorted_json`. A test shows the reader and the measurement rows
      agree on every selected value.
- [x] Manual live verification includes the single historical attempt in ADR 0005's Findings,
      `properties(datetime=...)` for 24 hours earlier. The result (honored, ignored, raises or
      inconclusive), the backend and the date are recorded in ADR 0005's Findings. Capture
      stays forward-only regardless.
- [x] No test constructs `QiskitRuntimeService`, enforced by a guard. No test opens a
      network connection.
- [x] `docs/architecture.md` and `docs/data-model.md` describe the snapshot store, and README
      documents the capture command and the saved-account prerequisite.
- [x] All gates pass.

### M1.3c acceptance criteria (approved)

- [ ] The first commit adds golden compare JSON for every `compare_hardware` exit listed in
      ADR 0005 section 7 and passes on unmodified `src/`.
- [ ] The second commit extracts `compare_calibration` and changes no golden file. Its golden
      test, and all existing compare tests, pass unchanged. `ComparisonPolicy.version`
      stays `qci.compare.v3` and `ENGINE_VERSION` stays `qci.compare.engine.4`.
- [ ] `qci snapshot compare BASE CAND --footprint-run RUN
      [--allow-footprint-backend-mismatch] [--json]` compares only the
      calibration of the run's physical footprint, using `IbmPropertiesCalibrationReader`
      unchanged.
- [ ] Snapshots from different providers or backends give `not_comparable` with a reason, and
      no parameter comparisons.
- [ ] `compare_calibration` takes `require_matching_units`, defaulting to `False`.
      `compare_hardware` does not pass it, and the golden files are unchanged. The snapshot
      path passes `True`.
- [ ] In the snapshot path, a parameter whose unit differs between the captures, including
      `None` against a unit, has `status="not_comparable"`, both raw values, `delta=None` and
      a reason in `HardwareComparison.reason` naming the resource, the parameter and both
      units. No unit is converted. With no other `changed` parameter, the status is
      `partially_comparable` and `relevant_hardware_changed` is null.
- [ ] A test feeds the same unit mismatch through run comparison and gets the current
      behavior: no `not_comparable` parameter and output identical to before.
- [ ] A footprint run whose backend name differs from the snapshots' gives `not_comparable`,
      with a reason naming both backends, unless `--allow-footprint-backend-mismatch` is set.
- [ ] With the flag, the output always has a note naming both backends. If any footprint
      resource is missing from either snapshot, the result is `not_comparable`, with a reason
      listing every missing resource, and no parameter comparisons. Tests cover a qubit at or
      above `n_qubits`, a two-qubit gate on an ordered pair not in its `coupling_map`, and a
      `measure` on a present qubit (present).
- [ ] Without a backend mismatch, no presence check runs, and a footprint qubit outside a
      snapshot's range is unavailable, as now.
- [ ] On the committed real fixture against a synthetic second snapshot derived from it:
      a changed footprint value gives `changed`, with delta = candidate minus baseline; a
      change outside the footprint sets only `global_snapshot_changed`; a removed parameter or
      a gate name absent from the payload gives `unavailable` and
      `relevant_hardware_changed = null`, never 0.
- [ ] Identical snapshots (same content hash) give `unchanged` and
      `global_snapshot_changed = false`.
- [ ] For the footprint's resources, the output lists every error-type parameter (a parameter
      name containing `error`) whose value is exactly 1, stated as the provider's value with no
      interpretation.
- [ ] When a parameter's value is unchanged between the two snapshots, the output distinguishes
      "re-measured, same value" (its measurement date changed) from "not re-measured" (same
      measurement date), and never presents the second as evidence of stability.
- [ ] `--json` output is byte-identical across repeated invocations. The comparison is never
      persisted: the database bytes are unchanged after the command.
- [ ] Rendered and JSON output contain none of the rule 8 words.
- [ ] Docs updated, all gates pass, and the live capture is run manually by the user. No
      test performs one.

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
- The M2 meaningfulness policy. Design input from the M1.1v-addendum: a baseline should be a
  population of runs, not one run. In that sweep, every run at a level was compared against
  one baseline run. Level 2's baseline drew a high GHZ population (0.921, against a mean of
  0.9045 for the other 29 runs), so 27/29 differences were negative, and the five runs with
  the same circuit as the baseline still differed from it by sampling alone. To separate
  compilation variation from sampling variation, the clean experimental design is
  replication: several runs per compilation, comparing variation within a compilation to
  variation between compilations, as M1.1v's Groups A and B did. It is neither all-pairs
  comparison nor a pooled single baseline. Sharing one baseline run also made the pairs at a
  level dependent on each other, so their differences cannot be read as independent results.
- Rename `sampling_floor_requires_distinct_simulator_seeds` to reflect that it also governs
  observable difference intervals, at the next policy bump made for another reason.
- Invariant: per-register counts sum to `total_shots` for succeeded runs. Verify every stored
  run satisfies it before adding a validator, because validators also run when old records
  load.
- At the next policy bump, treat a register with no counts as `not_comparable` in the
  distribution gate (currently it crashes the sampling floor; unreachable through the Qiskit
  adapter).
- `qci test --baseline` and regression detection, built on the M2 meaningfulness policy.
- Evidence-based attribution.
- Repeated executions and experiment grouping (D7).
- More providers.
- Long-term backend snapshot history beyond M1.3's forward-only capture log, such as
  historical capture by datetime (D10; ADR 0005).
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
| D19 | How should standalone calibration snapshots be stored, and how is their history kept? | **Resolved by [ADR 0005](docs/adr/0005-live-calibration-snapshots.md).** An insert-only snapshot store beside the runs table, deduplicated by content hash. History is a forward-only capture log. Measurements are stored as generic rows with adapter-defined resource identifiers, and the raw payload is kept. |
| D20 | Run comparison does not check that baseline and candidate units agree. | Open. Fix at the next policy bump. Snapshot comparison (M1.3c) will report a unit mismatch as `not_comparable` for that parameter and never converts units (ADR 0005 section 7). |
| D21 | Historical calibration backfill. | `properties(datetime=...)` appears to be honored (one observation, ibm_fez, 2026-10-10; ADR 0005 Findings). Before relying on it: test multiple dates and devices, find how far back it works, and check IBM's terms and rate limits. Capture stays forward-only until then. |
| D22 | The calibration reader ignores `measure` gate entries (`gate_error`, `gate_length`, `threshold`). Should snapshot comparison report them? | Open. Out of scope for M1.3b and M1.3c. Observed on `ibm_fez` (ADR 0005, section 6). |
