"""Fake-backend run calibration against a live snapshot (M1.4b, ADR 0007), fully offline.

The baseline is a seeded GHZ-star run on ``fake_fez``, executed once per test session into a
temporary store. The candidate is the committed ``ibm_fez`` capture, or a deterministic edit
of it with its content hash recomputed. No live client is constructed and no network is used.
"""

import json
import re
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import cache
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from qci.adapters.qiskit_ibm.calibration import (
    ERROR_PARAMETERS,
    FAKE_DEVICE_SOURCES,
    IbmPropertiesCalibrationReader,
    extract_measurements,
    run_snapshot_comparison_support,
    snapshot_comparison_support,
)
from qci.cli.app import app
from qci.cli.render_run_snapshot_compare import render_run_snapshot_comparison
from qci.compare.footprint import footprint_for_run
from qci.compare.hardware import SnapshotFields, compare_calibration
from qci.compare.run_snapshot import LIMITATIONS, compare_run_to_snapshot
from qci.core.hashing import hash_json
from qci.core.ports import RunSnapshotComparisonSupport
from qci.domain.backend import SnapshotSource
from qci.domain.comparison import ComparisonStatus, ParameterComparison, ResourceKind
from qci.domain.metric import EvidenceKind
from qci.domain.run import Run, RunStatus
from qci.domain.snapshot import (
    CalibrationSnapshot,
    RunSnapshotComparison,
    SnapshotCapture,
    SnapshotFixture,
)
from qci.storage.snapshots import SqliteSnapshotRepository
from qci.storage.sqlite import SqliteRunRepository

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "snapshots" / "ibm_fez.json"
GHZ_STAR = ROOT / "examples" / "ghz_star.py"
SUPPORT = {"qiskit_ibm": run_snapshot_comparison_support()}
MAPPING_NOTE = (
    "fake_fez is the fake built from ibm_fez calibration (qiskit_ibm FAKE_DEVICE_SOURCES)"
)
FORBIDDEN = re.compile(
    r"better|worse|regress|improv|degrad|\bpass|fail|significan|verdict|caus|stale|outdated|"
    r"accurate|realistic|adequate",
    re.IGNORECASE,
)

Edit = Callable[[dict[str, Any]], None]


# --- inputs ----------------------------------------------------------------------------------


@cache
def fake_fez_run() -> Run:
    """A seeded GHZ-star run on fake_fez, executed once and stored in a temporary store."""
    from qci.adapters.qiskit_ibm import QiskitIbmAdapter
    from qci.domain.circuit import CompileConfig
    from qci.domain.execution import ExecutionConfig
    from qci.services.run_service import RunRequest, RunService

    with tempfile.TemporaryDirectory() as tmp:
        repository = SqliteRunRepository(Path(tmp) / "qci.db")
        try:
            outcome = RunService(QiskitIbmAdapter(), repository).run(
                RunRequest(
                    workload_path=GHZ_STAR,
                    backend_name="fake_fez",
                    entrypoint="build",
                    compile_config=CompileConfig(optimization_level=2, seed_transpiler=7),
                    execution_config=ExecutionConfig(shots=1000, seed_simulator=7),
                    tags={},
                )
            )
            run = repository.get(outcome.run_id)
        finally:
            repository.close()
    assert run.status is RunStatus.SUCCEEDED
    return run


def run_with(
    *edits: Edit, config: Edit | None = None, backend: dict[str, Any] | None = None, **fields: Any
) -> Run:
    """The session run with edits to its stored properties or configuration, revalidated."""
    data = fake_fez_run().model_dump(mode="json")
    raw = data["backend_snapshot"]["provider_raw"]
    for edit in edits:
        edit(raw["properties"])
    if config is not None:
        config(raw["configuration"])
    if backend:
        data["backend"].update(backend)
    data.update(fields)
    return Run.model_validate(data)


@cache
def _fixture() -> SnapshotFixture:
    return SnapshotFixture.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


def live(*edits: Edit, config: Edit | None = None, **fields: Any) -> CalibrationSnapshot:
    """The committed ibm_fez capture, optionally edited, with its content hash recomputed."""
    base = _fixture().snapshot
    raw: dict[str, Any] = json.loads(json.dumps(base.provider_raw))
    for edit in edits:
        edit(raw["properties"])
    if config is not None:
        config(raw["configuration"])
    data = {**base.model_dump(), "snapshot_id": "LIVE", "provider_raw": raw, **fields}
    data["content_hash"] = hash_json(
        {
            "provider": data["provider"],
            "backend_name": data["backend_name"],
            "capture_options": data["capture_options"],
            "provider_raw": raw,
        }
    )
    return CalibrationSnapshot.model_validate(data)


def compare(
    run: Run | None = None,
    snapshot: CalibrationSnapshot | None = None,
    support: dict[str, RunSnapshotComparisonSupport] = SUPPORT,
) -> RunSnapshotComparison:
    return compare_run_to_snapshot(run or fake_fez_run(), snapshot or live(), support.get)


def _qubit(properties: dict[str, Any], qubit: int, name: str) -> dict[str, Any]:
    (entry,) = [e for e in properties["qubits"][qubit] if e["name"] == name]
    assert isinstance(entry, dict)
    return entry


def _gate(properties: dict[str, Any], gate: str, qubits: list[int], name: str) -> dict[str, Any]:
    (g,) = [g for g in properties["gates"] if g["gate"] == gate and g["qubits"] == qubits]
    (entry,) = [e for e in g["parameters"] if e["name"] == name]
    assert isinstance(entry, dict)
    return entry


def _drop_qubit_parameter(qubit: int, name: str) -> Edit:
    def edit(p: dict[str, Any]) -> None:
        p["qubits"][qubit] = [e for e in p["qubits"][qubit] if e["name"] != name]

    return edit


def footprint_qubits() -> list[int]:
    return list(footprint_for_run(fake_fez_run()).qubits)


def first_cz() -> list[int]:
    fp = footprint_for_run(fake_fez_run())
    return list(next(op.qubits for op in fp.operations if op.name == "cz"))


def params(c: RunSnapshotComparison, status: str) -> list[ParameterComparison]:
    return [p for p in c.hardware.shared_resource_parameters if p.status == status]


def assert_no_parameters(c: RunSnapshotComparison) -> None:
    assert c.hardware.shared_resource_parameters == []
    assert c.measurement_dates == []
    assert c.parameters_on_one_side == [] and c.unit_differences == []
    assert c.error_values_at_one == []
    assert c.live_minus_fake_min is None and c.live_minus_fake_max is None
    assert c.status is c.hardware.status


def reason(c: RunSnapshotComparison) -> str:
    assert c.hardware.reason is not None
    return c.hardware.reason


# --- the explicit fake-to-device mapping --------------------------------------------------------


def test_mapping_has_exactly_three_entries() -> None:
    assert dict(FAKE_DEVICE_SOURCES) == {
        "fake_fez": "ibm_fez",
        "fake_kingston": "ibm_kingston",
        "fake_marrakesh": "ibm_marrakesh",
    }


def _recorded(fake: Any) -> str:
    name = fake.properties().to_dict()["backend_name"]
    assert isinstance(name, str)
    return name


def test_fake_fez_payload_records_ibm_fez() -> None:
    from qiskit_ibm_runtime.fake_provider import FakeFez

    fake = FakeFez()
    assert fake.name == "fake_fez"
    assert _recorded(fake) == FAKE_DEVICE_SOURCES["fake_fez"] == "ibm_fez"


def test_fake_kingston_payload_records_ibm_kingston() -> None:
    from qiskit_ibm_runtime.fake_provider import FakeKingston

    fake = FakeKingston()
    assert fake.name == "fake_kingston"
    assert _recorded(fake) == FAKE_DEVICE_SOURCES["fake_kingston"] == "ibm_kingston"


def test_fake_marrakesh_payload_records_ibm_marrakesh() -> None:
    from qiskit_ibm_runtime.fake_provider import FakeMarrakesh

    fake = FakeMarrakesh()
    assert fake.name == "fake_marrakesh"
    assert _recorded(fake) == FAKE_DEVICE_SOURCES["fake_marrakesh"] == "ibm_marrakesh"


def test_unlisted_fakes_have_no_device() -> None:
    devices = SUPPORT["qiskit_ibm"].devices
    for name in ("fake_torino", "fake_sherbrooke", "fake_bogota", "ibm_fez", "fez"):
        assert devices.device_for(name) is None
    assert devices.device_for("fake_fez") == "ibm_fez"


def test_recorded_device_reads_the_run_properties() -> None:
    snapshot = fake_fez_run().backend_snapshot
    assert snapshot is not None
    assert SUPPORT["qiskit_ibm"].devices.recorded_device(snapshot) == ("ibm_fez", "1.2.8")


# --- exits, in ADR 0007 section 6 order -------------------------------------------------------


def test_exit_1_run_without_backend_snapshot_is_unavailable() -> None:
    error = {"stage": "snapshot", "error_type": "RuntimeError", "message": "x"}
    for missing in ({"backend_snapshot": None}, {"backend": None, "backend_snapshot": None}):
        run = run_with(
            status="failed", error=error, compilation=None, execution=None, result=None, **missing
        )
        c = compare(run)
        assert c.status is ComparisonStatus.UNAVAILABLE
        assert reason(c) == f"run {run.run_id} has no backend or no backend snapshot"
        assert c.device_mapping is None
        assert_no_parameters(c)


def test_exit_2_run_snapshot_source_must_be_static_fake() -> None:
    for source in ("live_calibration", "simulator_ideal"):
        data = fake_fez_run().model_dump(mode="json")
        data["backend_snapshot"]["source"] = source
        c = compare(Run.model_validate(data))
        assert c.status is ComparisonStatus.NOT_COMPARABLE
        assert reason(c) == (
            f"run snapshot source is {source}, not static_fake; this comparison sets a fake "
            "backend's frozen calibration against a live snapshot"
        )
        assert_no_parameters(c)


def test_exit_3_snapshot_source_must_be_live_calibration() -> None:
    c = compare(snapshot=live(source=SnapshotSource.STATIC_FAKE))
    assert c.status is ComparisonStatus.NOT_COMPARABLE
    assert reason(c) == "snapshot LIVE source is static_fake, not live_calibration"
    assert_no_parameters(c)


def test_exit_4_providers_must_match() -> None:
    c = compare(run_with(backend={"provider": "other"}))
    assert c.status is ComparisonStatus.NOT_COMPARABLE
    assert reason(c) == (
        "run provider other differs from snapshot provider qiskit_ibm; calibration from "
        "different providers is not compared"
    )
    assert_no_parameters(c)


def test_exit_5_provider_without_support_is_unavailable() -> None:
    c = compare(support={})
    assert c.status is ComparisonStatus.UNAVAILABLE
    assert reason(c) == "no run-to-snapshot comparison support for provider 'qiskit_ibm'"
    assert c.error_parameters == []
    assert_no_parameters(c)


def test_exit_6_fake_not_in_the_mapping() -> None:
    c = compare(run_with(backend={"name": "fake_torino"}))
    assert c.status is ComparisonStatus.NOT_COMPARABLE
    assert reason(c) == (
        "fake_torino has no entry in qiskit_ibm FAKE_DEVICE_SOURCES; no device name is derived "
        "from a fake's name"
    )
    assert c.device_mapping is None
    assert MAPPING_NOTE not in reason(c)
    assert_no_parameters(c)


def test_exit_7_snapshot_backend_must_be_the_mapped_device() -> None:
    c = compare(snapshot=live(backend_name="ibm_torino"))
    assert c.status is ComparisonStatus.NOT_COMPARABLE
    assert reason(c) == (
        f"{MAPPING_NOTE}; snapshot LIVE is of ibm_torino, not the mapped device ibm_fez; "
        "calibration of different devices is not compared"
    )
    assert c.device_mapping is not None and c.device_mapping.device == "ibm_fez"
    assert_no_parameters(c)


def test_exit_8_recorded_device_must_be_the_mapped_device() -> None:
    def other(p: dict[str, Any]) -> None:
        p["backend_name"] = "ibm_torino"

    def absent(p: dict[str, Any]) -> None:
        del p["backend_name"]

    for edit, recorded in ((other, "ibm_torino"), (absent, "no device")):
        c = compare(run_with(edit))
        assert c.status is ComparisonStatus.NOT_COMPARABLE
        assert reason(c) == (
            f"{MAPPING_NOTE}; the run's recorded calibration names {recorded}, not the mapped "
            "device ibm_fez"
        )
        assert_no_parameters(c)


def test_exit_9_footprint_unavailable_or_dynamic() -> None:
    error = {"stage": "compile", "error_type": "RuntimeError", "message": "x"}
    failed = run_with(status="failed", error=error, compilation=None, execution=None, result=None)
    c = compare(failed)
    assert c.status is ComparisonStatus.UNAVAILABLE
    assert reason(c) == (
        f"{MAPPING_NOTE}; footprint of run {failed.run_id} unavailable: run has no compilation "
        "record"
    )
    assert_no_parameters(c)

    data = fake_fez_run().model_dump(mode="json")
    data["compilation"]["output"]["qasm3"] = (
        "OPENQASM 3.0;\nbit[1] c;\nc[0] = measure $0;\nif (c[0]) {\n  x $1;\n}\n"
    )
    c = compare(Run.model_validate(data))
    assert c.status is ComparisonStatus.NOT_COMPARABLE
    assert reason(c).startswith(f"{MAPPING_NOTE}; footprint of run {data['run_id']} ")
    assert_no_parameters(c)


def test_exit_10_missing_footprint_resources_are_listed_per_side() -> None:
    qubits = footprint_qubits()
    cz = first_cz()
    low = min(qubits)

    def shrink(config: dict[str, Any]) -> None:
        config["n_qubits"] = low + 1  # every footprint qubit above `low` is missing

    def drop_pair(config: dict[str, Any]) -> None:
        for gate in config["gates"]:
            if gate["name"] == "cz":
                gate["coupling_map"] = [e for e in gate["coupling_map"] if e != cz]

    c = compare(run_with(config=shrink), live(config=drop_pair))
    assert c.status is ComparisonStatus.NOT_COMPARABLE
    assert_no_parameters(c)
    above = [q for q in qubits if q > low]
    text = reason(c)
    assert text.startswith(f"{MAPPING_NOTE}; footprint resources missing from the baseline ")
    baseline_part, candidate_part = text.split("; footprint resources missing from the ")[1:]
    assert baseline_part.startswith(f"baseline (run {fake_fez_run().run_id} on fake_fez): ")
    for q in above:
        assert f"qubit {q}" in baseline_part
        assert f"measure({q})" in baseline_part
    assert candidate_part == f"candidate (snapshot LIVE of ibm_fez): cz({cz[0]},{cz[1]})"


# --- the calibration comparison ----------------------------------------------------------------


def test_calibration_is_compare_calibration_with_matching_units() -> None:
    run, snapshot = fake_fez_run(), live()
    assert run.backend_snapshot is not None
    fp = footprint_for_run(run)
    base = snapshot_comparison_support()
    common: SnapshotFields = {
        "global_snapshot_changed": True,
        "baseline_snapshot_source": SnapshotSource.STATIC_FAKE,
        "candidate_snapshot_source": SnapshotSource.LIVE_CALIBRATION,
    }
    expected = compare_calibration(
        run.backend_snapshot,
        base.resources.backend_snapshot(snapshot),
        fp,
        fp,
        IbmPropertiesCalibrationReader(),
        [MAPPING_NOTE],
        common,
        require_matching_units=True,
    )
    c = compare(run, snapshot)
    assert c.hardware == expected
    assert c.footprint == fp
    assert c.status is c.hardware.status is ComparisonStatus.CHANGED
    assert c.hardware.relevant_hardware_changed is True
    assert c.hardware.global_snapshot_changed is True
    assert c.device_mapping is not None
    assert (c.device_mapping.fake, c.device_mapping.device) == ("fake_fez", "ibm_fez")
    assert c.device_mapping.source == "qiskit_ibm FAKE_DEVICE_SOURCES"


def test_changed_values_have_live_minus_fake_deltas() -> None:
    changed = params(compare(), "changed")
    assert changed
    for p in changed:
        if isinstance(p.baseline, float) and isinstance(p.candidate, float):
            assert p.delta == p.candidate - p.baseline


def test_init_error_is_reported_by_the_live_side_only() -> None:
    c = compare()
    on_one_side = {
        (e.side, e.resource_kind, e.qubits, e.parameter) for e in c.parameters_on_one_side
    }
    for q in footprint_qubits():
        assert ("candidate", ResourceKind.QUBIT, (q,), "init_error") in on_one_side
        (p,) = [
            x
            for x in c.hardware.shared_resource_parameters
            if x.qubits == (q,) and x.parameter == "init_error"
        ]
        assert p.status == "unavailable" and p.baseline is None and p.delta is None
        assert p.candidate is not None
    assert {e.parameter for e in c.parameters_on_one_side} == {"init_error"}
    assert all(e.operation is None for e in c.parameters_on_one_side)


def test_parameter_reported_by_one_side_names_the_reporting_side() -> None:
    q = footprint_qubits()[0]
    # Removed from the live side: the fake side alone reports it.
    c = compare(snapshot=live(_drop_qubit_parameter(q, "T2")))
    entries = [e for e in c.parameters_on_one_side if e.parameter == "T2"]
    assert [(e.side, e.qubits) for e in entries] == [("baseline", (q,))]
    # Removed from the fake side: the live side alone reports it.
    c = compare(run_with(_drop_qubit_parameter(q, "T2")))
    entries = [e for e in c.parameters_on_one_side if e.parameter == "T2"]
    assert [(e.side, e.qubits) for e in entries] == [("candidate", (q,))]
    (p,) = [x for x in params(c, "unavailable") if x.parameter == "T2"]
    assert p.baseline is None and p.candidate is not None


def test_unrepresentable_value_is_unavailable_and_not_on_one_side() -> None:
    q = footprint_qubits()[0]

    def nan(p: dict[str, Any]) -> None:
        _qubit(p, q, "T1")["value"] = {"$float": "nan"}

    c = compare(snapshot=live(nan))
    (p,) = [x for x in params(c, "unavailable") if x.parameter == "T1"]
    assert p.qubits == (q,) and p.candidate is None and p.baseline is not None
    assert not [e for e in c.parameters_on_one_side if e.parameter == "T1"]


def test_unit_change_is_not_comparable_and_listed() -> None:
    q = footprint_qubits()[0]
    for unit, shown in (("ms", "ms"), ("", None)):

        def edit(p: dict[str, Any], unit: str = unit) -> None:
            _qubit(p, q, "T1")["unit"] = unit

        c = compare(snapshot=live(edit))
        (p,) = params(c, "not_comparable")
        assert (p.qubits, p.parameter, p.delta, p.unit) == ((q,), "T1", None, None)
        assert p.baseline == _qubit(_fake_properties(), q, "T1")["value"]
        assert p.candidate == _qubit(_live_properties(), q, "T1")["value"]
        assert (
            f"qubit {q} T1: units differ (baseline us, candidate {shown}); not compared"
            in reason(c)
        )
        (u,) = c.unit_differences
        assert (u.resource_kind, u.qubits, u.parameter) == (ResourceKind.QUBIT, (q,), "T1")
        assert (u.baseline_unit, u.candidate_unit) == ("us", shown)


def _fake_properties() -> dict[str, Any]:
    snapshot = fake_fez_run().backend_snapshot
    assert snapshot is not None
    properties = snapshot.provider_raw["properties"]
    assert isinstance(properties, dict)
    return properties


def _live_properties() -> dict[str, Any]:
    properties = live().provider_raw["properties"]
    assert isinstance(properties, dict)
    return properties


def test_error_values_of_one_are_listed_per_side() -> None:
    q = footprint_qubits()[0]
    cz = first_cz()

    def fake_edit(p: dict[str, Any]) -> None:
        _gate(p, "cz", cz, "gate_error")["value"] = 1
        _qubit(p, q, "prob_meas0_prep1")["value"] = 1  # not an error-type parameter

    def live_edit(p: dict[str, Any]) -> None:
        _qubit(p, q, "readout_error")["value"] = 1
        _gate(p, "cz", cz, "gate_length")["value"] = 1  # not an error-type parameter

    c = compare(run_with(fake_edit), live(live_edit))
    assert c.error_parameters == list(ERROR_PARAMETERS)
    found = [(e.side, e.operation, e.qubits, e.parameter, e.value) for e in c.error_values_at_one]
    assert found == [
        ("baseline", "cz", tuple(cz), "gate_error", 1.0),
        ("candidate", None, (q,), "readout_error", 1.0),
    ]
    assert compare().error_values_at_one == []


# --- measurement dates -------------------------------------------------------------------------


def test_measurement_dates_one_per_compared_parameter() -> None:
    c = compare()
    hw = c.hardware.shared_resource_parameters
    assert len(c.measurement_dates) == len(hw)
    by_key = {(p.resource_kind, p.operation, p.qubits, p.parameter): p for p in hw}
    differences = []
    for d in c.measurement_dates:
        p = by_key[(d.resource_kind, d.operation, d.qubits, d.parameter)]
        assert d.baseline_measured_at == p.baseline_calibrated_at
        assert d.candidate_measured_at == p.candidate_calibrated_at
        if d.baseline_measured_at is None or d.candidate_measured_at is None:
            assert d.live_minus_fake is None
            continue
        m = d.live_minus_fake
        assert m is not None
        assert (m.name, m.unit, m.kind) == ("live_minus_fake", "s", EvidenceKind.CALCULATED)
        assert (m.method, m.method_version) == ("live measured_at minus fake measured_at", "1")
        assert m.value == (d.candidate_measured_at - d.baseline_measured_at).total_seconds()
        differences.append(m.value)
    init = [d for d in c.measurement_dates if d.parameter == "init_error"]
    assert init and all(d.live_minus_fake is None for d in init)
    assert c.live_minus_fake_min is not None and c.live_minus_fake_max is not None
    assert c.live_minus_fake_min.value == min(differences)
    assert c.live_minus_fake_max.value == max(differences)
    for m in (c.live_minus_fake_min, c.live_minus_fake_max):
        assert m.kind is EvidenceKind.CALCULATED and m.unit == "s"


def test_missing_date_gives_null_difference_never_zero() -> None:
    q = footprint_qubits()[0]

    def undated(p: dict[str, Any]) -> None:
        del _qubit(p, q, "T1")["date"]

    c = compare(snapshot=live(undated))
    (d,) = [x for x in c.measurement_dates if x.qubits == (q,) and x.parameter == "T1"]
    assert d.candidate_measured_at is None and d.baseline_measured_at is not None
    assert d.live_minus_fake is None


def test_calibrated_at_difference() -> None:
    c = compare()
    run_snapshot = fake_fez_run().backend_snapshot
    assert run_snapshot is not None and run_snapshot.calibrated_at is not None
    snapshot = live()
    assert snapshot.calibrated_at is not None
    m = c.calibrated_at_difference
    assert m is not None
    assert m.value == (snapshot.calibrated_at - run_snapshot.calibrated_at).total_seconds()
    assert (m.name, m.unit, m.kind) == ("calibrated_at_difference", "s", EvidenceKind.CALCULATED)
    assert compare(snapshot=live(calibrated_at=None)).calibrated_at_difference is None


def test_no_parameter_with_both_dates_gives_null_range() -> None:
    def undated(p: dict[str, Any]) -> None:
        for entries in p["qubits"]:
            for e in entries:
                e.pop("date", None)
        for g in p["gates"]:
            for e in g["parameters"]:
                e.pop("date", None)

    c = compare(snapshot=live(undated))
    assert c.measurement_dates
    assert all(d.live_minus_fake is None for d in c.measurement_dates)
    assert c.live_minus_fake_min is None and c.live_minus_fake_max is None


def test_run_captured_at_is_never_used() -> None:
    data = fake_fez_run().model_dump(mode="json")
    data["backend_snapshot"]["captured_at"] = "2030-01-01T00:00:00Z"
    moved = Run.model_validate(data)
    assert compare(moved).model_dump_json() == compare().model_dump_json()


# --- output shape, metadata, ordering, wording --------------------------------------------------


def test_output_fields_cover_only_the_footprint() -> None:
    data = json.loads(compare().model_dump_json())
    assert set(data) == {
        "schema_version",
        "run_snapshot_comparison_id",
        "method_version",
        "status",
        "baseline",
        "candidate",
        "device_mapping",
        "footprint",
        "hardware",
        "parameters_on_one_side",
        "unit_differences",
        "error_parameters",
        "error_values_at_one",
        "calibrated_at_difference",
        "measurement_dates",
        "live_minus_fake_min",
        "live_minus_fake_max",
        "limitations",
    }


def test_output_carries_versions_and_provenance() -> None:
    c = compare()
    run = fake_fez_run()
    assert run.backend_snapshot is not None
    b, k = c.baseline, c.candidate
    assert (b.run_id, b.provider, b.backend_name) == (run.run_id, "qiskit_ibm", "fake_fez")
    assert b.backend_version == "1.2.8" and b.snapshot_source is SnapshotSource.STATIC_FAKE
    assert b.calibrated_at == run.backend_snapshot.calibrated_at
    assert (b.recorded_device, b.recorded_device_version) == ("ibm_fez", "1.2.8")
    assert b.qiskit_ibm_runtime_version == run.provenance.environment.packages["qiskit-ibm-runtime"]
    snapshot = live()
    assert (k.snapshot_id, k.provider, k.backend_name) == ("LIVE", "qiskit_ibm", "ibm_fez")
    assert k.backend_version == "1.3.37" and k.source is SnapshotSource.LIVE_CALIBRATION
    assert (k.content_hash, k.captured_at, k.calibrated_at) == (
        snapshot.content_hash,
        snapshot.captured_at,
        snapshot.calibrated_at,
    )
    assert c.method_version == "qci.compare.run_snapshot.1"


def test_limitations_are_exactly_the_adr_lines() -> None:
    assert compare().limitations == LIMITATIONS
    assert compare(support={}).limitations == LIMITATIONS
    assert len(LIMITATIONS) == 13
    assert LIMITATIONS[5] == (
        "This compares calibration data: the values the fake backend was built from and the "
        "live device's reported values. It does not compare the noise model a simulator "
        "constructs from that data; a simulator may use only some of these parameters, in its "
        "own way."
    )
    assert LIMITATIONS[0].startswith("This comparison reports what differs between the")
    assert LIMITATIONS[-1] == "These comparisons are never stored."


def test_comparison_id_is_deterministic() -> None:
    a, b = compare(), compare()
    assert a.run_snapshot_comparison_id == b.run_snapshot_comparison_id
    assert a.run_snapshot_comparison_id == hash_json(
        {
            "method_version": "qci.compare.run_snapshot.1",
            "run_id": fake_fez_run().run_id,
            "snapshot_id": "LIVE",
        }
    )
    assert compare(snapshot=live(snapshot_id="OTHER")).run_snapshot_comparison_id != (
        a.run_snapshot_comparison_id
    )


def _key(kind: ResourceKind, operation: str | None, qubits: tuple[int, ...], name: str) -> Any:
    return (kind.value, operation or "", qubits, name)


def test_lists_are_sorted() -> None:
    q0, q1 = footprint_qubits()[:2]
    cz = first_cz()

    def live_edit(p: dict[str, Any]) -> None:
        _qubit(p, q1, "T1")["unit"] = "ms"
        _qubit(p, q0, "T2")["unit"] = "ms"
        _qubit(p, q0, "readout_error")["value"] = 1

    def fake_edit(p: dict[str, Any]) -> None:
        _gate(p, "cz", cz, "gate_error")["value"] = 1
        _qubit(p, q1, "readout_error")["value"] = 1

    c = compare(run_with(fake_edit), live(live_edit))
    for items in (c.measurement_dates, c.unit_differences):
        keys = [_key(x.resource_kind, x.operation, x.qubits, x.parameter) for x in items]
        assert keys == sorted(keys) and len(keys) > 1
    keys = [
        (x.side, *_key(x.resource_kind, x.operation, x.qubits, x.parameter))
        for x in c.parameters_on_one_side
    ]
    assert keys == sorted(keys) and len(keys) > 1
    keys = [
        (x.side, *_key(x.resource_kind, x.operation, x.qubits, x.parameter))
        for x in c.error_values_at_one
    ]
    assert keys == sorted(keys) and len(keys) == 3


def _every_exit() -> list[RunSnapshotComparison]:
    error = {"stage": "snapshot", "error_type": "RuntimeError", "message": "x"}

    def other(p: dict[str, Any]) -> None:
        p["backend_name"] = "ibm_torino"

    data = fake_fez_run().model_dump(mode="json")
    data["backend_snapshot"]["source"] = "live_calibration"
    return [
        compare(),
        compare(
            run_with(
                status="failed",
                error=error,
                backend_snapshot=None,
                compilation=None,
                execution=None,
                result=None,
            )
        ),
        compare(Run.model_validate(data)),
        compare(snapshot=live(source=SnapshotSource.STATIC_FAKE)),
        compare(run_with(backend={"provider": "other"})),
        compare(support={}),
        compare(run_with(backend={"name": "fake_torino"})),
        compare(snapshot=live(backend_name="ibm_torino")),
        compare(run_with(other)),
        compare(
            run_with(compilation=None, status="failed", error=error, execution=None, result=None)
        ),
        compare(run_with(config=lambda cfg: cfg.update(n_qubits=1))),
        compare(snapshot=live(lambda p: _qubit(p, footprint_qubits()[0], "T1").update(unit="ms"))),
    ]


def test_rendered_and_json_output_use_neutral_wording() -> None:
    for c in _every_exit():
        for text in (c.model_dump_json(indent=2), render_run_snapshot_comparison(c)):
            assert FORBIDDEN.search(text) is None, FORBIDDEN.search(text)


def test_text_shows_a_unit_on_every_value_line() -> None:
    q = footprint_qubits()[0]

    def edit(p: dict[str, Any]) -> None:
        _qubit(p, q, "T1")["unit"] = "ms"
        _qubit(p, q, "readout_error")["value"] = 1

    text = render_run_snapshot_comparison(compare(snapshot=live(edit)))
    lines = text.splitlines()
    value_lines = [
        line
        for line in lines
        if line.startswith("    ") and (" -> " in line or " = " in line or "difference" in line)
    ]
    assert len(value_lines) > 100
    unit = re.compile(r"\[(us|ns|s|ms|GHz|no unit)\]")
    for line in value_lines:
        assert unit.search(line), line
    assert "difference [s]: unavailable" in text  # init_error has no fake-side date
    assert "[ms]" in text and "[us]" in text
    assert f"    qubit {q} T1: " in text
    assert "(units differ; not compared)" in text
    assert "    candidate qubit" in text  # one-side and error sections
    assert MAPPING_NOTE in text
    assert "live minus fake" in text


def test_text_sections() -> None:
    text = render_run_snapshot_comparison(compare())
    for heading in (
        "Calibration (footprint-scoped): changed",
        "Parameters reported by one side only: 5",
        "Unit differences: 0",
        "Error-type parameters equal to 1 (gate_error, readout_error, init_error): 0",
        "Measurement dates (fake -> live):",
        "Limitations:",
    ):
        assert heading in text, heading
    for line in LIMITATIONS:
        assert f"  - {line}" in text


# --- CLI: read-only, deterministic, unknown IDs -------------------------------------------------


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "store"
    monkeypatch.setenv("QCI_HOME", str(home))
    home.mkdir()
    snapshots = SqliteSnapshotRepository(home / "qci.db")
    runs = SqliteRunRepository(home / "qci.db")
    try:
        snap = live()
        snapshots.save(
            snap,
            extract_measurements(snap.provider_raw["properties"]),
            SnapshotCapture(capture_id="CAP", snapshot_id="LIVE", captured_at=snap.captured_at),
        )
        runs.save(fake_fez_run())
    finally:
        snapshots.close()
        runs.close()
    return home


def _invoke(*args: str) -> str:
    result = CliRunner().invoke(app, ["snapshot", "compare-run", *args])
    assert result.exit_code == 0, result.output
    return result.stdout


def test_cli_json_is_deterministic_and_nothing_is_persisted(store: Path) -> None:
    db = store / "qci.db"
    before = db.read_bytes()
    run_id = fake_fez_run().run_id
    first = _invoke(run_id, "LIVE", "--json")
    second = _invoke(run_id, "LIVE", "--json")
    text = _invoke(run_id, "LIVE")
    assert first == second
    assert db.read_bytes() == before
    assert sorted(p.name for p in store.iterdir()) == ["qci.db"]
    c = RunSnapshotComparison.model_validate_json(first)
    assert c == compare()
    assert text.rstrip("\n") == render_run_snapshot_comparison(c)
    assert FORBIDDEN.search(first) is None and FORBIDDEN.search(text) is None


def test_cli_unknown_ids_exit_1(store: Path) -> None:
    run_id = fake_fez_run().run_id
    before = (store / "qci.db").read_bytes()
    for args in (("NOPE", "LIVE"), (run_id, "NOPE")):
        result = CliRunner().invoke(app, ["snapshot", "compare-run", *args])
        assert result.exit_code == 1
        assert "error:" in result.stderr
    assert (store / "qci.db").read_bytes() == before


def test_cli_never_creates_a_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "absent"
    monkeypatch.setenv("QCI_HOME", str(home))
    result = CliRunner().invoke(app, ["snapshot", "compare-run", "RUN", "SNAP"])
    assert result.exit_code == 1
    assert not home.exists()


def test_fake_and_live_dates_are_far_apart_in_the_fixture() -> None:
    """Sanity: the fixture is a later capture than the frozen fake calibration."""
    c = compare()
    assert c.live_minus_fake_min is not None
    assert c.live_minus_fake_min.value > timedelta(days=365).total_seconds()
    assert c.baseline.calibrated_at is not None
    assert c.baseline.calibrated_at < datetime(2026, 1, 1, tzinfo=UTC)
