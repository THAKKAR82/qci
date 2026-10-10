# QCI

QCI records exactly what happened when a quantum workload ran, so that you can later see
precisely what differed between two executions.

Long term, QCI aims to be a vendor-neutral reliability and execution-intelligence layer for
quantum computing. Today it is the first building block: an instrumented runner that captures
an immutable, inspectable record of each execution.

**Status:** pre-alpha. See [PLAN.md](PLAN.md) for the current milestone and step.

## Quick start

```bash
python3.13 -m venv .venv
.venv/bin/pip install -e '.[dev]'

.venv/bin/qci run examples/bell.py --backend fake_sherbrooke --seed 7
.venv/bin/qci runs
.venv/bin/qci show <RUN_ID>
.venv/bin/qci show <RUN_ID> --json
.venv/bin/qci compare <BASELINE_RUN_ID> <CANDIDATE_RUN_ID> [--json] [--observable NAME=BITS[,BITS...]]
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

### Observables

`--observable NAME=BITS[,BITS...]` adds a workload-specific figure of merit: the probability that
a shot's outcome is in the given bitstring set. It is repeatable. For a 5-qubit GHZ state:

```bash
qci compare A B --observable ghz=00000,11111
```

Each run gets k/n with a Wilson 95% score interval, and the difference (candidate minus
baseline) gets a Newcombe hybrid score interval. The intervals describe sampling uncertainty at
the observed shot counts. They are not verdicts. Observables reuse the result-distribution
comparability gate: when it fails, each observable is `not_comparable` with the same reasons.
When both runs were simulated with the same simulator seed, their samples are not independent,
so the Newcombe interval is not computed and the output says why. Each run's estimate, its
Wilson interval and the point delta are still shown.

Bitstrings must match the provider's counts keys verbatim. For Qiskit, classical bit 0 is the
**rightmost** character, so in a 3-bit register `001` means bit 0 is 1. A bitstring that was
never observed counts as 0. Bitstrings of the wrong width, or with characters other than 0 and
1, are rejected.

No IBM account or network access is needed. `fake_sherbrooke` is a local simulator that uses
a frozen IBM calibration snapshot as its noise model.

## Calibration snapshots (live IBM hardware, read-only)

QCI can read the calibration an IBM backend currently publishes and store it as an immutable
snapshot. It executes nothing on hardware and costs no QPU time. This is the only QCI command
that uses the network.

**Prerequisite: a saved IBM account.** Save it once with Qiskit's own API. QCI never asks for,
stores, logs or prints a token, and it never reads credentials from environment variables:

```python
from qiskit_ibm_runtime import QiskitRuntimeService

QiskitRuntimeService.save_account(token="...", instance="...", name="default-ibm-quantum-platform")
```

```bash
qci snapshot capture --backend ibm_fez [--account default-ibm-quantum-platform]
qci snapshots [--backend ibm_fez] [--limit N]
qci snapshot show <SNAPSHOT_ID> [--json]
qci snapshot export <SNAPSHOT_ID> --fixture PATH [--account NAME]   # developers: test fixture
```

- `capture` reads once and exits. It does no polling, scheduling or retries. Run it again to
  record another point in time. Content identical to an existing snapshot is stored once, and
  the repeat is recorded as another capture.
- Fake backends (`fake_*`) and simulators are rejected with exit code 2, because frozen fake
  calibration must never be stored as live data. On any other error nothing is stored and the
  exit code is 1.
- Credential-like values in the payload (tokens, instance CRNs, URLs, emails and similar) are
  replaced with `{"$redacted": "<rule>"}` before storage, and their paths are listed.
- History is forward-only: it starts at your first capture.
- `calibrated_at` is the provider's own `last_update_date` for the properties document.
  Individual parameters carry their own dates.

Snapshots are stored in the same `qci.db` as runs, in separate tables.

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
- [docs/data-model.md](docs/data-model.md): the Run record, calibration snapshots, identity and
  schema versioning.
- [docs/research.md](docs/research.md): research hypotheses and what data supports them.
- [docs/adr/](docs/adr/): architecture decision records.

## Website

The static marketing page lives in `site/`: `site/index.html` with `styles.css`, `script.js`,
`bloch-sphere.js`, and synthetic examples in `demo-fixtures.js`. It is independent of the Python
package, has no build step, and is not covered by the product gates. Preview it locally from
the repository root with:

```bash
python3 -m http.server 8765 --bind 127.0.0.1 --directory site
```

Then open http://127.0.0.1:8765/.

The contact section is deliberately unconfigured in the draft. Set a monitored email address or
a form endpoint in `site/site-config.js` before publishing. A form endpoint must acknowledge
receipt with JSON `{"received": true}`; the page shows success only after that response.
