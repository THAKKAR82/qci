# Research

QCI is built in parallel with research on predicting quantum execution quality. The software's
job is to make **collecting trustworthy datasets easy**. It must not encode conclusions before
the research supports them.

## Central question

Can we predict which quantum computer will run a particular workload most successfully, using
circuit characteristics, compilation results, historical behavior, calibration data and
possibly lightweight live probes?

## Hypotheses

| ID | Hypothesis | Data QCI must capture |
|---|---|---|
| H1 | Workload-aware features predict quality better than backend-average calibration metrics. | Circuit structure, the transpiled circuit, the per-qubit and per-gate calibration actually used, and quality metrics |
| H2 | Historical execution behavior adds information beyond current calibration data. | Repeated runs over time with snapshot timestamps |
| H3 | Lightweight diagnostic circuits reveal current backend health. | Probe runs stored as ordinary runs, linked by time to workload runs |
| H4 | The interaction between circuit topology and backend topology strongly affects quality. | Two-qubit interaction edges, layout, coupling map and per-edge errors |

These are hypotheses, not facts. QCI must not hard-code which variables matter.

## What M0 already preserves for research

- **Logical structure:** depth, op counts and two-qubit interaction edges, for H1 and H4.
- **Transpiled structure and layout:** physical qubits used, for H1 and H4.
- **Raw calibration and configuration payloads,** kept verbatim, so features nobody has thought
  of yet can still be extracted later.
- **Seeds, shots, compiler settings and versions,** to separate compilation effects from
  hardware effects.
- **Calibration time versus capture time,** to measure staleness, for H2.

## Data-quality rules

1. **Label provenance honestly.** Fake-backend runs use a frozen calibration snapshot and a
   simulator. They are useful for building the pipeline but are **not** evidence about real
   hardware. Every such run carries `source=static_fake`, and analysis must filter on it.
2. **Never mix evidence kinds.** A statistical estimate is not a measurement, and a model
   prediction is not a causal claim.
3. **Keep failures.** Failed runs are part of the reliability distribution.
4. **Immutable history.** Do not recompute stored values in place. Derived datasets are
   regenerated from raw records with versioned methods.

## Open research questions affecting the software

- **Circuit and workload identity.** What makes two runs "the same workload" for comparison
  and for training data? See `docs/data-model.md`.
- **Metric choice.** Which quality metric fits which workload class? The candidates are
  Hellinger fidelity or TVD against an ideal, which only works when the ideal is computable,
  task-specific success probability, and expectation values.
- **Ground truth at scale.** How should quality be measured for circuits too large to simulate?
- **Snapshot granularity.** Is one calibration snapshot per run enough, or is calibration
  history between runs needed?
- **Statistical design.** How many repetitions are needed before two runs can be distinguished?
  M1.1 adds a computed sampling floor for TVD, and M1.1v validates it against repeated
  seeded runs.
- **Probe design.** What is the cheapest probe set that carries real predictive information?
- **SDK-level reproducibility hazards.** These were found while building M0.
  `qiskit_ibm_runtime.SamplerV2` local mode silently ignores `seed_simulator=0`. Qiskit's
  default `optimization_level` is 2, and a different level produced a different layout and
  different counts for the same seed. Recorded configuration must therefore always be explicit,
  never "whatever the default was". How many other silent defaults affect results?
- **Active-qubit representation.** A transpiled circuit spans the whole device. Which
  representation of "qubits actually used" should research features use: layout, interaction
  edges, or idle qubits as well, given that crosstalk may matter? See D12 in `PLAN.md`.
- **Calibration staleness in fake data.** `fake_sherbrooke`'s calibration dates from
  2025-02-26. Any feature built on fake snapshots learns about a frozen device, which reinforces
  the `static_fake` filtering rule.

## The physical footprint (M1)

M1 introduces the **workload-relevant physical footprint**: the physical qubits and native
operations, with ordered qubit arguments, that the final transpiled circuit actually uses. It
is the unit for scoping hardware evidence to a workload, which bears directly on H1 and H4.
Facts established while building it:

- **No native SWAP on this backend.** On `fake_sherbrooke`, routing swaps appear as `ecr` plus
  single-qubit sequences. The footprint reports what is in the final circuit.
- **Two-qubit direction matters.** IBM calibration exists for `ecr (104,103)` but not for
  `(103,104)`. Undirected edges are not a valid scope for hardware evidence.
- **Measurement calibration lives under qubits.** IBM reports readout under each qubit, with no
  per-measure gate entry.
- **Pairwise keys are ambiguous.** IBM `general` pairwise couplings such as `jq_6272` use a
  key that does not unambiguously name two qubits, so they are excluded from scoping.
- **Delays need explicit scheduling.** Workloads with a `delay` fail to transpile on this fake
  backend unless a scheduling method is set, which M0 and M1 don't expose.
- **Mapping changes defeat time-series comparison.** When the physical mapping changes, the
  same logical workload runs on different physical resources. Per-resource time series are only
  meaningful for resources that are physically identical across runs. How to compare workloads
  whose footprints differ is an open research question. M1.3 adds footprint-scoped
  snapshot-to-snapshot comparison for a fixed footprint. Comparing differing footprints stays
  in the deferred backlog.

## Not now

No ML models, no predictors and no routing. Dataset export tooling will be designed when
enough real runs exist to justify it.
