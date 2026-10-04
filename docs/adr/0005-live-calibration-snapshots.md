# ADR 0005: Live calibration snapshots

- **Status:** Proposed (M1.3a). Becomes Accepted when the M1.3b and M1.3c acceptance criteria
  below are approved.
- **Date:** 2026-10-04
- **Resolves:** D19 in `PLAN.md`.

## Context

M1.3 adds evidence of calibration change over time for a fixed footprint, at zero QPU cost. QCI
reads published calibration from IBM hardware and executes nothing. Today QCI holds calibration
only inside runs (`Run.backend_snapshot`), and every run so far uses a fake backend, whose
calibration is frozen (`source=static_fake`).

Constraints:

- Runs are immutable and separate from snapshots (ADR 0003). A snapshot is not a run.
- New storage must not assume integer qubit indices or IBM-shaped data (ADR 0006).
- Tests use no network and no credentials (CLAUDE.md rule 6).
- Existing `qci compare` output must stay byte-identical.
- No scheduler, daemon or polling loop. Each capture is one explicit command run by the user.

## Findings from the installed qiskit-ibm-runtime

The findings below come from the installed package source, version 0.50.0, at
`.venv/lib/python3.13/site-packages/qiskit_ibm_runtime/`. They are not from memory or online
documentation.

### Historical calibration by datetime

`ibm_backend.py`, line 325, class `IBMBackend`:

```python
def properties(
    self, refresh: bool = False, datetime: python_datetime | None = None
) -> BackendProperties | None:
```

The docstring says that with `datetime` the method returns the properties "whose timestamp is
closest to, but older than, the specified `datetime`". The same docstring also lists
`NotImplementedError: If datetime is specified when IBM Quantum Compute is used.` The code path
is:

- `ibm_backend.py:325`: `IBMBackend.properties` converts `datetime` to UTC and calls
  `self._api_client.backend_properties(self.name, datetime=datetime, calibration_id=...)`.
  It does not cache the result for a `datetime` request.
- `api/clients/runtime.py:301`: `backend_properties(self, backend_name: str, datetime:
  python_datetime | None = None, calibration_id: str | None = None) -> dict[str, Any]`. Its
  docstring also lists `NotImplementedError: If datetime is specified.`, but the body only
  forwards the call.
- `api/rest/cloud_backend.py:62`: `properties(self, datetime: python_datetime | None = None,
  calibration_id: str | None = None) -> dict[str, Any]`. It sends
  `params["updated_before"] = datetime.isoformat()` with a GET to the backend's `properties`
  endpoint.

`ibm_backend.py:301`, `target_history(self, datetime: python_datetime | None = None) ->
Target`, builds a `Target` from the same call. `ibm_backend.py:536`,
`IBMRetiredBackend.properties`, always returns `None`.

**Conclusion: historical calibration is not confirmed.** The client forwards a datetime as the
`updated_before` query parameter and raises nothing. Two docstrings say the feature is not
implemented, though. Whether the server honors `updated_before` cannot be checked offline, and
this step makes no network calls. QCI therefore designs for **forward-only capture**: history
is the set of snapshots the user has captured, starting at the first capture. QCI never
requests a past datetime and never backfills. Adding historical capture needs a new ADR, backed
by a recorded server response that shows the parameter is honored.

### Account resolution

`qiskit_runtime_service.py:209`, `QiskitRuntimeService.__init__(self, channel=None, token=None,
url=None, filename=None, name=None, instance=None, ...)`. In `accounts/management.py`,
`AccountManager.get(filename=None, name=None, channel=None)` documents this resolution order:

1. If `name` is given, read that saved account from the account file.
2. Otherwise, if environment variables define an account, use them.
3. Otherwise, use the default saved account.

`management.py:35` defines `_DEFAULT_ACCOUNT_NAME_IBM_QUANTUM_PLATFORM =
"default-ibm-quantum-platform"`. **Passing `name` is therefore the only way to make the client
use a saved account and never environment variables.**

### Payload transformations in the client

`utils/backend_decoder.py`:

- `properties_from_server_data` parses every date string and then calls `utc_to_local_all`
  (`utils/converters.py:69`). That function converts every `datetime` to the **local timezone
  of the capturing machine**. The same calibration captured on two machines would therefore
  serialize differently.
- `filter_raw_configuration` removes fractional gates (`rx`, `rzz`) from the configuration's
  `basis_gates`, `gates` and `supported_instructions` unless `use_fractional_gates=True`.
- `properties_from_server_data` filters `properties["gates"]` by the entry's `name` key. In
  stored payloads that key holds entry names such as `id0` or `cz12_13`, not gate names, so as
  written the filter appears to keep these entries. QCI does not depend on either behavior. It
  records the `use_fractional_gates` value it passed and stores whatever the client returns.

## Decision

### 1. Storage: an insert-only snapshot store, separate from runs

Snapshots live in the same SQLite file as runs (`$QCI_HOME/qci.db`), but in their own tables,
owned by a new `SqliteSnapshotRepository`. `SqliteRunRepository` and the `runs` table do not
change. The snapshot tables record their own version under a separate `schema_meta` key,
`snapshot_db_schema = 1`, so `DB_SCHEMA_VERSION` for runs stays 1.

```
calibration_snapshots              one row per distinct content
  snapshot_id      TEXT PK         ULID, from qci.core.ids
  content_hash     TEXT UNIQUE     sha256 over canonical JSON of the hashed content (below)
  schema_version   INTEGER         snapshot record schema, 1
  provider         TEXT            "qiskit_ibm"
  backend_name     TEXT            e.g. "ibm_fez"
  source           TEXT            "live_calibration" (existing SnapshotSource)
  first_captured_at TEXT           captured_at of the capture that created the row
  calibrated_at    TEXT NULL       provider's last_update_date, in UTC
  record_json      TEXT            the full CalibrationSnapshot record, including provider_raw
  index (provider, backend_name, first_captured_at)

snapshot_captures                  one row per capture command that succeeded
  capture_id       TEXT PK         ULID
  snapshot_id      TEXT            the snapshot this capture returned (new or existing)
  captured_at      TEXT            when QCI read the data, UTC
  index (snapshot_id), index (captured_at)

calibration_measurements           the generic projection of a snapshot (ADR 0006)
  snapshot_id      TEXT
  seq              INTEGER         position in extraction order; PK (snapshot_id, seq)
  resource_kind    TEXT            adapter-defined label, opaque to core
  resource         TEXT            adapter-defined identifier, opaque to core
  parameter        TEXT
  value_real       REAL NULL       numeric value
  value_text       TEXT NULL       non-numeric value
  unit             TEXT NULL
  measured_at      TEXT NULL       provider timestamp for this value, UTC; null if not reported
  index (resource, parameter)
```

- **Insert-only.** The repository has `save`, `get`, `get_by_hash`, `list` and
  `measurements(snapshot_id)`. It has no update and no delete.
- **Deduplication by content hash.** If a capture returns content whose hash already exists, no
  new snapshot is written. Only a `snapshot_captures` row is added. The capture log is the
  history: it records that the same calibration was still published at a later time.
- **Hashed content.** The hash covers `{provider, backend_name, use_fractional_gates,
  provider_raw}` after redaction (section 4) and UTC normalization (section 6). It excludes
  `captured_at` and the QCI environment. If the configuration payload carries a field that
  changes on every request, deduplication never triggers. That costs storage, never
  correctness.
- **Measurements are a projection, written once.** The adapter extracts the rows at capture
  time, and they are inserted in the same transaction as the snapshot. Duplicate entries in a
  provider payload are kept as separate rows, which is why the key is `seq` and not
  `(resource, parameter)`. The raw payload stays in `record_json` as the evidence. The
  extraction method and version are stored in the record. A later extractor version never
  rewrites old rows.
- **Unavailable is null.** A value the provider reported but that cannot be represented, such
  as a non-finite float or a complex number, is stored with `value_real` and `value_text` both
  null. A parameter the provider did not report has no row. Neither case is ever stored as 0.

### 2. Domain model (provider-neutral, `qci/domain/snapshot.py`)

```python
class Measurement(DomainModel):
    resource_kind: str             # adapter-defined; not the physical-level ResourceKind enum
    resource: str                  # adapter-defined; core never parses it
    parameter: str
    value: float | str | None      # None = unavailable, never 0
    unit: str | None = None
    measured_at: AwareDatetime | None = None

class CalibrationSnapshot(DomainModel):
    schema_version: Literal[1] = 1
    snapshot_id: str
    content_hash: str
    provider: str
    backend_name: str
    backend_version: str | None
    source: SnapshotSource         # LIVE_CALIBRATION for captures
    captured_at: AwareDatetime     # first capture
    calibrated_at: AwareDatetime | None
    capture_options: dict[str, JsonValue]   # e.g. {"use_fractional_gates": false}
    extraction_method: str         # measurement extractor, e.g. "qiskit_ibm.properties"
    extraction_method_version: str
    redactions: list[str]          # JSON paths the redactor replaced; values never kept
    environment: dict[str, str]    # versions of qci, qiskit, qiskit-ibm-runtime only
    provider_raw: dict[str, JsonValue]      # {"properties": ..., "configuration": ...}
```

The record carries no git provenance, hostname, user path, account name, token or instance.
Measurements are stored in their table and are not repeated in `record_json`.

#### Non-qubit resources without a schema change (ADR 0006)

Core and storage treat `resource_kind` and `resource` as opaque strings. Only the adapter
that wrote them, and that adapter's `CalibrationReader`, interpret them. IBM rows, a neutral-atom
site and a logical error-correction patch are therefore all rows in the same table:

| resource_kind | resource | parameter | value_real | value_text | unit | measured_at |
|---|---|---|---|---|---|---|
| `qubit` | `qubit/3` | `T1` | 182.4 | | `us` | 2026-10-04T06:12:00Z |
| `gate` | `gate/cz/3,4` | `gate_error` | 0.0031 | | | 2026-10-04T06:40:00Z |
| `general` | `general` | `jq_6272` | 0.0020 | | `GHz` | 2026-10-04T06:12:00Z |
| `site` | `site/zone=entangling/row=3/col=7` | `occupancy_probability` | 0.991 | | | 2026-11-02T09:00:00Z |
| `site` | `site/zone=entangling/row=3/col=7` | `trap_frequency` | 92.0 | | `kHz` | 2026-11-02T09:00:00Z |
| `site_pair` | `site_pair/(3,7)-(3,8)` | `cz_fidelity` | 0.995 | | | 2026-11-02T09:00:00Z |
| `logical_patch` | `patch/L0` | `logical_error_per_round` | 0.0012 | | | 2027-01-15T12:00:00Z |
| `logical_patch` | `patch/L0` | `decoder` | | `pymatching-2.2` | | |
| `logical_patch` | `patch/L0` | `code_distance` | 7 | | | |

The neutral-atom and logical rows are illustrative. No such adapter exists. Under ADR 0006
decision 3, the code, distance and decoder of a logical patch will become a provenance layer
once an encoding layer exists. Until then, they are only measurements an adapter chose to
report. Adding these kinds needs a new adapter and its reader, and no change to the tables or
to `Measurement`.

**Limit.** Storage is level-neutral. Comparison is not, yet: `PhysicalFootprint`,
`FootprintCalibration` and `CalibrationReader.select` are physical-level types keyed by integer
qubits (ADR 0006, Consequences). M1.3c compares IBM snapshots only. Comparing non-qubit
resources needs a footprint generalization through a future schema bump.

### 3. Command surface

```
qci snapshot capture --backend NAME [--account ACCOUNT]                     (M1.3b)
qci snapshots [--backend NAME] [--limit N]                                  (M1.3b)
qci snapshot show SNAPSHOT_ID [--json]                                      (M1.3b)
qci snapshot export SNAPSHOT_ID --fixture PATH                              (M1.3b, developer)
qci snapshot compare BASELINE_ID CANDIDATE_ID --footprint-run RUN_ID [--json]   (M1.3c)
```

- `capture` is the only command that touches the network. It runs once and exits: no
  scheduling, retries, polling or background process. If the user wants a series, they run
  the command again.
- `capture` prints the snapshot ID, whether the content was new or identical to an existing
  snapshot, `calibrated_at`, and the measurement count. It exits 0. On any error it persists
  nothing, prints a sanitized message (section 4) and exits 1. Snapshots are not runs, so rule
  4's failed-run record does not apply.
- `capture` rejects fake backends (`fake_*`) and simulators with exit code 2. A static fake
  must never be stored as `live_calibration`.
- `snapshots` lists `snapshot_id`, backend, `calibrated_at`, first and last capture time, and
  capture count, newest first.
- `snapshot export --fixture` writes a sanitized test fixture (section 5). It is offline.
- `snapshot compare` is defined in section 7.

**Wiring.** A new port, `CalibrationSource`, lives in `qci/core/ports.py`:
`capture(backend_name: str) -> CapturedCalibration`. It returns the redacted raw payload, the
measurements and the capture options. The IBM implementation lives in
`qci/adapters/qiskit_ibm/live.py` and imports `qiskit_ibm_runtime` lazily. A
`SnapshotService` in `qci/services/` hashes the payload, deduplicates, assigns IDs and saves.
The service depends only on the port, so tests pass a stub source built from the committed
fixture.

### 4. Credentials

- **Saved account only.** QCI builds the client as `QiskitRuntimeService(name=ACCOUNT)`, where
  `ACCOUNT` defaults to `"default-ibm-quantum-platform"`. QCI always passes `name`, so the
  client never falls back to environment variables (see Findings). QCI never passes `token`,
  `url`, `instance` or `filename`, and offers no CLI option or environment variable for them.
  The user saves the account beforehand with Qiskit's own `save_account`. QCI never reads the
  account file itself.
- **Never stored.** The snapshot record, measurements, capture log, CLI output and test
  fixtures never contain a token, API key, account ID, instance identifier or CRN, or the
  account name. The backend is opened with `service.backend(NAME)`, without `instance`. The
  stored payload is only `backend.properties(refresh=True)` and `backend.configuration()`,
  converted with `to_jsonable` and then redacted.
- **Redaction at capture time** (`qci/adapters/qiskit_ibm/redact.py`, `redact_payload`). The
  function walks the converted payload and replaces values with
  `{"$redacted": "<rule>"}`, recording each replaced JSON path in `redactions`:
  - (a) the value of any mapping key, matched case-insensitively, in: `token`, `api_key`,
    `apikey`, `access_token`, `refresh_token`, `authorization`, `password`, `secret`,
    `instance`, `instance_id`, `crn`, `account`, `account_id`, `iam_id`, `user_id`, `email`,
    `hub`, `group`, `project`, `url`, `endpoint`, `proxies`;
  - (b) any string value, under any key, that contains `crn:`, starts with `Bearer `, has the
    JWT shape `eyJ…\.…\.…`, looks like an email address, or is a URL with user-info or a query
    string.

  The tag makes the removal explicit. It leaves a structural marker, not the value. The
  `CalibrationReader` already treats any tagged mapping as unavailable. Redaction is
  idempotent, so redacting an already-redacted payload changes nothing. Rule 3 ("keep raw
  data") yields here, but only for these values.
- **Errors and logs.** Capture errors pass through `sanitize_error_message`. In M1.3b that
  function gains CRN, bearer-token and JWT redaction alongside its existing URL-credential
  stripping. QCI writes no log files and configures no logging handlers, so library log
  records never reach storage.
- **Tests.** Tests never construct `QiskitRuntimeService`. The live adapter takes a
  `service_factory` callable, and tests inject a stub. A guard test monkeypatches
  `qiskit_ibm_runtime.QiskitRuntimeService` to raise if any test constructs it. Sentinel
  strings stand in for every credential (section 5).

### 5. Fixture: one real capture, sanitized and committed

1. The user runs this once, manually, with a throwaway store:
   ```bash
   export QCI_HOME=$(mktemp -d)
   qci snapshot capture --backend <ibm_backend>
   qci snapshot export <SNAPSHOT_ID> --fixture tests/fixtures/snapshots/<ibm_backend>.json
   ```
2. `export --fixture` applies `redact_payload` again and writes the full `CalibrationSnapshot`
   record plus its measurements. It replaces `snapshot_id` and `capture_id` with fixed
   placeholders. It then scans the serialized output for exact matches of the active saved
   account's token, instance and URL, which it reads through the client's own
   `AccountManager.get(name=...)`. These values are held in memory for the scan only, and are
   never printed or written. **It aborts and writes nothing on a match.** An
   exact match outside the redaction rules means the rules are incomplete. That must be fixed
   in code, not by hand-editing the fixture.
3. The user reviews `git diff` of the fixture and commits it with a message that names the
   backend and `calibrated_at`. The full payload is kept, not trimmed. A trimmed payload would
   no longer be a real capture, and the real gate-name and parameter differences are what the
   fixture is there to cover.

**What sanitization removes.** It removes exactly the values matched by rules (a) and (b) in
section 4, plus the two local IDs (`snapshot_id`, `capture_id`). It removes nothing else.
Calibration values, dates, gate names, qubit indices, `backend_name` and `backend_version`
stay. They are public device data.

**How tests prove it** (M1.3b):

- `test_fixture_has_no_credential_material`: walks every key and string in the committed
  fixture. It asserts that no rule (a) key holds anything but a `$redacted` tag, and that no
  string matches a rule (b) pattern.
- `test_fixture_redactions_match_tags`: asserts that the fixture's `redactions` list equals
  the set of paths holding a `$redacted` tag.
- `test_fixture_is_redaction_fixed_point`: asserts `redact_payload(fixture) == fixture`, so
  nothing in the committed file would be redacted by the current rules.
- `test_redaction_removes_sentinels`: builds a synthetic payload with a sentinel in every rule
  (a) key and every rule (b) pattern, nested in dicts and lists and inside gate parameters. It
  asserts that no sentinel substring occurs in the canonical JSON bytes of the output, that
  every replaced path is listed, and that the calibration subtrees are byte-identical before
  and after.
- `test_capture_persists_no_credentials`: runs `qci snapshot capture` through the CLI with a
  stub service whose account and backend objects carry sentinel token, instance and CRN
  values. It asserts that no sentinel occurs in the raw bytes of `qci.db`, in stdout or stderr,
  or in the `caplog` text.
- `test_fixture_export_aborts_on_account_match`: plants a sentinel equal to the stub account's
  token under a key no rule covers. It asserts that the export exits non-zero and writes no
  file.

### 6. Real-device payloads versus fakes

These differences are already visible between installed fakes, or follow from the client code
cited above:

| Difference | Evidence | Handling |
|---|---|---|
| Two-qubit gate names differ: Heron devices report `cz`, plus `rzz` and `rx` when fractional gates are on; Eagle devices report `ecr`. | `FakeFez` gates: `cz, id, reset, rx, rz, rzz, sx, x`. `FakeSherbrooke`: `ecr, id, reset, rz, sx, x`. | The reader looks up the exact `(name, ordered qubits)`. An absent operation is `available=False` with the note "no calibration entry for this operation on these ordered qubits". |
| Qubit parameter sets differ. | `FakeFez` qubits lack `frequency` and `anharmonicity`, which `FakeSherbrooke` reports. | A parameter present on one side only is `status="unavailable"`, with a null value on the missing side. |
| A qubit's entry list can be empty or short on a real device. | Not verifiable offline. The fixture will show it if present. | An empty list is `available=False`. Missing parameters have no measurement row. |
| Non-finite or complex values. | `to_jsonable` tags them. | `_value` returns `None`, so the value is unavailable, never 0. |
| Dates are converted to the capturing machine's local timezone. | `utc_to_local_all`. | The adapter converts every `datetime` to UTC before `to_jsonable`. The instant is unchanged, and the local offset came from the client, not the provider. This also keeps content hashes stable across machines. |
| Fractional gates are filtered from the configuration by default. | `filter_raw_configuration`. | The capture passes `use_fractional_gates=False` explicitly and records it in `capture_options` and in the hash. |
| `properties()` can return `None`. | `IBMBackend.properties`. | The snapshot is stored with `properties: null`, no measurement rows and a note. The reader reports every resource as unavailable. |
| Pairwise `general` entries (`jq_*`, `zz_*`). | Both fakes. | Stored as measurements with `resource_kind="general"`. In comparison they stay excluded, as now (D14). |

**`CalibrationReader` reports these as unavailable, never zero.** M1.3c reuses
`IbmPropertiesCalibrationReader` unchanged. Its existing rules already cover every row of the
table: an absent qubit or empty entry list gives `available=False`, an absent or ambiguous gate
entry gives `available=False` with a note, and a tagged or missing value gives `value=None`.
`compare_hardware` then turns each of these into an `unavailable` entry and sets
`relevant_hardware_changed` to null. The measurement extractor and the reader share the same
parsing helpers (`_value`, `_date`, `_parameters` in `calibration.py`). A M1.3b test asserts
that, on the real fixture, every value the reader selects equals the matching measurement row.

### 7. Snapshot-to-snapshot comparison (M1.3c), reusing `compare_hardware`

`compare_hardware(baseline: Run, candidate: Run, ...)` uses only the two runs'
`backend_snapshot` and `backend.provider`. All of its comparison logic sits after the
"provider differs" and "footprint unusable" guards. The refactor is one extraction:

```python
# qci/compare/hardware.py
def compare_calibration(
    baseline_snapshot: BackendSnapshot,
    candidate_snapshot: BackendSnapshot,
    baseline_footprint: PhysicalFootprint,
    candidate_footprint: PhysicalFootprint,
    reader: CalibrationReader,
    notes: list[str],
    common: dict[str, Any],
) -> HardwareComparison:
    ...  # the current body from "shared_qubits = ..." to the final return, moved verbatim
```

`compare_hardware` keeps its signature, its guards and its notes, and its last line becomes
`return compare_calibration(bs, cs, baseline_footprint, candidate_footprint, reader, notes,
common)`. Nothing else in the module changes.

`qci/compare/snapshots.py` adds `compare_snapshots(baseline, candidate, footprint, reader_for)`:

- It returns `not_comparable`, with a reason, unless both snapshots have the same `provider`
  and `backend_name`. Calibration of different devices is never presented as change of one
  device.
- It builds a `BackendSnapshot` view of each `CalibrationSnapshot`: `source`, `captured_at`,
  `calibrated_at`, `provider_raw`, and `basis_gates` and `coupling_edges` from the stored
  configuration. It passes the same footprint on both sides, so `resources_identical` is true
  by construction. `global_snapshot_changed` compares content hashes.
- The footprint comes from a stored run, through the existing `footprint.py`. The run only
  selects which physical resources to read. It is never compared with a snapshot. A run on
  `fake_fez` can scope `ibm_fez` snapshots, because they share qubit indices. The output
  records the footprint run ID and that run's backend name. If the two backend names differ,
  the output adds a note saying the footprint was taken from a different backend. Qubits
  outside a snapshot's range are already unavailable in the reader.
- It returns a new `SnapshotComparison` model: snapshot IDs, `calibrated_at` and
  `captured_at` of each, the footprint run ID and its backend, the elapsed time between
  captures as a `calculated` value, and the `HardwareComparison` from `compare_calibration`.
  Like run comparisons, it is never persisted. It uses the same neutral vocabulary: deltas
  are candidate minus baseline, and the words in rule 8 do not appear.
- The rules of `qci.compare.v3` are unchanged. `ComparisonPolicy.version` and
  `ENGINE_VERSION` are not bumped, and `comparison_id` for run comparisons is not affected.
  The snapshot comparison has its own `snapshot_comparison_id` and method version,
  `qci.compare.snapshot.1`.

**How existing outputs are guaranteed byte-identical.** M1.3c is two commits, in order:

1. **Golden files first, on unchanged code.** Add `tests/golden/compare/*.json`, generated by
   `CompareService.compare(...).model_dump_json(indent=2)` from fixed `conftest.physical_run`
   and `make_run` records (fixed IDs, timestamps and seeds, so the output is deterministic).
   Cover every `compare_hardware` exit: unchanged; changed on a used qubit and on a used gate;
   unused-qubit-only change; date-only change; different mapping (`partially_comparable`);
   missing relevant parameter; missing snapshot; dynamic footprint; unknown provider;
   cross-provider; plus one comparison with an observable. Add
   `tests/test_compare_golden.py`, which asserts that current output equals each file byte for
   byte. This commit must pass on unmodified `src/`.
2. **Then the refactor.** The second commit changes `src/` and leaves the golden files and
   their test untouched. The diff of `tests/golden/` between the two commits is empty, and the
   golden test passes after the refactor. The existing byte-identity CLI tests stay as they
   are.

## Proposed acceptance criteria

### M1.3b: capture and storage

- [ ] `qci/domain/snapshot.py` defines `Measurement` and `CalibrationSnapshot` as in section 2:
      frozen, `extra="forbid"`, with no provider SDK import (the architecture test covers the
      module).
- [ ] `CalibrationSource` port in `qci/core/ports.py`. `SqliteSnapshotRepository` with the
      three tables in section 1 and `snapshot_db_schema = 1`. It has `save`, `get`,
      `get_by_hash`, `list` and `measurements`, and no update or delete method. A test
      asserts that the class has no attribute named `update*` or `delete*`.
- [ ] An existing M0/M1 database opens unchanged. The `runs` table and `DB_SCHEMA_VERSION`
      are untouched, and the snapshot tables are created beside them.
- [ ] Capturing identical content twice creates one snapshot and two capture rows. Changed
      content creates a second snapshot. Content hashes do not depend on the local timezone:
      a test captures the same stub payload under two `TZ` settings and gets one snapshot.
- [ ] Measurements: one row per reported (resource, parameter). A non-finite or complex value
      is stored with both value columns null. An unreported parameter has no row. No
      unavailable value is stored as 0.
- [ ] A test stores rows with `resource_kind` values `site` and `logical_patch` through the
      repository, reads them back unchanged, and runs no migration.
- [ ] `qci snapshot capture --backend NAME [--account ACCOUNT]` constructs the client only as
      `QiskitRuntimeService(name=ACCOUNT)`. A test asserts the exact keyword arguments
      through the injected factory. It rejects `fake_*` names and simulators with exit code 2,
      and on any error persists nothing and exits 1.
- [ ] `qci snapshots`, `qci snapshot show ID [--json]` and
      `qci snapshot export ID --fixture PATH` work offline. `--json` output
      validates as `CalibrationSnapshot`.
- [ ] `redact_payload` and the six sanitization tests in section 5 exist and pass.
      `sanitize_error_message` redacts CRNs, bearer tokens and JWTs.
- [ ] One real sanitized capture is committed under `tests/fixtures/snapshots/`, together
      with a test showing the reader and the measurement rows agree on every selected value.
- [ ] No test constructs `QiskitRuntimeService`, enforced by a guard. No test opens a
      network connection.
- [ ] `docs/architecture.md` and `docs/data-model.md` describe the snapshot store, and README
      documents the capture command and the saved-account prerequisite.
- [ ] All gates pass.

### M1.3c: footprint-scoped snapshot-to-snapshot comparison

- [ ] The first commit adds golden compare JSON for every `compare_hardware` exit listed in
      section 7 and passes on unmodified `src/`.
- [ ] The second commit extracts `compare_calibration` and changes no golden file. Its golden
      test, and all existing compare tests, pass unchanged. `ComparisonPolicy.version`
      stays `qci.compare.v3` and `ENGINE_VERSION` stays `qci.compare.engine.4`.
- [ ] `qci snapshot compare BASE CAND --footprint-run RUN [--json]` compares only the
      calibration of the run's physical footprint, using `IbmPropertiesCalibrationReader`
      unchanged.
- [ ] Snapshots from different providers or backends give `not_comparable` with a reason, and
      no parameter comparisons.
- [ ] A footprint from a run on a different backend name gives a note. A footprint qubit
      outside a snapshot's range is unavailable.
- [ ] On the committed real fixture against a synthetic second snapshot derived from it:
      a changed footprint value gives `changed`, with delta = candidate minus baseline; a
      change outside the footprint sets only `global_snapshot_changed`; a removed parameter or
      a gate name absent from the payload gives `unavailable` and
      `relevant_hardware_changed = null`, never 0.
- [ ] Identical snapshots (same content hash) give `unchanged` and
      `global_snapshot_changed = false`.
- [ ] `--json` output is byte-identical across repeated invocations. The comparison is never
      persisted: the database bytes are unchanged after the command.
- [ ] Rendered and JSON output contain none of the rule 8 words.
- [ ] Docs updated, all gates pass, and the live capture is run manually by the user. No
      test performs one.

## Consequences

- **Good:** drift evidence for a footprint at no QPU cost, history by explicit repeated
  capture, and storage that admits non-qubit resources without a migration.
- **Good:** comparison reuses the existing reader and calibration logic through one
  extraction. Existing outputs are protected by golden files written before the refactor.
- **Cost:** raw payloads stay inline, which for a 156-qubit device is several hundred KB per
  distinct snapshot. Deduplication limits growth, and M0.5 blobs remove the rest (D4).
- **Cost:** history is forward-only. Calibration published before the first capture is not
  available to QCI.
- **Cost:** the measurement projection duplicates data held in the raw payload. It exists for
  generic queries and future providers. M1.3c's comparison reads the raw payload through the
  reader, and a test keeps the two consistent.
- **Known gap:** `compare_hardware` takes the first non-null unit and does not check that
  baseline and candidate units agree. Real devices could change a unit between captures.
  Fixing this is a comparison-rule change, which needs a policy bump. It is not part of M1.3.
- **Revisit when:** historical capture is confirmed against the server, a second provider
  arrives, or an encoding layer arrives (ADR 0006).
