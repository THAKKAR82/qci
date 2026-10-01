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
  This directly shapes M1.
- **Probe design.** What is the cheapest probe set that carries real predictive information?

## Not now

No ML models, no predictors and no routing. Dataset export tooling will be designed when
enough real runs exist to justify it.
