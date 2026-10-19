"""Analysis of the M1.5d calibration-history experiment (method ``qci.m15d.analysis.1``).

Implements docs/experiments/2026-10-calibration-history.md: set selection from the collection
date ``D``, readings and measurements, the D27 classes, the dense and sparse statistics, the
lag profile and the marking of P1-P4. The store is read through ``SqliteSnapshotRepository``
opened read-only.

Every number produced here is ``calculated``. The output holds counts, durations between
provider dates or stamps, and dimensionless statistics only: never a parameter value, or any
mean, median, extreme or quantile of values in a parameter's unit.
"""

import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from itertools import pairwise
from typing import Any

from history_stats import (
    Stat,
    coefficient_of_variation,
    kendall_tau_b,
    max_min_ratio,
    median,
    quartiles,
    random_order_below,
    successive_spread,
)

from qci.adapters.qiskit_ibm.adapter_ids import PROVIDER_ID
from qci.storage.snapshots import SqliteSnapshotRepository

METHOD = "m15d_calibration_history"
METHOD_VERSION = "qci.m15d.analysis.1"
EVIDENCE_KIND = "calculated"

Json = dict[str, Any]
SeriesKey = tuple[str, str]
"""(resource, parameter), as the adapter stores them, such as ("qubit/136", "T1")."""


@dataclass(frozen=True)
class Footprint:
    qubits: tuple[int, ...]
    cz_pairs: tuple[tuple[int, int], ...]
    """Ordered pairs, as recorded at M1.4c. Both directions are kept apart."""


FOOTPRINTS: dict[str, Footprint] = {
    "ibm_fez": Footprint(
        (136, 141, 142, 143, 144),
        ((142, 141), (142, 143), (143, 136), (143, 142), (143, 144)),
    ),
    "ibm_kingston": Footprint(
        (138, 149, 150, 151, 152),
        ((150, 149), (150, 151), (151, 138), (151, 150), (151, 152)),
    ),
    "ibm_marrakesh": Footprint(
        (10, 11, 12, 13, 18),
        ((11, 10), (11, 12), (11, 18), (12, 11), (12, 13)),
    ),
}

QUBIT_PARAMETERS = (
    "T1",
    "T2",
    "readout_error",
    "prob_meas0_prep1",
    "prob_meas1_prep0",
    "init_error",
)
ONE_QUBIT_GATES = ("sx", "measure")
CZ_GROUP = "cz gate_error"

DENSE_HOURS = 168
SPARSE_STEP_HOURS = 120
SPARSE_POINTS = 73
LAG_STEPS = (1, 2, 6, 12, 18, 36, 72)
LAG_GROUPS = ("readout_error", "T1", CZ_GROUP)
P3_STEP = 6

MIN_DOCUMENTS = 5
MIN_DEFINED = 3
P1_THRESHOLD = 0.10
P2_THRESHOLD = 3.0
P3_THRESHOLD = 0.5
P4_FRACTION = 0.99

SUPPORTED = "supported"
NOT_SUPPORTED = "not supported"
NOT_TESTABLE = "not testable"
BELOW = "below 0.5"
AT_OR_ABOVE = "at or above 0.5"

D27_CLASSES = (
    "unavailable",
    "not_re_measured",
    "revised_same_date",
    "re_measured_same_value",
    "re_measured_different_value",
    "date_earlier",
)
UNUSABLE_REASONS = (
    "missing_row",
    "duplicate_rows",
    "null_value",
    "non_numeric_value",
    "non_finite_value",
    "missing_date",
)
MIXED_UNITS = "mixed_units"

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_HOUR = timedelta(hours=1)


# --- series ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Series:
    key: SeriesKey
    group: str
    """The parameter group used for per-parameter medians, such as "T1" or "cz gate_error"."""


def qubit_key(qubit: int, parameter: str) -> SeriesKey:
    return (f"qubit/{qubit}", parameter)


def gate_key(gate: str, qubits: Sequence[int]) -> SeriesKey:
    return (f"gate/{gate}/{','.join(str(q) for q in qubits)}", "gate_error")


def rz_key(qubit: int) -> SeriesKey:
    return gate_key("rz", (qubit,))


def in_scope_series(footprint: Footprint) -> list[Series]:
    """The 45 in-scope series of one device, in a fixed order."""
    series = [Series(qubit_key(q, p), p) for p in QUBIT_PARAMETERS for q in footprint.qubits]
    series += [
        Series(gate_key(g, (q,)), f"{g} gate_error")
        for g in ONE_QUBIT_GATES
        for q in footprint.qubits
    ]
    series += [Series(gate_key("cz", pair), CZ_GROUP) for pair in footprint.cz_pairs]
    return series


def group_keys(footprint: Footprint, group: str) -> list[SeriesKey]:
    return [s.key for s in in_scope_series(footprint) if s.group == group]


def all_keys(footprint: Footprint) -> set[SeriesKey]:
    return {s.key for s in in_scope_series(footprint)} | {rz_key(q) for q in footprint.qubits}


# --- windows --------------------------------------------------------------------------------


def dense_anchor(collection_date: date) -> datetime:
    """E_d: D at 00:00:00Z."""
    return datetime(collection_date.year, collection_date.month, collection_date.day, tzinfo=UTC)


def sparse_anchor(collection_date: date) -> datetime:
    """E_s: the latest whole multiple of 120 h since the epoch at or before E_d."""
    step = timedelta(hours=SPARSE_STEP_HOURS)
    return _EPOCH + ((dense_anchor(collection_date) - _EPOCH) // step) * step


def dense_grid(collection_date: date) -> list[datetime]:
    """Every whole hour from E_d back to E_d - 168 h, both included, newest first."""
    anchor = dense_anchor(collection_date)
    return [anchor - k * _HOUR for k in range(DENSE_HOURS + 1)]


def sparse_grid(collection_date: date) -> list[datetime]:
    """G_k = E_s - k * 120 h for k = 0..72. Index k is G_k."""
    anchor = sparse_anchor(collection_date)
    return [anchor - k * timedelta(hours=SPARSE_STEP_HOURS) for k in range(SPARSE_POINTS)]


# --- store ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Row:
    value: float | str | None
    unit: str | None
    measured_at: datetime | None


@dataclass(frozen=True)
class Document:
    snapshot_id: str
    content_hash: str
    stamp: datetime | None
    """The snapshot's calibrated_at."""
    rows: Mapping[SeriesKey, tuple[Row, ...]]
    """Only the rows of the keys that were asked for. A key with no row is absent."""


@dataclass(frozen=True)
class Lookup:
    grid_time: datetime
    snapshot_id: str


@dataclass(frozen=True)
class DeviceLookups:
    by_time: dict[datetime, Lookup]
    duplicate_lookups: int
    """Lookups at a time that already had one. The earliest capture is used."""


class StoreReader:
    """Reads lookups and documents of one store through the read-only repository."""

    def __init__(self, repository: SqliteSnapshotRepository) -> None:
        self._repo = repository
        self._documents: dict[str, Document] = {}

    def lookups(self, backend: str) -> DeviceLookups:
        found: list[tuple[datetime, datetime, str, str]] = []
        for item in self._repo.list_snapshots(backend_name=backend):
            if item.provider != PROVIDER_ID:
                continue
            for capture in self._repo.captures(item.snapshot_id):
                if capture.method != "historical_lookup" or capture.requested_before is None:
                    continue
                found.append(
                    (
                        capture.requested_before.astimezone(UTC),
                        capture.captured_at,
                        capture.capture_id,
                        capture.snapshot_id,
                    )
                )
        by_time: dict[datetime, Lookup] = {}
        duplicates = 0
        for grid_time, _, _, snapshot_id in sorted(found):
            if grid_time in by_time:
                duplicates += 1
                continue
            by_time[grid_time] = Lookup(grid_time, snapshot_id)
        return DeviceLookups(by_time, duplicates)

    def document(self, snapshot_id: str, keys: set[SeriesKey]) -> Document:
        cached = self._documents.get(snapshot_id)
        if cached is not None:
            return cached
        snapshot = self._repo.get(snapshot_id)
        rows: dict[SeriesKey, list[Row]] = {}
        for m in self._repo.measurements(snapshot_id):
            key = (m.resource, m.parameter)
            if key in keys:
                rows.setdefault(key, []).append(Row(m.value, m.unit, m.measured_at))
        document = Document(
            snapshot_id=snapshot.snapshot_id,
            content_hash=snapshot.content_hash,
            stamp=snapshot.calibrated_at,
            rows={k: tuple(v) for k, v in rows.items()},
        )
        self._documents[snapshot_id] = document
        return document


# --- data sets ------------------------------------------------------------------------------


@dataclass(frozen=True)
class DataSet:
    grid: list[datetime]
    lookups: dict[datetime, tuple[Lookup, Document]]
    """The lookups at the set's grid times, by grid time."""
    documents: list[Document]
    """Distinct stamped documents, ordered by stamp, ties broken by content hash."""
    distinct_documents: int
    """Distinct content hashes among the lookups, stamped or not."""
    documents_without_stamp: int


def distinct(documents: Iterable[Document]) -> list[Document]:
    seen: dict[str, Document] = {}
    for document in documents:
        seen.setdefault(document.content_hash, document)
    return list(seen.values())


def build_set(
    reader: StoreReader, lookups: DeviceLookups, grid: list[datetime], keys: set[SeriesKey]
) -> DataSet:
    selected = {
        t: (lookups.by_time[t], reader.document(lookups.by_time[t].snapshot_id, keys))
        for t in grid
        if t in lookups.by_time
    }
    docs = distinct(doc for _, doc in selected.values())
    stamped = [d for d in docs if d.stamp is not None]
    ordered = sorted(stamped, key=lambda d: (d.stamp, d.content_hash))
    return DataSet(grid, selected, ordered, len(docs), len(docs) - len(stamped))


# --- readings and measurements --------------------------------------------------------------


@dataclass(frozen=True)
class Reading:
    value: float
    unit: str | None
    """None is the stored form of a dimensionless parameter (the provider's empty unit)."""
    measured_at: datetime


def read(document: Document, key: SeriesKey) -> Reading | str:
    """The usable reading of ``key`` on ``document``, or the reason it is unusable.

    Usable: exactly one row, a finite numeric value and a measurement date. The unit is not
    required (design clarification 2026-10-18); it is used only for the mixed-units check.
    """
    rows = document.rows.get(key, ())
    if not rows:
        return "missing_row"
    if len(rows) > 1:
        return "duplicate_rows"
    row = rows[0]
    if row.value is None:
        return "null_value"
    if not isinstance(row.value, float):
        return "non_numeric_value"
    if not math.isfinite(row.value):
        return "non_finite_value"
    if row.measured_at is None:
        return "missing_date"
    return Reading(row.value, row.unit, row.measured_at)


def classify(a: Reading | str, b: Reading | str) -> str:
    """The D27 class of one series between consecutive documents A and B."""
    if not isinstance(a, Reading) or not isinstance(b, Reading):
        return "unavailable"
    if b.measured_at < a.measured_at:
        return "date_earlier"
    same_value = b.value == a.value
    if b.measured_at == a.measured_at:
        return "not_re_measured" if same_value else "revised_same_date"
    return "re_measured_same_value" if same_value else "re_measured_different_value"


@dataclass(frozen=True)
class Measurements:
    dates: list[datetime]
    values: list[float]
    """In date order. One per distinct measurement date."""
    revised_same_date_readings: int
    """Later readings with an already seen date and a different value. Their values are
    not used."""


def measurements(readings: Sequence[Reading | str]) -> Measurements:
    """``readings`` in document order. A measurement's value is that of the earliest document
    carrying its date, so a carried-over value is one measurement, never several."""
    first: dict[datetime, float] = {}
    revised = 0
    for r in readings:
        if not isinstance(r, Reading):
            continue
        if r.measured_at not in first:
            first[r.measured_at] = r.value
        elif r.value != first[r.measured_at]:
            revised += 1
    dates = sorted(first)
    return Measurements(dates, [first[d] for d in dates], revised)


def hours(delta: timedelta) -> float:
    return delta.total_seconds() / 3600


def duration_summary(values: Sequence[float]) -> Json:
    q = quartiles(values)
    return {
        "count": len(values),
        "median": median(values),
        "q1": q[0] if q else None,
        "q3": q[2] if q else None,
        "max": max(values) if values else None,
    }


# --- per-series report ----------------------------------------------------------------------


@dataclass(frozen=True)
class SeriesResult:
    series: Series
    unusable: Counter[str]
    mixed_units: bool
    n: int
    revised_same_date_readings: int
    cv: Stat
    ratio: Stat
    spread: Stat
    classes: Counter[str] | None
    intervals_hours: list[float]
    per_document_n: int
    per_document_cv: Stat
    per_document_ratio: Stat

    def to_json(self, *, dense: bool) -> Json:
        out: Json = {
            "resource": self.series.key[0],
            "parameter": self.series.key[1],
            "group": self.series.group,
            "unusable_readings": {r: self.unusable.get(r, 0) for r in UNUSABLE_REASONS},
            "mixed_units": self.mixed_units,
            "measurements": self.n,
            "revised_same_date_readings": self.revised_same_date_readings,
            "cv": self.cv.to_json(),
            "max_min_ratio": self.ratio.to_json(),
            "successive_spread_over_mean": self.spread.to_json(),
        }
        if dense:
            assert self.classes is not None
            out["d27_classes"] = {c: self.classes.get(c, 0) for c in D27_CLASSES}
            out["measurement_intervals_hours"] = duration_summary(self.intervals_hours)
            out["per_document_not_used_for_marking"] = {
                "documents": self.per_document_n,
                "cv": self.per_document_cv.to_json(),
                "max_min_ratio": self.per_document_ratio.to_json(),
            }
        return out


def _mixed(stat: Stat, mixed: bool) -> Stat:
    return Stat(None, MIXED_UNITS) if mixed else stat


def analyze_series(series: Series, documents: Sequence[Document]) -> SeriesResult:
    readings = [read(d, series.key) for d in documents]
    usable = [r for r in readings if isinstance(r, Reading)]
    unusable = Counter(r for r in readings if isinstance(r, str))
    mixed = len({r.unit for r in usable}) > 1
    m = measurements(readings)
    per_document = [r.value for r in usable]
    return SeriesResult(
        series=series,
        unusable=unusable,
        mixed_units=mixed,
        n=len(m.values),
        revised_same_date_readings=m.revised_same_date_readings,
        cv=_mixed(coefficient_of_variation(m.values), mixed),
        ratio=_mixed(max_min_ratio(m.values), mixed),
        spread=_mixed(successive_spread(m.values), mixed),
        classes=Counter(classify(a, b) for a, b in pairwise(readings)),
        intervals_hours=[hours(b - a) for a, b in pairwise(m.dates)],
        per_document_n=len(per_document),
        per_document_cv=_mixed(coefficient_of_variation(per_document), mixed),
        per_document_ratio=_mixed(max_min_ratio(per_document), mixed),
    )


def stat_median(stats: Iterable[Stat]) -> Json:
    defined = [s.value for s in stats if s.value is not None]
    return {"median": median(defined), "defined": len(defined)}


def parameter_medians(results: Sequence[SeriesResult]) -> Json:
    groups: dict[str, list[SeriesResult]] = {}
    for r in results:
        groups.setdefault(r.series.group, []).append(r)
    return {
        group: {
            "resources": len(rs),
            "cv": stat_median(r.cv for r in rs),
            "max_min_ratio": stat_median(r.ratio for r in rs),
            "successive_spread_over_mean": stat_median(r.spread for r in rs),
        }
        for group, rs in groups.items()
    }


# --- set overview ---------------------------------------------------------------------------


def set_overview(data: DataSet, series: Sequence[Series]) -> Json:
    lags = [hours(t - doc.stamp) for t, (_, doc) in data.lookups.items() if doc.stamp is not None]
    docs = data.documents
    ties = sum(1 for a, b in pairwise(docs) if a.stamp == b.stamp)
    reasons: Counter[str] = Counter()
    with_unusable = 0
    for doc in distinct(doc for _, doc in data.lookups.values()):
        found = [r for r in (read(doc, s.key) for s in series) if isinstance(r, str)]
        reasons.update(found)
        with_unusable += bool(found)
    return {
        "grid_times": len(data.grid),
        "lookups_present": len(data.lookups),
        "missing_grid_times": len(data.grid) - len(data.lookups),
        "distinct_documents": data.distinct_documents,
        "documents_without_stamp": data.documents_without_stamp,
        "stamp_ties": ties,
        "requested_minus_stamp_hours": {
            "median": median(lags),
            "max": max(lags) if lags else None,
        },
        "documents_with_unusable_in_scope_series": with_unusable,
        "unusable_readings_by_reason": {r: reasons.get(r, 0) for r in UNUSABLE_REASONS},
    }


# --- lag profile and P3 ---------------------------------------------------------------------


@dataclass(frozen=True)
class LagPair:
    available: bool
    """False when a lookup is missing at G_0 or G_k."""
    tau: Stat
    n: int
    same_document: bool | None
    same_date: int
    untied: bool = False
    """No tie among the values on either document."""

    def to_json(self) -> Json:
        if not self.available:
            return {"tau_b": "undefined: lookup_missing", "n": 0}
        return {
            "tau_b": self.tau.to_json(),
            "n": self.n,
            "same_document": self.same_document,
            "resources_with_same_date": self.same_date,
        }


def lag_pair(sparse: DataSet, k: int, keys: Sequence[SeriesKey]) -> LagPair:
    g0, gk = sparse.grid[0], sparse.grid[k]
    if g0 not in sparse.lookups or gk not in sparse.lookups:
        return LagPair(False, Stat(None, "lookup_missing"), 0, None, 0)
    doc0, dock = sparse.lookups[g0][1], sparse.lookups[gk][1]
    a: list[float] = []
    b: list[float] = []
    same_date = 0
    for key in keys:
        r0, rk = read(doc0, key), read(dock, key)
        if isinstance(r0, Reading) and isinstance(rk, Reading):
            a.append(r0.value)
            b.append(rk.value)
            same_date += r0.measured_at == rk.measured_at
    same = doc0.content_hash == dock.content_hash
    untied = len(set(a)) == len(a) and len(set(b)) == len(b)
    return LagPair(True, kendall_tau_b(a, b), len(a), same, same_date, untied)


def window_documents(sparse: DataSet, last_step: int) -> int:
    """Distinct documents among the lookups at G_0..G_last_step."""
    docs = [sparse.lookups[t][1] for t in sparse.grid[: last_step + 1] if t in sparse.lookups]
    return len(distinct(docs))


# --- P4 -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class P4Counts:
    documents: int
    pairs: int
    numeric: int
    nonzero: int
    without_numeric_value: Counter[str]
    dated: int
    date_equals_stamp: int
    without_dates: int


def p4_counts(documents: Sequence[Document], qubits: Sequence[int]) -> P4Counts:
    numeric = nonzero = dated = equal = without_dates = pairs = 0
    without: Counter[str] = Counter()
    for doc in documents:
        for q in qubits:
            pairs += 1
            rows = doc.rows.get(rz_key(q), ())
            if not rows:
                without["missing_row"] += 1
                without_dates += 1
                continue
            if len(rows) > 1:
                without["duplicate_rows"] += 1
                without_dates += 1
                continue
            row = rows[0]
            if row.value is None:
                without["null_value"] += 1
            elif not isinstance(row.value, float):
                without["non_numeric_value"] += 1
            elif not math.isfinite(row.value):
                without["non_finite_value"] += 1
            else:
                numeric += 1
                nonzero += row.value != 0.0
            if row.measured_at is None or doc.stamp is None:
                without_dates += 1
            else:
                dated += 1
                equal += row.measured_at == doc.stamp
    return P4Counts(len(documents), pairs, numeric, nonzero, without, dated, equal, without_dates)


# --- marking --------------------------------------------------------------------------------


def mark_p1(distinct_documents: int, cvs: Sequence[Stat]) -> Json:
    defined = [s.value for s in cvs if s.value is not None]
    statistic = median(defined)
    if distinct_documents < MIN_DOCUMENTS or len(defined) < MIN_DEFINED:
        mark = NOT_TESTABLE
    else:
        assert statistic is not None
        mark = SUPPORTED if statistic >= P1_THRESHOLD else NOT_SUPPORTED
    return {
        "mark": mark,
        "distinct_documents": distinct_documents,
        "qubits_with_defined_cv": len(defined),
        "median_cv": statistic,
    }


def mark_p2(distinct_documents: int, ratios: Sequence[Stat]) -> Json:
    defined = [s.value for s in ratios if s.value is not None]
    if distinct_documents < MIN_DOCUMENTS:
        mark = NOT_TESTABLE
    elif any(r >= P2_THRESHOLD for r in defined):
        mark = SUPPORTED
    elif len(defined) >= MIN_DEFINED:
        mark = NOT_SUPPORTED
    else:
        mark = NOT_TESTABLE
    return {
        "mark": mark,
        "distinct_documents": distinct_documents,
        "qubits_with_defined_ratio": len(defined),
        "qubits_with_ratio_at_least_3": sum(r >= P2_THRESHOLD for r in defined),
        "largest_ratio": max(defined) if defined else None,
    }


P3_REFERENCE_QUBITS = 5
P3_INTERPRETATION = (
    "Interpretation only (2026-10-18, before collection): under a uniformly random relative "
    "ordering of 5 untied qubits, P(tau-b < 0.5) = 106/120, about 0.88. A 'supported' P3 is "
    "therefore weak evidence of rank instability; 'not supported' is the more informative "
    "outcome. Not used for marking."
)


def random_order_probability(n: int) -> Json:
    below, total = random_order_below(n, P3_THRESHOLD)
    return {"untied_items": n, "below": below, "orderings": total, "probability": below / total}


def p3_random_order(pair: LagPair) -> Json | str:
    """P(tau-b < 0.5) under a uniformly random relative ordering of this pair's n untied
    qubits. Interpretation only."""
    if not pair.available:
        return "undefined: lookup_missing"
    if pair.n < 3:
        return "undefined: too_few_measurements"
    if not pair.untied:
        return "undefined: ties"
    return random_order_probability(pair.n)


def mark_p3(window_docs: int, pair: LagPair) -> Json:
    if window_docs < MIN_DOCUMENTS or not pair.available or pair.tau.value is None:
        outcome = NOT_TESTABLE
    else:
        outcome = BELOW if pair.tau.value < P3_THRESHOLD else AT_OR_ABOVE
    return {
        "outcome": outcome,
        "distinct_documents_g0_to_g6": window_docs,
        **pair.to_json(),
        "random_order_probability_below_0.5": p3_random_order(pair),
    }


def mark_p4(c: P4Counts) -> Json:
    fraction = c.date_equals_stamp / c.dated if c.dated else None
    if c.documents < MIN_DOCUMENTS or c.numeric == 0 or fraction is None:
        mark = NOT_TESTABLE
    else:
        mark = SUPPORTED if c.nonzero == 0 and fraction >= P4_FRACTION else NOT_SUPPORTED
    return {
        "mark": mark,
        "distinct_documents": c.documents,
        "document_qubit_pairs": c.pairs,
        "pairs_with_numeric_value": c.numeric,
        "nonzero_values": c.nonzero,
        "pairs_without_numeric_value": dict(sorted(c.without_numeric_value.items())),
        "pairs_with_both_dates": c.dated,
        "pairs_without_a_date": c.without_dates,
        "fraction_date_equals_stamp": fraction,
    }


def overall_all_devices(marks: Iterable[str]) -> str:
    """P1, P2, P4: supported on all devices; not supported on at least one; else not
    testable."""
    marks = list(marks)
    if NOT_SUPPORTED in marks:
        return NOT_SUPPORTED
    if marks and all(m == SUPPORTED for m in marks):
        return SUPPORTED
    return NOT_TESTABLE


def overall_p3(outcomes: Iterable[str]) -> str:
    outcomes = list(outcomes)
    below = outcomes.count(BELOW)
    if below >= 2:
        return SUPPORTED
    if below + outcomes.count(NOT_TESTABLE) < 2:
        return NOT_SUPPORTED
    return NOT_TESTABLE


# --- device and experiment ------------------------------------------------------------------


@dataclass
class DeviceResult:
    json: Json
    p1: Json
    p2: Json
    p3: Json
    p4: Json
    lag: dict[str, dict[int, LagPair]] = field(default_factory=dict)


def analyze_device(
    reader: StoreReader, backend: str, footprint: Footprint, collection_date: date
) -> DeviceResult:
    keys = all_keys(footprint)
    series = in_scope_series(footprint)
    lookups = reader.lookups(backend)
    dense = build_set(reader, lookups, dense_grid(collection_date), keys)
    sparse = build_set(reader, lookups, sparse_grid(collection_date), keys)

    dense_results = [analyze_series(s, dense.documents) for s in series]
    sparse_results = [analyze_series(s, sparse.documents) for s in series]
    by_key = {r.series.key: r for r in dense_results}

    lag = {
        group: {k: lag_pair(sparse, k, group_keys(footprint, group)) for k in LAG_STEPS}
        for group in LAG_GROUPS
    }

    p1 = mark_p1(dense.distinct_documents, [by_key[k].cv for k in group_keys(footprint, "T1")])
    p1["per_document_not_used_for_marking"] = stat_median(
        by_key[k].per_document_cv for k in group_keys(footprint, "T1")
    )
    readout = group_keys(footprint, "readout_error")
    p2 = mark_p2(dense.distinct_documents, [by_key[k].ratio for k in readout])
    per_doc_ratios = [
        v for v in (by_key[k].per_document_ratio.value for k in readout) if v is not None
    ]
    p2["per_document_not_used_for_marking"] = {
        "qubits_with_defined_ratio": len(per_doc_ratios),
        "largest_ratio": max(per_doc_ratios) if per_doc_ratios else None,
    }
    p3 = mark_p3(window_documents(sparse, P3_STEP), lag["readout_error"][P3_STEP])
    p4_docs = distinct(
        [doc for _, doc in dense.lookups.values()] + [doc for _, doc in sparse.lookups.values()]
    )
    p4 = mark_p4(p4_counts(p4_docs, footprint.qubits))

    lookups_json = {"duplicate_lookups_ignored": lookups.duplicate_lookups}
    device_json: Json = {
        "lookups": lookups_json,
        "dense": {
            "overview": set_overview(dense, series),
            "series": [r.to_json(dense=True) for r in dense_results],
            "parameter_medians": parameter_medians(dense_results),
        },
        "sparse": {
            "overview": set_overview(sparse, series),
            "series": [r.to_json(dense=False) for r in sparse_results],
            "lag_profile": {
                group: {f"G_{k}": pair.to_json() for k, pair in pairs.items()}
                for group, pairs in lag.items()
            },
        },
    }
    return DeviceResult(device_json, p1, p2, p3, p4, lag)


def analyze(repository: SqliteSnapshotRepository, collection_date: date) -> Json:
    """The full result for every device. Reads only; never writes the store."""
    reader = StoreReader(repository)
    devices = {
        backend: analyze_device(reader, backend, footprint, collection_date)
        for backend, footprint in FOOTPRINTS.items()
    }
    predictions: Json = {
        "P1": {
            "per_device": {b: d.p1 for b, d in devices.items()},
            "overall": overall_all_devices(d.p1["mark"] for d in devices.values()),
        },
        "P2": {
            "per_device": {b: d.p2 for b, d in devices.items()},
            "overall": overall_all_devices(d.p2["mark"] for d in devices.values()),
        },
        "P3": {
            "per_device": {b: d.p3 for b, d in devices.items()},
            "overall": overall_p3(d.p3["outcome"] for d in devices.values()),
            "random_order_reference": {
                **random_order_probability(P3_REFERENCE_QUBITS),
                "note": P3_INTERPRETATION,
            },
        },
        "P4": {
            "per_device": {b: d.p4 for b, d in devices.items()},
            "overall": overall_all_devices(d.p4["mark"] for d in devices.values()),
        },
    }
    return {
        "method": METHOD,
        "method_version": METHOD_VERSION,
        "evidence_kind": EVIDENCE_KIND,
        "collection_date": collection_date.isoformat(),
        "dense_anchor_E_d": dense_anchor(collection_date).isoformat(),
        "sparse_anchor_E_s": sparse_anchor(collection_date).isoformat(),
        "predictions": predictions,
        "devices": {b: d.json for b, d in devices.items()},
    }


# --- Markdown -------------------------------------------------------------------------------


def fmt(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.4g}"
    if isinstance(value, dict) and "probability" in value:
        return f"{value['below']}/{value['orderings']} = {value['probability']:.4g}"
    return str(value)


def table(headers: Sequence[str], rows: Iterable[Sequence[object]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(fmt(v) for v in row) + " |" for row in rows]
    return [*lines, ""]


def render_markdown(result: Json) -> str:
    """A Markdown summary of ``result``. Aggregate statistics only."""
    lines = [
        "# M1.5d calibration history: results",
        "",
        f"Method `{result['method_version']}`; every number is `{result['evidence_kind']}`.",
        f"Collection date D = {result['collection_date']}; E_d = {result['dense_anchor_E_d']};"
        f" E_s = {result['sparse_anchor_E_s']}.",
        "",
    ]
    provenance = result.get("provenance")
    if provenance:
        lines += [
            "## Provenance",
            "",
            *table(
                ["Field", "Value"],
                [
                    ("git commit", provenance["git_commit"]),
                    ("git dirty", provenance["git_dirty"]),
                    ("store SHA-256 before", provenance["store_sha256_before"]),
                    ("store SHA-256 after", provenance["store_sha256_after"]),
                    ("store unchanged", provenance["store_unchanged"]),
                ],
            ),
        ]
    preds = result["predictions"]
    lines += ["## Predictions", ""]
    lines += table(
        ["Prediction", *FOOTPRINTS, "Overall"],
        [
            (
                name,
                *(
                    preds[name]["per_device"][b]["outcome" if name == "P3" else "mark"]
                    for b in FOOTPRINTS
                ),
                preds[name]["overall"],
            )
            for name in ("P1", "P2", "P3", "P4")
        ],
    )
    reference = preds["P3"]["random_order_reference"]
    lines += [
        f"P3 overall: {preds['P3']['overall']}. Beside it, P(tau-b < 0.5) under a uniformly "
        f"random relative ordering of {reference['untied_items']} untied qubits: "
        f"{fmt(reference)}. {reference['note']}",
        "",
    ]
    for name, fields in (
        ("P1", ("distinct_documents", "qubits_with_defined_cv", "median_cv")),
        (
            "P2",
            (
                "distinct_documents",
                "qubits_with_defined_ratio",
                "qubits_with_ratio_at_least_3",
                "largest_ratio",
            ),
        ),
        (
            "P3",
            (
                "distinct_documents_g0_to_g6",
                "tau_b",
                "n",
                "same_document",
                "resources_with_same_date",
                "random_order_probability_below_0.5",
            ),
        ),
        (
            "P4",
            (
                "distinct_documents",
                "pairs_with_numeric_value",
                "nonzero_values",
                "pairs_with_both_dates",
                "fraction_date_equals_stamp",
            ),
        ),
    ):
        lines += [f"### {name}", ""]
        lines += table(
            ["Device", *fields],
            [(b, *(preds[name]["per_device"][b].get(f) for f in fields)) for b in FOOTPRINTS],
        )
    for b, device in result["devices"].items():
        lines += [f"## {b}", "", "### Sets", ""]
        overview_fields = (
            "grid_times",
            "lookups_present",
            "missing_grid_times",
            "distinct_documents",
            "documents_without_stamp",
            "stamp_ties",
            "documents_with_unusable_in_scope_series",
        )
        lines += table(
            ["Set", *overview_fields, "requested - stamp, median h", "max h"],
            [
                (
                    name,
                    *(device[name]["overview"][f] for f in overview_fields),
                    device[name]["overview"]["requested_minus_stamp_hours"]["median"],
                    device[name]["overview"]["requested_minus_stamp_hours"]["max"],
                )
                for name in ("dense", "sparse")
            ],
        )
        lines += table(
            ["Set", *UNUSABLE_REASONS],
            [
                (name, *device[name]["overview"]["unusable_readings_by_reason"].values())
                for name in ("dense", "sparse")
            ],
        )
        lines += ["### Dense: per-parameter medians over footprint resources", ""]
        lines += table(
            [
                "Parameter",
                "resources",
                "median CV",
                "(defined)",
                "median max/min",
                "(defined)",
                "median d/m",
                "(defined)",
            ],
            [
                (
                    group,
                    g["resources"],
                    g["cv"]["median"],
                    g["cv"]["defined"],
                    g["max_min_ratio"]["median"],
                    g["max_min_ratio"]["defined"],
                    g["successive_spread_over_mean"]["median"],
                    g["successive_spread_over_mean"]["defined"],
                )
                for group, g in device["dense"]["parameter_medians"].items()
            ],
        )
        lines += ["### Dense: per series", ""]
        lines += table(
            [
                "Resource",
                "Parameter",
                "n",
                *D27_CLASSES,
                "interval median h",
                "CV",
                "max/min",
                "d/m",
            ],
            [
                (
                    s["resource"],
                    s["parameter"],
                    s["measurements"],
                    *s["d27_classes"].values(),
                    s["measurement_intervals_hours"]["median"],
                    s["cv"],
                    s["max_min_ratio"],
                    s["successive_spread_over_mean"],
                )
                for s in device["dense"]["series"]
            ],
        )
        lines += ["### Sparse: per series", ""]
        lines += table(
            ["Resource", "Parameter", "n", "CV", "max/min", "d/m"],
            [
                (
                    s["resource"],
                    s["parameter"],
                    s["measurements"],
                    s["cv"],
                    s["max_min_ratio"],
                    s["successive_spread_over_mean"],
                )
                for s in device["sparse"]["series"]
            ],
        )
        lines += ["### Sparse: lag profile (Kendall's tau-b, G_0 against G_k)", ""]
        lag = device["sparse"]["lag_profile"]
        lines += table(
            ["Parameter", *(f"G_{k}" for k in LAG_STEPS)],
            [
                (
                    group,
                    *(
                        f"{fmt(p['tau_b'])} (n={p['n']}, same doc: "
                        f"{fmt(p.get('same_document'))}, same date: "
                        f"{fmt(p.get('resources_with_same_date'))})"
                        for p in lag[group].values()
                    ),
                )
                for group in LAG_GROUPS
            ],
        )
    return "\n".join(lines)
