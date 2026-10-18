# ADR 0008: Historical calibration backfill

- **Status:** Accepted (2026-10-16), with amendments to the M1.5b protocol: a stricter
  `honored` (within 48 hours, and monotonic across offsets), a ground-truth cross-check
  against stored live snapshots, predictions P1-P4 frozen, and the known rate-limit facts
  recorded (sections 1, 2, 6 and 8).
- **Date:** 2026-10-16 (proposed), 2026-10-16 (accepted)
- **Milestone:** M1.5 (`PLAN.md`). This ADR is M1.5a. It resolves D21's verification protocol,
  and designs backfill only conditionally on that verification.

## Context

Snapshot history in QCI is forward-only (ADR 0005): it starts at the user's first capture.
The IBM client accepts a datetime for calibration properties, and one manual observation on
`ibm_fez` (2026-10-10, ADR 0005 Findings) returned an older document, so the server appears to
honor it. One observation on one device is not enough to build on. D21 asks for several dates
and devices, how far back lookups work, and IBM's terms and rate limits.

This ADR therefore designs M1.5 in four sub-steps, of which only the first is certain:
verify first, build only what the verification supports, and treat stopping as a valid
outcome.

Constraints: snapshots are insert-only and deduplicated by content hash (ADR 0005); a
backfilled snapshot must never be mistaken for a live capture; QCI makes no network call
outside an explicit, user-run command; and the product reports data, never analysis claims
(rule 8).

## Findings from the installed client

Read from the installed `qiskit-ibm-runtime` 0.50.0 source on 2026-10-16. No network call was
made. ADR 0005's Findings already trace the call path; these facts are new or matter here.

- **Properties only.** `IBMBackend.properties(refresh=False, datetime=None)`
  (`ibm_backend.py:325`) forwards a datetime as the `updated_before` query parameter
  (`api/rest/cloud_backend.py:62-78`). `configuration()` (`ibm_backend.py:404`, and
  `cloud_backend.py:46`, which accepts only `calibration_id`) has no datetime parameter.
  **Configuration cannot be requested for a past time,** so `n_qubits`, `coupling_map` and
  `supported_instructions` have no history through this client.
- **A datetime request is not cached** (`ibm_backend.py:375`), so repeated requests reach the
  server each time. The current-properties cache is not touched.
- **Timezone handling.** The client converts the requested datetime with `local_to_utc`
  (`utils/converters.py:45`). An aware datetime whose offset is not zero is treated as local
  time: its tzinfo is *replaced* with the local zone, not converted. Only a datetime in UTC
  with a zero offset is sent unchanged. QCI must always send aware UTC datetimes.
- **The client overwrites `backend_name`** in every properties response with the backend's
  own name (`cloud_backend.py:81`), so the payload's `backend_name` cannot show which device
  the server answered for.
- **Client-side retries.** The client's HTTP session retries a request up to 5 times with
  backoff (factor 0.5) on 500, 502, 503, 504, 520, 521, 522 and 524 responses
  (`api/session.py`, `STATUS_FORCELIST` and `_initialize_retry`). 429 is not in that list, so
  a too-many-requests response reaches the caller at once, as `RequestsApiError` with
  `status_code` 429 and the IBM error code in its message. QCI adds no retries of its own.
- **Docstrings still say not implemented.** `IBMBackend.properties` and
  `RuntimeClient.backend_properties` list `NotImplementedError` for a datetime, but neither
  body raises it. Only server responses can settle D21.

## Decision

### 1. Sub-steps and the decision rule

| Sub-step | Content | Who runs it |
|---|---|---|
| **M1.5a** | This ADR and `scripts/verify_historical_calibration.py`. No `src/` change. | Claude, reviewed by the user |
| **M1.5b** | The D21 verification (section 2) on three devices, plus the user's check of IBM's terms and rate limits (section 6). Results recorded in this ADR's Findings. No code. | The user, by hand |
| **M1.5c** | `qci snapshot backfill`, only if M1.5b supports it, narrowed to what it supports. | Claude, after approval |
| **M1.5d** | A research experiment on D27 (and the calibration side of H2), with predictions committed before any backfilled data is analyzed. | Claude and the user |

**Decision rule after M1.5b.** Each device is judged on its own. For a device, the
*verified depth* is the largest offset in the protocol whose request is `honored` and every
smaller offset is `honored` or `inconclusive:no_newer_document`. Only `honored` counts:
`honored_distant`, `non_monotonic`, any `ignored` label and any `raises` label end the chain.

- **Proceed** with M1.5c for every device whose verified depth is at least 30 days, whose
  repeat is `repeat:identical`, and that had no `raises` and no `non_monotonic` outcome in
  part 1 and no `raises` and no `different_document:inconsistent` outcome in part 2.
  Backfill for that device is limited to its verified depth.
- **Narrow** when only some devices qualify, or a device's verified depth is at least 7 but
  under 30 days: M1.5c covers only the qualifying devices, each limited to its verified depth.
  A depth of 7 days is the minimum worth building for.
- **Stop** when no device qualifies (every verified depth is below 7 days, or every device has
  a `repeat:different`, `raises`, `non_monotonic` or `different_document:inconsistent`
  outcome), or when the terms check
  (section 6) does not permit programmatic historical requests at the planned pacing. Then:
  D21 is resolved as "not supported for QCI's use", history stays forward-only, M1.5c is not
  built, and M1.5d is either redesigned on forward captures or dropped, in a separate approved
  step. This is a valid outcome of M1.5, not a defect.
- **Re-run once, never in a loop,** when a device's results are all `inconclusive`. If the
  second run is also inconclusive, that device does not qualify.

A `non_monotonic` outcome disqualifies the device even beyond its verified depth, since the
grid in section 5 assumes that a further-back request never returns a newer document.

The ground-truth cross-check (section 2, part 2) does not change the verified depth, but it
enters the rule:

- `match` and `different_document:lag_consistent` do not disqualify.
- `different_document:inconsistent` disqualifies the device: a lookup as of a capture time
  returned a document that the stored capture rules out.
- If any `different_document:lag_consistent` occurs on a device that qualifies, Findings must
  record, and M1.5c's documentation must state, that backfilled history for that device is
  documents ordered by their provider stamp, not what a user would have seen at a given
  time: a document can be stamped before a time and still have been published after it.

The applied rule, each device's verified depth and the resulting choice are recorded in
Findings at M1.5b before M1.5c starts.

### 2. The D21 verification protocol

`scripts/verify_historical_calibration.py`, protocol `qci.d21.verify.3` (amended at and after
acceptance; versions 1 and 2 were never run):

- **Devices:** `ibm_fez`, `ibm_kingston`, `ibm_marrakesh`, in that order. These are the three
  devices in `FAKE_DEVICE_SOURCES` (ADR 0007).
- **Anchor:** one UTC instant per invocation, the start time truncated to whole seconds,
  printed first. Requested times are `anchor - N days` for N in 1, 7, 30, 90, 180 and 365,
  sent as aware UTC datetimes with a zero offset (see Findings on `local_to_utc`).
- **Hash:** each properties document, returned or stored, is normalized exactly as
  `qci snapshot capture` normalizes it (UTC datetimes, lossless JSON, redaction, through
  `build_captured_calibration`), and its properties part is hashed with `hash_json`. Only the
  hash is kept. Properties only: backfilled snapshots have no configuration (section 3).
- **Pacing:** a pause between requests (default 5 s, minimum 1 s). No retries by QCI; the
  client's own retries on 5xx responses still apply (Findings). The first too-many-requests
  response (HTTP 429, or IBM error code 1202 anywhere in the exception chain) stops the whole
  script, labeled `raises:<Type>:too_many_requests`, with exit code 3.

**Part 1, offsets.** Per device: one current request (`properties(refresh=True)`), then one
request per offset, nearest first, then a **repeat** of the 30-day request with the identical
requested instant: 8 requests per device. With `requested` the requested instant, `returned`
and `current` the two documents, and `floor` the oldest `last_update_date` returned so far for
that device by less distant requests (the current request is the least distant), the outcome
is the first row that applies:

| Outcome | Condition |
|---|---|
| `inconclusive:no_document`, `inconclusive:no_returned_date` | no document, or no returned date |
| `non_monotonic` | the returned `last_update_date` is after `floor`: a further-back request returned a newer document |
| `inconclusive:no_current_date` | the hashes are equal and the current document has no date |
| `inconclusive:no_newer_document` | the hashes are equal, and the current `last_update_date` is itself at or before `requested`: nothing newer was published, so honored and ignored cannot be told apart |
| `ignored` | the hashes are equal, and the current `last_update_date` is after `requested` |
| `ignored:returned_after_requested` | a different document whose `last_update_date` is after `requested` |
| `honored_distant` | a different document whose `last_update_date` is more than 48 hours before `requested` |
| `honored` | a different document whose `last_update_date` is at or before `requested` and within 48 hours of it |
| `raises:<Type>` | the request raised; only the exception's type name is printed |

`honored` therefore requires all four conditions of the amendment: (a) at or before the
requested time, (b) different from the current document, (c) within 48 hours before the
requested time, and (d) no newer than any less distant request's result.

**Repeat:** `repeat:identical` when the second 30-day request returns the same hash as the
first, otherwise `repeat:different`. A different result means the same request does not
return the same content, and lookups on that device cannot be given a stable provenance.

**Part 2, ground-truth cross-check.** The script opens the QCI store once, read-only
(`SqliteSnapshotRepository(read_only=True)`, SQLite `mode=ro`), before any request, and reads
every stored `live_calibration` snapshot of the three devices (newest first capture first, at
most `--max-cross-checks` per device, default 10). Per snapshot, after that device's part 1,
it requests properties as of the snapshot's first `captured_at` and compares the hash of the
returned properties with the hash of the stored `provider_raw["properties"]`. With `L` the
stored document's `last_update_date`, `T` its first `captured_at` (the requested time) and
`R` the returned `last_update_date`, the outcome is the first row that applies:

| Outcome | Condition |
|---|---|
| `inconclusive:no_document` | no document returned |
| `match` | the properties hashes are equal (then `R == L`) |
| `inconclusive:no_returned_date`, `inconclusive:no_stored_date` | `R` or `L` is missing |
| `different_document:lag_consistent` | `L < R <= T`: a document stamped after the stored one and at or before the capture time |
| `different_document:inconsistent` | any other different document: `R < L`, `R == L` with a different hash, or `R > T` |
| `raises:<Type>` | the request raised |

`R > T` is not one of the cases named at acceptance. It is classed as inconsistent, since a
lookup as of `T` returned a document stamped after `T`.

`different_document:lag_consistent` fits publication lag: a document stamped before the
capture time but published after it. M1.3b observed this on `ibm_fez`: a capture at
2026-10-10T01:12:12Z held a document dated 00:19:17Z, and a request minutes later returned a
newer document dated 00:58:58Z, also before the capture (ADR 0005 Findings). A lookup as of
the capture time then returns the later-stamped document, which the capture never saw. It is
recorded with both dates and is never read as evidence that lookups are ignored. A stored
document whose payload was redacted under older rules could also hash differently; the
redaction rules have not changed since M1.3b (`redact.py` was last changed in `10bf573`).

**Output.** One line each for the protocol and anchor, the store's SHA-256 before any
request, the number of stored live snapshots per device, every request, and the store's
SHA-256 at the end. Each request line holds the device, the snapshot ID (part 2 only), the
requested time (or `current`), the returned and stored `last_update_date`, the hashes and the
outcome. Nothing else is printed: no account data, backend version, payload content, path or
error text. The script writes nothing to any QCI store and creates no file. It is
type-checked by the gates and never run by pytest.

The commands, run by the user in zsh from the repository root, are in PLAN.md's M1.5b
section and repeated here:

```bash
mkdir -p ~/qci-m15b
shasum -a 256 ~/.qci-live/qci.db
PYTHONPATH=src .venv/bin/python scripts/verify_historical_calibration.py --account default-ibm-quantum-platform --store "$HOME/.qci-live/qci.db" --pause 5 | tee ~/qci-m15b/d21.txt
shasum -a 256 ~/.qci-live/qci.db
```

The script's own before and after hashes, and the two `shasum` lines, show that the store was
not modified. `scripts/check_historical_calibration.py` (ADR 0005, one request on one device)
is kept as the record of the first observation; this script supersedes it for D21.

### 3. Provenance: a backfilled snapshot is always distinguishable

**Decision: provenance is recorded per capture, the content hash is unchanged, and the
snapshot store moves to `snapshot_db_schema = 2` with one new insert-only table.**

- **Capture records.** `SnapshotCapture` gains `method: Literal["live_capture",
  "historical_lookup"] = "live_capture"` and `requested_before: AwareDatetime | None = None`.
  A validator requires `requested_before` exactly when `method` is `historical_lookup`. The
  new table `snapshot_lookups` (`capture_id` primary key, `requested_before`, `method_version`)
  holds one row per historical capture. A capture with no row is a live capture, which is
  true of every existing row by construction, so no existing row or column changes.
- **Snapshot source.** `SnapshotSource` gains `historical_lookup`: calibration a provider
  published for a real device at an earlier time, returned by a lookup for a requested time.
  A snapshot's `source` records how QCI first obtained that content. `captured_at` stays
  "when QCI first read this content", which for a lookup is the request time, not a
  calibration time; `calibrated_at` is the returned `last_update_date`.
- **No historical configuration.** A lookup stores `provider_raw = {"properties": ...,
  "configuration": null}`. The configuration current at backfill time is not paired with an
  older properties document, since that would mix two times in one record (Findings).
- **Deduplication.** The content hash formula is unchanged (provider, backend name, capture
  options, provider raw). `requested_before` is never put into `capture_options`, so two grid
  points that return the same document produce one snapshot and two lookup captures. A lookup
  and a live capture never share content in practice, since a lookup's configuration is null.
  If they ever did, the snapshot keeps its first `source` and each capture row still says how
  it was obtained.
- **Schema.** `CalibrationSnapshot.schema_version` stays 1: its JSON shape is unchanged and
  only an enum value is added. The store version is a schema change, with an explicit upcast:
  opening a version 1 store for writing creates `snapshot_lookups` and records version 2, and
  changes no existing row. A read-only command on a version 1 store reads every capture as a
  live capture. Store damage detection accepts the version 1 table set (three tables) and the
  version 2 set (four). An older QCI opening a version 2 store reports the other schema
  version, as now. The `runs` table and `DB_SCHEMA_VERSION` are untouched.
- **Validation before storing.** A lookup is stored only if the returned `last_update_date`
  is present and at or before `requested_before`. Otherwise nothing is stored for that
  request, and the invocation stops with an error naming the device and both times.

What existing commands do with a historical snapshot, unchanged in M1.5c:

- `qci snapshot compare-run` returns `not_comparable` at exit 3 (source is not
  `live_calibration`).
- `qci snapshot compare` compares it, with the existing "snapshot sources differ" note when
  the other side is live. Without a configuration, the presence check under
  `--allow-footprint-backend-mismatch` lists every footprint resource as missing, so a
  footprint from a fake run gives `not_comparable`. `elapsed_between_captures` is the
  difference of request times. Both are recorded as D28 in `PLAN.md`.

### 4. Command surface (M1.5c)

```
qci snapshot backfill --backend NAME --days N [--step-hours H] [--max-requests M]
                      [--pause S] [--account ACCOUNT]
```

An explicit, user-run command, and the only networked command besides `qci snapshot
capture`. It rejects `fake_*` names and simulators with exit 2, checks the store before any
network request, and constructs the client only as `QiskitRuntimeService(name=ACCOUNT)`.

### 5. Sampling: a chosen grid of the latest earlier document

A lookup returns the latest document published before the requested time. Backfill
therefore samples history on a grid.

- **Default grid:** one requested time per day at 00:00:00 UTC, newest first, going back
  `--days` days from the most recent past midnight. `--step-hours` changes the spacing
  (minimum 1). Grid times are fixed UTC instants, so a re-run requests the same times.
- **`--days` is capped** at the device's verified depth recorded at M1.5b (section 1), as an
  explicit list in the IBM adapter. A device without an entry is not backfilled.
- **What the grid cannot recover:**
  - documents published and superseded between two grid points (ADR 0005 observed two
    `ibm_fez` documents within one hour);
  - publication times: a document's `last_update_date` can precede its publication (ADR 0005
    Findings), and the grid shows only that the document was the latest at the grid time;
  - configuration history (Findings), so device revisions in qubits, couplings or supported
    instructions are invisible;
  - anything older than the server keeps, or than the device's online date;
  - whether the returned document is what the provider published at that time, or a later
    reprocessing of it.

Each parameter keeps its own provider date, as in every snapshot.

### 6. Pacing, limits and resumability

- **No daemon, scheduler or polling loop.** Each invocation is one bounded run.
- **Cap:** `--max-requests` defaults to 30 and may not exceed 100. The invocation stops at
  the cap and prints how many grid times remain.
- **Pacing:** `--pause` seconds between requests, default 10, minimum 2. Values from the
  terms check below override these defaults before M1.5c is approved.
- **No retries.** The first error stops the invocation, including the first too-many-requests
  response (HTTP 429 or IBM error code 1202). Everything stored before it is kept, since each
  lookup is stored in its own transaction. The client's own retries on 5xx responses
  (Findings) are outside QCI's control and are stated in the command's help.
- **Resumable:** before each request, the command looks for an existing lookup capture with
  the same backend and `requested_before`. If it exists, the grid time is skipped and counts
  against no cap. Re-running the same command continues where the last one stopped.

**IBM terms and rate limits (to be checked by the user at M1.5b, before M1.5c):**

> Documented: job submission is limited to 5 per minute per user (not applicable; QCI submits
> no jobs). No published limit was found for reading properties. A generic too-many-requests
> error exists (code 1202); the script and the M1.5c command stop at the first such error,
> with no retries. Terms of service: to be checked by the user before M1.5c.
>
> _Still to record at M1.5b: the terms-of-service documents checked (title, URL, date read),
> what they say about programmatic or bulk requests for historical calibration data, and
> whether the planned pacing (10 s between requests, at most 100 per invocation) is within
> them. If the terms do not permit it, the decision rule in section 1 says stop._

### 7. What M1.5 does not do

- No analysis claims in product output. QCI stores and displays backfilled documents; it
  does not report trends, drift rates, stability, or whether a device or a fake is suited to
  a workload. Analysis lives in M1.5d's experiment scripts and notes, labeled as research.
- No automatic scheduling, polling, background capture or retries.
- No historical configuration, and no pairing of current configuration with past properties.
- No change to `qci compare`, `qci snapshot compare`, `qci snapshot compare-run`, their
  method versions, or the golden files.
- No backfill for a device without a verified depth, or beyond it.
- No execution on hardware, no change to the run schema, and no new comparison.

### 8. Acceptance criteria

#### M1.5b: verification of D21, run by the user

- [ ] The user runs the commands in section 2 (protocol `qci.d21.verify.3`) on the three
      devices. The full output is recorded verbatim in Findings ("D21 verification
      (M1.5b)"), with the anchor time.
- [ ] Findings record, per device: each offset's outcome, the returned `last_update_date`,
      whether the repeat is identical, any `honored_distant` or `non_monotonic` outcome, and
      the verified depth.
- [ ] Findings record every cross-check outcome with `L`, `R` and `T`, and classify each
      `different_document` as `lag_consistent` or `inconsistent`. Any
      `different_document:inconsistent` disqualifies its device. If any
      `different_document:lag_consistent` occurs on a qualifying device, Findings state that
      backfilled history for that device is documents by stamp time, not what a user would
      have seen at a given time.
- [ ] The store hash is identical in the script's `store_sha256_before` and
      `store_sha256_after` lines and in both `shasum` lines.
- [ ] If the script stopped at a too-many-requests response, that is recorded, and the run is
      not repeated before the terms check.
- [ ] The terms-of-service finding completes section 6.
- [ ] The decision rule in section 1 is applied and its result (proceed, narrow or stop, per
      device) is recorded. `PLAN.md` is updated to match: on stop, D21 is resolved, M1.5c is
      removed and M1.5d is marked for redesign or dropped.
- [ ] No QCI code changes in M1.5b.

#### M1.5c: `qci snapshot backfill` (only if M1.5b supports it)

- [ ] `SnapshotSource.HISTORICAL_LOOKUP`, `SnapshotCapture.method` and
      `SnapshotCapture.requested_before` exist as in section 3, with the validator. The
      committed `ibm_fez` fixture validates unchanged.
- [ ] `snapshot_db_schema = 2` with the `snapshot_lookups` table. A test opens a version 1
      store read-only (every capture reads as `live_capture`, nothing is written) and for
      writing (the table is created, the version becomes 2, and every existing row is
      byte-identical). A version 1 table set and a version 2 table set are both accepted;
      any other partial set is `DamagedStoreError`.
- [ ] The content hash formula is unchanged. Two grid times returning one document give one
      snapshot and two lookup captures. `requested_before` is not in `capture_options`.
- [ ] A lookup stores `configuration: null`. A test asserts that the client's
      `configuration()` is not stored for a lookup.
- [ ] Requested times are aware UTC datetimes with a zero offset. A stub test asserts the
      exact `datetime` keyword the client receives under two `TZ` settings.
- [ ] A returned `last_update_date` that is missing or after `requested_before` stores
      nothing for that request and stops with exit 1, naming the device and both times.
- [ ] The grid is as in section 5 (UTC midnights, newest first, `--step-hours` minimum 1),
      and `--days` above the device's verified depth, or a device with no verified depth,
      exits 2 with nothing requested.
- [ ] The first too-many-requests response (HTTP 429, or IBM error code 1202 in the exception
      chain) stops the invocation with exit 1, with nothing retried by QCI and everything
      stored before it kept. A stub test raises it on the third request and asserts two
      stored lookups and three requests.
- [ ] `--max-requests` defaults to 30 and is capped at 100. `--pause` defaults to 10 and has
      a minimum of 2, unless the section 6 finding sets other values. A stub test counts the
      requests and the pauses.
- [ ] Re-running after a stub error resumes: grid times already stored are skipped without a
      request, and the run completes the rest.
- [ ] `fake_*` names and simulators exit 2. The store is checked before any request. The
      client is constructed only as `QiskitRuntimeService(name=ACCOUNT)`, asserted through
      the injected factory. No test constructs the real client or opens a connection.
- [ ] `qci snapshot show` prints the source and, for each lookup capture, its
      `requested_before`. `qci snapshots` output for existing stores is unchanged.
- [ ] `qci compare`, `qci snapshot compare` and `qci snapshot compare-run` output is
      unchanged for existing inputs, and the golden files are unchanged.
- [ ] `docs/architecture.md`, `docs/data-model.md`, README and `CLAUDE.md` describe the
      command and the provenance. Where M1.5b recorded `different_document:lag_consistent`
      for a device, they and `qci snapshot backfill --help` state that its backfilled history
      is documents by stamp time, not what a user would have seen at a given time. All gates
      pass, and the neutral-wording check has no unexplained hit.
- [ ] Manual live check by the user: one small backfill (for example `--days 3`) on one
      qualifying device, recorded in Findings, with the store hash changing only through
      the backfill.

#### M1.5d: research experiment, with predictions pre-registered

**P1-P4 were pre-registered before any historical data was seen** (2026-10-16, at the
acceptance of this ADR). They may be amended only by a dated note in this section, written
before M1.5d collects any backfilled data, and only to fix a design problem (for example a
definition that cannot be computed), never in response to a result. Disclosure: they were
written after the M1.4c live check, which showed fake-to-live `readout_error` ratios of about
7.7 and 15.5 on `ibm_marrakesh` qubits 11 and 13 (ADR 0007 Findings). No backfilled or
historical calibration value had been seen.

Definitions, frozen with the predictions:

- **Data:** the `historical_lookup` snapshots M1.5c stores for a device, within its backfilled
  window. **Distinct documents** are distinct content hashes.
- **Footprint qubits:** the GHZ-star footprints recorded at M1.4c (ADR 0007 Findings):
  `ibm_fez` 136, 141, 142, 143, 144; `ibm_kingston` 138, 149, 150, 151, 152; `ibm_marrakesh`
  10, 11, 12, 13, 18.
- **Minimum data:** a prediction is evaluated on a device only if it has at least 5 distinct
  documents in the window the prediction needs. Otherwise it is "not testable" on that
  device. A prediction whose data the M1.5b outcome does not allow (for example P3 without a
  30-day depth on two devices) is recorded as not testable, not amended.
- **Values:** a parameter value that is unavailable on a document is left out, never set to
  0. Each prediction is reported per device, with no pooling across devices, as supported,
  not supported or not testable.

The predictions:

- **P1 (D27).** For each device, the median over its footprint qubits of the coefficient of
  variation of `T1` (sample standard deviation with n - 1, divided by the mean) across
  distinct documents is at least 0.10.
- **P2 (D27).** For each device, at least one footprint qubit has a maximum-to-minimum ratio
  of `readout_error` across distinct documents of at least 3. A qubit whose minimum is 0 has
  an undefined ratio and does not count.
- **P3 (H2, calibration side only).** For at least two of the three devices, Kendall's tau-b
  between the footprint qubits' `readout_error` on the document returned for the newest grid
  time and on the document returned for the grid time 30 days earlier is below 0.5.
- **P4 (D24).** On every distinct document of every backfilled device, `rz` `gate_error` on
  each footprint qubit is 0, and its date equals the document's `last_update_date` for at
  least 99% of (document, qubit) pairs.

M1.5d cannot test H2 itself, which concerns execution behavior: QCI has no hardware
executions. P3 tests only whether calibration at one time is a stable description of
calibration at another, which is a precondition for H2. The analysis script is committed
before it reads any backfilled data. The values it reports are `calculated`, with methods
and versions; none is presented as a causal claim. Results are research notes, not product
output.

## Consequences

- **Good:** D21 is settled by recorded server responses on three devices before any code
  depends on it, and stopping costs no code.
- **Good:** a backfilled snapshot is distinguishable from a live capture at both the
  snapshot (`source`) and the capture (`method`, `requested_before`) level, with existing rows
  and the content hash unchanged.
- **Cost:** a snapshot store schema change (version 2) with an upcast, and an adapter list of
  verified depths that must be maintained.
- **Known gap:** no configuration history, no publication times, and nothing between grid
  points. Historical snapshots cannot be scoped by a fake run's footprint in `qci snapshot
  compare` (D28).
- **Revisit when:** M1.5b's results are in, IBM changes the properties endpoint or its terms,
  or a provider offers configuration history.
