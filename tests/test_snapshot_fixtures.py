"""Snapshot fixtures are sanitized, plain, labeled and self-consistent (ADR 0005, section 5).

Every committed ``*.json`` under ``tests/fixtures/snapshots/`` is checked, plus the SYNTHETIC
FakeFez fixture, which is generated once per session and never committed. A file whose name
starts with ``synthetic_`` was not read from live hardware and must say so in
``fixture_origin``. Tests below the generic ones pin facts of the committed ``ibm_fez`` capture.
"""

import json
from collections import Counter
from functools import cache
from pathlib import Path
from typing import Any

import pytest
from pydantic import JsonValue

from qci.adapters.qiskit_ibm.calibration import (
    IbmPropertiesCalibrationReader,
    extract_measurements,
    gate_resource,
)
from qci.adapters.qiskit_ibm.redact import (
    SENSITIVE_KEYS,
    child_path,
    is_redaction_tag,
    redact_payload,
    string_rule,
)
from qci.core.hashing import hash_json
from qci.domain.backend import BackendSnapshot, SnapshotSource
from qci.domain.comparison import CalibrationValue
from qci.domain.snapshot import Measurement, SnapshotFixture
from snapshot_stubs import synthetic_fake_fez_fixture_text

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "snapshots"
COMMITTED = sorted(FIXTURES.glob("*.json"))
SYNTHETIC_NAME = "synthetic_fake_fez.json"
IBM_FEZ = FIXTURES / "ibm_fez.json"


def test_committed_fixtures_are_live_captures_only() -> None:
    assert IBM_FEZ in COMMITTED
    assert not [p for p in COMMITTED if p.name.startswith("synthetic_")]


@pytest.fixture(scope="session")
def synthetic_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("snapshots") / SYNTHETIC_NAME
    path.write_text(synthetic_fake_fez_fixture_text(), encoding="utf-8")
    return path


@pytest.fixture(params=[*[p.name for p in COMMITTED], SYNTHETIC_NAME])
def path(request: pytest.FixtureRequest, synthetic_path: Path) -> Path:
    name: str = request.param
    return synthetic_path if name == SYNTHETIC_NAME else FIXTURES / name


@cache
def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@cache
def _document(path: Path) -> Any:
    return json.loads(_text(path))


@cache
def _fixture(path: Path) -> SnapshotFixture:
    return SnapshotFixture.model_validate_json(_text(path))


def _walk(value: Any, path: str = "$") -> list[tuple[str, str | None, Any]]:
    """Every (path, key, value) triple, depth first."""
    out: list[tuple[str, str | None, Any]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            item_path = child_path(path, key)
            out.append((item_path, key, item))
            out += _walk(item, item_path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            item_path = child_path(path, index)
            out.append((item_path, None, item))
            out += _walk(item, item_path)
    return out


# --- ADR 0005 section 5: sanitization, on every fixture -----------------------------------


def test_fixture_is_plain_sorted_json(path: Path) -> None:
    raw = path.read_bytes()
    assert not raw.startswith(b"\x1f\x8b"), "fixture must not be gzip"
    text = raw.decode("utf-8")
    assert text == json.dumps(json.loads(text), sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def test_fixture_has_no_credential_material(path: Path) -> None:
    for item_path, key, value in _walk(_document(path)):
        if key is not None:
            assert string_rule(key) is None, item_path
            if key.lower() in SENSITIVE_KEYS:
                assert is_redaction_tag(value), f"{item_path} holds an unredacted value"
        if isinstance(value, str):
            assert string_rule(value) is None, f"{item_path} matches rule {string_rule(value)}"


def test_fixture_redactions_match_tags(path: Path) -> None:
    fixture = _fixture(path)
    tagged = [p for p, _, v in _walk(fixture.snapshot.provider_raw) if is_redaction_tag(v)]
    assert len(fixture.snapshot.redactions) == len(set(fixture.snapshot.redactions))
    assert set(fixture.snapshot.redactions) == set(tagged)


def test_fixture_is_redaction_fixed_point(path: Path) -> None:
    document: JsonValue = _document(path)
    redacted, paths = redact_payload(document)
    assert paths == []
    assert redacted == document


# --- labeling and self-consistency, on every fixture --------------------------------------


def test_fixture_is_labeled_by_origin(path: Path) -> None:
    fixture = _fixture(path)
    synthetic = path.name.startswith("synthetic_")
    assert (fixture.fixture_origin == "synthetic") is synthetic
    if synthetic:
        assert fixture.snapshot.source is not SnapshotSource.LIVE_CALIBRATION
        assert fixture.fixture_note and fixture.fixture_note.startswith("SYNTHETIC")
    else:
        assert fixture.snapshot.source is SnapshotSource.LIVE_CALIBRATION


def test_fixture_ids_are_placeholders_and_hash_matches_content(path: Path) -> None:
    fixture = _fixture(path)
    snap = fixture.snapshot
    assert snap.snapshot_id == "FIXTURE-SNAPSHOT"
    assert [c.capture_id for c in fixture.captures] == [
        f"FIXTURE-CAPTURE-{i}" for i in range(1, len(fixture.captures) + 1)
    ]
    assert snap.content_hash == hash_json(
        {
            "provider": snap.provider,
            "backend_name": snap.backend_name,
            "capture_options": snap.capture_options,
            "provider_raw": snap.provider_raw,
        }
    )


def test_measurement_rows_are_the_projection_of_the_payload(path: Path) -> None:
    fixture = _fixture(path)
    assert fixture.measurements == extract_measurements(fixture.snapshot.provider_raw["properties"])


def _key(p: CalibrationValue | Measurement) -> tuple[str, str, str | None, str | None]:
    name = p.name if isinstance(p, CalibrationValue) else p.parameter
    date = p.calibrated_at if isinstance(p, CalibrationValue) else p.measured_at
    return (name, repr(p.value), p.unit, date.isoformat() if date else None)


def test_reader_and_measurement_rows_agree_on_every_selected_value(path: Path) -> None:
    """Every value the reader selects equals its measurement row (ADR 0005, section 6).

    The reader never selects two kinds of rows: ``general`` (excluded, D14) and ``measure``
    gate entries, because it reports ``measure`` as readout under the measured qubit. Those
    rows are counted separately, so every row is accounted for exactly once.
    """
    fixture = _fixture(path)
    snap = fixture.snapshot
    properties = snap.provider_raw["properties"]
    assert isinstance(properties, dict)
    raw_qubits = properties["qubits"]
    raw_gates = properties["gates"]
    assert isinstance(raw_qubits, list) and isinstance(raw_gates, list)
    view = BackendSnapshot(
        source=snap.source,
        captured_at=snap.captured_at,
        calibrated_at=snap.calibrated_at,
        basis_gates=[],
        coupling_edges=[],
        provider_raw=snap.provider_raw,
    )
    operations: list[tuple[str, tuple[int, ...]]] = []
    for gate in raw_gates:
        assert isinstance(gate, dict)
        name, qubits = gate["gate"], gate["qubits"]
        assert isinstance(name, str) and isinstance(qubits, list)
        operations.append((name, tuple(q for q in qubits if isinstance(q, int))))
    selected = IbmPropertiesCalibrationReader().select(
        view, list(range(len(raw_qubits))), operations
    )

    rows: dict[str, Counter[tuple[str, str, str | None, str | None]]] = {}
    for m in fixture.measurements:
        rows.setdefault(m.resource, Counter())[_key(m)] += 1

    compared = 0
    for qubit in selected.qubits:
        reader = Counter(_key(p) for p in qubit.parameters)
        assert reader == rows.get(f"qubit/{qubit.qubit}", Counter()), qubit.qubit
        compared += len(qubit.parameters)
    for op in selected.operations:
        if op.name == "measure":
            assert op.available and op.parameters == []
            continue
        assert op.available, (op.name, op.qubits, op.note)
        reader = Counter(_key(p) for p in op.parameters)
        assert reader == rows[gate_resource(op.name, op.qubits)], (op.name, op.qubits)
        compared += len(op.parameters)
    unselected = sum(
        1
        for m in fixture.measurements
        if m.resource_kind == "general" or m.resource.startswith("gate/measure/")
    )
    assert compared + unselected == len(fixture.measurements)


# --- facts of the committed ibm_fez capture (a 156-qubit CZ device) ------------------------


def _fez() -> SnapshotFixture:
    return _fixture(IBM_FEZ)


def _fez_raw(name: str) -> dict[str, Any]:
    value = _fez().snapshot.provider_raw[name]
    assert isinstance(value, dict)
    return value


def _pairs(entries: Any) -> list[tuple[int, int]]:
    return [(int(a), int(b)) for a, b in entries]


def _config_coupling(gate: str) -> list[tuple[int, int]]:
    (entry,) = [g for g in _fez_raw("configuration")["gates"] if g["name"] == gate]
    return _pairs(entry["coupling_map"])


def test_fez_is_a_live_cz_device_captured_without_fractional_gates() -> None:
    snap = _fez().snapshot
    config = _fez_raw("configuration")
    assert snap.backend_name == "ibm_fez"
    assert snap.capture_options == {"use_fractional_gates": False}
    assert config["n_qubits"] == 156
    assert "cz" in config["basis_gates"] and "ecr" not in config["basis_gates"]
    assert set(snap.environment) == {"qci", "qiskit", "qiskit-ibm-runtime"}
    assert snap.redactions == ["$.configuration.url"]


def test_fez_lists_every_cz_connection_in_both_directions() -> None:
    """Presence (ADR 0005, section 7) matches exact ordered pairs. On this device the CZ
    coupling map lists every connection both ways, so either order of a connected pair is
    present, and the configuration and properties agree on the ordered pairs."""
    cz = _config_coupling("cz")
    ordered = set(cz)
    assert len(cz) == len(ordered) == 352
    assert all((b, a) in ordered for a, b in ordered)
    assert set(_pairs(_fez_raw("configuration")["coupling_map"])) == ordered
    properties_cz = [
        tuple(g["qubits"]) for g in _fez_raw("properties")["gates"] if g["gate"] == "cz"
    ]
    assert set(properties_cz) == ordered and len(properties_cz) == 352
    assert all(0 <= q < 156 for pair in ordered for q in pair)


def test_fez_presence_inputs_for_an_ordered_pair_and_for_measure() -> None:
    """The data the M1.3c presence rule will read: a connected pair is in the CZ coupling map
    in both orders, an unconnected pair in neither, and measure, reset and delay are
    supported instructions."""
    ordered = set(_config_coupling("cz"))
    assert (0, 1) in ordered and (1, 0) in ordered
    assert (0, 2) not in ordered and (2, 0) not in ordered
    assert {"measure", "reset", "delay"} <= set(_fez_raw("configuration")["supported_instructions"])


def test_fez_reader_resolves_both_orders_and_reports_unconnected_pairs_unavailable() -> None:
    snap = _fez().snapshot
    view = BackendSnapshot(
        source=snap.source,
        captured_at=snap.captured_at,
        calibrated_at=snap.calibrated_at,
        basis_gates=[],
        coupling_edges=[],
        provider_raw=snap.provider_raw,
    )
    selected = IbmPropertiesCalibrationReader().select(
        view, [0, 1, 156], [("cz", (0, 1)), ("cz", (1, 0)), ("cz", (0, 2)), ("ecr", (0, 1))]
    )
    assert [q.available for q in selected.qubits] == [True, True, False]
    forward, backward, unconnected, ecr = selected.operations
    assert forward.available and backward.available
    assert {p.name for p in forward.parameters} == {"gate_error", "gate_length"}
    assert not unconnected.available and not ecr.available
    assert unconnected.note == "no calibration entry for this operation on these ordered qubits"


def test_fez_payload_differs_from_fakes_as_recorded_in_adr_0005() -> None:
    properties = _fez_raw("properties")
    config_gates = {g["name"] for g in _fez_raw("configuration")["gates"]}
    property_gates = Counter(g["gate"] for g in properties["gates"])
    # The client filters fractional gates from the configuration, but its properties filter
    # matches entry names (rzz72_73), not gate names, so rx and rzz entries remain.
    assert not {"rx", "rzz"} & config_gates
    assert property_gates["rzz"] == 352 and property_gates["rx"] == 156
    # Real devices report gate entries for measure and reset, which the fakes do not.
    assert property_gates["measure"] == property_gates["reset"] == 156
    # Qubit parameter sets differ between qubits; an unreported parameter has no row.
    per_qubit = Counter(e["name"] for q in properties["qubits"] for e in q)
    assert per_qubit["T1"] == 156 and per_qubit["T2"] == 155 and per_qubit["init_error"] == 116
    rows = Counter(m.parameter for m in _fez().measurements if m.resource_kind == "qubit")
    assert rows["T2"] == 155 and rows["init_error"] == 116
    # Some entries report gate_error exactly 1; stored as given, never interpreted.
    error_one = Counter(
        g["gate"]
        for g in properties["gates"]
        for x in g["parameters"]
        if x["name"] == "gate_error" and x["value"] == 1
    )
    assert error_one["cz"] == 8 and error_one["measure"] == 0
    # No duplicate (gate, ordered qubits) entries, so the reader finds no ambiguity.
    keys = Counter((g["gate"], tuple(g["qubits"])) for g in properties["gates"])
    assert max(keys.values()) == 1


def test_fez_calibrated_at_is_the_properties_last_update_date() -> None:
    """``calibrated_at`` is the document-level ``last_update_date`` of the captured properties.
    It is not derived from parameter dates: some parameters carry later dates."""
    fixture = _fez()
    properties = _fez_raw("properties")
    assert properties["last_update_date"] == {"$datetime": "2026-10-10T00:19:17+00:00"}
    calibrated_at = fixture.snapshot.calibrated_at
    assert calibrated_at is not None
    assert calibrated_at.isoformat() == "2026-10-10T00:19:17+00:00"
    dates = [m.measured_at for m in fixture.measurements if m.measured_at is not None]
    assert max(dates) > calibrated_at
    assert min(dates) < calibrated_at
