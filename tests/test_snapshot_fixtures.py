"""Committed snapshot fixtures are sanitized, plain, labeled and self-consistent (ADR 0005, s5).

Every ``*.json`` under ``tests/fixtures/snapshots/`` is checked. Files whose name starts with
``synthetic_`` were not read from live hardware and must say so in ``fixture_origin``.
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

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "snapshots"
PATHS = sorted(FIXTURES.glob("*.json"))


def test_at_least_one_fixture_is_committed() -> None:
    assert PATHS


@cache
def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@cache
def _document(path: Path) -> Any:
    return json.loads(_text(path))


@cache
def _fixture(path: Path) -> SnapshotFixture:
    return SnapshotFixture.model_validate_json(_text(path))


fixture_paths = pytest.mark.parametrize("path", PATHS, ids=[p.name for p in PATHS])


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


@fixture_paths
def test_fixture_is_plain_sorted_json(path: Path) -> None:
    raw = path.read_bytes()
    assert not raw.startswith(b"\x1f\x8b"), "fixture must not be gzip"
    text = raw.decode("utf-8")
    assert text == json.dumps(json.loads(text), sort_keys=True, indent=2, ensure_ascii=False) + "\n"


@fixture_paths
def test_fixture_has_no_credential_material(path: Path) -> None:
    for item_path, key, value in _walk(_document(path)):
        if key is not None:
            assert string_rule(key) is None, item_path
            if key.lower() in SENSITIVE_KEYS:
                assert is_redaction_tag(value), f"{item_path} holds an unredacted value"
        if isinstance(value, str):
            assert string_rule(value) is None, f"{item_path} matches rule {string_rule(value)}"


@fixture_paths
def test_fixture_redactions_match_tags(path: Path) -> None:
    fixture = _fixture(path)
    tagged = [p for p, _, v in _walk(fixture.snapshot.provider_raw) if is_redaction_tag(v)]
    assert len(fixture.snapshot.redactions) == len(set(fixture.snapshot.redactions))
    assert set(fixture.snapshot.redactions) == set(tagged)


@fixture_paths
def test_fixture_is_redaction_fixed_point(path: Path) -> None:
    document: JsonValue = _document(path)
    redacted, paths = redact_payload(document)
    assert paths == []
    assert redacted == document


@fixture_paths
def test_fixture_is_labeled_by_origin(path: Path) -> None:
    fixture = _fixture(path)
    synthetic = path.name.startswith("synthetic_")
    assert (fixture.fixture_origin == "synthetic") is synthetic
    if synthetic:
        assert fixture.snapshot.source is not SnapshotSource.LIVE_CALIBRATION
        assert fixture.fixture_note and fixture.fixture_note.startswith("SYNTHETIC")
    else:
        assert fixture.snapshot.source is SnapshotSource.LIVE_CALIBRATION


@fixture_paths
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


@fixture_paths
def test_measurement_rows_are_the_projection_of_the_payload(path: Path) -> None:
    fixture = _fixture(path)
    assert fixture.measurements == extract_measurements(fixture.snapshot.provider_raw["properties"])


def _key(p: CalibrationValue | Measurement) -> tuple[str, str, str | None, str | None]:
    name = p.name if isinstance(p, CalibrationValue) else p.parameter
    date = p.calibrated_at if isinstance(p, CalibrationValue) else p.measured_at
    return (name, repr(p.value), p.unit, date.isoformat() if date else None)


@fixture_paths
def test_reader_and_measurement_rows_agree_on_every_selected_value(path: Path) -> None:
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
        if op.available:
            reader = Counter(_key(p) for p in op.parameters)
            assert reader == rows[gate_resource(op.name, op.qubits)], (op.name, op.qubits)
            compared += len(op.parameters)
    general = sum(1 for m in fixture.measurements if m.resource_kind == "general")
    assert compared + general == len(fixture.measurements)
