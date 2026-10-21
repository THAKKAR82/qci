# QCI

QCI records exactly what happened when a quantum workload ran, and reports precisely what
differs between two runs.

Quantum results move for many reasons at once: sampling noise, a different transpiler seed, a
different qubit mapping, a new calibration of the device, a new package version. Without a
record, two runs that disagree leave you guessing which of these changed. QCI keeps an
immutable, inspectable record of each run (source, environment, circuits, compilation,
backend calibration and counts) and compares two records section by section, so you can see
what changed, and by how much, before you decide what it means.

QCI is at version 0.1.0 and runs on Python 3.12 and 3.13. Today it supports IBM Quantum
through Qiskit: workloads run on local simulators of IBM devices, and calibration is read from
the devices themselves. Its core is provider-neutral.

## Install

Install into a virtual environment. With the `ibm` extra, QCI can run workloads on local IBM
simulators and read IBM calibration data:

```bash
python -m pip install 'bloq-qci[ibm]'
```

The core install has no provider SDK. It lists, shows and compares runs and snapshots that are
already in your store, and runs `qci where` and `qci doctor`:

```bash
python -m pip install bloq-qci
```

`qci run`, `qci snapshot capture`, `qci snapshot backfill` and `qci snapshot export` need the
extra. Without it they exit with code 2 and print the install command. The `ibm` extra
installs `qiskit`, `qiskit-ibm-runtime` (below 0.51, the version whose behavior QCI verifies)
and `qiskit-aer`. The distribution is named `bloq-qci`; the command and the Python package are
`qci`.

## Quickstart (about five minutes)

Install into a fresh virtual environment (Python 3.12 or 3.13):

```bash
python3 -m venv qci-env
source qci-env/bin/activate
python -m pip install 'bloq-qci[ibm]'
qci doctor
qci where
```

Write a two-qubit workload:

```bash
cat > bell.py <<'EOF'
from qiskit import QuantumCircuit


def build() -> QuantumCircuit:
    qc = QuantumCircuit(2, 2, name="bell")
    qc.h(0)
    qc.cx(0, 1)
    qc.measure([0, 1], [0, 1])
    return qc
EOF
```

Run it twice on a local simulator of the `ibm_fez` device, with different sampling seeds,
then compare the two runs (baseline first):

```bash
qci run bell.py --backend fake_fez --seed 7
qci run bell.py --backend fake_fez --seed 7 --seed-simulator 8
qci runs
qci compare 'latest~1' latest
qci compare 'latest~1' latest --observable bell=00,11
qci compare 'latest~1' latest --verbose
```

`fake_fez` runs on your machine with a frozen copy of IBM's calibration as its noise model.

### Optional: compare with live calibration (needs an IBM Quantum account)

Save your account once, in an interactive Python session so the token stays out of your
shell history:

```python
from qiskit_ibm_runtime import QiskitRuntimeService

QiskitRuntimeService.save_account(token="...", instance="...", name="default-ibm-quantum-platform")
```

Then read the calibration `ibm_fez` publishes now (read-only: nothing runs on the device)
and compare it with the calibration frozen into `fake_fez`, for the qubits your run used:

```bash
qci doctor
qci snapshot capture --backend ibm_fez
qci snapshot compare-run latest ibm_fez:latest
```

## Core ideas

### Runs

A run is one execution of a workload: a Python file with a `build()` function that returns a
Qiskit `QuantumCircuit` (`--entrypoint NAME` calls another function). `qci run` records:

- the workload's source hash, and the git commit, branch and dirty state of its directory;
- the Python version, the platform and the versions of QCI and the provider packages;
- the logical and transpiled circuits, including their OpenQASM 3 text;
- the transpiler settings, seed and qubit layout;
- the backend's identity and calibration, with the provider's raw payload kept verbatim;
- the execution settings, timing and measured counts;
- labeled metrics: each value says whether it was measured or calculated, and how.

Runs are immutable: QCI writes each record once and never edits or deletes it. A run that
stops with an error after its workload loaded is still recorded, with the stage where it
stopped and the error. `--seed N` seeds both the transpiler and the simulator;
`--seed-transpiler` and `--seed-simulator` set one stage each and take precedence for it, so
you can vary one source of randomness while holding the other fixed.

### Comparisons

`qci compare BASELINE CANDIDATE` reports what differs from the baseline run to the candidate
run, section by section: source, environment, logical circuit, compilation, execution,
backend, physical footprint, calibration of that footprint, and result distribution. Every
delta is candidate minus baseline. The default output is a short summary: each section's
status, the names of the fields that differ, the key statistics and the calibration
magnitudes. `--verbose` adds the full detail, and `--json` prints the complete comparison as
JSON. Comparisons are computed when you ask for them and are never stored.

Two terms need care:

- **A changed result distribution** means the observed, sampled distributions differ. It does
  not mean the underlying probability distribution changed.
- **Relevant hardware** means the calibration of the physical resources the workload used. It
  does not mean those parameters are known to affect the result.

### The sampling floor

Two samples from one distribution almost never give identical counts, so their total
variation distance (TVD) is rarely 0. The sampling floor estimates how large TVD would be from
sampling alone: QCI pools both runs' counts as one shared distribution, draws 2000 pairs of
samples of the observed sizes from it, and reports the 50th, 95th and 99th percentiles of
their TVD, plus a Monte Carlo p-value: (1 + the number of resampled TVDs at least as large
as the observed one) / 2001. The resampling is seeded from the comparison, so the numbers are reproducible.
When both runs were simulated with the same simulator seed, their samples are not
independent, and QCI does not compute the floor; the output says why. The Hellinger distance
is reported without a floor.

### Observables

`--observable NAME=BITS[,BITS...]` adds a workload-specific figure: the probability that a
shot's outcome is in the given set of bitstrings. It is repeatable. For each run QCI reports
k of n shots with a Wilson 95% interval, and for the difference (candidate minus baseline) a
Newcombe 95% interval. The intervals describe sampling uncertainty at the observed shot
counts.

Bitstrings must match the provider's counts keys exactly. For Qiskit, classical bit 0 is the
**rightmost** character, so in a 3-bit register `001` means bit 0 is 1. A bitstring that was
never observed counts as 0, and bitstrings of the wrong width are rejected.

### Footprints

A run's physical footprint is the set of physical qubits and operations its transpiled
circuit used, read from the stored OpenQASM 3 text. Calibration is compared only for
resources that are in both runs' footprints, one resource with itself: QCI never compares the
calibration of qubit 3 in one run with qubit 5 in another. When two runs used different
qubits, the comparison says so and compares only what they share. A missing calibration value
is reported as unavailable, never as 0.

The summary gives, for each calibration parameter of the footprint (grouped by qubit or
operation, parameter name and unit), how many resources were compared and how many differ,
and the median and largest absolute and relative deltas, each largest one naming its
resource. A baseline of exactly 0 has no relative delta and is counted as "baseline 0".

### Snapshots

A calibration snapshot is the calibration document a device publishes, stored as an immutable
record in the same store as your runs. Snapshots are read-only: nothing runs on the device.

- `qci snapshot capture --backend ibm_fez` reads the calibration the device publishes now,
  once. Capturing identical content again records one more capture of the same snapshot.
- `qci snapshot backfill --backend ibm_fez --days N` looks up documents the device published
  in the past, one request per grid time (one UTC midnight per day by default), bounded per
  invocation and resumable. Backfilled history is documents by the provider's time stamp, not
  what a user would have seen at a given time.
- `qci snapshot compare BASELINE CANDIDATE --footprint-run RUN` compares two snapshots for the
  footprint of one run. The run only selects which qubits and operations are read.
- `qci snapshot compare-run RUN SNAPSHOT` compares the calibration frozen into a fake
  backend, as recorded in a run, with a live snapshot of the device the fake was built from
  (`fake_fez` with `ibm_fez`, `fake_kingston` with `ibm_kingston`, `fake_marrakesh` with
  `ibm_marrakesh`). Deltas are live minus fake. It compares calibration data, not the noise
  model a simulator builds from it.

Fakes and simulators cannot be captured, a parameter whose unit differs between the two sides
is not compared, and units are never converted.

### Re-measured versus carried over

Each calibration value carries the date the provider measured it. When a value is the same in
both snapshots, QCI says which of three cases it is:

- **re-measured, same value:** the measurement date changed, and the new measurement gave the
  same value;
- **not re-measured:** the date is the same, so it is one measurement carried over and
  reported twice. This is not evidence that the value held constant between the captures;
- **measurement date unavailable:** the provider gave no date.

## Command reference

| Command | What it does | Needs `ibm` |
|---|---|---|
| `qci run WORKLOAD --backend NAME` | Run a workload on a local simulator and record it. Options: `--seed`, `--seed-transpiler`, `--seed-simulator`, `--shots` (default 1000), `--optimization-level` (default 2), `--entrypoint`, `--tag KEY=VALUE`. | yes |
| `qci runs` | List recorded runs, newest first (`--limit`, default 20). | no |
| `qci show RUN` | Show a run (`--json` for the full record). | no |
| `qci compare BASELINE CANDIDATE` | Compare two runs (`--observable`, `--verbose`, `--json`). | no |
| `qci snapshot capture --backend NAME` | Read a device's current calibration once and store it. Uses the network. | yes |
| `qci snapshot backfill --backend NAME --days N` | Look up past calibration documents (`--step-hours`, `--max-requests`, `--pause`). Uses the network. | yes |
| `qci snapshots` | List stored snapshots (`--backend`, `--limit`). | no |
| `qci snapshot show SNAPSHOT` | Show a snapshot (`--json`). | no |
| `qci snapshot compare BASELINE CANDIDATE --footprint-run RUN` | Compare two snapshots for a run's footprint (`--allow-footprint-backend-mismatch`, `--verbose`, `--json`). | no |
| `qci snapshot compare-run RUN SNAPSHOT` | Compare a fake-backend run's frozen calibration with a live snapshot (`--verbose`, `--json`). | no |
| `qci snapshot export SNAPSHOT --fixture PATH` | Write a sanitized test fixture, for developers. | yes |
| `qci where` | Print the path of the store file in use. | no |
| `qci doctor` | Check the installation, the saved account and the store. | no |

`capture`, `backfill` and `export` take `--account NAME`, the name of a saved IBM account
(default `default-ibm-quantum-platform`). Exit codes: 0 when the command did what was asked;
1 when something was not found, a selector is ambiguous, a run stopped with an error, a
capture or lookup request returned an error, the store is damaged, or a `qci doctor` check
reports a problem; 2 for a usage error, a workload that cannot be loaded, a missing `ibm`
extra, or a backend that `capture` or `backfill` does not accept (a fake, a simulator, or a
lookup beyond the device's verified depth).

### Selecting runs and snapshots

Every argument that names a run or a snapshot accepts:

| Form | Selects |
|---|---|
| `01M5E0T0VJBDHTTA4YJW9NXVC5` | The run or snapshot with this ID. |
| `01M5E0T0` | The one ID that starts with this prefix of 8 to 25 characters. |
| `latest`, `'latest~1'`, `'latest~2'` | Runs: the newest, the one before, and so on, as `qci runs` lists them. |
| `'fake_fez:latest~1'` | The same, among runs on one backend. |
| `ibm_fez:latest`, `'ibm_fez:latest~1'` | Snapshots: the newest calibration of one device, then the one before. The backend is required for snapshots. |

Quote a selector that contains `~`, as above: in zsh with the `EXTENDED_GLOB` option, an
unquoted `~` is a pattern operator. Snapshots are ordered by the provider's calibration date,
not by when you stored them. When
a selector is not the full ID, the command prints `role: selector -> ID` on stderr. A prefix
that matches more than one ID, or a `latest` position shared by two runs created in the same
millisecond (or two snapshots with the same calibration date), is reported with the
candidates, and nothing is selected.

## What QCI deliberately does not do

- **It does not judge.** QCI reports what differs and by how much. It never labels a run, a
  device or a change as good or bad, and it never reduces a comparison to a single grade.
- **It does not explain why.** A calibration difference next to a result difference is
  reported as two facts. QCI makes no claim that one produced the other.
- **It does not run on quantum hardware.** `qci run` executes only on local simulators.
  `capture` and `backfill` read published calibration and run nothing on a device.
- **It does not send your data anywhere.** There is no telemetry, no account system, no
  hosted service and no update check. `qci snapshot capture` and `qci snapshot backfill` are
  the only commands that use the network, and they only read from IBM.

## Data and privacy

- **Where your data lives.** Runs and snapshots are stored in one SQLite file, `qci.db`. By
  default it is per user: `~/Library/Application Support/qci` on macOS, `%LOCALAPPDATA%\qci`
  on Windows, and `$XDG_DATA_HOME/qci` or `~/.local/share/qci` elsewhere. Set `QCI_HOME` to a
  directory to use another store, and run `qci where` to see the file in use. QCI creates the
  directory on the first write, readable only by you on macOS and Linux. Commands that only
  read never create it.
- **Stores from before 0.1.0.** Earlier versions kept the store in `./.qci` in the current
  directory. QCI never moves or copies a store: when it finds `./.qci/qci.db` and `QCI_HOME`
  is unset, it prints the `export QCI_HOME=...` line that keeps using it. Runs can be
  compared only within one store.
- **Credentials.** QCI uses only accounts saved with `QiskitRuntimeService.save_account`,
  selected by name. It never asks for, stores, logs or prints a token, and never reads
  credentials from environment variables. `qci doctor` reports saved accounts by name only.
  Credential-like values in calibration payloads (tokens, instance CRNs, URLs, emails) are
  replaced with a `{"$redacted": ...}` marker before anything is stored.
- **IBM data stays local.** Calibration you capture or backfill is IBM's data, provided under
  IBM's terms. QCI keeps it in your local store and never uploads it, and
  `qci snapshot export` refuses backfilled data. The QCI packages themselves contain no IBM
  calibration data.

## License and contributing

QCI is licensed under the Apache License 2.0; see the `LICENSE` and `NOTICE` files in the
distribution. The copyright holder is "The QCI Authors", the authors of the commits in the
project's git history (`AUTHORS`).

Contributions are accepted under the Developer Certificate of Origin 1.1: every commit
carries a `Signed-off-by:` line (`git commit -s`). `CONTRIBUTING.md` in the source repository
has the certificate, the developer install and the project's workflow. The design is
documented in the source repository: `PLAN.md` (milestones), `docs/architecture.md`,
`docs/data-model.md` and the decision records in `docs/adr/`.
