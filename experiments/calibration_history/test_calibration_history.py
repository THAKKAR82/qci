"""Offline tests of the M1.5d analysis on synthetic stores built in temporary directories.

Expected values are computed here by hand or with the standard library's ``statistics``
module, never by calling the statistic under test.
"""

import hashlib
import json
import math
import statistics
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from itertools import combinations, permutations
from pathlib import Path

import pytest
import run_analysis
from history_analysis import (
    AT_OR_ABOVE,
    BELOW,
    NOT_SUPPORTED,
    NOT_TESTABLE,
    SUPPORTED,
    LagPair,
    P4Counts,
    analyze,
    dense_grid,
    mark_p1,
    mark_p2,
    mark_p3,
    mark_p4,
    overall_all_devices,
    overall_p3,
    sparse_grid,
)
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

from qci.domain.backend import SnapshotSource
from qci.domain.provenance import GitProvenance
from qci.domain.snapshot import CalibrationSnapshot, Measurement, SnapshotCapture
from qci.storage.snapshots import SqliteSnapshotRepository

D = date(2026, 10, 20)
E_D = datetime(2026, 10, 20, tzinfo=UTC)
# 2026-10-19 is 20,745 days after the epoch, a multiple of 5 days (120 h).
E_S = datetime(2026, 10, 19, tzinfo=UTC)
H = timedelta(hours=1)

FEZ_QUBITS = (136, 141, 142, 143, 144)
FEZ_PAIRS = ((142, 141), (142, 143), (143, 136), (143, 142), (143, 144))
KINGSTON_QUBITS = (138, 149, 150, 151, 152)
MARRAKESH_QUBITS = (10, 11, 12, 13, 18)

Json = dict[str, object]


# --- synthetic store ------------------------------------------------------------------------


def m(
    resource: str,
    parameter: str,
    value: float | str | None,
    measured_at: datetime | None,
    unit: str | None = None,
) -> Measurement:
    return Measurement(
        resource_kind=resource.split("/")[0],
        resource=resource,
        parameter=parameter,
        value=value,
        unit=unit,
        measured_at=measured_at,
    )


class StoreBuilder:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.repo = SqliteSnapshotRepository(path)
        self.count = 0
        self.captures = 0
        self.values: list[float] = []

    def add(
        self,
        backend: str,
        stamp: datetime | None,
        rows: Sequence[Measurement],
        grid_times: Sequence[datetime],
        *,
        live: bool = False,
    ) -> None:
        """One distinct document, returned by a lookup at each of ``grid_times``."""
        self.count += 1
        self.values += [r.value for r in rows if isinstance(r.value, float)]
        snapshot = CalibrationSnapshot(
            snapshot_id=f"SNAP-{self.count:04d}",
            content_hash=f"sha256:{self.count:064x}",
            provider="qiskit_ibm",
            backend_name=backend,
            backend_version="1.0.0",
            source=SnapshotSource.LIVE_CALIBRATION if live else SnapshotSource.HISTORICAL_LOOKUP,
            captured_at=datetime(2026, 10, 20, 12, tzinfo=UTC),
            calibrated_at=stamp,
            capture_options={},
            extraction_method="synthetic",
            extraction_method_version="1",
            redactions=[],
            environment={},
            provider_raw={},
        )
        times: Sequence[datetime | None] = [None] if live else grid_times
        for t in times:
            self.captures += 1
            capture = SnapshotCapture(
                capture_id=f"CAP-{self.captures:05d}",
                snapshot_id=snapshot.snapshot_id,
                captured_at=datetime(2026, 10, 20, 12, tzinfo=UTC) + self.captures * H,
                method="live_capture" if t is None else "historical_lookup",
                requested_before=t,
            )
            self.repo.save(snapshot, rows, capture)

    def close(self) -> None:
        self.repo.close()


@pytest.fixture
def builder(tmp_path: Path) -> StoreBuilder:
    return StoreBuilder(tmp_path / "qci.db")


def run(builder: StoreBuilder) -> Json:
    builder.close()
    repo = SqliteSnapshotRepository(builder.path, read_only=True)
    try:
        return analyze(repo, D)
    finally:
        repo.close()


def device(result: Json, backend: str = "ibm_fez") -> dict[str, dict[str, object]]:
    devices = result["devices"]
    assert isinstance(devices, dict)
    out = devices[backend]
    assert isinstance(out, dict)
    return out


def dense_series(result: Json, resource: str, parameter: str) -> dict[str, object]:
    for s in device(result)["dense"]["series"]:  # type: ignore[attr-defined]
        if s["resource"] == resource and s["parameter"] == parameter:
            return s  # type: ignore[no-any-return]
    raise AssertionError(f"no series {resource} {parameter}")


def prediction(result: Json, name: str) -> dict[str, object]:
    predictions = result["predictions"]
    assert isinstance(predictions, dict)
    out = predictions[name]
    assert isinstance(out, dict)
    return out


def full_rows(
    qubits: Sequence[int],
    pairs: Sequence[tuple[int, int]],
    value: Callable[[str, str, int], float],
    measured_at: datetime,
    stamp: datetime,
) -> list[Measurement]:
    """Every in-scope row plus rz, the value given by ``value(resource, parameter, index)``."""
    rows: list[Measurement] = []
    for i, q in enumerate(qubits):
        for p, unit in (
            ("T1", "us"),
            ("T2", "us"),
            ("readout_error", None),
            ("prob_meas0_prep1", None),
            ("prob_meas1_prep0", None),
            ("init_error", None),
        ):
            rows.append(m(f"qubit/{q}", p, value(f"qubit/{q}", p, i), measured_at, unit))
        for g in ("sx", "measure"):
            r = f"gate/{g}/{q}"
            rows.append(m(r, "gate_error", value(r, "gate_error", i), measured_at))
        rows.append(m(f"gate/rz/{q}", "gate_error", 0.0, stamp))
    for i, (a, b) in enumerate(pairs):
        r = f"gate/cz/{a},{b}"
        rows.append(m(r, "gate_error", value(r, "gate_error", i), measured_at))
    return rows


# --- statistics -----------------------------------------------------------------------------


def test_cv_ratio_and_successive_spread_by_hand() -> None:
    xs = [2.0, 4.0, 6.0]
    # m = 4, s = sqrt((4 + 0 + 4) / 2) = 2, CV = 0.5.
    assert coefficient_of_variation(xs).value == pytest.approx(0.5)
    assert max_min_ratio(xs).value == pytest.approx(3.0)
    # d = sqrt((2^2 + 2^2) / (2 * 2)) = sqrt(2), d / m = sqrt(2) / 4.
    assert successive_spread(xs).value == pytest.approx(math.sqrt(2) / 4)
    assert coefficient_of_variation([1.0]) == Stat(None, "too_few_measurements")
    assert max_min_ratio([0.0, 1.0]) == Stat(None, "non_positive_minimum")
    assert successive_spread([1.0, 2.0]) == Stat(None, "too_few_measurements")
    assert coefficient_of_variation([-1.0, -3.0]) == Stat(None, "non_positive_mean")


def test_median_and_type_7_quartiles_by_hand() -> None:
    assert median([3.0, 1.0, 2.0]) == 2.0
    assert median([4.0, 1.0, 3.0, 2.0]) == 2.5
    assert median([]) is None
    # Type 7: position (n - 1) p on the sorted list [1, 2, 3, 4]: 0.75, 1.5, 2.25.
    assert quartiles([4.0, 1.0, 3.0, 2.0]) == pytest.approx((1.75, 2.5, 3.25))


def test_kendall_tau_b_without_ties() -> None:
    # Pairs: 9 concordant, 1 discordant (4, 5), no ties: (9 - 1) / 10.
    assert kendall_tau_b([1, 2, 3, 4, 5], [1, 2, 3, 5, 4]).value == pytest.approx(0.8)
    assert kendall_tau_b([1, 2, 3, 4, 5], [5, 4, 3, 2, 1]).value == pytest.approx(-1.0)


def test_kendall_tau_b_with_ties_on_one_side_each() -> None:
    # a = (1, 2, 2, 3), b = (1, 3, 2, 2). Concordant: (1,2) (1,3) (1,4). Discordant: (2,4).
    # Tied: (2,3) in a, (3,4) in b. n_0 = 6, n_1 = 1, n_2 = 1: 2 / sqrt(5 * 5) = 0.4.
    assert kendall_tau_b([1, 2, 2, 3], [1, 3, 2, 2]).value == pytest.approx(0.4)


def test_kendall_tau_b_with_ties_on_both_sides() -> None:
    # a = (1, 1, 2, 2, 3), b = (1, 2, 1, 2, 3). Concordant: (1,4) (1,5) (2,5) (3,5) (4,5).
    # Discordant: (2,3). n_0 = 10, n_1 = 2, n_2 = 2: 4 / sqrt(8 * 8) = 0.5.
    assert kendall_tau_b([1, 1, 2, 2, 3], [1, 2, 1, 2, 3]).value == pytest.approx(0.5)


def test_kendall_tau_b_undefined() -> None:
    assert kendall_tau_b([1, 2], [2, 1]) == Stat(None, "too_few_measurements")
    assert kendall_tau_b([1, 1, 1], [1, 2, 3]) == Stat(None, "all_values_tied")


# --- windows and selection ------------------------------------------------------------------


def test_grids() -> None:
    dense = dense_grid(D)
    assert len(dense) == 169
    assert dense[0] == E_D
    assert dense[-1] == E_D - 168 * H
    sparse = sparse_grid(D)
    assert len(sparse) == 73
    assert sparse[0] == E_S
    assert sparse[6] == E_S - timedelta(days=30)
    assert sparse[72] == E_S - timedelta(days=360)


def test_selection_uses_only_lookups_on_the_grid_inside_the_window(builder: StoreBuilder) -> None:
    def rows(stamp: datetime) -> list[Measurement]:
        return [m("qubit/136", "T1", 100.5, stamp, "us")]

    builder.add("ibm_fez", E_D - 2 * H, rows(E_D - 2 * H), [E_D])
    builder.add("ibm_fez", E_D - 170 * H, rows(E_D - 170 * H), [E_D - 168 * H])
    builder.add("ibm_fez", E_D - 171 * H, rows(E_D - 171 * H), [E_D - 169 * H])  # too old
    builder.add("ibm_fez", E_D + 0.5 * H, rows(E_D), [E_D + H])  # after E_d
    builder.add("ibm_fez", E_D - 5 * H, rows(E_D - 5 * H), [E_D - 4.5 * H])  # off the grid
    builder.add("ibm_fez", E_D - H, rows(E_D - H), [], live=True)  # a live capture
    builder.add("ibm_kingston", E_D - H, rows(E_D - H), [E_D - H])  # another device
    overview = device(run(builder))["dense"]["overview"]
    assert isinstance(overview, dict)
    assert overview["lookups_present"] == 2
    assert overview["missing_grid_times"] == 167
    assert overview["distinct_documents"] == 2
    # Requested minus stamp: 2 h and 2 h.
    assert overview["requested_minus_stamp_hours"] == {"median": 2.0, "max": 2.0}


def test_one_document_at_several_grid_times_counts_once(builder: StoreBuilder) -> None:
    builder.add("ibm_fez", E_D - 3 * H, [], [E_D, E_D - H, E_D - 2 * H])
    overview = device(run(builder))["dense"]["overview"]
    assert isinstance(overview, dict)
    assert overview["lookups_present"] == 3
    assert overview["distinct_documents"] == 1


# --- D27 classes, measurements and unusable readings ----------------------------------------


def test_every_d27_class_and_measurements(builder: StoreBuilder) -> None:
    t1 = E_D - 100 * H
    t2, t3, t4 = t1 + 10 * H, t1 + 30 * H, t1 + 60 * H
    docs: list[tuple[float, datetime | None, float | None]] = [
        # (stamp offset in hours from E_D - 90 h, date, value), in stamp order.
        (0, t1, 1.0),
        (1, t1, 1.0),  # not_re_measured
        (2, t1, 2.0),  # revised_same_date
        (3, t2, 2.0),  # re_measured_same_value
        (4, t3, 3.0),  # re_measured_different_value
        (5, t2, 5.0),  # date_earlier, and a revision of t2
        (6, None, None),  # no row: unavailable
        (7, t4, 4.0),  # unavailable (previous reading missing)
    ]
    # Insert in reverse so that order comes from the stamps, not from insertion.
    for offset, when, value in reversed(docs):
        stamp = E_D - 90 * H + offset * H
        rows = [] if when is None else [m("qubit/136", "T1", value, when, "us")]
        builder.add("ibm_fez", stamp, rows, [E_D - (80 - offset) * H])
    s = dense_series(run(builder), "qubit/136", "T1")
    assert s["d27_classes"] == {
        "unavailable": 2,
        "not_re_measured": 1,
        "revised_same_date": 1,
        "re_measured_same_value": 1,
        "re_measured_different_value": 1,
        "date_earlier": 1,
    }
    # Measurements: t1 -> 1.0, t2 -> 2.0, t3 -> 3.0, t4 -> 4.0. Revisions: doc 3 and doc 6.
    assert s["measurements"] == 4
    assert s["revised_same_date_readings"] == 2
    assert s["cv"] == pytest.approx(statistics.stdev([1, 2, 3, 4]) / 2.5)
    assert s["max_min_ratio"] == pytest.approx(4.0)
    # Intervals 10, 20 and 30 h.
    assert s["measurement_intervals_hours"] == {
        "count": 3,
        "median": 20.0,
        "q1": 15.0,
        "q3": 25.0,
        "max": 30.0,
    }
    unusable = s["unusable_readings"]
    assert isinstance(unusable, dict)
    assert unusable["missing_row"] == 1


def test_carried_over_value_is_one_measurement(builder: StoreBuilder) -> None:
    first, second = E_D - 50 * H, E_D - 20 * H
    values = [(first, 2.0)] * 4 + [(second, 6.0)] * 2
    for i, (when, value) in enumerate(values):
        stamp = E_D - 40 * H + i * H
        builder.add("ibm_fez", stamp, [m("qubit/136", "T1", value, when, "us")], [E_D - i * H])
    s = dense_series(run(builder), "qubit/136", "T1")
    assert s["measurements"] == 2
    assert s["cv"] == pytest.approx(statistics.stdev([2.0, 6.0]) / statistics.mean([2.0, 6.0]))
    per_doc = [v for _, v in values]
    assert s["per_document_not_used_for_marking"] == {
        "documents": 6,
        "cv": pytest.approx(statistics.stdev(per_doc) / statistics.mean(per_doc)),
        "max_min_ratio": pytest.approx(3.0),
    }
    assert s["d27_classes"] == {
        "unavailable": 0,
        "not_re_measured": 4,
        "revised_same_date": 0,
        "re_measured_same_value": 0,
        "re_measured_different_value": 1,
        "date_earlier": 0,
    }


def test_unusable_readings_are_left_out_and_counted_never_zero(builder: StoreBuilder) -> None:
    r, p = "qubit/136", "readout_error"
    base = E_D - 100 * H
    docs: list[list[Measurement]] = [
        [m(r, p, 0.02, base)],
        [m(r, p, None, base + H)],
        [m(r, p, "n/a", base + 2 * H)],
        [m(r, p, math.inf, base + 3 * H)],
        [m(r, p, 0.07, None)],
        [m(r, p, 0.03, base + 5 * H), m(r, p, 0.05, base + 5 * H)],
        [],
        [m(r, p, 0.04, base + 7 * H)],
        [m(r, p, 0.06, base + 8 * H)],
    ]
    for i, rows in enumerate(docs):
        builder.add("ibm_fez", base + i * H + 0.5 * H, rows, [E_D - (60 - i) * H])
    s = dense_series(run(builder), r, p)
    assert s["unusable_readings"] == {
        "missing_row": 1,
        "duplicate_rows": 1,
        "null_value": 1,
        "non_numeric_value": 1,
        "non_finite_value": 1,
        "missing_date": 1,
    }
    # Only 0.02, 0.04 and 0.06 are measurements. A 0 in their place would leave the ratio
    # undefined.
    assert s["measurements"] == 3
    assert s["max_min_ratio"] == pytest.approx(3.0)
    assert s["cv"] == pytest.approx(0.5)


def test_dimensionless_series_without_a_unit_is_usable(builder: StoreBuilder) -> None:
    for i, value in enumerate((0.01, 0.02, 0.03)):
        when = E_D - (30 - i) * H
        builder.add("ibm_fez", when, [m("qubit/136", "readout_error", value, when)], [E_D - i * H])
    s = dense_series(run(builder), "qubit/136", "readout_error")
    assert s["mixed_units"] is False
    assert s["measurements"] == 3
    assert s["max_min_ratio"] == pytest.approx(3.0)


@pytest.mark.parametrize(
    ("units", "label"),
    [
        ((None, None, None, "us", "us", "us"), "no unit to a unit"),
        (("us", "us", "us", "ms", "ms", "ms"), "one unit to another"),
    ],
)
def test_mixed_units_get_no_statistic(
    builder: StoreBuilder, units: tuple[str | None, ...], label: str
) -> None:
    for i, unit in enumerate(units):
        when = E_D - (30 - i) * H
        builder.add("ibm_fez", when, [m("qubit/136", "T1", 50.0 + i, when, unit)], [E_D - i * H])
    s = dense_series(run(builder), "qubit/136", "T1")
    assert s["mixed_units"] is True, label
    assert s["measurements"] == 6
    assert s["cv"] == "undefined: mixed_units"
    assert s["max_min_ratio"] == "undefined: mixed_units"
    assert s["successive_spread_over_mean"] == "undefined: mixed_units"


def test_missing_qubit_and_parameter(builder: StoreBuilder) -> None:
    """Qubit 144 is absent from every document, and no document reports T2."""
    present = FEZ_QUBITS[:4]
    t1_values = {q: [10.0 + 2 * i + j for j in range(5)] for i, q in enumerate(present)}
    for j in range(5):
        when = E_D - (20 - j) * H
        rows = [m(f"qubit/{q}", "T1", t1_values[q][j], when, "us") for q in present]
        builder.add("ibm_fez", when, rows, [E_D - j * H])
    result = run(builder)
    missing = dense_series(result, "qubit/144", "T1")
    assert missing["measurements"] == 0
    assert missing["cv"] == "undefined: too_few_measurements"
    assert missing["unusable_readings"]["missing_row"] == 5  # type: ignore[index]
    t2 = dense_series(result, "qubit/136", "T2")
    assert t2["unusable_readings"]["missing_row"] == 5  # type: ignore[index]
    p1 = prediction(result, "P1")["per_device"]["ibm_fez"]  # type: ignore[index]
    expected = statistics.median(
        statistics.stdev(v) / statistics.mean(v) for v in t1_values.values()
    )
    assert p1["qubits_with_defined_cv"] == 4
    assert p1["median_cv"] == pytest.approx(expected)
    assert p1["mark"] == (SUPPORTED if expected >= 0.10 else NOT_SUPPORTED)


# --- marking rules --------------------------------------------------------------------------


def cvs(*values: float | None) -> list[Stat]:
    return [Stat(v) if v is not None else Stat(None, "too_few_measurements") for v in values]


def test_p1_marking() -> None:
    assert mark_p1(4, cvs(0.5, 0.5, 0.5, 0.5, 0.5))["mark"] == NOT_TESTABLE
    assert mark_p1(5, cvs(0.5, 0.5, None, None, None))["mark"] == NOT_TESTABLE
    assert mark_p1(5, cvs(0.05, 0.10, 0.5, None, None))["mark"] == SUPPORTED
    assert mark_p1(5, cvs(0.05, 0.09, 0.5, 0.01, None))["mark"] == NOT_SUPPORTED


def test_p2_marking() -> None:
    assert mark_p2(4, cvs(5.0, 5.0, 5.0))["mark"] == NOT_TESTABLE
    assert mark_p2(5, cvs(3.0, None, None, None, None))["mark"] == SUPPORTED
    assert mark_p2(5, cvs(2.9, 1.5, 1.1, None, None))["mark"] == NOT_SUPPORTED
    assert mark_p2(5, cvs(2.9, 1.5, None, None, None))["mark"] == NOT_TESTABLE


def pair(tau: float | None, *, available: bool = True, untied: bool = True) -> LagPair:
    stat = Stat(tau) if tau is not None else Stat(None, "all_values_tied")
    return LagPair(available, stat, 5, False, 0, untied)


def inversions(order: Sequence[int]) -> int:
    return sum(1 for i, j in combinations(range(len(order)), 2) if order[i] > order[j])


def test_random_order_probability_by_enumerating_120_permutations() -> None:
    # Without ties, tau-b = (10 - 2 * inversions) / 10 for 5 items, so tau-b < 0.5 exactly
    # when there are at least 3 inversions (at least 3 of 10 pairs discordant).
    orders = list(permutations(range(5)))
    assert len(orders) == 120
    at_most_two = sum(1 for o in orders if inversions(o) <= 2)
    assert at_most_two == 14
    below = len(orders) - at_most_two
    assert below == 106
    assert random_order_below(5, 0.5) == (below, len(orders))


def test_p3_states_the_random_order_probability() -> None:
    stated = mark_p3(5, pair(0.4))["random_order_probability_below_0.5"]
    assert stated == {
        "untied_items": 5,
        "below": 106,
        "orderings": 120,
        "probability": pytest.approx(106 / 120),
    }
    assert mark_p3(5, pair(0.4, untied=False))["random_order_probability_below_0.5"] == (
        "undefined: ties"
    )
    assert mark_p3(5, pair(None, available=False))["random_order_probability_below_0.5"] == (
        "undefined: lookup_missing"
    )


def test_p3_marking() -> None:
    assert mark_p3(4, pair(0.2))["outcome"] == NOT_TESTABLE
    assert mark_p3(5, pair(None, available=False))["outcome"] == NOT_TESTABLE
    assert mark_p3(5, pair(None))["outcome"] == NOT_TESTABLE
    assert mark_p3(5, pair(0.5))["outcome"] == AT_OR_ABOVE
    assert mark_p3(5, pair(0.4))["outcome"] == BELOW


def p4(**overrides: int) -> P4Counts:
    fields = {"documents": 5, "numeric": 25, "nonzero": 0, "dated": 100, "equal": 100}
    fields.update(overrides)
    return P4Counts(
        documents=fields["documents"],
        pairs=25,
        numeric=fields["numeric"],
        nonzero=fields["nonzero"],
        without_numeric_value=Counter(),
        dated=fields["dated"],
        date_equals_stamp=fields["equal"],
        without_dates=0,
    )


def test_p4_marking() -> None:
    assert mark_p4(p4())["mark"] == SUPPORTED
    assert mark_p4(p4(equal=99))["mark"] == SUPPORTED
    assert mark_p4(p4(documents=4))["mark"] == NOT_TESTABLE
    assert mark_p4(p4(numeric=0))["mark"] == NOT_TESTABLE
    assert mark_p4(p4(dated=0, equal=0))["mark"] == NOT_TESTABLE
    assert mark_p4(p4(nonzero=1))["mark"] == NOT_SUPPORTED
    assert mark_p4(p4(equal=98))["mark"] == NOT_SUPPORTED


def test_overall_rules() -> None:
    assert overall_all_devices([SUPPORTED] * 3) == SUPPORTED
    assert overall_all_devices([SUPPORTED, SUPPORTED, NOT_TESTABLE]) == NOT_TESTABLE
    assert overall_all_devices([SUPPORTED, NOT_TESTABLE, NOT_SUPPORTED]) == NOT_SUPPORTED
    assert overall_p3([BELOW, BELOW, AT_OR_ABOVE]) == SUPPORTED
    assert overall_p3([BELOW, AT_OR_ABOVE, AT_OR_ABOVE]) == NOT_SUPPORTED
    assert overall_p3([AT_OR_ABOVE, AT_OR_ABOVE, NOT_TESTABLE]) == NOT_SUPPORTED
    assert overall_p3([BELOW, NOT_TESTABLE, AT_OR_ABOVE]) == NOT_TESTABLE
    assert overall_p3([NOT_TESTABLE] * 3) == NOT_TESTABLE


# --- end to end -----------------------------------------------------------------------------


FEZ_DENSE_FACTORS = (1.0, 1.7, 2.3, 3.1, 4.3)
"""Factor of the dense ibm_fez document at E_D - k h, for k = 0..4."""


def build_experiment(builder: StoreBuilder) -> None:
    """ibm_fez: 5 hourly dense documents at E_D - k h, and sparse documents at G_0..G_6, of which
    G_0 (E_D - 24 h) and G_1 (E_D - 144 h) are also in the dense window. ibm_kingston: 4 dense
    documents. ibm_marrakesh: 5 dense documents with constant T1."""
    for k, f in enumerate(FEZ_DENSE_FACTORS):
        stamp = E_D - k * H - 0.25 * H

        def dense_value(r: str, p: str, i: int, f: float = f) -> float:
            return 0.0131 * (i + 1) * f

        builder.add(
            "ibm_fez",
            stamp,
            full_rows(FEZ_QUBITS, FEZ_PAIRS, dense_value, stamp, stamp),
            [E_D - k * H],
        )
    for k, t in enumerate(sparse_grid(D)[:7]):
        stamp = t - 0.5 * H

        def sparse_value(r: str, p: str, i: int, k: int = k) -> float:
            if k == 6 and p == "readout_error":
                return 0.0117 * (5 - i)  # decreasing across qubits
            return 0.0117 * (i + 1) * (1 + 0.37 * k)

        builder.add(
            "ibm_fez", stamp, full_rows(FEZ_QUBITS, FEZ_PAIRS, sparse_value, stamp, stamp), [t]
        )
    for k in range(4):
        stamp = E_D - k * H - 0.25 * H
        rows = [m(f"qubit/{q}", "T1", 70.3 + k, stamp, "us") for q in KINGSTON_QUBITS]
        builder.add("ibm_kingston", stamp, rows, [E_D - k * H])
    for k in range(5):
        stamp = E_D - k * H - 0.25 * H
        rows = [m(f"qubit/{q}", "T1", 87.65 + q, stamp, "us") for q in MARRAKESH_QUBITS]
        rows += [m(f"gate/rz/{q}", "gate_error", 0.0, stamp) for q in MARRAKESH_QUBITS]
        builder.add("ibm_marrakesh", stamp, rows, [E_D - k * H])


def fez_dense_values(i: int) -> list[float]:
    """Qubit index i's dense T1 (and readout_error) values in date order: G_1, G_0, then the
    hourly documents from oldest (k = 4) to newest (k = 0)."""
    return [0.0117 * (i + 1) * 1.37, 0.0117 * (i + 1)] + [
        0.0131 * (i + 1) * FEZ_DENSE_FACTORS[k] for k in reversed(range(5))
    ]


def test_predictions_end_to_end(builder: StoreBuilder) -> None:
    build_experiment(builder)
    result = run(builder)
    p1 = prediction(result, "P1")
    fez = p1["per_device"]["ibm_fez"]  # type: ignore[index]
    expected_cvs = [
        statistics.stdev(fez_dense_values(i)) / statistics.mean(fez_dense_values(i))
        for i in range(5)
    ]
    assert fez["distinct_documents"] == 7
    assert fez["median_cv"] == pytest.approx(statistics.median(expected_cvs))
    assert fez["mark"] == SUPPORTED
    assert p1["per_device"]["ibm_kingston"]["mark"] == NOT_TESTABLE  # type: ignore[index]
    # Constant T1 over 5 dates: CV 0 on every qubit.
    marrakesh = p1["per_device"]["ibm_marrakesh"]  # type: ignore[index]
    assert marrakesh["median_cv"] == 0.0
    assert marrakesh["mark"] == NOT_SUPPORTED
    assert p1["overall"] == NOT_SUPPORTED

    p2 = prediction(result, "P2")["per_device"]["ibm_fez"]  # type: ignore[index]
    # Every qubit: largest 0.0131 (i + 1) 4.3, smallest 0.0117 (i + 1).
    assert p2["largest_ratio"] == pytest.approx(0.0131 * 4.3 / 0.0117)
    assert p2["qubits_with_ratio_at_least_3"] == 5
    assert p2["mark"] == SUPPORTED

    p3 = prediction(result, "P3")
    fez3 = p3["per_device"]["ibm_fez"]  # type: ignore[index]
    # G_0 increases across qubits, G_6 decreases: all 10 pairs discordant.
    assert fez3["tau_b"] == pytest.approx(-1.0)
    assert fez3["n"] == 5
    assert fez3["outcome"] == BELOW
    assert fez3["same_document"] is False
    assert fez3["distinct_documents_g0_to_g6"] == 7
    assert fez3["random_order_probability_below_0.5"]["probability"] == pytest.approx(106 / 120)
    assert p3["per_device"]["ibm_kingston"]["outcome"] == NOT_TESTABLE  # type: ignore[index]
    assert p3["overall"] == NOT_TESTABLE
    reference = p3["random_order_reference"]
    assert reference["below"] == 106  # type: ignore[index]
    assert reference["orderings"] == 120  # type: ignore[index]

    p4 = prediction(result, "P4")["per_device"]
    assert p4["ibm_fez"]["mark"] == SUPPORTED  # type: ignore[index]
    # 5 hourly + 7 sparse documents, all distinct.
    assert p4["ibm_fez"]["distinct_documents"] == 12  # type: ignore[index]
    assert p4["ibm_fez"]["document_qubit_pairs"] == 60  # type: ignore[index]
    assert p4["ibm_fez"]["fraction_date_equals_stamp"] == 1.0  # type: ignore[index]
    assert p4["ibm_marrakesh"]["mark"] == SUPPORTED  # type: ignore[index]
    assert p4["ibm_kingston"]["mark"] == NOT_TESTABLE  # type: ignore[index]
    assert prediction(result, "P4")["overall"] == NOT_TESTABLE

    lag = device(result)["sparse"]["lag_profile"]
    assert lag["readout_error"]["G_1"]["tau_b"] == pytest.approx(1.0)  # type: ignore[index]
    assert lag["readout_error"]["G_72"]["tau_b"] == "undefined: lookup_missing"  # type: ignore[index]


# --- the runner -----------------------------------------------------------------------------


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_numbers(node: object) -> list[float]:
    """Every number anywhere in a parsed JSON document."""
    if isinstance(node, bool):
        return []
    if isinstance(node, int | float):
        return [float(node)]
    if isinstance(node, dict):
        return [x for v in node.values() for x in json_numbers(v)]
    if isinstance(node, list):
        return [x for v in node for x in json_numbers(v)]
    return []


def clean_git() -> GitProvenance:
    return GitProvenance(commit="a" * 40, branch="exp/test", dirty=False)


def test_runner_leaves_the_store_byte_identical_and_reports_no_values(
    builder: StoreBuilder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    build_experiment(builder)
    builder.close()
    before_bytes = builder.path.read_bytes()
    before = sha256(builder.path)
    files_before = sorted(p.name for p in builder.path.parent.iterdir())
    out = tmp_path / "out"
    monkeypatch.setattr(run_analysis, "git_state", clean_git)
    code = run_analysis.main(
        ["--store", str(builder.path), "--collection-date", D.isoformat(), "--out", str(out)]
    )
    assert code == 0
    assert builder.path.read_bytes() == before_bytes
    assert sorted(p.name for p in builder.path.parent.iterdir() if p.name != "out") == (
        files_before
    )
    result = json.loads((out / "results.json").read_text())
    assert result["provenance"]["store_sha256_before"] == before
    assert result["provenance"]["store_sha256_after"] == before
    assert result["provenance"]["store_unchanged"] is True
    assert result["provenance"]["git_dirty"] is False
    stored = {v for v in builder.values if v != 0.0}
    assert stored
    assert not stored & set(json_numbers(result))
    cells = {
        cell.strip()
        for line in (out / "results.md").read_text().splitlines()
        if line.startswith("|")
        for cell in line.strip("|").split("|")
    }
    assert not {f"{v:.4g}" for v in stored} & cells
    assert "106/120 = 0.8833" in (out / "results.md").read_text()
    # A second run refuses to overwrite.
    assert (
        run_analysis.main(
            ["--store", str(builder.path), "--collection-date", D.isoformat(), "--out", str(out)]
        )
        == 2
    )


@pytest.mark.parametrize(
    "git",
    [
        GitProvenance(commit="a" * 40, branch="x", dirty=True),
        GitProvenance(commit=None, branch=None, dirty=None),
    ],
)
def test_runner_refuses_a_dirty_or_unknown_tree(
    builder: StoreBuilder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, git: GitProvenance
) -> None:
    builder.add("ibm_fez", E_D - H, [], [E_D])
    builder.close()
    out = tmp_path / "out"
    monkeypatch.setattr(run_analysis, "git_state", lambda: git)
    code = run_analysis.main(
        ["--store", str(builder.path), "--collection-date", D.isoformat(), "--out", str(out)]
    )
    assert code == 2
    assert not out.exists()
