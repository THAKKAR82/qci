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

## Results

Produced on 2026-10-03 from branch `exp/m1.1v-sampling-validation`, with no `src/` changes
relative to `193f59d`. Runs record git provenance with `dirty=true`, because the experiment
scripts were uncommitted when the runs were created. Exact commands, from the repository
root:

```bash
PYTHONPATH=src:experiments/repeated_sampling QCI_HOME=.qci-exp \
    .venv/bin/python experiments/repeated_sampling/run_experiment.py
PYTHONPATH=src:experiments/repeated_sampling QCI_HOME=.qci-exp \
    .venv/bin/python experiments/repeated_sampling/analyze.py > .qci-exp/results.md
```

Every seed is listed under Setup or in the tables below. The `seed` column holds the
resampling seed that `CompareService` derived from each `comparison_id`. A regeneration
creates new run IDs, so its resampling seeds and p-values differ within Monte Carlo error.
The run counts are deterministic.

**Runtime:** run creation 187.5 s (110 runs), analysis 19.8 s (277 `CompareService`
comparisons, the pooled floor and 40 P5 recomputations). Total about 207 s.

The tables below are the verbatim output of `analyze.py`. "> p95" means observed TVD > null
p95. Pairwise rows put the baseline first and the candidate second.

### Transpiled circuits per group

- Group A: 1 distinct transpiled qasm3 hash(es): `e071a0e0ef4c`
- Group B: 1 distinct transpiled qasm3 hash(es): `f649eb91c05c`

### Within Group A (45 pairs)

Exceedances of null p95: **1/45**. p-values below 0.1: **6/45**. p < 0.05: 1/45.

p-value deciles [0,0.1) ... [0.9,1.0]: [6, 3, 6, 5, 4, 8, 3, 4, 6, 0]

| b sim | c sim | TVD | null p50 | null p95 | null p99 | p | p SE | > p95 | Hellinger | seed |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 2 | 0.0620 | 0.0390 | 0.0650 | 0.0810 | 0.0735 | 0.0058 | no | 0.1015 | 653962293232368 |
| 1 | 3 | 0.0400 | 0.0380 | 0.0650 | 0.0790 | 0.4593 | 0.0111 | no | 0.0778 | 6317468353913934 |
| 1 | 4 | 0.0380 | 0.0380 | 0.0630 | 0.0770 | 0.5117 | 0.0112 | no | 0.0910 | 3128852658427839 |
| 1 | 5 | 0.0510 | 0.0380 | 0.0650 | 0.0770 | 0.2069 | 0.0091 | no | 0.1001 | 1141862547460448 |
| 1 | 6 | 0.0450 | 0.0380 | 0.0630 | 0.0770 | 0.3038 | 0.0103 | no | 0.0711 | 2685554219086742 |
| 1 | 7 | 0.0630 | 0.0380 | 0.0640 | 0.0760 | 0.0595 | 0.0053 | no | 0.1027 | 718037518561305 |
| 1 | 8 | 0.0590 | 0.0380 | 0.0640 | 0.0750 | 0.0960 | 0.0066 | no | 0.0987 | 3420077954670362 |
| 1 | 9 | 0.0680 | 0.0390 | 0.0660 | 0.0820 | 0.0405 | 0.0044 | yes | 0.0958 | 6479192258475584 |
| 1 | 10 | 0.0310 | 0.0390 | 0.0640 | 0.0780 | 0.8151 | 0.0087 | no | 0.0946 | 3629482604229700 |
| 2 | 3 | 0.0440 | 0.0380 | 0.0660 | 0.0790 | 0.3578 | 0.0107 | no | 0.0854 | 3727504113530649 |
| 2 | 4 | 0.0510 | 0.0380 | 0.0650 | 0.0790 | 0.2094 | 0.0091 | no | 0.0971 | 8799311845592940 |
| 2 | 5 | 0.0450 | 0.0380 | 0.0650 | 0.0780 | 0.3273 | 0.0105 | no | 0.1062 | 7231832253605139 |
| 2 | 6 | 0.0360 | 0.0380 | 0.0650 | 0.0800 | 0.6022 | 0.0109 | no | 0.0910 | 76394923576860 |
| 2 | 7 | 0.0390 | 0.0380 | 0.0640 | 0.0780 | 0.4838 | 0.0112 | no | 0.1113 | 3782103690581780 |
| 2 | 8 | 0.0310 | 0.0390 | 0.0670 | 0.0790 | 0.7751 | 0.0093 | no | 0.1073 | 8216388414613841 |
| 2 | 9 | 0.0320 | 0.0390 | 0.0650 | 0.0780 | 0.7791 | 0.0093 | no | 0.0969 | 4747898342140154 |
| 2 | 10 | 0.0590 | 0.0400 | 0.0660 | 0.0790 | 0.1134 | 0.0071 | no | 0.1036 | 3388564254812016 |
| 3 | 4 | 0.0340 | 0.0370 | 0.0650 | 0.0770 | 0.6177 | 0.0109 | no | 0.0814 | 3529064231917402 |
| 3 | 5 | 0.0310 | 0.0370 | 0.0650 | 0.0770 | 0.7376 | 0.0098 | no | 0.0879 | 8095349684852710 |
| 3 | 6 | 0.0270 | 0.0370 | 0.0650 | 0.0800 | 0.8666 | 0.0076 | no | 0.0706 | 5582596909469364 |
| 3 | 7 | 0.0390 | 0.0370 | 0.0640 | 0.0780 | 0.4473 | 0.0111 | no | 0.0731 | 3041128703631910 |
| 3 | 8 | 0.0370 | 0.0380 | 0.0630 | 0.0770 | 0.5467 | 0.0111 | no | 0.0913 | 7594470955649621 |
| 3 | 9 | 0.0480 | 0.0390 | 0.0660 | 0.0760 | 0.2679 | 0.0099 | no | 0.0805 | 1072295896817413 |
| 3 | 10 | 0.0380 | 0.0390 | 0.0660 | 0.0780 | 0.5457 | 0.0111 | no | 0.0886 | 1578629986201885 |
| 4 | 5 | 0.0270 | 0.0360 | 0.0630 | 0.0750 | 0.8276 | 0.0084 | no | 0.0817 | 2619667763955387 |
| 4 | 6 | 0.0330 | 0.0360 | 0.0640 | 0.0780 | 0.6317 | 0.0108 | no | 0.0802 | 7169359509809637 |
| 4 | 7 | 0.0530 | 0.0360 | 0.0620 | 0.0740 | 0.1369 | 0.0077 | no | 0.0894 | 6926697447088860 |
| 4 | 8 | 0.0500 | 0.0370 | 0.0650 | 0.0790 | 0.1999 | 0.0089 | no | 0.1092 | 5911804299764922 |
| 4 | 9 | 0.0490 | 0.0380 | 0.0650 | 0.0760 | 0.2339 | 0.0095 | no | 0.0890 | 8773203855197287 |
| 4 | 10 | 0.0290 | 0.0380 | 0.0650 | 0.0800 | 0.8261 | 0.0085 | no | 0.0810 | 4365250753982002 |
| 5 | 6 | 0.0300 | 0.0380 | 0.0650 | 0.0780 | 0.8001 | 0.0089 | no | 0.0804 | 7471067846673032 |
| 5 | 7 | 0.0460 | 0.0370 | 0.0630 | 0.0790 | 0.2754 | 0.0100 | no | 0.0962 | 8412899767404316 |
| 5 | 8 | 0.0370 | 0.0370 | 0.0650 | 0.0790 | 0.5287 | 0.0112 | no | 0.0931 | 4238220584090742 |
| 5 | 9 | 0.0440 | 0.0380 | 0.0660 | 0.0780 | 0.3558 | 0.0107 | no | 0.0816 | 5165041278262467 |
| 5 | 10 | 0.0370 | 0.0390 | 0.0660 | 0.0770 | 0.5637 | 0.0111 | no | 0.0904 | 2027920288702933 |
| 6 | 7 | 0.0350 | 0.0370 | 0.0620 | 0.0750 | 0.5802 | 0.0110 | no | 0.0739 | 7479060492936055 |
| 6 | 8 | 0.0310 | 0.0370 | 0.0650 | 0.0790 | 0.7391 | 0.0098 | no | 0.0964 | 8700378753980263 |
| 6 | 9 | 0.0380 | 0.0380 | 0.0660 | 0.0790 | 0.5182 | 0.0112 | no | 0.0758 | 2065903952506729 |
| 6 | 10 | 0.0400 | 0.0390 | 0.0660 | 0.0800 | 0.4883 | 0.0112 | no | 0.0793 | 4986230940434147 |
| 7 | 8 | 0.0360 | 0.0370 | 0.0650 | 0.0780 | 0.5477 | 0.0111 | no | 0.1066 | 1290282263459760 |
| 7 | 9 | 0.0290 | 0.0400 | 0.0670 | 0.0800 | 0.8386 | 0.0082 | no | 0.0834 | 5351761434717185 |
| 7 | 10 | 0.0630 | 0.0380 | 0.0650 | 0.0800 | 0.0715 | 0.0058 | no | 0.0916 | 1243644000479687 |
| 8 | 9 | 0.0450 | 0.0390 | 0.0670 | 0.0780 | 0.3338 | 0.0105 | no | 0.1126 | 8066798098821600 |
| 8 | 10 | 0.0510 | 0.0390 | 0.0650 | 0.0800 | 0.2014 | 0.0090 | no | 0.0960 | 6682350389162237 |
| 9 | 10 | 0.0610 | 0.0400 | 0.0680 | 0.0810 | 0.1000 | 0.0067 | no | 0.0941 | 1813154606096681 |

### Within Group B (45 pairs)

Exceedances of null p95: **0/45**. p-values below 0.1: **1/45**. p < 0.05: 0/45.

p-value deciles [0,0.1) ... [0.9,1.0]: [1, 6, 4, 5, 3, 5, 4, 6, 5, 6]

| b sim | c sim | TVD | null p50 | null p95 | null p99 | p | p SE | > p95 | Hellinger | seed |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 2 | 0.0530 | 0.0380 | 0.0650 | 0.0800 | 0.1649 | 0.0083 | no | 0.0807 | 7775319393678128 |
| 1 | 3 | 0.0270 | 0.0370 | 0.0630 | 0.0760 | 0.8626 | 0.0077 | no | 0.0445 | 7945911569532641 |
| 1 | 4 | 0.0310 | 0.0370 | 0.0630 | 0.0740 | 0.7161 | 0.0101 | no | 0.0812 | 4229304427384549 |
| 1 | 5 | 0.0400 | 0.0370 | 0.0650 | 0.0790 | 0.4193 | 0.0110 | no | 0.0816 | 1617685811234345 |
| 1 | 6 | 0.0440 | 0.0370 | 0.0650 | 0.0790 | 0.3303 | 0.0105 | no | 0.0722 | 1308318367407824 |
| 1 | 7 | 0.0560 | 0.0380 | 0.0660 | 0.0800 | 0.1364 | 0.0077 | no | 0.0713 | 3996226489175148 |
| 1 | 8 | 0.0490 | 0.0360 | 0.0630 | 0.0780 | 0.1974 | 0.0089 | no | 0.0612 | 7181418877146063 |
| 1 | 9 | 0.0600 | 0.0390 | 0.0670 | 0.0820 | 0.1000 | 0.0067 | no | 0.0833 | 7935232640246559 |
| 1 | 10 | 0.0240 | 0.0380 | 0.0650 | 0.0780 | 0.9490 | 0.0049 | no | 0.0663 | 6128285961761233 |
| 2 | 3 | 0.0430 | 0.0380 | 0.0640 | 0.0780 | 0.3683 | 0.0108 | no | 0.0830 | 2394112629662576 |
| 2 | 4 | 0.0450 | 0.0370 | 0.0640 | 0.0780 | 0.2994 | 0.0102 | no | 0.0853 | 5829737593604115 |
| 2 | 5 | 0.0450 | 0.0380 | 0.0660 | 0.0780 | 0.3373 | 0.0106 | no | 0.1013 | 6518756070251715 |
| 2 | 6 | 0.0250 | 0.0370 | 0.0650 | 0.0780 | 0.9185 | 0.0061 | no | 0.0728 | 6648261151800526 |
| 2 | 7 | 0.0330 | 0.0380 | 0.0650 | 0.0770 | 0.6957 | 0.0103 | no | 0.0948 | 7706545732825117 |
| 2 | 8 | 0.0290 | 0.0370 | 0.0650 | 0.0780 | 0.7926 | 0.0091 | no | 0.0903 | 1529811689786372 |
| 2 | 9 | 0.0280 | 0.0390 | 0.0670 | 0.0790 | 0.8711 | 0.0075 | no | 0.0917 | 4507718041008730 |
| 2 | 10 | 0.0530 | 0.0390 | 0.0650 | 0.0790 | 0.1574 | 0.0081 | no | 0.0843 | 4776504236877988 |
| 3 | 4 | 0.0290 | 0.0360 | 0.0630 | 0.0770 | 0.7846 | 0.0092 | no | 0.0765 | 3694375338549367 |
| 3 | 5 | 0.0330 | 0.0370 | 0.0630 | 0.0780 | 0.6572 | 0.0106 | no | 0.0856 | 5148949545970492 |
| 3 | 6 | 0.0310 | 0.0380 | 0.0650 | 0.0760 | 0.7426 | 0.0098 | no | 0.0684 | 1848938381904270 |
| 3 | 7 | 0.0360 | 0.0370 | 0.0650 | 0.0770 | 0.5602 | 0.0111 | no | 0.0565 | 2160185005599806 |
| 3 | 8 | 0.0350 | 0.0370 | 0.0650 | 0.0770 | 0.5862 | 0.0110 | no | 0.0615 | 6331072856052003 |
| 3 | 9 | 0.0480 | 0.0380 | 0.0660 | 0.0790 | 0.2649 | 0.0099 | no | 0.0792 | 2026304740882427 |
| 3 | 10 | 0.0280 | 0.0370 | 0.0640 | 0.0760 | 0.8326 | 0.0083 | no | 0.0551 | 5398471133386799 |
| 4 | 5 | 0.0220 | 0.0360 | 0.0630 | 0.0770 | 0.9570 | 0.0045 | no | 0.0884 | 3887529491339382 |
| 4 | 6 | 0.0370 | 0.0370 | 0.0640 | 0.0770 | 0.5092 | 0.0112 | no | 0.0802 | 9000629784519696 |
| 4 | 7 | 0.0450 | 0.0360 | 0.0630 | 0.0810 | 0.2814 | 0.0101 | no | 0.0795 | 2598310134913356 |
| 4 | 8 | 0.0390 | 0.0370 | 0.0620 | 0.0760 | 0.4408 | 0.0111 | no | 0.0850 | 7255512162880864 |
| 4 | 9 | 0.0480 | 0.0380 | 0.0650 | 0.0800 | 0.2624 | 0.0098 | no | 0.0944 | 7855544682734508 |
| 4 | 10 | 0.0290 | 0.0370 | 0.0660 | 0.0810 | 0.8046 | 0.0089 | no | 0.0843 | 6120494335685407 |
| 5 | 6 | 0.0320 | 0.0370 | 0.0630 | 0.0770 | 0.7056 | 0.0102 | no | 0.0918 | 6694303936458604 |
| 5 | 7 | 0.0400 | 0.0380 | 0.0650 | 0.0780 | 0.4458 | 0.0111 | no | 0.0894 | 369390722295274 |
| 5 | 8 | 0.0330 | 0.0370 | 0.0640 | 0.0740 | 0.6367 | 0.0108 | no | 0.0774 | 5173466945855537 |
| 5 | 9 | 0.0410 | 0.0370 | 0.0640 | 0.0790 | 0.3868 | 0.0109 | no | 0.0758 | 2896390815796886 |
| 5 | 10 | 0.0310 | 0.0370 | 0.0650 | 0.0780 | 0.7431 | 0.0098 | no | 0.0667 | 2878780711897302 |
| 6 | 7 | 0.0270 | 0.0370 | 0.0650 | 0.0770 | 0.8736 | 0.0074 | no | 0.0699 | 8358915574544699 |
| 6 | 8 | 0.0210 | 0.0380 | 0.0660 | 0.0780 | 0.9820 | 0.0030 | no | 0.0755 | 5662314493763567 |
| 6 | 9 | 0.0380 | 0.0380 | 0.0670 | 0.0810 | 0.5087 | 0.0112 | no | 0.0941 | 6085086654976217 |
| 6 | 10 | 0.0380 | 0.0380 | 0.0660 | 0.0790 | 0.5157 | 0.0112 | no | 0.0727 | 2361029898440148 |
| 7 | 8 | 0.0240 | 0.0370 | 0.0650 | 0.0790 | 0.9335 | 0.0056 | no | 0.0698 | 1134596054456543 |
| 7 | 9 | 0.0220 | 0.0380 | 0.0650 | 0.0790 | 0.9740 | 0.0036 | no | 0.0755 | 7216720880957567 |
| 7 | 10 | 0.0530 | 0.0380 | 0.0650 | 0.0780 | 0.1604 | 0.0082 | no | 0.0766 | 3458284521389182 |
| 8 | 9 | 0.0330 | 0.0380 | 0.0660 | 0.0810 | 0.6902 | 0.0103 | no | 0.0874 | 8622335252709988 |
| 8 | 10 | 0.0440 | 0.0370 | 0.0650 | 0.0750 | 0.3208 | 0.0104 | no | 0.0709 | 5226860919359637 |
| 9 | 10 | 0.0530 | 0.0390 | 0.0660 | 0.0790 | 0.1739 | 0.0085 | no | 0.0723 | 5638751469132932 |

### Between groups, A (baseline) vs B (candidate), 100 pairs

Exceedances of null p95: **12/100**. p < 0.05: 12/100. p < 0.1: 22/100. Identical transpiled circuits: 0/100. Footprint resources identical: 100/100.

p-value deciles [0,0.1) ... [0.9,1.0]: [22, 13, 13, 18, 10, 11, 3, 1, 3, 6]

p-value summary: {"n": 100, "min": 0.0205, "median": 0.3058, "mean": 0.3388, "max": 0.991}

TVD matrix (rows: A simulator seed, columns: B simulator seed):

| A \ B | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 0.0360 | 0.0680 | 0.0500 | 0.0570 | 0.0580 | 0.0650 | 0.0770 | 0.0700 | 0.0740 | 0.0440 |
| 2 | 0.0680 | 0.0260 | 0.0580 | 0.0580 | 0.0520 | 0.0430 | 0.0450 | 0.0400 | 0.0310 | 0.0650 |
| 3 | 0.0430 | 0.0480 | 0.0230 | 0.0400 | 0.0400 | 0.0380 | 0.0450 | 0.0440 | 0.0480 | 0.0390 |
| 4 | 0.0450 | 0.0590 | 0.0460 | 0.0270 | 0.0370 | 0.0530 | 0.0610 | 0.0570 | 0.0580 | 0.0420 |
| 5 | 0.0480 | 0.0470 | 0.0380 | 0.0350 | 0.0190 | 0.0380 | 0.0470 | 0.0430 | 0.0430 | 0.0410 |
| 6 | 0.0560 | 0.0450 | 0.0440 | 0.0510 | 0.0410 | 0.0340 | 0.0440 | 0.0390 | 0.0460 | 0.0540 |
| 7 | 0.0720 | 0.0410 | 0.0500 | 0.0600 | 0.0520 | 0.0420 | 0.0230 | 0.0390 | 0.0320 | 0.0670 |
| 8 | 0.0600 | 0.0360 | 0.0480 | 0.0490 | 0.0390 | 0.0360 | 0.0410 | 0.0250 | 0.0390 | 0.0550 |
| 9 | 0.0750 | 0.0400 | 0.0610 | 0.0620 | 0.0540 | 0.0510 | 0.0360 | 0.0470 | 0.0220 | 0.0680 |
| 10 | 0.0380 | 0.0680 | 0.0480 | 0.0430 | 0.0460 | 0.0600 | 0.0730 | 0.0660 | 0.0680 | 0.0290 |

p-value matrix (rows: A simulator seed, columns: B simulator seed):

| A \ B | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 0.6162 | 0.0445 | 0.2219 | 0.1284 | 0.1059 | 0.0655 | 0.0205 | 0.0365 | 0.0205 | 0.3713 |
| 2 | 0.0430 | 0.9240 | 0.1169 | 0.1149 | 0.1849 | 0.3918 | 0.3578 | 0.4788 | 0.8101 | 0.0575 |
| 3 | 0.3878 | 0.2714 | 0.9670 | 0.4153 | 0.4628 | 0.5357 | 0.3078 | 0.3483 | 0.2754 | 0.5057 |
| 4 | 0.3033 | 0.0920 | 0.2684 | 0.8351 | 0.5077 | 0.1499 | 0.0820 | 0.1094 | 0.1119 | 0.3948 |
| 5 | 0.2519 | 0.2824 | 0.5107 | 0.5807 | 0.9910 | 0.5312 | 0.2789 | 0.3613 | 0.3708 | 0.4443 |
| 6 | 0.1274 | 0.3353 | 0.3558 | 0.2034 | 0.4048 | 0.6587 | 0.3473 | 0.4688 | 0.3118 | 0.1694 |
| 7 | 0.0275 | 0.4123 | 0.2204 | 0.0670 | 0.1684 | 0.3698 | 0.9595 | 0.4703 | 0.7366 | 0.0440 |
| 8 | 0.0870 | 0.5722 | 0.2534 | 0.2274 | 0.4453 | 0.5807 | 0.4213 | 0.9155 | 0.5167 | 0.1359 |
| 9 | 0.0205 | 0.5317 | 0.0950 | 0.0760 | 0.1669 | 0.2299 | 0.6317 | 0.3038 | 0.9890 | 0.0470 |
| 10 | 0.5617 | 0.0470 | 0.2989 | 0.3953 | 0.3078 | 0.0955 | 0.0235 | 0.0675 | 0.0475 | 0.8826 |

### Pooled A vs B (10 runs merged per group)

| shots (A, B) | outcomes | TVD | null p50 | null p95 | null p99 | p | p SE | B | seed |
|---|---|---|---|---|---|---|---|---|---|
| 10000, 10000 | 32 | 0.0213 | 0.0127 | 0.0210 | 0.0252 | 0.0455 | 0.0047 | 2000 | 20261003 |

### Compilation sweep, optimization level 1 (baseline transpiler seed 0)

Identical transpiled circuits: 1/29 (p-values: ['1.0000']). Different physical footprints: 27/29, of which exceed null p95: 0.

| c seed_t | identical qasm3 | resources identical | TVD | null p95 | p | p SE | > p95 | Hellinger |
|---|---|---|---|---|---|---|---|---|
| 1 | no | False | 0.0530 | 0.0640 | 0.1759 | 0.0085 | no | 0.1414 |
| 2 | no | False | 0.0530 | 0.0640 | 0.1664 | 0.0083 | no | 0.1414 |
| 3 | no | False | 0.0530 | 0.0670 | 0.1749 | 0.0085 | no | 0.1414 |
| 4 | no | False | 0.0490 | 0.0660 | 0.2824 | 0.0101 | no | 0.1339 |
| 5 | no | False | 0.0450 | 0.0670 | 0.3473 | 0.0106 | no | 0.1418 |
| 6 | no | False | 0.0380 | 0.0640 | 0.5382 | 0.0111 | no | 0.1225 |
| 7 | no | False | 0.0450 | 0.0670 | 0.3358 | 0.0106 | no | 0.1418 |
| 8 | no | False | 0.0530 | 0.0660 | 0.1664 | 0.0083 | no | 0.1414 |
| 9 | no | False | 0.0450 | 0.0660 | 0.3193 | 0.0104 | no | 0.1418 |
| 10 | no | False | 0.0410 | 0.0630 | 0.4458 | 0.0111 | no | 0.1114 |
| 11 | no | False | 0.0490 | 0.0690 | 0.2639 | 0.0099 | no | 0.1339 |
| 12 | no | False | 0.0530 | 0.0650 | 0.1739 | 0.0085 | no | 0.1414 |
| 13 | no | False | 0.0530 | 0.0660 | 0.1629 | 0.0083 | no | 0.1414 |
| 14 | no | False | 0.0530 | 0.0640 | 0.1659 | 0.0083 | no | 0.1414 |
| 15 | no | False | 0.0290 | 0.0650 | 0.8096 | 0.0088 | no | 0.1143 |
| 16 | no | False | 0.0470 | 0.0640 | 0.2594 | 0.0098 | no | 0.1207 |
| 17 | no | False | 0.0530 | 0.0650 | 0.1694 | 0.0084 | no | 0.1414 |
| 18 | no | False | 0.0450 | 0.0660 | 0.3398 | 0.0106 | no | 0.1418 |
| 19 | no | True | 0.0180 | 0.0620 | 0.9915 | 0.0021 | no | 0.0930 |
| 20 | no | False | 0.0540 | 0.0620 | 0.1279 | 0.0075 | no | 0.1148 |
| 21 | no | False | 0.0170 | 0.0640 | 0.9980 | 0.0010 | no | 0.0593 |
| 22 | no | False | 0.0450 | 0.0660 | 0.3398 | 0.0106 | no | 0.1418 |
| 23 | no | False | 0.0450 | 0.0660 | 0.3458 | 0.0106 | no | 0.1418 |
| 24 | no | False | 0.0360 | 0.0640 | 0.5807 | 0.0110 | no | 0.1211 |
| 25 | no | False | 0.0290 | 0.0640 | 0.8136 | 0.0087 | no | 0.1143 |
| 26 | no | False | 0.0530 | 0.0650 | 0.1684 | 0.0084 | no | 0.1414 |
| 27 | no | False | 0.0530 | 0.0650 | 0.1814 | 0.0086 | no | 0.1264 |
| 28 | yes | True | 0.0000 | 0.0640 | 1.0000 | 0.0000 | no | 0.0000 |
| 29 | no | False | 0.0530 | 0.0650 | 0.1589 | 0.0082 | no | 0.1414 |

### Compilation sweep, optimization level 2 (baseline transpiler seed 0)

Identical transpiled circuits: 5/29 (p-values: ['1.0000']). Different physical footprints: 15/29, of which exceed null p95: 0.

| c seed_t | identical qasm3 | resources identical | TVD | null p95 | p | p SE | > p95 | Hellinger |
|---|---|---|---|---|---|---|---|---|
| 1 | no | False | 0.0490 | 0.0640 | 0.2379 | 0.0095 | no | 0.1265 |
| 2 | no | False | 0.0450 | 0.0650 | 0.3413 | 0.0106 | no | 0.1203 |
| 3 | no | False | 0.0390 | 0.0650 | 0.4703 | 0.0112 | no | 0.1286 |
| 4 | no | True | 0.0230 | 0.0640 | 0.9500 | 0.0049 | no | 0.1083 |
| 5 | no | True | 0.0210 | 0.0660 | 0.9720 | 0.0037 | no | 0.0533 |
| 6 | no | False | 0.0410 | 0.0650 | 0.4318 | 0.0111 | no | 0.1341 |
| 7 | no | True | 0.0230 | 0.0650 | 0.9470 | 0.0050 | no | 0.1083 |
| 8 | yes | True | 0.0000 | 0.0650 | 1.0000 | 0.0000 | no | 0.0000 |
| 9 | yes | True | 0.0000 | 0.0640 | 1.0000 | 0.0000 | no | 0.0000 |
| 10 | no | False | 0.0490 | 0.0650 | 0.2464 | 0.0096 | no | 0.1265 |
| 11 | no | False | 0.0390 | 0.0650 | 0.4958 | 0.0112 | no | 0.1286 |
| 12 | no | False | 0.0540 | 0.0670 | 0.1764 | 0.0085 | no | 0.1384 |
| 13 | no | False | 0.0570 | 0.0640 | 0.1164 | 0.0072 | no | 0.1404 |
| 14 | yes | True | 0.0000 | 0.0630 | 1.0000 | 0.0000 | no | 0.0000 |
| 15 | no | False | 0.0280 | 0.0640 | 0.8491 | 0.0080 | no | 0.1208 |
| 16 | no | True | 0.0320 | 0.0670 | 0.7176 | 0.0101 | no | 0.1206 |
| 17 | no | False | 0.0380 | 0.0660 | 0.5112 | 0.0112 | no | 0.1162 |
| 18 | no | False | 0.0240 | 0.0640 | 0.9085 | 0.0064 | no | 0.0889 |
| 19 | no | True | 0.0230 | 0.0650 | 0.9440 | 0.0051 | no | 0.1083 |
| 20 | yes | True | 0.0000 | 0.0630 | 1.0000 | 0.0000 | no | 0.0000 |
| 21 | no | True | 0.0210 | 0.0630 | 0.9760 | 0.0034 | no | 0.0533 |
| 22 | no | False | 0.0390 | 0.0650 | 0.4848 | 0.0112 | no | 0.1286 |
| 23 | no | True | 0.0210 | 0.0640 | 0.9735 | 0.0036 | no | 0.0533 |
| 24 | no | False | 0.0390 | 0.0660 | 0.4933 | 0.0112 | no | 0.1286 |
| 25 | no | False | 0.0280 | 0.0640 | 0.8531 | 0.0079 | no | 0.1208 |
| 26 | no | False | 0.0390 | 0.0650 | 0.4873 | 0.0112 | no | 0.1286 |
| 27 | no | True | 0.0230 | 0.0650 | 0.9535 | 0.0047 | no | 0.1083 |
| 28 | yes | True | 0.0000 | 0.0630 | 1.0000 | 0.0000 | no | 0.0000 |
| 29 | no | True | 0.0230 | 0.0640 | 0.9580 | 0.0045 | no | 0.1083 |

### Compilation sweep, optimization level 3 (baseline transpiler seed 0)

Identical transpiled circuits: 4/29 (p-values: ['1.0000']). Different physical footprints: 15/29, of which exceed null p95: 0.

| c seed_t | identical qasm3 | resources identical | TVD | null p95 | p | p SE | > p95 | Hellinger |
|---|---|---|---|---|---|---|---|---|
| 1 | no | False | 0.0280 | 0.0640 | 0.8511 | 0.0080 | no | 0.1082 |
| 2 | no | True | 0.0240 | 0.0650 | 0.9560 | 0.0046 | no | 0.1109 |
| 3 | no | False | 0.0370 | 0.0640 | 0.5317 | 0.0112 | no | 0.1133 |
| 4 | no | True | 0.0210 | 0.0640 | 0.9730 | 0.0036 | no | 0.1029 |
| 5 | no | True | 0.0210 | 0.0650 | 0.9760 | 0.0034 | no | 0.1029 |
| 6 | no | False | 0.0390 | 0.0660 | 0.5087 | 0.0112 | no | 0.1302 |
| 7 | no | False | 0.0390 | 0.0650 | 0.4743 | 0.0112 | no | 0.1261 |
| 8 | no | False | 0.0370 | 0.0650 | 0.5312 | 0.0112 | no | 0.1133 |
| 9 | yes | True | 0.0000 | 0.0640 | 1.0000 | 0.0000 | no | 0.0000 |
| 10 | yes | True | 0.0000 | 0.0640 | 1.0000 | 0.0000 | no | 0.0000 |
| 11 | no | False | 0.0390 | 0.0660 | 0.5132 | 0.0112 | no | 0.1261 |
| 12 | no | False | 0.0550 | 0.0650 | 0.1434 | 0.0078 | no | 0.1378 |
| 13 | no | True | 0.0280 | 0.0650 | 0.8521 | 0.0079 | no | 0.1054 |
| 14 | yes | True | 0.0000 | 0.0640 | 1.0000 | 0.0000 | no | 0.0000 |
| 15 | no | False | 0.0280 | 0.0650 | 0.8621 | 0.0077 | no | 0.1082 |
| 16 | no | True | 0.0210 | 0.0650 | 0.9790 | 0.0032 | no | 0.1029 |
| 17 | no | True | 0.0240 | 0.0650 | 0.9570 | 0.0045 | no | 0.1109 |
| 18 | no | False | 0.0240 | 0.0640 | 0.9345 | 0.0055 | no | 0.0895 |
| 19 | no | True | 0.0210 | 0.0640 | 0.9770 | 0.0034 | no | 0.1029 |
| 20 | no | False | 0.0390 | 0.0650 | 0.5102 | 0.0112 | no | 0.1261 |
| 21 | no | False | 0.0190 | 0.0630 | 0.9910 | 0.0021 | no | 0.0736 |
| 22 | no | False | 0.0390 | 0.0660 | 0.4978 | 0.0112 | no | 0.1261 |
| 23 | no | True | 0.0210 | 0.0630 | 0.9715 | 0.0037 | no | 0.1029 |
| 24 | no | False | 0.0390 | 0.0660 | 0.5052 | 0.0112 | no | 0.1261 |
| 25 | no | False | 0.0280 | 0.0650 | 0.8546 | 0.0079 | no | 0.1082 |
| 26 | no | False | 0.0390 | 0.0650 | 0.5102 | 0.0112 | no | 0.1261 |
| 27 | no | True | 0.0210 | 0.0630 | 0.9755 | 0.0035 | no | 0.1029 |
| 28 | yes | True | 0.0000 | 0.0640 | 1.0000 | 0.0000 | no | 0.0000 |
| 29 | no | True | 0.0210 | 0.0640 | 0.9875 | 0.0025 | no | 0.1029 |

### P5: Monte Carlo stability (B=2000, seeds 1000-1019)

| counts | mean p | SD of p | SE at mean p | SD / SE |
|---|---|---|---|---|
| pooled_A_vs_B | 0.0551 | 0.0052 | 0.0051 | 1.0216 |
| groupA_sim1_vs_sim2 | 0.0794 | 0.0055 | 0.0060 | 0.9121 |

- pooled_A_vs_B p-values by seed: 1000: 0.0505, 1001: 0.0590, 1002: 0.0545, 1003: 0.0495, 1004: 0.0520, 1005: 0.0540, 1006: 0.0515, 1007: 0.0595, 1008: 0.0625, 1009: 0.0415, 1010: 0.0620, 1011: 0.0605, 1012: 0.0515, 1013: 0.0615, 1014: 0.0595, 1015: 0.0565, 1016: 0.0565, 1017: 0.0525, 1018: 0.0530, 1019: 0.0545
- groupA_sim1_vs_sim2 p-values by seed: 1000: 0.0720, 1001: 0.0820, 1002: 0.0865, 1003: 0.0800, 1004: 0.0695, 1005: 0.0805, 1006: 0.0880, 1007: 0.0895, 1008: 0.0765, 1009: 0.0720, 1010: 0.0795, 1011: 0.0750, 1012: 0.0825, 1013: 0.0785, 1014: 0.0870, 1015: 0.0800, 1016: 0.0755, 1017: 0.0750, 1018: 0.0785, 1019: 0.0815

### D1: GHZ population P(00000) + P(11111) (descriptive)

| sim seed | A population | A SE | B population | B SE |
|---|---|---|---|---|
| 1 | 0.8930 | 0.0098 | 0.8970 | 0.0096 |
| 2 | 0.9070 | 0.0092 | 0.9050 | 0.0093 |
| 3 | 0.8950 | 0.0097 | 0.8940 | 0.0097 |
| 4 | 0.9130 | 0.0089 | 0.9120 | 0.0090 |
| 5 | 0.9150 | 0.0088 | 0.9170 | 0.0087 |
| 6 | 0.9020 | 0.0094 | 0.9040 | 0.0093 |
| 7 | 0.8990 | 0.0095 | 0.8980 | 0.0096 |
| 8 | 0.9140 | 0.0089 | 0.9080 | 0.0091 |
| 9 | 0.8940 | 0.0097 | 0.9000 | 0.0095 |
| 10 | 0.8960 | 0.0097 | 0.8980 | 0.0096 |

| quantity | value | SE |
|---|---|---|
| pooled A (10000 shots) | 0.9028 | 0.0030 |
| pooled B (10000 shots) | 0.9033 | 0.0030 |
| B minus A | 0.0005 | 0.0042 |

### D2: Hellinger distance (descriptive, no sampling floor)

| set | n | min | median | mean | max |
|---|---|---|---|---|---|
| within_A | 45 | 0.0706 | 0.0910 | 0.0908 | 0.1126 |
| within_B | 45 | 0.0445 | 0.0792 | 0.0779 | 0.1013 |
| between | 100 | 0.0742 | 0.1217 | 0.1198 | 0.1445 |

Pooled A vs B Hellinger distance: 0.0857

Runtime: run creation 187.5 s, analysis 19.8 s.

## Discussion

### Predictions

| Prediction | Result | Marking | Reasoning |
|---|---|---|---|
| P1 | A: 1/45 exceedances; B: 0/45 | **matched** | Both groups fall in the pre-registered 0–6 range. |
| P2 | p < 0.1: A 6/45, B 1/45; deciles A [6,3,6,5,4,8,3,4,6,0], B [1,6,4,5,3,5,4,6,5,6] | **matched** | Both groups are at or below the threshold of 9. Neither shows a pile-up near 0. |
| P3 | 100 pairs: p median 0.306, 12/100 below 0.05, 22/100 below 0.1. Pooled: TVD 0.0213, null p95 0.0210, p 0.0455 (seed 20261003) | **inconclusive** (by the pre-registered rule) | The premise holds: A and B have different transpiled qasm3 hashes. P3 predicted no outcome. |
| P4 | Identical-circuit pairs: 1 (level 1), 5 (level 2), 4 (level 3), all with TVD 0 and p = 1.0000. Different-footprint pairs: 0/57 exceed null p95 | **matched** (degenerate) | As noted before running, identical circuits with the same simulator seed give identical counts. The different-footprint half was descriptive only. |
| P5 | SD/SE: pooled 1.02 (mean p 0.0551); Group A seed 1 vs 2: 0.91 (mean p 0.0794) | **matched** | Both ratios are close to 1 and well below 2. The reported Monte Carlo standard error matches the observed seed-to-seed spread. |

No prediction was marked not matched. The statistic and the analysis were not changed after
the results were seen.

### Findings beyond the marked predictions

These are observations, not marked results. The split below was done after seeing the
results and was not pre-registered.

1. **Shared simulator seeds correlate samples.** In the between-group matrix, the 10 diagonal
   pairs share a simulator seed. They have p-values 0.62–0.99 (median 0.92) and median TVD
   0.0255. The 90 off-diagonal pairs have median p 0.277 and median TVD 0.0475. All 12
   between-group pairs with p < 0.05 are off-diagonal: 12/90, about 13%. A and B use the same
   physical qubits and operations; their circuits differ only in rz angles, two-ECR ordering
   and which physical qubits measure classical bits 1 and 2. With nearly identical circuits,
   the same simulator seed drives nearly the same random draws, so the two samples are
   positively correlated. That violates the floor's assumption of independent samples, and in
   this direction the p-values come out larger than independent sampling would give. The
   compilation sweep fixes simulator seed 7 for every run, so its re-score has the same issue.
   Many same-resource sweep pairs show p > 0.9 and repeated TVD values (for example, 0.0530
   eleven times at level 1). **The sweep re-score is therefore not a valid test of the floor
   on different compilations.** A fair re-score needs independent simulator seeds per run.
2. **Pooled A vs B sits at the boundary.** Pooled TVD (0.0213) is just above null p95
   (0.0210), with p = 0.0455 at seed 20261003. Across the 20 P5 seeds, p ranges from
   0.0415 to 0.0625 (mean 0.0551). Whether this p-value falls below 0.05 depends on the
   resampling seed. With 10000 shots per side, these data neither clearly show nor rule out a
   difference between the A and B empirical distributions. No significance claim is made.
3. **Group A's top decile is empty** (0/45 pairs with p ≥ 0.9), while Group B has 6/45.
   The pairs share runs, so the 45 p-values per group are strongly dependent. Uniform
   p-values would put 4.5 pairs in this decile. This is noted but not interpreted.

### D1: GHZ population (descriptive)

Per-run populations lie between 0.893 and 0.917, with binomial SE about 0.009 (table above).
Pooled: A 0.9028 ± 0.0030, B 0.9033 ± 0.0030. B minus A is 0.0005 ± 0.0042.

### D2: Hellinger distance (descriptive, hypothesis-generating only)

Median Hellinger distance is 0.091 within A, 0.079 within B and 0.122 between groups. The
off-diagonal between-group median, on independent simulator seeds, is 0.123. The pooled A vs
B distance is 0.086. Hellinger has no sampling floor, so these numbers have no reference
distribution. One hypothesis, not tested here: A and B have nearly equal GHZ populations
(D1), but they route the circuit differently and swap the physical qubits measuring bits 1
and 2. Their error outcomes could therefore fall on different bitstrings. That would affect
distances over the full distribution, which weight the rare error outcomes, but not the GHZ
population. M2's workload-specific observables would be the place to look.

### Scope statement

All runs used `fake_sherbrooke`: a static noise model and calibration simulated locally with
qiskit-aer. **None of these results is evidence about real hardware.** They say nothing
about drift, about shots within a job being independent and identically distributed on a
QPU, or about how a real device behaves across compilations. They check only the M1.1 TVD
sampling floor against draws from its own null on simulated data.
