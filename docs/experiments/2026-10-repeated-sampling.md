# Experiment: repeated sampling and the M1.1 TVD sampling floor (M1.1v)

Date: 2026-10-03. Branch: `exp/m1.1v-sampling-validation`. Milestone: M1.1v in `PLAN.md`.

## Purpose

M1.1 added a TVD sampling floor: null TVD quantiles and a Monte Carlo p-value under
H0 that both runs sampled one shared distribution, estimated by the pooled plug-in
estimate. The unit tests check the statistic on synthetic multinomial draws. This experiment
checks it on runs produced by the real QCI pipeline on a fake backend. In that setting,
repeated runs of one transpiled circuit differ only by simulator seed, so H0 holds by
construction. It also re-scores the earlier compilation sweep against the floor.

This is an experiment, not a product feature. It uses a static fake backend with a
simulated noise model. Nothing here is evidence about real hardware.

## Setup

- **qci commit:** `193f59d5612e060a18887cfe357d8f222174f63b` (`main` at the start of this
  step). The experiment makes no `src/` changes, so this is the code under test.
- **Environment:** Python 3.13.9, numpy 2.5.3, qiskit 2.5.2, qiskit-aer 0.17.2,
  qiskit-ibm-runtime 0.50.0.
- **Workload:** `examples/ghz_star.py` (5-qubit GHZ with star connectivity, which needs
  routing), entrypoint `build`.
- **Backend:** `fake_sherbrooke`, with its static noise model and calibration.
- **Execution:** `qiskit.primitives.BackendSamplerV2`, through `RunService` (not the CLI).
- **Store:** `QCI_HOME=.qci-exp` (gitignored), separate from `.qci/`.
- **Group A:** optimization level 2, transpiler seed 7, simulator seeds 1–10, 1000 shots each.
- **Group B:** identical except transpiler seed 0.
- **Compilation sweep (regenerated):** transpiler seeds 0–29 at optimization levels 1, 2
  and 3, simulator seed 7, 1000 shots each (90 runs). PLAN.md does not name the sweep's
  workload. GHZ-star is used because it is the routing-sensitive workload added for
  observing compilation-induced changes. Each run is compared against the transpiler-seed-0
  run of its level, giving 29 pairs per level and 87 in total.
- **Comparisons through `CompareService`** use policy `qci.compare.v2` with B = 2000. The
  resampling seed is `seed_from_comparison_id(comparison_id)`. `comparison_id` includes the
  run IDs, which are freshly generated ULIDs. A regeneration therefore uses different
  resampling seeds, and its p-values match only up to Monte Carlo error. The seeds actually
  used are recorded in the results.
- **Within-group pairs:** all 45 pairs (i, j) with i < j. The baseline is simulator seed i
  and the candidate is simulator seed j.
- **Between-group pairs:** all 100 pairs. The baseline is a Group A run and the candidate is
  a Group B run.
- **Pooled comparison:** each group's 10 runs merged into 10000 shots. Baseline = merged A,
  candidate = merged B. It calls `qci.compare.sampling.tvd_sampling_floor` directly with
  B = 2000 and seed `20261003`.
- **P5 recomputation:** `tvd_sampling_floor` with B = 2000 and seeds `1000`–`1019`
  (20 seeds). It is applied to the pooled A-vs-B counts and to Group A simulator seed 1
  (baseline) vs simulator seed 2 (candidate).
- **Exceedance:** a pair exceeds its floor when observed TVD > that pair's null p95.

## Pre-registered predictions

Written and committed before any experiment run. The "Marking rule" lines operationalize
each prediction so it can be marked matched, not matched or inconclusive without choosing a
rule after the results are known.

**P1.** For each group, about 5% of the 45 within-group pairwise TVDs exceed that pair's null
p95. The 45 pairs share runs and are not independent, so anything from 0 to about 6
exceedances is unremarkable.
*Marking rule:* per group, 0–6 exceedances is matched, 7–9 is inconclusive (the "about"
margin), and 10 or more is not matched.

**P2.** Within-group p-values are roughly uniform, with no strong pile-up near 0.
*Marking rule:* report decile histograms per group. Uniform p-values would put 4.5 of 45
below 0.1. Per group, at most 9 p-values below 0.1 (twice the expected count) is matched,
and 10 or more is not matched.

**P3.** Between groups (A vs B), FakeSherbrooke's noise model is static, so any difference
between the two compilations is deterministic. Whether 1000 shots detects it depends on
effect size. No direction is predicted. Report the p-value distribution across all 100 pairs,
and the pooled comparison (each group's 10 runs merged into 10000 shots).
*Marking rule:* P3 makes no prediction about the outcome, so it is reported descriptively and
marked inconclusive. One exception: if Groups A and B compile to identical transpiled
circuits (same transpiled qasm3 hash), its premise fails, and that is reported.

**P4.** In the re-scored compilation sweep, pairs with identical transpiled circuits give
p-values consistent with sampling. Pairs with different physical footprints may or may not
exceed the floor.
*Note, written before running:* the sweep fixes simulator seed 7. Two runs with identical
transpiled circuits are therefore expected to produce identical counts (TVD 0, p-value 1),
not two independent samples. For these pairs the check is degenerate.
*Marking rule:* matched if every identical-circuit pair has p-value ≥ 0.05, and not matched
otherwise. The different-footprint half makes no prediction and is reported descriptively.

**P5.** Monte Carlo stability. For a fixed pair of counts, p-values recomputed with different
seeds have a standard deviation close to the reported Monte Carlo standard error,
sqrt(p(1-p)/(B+1)). A standard deviation more than 2 times the reported standard error would
indicate the reported uncertainty is too small.
*Marking rule:* the standard error is evaluated at the mean p-value. For each of the two
count pairs, ratio ≤ 2 is matched and ratio > 2 is not matched. If the mean p-value is
1/(B+1), the standard error is near its minimum and every resample is at the floor, so the
ratio is reported but the case is marked inconclusive.

**D1 (descriptive, no prediction).** GHZ population P(00000) + P(11111) per run, with
binomial standard error sqrt(p(1-p)/n), and the between-group difference of pooled
populations (B minus A) with standard error sqrt(SE_A² + SE_B²). This is computed in the
experiment script only, as a stand-in for M1.2.

**D2 (descriptive, no prediction).** Hellinger distance within vs between groups. Hellinger
has no sampling floor, so it is reported only as a hypothesis-generating observation.
