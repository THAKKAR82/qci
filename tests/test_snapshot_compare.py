"""Footprint-scoped snapshot comparison (M1.3c, ADR 0005 section 7), fully offline.

The baseline is the committed ``ibm_fez`` capture. Candidates are deterministic edits of it
(perturbed values, changed and unchanged dates, a unit change, a removed parameter), each with
its content hash recomputed, so every status is exercised without a live capture.
"""

import inspect
import json
import re
from collections.abc import Callable
from datetime import timedelta
from functools import cache
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from conftest import ibm_properties, physical_run
from qci.adapters.qiskit_ibm.calibration import (
    ERROR_PARAMETERS,
    IbmPropertiesCalibrationReader,
    extract_measurements,
    missing_resources,
    snapshot_comparison_support,
)
from qci.cli.app import app
from qci.compare.footprint import footprint_for_run
from qci.compare.hardware import compare_calibration, compare_hardware
from qci.compare.snapshots import compare_snapshots
from qci.core.hashing import hash_json
from qci.core.ports import SnapshotComparisonSupport
from qci.domain.comparison import ComparisonStatus, ParameterComparison
from qci.domain.run import Run
from qci.domain.snapshot import (
    CalibrationSnapshot,
    SnapshotCapture,
    SnapshotComparison,
    SnapshotFixture,
)
from qci.storage.snapshots import SqliteSnapshotRepository
from qci.storage.sqlite import SqliteRunRepository

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "snapshots" / "ibm_fez.json"
SUPPORT = {"qiskit_ibm": snapshot_comparison_support()}
LATER = timedelta(days=1)
NEW_DATE = {"$datetime": "2026-10-11T00:00:00+00:00"}

# Qubits 0 and 1 report every parameter they have in both snapshots, and their gates have
# calibration entries, so the unedited footprint is fully comparable.
BASIC = """OPENQASM 3.0;
include "stdgates.inc";
bit[2] c;
sx $0;
cz $0, $1;
sx $1;
c[0] = measure $0;
c[1] = measure $1;
"""


@cache
def _fixture() -> SnapshotFixture:
    return SnapshotFixture.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


def fez(snapshot_id: str = "FEZ-A") -> CalibrationSnapshot:
    return _fixture().snapshot.model_copy(update={"snapshot_id": snapshot_id})


Edit = Callable[[dict[str, Any]], None]


def _qubit(properties: dict[str, Any], qubit: int, name: str) -> dict[str, Any]:
    (entry,) = [e for e in properties["qubits"][qubit] if e["name"] == name]
    assert isinstance(entry, dict)
    return entry


def _gate(properties: dict[str, Any], gate: str, qubits: list[int], name: str) -> dict[str, Any]:
    (g,) = [g for g in properties["gates"] if g["gate"] == gate and g["qubits"] == qubits]
    (entry,) = [e for e in g["parameters"] if e["name"] == name]
    assert isinstance(entry, dict)
    return entry


def derive(*edits: Edit, snapshot_id: str = "FEZ-B", **fields: Any) -> CalibrationSnapshot:
    """A second snapshot derived from the fixture, captured one day later."""
    base = fez()
    raw: dict[str, Any] = json.loads(json.dumps(base.provider_raw))
    for edit in edits:
        edit(raw["properties"])
    snap = base.model_copy(
        update={
            "snapshot_id": snapshot_id,
            "captured_at": base.captured_at + LATER,
            "provider_raw": raw,
            **fields,
        }
    )
    content_hash = hash_json(
        {
            "provider": snap.provider,
            "backend_name": snap.backend_name,
            "capture_options": snap.capture_options,
            "provider_raw": snap.provider_raw,
        }
    )
    return CalibrationSnapshot.model_validate({**snap.model_dump(), "content_hash": content_hash})


def footprint_run(qasm: str = BASIC, backend: str = "ibm_fez", run_id: str = "FPRUN") -> Run:
    run = physical_run(run_id, qasm3=qasm, layout=None)
    assert run.backend is not None
    return run.model_copy(update={"backend": run.backend.model_copy(update={"name": backend})})


def compare(
    candidate: CalibrationSnapshot,
    run: Run | None = None,
    *,
    baseline: CalibrationSnapshot | None = None,
    allow: bool = False,
    support: dict[str, SnapshotComparisonSupport] = SUPPORT,
) -> SnapshotComparison:
    return compare_snapshots(
        baseline or fez(),
        candidate,
        run or footprint_run(),
        support.get,
        allow_footprint_backend_mismatch=allow,
    )


def params(c: SnapshotComparison, status: str) -> list[ParameterComparison]:
    return [p for p in c.hardware.shared_resource_parameters if p.status == status]


# --- statuses --------------------------------------------------------------------------------


def test_identical_snapshots_are_unchanged_and_nothing_was_re_measured() -> None:
    c = compare(fez("FEZ-A"))
    assert c.status is ComparisonStatus.UNCHANGED
    assert c.hardware.global_snapshot_changed is False
    assert c.hardware.relevant_hardware_changed is False
    assert c.hardware.shared_resource_parameters
    assert params(c, "unchanged") == c.hardware.shared_resource_parameters
    assert {u.measurement for u in c.unchanged_values} == {"not_re_measured"}
    assert len(c.unchanged_values) == len(c.hardware.shared_resource_parameters)
    assert c.elapsed_between_captures.value == 0.0
    assert c.elapsed_between_captures.kind.value == "calculated"


def test_changed_footprint_value_has_candidate_minus_baseline_delta() -> None:
    def edit(p: dict[str, Any]) -> None:
        entry = _qubit(p, 0, "T1")
        entry["value"] += 5.0
        entry["date"] = NEW_DATE

    c = compare(derive(edit))
    assert c.status is ComparisonStatus.CHANGED
    assert c.hardware.relevant_hardware_changed is True
    (changed,) = params(c, "changed")
    assert (changed.qubits, changed.parameter, changed.unit) == ((0,), "T1", "us")
    assert isinstance(changed.baseline, float) and isinstance(changed.candidate, float)
    assert changed.delta == changed.candidate - changed.baseline
    assert changed.candidate > changed.baseline
    assert c.elapsed_between_captures.value == LATER.total_seconds()


def test_change_outside_the_footprint_sets_only_global_snapshot_changed() -> None:
    def edit(p: dict[str, Any]) -> None:
        _qubit(p, 100, "T1")["value"] += 5.0
        _gate(p, "cz", [72, 73], "gate_error")["value"] = 0.5

    c = compare(derive(edit))
    assert c.hardware.global_snapshot_changed is True
    assert c.hardware.relevant_hardware_changed is False
    assert c.status is ComparisonStatus.UNCHANGED
    assert all(100 not in p.qubits for p in c.hardware.shared_resource_parameters)


def test_removed_parameter_is_unavailable_never_zero() -> None:
    def edit(p: dict[str, Any]) -> None:
        p["qubits"][1] = [e for e in p["qubits"][1] if e["name"] != "T2"]

    c = compare(derive(edit))
    assert c.status is ComparisonStatus.PARTIALLY_COMPARABLE
    assert c.hardware.relevant_hardware_changed is None
    (missing,) = params(c, "unavailable")
    assert (missing.qubits, missing.parameter) == ((1,), "T2")
    assert missing.baseline is not None and missing.candidate is None and missing.delta is None
    assert "qubit 1 T2: unavailable" in c.hardware.unavailable


def test_gate_name_absent_from_the_payload_is_unavailable() -> None:
    qasm = BASIC.replace("cz $0, $1;", "ecr $0, $1;")
    c = compare(fez("FEZ-B"), footprint_run(qasm))
    assert c.status is ComparisonStatus.PARTIALLY_COMPARABLE
    assert c.hardware.relevant_hardware_changed is None
    assert "ecr(0,1): no calibration in baseline and candidate snapshot" in c.hardware.unavailable


def test_dynamic_footprint_is_not_comparable() -> None:
    qasm = "OPENQASM 3.0;\nbit[1] c;\nc[0] = measure $0;\nif (c[0]) {\n  x $1;\n}\n"
    c = compare(fez("FEZ-B"), footprint_run(qasm))
    assert c.status is ComparisonStatus.NOT_COMPARABLE
    assert c.hardware.shared_resource_parameters == []


def test_snapshots_of_different_backends_or_providers_are_not_comparable() -> None:
    for fields, named in (
        ({"backend_name": "ibm_torino"}, "qiskit_ibm/ibm_torino"),
        ({"provider": "other"}, "other/ibm_fez"),
    ):
        c = compare(derive(**fields))
        assert c.status is ComparisonStatus.NOT_COMPARABLE
        assert c.hardware.reason is not None
        assert "qiskit_ibm/ibm_fez" in c.hardware.reason and named in c.hardware.reason
        assert c.hardware.shared_resource_parameters == []
        assert c.unchanged_values == [] and c.error_values_at_one == []


def test_unknown_provider_support_is_unavailable() -> None:
    c = compare(fez("FEZ-B"), support={})
    assert c.status is ComparisonStatus.UNAVAILABLE
    assert c.hardware.shared_resource_parameters == []


# --- units -----------------------------------------------------------------------------------


def _ms(p: dict[str, Any]) -> None:
    _qubit(p, 0, "T2")["unit"] = "ms"


def test_unit_mismatch_is_not_comparable_and_never_converted() -> None:
    c = compare(derive(_ms))
    (mismatch,) = params(c, "not_comparable")
    assert (mismatch.qubits, mismatch.parameter) == ((0,), "T2")
    assert mismatch.baseline == mismatch.candidate == _qubit(_raw(fez()), 0, "T2")["value"]
    assert mismatch.delta is None and mismatch.unit is None
    assert c.hardware.reason is not None
    assert "qubit 0 T2: units differ (baseline us, candidate ms); not compared" in (
        c.hardware.reason
    )
    assert c.status is ComparisonStatus.PARTIALLY_COMPARABLE
    assert c.hardware.relevant_hardware_changed is None
    assert all(p.parameter != "T2" or p.qubits != (0,) for p in _unchanged(c))
    assert not [d for d in c.hardware.calibration_date_changes if "qubit 0 T2" in d]


def test_none_against_a_unit_is_a_mismatch() -> None:
    def edit(p: dict[str, Any]) -> None:
        _qubit(p, 1, "readout_length")["unit"] = ""

    c = compare(derive(edit))
    (mismatch,) = params(c, "not_comparable")
    assert (mismatch.qubits, mismatch.parameter) == ((1,), "readout_length")
    assert c.hardware.reason is not None
    assert "baseline ns, candidate None" in c.hardware.reason


def test_unit_mismatch_with_another_change_is_changed() -> None:
    def edit(p: dict[str, Any]) -> None:
        _qubit(p, 1, "T1")["value"] += 1.0

    c = compare(derive(_ms, edit))
    assert c.status is ComparisonStatus.CHANGED
    assert c.hardware.relevant_hardware_changed is True
    assert len(params(c, "not_comparable")) == 1


def _raw(snapshot: CalibrationSnapshot) -> dict[str, Any]:
    properties = snapshot.provider_raw["properties"]
    assert isinstance(properties, dict)
    return properties


def _unchanged(c: SnapshotComparison) -> list[ParameterComparison]:
    return params(c, "unchanged")


def test_run_comparison_keeps_its_unit_behavior() -> None:
    """The same unit mismatch through run comparison: no ``not_comparable`` parameter, and
    the unit of the first side, as before (D20). Golden file ``unit_mismatch`` pins the
    full output."""
    props = ibm_properties()
    candidate_props = json.loads(json.dumps(props))
    candidate_props["qubits"][1][0]["unit"] = "ns"
    qasm = BASIC.replace("cz $0, $1;", "ecr $1, $0;")
    a = physical_run("A", qasm3=qasm, properties=props, layout=None)
    b = physical_run("B", qasm3=qasm, properties=candidate_props, layout=None)
    hw = compare_hardware(
        a,
        b,
        footprint_for_run(a),
        footprint_for_run(b),
        {"qiskit_ibm": IbmPropertiesCalibrationReader()}.get,
    )
    assert not [p for p in hw.shared_resource_parameters if p.status == "not_comparable"]
    (t1,) = [p for p in hw.shared_resource_parameters if (p.qubits, p.parameter) == ((1,), "T1")]
    assert (t1.status, t1.unit) == ("unchanged", "us")
    assert hw.status is ComparisonStatus.UNCHANGED


def test_require_matching_units_defaults_off() -> None:
    parameter = inspect.signature(compare_calibration).parameters["require_matching_units"]
    assert parameter.default is False
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY


# --- re-measured versus not re-measured --------------------------------------------------------


def test_unchanged_values_distinguish_re_measured_from_not_re_measured() -> None:
    def edit(p: dict[str, Any]) -> None:
        _qubit(p, 1, "T1")["date"] = NEW_DATE  # same value, new measurement
        del _qubit(p, 1, "T2")["date"]  # date no longer reported

    c = compare(derive(edit))
    by_key = {(u.qubits, u.operation, u.parameter): u for u in c.unchanged_values}
    re_measured = by_key[((1,), None, "T1")]
    assert re_measured.measurement == "re_measured_same_value"
    assert re_measured.candidate_measured_at is not None
    assert re_measured.candidate_measured_at.isoformat() == "2026-10-11T00:00:00+00:00"
    assert by_key[((1,), None, "T2")].measurement == "measurement_date_unavailable"
    assert by_key[((0,), None, "T1")].measurement == "not_re_measured"
    assert any("qubit 1 T1" in d for d in c.hardware.calibration_date_changes)


def test_rendering_never_presents_not_re_measured_as_evidence_of_constancy() -> None:
    from qci.cli.render_snapshot_compare import render_snapshot_comparison

    text = render_snapshot_comparison(compare(fez("FEZ-A")))
    lines = text.splitlines()
    head = lines.index("  not re-measured: " + str(len(compare(fez("FEZ-A")).unchanged_values)))
    assert head > lines.index("  re-measured, same value: 0")
    assert "not evidence that the value held constant" in text
    for word in ("stable", "stability", "confirmed", "verified"):
        assert word not in text.lower()


# --- error-type parameters equal to 1 ----------------------------------------------------------


def test_error_parameters_are_an_explicit_list() -> None:
    assert ERROR_PARAMETERS == ("gate_error", "readout_error", "init_error")
    assert compare(fez("FEZ-B")).error_parameters == list(ERROR_PARAMETERS)


def test_error_values_of_one_on_footprint_resources_are_listed_as_given() -> None:
    qasm = BASIC.replace("sx $0;\ncz $0, $1;", "sx $72;\ncz $72, $73;\nsx $0;\ncz $0, $1;")

    def edit(p: dict[str, Any]) -> None:
        _qubit(p, 0, "readout_error")["value"] = 1
        _qubit(p, 0, "prob_meas0_prep1")["value"] = 1  # not an error-type parameter
        _gate(p, "sx", [0], "gate_length")["value"] = 1  # not an error-type parameter
        p["qubits"][1].append({"name": "my_error", "unit": "", "value": 1})  # not listed

    c = compare(derive(edit), footprint_run(qasm))
    found = [(e.side, e.operation, e.qubits, e.parameter, e.value) for e in c.error_values_at_one]
    assert found == [
        ("baseline", "cz", (72, 73), "gate_error", 1.0),
        ("baseline", "sx", (72,), "gate_error", 1.0),
        ("candidate", None, (0,), "readout_error", 1.0),
        ("candidate", "cz", (72, 73), "gate_error", 1.0),
        ("candidate", "sx", (72,), "gate_error", 1.0),
    ]


def test_error_values_outside_the_footprint_are_not_listed() -> None:
    assert compare(fez("FEZ-B")).error_values_at_one == []


def test_fez_error_values_of_one_by_physical_connection() -> None:
    """The committed capture's gate_error = 1 entries, as recorded in the M1.3c report."""
    properties = _raw(fez())
    at_one = [
        (g["gate"], tuple(g["qubits"]))
        for g in properties["gates"]
        for x in g["parameters"]
        if x["name"] in ERROR_PARAMETERS and x["value"] == 1
    ]
    connections = {tuple(sorted(q)) for gate, q in at_one if gate == "cz"}
    assert connections == {(27, 28), (32, 33), (71, 72), (72, 73)}
    single = {(gate, q) for gate, q in at_one if len(q) == 1}
    assert single == {("id", (72,)), ("rx", (72,)), ("sx", (72,)), ("x", (72,)), ("xslow", (72,))}
    assert not [
        (i, e["name"])
        for i, q in enumerate(properties["qubits"])
        for e in q
        if e["name"] in ERROR_PARAMETERS and e["value"] == 1
    ]


# --- footprint backend mismatch and presence ----------------------------------------------------


def test_footprint_from_another_backend_is_not_comparable_without_the_flag() -> None:
    c = compare(fez("FEZ-B"), footprint_run(backend="fake_fez"))
    assert c.status is ComparisonStatus.NOT_COMPARABLE
    assert c.hardware.reason is not None
    assert "on fake_fez; snapshots are of ibm_fez" in c.hardware.reason
    assert c.hardware.shared_resource_parameters == []
    assert c.footprint_backend == "fake_fez"


def test_with_the_flag_a_note_names_both_backends() -> None:
    c = compare(fez("FEZ-B"), footprint_run(backend="fake_fez"), allow=True)
    assert c.status is ComparisonStatus.UNCHANGED
    assert c.allow_footprint_backend_mismatch is True
    assert (
        c.hardware.reason == "footprint taken from run FPRUN on fake_fez; snapshots are of ibm_fez"
    )


def test_with_the_flag_every_missing_resource_is_listed() -> None:
    qasm = BASIC.replace("sx $1;", "sx $1;\nsx $156;\ncz $0, $2;\nx $157;")
    c = compare(fez("FEZ-B"), footprint_run(qasm, backend="fake_fez"), allow=True)
    assert c.status is ComparisonStatus.NOT_COMPARABLE
    assert c.hardware.shared_resource_parameters == []
    reason = c.hardware.reason
    assert reason is not None
    assert "footprint taken from run FPRUN on fake_fez; snapshots are of ibm_fez" in reason
    for side in ("baseline", "candidate"):
        assert (
            f"footprint resources missing from the {side} snapshot: qubit 156, qubit 157, "
            "cz(0,2), sx(156), x(157)"
        ) in reason
    assert "measure" not in reason


def test_presence_rules() -> None:
    raw = fez().provider_raw
    assert missing_resources(raw, [0, 155], [("measure", (0,)), ("cz", (1, 0))]) == []
    assert missing_resources(raw, [156], [("measure", (156,))]) == ["qubit 156", "measure(156)"]
    assert missing_resources(raw, [], [("cz", (0, 2)), ("ecr", (0, 1))]) == [
        "cz(0,2)",
        "ecr(0,1)",
    ]
    assert missing_resources(raw, [], [("reset", (0,)), ("delay", (3,))]) == []
    assert missing_resources({"configuration": None}, [0], [("measure", (0,))]) == [
        "qubit 0",
        "measure(0)",
    ]


def test_without_a_mismatch_no_presence_check_runs() -> None:
    qasm = BASIC.replace("sx $1;", "sx $1;\nx $200;")
    c = compare(fez("FEZ-B"), footprint_run(qasm))
    assert c.status is ComparisonStatus.PARTIALLY_COMPARABLE
    assert "qubit 200: no calibration in baseline and candidate snapshot" in c.hardware.unavailable
    assert c.hardware.reason is not None and "missing from" not in c.hardware.reason


# --- CLI: determinism, nothing persisted, neutral wording --------------------------------------

RULE_8 = re.compile(
    r"better|worse|regress|improv|degrad|\bpass|fail|significan|verdict|caus", re.IGNORECASE
)


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "store"
    monkeypatch.setenv("QCI_HOME", str(home))
    home.mkdir()
    snapshots = SqliteSnapshotRepository(home / "qci.db")
    runs = SqliteRunRepository(home / "qci.db")
    try:
        for snap in (
            fez("FEZ-A"),
            derive(_ms, lambda p: _qubit(p, 1, "T1").update(date=NEW_DATE)),
        ):
            properties = snap.provider_raw["properties"]
            snapshots.save(
                snap,
                extract_measurements(properties),
                SnapshotCapture(
                    capture_id=f"CAP-{snap.snapshot_id}",
                    snapshot_id=snap.snapshot_id,
                    captured_at=snap.captured_at,
                ),
            )
        runs.save(footprint_run(backend="fake_fez", run_id="FAKEFEZRUN"))
    finally:
        snapshots.close()
        runs.close()
    return home


def _invoke(*args: str) -> str:
    result = CliRunner().invoke(app, ["snapshot", "compare", *args])
    assert result.exit_code == 0, result.output
    return result.stdout


def test_cli_json_is_deterministic_and_nothing_is_persisted(store: Path) -> None:
    before = (store / "qci.db").read_bytes()
    args = ("FEZ-A", "FEZ-B", "--footprint-run", "FAKEFEZRUN", "--allow-footprint-backend-mismatch")
    first = _invoke(*args, "--json")
    second = _invoke(*args, "--json")
    text = _invoke(*args)
    assert first == second
    assert (store / "qci.db").read_bytes() == before
    c = SnapshotComparison.model_validate_json(first)
    assert c.status is ComparisonStatus.PARTIALLY_COMPARABLE
    assert [u.measurement for u in c.unchanged_values].count("re_measured_same_value") == 1
    assert "units differ (baseline us, candidate ms)" in text
    assert "re-measured, same value: 1" in text
    assert RULE_8.search(first) is None and RULE_8.search(text) is None


def test_cli_rendering_of_every_exit_uses_neutral_wording(store: Path) -> None:
    for args in (
        ("FEZ-A", "FEZ-B", "--footprint-run", "FAKEFEZRUN"),
        ("FEZ-A", "FEZ-A", "--footprint-run", "FAKEFEZRUN", "--allow-footprint-backend-mismatch"),
    ):
        for extra in ((), ("--json",)):
            assert RULE_8.search(_invoke(*args, *extra)) is None


def test_cli_unknown_ids_exit_1(store: Path) -> None:
    for args in (
        ("NOPE0000000000000000000000", "FEZ-B", "--footprint-run", "FAKEFEZRUN"),
        ("FEZ-A", "FEZ-B", "--footprint-run", "NOPE0000000000000000000000"),
    ):
        result = CliRunner().invoke(app, ["snapshot", "compare", *args])
        assert result.exit_code == 1
        assert "error:" in result.stderr


def test_limitations_qualify_re_measured_by_the_provider_timestamp() -> None:
    (line,) = [x for x in compare(fez("FEZ-B")).limitations if "provider's timestamp" in x]
    assert "virtual gates (such as rz)" in line and "configured durations" in line
    assert "may not mean physically re-measured" in line
