# ADR 0007: Stale-noise check (fake calibration against a live snapshot)

- **Status:** Accepted (2026-10-16), with five amendments: a limitation line on calibration
  data versus a simulator's noise model (section 7), the command name confirmed (section 6),
  three mapping entries verified offline (section 2), device-wide lists moved to the backlog
  (sections 4 and 6), and units on every value line (section 6, D26).
- **Date:** 2026-10-16 (proposed), 2026-10-16 (accepted), 2026-10-16 (M1.4b implemented on
  `feat/m1.4b-compare-run`; M1.4c live check recorded in Findings, M1.4 closed)
- **Milestone:** M1.4 (`PLAN.md`). This ADR is M1.4a. M1.4b implements it, and M1.4c is the
  user's live check.

## Context

Every QCI run so far executed on an IBM fake backend. A fake backend simulates noise from a
calibration document frozen into the installed `qiskit-ibm-runtime` package
(`source=static_fake`). M1.3 added live calibration snapshots of real devices. M1.4 puts the
two side by side: for one stored fake-backend run, how does the calibration the fake used
differ from a live snapshot of the real device it was derived from, for the physical resources
that run actually used?

The check reports differences and measurement dates. It does not say whether the fake's noise
model is adequate for the workload, and it does not predict how the workload would behave on
the device.

Constraints:

- Runs are immutable (ADR 0003). The check must work on existing runs with no schema change.
- It must not compare calibration of different devices as a change of one device (rule 8).
  The fake-to-device correspondence must therefore be explicit, never guessed.
- It reuses the M1.3c calibration logic where possible. Existing `qci compare` and
  `qci snapshot compare` output stays byte-identical.
- Offline and read-only: it reads the run store and the snapshot store and writes nothing.

## Findings from the code and the installed fakes

These were checked on 2026-10-16 against the code at `c507fae`, the installed
qiskit-ibm-runtime 0.50.0, the committed fixture `tests/fixtures/snapshots/ibm_fez.json`, and
(read-only) the user's stored run `01M4K9G88XK5DS4X23D7ZSH1T0` in `~/.qci-live`. The store's
file size and modification time were unchanged afterwards. No network call was made.

### What a fake-backend run record holds

`QiskitFakeBackendCatalog.snapshot` (`adapters/qiskit_ibm/adapter.py`) builds
`Run.backend_snapshot` as a `BackendSnapshot`:

| Field | Content for a fake backend | Example (`fake_fez` run above) |
|---|---|---|
| `source` | `static_fake` | `static_fake` |
| `captured_at` | When QCI read the fake, at run time. **Not a calibration date.** | 2026-10-10T16:14:26Z |
| `calibrated_at` | The fake properties' `last_update_date`, in UTC | 2025-02-26T20:16:25Z |
| `basis_gates`, `coupling_edges` | From the fake configuration | |
| `provider_raw["properties"]` | `properties().to_dict()` through `to_jsonable`, verbatim | 4,509 measurement rows when projected by `extract_measurements` |
| `provider_raw["configuration"]` | `configuration().to_dict()` through `to_jsonable`, verbatim | `n_qubits` 156, `gates` with `coupling_map`, `supported_instructions` |

Further facts from the same record:

- `Run.backend` is `{provider: qiskit_ibm, name: fake_fez, version: 1.2.8, num_qubits: 156,
  is_simulator: true}`.
- The properties payload records the device it came from: `properties.backend_name` is
  `ibm_fez`, `properties.backend_version` is `1.2.8`. The configuration says `fake_fez`.
- Every parameter keeps its own provider date. In the `fake_fez` payload they range from
  2024-12-28 to 2025-02-26, with most on 2025-02-24 (3,004 rows) and 2025-02-26 (1,276 rows).
  The dates carry an explicit UTC offset, and the reader converts them to UTC instants.
- `Run.provenance.environment.packages` records the installed `qiskit-ibm-runtime` version
  (0.50.0), which is the package the frozen calibration came from.
- `Run.compilation.output.qasm3` holds the transpiled circuit, from which `footprint.py`
  derives the physical footprint (ADR 0004).

**Conclusion: the run record is sufficient, with no change to the run schema.** It holds the
fake's full calibration document with per-parameter dates and units, the configuration needed
for the presence check, the device name the payload itself records, the package version, and
the transpiled circuit for the footprint. The one field that must not be used is
`backend_snapshot.captured_at`. For a fake it is the run time, not a calibration time.

### The fakes' recorded device names

The device each installed fake's properties payload names is not a fixed transformation of
the fake's name. Of the 68 installed fakes, most map `fake_X` to `ibm_X`, but others record
`ibmq_X` (for example `fake_bogota -> ibmq_bogota`), `alt_X` (`fake_auckland`, `fake_cairo`),
`ibmq_16_melbourne` (`fake_melbourne`), `ibmqx2` (`fake_yorktown`), or the fake's own name
(`fake_fractional`, `fake_nighthawk`). Deriving a device name from a fake name would be wrong
for some fakes.

**Mapping entries, checked offline at acceptance (2026-10-16).** With qiskit-ibm-runtime
0.50.0, each of the three fakes named in the amendment is installed, and its properties
payload's `backend_name` equals the device it is mapped to:

| Fake (class) | `properties.backend_name` | `backend_version` | `last_update_date` | Qubits |
|---|---|---|---|---|
| `fake_fez` (`FakeFez`) | `ibm_fez` | 1.2.8 | 2025-02-26T15:16:25-05:00 | 156 |
| `fake_kingston` (`FakeKingston`) | `ibm_kingston` | 1.0.0 | 2026-04-15T09:15:15+02:00 | 156 |
| `fake_marrakesh` (`FakeMarrakesh`) | `ibm_marrakesh` | 1.0.7 | 2025-02-26T14:52:45-05:00 | 156 |

### Fake against live, offline prototype

A scratch script (not committed) applied the reuse in section 4 to the stored `fake_fez` run
and the committed `ibm_fez` fixture (captured 2026-10-10, `calibrated_at`
2026-10-10T00:19:17Z, `backend_version` 1.3.37). It used `compare_calibration` with
`require_matching_units=True`, unmodified:

- The footprint has qubits 136, 141, 142, 143 and 144, with `cz`, `measure`, `rz` and `sx`
  operations. `missing_resources` lists no missing resource on either side.
- 65 parameters: 45 `changed`, 15 `unchanged` (`rz` `gate_error` and `gate_length`, both 0 on
  both sides, and `sx` `gate_length`, 24 ns on both sides), and 5 `unavailable`, which are
  `init_error` on every footprint qubit, reported by the live side only.
- Among the differences: `cz` `gate_length` 84 ns on the fake, 68 ns on the live side, and
  `readout_length` 1560 ns on the fake, 1660 ns on the live side. Units agree everywhere, so no
  parameter is `not_comparable`.
- No footprint error-type value equals 1 on either side. Device-wide, the fake reports
  `gate_error` exactly 1 on 14 `cz` and 98 `rzz` entries.
- Live date minus fake date per parameter: about 589.5 to 592.5 days. Live `calibrated_at`
  minus fake `calibrated_at`: about 590.2 days. The `rz` dates on both sides equal their
  document's `calibrated_at` (D24).
- Gate names on one side only (device-wide): the live side also has `measure`, `measure_2`,
  `measure_reset`, `measure_reset_2`, `reset_2` and `xslow`. Qubit parameters on one side
  only: `init_error` (live). Measure-gate parameters, such as `threshold`, are not read by the
  reader (D22). Device-wide differences are not part of M1.4b. They are a backlog item in
  `PLAN.md`.

### Live check (M1.4c)

Run by the user on 2026-10-16 (local time) on their own store, `~/.qci-live`, on branch
`feat/m1.4b-compare-run`. The three snapshots were captured at 2026-10-17 02:35 UTC. One
seeded GHZ-star run (`examples/ghz_star.py --seed 7`) was executed on
each fake, and each run was compared with the most recent snapshot of its mapped device, as
text and twice as JSON. The database hash was taken after the runs and before the
comparisons, and again after them. Every value below was checked against the stored JSON.

| | `fake_fez` → `ibm_fez` | `fake_kingston` → `ibm_kingston` | `fake_marrakesh` → `ibm_marrakesh` |
|---|---|---|---|
| Run | `01M53WS95J24M0GKV7TW2QHV4G` | `01M53WSKVXWWX4GSJ8MZX7Z3R7` | `01M53WSWP5Q2YBAZJX9GT97Y8D` |
| Snapshot | `01M53VD2ZQWXPP8FZYKN4SJEEE` | `01M53VD7HEW073D41KACG554YG` | `01M53VDC75KJ0WPXRE20KN2XGC` |
| Fake version, `calibrated_at` | 1.2.8, 2025-02-26T20:16:25Z | 1.0.0, 2026-04-15T07:15:15Z | 1.0.7, 2025-02-26T19:52:45Z |
| Live version, `calibrated_at` | 1.3.37, 2026-10-17T02:18:24Z | 1.0.0, 2026-10-17T02:17:17Z | 1.0.21, 2026-10-17T01:18:11Z |
| Recorded device (run payload) | `ibm_fez` 1.2.8 | `ibm_kingston` 1.0.0 | `ibm_marrakesh` 1.0.7 |
| Footprint qubits | 136, 141, 142, 143, 144 | 138, 149, 150, 151, 152 | 10, 11, 12, 13, 18 |
| `cz` operations | (142,141), (142,143), (143,136), (143,142), (143,144) | (150,149), (150,151), (151,138), (151,150), (151,152) | (11,10), (11,12), (11,18), (12,11), (12,13) |
| Status | `changed` | `changed` | `changed` |
| Parameters | 65: 45 changed, 15 unchanged, 5 unavailable, 0 not compared | 65: 39 changed, 21 unchanged, 5 unavailable, 0 not compared | 65: 40 changed, 20 unchanged, 5 unavailable, 0 not compared |
| `live_minus_fake` range | 596.9 to 599.3 days | 184.0 to 184.8 days | 597.2 to 601.2 days |
| `calibrated_at_difference` | 51602519 s (597.3 days) | 15966122 s (184.8 days) | 51600326 s (597.2 days) |

For all three pairs:

- The operations are `cz`, `measure`, `rz` and `sx`. Every footprint resource is present on
  both sides. `relevant_hardware_changed` and `global_snapshot_changed` are true. The reason
  is the mapping note alone, such as `fake_fez is the fake built from ibm_fez calibration
  (qiskit_ibm FAKE_DEVICE_SOURCES)`. The runs' `qiskit-ibm-runtime` version is 0.50.0.
- `parameters_on_one_side`: `init_error` on each of the 5 footprint qubits, `side="candidate"`
  (reported by the live side only). These are the 5 `unavailable` parameters, and the only
  `measurement_dates` entries with a null `live_minus_fake`.
- `unit_differences`: empty. `error_values_at_one`: empty. No error-type value equals 1 in any
  footprint, on either side.
- The database hash was `23fc1a7e987110d31af08cbb8e0141612746a680953daa6d9ffa950a2f4aad06`
  before and after the comparisons. For each pair, the two JSON outputs are byte-identical.
- No output line, text or JSON, contains the rule 8 words or the additional substrings in
  section 5, and no line was identified as a judgment.

Observed values, stated without interpretation:

- `readout_length` differs by +100 ns on every footprint qubit for `fez` and `marrakesh`
  (1560 ns on the fake, 1660 ns live, for `fez`), and by -100 ns for `kingston`.
- `ibm_marrakesh` `readout_error`: qubit 11 is 0.0083 on the fake and 0.0642 live; qubit 13 is
  0.0051 on the fake and 0.0792 live. The other three footprint qubits are between 0.0039 and
  0.0079 on both sides.
- `cz` `gate_length`: 84 ns on the fake and 68 ns live for `fez`. It is equal on both sides
  for `kingston` and `marrakesh` (68 ns or 80 ns, depending on the pair).
- The unchanged parameters are `rz` `gate_error` and `gate_length` and `sx` `gate_length`
  everywhere, plus `cz` `gate_length` for `kingston` and `marrakesh`, plus one
  `prob_meas0_prep1` for `kingston`.
- The device version differs between the fake and the live side for `fez` (1.2.8 and 1.3.37)
  and `marrakesh` (1.0.7 and 1.0.21). It is equal for `kingston` (1.0.0). Limitation 3
  applies: QCI cannot detect whether a revision renamed physical resources.
- Exact comparison counts nearly every continuous value that was measured again as
  `changed` (39 to 45 of 65 here). A summary by magnitude is a backlog item in `PLAN.md`.

## Decision

### 1. Inputs: one stored run and one stored live snapshot

The check takes a run ID and a snapshot ID. The run supplies both the footprint and the
baseline calibration, `run.backend_snapshot`, which is already a `BackendSnapshot`. The
snapshot supplies the candidate calibration through the existing
`IbmSnapshotResourceIndex.backend_snapshot` view. No new data is captured. The run schema
and the snapshot schema are unchanged.

Required preconditions, each checked explicitly (exits in section 6):

- the run has a `backend` and a `backend_snapshot`, and its snapshot source is `static_fake`;
- the snapshot source is `live_calibration`;
- both are from the same provider;
- the run's fake backend has an entry in the explicit device mapping (section 2), and that
  device equals both the snapshot's `backend_name` and the device recorded in the run's own
  properties payload;
- the run's footprint is available, and every footprint resource is present on both sides.

A failed run with a backend snapshot is accepted. Its footprint is then usually unavailable,
which is reported as such.

### 2. Fake-to-real matching: an explicit mapping in the IBM adapter

**Decision: an explicit, documented mapping in the IBM adapter, cross-checked against the
device name the fake's own payload records.** The user does not supply a device name.

```python
# adapters/qiskit_ibm/calibration.py
FAKE_DEVICE_SOURCES: Mapping[str, str] = {
    "fake_fez": "ibm_fez",
    "fake_kingston": "ibm_kingston",
    "fake_marrakesh": "ibm_marrakesh",
}
"""Fake backend name -> the real device whose calibration the fake was built from. Explicit
and exact. A fake not listed here is not compared with any live snapshot. Entries are added
only when verified (see the test below); device names are never derived from fake names."""
```

- **Three entries in M1.4b, and no others.** `fake_fez -> ibm_fez`,
  `fake_kingston -> ibm_kingston` and `fake_marrakesh -> ibm_marrakesh`. Each was checked
  offline at acceptance (see Findings). `fake_fez` is the only one with a committed live
  fixture and live snapshots in the user's store. Any further entry is one line plus its own
  test, added in a later, approved step.
- **Cross-check.** The comparison also reads `provider_raw["properties"]["backend_name"]` from
  the run record. If it differs from the mapped device, the result is `not_comparable`. This
  catches a later `qiskit-ibm-runtime` release whose fake was rebuilt from another device, for
  runs stored under that release.
- **Tests.** Each entry has its own test, which instantiates the installed fake and asserts
  that its properties `backend_name` equals the mapped device. A further test asserts that the
  mapping has exactly these three keys.
- **The snapshot's device must match.** The user picks the snapshot ID. If its `backend_name`
  is not the mapped device, the result is `not_comparable`, naming both. So the user's choice
  of snapshot can never pair calibration from two devices.

Why not a user-supplied device name: it would let a `fake_fez` run be set against an
`ibm_torino` snapshot, which compares two devices as one. Every pairing would rest on the
user's typing, with nothing for QCI to check. The mapping is a small, reviewable and testable
statement of which fake came from which device.

Why not the payload's `backend_name` alone: the payload is data shipped by a third party.
For some fakes it is the fake's own name (`fake_fractional`), and for retired devices the
name refers to hardware that can no longer be captured. Requiring an explicit entry keeps
every supported pair a reviewed decision. The payload name is used as a check, not as the
source.

### 3. Ages: dates side by side, differences calculated

- **Dates as given.** For every compared parameter, the output lists the fake-side and the
  live-side provider date (`ParameterComparison.baseline_calibrated_at` and
  `candidate_calibrated_at`, which `compare_calibration` already fills). They are
  provider-reported values, shown as given in UTC, not values QCI computed.
- **Difference, calculated.** Per parameter, `live_minus_fake` is a `Metric` with
  `kind=calculated`, unit `s`, method `"live measured_at minus fake measured_at"` and
  method version `1`. It is null when either date is missing, never 0. The output also gives
  the minimum and the maximum of these differences, each as a calculated `Metric`, or null
  when no parameter has both dates.
- **Document dates.** Both documents' `calibrated_at` are shown, and
  `calibrated_at_difference` (live minus fake, in seconds) is a calculated `Metric`, null when
  either is missing.
- **Never used:** the run's `backend_snapshot.captured_at`, which is when QCI read the fake,
  and the current time. The output has no "age now". Ages at capture time for a footprint
  are D25, scheduled for M1.6.
- The M1.3c labels `re_measured_same_value` and `not_re_measured` are not reused. Between a
  fake and a live document, the dates always differ, so every equal value would be labeled
  "re-measured" even for `rz`, where the date is only the document timestamp (D24). The plain
  dates and their difference carry the information without that label.

### 4. Kind differences, reported explicitly

| Difference | How it is reported | Reuse |
|---|---|---|
| Footprint resource absent from one side (a qubit at or above `n_qubits`, an ordered pair not in the gate's `coupling_map`, an unsupported instruction) | `not_comparable`, with a reason listing every missing resource per side, and no parameter comparisons. The check always runs, since a fake and a device always have different backend names. | `missing_resources(provider_raw, qubits, operations)` in `adapters/qiskit_ibm/calibration.py`, unchanged. It takes `provider_raw`, so it applies to the run's `BackendSnapshot` as is. The port method `SnapshotResourceIndex.missing_resources` takes a `CalibrationSnapshot`, so it cannot be reused for the run side. A new port method (section 6, Wiring) calls the same function. |
| Parameter reported on one side only (for `fake_fez` against `ibm_fez`: `init_error`, live only) | `status="unavailable"` with a null value on the missing side, never 0, as now. In addition, `parameters_on_one_side` lists `{side, resource_kind, operation, qubits, parameter}` for each one. | `compare_calibration` unchanged for the status. `parameters_on_one_side` is new: `compare_calibration` puts "not reported" and "reported, value unrepresentable" both into `unavailable` with a null value, so the list is built from the two reader selections, where a reported parameter has an entry and an unreported one has none. |
| Reported, but the value is unrepresentable (non-finite, complex, redacted) | `status="unavailable"`, as now. It does not appear in `parameters_on_one_side`. | Unchanged. |
| Unit differs, including `None` against a unit | `status="not_comparable"`, both raw values, `delta=None`, and the reason naming the resource, the parameter and both units. No unit is converted. In addition, `unit_differences` lists `{resource_kind, operation, qubits, parameter, baseline_unit, candidate_unit}`. | `compare_calibration(require_matching_units=True)` unchanged. `unit_differences` is new, because a mismatched `ParameterComparison` has `unit=None` and the two units appear only in the reason string. It is built from the two reader selections. |
| Error-type value exactly 1 on either side | `error_values_at_one`, per side, with `side="baseline"` (fake) or `"candidate"` (live), as the provider gave it, with no interpretation. | `error_values_at_one` and `ERROR_PARAMETERS` from M1.3c, unchanged. |
| `general` pairwise parameters and `measure` gate entries | Excluded and listed in `hardware.excluded`, as now (D14, D22). | Unchanged. |

Device-wide gate-set and qubit-count differences between a fake and its live device are not
reported in M1.4b. They are a backlog item in `PLAN.md` (amendment 4). The output covers the
footprint only.

`compare_calibration` itself is not modified. `compare_snapshots` cannot be reused: it
requires both sides to be `CalibrationSnapshot`s of one backend name, it takes the footprint
from a separate run, and it adds the re-measured labels that section 3 rejects. A new function
`compare_run_to_snapshot` in a new module `qci/compare/run_snapshot.py` calls
`compare_calibration` directly, with the same footprint on both sides, so
`resources_identical` is true by construction.

`global_snapshot_changed` is set from the inequality of the two content hashes, as in
`compare_hardware`. A fake and a live payload always differ (at least in the configuration's
`backend_name`), so the field is true in practice. The limitations say so.

### 5. Output wording

- The direction is fake (baseline) to live (candidate). Every delta is live minus fake, and
  every date difference is live minus fake.
- The output reports differences, dates and date differences only. It contains none of the
  rule 8 words, nor the substrings `significan`, `verdict`, `caus`, `degrad`, `stale`,
  `outdated`, `accurate`, `realistic` or `adequate`, matched case-insensitively. The
  milestone's name appears in the docs only, never in command output.
- `changed` means that the two reports give different values for that parameter. It does not
  mean that the device changed in a specific way, and it says nothing about the fake's
  suitability for the workload.
- `relevant_hardware_changed` keeps its existing meaning: calibration for the footprint's
  resources differs. It does not mean a parameter is known to affect the workload.

### 6. Command surface, JSON shape, read-only behavior

```
qci snapshot compare-run RUN_ID SNAPSHOT_ID [--json]
```

`RUN_ID` is the baseline, a stored fake-backend run. `SNAPSHOT_ID` is the candidate, a stored
live snapshot. The name says what it does: compare the calibration stored in a run with a
snapshot. It sits beside `qci snapshot compare`.

**Read-only.** It opens the run repository and the snapshot repository with
`read_only=True` (SQLite `mode=ro`), as `qci snapshot compare` does. It never creates or
modifies the store, never constructs an IBM client, and never persists the comparison. An
unknown run or snapshot ID prints an error and exits 1.

**Exits, in order.** Each sets `status` and a `reason`, and none produces parameter
comparisons:

1. The run has no `backend` or no `backend_snapshot`: `unavailable`.
2. The run's snapshot source is not `static_fake`: `not_comparable`. This check compares a
   fake backend's frozen calibration with a live snapshot.
3. The snapshot's source is not `live_calibration`: `not_comparable`.
4. The run's provider differs from the snapshot's: `not_comparable`.
5. No support for the provider: `unavailable`.
6. The run's backend is not in the provider's fake-to-device mapping: `not_comparable`, with
   a reason naming the fake and saying that no device name is derived from it.
7. The snapshot's `backend_name` is not the mapped device: `not_comparable`, naming both.
8. The run's recorded properties `backend_name` is missing or is not the mapped device:
   `not_comparable`, naming both.
9. The footprint is not available: `not_comparable` when dynamic, otherwise `unavailable`.
10. A footprint resource is missing from either side: `not_comparable`, with every missing
    resource listed per side.
11. Otherwise: `compare_calibration`, and `status` equals `hardware.status`.

The mapping note `fake_fez is the fake built from ibm_fez calibration
(qiskit_ibm FAKE_DEVICE_SOURCES)` is always in the output after exit 6.

**JSON shape** (`RunSnapshotComparison` in `qci/domain/snapshot.py`, frozen,
`extra="forbid"`):

```text
{
  "schema_version": 1,
  "run_snapshot_comparison_id": "<sha256>",   // run ID, snapshot ID, method version
  "method_version": "qci.compare.run_snapshot.1",
  "status": "changed",                        // equal to hardware.status after exit 11
  "baseline": {                               // the fake side, from the run record
    "run_id": "...", "provider": "qiskit_ibm",
    "backend_name": "fake_fez", "backend_version": "1.2.8",
    "snapshot_source": "static_fake",
    "calibrated_at": "2025-02-26T20:16:25Z",
    "recorded_device": "ibm_fez",             // properties.backend_name in the run record
    "recorded_device_version": "1.2.8",       // properties.backend_version
    "qiskit_ibm_runtime_version": "0.50.0"    // from the run's environment provenance
  },
  "candidate": {                              // the live side
    "snapshot_id": "...", "provider": "qiskit_ibm",
    "backend_name": "ibm_fez", "backend_version": "1.3.37",
    "content_hash": "...", "source": "live_calibration",
    "captured_at": "...", "calibrated_at": "2026-10-10T00:19:17Z"
  },
  "device_mapping": {"fake": "fake_fez", "device": "ibm_fez",
                     "source": "qiskit_ibm FAKE_DEVICE_SOURCES"},   // null before exit 6
  "footprint": { ... PhysicalFootprint ... },
  "hardware": { ... HardwareComparison, from compare_calibration ... },
  "parameters_on_one_side": [
    {"side": "candidate", "resource_kind": "qubit", "operation": null,
     "qubits": [136], "parameter": "init_error"}
  ],
  "unit_differences": [],
  "error_parameters": ["gate_error", "readout_error", "init_error"],
  "error_values_at_one": [],
  "calibrated_at_difference": {"name": "calibrated_at_difference", "value": 50990572.0,
                               "unit": "s", "kind": "calculated", ...},
  "measurement_dates": [
    {"resource_kind": "qubit", "operation": null, "qubits": [136], "parameter": "T1",
     "baseline_measured_at": "2025-02-26T11:56:47Z",
     "candidate_measured_at": "2026-10-09T00:12:21Z",
     "live_minus_fake": {"value": 50933734.0, "unit": "s", "kind": "calculated", ...}}
  ],
  "live_minus_fake_min": { ... Metric or null ... },
  "live_minus_fake_max": { ... Metric or null ... },
  "limitations": [ ... section 7 ... ]
}
```

Lists are sorted deterministically: by resource kind, operation, qubits and parameter, and
`error_values_at_one` by side first. `--json` output is byte-identical across invocations.
The text renderer shows the same sections. It shows units on every value line, which closes
D26 for this command only.

**Wiring.** `core/ports.py` gains a `FakeDeviceIndex` protocol, implemented in the IBM
adapter:

- `device_for(backend_name: str) -> str | None`, from `FAKE_DEVICE_SOURCES`;
- `recorded_device(snapshot: BackendSnapshot) -> tuple[str | None, str | None]`, the
  properties `backend_name` and `backend_version`;
- `missing_resources(snapshot: BackendSnapshot, qubits, operations) -> list[str]`, which calls
  the existing `missing_resources(snapshot.provider_raw, ...)`;

A dataclass `RunSnapshotComparisonSupport` bundles the existing `SnapshotComparisonSupport`
(`snapshot`) and a `FakeDeviceIndex` (`devices`), with two provider-supplied strings, so that
`qci.compare` holds no provider names:

- `mapping_source`: the name of the explicit list `devices` reads, shown in `device_mapping`
  and the mapping note (IBM: `"qiskit_ibm FAKE_DEVICE_SOURCES"`);
- `fake_package`: the distribution whose installed fakes hold the frozen calibration, whose
  version is read from the run's environment provenance into
  `baseline.qiskit_ibm_runtime_version` (IBM: `"qiskit-ibm-runtime"`).

These two fields were added in M1.4b and recorded here at M1.4c. A `RunSnapshotCompareService` in `qci/services/` loads the run and the
snapshot and calls `compare_run_to_snapshot`. `qci.compare` imports no provider SDK, and the
architecture test covers the new module.

**Policy and versions.** Run comparison rules are unchanged: `ComparisonPolicy.version` stays
`qci.compare.v3` and `ENGINE_VERSION` is not bumped. The new comparison has its own method
version, `qci.compare.run_snapshot.1`. `SnapshotComparison` and its method version
`qci.compare.snapshot.1` are unchanged.

### 7. Limitations text

`compare_run_to_snapshot` emits exactly these lines, in this order:

1. "This comparison reports what differs between the calibration frozen into a fake backend,
   as stored in one run, and one live snapshot of the device the fake was built from, for the
   physical resources of that run's footprint. Deltas and date differences are live minus
   fake."
2. "The fake-to-device correspondence comes from an explicit list in the provider adapter and
   is checked against the device name recorded in the fake's own calibration payload. QCI
   cannot check that the fake's payload equals what the device published at that time."
3. "Both sides are reports about one device at different times. Qubit and gate indices are
   assumed to name the same physical resources on both sides. A device revision between the
   two dates (both backend versions are shown) could break this, and QCI cannot detect it."
4. "Values are provider-reported and compared exactly, with no tolerance. A parameter whose
   unit differs between the two sides is not compared, and no unit is converted."
5. "A changed value means only that the two reports give different values. This comparison
   does not say whether the fake's noise model suits the workload, and it does not predict
   how the workload would behave on the device. Nothing is simulated against the live
   snapshot."
6. "This compares calibration data: the values the fake backend was built from and the live
   device's reported values. It does not compare the noise model a simulator constructs from
   that data; a simulator may use only some of these parameters, in its own way."
7. "Measurement dates are provider timestamps, shown as given. Their differences are
   calculated. For virtual gates (such as rz) and configured durations (such as gate_length),
   the date can be the document timestamp rather than the time of a physical measurement."
8. "The run's captured_at is when QCI read the fake backend, not a calibration date, and is
   not used."
9. "Relevant hardware means calibration data for the physical resources of the footprint. It
   does not mean a parameter is known to affect workload performance."
10. "The raw payloads of a fake and a live device always differ, so global_snapshot_changed
    is true in practice and carries no further information here."
11. "Error-type parameters with a value of exactly 1 are listed as the provider reported
    them. QCI does not interpret them."
12. "Pairwise general parameters (D14) and measure gate entries (D22) are not compared."
13. "These comparisons are never stored."

### 8. Out of scope

- Simulating the workload against a live snapshot, or building a noise model from one.
- Routing, backend selection or layout advice.
- Predictions of any kind, including an estimated success probability (M1.6).
- Ages relative to the current time or to the capture time (D25, M1.6).
- Mapping entries beyond the three in section 2.
- Device-wide gate-set and qubit-count differences (backlog).
- Comparing two runs' fake calibrations, or a run against a snapshot from another device.
- Any change to run comparison, snapshot comparison, the run schema or the snapshot schema.
- Network access, live capture inside the command, and historical lookups (M1.5).

### 9. Acceptance criteria

#### M1.4b: implementation (approved 2026-10-16, with amendments)

- [x] `FAKE_DEVICE_SOURCES` in `adapters/qiskit_ibm/calibration.py` is an explicit mapping
      with exactly three entries: `fake_fez -> ibm_fez`, `fake_kingston -> ibm_kingston` and
      `fake_marrakesh -> ibm_marrakesh`. Each entry has its own test, which instantiates the
      installed fake and asserts that its properties payload's `backend_name` equals the
      mapped device. A test asserts that the mapping has exactly these keys. No code derives a
      device name from a fake name.
- [x] `qci snapshot compare-run RUN_ID SNAPSHOT_ID [--json]` opens both repositories
      read-only. The database bytes are unchanged after the command, and the existing guard
      shows that no IBM client is constructed. An unknown run or snapshot ID exits 1.
- [x] Each exit in section 6 has a test that asserts its status and its reason, and that no
      parameter comparisons are produced: no backend snapshot (`unavailable`); run snapshot
      source not `static_fake` (`not_comparable`); snapshot source not `live_calibration`
      (`not_comparable`); provider differs (`not_comparable`); fake not in the mapping
      (`not_comparable`, naming the fake and saying that no device name is derived from it);
      snapshot backend differs from the mapped device (`not_comparable`, naming both); the
      run's recorded properties `backend_name` missing or different from the mapped device
      (`not_comparable`, naming both); footprint not available (`unavailable`, or
      `not_comparable` when dynamic); footprint resources missing from either side
      (`not_comparable`, listing each one per side).
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
      section 7, including: "This compares calibration data: the values the fake backend was
      built from and the live device's reported values. It does not compare the noise model a
      simulator constructs from that data; a simulator may use only some of these parameters,
      in its own way."
- [x] The text renderer shows the unit on every value line (D26, for this command).
- [x] `run_snapshot_comparison_id` is deterministic, lists are sorted as in section 6, and
      `--json` output is byte-identical across two invocations.
- [x] Rendered and JSON output contain none of the rule 8 words, nor `significan`,
      `verdict`, `caus`, `degrad`, `stale`, `outdated`, `accurate`, `realistic` or
      `adequate`, checked by a test.
- [x] `docs/architecture.md`, `docs/data-model.md` and README describe the command, and all
      gates pass.

#### M1.4c: manual live check by the user

Run on the user's store, with no capture needed if the existing snapshots are used. Optionally
capture one fresh `ibm_fez` snapshot first (`qci snapshot capture --backend ibm_fez`, which is
the only networked step). Then, offline:

```bash
export QCI_HOME=~/.qci-live
shasum -a 256 "$QCI_HOME/qci.db"                      # before
qci snapshot compare-run 01M4K9G88XK5DS4X23D7ZSH1T0 01M53QQFQBDDB5W0RXXCZR68YM
qci snapshot compare-run 01M4K9G88XK5DS4X23D7ZSH1T0 01M53QQFQBDDB5W0RXXCZR68YM --json > a.json
qci snapshot compare-run 01M4K9G88XK5DS4X23D7ZSH1T0 01M53QQFQBDDB5W0RXXCZR68YM --json > b.json
cmp a.json b.json                                     # byte-identical
qci snapshot compare-run 01M4K9G88XK5DS4X23D7ZSH1T0 01M4HQ5J939C5ZCK43M51EX1CF --json > c.json
shasum -a 256 "$QCI_HOME/qci.db"                      # after: unchanged
```

`01M4K9G88XK5DS4X23D7ZSH1T0` is the seeded GHZ-star run on `fake_fez`.
`01M53QQFQBDDB5W0RXXCZR68YM` (calibrated 2026-10-17 01:04:01 UTC) and
`01M4HQ5J939C5ZCK43M51EX1CF` (calibrated 2026-10-10 00:58:58 UTC) are `ibm_fez` snapshots in
that store. Record in a "Live check (M1.4c)" section of this ADR, checked against the stored
JSON:

- [x] the status, the footprint, and the counts of `changed`, `unchanged`, `unavailable` and
      `not_comparable` parameters;
- [x] `parameters_on_one_side`, `unit_differences` and `error_values_at_one`, each listed in
      full or stated as empty;
- [x] the range of `live_minus_fake` and `calibrated_at_difference`, for every snapshot used;
- [x] both backend versions;
- [x] that the database hash is unchanged and `a.json` equals `b.json`;
- [x] any output line that could be read as a judgment, to be fixed before M1.4 closes.

Done 2026-10-16. The check was run on three fake/device pairs instead of the two `ibm_fez`
snapshots named above; see "Live check (M1.4c)" in Findings.

## Consequences

- **Good:** the first comparison of a fake's frozen calibration with live data, for the
  resources a workload actually used, from records QCI already stores, at zero QPU cost and
  with no schema change.
- **Good:** `compare_calibration`, `missing_resources`, `error_values_at_one` and
  `compare_set` are reused unchanged. Run comparison and snapshot comparison output stays
  byte-identical.
- **Cost:** three mapping entries. Every additional fake needs a reviewed one-line entry and its
  test before it can be compared.
- **Cost:** a run is now compared with a snapshot. In M1.3c the run only selected resources.
  Here its stored calibration is the baseline. This is the reason for the source checks
  (exits 2 and 3) and the device checks (exits 6 to 8).
- **Known gap:** QCI cannot verify that a fake's payload is what the device published, or
  that indices name the same physical resources across a device revision. Both are stated in
  the limitations.
- **Revisit when:** another fake needs a mapping entry, a provider ships fakes with a
  different provenance record, or M1.6 adds footprint ages relative to capture time.
