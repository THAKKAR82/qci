# Experiment: calibration history on three IBM devices (M1.5d)

Date: 2026-10-18 (design). Branch: `docs/m1.5d-experiment-design`. Milestone: M1.5d in
`PLAN.md`. Predictions: P1-P4, frozen in [ADR 0008](../adr/0008-historical-backfill.md)
section 8 on 2026-10-16.

Status: design, accepted 2026-10-18. The analysis script is committed
(`experiments/calibration_history/`, branch `exp/m1.5d-analysis`), with a dated
clarification of the reading rule (Change history). No data set has been collected or read.
The next step is collection by the user (Procedure).

## Purpose

This is a research experiment, not a product feature. Its results are research notes and never
QCI output (ADR 0008 section 7).

- **D27.** IBM publishes no uncertainty for its calibration estimates: each parameter has only
  `name`, `value`, `unit` and `date`. Tracking one parameter across consecutive
  re-measurements gives an empirical spread between re-measurements. That spread includes both
  estimation noise and any physical change between measurements. This experiment cannot
  separate the two, and does not claim to.
- **H2, calibration side only.** H2 (`docs/research.md`) is about execution behavior, and QCI
  has no hardware executions, so H2 itself is not tested. The experiment asks only whether
  calibration of a footprint at one time is a stable description of the same footprint at
  another time. That is a precondition for H2.
- **D24.** P4 checks a regularity of virtual `rz` gates on every analyzed document.

## Data

### Source and scope

- **Store:** the user's local store, `~/.qci-live/qci.db` (`QCI_HOME=~/.qci-live`). Analysis
  opens it read-only (SQLite `mode=ro`).
- **Records:** only lookup captures, that is captures with a `snapshot_lookups` row
  (`method = historical_lookup`), made by `qci snapshot backfill`. Live captures are not part
  of either data set (ADR 0008 section 8, "Data").
- **Devices:** `ibm_fez`, `ibm_kingston`, `ibm_marrakesh`. Each has a verified lookup depth of
  365 days (ADR 0008 Findings).
- **Footprints,** as recorded at M1.4c (ADR 0007, "Live check (M1.4c)"):

  | Device | Qubits | `cz` ordered pairs |
  |---|---|---|
  | `ibm_fez` | 136, 141, 142, 143, 144 | (142,141), (142,143), (143,136), (143,142), (143,144) |
  | `ibm_kingston` | 138, 149, 150, 151, 152 | (150,149), (150,151), (151,138), (151,150), (151,152) |
  | `ibm_marrakesh` | 10, 11, 12, 13, 18 | (11,10), (11,12), (11,18), (12,11), (12,13) |

  The pairs are analyzed as recorded. Each of the three lists holds both directions of one
  connection, and IBM reports each direction as its own `gate/cz/a,b` resource, so they are
  kept apart and never merged.

### Collection date and grid anchors

The **collection date `D`** is the UTC date at the start of the first dense invocation
(Procedure). The user records it with `date -u` before that invocation, and it is the only
input that sets the windows. No window depends on any returned document.

- `E_d = D` at 00:00:00Z, the newest dense grid time.
- `E_s` = the latest whole multiple of 120 hours since 1970-01-01T00:00Z at or before `E_d`.
  It is always a UTC midnight, and is `E_d` itself or up to 4 days earlier.

### Dense set (D27, P1, P2)

- **Grid:** every whole hour `G` with `E_d - 168 h <= G <= E_d`: 169 grid times per device,
  both ends included.
- **Command:** `--days 8 --step-hours 1`. The command's grid ends at the latest midnight and
  reaches back 8 days from the request time, so it covers all 169 times while the request runs
  on day `D`. Lookups it adds before `E_d - 168 h` (between 0 and 23 per device, depending on
  the start hour) are stored but are outside the window and not analyzed. Verified offline
  with `grid_times` from `qci.services.backfill_service`: started at hour h of day `D`, the
  invocation's grid has 193 - ceil(h) times, of which exactly 169 are in the window.
- **Why hourly:** 1 hour is the finest step the command allows. The 47 `ibm_fez` documents of
  M1.5c had 46 intervals between consecutive stamps, with quartiles of 46, 61 and 78 minutes,
  and 51 hourly grid times returned 47 distinct documents (ADR 0008 Findings). An hourly grid
  therefore returns most published documents. A coarser grid would skip many of them, and the
  re-measurement classification below needs consecutive documents.
- **Why 7 days:** the cadence at which IBM re-measures each parameter is not known, and some
  parameters may be re-measured far less often than documents are published. Seven days gives
  several re-measurements for a parameter re-measured about daily and stays within the storage
  budget. A 14-day window would roughly double dense storage, to about 2.1 GB for three
  devices, above the budget.

### Sparse set (H2 calibration side, P3)

- **Grid:** `G_k = E_s - k * 120 h` for `k = 0, 1, ..., 72`: 73 grid times per device, from
  `E_s` back 360 days.
- **Command:** `--days 365 --step-hours 120`. Verified offline: on any day, its grid has 73
  times, the newest is `E_s`, and `G_6` is exactly 30 days (720 h) before `E_s`.
- **Why 120 hours, not weekly:** P3 needs the document for the newest grid time and for the
  grid time exactly 30 days earlier. The command anchors grid times at 1970-01-01T00:00Z, so a
  grid contains both only if its step divides 720 hours. A weekly step (168 h) does not:
  30 days is about 4.3 weeks. The steps that divide 720 h and land on UTC midnights are 24,
  48, 72, 120, 144, 240, 360 and 720 hours. 120 h is the nearest to weekly that still gives
  more than 70 points. A daily step would need about 767 MB per device (2.3 GB for three),
  above the budget.
- **Why 365 days:** the verified depth of all three devices, and the command's cap.
- **Overlap with the dense set:** 1 or 2 sparse grid times fall in the dense window. They are
  stored once. The dense invocations store them first, and the sparse invocation skips them
  without a request (resumability, ADR 0008 section 6). Grid times identify the sets, not
  the invocation that stored them, so a lookup at such a time belongs to both sets.

### Storage, requests and time

The estimate uses the M1.5c measurement: the store grew by 98,697,216 bytes for 47 `ibm_fez`
documents, that is 2,099,941 bytes (about 2.10 MB) and 6,652 measurement rows per document
(ADR 0008 Findings). Stored live snapshots have 6,652 (`ibm_fez`), 6,659 (`ibm_kingston`) and
6,678 (`ibm_marrakesh`) measurement rows, over the same 2,733 resources, so the per-document
size is taken as the same for all three devices. Every lookup is assumed to return a new
document (an upper bound). The M1.5c hourly ratio, 47 distinct of 51, gives the expected
values.

| Per device | Lookups (upper bound) | Distinct documents (expected) | Storage (upper bound) | Measurement rows (upper bound) |
|---|---|---|---|---|
| Dense, 169 in the window plus up to 23 outside | 192 | about 156 in the window, plus up to 21 outside | 403 MB | 1.28 M |
| Sparse | 73 (71 or 72 new) | 73 | 153 MB | 0.49 M |
| **Total per device** | **265** | **about 230 to 250** | **556 MB** | **1.77 M** |

- **Three devices:** at most 795 lookups, 1.67 GB and 5.3 M measurement rows added. With the
  current store (114,020,352 bytes on 2026-10-18), the store stays under about 1.8 GB. For a
  start near 12:00Z the expected addition is about 1.5 GB (about 240 documents per device),
  and the store about 1.6 GB. Both are within the 2 GB budget.
- **`ibm_fez`:** the 51 existing lookups (Integrity notes) are all at hourly grid times. All
  of them are in the dense window if `D <= 2026-10-22`, and some of them up to
  `D = 2026-10-25`. Those grid times are skipped without a request, so the `ibm_fez` numbers
  above shrink by up to 51 requests and 47 documents (about 99 MB).
- **Requests:** dense 175 to 192 per device (193 - ceil(h) for a start at hour h of day `D`),
  in 2 invocations at `--max-requests 100`; sparse 71 or 72 per device, in 1 invocation; 9
  invocations in all, at most 795 requests.
- **Time:** at the default `--pause 10` plus an assumed 2 to 5 s per response (not measured
  in M1.5c), about 12 to 15 s per request: about 1.9 to 2.4 h for the dense invocations
  (at most 576 requests) and 0.7 to 0.9 h for the sparse ones, so 2.6 to 3.3 h in total. The
  user records the actual start and end times.

## Analyses

All analyses run per device. Nothing is pooled across devices. All are computed by one
committed script (Procedure), method version `qci.m15d.analysis.1`. Every reported number is
`calculated` (rule 5), with that method and version. None is presented as a statement about
why a value differs.

### Units of observation

- **Lookup:** one lookup capture: `(device, G, snapshot)`. Only lookups whose `G` is on the
  set's grid and inside its window are used. Each grid time has at most one lookup, since the
  command skips stored grid times.
- **Document:** one stored snapshot, that is one distinct content hash. Its **stamp** is the
  snapshot's `calibrated_at` (the returned `last_update_date`, in UTC). A document returned for
  several grid times is one document, and counts once in every document-based statistic. The
  **documents of a set** are the distinct snapshots of its lookups, ordered by stamp, with ties
  broken by content hash. Ties are counted and reported.
- **Series:** one `(resource, parameter)` pair on one device, such as `qubit/136` `T1` or
  `gate/cz/142,141` `gate_error`.
- **Reading:** a series' row on one document. A reading is **usable** when the document has
  exactly one row for the series, with a numeric `value_real` and a `measured_at` date. A unit
  is not required (clarified 2026-10-18, Change history). A missing row, a null or non-numeric
  value, a missing date, or more than one row for the series on one document (the store keeps
  duplicates) makes the reading unusable. Unusable readings are left out and counted per
  reason, never set to 0. A series whose usable readings have more than one unit across the
  set is reported as `mixed_units` and gets no statistic. No unit (`null`, a dimensionless
  parameter) counts as one unit value, so a series that has no unit on some readings and a
  unit on others is `mixed_units`.
- **Measurement:** the provider's date is the only evidence of a re-measurement. Within a set,
  the measurements of a series are its distinct `measured_at` dates among usable readings. A
  measurement's value is the value of the earliest-stamped document that carries that date. A
  later document with the same date and a different value is counted as
  `revised_same_date`, and its value is not used. A value carried over unchanged to later
  documents is therefore one measurement, never several.

### In-scope series

On each footprint qubit: `T1`, `T2`, `readout_error`, `prob_meas0_prep1`, `prob_meas1_prep0`
and `init_error` (qubit parameters), plus `gate_error` of `sx` and of `measure`. On each
recorded `cz` ordered pair: `gate_error`. That is 45 series per device. `rz` `gate_error` is
used for P4 only. `gate_length`, `readout_length` and `threshold` are configured settings,
not estimates, and are out of scope (D24). The parameter names are those of the committed
`ibm_fez` fixture (`tests/fixtures/snapshots/ibm_fez.json`).

### Exact statistics

For a series with `n` measurement values `x_1, ..., x_n`, in date order:

- **Mean:** `m = (x_1 + ... + x_n) / n`.
- **Sample standard deviation,** n - 1 convention: `s = sqrt(sum_i (x_i - m)^2 / (n - 1))`.
  Defined for `n >= 2`.
- **Coefficient of variation:** `CV = s / m`. Defined for `n >= 2` and `m > 0`.
- **Maximum-to-minimum ratio:** `max_i x_i / min_i x_i`. Defined for `n >= 2` and
  `min_i x_i > 0`.
- **Successive-difference spread** (D27, descriptive): `d = sqrt(sum_{k=1}^{n-1}
  (x_{k+1} - x_k)^2 / (2 (n - 1)))`, reported relative to the mean as `d / m`. Defined for
  `n >= 3` and `m > 0`. It is less sensitive than `s` to slow drift. It still includes any
  physical change between consecutive measurements.
- **Median** of a list: the middle value of the sorted list, or the mean of the two middle
  values when the list has even length.
- **Quartiles:** linear interpolation between order statistics (numpy's default `linear`
  method, Hyndman-Fan type 7).
- **Kendall's tau-b** of paired lists `(a_i, b_i)`, `i = 1..n`: over all pairs `i < j`, with
  `n_c` the pairs where `sign(a_i - a_j) * sign(b_i - b_j) = +1` and `n_d` those where it is
  -1, `n_0 = n (n - 1) / 2`, `n_1 = sum over groups of equal a values of t (t - 1) / 2`, and
  `n_2` the same for `b`: `tau_b = (n_c - n_d) / sqrt((n_0 - n_1) (n_0 - n_2))`. Equality
  means exact equality of the stored floats. Defined for `n >= 3` and a positive denominator.
  Implemented directly in numpy, with no SciPy dependency, and checked in the script's tests
  against hand-computed cases with and without ties.

Each statistic is computed only where defined. Otherwise it is reported as `undefined`, with
the reason (too few measurements, zero minimum, non-positive mean, all values tied).

### D27: re-measured or not

For each pair of consecutive documents `(A, B)` of the dense set, and each in-scope series,
exactly one class applies:

| Class | Condition |
|---|---|
| `unavailable` | the reading on A or on B is unusable |
| `not_re_measured` | `date_B == date_A` and `value_B == value_A` |
| `revised_same_date` | `date_B == date_A` and `value_B != value_A` |
| `re_measured_same_value` | `date_B > date_A` and `value_B == value_A` |
| `re_measured_different_value` | `date_B > date_A` and `value_B != value_A` |
| `date_earlier` | `date_B < date_A` |

Dates are compared as UTC instants, and values by exact equality of the stored floats. A
carried-over value (`not_re_measured`) is never counted as a measurement. "Re-measured" means
only that the provider reports a later date. Under D24 a date can change without a
measurement, and that cannot be detected here for the in-scope parameters.

Reported per device, from the dense set:

1. Lookups per window (169 expected), missing grid times, distinct documents, stamp ties, and
   the requested time minus returned stamp (median and maximum).
2. Per series: the counts of each class above, and the number of measurements `n`.
3. Per series: the intervals between consecutive measurement dates (median and quartiles,
   in hours).
4. Per series: `CV`, the maximum-to-minimum ratio, and `d / m`, from the measurements.
5. Per parameter, over its footprint resources: the median of each statistic in item 4.

### H2, calibration side (sparse set, descriptive)

Reported per device:

1. Lookups present of the 73 grid times, distinct documents, and the requested time minus
   returned stamp (median and maximum).
2. Per series: measurements `n`, `CV`, the maximum-to-minimum ratio and `d / m` over the
   sparse set's measurements.
3. Lag profile: Kendall's tau-b between the footprint values on the document for `G_0` and
   on the document for `G_k`, for `k` = 1, 2, 6, 12, 18, 36 and 72 (5, 10, 30, 60, 90, 180 and
   360 days). It is computed for `readout_error` and `T1` over the 5 footprint qubits, and
   for `cz` `gate_error` over the 5 recorded pairs. Readings are taken as they appear on each
   document (as in P3), and resources unusable on either document are left out. For each
   pair, the output also gives `n`, whether the two documents are the same, and how many
   resources have the same date on both.

These figures carry no prediction and are not marked. Anything computed beyond this list is
labeled exploratory in the results.

### What the output contains

Counts, durations between provider dates or stamps, and dimensionless statistics (CV,
ratios, `d / m`, tau-b, fractions), labeled by device, resource and parameter. It never
contains a parameter value, or a mean, median, minimum, maximum or quantile of values in the
parameter's unit. It contains no per-document table, no snapshot ID and no raw payload.

## Pre-registered predictions

P1-P4 are restated exactly as frozen in ADR 0008 section 8 (2026-10-16), with the frozen
definitions. Each restatement is followed by its data, its computation, and a marking rule
committed with this design, before any data set here is collected or analyzed. No threshold
is changed.

Frozen definitions (ADR 0008 section 8, quoted):

> - **Data:** the `historical_lookup` snapshots M1.5c stores for a device, within its
>   backfilled window. **Distinct documents** are distinct content hashes.
> - **Footprint qubits:** the GHZ-star footprints recorded at M1.4c (ADR 0007 Findings):
>   `ibm_fez` 136, 141, 142, 143, 144; `ibm_kingston` 138, 149, 150, 151, 152; `ibm_marrakesh`
>   10, 11, 12, 13, 18.
> - **Minimum data:** a prediction is evaluated on a device only if it has at least 5 distinct
>   documents in the window the prediction needs. Otherwise it is "not testable" on that
>   device. A prediction whose data the M1.5b outcome does not allow (for example P3 without a
>   30-day depth on two devices) is recorded as not testable, not amended.
> - **Values:** a parameter value that is unavailable on a document is left out, never set to
>   0. Each prediction is reported per device, with no pooling across devices, as supported,
>   not supported or not testable.

**Testability now.** All four predictions are testable on the chosen data: each device has a
verified depth of 365 days, the dense window holds up to 169 documents, and the sparse grid
contains both `E_s` and `E_s - 30 days`. None is marked "not testable" in advance. Each
marking rule still says when a device becomes not testable once the data is in.

**Measurements and "across distinct documents".** For P1 and P2 the values are the
measurements of a series (Analyses): one value per distinct provider date, taken from the
earliest-stamped document carrying it. This is how the design computes "across distinct
documents": each distinct document is used once, and a value carried over unchanged to later
documents is not counted again as a separate observation. Taking every document's value
instead would count one measurement once per document that repeats it. This is recorded in
ADR 0008 section 8 as a dated design clarification (2026-10-18, before collection), with the
thresholds unchanged. For P2 it cannot change the maximum or minimum, except through
`revised_same_date` readings. For P1 it can change `n` and the CV. The per-document
form (each distinct document's usable value, once per document) is also computed and
reported for P1 and P2, labeled "per-document, not used for marking". The decision to mark on
measurements is fixed here, before any data is seen.

### P1 (D27)

> **P1 (D27).** For each device, the median over its footprint qubits of the coefficient of
> variation of `T1` (sample standard deviation with n - 1, divided by the mean) across
> distinct documents is at least 0.10.

- **Data:** the dense set. Minimum data: at least 5 distinct documents in the dense window.
- **Computation:** per footprint qubit, `CV` of its `T1` measurements (Analyses). The device
  statistic is the median of the defined CVs.
- **Marking, per device:** not testable if fewer than 5 distinct documents, or fewer than 3
  of the 5 footprint qubits have a defined CV. Otherwise supported if the median is at least
  0.10, and not supported if it is below 0.10.
- **Overall:** supported if supported on all three devices; not supported if not supported on
  at least one device; otherwise not testable.

### P2 (D27)

> **P2 (D27).** For each device, at least one footprint qubit has a maximum-to-minimum ratio
> of `readout_error` across distinct documents of at least 3. A qubit whose minimum is 0 has
> an undefined ratio and does not count.

- **Data:** the dense set. Minimum data: at least 5 distinct documents in the dense window.
- **Computation:** per footprint qubit, the maximum-to-minimum ratio of its `readout_error`
  measurements. It is defined only for at least 2 measurements and a minimum above 0.
- **Marking, per device:** not testable if fewer than 5 distinct documents. Otherwise
  supported if any qubit has a defined ratio of at least 3. If none does, not supported when at
  least 3 of the 5 footprint qubits have a defined ratio, and not testable otherwise.
- **Overall:** as for P1.

### P3 (H2, calibration side only)

> **P3 (H2, calibration side only).** For at least two of the three devices, Kendall's tau-b
> between the footprint qubits' `readout_error` on the document returned for the newest grid
> time and on the document returned for the grid time 30 days earlier is below 0.5.

- **Data:** the sparse set. "The newest grid time" is `G_0 = E_s`, and "the grid time 30
  days earlier" is `G_6 = E_s - 720 h`. Minimum data: at least 5 distinct documents among the
  sparse lookups at `G_0, ..., G_6` (the 30-day window), and lookups present at both `G_0`
  and `G_6`.
- **Computation:** `a_i` is qubit `i`'s `readout_error` on the document for `G_0`, and `b_i`
  is the same on the document for `G_6`, over footprint qubits usable on both. These are
  values as they appear on the two documents, not measurements, since the prediction names
  the documents. Kendall's tau-b as defined in Analyses. If both grid times returned the same
  document, tau-b is computed as is. The output reports whether the documents are the same,
  and how many qubits have the same `readout_error` date on both.
- **Marking, per device:** not testable if the minimum data is not met, or tau-b is undefined
  (fewer than 3 usable qubits, or all values tied on either side). Otherwise "below 0.5" or
  "at or above 0.5". Without ties, five qubits give tau-b in steps of 0.2, so 0.5 cannot be
  reached exactly.
- **Overall:** supported if at least two devices are "below 0.5". Not supported if the number
  of devices "below 0.5" plus the number not testable is less than two. Otherwise not
  testable.

### P4 (D24)

> **P4 (D24).** On every distinct document of every backfilled device, `rz` `gate_error` on
> each footprint qubit is 0, and its date equals the document's `last_update_date` for at
> least 99% of (document, qubit) pairs.

- **Data:** every distinct document of the dense set and the sparse set together, each
  counted once. Lookups outside both windows are not used. Minimum data: at least 5 distinct
  documents.
- **Computation:** over the (document, footprint qubit) pairs, for the series
  `gate/rz/q` `gate_error`:
  - (a) every pair with a numeric value has a value exactly equal to 0.0. Pairs without a
    numeric value are left out and counted.
  - (b) over pairs with both a `measured_at` date and a document stamp, the fraction whose
    date equals the stamp, as UTC instants, is at least 0.99. Pairs without either date are
    left out of the denominator and counted.
- **Marking, per device:** not testable if fewer than 5 distinct documents, or no pair has a
  numeric value, or no pair has both dates. Otherwise supported if (a) and (b) both hold, and
  not supported if either does not. The output reports the count of nonzero values and the
  fraction in (b).
- **Overall:** as for P1.

## Integrity notes

- **Order of work.** P1-P4 and their definitions were frozen on 2026-10-16, before any
  backfilled document existed. This design and its marking rules are committed before any
  data set defined here is collected. The analysis script is committed before it reads any
  backfilled data (ADR 0008 section 8). It is run once on the collected data, from a clean
  tree, and its output records the commit hash and dirty flag. If the tree is dirty, the run
  is repeated from a clean tree before any result is recorded.
- **Existing `ibm_fez` lookups.** The store already holds 51 hourly-grid `ibm_fez` lookups of
  47 distinct documents, requested for 2026-10-15T22:00Z to 2026-10-18T00:00Z, from the M1.5c
  manual live check. Their document stamps (2026-10-15T21:20:44Z to 2026-10-17T23:21:10Z),
  the intervals between them, their row counts and the store's size have been inspected and
  are recorded in ADR 0008 Findings. They were used to choose the dense grid and the storage
  estimate. None of their parameter values or parameter dates has been read or reported.
  - **Decision: they are used** wherever their grid times fall in the dense window (all of
    them when `D <= 2026-10-22`, some of them up to `D = 2026-10-25`). They were made by the same command at the same hourly grid times. A
    lookup is repeatable (all 18 M1.5b offsets on three devices `repeat:identical`), and the
    M1.5c consistency check found a stored lookup byte-identical to an earlier fetch of the
    same document. Requesting them again would return the same documents, and the command
    would skip those grid times anyway. Excluding them would leave a gap of up to 51 hours in
    the `ibm_fez` window and no way to refill it. P1-P4 were frozen before these lookups
    existed. What was inspected is document stamps, which none of P1-P3 uses. P4 uses `rz`
    dates, which were not inspected.
- **Inspection in this step.** To size the design, the store was opened read-only on
  2026-10-18 and only these were counted: snapshots per device and source, with their oldest
  and newest stamps; measurement rows per snapshot and distinct resources per device and
  source; lookups per device, with the oldest and newest requested time; and total
  measurement rows. No value, unit or measurement date was read. The store's SHA-256 was
  `2fc55a9da533c0562faed69f04302a0bd650f3c77023817e3a4021c4a99245c6` before and after. Parameter
  names come from the committed `ibm_fez` fixture, not from the store.
- **Prior observations disclosed with the predictions** (ADR 0008 section 8): P1-P4 were
  written after the M1.4c live check, "which showed fake-to-live `readout_error` ratios of
  about 7.7 and 15.5 on `ibm_marrakesh` qubits 11 and 13 (ADR 0007 Findings)". That
  observation compares a fake's frozen calibration with a live document. It is not a
  maximum-to-minimum ratio across documents, but it may have informed P2's threshold of 3.
  P4 was written knowing the D24 observation in ADR 0005 section 6, that `rz` reports
  `gate_error` 0 dated with the document timestamp on one live document. P4 is a test of that
  regularity across many documents, not a new hypothesis.
- **Stamp time, not view time.** Backfilled history is documents by provider stamp time, not
  what a user would have seen at a given time (ADR 0008 Findings, publication lag of at least
  5 min 33 s). Every statistic here is over documents and provider dates, never over what was
  current at a wall-clock time.
- **What the grids miss.** Documents published and superseded within one grid step are not
  seen (ADR 0008 section 5). The D27 classes are therefore between consecutive observed
  documents, and measurement intervals are upper bounds on the provider's interval. Device
  configuration history is not available, so a device revision during the 360-day sparse span
  would not be visible. The analysis reports only, per set, how many documents have at least
  one unusable in-scope series, and the counts of unusable readings by reason.
- **Reporting.** Results are reported as aggregate statistics only (Analyses, "What the
  output contains"): no IBM parameter value and no raw table. Backfilled data stays in the
  user's local store and is never committed, exported as a fixture or redistributed (ADR 0008
  section 6, D29). The script's full output is kept in the user's local files
  (`~/qci-m15d/`). Only the aggregate tables are copied into the Results section of this file.
- **Wording.** Results use rule 8's neutral terms. A difference between documents is a
  difference in reported values, never evidence of why it arose. A prediction is marked only
  supported, not supported or not testable.

## Procedure

Run by the user, in zsh, from the repository root, only after the analysis script is
committed (step after this design) and its gates are clean. Each invocation stays within the
per-invocation cap (`--max-requests 100`). Re-running a command resumes where it stopped and
prints `Nothing to request.` when its grid is complete. The output of each invocation goes to
a local log in `~/qci-m15d/`, and those logs are never committed.

### 1. Before collection

The backup takes about 114 MB. The disk check confirms room for about 1.8 GB more.

```bash
mkdir -p ~/qci-m15d
df -h "$HOME"
cp ~/.qci-live/qci.db ~/qci-m15d/qci-before-m15d.db
shasum -a 256 ~/.qci-live/qci.db ~/qci-m15d/qci-before-m15d.db
git rev-parse HEAD
git status --short
date -u +%Y-%m-%dT%H:%M:%SZ | tee ~/qci-m15d/collection-start.txt
```

The UTC date in `collection-start.txt` is `D`. Start between about 06:00Z and 19:00Z, so that
the dense invocations (about 2 to 2.5 h) finish on day `D`.

### 2. Dense set, all three devices on day `D`

Run each command, then run it again until it prints `Nothing to request.`. Each device takes
two invocations, and `ibm_fez` may need only one.

```bash
QCI_HOME="$HOME/.qci-live" PYTHONPATH=src .venv/bin/qci snapshot backfill --backend ibm_fez --days 8 --step-hours 1 --max-requests 100 --pause 10 --account default-ibm-quantum-platform 2>&1 | tee -a ~/qci-m15d/dense-ibm_fez.txt
QCI_HOME="$HOME/.qci-live" PYTHONPATH=src .venv/bin/qci snapshot backfill --backend ibm_kingston --days 8 --step-hours 1 --max-requests 100 --pause 10 --account default-ibm-quantum-platform 2>&1 | tee -a ~/qci-m15d/dense-ibm_kingston.txt
QCI_HOME="$HOME/.qci-live" PYTHONPATH=src .venv/bin/qci snapshot backfill --backend ibm_marrakesh --days 8 --step-hours 1 --max-requests 100 --pause 10 --account default-ibm-quantum-platform 2>&1 | tee -a ~/qci-m15d/dense-ibm_marrakesh.txt
```

If a dense invocation would start after 00:00Z on the day after `D`, use `--days 9` instead
of `--days 8` for the rest of the dense set. The window still ends at `E_d`. The newer hourly
times the command then requests first are outside the window and are not analyzed. This was
checked offline with `grid_times`.

### 3. Sparse set, all three devices, on day `D` if possible

One invocation each (73 grid times, 1 or 2 already stored by the dense set).

```bash
QCI_HOME="$HOME/.qci-live" PYTHONPATH=src .venv/bin/qci snapshot backfill --backend ibm_fez --days 365 --step-hours 120 --max-requests 100 --pause 10 --account default-ibm-quantum-platform 2>&1 | tee -a ~/qci-m15d/sparse-ibm_fez.txt
QCI_HOME="$HOME/.qci-live" PYTHONPATH=src .venv/bin/qci snapshot backfill --backend ibm_kingston --days 365 --step-hours 120 --max-requests 100 --pause 10 --account default-ibm-quantum-platform 2>&1 | tee -a ~/qci-m15d/sparse-ibm_kingston.txt
QCI_HOME="$HOME/.qci-live" PYTHONPATH=src .venv/bin/qci snapshot backfill --backend ibm_marrakesh --days 365 --step-hours 120 --max-requests 100 --pause 10 --account default-ibm-quantum-platform 2>&1 | tee -a ~/qci-m15d/sparse-ibm_marrakesh.txt
```

If the sparse set runs after day `D`, `E_s` is still computed from `D`. Its oldest grid time
`G_72` can then be outside a later invocation's 365-day reach. It is reported as missing,
which affects only the descriptive sparse figures, not P3.

### 4. After collection

```bash
date -u +%Y-%m-%dT%H:%M:%SZ | tee ~/qci-m15d/collection-end.txt
shasum -a 256 ~/.qci-live/qci.db
ls -l ~/.qci-live/qci.db
QCI_HOME="$HOME/.qci-live" PYTHONPATH=src .venv/bin/qci snapshots --backend ibm_fez --limit 5
```

`qci snapshots` prints IDs, sources and stamps only. No `qci snapshot show`, `qci snapshot
compare` or other command that displays parameter values is run on the new lookups before the
analysis.

The first too-many-requests response stops an invocation with nothing retried (ADR 0008
section 6). If that happens, the user stops collection and records it. Collection resumes only
after a pause the user chooses, with the same commands, which skip everything already stored.

### 5. Analysis

The committed script is run once, read-only, with `D` as its only data-selection input. Its
interface, fixed by the step that added it:

```bash
PYTHONPATH=src:experiments/calibration_history .venv/bin/python experiments/calibration_history/run_analysis.py --store ~/.qci-live/qci.db --collection-date YYYY-MM-DD --out ~/qci-m15d
```

It refuses to run on a dirty tree and refuses to overwrite an earlier result. It prints the
store's SHA-256 before and after, the commit hash and the dirty flag, and writes its full
output to `~/qci-m15d/results.json` and `~/qci-m15d/results.md`. It exits non-zero if the
store's hash changed. The aggregate tables and the marks for P1-P4 are then copied into a
Results section of this file, in a separate commit.

## Results

None yet. This file is the design. Results are added only after the procedure above.

## Change history

- **2026-10-16.** P1-P4 frozen in ADR 0008 section 8.
- **2026-10-18.** Design accepted (branch `docs/m1.5d-experiment-design`). ADR 0008 section 8
  records a dated design clarification of P1 and P2: "across distinct documents" is over
  distinct measurements; thresholds unchanged.
- **2026-10-18, design clarification, before any data set is collected or read** (branch
  `exp/m1.5d-analysis`). The reading rule ("Units of observation") no longer requires a unit.
  IBM reports the unit `""` for every dimensionless parameter (`readout_error`,
  `prob_meas0_prep1`, `prob_meas1_prep0`, `init_error` and every `gate_error`), and the
  adapter stores it as `null` (`src/qci/adapters/qiskit_ibm/calibration.py`, as seen in the
  committed `ibm_fez` fixture, where only `T1` and `T2` have a unit). Read literally, the
  rule would have made 39 of the 45 in-scope series unusable on every document, and P2 and P3
  not testable for a reason unrelated to the data. The unit is used only for the
  `mixed_units` check, where no unit counts as one unit value. No threshold, window,
  statistic or marking rule changes.
- **2026-10-18, before collection, interpretation only** (branch `exp/m1.5d-analysis`): with
  5 untied qubits, tau-b < 0.5 means at least 3 of 10 pairs discordant. Under a uniformly
  random relative ordering, P(tau-b < 0.5) = 106/120 ≈ 0.88 (only 14 of 120 permutations have
  at most 2 inversions). A 'supported' P3 is therefore weak evidence of rank instability; a
  'not supported' result is the more informative outcome. The analysis report states this
  probability next to P3's result. No threshold or marking rule changes.
