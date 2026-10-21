# PLAN

**Current milestone: R1 (release 1: packaging and first-run usability). Current step: R1c
(clean-machine install test and TestPyPI release, run by the user).** R1b is done
(2026-10-20, branch `feat/r1b-packaging`: distribution `bloq-qci` 0.1.0, the `ibm` extra, the
per-user store, `qci where`, `qci doctor`, selectors and summary-first comparison output;
ADR 0009 section 10, with the dated clarifications and findings recorded there). R1a is
done: [ADR 0009](docs/adr/0009-packaging-and-first-run.md)
accepted 2026-10-20 with the user's answers (branch `docs/r1a-packaging-design`).
M1.5 (historical backfill) is done. The M1.5d data manifest and
reproducibility check are done (branch `chore/m1.5d-data-manifest`,
`docs/experiments/2026-10-calibration-history-manifest.csv`; an offline rerun on the
frozen archive gave identical results). The M1.5d independent re-fetch check is done
(2026-10-20, branch `docs/m1.5d-refetch-check`: sparse sets re-fetched into a fresh store,
0 manifest rows differ). M1.5d is
done: collected and analyzed 2026-10-19, results and discussion
recorded (`docs/experiments/2026-10-calibration-history.md`, branch `docs/m1.5d-results`;
ADR 0008 section 8 Findings). P1, P2 and P4 were supported and P3 was not supported. The
M1.5d analysis script is done (`experiments/calibration_history/`, branch
`exp/m1.5d-analysis`, committed before any data set is collected or read, with a dated
clarification of the reading rule in the design's change history). The M1.5d design is
done: accepted 2026-10-18 (`docs/experiments/2026-10-calibration-history.md`, branch
`docs/m1.5d-experiment-design`), with a dated design clarification of P1 and P2 in ADR 0008
section 8. M1.5c is done (`qci snapshot backfill`,
branch `feat/m1.5c-historical-backfill`; manual live check on `ibm_fez` 2026-10-18, ADR 0008
Findings). The terms-of-service finding was recorded on 2026-10-18 (ADR 0008 section 6):
personal, local research use only (D29). M1.5b is done (D21
verified 2026-10-18 on `ibm_fez`, `ibm_kingston` and `ibm_marrakesh` to 365 days; ADR 0008
Findings). M1.5a is done (ADR 0008 accepted 2026-10-16 with amendments, branch
`docs/m1.5a-historical-backfill-design`).
M1.4 (stale-noise check) is done: M1.4c (live check by the user on three fake/device pairs,
2026-10-16, recorded in ADR 0007 Findings), M1.4b (`qci snapshot compare-run`, branch
`feat/m1.4b-compare-run`) and M1.4a (ADR 0007 accepted 2026-10-16 with amendments, branch
`docs/m1.4a-stale-noise-design`). M1.3 (read-only live calibration snapshots) is
done: M1.3c (footprint-scoped snapshot comparison, branch `feat/m1.3c-snapshot-diff`, live
check 2026-10-10), M1.3b (capture and storage, branch `feat/m1.3b-snapshot-capture`) and M1.3a
(ADR 0005 accepted 2026-10-09). M1.1 (including M1.1v-addendum) and M1.2 are complete.
**Status:** M0 and M1 are complete and committed (`f722eb9`, `07856e0`). Independent seeds
(`80cfe02`) and the GHZ-star workload (`48638a5`) are committed. M1.1a, M1.1b and M1.1v are
complete (`82ccd2e`). M1.1c is complete (`6e5ebe7`).
M1.1v-addendum is complete (predictions `b7f9ae6`). M1.2 is complete (`aec0e3d`, `c564c13`).

Milestones and sub-steps are strictly sequential: M1.1a, M1.1b, M1.1v, M1.1c,
M1.1v-addendum, M1.2, M1.3a, M1.3b, M1.3c, M1.4a, M1.4b, M1.4c, M1.5a (design), the later
M1.5 sub-steps its ADR defines, then R1 (R1a, R1b, R1c, R1d), then M1.6. Do not build a
later step, or anything in the deferred backlog, while an earlier one is open. Each step
follows the step workflow in `CLAUDE.md`.

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

## M1.3: Read-only live calibration snapshots (DONE)

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
- **M1.3c: footprint-scoped snapshot-to-snapshot comparison (DONE),** reusing the existing hardware
  comparison logic. Existing compare outputs stay unchanged. Live capture is run manually by
  the user.

**Acceptance:** defined in ADR 0005, approved on 2026-10-09 with amendments, and copied here.
Two M1.3c criteria (error parameters equal to 1, and re-measured versus not re-measured
parameters) were added at the M1.3b review on 2026-10-10. At the start of M1.3c the error-type
parameters became an explicit list, and the re-measured distinction was limited to snapshot
comparison (D23).

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

- [x] The first commit adds golden compare JSON for every `compare_hardware` exit listed in
      ADR 0005 section 7 and passes on unmodified `src/`.
- [x] The second commit extracts `compare_calibration` and changes no golden file. Its golden
      test, and all existing compare tests, pass unchanged. `ComparisonPolicy.version`
      stays `qci.compare.v3` and `ENGINE_VERSION` stays `qci.compare.engine.4`.
- [x] `qci snapshot compare BASE CAND --footprint-run RUN
      [--allow-footprint-backend-mismatch] [--json]` compares only the
      calibration of the run's physical footprint, using `IbmPropertiesCalibrationReader`
      unchanged.
- [x] Snapshots from different providers or backends give `not_comparable` with a reason, and
      no parameter comparisons.
- [x] `compare_calibration` takes `require_matching_units`, defaulting to `False`.
      `compare_hardware` does not pass it, and the golden files are unchanged. The snapshot
      path passes `True`.
- [x] In the snapshot path, a parameter whose unit differs between the captures, including
      `None` against a unit, has `status="not_comparable"`, both raw values, `delta=None` and
      a reason in `HardwareComparison.reason` naming the resource, the parameter and both
      units. No unit is converted. With no other `changed` parameter, the status is
      `partially_comparable` and `relevant_hardware_changed` is null.
- [x] A test feeds the same unit mismatch through run comparison and gets the current
      behavior: no `not_comparable` parameter and output identical to before.
- [x] A footprint run whose backend name differs from the snapshots' gives `not_comparable`,
      with a reason naming both backends, unless `--allow-footprint-backend-mismatch` is set.
- [x] With the flag, the output always has a note naming both backends. If any footprint
      resource is missing from either snapshot, the result is `not_comparable`, with a reason
      listing every missing resource, and no parameter comparisons. Tests cover a qubit at or
      above `n_qubits`, a two-qubit gate on an ordered pair not in its `coupling_map`, and a
      `measure` on a present qubit (present).
- [x] Without a backend mismatch, no presence check runs, and a footprint qubit outside a
      snapshot's range is unavailable, as now.
- [x] On the committed real fixture against a synthetic second snapshot derived from it:
      a changed footprint value gives `changed`, with delta = candidate minus baseline; a
      change outside the footprint sets only `global_snapshot_changed`; a removed parameter or
      a gate name absent from the payload gives `unavailable` and
      `relevant_hardware_changed = null`, never 0.
- [x] Identical snapshots (same content hash) give `unchanged` and
      `global_snapshot_changed = false`.
- [x] For the footprint's resources, the output lists every error-type parameter whose value
      is exactly 1, stated as the provider's value with no interpretation. Error-type
      parameters are an explicit, documented list in the IBM adapter: `gate_error`,
      `readout_error` and `init_error`. Names are never matched by substring, and an unlisted
      parameter is never listed.
- [x] In snapshot comparison, when a parameter's value is unchanged between the two snapshots,
      the output distinguishes "re-measured, same value" (its measurement date changed) from
      "not re-measured" (same measurement date), and never presents the second as evidence of
      stability. Run comparison output is unchanged (D23).
- [x] `--json` output is byte-identical across repeated invocations. The comparison is never
      persisted: the database bytes are unchanged after the command.
- [x] Rendered and JSON output contain none of the rule 8 words.
- [x] Docs updated, all gates pass, and the live capture is run manually by the user. No
      test performs one. (Live check by the user on 2026-10-10: two `ibm_fez` captures
      compared over a seeded GHZ-star footprint compiled for `fake_fez`; findings in ADR 0005,
      section 6.)

## M1.4: Stale-noise check (DONE)

**Goal:** show, for one stored fake-backend run, how the calibration frozen into that fake
backend differs from a live snapshot of the corresponding real device, scoped to the run's
physical footprint. It reports differences and measurement ages only. It does not say whether
the fake's noise model is adequate for the workload.

Scope sketch (designed in ADR 0007):

- Inputs: one stored run on a fake backend and one stored live snapshot. Read-only, offline,
  never persisted.
- The fake-to-real device correspondence is explicit and documented. Device names are never
  guessed.
- Direction: fake (baseline) to live (candidate). Deltas are live minus fake.
- Measurement dates on both sides, side by side, and their differences as calculated values.
- Kind differences (a resource or parameter on one side only, unit differences, error-type
  values equal to 1) are each reported explicitly.

Sub-steps, each reviewed separately:

- **M1.4a: design and [ADR 0007](docs/adr/0007-stale-noise-check.md) only, no code (DONE:
  ADR 0007 accepted 2026-10-16 with amendments).** Branch `docs/m1.4a-stale-noise-design`.
- **M1.4b: implementation (DONE, branch `feat/m1.4b-compare-run`),** with offline tests on
  the committed `ibm_fez` fixture and fake backends.
- **M1.4c: live check by the user (DONE, 2026-10-16),** on their own store, recorded in
  ADR 0007 Findings ("Live check (M1.4c)"). All M1.4c criteria in ADR 0007 section 9 are
  ticked.

### M1.4b acceptance criteria (approved 2026-10-16 with amendments; ADR 0007, section 9)

- [x] `FAKE_DEVICE_SOURCES` in `adapters/qiskit_ibm/calibration.py` is an explicit mapping
      with exactly three entries: `fake_fez -> ibm_fez`, `fake_kingston -> ibm_kingston` and
      `fake_marrakesh -> ibm_marrakesh`. Each entry has its own test, which instantiates the
      installed fake and asserts that its properties payload's `backend_name` equals the
      mapped device. A test asserts that the mapping has exactly these keys. No code derives a
      device name from a fake name.
- [x] `qci snapshot compare-run RUN_ID SNAPSHOT_ID [--json]` opens both repositories
      read-only. The database bytes are unchanged after the command, and the existing guard
      shows that no IBM client is constructed. An unknown run or snapshot ID exits 1.
- [x] Each exit in ADR 0007 section 6 has a test that asserts its status and its reason,
      and that no parameter comparisons are produced: no backend snapshot (`unavailable`);
      run snapshot source not `static_fake` (`not_comparable`); snapshot source not
      `live_calibration` (`not_comparable`); provider differs (`not_comparable`); fake not in
      the mapping (`not_comparable`, naming the fake and saying that no device name is
      derived from it); snapshot backend differs from the mapped device (`not_comparable`,
      naming both); the run's recorded properties `backend_name` missing or different from
      the mapped device (`not_comparable`, naming both); footprint not available
      (`unavailable`, or `not_comparable` when dynamic); footprint resources missing from
      either side (`not_comparable`, listing each one per side).
- [x] The calibration comparison is `compare_calibration` with `require_matching_units=True`,
      with the run's stored `BackendSnapshot` as baseline and the live snapshot's
      `BackendSnapshot` view as candidate, and the same footprint on both sides.
      `compare_calibration`, `compare_hardware`, `compare_snapshots`, `missing_resources`,
      `error_values_at_one`, the golden files, `ComparisonPolicy.version` (`qci.compare.v3`)
      and `ENGINE_VERSION` are unchanged, and all existing compare tests pass unmodified.
- [x] On a `fake_fez` run built in the test session and the committed `ibm_fez` fixture:
      `init_error` on each footprint qubit appears in `parameters_on_one_side` with
      `side="candidate"`, has `status="unavailable"` and a null baseline value, never 0.
      `side` names the side that reports the parameter: a synthetic removal from the live
      side appears with `side="baseline"`, and a removal from the fake side with
      `side="candidate"`. A synthetic unrepresentable value is `unavailable` and is not in
      `parameters_on_one_side`. (Wording corrected at M1.4c to match the implementation.)
- [x] A synthetic unit change, including `None` against a unit, gives `not_comparable`, both
      raw values, `delta=None`, the reason naming both units, and one `unit_differences`
      entry with both units. No unit is converted.
- [x] Error-type values of exactly 1 are listed per side with the existing
      `ERROR_PARAMETERS` and `error_values_at_one`. A test plants one on each side, and an
      unlisted parameter with value 1 is not listed.
- [x] `measurement_dates` has one entry per compared parameter, with both provider dates as
      given and `live_minus_fake` as a calculated `Metric` in seconds, null when either date
      is missing, never 0. `live_minus_fake_min`, `live_minus_fake_max` and
      `calibrated_at_difference` are calculated `Metric`s, or null. A test shows that
      changing the run's `backend_snapshot.captured_at` changes no date, difference or
      status in the output.
- [x] The output has no device-wide gate-set, parameter-set or qubit-count fields; only the
      footprint is compared.
- [x] The output carries both backend versions, the recorded device and its version, the
      run's `qiskit-ibm-runtime` version, `device_mapping`, and exactly the limitations in
      ADR 0007 section 7, including: "This compares calibration data: the values the fake
      backend was built from and the live device's reported values. It does not compare the
      noise model a simulator constructs from that data; a simulator may use only some of
      these parameters, in its own way."
- [x] The text renderer shows the unit on every value line (D26, for this command).
- [x] `run_snapshot_comparison_id` is deterministic, lists are sorted as in ADR 0007
      section 6, and `--json` output is byte-identical across two invocations.
- [x] Rendered and JSON output contain none of the rule 8 words, nor `significan`,
      `verdict`, `caus`, `degrad`, `stale`, `outdated`, `accurate`, `realistic` or
      `adequate`, checked by a test.
- [x] `docs/architecture.md`, `docs/data-model.md` and README describe the command, and all
      gates pass.

## M1.5: Historical backfill (DONE)

**Goal:** calibration history from before the first capture, if the provider honors
historical lookups. Resolves D21 first, then captures past calibrations. Feeds research
hypothesis H2 and D27.

Designed in [ADR 0008](docs/adr/0008-historical-backfill.md), accepted 2026-10-16 with
amendments to the M1.5b protocol. Sub-steps, each reviewed separately:

- **M1.5a: design, ADR 0008 and `scripts/verify_historical_calibration.py` (DONE: ADR 0008
  accepted 2026-10-16 with amendments).** Branch `docs/m1.5a-historical-backfill-design`.
- **M1.5b: verification of D21, run by the user (DONE, 2026-10-18; ADR 0008 Findings).**
  Protocol `qci.d21.verify.3` in ADR 0008 section 2: `ibm_fez`, `ibm_kingston` and
  `ibm_marrakesh` at 1, 7, 30, 90, 180 and 365 days back with one repeated request, plus a
  ground-truth cross-check against the stored live snapshots. All 18 offsets `honored`,
  repeats identical, 5 `match` and 1 `different_document:lag_consistent`; proceed for all
  three devices. The terms-of-service check was moved to a gate before M1.5c. No code.
- **M1.5c: `qci snapshot backfill` (DONE, 2026-10-18; ADR 0008 Findings).** Branch
  `feat/m1.5c-historical-backfill`. Terms finding recorded 2026-10-18: personal, local
  research use only (D29). Manual live check on `ibm_fez`: 51 lookups of 47 distinct
  documents, store changed only by backfill additions, and both documents fetched by M1.5b
  and the backfill have identical properties hashes.
  M1.5b supports it for all three devices, each with a depth cap of 365 days. Backfilled
  history is documents by stamp time, not what a user would have seen at a given time
  (publication lag observed: at least 5 min 33 s).
- **M1.5d: research experiment on D27 and the calibration side of H2 (DONE, 2026-10-19;
  results and discussion in the design file, branch `docs/m1.5d-results`; ADR 0008 section 8
  Findings).** P1, P2 and P4 supported, P3 not supported. Exploratory observations, labeled
  as not pre-registered, inform D22, D24, D25 and D27.
  Predictions P1-P4 are pre-registered in ADR 0008 section 8; the analysis script is committed
  before any backfilled value is analyzed. The design must choose the sampling grid and window
  explicitly, with an estimate of storage size, before any larger backfill: `ibm_fez`
  documents were stamped about every 46 to 78 minutes (interquartile range over 3 days), so a
  daily grid samples about one document in 23, and each document took about 2.1 MB in the
  store (ADR 0008 Findings).
  **Design (accepted 2026-10-18, branch `docs/m1.5d-experiment-design`):**
  [docs/experiments/2026-10-calibration-history.md](docs/experiments/2026-10-calibration-history.md).
  It defines a dense set for D27, P1 and P2 (hourly, the 7 days ending at the collection date
  `D`, 169 grid times per device) and a sparse set for P3 and the calibration side of H2
  (every 120 hours over 365 days, 73 grid times per device, so that the grid time 30 days
  before the newest is on the grid) on `ibm_fez`, `ibm_kingston` and `ibm_marrakesh`. Upper
  bound: 795 requests in 9 invocations and 1.67 GB added. The design also gives the exact
  statistics, the marking rules for P1-P4 (thresholds unchanged), the integrity notes
  (including the use of the 51 existing `ibm_fez` lookups) and the backfill commands.
  ADR 0008 section 8 records a dated design clarification (2026-10-18, before collection):
  "across distinct documents" in P1 and P2 is over distinct measurements; thresholds
  unchanged. Remaining M1.5d parts, each a separate approved step: (1) the analysis script
  under `experiments/calibration_history/` (DONE, branch `exp/m1.5d-analysis`), committed
  with offline tests on synthetic stores before any data set is collected or read; the design
  records a dated clarification (2026-10-18): a reading needs no unit, since IBM reports an
  empty unit for dimensionless parameters; (2) collection by the user with the design's
  commands (DONE, 2026-10-19); (3) one analysis run from a clean tree, with the aggregate
  results and marks recorded in the design file (DONE, 2026-10-19).

**Decision rule after M1.5b** (ADR 0008 section 1): per device, the verified depth is the
largest offset that is `honored` (at or before the requested time, different from the
current document, within 48 hours before the requested time, and no newer than any less
distant request's result), with every smaller offset `honored` or
`inconclusive:no_newer_document`. `honored_distant` does not count. Proceed for devices with
a verified depth of at least 30 days, an identical repeat, and no `raises` or `non_monotonic`
outcome; narrow to devices with at least 7 but under 30 days; stop when no device qualifies
or the terms do not permit the planned use. In the cross-check, `match` and
`different_document:lag_consistent` (stored stamp < returned stamp <= capture time) do not
disqualify; `different_document:inconsistent` does. Any `lag_consistent` result means
backfilled history for that device is documents by stamp time, not what a user would have
seen at a given time, and the ADR and M1.5c's docs must say so. Stopping is a valid
outcome: D21 is then resolved as not supported for QCI's use and history stays forward-only.

The M1.5b commands, run in zsh from the repository root:

```bash
mkdir -p ~/qci-m15b
shasum -a 256 ~/.qci-live/qci.db
PYTHONPATH=src .venv/bin/python scripts/verify_historical_calibration.py --account default-ibm-quantum-platform --store "$HOME/.qci-live/qci.db" --pause 5 | tee ~/qci-m15b/d21.txt
shasum -a 256 ~/.qci-live/qci.db
```

### M1.5b acceptance criteria (approved 2026-10-16, amended 2026-10-18; ADR 0008, section 8)

- [x] The user runs the commands in ADR 0008 section 2 (protocol `qci.d21.verify.3`) on the
      three devices. The full output is recorded verbatim in ADR 0008 Findings ("D21
      verification (M1.5b)"), with the anchor time.
- [x] Those Findings record, per device: each offset's outcome, the returned `last_update_date`,
      whether the repeat is identical, any `honored_distant` or `non_monotonic` outcome, and the
      verified depth.
- [x] Those Findings record every cross-check outcome with `L`, `R` and `T`, and classify each
      `different_document` as `lag_consistent` or `inconsistent`. Any
      `different_document:inconsistent` disqualifies its device. If any
      `different_document:lag_consistent` occurs on a qualifying device, Findings state that
      backfilled history for that device is documents by stamp time, not what a user would have
      seen at a given time.
- [x] The store hash is identical in the script's `store_sha256_before` and `store_sha256_after`
      lines and in both `shasum` lines.
- [x] If the script stopped at a too-many-requests response, that is recorded, and the run is
      not repeated before the terms check. (It did not occur.)
- [x] The terms-of-service finding completes ADR 0008 section 6. Moved by the user on
      2026-10-18 to a gate before M1.5c, and recorded on 2026-10-18: personal, local research
      use only; redistribution and commercial use stay open as D29.
- [x] The decision rule in ADR 0008 section 1 is applied and its result (proceed, narrow or
      stop, per device) is recorded. `PLAN.md` is updated to match: on stop, D21 is resolved,
      M1.5c is removed and M1.5d is marked for redesign or dropped.
- [x] No QCI code changes in M1.5b.

### M1.5c acceptance criteria (approved 2026-10-16, amended 2026-10-18; all met 2026-10-18)

- [x] `SnapshotSource.HISTORICAL_LOOKUP`, `SnapshotCapture.method` and
      `SnapshotCapture.requested_before` exist as in ADR 0008 section 3, with the validator. The
      committed `ibm_fez` fixture validates unchanged.
- [x] `snapshot_db_schema = 2` with the `snapshot_lookups` table. A test opens a version 1 store
      read-only (every capture reads as `live_capture`, nothing is written) and for writing (the
      table is created, the version becomes 2, and every existing row is byte-identical). A
      version 1 table set and a version 2 table set are both accepted; any other partial set is
      `DamagedStoreError`.
- [x] The content hash formula is unchanged. Two grid times returning one document give one
      snapshot and two lookup captures. `requested_before` is not in `capture_options`.
- [x] A lookup stores `configuration: null`. A test asserts that the client's `configuration()`
      is not stored for a lookup.
- [x] Requested times are aware UTC datetimes with a zero offset. A stub test asserts the exact
      `datetime` keyword the client receives under two `TZ` settings.
- [x] A returned `last_update_date` that is missing or after `requested_before` stores nothing
      for that request and stops with exit 1, naming the device and both times.
- [x] The grid is as in ADR 0008 section 5 (UTC midnights, newest first, `--step-hours` minimum
      1), and `--days` above the device's verified depth, or a device with no verified depth,
      exits 2 with nothing requested.
- [x] The first too-many-requests response (HTTP 429, or IBM error code 1202 in the exception
      chain) stops the invocation with exit 1, with nothing retried by QCI and everything stored
      before it kept. A stub test raises it on the third request and asserts two stored lookups
      and three requests.
- [x] `--max-requests` defaults to 30 and is capped at 100. `--pause` defaults to 10 and has a
      minimum of 2, unless the ADR 0008 section 6 finding sets other values. A stub test counts
      the requests and the pauses.
- [x] Re-running after a stub error resumes: grid times already stored are skipped without a
      request, and the run completes the rest.
- [x] `fake_*` names and simulators exit 2. The store is checked before any request. The client
      is constructed only as `QiskitRuntimeService(name=ACCOUNT)`, asserted through the injected
      factory. No test constructs the real client or opens a connection.
- [x] `qci snapshot show` prints the source and, for each lookup capture, its
      `requested_before`. `qci snapshots` output for existing stores is unchanged.
- [x] `qci compare`, `qci snapshot compare` and `qci snapshot compare-run` output is unchanged
      for existing inputs, and the golden files are unchanged.
- [x] `docs/architecture.md`, `docs/data-model.md`, README and `CLAUDE.md` describe the command
      and the provenance. Where M1.5b recorded `different_document:lag_consistent` for a device,
      they and `qci snapshot backfill --help` state that its backfilled history is documents by
      stamp time, not what a user would have seen at a given time. All gates pass, and the
      neutral-wording check has no unexplained hit.
- [x] Manual live check by the user: one small backfill (for example `--days 3`) on one
      qualifying device, recorded in ADR 0008 Findings, with the store hash changing only
      through the backfill. (2026-10-18, `ibm_fez`.)

## R1: Release 1, packaging and first-run usability

**Goal:** a new user installs QCI from PyPI with one command, runs and compares two
simulations offline within about five minutes, and optionally compares a run with live
calibration. Packaging, store location and presentation only: comparison rules, record
schemas and JSON output are unchanged.

Designed in [ADR 0009](docs/adr/0009-packaging-and-first-run.md), accepted 2026-10-20 with
the user's answers to six review questions. Its sections resolve:

1. **Distribution:** PyPI name `bloq-qci`, import name `qci`, command `qci`, version `0.1.0`
   single-sourced from `qci.__version__`. Apache-2.0 with `LICENSE`, `NOTICE` ("Copyright
   2026 The QCI Authors", the commit authors in the git history; see `AUTHORS`) and PEP 639
   metadata. `LICENSE` and `NOTICE` are on `main` (PR #5, 2026-10-20), and `toorha` and
   `dhruvhptl` recorded their agreement as comments on PR #5 on 2026-10-20, so the NOTICE
   needs no `site/` exclusion and the licensing gate is met. Future
   contributions use the Developer Certificate of Origin (`Signed-off-by:`), documented in
   `CONTRIBUTING.md` and `CLAUDE.md`. No project URLs while the repository is private. Python 3.12 or later, tested on 3.12 and 3.13.
   Wheel and sdist contents are explicit allow-lists that exclude `tests/` (including the
   `ibm_fez` fixture), `experiments/`, `docs/`, `site/`, `examples/` and `scripts/`, enforced
   by an archive test that also scans for IBM payloads (D29).
2. **Extras:** a core install without provider SDKs, which can list, show and compare
   stored runs and snapshots; an `ibm` extra (`qiskit`, `qiskit-ibm-runtime` capped below
   0.51 for 0.1.0, `qiskit-aer`) for `run`, `snapshot capture`, `snapshot backfill` and
   `snapshot export`, which exit 2 without it. Non-editable installs are the documented user
   path, which avoids the macOS hidden `.pth` problem.
3. **Store:** per user (`~/Library/Application Support/qci` on macOS, `%LOCALAPPDATA%\qci` on
   Windows, `$XDG_DATA_HOME/qci` or `~/.local/share/qci` elsewhere), `QCI_HOME` still
   overriding, and `qci where`. An existing `./.qci/qci.db` gets a stderr note with the exact
   `QCI_HOME` command; nothing is moved or copied (resolves D5 when accepted).
4. **`qci doctor`:** Python, package and dependency versions, the `ibm` extra, the saved
   account by name only, and read-only store health (empty, healthy, damaged, other schema
   version). Exit 0 without a problem, 1 with one, 2 for usage.
5. **Selectors:** `ID`, an 8-or-more-character unique `PREFIX`, or
   `[BACKEND:]latest[~N]` (runs in listing order; snapshots by provider stamp, backend
   required). Ambiguity exits 1 with the candidates listed.
6. **Summary-first text:** `qci compare`, `qci snapshot compare` and
   `qci snapshot compare-run` print a summary with key statistics and per-parameter
   calibration magnitudes (absolute and relative deltas, labeled calculated); `--verbose`
   adds today's full text, byte for byte. JSON and golden files are unchanged, guaranteed by
   CLI-level goldens committed before any `src/` change.
7. **Quickstart** for the README (text in the ADR). The README is self-contained for PyPI,
   with no relative links; absolute links wait until the repository's visibility is settled.
   It is written for users (user decision, 2026-10-20): developer material moves to
   `CONTRIBUTING.md` and `docs/`, the landing-page section to `site/README.md`, and the
   IBM-data statement to `tests/fixtures/snapshots/README.md` and `CONTRIBUTING.md`.
8. **Release process:** versioning, `CHANGELOG.md`, build once, TestPyPI before PyPI, and the
   clean-machine test.
9. **Out of scope:** new comparison features, hosted services, any redistribution of IBM data.

Sub-steps, each reviewed separately:

- **R1a: design, ADR 0009 only, no code (DONE: ADR 0009 accepted 2026-10-20).** Branch
  `docs/r1a-packaging-design`.
- **R1b: implementation (DONE 2026-10-20, branch `feat/r1b-packaging`),** with offline
  tests. Commit
  order: CLI-level golden files first, on unmodified `src/` (ADR 0009 section 6); then
  packaging and license; then store location, `qci where` and `qci doctor`; then selectors;
  then the summary. Docs that describe `./.qci` or the editable install as the user path
  (`CLAUDE.md`, `AGENTS.md`, `README.md`, `docs/architecture.md`, `docs/data-model.md`) are
  updated in the same step, and `CHANGELOG.md` is created.
- **R1c: clean-machine install test and TestPyPI release,** run by the user (ADR 0009
  section 8), in two parts. Part 1, not gated: the locally built wheel and sdist in fresh
  environments on Python 3.12 and 3.13 with an isolated `HOME`, the quickstart's offline
  steps, and a core-only install. Part 2: the TestPyPI upload and the same steps from
  TestPyPI, gated on the two license agreements (met 2026-10-20, PR #5). D29 does not gate
  TestPyPI: the archive test checks that the packages hold no IBM data. Includes the PyPI
  name checks. Recorded in ADR 0009 Findings.
- **R1d: PyPI release,** by the user. Gated on D29 being resolved for a public release (the
  repository stays private until then). The licensing gate is met (PR #5, 2026-10-20).
  Uploads the exact files R1c tested (hashes checked) and repeats the offline quickstart from
  PyPI.

### R1b acceptance criteria (approved 2026-10-20; ADR 0009 section 10)

Commit order and provenance:

- [x] The first R1b commit changes no file under `src/` and adds the CLI-level golden files
      of ADR 0009 section 6 (`--json` and text, for `qci compare` over the runs of the 13
      service-level cases, and for `qci snapshot compare` and `qci snapshot compare-run` over
      their existing test cases on the committed fixture), in `tests/golden/cli/`, compared
      byte for byte. They are green on unmodified `src/`.
- [x] Every R1b commit carries a `Signed-off-by:` line (DCO 1.1).

Distribution and license:

- [x] `pyproject.toml`: name `bloq-qci`; `dynamic = ["version"]` read from
      `src/qci/__init__.py`, where `__version__ = "0.1.0"`; `license = "Apache-2.0"` and
      `license-files = ["LICENSE", "NOTICE"]`; build requirement `hatchling>=1.27`;
      `requires-python = ">=3.12"`; classifiers for Python 3.12 and 3.13 only; no
      `[project.urls]`; core dependencies, and the `ibm` and `dev` extras, exactly as in
      section 2, with `qiskit-ibm-runtime>=0.50,<0.51`.
- [x] `LICENSE` is the unmodified Apache License 2.0 text and `NOTICE` is the two lines in ADR
      0009 section 1 (on `main` since PR #5, 2026-10-20; ADR 0009 Findings). R1b leaves both
      unchanged.
- [x] `AUTHORS` says the QCI Authors are the commit authors in the git history and names no
      one. `tests/fixtures/snapshots/README.md` and `CONTRIBUTING.md` say the IBM data under
      `tests/fixtures/` is not licensed by this project and is provided by IBM under IBM's
      own terms (moved from the README by user decision, 2026-10-20).
- [x] `CONTRIBUTING.md` adopts the Developer Certificate of Origin 1.1, includes its text, and
      asks for `git commit -s`. `CLAUDE.md`'s step workflow requires a `Signed-off-by:` line
      on every commit, including commits made through Claude Code.
- [x] `src/qci/py.typed` exists and is in the wheel.
- [x] `provenance/environment.py` reads the version of the distribution `bloq-qci` and
      records it under the package key `qci`; a test shows the key and a non-null version
      with the package installed.
- [x] `tests/test_distribution_contents.py` builds the sdist and the wheel from that sdist
      with `python -m build --no-isolation` into a temporary directory, and reports every
      member that meets any of the five conditions of ADR 0009 section 1; no member does. The wheel
      and the sdist hold exactly the allow-listed members. A scanner self-test reports a
      synthetic archive holding `ibm_fez.json` under `tests/fixtures/`, and one holding the
      fixture's text inside a `.py` file.
- [x] The build test writes nothing in the working tree (`git status` is clean afterwards).

Extras:

- [x] With an import hook that blocks `qiskit`, `qiskit_ibm_runtime` and `qiskit_aer`, in a
      subprocess over a store prepared in the test session: `qci runs`, `qci show`,
      `qci compare`, `qci snapshots`, `qci snapshot show`, `qci snapshot compare`,
      `qci snapshot compare-run`, `qci where` and `qci doctor` print the same stdout and
      exit with the same code as with the SDKs (for `qci doctor`, every line except the
      `ibm` extra and saved-account lines, which report the extra missing by design); `qci
      run`, `qci snapshot capture`,
      `qci snapshot backfill` and `qci snapshot export` exit 2 with the message in
      section 2, before opening the store or loading a workload, and the store bytes are
      unchanged.
- [x] The extra check lives in `adapters/qiskit_ibm/` and uses `importlib.util.find_spec`
      without importing the SDKs. The architecture test still holds.

Store location:

- [x] The per-user directory is tested for `darwin`, `win32` with and without
      `LOCALAPPDATA`, and another platform with `XDG_DATA_HOME` absolute, relative and unset,
      by patching the platform and environment. `QCI_HOME` overrides it; an empty `QCI_HOME`
      counts as unset.
- [x] Read-only commands on a missing per-user directory create nothing and read an empty
      store. The first write creates the directory, with mode `0o700` on POSIX.
- [x] `qci where` prints exactly the absolute `qci.db` path on stdout, its source and whether
      the file exists on stderr, opens no store, and exits 0.
- [x] The `./.qci` note of ADR 0009 section 3 is printed to stderr exactly when `QCI_HOME` is
      unset and `./.qci/qci.db` is a file in the current directory, by every command that opens
      a store and by `qci where` and `qci doctor`; never for a parent directory. stdout and exit
      codes are identical with and without it. The legacy file's bytes and modification time are
      unchanged after every command.

`qci doctor`:

- [x] Each check of ADR 0009 section 4 has a test for each of its `ok`, `note` and `problem`
      outcomes, with the account lister and the environment injected.
- [x] A stub saved account whose token, instance, URL and channel are sentinel strings: none of
      them appears in stdout or stderr; the account name does. An unparseable account file
      prints only the exception type.
- [x] Store outcomes `empty`, `healthy` (with schema versions and counts), `damaged` and
      `other schema version` are each tested, for runs and snapshots separately; the store
      bytes are unchanged after every case.
- [x] Exit 0 with notes only, exit 1 with any `problem`. No IBM client is constructed and no
      connection is opened (the session guard).

Selectors:

- [x] `qci/core/selectors.py` is a pure function over `(id, backend, sort_key)` lists with no
      provider import and no SQL; the architecture test covers it.
- [x] Every argument listed in ADR 0009 section 5 accepts each form: full ID, unique prefix of 8
      to 25 characters, `latest`, `latest~N`, and `BACKEND:latest[~N]`. For runs, the order is
      `run_id` descending and includes every status. For snapshots, it is `calibrated_at`
      descending, a snapshot without `calibrated_at` is never selected, and `BACKEND:` is
      required.
- [x] Each ambiguity of ADR 0009 section 5 (a prefix with two or more matches, a run sharing its
      millisecond with a neighbor, a snapshot sharing its `calibrated_at` with a neighbor)
      exits 1, selects nothing and lists the candidates, at most 10 and then a count.
- [x] No match exits 1. Each malformed form of ADR 0009 section 5 exits 2.
- [x] A selector echoes `<role>: <selector> -> <ID>` on stderr. For each command, stdout with a
      selector is byte-identical to stdout with the full ID it resolved to.

Summary-first output:

- [x] Default text output of the three commands is the summary of ADR 0009 section 6. `--verbose`
      output is that summary followed by exactly the text golden of the first commit.
- [x] `git diff` from the first R1b commit to the last over `tests/golden/` is empty for every
      JSON file, the 13 service-level ones and the CLI-level ones.
- [x] `--json` and `--json --verbose` print identical bytes for every golden case.
- [x] Magnitudes: for each parameter name and unit, counts compared and changed, median and
      largest absolute delta with unit, median and largest relative delta, each largest one
      naming its resource. Tests cover a baseline of exactly 0 (left out of relative figures,
      counted as "baseline 0", no infinite value) and `unavailable` and `not_comparable`
      parameters (counted, never entered as 0).
- [x] Each figure is a `Metric` with `EvidenceKind.CALCULATED`, method
      `qci.summary.magnitude`, version 1, built in `qci/compare/summary.py` from the existing
      models. `ComparisonPolicy.version` (`qci.compare.v3`) and `ENGINE_VERSION` are
      unchanged.
- [x] The existing neutral-wording tests of the three commands cover the default summary,
      with the M1.4b word list.

Docs:

- [x] README is self-contained as in ADR 0009 section 7, written for users in the order of
      section 7: the quickstart verbatim, the essential explanations inline, a "License and
      contributing" section pointing to `CONTRIBUTING.md` (which has the editable install),
      and no relative link (checked by a test). A test runs the quickstart's offline commands,
      extracted from `README.md`, in a temporary store. Developer material is in
      `CONTRIBUTING.md` or `docs/`, and the landing-page section in `site/README.md`. The
      README passes the neutral-wording check in full.
- [x] `CLAUDE.md`, `AGENTS.md`, `docs/architecture.md` and `docs/data-model.md` describe the
      per-user store, `QCI_HOME`, the extras, `qci where`, `qci doctor`, selectors, the
      summary and `--verbose`, and the exit-code rows for the extra check, `qci doctor`,
      selectors and `qci where`. `CHANGELOG.md` exists with an `Unreleased` section describing
      R1. `PLAN.md` marks D5 resolved.
- [x] All gates are clean, and every neutral-wording hit is justified.

### R1c acceptance criteria (approved 2026-10-20, split 2026-10-20; ADR 0009 section 10; run by the user)

Part 1, local clean-machine test (no gate):

- [ ] Before part 2: the name `bloq-qci` is unclaimed on PyPI and TestPyPI, and a search of
      PyPI for distributions shipping a top-level `qci` package is recorded.
- [ ] `CHANGELOG.md` has its dated `0.1.0` entry and every packaged file is final before the
      build. The two files are built once with `python -m build` from a clean checkout of the
      release commit on `main`; the archive test is run over those exact files, and both
      SHA-256 hashes are recorded.
- [ ] The clean-machine test of ADR 0009 section 8, steps 1 to 3, on Python 3.12 and on 3.13,
      outside the repository, with `PYTHONPATH` unset and `HOME` a new empty directory, from the
      locally built wheel and, separately, the locally built sdist: every command and exit code
      is recorded; `qci where` names a path under that `HOME`; `qci doctor` exits 0 with the
      account check as a note; the core-only environment reads the store, and `qci run` there
      exits 2 with the extra message and the store bytes unchanged.
- [ ] Whether the hidden `.pth` problem appeared is recorded.

Part 2, TestPyPI (gated on the two license agreements: met 2026-10-20; not gated on D29):

- [x] Both license agreements are recorded (PR #5, 2026-10-20; ADR 0009 Findings).
- [ ] Part 1 is complete, on the same two files (hashes checked).
- [ ] The user uploads both files to TestPyPI. Steps 1 and 2 are repeated installing
      `bloq-qci[ibm]==0.1.0` from TestPyPI with the index options of ADR 0009 section 8, and the
      installed wheel's hash equals the recorded one.
- [ ] Machine, OS, Python versions, hashes and outputs are recorded in ADR 0009 Findings. No
      IBM call is made; the quickstart's optional live part is not part of R1c.

### R1d acceptance criteria (approved 2026-10-20; ADR 0009 section 10; run by the user)

- [ ] D29 is resolved for a public release, with the date and the outcome in `PLAN.md`.
- [x] The comments by `toorha` and `dhruvhptl` on the pull request that adds `LICENSE`, each
      stating "I agree to license my contributions to this repository under the Apache
      License 2.0.", are recorded in ADR 0009 Findings (PR #5, 2026-10-20). The NOTICE
      has no `site/` exclusion, so no NOTICE change is needed.
- [ ] No packaged file changed since R1c's build; otherwise R1c is repeated on the new build.
- [ ] The user tags `v0.1.0` on the release commit and uploads to PyPI the two files R1c
      recorded; the hashes PyPI reports equal R1c's.
- [ ] The quickstart's offline steps, run from PyPI in a fresh environment with an empty
      `HOME`, give the same exit codes as in R1c, recorded in ADR 0009 Findings.
- [ ] `PLAN.md` marks R1 done.

## M1.6: Footprint staleness and pre-flight

**Goal:** before a run, report how old the calibration of a footprint is, and later an
estimated success probability that is clearly labeled as a model prediction.

Scope sketch (designed in its own ADR, after M1.5):

- D25: for a footprint, the age of each relevant measurement at capture time and the oldest
  one, as calculated values.
- Then an estimated success probability, labeled `model_prediction` with its method and
  method version, never presented as a measurement.
- Later, validate the estimate against a few real runs. This is the first paid hardware
  execution and needs its own approval.

## Deferred backlog (unplanned order)

None of these is scheduled. M0.5 stays unscheduled. The rest have no planned order:

- M0.5: archival and richer measurement (details below).
- Estimated success probability as a labeled `MODEL_PREDICTION` (now sketched in M1.6).
- Device-wide gate-set and qubit-count differences between a fake and its live device
  (removed from M1.4b at the ADR 0007 review, 2026-10-16).
- Summarize footprint differences by magnitude (relative and absolute), not only counts;
  under exact comparison nearly every re-measured continuous value counts as changed
  (M1.4c, 2026-10-16). Now scheduled in R1b (ADR 0009 section 6).
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
- Widen the `qiskit-ibm-runtime<0.51` cap (ADR 0009 section 2) only after checking each new
  version against the behavior QCI depends on: historical requests, account handling,
  logging and redaction.
- Summary-first text output for `qci show` and `qci snapshot show` (ADR 0009 section 6 covers
  only the three comparison commands).
- CUDA-Q adapter as the second provider (after M1.6): tests vendor neutrality; needs a Linux
  NVIDIA-GPU environment for GPU features.
- Run provenance: record simulator method, device (CPU or GPU) and numerical precision.
- Watch item: NVIDIA Ising (AI calibration and decoding) and NVQLink: relevant to
  calibration and decoder provenance in the error-correction era (ADR 0006); revisit with
  operator customers.
- Long-term backend snapshot history beyond M1.3's forward-only capture log, such as
  historical capture by datetime (D10; ADR 0005). Historical capture is now sketched in M1.5.
- Research datasets. See `docs/research.md` and `docs/product.md`.
- Revisit data version control tooling (for example DVC) when there are multiple datasets,
  collaborators, or a storage location D29 permits.

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
| D5 | Project-local or user-global store? | **Resolved 2026-10-20 (R1b, branch `feat/r1b-packaging`):** a per-user store (`~/Library/Application Support/qci` on macOS, `%LOCALAPPDATA%\qci` on Windows, `$XDG_DATA_HOME/qci` or `~/.local/share/qci` elsewhere), `QCI_HOME` still overriding, `qci where` printing the path, and existing `./.qci` stores never moved (a stderr note gives the `QCI_HOME` setting). Decided in [ADR 0009](docs/adr/0009-packaging-and-first-run.md) section 3. Before R1: project-local `.qci/` with a `QCI_HOME` override. |
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
| D21 | Historical calibration backfill. | **Resolved by M1.5b (2026-10-18, [ADR 0008](docs/adr/0008-historical-backfill.md) Findings).** `properties(datetime=...)` is honored on `ibm_fez`, `ibm_kingston` and `ibm_marrakesh` at 1, 7, 30, 90, 180 and 365 days back: every returned document is older than the requested time by at most 1 h 41 min, monotonic, and repeatable, and 5 of 6 cross-checks against stored captures match. The sixth shows publication lag (at least 5 min 33 s), so backfilled history is documents by stamp time, not what a user would have seen at a given time. `configuration()` has no history. Backfill (M1.5c) was gated on the user's terms-of-service check, recorded 2026-10-18 (ADR 0008 section 6): personal, local research use only (D29). |
| D22 | The calibration reader ignores `measure` gate entries (`gate_error`, `gate_length`, `threshold`). Should snapshot comparison report them? | Open. Out of scope for M1.3b and M1.3c. Observed on `ibm_fez` (ADR 0005, section 6). M1.5d (2026-10-19, exploratory): `measure` `gate_error` has statistics identical to `readout_error` on all 15 footprint qubits in both data sets, which is evidence that it duplicates `readout_error` there ([results](docs/experiments/2026-10-calibration-history.md#c-exploratory-observations-not-pre-registered)). |
| D23 | Run comparison reports unchanged parameter values the same way whether or not they were re-measured; make the distinction at the next policy bump. | Open. Snapshot comparison (M1.3c) makes the distinction; run comparison output stays unchanged until the next policy bump. |
| D24 | Some provider parameters are not physically measured: virtual gates such as `rz` (IBM reports `gate_error` 0 and `gate_length` 0, dated with the document timestamp) and configured durations such as `gate_length`. Their date can change without a measurement. | Open. Classify them through an explicit adapter list and exclude them from the "re-measured, same value" evidence. Observed in the first live comparison (ADR 0005, section 6). Supported by M1.5d P4 (2026-10-19): on 3,305 of 3,305 (document, footprint qubit) pairs on three devices, `rz` `gate_error` is exactly 0 and dated with the document's stamp, so `rz` is never physically measured. The adapter list can proceed in a future step. |
| D25 | Report, for a footprint, the age of each relevant measurement at capture time and the oldest one, as a calculated value. | Open. Scheduled in M1.6. In the first live comparison, values that were not re-measured were about 1 h (T2) to about 22 h (cz) old at the later capture. Informed by M1.5d (2026-10-19, exploratory): over one week on three devices, `T1`, `T2`, `sx` and `cz` were re-measured about daily, and `readout_error`, `prob_meas*` and `init_error` every 1.3 to 4.9 h on most series, so measurement ages depend on the parameter. |
| D26 | Show units in the text renderer (T1 and T2 in microseconds, lengths in nanoseconds). | Open. Checked on 2026-10-10: the JSON carries `unit` on every `hardware.shared_resource_parameters` entry (`us`, `ns`, or null for dimensionless values and unit mismatches). `unchanged_values` and `error_values_at_one` entries have no unit field. The text renderer shows the unit only on changed lines. `qci snapshot compare-run` (M1.4b, ADR 0007) shows the unit on every value line. |
| D27 | Research: estimate the noise in provider calibration estimates by tracking the same parameter across many recalibrations. | Partially addressed by M1.5d (2026-10-19, [results](docs/experiments/2026-10-calibration-history.md#results)). IBM publishes no uncertainty for these estimates: each parameter carries only `name`, `value`, `unit` and `date`. A `changed` value means only that the reported value changed. The spread across re-measurements is now quantified on 15 footprint qubits over one week (P1: median `T1` CV 0.19 to 0.27; `readout_error` CV and `d / m` larger on every device). Physical change and estimation noise are not separated. |
| D28 | Historical snapshots have no configuration (ADR 0008 section 3): `qci snapshot compare` with `--allow-footprint-backend-mismatch` lists every footprint resource as missing, and `elapsed_between_captures` is the difference of request times. | Open. Raised in M1.5a. Comparison code is unchanged in M1.5. Decide in a later step whether presence for a historical snapshot may use another snapshot's configuration, and how elapsed time is reported for lookups. |
| D29 | Review the IBM Quantum service agreement for redistribution of calibration data and commercial use under the Open Plan before any public release, hosted service, or shared dataset. | Open. Raised 2026-10-18 by the terms finding in [ADR 0008](docs/adr/0008-historical-backfill.md) section 6: M1.5c proceeds for personal, local research use only, and backfilled data is never committed to the repository or redistributed. The committed M1.5d manifest contains, per backfilled document, IBM's last_update_date and QCI's content hash, but no parameter values. These are treated as identifying metadata, not IBM data content; if the D29 review concludes otherwise, the provider_stamp column is removed. The PyPI release (R1d, [ADR 0009](docs/adr/0009-packaging-and-first-run.md)) is a public release and is gated on this review. The built packages contain no IBM data, enforced by an archive test. The repository is made private until D29 is resolved (user decision, 2026-10-20); whether a public repository may keep the committed `ibm_fez` fixture is part of the review. Mitigating fact, not a resolution: Qiskit's own fake backends distribute equivalent IBM calibration snapshots under Apache-2.0. |
