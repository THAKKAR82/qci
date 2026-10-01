# Product

## Vision

QCI aims to become a vendor-neutral reliability and execution-intelligence layer for quantum
computing. The platform should eventually answer questions like these:

- Did this quantum workload actually improve?
- Did a regression come from the source code, from compilation, from statistical variation, or
  from hardware drift?
- Which available backend is most likely to run this specific workload successfully?
- Which execution strategy fits a given set of reliability, cost and latency requirements?
- Can an execution result be independently validated?
- How has this workload behaved historically across hardware and calibration states?

## Possible progression

This is a direction, not a commitment. Each step builds on data that the previous steps capture.

1. Quantum CI
2. Experiment system of record
3. Regression detection
4. Regression attribution
5. Quantum observability
6. Hardware and backend intelligence
7. Backend recommendation
8. Workload routing
9. Result validation
10. Vendor-neutral reliable quantum execution

## V1: Quantum CI

V1 is the instrumentation and regression foundation. The target workflow is:

```bash
qci run examples/bell.py --backend fake_sherbrooke
qci runs
qci show RUN_ID
qci compare RUN_A RUN_B
qci test --baseline BASELINE
```

V1 is delivered in small slices, which `PLAN.md` tracks:

| Milestone | Delivers |
|---|---|
| M0 | `run`, `runs` and `show`, with an immutable and inspectable run record |
| M0.5 | Raw artifact archival, fuller provenance and ideal-distribution quality metrics |
| M1 | `compare`, with statistically labeled differences between two runs |
| Later | `test --baseline` and regression detection |

## Who it is for, initially

Developers and researchers who write Qiskit workloads and want to know whether a change to
their code, the compiler settings or the target backend changed the outcome. The first
environment is local fake backends, so it needs no paid hardware.

## Product principles

- **Vendor-neutral internally.** IBM is the first adapter, not the architecture.
- **Raw data is an asset.** The historical dataset may become the most valuable thing QCI owns,
  so nothing is discarded merely because QCI does not use it yet.
- **No fabricated certainty.** Every number says how it was obtained. Attribution is a research
  problem and is never presented as proven when it is a heuristic.
- **Reliability product, reliable code.** Tests are part of the product.

## Explicitly out of scope for V1

Web UI, authentication, organizations, billing, machine learning models, automatic routing,
hosted or cloud infrastructure, and paid QPU access in tests.
