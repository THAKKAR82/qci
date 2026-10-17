# ADR 0008: Historical calibration backfill

- **Status:** Proposed
- **Date:** 2026-10-16 (proposed)
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
*verified depth* is the largest offset in the protocol for which that device's request is
`honored` and every smaller offset is `honored` or `inconclusive:no_newer_document`.

- **Proceed** with M1.5c for every device whose verified depth is at least 30 days, whose
  repeat is `repeat:identical`, and that had no `raises` outcome. Backfill for that device is
  limited to its verified depth.
- **Narrow** when only some devices qualify, or a device's verified depth is at least 7 but
  under 30 days: M1.5c covers only the qualifying devices, each limited to its verified depth. A
  depth of 7 days is the minimum worth building for.
- **Stop** when no device qualifies (every verified depth is below 7 days, or every repeat is
  `repeat:different`, or every device raises), or when the terms check (section 6) does not
  permit programmatic historical requests at the planned pacing. Then: D21 is resolved as
  "not supported for QCI's use", history stays forward-only, M1.5c is not built, and M1.5d is
  either redesigned on forward captures or dropped, in a separate approved step. This is a
  valid outcome of M1.5, not a defect.
- **Re-run once, never in a loop,** when a device's results are all `inconclusive`. If the
  second run is also inconclusive, that device does not qualify.

The applied rule, each device's verified depth and the resulting choice are recorded in
Findings at M1.5b before M1.5c starts.

### 2. The D21 verification protocol

`scripts/verify_historical_calibration.py`, protocol `qci.d21.verify.1`:

- **Devices:** `ibm_fez`, `ibm_kingston`, `ibm_marrakesh`, in that order. These are the three
  devices in `FAKE_DEVICE_SOURCES` (ADR 0007).
- **Anchor:** one UTC instant per invocation, the start time truncated to whole seconds,
  printed first. Requested times are `anchor - N days` for N in 1, 7, 30, 90, 180 and 365,
  sent as aware UTC datetimes with a zero offset (see Findings on `local_to_utc`).
- **Per device:** one current request (`properties(refresh=True)`), then one request per
  offset, then a **repeat** of the 30-day request with the identical requested instant. That
  is 8 requests per device and 24 in all, with a pause between requests (default 5 s,
  minimum 1 s). No retries.
- **Hash:** each returned properties document is normalized as capture normalizes it (UTC
  datetimes, lossless JSON, redaction) and hashed with `hash_json`. Only the hash is kept.
- **Outcome per request,** with `requested` the requested instant, `returned` and `current`
  the two documents:

| Outcome | Condition |
|---|---|
| `honored` | the returned hash differs from the current hash, and the returned `last_update_date` is at or before `requested` |
| `ignored` | the returned hash equals the current hash, and the current `last_update_date` is after `requested` |
| `ignored:returned_after_requested` | a different document whose `last_update_date` is after `requested` |
| `raises:<Type>` | the request raised; only the exception's type name is printed |
| `inconclusive:no_newer_document` | the hashes are equal, but the current `last_update_date` is itself at or before `requested`: nothing newer was published, so honored and ignored cannot be told apart |
| `inconclusive:no_document`, `inconclusive:no_returned_date`, `inconclusive:no_current_date` | no document, or a missing date, on the side named |

- **Repeat:** `repeat:identical` when the second 30-day request returns the same hash as the
  first, otherwise `repeat:different`. A different result means the same request does not
  return the same content, and lookups on that device cannot be given a stable provenance.
- **Output:** one line per request: device, requested time (or `current`), returned
  `last_update_date`, properties hash and outcome. Nothing else is printed: no account data,
  backend version, payload content or error text. The script opens no QCI store and writes no
  file. It is type-checked by the gates and never run by pytest.

The command, run by the user in zsh from the repository root:

```bash
mkdir -p ~/qci-m15b
shasum -a 256 ~/.qci-live/qci.db
PYTHONPATH=src .venv/bin/python scripts/verify_historical_calibration.py --account default-ibm-quantum-platform --pause 5 | tee ~/qci-m15b/d21.txt
shasum -a 256 ~/.qci-live/qci.db
```

The two hashes show that no QCI store was touched. `scripts/check_historical_calibration.py`
(ADR 0005, one request on one device) is kept as the record of the first observation; this
script supersedes it for D21.

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
- **No retries.** The first error stops the invocation. Everything stored before it is kept,
  since each lookup is stored in its own transaction.
- **Resumable:** before each request, the command looks for an existing lookup capture with
  the same backend and `requested_before`. If it exists, the grid time is skipped and counts
  against no cap. Re-running the same command continues where the last one stopped.

**IBM terms and rate limits (to be checked by the user at M1.5b, before M1.5c):**

> _Placeholder. Record: the documents checked (title, URL, date read), what they say about
> programmatic or bulk requests for historical calibration data, any stated request-rate
> limits, and whether the planned pacing (10 s between requests, at most 100 per invocation)
> is within them. If the terms do not permit it, the decision rule in section 1 says stop._

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

- [ ] The user runs the command in section 2 on the three devices. The full output is
      recorded verbatim in Findings ("D21 verification (M1.5b)"), with the anchor time.
- [ ] Findings record, per device: each offset's outcome, the returned `last_update_date`,
      whether the repeat is identical, and the verified depth.
- [ ] The store hash of `~/.qci-live/qci.db` is identical before and after the script.
- [ ] The terms and rate-limit finding replaces the placeholder in section 6.
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
      command and the provenance. All gates pass, and the neutral-wording check has no
      unexplained hit.
- [ ] Manual live check by the user: one small backfill (for example `--days 3`) on one
      qualifying device, recorded in Findings, with the store hash changing only through
      the backfill.

#### M1.5d: research experiment (designed in its own step, outline only)

Predictions are committed, with the analysis script, before any backfilled value is
analyzed (CLAUDE.md, step workflow item 6). Its results are research notes, not product
output. Draft predictions, to be frozen at M1.5d's design:

- **P1 (D27).** For the GHZ-star footprint qubits of each device, over the backfilled daily
  grid, the median coefficient of variation of `T1` across distinct documents is at least
  0.10.
- **P2 (D27).** For `readout_error` on the same qubits, at least one qubit per device has a
  maximum-to-minimum ratio of at least 3 over the backfilled window.
- **P3 (H2, calibration side only).** For at least two of the three devices, the rank order
  of footprint qubits by `readout_error` on the newest document and on the document 30 days
  earlier has Kendall's tau below 0.5.
- **P4 (D24).** `rz` `gate_error` is 0 on every document, and its date equals the document's
  `last_update_date` on at least 99% of documents.

M1.5d cannot test H2 itself, which concerns execution behavior: QCI has no hardware
executions. P3 tests only whether calibration at one time is a stable description of
calibration at another, which is a precondition for H2. The results are labeled `statistical`
or `calculated`, with methods and versions, and never as causal claims.

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
