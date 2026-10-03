# QCI

QCI records exactly what happened when a quantum workload ran, so that you can later tell
whether it got better or worse and why.

Long term, QCI aims to be a vendor-neutral reliability and execution-intelligence layer for
quantum computing. Today it is the first building block: an instrumented runner that captures
an immutable, inspectable record of each execution.

**Status:** pre-alpha, milestone M1. IBM/Qiskit fake backends only.

## Quick start

```bash
python3.13 -m venv .venv
.venv/bin/pip install -e '.[dev]'

.venv/bin/qci run examples/bell.py --backend fake_sherbrooke --seed 7
.venv/bin/qci runs
.venv/bin/qci show <RUN_ID>
.venv/bin/qci show <RUN_ID> --json
.venv/bin/qci compare <BASELINE_RUN_ID> <CANDIDATE_RUN_ID> [--json]
```

### Seeds

`--seed N` seeds both the transpiler and the simulator. To vary one source of randomness while
holding the other fixed, use the stage-specific flags. A specific flag overrides `--seed` for its
stage only:

```bash
qci run examples/bell.py --backend fake_sherbrooke --seed 7                       # transpiler 7, simulator 7
qci run examples/bell.py --backend fake_sherbrooke --seed 7 --seed-simulator 8    # transpiler 7, simulator 8
qci run examples/bell.py --backend fake_sherbrooke --seed 7 --seed-transpiler 9   # transpiler 9, simulator 7
```

A stage with no seed is unseeded, and Qiskit chooses its own randomness, so its output may
differ between runs. The effective seeds are stored separately on the compilation and execution
records. `qci compare` reports them under compilation and execution respectively.

`qci compare` reports what changed from a baseline run to a candidate run. It covers source,
environment, circuits, compilation, execution, the physical qubits and operations the
transpiled circuit used, the calibration of those exact resources, and the result
distributions. It makes no better/worse, regression or causal claims.

Two terms need care when reading a comparison:
- **A changed result distribution** means the observed, sampled distributions differ. It does
  not mean the underlying probability distribution changed, or that the difference is
  statistically significant.
- **Relevant hardware** means calibration data for the physical resources the workload actually
  used. It does not mean those parameters are known to affect the result, or that a calibration
  change caused a result change.

No IBM account or network access is needed. `fake_sherbrooke` is a local simulator that uses
a frozen IBM calibration snapshot as its noise model.

## What a run captures (M0)

- Git commit, branch, dirty state and remote, plus the Python and Qiskit versions.
- The workload source file hash and entrypoint.
- Logical and transpiled circuit summaries, including OpenQASM 3 text.
- The transpiler configuration, seed and layout.
- The backend's identity and calibration snapshot, with the raw provider payload kept verbatim.
- The execution configuration, timing and measured counts.
- Labeled metrics, where each value states whether it was measured or calculated.

Runs are stored in `./.qci/qci.db` (SQLite) by default. Set `QCI_HOME` to use another location.

## Writing a workload

A workload is a Python file with a `build()` function that returns a Qiskit `QuantumCircuit`:

```python
from qiskit import QuantumCircuit


def build() -> QuantumCircuit:
    qc = QuantumCircuit(2, 2, name="bell")
    qc.h(0)
    qc.cx(0, 1)
    qc.measure([0, 1], [0, 1])
    return qc
```

Use `--entrypoint NAME` to call a different function.

## Documentation

- [PLAN.md](PLAN.md): milestones, acceptance criteria and open decisions.
- [docs/product.md](docs/product.md): product vision and V1 scope.
- [docs/architecture.md](docs/architecture.md): module boundaries and ports.
- [docs/data-model.md](docs/data-model.md): the Run record, identity and schema versioning.
- [docs/research.md](docs/research.md): research hypotheses and what data supports them.
- [docs/adr/](docs/adr/): architecture decision records.
