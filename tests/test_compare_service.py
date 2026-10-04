"""CompareService: directional, deterministic, read-only."""

import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from conftest import ibm_properties, make_run, physical_bell_qasm, physical_run
from qci.adapters.qiskit_ibm.calibration import IbmPropertiesCalibrationReader
from qci.compare.sampling import MIN_RESAMPLES, seed_from_comparison_id
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
    assert c.policy.version == "qci.compare.v3"
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


def test_sampling_floor_seed_is_derived_from_the_comparison_id(service: CompareService) -> None:
    c = service.compare("BASE", "CAND")
    assert c.engine_version == "qci.compare.engine.4"
    f = c.distribution.sampling_floor
    assert f is not None
    assert f.seed == seed_from_comparison_id(c.comparison_id)
    assert f.resamples == c.policy.distribution_null_resamples == 2000
    # Reversing direction changes the comparison_id and therefore the seed.
    backward = service.compare("CAND", "BASE").distribution.sampling_floor
    assert backward is not None and backward.seed != f.seed


def test_failed_run_comparison_has_no_sampling_floor(service: CompareService) -> None:
    assert service.compare("BASE", "FAIL").distribution.sampling_floor is None


def test_policy_rejects_fewer_than_minimum_null_resamples() -> None:
    assert MIN_RESAMPLES == 100
    with pytest.raises(ValidationError):
        ComparisonPolicy(distribution_null_resamples=99)
    assert ComparisonPolicy(distribution_null_resamples=100).distribution_null_resamples == 100


def test_null_resamples_are_part_of_the_policy_hash() -> None:
    default = hash_json(ComparisonPolicy())
    assert hash_json(ComparisonPolicy(distribution_null_resamples=500)) != default


def test_shared_seed_guard_is_part_of_the_policy_hash() -> None:
    default = ComparisonPolicy()
    assert default.sampling_floor_requires_distinct_simulator_seeds is True
    disabled = ComparisonPolicy(sampling_floor_requires_distinct_simulator_seeds=False)
    assert hash_json(disabled) != hash_json(default)


def test_limitations_describe_the_sampling_floor(service: CompareService) -> None:
    text = " ".join(service.compare("BASE", "CAND").limitations)
    assert "TVD has a sampling floor" in text
    assert "Hellinger distance still has no sampling floor" in text
    assert text.count("Sampling floor caveat:") == 4
    assert "not computed when both runs were simulated with the same simulator seed" in text
