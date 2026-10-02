"""CompareService: directional, deterministic, read-only."""

import sqlite3
from pathlib import Path

import pytest

from conftest import ibm_properties, make_run, physical_bell_qasm, physical_run
from qci.adapters.qiskit_ibm.calibration import IbmPropertiesCalibrationReader
from qci.core.errors import RunNotFoundError
from qci.core.hashing import hash_json
from qci.domain.comparison import Comparison, ComparisonPolicy, ComparisonStatus
from qci.domain.run import RunError, RunStage, RunStatus
from qci.services.compare_service import ENGINE_VERSION, CompareService, comparison_id
from qci.storage.sqlite import SqliteRunRepository

READERS = {"qiskit_ibm": IbmPropertiesCalibrationReader()}


@pytest.fixture
def service(repo: SqliteRunRepository) -> CompareService:
    repo.save(physical_run("BASE", qasm3=physical_bell_qasm(1, 0)))
    repo.save(physical_run("SAME", qasm3=physical_bell_qasm(1, 0)))
    repo.save(
        physical_run(
            "CAND",
            qasm3=physical_bell_qasm(1, 0),
            counts={"c": {"00": 40, "11": 60}},
            properties=ibm_properties(t1={1: 70.0}),
        )
    )
    repo.save(
        make_run(
            "FAIL",
            status=RunStatus.FAILED,
            error=RunError(stage=RunStage.RESOLVE_BACKEND, error_type="E", message="m"),
            backend=None,
            backend_snapshot=None,
            compilation=None,
            execution=None,
            result=None,
            metrics=[],
        )
    )
    return CompareService(repo, READERS)


def test_identical_runs_are_unchanged(service: CompareService) -> None:
    c = service.compare("BASE", "SAME")
    assert c.status is ComparisonStatus.UNCHANGED
    assert (c.baseline_run_id, c.candidate_run_id) == ("BASE", "SAME")
    assert c.policy.version == "qci.compare.v1"
    assert any("no causal attribution" in line for line in c.limitations)


def test_changes_are_directional(service: CompareService) -> None:
    forward = service.compare("BASE", "CAND")
    backward = service.compare("CAND", "BASE")
    assert forward.status is ComparisonStatus.CHANGED
    (f,) = [p for p in forward.hardware.shared_resource_parameters if p.status == "changed"]
    (b,) = [p for p in backward.hardware.shared_resource_parameters if p.status == "changed"]
    assert (f.baseline, f.candidate, f.delta) == (100.0, 70.0, -30.0)
    assert (b.baseline, b.candidate, b.delta) == (70.0, 100.0, 30.0)
    assert forward.comparison_id != backward.comparison_id


def test_comparison_id_is_deterministic_and_policy_bound(service: CompareService) -> None:
    c = service.compare("BASE", "CAND")
    policy_hash = hash_json(ComparisonPolicy())
    assert c.policy_hash == policy_hash
    assert c.comparison_id == comparison_id("BASE", "CAND", policy_hash)
    assert c.engine_version == ENGINE_VERSION
    assert service.compare("BASE", "CAND").model_dump_json() == c.model_dump_json()
    other_policy = ComparisonPolicy(distribution_max_classical_registers=2)
    assert comparison_id("BASE", "CAND", hash_json(other_policy)) != c.comparison_id


def test_json_round_trip(service: CompareService) -> None:
    c = service.compare("BASE", "CAND")
    assert Comparison.model_validate_json(c.model_dump_json()) == c


def test_failed_run_comparison_is_partial_not_a_crash(service: CompareService) -> None:
    c = service.compare("BASE", "FAIL")
    assert c.status is ComparisonStatus.PARTIALLY_COMPARABLE
    assert c.compilation.status is ComparisonStatus.UNAVAILABLE
    assert c.execution.status is ComparisonStatus.UNAVAILABLE
    assert c.backend.status is ComparisonStatus.UNAVAILABLE
    assert c.hardware.status is ComparisonStatus.UNAVAILABLE
    assert c.distribution.status is ComparisonStatus.UNAVAILABLE
    assert c.candidate_counts is None and c.baseline_counts is not None
    assert c.source.status in (ComparisonStatus.UNCHANGED, ComparisonStatus.CHANGED)


def test_compare_does_not_mutate_stored_records(
    service: CompareService, repo: SqliteRunRepository, tmp_path: Path
) -> None:
    def snapshot() -> list[tuple[str, str]]:
        with sqlite3.connect(tmp_path / "qci.db") as conn:
            return conn.execute("SELECT run_id, record_json FROM runs ORDER BY run_id").fetchall()

    before = snapshot()
    for a, b in (("BASE", "CAND"), ("CAND", "BASE"), ("BASE", "FAIL"), ("FAIL", "FAIL")):
        service.compare(a, b)
    assert snapshot() == before


def test_unknown_run_raises(service: CompareService) -> None:
    with pytest.raises(RunNotFoundError):
        service.compare("BASE", "NOPE")
